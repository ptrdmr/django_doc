"""
Celery tasks for document processing.
Handles async document parsing and FHIR data extraction.
"""

from celery import shared_task
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


@shared_task(bind=True)
def process_document_async(self, document_id):
    """
    Process medical documents asynchronously with PDF text extraction and AI analysis.
    
    Args:
        document_id (int): ID of the document to process
        
    Returns:
        dict: Processing result with extracted text and AI analysis information
    """
    from .models import Document
    from .services import PDFTextExtractor, DocumentAnalyzer
    
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
        
        # STEP 2: Analyze document with AI (if text was extracted and API keys are available)
        ai_result = None
        if extraction_result['text'].strip():
            try:
                logger.info(f"Step 2: Starting AI analysis for document {document_id}")
                
                # Initialize document analyzer
                ai_analyzer = DocumentAnalyzer()
                
                # Prepare context for AI analysis
                context = None
                if hasattr(document, 'document_type') and document.document_type:
                    context = document.document_type
                elif document.providers.exists():
                    # Use provider info as context
                    provider = document.providers.first()
                    context = f"{provider.name} - {provider.specialty}" if hasattr(provider, 'specialty') else provider.name
                
                # Perform AI analysis
                ai_result = ai_analyzer.analyze_document(
                    document_content=extraction_result['text'],
                    context=context
                )
                
                if ai_result['success']:
                    logger.info(f"AI analysis successful: {len(ai_result['fields'])} fields extracted")
                    
                    # Convert to FHIR format
                    fhir_data = ai_analyzer.convert_to_fhir(ai_result['fields'])
                    
                    # Store AI results (we'll create the ParsedData model in the next subtask)
                    # For now, we can store in a JSON field if it exists on Document model
                    if hasattr(document, 'ai_extracted_data'):
                        document.ai_extracted_data = ai_result['fields']
                    if hasattr(document, 'fhir_data'):
                        document.fhir_data = fhir_data
                    
                    # Store AI usage information
                    if hasattr(document, 'ai_tokens_used'):
                        document.ai_tokens_used = ai_result.get('usage', {}).get('total_tokens', 0)
                    if hasattr(document, 'ai_model_used'):
                        document.ai_model_used = ai_result.get('model_used', 'unknown')
                    
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
        
        # Mark document as completed
        document.status = 'completed'
        document.processed_at = timezone.now()
        document.error_message = ''
        document.save()
        
        # Prepare comprehensive result
        result = {
            'success': True,
            'document_id': document_id,
            'status': 'completed',
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
                'task_id': self.request.id,
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