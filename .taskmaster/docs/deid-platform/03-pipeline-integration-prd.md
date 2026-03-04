# Pipeline Integration - PRD

> **Purpose:** Wire the de-identification engine into the existing document processing pipeline, adding Mode A/B branching, AI prompt enhancements for PHI annotation, and document lifecycle management for Mode B.

---

## Parent Context

Part of the **De-Identification + FHIR Conversion Platform** initiative. See [deidentification-fhir-platform-prd.md](../deidentification-fhir-platform-prd.md) for overall vision.

Depends on:
- **Sub-PRD 01: Foundation & Infrastructure** for ProcessingJob, ProcessingResult models, and `assemble_r4_bundle()`
- **Sub-PRD 02: De-Identification Engine** for `DeidentificationEngine`

---

## Overview

The existing Celery task `process_document_async` in `apps/documents/tasks.py` implements a linear pipeline: extract text, extract structured data, convert to FHIR, merge into patient record. This phase adds a branch point after structured extraction that routes to either Mode A (existing, unchanged) or Mode B (de-identification + FHIR bundle output).

Mode A code paths are not modified. Mode B is implemented as a new task chain that reuses the shared extraction steps and adds de-identification, FHIR bundle assembly, result storage, and source document purge.

### Problem Statement

- The pipeline is coupled to the Patient model -- every processed document must be linked to a patient
- No mechanism exists to run the extraction pipeline without storing PHI permanently
- The AI extraction prompt does not ask the LLM to annotate where PHI appears in the source text, which would improve de-identification accuracy
- No lifecycle management for temporary processing data (source documents linger indefinitely)

### Solution

- Add a `processing_mode` check in the pipeline that routes to Mode A or Mode B after extraction
- Implement a Mode B task chain: de-identify → assemble FHIR bundle → store result → deliver webhook → schedule purge
- Enhance the AI extraction prompt with a PHI annotation instruction (additive, does not change existing extraction behavior)
- Add a periodic Celery Beat task to purge expired jobs and their source files

---

## Design Decisions

**1. New task vs. mode parameter on existing task**

Implement Mode B as a separate Celery task (`process_job_deidentification`) rather than adding a mode parameter to `process_document_async`. Rationale: the existing task has complex error handling, idempotency checks, and patient-specific logic. Modifying it risks regressions. The new task reuses the shared extraction functions but has its own orchestration logic.

**2. Shared extraction functions, not shared tasks**

The text extraction and AI extraction steps are shared at the function level, not the task level. Both `process_document_async` (Mode A) and `process_job_deidentification` (Mode B) call the same underlying functions:
- `PDFTextExtractor.extract_text()` from `apps/documents/services.py`
- `extract_medical_data_structured()` from `apps/documents/services/ai_extraction.py`

This avoids modifying the existing task's signature or behavior.

**3. PHI annotation is additive to extraction prompt**

The existing AI extraction prompt produces `StructuredMedicalExtraction`. The enhancement adds a new field `phi_annotations: List[PHIAnnotation]` to this model. The existing extraction behavior is unchanged -- the LLM still produces all the same fields. It additionally flags PHI locations. If the LLM doesn't produce annotations (e.g., with older prompts), the field defaults to an empty list.

**4. Source document purge is deferred, not immediate**

After Mode B processing completes, the source document and raw text are not deleted immediately. They are marked for purge at `expires_at` and cleaned up by a periodic task. This allows customers to retrieve results up to the TTL window and allows reprocessing if needed.

**5. Mode A is verified, not modified**

This phase includes a Mode A regression verification step: run the existing test suite against the shared extraction functions to confirm that PHI annotation changes don't affect Mode A output. The `phi_annotations` field is simply ignored by Mode A's FHIR conversion and patient merge logic.

---

## Technical Scope

### AI Prompt Enhancement

**Modify:** `apps/documents/services/ai_extraction.py`

**New Pydantic model:**

```python
class PHIAnnotation(BaseModel):
    """A detected PHI instance in the source text."""
    identifier_type: str = Field(
        description="HIPAA Safe Harbor identifier type: name, date, phone, "
                    "email, ssn, mrn, address, zip_code, fax, url, ip_address, "
                    "account_number, license_number, device_identifier, "
                    "vehicle_identifier, beneficiary_number, other_identifier"
    )
    value: str = Field(description="The PHI value as it appears in the text")
    start_index: int = Field(description="Approximate start position in source text", ge=0, default=0)
    end_index: int = Field(description="Approximate end position in source text", ge=0, default=0)
    confidence: float = Field(description="Confidence that this is PHI (0.0-1.0)", ge=0.0, le=1.0, default=0.9)
```

**Add to `StructuredMedicalExtraction`:**

```python
class StructuredMedicalExtraction(BaseModel):
    # ... existing fields unchanged ...

    # PHI annotations (used by de-identification engine, ignored by Mode A)
    phi_annotations: List[PHIAnnotation] = Field(
        default_factory=list,
        description="All instances of Protected Health Information (PHI) detected "
                    "in the source text, tagged by HIPAA Safe Harbor identifier type"
    )
```

**Modify extraction prompt** in `apps/documents/services/ai_extraction_service.py`:

Add the following instruction block to `_get_comprehensive_extraction_prompt()`. This is appended to the existing prompt, not replacing any existing instructions:

```
Additionally, identify ALL instances of Protected Health Information (PHI) in the 
document according to the HIPAA Safe Harbor method. For each PHI instance, provide:
- The identifier type (name, date, phone, email, ssn, mrn, address, zip_code, etc.)
- The exact value as it appears in the text
- The approximate start and end character positions
- Your confidence level

Include PHI that appears anywhere in the document, even if it is not captured in 
the structured extraction fields above. This includes patient names, provider names, 
dates of birth, social security numbers, phone numbers, addresses, medical record 
numbers, and any other HIPAA Safe Harbor identifiers.
```

### Mode B Celery Task

**New file:** `apps/api/tasks.py`

```python
@shared_task(bind=True, acks_late=True, max_retries=2)
def process_job_deidentification(self, job_id: str):
    """
    Process a de-identification job (Mode B).

    Pipeline:
    1. Load ProcessingJob and input (file or text)
    2. Extract text from document (if file input)
    3. Extract structured medical data (AI extraction)
    4. De-identify extracted data
    5. Convert to FHIR R4 Bundle
    6. Store ProcessingResult
    7. Deliver webhook (if configured)
    8. Mark job complete
    """
```

**Task chain detail:**

| Step | Function | Source | Notes |
|------|----------|--------|-------|
| 1. Load job | `ProcessingJob.objects.get(id=job_id)` | `apps/api/models.py` | Set status to `processing` |
| 2. Extract text | `PDFTextExtractor.extract_text()` | `apps/documents/services.py` | Only if `input_type == 'file'`; skipped for text input |
| 3. AI extraction | `extract_medical_data_structured()` | `apps/documents/services/ai_extraction.py` | Same function as Mode A. Returns `StructuredMedicalExtraction` with `phi_annotations`. |
| 4. De-identify | `DeidentificationEngine.deidentify()` | `apps/deidentify/engine.py` | Uses profile from `job.deidentification_profile` |
| 5. Convert to FHIR | `StructuredDataConverter.convert_structured_data()` | `apps/fhir/converters.py` | Input is de-identified extraction. No patient reference. |
| 6. Assemble bundle | `assemble_r4_bundle()` | `apps/fhir/bundle_utils.py` | Wraps FHIR resources into R4 Bundle |
| 7. Store result | `ProcessingResult.objects.create()` | `apps/api/models.py` | Stores FHIR bundle, metrics, de-ID summary |
| 8. Webhook | `deliver_webhook()` | `apps/api/webhooks.py` | If `job.webhook_url` is set |
| 9. Complete | Set `job.status = 'completed'` | | Set `completed_at`, calculate `processing_time_ms` |

**Error handling:**

| Error Type | Behavior |
|-----------|----------|
| `PDFExtractionError` | Set job status to `failed`, store error message, no retry |
| `AIExtractionError` | Retry up to 2 times with exponential backoff |
| `AIServiceRateLimitError` | Retry with longer backoff (60s base) |
| `DeidentificationError` (new) | Set job status to `failed`, log details, no retry |
| `FHIRConversionError` | Set job status to `failed`, store error message, no retry |
| Any unexpected exception | Set job status to `failed`, log full traceback |

### FHIR Conversion Without Patient Reference

**Modify:** `apps/fhir/converters.py` -- `StructuredDataConverter.convert_structured_data()`

Currently this method accepts a `patient` parameter that creates FHIR resource references (e.g., `Condition.subject` references the patient). For Mode B, `patient` should be optional. When `patient` is `None`:

- `subject` references are set to a placeholder: `{"reference": "Patient/deidentified"}`
- No `Patient` FHIR resource is included in the output bundle
- All other resource generation proceeds normally

This is a small change: make the `patient` parameter optional with a default of `None` and add a conditional for subject reference generation.

### Document Lifecycle Management

**New periodic task** in `apps/api/tasks.py`:

```python
@app.task(name='apps.api.tasks.purge_expired_jobs')
def purge_expired_jobs():
    """
    Purge expired processing jobs, their results, and source files.

    Runs via Celery Beat on a configurable schedule (default: every hour).
    """
```

**Purge behavior:**

| What | Action |
|------|--------|
| `ProcessingJob` where `expires_at < now` and `status in (completed, failed)` | Delete source file from storage, clear `input_text`, set status to `expired` |
| `ProcessingResult` for expired jobs | Delete (cascade from job, or explicit) |
| `WebhookDelivery` for expired jobs | Delete (cascade) |
| `DeidentificationLog` for expired jobs | Keep (audit trail persists) |

**Celery Beat configuration** (add to `settings/base.py`):

```python
CELERY_BEAT_SCHEDULE = {
    # ... existing schedules ...
    'purge-expired-jobs': {
        'task': 'apps.api.tasks.purge_expired_jobs',
        'schedule': 3600.0,  # Every hour
    },
}
```

### Webhook Delivery

**New file:** `apps/api/webhooks.py`

```python
def deliver_webhook(job: ProcessingJob):
    """
    Deliver processing result to the configured webhook URL.

    - POST request with JSON body containing job_id, status, result_url
    - Retry up to WEBHOOK_MAX_RETRIES times with exponential backoff
    - Log each delivery attempt in WebhookDelivery model
    """
```

**Webhook payload:**

```json
{
    "event": "job.completed",
    "job_id": "uuid-here",
    "status": "completed",
    "result_url": "/api/v1/jobs/{job_id}/result/",
    "resource_count": 15,
    "processing_time_ms": 12450,
    "completed_at": "2026-03-01T10:30:00Z"
}
```

For failed jobs:

```json
{
    "event": "job.failed",
    "job_id": "uuid-here",
    "status": "failed",
    "error": "AI extraction failed after 2 retries",
    "failed_at": "2026-03-01T10:30:00Z"
}
```

---

## Mode A Regression Verification

The following must remain unchanged and passing after all modifications in this phase:

| Test Area | What to Verify |
|-----------|---------------|
| `process_document_async` | Task still processes documents linked to patients correctly |
| `StructuredMedicalExtraction` | Existing fields produce identical output; `phi_annotations` defaults to empty list |
| `StructuredDataConverter` | FHIR conversion with a patient reference works identically |
| `Patient.add_fhir_resources()` | FHIR merge into patient record works identically |
| Review workflow | `determine_review_status()` works identically |
| Document upload UI | Upload form and Celery task dispatch work identically |

**Verification approach:** Run existing test suite before and after changes. Any new test failures indicate a regression.

---

## Implementation Checklist

1. Add `PHIAnnotation` Pydantic model to `apps/documents/services/ai_extraction.py`
2. Add `phi_annotations` field to `StructuredMedicalExtraction` with `default_factory=list`
3. Append PHI annotation instruction to `_get_comprehensive_extraction_prompt()` in `ai_extraction_service.py`
4. Verify Mode A extraction still works (existing tests pass, `phi_annotations` defaults to empty)
5. Make `patient` parameter optional in `StructuredDataConverter.convert_structured_data()`
6. Add placeholder subject reference when `patient` is `None`
7. Create `apps/api/tasks.py` with `process_job_deidentification` task
8. Implement the full Mode B task chain (steps 1-9 from task chain detail above)
9. Create `apps/api/webhooks.py` with `deliver_webhook()` function
10. Create `purge_expired_jobs` periodic task
11. Add Celery Beat schedule for purge task
12. Write integration test: submit a ProcessingJob → process_job_deidentification → verify de-identified FHIR bundle in ProcessingResult
13. Write Mode A regression test: run full Mode A pipeline after prompt changes, verify identical output
14. Test webhook delivery with mock HTTP server

---

## Risks and Mitigations

**Risk 1: PHI annotation instruction degrades extraction quality**

Adding instructions to the LLM prompt increases its cognitive load. The extraction of medical data (conditions, medications, etc.) might become less accurate.

**Mitigation:** The PHI annotation is a separate instruction block, not modifying the existing extraction instructions. Test extraction quality (field counts, confidence scores) before and after the prompt change on a sample of documents. If quality degrades, make PHI annotation a separate LLM call (at the cost of additional tokens/latency).

**Risk 2: StructuredDataConverter breaks with patient=None**

The converter may have implicit assumptions about the patient parameter being present (e.g., using `patient.id` in resource references without null checks).

**Mitigation:** Audit all usages of the `patient` parameter in `StructuredDataConverter` and its helper methods. Add null guards. Test with `patient=None` explicitly.

**Risk 3: Webhook delivery blocks the task**

HTTP requests to external webhook URLs could hang or be slow, delaying job completion.

**Mitigation:** Webhook delivery is fire-and-forget from the main task's perspective. Use a short timeout (30 seconds). If delivery fails, create a `WebhookDelivery` record with `status='failed'` and schedule a retry via a separate Celery task. The main job is marked `completed` regardless of webhook delivery status.

**Risk 4: Purge task deletes data that is still needed**

A race condition where a customer requests results at the same moment the purge task runs.

**Mitigation:** Jobs are only purged when `status in ('completed', 'failed')` AND `expires_at < now`. The API returns `410 Gone` for expired jobs. Set a generous default TTL (72 hours). Document the TTL in API documentation.

---

## Existing Code References

**Celery task to parallel (not modify):**
- `apps/documents/tasks.py` -- `process_document_async()` (line 244+)
- `check_document_idempotency()` (line 52) -- follow this pattern for job idempotency

**Shared extraction functions:**
- `apps/documents/services.py` -- `PDFTextExtractor.extract_text()` (line 164)
- `apps/documents/services/ai_extraction.py` -- `extract_medical_data_structured()` (line 363)

**AI extraction prompt:**
- `apps/documents/services/ai_extraction_service.py` -- `_get_comprehensive_extraction_prompt()`

**FHIR conversion:**
- `apps/fhir/converters.py` -- `StructuredDataConverter.convert_structured_data()` (line 591)
- `apps/fhir/bundle_utils.py` -- `assemble_r4_bundle()` (to be created in Sub-PRD 01)

**Error handling patterns:**
- `apps/documents/exceptions.py` -- Custom exception hierarchy (reuse for Mode B)

**Celery Beat configuration:**
- `meddocparser/settings/base.py` -- `CELERY_BEAT_SCHEDULE` dict

---

## TaskMaster Integration

**Workflow:** Parse this PRD as 1 task, then expand into subtasks.

**Step 1 -- Parse (1 task):**
```bash
task-master parse-prd .taskmaster/docs/deid-platform/03-pipeline-integration-prd.md --tag=deid-platform --num-tasks=1 --append
```

**Step 2 -- Expand into subtasks:**
```bash
task-master expand --id=3 --tag=deid-platform --num=10
```

**Expected subtasks:** ~10 (PHI annotation model, prompt modification, converter modification, Mode B task, webhook delivery, purge task, Celery Beat config, integration test, regression test, error handling)
