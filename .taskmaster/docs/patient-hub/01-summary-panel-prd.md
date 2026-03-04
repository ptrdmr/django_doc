# Patient Summary Side Panel - PRD

> **Purpose:** Add a collapsible right-side panel to the patient detail page that displays the comprehensive patient summary report, eliminating the need to navigate to the Reports module.

---

## Parent Context

Part of the **Patient-Centric Hub** initiative. See [patient-centric-hub-prd.md](../patient-centric-hub-prd.md) for overall vision.

---

## Overview

A collapsible right-side panel displays the comprehensive patient summary report (the same 7-section report currently generated via the Reports module). Users can view demographics, diagnoses, weight trends, medications, and other clinical data without leaving the patient page. This eliminates navigation to `/reports/generate/` for summary viewing.

### Problem Statement

- Users must navigate away from the patient page to generate and view patient summaries
- Context-switching slows clinical workflows
- Care coordinators frequently reference patient history while performing other actions

### Solution

- Toggle button in patient header opens/closes panel
- Panel slides in from right side (~400px wide on desktop)
- Fetches report data via AJAX from existing `get_comprehensive_report()` method
- "Download PDF" button uses new patient-scoped PDF endpoint (see Design Decisions)

---

## Design Decisions

**1. Download PDF**
- **New endpoint:** `GET /patients/<uuid:pk>/summary-pdf/` — generates and returns PDF directly
- **Cleanup:** Deprecate or remove the old Reports flow for patient summaries. The patient page becomes the only place to generate patient summary reports for a given patient.

**2. Getting the data**
- **JSON + Alpine.js (Option A):** Endpoint returns JSON; Alpine component fetches and renders the 7 sections client-side. Keeps flexibility for future enhancements.

**3. Mapping the 7 sections**
- **Inspect both first:** Before implementation, inspect `get_comprehensive_report()` output structure and `templates/reports/preview/patient_summary.html` to map the 7 sections correctly. Document any gaps or adjustments needed.

**4. Z-index hierarchy**
- Main content: 10
- Panel: 40
- Modals (FHIR, diagnosis selector): 50

---

## User Flow: Review and Export Summary

1. Navigate to patient detail page
2. Click "Summary" toggle button
3. Side panel slides open with full patient summary
4. Scroll through 7 sections (demographics, diagnoses, weight, etc.)
5. Click "Download PDF" to get exportable version
6. Close panel to continue other work

---

## Technical Scope

### Endpoints

**1. Summary data (JSON)**
```
GET /patients/<uuid:pk>/summary-data/
Response: JSON with structured patient summary data
Auth: requires_phi_access, has_permission('patients.view_patient')
```
- Calls `patient.get_comprehensive_report()`
- Returns JSON for Alpine.js rendering
- Used by side panel for dynamic loading

**2. Summary PDF (new)**
```
GET /patients/<uuid:pk>/summary-pdf/
Response: application/pdf file download
Auth: requires_phi_access, has_permission('patients.view_patient')
```
- Generates patient summary report using existing report generation logic
- Returns PDF as file download (no navigation)
- Replaces old Reports flow for patient summaries; old flow to be deprecated/removed

### Templates

- `templates/patients/partials/_summary_panel.html` - Side panel content with all 7 report sections

### Alpine.js Component

```javascript
patientSummaryPanel() {
  return {
    isOpen: false,
    isLoading: false,
    summaryData: null,
    error: null,
    toggle() { ... },
    fetchSummary() { ... },
    downloadPdf() { ... }
  }
}
```

### Implementation Checklist

1. **Inspect first:** Map `get_comprehensive_report()` output to the 7 sections in `templates/reports/preview/patient_summary.html`; document structure and any gaps
2. Create summary data JSON endpoint (`/patients/<pk>/summary-data/`)
3. Create summary PDF endpoint (`/patients/<pk>/summary-pdf/`) — generates and returns PDF directly
4. Create `_summary_panel.html` partial template with all 7 report sections (Alpine.js renders from JSON)
5. Add Alpine.js `patientSummaryPanel()` component to patient_detail.html
6. Add toggle button to patient header
7. Implement slide-in/slide-out CSS animation (z-index: panel 40, modals 50)
8. Wire up "Download PDF" button to new endpoint (e.g. `window.location` or fetch + blob)
9. Handle loading and error states
10. Add localStorage persistence for panel open/closed state
11. Mobile responsive: full-screen overlay on small screens
12. **Cleanup:** Deprecate or remove old Reports flow for patient summaries (patient page is sole entry point)

---

## UI/UX Considerations

- Panel width: 400px desktop, 100% mobile (full-screen overlay)
- Side panel should not obscure critical patient header info
- Z-index hierarchy: panel 40, modals 50 (below FHIR modal, above main content)
- Summary panel content scrollable independently
- Loading states must be clear and non-blocking
- Error states must be actionable (retry buttons, clear messages)

---

## Risks and Mitigations

**Risk 1: Side Panel CSS Conflicts with Existing Modals**
- FHIR modal and primary diagnosis selector already exist
- **Mitigation:** Establish clear z-index hierarchy (panel: 40, modals: 50)

**Risk 2: Large FHIR Bundles Cause Slow Panel Load**
- Some patients have 500+ FHIR resources; get_comprehensive_report() could take 2+ seconds
- **Mitigation:** Add loading skeleton, consider caching, paginate large sections

---

## Existing Code References

**Patient Summary Data Method:**
- `apps/patients/models.py` → `Patient.get_comprehensive_report()`
- Returns structured dict with patient_info, clinical_summary, report_metadata

**Existing Report Templates:**
- `templates/reports/preview/patient_summary.html` - Full preview template (reuse CSS classes)
- `templates/reports/pdf/patient_summary.html` - PDF generation template

**Patient Detail Page:**
- `templates/patients/patient_detail.html` - Already uses Alpine.js for diagnosis selector

---

## TaskMaster Integration

**Workflow:** Each PRD generates one top-level task, then expand it into subtasks.

**Step 1 — Parse (1 task):**
```bash
task-master add-tag patient-hub --description="Patient-Centric Hub feature"
task-master parse-prd .taskmaster/docs/patient-hub/01-summary-panel-prd.md --tag=patient-hub --num-tasks=1
```

**Step 2 — Expand into subtasks:**
```bash
task-master expand --id=1 --tag=patient-hub --num=8
```

**Expected subtasks:** ~7–8 (endpoints, templates, Alpine component, PDF download, cleanup of old Reports flow)
