# PRD: AWS Textract OCR Integration

**Version:** 3.0  
**Status:** Ready for Implementation  
**Last Updated:** 2026-01-27

---

## TL;DR

Replace local Tesseract OCR with AWS Textract, adding S3 infrastructure for async processing of large documents. No fallback to local OCR—if Textract fails, the document fails and enters the review queue.

---

## Vision Statement

Replace the current local Tesseract OCR fallback with AWS Textract while preserving our existing Django/Celery document pipeline, review workflow, and HIPAA audit practices. The core change is confined to the PDF text extraction step (`PDFTextExtractor`), with the rest of the pipeline (AI extraction, FHIR conversion, optimistic merge, review queue) remaining intact.

**Core insight:** The right place for OCR routing is inside `PDFTextExtractor`, not a new standalone service. We already have page-level text extraction via pdfplumber; we just need to offload image-heavy pages to AWS Textract and return the same text format the downstream pipeline expects.

---

## Current Architecture Snapshot

### Upload & Task Orchestration
- `apps/documents/views.DocumentUploadView` saves the document
- `apps/documents/tasks.process_document_async` runs the pipeline asynchronously in Celery
- Idempotency is enforced via `check_document_idempotency`

### Text Extraction
- `apps/documents/services.PDFTextExtractor` extracts text with pdfplumber
- If no embedded text is found, it falls back to local OCR via `extract_with_ocr()` (pytesseract + pdf2image)

### AI Extraction & FHIR Merge
- `apps/documents/analyzers.DocumentAnalyzer` runs structured AI extraction (Claude primary + OpenAI fallback)
- `apps/fhir/converters.StructuredDataConverter` converts structured data to FHIR resources
- `ParsedData` is created and FHIR is merged immediately into the patient record (optimistic merge)
- Review status is tracked in `ParsedData.review_status`

### Audit & Monitoring
- Audit events use `AuditLog` via `audit_extraction_decision` and `audit_merge_operation`
- Monitoring is handled by `apps/documents/monitoring.ErrorMetrics` and `performance_monitor`

### Storage & Security
- `Document.file` is stored using `EncryptedFileField` (encrypted at rest)
- Max file size: 50MB
- `Document.original_text` is stored encrypted

---

## Problem Space (Why Change)

Current OCR fallback lives inside the Celery worker (`PDFTextExtractor.extract_with_ocr`) and uses:
- `pdf2image` to render pages at 300 DPI
- `pytesseract` to OCR each page

This is **CPU/memory-intensive**, blocking document processing and creating scaling bottlenecks. It also increases operational risk since OCR is tied to a single worker environment.

---

## Goals

1. Replace local Tesseract OCR with AWS Textract
2. Preserve the current `PDFTextExtractor` output format (page separators, text cleaning)
3. Maintain the existing Celery-based pipeline and optimistic FHIR merge flow
4. Add page-level selective OCR for hybrid documents
5. Keep HIPAA audit logging and monitoring consistent with current patterns
6. Set up AWS S3 infrastructure for async OCR processing

## Non-Goals

- No changes to AI extraction logic or FHIR conversion
- No changes to the review workflow or optimistic merge system
- No changes to the upload UI or document review UI
- No fallback to local Tesseract—if Textract fails, document fails
- No gradual rollout—flip the switch when ready
- No provider abstraction layer—committed to AWS Textract

---

## Architectural Decisions (Resolved)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| OCR Provider | AWS Textract (committed) | Best medical document support, tables/forms detection |
| Textract API | `AnalyzeDocument` | Includes table and form detection for lab results |
| Fallback Policy | None | Simplifies architecture; failed docs go to review queue |
| Sync/Async Mode | Hybrid | Sync for <5MB, async for ≥5MB |
| S3 Storage | New OCR-only bucket | Minimal scope, 24hr auto-delete |
| S3 Encryption | SSE-S3 | AWS-managed keys, simpler than KMS |
| AWS Auth | IAM role (prod) + env vars (dev) | Security best practice with local dev flexibility |
| Celery Queue | Same queue initially | Optimize later if needed |
| Concurrency Limits | Deferred | Add if Textract quotas become an issue |
| Text Threshold | 50 chars (tunable) | Start here, adjust based on results |
| Existing Documents | Leave alone | Only affects new documents |
| Local Dev | Require AWS sandbox credentials | No mocking, real integration tests |

---

## Strategic Approach

### OCR Routing Lives Inside PDFTextExtractor

We already process pages with pdfplumber. Use that to classify pages and decide which need OCR.

### Routing Logic (Page-Level)

- **Text page:** `page.extract_text()` returns ≥ `OCR_TEXT_THRESHOLD` chars (default: 50)
- **Image page:** insufficient text (< threshold)

### Classification & Processing Paths

| Path | Condition | Action |
|------|-----------|--------|
| Local Fast Path | All pages have embedded text | Use pdfplumber only |
| Full External OCR | No pages have embedded text | Send entire document to Textract |
| Selective OCR | Mixed pages | OCR only image pages; merge with local text |

### Sync vs Async Decision

| Document Size | Mode | Flow |
|---------------|------|------|
| < 5MB | Synchronous | Direct `AnalyzeDocument` API call |
| ≥ 5MB | Asynchronous | Upload to S3 → `StartDocumentAnalysis` → Poll for results |

---

## AWS Infrastructure Requirements (New)

### S3 Bucket Setup

Create a dedicated OCR temp bucket with these properties:

```
Bucket Name: {project}-ocr-temp-{environment}
Region: us-east-1 (or match existing infra)
Encryption: SSE-S3 (AWS-managed keys)
Public Access: Blocked (all settings)
Versioning: Disabled (temp files only)
```

### Lifecycle Rule

```json
{
  "Rules": [{
    "ID": "DeleteOCRTempFiles",
    "Status": "Enabled",
    "Filter": {"Prefix": ""},
    "Expiration": {"Days": 1}
  }]
}
```

### IAM Policy for Textract + S3

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TextractAccess",
      "Effect": "Allow",
      "Action": [
        "textract:AnalyzeDocument",
        "textract:StartDocumentAnalysis",
        "textract:GetDocumentAnalysis"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3OCRBucketAccess",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::{bucket-name}/*"
    },
    {
      "Sid": "S3BucketList",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::{bucket-name}"
    }
  ]
}
```

### Authentication Strategy

**Production:** IAM role attached to EC2 instance or ECS task (no credentials in code)

**Local Development:** Environment variables with sandbox AWS account:
```
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1
```

---

## Core Components

### 1) PDFTextExtractor (Existing - Modified)

Update `extract_text()` to:
- Track page-level text counts
- Route OCR only when needed (based on threshold)
- Call Textract service for OCR pages
- Preserve the same output format (`--- Page N ---`)
- Return `metadata.extraction_method` and page counts

**Key requirement:** Downstream code in `process_document_async` and `DocumentAnalyzer` must not change.

### 2) TextractService (New Module)

Add `apps/documents/services/textract.py`:

```python
class TextractService:
    """AWS Textract OCR service."""
    
    def analyze_document_sync(self, document_bytes: bytes) -> TextractResult:
        """Synchronous OCR for documents <5MB."""
        ...
    
    def start_async_analysis(self, s3_bucket: str, s3_key: str) -> str:
        """Start async job for large documents. Returns job_id."""
        ...
    
    def get_async_result(self, job_id: str) -> TextractResult:
        """Poll/retrieve async job results."""
        ...
    
    def extract_text_from_result(self, result: TextractResult) -> str:
        """Convert Textract response to plain text with page separators."""
        ...
```

### 3) S3 Upload Service (New Module)

Add `apps/documents/services/s3_upload.py`:

```python
class OCRTempStorage:
    """Temporary S3 storage for async Textract jobs."""
    
    def upload_for_ocr(self, document_bytes: bytes, document_id: int) -> str:
        """Upload document to S3, return S3 URI."""
        ...
    
    def delete_temp_file(self, s3_key: str) -> None:
        """Delete temp file after OCR completes."""
        ...
```

### 4) Celery Task Pattern (Split Tasks)

For async OCR (documents ≥5MB), use a callback chain:

```
process_document_async
  → PDFTextExtractor detects OCR needed + doc ≥5MB
  → Calls start_textract_async_job.delay()
  → Returns early (document status: 'ocr_pending')

start_textract_async_job
  → Uploads to S3
  → Calls Textract StartDocumentAnalysis
  → Schedules poll_textract_job.delay(job_id, countdown=10)

poll_textract_job
  → Checks job status
  → If complete: retrieves results, deletes S3 file, chains to continue_document_processing
  → If in progress: reschedules self with exponential backoff
  → If failed: marks document failed, creates review queue entry

continue_document_processing
  → Receives OCR text
  → Continues with AI analysis → FHIR conversion → merge
```

### 5) Metadata Storage (No New Models)

Use existing fields:
- `ParsedData.structured_extraction_metadata` for OCR metrics
- `Document.error_log` for OCR failures or warnings
- `Document.processing_message` for user-visible error messages

### 6) Audit Logging (Existing AuditLog)

Add these audit events:
- `ocr_sync_completed` - Sync OCR finished
- `ocr_async_job_started` - Async job submitted (includes job_id)
- `ocr_async_job_polling` - Polling attempt (for debugging)
- `ocr_async_job_completed` - Async job finished successfully
- `ocr_async_job_timeout` - Async job exceeded time limit
- `ocr_async_job_failed` - Async job failed
- `ocr_temp_upload` - File uploaded to S3 for OCR
- `ocr_temp_delete` - Temp file deleted from S3

---

## Configuration

Add to `meddocparser/settings/base.py`:

```python
# AWS OCR Configuration
OCR_ENABLED = config('OCR_ENABLED', default=True, cast=bool)
OCR_SELECTIVE_ENABLED = config('OCR_SELECTIVE_ENABLED', default=True, cast=bool)
OCR_TEXT_THRESHOLD = config('OCR_TEXT_THRESHOLD', default=50, cast=int)
OCR_ASYNC_THRESHOLD_MB = config('OCR_ASYNC_THRESHOLD_MB', default=5, cast=int)

# AWS Credentials (local dev fallback - production uses IAM roles)
AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID', default=None)
AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY', default=None)
AWS_DEFAULT_REGION = config('AWS_DEFAULT_REGION', default='us-east-1')

# S3 OCR Temp Bucket
OCR_S3_BUCKET = config('OCR_S3_BUCKET', default=None)
OCR_S3_PREFIX = config('OCR_S3_PREFIX', default='ocr-temp/')

# Textract Settings
TEXTRACT_FEATURE_TYPES = ['TABLES', 'FORMS']  # AnalyzeDocument features
TEXTRACT_ASYNC_POLL_INTERVAL = config('TEXTRACT_ASYNC_POLL_INTERVAL', default=10, cast=int)
TEXTRACT_ASYNC_MAX_WAIT = config('TEXTRACT_ASYNC_MAX_WAIT', default=300, cast=int)  # 5 minutes
```

Add to `.env.example`:

```bash
# AWS OCR Configuration
OCR_ENABLED=true
OCR_SELECTIVE_ENABLED=true
OCR_TEXT_THRESHOLD=50
OCR_ASYNC_THRESHOLD_MB=5

# AWS Credentials (for local development - production uses IAM roles)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-1

# S3 OCR Temp Bucket
OCR_S3_BUCKET=your-project-ocr-temp-dev
OCR_S3_PREFIX=ocr-temp/
```

---

## Error Handling

### No Fallback Policy

If Textract fails, the document **fails**. No fallback to local Tesseract.

### Error Flow

1. Textract returns error or times out
2. `PDFExtractionError` is raised with error details
3. Document status set to `'failed'`
4. `Document.processing_message` populated with user-friendly error
5. Review queue entry created with `'OCR failed - manual review needed'`
6. Audit log entry created with error details (no PHI)

### Retry Logic

- Sync OCR: No automatic retry (fast fail)
- Async OCR: Celery task retries with exponential backoff (3 attempts max)
- Throttling errors (429): Longer backoff (60s, 120s, 240s)

---

## HIPAA & Security

### Data Protection

- Document files remain encrypted at rest via `EncryptedFileField`
- S3 temp files encrypted with SSE-S3
- Temp files deleted immediately after OCR retrieval
- 24-hour lifecycle rule as safety net

### Audit Requirements

- All OCR operations logged to `AuditLog`
- Audit events contain metadata only (document_id, page_count, duration)
- **Never log extracted text or page content**

### Network Security

- Textract API calls over HTTPS
- S3 access via HTTPS only
- No public bucket access

---

## Testing Strategy

### Requirements

- **AWS sandbox credentials required** for all testing (no mocks)
- Use real anonymized documents for integration tests

### Unit Tests (`apps/documents/tests/test_textract.py`)

- TextractService correctly parses Textract response format
- Page text extraction preserves page separators
- Error handling for various Textract error codes
- S3 upload/delete operations work correctly

### Integration Tests (`apps/documents/tests/test_ocr_integration.py`)

- Text-only PDF → `extraction_method=embedded_text` (no Textract call)
- Image-only PDF → `extraction_method=external_ocr` (Textract called)
- Hybrid PDF → selective OCR, merged output preserves page order
- Large document (>5MB) → async flow completes successfully
- OCR failure → document marked failed, review queue entry created
- `process_document_async` continues to produce `ParsedData` and merge FHIR

### Performance Tests

- Sync OCR completes within 30 seconds for typical documents
- Async OCR completes within 5 minutes for large documents
- No regression on text-based PDFs (should stay <2s)

---

## Observability

### Metrics (via performance_monitor)

- `ocr.extraction_time_ms` - Time spent in OCR step
- `ocr.pages_external` - Pages sent to Textract
- `ocr.pages_local` - Pages extracted locally (pdfplumber)
- `ocr.documents_by_route` - Count by extraction_method
- `ocr.async_jobs_started` - Async job submissions
- `ocr.async_jobs_completed` - Successful async completions
- `ocr.async_jobs_failed` - Failed async jobs

### Error Tracking (via ErrorMetrics)

- Textract API error rates by error code
- Timeout rates for sync vs async
- S3 upload/delete failure rates

---

## Implementation Phases

### Phase 1: AWS Infrastructure Setup (1 week)

**Tasks:**
1. Create S3 bucket with lifecycle rule and bucket policy
2. Create IAM policy for Textract + S3 access
3. Attach IAM role to EC2/ECS (production)
4. Add AWS credentials to local dev environment
5. Add configuration settings to `base.py` and `.env.example`
6. Verify AWS connectivity with simple boto3 test

**Acceptance Criteria:**
- S3 bucket exists with correct permissions
- IAM role can call Textract and access S3
- Local dev can authenticate with env vars
- `boto3` can list bucket contents from Django shell

### Phase 2: Textract Sync Integration (2 weeks)

**Tasks:**
1. Create `TextractService` class with `analyze_document_sync()`
2. Create `TextractResult` dataclass for response parsing
3. Implement text extraction from Textract `WORD` and `LINE` blocks
4. Add page separator formatting (`--- Page N (OCR) ---`)
5. Update `PDFTextExtractor` to call Textract for sync OCR
6. Add sync OCR audit logging
7. Write unit tests for TextractService
8. Write integration test for image-only PDF

**Acceptance Criteria:**
- Image-only PDF processed successfully via Textract
- Output format matches existing OCR format
- Audit log contains `ocr_sync_completed` event
- No regression on text-based PDFs

### Phase 3: Async Mode for Large Documents (2 weeks)

**Tasks:**
1. Create `OCRTempStorage` class for S3 upload/delete
2. Add `start_async_analysis()` and `get_async_result()` to TextractService
3. Create `start_textract_async_job` Celery task
4. Create `poll_textract_job` Celery task with exponential backoff
5. Create `continue_document_processing` Celery task
6. Update `PDFTextExtractor` to detect large docs and trigger async flow
7. Add async OCR audit logging
8. Write integration test for large document async flow

**Acceptance Criteria:**
- Documents ≥5MB processed via async flow
- S3 temp files deleted after OCR completes
- Async job polling works with backoff
- Document processing completes end-to-end

### Phase 4: Selective OCR for Hybrid Documents (1 week)

**Tasks:**
1. Implement page-level text detection in `PDFTextExtractor`
2. Add threshold-based classification (text vs image page)
3. Extract only image pages via Textract
4. Merge OCR text with embedded text preserving page order
5. Add `extraction_method=hybrid` tracking
6. Write integration test for hybrid PDF

**Acceptance Criteria:**
- Hybrid PDFs only send image pages to Textract
- Merged output has correct page order
- Metrics show reduced OCR page count for hybrid docs

### Phase 5: Hardening & Error Handling (1 week)

**Tasks:**
1. Implement error handling for all Textract error codes
2. Add retry logic for transient failures
3. Implement review queue entry creation on OCR failure
4. Add threshold tuning mechanism (configurable, log distribution)
5. Add all monitoring metrics
6. Document threshold tuning process
7. Final integration test suite

**Acceptance Criteria:**
- Failed OCR creates review queue entry with clear message
- Throttling errors handled with appropriate backoff
- Metrics dashboard shows OCR health
- Threshold is tunable via settings

---

## Success Criteria

### Must Have

- Text-based PDFs stay <2s p95 (no regression)
- OCR step completes <60s p95 (sync and async)
- No regression in `process_document_async` success rate (>99%)
- External OCR cost <$20/month at current scale
- Failed OCR documents appear in review queue with clear error message

### Should Have

- Selective OCR reduces Textract pages by ≥20% for hybrid docs
- Textract error rate <2%
- Async jobs complete within 5 minutes

---

## Dependencies

### Python Packages (add to requirements.txt)

```
boto3>=1.34.0
```

### AWS Services

- Amazon Textract
- Amazon S3

### Existing Infrastructure

- Celery workers (existing)
- Redis (existing, for Celery)
- PostgreSQL (existing, for audit logs)

---

## Appendix: Updated Pipeline Flow

```
DocumentUploadView
  → process_document_async (Celery)
     → PDFTextExtractor.extract_text
        → pdfplumber (embedded text check)
        → [If OCR needed + <5MB] TextractService.analyze_document_sync
        → [If OCR needed + ≥5MB] start_textract_async_job.delay → RETURN EARLY
     → DocumentAnalyzer (Claude/OpenAI)
     → StructuredDataConverter
     → ParsedData + optimistic FHIR merge
     → audit_extraction_decision + audit_merge_operation

Async OCR Flow (≥5MB):
  start_textract_async_job
     → OCRTempStorage.upload_for_ocr
     → TextractService.start_async_analysis
     → poll_textract_job.delay (scheduled)

  poll_textract_job
     → TextractService.get_async_result
     → [If complete] OCRTempStorage.delete_temp_file → continue_document_processing.delay
     → [If in progress] poll_textract_job.delay (backoff)
     → [If failed] Mark document failed + review queue entry

  continue_document_processing
     → Receives OCR text
     → DocumentAnalyzer (Claude/OpenAI)
     → StructuredDataConverter
     → ParsedData + optimistic FHIR merge
     → audit_extraction_decision + audit_merge_operation
```

---

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| 2.1 | 2026-01-14 | Initial architecture-aligned draft |
| 3.0 | 2026-01-27 | Resolved all open questions, added S3 infrastructure, committed to Textract, removed fallback, detailed Celery task pattern |
| 3.1 | 2026-01-27 | Added TaskMaster Build Guidance section for task generation |

---

## TaskMaster Build Guidance

### Recommended Task Breakdown

**Parent Task**: "Implement AWS Textract OCR Integration"

**Subtasks**:

1. **Add boto3 dependency** - Add boto3>=1.34.0 to requirements.txt and verify installation in virtual environment

2. **Create S3 OCR temp bucket** - Create dedicated S3 bucket with SSE-S3 encryption, blocked public access, and 24-hour lifecycle rule for auto-deletion. Document bucket name pattern: `{project}-ocr-temp-{environment}`

3. **Create IAM policy for Textract and S3** - Create IAM policy with textract:AnalyzeDocument, textract:StartDocumentAnalysis, textract:GetDocumentAnalysis permissions plus S3 PutObject/GetObject/DeleteObject for OCR bucket. Attach to EC2/ECS role for production.

4. **Add AWS configuration to Django settings** - Add OCR_ENABLED, OCR_TEXT_THRESHOLD, OCR_ASYNC_THRESHOLD_MB, AWS credentials, OCR_S3_BUCKET settings to `meddocparser/settings/base.py` using python-decouple pattern. Update `.env.example` with all new variables.

5. **Create TextractResult dataclass** - Create dataclass in `apps/documents/services/textract.py` to hold parsed Textract response with pages, text blocks, confidence scores, and metadata.

6. **Create TextractService with sync analysis** - Implement `TextractService` class with `analyze_document_sync()` method that calls Textract AnalyzeDocument API for documents <5MB. Include TABLES and FORMS feature types.

7. **Implement Textract response text extraction** - Add `extract_text_from_result()` method to TextractService that converts Textract WORD/LINE blocks to plain text with page separators matching existing format (`--- Page N (OCR) ---`).

8. **Create OCRTempStorage service for S3** - Create `apps/documents/services/s3_upload.py` with `OCRTempStorage` class implementing `upload_for_ocr()` and `delete_temp_file()` methods using boto3 S3 client.

9. **Add async Textract methods to TextractService** - Implement `start_async_analysis()` that calls StartDocumentAnalysis API with S3 location, and `get_async_result()` that calls GetDocumentAnalysis to retrieve results.

10. **Create start_textract_async_job Celery task** - Add new Celery task in `apps/documents/tasks.py` that uploads document to S3 via OCRTempStorage, starts async Textract job, and schedules poll task.

11. **Create poll_textract_job Celery task** - Add Celery task that polls Textract job status with exponential backoff (10s, 20s, 40s), retrieves results on completion, deletes S3 temp file, and chains to continue_document_processing.

12. **Create continue_document_processing Celery task** - Add Celery task that receives OCR text and continues document pipeline (DocumentAnalyzer, FHIR conversion, merge) for documents that went through async OCR flow.

13. **Update PDFTextExtractor with page-level text detection** - Modify `extract_text()` in `apps/documents/services.py` to track per-page character counts using pdfplumber and classify pages as text (>=50 chars) or image (<50 chars).

14. **Integrate TextractService into PDFTextExtractor for sync OCR** - Update PDFTextExtractor to call `TextractService.analyze_document_sync()` for documents <5MB when OCR is needed, replacing local Tesseract fallback.

15. **Integrate async OCR flow into PDFTextExtractor** - Update PDFTextExtractor to detect documents >=5MB needing OCR, trigger `start_textract_async_job.delay()`, and return early with 'ocr_pending' status.

16. **Implement selective OCR for hybrid documents** - Update PDFTextExtractor to OCR only image pages (not entire document) for hybrid PDFs, then merge OCR text with embedded text preserving page order.

17. **Implement OCR error handling with review queue** - Add error handling for Textract failures: raise PDFExtractionError, set document status to 'failed', populate processing_message, create review queue entry with 'OCR failed - manual review needed'.

18. **Add OCR audit logging events** - Add audit events to AuditLog: ocr_sync_completed, ocr_async_job_started, ocr_async_job_completed, ocr_async_job_failed, ocr_temp_upload, ocr_temp_delete. Log metadata only (no PHI).

19. **Add OCR metrics to monitoring** - Add metrics to performance_monitor: ocr.extraction_time_ms, ocr.pages_external, ocr.pages_local, ocr.documents_by_route. Add Textract error rates to ErrorMetrics.

20. **Write unit tests for TextractService** - Create `apps/documents/tests/test_textract.py` with tests for response parsing, text extraction with page separators, error code handling. Requires AWS sandbox credentials.

21. **Write integration tests for OCR flows** - Create `apps/documents/tests/test_ocr_integration.py` with tests for: text-only PDF (no OCR), image-only PDF (sync OCR), hybrid PDF (selective OCR), large document (async flow), OCR failure (review queue entry).

22. **Remove local Tesseract OCR code** - Delete `extract_with_ocr()` method from PDFTextExtractor and remove pytesseract/pdf2image imports. Update requirements.txt to remove pytesseract and pdf2image dependencies.

### Dependencies Between Subtasks

```
Foundation (parallel):
  1 (boto3) ─┬─→ 5, 6, 8
  2 (S3 bucket) ─┤
  3 (IAM policy) ─┤
  4 (Django config) ─┘

Sync OCR path:
  5 (dataclass) → 6 (sync service) → 7 (text extraction) → 14 (PDFTextExtractor sync)

Async OCR path:
  8 (S3 upload) ─┬─→ 9 (async methods) → 10, 11, 12 (Celery tasks) → 15 (PDFTextExtractor async)
  6 (sync service) ─┘

Integration:
  14, 15 → 13 (page detection) → 16 (selective OCR)

Error handling & observability (parallel with 16):
  14, 15 → 17 (error handling)
  14, 15 → 18 (audit logging)
  14, 15 → 19 (metrics)

Testing & cleanup:
  6, 7, 8, 9 → 20 (unit tests)
  14, 15, 16, 17 → 21 (integration tests)
  21 → 22 (remove Tesseract)
```

### Testing Strategy

- **Unit tests**: TextractService parsing, S3 operations, text extraction formatting
- **Integration tests**: Full OCR flows with real AWS calls (sandbox credentials required)
- **Test documents**: Use real anonymized medical documents (no mocking Textract)
- **Coverage targets**: 
  - Text-only PDF → extraction_method=embedded_text, no Textract call
  - Image-only PDF → extraction_method=external_ocr, sync Textract
  - Hybrid PDF → extraction_method=hybrid, selective page OCR
  - Large document (>5MB) → async flow with S3 upload
  - OCR failure → document failed, review queue entry created
- **Performance**: Verify text PDFs stay <2s, no regression from OCR routing logic

### Estimated Complexity

**Overall: 7/10 (Medium-High)**

| Component | Complexity | Notes |
|-----------|------------|-------|
| AWS infrastructure | 3/10 | Mostly configuration, well-documented |
| TextractService sync | 4/10 | Standard boto3 API calls |
| TextractService async | 6/10 | Job polling, error states |
| Celery task chain | 8/10 | Most complex - state management, backoff, chaining |
| PDFTextExtractor integration | 5/10 | Modify existing code carefully |
| Selective OCR | 6/10 | Page-level logic, merge ordering |
| Error handling | 5/10 | Follow existing patterns |

### Files to Create

- `apps/documents/services/textract.py` - TextractService, TextractResult
- `apps/documents/services/s3_upload.py` - OCRTempStorage
- `apps/documents/tests/test_textract.py` - Unit tests
- `apps/documents/tests/test_ocr_integration.py` - Integration tests

### Files to Modify

- `requirements.txt` - Add boto3, remove pytesseract/pdf2image
- `meddocparser/settings/base.py` - Add AWS/OCR configuration
- `.env.example` - Add AWS environment variables
- `apps/documents/services.py` - Modify PDFTextExtractor
- `apps/documents/tasks.py` - Add async OCR Celery tasks
- `apps/core/models.py` - Add OCR audit event types (if enum-based)

### Risk Mitigation

- **AWS credentials in CI/CD**: Use GitHub secrets or similar for test credentials
- **Async job timeout**: Set TEXTRACT_ASYNC_MAX_WAIT=300s, fail gracefully
- **Cost overruns**: Monitor Textract API calls, selective OCR reduces volume
- **Breaking existing flow**: Keep text PDF path unchanged, only modify OCR branch
