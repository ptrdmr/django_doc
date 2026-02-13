# FHIR Converter Alignment Issues — Agent Work Order

## Background

The document processing pipeline has **two parallel FHIR conversion paths**:

1. **Primary (Structured)**: `StructuredDataConverter` in `apps/fhir/converters.py` — handles Pydantic `StructuredMedicalExtraction` from AI extraction
2. **Fallback (Legacy)**: `FHIRProcessor` in `apps/fhir/services/fhir_processor.py` — routes through 11 individual service classes in `apps/fhir/services/`

The structured converter was built early (Task 34, Sept 2025) as a quick bridge with its own internal conversion methods for only 6 of 12 resource types. Later, Task 40 (Oct 2025) upgraded all 11 service classes to support dual-format input (structured Pydantic dicts + legacy fields) and achieved 12/12 resource alignment in `FHIRProcessor`.

A commit (`a2e14c6`, 2025-10-29) wired the structured converter to delegate to `FHIRProcessor`, but a subsequent checkpoint commit (`1bce819`, 2025-11-16) **reverted that fix** due to a return-type incompatibility: `FHIRProcessor` returns plain dicts, but `StructuredDataConverter` callers expect `fhir.resources` objects. The revert was bundled with AI prompt improvements and described as "FHIR converter enhancements," masking the regression.

The result: the primary pipeline still uses the converter's homebrew methods, bypassing all the service-layer intelligence built in Task 40.

---

## Issues To Fix (ordered by severity)

### CRITICAL-1: Vital signs get fabricated codes, invisible to reports

**Files involved:**
- `apps/fhir/converters.py` — `StructuredDataConverter._create_vital_sign_observation()` (line ~1117)
- `apps/fhir/services/observation_service.py` — `ObservationService.VITAL_LOINC_MAPPING` (line ~27-39)
- `apps/reports/utils/anthropometric_utils.py` — `WEIGHT_LOINC_CODES` (line ~16-19)

**Problem:** The structured converter generates codes like `VITAL-WEIGHT` instead of real LOINC code `29463-7`. The report utilities (`anthropometric_utils`, `lab_utils`) filter by real LOINC codes, so all vital signs created through the structured path are invisible to reports, BMI calculations, and weight trend analysis.

**What correct behavior looks like:** The `ObservationService` already has the correct mapping:
```python
VITAL_LOINC_MAPPING = {
    "blood pressure": "85354-9",
    "systolic": "8480-6",
    "diastolic": "8462-4",
    "heart rate": "8867-4",
    "pulse": "8867-4",
    "temperature": "8310-5",
    "respiratory rate": "9279-1",
    "oxygen saturation": "59408-5",
    "height": "8302-2",
    "weight": "29463-7",
    "bmi": "39156-5"
}
```

### CRITICAL-2: Lab results get fabricated hash-based codes

**Files involved:**
- `apps/fhir/converters.py` — `StructuredDataConverter._create_lab_observation()` (line ~1153)
- `apps/reports/utils/lab_utils.py` — `LOINC_CATEGORIES` dict and `extract_observation_data()` (lines ~17-84, ~193-288)

**Problem:** Lab results get codes like `LAB-04821` (a hash of the test name). While these technically pass the `http://loinc.org` system check, they don't match any entry in `LOINC_CATEGORIES`, so all labs fall into the "Other" category and lose their clinical categorization (Hematology, Chemistry, Lipid Panel, etc.).

**What correct behavior looks like:** The `ObservationService._create_observation_from_structured()` attempts LOINC lookup via `VITAL_LOINC_MAPPING`. For labs, a similar lookup using known LOINC codes from `lab_utils.LOINC_CATEGORIES` would be ideal. At minimum, the service classes' existing logic should be used instead of the hash-based approach.

### CRITICAL-3: Six resource types silently dropped by structured converter

**Files involved:**
- `apps/fhir/converters.py` — `StructuredDataConverter._convert_structured_to_dict()` (line ~934-1042)
- `apps/documents/services/ai_extraction.py` — `StructuredMedicalExtraction` (line ~292-361)
- `apps/fhir/services/fhir_processor.py` — `FHIRProcessor` processes all 12 types

**Problem:** `_convert_structured_to_dict()` only converts: `conditions`, `medications`, `vital_signs`, `lab_results`, `procedures`, `providers`. These 6 Pydantic types are extracted by AI but silently discarded:
- `encounters` (Encounter)
- `service_requests` (ServiceRequest)
- `diagnostic_reports` (DiagnosticReport)
- `allergies` (AllergyIntolerance)
- `care_plans` (CarePlan)
- `organizations` (Organization)

**What correct behavior looks like:** `FHIRProcessor` already processes all 12 types through dedicated services:
- `apps/fhir/services/encounter_service.py`
- `apps/fhir/services/service_request_service.py`
- `apps/fhir/services/diagnostic_report_service.py`
- `apps/fhir/services/allergy_intolerance_service.py`
- `apps/fhir/services/care_plan_service.py`
- `apps/fhir/services/organization_service.py`

### HIGH-1: Legacy compatibility function has AttributeError on `measurement_type`

**Files involved:**
- `apps/documents/services/ai_extraction.py` — `extract_medical_data()` (line ~1148)

**Problem:** The legacy wrapper references `vital.measurement_type` but the `VitalSign` Pydantic model's field is named `measurement`. This causes an `AttributeError` at runtime whenever the legacy function is called with vital sign data present.

**Fix:** Change `vital.measurement_type` to `vital.measurement` on line 1148.

### HIGH-2: Condition codes use free-text names as ICD-10 codes

**Files involved:**
- `apps/fhir/converters.py` — `_create_condition_from_structured()` (line ~1053)
- `apps/fhir/fhir_models.py` — `ConditionResource.create_from_diagnosis()` (line ~342-347)

**Problem:** When `icd_code` is None (which is common — the AI often doesn't extract coded values), the condition's free-text `name` (e.g., "Type 2 Diabetes Mellitus") is used as the `condition_code` and stored with system `http://hl7.org/fhir/sid/icd-10`. This is an invalid FHIR coding and pollutes the `searchable_medical_codes` index.

**Fix:** When no ICD code is available, either: (a) use `code.text` instead of `code.coding` for the display name, or (b) use a separate code system like `http://terminology.hl7.org/CodeSystem/data-absent-reason` to indicate the code is text-based.

### MEDIUM-1: Vital sign values stored as `valueString` instead of `valueQuantity`

**Files involved:**
- `apps/fhir/converters.py` — `_create_vital_sign_observation()` passes string value
- `apps/fhir/fhir_models.py` — `ObservationResource.create_from_lab_result()` (line ~462-471)
- `apps/reports/utils/anthropometric_utils.py` — reads `valueQuantity.value` (line ~204-206)

**Problem:** `VitalSign.value` is always a string (Pydantic model defines `value: str`). `create_from_lab_result()` checks `isinstance(value, (int, float))` — since it's a string, it stores as `valueString`. The retrieval layer reads `valueQuantity`, so numeric vital signs are invisible even if LOINC codes were correct.

**What correct behavior looks like:** The `ObservationService._create_observation_from_structured()` (line ~209-224) already does `float(value.replace(',', '').strip())` to attempt numeric parsing. This pattern should be used.

### MEDIUM-2: Lab result `reference_range` not passed to FHIR resource

**Files involved:**
- `apps/fhir/converters.py` — `_create_lab_observation()` (line ~1151-1158)

**Problem:** `lab_data["reference_range"]` is available from the Pydantic extraction but is never passed to `ObservationResource.create_from_lab_result()`. The method accepts a `reference_range` parameter but the converter doesn't send it.

**Fix:** Add `reference_range=lab_data.get("reference_range")` to the `create_from_lab_result()` call. Note: `create_from_lab_result` currently doesn't use this parameter either — that would also need adding to the method body.

### MEDIUM-3: Medication frequency duplicated in dosage text and timing

**Files involved:**
- `apps/fhir/converters.py` — `_create_medication_from_structured()` (line ~1070-1086)
- `apps/fhir/fhir_models.py` — `MedicationStatementResource.create_from_medication()` (line ~576-632)

**Problem:** The converter concatenates frequency into `dosage_text` AND passes `frequency` separately. Inside `create_from_medication()`, `frequency` is parsed into `dosage[0].timing.repeat` while `dosage_text` (which already contains the frequency string) goes into `dosage[0].text`. This creates redundant data.

**Fix:** Either pass frequency only via the `frequency` parameter (not in dosage text), or don't pass it separately.

### MEDIUM-4: Procedure status hardcoded to "completed"

**Files involved:**
- `apps/fhir/converters.py` — `_create_procedure_resource_structured()` (line ~1195)

**Problem:** All procedures are stored as `status="completed"` regardless of actual status. The code even has a comment: `# Could map from procedure_data.get('status')`.

**Fix:** The Pydantic `Procedure` model doesn't have a status field, but procedures extracted from clinical notes may be planned or in-progress. Consider defaulting to "completed" but allowing override from the extraction data.

### LOW-1: Item count logging excludes 6 resource types

**Files involved:**
- `apps/fhir/converters.py` — `convert_structured_data()` (line ~652-655)

**Problem:** The `total_items` calculation only counts the original 6 types, understating extraction volume and masking data loss from CRITICAL-3.

---

## Recommended Fix Strategy

### Previous attempt (reverted)
Commit `a2e14c6` tried to have `StructuredDataConverter.convert_structured_data()` call `FHIRProcessor().process_extracted_data()` directly, then convert the returned dicts back to `fhir.resources` objects. This failed because the dict-to-object conversion was fragile — FHIR resource Pydantic validators rejected some dict patterns produced by the services.

### Recommended approach
Have `StructuredDataConverter` delegate to individual service classes directly, keeping the return type as dicts (since `Patient.add_fhir_resources()` accepts dicts anyway). This avoids both:
- The dict-to-object conversion problem that caused the revert
- The need to re-implement LOINC mapping, numeric parsing, and resource type coverage in the converter

**Concrete steps:**

1. **In `StructuredDataConverter.convert_structured_data()`**: Replace the `_convert_structured_to_dict()` + `self.convert()` chain with direct calls to each service's `process_*()` method, passing the Pydantic data as `structured_data` dict format that the dual-format services already accept.

2. **Return dicts instead of `fhir.resources` objects**: Check what the callers of `convert_structured_data()` actually need. In `apps/documents/tasks.py`, the returned resources go into `Patient.add_fhir_resources()` which accepts dicts. If any caller truly needs `fhir.resources` objects, add conversion at that boundary only.

3. **Fix the `measurement_type` AttributeError** in `apps/documents/services/ai_extraction.py` line 1148: change `vital.measurement_type` to `vital.measurement`.

4. **Fix condition code handling**: When `icd_code` is None, don't put free text into `code.coding` with ICD-10 system. Use `code.text` instead.

5. **Pass `reference_range`** through to lab observations.

6. **Fix medication frequency duplication**: Don't concatenate frequency into dosage_text if also passing it as separate parameter.

### Key files to modify
- `apps/fhir/converters.py` — Primary target: `StructuredDataConverter` class
- `apps/documents/services/ai_extraction.py` — Fix `measurement_type` bug (line 1148)
- `apps/fhir/fhir_models.py` — Fix condition code handling in `ConditionResource.create_from_diagnosis()`

### Key files for reference (working correctly, use as patterns)
- `apps/fhir/services/observation_service.py` — Correct LOINC mapping and numeric parsing
- `apps/fhir/services/fhir_processor.py` — Correct routing to all 12 services
- `apps/fhir/services/condition_service.py` — Correct dual-format condition handling
- `apps/fhir/services/medication_service.py` — Correct dual-format medication handling
- `apps/reports/utils/anthropometric_utils.py` — Documents what the retrieval layer expects
- `apps/reports/utils/lab_utils.py` — Documents what lab retrieval expects

### Key files for context (how data flows end-to-end)
- `apps/documents/tasks.py` — `process_document_task()` calls the converter, stores results via `Patient.add_fhir_resources()`
- `apps/patients/models.py` — `Patient.add_fhir_resources()` stores dicts in `encrypted_fhir_bundle`; `extract_searchable_metadata()` indexes resources
- `apps/documents/services/ai_extraction.py` — All 12 Pydantic models and the `StructuredMedicalExtraction` container

### Tests to verify the fix
- Vital signs created via structured path must have real LOINC codes (e.g., weight → `29463-7`)
- Vital sign numeric values must be stored as `valueQuantity`, not `valueString`
- All 12 resource types from `StructuredMedicalExtraction` must produce FHIR resources
- `anthropometric_utils.extract_weight_observations()` must find weight observations created via structured path
- `lab_utils.group_lab_results()` must correctly categorize labs created via structured path
- Legacy `extract_medical_data()` must not crash with `AttributeError` on vital signs
- Conditions without ICD codes must not have free text stored as ICD-10 coded values
