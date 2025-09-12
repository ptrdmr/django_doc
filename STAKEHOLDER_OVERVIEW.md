## Project Overview (Stakeholder Brief)

- **TL;DR**: Core ingestion, FHIR accumulation/merge, and HIPAA controls are implemented. Next up: human-in-the-loop review UI, reporting suite, IP restrictions, email delivery, and final integration.
- **As of**: 2025-09-08 18:54:01

## System Flow (End-to-End)

```text
Upload → Async processing (Celery/Redis) → PDF text extraction → LLM extraction (Claude; GPT fallback)
→ Robust JSON parsing → FHIR conversion & validation → Merge into cumulative patient bundle (JSONB)
→ Provenance + versioning + dedup → Patient/Provider UIs (search on non‑PHI)
```

- **Upload & queueing**: Documents are uploaded and placed on a Celery queue (keeps web responsive).
- **AI extraction with fallbacks**: Anthropic Claude primary; OpenAI fallback for resilience.
- **FHIR-first storage**: Extracted data becomes FHIR resources and is merged append-only with provenance.
- **Patient/Provider modules**: Complete CRUD, relationships, and safe search (no PHI in search fields).
- **Security/HIPAA**: Field-level encryption, audit logging, RBAC, rate limiting, optional 2FA, secure settings.
- **Stability**: Multi-strategy JSON parsing, chunking for large docs, retries/backoff, cost/token tracking.

## Why These Tools (Key Choices)

- **Django 5 + DRF**: Mature, secure stack; DRF positions us for partner APIs.
- **PostgreSQL JSONB**: Efficient, indexed storage for rich FHIR bundles.
- **Celery + Redis**: Offloads heavy IO/LLM work; time limits, retries, scale-out workers.
- **fhir.resources**: Spec-compliant FHIR objects and validation.
- **django-cryptography-5**: Field-level PHI encryption at rest.
- **django-allauth + django-otp + django-axes + ratelimit**: Hardened auth, MFA option, abuse protection.
- **htmx + Tailwind (+ Alpine where needed)**: Snappy UX via partial updates, minimal JS.
- **pdfplumber/pdfminer.six, PyPDF2**: Robust PDF text extraction across varied medical documents.
- **WeasyPrint/ReportLab**: Standards-based PDF generation for reporting (used in reports work).
- **sentry-sdk + structlog**: Traceability and structured logs for operations and audits.

## Current Capabilities

- **Patient management**: Encrypted PHI, cumulative FHIR record, provenance, safe search on non‑PHI.
- **Provider management**: Directory, specialties, links to patients/documents.
- **FHIR pipeline**: Conversion, merge, dedup, conflict detection/resolution, referential integrity, metrics.
- **Document ingestion**: Chunking, resilient JSON parsing, cost/token monitoring, robust error recovery.
- **Security & compliance**: RBAC, audit logging, secure headers/cookies, CSRF, optional MFA.

## Known Limitations

- **Human review required**: AI extraction can be imperfect; review/approval UI will precede merges.
- **PDF variability**: Low-quality scans/layouts reduce quality; mitigated but not eliminated.
- **Code systems**: Ongoing normalization across coding systems and free text.
- **Operational scale**: Will add dashboards/autoscaling as usage grows.
- **Key management**: Encryption works; formal rotation and HSM/KMS are deployment hardening tasks.
- **Costs**: AI spend tracked; throttling/budget alerts are on the roadmap.

## Project Status

- **Top-level tasks**: 15/24 completed (62.5%).
- **Subtasks**: 98/110 completed (89.1%).

## Near-Term Roadmap (Next)

- **Document Review Interface (Task 13)**
  - PDF preview (done), next: highlight mapping, patient/data review forms, HTMX partial validations,
    approval workflow, and merge-on-approval.
- **Reports (Tasks 15–18)**
  - Reports infrastructure → Patient Summary → Provider Activity → Processing/Ops metrics.
- **User Account Management (Task 10)**
  - Profiles, preferences, activity history.
- **IP-based Access Restrictions (Task 24)**
  - Network-range allowlists; integrate with RBAC/audit.
- **Email Service for Invitations (Task 29)**
  - Configure SES/SendGrid/Gmail for provider invitations.
- **Final System Integration (Task 23)**
  - Cross-module tests, perf passes, deployment prep and checks.

## Stakeholder Demo (5–7 Minutes)

- **Upload a sample PDF** → show immediate queueing/status.
- **Processing overview**: tokens/costs, retries, error handling.
- **Open patient record**: appended FHIR with provenance/versioning.
- **Security posture**: encrypted fields at DB, RBAC-limited views, audit trails.
- **Preview Review UI**: highlights, edit/approve, safe merge.
- **Preview Reports**: Patient Summary and Ops Metrics PDFs.

## Success Metrics

- **Data capture rate**: Target >90% for core FHIR types.
- **Time-to-ingest**: Minutes from upload to merged record for typical docs.
- **Reviewer efficiency**: Cut manual correction time by 50–70%.
- **Security posture**: 0 PHI-in-logs; verified encryption; add IP restrictions and key rotation.

## Risks & Mitigations

- **Model drift/vendor changes** → Dual-vendor fallback; version pinning; regression tests.
- **Complex FHIR edge cases** → Resource-specific handlers/tests; append-only with provenance.
- **Scale spikes** → Horizontal workers; queue backpressure; AI cost circuit breakers.

*Updated: 2025-09-08 18:54:01 | Stakeholder overview created*
