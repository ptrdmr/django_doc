# De-Identification Engine - PRD

> **Purpose:** Implement the core HIPAA Safe Harbor de-identification logic that strips Protected Health Information from structured medical extractions before FHIR conversion.

---

## Parent Context

Part of the **De-Identification + FHIR Conversion Platform** initiative. See [deidentification-fhir-platform-prd.md](../deidentification-fhir-platform-prd.md) for overall vision.

Depends on **Sub-PRD 01: Foundation & Infrastructure** for the ProcessingJob and configuration models.

---

## Overview

The de-identification engine operates on `StructuredMedicalExtraction` -- the Pydantic model output from the AI extraction step. Because the LLM has already parsed the document into typed fields (names, dates, addresses, clinical findings, etc.), de-identification becomes a deterministic, field-level operation on known data types rather than an NLP problem on raw text.

The engine implements the HIPAA Safe Harbor method, which requires removal or generalization of 18 specific identifier types. It supports configurable profiles so customers can choose the level of de-identification (full Safe Harbor, date-shift only, custom).

### Problem Statement

- The existing pipeline extracts structured medical data including PHI (provider names, dates, locations, contact info, identifiers)
- No mechanism exists to strip PHI before output
- Free-text fields (diagnostic findings, care plan descriptions, source snippets) may contain embedded PHI beyond what structured extraction captures
- Different customers need different de-identification levels (full Safe Harbor for researchers, partial for internal analytics)

### Solution

A new `apps/deidentify/` app that:

- Maps all 18 HIPAA Safe Harbor identifiers to specific fields in the `StructuredMedicalExtraction` model
- Applies configurable strategies (redact, replace with category tag, date-shift, generalize) to each identifier type
- Performs a secondary sweep on free-text fields to catch residual PHI
- Validates the de-identified output for PHI leakage before returning it
- Logs what was de-identified (counts and types, not original values) for audit purposes

---

## Design Decisions

**1. De-identify structured data, not raw text**

The AI extraction step has already identified what is a name, what is a date, what is an address, etc. De-identifying the structured `StructuredMedicalExtraction` is more reliable than running NER on raw text because the data types are known. The raw document text is never included in Mode B output.

**2. De-identify before FHIR conversion, not after**

Operating on the Pydantic model (pre-FHIR) means we have a single, well-typed data structure to process. If we de-identified after FHIR conversion, we'd need to handle 11 different FHIR resource schemas. Pre-FHIR de-ID is simpler and less error-prone.

**3. Date shifting preserves clinical utility**

Dates are shifted by a random offset (consistent per job) rather than removed. This preserves the temporal relationships between clinical events (e.g., "medication started 3 days after diagnosis") which is valuable for researchers. The shift range is configurable (default: +/- 365 days).

**4. Category tags over synthetic data by default**

Default replacement strategy uses category tags like `[PROVIDER_NAME]`, `[ORGANIZATION]`, `[ADDRESS]` rather than synthetic names (e.g., "Jane Smith"). Rationale: category tags make it obvious that de-identification occurred, reducing the risk of someone mistaking de-identified data for real data. Synthetic replacement is available as an alternative profile option.

**5. Source context snippets require special handling**

Every extracted item has a `SourceContext.text` field containing the exact snippet from the document where the data was found. These snippets frequently contain PHI that isn't in the structured fields (e.g., the snippet for a medication might include "prescribed by Dr. Johnson on 3/15/2024"). All source context text must be either stripped entirely or have PHI redacted within it.

---

## HIPAA Safe Harbor: 18 Identifier Mapping

The following table maps each of the 18 HIPAA Safe Harbor identifiers to where they appear in the `StructuredMedicalExtraction` Pydantic models and the default de-identification strategy.

### Identifiers Found in Structured Fields

| # | Identifier | Extraction Fields | Default Strategy |
|---|-----------|-------------------|------------------|
| 1 | **Names** | `Provider.name`, `Encounter.participants[]`, `ServiceRequest.requester`, `DiagnosticReport.ordering_provider`, `Procedure.provider` | Replace with category tag `[PROVIDER_NAME_1]`, `[PROVIDER_NAME_2]`, etc. (numbered for cross-reference consistency) |
| 2 | **Geographic data** (below state level) | `Organization.address`, `Organization.city`, `Organization.postal_code`, `Encounter.location` | Address/city: replace with `[LOCATION]`. Postal code: truncate to first 3 digits (Safe Harbor allows 3-digit zip if population > 20,000; otherwise replace entirely). State: keep as-is (permitted). |
| 3 | **Dates** (except year) | `MedicalCondition.onset_date`, `Medication.start_date`, `Medication.stop_date`, `VitalSign.timestamp`, `LabResult.test_date`, `Procedure.procedure_date`, `Encounter.encounter_date`, `Encounter.encounter_end_date`, `ServiceRequest.request_date`, `DiagnosticReport.report_date`, `AllergyIntolerance.onset_date`, `CarePlan.period_start`, `CarePlan.period_end`, `StructuredMedicalExtraction.extraction_timestamp` | Date-shift by consistent random offset per job. Year preserved for ages ≤89; for ages >89, generalize to "90+". |
| 4 | **Phone numbers** | `Organization.phone`, `Provider.contact_info` (if phone) | Remove entirely |
| 5 | **Fax numbers** | `Provider.contact_info` (if fax), `SourceContext.text` | Remove entirely |
| 6 | **Email addresses** | `Provider.contact_info` (if email), `SourceContext.text` | Remove entirely |
| 7 | **SSN** | Not in structured extraction models; may appear in `SourceContext.text` | Remove entirely (regex sweep) |
| 8 | **MRN** | `Encounter.encounter_id`, `Organization.identifier` | Replace with synthetic UUID |
| 9 | **Health plan beneficiary numbers** | Not in structured extraction models; may appear in `SourceContext.text` | Remove entirely (regex sweep) |
| 10 | **Account numbers** | Not in structured extraction models; may appear in `SourceContext.text` | Remove entirely (regex sweep) |
| 11 | **Certificate/license numbers** | `Organization.identifier`, `Provider.contact_info` | Remove entirely |
| 12 | **Vehicle identifiers** | Not expected in clinical documents; may appear in `SourceContext.text` | Remove if detected (regex sweep) |
| 13 | **Device identifiers** | May appear in `Procedure` context or `SourceContext.text` | Remove if detected |
| 14 | **Web URLs** | `SourceContext.text`, `Provider.contact_info` | Remove entirely (regex sweep) |
| 15 | **IP addresses** | Not expected in clinical documents | Remove if detected (regex sweep) |
| 16 | **Biometric identifiers** | Not applicable (text-based extraction) | N/A |
| 17 | **Full-face photographs** | Not applicable (text-based extraction) | N/A |
| 18 | **Any other unique identifier** | `Organization.identifier`, any `*_id` fields | Replace with synthetic UUID |

### Identifiers in Free-Text Fields (Secondary Sweep)

These fields contain narrative text that may embed any identifier type:

| Field | Model | Handling |
|-------|-------|----------|
| `SourceContext.text` | All 13 extraction models | Strip entirely from output by default. Optional: regex-based redaction if source snippets are desired in output. |
| `DiagnosticReport.findings` | DiagnosticReport | Regex sweep for names, dates, SSNs, phone numbers, addresses |
| `DiagnosticReport.conclusion` | DiagnosticReport | Same sweep |
| `DiagnosticReport.recommendations` | DiagnosticReport | Same sweep |
| `CarePlan.plan_description` | CarePlan | Same sweep |
| `CarePlan.goals[]` | CarePlan | Same sweep |
| `CarePlan.activities[]` | CarePlan | Same sweep |
| `Encounter.reason` | Encounter | Same sweep |
| `ServiceRequest.reason` | ServiceRequest | Same sweep |
| `ServiceRequest.clinical_context` | ServiceRequest | Same sweep |

---

## Technical Scope

### New App: `apps/deidentify/`

```
apps/deidentify/
├── __init__.py
├── apps.py              (name = 'apps.deidentify')
├── engine.py            (DeidentificationEngine - main orchestrator)
├── safe_harbor.py       (SafeHarborRules - 18 identifier handlers)
├── strategies.py        (RedactStrategy, DateShiftStrategy, etc.)
├── profiles.py          (Profile configurations)
├── validators.py        (PHILeakageValidator - post-de-ID verification)
├── text_scrubber.py     (Regex-based PHI scrubbing for free-text fields)
├── models.py            (DeidentificationProfile, DeidentificationLog)
├── admin.py             (Admin registration)
├── constants.py         (Regex patterns, zip code population data, etc.)
└── migrations/
```

### Core Classes

**`DeidentificationEngine`** (`engine.py`)

The main orchestrator. Takes a `StructuredMedicalExtraction` and a profile name, returns a de-identified copy.

```python
class DeidentificationEngine:
    def deidentify(
        self,
        extraction: StructuredMedicalExtraction,
        profile: str = "safe_harbor",
        job_id: Optional[str] = None
    ) -> DeidentificationResult:
        """
        De-identify a structured medical extraction.

        Args:
            extraction: The AI-extracted structured data
            profile: De-identification profile name
            job_id: Used to generate consistent date shift offset

        Returns:
            DeidentificationResult containing:
                - deidentified_extraction: Modified StructuredMedicalExtraction
                - summary: Dict of what was changed (counts by type)
                - validation_result: PHI leakage check result
        """
```

**`SafeHarborRules`** (`safe_harbor.py`)

Maps each of the 18 identifier types to handler functions. Each handler knows which fields to process and which strategy to apply.

```python
class SafeHarborRules:
    def __init__(self, profile: DeidentificationProfile):
        self.profile = profile
        self.handlers = self._build_handler_map()

    def apply(
        self,
        extraction: StructuredMedicalExtraction,
        date_shift_days: int
    ) -> Tuple[StructuredMedicalExtraction, Dict[str, int]]:
        """
        Apply all Safe Harbor rules to the extraction.
        Returns (modified_extraction, change_counts).
        """
```

**Strategies** (`strategies.py`)

Each strategy is a callable that transforms a field value:

| Strategy | Input | Output | Use Case |
|----------|-------|--------|----------|
| `RedactStrategy` | Any value | `None` or `""` | Phone, fax, email, SSN |
| `CategoryTagStrategy` | A name string | `[PROVIDER_NAME_1]` | Provider names, organization names |
| `DateShiftStrategy` | ISO date string | Shifted date string | All clinical dates |
| `GeneralizeStrategy` | Full value | Generalized value | Zip codes (→ 3-digit), ages >89 (→ "90+") |
| `SyntheticReplaceStrategy` | A name/address | Faker-generated value | Optional profile for realistic-looking output |
| `UUIDReplaceStrategy` | An identifier | Random UUID | MRNs, encounter IDs, other unique IDs |

```python
class DateShiftStrategy:
    def __init__(self, shift_days: int):
        self.shift_days = shift_days

    def apply(self, date_string: str) -> Optional[str]:
        """Shift a date by the configured offset, preserving format."""
```

**`TextScrubber`** (`text_scrubber.py`)

Regex-based PHI scrubber for free-text fields. Used as a secondary sweep after structured field de-identification.

```python
class TextScrubber:
    def scrub(self, text: str, known_names: List[str] = None) -> str:
        """
        Remove PHI patterns from free text.

        Detects and redacts:
        - SSN patterns (XXX-XX-XXXX)
        - Phone patterns (various formats)
        - Email addresses
        - Common date formats
        - Known names (from structured extraction)
        - URLs
        - IP addresses
        """
```

The `known_names` parameter receives provider names, organization names, and location names extracted in the structured step, so the scrubber can look for those specific strings in free text.

**`PHILeakageValidator`** (`validators.py`)

Post-de-identification check that scans the entire de-identified output for residual PHI patterns.

```python
class PHILeakageValidator:
    def validate(
        self,
        deidentified: StructuredMedicalExtraction,
        original_phi: Dict[str, List[str]]
    ) -> ValidationResult:
        """
        Check de-identified output for PHI leakage.

        Args:
            deidentified: The de-identified extraction
            original_phi: Dict mapping PHI type to original values
                          (e.g., {"names": ["Dr. Smith"], "phones": ["555-1234"]})

        Returns:
            ValidationResult with:
                - is_clean: bool
                - leaks_found: List of leak descriptions (no PHI values, just types and locations)
                - confidence_score: 0.0-1.0
        """
```

### De-Identification Profiles

**Database model** (`models.py`):

| Field | Type | Notes |
|-------|------|-------|
| id | AutoField (PK) | |
| name | CharField(50, unique) | e.g., `safe_harbor`, `dates_only`, `minimal` |
| display_name | CharField(100) | Human-readable name |
| description | TextField | What this profile does |
| rules | JSONField | Configuration for each identifier type |
| strip_source_context | BooleanField(default=True) | Whether to remove SourceContext.text |
| is_active | BooleanField(default=True) | |
| is_system | BooleanField(default=True) | System profiles cannot be deleted |
| created_at | DateTimeField | Auto |

**Default profiles (seeded via data migration):**

| Profile | Description | Behavior |
|---------|-------------|----------|
| `safe_harbor` | Full HIPAA Safe Harbor compliance | All 18 identifiers handled. Dates shifted. Names tagged. Source context stripped. |
| `safe_harbor_synthetic` | Safe Harbor with synthetic replacements | Same as above but names replaced with Faker-generated names instead of category tags |
| `dates_only` | Shift dates, keep other identifiers | Only dates are modified. Names, addresses, etc. kept. NOT Safe Harbor compliant -- for internal use only. |
| `minimal` | Remove only direct identifiers | SSN, phone, email, fax removed. Names and dates kept. NOT Safe Harbor compliant. |

**Audit model** (`models.py`):

| Field | Type | Notes |
|-------|------|-------|
| id | UUIDField (PK) | |
| job | ForeignKey(ProcessingJob) | Link to processing job |
| profile_used | CharField(50) | Which profile was applied |
| identifiers_processed | JSONField | Counts per identifier type, e.g., `{"names": 5, "dates": 12, "phones": 2}` |
| source_contexts_stripped | IntegerField | How many source context snippets were removed |
| free_text_scrubs | IntegerField | How many free-text fields were scrubbed |
| validation_passed | BooleanField | Whether PHI leakage validator passed |
| validation_confidence | FloatField | Confidence score from validator |
| leaks_found | IntegerField(default=0) | Number of potential leaks detected |
| processing_time_ms | IntegerField | Time spent on de-identification |
| created_at | DateTimeField | Auto |

---

## Implementation Checklist

1. Create `apps/deidentify/` app with all module files
2. Implement `DateShiftStrategy` with consistent per-job offset generation (seeded by job_id)
3. Implement `RedactStrategy`, `CategoryTagStrategy`, `UUIDReplaceStrategy`, `GeneralizeStrategy`
4. Implement `SyntheticReplaceStrategy` using Faker library for name/address generation
5. Implement `SafeHarborRules` with the full 18-identifier mapping table
6. Implement `TextScrubber` with regex patterns for SSN, phone, email, date, URL, IP
7. Implement `DeidentificationEngine` orchestrator that chains: structured de-ID → text scrubbing → validation
8. Implement `PHILeakageValidator` that checks output against known original PHI values
9. Define `DeidentificationProfile` and `DeidentificationLog` models
10. Create data migration to seed default profiles (safe_harbor, safe_harbor_synthetic, dates_only, minimal)
11. Register models in Django admin
12. Add `apps.deidentify` to `INSTALLED_APPS`
13. Write unit tests for each strategy with edge cases (empty dates, malformed SSNs, international phone formats)
14. Write integration test: full `StructuredMedicalExtraction` → de-identify → validate → verify no PHI in output

---

## Risks and Mitigations

**Risk 1: PHI in free-text fields is missed by regex**

Medical narratives can contain PHI in unexpected formats ("the patient's mother, Susan Martinez, reports..."). Regex patterns won't catch all variations.

**Mitigation:** Strip `SourceContext.text` entirely by default (safest). For narrative fields like `DiagnosticReport.findings`, combine regex with known-name matching (names from structured extraction are used as search terms). Validator catches remaining leaks. Document that narrative fields may require manual review for highest-assurance use cases.

**Risk 2: Date shifting breaks clinical meaning for edge cases**

Shifting dates near year boundaries could change the year (Dec 31 + 30 days = Jan 30 next year). For age-based conditions, the shifted dates might imply a different age.

**Mitigation:** Shift all dates by the same offset within a job, preserving intervals. Document that year values in shifted dates may not match the original year. For age >89 cases, replace with "90+" per Safe Harbor rules regardless of shift.

**Risk 3: Zip code population check is complex**

Safe Harbor allows 3-digit zip codes only if the geographic unit has a population > 20,000. The full list of restricted 3-digit zips is published by HHS.

**Mitigation:** Embed the HHS restricted zip code list (currently ~17 three-digit prefixes) as a constant. Zip codes with restricted prefixes are replaced entirely with `[ZIP_REDACTED]` instead of truncated.

**Risk 4: Faker-generated synthetic data could collide with real data**

If synthetic names happen to match real patient names, the output might be mistakenly treated as containing real PHI.

**Mitigation:** Synthetic replacement is an optional profile, not the default. Default uses category tags which are clearly not real data. Document the risk in profile descriptions.

---

## Existing Code References

**Pydantic extraction models (the input to de-identification):**
- `apps/documents/services/ai_extraction.py` -- Lines 128-348
- `StructuredMedicalExtraction` (line 292) is the root model containing all 13 extraction types
- Each sub-model has typed fields that map directly to Safe Harbor identifiers

**FHIR converters (consume de-identified output):**
- `apps/fhir/converters.py` -- `StructuredDataConverter.convert_structured_data()` (line 591)
- The converter reads the same Pydantic model fields that de-identification modifies
- No changes needed to converters -- they receive de-identified data transparently

**Audit logging pattern:**
- `apps/core/models.py` -- `AuditLog` model for event tracking pattern
- `apps/documents/models.py` -- `audit_extraction_decision()` for PHI-safe audit logging pattern

---

## TaskMaster Integration

**Workflow:** Parse this PRD as 1 task, then expand into subtasks.

**Step 1 -- Parse (1 task):**
```bash
task-master parse-prd .taskmaster/docs/deid-platform/02-deidentification-engine-prd.md --tag=deid-platform --num-tasks=1 --append
```

**Step 2 -- Expand into subtasks:**
```bash
task-master expand --id=2 --tag=deid-platform --num=12
```

**Expected subtasks:** ~12 (app scaffolding, each strategy class, Safe Harbor rules, text scrubber, validator, engine orchestrator, models, migrations, seed data, tests)
