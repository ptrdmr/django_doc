"""
Celery tasks for document processing.
Handles async document parsing and FHIR data extraction.

Enhanced with comprehensive error handling and logging for Task 34.5.
"""

from celery import shared_task
from meddocparser.celery import app
import time
import logging
from django.utils import timezone
from typing import Dict, Any

# Import custom exceptions for enhanced error handling
from .exceptions import (
    DocumentProcessingError,
    PDFExtractionError,
    AIExtractionError,
    AIServiceRateLimitError,
    AIServiceTimeoutError,
    FHIRConversionError,
    CeleryTaskError,
    categorize_exception,
    get_recovery_strategy
)

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


@shared_task(bind=True, name="apps.documents.tasks.process_document_async", acks_late=True, 
             autoretry_for=(AIServiceRateLimitError, AIServiceTimeoutError), 
             retry_kwargs={'max_retries': 3, 'countdown': 60})
def process_document_async(self, document_id: int):
    """
    Asynchronous task to process an uploaded medical document.
    This task handles PDF text extraction, AI analysis, and FHIR data accumulation.
    It's designed to be robust, with retries and comprehensive error logging.
    
    Enhanced with comprehensive error handling and recovery strategies for Task 34.5.
    
    Args:
        document_id: ID of the document to process
        
    Returns:
        Dict with processing results and error information
        
    Raises:
        CeleryTaskError: For critical failures that require manual intervention
    """
    # Ensure Django is set up before importing models
    import django
    django.setup()
    
    from .models import Document
    from apps.documents.services import PDFTextExtractor, APIRateLimitError
    from apps.documents.analyzers import DocumentAnalyzer
    from apps.fhir.converters import StructuredDataConverter
    
    # Initialize task tracking
    task_id = self.request.id
    start_time = time.time()
    processing_errors = []
    recovery_actions = []
    
    logger.info(f"[{task_id}] Starting document processing for document {document_id}")
    
    try:
        # Enhanced document retrieval with validation
        try:
            document = Document.objects.select_related('patient').get(id=document_id)
            
            # Validate document state
            if not document.file:
                raise DocumentProcessingError(
                    "Document has no associated file",
                    error_code="MISSING_FILE",
                    details={'document_id': document_id, 'task_id': task_id}
                )
            
            if not document.patient:
                raise DocumentProcessingError(
                    "Document has no associated patient",
                    error_code="MISSING_PATIENT",
                    details={'document_id': document_id, 'task_id': task_id}
                )
            
            logger.info(f"[{task_id}] Document validated: {document.file.name} for patient {document.patient.id}")
            
        except Document.DoesNotExist:
            error_msg = f"Document with ID {document_id} does not exist"
            logger.error(f"[{task_id}] {error_msg}")
            raise CeleryTaskError(
                error_msg,
                task_id=task_id,
                details={'document_id': document_id, 'lookup_failed': True}
            )
        except DocumentProcessingError:
            raise
        except Exception as e:
            raise CeleryTaskError(
                f"Failed to retrieve document {document_id}: {str(e)}",
                task_id=task_id,
                details={'document_id': document_id, 'error_type': type(e).__name__}
            )
        
        # Update status to processing with comprehensive tracking
        try:
            document.status = 'processing'
            document.processing_started_at = timezone.now()
            document.increment_processing_attempts()
            document.save()
            
            logger.info(f"[{task_id}] Document status updated to processing (attempt #{document.processing_attempts})")
            
        except Exception as e:
            logger.error(f"[{task_id}] Failed to update document status: {e}")
            # Continue processing despite status update failure
            
        # STEP 1: Enhanced PDF text extraction with detailed error handling
        pdf_step_start = time.time()
        logger.info(f"[{task_id}] Step 1: Starting PDF text extraction from {document.file.path}")
        
        try:
            # Validate file existence and readability
            import os
            if not os.path.exists(document.file.path):
                raise PDFExtractionError(
                    f"Document file not found: {document.file.path}",
                    file_path=document.file.path,
                    details={'document_id': document_id, 'task_id': task_id}
                )
            
            file_size = os.path.getsize(document.file.path)
            if file_size == 0:
                raise PDFExtractionError(
                    "Document file is empty",
                    file_path=document.file.path,
                    details={'document_id': document_id, 'task_id': task_id, 'file_size': file_size}
                )
            
            if file_size > 100 * 1024 * 1024:  # 100MB limit
                logger.warning(f"[{task_id}] Large file detected: {file_size / (1024*1024):.1f}MB")
            
            # Perform PDF extraction
            pdf_extractor = PDFTextExtractor()
            extraction_result = pdf_extractor.extract_text(document.file.path)
            
            pdf_step_time = time.time() - pdf_step_start
            
            if not extraction_result.get('success', False):
                error_msg = extraction_result.get('error_message', 'Unknown PDF extraction error')
                raise PDFExtractionError(
                    f"PDF extraction failed: {error_msg}",
                    file_path=document.file.path,
                    details={
                        'document_id': document_id,
                        'task_id': task_id,
                        'file_size': file_size,
                        'extraction_time': pdf_step_time,
                        'extraction_result': extraction_result
                    }
                )
            
            # Validate extraction results
            extracted_text = extraction_result.get('text', '')
            if not extracted_text or not extracted_text.strip():
                logger.warning(f"[{task_id}] PDF extraction returned empty text")
                raise PDFExtractionError(
                    "PDF extraction returned no text content",
                    file_path=document.file.path,
                    details={
                        'document_id': document_id,
                        'task_id': task_id,
                        'page_count': extraction_result.get('page_count', 0),
                        'extraction_time': pdf_step_time
                    }
                )
            
            logger.info(f"[{task_id}] PDF extraction successful: {extraction_result.get('page_count', 0)} pages, "
                       f"{len(extracted_text)} characters in {pdf_step_time:.2f}s")
            
        except PDFExtractionError as pdf_error:
            processing_errors.append(str(pdf_error))
            
            # Update document with failure information
            try:
                document.status = 'failed'
                document.error_message = str(pdf_error)
                document.processed_at = timezone.now()
                document.save()
            except Exception as save_error:
                logger.error(f"[{task_id}] Failed to save PDF error to document: {save_error}")
            
            logger.error(f"[{task_id}] PDF extraction failed: {pdf_error}")
            
            # Return detailed error information
            return {
                'success': False,
                'document_id': document_id,
                'status': 'failed',
                'task_id': task_id,
                'error_type': 'PDFExtractionError',
                'error_code': pdf_error.error_code,
                'error_message': str(pdf_error),
                'error_details': pdf_error.details,
                'processing_time': time.time() - start_time,
                'recovery_strategy': get_recovery_strategy(pdf_error.error_code)
            }
        except Exception as unexpected_error:
            error_info = categorize_exception(unexpected_error)
            processing_errors.append(str(unexpected_error))
            
            logger.error(f"[{task_id}] Unexpected PDF extraction error: {unexpected_error}", exc_info=True)
            
            # Update document with failure information
            try:
                document.status = 'failed'
                document.error_message = f"Unexpected PDF error: {str(unexpected_error)}"
                document.processed_at = timezone.now()
                document.save()
            except Exception as save_error:
                logger.error(f"[{task_id}] Failed to save unexpected PDF error: {save_error}")
            
            return {
                'success': False,
                'document_id': document_id,
                'status': 'failed',
                'task_id': task_id,
                'error_type': 'UnexpectedError',
                'error_message': str(unexpected_error),
                'error_details': error_info,
                'processing_time': time.time() - start_time,
                'recovery_strategy': 'manual_intervention'
            }
        
        # Store extracted text in document
        document.original_text = extraction_result['text']
        document.save()
        
        logger.info(f"PDF extraction successful: {extraction_result['page_count']} pages, "
                   f"{len(extraction_result['text'])} characters")
        
        # STEP 2: Analyze document with AI using new structured extraction pipeline
        ai_result = None
        structured_extraction = None
        if extraction_result['text'].strip():
            try:
                logger.info(f"Step 2: Starting AI analysis with structured extraction pipeline for document {document_id}")
                
                # Initialize document analyzer
                ai_analyzer = DocumentAnalyzer(document=document)
                
                # Prepare context for AI analysis
                context = None
                if hasattr(document, 'document_type') and document.document_type:
                    context = document.document_type
                elif document.providers.exists():
                    # Use provider info as context
                    provider = document.providers.first()
                    context = f"{provider.name} - {provider.specialty}" if hasattr(provider, 'specialty') else provider.name
                
                # NEW: Use structured extraction pipeline
                try:
                    logger.info(f"Attempting structured extraction for document {document_id}")
                    structured_extraction = ai_analyzer.analyze_document_structured(
                        document_content=extraction_result['text'],
                        context=context
                    )
                    
                    if structured_extraction:
                        # Convert structured data to legacy format for backward compatibility
                        ai_result = {
                            'success': True,
                            'fields': [
                                # Convert conditions
                                *[{
                                    'label': f'diagnosis_{i+1}',
                                    'value': condition.name,
                                    'confidence': condition.confidence,
                                    'source_text': condition.source.text,
                                    'char_position': condition.source.start_index
                                } for i, condition in enumerate(structured_extraction.conditions)],
                                
                                # Convert medications
                                *[{
                                    'label': f'medication_{i+1}',
                                    'value': f"{medication.name} {medication.dosage or ''}".strip(),
                                    'confidence': medication.confidence,
                                    'source_text': medication.source.text,
                                    'char_position': medication.source.start_index
                                } for i, medication in enumerate(structured_extraction.medications)],
                                
                                # Convert vital signs
                                *[{
                                    'label': f'vital_{vital.measurement.lower().replace(" ", "_")}',
                                    'value': f"{vital.value} {vital.unit or ''}".strip(),
                                    'confidence': vital.confidence,
                                    'source_text': vital.source.text,
                                    'char_position': vital.source.start_index
                                } for vital in structured_extraction.vital_signs],
                                
                                # Convert lab results
                                *[{
                                    'label': f'lab_{lab.test_name.lower().replace(" ", "_")}',
                                    'value': f"{lab.value} {lab.unit or ''}".strip(),
                                    'confidence': lab.confidence,
                                    'source_text': lab.source.text,
                                    'char_position': lab.source.start_index
                                } for lab in structured_extraction.lab_results]
                            ],
                            'model_used': 'structured_extraction_claude',
                            'processing_method': 'structured_pydantic',
                            'usage': {
                                'total_tokens': 0,  # Will be updated if available
                            },
                            'processing_duration_ms': 0,  # Will be updated if available
                            'structured_data': structured_extraction  # Store the original structured data
                        }
                        
                        logger.info(f"Structured extraction successful: {len(ai_result['fields'])} fields extracted from structured data")
                    
                except Exception as structured_exc:
                    logger.error(f"Structured extraction failed for document {document_id}: {structured_exc}")
                    structured_extraction = None
                    # Create a failure ai_result instead of None
                    ai_result = {
                        'success': False,
                        'error': f"Structured extraction failed: {str(structured_exc)}",
                        'fields': [],
                        'model_used': 'structured_extraction_failed',
                        'processing_method': 'failed'
                    }
                
                # FALLBACK: Use legacy extraction if structured extraction failed
                # KEEP DISABLED TO FORCE STRUCTURED EXTRACTION AND EXPOSE REAL ERRORS
                # if not structured_extraction:
                #     logger.error(f"STRUCTURED EXTRACTION FAILED for document {document_id}, using legacy fallback")
                #     ai_result = ai_analyzer.analyze_document(
                #         document_content=extraction_result['text'],
                #         context=context
                #     )
                
                # Handle graceful degradation responses
                if ai_result and ai_result.get('degraded'):
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
                
                if ai_result and ai_result.get('success'):
                    logger.info(f"AI analysis successful: {len(ai_result['fields'])} fields extracted")
                    
                    # STEP 3: Convert to FHIR format using appropriate converter
                    patient_id = str(document.patient.id) if document.patient else None
                    
                    # NEW: Use StructuredDataConverter if we have structured data
                    if structured_extraction:
                        try:
                            logger.info(f"Using StructuredDataConverter for FHIR conversion")
                            structured_converter = StructuredDataConverter()
                            
                            # Prepare metadata for conversion
                            conversion_metadata = {
                                'document_id': document.id,
                                'extraction_timestamp': structured_extraction.extraction_timestamp,
                                'document_type': structured_extraction.document_type,
                                'confidence_average': structured_extraction.confidence_average
                            }
                            
                            fhir_resources = structured_converter.convert_structured_data(
                                structured_extraction, 
                                conversion_metadata, 
                                document.patient
                            )
                            
                            logger.info(f"StructuredDataConverter created {len(fhir_resources)} resources from structured data")
                            
                        except Exception as struct_conv_exc:
                            logger.warning(f"StructuredDataConverter failed, falling back to legacy: {struct_conv_exc}")
                            structured_extraction = None  # Clear to trigger fallback
                    
                    # FALLBACK: Use legacy FHIR processor if structured conversion failed or not available
                    if not structured_extraction:
                        try:
                            from apps.fhir.services import FHIRProcessor, FHIRMetricsService
                            
                            fhir_processor = FHIRProcessor()
                            fhir_resources = fhir_processor.process_extracted_data(ai_result['fields'], patient_id)
                            
                            logger.info(f"Legacy FHIRProcessor created {len(fhir_resources)} resources from extracted data")
                            
                        except Exception as fhir_proc_exc:
                            logger.warning(f"FHIRProcessor failed, no FHIR conversion available: {fhir_proc_exc}")
                            # No fallback available - structured extraction should handle FHIR conversion
                            fhir_resources = []
                    
                    # Calculate data capture metrics (works with both structured and legacy data)
                    try:
                        from apps.fhir.services import FHIRMetricsService
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
                    
                    # FHIR resources are now stored in ParsedData for review workflow
                    # Actual accumulation to patient record happens after user approval
                    # via the merge_to_patient_record task
                    logger.info(f"FHIR processing completed: {len(fhir_resources)} resources ready for review and approval")
                    
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
                    
                    # ENHANCED: Create ParsedData record with structured data support
                    try:
                        from .models import ParsedData
                        
                        # Extract snippet data from fields for the new source_snippets field
                        fields_data = ai_result.get('fields', [])
                        snippets_data = {}
                        
                        for field in fields_data:
                            field_label = field.get('label', '')
                            if field_label and ('source_text' in field or 'char_position' in field):
                                snippets_data[field_label] = {
                                    'source_text': field.get('source_text', ''),
                                    'char_position': field.get('char_position', 0)
                                }
                        
                        # Calculate confidence and processing time from fields and usage data
                        avg_confidence = 0.0
                        if structured_extraction:
                            # Use structured data confidence average if available
                            avg_confidence = structured_extraction.confidence_average
                        elif fields_data:
                            # Fallback to calculating from individual fields
                            confidences = [field.get('confidence', 0.0) for field in fields_data if isinstance(field, dict)]
                            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
                        
                        # Get processing time from usage data
                        usage_data = ai_result.get('usage', {})
                        processing_time = ai_result.get('processing_duration_ms', 0) / 1000.0 if 'processing_duration_ms' in ai_result else 0.0
                        
                        # Prepare structured data for storage (serialize if available)
                        structured_data_dict = None
                        if structured_extraction:
                            structured_data_dict = structured_extraction.dict()
                        
                        parsed_data, created = ParsedData.objects.update_or_create(
                            document=document,
                            defaults={
                                'patient': document.patient,
                                'extraction_json': fields_data,
                                'source_snippets': snippets_data,  # Store snippet data in new field
                                'fhir_delta_json': fhir_resources if fhir_resources else {},
                                'extraction_confidence': avg_confidence,
                                'ai_model_used': ai_result.get('model_used', 'unknown'),
                                'processing_time_seconds': processing_time,
                                'capture_metrics': ai_result.get('capture_metrics', {}),
                                'is_approved': False,  # Reset approval status for reprocessed documents
                                'is_merged': False,    # Reset merge status for reprocessed documents
                                'reviewed_at': None,   # Clear review timestamp for reprocessed documents
                                'reviewed_by': None,   # Clear reviewer for reprocessed documents
                                # NEW: Store structured data if available (could add a field for this)
                                'corrections': {'structured_data': structured_data_dict} if structured_data_dict else {},
                            }
                        )
                        
                        action = "Created" if created else "Updated"
                        logger.info(f"{action} ParsedData record {parsed_data.id} for document {document_id}")
                        
                    except Exception as pd_exc:
                        logger.error(f"Failed to save ParsedData for document {document_id}: {pd_exc}")
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
                'tokens_used': ai_result.get('usage', {}).get('total_tokens', 0),
                'fhir_resources_created': len(fhir_resources) if fhir_resources else 0,
                'structured_extraction_used': structured_extraction is not None,
                'structured_data_types': {
                    'conditions': len(structured_extraction.conditions) if structured_extraction else 0,
                    'medications': len(structured_extraction.medications) if structured_extraction else 0,
                    'vital_signs': len(structured_extraction.vital_signs) if structured_extraction else 0,
                    'lab_results': len(structured_extraction.lab_results) if structured_extraction else 0,
                    'procedures': len(structured_extraction.procedures) if structured_extraction else 0,
                    'providers': len(structured_extraction.providers) if structured_extraction else 0
                } if structured_extraction else {}
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


@shared_task(bind=True, name="apps.documents.tasks.merge_to_patient_record")
def merge_to_patient_record(self, parsed_data_id: int):
    """
    Merge approved FHIR data from ParsedData into patient's cumulative record.
    
    This task is triggered when a document is approved during the review process.
    It takes the FHIR data from the ParsedData record and merges it into the
    patient's encrypted_fhir_bundle using the patient's add_fhir_resources method.
    
    Args:
        parsed_data_id (int): ID of the ParsedData record to merge
        
    Returns:
        dict: Task result with success status and details
    """
    import django
    django.setup()
    
    from .models import ParsedData
    from apps.patients.models import Patient
    
    try:
        logger.info(f"Starting FHIR data merge for ParsedData {parsed_data_id}")
        
        # Get the ParsedData record
        try:
            parsed_data = ParsedData.objects.select_related('patient', 'document').get(id=parsed_data_id)
        except ParsedData.DoesNotExist:
            error_msg = f"ParsedData with ID {parsed_data_id} does not exist"
            logger.error(error_msg)
            return {
                'success': False,
                'parsed_data_id': parsed_data_id,
                'error_message': error_msg,
                'task_id': self.request.id
            }
        
        # Verify the data is approved and not already merged
        if not parsed_data.is_approved:
            error_msg = f"ParsedData {parsed_data_id} is not approved for merging"
            logger.error(error_msg)
            return {
                'success': False,
                'parsed_data_id': parsed_data_id,
                'error_message': error_msg,
                'task_id': self.request.id
            }
        
        if parsed_data.is_merged:
            logger.warning(f"ParsedData {parsed_data_id} is already merged")
            return {
                'success': True,
                'parsed_data_id': parsed_data_id,
                'message': 'Data already merged',
                'task_id': self.request.id
            }
        
        # Get FHIR data to merge
        fhir_data = parsed_data.fhir_delta_json
        if not fhir_data:
            error_msg = f"No FHIR data found in ParsedData {parsed_data_id}"
            logger.error(error_msg)
            return {
                'success': False,
                'parsed_data_id': parsed_data_id,
                'error_message': error_msg,
                'task_id': self.request.id
            }
        
        # Convert FHIR data to list format if it's a dict
        fhir_resources = []
        if isinstance(fhir_data, dict):
            # If it's a bundle, extract resources
            if fhir_data.get('resourceType') == 'Bundle' and 'entry' in fhir_data:
                fhir_resources = [entry['resource'] for entry in fhir_data['entry'] if 'resource' in entry]
            else:
                # Single resource
                fhir_resources = [fhir_data]
        elif isinstance(fhir_data, list):
            fhir_resources = fhir_data
        else:
            error_msg = f"Invalid FHIR data format in ParsedData {parsed_data_id}: {type(fhir_data)}"
            logger.error(error_msg)
            return {
                'success': False,
                'parsed_data_id': parsed_data_id,
                'error_message': error_msg,
                'task_id': self.request.id
            }
        
        # Merge FHIR data into patient record
        try:
            patient = parsed_data.patient
            success = patient.add_fhir_resources(fhir_resources, document_id=parsed_data.document.id)
            
            if success:
                # Mark ParsedData as merged
                parsed_data.is_merged = True
                parsed_data.merged_at = timezone.now()
                parsed_data.save()
                
                logger.info(
                    f"Successfully merged {len(fhir_resources)} FHIR resources from ParsedData {parsed_data_id} "
                    f"into patient {patient.mrn} record"
                )
                
                return {
                    'success': True,
                    'parsed_data_id': parsed_data_id,
                    'patient_mrn': patient.mrn,
                    'resources_merged': len(fhir_resources),
                    'document_id': parsed_data.document.id,
                    'task_id': self.request.id,
                    'message': f'Successfully merged {len(fhir_resources)} FHIR resources into patient record'
                }
            else:
                error_msg = f"Failed to add FHIR resources to patient {patient.mrn}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'parsed_data_id': parsed_data_id,
                    'error_message': error_msg,
                    'task_id': self.request.id
                }
                
        except Exception as merge_error:
            logger.error(f"Error merging FHIR data for ParsedData {parsed_data_id}: {merge_error}")
            return {
                'success': False,
                'parsed_data_id': parsed_data_id,
                'error_message': f"Merge error: {str(merge_error)}",
                'task_id': self.request.id
            }
        
    except Exception as exc:
        logger.error(f"Unexpected error in merge task for ParsedData {parsed_data_id}: {exc}")
        
        # Retry the task if it's a retryable error
        if hasattr(self, 'retry') and self.request.retries < 3:
            logger.info(f"Retrying merge task for ParsedData {parsed_data_id} (attempt {self.request.retries + 1})")
            raise self.retry(exc=exc, countdown=60, max_retries=3)
        else:
            return {
                'success': False,
                'parsed_data_id': parsed_data_id,
                'error_message': f"Task failed after retries: {str(exc)}",
                'task_id': self.request.id
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