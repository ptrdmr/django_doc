# Inline Document Upload - PRD

> **Purpose:** Enable document upload directly from the patient detail page without navigating away, using htmx to POST files and insert new document rows into the table.

---

## Parent Context

Part of the **Patient-Centric Hub** initiative. See [patient-centric-hub-prd.md](../patient-centric-hub-prd.md) for overall vision.

---

## Prerequisite

**Requires Patient Summary Side Panel PRD (01) to be implemented.** The layout/structure from the side panel work must be in place before adding the upload zone to the Documents section.

---

## Overview

Upload documents directly from the patient detail page without navigating to `/documents/upload/`. Document upload is the most common action performed on a patient; requiring navigation breaks workflow continuity. This feature adds a file input/drop zone within the Documents section and uses htmx to POST to a patient-scoped endpoint, returning a partial HTML document row that inserts into the table.

---

## User Flow: Upload and Verify Document (Steps 1-4)

1. Navigate to patient detail page
2. Drop/select file in upload zone (no navigation)
3. See document appear in table with "uploading" status
4. Status changes to "processing" automatically (real-time updates come in PRD 03)
5. Optional: Open summary panel to see new data reflected

---

## Technical Scope

### Endpoint

```
POST /patients/<uuid:pk>/upload-document/
Request: multipart/form-data with file
Response: HTML partial (document table row)
Auth: provider_required, has_permission('documents.add_document')
```

- Handles file validation (reuse existing DocumentUploadForm logic)
- Creates Document record linked to patient
- Triggers Celery processing task
- Returns `documents/partials/_document_row.html` partial

### Templates

- `templates/patients/partials/_upload_zone.html` - Inline upload form with file input and drop target
- `templates/documents/partials/_document_row.html` - Single document row (used by upload response and by PRD 03 for polling)

### htmx Attributes

- `hx-post` on upload form targeting patient-scoped endpoint
- `hx-target` for precise DOM insertion (documents table body)
- `hx-swap` to insert new row at top of table

### Implementation Checklist

1. Create patient-scoped upload endpoint (`/patients/<pk>/upload-document/`)
2. Create `_document_row.html` partial for htmx responses
3. Create `_upload_zone.html` partial with file input and drop target
4. Add upload zone to Documents section in patient_detail.html
5. Add htmx attributes to upload form (`hx-post`, `hx-target`, `hx-swap`)
6. Show upload progress indicator (CSS-only or simple percentage)
7. Handle validation errors inline (file type, size limits)
8. Auto-trigger Celery processing on successful upload
9. Insert new document row at top of table with "uploading" status

---

## Technical Notes

- Reuse validation logic from existing `DocumentUploadForm`
- File size limit: existing 50MB limit
- Allowed types: PDF only (existing constraint)
- CSRF token must be included in htmx request

---

## Risks and Mitigations

**Risk: File Upload Edge Cases**
- Large files (approaching 50MB limit)
- Network interruptions mid-upload
- **Mitigation:** Client-side size check before upload, clear error messages, retry option

---

## Existing Code References

**Existing Document Upload:**
- `apps/documents/views.py` → `DocumentUploadView`
- `apps/documents/forms.py` → `DocumentUploadForm`
- Validation logic should be reused, not duplicated

**Patient Detail Page:**
- `templates/patients/patient_detail.html` - Already uses htmx in broader project

---

## TaskMaster Integration

**Workflow:** Each PRD generates one top-level task, then expand it into subtasks.

**Step 1 — Parse (1 task):**
```bash
task-master parse-prd .taskmaster/docs/patient-hub/02-inline-upload-prd.md --tag=patient-hub --num-tasks=1
```

**Step 2 — Expand into subtasks:**
```bash
task-master expand --id=2 --tag=patient-hub --num=6
```

**Expected subtasks:** ~6 (upload endpoint, document row partial, upload zone, htmx wiring, validation, progress)
