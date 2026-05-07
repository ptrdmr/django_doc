# Manual Bug Log — Layer-by-Layer Diagnostic Sweep

**Project:** Medical Document Parser (doc2db_2025_django)
**Date:** 2026-04-12
**Status:** Diagnostic only — no fixes applied
**Methodology:** Static code analysis, layer-by-layer sweep

---

## Layer 1: Infrastructure & Configuration

### Finding 1: Dockerfile / Docker-Compose Settings Module Conflict
**Severity:** MEDIUM | **Category:** Configuration Drift

The Dockerfile hardcodes `DJANGO_SETTINGS_MODULE=meddocparser.settings.production` (line 8), but docker-compose.yml overrides it to `development` (line 51). This works in dev because the compose override wins, but if anyone runs the built image directly (`docker run`), it silently falls into production mode with `DEBUG=False` and no `ALLOWED_HOSTS` — guaranteed 400 errors.

The `collectstatic` step during build (Dockerfile line 41) explicitly overrides to development settings, revealing the author knew about the conflict and patched it locally rather than fixing the root.

**Files:** `Dockerfile:8,41`, `docker-compose.yml:51`

---

### Finding 2: Redis Healthcheck Will Fail With Auth
**Severity:** LOW-MEDIUM | **Category:** Docker Reliability

Redis requires a password (`--requirepass`), but the dev compose healthcheck doesn't authenticate:

```yaml
# docker-compose.yml line 37
test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
```

This returns `NOAUTH Authentication required` on a password-protected instance. The healthcheck always fails, meaning Docker marks Redis as unhealthy. Services with `condition: service_healthy` on Redis could wait forever or hit retry limits.

The production compose (docker-compose.prod.yml line 42) correctly authenticates — the dev compose was missed.

**Files:** `docker-compose.yml:37`, `docker-compose.prod.yml:42`

---

### Finding 3: Production Cache Backend Mismatch
**Severity:** MEDIUM | **Category:** Potential Runtime Crash

Production settings use Django's built-in `django.core.cache.backends.redis.RedisCache` but pass `django_redis`-specific options:

```python
# production.py line 49-58
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',  # Not supported!
        }
    }
}
```

Django's built-in `RedisCache` does not support `CLIENT_CLASS`. That option is `django_redis`-specific. In production, this would either be silently ignored or raise a configuration error. The base settings correctly use `django_redis.cache.RedisCache`.

**Files:** `meddocparser/settings/production.py:49-58`, `meddocparser/settings/base.py:367-397`

---

### Finding 4: Celery Default Settings Module Points to Development
**Severity:** LOW | **Category:** Deployment Safety

```python
# celery.py line 11
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
```

If someone starts a Celery worker outside Docker without setting the env var, it silently uses development settings. In Docker containers, the env var is always set explicitly so this doesn't matter operationally.

**Files:** `meddocparser/celery.py:11`

---

### Finding 5: Duplicate/Conflicting Celery Configuration
**Severity:** LOW | **Category:** Maintenance Debt

Celery routing and worker settings are defined in three places that could drift:

1. `meddocparser/settings/base.py` lines 343-364 (includes `apps.core.tasks.*` → `general` queue)
2. `meddocparser/celery.py` lines 31-52 (does NOT include `apps.core.tasks`)
3. `docker-compose.yml` line 137 (CLI flags)

Since `celery.py` calls `app.conf.update` after `config_from_object`, the celery.py routes overwrite the base.py routes — meaning the `general` queue routing for `apps.core.tasks` is silently lost.

**Files:** `meddocparser/settings/base.py:343-347`, `meddocparser/celery.py:31-36`

---

### Finding 6: `POSTGRES_HOST_AUTH_METHOD: trust` in Dev Docker
**Severity:** LOW | **Category:** Security Hygiene (dev only)

```yaml
# docker-compose.yml line 12
POSTGRES_HOST_AUTH_METHOD: trust
```

Bypasses all password authentication for PostgreSQL. Anyone who can reach port 5432 (exposed to host) can connect without credentials. The password is also set, creating mixed signals.

**Files:** `docker-compose.yml:12`

---

### Finding 7: AI Cache Location String Concatenation Issue
**Severity:** LOW | **Category:** Subtle Bug

```python
# base.py line 387
'LOCATION': REDIS_URL + '/1',  # Use database 1 for AI cache
```

If `REDIS_URL` is `redis://localhost:6379/0`, this becomes `redis://localhost:6379/0/1` — not valid. It should replace the database number, not append. Most Redis clients will either error or silently ignore the extra path segment.

**Files:** `meddocparser/settings/base.py:387`

---

### Finding 8: `env.example` Lists SQLite as Default, Docker Expects PostgreSQL
**Severity:** LOW | **Category:** Onboarding Confusion

```
# env.example line 30-31
DB_ENGINE=sqlite
```

But Docker setup hardcodes `DB_ENGINE=postgresql`, and development.py defaults to `postgresql`. New developers copying env.example as-is get SQLite, which doesn't support JSONB and will break FHIR features.

**Files:** `env.example:30-31`

---

### Finding 9: `ALLOWED_HOSTS` Typo in `env.example`
**Severity:** LOW | **Category:** Typo

```
# env.example line 145
ALLOWED_HOSTS=localhost,1227.0.0.1,0.0.0.0,3.129.92.221
```

`1227.0.0.1` should be `127.0.0.1`.

**Files:** `env.example:145`

---

### Finding 10: `debug_toolbar` in Base `INSTALLED_APPS` and `MIDDLEWARE`
**Severity:** LOW | **Category:** Production Safety

Despite comments saying "Development only," `debug_toolbar` is in `base.py` which is imported by all settings including production. In production with `DEBUG=False`, the toolbar won't render, but the middleware still runs on every request (checking `INTERNAL_IPS`, etc.), adding unnecessary overhead.

**Files:** `meddocparser/settings/base.py:44,78`

---

### Finding 11: `AxesBackend` Position in `AUTHENTICATION_BACKENDS`
**Severity:** LOW | **Category:** Correctness

```python
# base.py line 250-254
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
    'axes.backends.AxesBackend',  # Should be FIRST
]
```

Per django-axes documentation, `AxesBackend` should be the first backend listed so it can intercept authentication attempts before they reach other backends. With it last, axes may not properly track successful logins for lockout reset.

**Files:** `meddocparser/settings/base.py:250-254`

---

### Finding 12: Test Settings Use SQLite — JSONB Tests Won't Work
**Severity:** MEDIUM | **Category:** Test Reliability

```python
# test.py line 11-19
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}
```

Tests run on SQLite in-memory. Any test exercising JSONB queries, GIN indexes, `pg_trgm`, or PostgreSQL-specific features will either silently behave differently or fail. For a medical app where FHIR data lives in JSONB fields, the test suite can't validate core data integrity patterns.

**Files:** `meddocparser/settings/test.py:11-19`

---

## Layer 2: Database & Models

### Finding 13: Index on Encrypted `date_of_birth` Field is Useless
**Severity:** MEDIUM | **Category:** Performance / Silent Failure

```python
# patients/models.py line 142
models.Index(fields=['date_of_birth']),
```

`date_of_birth` is `encrypt(models.CharField(...))` (line 56). Encrypted fields store ciphertext — a B-tree index on ciphertext can't support range queries, sorting, or equality lookups on the actual date. The index wastes disk space and slows writes.

**Files:** `apps/patients/models.py:56,142`

---

### Finding 14: Inconsistent User Model References — `User` vs `settings.AUTH_USER_MODEL`
**Severity:** MEDIUM | **Category:** Upgrade/Extensibility Hazard

Two apps import `User` directly instead of using `settings.AUTH_USER_MODEL`:

- `apps/core/models.py` line 7
- `apps/fhir/models.py` line 2

All other apps correctly use string references. If the project switches to a custom user model, these two apps will break with hard-to-debug FK errors.

**Files:** `apps/core/models.py:7`, `apps/fhir/models.py:2`

---

### Finding 15: `AuditLog.request_url` Uses `URLField` — May Reject Valid Paths
**Severity:** LOW-MEDIUM | **Category:** Data Loss Risk

```python
# core/models.py line 165
request_url = models.URLField(blank=True)
```

`URLField` validates proper URLs. Internal Docker URLs, development paths, or Celery task contexts without real requests may fail validation. `CharField` or `TextField` would be safer for audit logging.

**Files:** `apps/core/models.py:165`

---

### Finding 16: `EncryptedFileField` Does Not Actually Encrypt File Contents
**Severity:** MEDIUM | **Category:** Security / False Confidence (HIPAA Gap)

```python
# documents/models.py line 46-88
class EncryptedFileField(models.FileField):
    """Custom FileField that encrypts file contents at rest."""
    
    def save_form_data(self, instance, data):
        if data is not None:
            super().save_form_data(instance, data)  # No encryption!
```

Despite the docstring claiming encryption at rest, the implementation is a standard `FileField` with zero encryption logic. Comments acknowledge: "we rely on the storage system or OS-level encryption." Medical PDFs are stored as plain files on disk. The field name gives false confidence that HIPAA file-at-rest requirements are met.

**Files:** `apps/documents/models.py:46-88`

---

### Finding 17: `Document.save()` Fetches Original on Every Save
**Severity:** LOW-MEDIUM | **Category:** Performance

```python
# documents/models.py line 248-260
if self.pk:
    original = Document.objects.get(pk=self.pk)  # Extra SELECT every save
```

Every `save()` on an existing Document triggers an extra `SELECT` for status change detection. During batch processing or Celery tasks calling `save()` multiple times, this doubles database queries. Also, if the document is deleted between the check and save, raises `Document.DoesNotExist`.

**Files:** `apps/documents/models.py:248-260`

---

### Finding 18: `PatientHistory.action` Choices Missing `fhir_merge`
**Severity:** LOW | **Category:** Data Integrity

```python
# patients/models.py line 2430-2438
choices=[
    ('created', 'Patient Created'),
    ('updated', 'Patient Updated'),
    ('fhir_append', 'FHIR Resources Added'),
    ('fhir_history_preserved', 'FHIR Historical Data Preserved'),
    ('document_processed', 'Document Processed'),
]
```

But `Patient.add_fhir_resources()` creates history records with `action='fhir_merge'` (line 362), which isn't in the choices list. `get_action_display()` returns the raw string instead of a human-readable label.

**Files:** `apps/patients/models.py:2430-2438,362`

---

### Finding 19: `PatientHistory.document` FK Still Commented Out
**Severity:** LOW | **Category:** Stale TODO / Missing Audit Link

```python
# patients/models.py line 2410-2428
# TODO: Uncomment when Task 4 (Document Management) is complete
# document = models.ForeignKey(
#     'documents.Document', ...
```

The Document model has been fully implemented, but this FK is still commented out. FHIR merge audit records can't directly link to source documents — they embed document IDs in text notes, requiring string parsing instead of FK joins for HIPAA queries.

**Files:** `apps/patients/models.py:2410-2428`

---

### Finding 20: Deprecated `is_approved` Field Still Indexed
**Severity:** LOW | **Category:** Maintenance Debt

```python
# documents/models.py line 547-550 (deprecated field)
is_approved = models.BooleanField(default=False, ...)

# documents/models.py line 579 (index still active)
models.Index(fields=['document', 'is_approved']),
```

The deprecated `is_approved` field still has a composite index. `review_status` is the source of truth, making this index useless — it only costs write performance.

**Files:** `apps/documents/models.py:547-550,579`

---

### Finding 21: `AuditLog` Entries Created With Non-Standard `event_type` Values
**Severity:** LOW-MEDIUM | **Category:** Data Integrity

The `audit_extraction_decision()` function creates entries with `event_type='extraction_auto_approved'` and `'extraction_flagged'`, and `category='document_processing'`. None of these are in `AuditLog.EVENT_TYPES` or `CATEGORIES` choices. Records save fine (Django doesn't enforce choices at DB level), but compliance reports filtering by known event types will miss extraction decisions.

**Files:** `apps/documents/models.py:1412-1415`, `apps/core/models.py:88-128,131-139`

---

### Finding 22: Soft Delete on Patient but `CASCADE` from Document
**Severity:** MEDIUM | **Category:** Data Integrity / HIPAA Compliance

```python
# documents/models.py line 106-110
patient = models.ForeignKey(
    'patients.Patient',
    on_delete=models.CASCADE,  # Hard delete cascades!
)
```

`Patient` uses soft delete (sets `deleted_at`), but `Document.patient` uses `CASCADE`. If someone bypasses soft delete and calls `.delete()` on a QuerySet (e.g., `Patient.all_objects.filter(...).delete()`), it hard-deletes the patient AND cascades to all documents, parsed data, comparisons, and audits. For HIPAA, medical records should never be hard-deletable. `PROTECT` would be safer.

Same pattern in `ParsedData`, `PatientDataComparison`, `PatientDataAudit`, and `FHIRMergeOperation`.

**Files:** `apps/documents/models.py:106-110`, `apps/documents/models.py:399,405,971,977,983`

---

### Finding 23: Provider Methods Permanently Return Zero
**Severity:** LOW | **Category:** Dead Code / Stale TODO

```python
# providers/models.py line 91-103
def get_patients(self):
    # TODO: Uncomment when Document and DocumentProvider models exist
    return Patient.objects.none()

def get_document_count(self):
    # TODO: Uncomment when DocumentProvider model exists
    return 0
```

The Document model exists and has a `providers` M2M field. These could work using `Patient.objects.filter(documents__providers=self).distinct()` and `self.documents.count()`. Any UI relying on these shows zero for every provider.

**Files:** `apps/providers/models.py:91-103,111-120`

---

### Finding 24: `FHIRMergeConfiguration.save()` Calls `full_clean()` Unconditionally
**Severity:** LOW | **Category:** Unexpected Side Effects

```python
# fhir/models.py line 142-148
def save(self, *args, **kwargs):
    if self.is_default:
        FHIRMergeConfiguration.objects.filter(is_default=True).update(is_default=False)
    self.full_clean()
    super().save(*args, **kwargs)
```

Calling `full_clean()` in `save()` is unusual in Django. Programmatic saves from management commands, Celery tasks, or data migrations will trigger form-level validation, which may cause unexpected `ValidationError` exceptions in automated workflows.

**Files:** `apps/fhir/models.py:142-148`

---

## Layer 3: Authentication & Authorization

### Finding 25: `@csrf_exempt` on Authenticated FHIR API Endpoints
**Severity:** HIGH | **Category:** Security / HIPAA Compliance

Eight API endpoints in `apps/fhir/api_views.py` and `apps/fhir/merge_api_views.py` use `@csrf_exempt` alongside `@login_required`. These endpoints accept `POST`, `PUT`, and `DELETE` requests that create, modify, and delete FHIR merge configurations and trigger merge operations — they mutate patient medical data. Disabling CSRF on session-authenticated endpoints means any malicious site can submit cross-origin requests using the user's session cookies. This is a textbook CSRF vulnerability on endpoints that modify PHI.

The base settings have `CSRF_USE_SESSIONS = True` and `CSRF_COOKIE_HTTPONLY = True`, indicating the project takes CSRF seriously — then bypasses it on the most sensitive endpoints.

**Files:** `apps/fhir/api_views.py:123,198,256,287,311`, `apps/fhir/merge_api_views.py:36,336`

---

### Finding 26: `AuditLoggingMiddleware` Uses Non-Existent `event_type='system_access'`
**Severity:** LOW-MEDIUM | **Category:** Data Integrity (extends Finding 21)

The middleware's `_determine_event_type` method returns `'system_access'` as its default event type (line 318), and `_log_request_complete` also uses it for non-PHI requests (line 273). This value is not in `AuditLog.EVENT_TYPES`. Combined with Finding 21, there are now at least 4 non-standard event types and 1 non-standard category being written to the audit log. Any compliance report filtering by defined choices will miss a significant portion of entries.

**Files:** `apps/core/middleware.py:273,318`, `apps/core/models.py:88-128`

---

### Finding 27: `RateLimitingMiddleware` is a Complete No-Op
**Severity:** MEDIUM | **Category:** Security Gap

```python
# middleware.py line 438-441
def _is_rate_limited(self, request):
    # For now, just return False
    return False
```

The rate limiting middleware is registered in `MIDDLEWARE` and runs on every request, but always returns `False`. It provides zero protection against brute force attacks or API abuse. `django-ratelimit==4.1.0` is already in `requirements.txt` but isn't wired up. The middleware adds overhead on every request with no benefit.

**Files:** `apps/core/middleware.py:428-441`, `meddocparser/settings/base.py:66`

---

### Finding 28: `admin_required` Allows `is_staff` Users Without Admin Role
**Severity:** LOW-MEDIUM | **Category:** Authorization Bypass

```python
# decorators.py line 239-242
if request.user.is_superuser or request.user.is_staff:
    return view_func(request, *args, **kwargs)
```

The `admin_required` decorator allows any user with `is_staff=True` to access admin-only views. Django's `is_staff` flag only controls Django admin panel access — it's not the same as the custom `admin` role. Any `is_staff` user gets full access to role management, user management, bulk role assignment, and invitation management, bypassing the entire RBAC system.

**Files:** `apps/accounts/decorators.py:239-242`

---

### Finding 29: `PermissionChecker.invalidate_all_caches()` Calls `cache.clear()`
**Severity:** LOW-MEDIUM | **Category:** Availability / Side Effects

```python
# permissions.py line 263-266
def invalidate_all_caches(cls) -> None:
    cache.clear()
```

This wipes the entire default cache — including Django sessions (if using cache sessions in production), AI extraction results, and any other cached data. In production where `SESSION_ENGINE = 'django.contrib.sessions.backends.cache'`, calling this would log out every user.

**Files:** `apps/accounts/permissions.py:263-266`

---

### Finding 30: Audit Middleware Creates Two AuditLog Entries Per Request
**Severity:** LOW | **Category:** Performance / Audit Noise

The `AuditLoggingMiddleware` creates one entry in `process_request` (request start) and another in `process_response` (request complete) for every audit-worthy request. A single patient record view creates two audit entries. Over time this doubles audit data volume, making compliance queries slower and reports noisier.

**Files:** `apps/core/middleware.py:243,272`

---

### Finding 31: `AcceptInvitationView` is Unauthenticated With No Rate Limiting
**Severity:** LOW-MEDIUM | **Category:** Security

The invitation acceptance view is public (intentionally — invitees don't have accounts). Combined with Finding 27 (rate limiting is no-op), there's no protection against token brute-forcing. The tokens use `secrets.token_urlsafe(48)` so entropy is good, but the endpoint has no failed-attempt tracking, no CAPTCHA, and no rate limiting.

**Files:** `apps/accounts/views.py:935-962`

---

### Finding 32: `InvitationRegistrationForm.email` Has `readonly` HTML But Server-Side Validation Exists
**Severity:** LOW | **Category:** Input Validation (Mitigated)

The email field uses HTML `readonly` (client-side only), but `clean_email` correctly validates that the submitted email matches the invitation email server-side. Properly handled — noted for completeness.

**Files:** `apps/accounts/forms.py:157-159,191-206`

---

### Finding 33: Custom `PermissionRequiredMixin` Shadows Django's Built-in
**Severity:** LOW | **Category:** Naming Conflict

A custom `PermissionRequiredMixin` in `decorators.py` has the same name as Django's `django.contrib.auth.mixins.PermissionRequiredMixin`. The custom one is never actually used — all views use Django's `LoginRequiredMixin` plus `@method_decorator(has_permission(...))` instead. Dead code with a confusing name collision.

**Files:** `apps/accounts/decorators.py:392-446`

---

### Finding 34: Custom Headers Leak Application Identity
**Severity:** LOW | **Category:** Security Hardening

```python
# middleware.py line 61-62
response['X-Medical-App'] = 'HIPAA-Compliant'
response['X-PHI-Protection'] = 'Enabled'
```

Custom headers added to every response advertise that this is a medical/HIPAA application. Tells attackers the app handles high-value medical data and claims HIPAA compliance.

**Files:** `apps/core/middleware.py:61-62`

---

## Layer 4: Document Processing Pipeline

### Finding 35: `DataValidationError` Caught But Never Imported in Main Task
**Severity:** MEDIUM | **Category:** Silent Bug / Dead Code

The `process_document_async` task catches `DataValidationError` in two places (lines 1076 and 1121), but `DataValidationError` is never imported at the top of the function or in the imports block. The top-level imports include other exception classes from `.exceptions` but not this one. If these `except` clauses are ever reached, they raise `NameError`, which is caught by the outer generic `except Exception`, masking the real issue. The specialized error handling logic in those blocks will never execute.

**Files:** `apps/documents/tasks.py:1076,1121,36-46`, `apps/documents/exceptions.py:167`

---

### Finding 36: `cleanup_old_documents` Task is a Stub — Runs Daily
**Severity:** LOW-MEDIUM | **Category:** Dead Code / Wasted Resources

```python
# tasks.py line 2351-2362
def cleanup_old_documents():
    # Placeholder for cleanup logic
    # This will be implemented when we have the document models
    return "Cleanup task completed"
```

Registered in `CELERY_BEAT_SCHEDULE` to run every 24 hours. Does nothing except log two messages. The Document model has been fully implemented for a long time. Consumes a Celery worker slot daily with zero work.

**Files:** `apps/documents/tasks.py:2351-2362`, `meddocparser/settings/base.py:350-356`

---

### Finding 37: Result Dict References Variables That May Be Empty or Undefined
**Severity:** MEDIUM | **Category:** Runtime Error Risk

```python
# tasks.py line 1310-1312
'fhir_resources_created': len(fhir_resources) if fhir_resources else 0,
'structured_extraction_used': bool(structured_data_counts),
```

`fhir_resources` was mutated in-place by `.pop(0)` during serialization (line 934), leaving it as an empty list — `len()` always returns 0, never reflecting actual count. `structured_data_counts` is only assigned inside an `if structured_extraction:` block and may not exist in other code paths, risking `NameError`.

**Files:** `apps/documents/tasks.py:1310-1312,934,913`

---

### Finding 38: `document.status = 'requires_review'` Not in STATUS_CHOICES
**Severity:** LOW | **Category:** Data Integrity

```python
# tasks.py line 736
document.status = 'requires_review'
```

Document `STATUS_CHOICES` has `'review'`, not `'requires_review'`. Django won't enforce at DB level, but `get_status_display()` returns the raw string. Templates relying on display names will show the internal value.

**Files:** `apps/documents/tasks.py:736`, `apps/documents/models.py:97-103`

---

### Finding 39: Full `document.save()` After Processing — Re-writes Encrypted Text
**Severity:** LOW-MEDIUM | **Category:** Performance / Data Race

```python
# tasks.py line 1286-1288
document.processed_at = timezone.now()
document.error_message = ''
document.save()  # Full save — no update_fields
```

Saves ALL fields including `original_text` (encrypted full PDF text, potentially megabytes). Combined with Finding 17 (extra SELECT on every save), this triggers an unnecessary extra query and re-writes the entire row. Using `update_fields=['status', 'processed_at', 'error_message', 'processing_message']` would be far more efficient.

**Files:** `apps/documents/tasks.py:1286-1288`

---

### Finding 40: `django.setup()` Called Inside Task Body
**Severity:** LOW | **Category:** Unnecessary

```python
# tasks.py line 261-263
import django
django.setup()
```

Django is already set up by the time Celery workers start. Calling `setup()` again is a no-op but adds confusion.

**Files:** `apps/documents/tasks.py:261-263`

---

### Finding 41: Optimistic Merge Has No Automated Rollback on Rejection
**Severity:** MEDIUM | **Category:** Data Integrity / Business Logic Gap

The pipeline merges FHIR data into the patient record immediately, even for flagged extractions (optimistic concurrency). When a reviewer rejects a flagged extraction via the UI, `reject_extraction()` only updates ParsedData status — it does NOT call `rollback_document_merge()` to remove merged data from the patient record. The `Patient.rollback_document_merge()` method exists but is never triggered automatically. Merged data stays in the patient record after rejection with no UI surfacing this.

**Files:** `apps/documents/tasks.py:1015-1027`, `apps/documents/models.py:626-647`, `apps/patients/models.py:397`

---

### Finding 42: Failed Chunk Results Silently Merged Without Quality Signal
**Severity:** LOW-MEDIUM | **Category:** Silent Data Loss

When a document chunk fails processing, the task returns empty results with `processing_failed: True` in metadata. The aggregation function `_aggregate_chunked_extractions` merges these without checking the flag. If 3 of 5 chunks fail, the patient gets 40% of their data with no indication of loss. Confidence scores could still appear high based on successful chunks only.

**Files:** `apps/documents/tasks.py:188-204,2365`

---

## Layer 5: FHIR & Patient Data Management

### Finding 43: Dual FHIR Storage — `cumulative_fhir_json` vs `encrypted_fhir_bundle` — Inconsistent Usage
**Severity:** HIGH | **Category:** Data Integrity / Architecture Split

The Patient model has two FHIR fields: `cumulative_fhir_json` (legacy, unencrypted) and `encrypted_fhir_bundle` (new, encrypted). The main pipeline (`add_fhir_resources()`) writes to `encrypted_fhir_bundle`. But multiple subsystems still operate on `cumulative_fhir_json`:

- **Patient merge** (patients/views.py:1469-1483): reads/writes legacy field
- **Transaction manager** (fhir/transaction_manager.py:292,394,530,570): snapshots/restores legacy field
- **View rollback** (documents/views.py:3660-3681): reads/writes legacy field

Result: patient merges produce empty results, transaction snapshots capture empty data, and rollbacks operate on the wrong field. Data processed through the new pipeline is invisible to these subsystems.

**Files:** `apps/patients/models.py:112-119`, `apps/patients/views.py:1469-1483`, `apps/fhir/transaction_manager.py:292,570`, `apps/documents/views.py:3660-3681`

---

### Finding 44: `serialize_fhir_data` Imported Twice From Different Modules
**Severity:** LOW-MEDIUM | **Category:** Shadow Import

```python
# services.py line 32
from apps.core.jsonb_utils import serialize_fhir_data
# services.py line 47
from .validation import ... serialize_fhir_data  # Overwrites the first!
```

Two different implementations with the same name. The second import silently overwrites the first. Behavior depends on import order, not explicit choice.

**Files:** `apps/fhir/services.py:32,47`

---

### Finding 45: `PatientHistory.action` Choices Also Missing `fhir_rollback`
**Severity:** LOW | **Category:** Data Integrity (extends Finding 18)

`rollback_document_merge()` creates history records with `action='fhir_rollback'` (line 544), not in the choices list. Combined with Finding 18, there are now two undeclared action values in production.

**Files:** `apps/patients/models.py:544,2430-2438`

---

### Finding 46: Patient Merge Operates on Legacy Dict Structure, Not FHIR Bundle
**Severity:** MEDIUM | **Category:** Data Integrity / Silent Failure

The merge logic assumes `cumulative_fhir_json` is `{resourceType: [resources]}`. But `add_fhir_resources()` writes to `encrypted_fhir_bundle` in FHIR Bundle format: `{"resourceType": "Bundle", "entry": [...]}`. The merge iterates over keys like `"resourceType"`, `"entry"`, `"meta"` and tries to extend them as lists — producing nonsensical data. Encrypted data from the source patient is silently lost.

**Files:** `apps/patients/views.py:1461-1484`

---

### Finding 47: Transaction Snapshots Stored Only in Cache — Not Durable
**Severity:** MEDIUM | **Category:** Data Loss Risk

```python
# transaction_manager.py line 306
cache.set(cache_key, snapshot.to_dict(), timeout=86400 * 30)  # 30 days
```

FHIR transaction snapshots (for rollback) are stored only in Redis cache with 30-day TTL. If Redis restarts, flushes, or evicts keys (production has `maxmemory 256mb` with `allkeys-lru`), all snapshots are permanently lost. No database fallback exists. For HIPAA, rollback capability should be durable. Additionally, snapshots operate on `cumulative_fhir_json` (Finding 43), so they snapshot the wrong field.

**Files:** `apps/fhir/transaction_manager.py:306`

---

### Finding 48: View-Level Rollback Differs From `Patient.rollback_document_merge()`
**Severity:** MEDIUM | **Category:** Inconsistent Logic / Partial Rollback

Two rollback implementations exist:

1. `Patient.rollback_document_merge()` — uses `meta.source` matching on `encrypted_fhir_bundle`, atomic, full audit
2. View rollback (documents/views.py:3655-3694) — uses resource ID matching on `cumulative_fhir_json`, simplified

The view is what the UI actually calls. It operates on the wrong field, uses a different matching strategy, and self-describes as "a simplified rollback." The proper method is never invoked from any view.

**Files:** `apps/patients/models.py:397-512`, `apps/documents/views.py:3655-3694`

---

### Finding 49: Import Error in Converters Silently Disables Structured Conversion
**Severity:** LOW-MEDIUM | **Category:** Silent Degradation

```python
# converters.py line 45-58
try:
    from apps.documents.services.ai_extraction import (StructuredMedicalExtraction, ...)
except ImportError:
    logger.warning(...)  # But logger isn't defined until line 61!
    StructuredMedicalExtraction = None
```

If the import fails, `logger.warning` on line 57 references `logger` before it's defined on line 61 — causing a `NameError` that suppresses even the warning. The entire structured conversion silently degrades with no signal to operators.

**Files:** `apps/fhir/converters.py:45-61`

---

### Finding 50: `fhir_json_serializer` Loses Decimal Precision
**Severity:** LOW | **Category:** Data Precision

```python
# services.py line 132
if isinstance(obj, Decimal):
    return float(obj)
```

Converting `Decimal` to `float` loses precision. Lab values like `0.1` mg/dL become `0.10000000000000001`. FHIR R4 specifies decimal values should maintain original precision. Using `str(obj)` would preserve it.

**Files:** `apps/fhir/services.py:132`

---

## Layer 6: Views, Templates & Frontend

### Finding 51: `order_by('last_name', 'first_name')` on Encrypted Patient Fields
**Severity:** MEDIUM | **Category:** Silent Data Corruption (Ordering)

Multiple views order patients by the encrypted `last_name` and `first_name` fields:

```python
# patients/views.py line 137
return queryset.order_by('last_name', 'first_name')

# documents/forms.py line 86
self.fields['patient'].queryset = Patient.objects.order_by('last_name', 'first_name')

# documents/views.py line 318
'patients': Patient.objects.order_by('last_name', 'first_name'),
```

These fields are `encrypt(models.CharField(...))` — the database stores ciphertext. Ordering by ciphertext produces random/nonsensical ordering, not alphabetical. The patient list, patient selects in document forms, and duplicate finder all display patients in gibberish order.

The correct fields for ordering are `last_name_search` and `first_name_search` (unencrypted lowercase copies). Only `apps/reports/forms.py` does this correctly.

**Files:** `apps/patients/views.py:137,1252,1348`, `apps/documents/forms.py:86`, `apps/documents/views.py:318,2974`

---

### Finding 52: `has_fhir_data` Check Uses Legacy Field in Detail View
**Severity:** LOW | **Category:** Incorrect Data Signal (extends Finding 43)

```python
# patients/views.py line 354
'has_fhir_data': bool(self.object.cumulative_fhir_json)
```

The template's `has_fhir_data` flag checks the legacy `cumulative_fhir_json` field (empty for new data), not `encrypted_fhir_bundle` (where data actually lives). If a patient has FHIR data processed through the new pipeline, the UI will show "no FHIR data available" even though data exists. The detail view's `get_fhir_summary()` method at line 244 correctly reads `encrypted_fhir_bundle`, but the statistics dict contradicts it.

**Files:** `apps/patients/views.py:354`

---

### Finding 53: `files_are_identical()` Always Returns True For Same-Size Files
**Severity:** LOW-MEDIUM | **Category:** False Positive Duplicate Detection

```python
# documents/forms.py line 221-228
def files_are_identical(self, file1, file2):
    try:
        if file1.size != file2.size:
            return False
        # For now, assume files with same size are identical
        return True
```

The duplicate detection calculates a SHA-256 hash (`calculate_file_hash`) but then calls `files_are_identical` which ignores the hash entirely and treats all same-size files as duplicates. Two completely different medical PDFs that happen to be the same byte size will be rejected as duplicates. The comment says "In production, you'd want to compare actual content" — this *is* production code. The hash is computed but never used for comparison.

**Files:** `apps/documents/forms.py:162-182,210-228`

---

### Finding 54: `PatientHistory.action='fhir_export'` Not in Choices List
**Severity:** LOW | **Category:** Data Integrity (extends Findings 18, 45)

```python
# patients/views.py line 675
action='fhir_export',
```

The FHIR export view creates a PatientHistory record with `action='fhir_export'`, which is not in the choices list. This is now the third undeclared action value alongside `fhir_merge` (Finding 18) and `fhir_rollback` (Finding 45).

**Files:** `apps/patients/views.py:675`, `apps/patients/models.py:2430-2438`

---

### Finding 55: `DocumentUploadSuccessView.get_object()` Returns Wrong Document
**Severity:** LOW-MEDIUM | **Category:** Wrong Data Displayed

```python
# documents/views.py line 223-236
def get_object(self):
    """Get the most recently uploaded document by this user."""
    try:
        return Document.objects.filter(
            created_by=self.request.user
        ).order_by('-uploaded_at').first()
    except (DatabaseError, OperationalError) as db_error:
        return None
```

After uploading a document, the success page shows "the most recently uploaded document by this user" — but this is a race condition. If two users share an account, or if the user quickly uploads two documents, this may show the wrong document. More critically, the URL `success_url = reverse_lazy('documents:upload-success')` is a generic URL with no document ID — it relies entirely on "latest by user" query, which is inherently racy. `DetailView` with the actual document ID passed from `form_valid` would be correct.

**Files:** `apps/documents/views.py:47,223-236`

---

### Finding 56: PHI Leaked in `Content-Disposition` Filename
**Severity:** LOW-MEDIUM | **Category:** HIPAA / PHI Leakage

```python
# patients/views.py line 670
response['Content-Disposition'] = f'attachment; filename="patient_{patient.mrn}_fhir_export.json"'

# patients/views.py line 809
safe_name = f"{patient.first_name}_{patient.last_name}_Patient_Summary.pdf".replace(' ', '_')
response['Content-Disposition'] = f'attachment; filename="{safe_name}"'
```

The FHIR export includes the patient MRN in the filename, and the PDF summary includes the patient's full name. These filenames appear in browser download history, server access logs, proxy logs, and CDN logs. For HIPAA compliance, PHI (including names and MRNs) should not appear in HTTP headers that get logged by infrastructure. Using opaque identifiers (UUIDs or document IDs) would be safer.

**Files:** `apps/patients/views.py:670,809-810`

---

### Finding 57: `PatientDeleteView` Uses `super(Patient, patient).delete()` — Bypasses Soft Delete
**Severity:** LOW | **Category:** Intentional but Fragile

```python
# patients/views.py line 1092
super(Patient, patient).delete()
```

This explicitly bypasses the Patient model's soft-delete `delete()` override by calling the base `Model.delete()`. This is intentional (development-only hard delete), but the approach is brittle — it depends on the MRO (method resolution order) of `Patient` → `MedicalRecord` → `BaseModel` → `Model`. If the inheritance chain changes, this could silently revert to soft delete or break. A more explicit approach would be `models.Model.delete(patient)` or using `Patient.all_objects.filter(pk=pk).delete()` which calls the QuerySet-level delete.

Additionally, this view only deletes `PatientHistory` and `parsed_data` before deleting the patient, but doesn't clean up Documents (which have `CASCADE` on patient FK — Finding 22). The cascade handles it, but it's implicit and undocumented.

**Files:** `apps/patients/views.py:1092`

---

### Finding 58: Patient Search Rejects Hyphens in MRNs
**Severity:** LOW | **Category:** Usability Bug

```python
# patients/views.py line 63
allowed_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-_@')
```

The search form allows `.-_@` but not `/` or `#`. Many MRN formats use forward slashes (e.g., `MRN-2025/001`) or hash symbols. The comment says these are valid for MRN searches, but the character set is restrictive. Additionally, searching for an MRN containing characters outside this set will silently return "Invalid search criteria" with no results, which a clinician might interpret as "patient not found."

However, this is borderline — the allowed chars include hyphens and periods which cover most common MRN formats. The main risk is future MRN format changes.

**Files:** `apps/patients/views.py:63`

---

### Finding 59: Inline Upload Error Response Returns Unescaped User Input
**Severity:** LOW-MEDIUM | **Category:** XSS Risk

```python
# patients/views.py line 897
return HttpResponse(
    f'<div class="p-3 text-sm text-red-600 bg-red-50 rounded-lg border border-red-200">{error_text}</div>',
    status=422
)
```

The `error_text` variable is constructed from `form.errors` which could include user-supplied field names or values. This is injected directly into an HTML response without escaping. While Django's form error messages are generally safe, custom validation error messages that include user input (like filenames) could introduce reflected XSS. Using `format_html()` or Django's template engine would be safer.

The same pattern appears at line 909 with `{message}`.

**Files:** `apps/patients/views.py:897,909`

---

## Layer 7: Audit, Compliance & Reporting

### Finding 60: `ActivityTypes` Constants — 7 of 13 Don't Match `AuditLog.EVENT_TYPES`
**Severity:** MEDIUM | **Category:** Data Integrity / Audit Completeness

The `ActivityTypes` class (core/utils.py:195-212) defines constants used by `log_user_activity()` throughout the system. But 7 of 13 values have no matching entry in `AuditLog.EVENT_TYPES`:

| ActivityTypes Constant | Value | In EVENT_TYPES? |
|---|---|---|
| `DOCUMENT_PROCESS` | `'document_process'` | NO |
| `PROVIDER_CREATE` | `'provider_create'` | NO |
| `PROVIDER_UPDATE` | `'provider_update'` | NO |
| `PROVIDER_VIEW` | `'provider_view'` | NO |
| `REPORT_GENERATE` | `'report_generate'` | NO |
| `PROFILE_UPDATE` | `'profile_update'` | NO |
| `ADMIN` | `'admin_action'` | NO (`admin_access` exists) |

These non-standard event types are written to the database successfully (Django doesn't enforce choices at DB level), but:
- The audit trail report's event type dropdown only shows valid EVENT_TYPES — these 7 types are invisible to compliance officers
- Any filtering by `event_type` in compliance queries will miss them
- `get_event_type_display()` returns the raw string instead of a human-readable label

Combined with Findings 21, 26, 18, 45, and 54, there are now at least **13 undeclared values** being written to audit/history tables across the system.

**Files:** `apps/core/utils.py:195-212`, `apps/core/models.py:88-128`

---

### Finding 61: Audit Trail Statistics Execute `get_queryset()` Three Times
**Severity:** LOW-MEDIUM | **Category:** Performance

```python
# core/views.py line 150-152
total_logs = self.get_queryset().count()
phi_logs = self.get_queryset().filter(phi_involved=True).count()
failed_logs = self.get_queryset().filter(success=False).count()
```

`get_queryset()` applies 12 optional filters from request parameters. It's called 3 times here (plus once for the actual paginated list), producing 4 separate filtered database queries on every audit trail page load. For a table that grows continuously and may have millions of rows after 7 years of HIPAA retention, this is expensive. A single queryset with `.aggregate()` would replace 3 queries with 1.

**Files:** `apps/core/views.py:150-152`

---

### Finding 62: No Audit Log Retention Enforcement — Logs Grow Forever
**Severity:** MEDIUM | **Category:** Compliance / Operational Risk

`AUDIT_LOG_RETENTION_DAYS = 2555` (7 years) is configured in settings (line 223), but there is **no task, management command, or scheduled job** that enforces this retention policy. The `CELERY_BEAT_SCHEDULE` only includes `cleanup_old_documents` (which is itself a stub — Finding 36). There are no Celery tasks in `apps/core/` at all (`apps/core/tasks.py` doesn't exist).

Audit logs grow without bound. After years of operation, the `audit_logs` table will become a performance bottleneck — especially since every request generates 2 entries (Finding 30). The retention policy exists on paper but is never enforced.

**Files:** `meddocparser/settings/base.py:223,232`, `meddocparser/settings/base.py:350-356`

---

### Finding 63: `SecurityEvent` and `ComplianceReport` Models Are Imported But Never Used in Views
**Severity:** LOW | **Category:** Dead Code / Incomplete Feature

```python
# core/views.py line 18
from apps.core.models import AuditLog, SecurityEvent, ComplianceReport
```

`SecurityEvent` and `ComplianceReport` are imported but never referenced in any view, URL, or template. The models exist in the database (they have migrations), but there's no UI to view security events, no endpoint to generate compliance reports, and no scheduled task to create them. These are orphaned data models — the tables exist but nothing reads from or writes to them except through the Django admin.

The `SecurityEvent.create_from_audit_log()` classmethod exists but is never called from any production code path.

**Files:** `apps/core/views.py:18`, `apps/core/models.py:336-404,407-451`

---

### Finding 64: Audit Log CSV Export Vulnerable to CSV Injection
**Severity:** MEDIUM | **Category:** Security

```python
# core/views.py line 216-236
for log in queryset:
    writer.writerow([
        log.timestamp.isoformat(),
        log.event_type,
        ...
        log.description,        # User-influenced content
        log.error_message,      # Could contain crafted input
        ...
    ])
```

The CSV export writes `description` and `error_message` fields directly into CSV without sanitization. If an attacker crafts input that starts with `=`, `+`, `-`, or `@` (e.g., by manipulating a URL or form field that ends up in an error message), opening the CSV in Excel/Google Sheets would execute the formula. This is a known CSV injection vector. Fields should be prefixed with a single quote or tab character to prevent formula execution.

**Files:** `apps/core/views.py:216-236`

---

### Finding 65: Report Download Leaks PHI in Filename (extends Finding 56)
**Severity:** LOW-MEDIUM | **Category:** HIPAA / PHI Leakage

```python
# reports/views.py line 386-389
first = patient.first_name.strip().replace(' ', '_')
last = patient.last_name.strip().replace(' ', '_')
filename = f"{first}_{last}_{r_type}.{report.format}"
```

Report downloads include patient first/last name in the `Content-Disposition` filename. Same PHI leakage risk as Finding 56 — names appear in browser download history, server logs, and proxy logs.

**Files:** `apps/reports/views.py:386-389,400`

---

### Finding 66: Report Download Uses `open()` Without Context Manager
**Severity:** LOW | **Category:** Resource Leak

```python
# reports/views.py line 355-358
response = FileResponse(
    open(file_path, 'rb'),
    content_type=content_type
)
```

`FileResponse` receives a bare `open()` file handle. Django's `FileResponse` does handle closing the file after streaming, so this technically works. However, if an exception occurs between `open()` and the response being fully consumed (e.g., the `Content-Disposition` logic at line 389 raises an exception due to a missing patient), the file handle leaks. Using `with` or passing `FileResponse(..., as_attachment=True)` would be safer.

**Files:** `apps/reports/views.py:355-358`

---

### Finding 67: Audit Log Export Logs Itself as `phi_export` — Creates Recursive Audit Entries
**Severity:** LOW | **Category:** Audit Noise

```python
# core/views.py line 239-246
AuditLog.log_event(
    event_type='phi_export',
    user=request.user,
    request=request,
    description=f"Exported {queryset.count()} audit log entries",
    phi_involved=True,
    severity='info'
)
```

Exporting audit logs creates a new audit log entry with `phi_involved=True`. If a compliance officer exports audit logs daily (as is common practice), each export creates a new entry that will appear in the next export, which will create another entry, and so on. This isn't technically recursive (it runs once per export), but it pollutes the audit trail with meta-entries about viewing the audit trail itself. Over time, a significant fraction of "PHI access" audit entries will just be "someone looked at the audit logs."

Additionally, this calls `queryset.count()` a second time (the queryset was already counted at line 183 for the export size check), adding another query on what could be a very large table.

**Files:** `apps/core/views.py:239-246`

---

### Finding 68: `AuditTrailReportView` Has Both `audit_access_required` AND `PermissionRequiredMixin`
**Severity:** LOW | **Category:** Redundant / Confusing Authorization

```python
# core/views.py line 23-24
@method_decorator(audit_access_required, name='dispatch')
class AuditTrailReportView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    ...
    permission_required = 'core.view_audit_trail'
```

This view has **three layers** of authorization:
1. `LoginRequiredMixin` — requires authentication
2. `@audit_access_required` — requires admin or auditor role (custom RBAC)
3. `PermissionRequiredMixin` with `permission_required = 'core.view_audit_trail'` — requires Django permission

A user needs all three to pass. The RBAC check (`audit_access_required`) and the Django permission check (`core.view_audit_trail`) are independent systems — a user could have the admin role but lack the Django permission, or vice versa. This creates a confusing matrix where access depends on both systems being correctly configured. The same pattern exists on `AuditLogExportView`.

**Files:** `apps/core/views.py:23-24,33,164-165,170`

---

## Sweep Complete

**Total findings across all 7 layers: 68**

### Summary by Severity

| Severity | Count |
|----------|-------|
| HIGH | 2 (Findings 25, 43) |
| MEDIUM | 16 (Findings 1, 3, 12, 13, 14, 16, 22, 27, 35, 37, 41, 46, 47, 48, 51, 60, 62, 64) |
| LOW-MEDIUM | 14 (Findings 2, 15, 17, 21, 26, 28, 29, 31, 42, 44, 49, 53, 55, 56, 59, 61, 65) |
| LOW | 20 (Remaining) |

### Top 5 Critical Findings

1. **#43 (HIGH):** Dual FHIR storage split — pipeline writes encrypted, but merges/rollbacks/transactions use legacy field
2. **#25 (HIGH):** `@csrf_exempt` on session-authenticated FHIR API endpoints that mutate PHI
3. **#51 (MEDIUM):** All patient ordering sorts by ciphertext — random display order everywhere
4. **#41 (MEDIUM):** Optimistic merge has no automated rollback when extraction is rejected
5. **#60 (MEDIUM):** 7 of 13 activity types invisible to audit trail — compliance blind spots
