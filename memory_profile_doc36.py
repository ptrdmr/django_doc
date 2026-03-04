#!/usr/bin/env python
"""
Memory Profiling Script for Document Processing Pipeline
=========================================================

Runs the exact same pipeline steps as process_document_async but OUTSIDE
Celery, with memory measurements at each stage. This eliminates the fork
overhead and lets us see exactly where memory goes.

Usage:
    docker compose exec -T web python memory_profile_doc36.py
"""

import os
import sys
import gc
import resource
import time

# Force unbuffered output
os.environ['PYTHONUNBUFFERED'] = '1'

def get_rss_mb():
    """Get current RSS (Resident Set Size) in MB."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # Linux reports ru_maxrss in KB
    return usage.ru_maxrss / 1024

def get_rss_current_mb():
    """Get current (not peak) RSS from /proc/self/status."""
    try:
        with open('/proc/self/status', 'r') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024  # KB -> MB
    except Exception:
        return get_rss_mb()
    return 0

def log_mem(label, baseline_mb=0):
    """Log memory with delta from baseline."""
    current = get_rss_current_mb()
    peak = get_rss_mb()
    delta = current - baseline_mb if baseline_mb else 0
    delta_str = f" (delta: +{delta:.1f} MB)" if baseline_mb else ""
    print(f"[MEMORY] {label}: {current:.1f} MB RSS (peak: {peak:.1f} MB){delta_str}", flush=True)
    return current

def separator(title):
    print(f"\n{'='*60}", flush=True)
    print(f"  {title}", flush=True)
    print(f"{'='*60}", flush=True)

# ============================================================
#  STEP 0: Django Setup
# ============================================================
separator("STEP 0: Django Import & Setup")
baseline = log_mem("before Django import")

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
import django
django.setup()

after_django = log_mem("after Django setup", baseline)

# ============================================================
#  STEP 1: Import pipeline components
# ============================================================
separator("STEP 1: Import Pipeline Components")

from apps.documents.models import Document
log_mem("after Document model import", baseline)

from apps.documents.services import PDFTextExtractor
log_mem("after PDFTextExtractor import", baseline)

from apps.documents.analyzers import DocumentAnalyzer
log_mem("after DocumentAnalyzer import", baseline)

from apps.documents.services.ai_extraction import extract_medical_data_structured
log_mem("after ai_extraction import (Claude+OpenAI clients init)", baseline)

from apps.fhir.converters import StructuredDataConverter
log_mem("after StructuredDataConverter import", baseline)

# ============================================================
#  STEP 2: Load document from database
# ============================================================
separator("STEP 2: Load Document 36 from Database")

DOCUMENT_ID = 36
document = Document.objects.select_related('patient').get(id=DOCUMENT_ID)
log_mem("after loading document from DB", baseline)

print(f"  Document: {document.filename}", flush=True)
print(f"  File size: {document.file_size} bytes ({document.file_size / (1024*1024):.2f} MB)", flush=True)
print(f"  Patient: {document.patient}", flush=True)
print(f"  File path: {document.file.path}", flush=True)

if not os.path.exists(document.file.path):
    print(f"  ERROR: File not found at {document.file.path}", flush=True)
    sys.exit(1)

file_size_mb = os.path.getsize(document.file.path) / (1024 * 1024)
print(f"  Actual file size on disk: {file_size_mb:.2f} MB", flush=True)

# ============================================================
#  STEP 3: PDF Text Extraction (pdfplumber + Textract)
# ============================================================
separator("STEP 3: PDF Text Extraction")

before_pdf = log_mem("before PDF extraction", baseline)

pdf_extractor = PDFTextExtractor()
log_mem("after PDFTextExtractor.__init__", baseline)

print("  Starting extract_text()...", flush=True)
t0 = time.time()
extraction_result = pdf_extractor.extract_text(document.file.path)
t1 = time.time()

after_pdf = log_mem("after PDF extraction complete", baseline)
print(f"  Extraction time: {t1-t0:.2f}s", flush=True)
print(f"  Success: {extraction_result.get('success')}", flush=True)
print(f"  Text length: {len(extraction_result.get('text', ''))} chars", flush=True)
print(f"  Page count: {extraction_result.get('page_count', 0)}", flush=True)
print(f"  Extraction method: {extraction_result.get('metadata', {}).get('extraction_method', 'unknown')}", flush=True)
print(f"  Image pages: {extraction_result.get('metadata', {}).get('image_pages', [])}", flush=True)
print(f"  Text pages: {extraction_result.get('metadata', {}).get('text_pages', [])}", flush=True)
print(f"  PDF extraction memory cost: +{after_pdf - before_pdf:.1f} MB", flush=True)

if not extraction_result.get('success'):
    print(f"  ERROR: PDF extraction failed: {extraction_result.get('error_message')}", flush=True)
    sys.exit(1)

# Save text and free extraction_result
extracted_text = extraction_result['text']
text_length = len(extracted_text)
page_count = extraction_result.get('page_count', 0)

# Measure effect of freeing extraction_result
del extraction_result
del pdf_extractor
gc.collect()
log_mem("after freeing extraction_result + gc.collect()", baseline)

# ============================================================
#  STEP 4: AI Structured Extraction (Claude API)
# ============================================================
separator("STEP 4: AI Structured Extraction (Claude)")

before_ai = log_mem("before AI extraction", baseline)

context = "medical_document"
ai_analyzer = DocumentAnalyzer(document=document)
log_mem("after DocumentAnalyzer.__init__", baseline)

print(f"  Sending {text_length} chars to Claude...", flush=True)
t0 = time.time()
structured_extraction = ai_analyzer.analyze_document_structured(
    document_content=extracted_text,
    context=context
)
t1 = time.time()

after_ai = log_mem("after AI extraction complete", baseline)
print(f"  AI extraction time: {t1-t0:.2f}s", flush=True)
print(f"  Conditions: {len(structured_extraction.conditions)}", flush=True)
print(f"  Medications: {len(structured_extraction.medications)}", flush=True)
print(f"  Vital signs: {len(structured_extraction.vital_signs)}", flush=True)
print(f"  Lab results: {len(structured_extraction.lab_results)}", flush=True)
print(f"  Procedures: {len(structured_extraction.procedures)}", flush=True)
print(f"  Providers: {len(structured_extraction.providers)}", flush=True)
print(f"  Encounters: {len(structured_extraction.encounters)}", flush=True)
print(f"  AI extraction memory cost: +{after_ai - before_ai:.1f} MB", flush=True)

# Free extracted_text (already sent to AI, saved to DB by real pipeline)
del extracted_text
gc.collect()
log_mem("after freeing extracted_text + gc.collect()", baseline)

# ============================================================
#  STEP 5: Pydantic model_dump (serialization)
# ============================================================
separator("STEP 5: Pydantic model_dump()")

before_dump = log_mem("before model_dump()", baseline)

structured_data_dict = structured_extraction.model_dump()
after_dump = log_mem("after model_dump()", baseline)
print(f"  model_dump() memory cost: +{after_dump - before_dump:.1f} MB", flush=True)

import json
dict_json = json.dumps(structured_data_dict, default=str)
print(f"  Serialized dict size: {len(dict_json)} chars ({len(dict_json)/1024:.1f} KB)", flush=True)
del dict_json

# Free the Pydantic model
del structured_extraction
gc.collect()
log_mem("after freeing structured_extraction Pydantic model + gc.collect()", baseline)

# ============================================================
#  STEP 6: FHIR Conversion
# ============================================================
separator("STEP 6: FHIR Conversion")

before_fhir = log_mem("before FHIR conversion", baseline)

# Re-create a minimal StructuredMedicalExtraction from the dict for FHIR conversion
from apps.documents.services.ai_extraction import StructuredMedicalExtraction
structured_for_fhir = StructuredMedicalExtraction(**structured_data_dict)
log_mem("after re-creating Pydantic model from dict", baseline)

structured_converter = StructuredDataConverter()
conversion_metadata = {
    'document_id': document.id,
    'extraction_timestamp': structured_for_fhir.extraction_timestamp,
    'document_type': structured_for_fhir.document_type,
    'confidence_average': structured_for_fhir.confidence_average
}

t0 = time.time()
fhir_resources = structured_converter.convert_structured_data(
    structured_for_fhir,
    conversion_metadata,
    document.patient
)
t1 = time.time()

after_fhir = log_mem("after FHIR conversion complete", baseline)
print(f"  FHIR conversion time: {t1-t0:.2f}s", flush=True)
print(f"  FHIR resources created: {len(fhir_resources)}", flush=True)
print(f"  FHIR conversion memory cost: +{after_fhir - before_fhir:.1f} MB", flush=True)

# Free
del structured_for_fhir
gc.collect()
log_mem("after freeing structured_for_fhir + gc.collect()", baseline)

# ============================================================
#  STEP 7: FHIR Serialization
# ============================================================
separator("STEP 7: FHIR Serialization")

before_serial = log_mem("before FHIR serialization", baseline)

serialized_fhir = []
total = len(fhir_resources)
while fhir_resources:
    res = fhir_resources.pop(0)
    try:
        if hasattr(res, 'dict'):
            d = res.dict(exclude_none=True)
            serialized_fhir.append(json.loads(json.dumps(d, default=str)))
            del d
        elif hasattr(res, 'model_dump'):
            d = res.model_dump(exclude_none=True)
            serialized_fhir.append(json.loads(json.dumps(d, default=str)))
            del d
        elif isinstance(res, dict):
            serialized_fhir.append(json.loads(json.dumps(res, default=str)))
    except Exception as e:
        print(f"  WARNING: Failed to serialize resource: {e}", flush=True)
    finally:
        del res

gc.collect()
after_serial = log_mem("after FHIR serialization complete", baseline)
print(f"  Serialized {len(serialized_fhir)}/{total} FHIR resources", flush=True)

serialized_json = json.dumps(serialized_fhir, default=str)
print(f"  Total serialized FHIR JSON size: {len(serialized_json)} chars ({len(serialized_json)/1024:.1f} KB)", flush=True)
del serialized_json

print(f"  FHIR serialization memory cost: +{after_serial - before_serial:.1f} MB", flush=True)

# ============================================================
#  SUMMARY
# ============================================================
separator("MEMORY PROFILE SUMMARY")

peak = get_rss_mb()
final = get_rss_current_mb()
print(f"  Baseline (after Django import):  {after_django:.1f} MB", flush=True)
print(f"  Final RSS:                       {final:.1f} MB", flush=True)
print(f"  Peak RSS:                        {peak:.1f} MB", flush=True)
print(f"  Total growth from baseline:      +{final - after_django:.1f} MB", flush=True)
print(f"  Peak growth from baseline:       +{peak - after_django:.1f} MB", flush=True)
print(f"", flush=True)
print(f"  Document: {document.filename} ({file_size_mb:.2f} MB, {page_count} pages, {text_length} chars)", flush=True)
print(f"", flush=True)
print(f"  This ran WITHOUT Celery fork overhead.", flush=True)
print(f"  In Celery prefork mode, add ~200-500 MB for the fork COW tax.", flush=True)
print(f"{'='*60}", flush=True)
