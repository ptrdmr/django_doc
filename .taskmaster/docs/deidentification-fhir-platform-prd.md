# De-Identification + FHIR Conversion Platform PRD

> **Purpose:** Evolve the medical document parser from a single-mode patient summary tool into a dual-mode platform that also offers de-identification and FHIR conversion as a service.

> **Granular PRDs:** This PRD has been split into feature-focused sub-PRDs for easier parsing:
> - [01-foundation-infrastructure-prd.md](deid-platform/01-foundation-infrastructure-prd.md)
> - [02-deidentification-engine-prd.md](deid-platform/02-deidentification-engine-prd.md)
> - [03-pipeline-integration-prd.md](deid-platform/03-pipeline-integration-prd.md)
> - [04-api-gateway-prd.md](deid-platform/04-api-gateway-prd.md)

---

## Overview

The platform currently processes medical documents into FHIR-compliant patient histories for hospice and clinical workflows (Mode A: Patient Summary). This initiative adds a second processing mode (Mode B: De-Identification) that strips Protected Health Information from extracted clinical data and returns clean, HIPAA Safe Harbor-compliant FHIR R4 bundles via a REST API.

Both modes share the same document ingestion and AI extraction pipeline. They diverge after structured extraction: Mode A merges PHI-bearing FHIR data into a patient record; Mode B de-identifies the extraction and returns a standalone FHIR bundle with no PHI retained.

### Problem Statement

- The hospice patient summary market may not sustain the product on its own
- The document ingestion, AI extraction, and FHIR conversion infrastructure represents 1+ year of engineering that is underutilized
- Health tech companies, researchers, and data platforms need de-identified clinical data in FHIR format but lack the pipeline to produce it
- Generic AI tools can extract text from documents but cannot produce compliant de-identification with audit trails, FHIR R4 validation, or conflict resolution

### Solution

Add a de-identification engine and API gateway on top of the existing pipeline:

- Accept documents or raw text via REST API
- Extract structured clinical data using the existing AI pipeline (Claude/GPT with Pydantic models)
- De-identify using HIPAA Safe Harbor rules (18 identifier types)
- Convert to validated FHIR R4 bundles
- Return results via API response, polling, or webhook
- Optionally purge source documents after processing

### Value Proposition

**For existing customers (Mode A):** No change. The patient summary workflow continues to function exactly as it does today.

**For de-ID customers (Mode B):**
- Submit medical documents, receive clean FHIR bundles with no PHI
- Compliance-ready output with audit trail of what was de-identified
- 11 FHIR resource types extracted and validated
- Configurable de-identification profiles (full Safe Harbor, date-shift only, custom)
- No need to build or maintain their own extraction/FHIR pipeline

**For the business:**
- Reduced HIPAA compliance burden (Mode B handles PHI transiently, not as a data store)
- Existing infrastructure reused at ~70% -- the pivot is additive, not a rewrite
- Two revenue streams from one pipeline

---

## Dual-Mode Architecture

```
                    ┌───────────────────────────────────────┐
                    │        SHARED PIPELINE                │
                    │                                       │
  Document Input ──►│  1. Text Extraction                   │
  (Upload or API)   │     (pdfplumber / AWS Textract)       │
                    │                                       │
                    │  2. AI Structured Extraction           │
                    │     (Claude primary / GPT fallback)    │
                    │     → StructuredMedicalExtraction      │
                    │                                       │
                    └───────────────┬───────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
              ┌─────▼──────┐                 ┌──────▼──────┐
              │  MODE A    │                 │  MODE B     │
              │  Patient   │                 │  De-ID +    │
              │  Summary   │                 │  FHIR API   │
              └─────┬──────┘                 └──────┬──────┘
                    │                               │
              ┌─────▼──────┐                 ┌──────▼──────┐
              │ FHIR       │                 │ De-identify │
              │ conversion │                 │ extracted   │
              │ (with PHI) │                 │ data        │
              ├────────────┤                 ├─────────────┤
              │ Merge into │                 │ FHIR R4     │
              │ Patient    │                 │ Bundle      │
              │ record     │                 │ (no PHI)    │
              ├────────────┤                 ├─────────────┤
              │ Review     │                 │ Return via  │
              │ workflow   │                 │ API/webhook │
              ├────────────┤                 ├─────────────┤
              │ Patient    │                 │ Purge       │
              │ hub UI     │                 │ source doc  │
              └────────────┘                 └─────────────┘
```

**Branch point:** The `processing_mode` field on the ProcessingJob (or Document) determines which path runs after AI extraction. Steps 1 and 2 are identical for both modes.

---

## User Personas

### Persona 1: Clinical Data Specialist (Mode A -- Existing)

- Works in hospice or clinical setting
- Uploads 20-50 documents per day across multiple patients
- Needs to see unified patient history to assess qualification
- Uses the web portal and patient detail pages
- No change to their workflow

### Persona 2: Health Tech Developer (Mode B -- New)

- Building an EHR, telehealth platform, or health data product
- Has medical documents (PDFs, scanned records) they need structured
- Needs FHIR R4 output for interoperability
- Needs PHI stripped for downstream use (analytics, ML training, sharing)
- Integrates via REST API into their own pipeline
- Cares about: API reliability, response time, FHIR spec compliance, de-ID accuracy

### Persona 3: Clinical Researcher (Mode B -- New)

- Works at a research institution or CRO
- Has a corpus of clinical documents to de-identify for a study
- May submit documents in batches (10-100 at a time)
- Needs Safe Harbor compliance documentation for IRB approval
- Cares about: compliance certification, de-ID completeness, batch processing

---

## Key User Flows

### Flow 1: API Document Submission (Mode B)

1. Developer authenticates with API key
2. POSTs a PDF document to `/api/v1/documents/` with de-ID profile selection
3. Receives job ID and status URL
4. Polls status URL (or receives webhook) until processing completes
5. GETs the de-identified FHIR R4 bundle from the result endpoint
6. Source document is purged after TTL expires

### Flow 2: API Text Submission (Mode B)

1. Developer POSTs raw clinical text to `/api/v1/text/`
2. Skips OCR/text extraction (steps directly to AI extraction)
3. Same de-identification and result retrieval flow as Flow 1

### Flow 3: Patient Summary (Mode A -- Unchanged)

1. Clinical user uploads document via web portal
2. Document is processed, FHIR data merged into patient record
3. User views patient summary, downloads PDF
4. Existing review workflow applies

---

## Logical Dependency Chain

```
Phase 1: Foundation & Infrastructure
├── ProcessingJob, APIClient, ProcessingResult models
├── FHIR R4 Bundle compliance (assemble_r4_bundle, validate)
├── Configuration and settings
└── Database migrations

Phase 2: De-Identification Engine (depends on Phase 1)
├── Safe Harbor 18-identifier mapping
├── De-identification strategies (redact, date-shift, generalize, tag)
├── Configurable profiles
├── PHI leakage validator
└── Audit logging for de-ID actions

Phase 3: Pipeline Integration (depends on Phase 1 + 2)
├── Mode A/B branching in task pipeline
├── AI prompt PHI annotation enhancement
├── Mode B Celery task chain
├── Document purge task
└── Mode A regression verification

Phase 4: API Gateway (depends on Phase 1 + 3)
├── API key authentication
├── Document submission endpoint
├── Text submission endpoint
├── Job status and result endpoints
├── Rate limiting and throttling
├── Webhook delivery
└── OpenAPI documentation
```

### MVP Path

Phase 1 + Phase 2 + a minimal version of Phase 3 (hardcoded Mode B task, no branching) + a single API endpoint (POST document, synchronous response) constitutes a demonstrable MVP. This can be shown to potential customers before building the full async API.

### Atomic Feature Boundaries

- Phase 1 is standalone (infrastructure only, no behavior changes)
- Phase 2 is standalone (engine can be tested in isolation with unit tests)
- Phase 3 requires Phase 1 (models) and Phase 2 (engine)
- Phase 4 requires Phase 1 (models) and Phase 3 (pipeline wired up)
- Mode A is never modified -- existing tests should continue to pass at every phase

---

## Risks and Mitigations

### Risk 1: Incomplete De-Identification (PHI Leakage)

Free-text fields like `DiagnosticReport.findings`, `CarePlan.plan_description`, and `SourceContext.text` may contain embedded PHI that isn't captured by structured field-level de-identification.

**Mitigation:** Secondary regex/pattern sweep on all free-text output fields. PHI leakage validator checks for SSN patterns, phone patterns, date patterns, and common name patterns. Confidence scoring on de-ID completeness.

### Risk 2: Regulatory Correctness of Safe Harbor Implementation

HIPAA Safe Harbor requires removal or generalization of all 18 identifier types. Getting this wrong has legal consequences.

**Mitigation:** Map every identifier to specific extraction fields. Date-shifting preserves intervals (clinically useful) while removing exact dates. Postal codes generalized to 3-digit prefix. Build comprehensive test suite covering each identifier type. Consider legal review of the mapping before launch.

### Risk 3: Mode A Regression

Changes to the shared pipeline (AI extraction prompts, task routing) could break the existing patient summary workflow.

**Mitigation:** Mode A code paths are not modified. PHI annotation is additive to the extraction prompt (new field, existing fields unchanged). Pipeline branching is controlled by a field on the job, not by modifying existing task logic. Full Mode A regression test suite runs on every change.

### Risk 4: Performance Impact of De-Identification

Adding a de-identification step increases per-document processing time.

**Mitigation:** De-identification operates on the already-extracted Pydantic model (small data structure, not raw text). Expected overhead is <500ms per document. No additional AI/LLM calls required for de-identification itself.

### Risk 5: Multi-Tenancy Isolation

Mode A customers' data and Mode B customers' data must be strictly isolated.

**Mitigation:** Mode A uses existing Patient/Document models with organization scoping. Mode B uses separate ProcessingJob/ProcessingResult models. No shared data between modes except the processing pipeline code itself (which is stateless).

---

## Compliance Posture

### Mode A (Patient Summary)

Full HIPAA compliance required. PHI stored long-term in encrypted fields. BAA required with hosting provider. Audit logging for all PHI access.

### Mode B (De-Identification)

Reduced HIPAA exposure:
- PHI is handled transiently during processing (seconds to minutes)
- Source documents purged after configurable TTL (default 24 hours)
- Output contains no PHI (Safe Harbor compliant)
- De-identified data is not PHI under HIPAA -- downstream users do not need a BAA for the output
- Audit log records what was de-identified but does not store the original PHI values
- The brief PHI exposure during processing still requires security controls (encryption in transit, encrypted at rest during TTL, access controls)

This posture is significantly simpler and cheaper to maintain than Mode A's full PHI storage requirements.

---

## Existing Code References

### Shared Pipeline (Used by Both Modes)

- `apps/documents/services.py` -- `PDFTextExtractor.extract_text()` for document text extraction
- `apps/documents/services/ai_extraction.py` -- `StructuredMedicalExtraction` and 13 Pydantic models (lines 128-348)
- `apps/documents/services/ai_extraction.py` -- `extract_medical_data_structured()` for AI extraction
- `apps/documents/tasks.py` -- `process_document_async()` for Celery orchestration
- `apps/fhir/converters.py` -- `StructuredDataConverter.convert_structured_data()` for FHIR conversion
- `apps/fhir/bundle_utils.py` -- Bundle assembly and deduplication utilities
- `apps/fhir/deduplication.py` -- `ResourceDeduplicator` for FHIR resource deduplication

### Mode A Only (Unchanged)

- `apps/patients/models.py` -- `Patient.add_fhir_resources()` for FHIR merge into patient record
- `apps/documents/models.py` -- `Document` and `ParsedData` models
- `apps/fhir/merge_handlers.py` -- Conflict resolution strategies

### Infrastructure

- `meddocparser/settings/base.py` -- Django settings, `INSTALLED_APPS`, middleware
- `meddocparser/urls.py` -- Root URL configuration
- `apps/core/models.py` -- `BaseModel`, `MedicalRecord`, `AuditLog`, `APIUsageLog`
- `docker-compose.yml` -- PostgreSQL, Redis, Celery, Flower

---

## TaskMaster Integration

**Recommended approach:** Create a new tag `deid-platform` and parse each sub-PRD as 1 task, then expand into subtasks.

```bash
task-master add-tag deid-platform --description="De-identification + FHIR conversion platform"

task-master parse-prd .taskmaster/docs/deid-platform/01-foundation-infrastructure-prd.md --tag=deid-platform --num-tasks=1
task-master parse-prd .taskmaster/docs/deid-platform/02-deidentification-engine-prd.md --tag=deid-platform --num-tasks=1 --append
task-master parse-prd .taskmaster/docs/deid-platform/03-pipeline-integration-prd.md --tag=deid-platform --num-tasks=1 --append
task-master parse-prd .taskmaster/docs/deid-platform/04-api-gateway-prd.md --tag=deid-platform --num-tasks=1 --append

task-master expand --id=1 --tag=deid-platform --num=8
task-master expand --id=2 --tag=deid-platform --num=12
task-master expand --id=3 --tag=deid-platform --num=10
task-master expand --id=4 --tag=deid-platform --num=12
```
