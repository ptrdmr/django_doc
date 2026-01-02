# Database Schema Documentation

## Overview

This document provides a comprehensive overview of all database tables in the Medical Document Parser project. The schema is designed for HIPAA compliance with field-level encryption for Protected Health Information (PHI) and comprehensive audit logging.

## Database Technology

- **Database Engine**: PostgreSQL with JSONB support
- **ORM**: Django 5.0 ORM
- **Encryption**: django-cryptography-5 (Fernet encryption) for PHI fields
- **Compliance**: HIPAA-compliant with audit trails and soft delete functionality

---

## Core Tables

### 1. BaseModel (Abstract)

**Purpose**: Abstract base model providing common audit fields for all models.

| Field | Type | Description |
|-------|------|-------------|
| `created_at` | DateTimeField | Auto-set creation timestamp |
| `updated_at` | DateTimeField | Auto-updated modification timestamp |
| `created_by` | ForeignKey(User) | User who created the record |
| `updated_by` | ForeignKey(User) | User who last updated the record |

**Notes**: 
- All concrete models inherit from this base
- Provides consistent audit trail across all tables

### 2. MedicalRecord (Abstract)

**Purpose**: Abstract base for medical data with soft delete functionality.

| Field | Type | Description |
|-------|------|-------------|
| `deleted_at` | DateTimeField | Soft delete timestamp (NULL = not deleted) |
| *(inherits BaseModel fields)* | | |

**Managers**:
- `objects`: Default manager (excludes soft-deleted records)
- `all_objects`: Manager that includes soft-deleted records

**Notes**:
- Extends BaseModel
- Implements soft delete for HIPAA compliance (never hard delete medical data)

---

## User Management & Security

### 3. auth_user (Django Built-in)

**Purpose**: Django's default user authentication table.

| Field | Type | Description |
|-------|------|-------------|
| `id` | AutoField | Primary key |
| `username` | CharField(150) | Unique username |
| `email` | EmailField | User email address |
| `first_name` | CharField(150) | User's first name |
| `last_name` | CharField(150) | User's last name |
| `is_staff` | BooleanField | Django admin access |
| `is_active` | BooleanField | Account active status |
| `is_superuser` | BooleanField | Superuser privileges |
| `date_joined` | DateTimeField | Account creation date |
| `last_login` | DateTimeField | Last login timestamp |
| `password` | CharField | Hashed password |

### 4. roles

**Purpose**: Role-based access control for healthcare environments.

| Field | Type | Description | Indexes |
|-------|------|-------------|---------|
| `id` | UUIDField | Primary key | |
| `name` | CharField(100) | Unique role name (e.g., 'admin', 'provider') | ✓ |
| `display_name` | CharField(150) | Human-readable role name | |
| `description` | TextField | Role responsibilities description | |
| `is_active` | BooleanField | Role availability status | ✓ |
| `is_system_role` | BooleanField | System-defined role (cannot be deleted) | |
| `created_at` | DateTimeField | Creation timestamp | ✓ |
| `updated_at` | DateTimeField | Last update timestamp | |
| `created_by` | ForeignKey(User) | Creator user | |

**Relationships**:
- Many-to-Many with Django `Permission` model
- One-to-Many with `UserProfile` (reverse: `user_profiles`)

**Standard Roles**:
- **Admin**: Full system access
- **Provider**: Healthcare provider access to patient records
- **Staff**: Administrative staff with limited patient access
- **Auditor**: Read-only access to audit logs

### 5. user_profiles

**Purpose**: Extended user profiles with role assignments and security settings.

| Field | Type | Description | Indexes |
|-------|------|-------------|---------|
| `id` | AutoField | Primary key | |
| `user` | OneToOneField(User) | Associated user account | ✓ |
| `allowed_ip_ranges` | JSONField | CIDR notation IP restrictions | |
| `last_login_ip` | GenericIPAddressField | Last login IP address | ✓ |
| `require_mfa` | BooleanField | MFA requirement flag | |
| `is_locked` | BooleanField | Account lock status | ✓ |
| `lockout_until` | DateTimeField | Account unlock time | |
| `department` | CharField(100) | User's department | |
| `job_title` | CharField(100) | User's job title | |
| `phone` | CharField(20) | Contact phone number | |
| `created_at` | DateTimeField | Profile creation timestamp | ✓ |
| `updated_at` | DateTimeField | Last update timestamp | |

**Relationships**:
- One-to-One with Django `User`
- Many-to-Many with `Role`

---

## Patient Data

### 6. patients

**Purpose**: Core patient demographics and medical information storage.

| Field | Type | Encryption | Description | Indexes |
|-------|------|------------|-------------|---------|
| `id` | UUIDField | No | Primary key | |
| `mrn` | CharField(50) | No | Medical Record Number (unique) | ✓ |
| `first_name` | CharField(255) | **Encrypted** | Patient first name (PHI) | |
| `last_name` | CharField(255) | **Encrypted** | Patient last name (PHI) | |
| `date_of_birth` | CharField(10) | **Encrypted** | DOB in YYYY-MM-DD format (PHI) | ✓ |
| `gender` | CharField(1) | No | Gender (M/F/O) - not considered PHI | |
| `ssn` | CharField(11) | **Encrypted** | Social Security Number (PHI) | |
| `address` | TextField | **Encrypted** | Patient address (PHI) | |
| `phone` | CharField(20) | **Encrypted** | Phone number (PHI) | |
| `email` | CharField(100) | **Encrypted** | Email address (PHI) | |
| `cumulative_fhir_json` | JSONField | No | Legacy FHIR storage (being migrated) | |
| `encrypted_fhir_bundle` | JSONField | **Encrypted** | Complete FHIR data with PHI | |
| `searchable_medical_codes` | JSONField | No | Medical codes without PHI for searching | ✓ |
| `encounter_dates` | JSONField | No | List of encounter dates for searching | ✓ |
| `provider_references` | JSONField | No | Provider references for searching | ✓ |
| `deleted_at` | DateTimeField | No | Soft delete timestamp | |
| *(inherits BaseModel fields)* | | | |

**Key Features**:
- **Hybrid Encryption**: PHI encrypted, searchable metadata unencrypted
- **FHIR Storage**: Complete FHIR bundles with provenance tracking
- **Soft Delete**: Never hard delete patient records
- **Search Optimization**: Extracted codes for fast clinical searches

### 7. patient_history

**Purpose**: Audit trail for all patient record changes.

| Field | Type | Description | Indexes |
|-------|------|-------------|---------|
| `id` | AutoField | Primary key | |
| `patient` | ForeignKey(Patient) | Related patient | ✓ |
| `action` | CharField(50) | Type of change (created/updated/fhir_append) | ✓ |
| `fhir_version` | CharField(20) | FHIR version used (default: 4.0.1) | |
| `changed_at` | DateTimeField | When change occurred | ✓ |
| `changed_by` | ForeignKey(User) | User who made the change | |
| `fhir_delta` | JSONField | FHIR resources added (sanitized, no PHI) | |
| `notes` | TextField | Change description | |
| *(inherits BaseModel fields)* | | |

**Action Types**:
- `created`: Patient record created
- `updated`: Patient demographics updated
- `fhir_append`: FHIR resources added
- `fhir_history_preserved`: Historical data preserved
- `document_processed`: Document processing completed

---

## Document Management

### 8. documents

**Purpose**: Medical document upload and processing tracking.

| Field | Type | Encryption | Description | Indexes |
|-------|------|------------|-------------|---------|
| `id` | AutoField | No | Primary key | |
| `patient` | ForeignKey(Patient) | No | Associated patient | ✓ |
| `filename` | CharField(255) | No | Original uploaded filename | |
| `file` | EncryptedFileField | **Encrypted** | PDF file (encrypted at rest) | |
| `file_size` | PositiveIntegerField | No | File size in bytes | |
| `status` | CharField(20) | No | Processing status | ✓ |
| `uploaded_at` | DateTimeField | No | Upload timestamp | ✓ |
| `processing_started_at` | DateTimeField | No | Processing start time | |
| `processed_at` | DateTimeField | No | Processing completion time | |
| `original_text` | TextField | **Encrypted** | Extracted PDF text (PHI) | |
| `error_message` | TextField | No | Processing error details | |
| `processing_attempts` | PositiveIntegerField | No | Number of retry attempts | |
| `notes` | TextField | **Encrypted** | Additional notes (PHI) | |
| *(inherits BaseModel fields)* | | | |

**Status Values**:
- `pending`: Awaiting processing
- `processing`: Currently being processed
- `completed`: Processing successful
- `failed`: Processing failed
- `review`: Needs manual review

**Relationships**:
- Many-to-Many with `Provider` through document associations

### 9. parsed_data

**Purpose**: AI-extracted data from documents with optimistic concurrency review workflow.

| Field | Type | Encryption | Description | Indexes |
|-------|------|------------|-------------|---------|
| `id` | AutoField | No | Primary key | |
| `document` | OneToOneField(Document) | No | Source document | ✓ |
| `patient` | ForeignKey(Patient) | No | Associated patient | ✓ |
| `extraction_json` | JSONField | No | Raw AI extraction results | |
| `fhir_delta_json` | JSONField | No | FHIR resources from document | |
| `ai_model_used` | CharField(100) | No | AI model identifier | |
| `extraction_confidence` | FloatField | No | AI confidence score (0.0-1.0) | |
| `processing_time_seconds` | FloatField | No | Processing duration | |
| `merged_at` | DateTimeField | No | When merged to patient record | ✓ |
| `is_merged` | BooleanField | No | Merge status flag | ✓ |
| `reviewed_by` | ForeignKey(User) | No | Reviewing user | |
| `reviewed_at` | DateTimeField | No | Review timestamp | |
| `is_approved` | BooleanField | No | **DEPRECATED** - Use `review_status` instead | ✓ |
| **`review_status`** | **CharField(20)** | **No** | **5-state review machine (Task 41)** | **✓** |
| **`auto_approved`** | **BooleanField** | **No** | **Auto-approved for immediate merge (Task 41)** | **✓** |
| **`flag_reason`** | **TextField** | **No** | **Reason for flagging (Task 41)** | |
| `extraction_quality_score` | FloatField | No | Quality assessment (0.0-1.0) | |
| `review_notes` | TextField | **Encrypted** | Review comments (PHI) | |
| `corrections` | JSONField | No | Manual data corrections | |
| `clinical_date` | DateField | No | Clinical date for medical event (Task 35) | ✓ |
| `date_source` | CharField(20) | No | Date source: extracted/manual (Task 35) | |
| `date_status` | CharField(20) | No | Date verification status (Task 35) | |
| *(inherits BaseModel fields)* | | | |

**Task 41 - Optimistic Concurrency Fields:**

**`review_status` Choices (5-State Machine)**:
- `pending`: Initial state, not yet evaluated
- `auto_approved`: High quality, merged immediately, no review needed
- `flagged`: Low quality, merged but needs human review
- `reviewed`: Human verified and approved
- `rejected`: Human rejected, may need rollback

**Auto-Approval Criteria** (ALL must be true):
1. ✅ Confidence ≥ 0.80
2. ✅ Primary AI model used (Claude, not GPT fallback)
3. ✅ At least 1 resource extracted
4. ✅ If < 3 resources, confidence must be ≥ 0.95
5. ✅ No patient data conflicts (DOB/name match)

**Flagging Triggers** (ANY ONE triggers flagging):
1. ❌ Confidence < 0.80
2. ❌ Fallback model used (GPT)
3. ❌ Zero resources extracted
4. ❌ < 3 resources AND confidence < 0.95
5. ❌ Patient data conflict detected

**Migration**: `0013_add_optimistic_concurrency_fields.py`

---

## Provider Management

### 10. providers

**Purpose**: Healthcare provider information storage.

| Field | Type | Description | Indexes |
|-------|------|-------------|---------|
| `id` | UUIDField | Primary key | |
| `npi` | CharField(10) | National Provider Identifier (unique) | ✓ |
| `first_name` | CharField(100) | Provider first name | ✓ |
| `last_name` | CharField(100) | Provider last name | ✓ |
| `specialty` | CharField(100) | Medical specialty | ✓ |
| `organization` | CharField(200) | Healthcare organization | ✓ |
| `deleted_at` | DateTimeField | Soft delete timestamp | |
| *(inherits BaseModel fields)* | | |

**Security Note**: Provider data should be considered for encryption when linked to patient records.

### 11. provider_history

**Purpose**: Audit trail for provider record changes.

| Field | Type | Description | Indexes |
|-------|------|-------------|---------|
| `id` | AutoField | Primary key | |
| `provider` | ForeignKey(Provider) | Related provider | ✓ |
| `action` | CharField(50) | Type of change | ✓ |
| `changed_at` | DateTimeField | Change timestamp | ✓ |
| `changed_by` | ForeignKey(User) | User who made change | |
| `changes` | JSONField | Details of changes made | |
| `notes` | TextField | Change description | |
| *(inherits BaseModel fields)* | | |

**Action Types**:
- `created`: Provider record created
- `updated`: Provider information updated
- `linked_to_document`: Associated with document
- `unlinked_from_document`: Removed from document

---

## Audit & Compliance

### 12. audit_logs

**Purpose**: Comprehensive HIPAA compliance audit logging.

| Field | Type | Description | Indexes |
|-------|------|-------------|---------|
| `id` | AutoField | Primary key | |
| `timestamp` | DateTimeField | Event timestamp | ✓ |
| `event_type` | CharField(50) | Type of event (see choices below) | ✓ |
| `category` | CharField(50) | Event category | ✓ |
| `severity` | CharField(20) | Severity level (info/warning/error/critical) | ✓ |
| `user` | ForeignKey(User) | User who performed action | ✓ |
| `username` | CharField(150) | Username (preserved if user deleted) | |
| `user_email` | EmailField | User email | |
| `session_key` | CharField(40) | Session identifier | |
| `ip_address` | GenericIPAddressField | Client IP address | |
| `user_agent` | TextField | Browser/client information | |
| `request_method` | CharField(10) | HTTP method (GET/POST/etc.) | |
| `request_url` | URLField | Request URL | |
| `content_type` | ForeignKey(ContentType) | Related object type | |
| `object_id` | CharField(50) | Related object ID (supports UUIDs) | |
| `description` | TextField | Event description | |
| `details` | JSONField | Additional event data | |
| `patient_mrn` | CharField(50) | Patient MRN (if applicable) | ✓ |
| `phi_involved` | BooleanField | Whether PHI was accessed | ✓ |
| `success` | BooleanField | Operation success status | |
| `error_message` | TextField | Error details (if failed) | |

**Event Types** (21 total):
- Authentication: `login`, `logout`, `login_failed`, `password_change`, `password_reset`, `account_locked`, `account_unlocked`
- PHI Access: `phi_access`, `phi_create`, `phi_update`, `phi_delete`, `phi_export`
- Documents: `document_upload`, `document_download`, `document_view`, `document_delete`
- Patients: `patient_create`, `patient_update`, `patient_view`, `patient_search`
- FHIR: `fhir_export`, `fhir_import`
- **Optimistic Concurrency (Task 41.28)**: **`extraction_auto_approved`**, **`extraction_flagged`**
- System: `system_backup`, `system_restore`, `admin_access`, `config_change`
- Security: `security_violation`, `data_breach`, `unauthorized_access`

**Categories**:
- `authentication`, `authorization`, `data_access`, `data_modification`, `system_admin`, `security`, `compliance`

### 13. security_events

**Purpose**: High-priority security incidents requiring immediate attention.

| Field | Type | Description | Indexes |
|-------|------|-------------|---------|
| `id` | AutoField | Primary key | |
| `timestamp` | DateTimeField | Event timestamp | ✓ |
| `threat_level` | CharField(20) | Threat severity (low/medium/high/critical) | ✓ |
| `status` | CharField(20) | Investigation status | ✓ |
| `audit_log` | ForeignKey(AuditLog) | Related audit log entry | |
| `title` | CharField(200) | Security event title | |
| `description` | TextField | Event description | |
| `mitigation_steps` | TextField | Recommended mitigation | |
| `assigned_to` | ForeignKey(User) | Assigned investigator | |
| `investigation_notes` | TextField | Investigation details | |
| `resolved_at` | DateTimeField | Resolution timestamp | |
| `resolved_by` | ForeignKey(User) | Resolver user | |

**Status Values**:
- `open`: New security event
- `investigating`: Under investigation
- `resolved`: Investigation complete
- `false_positive`: Determined not a threat

### 14. compliance_reports

**Purpose**: Periodic HIPAA compliance reporting.

| Field | Type | Description | Indexes |
|-------|------|-------------|---------|
| `id` | AutoField | Primary key | |
| `timestamp` | DateTimeField | Report generation time | |
| `report_type` | CharField(20) | Report frequency type | ✓ |
| `period_start` | DateTimeField | Report period start | ✓ |
| `period_end` | DateTimeField | Report period end | ✓ |
| `total_events` | IntegerField | Total audit events | |
| `phi_access_events` | IntegerField | PHI access count | |
| `failed_login_attempts` | IntegerField | Failed login count | |
| `security_violations` | IntegerField | Security violation count | |
| `compliance_score` | DecimalField(5,2) | Compliance percentage | |
| `recommendations` | TextField | Compliance recommendations | |
| `report_file` | FileField | Generated report file | |

**Report Types**:
- `daily`, `weekly`, `monthly`, `quarterly`, `annual`, `incident`, `audit`

### 15. api_usage_logs

**Purpose**: AI API cost tracking and performance monitoring.

| Field | Type | Description | Indexes |
|-------|------|-------------|---------|
| `id` | AutoField | Primary key | |
| `document` | ForeignKey(Document) | Processed document | ✓ |
| `patient` | ForeignKey(Patient) | Associated patient | ✓ |
| `processing_session` | UUIDField | Session identifier for multi-chunk docs | ✓ |
| `provider` | CharField(50) | AI provider (anthropic/openai) | ✓ |
| `model` | CharField(100) | AI model used | ✓ |
| `input_tokens` | PositiveIntegerField | Input token count | |
| `output_tokens` | PositiveIntegerField | Output token count | |
| `total_tokens` | PositiveIntegerField | Total token usage | |
| `cost_usd` | DecimalField(10,6) | API call cost in USD | ✓ |
| `processing_started` | DateTimeField | API call start time | |
| `processing_completed` | DateTimeField | API call completion time | |
| `processing_duration_ms` | PositiveIntegerField | Duration in milliseconds | |
| `success` | BooleanField | API call success status | ✓ |
| `error_message` | TextField | Error details (if failed) | |
| `chunk_number` | PositiveIntegerField | Document chunk number | |
| `total_chunks` | PositiveIntegerField | Total chunks for document | |
| `created_at` | DateTimeField | Log entry creation | ✓ |

---

## FHIR Processing

### 16. fhir_merge_configurations

**Purpose**: Configuration profiles for FHIR data merging behavior.

| Field | Type | Description | Indexes |
|-------|------|-------------|---------|
| `id` | AutoField | Primary key | |
| `name` | CharField(100) | Configuration name (unique) | |
| `description` | TextField | Configuration description | |
| `is_default` | BooleanField | Default configuration flag | |
| `is_active` | BooleanField | Configuration active status | |
| `validate_fhir` | BooleanField | Enable FHIR validation | |
| `resolve_conflicts` | BooleanField | Enable conflict resolution | |
| `deduplicate_resources` | BooleanField | Enable deduplication | |
| `create_provenance` | BooleanField | Create provenance tracking | |
| `default_conflict_strategy` | CharField(20) | Conflict resolution strategy | |
| `deduplication_tolerance_hours` | IntegerField | Duplicate detection window | |
| `near_duplicate_threshold` | FloatField | Near-duplicate similarity threshold | |
| `fuzzy_duplicate_threshold` | FloatField | Fuzzy duplicate similarity threshold | |
| `max_processing_time_seconds` | IntegerField | Processing timeout | |
| `advanced_config` | JSONField | Advanced settings in JSON | |
| `created_by` | ForeignKey(User) | Configuration creator | |
| `created_at` | DateTimeField | Creation timestamp | |
| `updated_at` | DateTimeField | Last update timestamp | |

**Conflict Strategies**:
- `newest_wins`: Most recent data takes precedence
- `preserve_both`: Keep conflicting values
- `manual_review`: Flag for human review
- `confidence_based`: Use AI confidence scores

### 17. fhir_merge_configuration_audit

**Purpose**: Audit trail for FHIR configuration changes.

| Field | Type | Description | Indexes |
|-------|------|-------------|---------|
| `id` | AutoField | Primary key | |
| `configuration` | ForeignKey(FHIRMergeConfiguration) | Related configuration | |
| `action` | CharField(20) | Type of change | |
| `changes` | JSONField | Details of changes made | |
| `performed_by` | ForeignKey(User) | User who made change | |
| `timestamp` | DateTimeField | Change timestamp | ✓ |

**Action Types**:
- `created`, `updated`, `activated`, `deactivated`, `deleted`

### 18. fhir_merge_operations

**Purpose**: Tracking of individual FHIR merge operations.

| Field | Type | Description | Indexes |
|-------|------|-------------|---------|
| `id` | UUIDField | Primary key | |
| `patient` | ForeignKey(Patient) | Target patient | ✓ |
| `configuration` | ForeignKey(FHIRMergeConfiguration) | Merge configuration used | |
| `document` | ForeignKey(Document) | Source document (optional) | |
| `operation_type` | CharField(20) | Type of merge operation | ✓ |
| `status` | CharField(20) | Operation status | ✓ |
| `progress_percentage` | IntegerField | Progress (0-100) | |
| `current_step` | CharField(100) | Current processing step | |
| `created_at` | DateTimeField | Operation creation time | |
| `started_at` | DateTimeField | Processing start time | |
| `completed_at` | DateTimeField | Processing completion time | |
| `merge_result` | JSONField | Complete merge results | |
| `error_details` | JSONField | Error information | |
| `processing_time_seconds` | FloatField | Total processing time | |
| `resources_processed` | IntegerField | FHIR resources processed | |
| `conflicts_detected` | IntegerField | Conflicts found | |
| `conflicts_resolved` | IntegerField | Conflicts resolved | |
| `created_by` | ForeignKey(User) | Operation initiator | |
| `webhook_sent` | BooleanField | Webhook notification status | |
| `webhook_url` | URLField | Webhook endpoint | |
| `webhook_sent_at` | DateTimeField | Webhook send time | |

**Operation Types**:
- `single_document`: Single document merge
- `batch_documents`: Multiple document merge
- `reconciliation`: Data reconciliation
- `manual_merge`: Manual merge operation

**Status Values**:
- `pending`, `queued`, `processing`, `completed`, `failed`, `cancelled`, `partial_success`

---

## Django System Tables

### 19. django_migrations

**Purpose**: Django migration tracking (system table).

| Field | Type | Description |
|-------|------|-------------|
| `id` | AutoField | Primary key |
| `app` | CharField(255) | Django app name |
| `name` | CharField(255) | Migration filename |
| `applied` | DateTimeField | When migration was applied |

### 20. django_content_type

**Purpose**: Django content type framework (system table).

| Field | Type | Description |
|-------|------|-------------|
| `id` | AutoField | Primary key |
| `app_label` | CharField(100) | Django app label |
| `model` | CharField(100) | Model name |

### 21. auth_permission

**Purpose**: Django permission system (system table).

| Field | Type | Description |
|-------|------|-------------|
| `id` | AutoField | Primary key |
| `name` | CharField(255) | Permission name |
| `content_type_id` | IntegerField | Related content type |
| `codename` | CharField(100) | Permission code |

---

## Relationships Overview

### Primary Relationships

1. **User ↔ UserProfile**: One-to-One relationship
2. **UserProfile ↔ Role**: Many-to-Many relationship
3. **Role ↔ Permission**: Many-to-Many relationship
4. **Patient ↔ Document**: One-to-Many (Patient has many Documents)
5. **Document ↔ ParsedData**: One-to-One relationship
6. **Document ↔ Provider**: Many-to-Many relationship
7. **Patient ↔ PatientHistory**: One-to-Many (audit trail)
8. **Provider ↔ ProviderHistory**: One-to-Many (audit trail)

### Audit Relationships

- **AuditLog**: Generic foreign key to any model via ContentType
- **SecurityEvent**: One-to-One with AuditLog
- **APIUsageLog**: Many-to-One with Document and Patient
- **FHIRMergeOperation**: Many-to-One with Patient, Document, and Configuration

---

## Security & Compliance Features

### Field-Level Encryption (PHI)

**Encrypted Fields** (using django-cryptography-5):
- `Patient`: `first_name`, `last_name`, `date_of_birth`, `ssn`, `address`, `phone`, `email`, `encrypted_fhir_bundle`
- `Document`: `original_text`, `notes`
- `ParsedData`: `review_notes`

### Soft Delete Implementation

**Models with Soft Delete**:
- `Patient` (via MedicalRecord)
- `Provider` (via MedicalRecord)

**Behavior**:
- `objects` manager excludes deleted records
- `all_objects` manager includes deleted records
- `delete()` method sets `deleted_at` timestamp instead of removing record

### Audit Trail Coverage

**Complete Audit Trails**:
- All user authentication events
- All PHI access and modifications
- All document operations
- All patient record changes
- All provider record changes
- All FHIR merge operations
- All configuration changes

### Database Indexes

**Performance Optimizations**:
- Primary key indexes on all tables
- Foreign key indexes for relationships
- Composite indexes for common query patterns
- JSONB indexes for FHIR data searches
- Timestamp indexes for audit queries

---

## Data Flow Summary

1. **Document Upload**: User uploads PDF → `documents` table
2. **AI Processing**: Document processed → results in `parsed_data` table
3. **FHIR Generation**: AI extracts medical data → FHIR resources created
4. **Review Workflow**: Human reviews `parsed_data` → approves for merge
5. **Data Merge**: Approved data merged into `patients.encrypted_fhir_bundle`
6. **Audit Logging**: All operations logged in `audit_logs` table
7. **Search Optimization**: Medical codes extracted to `patients.searchable_medical_codes`

---

## Future Enhancements

### Planned Tables (Not Yet Implemented)

- **reports**: Custom reporting tables (currently empty models.py)
- **document_providers**: Junction table for document-provider relationships (commented out)

### Migration Status

- ✅ **Core models**: Fully implemented
- ✅ **Encryption**: PHI fields encrypted with django-cryptography-5
- ✅ **Audit logging**: Complete HIPAA audit trail
- ✅ **FHIR processing**: Advanced merge configurations
- 🔄 **Provider encryption**: Planned for provider PHI fields
- 🔄 **Reports module**: Awaiting implementation

---

*Updated: 2026-01-01 22:24:01 | Added Task 41 optimistic concurrency fields and Task 41.28 audit event types*
