# Optimistic Concurrency Merge System - Product Requirements Document

**Version:** 1.0  
**Date:** December 1, 2025  
**Status:** Approved for Implementation  
**Project:** Medical Document Parser (doc2db_2025_django)  
**Priority:** High  
**Estimated Effort:** 3-4 weeks  
**Task Structure:** Single main task with 9 subtasks

---

## Executive Summary

**THIS IS A SINGLE FEATURE IMPLEMENTATION** - Transform the document processing pipeline from a pessimistic locking model ("hold data until manually approved") to an optimistic concurrency model ("merge immediately, flag exceptions for review"). This architectural shift removes the human bottleneck that prevents clinical staff from accessing parsed medical data in real-time, while maintaining data quality through intelligent automated flagging and surgical rollback capabilities.

This PRD describes ONE cohesive feature that should be implemented as a single task with granular subtasks, not as multiple independent tasks.

**Core Principle:** Trust the AI extraction (which achieves >90% accuracy), merge data immediately to patient records, and flag only the 5-20% of extractions that show quality concerns for human verification.

---

## Problem Statement

### Current State (Pessimistic Locking)

**Workflow:** Upload → Extract → **Hold in ParsedData** → Manual Review → Approve → Merge to Patient FHIR

**Pain Points:**
- Extracted data is trapped in `ParsedData` table until someone manually reviews it
- Clinical staff cannot see new medical information for hours or days
- Every document requires human approval, creating a bottleneck (200 patients × 10 docs = 2,000 manual reviews)
- System assumes AI extraction is wrong by default, despite 90%+ accuracy
- Review workflow doesn't scale with document volume

**Stakeholder Feedback:** *"This is a stopgap that keeps us from being useful. We need data available immediately, not after someone clicks 'approve'."*

### Desired State (Optimistic Concurrency)

**Workflow:** Upload → Extract → **Immediately Merge to Patient FHIR** → Quality Check → Flag if Needed → Review Flagged Items Only

**Benefits:**
- Medical data available within 5 minutes of upload (vs 5 days)
- Only 5-20% of documents require human review (vs 100%)
- System scales infinitely (10 docs or 10,000 docs, same workflow)
- Trust AI by default, verify exceptions
- Complete audit trail for compliance

---

## Success Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| **Time to Data Availability** | Hours to days | < 5 minutes | Document upload to FHIR merge timestamp |
| **Manual Review Rate** | 100% | 5-20% | Percentage of documents flagged |
| **Merge Performance** | N/A | < 500ms | Time for `update_fhir_resources()` call |
| **Merge Failures** | N/A | < 1% | Failed merge operations / total merges |
| **False Positive Flags** | N/A | < 10% | Flagged items marked "correct" without changes |
| **Rollback Frequency** | N/A | < 2% | Documents requiring merge rollback |

---

## Core Requirements

### R1: Data Model Changes (ParsedData)

**Add Fields:**
- `auto_approved` (BooleanField) - Whether system auto-approved without flagging
- `flag_reason` (TextField) - Human-readable explanation of why flagged

**Update Choices:**
```python
REVIEW_STATUS_CHOICES = [
    ('pending', 'Pending Classification'),      # Initial state before analysis
    ('auto_approved', 'Auto-Approved'),         # High confidence, immediate merge
    ('flagged', 'Flagged for Review'),          # Low confidence or conflicts
    ('reviewed', 'Manually Reviewed'),          # Human verified
    ('rejected', 'Rejected'),                   # Human rejected
]
```

**Add Methods:**
- `determine_review_status()` - Runs quality checks, sets flags, returns bool
- `check_quick_conflicts()` - Fast (<100ms) DOB/name validation against patient record

**Database Indexes:**
- Add index on `auto_approved` for dashboard queries
- Add index on `(review_status, created_at)` for flagged items list

---

### R2: Patient Model Enhancements (FHIR Operations)

**Add Method: `update_fhir_resources(fhir_resources, document_id)`**

**Purpose:** Idempotent merge operation that prevents duplicates on retry

**Behavior:**
- Match existing resources by `(meta.source, resourceType)` composite key
- Update existing resources if found, append new ones if not
- Stamp all resources with `meta.source = "document_{document_id}"`
- Create audit trail via `PatientHistory`
- Return True on success, raise exception on failure

**Critical Requirement:** Must be safe to call multiple times (Celery retry safety)

**Add Method: `rollback_document_merge(document_id)`**

**Purpose:** Surgically remove all resources from a specific document

**Behavior:**
- Filter `encrypted_fhir_bundle['entry']` where `meta.source = "document_{document_id}"`
- Remove matched entries from bundle
- Update bundle metadata (lastUpdated, versionId)
- Create audit trail via `PatientHistory`
- Return count of removed resources

**Use Case:** User reviews flagged item and determines extraction is completely wrong

---

### R3: Quality Check Logic (Automated Flagging)

**Implement: `ParsedData.determine_review_status()`**

**Flag Conditions (ANY triggers flag):**
1. Extraction confidence < 0.80 (80%)
2. Fallback AI model was used
3. Zero resources extracted (no medical data found)
4. Fewer than 3 resources extracted AND confidence < 0.95
5. DOB conflict with existing patient record
6. Name mismatch with existing patient record (fuzzy match < 80% similarity)

**Performance Requirement:** Quick conflict checks must execute in < 100ms

**Output:**
- Sets `review_status` to 'auto_approved' or 'flagged'
- Sets `flag_reason` with human-readable explanation
- Sets `auto_approved` boolean
- Sets `reviewed_at` to current timestamp for auto-approved items
- Returns True if auto-approved, False if flagged

---

### R4: Task Flow Modification (Immediate Merge)

**Modify: `process_document_async` in `apps/documents/tasks.py`**

**New Flow (after FHIR extraction):**
```
1. Create/update ParsedData record
2. Call parsed_data.determine_review_status()
3. Merge immediately using patient.update_fhir_resources()
   - Use UPDATE semantics (not ADD) for idempotency
   - Merge regardless of flag status
4. Set parsed_data.is_merged = True on success
5. Log appropriately based on review_status
6. Mark document.status = 'completed'
```

**Key Principle:** Use `update_fhir_resources()` even for initial merge (prevents duplicates on retry)

**Error Handling:**
- If merge fails, add to `flag_reason` and set status to 'flagged'
- Don't fail the task, but log error for investigation
- Document remains in 'completed' state (processing done, just merge failed)

---

### R5: Data Migration (Existing Records)

**Create Migration:** `apps/documents/migrations/00XX_migrate_review_status.py`

**Mapping Logic:**
- `approved` + no `reviewed_by` → `auto_approved`
- `approved` + has `reviewed_by` → `reviewed`
- `pending` → `pending` (unchanged)
- `rejected` → `rejected` (unchanged)
- `flagged` → `flagged` (unchanged)

**Validation:** Test on copy of production data before deployment

---

### R6: Comprehensive Test Coverage

**Unit Tests:**
- Quality check logic (each flag condition independently)
- Resource matching in `update_fhir_resources()`
- Rollback filtering logic
- Performance tests (< 100ms for quick checks)

**Integration Tests:**
- End-to-end document processing with immediate merge
- Retry safety (task can run twice without duplicates)
- Flagged documents still merge successfully
- Rollback removes only target document's resources

**Test Data:**
- High confidence document (should auto-approve)
- Low confidence document (should flag)
- Document with DOB conflict (should flag)
- Document with zero resources (should flag)

---

### R7: Staging Deployment & Monitoring

**Deploy to Staging:**
- Run migration on staging database
- Process 20-30 diverse test documents
- Monitor for 3-5 days

**Monitor Metrics:**
- Flag rate (target: 5-20%)
- Merge performance (target: < 500ms)
- Merge failures (target: < 1%)
- False positive rate (flagged items marked correct)

**Threshold Tuning:**
- If flag rate > 20%: Lower confidence threshold (e.g., 70%)
- If flag rate < 5%: Raise confidence threshold (e.g., 85%)
- Document final thresholds before production deployment

---

### R8: Flagged Items UI (Phase 3)

**Dashboard Widget:**
- Show count of flagged documents prominently
- Link to flagged items list view
- Color-coded by age (red if > 7 days old)

**Flagged Items List View:**
- Filter: `ParsedData.objects.filter(review_status='flagged')`
- Show: Document name, patient, flag reason, age
- Sort: By created_at (oldest first)
- Actions: View detail, mark correct, correct data, rollback

**Flagged Item Detail/Modal:**
- Display flag reason prominently
- Show extracted data with source snippets
- Actions:
  - "Mark as Correct" - Clear flag, no changes to data
  - "Correct Data" - Edit FHIR resources, update patient record
  - "Remove from Record" - Rollback merge entirely

**URL Structure:**
- `/documents/flagged/` - List view
- `/documents/<id>/verify/` - Detail view for flagged item

---

### R9: Cleanup Old Review Workflow (Phase 4)

**Backend Cleanup:**
- Remove `merge_to_patient_record` Celery task (no longer needed)
- Simplify `DocumentReviewView.handle_approval()` (remove merge logic)
- Deprecate `ParsedData.is_approved` field (use `review_status` instead)

**Frontend Cleanup:**
- Remove old approval workflow templates
- Update messaging to reflect "verification" vs "approval"
- Remove "Approve & Merge" buttons (data already merged)

**Keep:**
- Audit trail functionality (PatientHistory)
- Review interface structure (repurpose for flagged items)
- Permission checks (still need authorization)

**Timeline:** After Phase 3 UI is deployed and validated

---

## Technical Architecture

### State Machine (ParsedData.review_status)

```
[Upload] → [Extract] → [pending]
                           ↓
                    [Quality Check]
                     ↙         ↘
            [auto_approved]  [flagged]
                   ↓              ↓
              [Merged]      [Merged + Needs Review]
                               ↓
                          [reviewed] or [rejected]
```

### Data Flow

```
1. Document uploaded
2. AI extraction completes
3. ParsedData created with status='pending'
4. determine_review_status() runs:
   - Checks confidence, resource count, conflicts
   - Sets status to 'auto_approved' or 'flagged'
5. update_fhir_resources() called immediately:
   - Matches by (source, resourceType)
   - Updates existing or appends new
   - Stamps with meta.source
6. ParsedData.is_merged = True
7. Document.status = 'completed'
8. If flagged: Appears in review queue
9. If auto_approved: No further action needed
```

### Key Methods

**Patient.update_fhir_resources(fhir_resources, document_id):**
- Idempotent merge operation
- Prevents duplicates on Celery retry
- Returns True/False

**Patient.rollback_document_merge(document_id):**
- Surgical deletion by meta.source
- Returns count of removed resources

**ParsedData.determine_review_status():**
- Runs quality checks
- Sets flags and reasons
- Returns True (auto-approved) or False (flagged)

**ParsedData.check_quick_conflicts():**
- Fast (<100ms) validation
- Returns list of conflict descriptions

---

## User Stories

### Story 1: Clinician - Immediate Data Access
**As a** hospice nurse  
**I want** patient medical data available immediately after document upload  
**So that** I can make time-sensitive care decisions without waiting for manual approval

**Acceptance Criteria:**
- Data appears in patient FHIR record within 5 minutes of upload
- No manual approval required for high-confidence extractions
- Audit trail shows when data was merged

### Story 2: Data Steward - Exception-Based Review
**As a** medical records coordinator  
**I want** to review only documents flagged for quality concerns  
**So that** I can focus my time on problematic extractions instead of rubber-stamping good ones

**Acceptance Criteria:**
- Dashboard shows count of flagged documents
- Flagged items list shows reason for each flag
- Can mark flagged items as correct without editing
- Can correct data if needed
- Can rollback merge if extraction is completely wrong

### Story 3: System Admin - Operational Visibility
**As a** system administrator  
**I want** to monitor auto-approval rates and flag reasons  
**So that** I can tune thresholds and ensure system is working correctly

**Acceptance Criteria:**
- Can view auto-approval rate (target: 80-95%)
- Can view flag rate (target: 5-20%)
- Can view most common flag reasons
- Can adjust confidence thresholds if needed

### Story 4: Compliance Officer - Audit Trail
**As a** compliance officer  
**I want** complete audit trail of all merges and corrections  
**So that** I can demonstrate HIPAA compliance and data integrity

**Acceptance Criteria:**
- PatientHistory records all merge operations
- Can identify which documents were auto-approved vs manually reviewed
- Can see who reviewed flagged items and when
- Can see what corrections were made

---

## Implementation Approach

**IMPORTANT:** This entire feature should be implemented as **ONE TASK** with the following **SUBTASKS**:

### Subtask 1: Update ParsedData Model Schema
**Goal:** Add fields for auto-approval and flagging

**Work Items:**
- Add `auto_approved` BooleanField
- Add `flag_reason` TextField
- Update `REVIEW_STATUS_CHOICES` to 5-state machine
- Add database indexes for performance
- Generate and test migration

**Deliverable:** Model changes ready for quality check logic

---

### Subtask 2: Add Patient FHIR Operations
**Goal:** Enable idempotent merge and surgical rollback

**Work Items:**
- Implement `update_fhir_resources(fhir_resources, document_id)` method
- Implement `rollback_document_merge(document_id)` method
- Match resources by (source, resourceType) composite key
- Create audit trail via PatientHistory
- Test idempotency (retry safety)

**Deliverable:** Patient model has merge and rollback capabilities

---

### Subtask 3: Implement Quality Check Logic
**Goal:** Automated flagging based on confidence and conflicts

**Work Items:**
- Implement `determine_review_status()` method on ParsedData
- Implement `check_quick_conflicts()` method
- Add confidence threshold checks
- Add resource count validation
- Add DOB/name conflict detection
- Performance optimization (< 100ms for quick checks)

**Deliverable:** Quality checks flag low-confidence extractions

---

### Subtask 4: Modify Document Processing Task
**Goal:** Immediate merge with automated flagging

**Work Items:**
- Update `process_document_async` to call `determine_review_status()`
- Change to use `update_fhir_resources()` instead of holding data
- Merge immediately regardless of flag status
- Handle merge failures gracefully
- Log appropriately based on review status

**Deliverable:** Documents merge immediately after extraction

---

### Subtask 5: Create Data Migration
**Goal:** Migrate existing records to new status system

**Work Items:**
- Map `approved` + no `reviewed_by` → `auto_approved`
- Map `approved` + has `reviewed_by` → `reviewed`
- Test migration on staging data copy
- Verify all records mapped correctly

**Deliverable:** Existing records compatible with new system

---

### Subtask 6: Add Comprehensive Test Coverage
**Goal:** Ensure reliability and catch regressions

**Work Items:**
- Unit tests for quality check logic
- Unit tests for FHIR operations (update, rollback)
- Integration tests for immediate merge workflow
- Retry safety tests (idempotency)
- Performance tests (< 500ms merge time)

**Deliverable:** Full test suite with >90% coverage

---

### Subtask 7: Deploy to Staging and Monitor
**Goal:** Validate with real data and tune thresholds

**Work Items:**
- Deploy to staging environment
- Process 20-30 diverse test documents
- Monitor flag rates (target: 5-20%)
- Monitor merge performance (target: < 500ms)
- Tune confidence thresholds if needed
- Test rollback functionality

**Deliverable:** Validated thresholds and performance benchmarks

---

### Subtask 8: Build Flagged Items UI
**Goal:** Enable human review of flagged extractions

**Work Items:**
- Create dashboard widget showing flagged count
- Build flagged items list view
- Build flagged item detail/verification view
- Implement "Mark as Correct" action
- Implement "Correct Data" workflow
- Implement "Rollback Merge" action

**Deliverable:** Complete UI for reviewing flagged items

---

### Subtask 9: Cleanup Old Review Workflow
**Goal:** Remove obsolete code and deploy to production

**Work Items:**
- Remove `merge_to_patient_record` Celery task
- Simplify `DocumentReviewView` (remove merge logic)
- Remove old approval workflow templates
- Deprecate `is_approved` field
- Update documentation
- Deploy to production
- Monitor for 3-5 days

**Deliverable:** Clean codebase, production deployment complete

---

## Non-Requirements (Explicitly Out of Scope)

### Phase 1 Exclusions:
- ❌ Complex clinical conflict detection (drug interactions, contradictory diagnoses)
- ❌ UI changes (dashboard, flagged items list)
- ❌ Notification system (email/Slack alerts)
- ❌ Threshold tuning interface (admin UI for adjusting confidence levels)
- ❌ Batch operations (bulk rollback, bulk approval)
- ❌ Deep FHIR resource validation (beyond basic structure)

### Future Considerations:
- Advanced conflict detection (defer to Phase 5)
- Machine learning for threshold optimization
- Predictive flagging based on document characteristics
- Integration with external FHIR servers

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Bad data merged immediately** | Low (5%) | Medium | - Robust flagging criteria<br>- Rollback capability<br>- Complete audit trail<br>- Monitor false negative rate |
| **Flag rate too high (>20%)** | Medium | Low | - Start with conservative thresholds<br>- Tune based on staging data<br>- Document threshold rationale |
| **Flag rate too low (<5%)** | Low | Medium | - Monitor false negative rate<br>- Review unflagged errors<br>- Adjust thresholds upward |
| **Performance degradation** | Very Low | Low | - Quick checks < 100ms<br>- Defer complex checks to background<br>- Monitor merge performance |
| **Stakeholder resistance** | Very Low | Low | - They requested this change<br>- Show immediate value (data availability)<br>- Maintain audit trail for compliance |
| **Rollback doesn't work** | Low | High | - Comprehensive testing on staging<br>- Test with various document types<br>- Verify audit trail completeness |
| **Celery retry creates duplicates** | Medium | High | - Use update_fhir_resources (not add)<br>- Match by (source, resourceType)<br>- Test retry scenarios explicitly |

---

## Dependencies

**Technical:**
- Existing `Patient.add_fhir_resources()` method (reference for pattern)
- Existing `PatientHistory` model (audit trail)
- Existing `ParsedData.get_extraction_quality_indicators()` method
- Celery task infrastructure

**Organizational:**
- Stakeholder approval (already obtained)
- Data steward training on new workflow (Phase 3)
- Compliance officer review of audit trail (Phase 2)

---

## Acceptance Criteria (Overall)

**Must Have:**
- ✅ Documents merge to patient FHIR within 5 minutes of upload
- ✅ Only 5-20% of documents flagged for review
- ✅ Flagged documents still merge immediately (no approval gate)
- ✅ Rollback successfully removes only target document's resources
- ✅ No duplicate resources created on Celery retry
- ✅ Complete audit trail for all operations
- ✅ Merge performance < 500ms
- ✅ Merge failures < 1%

**Should Have:**
- ✅ Dashboard widget showing flagged count
- ✅ Efficient UI for reviewing flagged items
- ✅ Notification system for flagged items
- ✅ Threshold tuning based on real data

**Nice to Have:**
- ⚠️ Advanced conflict detection (Phase 5)
- ⚠️ Predictive flagging
- ⚠️ Batch operations

---

## Glossary

**Optimistic Concurrency:** Architectural pattern that assumes operations will succeed and handles conflicts after the fact, rather than preventing them upfront

**Pessimistic Locking:** Architectural pattern that prevents conflicts by requiring approval before committing changes

**Idempotent:** Operation that produces the same result whether executed once or multiple times

**Flag Rate:** Percentage of documents that trigger quality concerns and require human review

**False Positive:** Document flagged for review that turns out to be correct (no changes needed)

**False Negative:** Document auto-approved that should have been flagged (error missed)

**Rollback:** Surgical removal of merged data from patient FHIR record

**Audit Trail:** Complete log of all data operations for compliance and debugging

---

## References

**Related Documents:**
- Main PRD: `docs/PRD.md`
- Architecture Overview: `docs/architecture/README.md`
- HIPAA Compliance: `docs/security/README.md`

**Related Code:**
- Patient Model: `apps/patients/models.py`
- ParsedData Model: `apps/documents/models.py`
- Processing Task: `apps/documents/tasks.py`
- Review Views: `apps/documents/views.py`

**External Resources:**
- FHIR Specification: https://www.hl7.org/fhir/
- Django Celery Best Practices: https://docs.celeryproject.org/en/stable/django/
- Optimistic Concurrency Pattern: https://martinfowler.com/eaaCatalog/optimisticOfflineLock.html

---

## Taskmaster Instructions

**IMPORTANT FOR AI PARSER:**

This PRD describes **ONE FEATURE** that should be created as:
- **1 main task:** "Implement Optimistic Concurrency Merge System"
- **9 subtasks:** As outlined in the Implementation Approach section above

**DO NOT** create 9 separate top-level tasks. This is a single cohesive feature with 9 implementation steps.

**Suggested Task Title:** "Implement Optimistic Concurrency Merge System"

**Suggested Priority:** High

**Suggested Dependencies:** None (this is a new feature)

---

**Document Status:** ✅ Ready for Taskmaster Parsing  
**Last Updated:** 2025-12-01 20:30:00  
**Next Action:** Parse with `task-master parse-prd docs/optimistic-merge-prd.md --num-tasks=1`

