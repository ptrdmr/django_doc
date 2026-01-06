# Patient-Centric Hub PRD

> **Purpose:** Transform the patient detail page into a unified command center for all patient-related operations.

---

## Overview

The Patient-Centric Hub transforms the existing patient detail page from a passive "view" into an active command center for all patient-related operations. Currently, users must navigate away from the patient page to upload documents, generate reports, or view comprehensive summaries. This creates friction and context-switching that slows clinical workflows.

### Problem Statement

Users working with a specific patient must currently:
- Navigate to `/documents/upload/` to upload a document, then navigate back
- Navigate to `/reports/generate/` to create a patient summary, then navigate back  
- Wait for page refreshes to see document processing status
- Open reports in separate pages/tabs to review content

### Solution

Consolidate all patient-centric actions into the patient detail page itself:
- Upload documents inline with real-time processing status
- View patient summary in a slide-out side panel that auto-updates
- Download PDF reports without leaving the page
- See documents appear and update status in real-time

### Value Proposition

- Reduces navigation clicks by ~60% for common patient workflows
- Keeps users focused on the patient context
- Provides real-time feedback on async operations (document processing)
- Aligns with how clinical users actually work: patient-first, then actions

---

## Core Features

### Feature 1: Patient Summary Side Panel

**What it does:** A collapsible right-side panel that displays the comprehensive patient summary report (the same 7-section report currently generated via the Reports module).

**Why it's important:** Users frequently need to review patient history while performing other actions. Currently this requires generating a separate report or navigating away.

**How it works:**
- Toggle button in patient header opens/closes panel
- Panel slides in from right side (~400px wide on desktop)
- Fetches report data via AJAX from existing `get_comprehensive_report()` method
- Renders inline using a streamlined version of the report template
- "Download PDF" button triggers existing report generation workflow
- Auto-refreshes when patient data changes (e.g., after document merge)

### Feature 2: Inline Document Upload

**What it does:** Upload documents directly from the patient detail page without navigating away.

**Why it's important:** Document upload is the most common action performed on a patient. Requiring navigation breaks workflow continuity.

**How it works:**
- File input/drop zone within the Documents section card
- Uses htmx to POST file to new patient-scoped upload endpoint
- Returns partial HTML that inserts into documents table
- Shows upload progress indicator
- Automatic Celery task triggering (existing infrastructure)

### Feature 3: Real-Time Document Status Updates

**What it does:** Documents table updates automatically as processing progresses, without page refresh.

**Why it's important:** Document processing takes 30 seconds to 2+ minutes. Users currently must refresh to see status changes.

**How it works:**
- htmx polling (`hx-trigger="every 5s"`) on documents with status != completed
- Poll endpoint returns fresh document row HTML
- Status badges update in place (pending → processing → completed)
- Polling stops automatically when document completes or fails
- Visual indicators for processing progress

---

## User Experience

### User Personas

**Primary: Clinical Data Specialist**
- Uploads 20-50 documents per day across multiple patients
- Needs to verify processing completed before moving on
- Frequently references patient history while uploading new documents

**Secondary: Care Coordinator**  
- Reviews patient summaries to prepare for care team meetings
- Exports PDF reports to share with external providers
- Less focused on document upload, more on report consumption

### Key User Flows

#### Flow 1: Upload and Verify Document
1. Navigate to patient detail page
2. Drop/select file in upload zone (no navigation)
3. See document appear in table with "uploading" status
4. Status changes to "processing" automatically
5. Status changes to "completed" with extracted resource counts
6. Optional: Open summary panel to see new data reflected

#### Flow 2: Review and Export Summary
1. Navigate to patient detail page
2. Click "Summary" toggle button
3. Side panel slides open with full patient summary
4. Scroll through 7 sections (demographics, diagnoses, weight, etc.)
5. Click "Download PDF" to get exportable version
6. Close panel to continue other work

#### Flow 3: Batch Document Processing
1. Open patient page
2. Upload first document
3. While processing, upload second document
4. Both documents show in table with live status
5. Continue working; documents complete in background
6. Summary panel reflects all new data when opened

### UI/UX Considerations

- Side panel should not obscure critical patient header info
- Mobile: Panel becomes full-screen overlay
- Keyboard shortcut for panel toggle (e.g., `Cmd/Ctrl + S`)
- Panel state persists within session (localStorage)
- Loading states must be clear and non-blocking
- Error states must be actionable (retry buttons, clear messages)

---

## Technical Architecture

### System Components

#### New Endpoints Required

**1. Patient Summary Data Endpoint**
```
GET /patients/<uuid:pk>/summary-data/
Response: JSON with structured patient summary data
Auth: requires_phi_access, has_permission('patients.view_patient')
```
- Calls `patient.get_comprehensive_report()` 
- Returns JSON for JavaScript rendering
- Used by side panel for dynamic loading

**2. Inline Document Upload Endpoint**
```
POST /patients/<uuid:pk>/upload-document/
Request: multipart/form-data with file
Response: HTML partial (document table row)
Auth: provider_required, has_permission('documents.add_document')
```
- Handles file validation (reuse existing DocumentUploadForm logic)
- Creates Document record linked to patient
- Triggers Celery processing task
- Returns `documents/_document_row.html` partial

**3. Document Status Partial Endpoint**
```
GET /documents/<uuid:pk>/status-partial/
Response: HTML partial (single document table row)
Auth: requires_phi_access
```
- Returns current document status as table row HTML
- Used by htmx polling for live updates

**4. Documents Table Partial Endpoint**
```
GET /patients/<uuid:pk>/documents-partial/
Response: HTML partial (full documents table body)
Auth: requires_phi_access
```
- Returns all documents for patient as table rows
- Used for full refresh after upload

### Template Components

**New Templates Required:**
1. `templates/patients/partials/_summary_panel.html` - Side panel content
2. `templates/patients/partials/_upload_zone.html` - Inline upload form
3. `templates/documents/partials/_document_row.html` - Single document row
4. `templates/patients/partials/_documents_table.html` - Full documents table

**Modified Templates:**
1. `templates/patients/patient_detail.html` - Add panel, upload zone, htmx attributes

### JavaScript/Alpine.js Components

**New Alpine Component: `patientSummaryPanel()`**
```javascript
{
  isOpen: false,
  isLoading: false,
  summaryData: null,
  error: null,
  
  toggle() { ... },
  fetchSummary() { ... },
  downloadPdf() { ... }
}
```

**htmx Enhancements:**
- `hx-post` on upload form
- `hx-trigger="every 5s"` on processing documents
- `hx-swap="outerHTML"` for row updates
- `hx-target` for precise DOM updates

### Data Models

No new models required. Feature leverages existing:
- `Patient` model with `get_comprehensive_report()` method
- `Document` model with status field
- `GeneratedReport` model for PDF persistence

### Infrastructure Requirements

No new infrastructure. Uses existing:
- Redis for Celery task queue (document processing)
- PostgreSQL for data storage
- Existing htmx and Alpine.js frontend stack

---

## Development Roadmap

### Phase 1: Patient Summary Side Panel (Foundation)

**Goal:** Add collapsible side panel with patient summary report

**Scope:**
1. Create summary data JSON endpoint (`/patients/<pk>/summary-data/`)
2. Create `_summary_panel.html` partial template with all 7 report sections
3. Add Alpine.js `patientSummaryPanel()` component
4. Add toggle button to patient header
5. Implement slide-in/slide-out CSS animation
6. Add "Download PDF" button that triggers existing report flow
7. Handle loading and error states
8. Add localStorage persistence for panel open/closed state
9. Mobile responsive: full-screen overlay on small screens

**Technical Notes:**
- Reuse CSS classes from `templates/reports/preview/patient_summary.html`
- Summary panel content should be scrollable independently
- Panel width: 400px desktop, 100% mobile
- Z-index must be below FHIR modal but above main content

### Phase 2: Inline Document Upload

**Goal:** Upload documents directly from patient page

**Scope:**
1. Create patient-scoped upload endpoint (`/patients/<pk>/upload-document/`)
2. Create `_upload_zone.html` partial with file input and drop target
3. Create `_document_row.html` partial for htmx responses
4. Add htmx attributes to upload form (`hx-post`, `hx-target`, `hx-swap`)
5. Show upload progress indicator (CSS-only or simple percentage)
6. Handle validation errors inline (file type, size limits)
7. Auto-trigger Celery processing on successful upload
8. Insert new document row at top of table with "uploading" status

**Technical Notes:**
- Reuse validation logic from existing `DocumentUploadForm`
- File size limit: existing 50MB limit
- Allowed types: PDF only (existing constraint)
- CSRF token must be included in htmx request

### Phase 3: Real-Time Document Status Updates

**Goal:** Documents update status automatically without page refresh

**Scope:**
1. Create document status partial endpoint (`/documents/<pk>/status-partial/`)
2. Add `hx-trigger="every 5s"` to document rows with status != completed/failed
3. Add `hx-get` to poll for updated row HTML
4. Implement conditional polling (stop when complete)
5. Add visual processing indicator (spinner, progress bar)
6. Handle error states with retry option
7. Optional: Add subtle animation when status changes

**Technical Notes:**
- Polling interval: 5 seconds (balance between responsiveness and server load)
- Stop polling when status is: completed, failed, cancelled
- Use `hx-swap="outerHTML"` to replace entire row

### Phase 4: Polish and Integration

**Goal:** Smooth out rough edges, ensure cohesive experience

**Scope:**
1. Add keyboard shortcut for panel toggle
2. Implement panel auto-refresh after document completes
3. Add success toast/notification when document completes
4. Ensure audit logging covers all new endpoints
5. Add rate limiting to polling endpoints
6. Performance testing with large FHIR bundles
7. Accessibility review (ARIA labels, focus management)
8. Cross-browser testing

**Technical Notes:**
- Rate limit: 60 requests/minute per user for polling endpoints
- Test with patients having 100+ FHIR resources
- Panel should work with screen readers

---

## Logical Dependency Chain

```
Phase 1: Summary Side Panel
├── 1.1 Create JSON endpoint for summary data
├── 1.2 Create panel partial template
├── 1.3 Add Alpine.js component to patient_detail.html
├── 1.4 Add toggle button and CSS animations
├── 1.5 Wire up PDF download button
├── 1.6 Add mobile responsive styles
└── 1.7 Add localStorage state persistence

Phase 2: Inline Document Upload (depends on Phase 1 layout)
├── 2.1 Create upload endpoint (patient-scoped)
├── 2.2 Create document row partial template
├── 2.3 Add upload zone to Documents section
├── 2.4 Wire up htmx POST and response handling
├── 2.5 Add upload progress indicator
└── 2.6 Handle validation errors inline

Phase 3: Real-Time Status (depends on Phase 2 row partial)
├── 3.1 Create status partial endpoint
├── 3.2 Add htmx polling attributes to rows
├── 3.3 Implement conditional polling logic
├── 3.4 Add processing status indicators
└── 3.5 Handle completion/failure states

Phase 4: Polish (depends on all above)
├── 4.1 Keyboard shortcuts
├── 4.2 Cross-feature integration (panel refresh on doc complete)
├── 4.3 Audit logging for new endpoints
├── 4.4 Rate limiting
├── 4.5 Performance testing
└── 4.6 Accessibility review
```

### MVP Path (Fastest to Usable)

Phase 1 alone delivers significant value and is fully usable. Users can view summaries without navigation. This should be completed first and validated before proceeding.

### Atomic Feature Boundaries

- Phase 1 is standalone (no dependencies on other phases)
- Phase 2 requires Phase 1 layout to be in place (panel affects page structure)
- Phase 3 requires Phase 2 row partial to exist
- Phase 4 is optional polish that can be done incrementally

---

## Risks and Mitigations

### Technical Challenges

**Risk 1: Side Panel CSS Conflicts with Existing Modals**
- The FHIR modal and primary diagnosis selector already exist
- Panel z-index could conflict
- **Mitigation:** Establish clear z-index hierarchy (panel: 40, modals: 50)

**Risk 2: Large FHIR Bundles Cause Slow Panel Load**
- Some patients have 500+ FHIR resources
- get_comprehensive_report() could take 2+ seconds
- **Mitigation:** Add loading skeleton, consider caching, paginate large sections

**Risk 3: htmx Polling Creates Server Load**
- Many concurrent users with processing documents = many requests
- **Mitigation:** Rate limiting, stop polling on completion, consider SSE for high-scale

**Risk 4: File Upload Edge Cases**
- Large files (approaching 50MB limit)
- Network interruptions mid-upload
- **Mitigation:** Client-side size check before upload, clear error messages, retry option

### MVP Definition

**Minimum Viable Product = Phase 1 Complete:**
- Summary panel opens/closes
- Shows all 7 report sections
- PDF download works
- Mobile responsive

This alone eliminates the need to navigate to Reports module for summary viewing, which is a significant workflow improvement.

**Enhanced MVP = Phase 1 + Phase 2:**
- Adds inline document upload
- Still requires manual refresh for status updates
- Covers the two most common patient page actions

### Resource Constraints

**Implementation Effort:**
- Phase 1: 4-6 hours
- Phase 2: 3-4 hours  
- Phase 3: 2-3 hours
- Phase 4: 2-3 hours
- Total: 11-16 hours

**Testing Effort:**
- Unit tests for new endpoints: 2-3 hours
- Integration testing: 2-3 hours
- Manual QA: 2 hours

---

## Appendix

### Existing Code References

**Patient Summary Data Method:**
- `apps/patients/models.py` → `Patient.get_comprehensive_report()`
- Returns structured dict with patient_info, clinical_summary, report_metadata

**Existing Report Templates:**
- `templates/reports/preview/patient_summary.html` - Full preview template
- `templates/reports/pdf/patient_summary.html` - PDF generation template
- CSS styles can be reused from preview template

**Existing Document Upload:**
- `apps/documents/views.py` → `DocumentUploadView`
- `apps/documents/forms.py` → `DocumentUploadForm`
- Validation logic should be reused, not duplicated

**Patient Detail Page:**
- `templates/patients/patient_detail.html` - 800+ lines, complex
- Already uses Alpine.js for diagnosis selector
- Already uses htmx in broader project

### Technical Specifications

**Browser Support:**
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

**Performance Targets:**
- Panel open time: < 500ms for patients with < 100 resources
- Panel open time: < 2s for patients with 500+ resources
- Upload response time: < 1s for files under 10MB
- Polling overhead: < 1% CPU on client

**Accessibility Requirements:**
- Panel toggle: keyboard accessible (Enter/Space)
- Panel close: Escape key
- Focus trap when panel open
- ARIA labels for dynamic content
- Screen reader announcements for status changes

### TaskMaster Integration

This PRD is designed to be parsed by TaskMaster for task generation.

**Recommended task count:** 12-15 top-level tasks

**Suggested task breakdown:**
1. Create patient summary JSON endpoint
2. Create summary panel partial template  
3. Add Alpine.js panel component to patient detail
4. Implement panel toggle and animations
5. Add PDF download functionality to panel
6. Create inline document upload endpoint
7. Create document row partial template
8. Add upload zone to patient detail page
9. Wire up htmx upload handling
10. Create document status partial endpoint
11. Add htmx polling for document status
12. Implement conditional polling logic
13. Add keyboard shortcuts and accessibility
14. Performance testing and optimization
15. Final integration testing and polish

**To parse this PRD:**
```bash
# Parse into a dedicated tag (recommended)
task-master add-tag patient-hub --description="Patient-Centric Hub feature"
task-master parse-prd .taskmaster/docs/patient-centric-hub-prd.md --tag=patient-hub --num-tasks=15

# Or parse directly into master
task-master parse-prd .taskmaster/docs/patient-centric-hub-prd.md --num-tasks=15
```

