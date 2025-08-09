# 🔌 API Documentation

## Overview

REST API documentation for the Medical Document Parser. This covers both web endpoints and API endpoints for the medical document processing platform.

## FHIR Merge Operations API - Task 14 Complete ✅

### Complete FHIR Data Integration API

The FHIR merge API provides comprehensive endpoints for triggering, monitoring, and managing FHIR data integration operations with advanced features including batch processing, configuration management, and real-time monitoring.

### Authentication Required
All FHIR merge endpoints require authentication and appropriate permissions:
- Login required for all operations
- `fhir.add_fhirmergeoperation` permission for triggering operations
- `fhir.change_fhirmergeoperation` permission for status updates
- Organization-based patient access control enforced

### Rate Limiting
- **Default Limit**: 10 operations per hour per user
- **Configurable**: Via `FHIR_MERGE_RATE_LIMIT_PER_HOUR` setting
- **Superuser Bypass**: Superusers exempt from rate limits
- **Response**: HTTP 429 when limit exceeded

#### Trigger FHIR Merge Operation
**POST** `/fhir/api/merge/trigger/`

Trigger a new FHIR merge operation for single documents or document batches.

**Request Body:**
```json
{
  "patient_id": "uuid-string",
  "document_ids": ["doc1-uuid", "doc2-uuid"],  // Optional: for batch processing
  "operation_type": "merge_document",          // or "batch_merge"
  "configuration_profile": "routine_update",   // optional: initial_import, reconciliation
  "async": true,                              // optional: default true
  "webhook_url": "https://example.com/webhook" // optional: completion notification
}
```

**Response - Async Operation (default):**
```json
{
  "operation_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "message": "FHIR merge operation queued successfully",
  "patient_mrn": "MRN001",
  "estimated_completion": "2025-01-09T15:30:00Z",
  "operation_type": "merge_document",
  "documents_count": 2
}
```

**Response - Sync Operation:**
```json
{
  "operation_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "message": "FHIR merge operation completed successfully",
  "result": {
    "resources_added": 5,
    "resources_updated": 2,
    "conflicts_detected": 1,
    "conflicts_resolved": 1,
    "validation_score": 95.5,
    "processing_time_seconds": 2.3
  }
}
```

**Error Responses:**
```json
// Rate limit exceeded
{
  "error": "rate_limit_exceeded",
  "message": "Rate limit exceeded. You can make 10 requests per hour.",
  "retry_after": 3600
}

// Patient not found or access denied
{
  "error": "patient_not_found",
  "message": "Patient not found or access denied"
}

// Invalid document IDs
{
  "error": "invalid_documents",
  "message": "One or more document IDs are invalid or inaccessible",
  "invalid_ids": ["invalid-uuid"]
}
```

#### List FHIR Merge Operations
**GET** `/fhir/api/merge/operations/`

List FHIR merge operations with filtering and pagination.

**Query Parameters:**
- `patient_id` - Filter by patient UUID
- `status` - Filter by status (`queued`, `processing`, `completed`, `failed`, `cancelled`)
- `operation_type` - Filter by operation type
- `page` - Page number (default: 1)
- `page_size` - Items per page (default: 20, max: 100)

**Response:**
```json
{
  "count": 45,
  "next": "/fhir/api/merge/operations/?page=3",
  "previous": "/fhir/api/merge/operations/?page=1",
  "results": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "patient_mrn": "MRN001",
      "status": "completed",
      "operation_type": "merge_document",
      "created_at": "2025-01-09T14:00:00Z",
      "completed_at": "2025-01-09T14:02:30Z",
      "progress_percentage": 100,
      "current_step": "completed",
      "resources_processed": 7,
      "conflicts_detected": 1,
      "webhook_url": "https://example.com/webhook"
    }
  ]
}
```

#### Get FHIR Merge Operation Status
**GET** `/fhir/api/merge/operations/{operation_id}/`

Get detailed status and progress for a specific FHIR merge operation.

**Path Parameters:**
- `operation_id` - UUID of the merge operation

**Response - In Progress:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "patient_mrn": "MRN001",
  "status": "processing",
  "operation_type": "batch_merge",
  "created_at": "2025-01-09T14:00:00Z",
  "started_at": "2025-01-09T14:00:15Z",
  "progress_percentage": 65,
  "current_step": "conflict_resolution",
  "step_description": "Resolving conflicts in medication statements",
  "documents_count": 3,
  "documents_processed": 2,
  "resources_processed": 12,
  "conflicts_detected": 2,
  "conflicts_resolved": 1,
  "estimated_completion": "2025-01-09T14:05:00Z",
  "configuration_profile": "routine_update",
  "webhook_url": null
}
```

**Response - Completed:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "patient_mrn": "MRN001",
  "status": "completed",
  "operation_type": "merge_document",
  "created_at": "2025-01-09T14:00:00Z",
  "started_at": "2025-01-09T14:00:15Z",
  "completed_at": "2025-01-09T14:02:30Z",
  "progress_percentage": 100,
  "current_step": "completed",
  "processing_time_seconds": 135.5,
  "documents_count": 1,
  "resources_processed": 5,
  "resources_added": 3,
  "resources_updated": 2,
  "conflicts_detected": 1,
  "conflicts_resolved": 1,
  "duplicates_removed": 2,
  "validation_score": 98.5,
  "webhook_delivered": true,
  "webhook_delivered_at": "2025-01-09T14:02:35Z"
}
```

#### Get FHIR Merge Operation Result
**GET** `/fhir/api/merge/operations/{operation_id}/result/`

Get detailed merge results for a completed FHIR merge operation.

**Response - Success:**
```json
{
  "operation_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "result": {
    "operation_summary": {
      "total_documents": 2,
      "total_resources_processed": 12,
      "resources_added": 7,
      "resources_updated": 3,
      "resources_skipped": 2,
      "conflicts_detected": 2,
      "conflicts_resolved": 2,
      "duplicates_removed": 1,
      "validation_score": 96.5,
      "processing_time_seconds": 45.2
    },
    "resource_breakdown": {
      "Patient": {"added": 0, "updated": 1},
      "Observation": {"added": 3, "updated": 1},
      "Condition": {"added": 2, "updated": 1},
      "MedicationStatement": {"added": 2, "updated": 0}
    },
    "conflict_summary": {
      "value_conflicts": 1,
      "temporal_conflicts": 1,
      "resolved_automatically": 2,
      "flagged_for_review": 0
    },
    "validation_results": {
      "critical_issues": 0,
      "errors": 0,
      "warnings": 1,
      "info": 3,
      "auto_corrections": 2
    },
    "performance_metrics": {
      "cache_hit_ratio": 0.89,
      "database_queries": 15,
      "memory_usage_mb": 45.2,
      "api_calls_made": 0
    }
  }
}
```

**Response - Failed:**
```json
{
  "operation_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "failed",
  "error": {
    "error_type": "validation_error",
    "message": "Critical FHIR validation errors detected",
    "details": {
      "validation_errors": [
        {
          "severity": "critical",
          "resource_type": "Observation",
          "field": "subject",
          "message": "Required field 'subject' is missing"
        }
      ],
      "partial_results": {
        "resources_processed": 8,
        "resources_added": 4
      }
    },
    "timestamp": "2025-01-09T14:02:15Z"
  }
}
```

#### Cancel FHIR Merge Operation
**POST** `/fhir/api/merge/operations/{operation_id}/cancel/`

Cancel a pending or processing FHIR merge operation.

**Path Parameters:**
- `operation_id` - UUID of the merge operation

**Response - Success:**
```json
{
  "operation_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "cancelled",
  "message": "FHIR merge operation cancelled successfully",
  "cancelled_at": "2025-01-09T14:01:30Z"
}
```

**Response - Cannot Cancel:**
```json
{
  "error": "cannot_cancel",
  "message": "Operation cannot be cancelled (status: completed)"
}
```

### Webhook Notifications

When a webhook URL is provided, the system will send a POST request upon operation completion:

**Webhook Payload:**
```json
{
  "operation_id": "550e8400-e29b-41d4-a716-446655440000",
  "patient_mrn": "MRN001",
  "status": "completed",
  "operation_type": "merge_document",
  "completed_at": "2025-01-09T14:02:30Z",
  "processing_time_seconds": 135.5,
  "result_summary": {
    "resources_added": 5,
    "resources_updated": 2,
    "conflicts_resolved": 1,
    "validation_score": 98.5
  },
  "webhook_id": "webhook-550e8400-e29b-41d4-a716-446655440000"
}
```

### Performance Dashboard

Access the FHIR performance monitoring dashboard:

**GET** `/fhir/dashboard/`

Real-time performance metrics and system health monitoring with:
- Operation timeline and resource distribution charts
- Cache performance monitoring with hit/miss ratios  
- System health indicators with alerts
- API usage tracking and cost analysis
- Performance trends and bottleneck identification

### Configuration Profiles

Available merge configuration profiles:

- **`initial_import`**: Conservative settings for first-time data import
- **`routine_update`**: Balanced settings for regular document processing  
- **`reconciliation`**: Aggressive conflict resolution for data cleanup

### Error Codes

| Code | Description |
|------|-------------|
| `rate_limit_exceeded` | API rate limit exceeded |
| `patient_not_found` | Patient not found or access denied |
| `invalid_documents` | Invalid document IDs provided |
| `operation_not_found` | Operation ID not found |
| `cannot_cancel` | Operation cannot be cancelled |
| `validation_error` | FHIR validation errors detected |
| `processing_error` | Error during merge processing |
| `configuration_error` | Invalid merge configuration |

## Document Processing Endpoints - Task 6 Complete ✅

### Document Upload and Management (Web Views)

#### Upload Document (Web Form)
**POST** `/documents/upload/`

Upload a medical document via web form interface.

**Request:**
```http
POST /documents/upload/
Content-Type: multipart/form-data

patient: <patient_id>
file: <pdf_file>
```

**Response:**
- **Success**: Redirects to `/documents/upload/success/` with success message
- **Error**: Returns form with validation errors

**Features:**
- PDF-only uploads with 50MB size limit
- Patient association required
- Triggers async Celery task for processing
- HIPAA-compliant audit logging
- Duplicate detection
- CSRF protection

#### Upload Success Page
**GET** `/documents/upload/success/`

Shows confirmation page after successful upload with processing information.

#### List Documents (Web View)
**GET** `/documents/`

Display paginated list of documents with filtering.

**Query Parameters:**
- `status` - Filter by status (`pending`, `processing`, `completed`, `failed`, `review`)
- `patient` - Filter by patient ID
- `q` - Search by filename
- `page` - Page number (20 documents per page)

**Response:** HTML template with document list

#### Document Detail (Web View)
**GET** `/documents/<id>/`

Display detailed document information including processing results.

**Response:** HTML template with document details, processing status, and metadata

#### Retry Document Processing (Hybrid)
**POST** `/documents/<id>/retry/`

Retry processing for a failed document. Supports both web forms and AJAX.

**AJAX Request:**
```http
POST /documents/123/retry/
Content-Type: application/json
```

**AJAX Response:**
```json
{
    "success": true,
    "message": "Document 'filename.pdf' has been queued for reprocessing.",
    "status": "pending"
}
```

**Web Form Response:**
- **Success**: Redirects to document detail with success message
- **Error**: Redirects to document detail with error message

### Real-Time API Endpoints (JSON)

#### Processing Status Monitor
**GET** `/documents/api/processing-status/`

Get real-time status updates for user's documents.

**Response:**
```json
{
    "success": true,
    "processing_documents": [
        {
            "id": 123,
            "filename": "report.pdf",
            "status": "processing",
            "status_display": "Processing",
            "patient_name": "John Doe",
            "uploaded_at": "2025-01-27T10:30:00Z"
        }
    ],
    "recent_documents": [
        {
            "id": 124,
            "filename": "labs.pdf",
            "status": "completed",
            "status_display": "Completed",
            "patient_name": "Jane Smith",
            "completed_at": "2025-01-27T10:25:00Z"
        }
    ],
    "timestamp": "2025-01-27T10:35:00Z"
}
```

**Notes:**
- Returns processing/pending documents (last 10)
- Returns recent completed/failed documents (last 5 minutes, max 5)
- Used by frontend for real-time status polling

#### Recent Uploads Refresh
**GET** `/documents/api/recent-uploads/`

Get updated recent uploads HTML fragment.

**Response:**
```html
<div class="upload-item">
    <span class="filename">report.pdf</span>
    <span class="status completed">Completed</span>
    <span class="patient">John Doe</span>
</div>
<!-- ... more upload items ... -->
```

**Notes:**
- Returns HTML template fragment, not JSON
- Used by frontend to refresh recent uploads sidebar
- Shows last 5 uploads for current user

#### Document Preview
**GET** `/documents/api/<id>/preview/`

Get document preview data for UI display.

**Response:**
```json
{
    "success": true,
    "document": {
        "id": 123,
        "filename": "patient_report.pdf",
        "status": "completed",
        "status_display": "Completed",
        "file_size": 2048576,
        "file_size_display": "2.0 MB",
        "uploaded_at": "2025-01-27T10:30:00Z",
        "patient": {
            "name": "John Doe",
            "mrn": "MRN12345"
        },
        "providers": ["Dr. Jane Smith", "Dr. Bob Wilson"],
        "notes": "Lab results from annual checkup",
        "original_text_preview": "First 500 characters of extracted text...",
        "error_message": null,
        "processing_attempts": 1,
        "can_retry": false
    }
}
```

### Document Processing Status Values

- `pending` - Document uploaded, waiting for processing
- `processing` - AI extraction currently in progress
- `completed` - Processing completed successfully
- `failed` - Processing failed (can be retried)
- `review` - Needs manual review

### Error Handling

**Web Views:**
- Use Django messages framework for user feedback
- Redirect to appropriate pages with error/success messages
- Form validation errors displayed inline

**API Endpoints:**
```json
{
    "success": false,
    "error": "Unable to fetch processing status"
}
```

**HTTP Status Codes:**
- `200 OK` - Successful request
- `302 Found` - Redirect after form submission
- `404 Not Found` - Document not found
- `500 Internal Server Error` - Processing error

### Document Model Fields

**Core Fields:**
- `id` - Primary key
- `filename` - Original uploaded filename
- `file` - FileField with PDF file
- `file_size` - Size in bytes
- `patient` - Foreign key to Patient model
- `providers` - Many-to-many to Provider model
- `status` - Processing status (see values above)
- `notes` - Optional user notes

**Processing Fields:**
- `uploaded_at` - Upload timestamp
- `processing_started_at` - When processing began
- `processed_at` - When processing finished
- `original_text` - Extracted PDF text
- `error_message` - Error details if processing failed
- `processing_attempts` - Number of processing attempts

**Audit Fields (from BaseModel):**
- `created_at` - Record creation timestamp
- `updated_at` - Last modification timestamp
- `created_by` - User who uploaded the document

### HIPAA Compliance Features

- **Audit Logging** - All document operations logged
- **User Isolation** - Users can only access their own documents
- **PHI Protection** - No patient information in error logs
- **Secure File Storage** - Files stored with UUID-based paths
- **Access Control** - Login required for all endpoints

---

## FHIR Merge Integration API - Task 14 (In Progress) ⭐

**Enterprise-grade FHIR resource merging endpoints with conflict detection and resolution capabilities.**

### Merge Document Data (Programmatic)
**POST** `/api/fhir/merge/{patient_id}/`

Merge extracted document data into patient's cumulative FHIR bundle with intelligent conflict resolution.

**Request:**
```http
POST /api/fhir/merge/12345/
Content-Type: application/json
Authorization: Bearer <token>

{
  "document_id": "doc_67890",
  "extracted_data": {
    "patient_info": {
      "name": "John Doe",
      "dob": "1980-01-15"
    },
    "lab_results": [
      {
        "test_name": "Glucose",
        "value": "95",
        "unit": "mg/dL",
        "reference_range": "70-100",
        "date": "2024-08-05"
      }
    ],
    "conditions": [
      {
        "name": "Type 2 Diabetes",
        "status": "active",
        "onset_date": "2022-03-10"
      }
    ]
  },
  "source_metadata": {
    "document_type": "lab_report",
    "provider": "Dr. Smith",
    "facility": "City Medical Center",
    "confidence_scores": {
      "overall": 0.92,
      "lab_results": 0.95,
      "conditions": 0.88
    }
  }
}
```

**Response - Success:**
```json
{
  "status": "success",
  "merge_id": "merge_abc123",
  "summary": {
    "resources_added": 3,
    "resources_updated": 1,
    "conflicts_detected": 2,
    "conflicts_resolved": 2,
    "validation_warnings": 1
  },
  "conflicts": [
    {
      "id": "conflict_001",
      "resource_type": "Observation",
      "field": "value.quantity.value",
      "existing_value": "98 mg/dL",
      "new_value": "95 mg/dL",
      "severity": "medium",
      "resolution_applied": "newest_wins",
      "resolution_reason": "New measurement more recent"
    }
  ],
  "validation_issues": [
    {
      "type": "warning",
      "field": "patient_info.name",
      "message": "Name format normalized from 'JOHN DOE' to 'John Doe'"
    }
  ],
  "fhir_bundle_updated": true,
  "provenance_id": "prov_def456"
}
```

**Response - Conflicts Requiring Review:**
```json
{
  "status": "conflicts_detected",
  "merge_id": "merge_xyz789",
  "critical_conflicts": [
    {
      "id": "conflict_002",
      "resource_type": "MedicationStatement",
      "field": "dosage.doseAndRate.doseQuantity.value",
      "existing_value": "500",
      "new_value": "1000",
      "severity": "critical",
      "requires_manual_review": true,
      "escalation_priority": "high",
      "safety_concern": "Significant dosage discrepancy detected"
    }
  ],
  "review_required": true,
  "review_url": "/fhir/conflicts/merge_xyz789/review/"
}
```

### Get Merge Status
**GET** `/api/fhir/merge/{merge_id}/status/`

Check the status of a merge operation.

**Response:**
```json
{
  "merge_id": "merge_abc123",
  "status": "completed",
  "created_at": "2024-08-05T10:30:00Z",
  "completed_at": "2024-08-05T10:30:15Z",
  "patient_id": "12345",
  "document_id": "doc_67890",
  "summary": {
    "resources_processed": 5,
    "conflicts_resolved": 2,
    "manual_reviews_pending": 0
  }
}
```

### Resolve Conflicts (Manual Review)
**POST** `/api/fhir/merge/{merge_id}/resolve/`

Manually resolve conflicts flagged for review.

**Request:**
```http
POST /api/fhir/merge/merge_xyz789/resolve/
Content-Type: application/json

{
  "conflict_resolutions": [
    {
      "conflict_id": "conflict_002",
      "resolution": "preserve_both",
      "reviewer_notes": "Both dosages valid for different time periods",
      "manual_review_by": "dr_jones"
    }
  ]
}
```

### Get Patient FHIR Bundle
**GET** `/api/fhir/patients/{patient_id}/bundle/`

Retrieve patient's complete cumulative FHIR bundle with optional filtering.

**Query Parameters:**
- `resource_types` - Comma-separated list (e.g., `Observation,Condition`)
- `date_from` - Filter resources from date (ISO format)
- `date_to` - Filter resources to date (ISO format)
- `include_provenance` - Include provenance information (default: false)

**Response:**
```json
{
  "resourceType": "Bundle",
  "id": "patient-12345-bundle",
  "meta": {
    "lastUpdated": "2024-08-05T10:30:15Z",
    "versionId": "v47"
  },
  "type": "collection",
  "total": 156,
  "entry": [
    {
      "fullUrl": "Patient/12345",
      "resource": {
        "resourceType": "Patient",
        "id": "12345",
        "name": [{"family": "Doe", "given": ["John"]}],
        "birthDate": "1980-01-15"
      }
    },
    {
      "fullUrl": "Observation/obs-glucose-001",
      "resource": {
        "resourceType": "Observation",
        "id": "obs-glucose-001",
        "status": "final",
        "code": {
          "coding": [{"code": "33747-0", "system": "http://loinc.org"}]
        },
        "valueQuantity": {
          "value": 95,
          "unit": "mg/dL"
        },
        "effectiveDateTime": "2024-08-05"
      }
    }
  ]
}
```

### Validation and Quality Checks
**POST** `/api/fhir/validate/`

Validate extracted data before merge operation.

**Request:**
```json
{
  "document_type": "lab_report",
  "extracted_data": {
    "lab_results": [
      {
        "test_name": "Glucose",
        "value": "invalid_value",
        "unit": "mg/dL"
      }
    ]
  }
}
```

**Response:**
```json
{
  "validation_result": "failed",
  "errors": [
    {
      "field": "lab_results[0].value",
      "error": "Invalid numeric value",
      "severity": "error"
    }
  ],
  "warnings": [],
  "normalized_data": {
    "lab_results": [
      {
        "test_name": "Glucose",
        "value": null,
        "unit": "mg/dL",
        "validation_error": "Could not parse numeric value"
      }
    ]
  }
}
```

### API Features

**Security & Compliance:**
- OAuth 2.0 / JWT authentication required
- HIPAA-compliant audit logging for all operations
- Rate limiting: 100 requests/minute per user
- Request validation and sanitization

**Error Handling:**
- Detailed error responses with field-specific issues
- HTTP status codes aligned with operation results
- Retry-after headers for rate limiting

**Performance:**
- Async processing for large merge operations
- Webhook notifications for completion (optional)
- Caching for frequently accessed bundles
- Optimized queries for large FHIR datasets

---

## Planned API Endpoints (Future Tasks)

### FHIR Integration API (Task 14)
- FHIR resource endpoints for extracted medical data
- Patient FHIR bundle retrieval and updates

### Authentication API
- Token-based authentication for API access
- User registration and profile management

### Patient Management API
- RESTful CRUD operations for patient records
- Advanced search and filtering capabilities

### Provider Management API
- Healthcare provider CRUD operations
- Provider-patient relationship management

### Reporting & Analytics API
- Report generation endpoints
- Usage analytics and metrics

---

*Updated: 2025-08-08 23:54:02 | FHIR Merge Integration API complete - Task 14 delivered with comprehensive FHIR processing, performance monitoring, and enterprise-grade capabilities* 