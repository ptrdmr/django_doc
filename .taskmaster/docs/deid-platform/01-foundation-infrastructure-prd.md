# Foundation & Infrastructure - PRD

> **Purpose:** Build the data models, configuration, and FHIR R4 Bundle compliance that underpin both the de-identification engine and the API gateway.

---

## Parent Context

Part of the **De-Identification + FHIR Conversion Platform** initiative. See [deidentification-fhir-platform-prd.md](../deidentification-fhir-platform-prd.md) for overall vision.

---

## Overview

This phase creates the foundational infrastructure for Mode B (de-identification) processing without modifying any Mode A (patient summary) behavior. It introduces job-based processing models, API client identity, and upgrades FHIR Bundle output to full R4 spec compliance.

### Problem Statement

- The current pipeline is patient-centric: every document must be linked to a Patient record. Mode B needs patient-free, job-based processing.
- FHIR output is stored as a bundle-like structure in `Patient.encrypted_fhir_bundle` but is not a formally compliant FHIR R4 Bundle resource.
- There is no concept of an API client or API key -- authentication is session-based for web users.
- No mechanism exists for time-limited processing results that auto-purge.

### Solution

- New `ProcessingJob` and `ProcessingResult` models for job-based, patient-independent processing
- New `APIClient` model for API key authentication and rate limiting
- Upgrade `apps/fhir/bundle_utils.py` to produce spec-compliant FHIR R4 Bundle resources
- Add webhook delivery tracking model
- Add configuration settings for de-identification and API behavior

---

## Design Decisions

**1. Separate models vs. extending Document**

New `ProcessingJob` model in a new `apps/api/` app rather than adding fields to `Document`. Rationale: keeps Mode A and Mode B concerns separate; avoids nullable foreign keys and conditional logic on existing models. The `Document` model continues to serve Mode A exclusively.

**2. API key storage**

API keys are hashed (SHA-256) before storage, similar to password hashing. The plaintext key is shown once at creation and never stored. This prevents key exposure even if the database is compromised.

**3. FHIR R4 Bundle compliance**

The `fhir.resources` library (already installed) provides `Bundle`, `BundleEntry`, and `Meta` classes. New functions wrap extracted FHIR resources into a formally valid Bundle with `resourceType: "Bundle"`, `type: "collection"`, unique `id`, `timestamp`, and proper `entry[].fullUrl` URIs.

**4. Job TTL and purge**

ProcessingResults have a configurable `expires_at` timestamp (default 72 hours). A Celery Beat periodic task purges expired jobs, their results, and any associated source files. This limits PHI exposure for Mode B.

---

## Technical Scope

### New App: `apps/api/`

Create a new Django app to house API-specific models. Views and serializers will be added in Sub-PRD 04 (API Gateway).

```
apps/api/
├── __init__.py
├── apps.py          (name = 'apps.api')
├── models.py        (APIClient, ProcessingJob, ProcessingResult, WebhookDelivery)
├── admin.py         (Admin registration for all models)
├── migrations/
└── managers.py      (Custom managers for active jobs, expired jobs)
```

### New Models

**APIClient**

| Field | Type | Notes |
|-------|------|-------|
| id | UUIDField (PK) | Auto-generated |
| name | CharField(100) | Human-readable client name |
| organization | ForeignKey(Organization, null=True) | Optional link to existing org model |
| api_key_prefix | CharField(8) | First 8 chars of key for identification (e.g., `sk_live_`) |
| api_key_hash | CharField(64) | SHA-256 hash of the full API key |
| allowed_modes | JSONField | List of allowed processing modes, e.g., `["deidentification"]` or `["patient_summary", "deidentification"]` |
| rate_limit_per_hour | IntegerField | Default 100. Requests per hour. |
| is_active | BooleanField | Default True |
| created_at | DateTimeField | Auto |
| last_used_at | DateTimeField(null=True) | Updated on each API call |
| metadata | JSONField(default=dict) | Flexible storage for billing info, notes |

**ProcessingJob**

| Field | Type | Notes |
|-------|------|-------|
| id | UUIDField (PK) | Auto-generated, used as job_id in API responses |
| api_client | ForeignKey(APIClient) | Who submitted this job |
| status | CharField | Choices: `queued`, `processing`, `completed`, `failed`, `expired` |
| processing_mode | CharField | Choices: `deidentification`, `patient_summary` |
| input_type | CharField | Choices: `file`, `text` |
| input_file | FileField(null=True) | Uploaded document (purged after TTL) |
| input_text | TextField(null=True) | Raw text input (encrypted, purged after TTL) |
| deidentification_profile | CharField(default='safe_harbor') | Which de-ID profile to use |
| output_format | CharField(default='fhir_r4_json') | Choices: `fhir_r4_json`, `fhir_r4_ndjson`, `raw_extracted` |
| webhook_url | URLField(null=True) | Where to POST results when done |
| error_message | TextField(null=True) | Error details if status is `failed` |
| created_at | DateTimeField | Auto |
| started_at | DateTimeField(null=True) | When processing began |
| completed_at | DateTimeField(null=True) | When processing finished |
| expires_at | DateTimeField | Default: created_at + PROCESSING_JOB_TTL_HOURS |
| metadata | JSONField(default=dict) | Processing metrics, page count, etc. |

**ProcessingResult**

| Field | Type | Notes |
|-------|------|-------|
| id | UUIDField (PK) | Auto-generated |
| job | OneToOneField(ProcessingJob) | One result per job |
| fhir_bundle | JSONField | The de-identified FHIR R4 Bundle |
| resource_count | IntegerField | Number of FHIR resources in the bundle |
| resource_types | JSONField | Dict of resource type counts, e.g., `{"Condition": 5, "Observation": 12}` |
| processing_time_ms | IntegerField | Total processing time in milliseconds |
| ai_model_used | CharField | Which AI model performed extraction |
| token_count | IntegerField | Tokens consumed by AI extraction |
| deidentification_summary | JSONField | Summary of what was de-identified (counts by identifier type, no PHI values) |
| created_at | DateTimeField | Auto |

**WebhookDelivery**

| Field | Type | Notes |
|-------|------|-------|
| id | UUIDField (PK) | Auto-generated |
| job | ForeignKey(ProcessingJob) | Which job triggered this delivery |
| url | URLField | Target URL |
| status | CharField | Choices: `pending`, `delivered`, `failed` |
| response_code | IntegerField(null=True) | HTTP status code from delivery attempt |
| attempts | IntegerField(default=0) | Number of delivery attempts |
| max_attempts | IntegerField(default=3) | Maximum retry attempts |
| last_attempt_at | DateTimeField(null=True) | When last attempt was made |
| next_retry_at | DateTimeField(null=True) | When to retry (exponential backoff) |
| created_at | DateTimeField | Auto |

### Custom Managers

```python
class ActiveJobManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().exclude(status='expired')

class ExpiredJobManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(
            expires_at__lt=timezone.now(),
            status__in=['completed', 'failed']
        )
```

### FHIR R4 Bundle Compliance

**Modify:** `apps/fhir/bundle_utils.py`

**New function: `assemble_r4_bundle()`**

```python
def assemble_r4_bundle(
    resources: List[Dict[str, Any]],
    bundle_id: Optional[str] = None,
    bundle_type: str = "collection",
    timestamp: Optional[str] = None
) -> Dict[str, Any]:
    """
    Wrap a list of FHIR resource dicts into a spec-compliant FHIR R4 Bundle.

    Returns a dict that validates against fhir.resources.bundle.Bundle.
    Includes proper entry[].fullUrl URNs and bundle-level metadata.
    """
```

**New function: `validate_bundle_r4()`**

```python
def validate_bundle_r4(bundle_dict: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate a bundle dict against the FHIR R4 spec using fhir.resources.

    Returns (is_valid, list_of_error_messages).
    """
```

**New function: `bundle_to_ndjson()`**

```python
def bundle_to_ndjson(bundle_dict: Dict[str, Any]) -> str:
    """
    Convert a FHIR Bundle to NDJSON format (one resource per line).

    Used for bulk FHIR data exchange.
    """
```

**Modify existing:** `create_initial_patient_bundle()` should internally use `assemble_r4_bundle()` to ensure Mode A also benefits from improved Bundle compliance.

### Configuration Settings

**Add to `meddocparser/settings/base.py`:**

```python
# De-Identification Settings
DEIDENTIFICATION_DATE_SHIFT_RANGE = config('DEID_DATE_SHIFT_RANGE', default=365, cast=int)
DEIDENTIFICATION_DEFAULT_PROFILE = config('DEID_DEFAULT_PROFILE', default='safe_harbor')
PROCESSING_JOB_TTL_HOURS = config('PROCESSING_JOB_TTL_HOURS', default=72, cast=int)
PROCESSING_JOB_MAX_FILE_SIZE_MB = config('PROCESSING_JOB_MAX_FILE_SIZE_MB', default=50, cast=int)

# API Settings
API_DEFAULT_RATE_LIMIT_PER_HOUR = config('API_RATE_LIMIT', default=100, cast=int)
API_KEY_HEADER_NAME = 'Authorization'
API_SYNC_TIMEOUT_SECONDS = config('API_SYNC_TIMEOUT', default=60, cast=int)

# Webhook Settings
WEBHOOK_TIMEOUT_SECONDS = config('WEBHOOK_TIMEOUT', default=30, cast=int)
WEBHOOK_MAX_RETRIES = config('WEBHOOK_MAX_RETRIES', default=3, cast=int)
WEBHOOK_RETRY_BACKOFF_BASE = 2  # Exponential backoff: 2^attempt seconds
```

**Add to `INSTALLED_APPS`:**

```python
LOCAL_APPS = [
    'apps.accounts',
    'apps.core',
    'apps.documents',
    'apps.patients',
    'apps.providers',
    'apps.fhir',
    'apps.reports',
    'apps.api',          # NEW
    'apps.deidentify',   # NEW (added in Sub-PRD 02)
]
```

---

## Implementation Checklist

1. Create `apps/api/` app with `apps.py`, `__init__.py`, `models.py`, `admin.py`, `managers.py`
2. Define `APIClient` model with key hashing and utility methods (`generate_key()`, `verify_key()`)
3. Define `ProcessingJob` model with status transitions and TTL logic
4. Define `ProcessingResult` model with FHIR bundle storage
5. Define `WebhookDelivery` model with retry tracking
6. Create and run database migrations
7. Register all models in Django admin with appropriate list displays and filters
8. Implement `assemble_r4_bundle()` in `apps/fhir/bundle_utils.py`
9. Implement `validate_bundle_r4()` in `apps/fhir/bundle_utils.py`
10. Implement `bundle_to_ndjson()` in `apps/fhir/bundle_utils.py`
11. Refactor `create_initial_patient_bundle()` to use `assemble_r4_bundle()` internally
12. Add configuration settings to `meddocparser/settings/base.py`
13. Add `apps.api` to `INSTALLED_APPS`
14. Create Celery Beat task `purge_expired_jobs` for periodic cleanup

---

## Risks and Mitigations

**Risk 1: Migration conflicts with existing models**

New models are in a new app (`apps.api`), so migrations are isolated from existing apps. No risk of conflict.

**Risk 2: FHIR Bundle refactor breaks Mode A**

Refactoring `create_initial_patient_bundle()` to use `assemble_r4_bundle()` internally could change output format. **Mitigation:** Write tests capturing current bundle output format before refactoring. Ensure backward compatibility.

**Risk 3: API key security**

If API keys are intercepted, unauthorized access is possible. **Mitigation:** Keys are transmitted over TLS only. Keys are hashed in the database. Keys can be revoked instantly via `is_active` flag. Rate limiting prevents abuse even with a valid key.

---

## Existing Code References

**Base models to inherit from:**
- `apps/core/models.py` -- `BaseModel` (lines 25-48) provides `created_at`, `updated_at`, `created_by`, `updated_by`

**FHIR Bundle utilities to extend:**
- `apps/fhir/bundle_utils.py` -- `create_initial_patient_bundle()` (line 35), `add_resource_to_bundle()`, `deduplicate_bundle()`
- `fhir.resources.bundle.Bundle` and `BundleEntry` (already imported, line 18-19)

**Existing API usage tracking pattern:**
- `apps/core/models.py` -- `APIUsageLog` model tracks AI API usage and costs; follow this pattern for API client usage tracking

**Settings file:**
- `meddocparser/settings/base.py` -- `LOCAL_APPS` (line 47), Celery configuration, Redis configuration

---

## TaskMaster Integration

**Workflow:** Parse this PRD as 1 task, then expand into subtasks.

**Step 1 -- Parse (1 task):**
```bash
task-master parse-prd .taskmaster/docs/deid-platform/01-foundation-infrastructure-prd.md --tag=deid-platform --num-tasks=1
```

**Step 2 -- Expand into subtasks:**
```bash
task-master expand --id=1 --tag=deid-platform --num=8
```

**Expected subtasks:** ~8 (new app scaffolding, each model group, FHIR bundle functions, settings, migrations, admin, purge task)
