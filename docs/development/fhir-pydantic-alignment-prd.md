# FHIR/Pydantic Complete Alignment - Implementation Plan

**Version:** 2.0 (TaskMaster Ready)  
**Date:** 2025-10-29  
**Status:** Ready for task generation via `task-master parse-prd`  
**Author:** AI Agent in collaboration with product stakeholders
**Estimated Effort:** 6-7 weeks across 4 phases for complete 12/12 alignment

---

## 1. Executive Summary

**Mission:** Achieve 12/12 alignment between AI extraction (Pydantic models) and FHIR processing (FHIR services) to eliminate data loss in medical document processing pipeline.

**Current State:** Only 6 of 12 resource types have complete Pydantic-to-FHIR alignment. Data loss occurs when `StructuredDataConverter._convert_structured_to_dict()` downgrades rich Pydantic models to legacy dict format during initial document processing (apps/fhir/converters.py:934-1030). This degradation happens BEFORE user review, meaning users approve already-lossy data.

**Critical Finding:** The review workflow (ParsedData approval) cannot recover data lost during conversion. Users review ParsedData.fhir_delta_json which contains already-degraded FHIR resources.

**Solution Approach:** Create complete bidirectional alignment by:
1. **AI Extraction Layer:** Add missing Pydantic models (Encounter, ServiceRequest, DiagnosticReport, AllergyIntolerance, CarePlan, Organization) and update AI prompts to extract them
2. **FHIR Processing Layer:** Update all 6 existing services to accept structured Pydantic input, create 6 new services for missing resource types
3. **Infrastructure:** Wire all services into FHIRProcessor, make structured path primary with legacy fallback

**Deliverable:** Complete pipeline where all 12 resource types flow from extraction → structured processing → user review → patient record without data degradation.

---

## 2. Problem Statement

### Current Alignment (6/12 Implemented)

|#|Pydantic Model|FHIR Service|Phase|Action Required|
|---|---|---|---|---|
|1|MedicalCondition ✅|ConditionService ✅|Existing|Update service for structured input|
|2|Medication ✅|MedicationService ✅|Existing|Update service for structured input|
|3|VitalSign ✅|ObservationService ✅|Existing|Update service for structured input|
|4|LabResult ✅|ObservationService ✅|Existing|Update service for structured input|
|5|Procedure ✅|❌ **Create in Phase 1**|Phase 1|Create FHIR service|
|6|Provider ✅|❌ **Create in Phase 1**|Phase 1|Create FHIR service|
|7|❌ **Create in Phase 2**|EncounterService ✅|Phase 2|Create Pydantic model|
|8|❌ **Create in Phase 2**|ServiceRequestService ✅|Phase 2|Create Pydantic model|
|9|❌ **Create in Phase 2**|DiagnosticReportService ✅|Phase 2|Create Pydantic model|
|10|❌ **Create in Phase 3**|❌ **Create in Phase 3**|Phase 3|Create both (AllergyIntolerance)|
|11|❌ **Create in Phase 3**|❌ **Create in Phase 3**|Phase 3|Create both (CarePlan)|
|12|❌ **Create in Phase 3**|❌ **Create in Phase 3**|Phase 3|Create both (Organization)|

**Target:** 12/12 Complete Alignment

### Core Issues

|Issue|Impact|Evidence|
|---|---|---|
|Structured data downgraded to legacy format|Loss of fidelity and extra transformations|`StructuredDataConverter` collapses Pydantic payloads into `'fields'` dictionaries before invoking services|
|`FHIRProcessor` advertises fewer services than metrics claim|Capabilities reports are inaccurate|`FHIRProcessor.get_supported_resource_types()` returns 4 entries vs. 11 in `FHIRMetricsService`|
|Missing Procedure & Practitioner handling in processor|Pydantic data bypasses processor; legacy fallback drops data|TODO comments in `FHIRProcessor` and empty `_process_procedures/_process_practitioners`|
|Services constrained to legacy `fields` arrays|Structured payload cannot flow end-to-end|`ConditionService`, `MedicationService`, etc. read only `'fields'`|

---

## 3. Architectural Goals

1. **Single primary pipeline:** `FHIRProcessor` becomes the canonical path, consuming structured payloads directly and falling back to legacy fields only as needed
    
2. **Dual-format services:** Every service must detect structured lists (Pydantic-derived dicts) and legacy `fields`, using ClinicalDateParser for date normalization in both cases
    
3. **Metrics parity:** `FHIRProcessor.get_supported_resource_types()` and `FHIRMetricsService.supported_resource_types` must list the same set, and real implementations must exist for each entry
    
4. **Backward compatibility:** Legacy `'fields'` payloads continue to work without regression
    

---

## 4. Scope

### In Scope

**Existing Service Updates (4 resources):**

- Updating ConditionService, MedicationService, and ObservationService (covering VitalSigns and LabResults) to accept both structured Pydantic inputs and legacy `fields` arrays

**New FHIR Service Creation (2 resources - Phase 1):**

- Implementing ProcedureService and PractitionerService to consume existing Pydantic models

**New Pydantic Model Creation (3 resources - Phase 2):**

- Creating Encounter, ServiceRequest, and DiagnosticReport Pydantic models
- Updating corresponding existing FHIR services to process these new structured models

**Complete Resource Implementation (3 resources - Phase 3):**

- Creating AllergyIntolerance, CarePlan, and Organization Pydantic models AND their corresponding FHIR services

**Infrastructure:**

- Wiring all new services into `FHIRProcessor` initialization, processing pipeline, and supported resource type registry
- Enhancing `FHIRMetricsService` to validate that all advertised services are wired and report discrepancies
- Maintaining ClinicalDateParser usage across all date handling paths

### Out of Scope

- Replacing `StructuredDataConverter`; it will remain as a bridge for legacy fallbacks
- Creating alternate processors or new monitoring modules (e.g., `alignment_monitor.py`)
- Modifying the AI extraction pipeline's core architecture (only updating prompts and schemas)

---

## 5. Updated Phase Plan

### Phase 1 – Update Existing Services and Create Missing Services (Weeks 1-2)

**Objective:** Enable 4 existing FHIR services to accept structured Pydantic input while maintaining legacy support. Create 2 new FHIR services for existing Pydantic models (Procedure, Provider).

**Target Files:**
- Modify: `apps/fhir/services/condition_service.py`
- Modify: `apps/fhir/services/medication_service.py`
- Modify: `apps/fhir/services/observation_service.py`
- Create: `apps/fhir/services/procedure_service.py` (~200 lines following ConditionService pattern)
- Create: `apps/fhir/services/practitioner_service.py` (~180 lines following ConditionService pattern)
- Modify: `apps/fhir/services/fhir_processor.py` (wire new services into pipeline)
- Modify: `apps/fhir/services/metrics_service.py` (dynamic resource type detection)

**Detailed Implementation Requirements:**

1. **Update ConditionService** (apps/fhir/services/condition_service.py):
   - Add `_create_condition_from_structured(condition_dict: Dict, patient_id: str)` method that processes MedicalCondition Pydantic model dict format
   - Modify `process_conditions()` to detect `structured_data` key and prioritize it over legacy `fields`
   - Extract: name, status, onset_date, icd_code, source context from condition_dict
   - Use ClinicalDateParser for all date handling in both structured and legacy paths
   - Add logging to indicate which path (structured vs legacy) was used for each resource
   - Maintain 100% backward compatibility with existing legacy fields processing

2. **Update MedicationService** (apps/fhir/services/medication_service.py):
   - Add `_create_medication_from_structured(medication_dict: Dict, patient_id: str)` method for Medication Pydantic model
   - Update `process_medications()` for dual-format detection
   - Extract: medication_name, dosage, frequency, route, start_date, end_date, prescriber from medication_dict
   - Ensure ClinicalDateParser handles start_date and end_date consistently
   - Maintain legacy fallback with full regression coverage

3. **Update ObservationService** (apps/fhir/services/observation_service.py):
   - Add `_create_observation_from_structured(observation_dict: Dict, patient_id: str, obs_type: str)` method
   - Handle both VitalSign Pydantic model (measurement, value, unit, timestamp) and LabResult Pydantic model (test_name, value, unit, reference_range, result_date)
   - Update `process_observations()` to detect structured vital_signs and lab_results lists
   - Use ClinicalDateParser for timestamp and result_date fields
   - Maintain legacy fields processing for backward compatibility

4. **Create ProcedureService** (apps/fhir/services/procedure_service.py):
   - New service following ConditionService architectural pattern
   - Implement `process_procedures(extracted_data: Dict)` main entry point
   - Implement `_create_procedure_from_structured(procedure_dict: Dict, patient_id: str)` for Procedure Pydantic model
   - Extract: procedure_name, procedure_date, performer, location, notes from procedure_dict
   - Implement `_create_procedure_from_field(field: Dict, patient_id: str)` for legacy fallback
   - Use ClinicalDateParser for procedure_date normalization
   - Return List[Dict[str, Any]] of FHIR Procedure resources

5. **Create PractitionerService** (apps/fhir/services/practitioner_service.py):
   - New service following established service patterns
   - Implement `process_practitioners(extracted_data: Dict)` main entry point
   - Implement `_create_practitioner_from_structured(provider_dict: Dict, patient_id: str)` for Provider Pydantic model
   - Extract: provider_name, credentials, specialty, npi from provider_dict
   - Handle name parsing for various formats (Last, First; First Last; Dr. First Last)
   - Implement legacy fallback for backward compatibility
   - Return List[Dict[str, Any]] of FHIR Practitioner resources

6. **Wire Services into FHIRProcessor** (apps/fhir/services/fhir_processor.py):
   - Import ProcedureService and PractitionerService in __init__ section
   - Instantiate both services in __init__() method: `self.procedure_service = ProcedureService()` and `self.practitioner_service = PractitionerService()`
   - Implement `_process_procedures(extracted_data: Dict)` method calling procedure_service.process_procedures()
   - Implement `_process_practitioners(extracted_data: Dict)` method calling practitioner_service.process_practitioners()
   - Call both methods from main `process_extracted_data()` pipeline
   - Update `get_supported_resource_types()` to return 8 types (was 4): add 'Procedure' and 'Practitioner'
   - Update `validate_processing_capabilities()` to check procedure_service and practitioner_service initialization

7. **Update FHIRMetricsService** (apps/fhir/services/metrics_service.py):
   - Change `supported_resource_types` from hardcoded list to dynamic computation
   - Query FHIRProcessor.get_supported_resource_types() for actual capabilities
   - Add validation method that emits warnings if metrics claim resources not in processor
   - Ensure metrics calculations work with new 8-type list

**Testing Requirements:**
- Unit tests for each updated service: structured input, minimal data, legacy fallback, error handling (test coverage ≥95%)
- Unit tests for new services: full CRUD operations, date parsing, name parsing (≥95% coverage)
- Integration tests: end-to-end pipeline with Procedure and Practitioner data
- Regression tests: all existing legacy tests must pass without modification
- Metrics validation tests: FHIRMetricsService matches FHIRProcessor capabilities

**Acceptance Criteria:**
- All 4 existing services process structured Pydantic models without data loss
- 2 new services successfully process Procedure and Practitioner models
- Legacy fields format still works (zero regression)
- FHIRProcessor.get_supported_resource_types() returns 8 types
- FHIRMetricsService dynamically reflects processor capabilities
- All dates parsed consistently via ClinicalDateParser
- Test coverage ≥95% on all modified/new code
- Alignment progress: 6/12 → 8/12 resource types complete

### Phase 2 – Add Missing Pydantic Models and Update Services (Weeks 3-4)

**Objective:** Create 3 new Pydantic models for AI extraction (Encounter, ServiceRequest, DiagnosticReport), update AI prompts to extract them, and modify 3 existing FHIR services to process the new structured data.

**Target Files:**
- Modify: `apps/documents/services/ai_extraction.py` (add 3 Pydantic models, update system prompt, update StructuredMedicalExtraction)
- Modify: `apps/fhir/services/encounter_service.py`
- Modify: `apps/fhir/services/service_request_service.py`
- Modify: `apps/fhir/services/diagnostic_report_service.py`

**Detailed Implementation Requirements:**

**PART A: AI Extraction Layer (add missing Pydantic models)**

1. **Create Encounter Pydantic Model** (apps/documents/services/ai_extraction.py, add after Provider class ~line 194):
   ```python
   class Encounter(BaseModel):
       encounter_id: Optional[str] = Field(default=None, description="Unique identifier for this encounter")
       encounter_type: str = Field(description="Type: office visit, emergency, telehealth, inpatient, outpatient, etc.")
       encounter_date: Optional[str] = Field(default=None, description="Start date/time of encounter (ISO format preferred)")
       encounter_end_date: Optional[str] = Field(default=None, description="End date/time if applicable")
       location: Optional[str] = Field(default=None, description="Facility or location name")
       reason: Optional[str] = Field(default=None, description="Chief complaint or reason for visit")
       participants: List[str] = Field(default_factory=list, description="Provider names involved in encounter")
       status: Optional[str] = Field(default=None, description="Status: planned, arrived, in-progress, finished, cancelled")
       source: SourceContext = Field(description="Source location in document")
       confidence: float = Field(ge=0.0, le=1.0, description="Extraction confidence 0-1")
   ```
   - Add validator for encounter_date format validation
   - Add docstring with examples of what constitutes an encounter

2. **Create ServiceRequest Pydantic Model** (apps/documents/services/ai_extraction.py, add after Encounter):
   ```python
   class ServiceRequest(BaseModel):
       request_id: Optional[str] = Field(default=None, description="Unique identifier")
       request_type: str = Field(description="Type: lab test, imaging study, referral, consultation, procedure order")
       requester: Optional[str] = Field(default=None, description="Ordering provider name")
       reason: Optional[str] = Field(default=None, description="Clinical indication or reason for request")
       priority: Optional[str] = Field(default=None, description="Priority: routine, urgent, stat, asap")
       clinical_context: Optional[str] = Field(default=None, description="Additional clinical context")
       request_date: Optional[str] = Field(default=None, description="Date order was placed")
       source: SourceContext = Field(description="Source location in document")
       confidence: float = Field(ge=0.0, le=1.0, description="Extraction confidence 0-1")
   ```
   - Add validator for request_date format
   - Add docstring with examples (referrals, lab orders, imaging orders)

3. **Create DiagnosticReport Pydantic Model** (apps/documents/services/ai_extraction.py, add after ServiceRequest):
   ```python
   class DiagnosticReport(BaseModel):
       report_id: Optional[str] = Field(default=None, description="Unique identifier")
       report_type: str = Field(description="Type: lab, radiology, pathology, cardiology, etc.")
       findings: str = Field(description="Key findings or results from report")
       conclusion: Optional[str] = Field(default=None, description="Diagnostic conclusion or impression")
       recommendations: Optional[str] = Field(default=None, description="Recommended follow-up or actions")
       status: Optional[str] = Field(default=None, description="Status: preliminary, final, amended, corrected")
       report_date: Optional[str] = Field(default=None, description="Date report was generated")
       ordering_provider: Optional[str] = Field(default=None, description="Provider who ordered the test")
       source: SourceContext = Field(description="Source location in document")
       confidence: float = Field(ge=0.0, le=1.0, description="Extraction confidence 0-1")
   ```
   - Add validator for report_date format
   - Add docstring with examples of diagnostic reports

4. **Update StructuredMedicalExtraction Schema** (apps/documents/services/ai_extraction.py, ~line 196-227):
   - Add three new fields to StructuredMedicalExtraction class:
   ```python
   encounters: List[Encounter] = Field(
       default_factory=list,
       description="All clinical encounters and visits documented"
   )
   service_requests: List[ServiceRequest] = Field(
       default_factory=list,
       description="All service requests, orders, and referrals"
   )
   diagnostic_reports: List[DiagnosticReport] = Field(
       default_factory=list,
       description="All diagnostic reports and study results"
   )
   ```
   - Update confidence_average validator to include new resource types

5. **Update AI Extraction System Prompt** (apps/documents/services/ai_extraction.py, ~lines 334-415):
   - Add comprehensive extraction instructions for each new resource type in the system prompt:
   ```
   7. **Encounter Information** - Extract ALL encounter/visit details:
      - Type of encounter (office visit, ER visit, telehealth, hospital admission, discharge, etc.)
      - Encounter dates (admission date, discharge date, visit date)
      - Location or facility name
      - Reason for visit or chief complaint
      - All providers involved (attending, consultants, specialists)
      - Status if mentioned (planned, completed, cancelled)
      
   8. **Service Requests** - Extract ALL orders, referrals, and requests:
      - Type of request (lab test, imaging study, specialist referral, procedure order)
      - Ordering provider
      - Clinical indication or reason
      - Priority level (routine, urgent, stat)
      - Date ordered
      
   9. **Diagnostic Reports** - Extract ALL test results and diagnostic findings:
      - Report type (lab, radiology, pathology, cardiology, etc.)
      - Key findings and results
      - Diagnostic conclusions or impressions
      - Recommendations or follow-up actions
      - Report date
      - Ordering provider
   ```
   - Add examples of medical terminology to look for (e.g., "referred to cardiology" = ServiceRequest, "CT scan showed" = DiagnosticReport)

**PART B: FHIR Processing Layer (update existing services)**

6. **Update EncounterService** (apps/fhir/services/encounter_service.py):
   - Add `_create_encounter_from_structured(encounter_dict: Dict, patient_id: str)` method
   - Update `process_encounter()` to detect `structured_data.encounters` list and prioritize it
   - Extract: encounter_type, encounter_date, encounter_end_date, location, reason, participants list
   - Use ClinicalDateParser for both encounter_date and encounter_end_date
   - Map participants list to FHIR Encounter.participant array
   - Maintain legacy `fields` handling as fallback

7. **Update ServiceRequestService** (apps/fhir/services/service_request_service.py):
   - Add `_create_service_request_from_structured(request_dict: Dict, patient_id: str)` method
   - Update `process_service_requests()` to detect `structured_data.service_requests` list
   - Extract: request_type, requester, reason, priority, clinical_context, request_date
   - Use ClinicalDateParser for request_date
   - Map priority to FHIR priority codes (routine, urgent, stat, asap)
   - Maintain legacy fallback

8. **Update DiagnosticReportService** (apps/fhir/services/diagnostic_report_service.py):
   - Add `_create_diagnostic_report_from_structured(report_dict: Dict, patient_id: str)` method
   - Update `process_diagnostic_reports()` to detect `structured_data.diagnostic_reports` list
   - Extract: report_type, findings, conclusion, recommendations, status, report_date, ordering_provider
   - Use ClinicalDateParser for report_date
   - Map status to FHIR DiagnosticReport status codes (preliminary, final, amended, corrected)
   - Maintain legacy fallback

**Testing Requirements:**
- **Pydantic Model Tests:** Validation, serialization, edge cases for each new model (≥95% coverage)
- **AI Extraction Tests:** Create 3-5 sample documents per resource type, verify LLM extracts with ≥85% recall and ≥0.7 confidence
- **Service Tests:** Structured input, minimal data, legacy fallback, error handling for each service (≥95% coverage)
- **End-to-End Tests:** Full pipeline from document → AI extraction → FHIR processing → ParsedData for all 3 new types
- **Regression Tests:** All existing tests pass, no impact on other resource extraction

**Acceptance Criteria:**
- 3 new Pydantic models exist, validate correctly, and are fully documented
- AI extraction system prompt includes comprehensive instructions for all 3 types
- AI successfully extracts all 3 types from test documents with ≥85% recall
- All 3 FHIR services process structured Pydantic models without data loss
- Legacy fields format still works for all 3 services
- Test coverage ≥95% on all new code
- Alignment progress: 8/12 → 11/12 resource types complete (counting VitalSign + LabResult separately)

### Phase 3 – Complete Resource Coverage (Weeks 5-6)

**Objective:** Create 3 final Pydantic models (AllergyIntolerance, CarePlan, Organization), create 3 corresponding FHIR services, update AI prompts, and achieve 12/12 complete alignment.

**Target Files:**
- Modify: `apps/documents/services/ai_extraction.py` (add 3 Pydantic models, update system prompt, update Structured MedicalExtraction)
- Create: `apps/fhir/services/allergy_intolerance_service.py` (~200 lines)
- Create: `apps/fhir/services/care_plan_service.py` (~220 lines)
- Create: `apps/fhir/services/organization_service.py` (~180 lines)
- Modify: `apps/fhir/services/fhir_processor.py` (wire 3 new services)

**Detailed Implementation Requirements:**

**PART A: AI Extraction Layer (final 3 Pydantic models)**

1. **Create AllergyIntolerance Pydantic Model** (apps/documents/services/ai_extraction.py, add after DiagnosticReport):
   ```python
   class AllergyIntolerance(BaseModel):
       allergy_id: Optional[str] = Field(default=None, description="Unique identifier")
       allergen: str = Field(description="Substance causing allergy (medication, food, environmental)")
       reaction: Optional[str] = Field(default=None, description="Type of reaction observed")
       severity: Optional[str] = Field(default=None, description="Severity: mild, moderate, severe, life-threatening")
       onset_date: Optional[str] = Field(default=None, description="Date allergy was first observed")
       status: Optional[str] = Field(default=None, description="Status: active, inactive, resolved")
       verification_status: Optional[str] = Field(default=None, description="Verification: confirmed, unconfirmed, refuted")
       source: SourceContext = Field(description="Source location in document")
       confidence: float = Field(ge=0.0, le=1.0, description="Extraction confidence 0-1")
   ```
   - Add validator for onset_date format
   - Add docstring with examples of allergy documentation

2. **Create CarePlan Pydantic Model** (apps/documents/services/ai_extraction.py, add after AllergyIntolerance):
   ```python
   class CarePlan(BaseModel):
       plan_id: Optional[str] = Field(default=None, description="Unique identifier")
       plan_description: str = Field(description="Overview of care plan or treatment plan")
       goals: List[str] = Field(default_factory=list, description="Care goals or treatment objectives")
       activities: List[str] = Field(default_factory=list, description="Planned activities or interventions")
       period_start: Optional[str] = Field(default=None, description="Care plan start date")
       period_end: Optional[str] = Field(default=None, description="Care plan end date")
       status: Optional[str] = Field(default=None, description="Status: draft, active, completed, cancelled")
       intent: Optional[str] = Field(default=None, description="Intent: proposal, plan, order")
       source: SourceContext = Field(description="Source location in document")
       confidence: float = Field(ge=0.0, le=1.0, description="Extraction confidence 0-1")
   ```
   - Add validators for period_start and period_end dates
   - Add docstring with examples of treatment plans and care coordination

3. **Create Organization Pydantic Model** (apps/documents/services/ai_extraction.py, add after CarePlan):
   ```python
   class Organization(BaseModel):
       organization_id: Optional[str] = Field(default=None, description="Unique identifier")
       name: str = Field(description="Organization or facility name")
       identifier: Optional[str] = Field(default=None, description="NPI, tax ID, or other identifier")
       organization_type: Optional[str] = Field(default=None, description="Type: hospital, clinic, lab, pharmacy, payer, etc.")
       address: Optional[str] = Field(default=None, description="Physical address")
       city: Optional[str] = Field(default=None, description="City")
       state: Optional[str] = Field(default=None, description="State or province")
       postal_code: Optional[str] = Field(default=None, description="ZIP or postal code")
       phone: Optional[str] = Field(default=None, description="Contact phone number")
       source: SourceContext = Field(description="Source location in document")
       confidence: float = Field(ge=0.0, le=1.0, description="Extraction confidence 0-1")
   ```
   - Add validator for phone number format (optional)
   - Add docstring with examples of healthcare facilities and organizations

4. **Update StructuredMedicalExtraction Schema** (apps/documents/services/ai_extraction.py):
   - Add three new fields:
   ```python
   allergies: List[AllergyIntolerance] = Field(
       default_factory=list,
       description="All documented allergies and intolerances"
   )
   care_plans: List[CarePlan] = Field(
       default_factory=list,
       description="All documented care plans and treatment plans"
   )
   organizations: List[Organization] = Field(
       default_factory=list,
       description="All healthcare organizations and facilities mentioned"
   )
   ```
   - Update confidence_average validator to include all 12 resource types

5. **Update AI Extraction System Prompt** (apps/documents/services/ai_extraction.py, ~lines 334-415):
   - Add comprehensive extraction instructions:
   ```
   10. **Allergies and Intolerances** - Extract ALL documented allergies:
       - Allergen substance (medication, food, environmental agent)
       - Type of reaction (rash, anaphylaxis, GI upset, etc.)
       - Severity (mild, moderate, severe, life-threatening)
       - Date first observed or documented
       - Current status (active, inactive, resolved)
       
   11. **Care Plans and Treatment Plans** - Extract documented plans:
       - Plan description or overview
       - Treatment goals and objectives
       - Planned activities and interventions
       - Plan timeline (start and end dates)
       - Plan status (draft, active, completed)
       
   12. **Organizations and Facilities** - Extract healthcare organizations:
       - Facility or organization names
       - Identifiers (NPI, tax ID)
       - Organization type (hospital, clinic, lab, pharmacy)
       - Address and contact information
   ```
   - Add medical terminology examples ("NKDA" = no known drug allergies, "treatment protocol", "referred to XYZ Hospital")

**PART B: FHIR Processing Layer (create 3 new services)**

6. **Create AllergyIntoleranceService** (apps/fhir/services/allergy_intolerance_service.py):
   - New service following established patterns
   - Implement `process_allergies(extracted_data: Dict)` main entry point
   - Implement `_create_allergy_from_structured(allergy_dict: Dict, patient_id: str)` for AllergyIntolerance Pydantic model
   - Extract: allergen, reaction, severity, onset_date, status, verification_status
   - Implement `_create_allergy_from_field(field: Dict, patient_id: str)` for legacy fallback
   - Use ClinicalDateParser for onset_date
   - Map severity to FHIR codes (mild, moderate, severe, unable-to-assess)
   - Map status to FHIR codes (active, inactive, resolved)
   - Return List[Dict[str, Any]] of FHIR AllergyIntolerance resources

7. **Create CarePlanService** (apps/fhir/services/care_plan_service.py):
   - New service following established patterns
   - Implement `process_care_plans(extracted_data: Dict)` main entry point
   - Implement `_create_care_plan_from_structured(plan_dict: Dict, patient_id: str)` for CarePlan Pydantic model
   - Extract: plan_description, goals list, activities list, period_start, period_end, status, intent
   - Use ClinicalDateParser for period_start and period_end
   - Map goals list to FHIR CarePlan.goal array
   - Map activities list to FHIR CarePlan.activity array
   - Implement legacy fallback
   - Return List[Dict[str, Any]] of FHIR CarePlan resources

8. **Create OrganizationService** (apps/fhir/services/organization_service.py):
   - New service following established patterns
   - Implement `process_organizations(extracted_data: Dict)` main entry point
   - Implement `_create_organization_from_structured(org_dict: Dict, patient_id: str)` for Organization Pydantic model
   - Extract: name, identifier, organization_type, address, city, state, postal_code, phone
   - Build FHIR Organization.address structure from individual fields
   - Build FHIR Organization.telecom array from phone
   - Map organization_type to FHIR Organization.type codes
   - Implement legacy fallback
   - Return List[Dict[str, Any]] of FHIR Organization resources

9. **Wire Services into FHIRProcessor** (apps/fhir/services/fhir_processor.py):
   - Import AllergyIntoleranceService, CarePlanService, OrganizationService
   - Instantiate all three in __init__(): 
     ```python
     self.allergy_service = AllergyIntoleranceService()
     self.care_plan_service = CarePlanService()
     self.organization_service = OrganizationService()
     ```
   - Implement `_process_allergies(extracted_data: Dict)` method
   - Implement `_process_care_plans(extracted_data: Dict)` method
   - Implement `_process_organizations(extracted_data: Dict)` method
   - Call all three from main `process_extracted_data()` pipeline
   - Update `get_supported_resource_types()` to return all 12 types
   - Update `validate_processing_capabilities()` to check all services

10. **Final FHIRMetricsService Validation** (apps/fhir/services/metrics_service.py):
    - Verify supported_resource_types matches FHIRProcessor (should now be 12 types)
    - Add validation that confirms all 12 types have corresponding services
    - Add logging if any type is advertised but missing from processor

**Testing Requirements:**
- **Pydantic Model Tests:** Validation, serialization, edge cases for each of 3 new models (≥95% coverage)
- **AI Extraction Tests:** Create 3-5 sample documents per resource type, verify LLM extracts with ≥85% recall and ≥0.7 confidence
- **Service Tests:** Full CRUD, date parsing, data mapping for each of 3 new services (≥95% coverage)
- **Integration Tests:** End-to-end pipeline for all 3 types
- **Metrics Tests:** Validate FHIRMetricsService reports 12/12 alignment
- **Full Regression Suite:** All Phase 1 and Phase 2 tests still pass

**Acceptance Criteria:**
- All 3 new Pydantic models exist, validate correctly, and are documented
- AI extraction prompt includes comprehensive instructions for all 3 types
- AI successfully extracts all 3 types from test documents with ≥85% recall
- All 3 new FHIR services process structured models without data loss
- Legacy fallback works for all 3 services
- FHIRProcessor processes all 12 resource types
- get_supported_resource_types() returns all 12 types
- FHIRMetricsService validates 12/12 alignment
- Test coverage ≥95% on all new code
- Zero regression in Phases 1 and 2
- **Complete alignment achieved: 11/12 → 12/12 resource types** ✅

### Phase 4 – Pipeline Finalization and Validation (Week 7)

**Objective:** Ensure structured path is primary throughout pipeline, add comprehensive logging for observability, validate complete 12/12 alignment, and update documentation.

**Target Files:**
- Modify: `apps/documents/tasks.py` (ensure structured data flows to FHIRProcessor)
- Modify: `apps/fhir/services/fhir_processor.py` (add structured-first logging)
- Modify: All service files (add fallback usage logging)
- Update: `docs/development/README.md` (document new pipeline architecture)
- Update: `docs/architecture/README.md` (update FHIR processing diagrams)

**Detailed Implementation Requirements:**

1. **Pipeline Configuration** (apps/documents/tasks.py, ~lines 620-680):
   - Ensure `process_document` task passes structured_extraction.model_dump() to FHIRProcessor
   - Verify processor_input includes both `structured_data` key (Pydantic models) and `fields` key (legacy fallback)
   - Add logging to indicate which format was provided to FHIRProcessor
   - Example structure:
     ```python
     processor_input = {
         'patient_id': str(patient.id),
         'structured_data': structured_extraction.model_dump(),  # Primary path
         'fields': ai_result.get('fields', [])  # Legacy fallback
     }
     fhir_resources = fhir_processor.process_extracted_data(processor_input)
     ```

2. **Enhanced Logging for Observability** (all service files):
   - Add info-level logging when structured path is used: `logger.info(f"Processing {resource_type} via structured path")`
   - Add warning-level logging when falling back to legacy: `logger.warning(f"Fallback to legacy fields for {resource_type}")`
   - Track and log structured vs. legacy usage statistics in FHIRProcessor
   - Add metrics to ParsedData model indicating path used for each resource type

3. **Comprehensive Validation Suite**:
   - Create validation script that processes 20-30 sample medical documents
   - Measure extraction recall and precision for all 12 resource types
   - Validate FHIRMetricsService reports 12/12 alignment
   - Confirm zero data loss compared to manual review baseline
   - Measure structured path usage rate (target: ≥95%)
   - Verify all legacy regression tests still pass

4. **Update Documentation** (docs/development/README.md):
   - Document new 12/12 aligned architecture
   - Explain structured-first, legacy-fallback pattern
   - Provide examples of adding new resource types
   - Document Pydantic model → FHIR service mapping
   - Add troubleshooting guide for data loss issues

5. **Update Architecture Documentation** (docs/architecture/README.md):
   - Update data flow diagrams showing structured path
   - Document all 12 resource types and their services
   - Explain review workflow and where data might be lost (spoiler: nowhere now!)
   - Add metrics and monitoring guidance

**Testing Requirements:**
- Validation suite processes ≥20 sample documents successfully
- All 12 resource types extracted and processed without loss
- Structured path used ≥95% of the time
- Legacy fallback works when structured data unavailable
- Full regression suite passes (Phases 1, 2, 3)
- Performance benchmarks show no significant slowdown

**Acceptance Criteria:**
- FHIRProcessor receives and prioritizes structured Pydantic data
- Comprehensive logging provides observability into path usage
- FHIRMetricsService validates 12/12 complete alignment
- Validation suite confirms 0% data loss on sample corpus
- Documentation fully updated with new architecture
- Structured path usage rate ≥95% in validation tests
- All regression tests pass
- **Project achieves complete 12/12 resource type alignment** 🎉

---

## 6. Technical Guidelines

- **Reuse Existing Models:** Extend the current `Procedure` and `Provider` Pydantic definitions only if additional fields are required. Do not fork the model hierarchy
    
- **Service Pattern:** Follow `ConditionService` structure but add explicit structured payload handling branches
    
- **Testing Framework:** Continue using `unittest.TestCase` for all new tests
    
- **Date Handling:** All date parsing must rely on `ClinicalDateParser` to maintain consistency
    
- **Backward Compatibility:** Any legacy `fields` behavior must remain covered by regression tests
    

---

## 7. Risks & Mitigations

|Risk|Mitigation|
|---|---|
|Divergence between metrics and implementation persists|`FHIRMetricsService` validation step fails CI if resource missing|
|Legacy clients rely on `fields` semantics|Maintain legacy code paths and add regression coverage|
|Performance impact from dual-path processing|Measure structured vs. legacy processing time; optimize hot spots|
|Model-field mismatch|Document mappings and review during code review|

---

## 8. Open Questions for Stakeholders

1. Should structured payload logging include PHI? (Impacts observability design.)
2. Are there regulatory constraints on promoting structured processing ahead of legacy for certain clients?
3. What is the acceptable threshold for legacy fallback usage before we consider it an incident?

---

## 9. Appendices

**Reference Services:**

- `apps/fhir/services/condition_service.py`
- `apps/fhir/services/medication_service.py`

**Metrics Module:**

- `apps/fhir/services/metrics_service.py`

**Processor:**

- `apps/fhir/processor.py`

**Structured Models:**

- `apps/documents/services/ai_extraction.py`