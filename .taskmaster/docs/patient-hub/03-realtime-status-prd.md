# Real-Time Document Status Updates - PRD

> **Purpose:** Documents table updates automatically as processing progresses, without page refresh. Users see status changes (uploading → processing → completed) in place via htmx polling.

---

## Parent Context

Part of the **Patient-Centric Hub** initiative. See [patient-centric-hub-prd.md](../patient-centric-hub-prd.md) for overall vision.

---

## Prerequisite

**Requires Inline Document Upload PRD (02) to be implemented.** This feature needs the `_document_row.html` partial template created in PRD 02. Document rows must exist in the table before polling can update them.

---

## Overview

Document processing takes 30 seconds to 2+ minutes. Users currently must refresh the page to see status changes. This feature adds htmx polling to document rows with non-terminal status; each poll fetches fresh row HTML and replaces it in place. Status badges update automatically (pending → processing → completed). Polling stops when a document completes or fails.

---

## User Flow: Status Updates Without Refresh

1. User has uploaded document(s) via inline upload (PRD 02)
2. Document rows show "uploading" or "processing" status
3. Every 5 seconds, htmx polls for updated row HTML
4. Status badges update in place (no page refresh)
5. Polling stops automatically when status is completed, failed, or cancelled
6. Visual indicators (spinner, progress) show processing state

---

## Technical Scope

### Endpoint

```
GET /documents/<uuid:pk>/status-partial/
Response: HTML partial (single document table row)
Auth: requires_phi_access
```

- Returns current document status as table row HTML
- Used by htmx polling for live updates

### htmx Polling

- `hx-trigger="every 5s"` on document rows with status != completed/failed/cancelled
- `hx-get` to poll status partial endpoint
- `hx-swap="outerHTML"` to replace entire row with fresh HTML
- Conditional polling: rows with terminal status do not have polling attributes

### Implementation Checklist

1. Create document status partial endpoint (`/documents/<pk>/status-partial/`)
2. Add `hx-trigger="every 5s"` to document rows with status != completed/failed
3. Add `hx-get` to poll for updated row HTML
4. Implement conditional polling logic (stop when complete)
5. Add visual processing indicator (spinner, progress bar)
6. Handle error states with retry option
7. Optional: Add subtle animation when status changes

---

## Technical Notes

- Polling interval: 5 seconds (balance between responsiveness and server load)
- Stop polling when status is: completed, failed, cancelled
- Reuse `_document_row.html` partial from PRD 02 for consistent row structure

---

## Risks and Mitigations

**Risk: htmx Polling Creates Server Load**
- Many concurrent users with processing documents = many requests
- **Mitigation:** Rate limiting (addressed in PRD 04), stop polling on completion, consider SSE for high-scale future

---

## TaskMaster Integration

**Workflow:** Each PRD generates one top-level task, then expand it into subtasks.

**Step 1 — Parse (1 task):**
```bash
task-master parse-prd .taskmaster/docs/patient-hub/03-realtime-status-prd.md --tag=patient-hub --num-tasks=1
```

**Step 2 — Expand into subtasks:**
```bash
task-master expand --id=3 --tag=patient-hub --num=5
```

**Expected subtasks:** ~5 (status endpoint, htmx polling, conditional logic, visual indicators, error handling)
