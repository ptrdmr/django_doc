"""
Celery tasks for document processing.
Handles async document parsing and FHIR data extraction.

Enhanced with comprehensive error handling and logging for Task 34.5.
"""

from celery import shared_task
from meddocparser.celery import app
import time
import logging
import json
from django.conf import settings
from django.utils import timezone
from typing import Dict, Any, List

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
from .performance import performance_monitor, document_chunker

logger = logging.getLogger(__name__)


def check_document_idempotency(document_id: int, task_id: str) -> dict:
    """
    Check if document has already been processed to prevent duplicate processing.
    
    Uses database-level locking (select_for_update) to prevent race conditions
    where multiple tasks attempt to process the same document simultaneously.
    
    Args:
        document_id: ID of the document to check
        task_id: Celery task ID for logging
    
    Returns:
        dict with 'should_skip' bool and optional 'skip_response' dict
        
        If should_skip is True, skip_response contains:
        - success: True
        - document_id: Document ID
        - status: 'completed' or 'skipped'
        - task_id: Celery task ID
        - message: Reason for skipping
        - idempotent_skip: True
        - already_processed: True (if document was already merged)
    
    Raises:
        Document.DoesNotExist: If document doesn't exist (should be handled by caller)
    
    Performance:
        - Completes in <5ms for already-processed documents
        - Uses nowait=True to fail fast if document is locked
    """
    from .models import Document, ParsedData
    from django.db import transaction
    from django.db.utils import OperationalError
    
    with transaction.atomic():
        # Lock the document row to prevent concurrent processing
        try:
            document_check = Document.objects.select_for_update(nowait=True).get(id=document_id)
        except Document.DoesNotExist:
            # Document doesn't exist - re-raise to be handled by caller
            logger.warning(f"[{task_id}] Document {document_id} does not exist during idempotency check")
            raise
        except OperationalError:
            # Can't get lock - another task is processing this document
            logger.warning(
                f"[{task_id}] Document {document_id} is currently being processed by another task. "
                "Skipping to prevent duplicate processing."
            )
            return {
                'should_skip': True,
                'skip_response': {
                    'success': True,
                    'document_id': document_id,
                    'status': 'skipped',
                    'task_id': task_id,
                    'message': 'Document is already being processed by another task',
                    'idempotent_skip': True
                }
            }
        
        # Check if document already has successful processing
        if document_check.status == 'completed':
            parsed_data_exists = ParsedData.objects.filter(
                document_id=document_id,
                is_merged=True
            ).exists()
            
            if parsed_data_exists:
                logger.info(
                    f"[{task_id}] Document {document_id} already successfully processed and merged. "
                    "Skipping to maintain idempotency."
                )
                return {
                    'should_skip': True,
                    'skip_response': {
                        'success': True,
                        'document_id': document_id,
                        'status': 'completed',
                        'task_id': task_id,
                        'message': 'Document already successfully processed',
                        'idempotent_skip': True,
                        'already_processed': True
                    }
                }
        
        # Check if document is in failed state and needs reprocessing
        if document_check.status == 'failed':
            logger.info(
                f"[{task_id}] Document {document_id} previously failed, attempting reprocessing"
            )
            # Reset status to allow reprocessing
            document_check.status = 'pending'
            document_check.error_message = ''  # Empty string, not None (field is not nullable)
            document_check.save(update_fields=['status', 'error_message'])
        
        logger.info(f"[{task_id}] Idempotency check passed, proceeding with processing")
        return {'should_skip': False}


@shared_task(bind=True)
@performance_monitor.timing_decorator("document_chunk_processing")
def process_document_chunk(self, document_id: int, chunk_text: str, chunk_id: int, chunk_metadata: Dict = None):
    """
    Process a single chunk of a large document for parallel extraction.
    
    Args:
        document_id: ID of the source document
        chunk_text: Text content of this chunk
        chunk_id: Unique identifier for this chunk
        chunk_metadata: Additional metadata about the chunk (start/end positions, etc.)
        
    Returns:
        Extracted medical data from this chunk
    """
    try:
        logger.info(f"Processing chunk {chunk_id} for document {document_id} ({len(chunk_text)} chars)")
        
        # Extract medical data from chunk
        from apps.documents.services.ai_extraction import extract_medical_data_structured
        
        chunk_context = f"Document chunk {chunk_id + 1} of large medical document"
        structured_data = extract_medical_data_structured(chunk_text, context=chunk_context)
        
        # Convert to dictionary and add chunk metadata
        result = structured_data.model_dump()
        result['chunk_metadata'] = {
            'chunk_id': chunk_id,
            'chunk_size': len(chunk_text),
            'document_id': document_id,
            'start_index': chunk_metadata.get('start_index', 0) if chunk_metadata else 0,
            'end_index': chunk_metadata.get('end_index', len(chunk_text)) if chunk_metadata else len(chunk_text)
        }
        
        logger.info(f"Chunk {chunk_id} processed successfully: {sum(len(v) for k, v in result.items() if isinstance(v, list))} items")
        return result
        
    except Exception as e:
        logger.error(f"Failed to process chunk {chunk_id} for document {document_id}: {e}")
        # Return empty result rather than failing the entire parallel operation
        return {
            'conditions': [],
            'medications': [],
            'vital_signs': [],
            'lab_results': [],
            'procedures': [],
            'providers': [],
            'chunk_metadata': {
                'chunk_id': chunk_id,
                'document_id': document_id,
                'error': str(e),
                'processing_failed': True
            }
        }


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
    from apps.core.porthole import capture_pdf_text, capture_llm_output, capture_fhir_data, capture_raw_llm_response, capture_pipeline_error
    from .validation_utils import ValidationContext, validate_before_ai_extraction, validate_after_ai_extraction
    
    # Initialize task tracking
    task_id = self.request.id
    start_time = time.time()
    processing_errors = []
    recovery_actions = []
    
    logger.info(f"[{task_id}] Starting document processing for document {document_id}")
    
    # Task 41.15: IDEMPOTENCY CHECK - Prevent duplicate processing
    try:
        idempotency_result = check_document_idempotency(document_id, task_id)
        if idempotency_result['should_skip']:
            return idempotency_result['skip_response']
    except Document.DoesNotExist:
        # Document doesn't exist - re-raise to be handled by main try block
        raise
    except Exception as idempotency_check_error:
        # Log but don't fail - proceed with processing
        logger.warning(
            f"[{task_id}] Idempotency check failed: {idempotency_check_error}. "
            "Proceeding with processing."
        )
    
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
            document.processing_message = "Initializing processing..."
            document.processing_started_at = timezone.now()
            document.increment_processing_attempts()
            document.save()
            
            logger.info(f"[{task_id}] Document status updated to processing (attempt #{document.processing_attempts})")
            
        except Exception as e:
            logger.error(f"[{task_id}] Failed to update document status: {e}")
            # Continue processing despite status update failure
            
        # STEP 1: Enhanced PDF text extraction with detailed error handling
        document.processing_message = "Extracting text from PDF..."
        document.save(update_fields=['processing_message'])
        
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
        
        # PORTHOLE: Capture PDF text extraction
        capture_pdf_text(
            document_id=document_id,
            extracted_text=extraction_result['text'],
            metadata={
                'page_count': extraction_result['page_count'],
                'file_size_mb': extraction_result['file_size'],
                'pdf_metadata': extraction_result.get('metadata', {})
            }
        )
        
        logger.info(f"PDF extraction successful: {extraction_result['page_count']} pages, "
                   f"{len(extraction_result['text'])} characters")
        
        # PERFORMANCE OPTIMIZATION: Determine processing strategy based on document size
        extracted_text = extraction_result['text']
        text_length = len(extracted_text)
        chunk_threshold = getattr(settings, 'AI_TOKEN_THRESHOLD_FOR_CHUNKING', 20000)
        
        logger.info(f"[{task_id}] Document size: {text_length} chars (threshold: {chunk_threshold})")
        
        # STEP 2: Analyze document with AI using size-appropriate strategy
        ai_result = None
        structured_extraction = None
        if extracted_text.strip():
            # VALIDATION: Check text quality before AI extraction
            if not validate_before_ai_extraction(document, extraction_result['text']):
                logger.warning(f"[{task_id}] Text quality validation failed for document {document_id}, proceeding with caution")
            
            try:
                document.processing_message = "Analyzing document with AI..."
                document.save(update_fields=['processing_message'])
                
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
                
                # PERFORMANCE OPTIMIZATION: Choose processing strategy based on size
                if text_length > chunk_threshold:
                    logger.info(f"[{task_id}] Large document detected ({text_length} chars), chunking for efficiency")
                    
                    # For very large documents, use direct AI extraction with chunking
                    from apps.documents.services.ai_extraction import extract_medical_data_structured
                    
                    chunks = document_chunker.chunk_text(extracted_text, preserve_context=True)
                    
                    if len(chunks) > 1:
                        # Process in chunks and aggregate
                        all_chunk_data = []
                        for chunk in chunks:
                            chunk_result = extract_medical_data_structured(chunk['text'], context=context)
                            all_chunk_data.append(chunk_result.model_dump())
                        
                        # Aggregate results
                        structured_extraction = _aggregate_chunked_extractions(all_chunk_data)
                        logger.info(f"[{task_id}] Chunked processing completed: {len(chunks)} chunks processed")
                    else:
                        # Single chunk, process normally
                        structured_extraction = ai_analyzer.analyze_document_structured(
                            document_content=extracted_text,
                            context=context
                        )
                else:
                    logger.info(f"[{task_id}] Standard size document, using optimized single processing")
                
                # NEW: Use structured extraction pipeline
                try:
                    if not structured_extraction:  # Only run if not already processed above
                        logger.info(f"Attempting structured extraction for document {document_id}")
                        structured_extraction = ai_analyzer.analyze_document_structured(
                            document_content=extraction_result['text'],
                            context=context
                        )
                    
                    # PORTHOLE: Capture LLM structured output
                    capture_llm_output(
                        document_id=document_id,
                        llm_response=structured_extraction,
                        llm_type="structured_extraction_claude",
                        success=bool(structured_extraction)
                    )
                    
                    if structured_extraction:
                        # VALIDATION: Check structured extraction quality
                        if not validate_after_ai_extraction(document, structured_extraction):
                            logger.warning(f"[{task_id}] Structured extraction validation failed for document {document_id}, proceeding with caution")
                        
                        # Convert structured data to legacy format for backward compatibility
                        ai_result = {
                            'success': True,
                            'fields': [
                                # Convert conditions (with null safety for source)
                                *[{
                                    'label': f'diagnosis_{i+1}',
                                    'value': condition.name,
                                    'confidence': condition.confidence,
                                    'source_text': condition.source.text if condition.source else '',
                                    'char_position': condition.source.start_index if condition.source else 0
                                } for i, condition in enumerate(structured_extraction.conditions)],
                                
                                # Convert medications (with null safety for source)
                                *[{
                                    'label': f'medication_{i+1}',
                                    'value': f"{medication.name} {medication.dosage or ''}".strip(),
                                    'confidence': medication.confidence,
                                    'source_text': medication.source.text if medication.source else '',
                                    'char_position': medication.source.start_index if medication.source else 0
                                } for i, medication in enumerate(structured_extraction.medications)],
                                
                                # Convert vital signs (with null safety for source)
                                *[{
                                    'label': f'vital_{vital.measurement.lower().replace(" ", "_")}',
                                    'value': f"{vital.value} {vital.unit or ''}".strip(),
                                    'confidence': vital.confidence,
                                    'source_text': vital.source.text if vital.source else '',
                                    'char_position': vital.source.start_index if vital.source else 0
                                } for vital in structured_extraction.vital_signs],
                                
                                # Convert lab results (with null safety for source)
                                *[{
                                    'label': f'lab_{lab.test_name.lower().replace(" ", "_")}',
                                    'value': f"{lab.value} {lab.unit or ''}".strip(),
                                    'confidence': lab.confidence,
                                    'source_text': lab.source.text if lab.source else '',
                                    'char_position': lab.source.start_index if lab.source else 0
                                } for lab in structured_extraction.lab_results]
                            ],
                            'model_used': 'structured_extraction_claude',
                            'processing_method': 'structured_pydantic',
                            'usage': {
                                'total_tokens': 0,  # Will be updated if available
                            },
                            'processing_duration_ms': 0,  # Will be updated if available
                            # NOTE: Do NOT store Pydantic model here - Celery cannot serialize it
                            # Structured data is serialized at line 697 using .dict() for storage
                        }
                        
                        logger.info(f"Structured extraction successful: {len(ai_result['fields'])} fields extracted from structured data")
                    
                except Exception as structured_exc:
                    logger.error(f"Structured extraction failed for document {document_id}: {structured_exc}")
                    
                    # PORTHOLE: Capture extraction error
                    capture_pipeline_error(
                        document_id=document_id,
                        stage="structured_extraction",
                        error_message=str(structured_exc),
                        error_data={
                            'context': context,
                            'text_length': len(extraction_result['text'])
                        }
                    )
                    
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
                    document.processing_message = "Converting to FHIR format..."
                    document.save(update_fields=['processing_message'])
                    
                    logger.info(f"AI analysis successful: {len(ai_result['fields'])} fields extracted")
                    
                    # STEP 3: Convert to FHIR format using appropriate converter
                    patient_id = str(document.patient.id) if document.patient else None
                    
                    # Task 35.7: Retrieve existing ParsedData for clinical date lookup
                    parsed_data_for_dates = None
                    try:
                        from apps.documents.models import ParsedData
                        parsed_data_for_dates = ParsedData.objects.filter(document=document).first()
                        if parsed_data_for_dates and parsed_data_for_dates.has_clinical_date():
                            logger.info(f"Found existing ParsedData with clinical_date: {parsed_data_for_dates.clinical_date}")
                        else:
                            logger.debug(f"No existing ParsedData with clinical_date found for document {document.id}")
                    except Exception as pd_lookup_exc:
                        logger.warning(f"Could not look up ParsedData for clinical date: {pd_lookup_exc}")
                    
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
                            
                            # Task 35.7: Pass ParsedData to converter for clinical date integration
                            fhir_resources = structured_converter.convert_structured_data(
                                structured_extraction, 
                                conversion_metadata, 
                                document.patient,
                                parsed_data=parsed_data_for_dates
                            )
                            
                            logger.info(f"StructuredDataConverter created {len(fhir_resources)} resources from structured data")
                            
                            # PORTHOLE: Capture FHIR conversion output from StructuredDataConverter
                            # Note: Resources are still Pydantic models at this point, will be serialized later
                            try:
                                # Serialize for porthole capture (same logic as main serialization)
                                porthole_resources = []
                                for resource in fhir_resources:
                                    if hasattr(resource, 'dict'):
                                        porthole_resources.append(json.loads(json.dumps(resource.dict(exclude_none=True), default=str)))
                                    elif hasattr(resource, 'model_dump'):
                                        porthole_resources.append(json.loads(json.dumps(resource.model_dump(exclude_none=True), default=str)))
                                    elif isinstance(resource, dict):
                                        porthole_resources.append(json.loads(json.dumps(resource, default=str)))
                                
                                capture_fhir_data(
                                    document_id=document_id,
                                    fhir_resources=porthole_resources,
                                    patient_id=patient_id,
                                    stage="structured_fhir_conversion"
                                )
                            except Exception as porthole_exc:
                                logger.warning(f"Porthole FHIR capture failed (non-critical): {porthole_exc}")
                            
                        except Exception as struct_conv_exc:
                            logger.warning(f"StructuredDataConverter failed, falling back to legacy: {struct_conv_exc}")
                            structured_extraction = None  # Clear to trigger fallback
                    
                    # FALLBACK: Use legacy FHIR processor if structured conversion failed or not available
                    if not structured_extraction:
                        try:
                            from apps.fhir.services import FHIRProcessor, FHIRMetricsService
                            
                            # Pass structured data in format FHIRProcessor already supports
                            extracted_data = {
                                'fields': ai_result['fields'],
                                'patient_id': patient_id
                            }
                            
                            fhir_processor = FHIRProcessor()
                            fhir_resources = fhir_processor.process_extracted_data(extracted_data, patient_id)
                            
                            # PORTHOLE: Capture FHIR conversion output
                            capture_fhir_data(
                                document_id=document_id,
                                fhir_resources=fhir_resources,
                                patient_id=patient_id,
                                stage="fhir_conversion"
                            )
                            
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
                            ai_result.get('fields', []), fhir_resources
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
                            structured_data_dict = structured_extraction.model_dump()
                        
                        # Serialize FHIR resources to JSON-compatible dicts
                        # StructuredDataConverter returns FHIR resource models that need serialization
                        serialized_fhir_resources = []
                        if fhir_resources:
                            logger.info(f"Starting serialization of {len(fhir_resources)} FHIR resources for document {document_id}")
                            for i, resource in enumerate(fhir_resources):
                                try:
                                    # Log the resource type for debugging
                                    logger.debug(f"Serializing resource #{i+1}, type: {type(resource).__name__}")
                                    
                                    if hasattr(resource, 'dict'):
                                        # FHIR resource model (fhir.resources) - serialize it
                                        # Use exclude_none=True to remove null fields and reduce size
                                        resource_dict = resource.dict(exclude_none=True)
                                        # Convert datetime objects to ISO format strings for JSON compatibility
                                        serialized_fhir_resources.append(json.loads(json.dumps(resource_dict, default=str)))
                                    elif hasattr(resource, 'model_dump'):
                                        # Pydantic v2 model - serialize it
                                        resource_dict = resource.model_dump(exclude_none=True)
                                        serialized_fhir_resources.append(json.loads(json.dumps(resource_dict, default=str)))
                                    elif isinstance(resource, dict):
                                        # Already a dict - ensure JSON compatibility
                                        serialized_fhir_resources.append(json.loads(json.dumps(resource, default=str)))
                                    else:
                                        # Unknown type - log warning and skip
                                        logger.warning(f"Unexpected FHIR resource type: {type(resource)}, skipping serialization")
                                except Exception:
                                    # Use logger.exception to capture full traceback
                                    logger.exception(f"Failed to serialize FHIR resource #{i+1} of type {type(resource)}")
                                    # Continue with other resources
                            
                            logger.info(f"Successfully serialized {len(serialized_fhir_resources)}/{len(fhir_resources)} FHIR resources for document {document_id}")
                        
                        parsed_data, created = ParsedData.objects.update_or_create(
                            document=document,
                            defaults={
                                'patient': document.patient,
                                'extraction_json': fields_data,
                                'source_snippets': snippets_data,  # Store snippet data in new field
                                'fhir_delta_json': serialized_fhir_resources if serialized_fhir_resources else {},
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
                        
                        # Task 41.13: Determine review status and merge immediately (optimistic concurrency)
                        try:
                            logger.info(f"[{task_id}] Determining review status for ParsedData {parsed_data.id}")
                            
                            # Determine if data should be auto-approved or flagged
                            review_status, flag_reason = parsed_data.determine_review_status()
                            
                            # Update ParsedData with review status
                            parsed_data.review_status = review_status
                            parsed_data.auto_approved = (review_status == 'auto_approved')
                            parsed_data.flag_reason = flag_reason
                            parsed_data.save(update_fields=['review_status', 'auto_approved', 'flag_reason'])
                            
                            logger.info(
                                f"[{task_id}] Review status determined: {review_status} "
                                f"{'(auto-approved)' if parsed_data.auto_approved else f'(flagged: {flag_reason})'}"
                            )
                            
                            # Immediately merge data into patient record regardless of review status
                            # This is the core of optimistic concurrency: merge now, review later if needed
                            if serialized_fhir_resources:
                                logger.info(
                                    f"[{task_id}] Merging {len(serialized_fhir_resources)} FHIR resources "
                                    f"into patient {document.patient.mrn} record (optimistic merge)"
                                )
                                
                                # Merge using patient's add_fhir_resources method
                                merge_success = document.patient.add_fhir_resources(
                                    serialized_fhir_resources,
                                    document_id=document.id
                                )
                                
                                if merge_success:
                                    # Mark ParsedData as merged
                                    parsed_data.is_merged = True
                                    parsed_data.merged_at = timezone.now()
                                    parsed_data.save(update_fields=['is_merged', 'merged_at'])
                                    
                                    logger.info(
                                        f"[{task_id}] Successfully merged {len(serialized_fhir_resources)} "
                                        f"resources into patient {document.patient.mrn}"
                                    )
                                else:
                                    logger.error(
                                        f"[{task_id}] Failed to merge FHIR resources into patient record "
                                        f"for document {document_id}"
                                    )
                            else:
                                logger.warning(
                                    f"[{task_id}] No FHIR resources to merge for document {document_id}"
                                )
                                
                        except FHIRConversionError as fhir_merge_error:
                            # Specific handling for FHIR conversion errors during merge
                            error_info = fhir_merge_error.to_dict()
                            processing_errors.append(str(fhir_merge_error))
                            recovery_actions.append(get_recovery_strategy(fhir_merge_error.error_code))
                            
                            logger.error(
                                f"[{task_id}] FHIR conversion error during merge: {fhir_merge_error}",
                                extra={
                                    'document_id': document_id,
                                    'parsed_data_id': parsed_data.id,
                                    'error_code': fhir_merge_error.error_code,
                                    'error_details': fhir_merge_error.details
                                }
                            )
                            # Don't fail the entire task - data is still saved in ParsedData
                            # It can be merged later manually or via retry
                            
                        except DataValidationError as validation_error:
                            # Specific handling for data validation errors during merge
                            error_info = validation_error.to_dict()
                            processing_errors.append(str(validation_error))
                            recovery_actions.append(get_recovery_strategy(validation_error.error_code))
                            
                            logger.error(
                                f"[{task_id}] Data validation error during merge: {validation_error}",
                                extra={
                                    'document_id': document_id,
                                    'parsed_data_id': parsed_data.id,
                                    'error_code': validation_error.error_code,
                                    'error_details': validation_error.details
                                }
                            )
                            # Don't fail the entire task - data is still saved in ParsedData
                            # It can be merged later manually or via retry
                            
                        except Exception as merge_exc:
                            # Categorize unexpected errors
                            error_info = categorize_exception(merge_exc)
                            processing_errors.append(str(merge_exc))
                            recovery_actions.append(get_recovery_strategy(error_info['error_code']))
                            
                            logger.error(
                                f"[{task_id}] Unexpected error during review status determination or immediate merge: {merge_exc}",
                                exc_info=True,
                                extra={
                                    'document_id': document_id,
                                    'parsed_data_id': parsed_data.id if parsed_data else None,
                                    'error_category': error_info['error_code'],
                                    'recovery_strategy': error_info.get('recovery_strategy')
                                }
                            )
                            # Don't fail the entire task - data is still saved in ParsedData
                            # It can be merged later manually or via retry
                        
                    except DataValidationError as validation_exc:
                        # Specific handling for data validation errors during ParsedData creation
                        error_info = validation_exc.to_dict()
                        processing_errors.append(f"ParsedData validation error: {str(validation_exc)}")
                        recovery_actions.append(get_recovery_strategy(validation_exc.error_code))
                        
                        logger.error(
                            f"[{task_id}] Data validation error creating ParsedData for document {document_id}: {validation_exc}",
                            extra={
                                'document_id': document_id,
                                'error_code': validation_exc.error_code,
                                'error_details': validation_exc.details
                            }
                        )
                        # Don't fail the task - processing was successful, just data storage failed
                        
                    except Exception as pd_exc:
                        # Categorize unexpected ParsedData errors
                        error_info = categorize_exception(pd_exc)
                        processing_errors.append(f"ParsedData creation error: {str(pd_exc)}")
                        recovery_actions.append(get_recovery_strategy(error_info['error_code']))
                        
                        logger.error(
                            f"[{task_id}] Failed to save ParsedData for document {document_id}: {pd_exc}",
                            exc_info=True,
                            extra={
                                'document_id': document_id,
                                'error_category': error_info['error_code'],
                                'error_details': error_info.get('details', {})
                            }
                        )
                        # Don't fail the task - processing was successful, just data storage failed
                    
                else:
                    logger.warning(f"AI analysis failed for document {document_id}: {ai_result.get('error', 'Unknown error')}")
                    # Don't fail the entire task if AI fails - PDF extraction was successful
                    
            except AIExtractionError as ai_exc:
                # Specific handling for AI extraction errors
                error_info = ai_exc.to_dict()
                processing_errors.append(str(ai_exc))
                recovery_actions.append(get_recovery_strategy(ai_exc.error_code))
                
                logger.warning(
                    f"[{task_id}] AI extraction error for document {document_id}: {ai_exc}",
                    extra={
                        'document_id': document_id,
                        'error_code': ai_exc.error_code,
                        'error_details': ai_exc.details
                    }
                )
                
                # Continue processing even if AI fails - we still have the extracted text
                ai_result = {
                    'success': False,
                    'error': str(ai_exc),
                    'error_code': ai_exc.error_code,
                    'fields': []
                }
                
            except Exception as ai_exc:
                # Categorize unexpected AI errors
                error_info = categorize_exception(ai_exc)
                processing_errors.append(f"AI analysis error: {str(ai_exc)}")
                recovery_actions.append(get_recovery_strategy(error_info['error_code']))
                
                logger.warning(
                    f"[{task_id}] Unexpected AI analysis error for document {document_id}: {ai_exc}",
                    exc_info=True,
                    extra={
                        'document_id': document_id,
                        'error_category': error_info['error_code'],
                        'error_details': error_info.get('details', {})
                    }
                )
                
                # Continue processing even if AI fails - we still have the extracted text
                ai_result = {
                    'success': False,
                    'error': str(ai_exc),
                    'error_code': error_info['error_code'],
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
        
        # Task 41.13: Set document status based on review status AND merge status
        # Critical: A document is only truly "completed" if the merge succeeded
        try:
            # Get the ParsedData to check review status and merge status
            from .models import ParsedData
            parsed_data = ParsedData.objects.filter(document=document).first()
            
            if not parsed_data:
                # No ParsedData at all - something went wrong
                document.status = 'failed'
                document.processing_message = "Processing failed - no parsed data created"
                logger.error(f"[{task_id}] Document {document_id} has no ParsedData record")
            elif not parsed_data.is_merged:
                # CRITICAL: Data was extracted but NOT merged into patient record
                # This is a partial failure - data exists but isn't in the patient's bundle
                document.status = 'failed'
                document.processing_message = (
                    f"Merge failed - data extracted but not merged to patient record. "
                    f"Review status: {parsed_data.review_status}. "
                    f"ParsedData ID: {parsed_data.id} contains the extracted data."
                )
                logger.error(
                    f"[{task_id}] Document {document_id} MERGE FAILED - is_merged=False. "
                    f"ParsedData {parsed_data.id} has {len(parsed_data.fhir_delta_json or [])} resources waiting to merge."
                )
            elif parsed_data.auto_approved:
                # High quality extraction AND successfully merged - mark as completed
                document.status = 'completed'
                document.processing_message = "Processing completed - data auto-approved and merged"
                logger.info(f"[{task_id}] Document {document_id} auto-approved and completed")
            elif parsed_data.review_status == 'flagged':
                # Lower quality or conflicts - but data IS merged, just needs review
                document.status = 'review'
                document.processing_message = f"Merged with flags - review recommended: {parsed_data.flag_reason[:100] if parsed_data.flag_reason else 'Unknown'}"
                logger.info(f"[{task_id}] Document {document_id} flagged for review: {parsed_data.flag_reason}")
            else:
                # Fallback for unexpected states
                document.status = 'review'
                document.processing_message = "Processing completed - review recommended"
                logger.warning(f"[{task_id}] Document {document_id} in unexpected state, defaulting to review")
                
        except Exception as status_exc:
            # Categorize status update error
            error_info = categorize_exception(status_exc)
            processing_errors.append(f"Status update error: {str(status_exc)}")
            
            logger.error(
                f"[{task_id}] Error setting document status: {status_exc}",
                extra={
                    'document_id': document_id,
                    'error_category': error_info['error_code'],
                    'error_details': error_info.get('details', {})
                }
            )
            
            # Fallback to review status on error
            try:
                document.status = 'review'
                document.processing_message = "Processing completed - review recommended (status update failed)"
                document.save(update_fields=['status', 'processing_message'])
            except Exception as fallback_error:
                logger.critical(
                    f"[{task_id}] Critical: Failed to set fallback status for document {document_id}: {fallback_error}"
                )
        
        document.processed_at = timezone.now()
        document.error_message = ''
        document.save()
        
        logger.info(f"Document {document_id} processed successfully - status: {document.status}")
        
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
        # Categorize the error for better handling
        error_info = categorize_exception(exc)
        error_code = error_info.get('error_code', 'UNKNOWN_ERROR')
        recovery_strategy = get_recovery_strategy(error_code)
        
        # Calculate total processing time
        total_time = time.time() - start_time
        
        # Enhanced error logging with structured data
        logger.error(
            f"[{task_id}] Document processing failed for {document_id}: {exc}",
            exc_info=True,
            extra={
                'document_id': document_id,
                'task_id': task_id,
                'error_category': error_code,
                'error_type': error_info.get('error_type'),
                'recovery_strategy': recovery_strategy,
                'processing_time': total_time,
                'processing_errors': processing_errors,
                'recovery_actions': recovery_actions
            }
        )
        
        # Attempt to update document status with detailed error information
        try:
            document = Document.objects.get(id=document_id)
            document.status = 'failed'
            document.error_message = f"[{error_code}] {str(exc)[:500]}"  # Truncate long messages
            document.processed_at = timezone.now()
            document.save()
            
            logger.info(f"[{task_id}] Updated document {document_id} status to 'failed'")
            
        except Exception as status_update_error:
            # Critical: If we can't even update the document, log it with high severity
            logger.critical(
                f"[{task_id}] CRITICAL: Failed to update document {document_id} status after error: {status_update_error}",
                extra={
                    'document_id': document_id,
                    'original_error': str(exc),
                    'status_update_error': str(status_update_error)
                }
            )
        
        # Determine if error is retryable based on error category
        retryable_errors = [
            'AI_SERVICE_TIMEOUT',
            'AI_SERVICE_RATE_LIMIT', 
            'EXTERNAL_SERVICE_ERROR',
            'AI_EXTRACTION_ERROR'
        ]
        
        is_retryable = error_code in retryable_errors
        
        # Check if we can retry the processing
        try:
            can_retry = document.can_retry_processing() if hasattr(document, 'can_retry_processing') else False
        except:
            can_retry = False
        
        # Retry logic with categorization
        if is_retryable and can_retry:
            # Determine retry delay based on error type
            retry_delays = {
                'AI_SERVICE_RATE_LIMIT': 120,  # 2 minutes
                'AI_SERVICE_TIMEOUT': 60,       # 1 minute
                'EXTERNAL_SERVICE_ERROR': 180,  # 3 minutes
                'AI_EXTRACTION_ERROR': 300      # 5 minutes
            }
            retry_delay = retry_delays.get(error_code, 300)
            
            logger.info(
                f"[{task_id}] Retrying document {document_id} processing "
                f"(attempt {document.processing_attempts}, delay: {retry_delay}s, reason: {error_code})"
            )
            
            raise self.retry(exc=exc, countdown=retry_delay, max_retries=3)
        else:
            # Log why we're not retrying
            retry_reason = "not retryable" if not is_retryable else "max retries exceeded"
            logger.error(
                f"[{task_id}] Document {document_id} processing failed permanently ({retry_reason})"
            )
            
            # Return detailed failure information
            return {
                'success': False,
                'document_id': document_id,
                'status': 'failed',
                'task_id': task_id,
                'error_type': error_info.get('error_type'),
                'error_code': error_code,
                'error_message': str(exc),
                'error_details': error_info.get('details', {}),
                'recovery_strategy': recovery_strategy,
                'processing_time': total_time,
                'processing_errors': processing_errors,
                'recovery_actions': recovery_actions,
                'retry_reason': retry_reason,
                'message': f'Document processing failed permanently: {str(exc)[:200]}'
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


def _aggregate_chunked_extractions(chunk_results: List[Dict]) -> 'StructuredMedicalExtraction':
    """
    Aggregate multiple chunk extraction results into a single StructuredMedicalExtraction.
    
    Args:
        chunk_results: List of extraction results from document chunks
        
    Returns:
        Aggregated StructuredMedicalExtraction object
    """
    from apps.documents.services.ai_extraction import StructuredMedicalExtraction
    from collections import defaultdict
    from difflib import SequenceMatcher
    
    # Initialize aggregated data
    aggregated = {
        'conditions': [],
        'medications': [],
        'vital_signs': [],
        'lab_results': [],
        'procedures': [],
        'providers': [],
        'extraction_timestamp': timezone.now().isoformat(),
        'document_type': 'chunked_document'
    }
    
    # Collect all items from chunks
    for chunk_result in chunk_results:
        if chunk_result and isinstance(chunk_result, dict):
            for key in ['conditions', 'medications', 'vital_signs', 'lab_results', 'procedures', 'providers']:
                if key in chunk_result:
                    aggregated[key].extend(chunk_result[key])
    
    # Deduplicate similar items using fuzzy matching
    def is_similar(a: str, b: str, threshold: float = 0.85) -> bool:
        """Check if two medical terms are similar enough to be duplicates."""
        return SequenceMatcher(None, a.lower(), b.lower()).ratio() > threshold
    
    for data_type in ['conditions', 'medications', 'procedures']:
        if data_type in aggregated:
            items = aggregated[data_type]
            deduplicated = []
            
            for item in items:
                # Extract name for comparison
                item_name = item.get('name', str(item)) if isinstance(item, dict) else str(item)
                
                # Check if similar item already exists
                is_duplicate = False
                for existing in deduplicated:
                    existing_name = existing.get('name', str(existing)) if isinstance(existing, dict) else str(existing)
                    if is_similar(item_name, existing_name):
                        # Keep the item with higher confidence if available
                        if isinstance(item, dict) and isinstance(existing, dict):
                            if item.get('confidence', 0) > existing.get('confidence', 0):
                                # Replace existing with higher confidence item
                                idx = deduplicated.index(existing)
                                deduplicated[idx] = item
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    deduplicated.append(item)
            
            logger.info(f"Deduplicated {data_type}: {len(items)} -> {len(deduplicated)} items")
            aggregated[data_type] = deduplicated
    
    # Create and return StructuredMedicalExtraction object
    return StructuredMedicalExtraction.model_validate(aggregated) 