# Patient Hub Polish and Integration - PRD

> **Purpose:** Smooth out rough edges and ensure a cohesive experience across the Patient-Centric Hub features. Covers keyboard shortcuts, cross-feature integration, audit logging, rate limiting, performance testing, and accessibility.

---

## Parent Context

Part of the **Patient-Centric Hub** initiative. See [patient-centric-hub-prd.md](../patient-centric-hub-prd.md) for overall vision.

---

## Prerequisite

**Requires PRDs 01, 02, and 03 to be complete.** All core features (summary panel, inline upload, real-time status) must be implemented before this polish work.

---

## Overview

Cross-feature polish that ties the Patient Hub together: keyboard shortcuts for power users, panel auto-refresh when documents complete, success notifications, audit logging for HIPAA compliance, rate limiting on polling endpoints, performance validation, and accessibility improvements.

---

## Scope

### Keyboard Shortcuts

- Panel toggle: `Cmd/Ctrl + S` (or similar)
- Panel close: Escape key

### Cross-Feature Integration

- Panel auto-refresh when document completes (so summary reflects new data without manual refresh)
- Success toast/notification when document completes

### Audit and Security

- Ensure audit logging covers all new endpoints:
  - `GET /patients/<pk>/summary-data/`
  - `POST /patients/<pk>/upload-document/`
  - `GET /documents/<pk>/status-partial/`

### Rate Limiting

- Polling endpoints: 60 requests/minute per user
- Prevents abuse when many users have processing documents

### Performance Testing

- Test with patients having 100+ FHIR resources
- Panel open time target: < 500ms for < 100 resources, < 2s for 500+ resources

### Accessibility

- Panel toggle: keyboard accessible (Enter/Space)
- Panel close: Escape key
- Focus trap when panel open
- ARIA labels for dynamic content
- Screen reader announcements for status changes
- Panel should work with screen readers

### Additional

- Cross-browser testing (Chrome 90+, Firefox 88+, Safari 14+, Edge 90+)

---

## Implementation Checklist

1. Add keyboard shortcut for panel toggle
2. Implement panel auto-refresh after document completes
3. Add success toast/notification when document completes
4. Ensure audit logging covers all new endpoints
5. Add rate limiting to polling endpoints (60 req/min per user)
6. Performance testing with large FHIR bundles
7. Accessibility review (ARIA labels, focus management)
8. Cross-browser testing

---

## Technical Notes

- Rate limit: 60 requests/minute per user for polling endpoints
- Test with patients having 100+ FHIR resources
- Panel should work with screen readers

---

## TaskMaster Integration

**Workflow:** Each PRD generates one top-level task, then expand it into subtasks.

**Step 1 — Parse (1 task):**
```bash
task-master parse-prd .taskmaster/docs/patient-hub/04-polish-integration-prd.md --tag=patient-hub --num-tasks=1
```

**Step 2 — Expand into subtasks:**
```bash
task-master expand --id=4 --tag=patient-hub --num=5
```

**Expected subtasks:** ~5 (keyboard shortcuts, panel auto-refresh, audit logging, rate limiting, accessibility)
