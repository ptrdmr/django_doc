# apps/documents/tasks.py
"""
Celery tasks template for AI document processing
Based on Flask to Django patterns and async processing requirements
"""

from celery import shared_task
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
import logging
from typing import Dict, Any, Optional

from .models import Document, ParsedData
from .services.ai_analyzer import DocumentAnalyzer
from .services.cost_tracking import CostTracker
from .services.error_handling import AIServiceErrorHandler


logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_document_with_ai(self, document_id: int, context_tags: Optional[list] = None) -> Dict[str, Any]:
    """
    Process a document using AI extraction in background
    
    Args:
        self: Celery task instance (bind=True)
        document_id: ID of the document to process
        context_tags: Optional context tags for enhanced extraction
        
    Returns:
        Dictionary with processing results
    """
    try:
        logger.info(f"Starting AI processing for document {document_id}")
        
        # Get document with select_related for efficiency
        with transaction.atomic():
            document = Document.objects.select_related('patient', 'uploaded_by').get(id=document_id)
            
            # Mark processing as started
            document.status = 'processing'
            document.ai_processing_started_at = timezone.now()
            document.save(update_fields=['status', 'ai_processing_started_at'])
        
        # Initialize services
        analyzer = DocumentAnalyzer()
        cost_tracker = CostTracker()
        error_handler = AIServiceErrorHandler()
        
        # Validate document has content
        if not document.original_text:
            raise ValidationError("Document has no text content to process")
        
        # Process with AI
        logger.info(f"Analyzing document content ({len(document.original_text)} characters)")
        
        result = analyzer.analyze_document(
            document_content=document.original_text,
            context_tags=context_tags,
            fhir_focused=True  # Always use FHIR-focused extraction
        )
        
        if result['success']:
            with transaction.atomic():
                # Track API costs
                estimated_cost = cost_tracker.log_usage(
                    document=document,
                    model=result['model_used'],
                    usage_data=result['usage']
                )
                
                # Convert to FHIR format
                fhir_data = analyzer.convert_to_fhir(result['fields'])
                
                # Store parsed data
                parsed_data = ParsedData.objects.create(
                    document=document,
                    patient=document.patient,
                    extraction_json=result['fields'],
                    fhir_delta_json=fhir_data,
                    confidence_score=_calculate_average_confidence(result['fields']),
                    processing_method=result.get('processing_method', 'unknown'),
                    chunks_processed=result.get('chunks_processed', 1)
                )
                
                # Update document with processing results
                document.status = 'completed'
                document.ai_processing_completed_at = timezone.now()
                document.ai_model_used = result['model_used']
                document.ai_tokens_used = result['usage']['total_tokens']
                document.ai_estimated_cost = estimated_cost
                document.processed_at = timezone.now()
                document.save()
                
                # Add FHIR data to patient's cumulative record
                if document.patient:
                    _add_fhir_to_patient(document.patient, fhir_data, document.id)
                
                logger.info(f"Successfully completed AI processing for document {document_id}")
                
                return {
                    "success": True,
                    "document_id": document_id,
                    "fields_extracted": len(result['fields']),
                    "tokens_used": result['usage']['total_tokens'],
                    "estimated_cost": float(estimated_cost),
                    "processing_method": result.get('processing_method'),
                    "confidence_score": parsed_data.confidence_score
                }
        else:
            # Handle processing failure
            with transaction.atomic():
                document.status = 'failed'
                document.error_message = result.get('error', 'Unknown AI processing error')
                document.ai_processing_completed_at = timezone.now()
                document.save()
            
            logger.error(f"AI processing failed for document {document_id}: {result.get('error')}")
            
            return {
                "success": False,
                "document_id": document_id,
                "error": result.get('error'),
                "error_type": result.get('error_type')
            }
            
    except Document.DoesNotExist:
        logger.error(f"Document {document_id} not found")
        return {
            "success": False,
            "document_id": document_id,
            "error": "Document not found"
        }
        
    except Exception as exc:
        logger.error(f"Error processing document {document_id}: {exc}", exc_info=True)
        
        # Update document status on error
        try:
            document = Document.objects.get(id=document_id)
            error_handler.handle_processing_error(document, exc, self)
        except:
            pass  # Don't fail on error handling failure
        
        # Retry logic based on error type
        if isinstance(exc, ValidationError):
            # Don't retry validation errors
            return {
                "success": False,
                "document_id": document_id,
                "error": str(exc),
                "retry": False
            }
        else:
            # Retry other errors with exponential backoff
            logger.warning(f"Retrying document {document_id} processing (attempt {self.request.retries + 1})")
            raise self.retry(exc=exc, countdown=300 * (2 ** self.request.retries))


@shared_task
def batch_process_documents(document_ids: list, context_tags: Optional[list] = None) -> Dict[str, Any]:
    """
    Process multiple documents in parallel
    
    Args:
        document_ids: List of document IDs to process
        context_tags: Optional context tags for all documents
        
    Returns:
        Batch processing results
    """
    logger.info(f"Starting batch processing for {len(document_ids)} documents")
    
    # Create individual tasks for each document
    task_results = []
    
    for doc_id in document_ids:
        # Submit each document for processing
        task = process_document_with_ai.delay(doc_id, context_tags)
        task_results.append({
            "document_id": doc_id,
            "task_id": task.id
        })
    
    return {
        "success": True,
        "batch_size": len(document_ids),
        "tasks_created": len(task_results),
        "task_results": task_results
    }


@shared_task
def reprocess_failed_documents(hours_back: int = 24) -> Dict[str, Any]:
    """
    Reprocess documents that failed within the specified time period
    
    Args:
        hours_back: How many hours back to look for failed documents
        
    Returns:
        Reprocessing results
    """
    from django.utils import timezone
    from datetime import timedelta
    
    cutoff_time = timezone.now() - timedelta(hours=hours_back)
    
    failed_documents = Document.objects.filter(
        status='failed',
        updated_at__gte=cutoff_time
    ).values_list('id', flat=True)
    
    logger.info(f"Found {len(failed_documents)} failed documents to reprocess")
    
    if not failed_documents:
        return {
            "success": True,
            "documents_found": 0,
            "tasks_created": 0
        }
    
    # Reset status and reprocess
    Document.objects.filter(id__in=failed_documents).update(
        status='pending',
        error_message=None,
        ai_processing_started_at=None,
        ai_processing_completed_at=None
    )
    
    # Submit for reprocessing
    task_results = []
    for doc_id in failed_documents:
        task = process_document_with_ai.delay(doc_id)
        task_results.append({
            "document_id": doc_id,
            "task_id": task.id
        })
    
    return {
        "success": True,
        "documents_found": len(failed_documents),
        "tasks_created": len(task_results),
        "task_results": task_results
    }


@shared_task
def cleanup_old_processing_records(days_old: int = 30) -> Dict[str, Any]:
    """
    Clean up old API usage logs and temporary processing data
    
    Args:
        days_old: How many days old records should be cleaned up
        
    Returns:
        Cleanup results
    """
    from datetime import timedelta
    from django.utils import timezone
    from apps.documents.models import APIUsageLog
    
    cutoff_date = timezone.now() - timedelta(days=days_old)
    
    # Clean up old API usage logs
    old_logs = APIUsageLog.objects.filter(timestamp__lt=cutoff_date)
    deleted_count = old_logs.count()
    old_logs.delete()
    
    logger.info(f"Cleaned up {deleted_count} old API usage log records")
    
    return {
        "success": True,
        "records_deleted": deleted_count,
        "cutoff_date": cutoff_date.isoformat()
    }


@shared_task
def generate_processing_report() -> Dict[str, Any]:
    """
    Generate a summary report of document processing statistics
    
    Returns:
        Processing statistics report
    """
    from django.db.models import Count, Avg, Sum
    from datetime import timedelta
    from django.utils import timezone
    
    # Get statistics for the last 24 hours
    last_24h = timezone.now() - timedelta(hours=24)
    
    stats = Document.objects.filter(updated_at__gte=last_24h).aggregate(
        total_documents=Count('id'),
        completed_documents=Count('id', filter=models.Q(status='completed')),
        failed_documents=Count('id', filter=models.Q(status='failed')),
        avg_tokens_used=Avg('ai_tokens_used'),
        total_cost=Sum('ai_estimated_cost')
    )
    
    # Calculate success rate
    total = stats['total_documents'] or 1
    success_rate = (stats['completed_documents'] / total) * 100
    
    report = {
        "period": "last_24_hours",
        "total_documents_processed": stats['total_documents'],
        "successful_extractions": stats['completed_documents'],
        "failed_extractions": stats['failed_documents'],
        "success_rate_percent": round(success_rate, 2),
        "average_tokens_per_document": round(stats['avg_tokens_used'] or 0, 0),
        "total_estimated_cost": round(float(stats['total_cost'] or 0), 4),
        "generated_at": timezone.now().isoformat()
    }
    
    logger.info(f"Generated processing report: {report}")
    return report


# Helper functions
def _calculate_average_confidence(fields: list) -> float:
    """Calculate average confidence score from extracted fields"""
    if not fields:
        return 0.0
    
    confidences = [field.get('confidence', 0.0) for field in fields if 'confidence' in field]
    return sum(confidences) / len(confidences) if confidences else 0.0


def _add_fhir_to_patient(patient, fhir_data: Dict, document_id: int) -> None:
    """Add FHIR data to patient's cumulative record"""
    try:
        # This would integrate with the existing patient FHIR methods
        if hasattr(patient, 'add_fhir_resources'):
            # Extract resources from bundle
            resources = []
            for entry in fhir_data.get('entry', []):
                if 'resource' in entry:
                    resources.append(entry['resource'])
            
            if resources:
                patient.add_fhir_resources(resources, document_id)
        
    except Exception as e:
        logger.error(f"Error adding FHIR data to patient {patient.id}: {e}")
        # Don't fail the task if FHIR integration fails


# Celery task routing configuration
# Add to settings/base.py:
"""
CELERY_TASK_ROUTES = {
    'apps.documents.tasks.process_document_with_ai': {'queue': 'ai_processing'},
    'apps.documents.tasks.batch_process_documents': {'queue': 'ai_processing'},
    'apps.documents.tasks.reprocess_failed_documents': {'queue': 'maintenance'},
    'apps.documents.tasks.cleanup_old_processing_records': {'queue': 'maintenance'},
    'apps.documents.tasks.generate_processing_report': {'queue': 'reports'},
}

# Worker configuration for AI processing
CELERY_TASK_TIME_LIMIT = 1800  # 30 minutes
CELERY_TASK_SOFT_TIME_LIMIT = 1620  # 27 minutes
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # One task at a time for AI processing
"""

# Usage examples:
"""
# In Django views
from .tasks import process_document_with_ai, batch_process_documents

# Single document processing
task = process_document_with_ai.delay(
    document_id=123,
    context_tags=[{"text": "Emergency Department"}]
)

# Batch processing
task = batch_process_documents.delay(
    document_ids=[1, 2, 3, 4, 5],
    context_tags=[{"text": "Cardiology Consultation"}]
)

# Check task status
result = task.get()  # Blocking
# or
if task.ready():
    result = task.result
""" 