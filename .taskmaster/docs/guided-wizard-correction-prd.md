# Guided Wizard for Flagged Data Correction - PRD

## Overview

Replace the raw JSON editor in the flagged data correction workflow with an intuitive, multi-step guided wizard that allows medical professionals to review and correct extracted data without needing to understand FHIR JSON structure.

## Problem Statement

Current implementation (Task 41.26) requires users to manually edit raw FHIR JSON, which is:
- **Not user-friendly** for medical professionals unfamiliar with JSON/FHIR
- **Error-prone** - easy to break JSON structure or introduce invalid data
- **Inefficient** - requires scrolling through large JSON blocks to find issues
- **Lacks context** - doesn't show source document or confidence scores

Medical staff need a **clinical interface** that presents data in familiar medical terms and guides them through corrections step-by-step.

## Target Users

- **Primary**: Medical providers (doctors, nurses, medical assistants) reviewing flagged documents
- **Secondary**: Medical records staff performing quality assurance
- **Skill Level**: Basic computer literacy, medical terminology knowledge, no technical/coding experience

## Core User Journey

### Current Flow (Problematic)
1. User sees flagged document in list
2. Clicks "Correct Data"
3. Sees 500+ lines of FHIR JSON in textarea
4. Must manually find and edit problematic fields
5. Risk breaking JSON structure
6. Click "Save Corrections & Approve"

### New Flow (Guided Wizard)
1. User sees flagged document in list
2. Clicks "Review & Correct Data"
3. **Step 1**: See summary of flagged items (3 issues found)
4. **Step 2**: Review each issue one-at-a-time with context
5. **Step 3**: Confirm all changes with before/after summary
6. **Step 4**: Approve and merge corrected data

## Detailed Requirements

### R1: Wizard Entry Point (Replace Current "Correct Data" Button)

**URL**: `/documents/flagged/<id>/wizard/`

**Initial Screen**:
```
┌─────────────────────────────────────────────────────┐
│ Review Flagged Document                              │
│ Document: patient_record_2024.pdf                   │
│ Patient: John Doe (MRN: 12345)                      │
├─────────────────────────────────────────────────────┤
│ Flag Reason:                                         │
│ • Low extraction confidence (0.72 < 0.80 threshold) │
│ • Fallback AI model used: gpt-3.5-turbo            │
│ • Potential data conflict: Birth date mismatch      │
├─────────────────────────────────────────────────────┤
│ Issues Found: 3                                      │
│                                                      │
│ ⚠️ Birth Date Conflict                              │
│ ⚠️ Medication Dosage Unclear                        │
│ ⚠️ Diagnosis Code Low Confidence (68%)              │
│                                                      │
│ [Start Review] [Mark All as Correct] [Cancel]       │
└─────────────────────────────────────────────────────┘
```

**Technical Implementation**:
- Parse `flag_reason` to identify specific issues
- Analyze `extraction_json` for low-confidence fields (< 0.80)
- Compare `fhir_delta_json` with existing `patient.cumulative_fhir_json` for conflicts
- Count total issues to show progress (Issue 1 of 3)

---

### R2: Step-by-Step Issue Resolution

**URL**: `/documents/flagged/<id>/wizard/issue/<issue_id>/`

**For Each Issue, Show**:

#### A) Issue Context Card
```
┌─────────────────────────────────────────────────────┐
│ Issue 1 of 3: Birth Date Conflict                   │
│ Confidence: 75%                                      │
├─────────────────────────────────────────────────────┤
│ Extracted Value:  1980-01-15                        │
│ Current Record:   1980-01-01                        │
│ Source Location:  Page 2, Header Section            │
└─────────────────────────────────────────────────────┘
```

#### B) OCR Preview (Visual Context)
```
┌─────────────────────────────────────────────────────┐
│ Document Preview                                     │
│ ┌─────────────────────────────────────────────────┐ │
│ │ [Highlighted section of PDF showing:]           │ │
│ │                                                  │ │
│ │ Patient Name: John Doe                          │ │
│ │ Date of Birth: 01/15/1980  ← [HIGHLIGHTED]     │ │
│ │ MRN: 12345                                      │ │
│ └─────────────────────────────────────────────────┘ │
│ [View Full Document]                                 │
└─────────────────────────────────────────────────────┘
```

#### C) Resolution Options
```
┌─────────────────────────────────────────────────────┐
│ How would you like to resolve this?                 │
│                                                      │
│ ○ Use extracted value: 1980-01-15                   │
│   (From document, confidence 75%)                   │
│                                                      │
│ ○ Keep existing value: 1980-01-01                   │
│   (Current patient record)                          │
│                                                      │
│ ● Enter manually:                                    │
│   [MM/DD/YYYY] [📅 Calendar Picker]                │
│   1980-01-15                                        │
│                                                      │
│ ○ Skip this field (leave unchanged)                 │
│                                                      │
│ Notes (optional):                                    │
│ [Verified with patient during check-in]             │
│                                                      │
│ [← Previous] [Next Issue →] [Skip All Remaining]    │
└─────────────────────────────────────────────────────┘
```

#### D) AI-Assisted Suggestions (Smart Defaults)
```
┌─────────────────────────────────────────────────────┐
│ 💡 AI Suggestion                                     │
│                                                      │
│ Extracted: "metformin 500 twice daily"              │
│                                                      │
│ Did you mean:                                        │
│ ✓ Metformin 500mg PO BID                            │
│   (RxNorm: 860975)                                  │
│                                                      │
│ Other possibilities:                                 │
│ • Metformin 500mg PO TID                            │
│ • Metformin ER 500mg PO QD                          │
│                                                      │
│ [Use Suggestion] [Edit Manually] [Skip]             │
└─────────────────────────────────────────────────────┘
```

**Technical Implementation**:
- Store wizard state in session: `request.session['wizard_state']`
- Track current issue index, resolutions made, skipped items
- Use `extraction_json` to get confidence scores and source locations
- Parse `structured_data` (encrypted field) to get OCR bounding boxes
- Call AI service for suggestions (Claude/GPT with medical context)
- Integrate with RxNorm API for medication validation
- Integrate with ICD-10 API for diagnosis code validation

---

### R3: Confirmation Summary Screen

**URL**: `/documents/flagged/<id>/wizard/confirm/`

**Show Before/After Comparison**:
```
┌─────────────────────────────────────────────────────┐
│ Review Your Changes                                  │
│                                                      │
│ You've resolved 3 issues:                           │
├─────────────────────────────────────────────────────┤
│ 1. Birth Date                                        │
│    Before: 1980-01-01                               │
│    After:  1980-01-15 ✓                             │
│    Note:   Verified with patient                    │
│                                                      │
│ 2. Medication                                        │
│    Before: metformin 500 twice daily                │
│    After:  Metformin 500mg PO BID ✓                 │
│    Note:   AI suggestion accepted                   │
│                                                      │
│ 3. Diagnosis                                         │
│    Before: Type 2 diabetes (confidence 68%)         │
│    After:  Type 2 diabetes mellitus (E11.9) ✓       │
│    Note:   Code validated                           │
├─────────────────────────────────────────────────────┤
│ Final Review Notes (optional):                      │
│ [All corrections verified against source document]  │
│                                                      │
│ [← Back to Edit] [Approve & Save] [Cancel]          │
└─────────────────────────────────────────────────────┘
```

**Technical Implementation**:
- Retrieve all resolutions from session
- Build comparison table showing old vs. new values
- Generate updated FHIR JSON from resolutions
- Validate FHIR structure before allowing approval
- Store resolution metadata for audit trail

---

### R4: Final Approval & Merge

**Action**: Convert wizard resolutions back to FHIR JSON and save

**Process**:
1. Take user's field-level corrections
2. Update corresponding FHIR resources in `fhir_delta_json`
3. Validate FHIR structure
4. Save to `ParsedData.fhir_delta_json`
5. Call `approve_extraction(user, notes=wizard_summary)`
6. Redirect to flagged list with success message

**Success Message**:
```
✓ Document corrected and approved
  3 fields updated, data merged to patient record
```

---

### R5: OCR Preview Integration

**Requirements**:
- Display PDF with highlighted bounding boxes around extracted text
- Use `structured_data` field (encrypted) which contains OCR coordinates
- Render PDF in browser with overlays using PDF.js
- Click highlighted region to zoom/focus

**Technical Stack**:
- **Frontend**: PDF.js for rendering, Canvas API for highlights
- **Backend**: Decrypt `structured_data`, extract bounding boxes
- **API Endpoint**: `/documents/<id>/ocr-preview/?field=<field_name>`

**Example Response**:
```json
{
  "pdf_url": "/media/documents/patient_record.pdf",
  "highlights": [
    {
      "field": "date_of_birth",
      "page": 2,
      "bbox": {"x": 120, "y": 350, "width": 80, "height": 20},
      "text": "01/15/1980",
      "confidence": 0.75
    }
  ]
}
```

---

### R6: AI-Assisted Suggestions

**Use Cases**:
1. **Medication Normalization**: "metformin 500 twice daily" → "Metformin 500mg PO BID"
2. **Diagnosis Code Lookup**: "diabetes" → "Type 2 diabetes mellitus (E11.9)"
3. **Date Format Standardization**: "1/15/80" → "1980-01-15"
4. **Dosage Clarification**: "1 tab" → "1 tablet PO"

**Technical Implementation**:
- Call Claude/GPT with medical context prompt
- Include extracted text, confidence score, field type
- Request structured response with alternatives
- Cache common corrections in database for speed
- Fallback to manual entry if AI unavailable

**Prompt Template**:
```
You are a medical data assistant helping correct extracted patient data.

Field Type: Medication
Extracted Text: "metformin 500 twice daily"
Confidence: 0.72

Provide:
1. Most likely correct interpretation in standard medical notation
2. RxNorm code if applicable
3. 2-3 alternative interpretations if ambiguous

Format response as JSON.
```

---

### R7: Medical Terminology API Integration

**Integrate with**:
1. **RxNorm API** (NLM): Medication validation and normalization
   - Endpoint: `https://rxnav.nlm.nih.gov/REST/rxcui.json?name=metformin`
   - Use for: Medication names, dosages, RxCUI codes

2. **ICD-10 API** (CMS): Diagnosis code validation
   - Endpoint: `https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search`
   - Use for: Diagnosis codes, descriptions

3. **LOINC API**: Lab test codes (future enhancement)

**Caching Strategy**:
- Cache API responses in Redis (1 week TTL)
- Store common corrections in `MedicalTerminologyCache` model
- Fallback to local database if API unavailable

---

### R8: Wizard State Management

**Session Storage**:
```python
request.session['wizard_state'] = {
    'parsed_data_id': 123,
    'total_issues': 3,
    'current_issue_index': 0,
    'resolutions': [
        {
            'field': 'date_of_birth',
            'original_value': '1980-01-01',
            'corrected_value': '1980-01-15',
            'resolution_type': 'manual_entry',
            'notes': 'Verified with patient',
            'fhir_path': 'Patient.birthDate'
        }
    ],
    'skipped_fields': ['medication_2'],
    'started_at': '2025-01-02T12:00:00Z'
}
```

**Persistence**:
- Store in Django session (database-backed)
- Expire after 1 hour of inactivity
- Allow "Resume" if user navigates away

---

## Technical Architecture

### New Models

```python
class WizardSession(models.Model):
    """Track wizard correction sessions for audit trail"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    parsed_data = models.ForeignKey(ParsedData, on_delete=models.CASCADE)
    started_by = models.ForeignKey(User, on_delete=models.PROTECT)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=20)  # 'in_progress', 'completed', 'abandoned'
    resolutions = models.JSONField(default=list)
    total_issues = models.IntegerField()
    issues_resolved = models.IntegerField(default=0)

class MedicalTerminologyCache(models.Model):
    """Cache API responses for medical terminology lookups"""
    term = models.CharField(max_length=255, unique=True, db_index=True)
    term_type = models.CharField(max_length=50)  # 'medication', 'diagnosis', 'procedure'
    normalized_value = models.CharField(max_length=255)
    standard_code = models.CharField(max_length=50)  # RxNorm, ICD-10, etc.
    confidence = models.FloatField()
    source_api = models.CharField(max_length=50)
    cached_at = models.DateTimeField(auto_now_add=True)
    hit_count = models.IntegerField(default=0)
```

### New Views

```python
# apps/documents/views.py

class WizardStartView(LoginRequiredMixin, DetailView):
    """Initialize wizard session and show issue summary"""
    
class WizardIssueView(LoginRequiredMixin, View):
    """Display single issue for resolution"""
    
class WizardConfirmView(LoginRequiredMixin, View):
    """Show summary of all resolutions before saving"""
    
class WizardApproveView(LoginRequiredMixin, View):
    """Convert resolutions to FHIR and save"""

# API endpoints
class OCRPreviewAPIView(LoginRequiredMixin, View):
    """Return PDF with OCR bounding boxes"""
    
class AISuggestionAPIView(LoginRequiredMixin, View):
    """Get AI-powered correction suggestions"""
    
class MedicalTermLookupAPIView(LoginRequiredMixin, View):
    """Query medical terminology APIs"""
```

### New Services

```python
# apps/documents/services/wizard_service.py

class WizardIssueAnalyzer:
    """Analyze ParsedData to identify specific issues"""
    def analyze_flagged_data(self, parsed_data) -> List[Issue]
    def extract_low_confidence_fields(self, extraction_json) -> List[Issue]
    def detect_conflicts(self, fhir_delta, patient_fhir) -> List[Issue]

class WizardResolutionConverter:
    """Convert field-level resolutions back to FHIR JSON"""
    def apply_resolutions(self, fhir_json, resolutions) -> dict
    def validate_fhir_structure(self, fhir_json) -> bool

class MedicalTerminologyService:
    """Interface with medical terminology APIs"""
    def lookup_medication(self, text) -> List[MedicationSuggestion]
    def lookup_diagnosis(self, text) -> List[DiagnosisSuggestion]
    def normalize_dosage(self, text) -> str

class AISuggestionService:
    """Generate AI-powered correction suggestions"""
    def suggest_correction(self, field_type, extracted_text, confidence) -> Suggestion
```

---

## UI/UX Requirements

### Design Principles
- **Progressive disclosure**: Show one issue at a time, don't overwhelm
- **Visual hierarchy**: Use color/icons to indicate severity (red=conflict, yellow=low confidence)
- **Contextual help**: Inline tooltips explaining medical codes
- **Keyboard navigation**: Tab through options, Enter to confirm
- **Mobile responsive**: Works on tablets for bedside review

### Visual Design
- Use existing Tailwind CSS classes for consistency
- Color coding:
  - 🔴 Red: Conflicts requiring resolution
  - 🟡 Yellow: Low confidence (< 0.80)
  - 🟢 Green: Resolved/approved
  - 🔵 Blue: AI suggestions
- Progress indicator: "Issue 2 of 5" with progress bar

### Accessibility
- ARIA labels for screen readers
- Keyboard shortcuts (N=Next, P=Previous, S=Skip)
- High contrast mode support
- Focus management between steps

---

## Implementation Phases

### Phase 1: Core Wizard Flow (MVP)
**Estimated: 2-3 days**
- Wizard entry point and issue summary screen
- Step-by-step issue resolution (basic)
- Confirmation summary
- Convert resolutions to FHIR and save
- **No AI suggestions or OCR preview yet**

### Phase 2: AI-Assisted Suggestions
**Estimated: 2 days**
- Integrate Claude/GPT for suggestions
- Medication normalization
- Diagnosis code lookup
- Smart defaults based on field type

### Phase 3: OCR Preview Integration
**Estimated: 2-3 days**
- PDF.js integration for rendering
- Decrypt and parse `structured_data`
- Highlight bounding boxes
- Click to zoom/focus

### Phase 4: Medical Terminology APIs
**Estimated: 1-2 days**
- RxNorm API integration
- ICD-10 API integration
- Caching layer
- Fallback handling

### Phase 5: Polish & Testing
**Estimated: 1-2 days**
- Comprehensive test coverage
- Performance optimization
- Error handling edge cases
- User acceptance testing

**Total Estimated Time: 8-12 days**

---

## Success Metrics

### User Experience
- **Time to resolve**: < 2 minutes per flagged document (vs. 5+ minutes with JSON editor)
- **Error rate**: < 5% of corrections require re-review
- **User satisfaction**: > 80% prefer wizard over manual editing
- **Abandonment rate**: < 10% of started wizards not completed

### Technical
- **API response time**: < 500ms for AI suggestions
- **OCR preview load time**: < 2 seconds
- **Session persistence**: 99% of sessions recoverable after navigation
- **FHIR validation**: 100% of wizard outputs produce valid FHIR

### Business
- **Adoption rate**: > 90% of flagged documents use wizard (vs. Mark as Correct/Rollback)
- **Throughput**: 2x increase in flagged documents processed per day
- **Quality**: 30% reduction in post-approval corrections

---

## Dependencies

### External APIs
- **RxNorm API** (NLM): Free, no API key required
- **ICD-10 API** (NLM): Free, no API key required
- **Claude/GPT**: Existing API keys (already in use)

### Internal Systems
- **PDF.js**: Add to frontend dependencies
- **Redis**: For caching API responses (optional, can use DB)
- **Celery**: For async AI suggestion generation (optional)

### Database Changes
- Add `WizardSession` model (new table)
- Add `MedicalTerminologyCache` model (new table)
- No changes to existing `ParsedData` structure

---

## Rollout Strategy

### Beta Testing
1. **Week 1-2**: Internal testing with dev team
2. **Week 3-4**: Pilot with 2-3 medical staff users
3. **Week 5**: Gather feedback, iterate on UX
4. **Week 6**: Full rollout to all users

### Feature Flags
- `WIZARD_ENABLED`: Master switch to enable/disable wizard
- `WIZARD_AI_SUGGESTIONS`: Toggle AI suggestions
- `WIZARD_OCR_PREVIEW`: Toggle OCR preview
- `WIZARD_API_INTEGRATION`: Toggle external API calls

### Rollback Plan
- Keep existing "Correct Data" (raw JSON) as fallback
- Add "Use Advanced Editor" link in wizard for power users
- Monitor error rates and user feedback
- Can disable wizard via feature flag without code deploy

---

## Open Questions / Future Enhancements

1. **Batch Correction**: Allow resolving similar issues across multiple documents at once?
2. **Learning System**: Track common corrections to improve AI suggestions over time?
3. **Collaborative Review**: Allow multiple reviewers to work on same document?
4. **Mobile App**: Native iOS/Android app for bedside review?
5. **Voice Input**: "Alexa, update patient birth date to January 15, 1980"?
6. **Integration with EHR**: Pull existing patient data from Epic/Cerner for comparison?

---

## Appendix: Example Issue Types

### A) Low Confidence Extraction
```
Field: Medication dosage
Extracted: "1 tab"
Confidence: 0.65
Issue: Ambiguous - need to specify mg and frequency
Suggestion: "1 tablet PO QD" or "1 tablet PO BID"?
```

### B) Data Conflict
```
Field: Birth date
Extracted: 1980-01-15
Existing: 1980-01-01
Issue: Mismatch between document and patient record
Resolution: User must choose or enter manually
```

### C) Missing Required Field
```
Field: Diagnosis code
Extracted: "diabetes"
Issue: No ICD-10 code provided
Suggestion: E11.9 (Type 2 diabetes mellitus without complications)
```

### D) Format Standardization
```
Field: Medication name
Extracted: "metformin five hundred milligrams twice a day"
Issue: Non-standard format
Suggestion: Metformin 500mg PO BID (RxNorm: 860975)
```

---

## TaskMaster Build Guidance

### Recommended Task Breakdown

**Parent Task**: "Implement Guided Wizard for Flagged Data Correction"

**Subtasks**:
1. Create `WizardSession` and `MedicalTerminologyCache` models with migrations
2. Build `WizardIssueAnalyzer` service to parse flagged data into discrete issues
3. Implement wizard entry point view (issue summary screen)
4. Build step-by-step issue resolution view with radio button options
5. Create confirmation summary view showing before/after comparison
6. Implement `WizardResolutionConverter` to convert field resolutions back to FHIR
7. Build AI suggestion service integration (Claude/GPT)
8. Integrate RxNorm API for medication lookup and caching
9. Integrate ICD-10 API for diagnosis code validation
10. Implement OCR preview with PDF.js and bounding box highlights
11. Add session state management and recovery
12. Create comprehensive test suite for wizard flow
13. Build wizard UI templates with Tailwind CSS
14. Add keyboard navigation and accessibility features
15. Implement feature flags and rollback mechanisms

**Dependencies Between Subtasks**:
- Subtask 2 must complete before 3-5 (need issue analysis)
- Subtask 6 must complete before wizard can save (FHIR conversion)
- Subtasks 7-9 can be done in parallel (AI/API integrations)
- Subtask 10 can be done independently (OCR preview)
- Subtask 13 depends on 3-5 (need views before templates)

**Testing Strategy**:
- Unit tests for each service class
- Integration tests for wizard flow end-to-end
- API mocking for external services (RxNorm, ICD-10)
- UI tests with Selenium for step navigation
- Load testing with 100+ concurrent wizard sessions

**Estimated Complexity**: High (8-10 on scale of 1-10)
**Estimated Time**: 8-12 development days
**Priority**: Medium (enhancement to existing feature)

---

*This PRD provides a complete specification for TaskMaster to generate detailed implementation tasks. All technical details, API endpoints, data models, and user flows are included for autonomous task generation.*

