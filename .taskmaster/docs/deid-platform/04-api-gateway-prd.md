# API Gateway - PRD

> **Purpose:** Build the RESTful API that external customers use to submit documents, check processing status, and retrieve de-identified FHIR bundles.

---

## Parent Context

Part of the **De-Identification + FHIR Conversion Platform** initiative. See [deidentification-fhir-platform-prd.md](../deidentification-fhir-platform-prd.md) for overall vision.

Depends on:
- **Sub-PRD 01: Foundation & Infrastructure** for APIClient, ProcessingJob, ProcessingResult models
- **Sub-PRD 03: Pipeline Integration** for `process_job_deidentification` Celery task and webhook delivery

---

## Overview

The API gateway is the customer-facing surface of Mode B. It accepts documents or raw text, creates ProcessingJobs, dispatches Celery tasks, and serves results. Authentication uses API keys (not session-based auth), and all endpoints are versioned under `/api/v1/`.

The project already uses Django REST Framework and drf-spectacular. This phase adds DRF views, serializers, a custom API key authentication backend, per-key rate limiting, and auto-generated OpenAPI documentation.

### Problem Statement

- The current API surface is Django view-based with session authentication, designed for logged-in web users
- No mechanism for external system-to-system integration
- No API key management for programmatic access
- No versioned API for backward-compatible evolution
- Document submission currently requires a browser-based upload form

### Solution

- DRF ViewSets and serializers for all Mode B endpoints
- Custom `APIKeyAuthentication` backend that validates hashed API keys
- Per-key rate limiting extending DRF's throttling
- Versioned URL namespace (`/api/v1/`)
- drf-spectacular auto-generated OpenAPI docs at `/api/v1/docs/`
- Synchronous processing option for small documents (`?sync=true`)

---

## Design Decisions

**1. API key format**

Keys follow the format `sk_live_` + 32 random hex characters (e.g., `sk_live_a1b2c3d4e5f6...`). The `sk_live_` prefix makes keys identifiable in logs and config files. The prefix is stored in `APIClient.api_key_prefix` for identification; the full key is hashed (SHA-256) and stored in `api_key_hash`.

**2. Authentication header**

Keys are passed in the `Authorization` header as `Bearer sk_live_...`. This follows the standard Bearer token convention and works with common HTTP clients, API gateways, and load balancers.

**3. Synchronous vs. asynchronous processing**

By default, document submission returns immediately with a job ID (async). Customers can add `?sync=true` to block until processing completes (up to `API_SYNC_TIMEOUT_SECONDS`, default 60s). If the timeout is exceeded, the response returns the job ID for async polling. The sync option is limited to files under 10MB.

**4. Output format selection**

Customers specify `output_format` in their request:
- `fhir_r4_json` (default) -- Standard FHIR R4 Bundle as JSON
- `fhir_r4_ndjson` -- One resource per line (for bulk FHIR pipelines)
- `raw_extracted` -- The structured extraction (pre-FHIR) as JSON, for customers who want to do their own FHIR conversion

**5. No pagination on results**

Each job produces one result (a single FHIR Bundle). There is no list of results to paginate. The jobs list endpoint (for a given API client) uses cursor-based pagination.

---

## API Endpoints

### Authentication

All endpoints require a valid API key in the `Authorization` header:

```
Authorization: Bearer sk_live_a1b2c3d4e5f6...
```

Unauthenticated requests receive `401 Unauthorized`. Requests with invalid or revoked keys receive `403 Forbidden`.

### Endpoint Reference

**POST `/api/v1/documents/`** -- Submit a document for processing

| Parameter | Location | Type | Required | Notes |
|-----------|----------|------|----------|-------|
| file | body (multipart) | File | Yes | PDF, max 50MB |
| profile | body | string | No | De-ID profile name. Default: `safe_harbor` |
| output_format | body | string | No | `fhir_r4_json`, `fhir_r4_ndjson`, `raw_extracted`. Default: `fhir_r4_json` |
| webhook_url | body | string (URL) | No | URL to POST results when complete |
| sync | query | boolean | No | If `true`, block until complete (max 60s, files <10MB only) |

Response (async, 202 Accepted):
```json
{
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "queued",
    "status_url": "/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000/",
    "result_url": "/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000/result/",
    "created_at": "2026-03-01T10:00:00Z",
    "expires_at": "2026-03-04T10:00:00Z"
}
```

Response (sync, 200 OK):
```json
{
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "completed",
    "processing_time_ms": 15200,
    "result": {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [...]
    }
}
```

---

**POST `/api/v1/text/`** -- Submit raw text for processing

| Parameter | Location | Type | Required | Notes |
|-----------|----------|------|----------|-------|
| text | body (JSON) | string | Yes | Raw clinical text, max 100,000 characters |
| profile | body | string | No | De-ID profile name. Default: `safe_harbor` |
| output_format | body | string | No | Default: `fhir_r4_json` |
| webhook_url | body | string (URL) | No | URL to POST results when complete |
| sync | query | boolean | No | If `true`, block until complete (max 60s) |

Response: Same structure as document submission.

---

**GET `/api/v1/jobs/{job_id}/`** -- Check job status

Response (200 OK):
```json
{
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "processing",
    "input_type": "file",
    "profile": "safe_harbor",
    "output_format": "fhir_r4_json",
    "created_at": "2026-03-01T10:00:00Z",
    "started_at": "2026-03-01T10:00:02Z",
    "completed_at": null,
    "expires_at": "2026-03-04T10:00:00Z",
    "processing_time_ms": null,
    "error": null
}
```

Status values: `queued`, `processing`, `completed`, `failed`, `expired`

Returns `404` if job_id does not exist or belongs to a different API client.

---

**GET `/api/v1/jobs/{job_id}/result/`** -- Retrieve de-identified FHIR bundle

Response (200 OK, when `output_format` is `fhir_r4_json`):
```json
{
    "resourceType": "Bundle",
    "id": "bundle-uuid",
    "type": "collection",
    "timestamp": "2026-03-01T10:00:15Z",
    "entry": [
        {
            "fullUrl": "urn:uuid:resource-uuid",
            "resource": {
                "resourceType": "Condition",
                "code": { "coding": [{ "code": "E11.9", "display": "Type 2 diabetes" }] },
                "subject": { "reference": "Patient/deidentified" }
            }
        }
    ],
    "meta": {
        "deidentification": {
            "profile": "safe_harbor",
            "identifiers_processed": { "names": 3, "dates": 8, "phones": 1 },
            "source_contexts_stripped": 15,
            "validation_passed": true
        }
    }
}
```

Response when `output_format` is `fhir_r4_ndjson`: Content-Type `application/x-ndjson`, one JSON resource per line.

Response when `output_format` is `raw_extracted`: The de-identified `StructuredMedicalExtraction` as JSON.

Returns `404` if job does not exist or belongs to different client.
Returns `202 Accepted` if job is still processing (with status body).
Returns `410 Gone` if job has expired and results were purged.

---

**GET `/api/v1/profiles/`** -- List available de-identification profiles

Response (200 OK):
```json
{
    "profiles": [
        {
            "name": "safe_harbor",
            "display_name": "HIPAA Safe Harbor (Full)",
            "description": "Full HIPAA Safe Harbor compliance. All 18 identifier types handled.",
            "is_hipaa_compliant": true
        },
        {
            "name": "safe_harbor_synthetic",
            "display_name": "Safe Harbor with Synthetic Data",
            "description": "Safe Harbor with Faker-generated replacement names and addresses.",
            "is_hipaa_compliant": true
        },
        {
            "name": "dates_only",
            "display_name": "Date Shifting Only",
            "description": "Only dates are shifted. Names and other identifiers kept. NOT Safe Harbor compliant.",
            "is_hipaa_compliant": false
        },
        {
            "name": "minimal",
            "display_name": "Minimal (Direct Identifiers Only)",
            "description": "Remove SSN, phone, email, fax only. NOT Safe Harbor compliant.",
            "is_hipaa_compliant": false
        }
    ]
}
```

No authentication required for this endpoint (public reference).

---

**GET `/api/v1/usage/`** -- API usage statistics

Response (200 OK):
```json
{
    "client_name": "Acme Health Tech",
    "rate_limit_per_hour": 100,
    "current_hour_usage": 23,
    "total_jobs": 1547,
    "total_jobs_completed": 1520,
    "total_jobs_failed": 27,
    "total_tokens_consumed": 4250000,
    "period": "all_time"
}
```

---

**POST `/api/v1/validate/`** -- Validate a FHIR bundle

| Parameter | Location | Type | Required | Notes |
|-----------|----------|------|----------|-------|
| bundle | body (JSON) | object | Yes | A FHIR Bundle to validate |

Response (200 OK):
```json
{
    "is_valid": true,
    "errors": [],
    "resource_count": 15,
    "resource_types": { "Condition": 5, "Observation": 8, "MedicationStatement": 2 }
}
```

No rate limit cost for validation requests (utility endpoint).

---

## Technical Scope

### New Files in `apps/api/`

| File | Purpose |
|------|---------|
| `urls.py` | DRF URL routing under `/api/v1/` |
| `views.py` | DRF ViewSets for all endpoints |
| `serializers.py` | Input/output serializers |
| `authentication.py` | `APIKeyAuthentication` custom auth backend |
| `throttling.py` | Per-key rate limiting |
| `permissions.py` | `HasValidAPIKey`, `CanUseDeidentification` permission classes |
| `pagination.py` | Cursor-based pagination for job lists (future) |

### API Key Authentication

**File:** `apps/api/authentication.py`

```python
class APIKeyAuthentication(BaseAuthentication):
    """
    DRF authentication backend that validates API keys.

    Looks for: Authorization: Bearer sk_live_...
    Hashes the key and looks up APIClient by api_key_hash.
    Returns (api_client, None) on success.
    """

    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer '):
            return None

        key = auth_header[7:]  # Strip 'Bearer '
        key_hash = hashlib.sha256(key.encode()).hexdigest()

        try:
            client = APIClient.objects.get(
                api_key_hash=key_hash,
                is_active=True
            )
            client.last_used_at = timezone.now()
            client.save(update_fields=['last_used_at'])
            return (client, None)
        except APIClient.DoesNotExist:
            raise AuthenticationFailed('Invalid or revoked API key')
```

**DRF configuration** (add to `settings/base.py`):

```python
REST_FRAMEWORK = {
    # ... existing settings ...
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',  # existing
        'apps.api.authentication.APIKeyAuthentication',         # NEW
    ],
}
```

Session authentication remains for Mode A web users. API key authentication is used by Mode B API clients. DRF tries each backend in order; the first one that returns a result wins.

### Rate Limiting

**File:** `apps/api/throttling.py`

```python
class APIKeyRateThrottle(SimpleRateThrottle):
    """
    Per-API-key rate limiting.
    Rate is configured on the APIClient model (rate_limit_per_hour).
    """

    def get_cache_key(self, request, view):
        if hasattr(request, 'auth') and request.auth is None:
            # request.user is an APIClient when using APIKeyAuthentication
            client = request.user
            if isinstance(client, APIClient):
                return f'api_throttle_{client.id}'
        return None

    def get_rate(self):
        # Dynamic rate from APIClient model
        return f'{self.request.user.rate_limit_per_hour}/hour'
```

### Serializers

**File:** `apps/api/serializers.py`

Key serializers:

```python
class DocumentSubmissionSerializer(serializers.Serializer):
    file = serializers.FileField(required=True)
    profile = serializers.CharField(default='safe_harbor', required=False)
    output_format = serializers.ChoiceField(
        choices=['fhir_r4_json', 'fhir_r4_ndjson', 'raw_extracted'],
        default='fhir_r4_json',
        required=False
    )
    webhook_url = serializers.URLField(required=False, allow_null=True)

    def validate_file(self, value):
        # Max 50MB, PDF only
        ...

    def validate_profile(self, value):
        # Must be an active DeidentificationProfile
        ...


class TextSubmissionSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=100000, required=True)
    profile = serializers.CharField(default='safe_harbor', required=False)
    output_format = serializers.ChoiceField(
        choices=['fhir_r4_json', 'fhir_r4_ndjson', 'raw_extracted'],
        default='fhir_r4_json',
        required=False
    )
    webhook_url = serializers.URLField(required=False, allow_null=True)


class JobStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProcessingJob
        fields = [
            'id', 'status', 'input_type', 'deidentification_profile',
            'output_format', 'created_at', 'started_at', 'completed_at',
            'expires_at', 'error_message'
        ]
        read_only_fields = fields


class ProcessingResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProcessingResult
        fields = [
            'fhir_bundle', 'resource_count', 'resource_types',
            'processing_time_ms', 'deidentification_summary'
        ]
        read_only_fields = fields
```

### URL Configuration

**File:** `apps/api/urls.py`

```python
from django.urls import path
from . import views

app_name = 'api'

urlpatterns = [
    path('documents/', views.DocumentSubmissionView.as_view(), name='submit_document'),
    path('text/', views.TextSubmissionView.as_view(), name='submit_text'),
    path('jobs/<uuid:job_id>/', views.JobStatusView.as_view(), name='job_status'),
    path('jobs/<uuid:job_id>/result/', views.JobResultView.as_view(), name='job_result'),
    path('profiles/', views.ProfileListView.as_view(), name='profile_list'),
    path('usage/', views.UsageView.as_view(), name='usage'),
    path('validate/', views.ValidateBundleView.as_view(), name='validate_bundle'),
]
```

**Add to `meddocparser/urls.py`:**

```python
urlpatterns = [
    # ... existing patterns ...
    path('api/v1/', include('apps.api.urls')),
]
```

### OpenAPI Documentation

drf-spectacular is already installed. Add schema configuration:

```python
# settings/base.py
SPECTACULAR_SETTINGS = {
    'TITLE': 'Medical Document De-Identification API',
    'DESCRIPTION': 'De-identify medical documents and convert to FHIR R4 bundles',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SCHEMA_PATH_PREFIX': '/api/v1/',
}
```

Add docs URL:

```python
# apps/api/urls.py
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns += [
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='api:schema'), name='docs'),
]
```

### API Key Management (Admin)

API keys are created and managed through Django admin. The admin interface provides:

- Create new APIClient with auto-generated key (displayed once)
- View key prefix and last-used timestamp
- Activate/deactivate keys
- Set rate limits per client
- View usage statistics per client

No self-service key management portal in this phase. Keys are provisioned by the system administrator.

---

## Implementation Checklist

1. Create `apps/api/urls.py` with all endpoint URL patterns
2. Create `apps/api/authentication.py` with `APIKeyAuthentication` backend
3. Add `APIKeyAuthentication` to DRF `DEFAULT_AUTHENTICATION_CLASSES` in settings
4. Create `apps/api/throttling.py` with `APIKeyRateThrottle`
5. Create `apps/api/permissions.py` with `HasValidAPIKey` and `CanUseDeidentification`
6. Create `apps/api/serializers.py` with all input/output serializers
7. Create `apps/api/views.py` with `DocumentSubmissionView` (handles file upload, creates ProcessingJob, dispatches Celery task)
8. Create `TextSubmissionView` (handles raw text submission)
9. Create `JobStatusView` (returns job status, scoped to authenticated client)
10. Create `JobResultView` (returns FHIR bundle, handles 202/404/410 status codes, supports output format selection)
11. Create `ProfileListView` (lists de-ID profiles, no auth required)
12. Create `UsageView` (returns usage stats for authenticated client)
13. Create `ValidateBundleView` (validates FHIR bundle against R4 spec)
14. Implement synchronous processing option (`?sync=true`) with timeout
15. Add `/api/v1/` to `meddocparser/urls.py`
16. Configure drf-spectacular settings and add schema/docs URLs
17. Add API key generation utility to `APIClient` model (`generate_key()` class method)
18. Configure Django admin for APIClient with key display and management
19. Write API tests: auth (valid key, invalid key, revoked key, no key)
20. Write API tests: document submission (valid PDF, invalid file, too large, missing file)
21. Write API tests: job status and result retrieval (own job, other client's job, expired job)
22. Write API tests: rate limiting (verify throttle kicks in at configured rate)

---

## User Flow: Complete API Interaction

### Async Flow (Default)

```bash
# 1. Submit document
curl -X POST https://api.example.com/api/v1/documents/ \
  -H "Authorization: Bearer sk_live_a1b2c3d4..." \
  -F "file=@medical_record.pdf" \
  -F "profile=safe_harbor"

# Response: {"job_id": "uuid", "status": "queued", "status_url": "/api/v1/jobs/uuid/"}

# 2. Poll for status
curl -H "Authorization: Bearer sk_live_a1b2c3d4..." \
  https://api.example.com/api/v1/jobs/uuid/

# Response: {"status": "processing", ...}  (wait and retry)
# Response: {"status": "completed", ...}   (proceed to step 3)

# 3. Retrieve result
curl -H "Authorization: Bearer sk_live_a1b2c3d4..." \
  https://api.example.com/api/v1/jobs/uuid/result/

# Response: {"resourceType": "Bundle", "type": "collection", "entry": [...]}
```

### Sync Flow (Small Documents)

```bash
# Submit and wait for result
curl -X POST "https://api.example.com/api/v1/documents/?sync=true" \
  -H "Authorization: Bearer sk_live_a1b2c3d4..." \
  -F "file=@small_record.pdf" \
  -F "profile=safe_harbor"

# Response (after 10-30 seconds):
# {"job_id": "uuid", "status": "completed", "result": {"resourceType": "Bundle", ...}}
```

### Webhook Flow

```bash
# Submit with webhook
curl -X POST https://api.example.com/api/v1/documents/ \
  -H "Authorization: Bearer sk_live_a1b2c3d4..." \
  -F "file=@medical_record.pdf" \
  -F "profile=safe_harbor" \
  -F "webhook_url=https://my-server.com/hooks/deid-complete"

# Response: {"job_id": "uuid", "status": "queued"}

# When complete, your server receives:
# POST https://my-server.com/hooks/deid-complete
# {"event": "job.completed", "job_id": "uuid", "result_url": "/api/v1/jobs/uuid/result/"}
```

---

## Risks and Mitigations

**Risk 1: API key brute force**

Attackers could attempt to guess valid API keys.

**Mitigation:** Keys are 32 hex characters (128 bits of entropy) -- brute force is computationally infeasible. Rate limiting on authentication failures (429 after 10 failed attempts per IP per hour). Log failed authentication attempts to SecurityEvent model.

**Risk 2: Large file uploads consume memory**

50MB file uploads could strain server memory if many are concurrent.

**Mitigation:** Django's `FILE_UPLOAD_MAX_MEMORY_SIZE` setting ensures large files are streamed to disk, not held in memory. Celery task processes the file from disk. Rate limiting prevents a single client from overwhelming the server.

**Risk 3: Synchronous timeout causes poor UX**

If a document takes longer than 60 seconds to process (large document, AI rate limiting), the sync request times out and the customer must switch to async polling.

**Mitigation:** Return the job ID in the timeout response so the customer can continue polling. Document the sync timeout clearly. Recommend async for production use; sync is for testing and small documents only.

**Risk 4: Webhook URL is malicious**

A customer could provide a webhook URL pointing to internal infrastructure (SSRF).

**Mitigation:** Validate webhook URLs against a denylist of private IP ranges (10.x, 172.16-31.x, 192.168.x, localhost, 127.x). Use a dedicated outbound HTTP client with timeouts and no redirect following. Log all webhook deliveries.

---

## Existing Code References

**DRF configuration:**
- `meddocparser/settings/base.py` -- `REST_FRAMEWORK` dict (existing DRF config)
- `drf_spectacular` already in `THIRD_PARTY_APPS` (line 29)

**Existing API patterns to follow:**
- `apps/fhir/urls.py` -- URL patterns for FHIR API endpoints
- `apps/fhir/api_views.py` -- Function-based DRF views (the new API will use class-based for consistency with DRF conventions)
- `apps/fhir/merge_api_views.py` -- Merge operation trigger/status/result pattern (similar to job status/result pattern)

**URL configuration:**
- `meddocparser/urls.py` -- Root URL config where `api/v1/` will be added

**Models (from Sub-PRD 01):**
- `apps/api/models.py` -- `APIClient`, `ProcessingJob`, `ProcessingResult`, `WebhookDelivery`

---

## TaskMaster Integration

**Workflow:** Parse this PRD as 1 task, then expand into subtasks.

**Step 1 -- Parse (1 task):**
```bash
task-master parse-prd .taskmaster/docs/deid-platform/04-api-gateway-prd.md --tag=deid-platform --num-tasks=1 --append
```

**Step 2 -- Expand into subtasks:**
```bash
task-master expand --id=4 --tag=deid-platform --num=12
```

**Expected subtasks:** ~12 (auth backend, throttling, permissions, serializers, each view group, sync option, URL config, OpenAPI docs, admin key management, auth tests, endpoint tests, rate limit tests)
