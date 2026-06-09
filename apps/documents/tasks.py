"""
Celery tasks for document processing.
Handles async document parsing and FHIR data extraction.

Enhanced with comprehensive error handling and logging for Task 34.5.
Memory optimizations added for large document processing (OOM fix).
"""

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from meddocparser.celery import app
import time
import logging
import json
import gc
import uuid
from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone
from typing import Dict, Any, List, Optional


def force_memory_cleanup(context: str = "unknown"):
    """
    Force garbage collection to free memory.
    
    Call this between major processing steps to prevent memory accumulation,
    especially important for large documents where multiple copies of data
    exist simultaneously.
    
    Args:
        context: Description of when/why cleanup is happening for logging
    """
    collected = gc.collect()
    if collected > 0:
        logger.debug(f"[Memory cleanup - {context}] Collected {collected} objects")


def _coerce_iso_date(raw_date):
    """
    Coerce a possibly-partial date string into a full YYYY-MM-DD string for storage.

    ParsedData.clinical_date is a DateField and therefore requires a full calendar date.
    Partial dates (year, year-month) are padded to the first day SOLELY for this single
    sortable/storable field; the original precision is preserved untouched in the FHIR
    resources and structured extraction data.

    Args:
        raw_date: A date string in YYYY, YYYY-MM, or YYYY-MM-DD form (other formats ignored).

    Returns:
        A 'YYYY-MM-DD' string, or None if the input could not be interpreted.
    """
    import re

    if not raw_date or not isinstance(raw_date, str):
        return None

    candidate = raw_date.strip()[:10]

    if re.match(r'^\d{4}-\d{2}-\d{2}$', candidate):
        return candidate
    if re.match(r'^\d{4}-\d{2}$', candidate):
        return f"{candidate}-01"
    if re.match(r'^\d{4}$', candidate):
        return f"{candidate}-01-01"
    return None


def derive_clinical_date(structured_data, fhir_resources):
    """
    Derive a single clinical date for a document from already-serialized extraction data.

    Both inputs are plain JSON-compatible structures (the Pydantic model and fhir.resources
    objects have already been serialized at the call sites), so this function never touches
    live model objects.

    Priority order:
        1. AI-provided top-level clinical_date
        2. Earliest encounter date (structured encounters, then FHIR Encounter.period.start)
        3. Earliest dated clinical item (lab test_date, procedure_date, vital timestamp)

    Args:
        structured_data: dict dump of StructuredMedicalExtraction (or None).
        fhir_resources: flat list of serialized FHIR resource dicts (or None).

    Returns:
        (iso_date_str, source_label) where iso_date_str is 'YYYY-MM-DD' (or None) and
        source_label describes where the date came from (or None).
    """
    structured_data = structured_data or {}
    fhir_resources = fhir_resources or []

    # Priority 1: explicit AI-provided clinical date
    iso = _coerce_iso_date(structured_data.get('clinical_date'))
    if iso:
        return iso, 'ai_clinical_date'

    # Priority 2a: earliest encounter date from structured extraction
    encounter_dates = [
        iso for enc in (structured_data.get('encounters') or [])
        if isinstance(enc, dict) and (iso := _coerce_iso_date(enc.get('encounter_date')))
    ]
    if encounter_dates:
        return min(encounter_dates), 'encounter'

    # Priority 2b: earliest Encounter.period.start from the flat FHIR resource list
    fhir_encounter_dates = []
    for resource in fhir_resources:
        if isinstance(resource, dict) and resource.get('resourceType') == 'Encounter':
            period = resource.get('period') or {}
            iso = _coerce_iso_date(period.get('start'))
            if iso:
                fhir_encounter_dates.append(iso)
    if fhir_encounter_dates:
        return min(fhir_encounter_dates), 'fhir_encounter'

    # Priority 3: earliest dated clinical item from structured extraction
    clinical_item_dates = []
    for lab in (structured_data.get('lab_results') or []):
        if isinstance(lab, dict) and (iso := _coerce_iso_date(lab.get('test_date'))):
            clinical_item_dates.append(iso)
    for proc in (structured_data.get('procedures') or []):
        if isinstance(proc, dict) and (iso := _coerce_iso_date(proc.get('procedure_date'))):
            clinical_item_dates.append(iso)
    for vital in (structured_data.get('vital_signs') or []):
        if isinstance(vital, dict) and (iso := _coerce_iso_date(vital.get('timestamp'))):
            clinical_item_dates.append(iso)
    if clinical_item_dates:
        return min(clinical_item_dates), 'clinical_item'

    return None, None


def _build_clinical_date_defaults(structured_data, fhir_resources):
    """
    Build the ParsedData date fields for an update_or_create defaults dict.

    Returns an empty dict when no date could be derived (so we never stamp
    date_source='extracted' on a record that has no clinical_date).
    """
    from datetime import datetime as _datetime

    iso_date, source_label = derive_clinical_date(structured_data, fhir_resources)
    if not iso_date:
        return {}

    try:
        parsed = _datetime.strptime(iso_date, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        logger.warning(f"derive_clinical_date produced unparseable date '{iso_date}'")
        return {}

    logger.info(f"Derived clinical_date {parsed.isoformat()} (source: {source_label})")
    return {
        'clinical_date': parsed,
        'date_source': 'extracted',
        'date_status': 'pending',
    }


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


def _get_processing_session_id(task_id: str):
    """Return a UUID for API usage logging from a Celery task id."""
    try:
        return uuid.UUID(str(task_id))
    except (ValueError, AttributeError, TypeError):
        return uuid.uuid4()


def _textract_mode_to_model(mode: Optional[str]) -> str:
    """Map Textract mode/job_type to APIUsageLog model identifier."""
    mode_key = (mode or getattr(settings, 'TEXTRACT_MODE', 'detect') or 'detect').lower()
    if mode_key in ('analyze', 'start_document_analysis'):
        return 'analyze_document'
    return 'detect_document_text'


def _log_textract_usage(document, textract_metadata, session_id, textract_mode=None):
    """Persist Textract OCR cost/usage after sync or async OCR completes."""
    if not textract_metadata:
        return

    page_count = textract_metadata.get('page_count', 0)
    if not page_count:
        return

    from apps.core.services import APIUsageMonitor

    extraction_time_ms = textract_metadata.get('extraction_time_ms', 0) or 0
    end_time = timezone.now()
    start_time = end_time - timedelta(milliseconds=extraction_time_ms)

    try:
        APIUsageMonitor.log_textract_usage(
            document=document,
            patient=getattr(document, 'patient', None),
            session_id=session_id,
            mode=_textract_mode_to_model(textract_mode),
            page_count=page_count,
            start_time=start_time,
            end_time=end_time,
            success=True,
        )
    except Exception as log_error:
        logger.warning(f"Failed to log Textract usage for document {document.id}: {log_error}")


def _save_document_stage_timing(document, **timing_fields):
    """Persist per-stage timing metrics without overwriting unrelated fields."""
    if not timing_fields:
        return
    for field_name, value in timing_fields.items():
        setattr(document, field_name, value)
    document.save(update_fields=list(timing_fields.keys()))


def _compute_queue_wait_ms(document) -> Optional[int]:
    """Calculate queue wait time from upload to processing start."""
    if not document.uploaded_at or not document.processing_started_at:
        return None
    delta = document.processing_started_at - document.uploaded_at
    return max(int(delta.total_seconds() * 1000), 0)


def _notify_monitor_stage(document) -> None:
    """Publish document stage updates for the admin monitor dashboard."""
    try:
        from apps.core.monitor_service import PipelineMetricsService

        PipelineMetricsService.publish_document_stage(document)
    except Exception as notify_error:
        logger.debug(
            "Monitor stage notification skipped for document %s: %s",
            document.id,
            notify_error,
        )


def _field_label_to_category(label: str) -> str:
    """
    Map legacy flat AI field labels to FHIRMetricsService category keys.

    Structured extraction builds labels like ``diagnosis_1``, ``medication_2``,
    ``vital_*``, ``lab_*``; metrics expects dict keys matching category_mappings
    in apps.fhir.services.metrics_service (e.g. ``conditions``, ``medications``).
    """
    if not label or not isinstance(label, str):
        return 'other_fields'
    lower = label.lower()
    if lower.startswith('diagnosis_'):
        return 'conditions'
    if lower.startswith('medication_'):
        return 'medications'
    if lower.startswith('vital_'):
        return 'vital_signs'
    if lower.startswith('lab_'):
        return 'lab_results'
    if lower.startswith('procedure_'):
        return 'procedures'
    if lower.startswith('provider_'):
        return 'providers'
    return 'other_fields'


def _group_ai_fields_for_metrics(
    fields: Optional[List[Dict[str, Any]]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Group flat ``fields`` list into category dict for calculate_data_capture_metrics."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    if not fields:
        return grouped
    for field in fields:
        if not isinstance(field, dict):
            continue
        label = field.get('label', '') or ''
        category = _field_label_to_category(str(label))
        grouped.setdefault(category, []).append(field)
    return grouped


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
             retry_kwargs={'max_retries': 3, 'countdown': 60},
             time_limit=getattr(settings, 'LARGE_DOCUMENT_TASK_TIME_LIMIT', 2100),
             soft_time_limit=getattr(settings, 'LARGE_DOCUMENT_TASK_SOFT_TIME_LIMIT', 1800))
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
            queue_wait_ms = _compute_queue_wait_ms(document)
            if queue_wait_ms is not None:
                document.queue_wait_time_ms = queue_wait_ms
            document.save()
            
            logger.info(f"[{task_id}] Document status updated to processing (attempt #{document.processing_attempts})")
            _notify_monitor_stage(document)
            
        except Exception as e:
            logger.error(f"[{task_id}] Failed to update document status: {e}")
            # Continue processing despite status update failure
            
        # STEP 1: Enhanced PDF text extraction with detailed error handling
        document.processing_message = "Extracting text from PDF..."
        document.save(update_fields=['processing_message'])
        _notify_monitor_stage(document)
        
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
            
            # ASYNC OCR HANDOFF: If document needs async Textract (multi-page scanned PDF),
            # trigger the async Textract chain and return early. The chain will:
            #   start_textract_async_job → poll_textract_job → continue_document_processing
            if extraction_result.get('ocr_pending'):
                page_count_info = extraction_result.get('page_count', 0)
                image_pages_info = extraction_result.get('metadata', {}).get('image_pages', [])
                
                logger.info(
                    f"[{task_id}] Document {document_id} requires async Textract OCR "
                    f"({page_count_info} pages, {len(image_pages_info)} image pages). "
                    f"Handing off to async Textract chain."
                )
                
                # Update document status to reflect OCR pending
                document.status = 'ocr_pending'
                document.processing_message = (
                    f"Document has {page_count_info} scanned pages. "
                    f"Sending to AWS Textract for OCR processing..."
                )
                document.save(update_fields=['status', 'processing_message'])
                _notify_monitor_stage(document)
                
                # Trigger the async Textract chain (already built in 42.10/42.11/42.12)
                from .tasks import start_textract_async_job
                start_textract_async_job.delay(document_id)
                
                logger.info(
                    f"[{task_id}] Async Textract job queued for document {document_id}. "
                    f"This task is complete; processing continues via async chain."
                )
                
                return {
                    'success': True,
                    'document_id': document_id,
                    'status': 'ocr_pending',
                    'task_id': task_id,
                    'message': f'Document handed off to async Textract OCR ({page_count_info} pages)',
                    'processing_time': time.time() - start_time,
                }
            
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

            _save_document_stage_timing(
                document,
                pdf_extraction_time_ms=int(pdf_step_time * 1000),
            )
            _notify_monitor_stage(document)

            textract_metadata = extraction_result.get('metadata', {}).get('textract_metadata')
            if textract_metadata:
                _log_textract_usage(
                    document,
                    textract_metadata,
                    _get_processing_session_id(task_id),
                )
            
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
        
        # MEMORY FIX: extraction_result holds the full text duplicated with extracted_text
        # Keep only metadata we need for final result reporting
        extraction_result_meta = {
            'success': extraction_result['success'],
            'text_length': text_length,
            'page_count': extraction_result['page_count'],
            'file_size': extraction_result.get('file_size', 0),
            'metadata': extraction_result.get('metadata', {}),
        }
        del extraction_result
        force_memory_cleanup("after extraction_result cleanup")
        
        logger.info(f"[{task_id}] Document size: {text_length} chars (threshold: {chunk_threshold})")

        size_failure = _check_document_text_size_limit(document, text_length, task_id)
        if size_failure:
            return size_failure
        
        # STEP 2: Analyze document with AI using size-appropriate strategy
        ai_result = None
        structured_extraction = None
        chunk_stats = None
        if extracted_text.strip():
            # VALIDATION: Check text quality before AI extraction
            if not validate_before_ai_extraction(document, extracted_text):
                logger.warning(f"[{task_id}] Text quality validation failed for document {document_id}, proceeding with caution")
            
            try:
                document.processing_message = "Analyzing document with AI..."
                document.save(update_fields=['processing_message'])
                _notify_monitor_stage(document)
                
                logger.info(f"Step 2: Starting AI analysis with structured extraction pipeline for document {document_id}")
                
                ai_step_start = time.time()
                
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
                    
                    chunks = document_chunker.chunk_text(extracted_text, preserve_context=True)
                    chunk_failure = _check_document_chunk_limit(document, len(chunks), task_id)
                    if chunk_failure:
                        return chunk_failure
                    
                    if len(chunks) > 1:
                        total_chunks = len(chunks)
                        structured_extraction, chunk_stats = _process_chunks_streaming(
                            chunks, context, task_id, document=document
                        )
                        force_memory_cleanup("after chunk aggregation")
                        logger.info(
                            f"[{task_id}] Chunked processing completed: "
                            f"{chunk_stats['succeeded']}/{chunk_stats['total']} chunks succeeded "
                            f"({chunk_stats['ledger_hits']} ledger hits)"
                        )
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
                            document_content=extracted_text,
                            context=context
                        )
                    
                    # PORTHOLE: Capture LLM structured output
                    capture_llm_output(
                        document_id=document_id,
                        llm_response=structured_extraction,
                        llm_type="structured_extraction_claude",
                        success=bool(structured_extraction)
                    )
                    
                    # MEMORY FIX: extracted_text is no longer needed after AI extraction
                    # It was already saved to document.original_text earlier
                    del extracted_text
                    force_memory_cleanup("after AI extraction - freed extracted_text")
                    
                    if structured_extraction:
                        # VALIDATION: Check structured extraction quality
                        if not validate_after_ai_extraction(document, structured_extraction):
                            logger.warning(f"[{task_id}] Structured extraction validation failed for document {document_id}, proceeding with caution")
                        
                        ai_result = {
                            'success': True,
                            'fields': [],
                            'model_used': 'structured_extraction_claude',
                            'processing_method': 'structured_pydantic',
                            'usage': {'total_tokens': 0},
                            'processing_duration_ms': 0,
                        }
                        
                        total_items = (
                            len(structured_extraction.conditions) +
                            len(structured_extraction.medications) +
                            len(structured_extraction.vital_signs) +
                            len(structured_extraction.lab_results) +
                            len(structured_extraction.procedures) +
                            len(structured_extraction.providers)
                        )
                        logger.info(f"Structured extraction successful: {total_items} items across all resource types")
                    
                except Exception as structured_exc:
                    logger.error(f"Structured extraction failed for document {document_id}: {structured_exc}")
                    
                    # PORTHOLE: Capture extraction error
                    capture_pipeline_error(
                        document_id=document_id,
                        stage="structured_extraction",
                        error_message=str(structured_exc),
                        error_data={
                            'context': context,
                            'text_length': text_length
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

                ai_step_time_ms = int((time.time() - ai_step_start) * 1000)
                _save_document_stage_timing(document, ai_extraction_time_ms=ai_step_time_ms)
                _notify_monitor_stage(document)
                
                # FALLBACK: Use legacy extraction if structured extraction failed
                # KEEP DISABLED TO FORCE STRUCTURED EXTRACTION AND EXPOSE REAL ERRORS
                # if not structured_extraction:
                #     logger.error(f"STRUCTURED EXTRACTION FAILED for document {document_id}, using legacy fallback")
                #     ai_result = ai_analyzer.analyze_document(
                #         document_content=extracted_text,
                #         context=context
                #     )
                
                # Handle graceful degradation responses
                if ai_result and ai_result.get('degraded'):
                    logger.warning(f"Document {document_id} processed with degradation: {ai_result.get('error_context', 'Unknown error')}")
                    
                    document.error_message = f"AI processing degraded: {ai_result.get('error_context', 'All AI services failed')}"
                    
                    # Log degradation in audit system (internal audit trail only)
                    from apps.core.models import AuditLog
                    AuditLog.log_event(
                        event_type='document_requires_review',
                        description=f"Document {document_id} processed with AI degradation (merge continues)",
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
                    _notify_monitor_stage(document)
                    
                    logger.info(f"AI analysis successful: {len(ai_result['fields'])} fields extracted")
                    
                    # STEP 3: Convert to FHIR format using appropriate converter
                    fhir_step_start = time.time()
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
                    
                    # WP1 council fix: Snapshot structured data BEFORE converter attempt
                    # so clinical_date derivation still has access if the converter fails.
                    _pre_convert_structured_dict = None
                    if structured_extraction:
                        _pre_convert_structured_dict = structured_extraction.model_dump()

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
                            
                            # PORTHOLE: Log FHIR conversion summary (skip full serialization to save memory)
                            # Full serialization happens once later at the main FHIR serialization step
                            logger.info(f"Porthole: StructuredDataConverter produced {len(fhir_resources)} FHIR resources for document {document_id}")
                            
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
                        fields_for_metrics = _group_ai_fields_for_metrics(
                            ai_result.get('fields', [])
                        )
                        capture_metrics = metrics_service.calculate_data_capture_metrics(
                            fields_for_metrics, fhir_resources
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

                    fhir_step_time_ms = int((time.time() - fhir_step_start) * 1000)
                    _save_document_stage_timing(document, fhir_conversion_time_ms=fhir_step_time_ms)
                    _notify_monitor_stage(document)
                    
                    # FHIR resources are now stored in ParsedData for review workflow
                    # Actual accumulation to patient record happens after user approval
                    # via the merge_to_patient_record task
                    logger.info(f"FHIR processing completed: {len(fhir_resources)} resources ready for review and approval")
                    
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
                        # WP1 council fix: fall back to pre-converter snapshot when
                        # structured_extraction was cleared due to converter failure.
                        structured_data_dict = None
                        structured_data_counts = {}
                        if structured_extraction:
                            structured_data_dict = _pre_convert_structured_dict or structured_extraction.model_dump()
                            structured_data_counts = {
                                'conditions': len(structured_extraction.conditions),
                                'medications': len(structured_extraction.medications),
                                'vital_signs': len(structured_extraction.vital_signs),
                                'lab_results': len(structured_extraction.lab_results),
                                'procedures': len(structured_extraction.procedures),
                                'providers': len(structured_extraction.providers),
                            }
                            del structured_extraction
                            force_memory_cleanup("after structured_extraction model_dump")
                        elif _pre_convert_structured_dict:
                            structured_data_dict = _pre_convert_structured_dict
                            structured_data_counts = {
                                k: len(v) for k, v in _pre_convert_structured_dict.items()
                                if isinstance(v, list)
                            }
                        
                        # Serialize FHIR resources to JSON-compatible dicts
                        # StructuredDataConverter returns FHIR resource models that need serialization
                        # MEMORY FIX: Process one at a time and clear references
                        serialized_fhir_resources = []
                        if fhir_resources:
                            total_resources = len(fhir_resources)
                            logger.info(f"Starting serialization of {total_resources} FHIR resources for document {document_id}")
                            
                            # MEMORY FIX: Pop resources from list to avoid holding both list and serialized copies
                            while fhir_resources:
                                resource = fhir_resources.pop(0)  # Remove from original list
                                resource_num = total_resources - len(fhir_resources)
                                
                                try:
                                    # Log the resource type for debugging
                                    logger.debug(f"Serializing resource #{resource_num}, type: {type(resource).__name__}")
                                    
                                    if hasattr(resource, 'dict'):
                                        # FHIR resource model (fhir.resources) - serialize it
                                        # Use exclude_none=True to remove null fields and reduce size
                                        resource_dict = resource.dict(exclude_none=True)
                                        # Convert datetime objects to ISO format strings for JSON compatibility
                                        serialized_fhir_resources.append(json.loads(json.dumps(resource_dict, default=str)))
                                        del resource_dict  # MEMORY FIX: Clear intermediate dict
                                    elif hasattr(resource, 'model_dump'):
                                        # Pydantic v2 model - serialize it
                                        resource_dict = resource.model_dump(exclude_none=True)
                                        serialized_fhir_resources.append(json.loads(json.dumps(resource_dict, default=str)))
                                        del resource_dict  # MEMORY FIX: Clear intermediate dict
                                    elif isinstance(resource, dict):
                                        # Already a dict - ensure JSON compatibility
                                        serialized_fhir_resources.append(json.loads(json.dumps(resource, default=str)))
                                    else:
                                        # Unknown type - log warning and skip
                                        logger.warning(f"Unexpected FHIR resource type: {type(resource)}, skipping serialization")
                                except Exception:
                                    # Use logger.exception to capture full traceback
                                    logger.exception(f"Failed to serialize FHIR resource #{resource_num} of type {type(resource)}")
                                    # Continue with other resources
                                finally:
                                    del resource  # MEMORY FIX: Clear reference
                            
                            # MEMORY FIX: Force cleanup after serialization loop
                            force_memory_cleanup("after FHIR serialization")
                            logger.info(f"Successfully serialized {len(serialized_fhir_resources)}/{total_resources} FHIR resources for document {document_id}")
                        
                        # WP1 Phase 3: Derive clinical_date from serialized extraction data
                        clinical_date_defaults = _build_clinical_date_defaults(
                            structured_data_dict, serialized_fhir_resources
                        )

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
                                # WP1 Phase 3: clinical_date / date_source / date_status (empty when undetermined)
                                **clinical_date_defaults,
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
                            
                            # Partial chunk completion overrides any auto-approval
                            if _apply_partial_completion_flag(parsed_data, chunk_stats, task_id):
                                review_status = parsed_data.review_status
                                flag_reason = parsed_data.flag_reason
                            
                            logger.info(
                                f"[{task_id}] Review status determined: {review_status} "
                                f"{'(auto-approved)' if parsed_data.auto_approved else f'(flagged: {flag_reason})'}"
                            )
                            
                            if review_status == 'flagged':
                                logger.warning(
                                    f"[{task_id}] Low-confidence extraction flagged for document {document_id}: "
                                    f"{flag_reason}. Proceeding with merge (audit only)."
                                )
                            
                            # Task 41.28: HIPAA audit logging for review decision
                            from apps.documents.models import audit_extraction_decision
                            audit_extraction_decision(parsed_data, request=None)
                            
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
                                
                                # Task 41.28: HIPAA audit logging for merge operation
                                from apps.documents.models import audit_merge_operation
                                audit_merge_operation(
                                    parsed_data, 
                                    merge_success=merge_success,
                                    resource_count=len(serialized_fhir_resources),
                                    request=None
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
                        
                        # MEMORY FIX: Free large data structures after ParsedData save + merge
                        # These are now persisted in the database and no longer needed in memory
                        del serialized_fhir_resources
                        del structured_data_dict
                        del fields_data
                        del snippets_data
                        force_memory_cleanup("after ParsedData save and merge")
                        
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
        
        # Task 41.13: Set document status based on merge status (always complete when merged)
        try:
            # Get the ParsedData to check merge status
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
            else:
                document.status = 'completed'
                if parsed_data.review_status == 'flagged':
                    logger.warning(
                        f"[{task_id}] Document {document_id} merged with low-confidence flags: "
                        f"{parsed_data.flag_reason}"
                    )
                    document.processing_message = (
                        f"Processing completed (flags logged): "
                        f"{parsed_data.flag_reason[:100] if parsed_data.flag_reason else 'Unknown'}"
                    )
                elif parsed_data.auto_approved:
                    document.processing_message = "Processing completed - data auto-approved and merged"
                else:
                    document.processing_message = "Processing completed - data merged"
                logger.info(f"[{task_id}] Document {document_id} completed")
                
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
            
            try:
                document.status = 'failed'
                document.processing_message = "Processing failed - could not determine final status"
                document.save(update_fields=['status', 'processing_message'])
            except Exception as fallback_error:
                logger.critical(
                    f"[{task_id}] Critical: Failed to set fallback status for document {document_id}: {fallback_error}"
                )
        
        document.processed_at = timezone.now()
        document.error_message = ''
        document.save()
        _notify_monitor_stage(document)
        
        logger.info(f"Document {document_id} processed successfully - status: {document.status}")
        
        # Prepare comprehensive result (uses extraction_result_meta saved earlier)
        result = {
            'success': True,
            'document_id': document_id,
            'status': document.status,
            'task_id': self.request.id,
            'pdf_extraction': extraction_result_meta,
            'ai_analysis': ai_result if ai_result else {'success': False, 'error': 'AI analysis skipped - no content or no API keys'},
            'message': f'Document processing completed successfully - {extraction_result_meta["page_count"]} pages processed'
        }
        
        # Add AI-specific info to result if successful
        if ai_result and ai_result['success']:
            result['ai_analysis'].update({
                'fields_extracted': len(ai_result['fields']),
                'model_used': ai_result.get('model_used'),
                'processing_method': ai_result.get('processing_method'),
                'tokens_used': ai_result.get('usage', {}).get('total_tokens', 0),
                'fhir_resources_created': len(fhir_resources) if fhir_resources else 0,
                'structured_extraction_used': bool(structured_data_counts),
                'structured_data_types': structured_data_counts if structured_data_counts else {}
            })
        
        logger.info(f"Document {document_id} processing completed successfully")
        return result
        
    except APIRateLimitError as exc:
        logger.warning(f"Rate limit exceeded for document {document_id}. Retrying task.")
        raise self.retry(exc=exc, countdown=60, max_retries=5) # Retry after 60s

    except SoftTimeLimitExceeded:
        # Completed chunks are checkpointed in the ledger; hand off to a
        # resume run instead of failing (text is in document.original_text)
        return _handle_soft_time_limit(
            document_id, task_id, time.time() - start_time, resume_attempt=0
        )

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


# REMOVED: merge_to_patient_record task (Task 41.27)
# This task is obsolete in the optimistic concurrency system.
# Documents now merge automatically in process_document_async (lines 921-953)
# without waiting for manual approval.


# =============================================================================
# ASYNC TEXTRACT OCR TASKS (Task 42.10, 42.11, 42.12)
# =============================================================================

@shared_task(bind=True, name="apps.documents.tasks.start_textract_async_job", acks_late=True,
             max_retries=3, default_retry_delay=60)
def start_textract_async_job(self, document_id: int):
    """
    Start an asynchronous AWS Textract OCR job for large documents (>=5MB).
    
    This task handles documents too large for synchronous Textract processing by:
    1. Loading the Document from database
    2. Uploading PDF bytes to S3 temp bucket via OCRTempStorage
    3. Starting async Textract analysis via TextractService.start_async_analysis()
    4. Storing job_id and s3_key in Document.structured_data for tracking
    5. Scheduling poll_textract_job to check for completion
    6. Creating audit log entry 'ocr_async_job_started'
    
    Args:
        document_id: ID of the Document to process with async OCR
        
    Returns:
        Dict with job_id, s3_key, and task scheduling info
        
    Raises:
        CeleryTaskError: If document lookup fails or critical errors occur
        S3StorageError: If S3 upload fails (will retry)
        TextractAPIError: If Textract job start fails (will retry)
    """
    from .models import Document
    from .services.textract import (
        TextractService, 
        OCRTempStorage, 
        TextractAPIError, 
        TextractConfigurationError,
        S3StorageError
    )
    from apps.core.models import AuditLog
    
    task_id = self.request.id
    start_time = time.time()
    
    logger.info(
        f"[{task_id}] Starting async Textract job for document {document_id}"
    )
    
    # Step 1: Load and validate Document
    try:
        document = Document.objects.select_related('patient').get(id=document_id)
        
        if not document.file:
            raise CeleryTaskError(
                f"Document {document_id} has no file attached",
                task_id=task_id,
                details={'document_id': document_id}
            )
        
        # Read document bytes
        document.file.seek(0)
        document_bytes = document.file.read()
        file_size = len(document_bytes)
        
        logger.info(
            f"[{task_id}] Document loaded: {document.filename}, "
            f"size={file_size:,} bytes, patient={document.patient.mrn if document.patient else 'None'}"
        )
        
    except Document.DoesNotExist:
        error_msg = f"Document {document_id} not found"
        logger.error(f"[{task_id}] {error_msg}")
        raise CeleryTaskError(
            error_msg,
            task_id=task_id,
            details={'document_id': document_id, 'lookup_failed': True}
        )
    except Exception as load_error:
        logger.error(f"[{task_id}] Failed to load document: {load_error}")
        raise CeleryTaskError(
            f"Failed to load document {document_id}: {str(load_error)}",
            task_id=task_id,
            details={'document_id': document_id, 'error_type': type(load_error).__name__}
        )
    
    # Step 2: Upload to S3 temp bucket
    try:
        s3_storage = OCRTempStorage()
        s3_key = s3_storage.upload_document(
            document_bytes=document_bytes,
            document_id=str(document_id),
            file_extension='pdf'
        )
        
        logger.info(
            f"[{task_id}] Document uploaded to S3: bucket={s3_storage.bucket}, key={s3_key}"
        )
        
        # Audit log: S3 upload
        try:
            AuditLog.log_event(
                event_type='ocr_temp_upload',
                description=f"Document {document_id} uploaded to S3 for async OCR",
                details={
                    'document_id': document_id,
                    's3_key': s3_key,
                    's3_bucket': s3_storage.bucket,
                    'file_size_bytes': file_size,
                    'task_id': task_id
                },
                severity='info'
            )
        except Exception as audit_error:
            logger.warning(f"[{task_id}] Failed to create S3 upload audit log: {audit_error}")
        
    except TextractConfigurationError as config_error:
        # Configuration errors are not retryable
        logger.error(f"[{task_id}] S3 configuration error: {config_error}")
        document.status = 'failed'
        document.error_message = f"OCR configuration error: {str(config_error)}"
        document.processed_at = timezone.now()
        document.save(update_fields=['status', 'error_message', 'processed_at'])
        
        return {
            'success': False,
            'document_id': document_id,
            'error_type': 'configuration_error',
            'error_message': str(config_error),
            'task_id': task_id
        }
        
    except S3StorageError as s3_error:
        # S3 errors may be transient - retry
        logger.warning(f"[{task_id}] S3 upload failed: {s3_error}")
        raise self.retry(exc=s3_error, countdown=30)
    
    # Step 3: Start async Textract (text detection or analysis per settings.TEXTRACT_MODE)
    try:
        textract_service = TextractService()
        async_job = textract_service.start_async_job(
            s3_bucket=s3_storage.bucket,
            s3_key=s3_key,
        )
        job_id = async_job['job_id']
        textract_job_type = async_job['job_type']

        logger.info(
            f"[{task_id}] Textract async job started: job_id={job_id}, job_type={textract_job_type}"
        )
        
    except TextractConfigurationError as config_error:
        # Configuration errors are not retryable - clean up S3
        logger.error(f"[{task_id}] Textract configuration error: {config_error}")
        
        try:
            s3_storage.delete_document(s3_key)
            logger.info(f"[{task_id}] Cleaned up S3 object after config error: {s3_key}")
        except Exception as cleanup_error:
            logger.warning(f"[{task_id}] Failed to clean up S3 object: {cleanup_error}")
        
        document.status = 'failed'
        document.error_message = f"Textract configuration error: {str(config_error)}"
        document.processed_at = timezone.now()
        document.save(update_fields=['status', 'error_message', 'processed_at'])
        
        return {
            'success': False,
            'document_id': document_id,
            'error_type': 'configuration_error',
            'error_message': str(config_error),
            'task_id': task_id
        }
        
    except TextractAPIError as api_error:
        # Some API errors may be transient (rate limits, service issues) - retry
        if api_error.error_code in ('ThrottlingException', 'LimitExceededException', 
                                      'ProvisionedThroughputExceededException'):
            logger.warning(
                f"[{task_id}] Textract rate limited, retrying: {api_error.error_code}"
            )
            raise self.retry(exc=api_error, countdown=60)
        else:
            # Non-retryable API error - clean up S3
            logger.error(f"[{task_id}] Textract API error: {api_error}")
            
            try:
                s3_storage.delete_document(s3_key)
                logger.info(f"[{task_id}] Cleaned up S3 object after API error: {s3_key}")
            except Exception as cleanup_error:
                logger.warning(f"[{task_id}] Failed to clean up S3 object: {cleanup_error}")
            
            document.status = 'failed'
            document.error_message = f"Textract API error: {str(api_error)}"
            document.processed_at = timezone.now()
            document.save(update_fields=['status', 'error_message', 'processed_at'])
            
            return {
                'success': False,
                'document_id': document_id,
                'error_type': 'textract_api_error',
                'error_code': api_error.error_code,
                'error_message': str(api_error),
                'task_id': task_id
            }
    
    # Step 4: Store job tracking info in Document.structured_data
    try:
        # Preserve existing structured_data if any
        existing_data = document.structured_data or {}
        existing_data['textract_async'] = {
            'job_id': job_id,
            'job_type': textract_job_type,
            's3_key': s3_key,
            's3_bucket': s3_storage.bucket,
            'started_at': timezone.now().isoformat(),
            'task_id': task_id,
            'file_size_bytes': file_size,
        }
        document.structured_data = existing_data
        document.status = 'processing'
        document.processing_message = 'Async OCR processing started...'
        document.save(update_fields=['structured_data', 'status', 'processing_message'])
        
        logger.info(
            f"[{task_id}] Stored job tracking info in document.structured_data"
        )
        
    except Exception as save_error:
        logger.error(f"[{task_id}] Failed to save job tracking info: {save_error}")
        # Continue anyway - we can still poll using the job_id
    
    # Step 5: Schedule poll task with initial delay
    poll_interval = getattr(settings, 'TEXTRACT_ASYNC_POLL_INTERVAL', 10)
    
    try:
        poll_textract_job.apply_async(
            args=[document_id, job_id, s3_key],
            kwargs={'attempt': 0},
            countdown=poll_interval
        )
        
        logger.info(
            f"[{task_id}] Scheduled poll_textract_job with {poll_interval}s delay"
        )
        
    except Exception as schedule_error:
        logger.error(f"[{task_id}] Failed to schedule poll task: {schedule_error}")
        # This is a problem but not fatal - manual intervention can resume
    
    # Step 6: Create audit log entry
    try:
        AuditLog.log_event(
            event_type='ocr_async_job_started',
            description=f"Async Textract OCR job started for document {document_id}",
            details={
                'document_id': document_id,
                'job_id': job_id,
                's3_key': s3_key,
                's3_bucket': s3_storage.bucket,
                'file_size_bytes': file_size,
                'task_id': task_id,
                'processing_time_ms': int((time.time() - start_time) * 1000)
            },
            severity='info'
        )
    except Exception as audit_error:
        logger.warning(f"[{task_id}] Failed to create async job audit log: {audit_error}")
    
    # Return success result
    processing_time = time.time() - start_time
    logger.info(
        f"[{task_id}] Async Textract job started successfully in {processing_time:.2f}s: "
        f"job_id={job_id}, document_id={document_id}"
    )
    
    return {
        'success': True,
        'document_id': document_id,
        'job_id': job_id,
        's3_key': s3_key,
        's3_bucket': s3_storage.bucket,
        'task_id': task_id,
        'processing_time_seconds': round(processing_time, 2),
        'poll_task_scheduled': True,
        'poll_delay_seconds': poll_interval
    }


@shared_task(bind=True, name="apps.documents.tasks.poll_textract_job", acks_late=True,
             max_retries=30, default_retry_delay=10)
def poll_textract_job(self, document_id: int, job_id: str, s3_key: str, attempt: int = 0):
    """
    Poll AWS Textract for async job completion with exponential backoff.
    
    This task checks the status of an async Textract job and:
    - On IN_PROGRESS: Retries with exponential backoff (10s, 20s, 40s... up to 60s max)
    - On SUCCEEDED: Retrieves results, cleans up S3, chains to continue_document_processing
    - On FAILED/timeout: Marks Document as failed, creates review queue entry
    
    Args:
        document_id: ID of the Document being processed
        job_id: Textract async job ID
        s3_key: S3 key of the temporary document file
        attempt: Current polling attempt number (for backoff calculation)
        
    Returns:
        Dict with job status and result info
        
    Raises:
        TextractAPIError: If status check fails (will retry)
    """
    from .models import Document
    from .services.textract import (
        TextractService, 
        OCRTempStorage,
        TextractAPIError,
        TextractConfigurationError
    )
    from apps.core.models import AuditLog
    
    task_id = self.request.id
    max_wait_seconds = getattr(settings, 'TEXTRACT_ASYNC_MAX_WAIT', 300)
    
    logger.info(
        f"[{task_id}] Polling Textract job: job_id={job_id}, "
        f"document_id={document_id}, attempt={attempt}"
    )
    
    # Load Document for status updates
    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error(f"[{task_id}] Document {document_id} not found during polling")
        # Can't continue without document - cleanup S3 and exit
        try:
            OCRTempStorage().delete_document(s3_key)
        except Exception:
            pass
        return {
            'success': False,
            'document_id': document_id,
            'error': 'Document not found',
            'job_id': job_id
        }
    
    # Check elapsed time from job start
    textract_data = (document.structured_data or {}).get('textract_async', {})
    started_at_str = textract_data.get('started_at')
    elapsed_seconds = 0
    
    if started_at_str:
        try:
            from django.utils.dateparse import parse_datetime
            started_at = parse_datetime(started_at_str)
            if started_at:
                elapsed_seconds = (timezone.now() - started_at).total_seconds()
        except Exception:
            pass
    
    # Check for timeout
    if elapsed_seconds >= max_wait_seconds:
        logger.error(
            f"[{task_id}] Textract job timed out: job_id={job_id}, "
            f"elapsed={elapsed_seconds:.0f}s, max={max_wait_seconds}s"
        )
        
        # Clean up S3
        try:
            OCRTempStorage().delete_document(s3_key)
            logger.info(f"[{task_id}] Cleaned up S3 object after timeout: {s3_key}")
        except Exception as cleanup_error:
            logger.warning(f"[{task_id}] Failed to clean up S3: {cleanup_error}")
        
        # Mark document as failed
        document.status = 'failed'
        document.error_message = f"OCR processing timed out after {max_wait_seconds}s"
        document.processed_at = timezone.now()
        document.save(update_fields=['status', 'error_message', 'processed_at'])
        
        # Audit log: timeout
        try:
            AuditLog.log_event(
                event_type='ocr_async_job_timeout',
                description=f"Async Textract job timed out for document {document_id}",
                details={
                    'document_id': document_id,
                    'job_id': job_id,
                    'elapsed_seconds': elapsed_seconds,
                    'max_wait_seconds': max_wait_seconds,
                    'task_id': task_id
                },
                severity='error'
            )
        except Exception:
            pass
        
        return {
            'success': False,
            'document_id': document_id,
            'job_id': job_id,
            'status': 'timeout',
            'elapsed_seconds': elapsed_seconds
        }
    
    # Check job status
    textract_job_type = textract_data.get(
        'job_type', TextractService.JOB_TYPE_ANALYZE
    )
    try:
        textract_service = TextractService()
        status = textract_service.get_async_job_status(
            job_id, job_type=textract_job_type
        )
        
        logger.info(
            f"[{task_id}] Textract job status: {status} (attempt {attempt}, "
            f"elapsed {elapsed_seconds:.0f}s)"
        )
        
        # Audit log: polling attempt
        try:
            AuditLog.log_event(
                event_type='ocr_async_job_polling',
                description=f"Polling Textract job {job_id}",
                details={
                    'document_id': document_id,
                    'job_id': job_id,
                    'status': status,
                    'attempt': attempt,
                    'elapsed_seconds': elapsed_seconds,
                    'task_id': task_id
                },
                severity='debug'
            )
        except Exception:
            pass
        
    except TextractAPIError as api_error:
        logger.warning(f"[{task_id}] Error checking job status: {api_error}")
        # Retry with backoff
        backoff_delay = min(10 * (2 ** attempt), 60)
        raise self.retry(exc=api_error, countdown=backoff_delay)
    
    # Handle status outcomes
    if status == 'IN_PROGRESS':
        # Job still running - retry with exponential backoff
        backoff_delay = min(10 * (2 ** attempt), 60)  # 10s, 20s, 40s, 60s max
        
        document.processing_message = f"OCR processing in progress ({elapsed_seconds:.0f}s elapsed)..."
        document.save(update_fields=['processing_message'])
        
        logger.info(
            f"[{task_id}] Job still in progress, retrying in {backoff_delay}s"
        )
        
        raise self.retry(
            args=[document_id, job_id, s3_key],
            kwargs={'attempt': attempt + 1},
            countdown=backoff_delay
        )
    
    elif status in ('SUCCEEDED', 'PARTIAL_SUCCESS'):
        # Job completed - retrieve results
        logger.info(f"[{task_id}] Textract job succeeded, retrieving results...")
        
        try:
            # Get the full results (handles pagination internally)
            result = textract_service.get_async_result(
                job_id,
                poll_interval_seconds=1,  # Already completed, minimal poll
                max_wait_seconds=30,      # Should return immediately
                job_type=textract_job_type,
            )
            
            # Extract text from result
            ocr_text = textract_service.extract_text_from_result(result)
            
            logger.info(
                f"[{task_id}] Retrieved OCR results: pages={result.page_count}, "
                f"confidence={result.confidence:.1f}%, chars={len(ocr_text)}"
            )
            
        except TextractAPIError as result_error:
            logger.error(f"[{task_id}] Failed to retrieve results: {result_error}")
            
            document.status = 'failed'
            document.error_message = f"Failed to retrieve OCR results: {str(result_error)}"
            document.processed_at = timezone.now()
            document.save(update_fields=['status', 'error_message', 'processed_at'])
            
            # Still clean up S3
            try:
                OCRTempStorage().delete_document(s3_key)
            except Exception:
                pass
            
            return {
                'success': False,
                'document_id': document_id,
                'job_id': job_id,
                'status': 'result_retrieval_failed',
                'error': str(result_error)
            }
        
        # Clean up S3 temp file
        try:
            OCRTempStorage().delete_document(s3_key)
            logger.info(f"[{task_id}] Cleaned up S3 object: {s3_key}")
            
            # Audit log: S3 cleanup
            try:
                AuditLog.log_event(
                    event_type='ocr_temp_delete',
                    description=f"Cleaned up S3 temp file after OCR completion",
                    details={
                        's3_key': s3_key,
                        'document_id': document_id,
                        'job_id': job_id,
                        'task_id': task_id
                    },
                    severity='info'
                )
            except Exception:
                pass
            
        except Exception as cleanup_error:
            logger.warning(f"[{task_id}] Failed to clean up S3: {cleanup_error}")
            # Continue anyway - file will be auto-deleted by lifecycle policy
        
        # Update document with OCR metadata
        textract_data['completed_at'] = timezone.now().isoformat()
        textract_data['result_metadata'] = result.to_audit_dict()
        document.structured_data = {**document.structured_data, 'textract_async': textract_data}
        document.save(update_fields=['structured_data'])
        
        # Audit log: job completed
        try:
            AuditLog.log_event(
                event_type='ocr_async_job_completed',
                description=f"Async Textract OCR completed for document {document_id}",
                details={
                    'document_id': document_id,
                    'job_id': job_id,
                    'page_count': result.page_count,
                    'confidence': result.confidence,
                    'extraction_time_ms': result.extraction_time_ms,
                    'text_length': len(ocr_text),
                    'elapsed_seconds': elapsed_seconds,
                    'task_id': task_id
                },
                severity='info'
            )
        except Exception:
            pass

        _log_textract_usage(
            document,
            result.to_audit_dict(),
            _get_processing_session_id(task_id),
            textract_mode=textract_job_type,
        )
        
        # Chain to continue_document_processing
        try:
            continue_document_processing.delay(document_id, ocr_text)
            logger.info(
                f"[{task_id}] Chained to continue_document_processing for document {document_id}"
            )
        except Exception as chain_error:
            logger.error(f"[{task_id}] Failed to chain processing task: {chain_error}")
            # Store OCR text in document for manual recovery
            document.original_text = ocr_text
            document.status = 'failed'
            document.processing_message = 'OCR complete but processing chain failed'
            document.save(update_fields=['original_text', 'status', 'processing_message'])
        
        return {
            'success': True,
            'document_id': document_id,
            'job_id': job_id,
            'status': status,
            'page_count': result.page_count,
            'confidence': result.confidence,
            'text_length': len(ocr_text),
            'elapsed_seconds': elapsed_seconds,
            'chained_to_processing': True
        }
    
    else:  # FAILED or other error status
        logger.error(f"[{task_id}] Textract job failed with status: {status}")
        
        # Clean up S3
        try:
            OCRTempStorage().delete_document(s3_key)
            logger.info(f"[{task_id}] Cleaned up S3 object after failure: {s3_key}")
        except Exception as cleanup_error:
            logger.warning(f"[{task_id}] Failed to clean up S3: {cleanup_error}")
        
        # Mark document as failed
        document.status = 'failed'
        document.error_message = f"OCR processing failed: Textract job status={status}"
        document.processed_at = timezone.now()
        document.save(update_fields=['status', 'error_message', 'processed_at'])
        
        # Audit log: job failed
        try:
            AuditLog.log_event(
                event_type='ocr_async_job_failed',
                description=f"Async Textract job failed for document {document_id}",
                details={
                    'document_id': document_id,
                    'job_id': job_id,
                    'status': status,
                    'elapsed_seconds': elapsed_seconds,
                    'task_id': task_id
                },
                severity='error'
            )
        except Exception:
            pass
        
        return {
            'success': False,
            'document_id': document_id,
            'job_id': job_id,
            'status': status,
            'error': f'Textract job failed with status: {status}'
        }


@shared_task(bind=True, name="apps.documents.tasks.continue_document_processing", acks_late=True,
             max_retries=3, default_retry_delay=60,
             time_limit=getattr(settings, 'LARGE_DOCUMENT_TASK_TIME_LIMIT', 2100),
             soft_time_limit=getattr(settings, 'LARGE_DOCUMENT_TASK_SOFT_TIME_LIMIT', 1800))
def continue_document_processing(self, document_id: int, ocr_text: str, resume_attempt: int = 0):
    """
    Continue document processing pipeline after async OCR completion.
    
    This task receives the OCR text from the async Textract workflow and
    continues the standard processing pipeline:
    1. Stores OCR text in Document.original_text
    2. Runs DocumentAnalyzer for AI extraction
    3. Converts to FHIR resources via StructuredDataConverter
    4. Creates ParsedData with optimistic merge
    5. Sets Document.status to 'completed' when merge succeeds
    
    This mirrors the sync processing path after text extraction, reusing
    as much code as possible from process_document_async.
    
    Also serves as the RESUME path after a soft time limit: when called with
    empty ocr_text, the text is reloaded from document.original_text and the
    chunk ledger skips all previously completed chunks.
    
    Args:
        document_id: ID of the Document to continue processing
        ocr_text: Extracted text from async Textract OCR. Empty string means
            "resume from document.original_text".
        resume_attempt: How many soft-time-limit resumes have already happened.
        
    Returns:
        Dict with processing results matching process_document_async format
    """
    from .models import Document
    
    task_id = self.request.id
    start_time = time.time()
    
    logger.info(
        f"[{task_id}] Continuing document processing after async OCR: "
        f"document_id={document_id}, text_length={len(ocr_text)}, "
        f"resume_attempt={resume_attempt}"
    )
    
    # Load document
    try:
        document = Document.objects.select_related('patient').get(id=document_id)
    except Document.DoesNotExist:
        logger.error(f"[{task_id}] Document {document_id} not found")
        return {
            'success': False,
            'document_id': document_id,
            'error': 'Document not found',
            'task_id': task_id
        }
    
    if ocr_text:
        # Normal path: store fresh OCR text in document
        document.original_text = ocr_text
        document.status = 'processing'
        document.processing_message = "OCR complete, analyzing document with AI..."
        document.save(update_fields=['original_text', 'status', 'processing_message'])
    else:
        # Resume path: reload previously saved text, never overwrite it
        ocr_text = document.original_text or ''
        if not ocr_text.strip():
            logger.error(
                f"[{task_id}] Resume requested for document {document_id} but "
                f"original_text is empty — cannot resume"
            )
            document.status = 'failed'
            document.error_message = "Resume failed: no saved text available"
            document.save(update_fields=['status', 'error_message'])
            return {
                'success': False,
                'document_id': document_id,
                'error': 'Resume failed: no saved text available',
                'task_id': task_id
            }
        document.status = 'processing'
        document.processing_message = (
            f"Resuming AI extraction from checkpoint (attempt {resume_attempt})..."
        )
        document.save(update_fields=['status', 'processing_message'])
        logger.info(
            f"[{task_id}] Resume path: loaded {len(ocr_text)} chars from document.original_text"
        )
    _notify_monitor_stage(document)
    
    # Get page count from structured_data if available
    textract_data = (document.structured_data or {}).get('textract_async', {})
    result_metadata = textract_data.get('result_metadata', {})
    page_count = result_metadata.get('page_count', ocr_text.count('--- Page') or 1)
    
    logger.info(
        f"[{task_id}] OCR text stored ({len(ocr_text)} chars, {page_count} pages). "
        f"Starting AI analysis pipeline..."
    )
    
    # Import pipeline components
    from apps.documents.analyzers import DocumentAnalyzer
    from apps.fhir.converters import StructuredDataConverter
    from apps.documents.services.ai_extraction import extract_medical_data_structured
    from .validation_utils import validate_before_ai_extraction, validate_after_ai_extraction
    from .models import ParsedData
    from apps.documents.exceptions import (
        AIExtractionError, FHIRConversionError, DataValidationError,
        categorize_exception, get_recovery_strategy
    )
    
    extracted_text = ocr_text
    del ocr_text  # Free the parameter copy
    text_length = len(extracted_text)
    
    processing_errors = []
    ai_result = None
    structured_extraction = None
    chunk_stats = None
    fhir_resources = []
    
    try:
        # STEP 2: AI Structured Extraction
        document.processing_message = "Analyzing document with AI..."
        document.save(update_fields=['processing_message'])
        _notify_monitor_stage(document)
        
        context = "medical_document"
        ai_analyzer = DocumentAnalyzer(document=document)
        chunk_threshold = getattr(settings, 'AI_TOKEN_THRESHOLD_FOR_CHUNKING', 20000)
        
        logger.info(f"[{task_id}] Starting AI structured extraction ({text_length} chars, threshold={chunk_threshold})")

        size_failure = _check_document_text_size_limit(document, text_length, task_id)
        if size_failure:
            return size_failure
        
        ai_step_start = time.time()
        
        if text_length > chunk_threshold:
            logger.info(f"[{task_id}] Large OCR document ({text_length} chars), chunking for efficiency")
            chunks = document_chunker.chunk_text(extracted_text, preserve_context=True)
            del extracted_text
            force_memory_cleanup("after chunking extracted_text in continue_processing")

            chunk_failure = _check_document_chunk_limit(document, len(chunks), task_id)
            if chunk_failure:
                return chunk_failure
            
            if len(chunks) > 1:
                total_chunks = len(chunks)
                structured_extraction, chunk_stats = _process_chunks_streaming(
                    chunks, context, task_id, document=document
                )
                force_memory_cleanup("after chunk aggregation in continue_processing")
                logger.info(
                    f"[{task_id}] Chunked processing completed: "
                    f"{chunk_stats['succeeded']}/{chunk_stats['total']} chunks succeeded "
                    f"({chunk_stats['ledger_hits']} ledger hits)"
                )
            else:
                structured_extraction = ai_analyzer.analyze_document_structured(
                    document_content=chunks[0]['text'], context=context
                )
                del chunks
                force_memory_cleanup("after single-chunk extraction in continue_processing")
        else:
            structured_extraction = ai_analyzer.analyze_document_structured(
                document_content=extracted_text, context=context
            )
            del extracted_text
            force_memory_cleanup("after AI extraction in continue_processing")
        
        ai_step_time_ms = int((time.time() - ai_step_start) * 1000)
        _save_document_stage_timing(document, ai_extraction_time_ms=ai_step_time_ms)
        _notify_monitor_stage(document)
        
        if structured_extraction:
            ai_result = {
                'success': True,
                'fields': [],
                'model_used': 'structured_extraction_claude',
                'processing_method': 'async_ocr_then_structured',
            }
            
            logger.info(
                f"[{task_id}] AI extraction successful: "
                f"{len(structured_extraction.conditions)} conditions, "
                f"{len(structured_extraction.medications)} medications, "
                f"{len(structured_extraction.vital_signs)} vitals, "
                f"{len(structured_extraction.lab_results)} labs, "
                f"{len(structured_extraction.procedures)} procedures, "
                f"{len(structured_extraction.providers)} providers, "
                f"{len(structured_extraction.encounters)} encounters, "
                f"{len(structured_extraction.allergies)} allergies"
            )
            
            # STEP 3: FHIR Conversion
            document.processing_message = "Converting to FHIR format..."
            document.save(update_fields=['processing_message'])
            _notify_monitor_stage(document)
            
            fhir_step_start = time.time()
            patient_id = str(document.patient.id) if document.patient else None
            structured_converter = StructuredDataConverter()
            
            conversion_metadata = {
                'document_id': document.id,
                'extraction_timestamp': structured_extraction.extraction_timestamp,
                'document_type': structured_extraction.document_type,
                'confidence_average': structured_extraction.confidence_average
            }
            
            fhir_resources = structured_converter.convert_structured_data(
                structured_extraction, conversion_metadata, document.patient
            )
            logger.info(f"[{task_id}] FHIR conversion: {len(fhir_resources)} resources created")

            fhir_step_time_ms = int((time.time() - fhir_step_start) * 1000)
            _save_document_stage_timing(document, fhir_conversion_time_ms=fhir_step_time_ms)
            _notify_monitor_stage(document)
            
            # STEP 4: Serialize and store
            document.processing_message = "Saving results..."
            document.save(update_fields=['processing_message'])
            
            # Serialize structured extraction
            structured_data_dict = structured_extraction.model_dump()
            avg_confidence = structured_extraction.confidence_average or 0.0
            
            # MEMORY FIX: Free Pydantic model after serialization
            del structured_extraction
            force_memory_cleanup("after model_dump in continue_processing")
            
            # Serialize FHIR resources
            serialized_fhir_resources = []
            total_resources = len(fhir_resources)
            while fhir_resources:
                resource = fhir_resources.pop(0)
                try:
                    if hasattr(resource, 'dict'):
                        resource_dict = resource.dict(exclude_none=True)
                        serialized_fhir_resources.append(json.loads(json.dumps(resource_dict, default=str)))
                        del resource_dict
                    elif hasattr(resource, 'model_dump'):
                        resource_dict = resource.model_dump(exclude_none=True)
                        serialized_fhir_resources.append(json.loads(json.dumps(resource_dict, default=str)))
                        del resource_dict
                    elif isinstance(resource, dict):
                        serialized_fhir_resources.append(json.loads(json.dumps(resource, default=str)))
                except Exception as ser_exc:
                    logger.warning(f"[{task_id}] Failed to serialize FHIR resource: {ser_exc}")
                finally:
                    del resource
            
            force_memory_cleanup("after FHIR serialization in continue_processing")
            logger.info(f"[{task_id}] Serialized {len(serialized_fhir_resources)}/{total_resources} FHIR resources")
            
            # STEP 5: Create ParsedData record
            # WP1 Phase 3: Derive clinical_date from serialized extraction data
            clinical_date_defaults = _build_clinical_date_defaults(
                structured_data_dict, serialized_fhir_resources
            )

            parsed_data, created = ParsedData.objects.update_or_create(
                document=document,
                defaults={
                    'patient': document.patient,
                    'extraction_json': ai_result.get('fields', []),
                    'fhir_delta_json': serialized_fhir_resources if serialized_fhir_resources else {},
                    'extraction_confidence': avg_confidence,
                    'ai_model_used': ai_result.get('model_used', 'unknown'),
                    'corrections': {'structured_data': structured_data_dict} if structured_data_dict else {},
                    'is_approved': False,
                    'is_merged': False,
                    'reviewed_at': None,
                    'reviewed_by': None,
                    # WP1 Phase 3: clinical_date / date_source / date_status (empty when undetermined)
                    **clinical_date_defaults,
                }
            )
            
            action = "Created" if created else "Updated"
            logger.info(f"[{task_id}] {action} ParsedData {parsed_data.id} for document {document_id}")
            
            # STEP 6: Review status + optimistic merge
            try:
                review_status, flag_reason = parsed_data.determine_review_status()
                parsed_data.review_status = review_status
                parsed_data.auto_approved = (review_status == 'auto_approved')
                parsed_data.flag_reason = flag_reason
                parsed_data.save(update_fields=['review_status', 'auto_approved', 'flag_reason'])

                # Partial chunk completion overrides any auto-approval
                if _apply_partial_completion_flag(parsed_data, chunk_stats, task_id):
                    review_status = parsed_data.review_status
                    flag_reason = parsed_data.flag_reason

                logger.info(f"[{task_id}] Review status: {review_status}")
                
                if review_status == 'flagged':
                    logger.warning(
                        f"[{task_id}] Low-confidence extraction flagged for document {document_id}: "
                        f"{flag_reason}. Proceeding with merge (audit only)."
                    )
                
                # Optimistic merge into patient record
                if serialized_fhir_resources and document.patient:
                    merge_success = document.patient.add_fhir_resources(
                        serialized_fhir_resources,
                        document_id=document.id
                    )
                    if merge_success:
                        parsed_data.is_merged = True
                        parsed_data.merged_at = timezone.now()
                        parsed_data.save(update_fields=['is_merged', 'merged_at'])
                        logger.info(f"[{task_id}] Merged {len(serialized_fhir_resources)} FHIR resources into patient record")
                    else:
                        logger.error(f"[{task_id}] Failed to merge FHIR resources into patient record")
                        
            except Exception as merge_exc:
                logger.error(f"[{task_id}] Review/merge error: {merge_exc}", exc_info=True)
                processing_errors.append(f"Merge error: {str(merge_exc)}")
            
            # Free large data
            del serialized_fhir_resources
            del structured_data_dict
            force_memory_cleanup("after ParsedData save in continue_processing")
        
        else:
            logger.warning(f"[{task_id}] AI structured extraction returned None for document {document_id}")
            ai_result = {'success': False, 'error': 'Structured extraction returned None', 'fields': []}
    
    except SoftTimeLimitExceeded:
        # Completed chunks are checkpointed in the ledger; hand off to a
        # resume run instead of failing
        return _handle_soft_time_limit(
            document_id, task_id, time.time() - start_time, resume_attempt=resume_attempt
        )

    except Exception as pipeline_exc:
        logger.error(f"[{task_id}] Pipeline error in continue_processing: {pipeline_exc}", exc_info=True)
        processing_errors.append(str(pipeline_exc))
        ai_result = ai_result or {'success': False, 'error': str(pipeline_exc), 'fields': []}
    
    # Set final document status based on merge status (always complete when merged)
    try:
        parsed_data_final = ParsedData.objects.filter(document=document).first()
        
        if not parsed_data_final:
            document.status = 'failed'
            document.processing_message = "Processing failed - no parsed data created"
            logger.error(f"[{task_id}] Document {document_id} has no ParsedData record after pipeline")
        elif not parsed_data_final.is_merged:
            document.status = 'failed'
            document.processing_message = (
                f"Merge failed - data extracted but not merged to patient record. "
                f"ParsedData ID: {parsed_data_final.id} contains the extracted data."
            )
            logger.error(f"[{task_id}] Document {document_id} MERGE FAILED")
        else:
            document.status = 'completed'
            if parsed_data_final.review_status == 'flagged':
                logger.warning(
                    f"[{task_id}] Document {document_id} merged with low-confidence flags: "
                    f"{parsed_data_final.flag_reason}"
                )
                document.processing_message = (
                    f"Processing completed (flags logged): "
                    f"{parsed_data_final.flag_reason[:100] if parsed_data_final.flag_reason else 'Unknown'}"
                )
            elif parsed_data_final.auto_approved:
                document.processing_message = "Processing completed - data auto-approved and merged"
            else:
                document.processing_message = "Processing completed - data merged"
            logger.info(f"[{task_id}] Document {document_id} completed")
    except Exception as status_exc:
        logger.error(f"[{task_id}] Error determining final status: {status_exc}")
        document.status = 'failed'
        document.processing_message = "Processing failed - could not determine final status"
    
    if processing_errors:
        document.error_message = '; '.join(processing_errors[:3])
    else:
        document.error_message = ''
    
    document.processed_at = timezone.now()
    document.save(update_fields=['status', 'processing_message', 'processed_at', 'error_message'])
    _notify_monitor_stage(document)
    
    processing_time = time.time() - start_time
    
    logger.info(
        f"[{task_id}] Document {document_id} processing complete via async OCR pipeline. "
        f"Status: {document.status}, Time: {processing_time:.1f}s"
    )
    
    return {
        'success': len(processing_errors) == 0,
        'document_id': document_id,
        'status': document.status,
        'task_id': task_id,
        'ocr_text_length': text_length,
        'page_count': page_count,
        'ai_analysis': ai_result if ai_result else {'success': False},
        'processing_time_seconds': round(processing_time, 2),
        'errors': processing_errors if processing_errors else None,
    }


@shared_task
def cleanup_old_documents():
    """
    Periodic watchdog for documents stuck in processing or async OCR.

    Detects orphaned records (e.g. worker OOM/SIGKILL) and either re-queues
    them or marks them failed after max attempts.
    """
    from .models import Document

    threshold_minutes = getattr(settings, 'STUCK_DOCUMENT_THRESHOLD_MINUTES', 15)
    cutoff = timezone.now() - timedelta(minutes=threshold_minutes)

    stuck_docs = Document.objects.filter(
        status__in=['processing', 'ocr_pending'],
        processing_started_at__isnull=False,
        processing_started_at__lt=cutoff,
    ).order_by('processing_started_at')

    recovered = 0
    failed = 0

    for document in stuck_docs:
        elapsed_minutes = int(
            (timezone.now() - document.processing_started_at).total_seconds() / 60
        )
        logger.warning(
            "Stuck document detected: id=%s status=%s attempts=%s elapsed_min=%s",
            document.id,
            document.status,
            document.processing_attempts,
            elapsed_minutes,
        )

        document.add_error_to_log(
            error_type='stuck_processing',
            error_message=(
                f"Document stuck in {document.status} for {elapsed_minutes} minutes; "
                "watchdog recovery triggered"
            ),
            context={'elapsed_minutes': elapsed_minutes},
        )

        if document.processing_attempts < 3:
            document.status = 'pending'
            document.processing_message = 'Re-queued after processing timeout'
            document.error_message = ''
            document.processing_started_at = None
            document.increment_processing_attempts()
            document.save(
                update_fields=[
                    'status',
                    'processing_message',
                    'error_message',
                    'processing_started_at',
                    'processing_attempts',
                ]
            )
            _notify_monitor_stage(document)
            process_document_async.delay(document.id)
            recovered += 1
            logger.warning(
                "Re-queued stuck document %s (attempt %s/3)",
                document.id,
                document.processing_attempts,
            )
        else:
            document.status = 'failed'
            document.processing_message = 'Processing timed out after multiple attempts'
            document.error_message = (
                'Processing timed out after multiple attempts. '
                'The document may be too large or the worker was interrupted.'
            )
            document.processed_at = timezone.now()
            document.save(
                update_fields=[
                    'status',
                    'processing_message',
                    'error_message',
                    'processed_at',
                ]
            )
            _notify_monitor_stage(document)
            failed += 1
            logger.warning(
                "Marked stuck document %s as failed after %s attempts",
                document.id,
                document.processing_attempts,
            )

    summary = (
        f"Watchdog complete: recovered={recovered}, failed={failed}, "
        f"checked={stuck_docs.count()}"
    )
    logger.info(summary)
    return summary


def _fail_document_with_limit(
    document,
    *,
    error_message: str,
    processing_message: str,
    task_id: str,
    error_type: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Mark a document failed due to size/limit constraints and return task result."""
    document.status = 'failed'
    document.processing_message = processing_message
    document.error_message = error_message
    document.processed_at = timezone.now()
    document.save(
        update_fields=[
            'status',
            'processing_message',
            'error_message',
            'processed_at',
        ]
    )
    document.add_error_to_log(
        error_type=error_type,
        error_message=error_message,
        context=context or {},
    )
    _notify_monitor_stage(document)
    logger.warning("[%s] %s for document %s", task_id, error_type, document.id)
    return {
        'success': False,
        'document_id': document.id,
        'status': 'failed',
        'error_message': error_message,
    }


def _check_document_text_size_limit(document, text_length: int, task_id: str) -> Optional[Dict[str, Any]]:
    """Return a failure result if extracted text exceeds the configured limit."""
    max_length = getattr(settings, 'MAX_DOCUMENT_TEXT_LENGTH', 500000)
    if text_length <= max_length:
        return None

    error_message = (
        f"Document too large for processing: {text_length:,} characters exceeds "
        f"{max_length:,} character limit. Contact administrator."
    )
    return _fail_document_with_limit(
        document,
        error_message=error_message,
        processing_message='Document exceeds maximum text size',
        task_id=task_id,
        error_type='document_too_large',
        context={'text_length': text_length, 'max_length': max_length},
    )


def _check_document_chunk_limit(document, chunk_count: int, task_id: str) -> Optional[Dict[str, Any]]:
    """Return a failure result if chunk count exceeds the configured limit."""
    max_chunks = getattr(settings, 'MAX_DOCUMENT_CHUNKS', 25)
    if chunk_count <= max_chunks:
        return None

    error_message = (
        f"Document requires too many processing chunks ({chunk_count} > {max_chunks}). "
        "The document may be too large for reliable processing."
    )
    return _fail_document_with_limit(
        document,
        error_message=error_message,
        processing_message='Document exceeds maximum chunk count',
        task_id=task_id,
        error_type='document_too_many_chunks',
        context={'chunk_count': chunk_count, 'max_chunks': max_chunks},
    )


def _create_empty_aggregated_dict() -> Dict[str, Any]:
    """Initialize the aggregated extraction dict used for chunked processing."""
    return {
        'conditions': [],
        'medications': [],
        'vital_signs': [],
        'lab_results': [],
        'procedures': [],
        'immunizations': [],
        'providers': [],
        'encounters': [],
        'service_requests': [],
        'diagnostic_reports': [],
        'allergies': [],
        'care_plans': [],
        'organizations': [],
        'family_history': [],
        'physical_exam_findings': [],
        'social_history': [],
        'extraction_timestamp': timezone.now().isoformat(),
        'document_type': 'chunked_document',
    }


_CHUNK_LIST_KEYS = [
    'conditions', 'medications', 'vital_signs', 'lab_results', 'procedures', 'immunizations',
    'providers', 'encounters', 'service_requests', 'diagnostic_reports', 'allergies',
    'care_plans', 'organizations', 'family_history', 'physical_exam_findings', 'social_history',
]


def _extend_aggregated_from_chunk(aggregated: Dict[str, Any], chunk_result: Dict) -> None:
    """Merge a single chunk extraction dict into the running aggregate."""
    if not chunk_result or not isinstance(chunk_result, dict):
        return
    for key in _CHUNK_LIST_KEYS:
        if key in chunk_result:
            aggregated[key].extend(chunk_result[key])


# Exact-match dedup keys for structured items duplicated across chunk overlap zones.
# Unlike narrative items (conditions/medications), these are discrete measurements where
# fuzzy matching would incorrectly merge distinct results (e.g., two different glucose draws).
_EXACT_DEDUP_KEYS = {
    'lab_results': ('test_name', 'value', 'test_date'),
    'vital_signs': ('measurement', 'value', 'timestamp'),
    'immunizations': ('vaccine_name', 'date_administered'),
}


def _deduplicate_exact(aggregated: Dict[str, Any], data_type: str, key_fields: tuple) -> None:
    """Remove exact duplicates (same identifying fields) introduced by chunk overlap."""
    if data_type not in aggregated:
        return
    items = aggregated[data_type]
    seen = set()
    deduplicated = []

    for item in items:
        if not isinstance(item, dict):
            deduplicated.append(item)
            continue
        identity = tuple(
            str(item.get(field) or '').strip().lower() for field in key_fields
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduplicated.append(item)

    if len(deduplicated) != len(items):
        logger.info(
            "Deduplicated %s: %s -> %s items (exact match)",
            data_type,
            len(items),
            len(deduplicated),
        )
    aggregated[data_type] = deduplicated


def _deduplicate_aggregated(aggregated: Dict[str, Any]) -> None:
    """Deduplicate similar medical items in aggregated chunk results."""
    from difflib import SequenceMatcher

    def is_similar(a: str, b: str, threshold: float = 0.85) -> bool:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio() > threshold

    for data_type in ['conditions', 'medications', 'procedures']:
        if data_type not in aggregated:
            continue
        items = aggregated[data_type]
        deduplicated = []

        for item in items:
            item_name = item.get('name', str(item)) if isinstance(item, dict) else str(item)
            is_duplicate = False
            for existing in deduplicated:
                existing_name = (
                    existing.get('name', str(existing))
                    if isinstance(existing, dict)
                    else str(existing)
                )
                if is_similar(item_name, existing_name):
                    if isinstance(item, dict) and isinstance(existing, dict):
                        if item.get('confidence', 0) > existing.get('confidence', 0):
                            idx = deduplicated.index(existing)
                            deduplicated[idx] = item
                    is_duplicate = True
                    break
            if not is_duplicate:
                deduplicated.append(item)

        logger.info(
            "Deduplicated %s: %s -> %s items",
            data_type,
            len(items),
            len(deduplicated),
        )
        aggregated[data_type] = deduplicated

    # Exact-match dedup for discrete measurements duplicated by chunk overlap
    for data_type, key_fields in _EXACT_DEDUP_KEYS.items():
        _deduplicate_exact(aggregated, data_type, key_fields)


def _handle_soft_time_limit(document_id: int, task_id: str, total_time: float,
                            resume_attempt: int = 0) -> Dict[str, Any]:
    """
    Handle a soft time limit hit during document processing.

    Chunk checkpoints are already persisted in the ledger, so instead of
    failing we re-enqueue a resume run (continue_document_processing with no
    ocr_text, which reloads document.original_text). The resume run skips all
    succeeded chunks via the ledger and only pays for unfinished work.

    Marks the document failed only after LARGE_DOCUMENT_MAX_RESUMES attempts.
    """
    from .models import Document

    max_resumes = getattr(settings, 'LARGE_DOCUMENT_MAX_RESUMES', 2)

    if resume_attempt < max_resumes:
        next_attempt = resume_attempt + 1
        logger.warning(
            f"[{task_id}] Document {document_id} hit soft time limit ({total_time:.0f}s). "
            f"Re-enqueueing resume run {next_attempt}/{max_resumes} "
            f"(completed chunks are checkpointed)."
        )
        try:
            document = Document.objects.get(id=document_id)
            document.processing_message = (
                f"Time limit reached — resuming from checkpoint (attempt {next_attempt}/{max_resumes})"
            )
            document.save(update_fields=['processing_message'])
        except Exception as save_err:
            logger.error(f"[{task_id}] Could not update resume message: {save_err}")

        continue_document_processing.apply_async(
            args=[document_id, ''],
            kwargs={'resume_attempt': next_attempt},
            countdown=15,
        )
        return {
            'success': False,
            'document_id': document_id,
            'status': 'resuming',
            'error_type': 'SoftTimeLimitExceeded',
            'resume_attempt': next_attempt,
            'error_message': (
                f'Processing timed out after {total_time/60:.1f} minutes; '
                f'resume run {next_attempt} enqueued'
            ),
        }

    logger.error(
        f"[{task_id}] Document {document_id} exceeded soft time limit ({total_time:.0f}s) "
        f"after {resume_attempt} resume attempts. Marking as failed."
    )
    try:
        document = Document.objects.get(id=document_id)
        document.status = 'failed'
        document.error_message = (
            f"Processing timed out after {total_time/60:.1f} minutes "
            f"({resume_attempt} resume attempts exhausted). "
            f"Completed chunks remain checkpointed for a manual retry."
        )
        document.processed_at = timezone.now()
        document.save(update_fields=['status', 'error_message', 'processed_at'])
    except Exception as save_err:
        logger.critical(
            f"[{task_id}] Failed to save timeout status for document {document_id}: {save_err}"
        )
    return {
        'success': False,
        'document_id': document_id,
        'status': 'failed',
        'error_type': 'SoftTimeLimitExceeded',
        'error_message': f'Processing timed out after {total_time/60:.1f} minutes',
    }


def _apply_partial_completion_flag(parsed_data, chunk_stats, task_id: str) -> bool:
    """
    Force 'flagged' review status when some chunks failed extraction.

    Partial results (>= AI_CHUNK_PARTIAL_THRESHOLD of chunks) are still merged,
    but a reviewer must know which chunks are missing. The failed chunk list is
    persisted in structured_extraction_metadata for the review UI.

    Returns True if the flag was applied.
    """
    if not chunk_stats or not chunk_stats.get('failed_chunks'):
        return False

    try:
        parsed_data.review_status = 'flagged'
        parsed_data.auto_approved = False
        parsed_data.flag_reason = (
            f"Partial extraction: {chunk_stats['succeeded']}/{chunk_stats['total']} "
            f"chunks succeeded; chunks {chunk_stats['failed_chunks']} failed"
        )
        metadata = parsed_data.structured_extraction_metadata or {}
        metadata['partial_completion'] = {
            'total_chunks': chunk_stats['total'],
            'succeeded_chunks': chunk_stats['succeeded'],
            'failed_chunk_indices': chunk_stats['failed_chunks'],
            'ledger_hits': chunk_stats['ledger_hits'],
            'flagged_at': timezone.now().isoformat(),
        }
        parsed_data.structured_extraction_metadata = metadata
        parsed_data.save(update_fields=[
            'review_status', 'auto_approved', 'flag_reason', 'structured_extraction_metadata'
        ])
        logger.warning(
            f"[{task_id}] ParsedData {parsed_data.id} flagged for partial completion: "
            f"{parsed_data.flag_reason}"
        )
        return True
    except Exception as flag_error:
        logger.error(f"[{task_id}] Failed to apply partial completion flag: {flag_error}")
        return False


# Version stamp folded into chunk content hashes. Bump when prompts/schema
# change so stale ledger checkpoints are correctly invalidated.
# Kept in sync with the Redis cache 'extraction_version'.
CHUNK_EXTRACTION_VERSION = '4.0'


def _chunk_content_hash(chunk_text: str, model: str) -> str:
    """SHA-256 over chunk text + extraction version + model name."""
    import hashlib
    payload = f"{chunk_text}|{CHUNK_EXTRACTION_VERSION}|{model}"
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _get_chunk_usage() -> Dict[str, Any]:
    """
    Pull usage stats from the most recent cached-extractor API call.

    Returns zeros when the legacy (non-cached) path handled the chunk.
    """
    try:
        from apps.documents.services.cached_extraction import _extractor_instance
        if _extractor_instance is not None and _extractor_instance.last_usage:
            return dict(_extractor_instance.last_usage)
    except Exception:
        pass
    return {}


def _estimate_chunk_cost(usage: Dict[str, Any]):
    """Estimate USD cost of one chunk call from its token usage."""
    from decimal import Decimal
    from apps.core.services import CostCalculator

    if not usage:
        return Decimal('0')
    model = usage.get('model') or getattr(settings, 'AI_MODEL_PRIMARY', 'claude-sonnet-4-5-20250929')
    return CostCalculator.calculate_cost(
        'anthropic', model,
        usage.get('input_tokens', 0) or 0,
        usage.get('output_tokens', 0) or 0,
    )


def _check_cost_circuit_breaker(document, task_id: str) -> None:
    """
    Halt chunk processing when per-document or daily AI spend limits are hit.

    Per-document spend comes from the chunk ledger; daily spend from
    APIUsageLog. Raises AIExtractionError with a clear message on breach.
    """
    from decimal import Decimal
    from django.db.models import Sum
    from .models import DocumentChunkResult
    from apps.core.models import APIUsageLog

    per_doc_limit = Decimal(str(getattr(settings, 'AI_PER_DOCUMENT_COST_LIMIT', 5.00)))
    daily_limit = Decimal(str(getattr(settings, 'AI_DAILY_COST_LIMIT', 100.00)))

    doc_spend = DocumentChunkResult.objects.filter(document=document).aggregate(
        total=Sum('cost_usd')
    )['total'] or Decimal('0')
    if doc_spend >= per_doc_limit:
        raise AIExtractionError(
            f"Per-document AI cost limit reached (${doc_spend:.2f} >= ${per_doc_limit:.2f}). "
            f"Processing halted to prevent cost overrun. Raise AI_PER_DOCUMENT_COST_LIMIT "
            f"to allow this document to complete.",
            details={'document_id': document.id, 'spend_usd': float(doc_spend)},
        )

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    daily_spend = APIUsageLog.objects.filter(created_at__gte=today_start).aggregate(
        total=Sum('cost_usd')
    )['total'] or Decimal('0')
    if daily_spend >= daily_limit:
        raise AIExtractionError(
            f"Daily AI cost limit reached (${daily_spend:.2f} >= ${daily_limit:.2f}). "
            f"Processing halted until tomorrow or until AI_DAILY_COST_LIMIT is raised.",
            details={'document_id': document.id, 'daily_spend_usd': float(daily_spend)},
        )


def _log_chunk_api_usage(document, usage: Dict[str, Any], task_id: str,
                         chunk_number: int, total_chunks: int,
                         start_time: float, success: bool = True,
                         error_message: Optional[str] = None) -> None:
    """Record one chunk's API usage in APIUsageLog; never fails processing."""
    try:
        from datetime import datetime, timezone as dt_timezone
        from apps.core.services import APIUsageMonitor

        if not usage:
            return
        APIUsageMonitor.log_api_usage(
            document=document,
            patient=document.patient,
            session_id=_get_processing_session_id(task_id),
            provider='anthropic',
            model=usage.get('model') or getattr(settings, 'AI_MODEL_PRIMARY', 'unknown'),
            input_tokens=usage.get('input_tokens', 0) or 0,
            output_tokens=usage.get('output_tokens', 0) or 0,
            total_tokens=(usage.get('input_tokens', 0) or 0) + (usage.get('output_tokens', 0) or 0),
            start_time=datetime.fromtimestamp(start_time, tz=dt_timezone.utc),
            end_time=datetime.now(tz=dt_timezone.utc),
            success=success,
            error_message=error_message,
            chunk_number=chunk_number,
            total_chunks=total_chunks,
        )
    except Exception as log_error:
        logger.warning(f"[{task_id}] Failed to log chunk API usage: {log_error}")


def _process_chunks_streaming(
    chunks: List[Dict[str, Any]],
    context: Optional[str],
    task_id: str,
    document=None,
) -> tuple:
    """
    Ledger-aware sequential chunk processing with incremental aggregation.

    For each chunk (in order):
    1. Skip the API entirely if the ledger has a 'succeeded' row with a
       matching content hash (retry/resume costs nothing for done chunks).
    2. Otherwise check the cost circuit breaker, call the AI, and persist the
       result to the ledger immediately — a crash or kill never loses
       completed work.
    3. On chunk failure, record it and continue — no longer all-or-nothing.

    Peak memory is one chunk result plus the running aggregate.

    Returns:
        (StructuredMedicalExtraction, chunk_stats) where chunk_stats is
        {'total': int, 'succeeded': int, 'failed_chunks': [int], 'ledger_hits': int}

    Raises:
        AIExtractionError: If the cost circuit breaker trips, or fewer than
            AI_CHUNK_PARTIAL_THRESHOLD of chunks succeeded.
        SoftTimeLimitExceeded: Propagated so the task can re-enqueue a resume;
            all completed chunks are already persisted in the ledger.
    """
    from apps.documents.services.ai_extraction import (
        extract_medical_data_structured,
        StructuredMedicalExtraction,
    )
    from .models import DocumentChunkResult

    model = getattr(settings, 'AI_MODEL_PRIMARY', 'claude-sonnet-4-5-20250929')
    aggregated = _create_empty_aggregated_dict()
    total_chunks = len(chunks)
    failed_chunks: List[int] = []
    ledger_hits = 0

    for chunk_idx, chunk in enumerate(chunks):
        chunk_text = chunk['text']
        content_hash = _chunk_content_hash(chunk_text, model) if document else None

        # 1. Ledger checkpoint: skip chunks already extracted with this exact
        #    text/version/model combination
        chunk_data = None
        if document is not None:
            ledger_row = DocumentChunkResult.objects.filter(
                document=document,
                chunk_index=chunk_idx,
                content_hash=content_hash,
                status='succeeded',
            ).first()
            if ledger_row is not None:
                chunk_data = ledger_row.structured_json
                ledger_hits += 1
                logger.info(
                    f"[{task_id}] Chunk {chunk_idx + 1}/{total_chunks}: ledger hit, skipping API call"
                )

        # 2. Fresh extraction with immediate checkpoint persistence
        if chunk_data is None:
            if document is not None:
                _check_cost_circuit_breaker(document, task_id)

            logger.info(f"[{task_id}] Processing chunk {chunk_idx + 1}/{total_chunks}")
            chunk_start = time.time()
            try:
                chunk_result = extract_medical_data_structured(chunk_text, context=context)
                chunk_data = chunk_result.model_dump()
                del chunk_result

                usage = _get_chunk_usage()
                if document is not None:
                    ledger_row, _ = DocumentChunkResult.objects.update_or_create(
                        document=document,
                        chunk_index=chunk_idx,
                        content_hash=content_hash,
                        defaults={
                            'status': 'succeeded',
                            'structured_json': chunk_data,
                            'input_tokens': usage.get('input_tokens', 0) or 0,
                            'output_tokens': usage.get('output_tokens', 0) or 0,
                            'cost_usd': _estimate_chunk_cost(usage),
                            'error_message': '',
                        },
                    )
                    DocumentChunkResult.objects.filter(pk=ledger_row.pk).update(
                        attempts=models.F('attempts') + 1
                    )
                    _log_chunk_api_usage(
                        document, usage, task_id, chunk_idx + 1, total_chunks, chunk_start
                    )
            except SoftTimeLimitExceeded:
                # Completed chunks are already in the ledger — propagate so the
                # task layer can re-enqueue a resume run
                raise
            except Exception as chunk_error:
                logger.error(
                    f"[{task_id}] Chunk {chunk_idx + 1}/{total_chunks} failed: {chunk_error}"
                )
                failed_chunks.append(chunk_idx)
                if document is not None:
                    ledger_row, _ = DocumentChunkResult.objects.update_or_create(
                        document=document,
                        chunk_index=chunk_idx,
                        content_hash=content_hash,
                        defaults={
                            'status': 'failed',
                            'structured_json': {},
                            'error_message': str(chunk_error)[:2000],
                        },
                    )
                    DocumentChunkResult.objects.filter(pk=ledger_row.pk).update(
                        attempts=models.F('attempts') + 1
                    )
                    _log_chunk_api_usage(
                        document, _get_chunk_usage(), task_id, chunk_idx + 1,
                        total_chunks, chunk_start, success=False,
                        error_message=str(chunk_error)[:500],
                    )
                chunk['text'] = ''
                continue

        # 3. Aggregate and update progress
        _extend_aggregated_from_chunk(aggregated, chunk_data)
        del chunk_data
        chunk['text'] = ''

        if document is not None:
            try:
                document.processing_message = (
                    f"AI extraction: {chunk_idx + 1}/{total_chunks} chunks"
                )
                document.save(update_fields=['processing_message'])
            except Exception as msg_error:
                logger.debug(f"[{task_id}] Could not update progress message: {msg_error}")

        if chunk_idx < total_chunks - 1:
            force_memory_cleanup(f"after chunk {chunk_idx + 1}")

    del chunks
    force_memory_cleanup("after all chunks processed")

    succeeded = total_chunks - len(failed_chunks)
    chunk_stats = {
        'total': total_chunks,
        'succeeded': succeeded,
        'failed_chunks': failed_chunks,
        'ledger_hits': ledger_hits,
    }

    partial_threshold = float(getattr(settings, 'AI_CHUNK_PARTIAL_THRESHOLD', 0.85))
    if total_chunks > 0 and (succeeded / total_chunks) < partial_threshold:
        raise AIExtractionError(
            f"Only {succeeded}/{total_chunks} chunks extracted successfully "
            f"(below {partial_threshold:.0%} threshold). Failed chunks: {failed_chunks}. "
            f"Succeeded chunks are checkpointed — retry will only re-process failures.",
            details={'document_id': getattr(document, 'id', None), **chunk_stats},
        )

    if failed_chunks:
        logger.warning(
            f"[{task_id}] Partial completion: {succeeded}/{total_chunks} chunks succeeded, "
            f"failed chunks {failed_chunks} — result will be flagged for review"
        )

    _deduplicate_aggregated(aggregated)
    return StructuredMedicalExtraction.model_validate(aggregated), chunk_stats


def _aggregate_chunked_extractions(chunk_results: List[Dict]) -> 'StructuredMedicalExtraction':
    """
    Aggregate multiple chunk extraction results into a single StructuredMedicalExtraction.
    
    Args:
        chunk_results: List of extraction results from document chunks
        
    Returns:
        Aggregated StructuredMedicalExtraction object
    """
    from apps.documents.services.ai_extraction import StructuredMedicalExtraction

    aggregated = _create_empty_aggregated_dict()
    for chunk_result in chunk_results:
        _extend_aggregated_from_chunk(aggregated, chunk_result)
    _deduplicate_aggregated(aggregated)
    return StructuredMedicalExtraction.model_validate(aggregated) 