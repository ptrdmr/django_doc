"""
Celery tasks for document processing.
Handles async document parsing and FHIR data extraction.
"""

from celery import shared_task
from meddocparser.celery import app
import time
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def test_celery_task(self, message="Hello from Celery!"):
    """
    Simple test task to verify Celery is working properly.
    
    Args:
        message (str): Test message to return
        
    Returns:
        dict: Task result with success status and message
    """
    try:
        # Log the task start
        logger.info(f"Starting test task: {self.request.id}")
        
        # Simulate some work
        time.sleep(2)
        
        result = {
            'success': True,
            'message': message,
            'task_id': self.request.id,
            'timestamp': time.time()
        }
        
        logger.info(f"Test task completed successfully: {self.request.id}")
        return result
        
    except Exception as exc:
        logger.error(f"Test task failed: {exc}")
        # Retry the task if it fails
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@shared_task(bind=True, name="apps.documents.tasks.process_document_async", acks_late=True)
def process_document_async(self, document_id: int):
    """
    Asynchronous task to process an uploaded medical document.
    This task handles PDF text extraction, AI analysis, and FHIR data accumulation.
    It's designed to be robust, with retries and comprehensive error logging.
    """
    # Ensure Django is set up before importing models
    import django
    django.setup()
    
    from .models import Document
    from .services import PDFTextExtractor, DocumentAnalyzer, APIRateLimitError
    
    try:
        logger.info(f"Starting document processing for document {document_id}")
        
        # Get the document object
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            error_msg = f"Document with ID {document_id} does not exist"
            logger.error(error_msg)
            return {
                'success': False,
                'document_id': document_id,
                'error_message': error_msg,
                'task_id': self.request.id
            }
        
        # Update status to processing
        document.status = 'processing'
        document.processing_started_at = timezone.now()
        document.increment_processing_attempts()
        document.save()
        
        # STEP 1: Extract text from PDF
        logger.info(f"Step 1: Extracting text from PDF: {document.file.path}")
        pdf_extractor = PDFTextExtractor()
        extraction_result = pdf_extractor.extract_text(document.file.path)
        
        if not extraction_result['success']:
            # Handle PDF extraction failure
            document.status = 'failed'
            document.error_message = f"PDF extraction failed: {extraction_result['error_message']}"
            document.processed_at = timezone.now()
            document.save()
            
            logger.error(f"PDF extraction failed for document {document_id}: {extraction_result['error_message']}")
            
            return {
                'success': False,
                'document_id': document_id,
                'status': 'failed',
                'task_id': self.request.id,
                'error_message': extraction_result['error_message'],
                'message': 'PDF text extraction failed'
            }
        
        # Store extracted text in document
        document.original_text = extraction_result['text']
        document.save()
        
        logger.info(f"PDF extraction successful: {extraction_result['page_count']} pages, "
                   f"{len(extraction_result['text'])} characters")
        
        # STEP 2: Analyze document with AI using comprehensive error recovery
        ai_result = None
        if extraction_result['text'].strip():
            try:
                logger.info(f"Step 2: Starting AI analysis with comprehensive error recovery for document {document_id}")
                
                # Initialize document analyzer with document for cost monitoring
                ai_analyzer = DocumentAnalyzer(document=document)
                
                # Prepare context for AI analysis
                context = None
                if hasattr(document, 'document_type') and document.document_type:
                    context = document.document_type
                elif document.providers.exists():
                    # Use provider info as context
                    provider = document.providers.first()
                    context = f"{provider.name} - {provider.specialty}" if hasattr(provider, 'specialty') else provider.name
                
                # DIRECT FIX: Call analyze_document directly to bypass any issues in process_with_comprehensive_recovery
                ai_result = ai_analyzer.analyze_document(
                    document_content=extraction_result['text'],
                    context=context
                )
                
                # Handle graceful degradation responses
                if ai_result.get('degraded'):
                    logger.warning(f"Document {document_id} processed with degradation: {ai_result.get('error_context', 'Unknown error')}")
                    
                    # Mark document for manual review
                    document.status = 'requires_review'
                    document.error_message = f"AI processing degraded: {ai_result.get('error_context', 'All AI services failed')}"
                    
                    # Log manual review requirement in audit system
                    from apps.core.models import AuditLog
                    AuditLog.log_event(
                        event_type='document_requires_review',
                        description=f"Document {document_id} requires manual review due to AI processing degradation",
                        details={
                            'document_id': document_id,
                            'degradation_reason': ai_result.get('error_context', 'Unknown'),
                            'partial_results_count': len(ai_result.get('fields', {})),
                            'manual_review_priority': ai_result.get('manual_review_priority', 'medium')
                        },
                        severity='warning'
                    )
                    
                    # Continue processing with partial results if any were extracted
                    if ai_result.get('fields'):
                        logger.info(f"Continuing with {len(ai_result['fields'])} partial results from degraded processing")
                else:
                    # Normal successful processing
                    ai_result = ai_result
                
                if ai_result['success']:
                    logger.info(f"AI analysis successful: {len(ai_result['fields'])} fields extracted")
                    
                    # STEP 3: Convert to FHIR format using enhanced FHIR processor
                    patient_id = str(document.patient.id) if document.patient else None
                    
                    # Use the new FHIRProcessor for comprehensive resource processing
                    try:
                        from apps.fhir.services import FHIRProcessor, FHIRMetricsService
                        
                        fhir_processor = FHIRProcessor()
                        fhir_resources = fhir_processor.process_extracted_data(ai_result['fields'], patient_id)
                        
                        logger.info(f"FHIRProcessor created {len(fhir_resources)} resources from extracted data")
                        
                        # Calculate data capture metrics
                        try:
                            metrics_service = FHIRMetricsService()
                            capture_metrics = metrics_service.calculate_data_capture_metrics(
                                ai_result['fields'], fhir_resources
                            )
                            
                            # Store metrics in AI result for reporting
                            ai_result['capture_metrics'] = capture_metrics
                            
                            # Log metrics summary
                            overall_rate = capture_metrics['overall']['capture_rate']
                            total_points = capture_metrics['overall']['total_data_points']
                            captured_points = capture_metrics['overall']['captured_data_points']
                            
                            logger.info(
                                f"Data capture metrics for document {document_id}: "
                                f"{overall_rate:.1f}% capture rate "
                                f"({captured_points}/{total_points} data points)"
                            )
                            
                            # Generate and log detailed metrics report
                            metrics_report = metrics_service.generate_metrics_report(capture_metrics)
                            logger.info(f"Detailed metrics report for document {document_id}:\n{metrics_report}")
                            
                        except Exception as metrics_exc:
                            logger.warning(f"Metrics calculation failed for document {document_id}: {metrics_exc}")
                            # Don't fail the task if metrics calculation fails
                        
                    except Exception as fhir_proc_exc:
                        logger.warning(f"FHIRProcessor failed, falling back to legacy converter: {fhir_proc_exc}")
                        # Fallback to legacy converter if new processor fails
                        fhir_resources = ai_analyzer.convert_to_fhir(ai_result['fields'], patient_id)
                    
                    # STEP 4: Accumulate FHIR resources to patient record
                    if document.patient and fhir_resources:
                        try:
                            from apps.fhir.services import FHIRAccumulator
                            
                            logger.info(f"Step 3: Accumulating {len(fhir_resources)} FHIR resources to patient {document.patient.mrn}")
                            
                            accumulator = FHIRAccumulator()
                            accumulation_result = accumulator.add_resources_to_patient(
                                patient=document.patient,
                                fhir_resources=fhir_resources,
                                source_system="DocumentAnalyzer",
                                responsible_user=document.uploaded_by,
                                source_document_id=str(document.id),
                                reason="Medical document processing",
                                validate_fhir=True,
                                resolve_conflicts=True
                            )
                            
                            if accumulation_result['success']:
                                logger.info(
                                    f"FHIR accumulation successful: {accumulation_result['resources_added']} "
                                    f"resources added, {accumulation_result['resources_skipped']} skipped, "
                                    f"{accumulation_result['conflicts_resolved']} conflicts resolved"
                                )
                                
                                # Store accumulation result for task response
                                ai_result['fhir_accumulation'] = {
                                    'success': True,
                                    'resources_added': accumulation_result['resources_added'],
                                    'resources_skipped': accumulation_result['resources_skipped'],
                                    'conflicts_resolved': accumulation_result['conflicts_resolved'],
                                    'bundle_version': accumulation_result['bundle_version']
                                }
                            else:
                                logger.error(f"FHIR accumulation failed: {accumulation_result.get('errors', [])}")
                                ai_result['fhir_accumulation'] = {
                                    'success': False,
                                    'errors': accumulation_result.get('errors', [])
                                }
                        
                        except Exception as fhir_exc:
                            logger.error(f"FHIR accumulation error for document {document_id}: {fhir_exc}")
                            ai_result['fhir_accumulation'] = {
                                'success': False,
                                'error': str(fhir_exc)
                            }
                    
                    # Store AI results (for backward compatibility and debugging)
                    if hasattr(document, 'ai_extracted_data'):
                        document.ai_extracted_data = ai_result['fields']
                    if hasattr(document, 'fhir_data'):
                        document.fhir_data = fhir_resources
                    
                    # Store AI usage information
                    if hasattr(document, 'ai_tokens_used'):
                        document.ai_tokens_used = ai_result.get('usage', {}).get('total_tokens', 0)
                    if hasattr(document, 'ai_model_used'):
                        document.ai_model_used = ai_result.get('model_used', 'unknown')
                    
                    # CRITICAL FIX: Create ParsedData record
                    try:
                        from .models import ParsedData
                        
                        parsed_data = ParsedData.objects.create(
                            document=document,
                            patient=document.patient,
                            extraction_json=ai_result.get('fields', []),
                            fhir_delta_json=fhir_resources if fhir_resources else {},
                            extraction_confidence=ai_result.get('confidence', 0.0),
                            ai_model_used=ai_result.get('model_used', 'unknown'),
                            processing_time_seconds=ai_result.get('processing_time', 0.0),  # Model has processing_time_seconds, not processing_duration_ms
                            capture_metrics=ai_result.get('capture_metrics', {})
                        )
                        
                        logger.info(f"Created ParsedData record {parsed_data.id} for document {document_id}")
                        
                    except Exception as pd_exc:
                        logger.error(f"Failed to create ParsedData for document {document_id}: {pd_exc}")
                        # Don't fail the task, but log the error
                    
                else:
                    logger.warning(f"AI analysis failed for document {document_id}: {ai_result.get('error', 'Unknown error')}")
                    # Don't fail the entire task if AI fails - PDF extraction was successful
                    
            except Exception as ai_exc:
                logger.warning(f"AI analysis error for document {document_id}: {ai_exc}")
                # Continue processing even if AI fails - we still have the extracted text
                ai_result = {
                    'success': False,
                    'error': str(ai_exc),
                    'fields': []
                }
        
        # FINAL CHECK: If AI analysis failed or was skipped, mark document as failed
        if not ai_result or not ai_result.get('success'):
            logger.error(f"AI analysis failed for document {document_id}. Marking document status as 'failed'.")
            document.status = 'failed'
            document.error_message = f"AI analysis failed: {ai_result.get('error', 'No content to analyze') if ai_result else 'No content to analyze'}"
            document.processed_at = timezone.now()
            document.save()
            
            # Return a failure result
            return {
                'success': False,
                'document_id': document_id,
                'status': 'failed',
                'error_message': document.error_message
            }
        
        # Mark document as ready for review (NOT completed yet)
        # Data should only be marked 'completed' after user review and approval
        document.status = 'review'
        document.processed_at = timezone.now()
        document.error_message = ''
        document.save()
        
        logger.info(f"Document {document_id} processed successfully and marked for review")
        
        # Prepare comprehensive result
        result = {
            'success': True,
            'document_id': document_id,
            'status': 'review',
            'task_id': self.request.id,
            'pdf_extraction': {
                'success': extraction_result['success'],
                'text_length': len(extraction_result['text']),
                'page_count': extraction_result['page_count'],
                'file_size_mb': extraction_result['file_size'],
                'metadata': extraction_result['metadata']
            },
            'ai_analysis': ai_result if ai_result else {'success': False, 'error': 'AI analysis skipped - no content or no API keys'},
            'message': f'Document processing completed successfully - {extraction_result["page_count"]} pages processed'
        }
        
        # Add AI-specific info to result if successful
        if ai_result and ai_result['success']:
            result['ai_analysis'].update({
                'fields_extracted': len(ai_result['fields']),
                'model_used': ai_result.get('model_used'),
                'processing_method': ai_result.get('processing_method'),
                'tokens_used': ai_result.get('usage', {}).get('total_tokens', 0)
            })
        
        logger.info(f"Document {document_id} processing completed successfully")
        return result
        
    except APIRateLimitError as exc:
        logger.warning(f"Rate limit exceeded for document {document_id}. Retrying task.")
        raise self.retry(exc=exc, countdown=60, max_retries=5) # Retry after 60s
        
    except Exception as exc:
        # Handle unexpected errors
        logger.error(f"Document processing failed for {document_id}: {exc}")
        
        try:
            # Try to update document status
            document = Document.objects.get(id=document_id)
            document.status = 'failed'
            document.error_message = f"Processing error: {str(exc)}"
            document.processed_at = timezone.now()
            document.save()
        except:
            # If we can't even update the document, log it
            logger.error(f"Failed to update document {document_id} status after error")
        
        # Retry the task if it's a retryable error
        if document.can_retry_processing():
            logger.info(f"Retrying document {document_id} processing (attempt {document.processing_attempts})")
            raise self.retry(exc=exc, countdown=300, max_retries=3)  # 5 minute retry delay
        else:
            logger.error(f"Max retries exceeded for document {document_id}")
            return {
                'success': False,
                'document_id': document_id,
                'status': 'failed',
                'error_message': f"Processing failed after max retries: {str(exc)}",
                'message': 'Document processing failed permanently'
            }


@shared_task
def cleanup_old_documents():
    """
    Periodic task to clean up old processed documents.
    This task is scheduled in the CELERY_BEAT_SCHEDULE.
    """
    logger.info("Starting cleanup of old documents")
    
    # Placeholder for cleanup logic
    # This will be implemented when we have the document models
    
    logger.info("Document cleanup completed")
    return "Cleanup task completed" 