"""
Canonical static prompts for structured medical extraction.

This module is the single source of truth for the static (cacheable) portions
of the extraction prompt. The text returned here MUST be byte-identical across
all chunk calls within a document run — Anthropic prompt caching keys on the
exact byte prefix, so any per-call variation (context, chunk text, timestamps)
must live in the user message instead.

Layout:
- get_canonical_system_prompt(): comprehensive extraction instructions
  (base prompt from AIExtractionService plus the structured-output overlay,
  with previously duplicated rule blocks consolidated).
- SCHEMA_PROMPT: the exact JSON shape expected back, matching
  StructuredMedicalExtraction.
- get_context_instructions(): per-document-type guidance. Variable content —
  must be placed in the user message, never the system prompt.
"""

from functools import lru_cache
from typing import Optional


# Overlay of structured-output requirements that are NOT already covered by the
# comprehensive base prompt in AIExtractionService. Duplicated blocks (strict
# clinical assertion rules, date granularity, SIG capture, code capture,
# organization noise filtering) were removed — they already appear verbatim in
# the base prompt and were costing ~4-5K duplicate tokens per call.
STRUCTURED_OUTPUT_OVERLAY = """
CRITICAL REQUIREMENTS FOR STRUCTURED OUTPUT:
1. Extract EVERY piece of medical information mentioned
2. Provide source context for each extracted item (use exact text snippets)
3. Assign accurate confidence scores based on clarity and certainty
4. Use proper medical terminology and classifications
5. Include dates, values, and units exactly as written
6. **EXTRACT ALL DATES**: Look for dates near each medical finding and extract them aggressively

CONFIDENCE SCORING:
- 0.9-1.0: Information explicitly and clearly stated
- 0.7-0.9: Information clearly implied from document context
- 0.5-0.7: Information mentioned but with some ambiguity
- 0.3-0.5: Information suggested but unclear
- 0.1-0.3: Information possibly mentioned but very unclear

ENCOUNTER EXTRACTION:
Extract ALL encounter/visit information:
- encounter_type: Type of visit (office visit, emergency, ER visit, telehealth, virtual visit, inpatient, hospital admission, outpatient, etc.)
- encounter_date: Start date/time of encounter
- encounter_end_date: End date/time if applicable (discharge date for admissions)
- location: Facility or clinic name
- reason: Chief complaint or reason for visit
- participants: ALL provider names involved (attending, consultants, specialists, nurses)
- status: If mentioned (planned, arrived, in-progress, finished, cancelled)
Examples: "Patient seen in ER on 10/20/24", "Office visit with Dr. Smith 09/15/24", "Admitted 08/01 discharged 08/05"

SERVICE REQUEST EXTRACTION:
Extract ALL orders, referrals, and requests:
- request_type: Type (lab test, imaging study, specialist referral, consultation, procedure order)
- requester: Ordering provider name
- reason: Clinical indication or reason for request
- priority: Priority level if mentioned (routine, urgent, stat, asap)
- clinical_context: Additional context
- request_date: Date order was placed
Examples: "Referred to cardiology", "Order chest X-ray stat", "Labs ordered: CBC, CMP", "MRI brain with contrast"

DIAGNOSTIC REPORT EXTRACTION:
Extract ALL test results and diagnostic findings:
- report_type: Type of report (lab, radiology, pathology, cardiology, pulmonary, etc.)
- findings: Key findings and results (REQUIRED - capture ALL results)
- conclusion: Diagnostic conclusion or impression
- recommendations: Recommended follow-up or actions
- status: Report status if mentioned (preliminary, final, amended, corrected)
- report_date: Date report was generated
- ordering_provider: Provider who ordered the test
Examples: "CT scan shows...", "Lab results: Glucose 105", "Echo report: EF 55%", "Path report: benign tissue"

ALLERGY/INTOLERANCE EXTRACTION:
Extract ALL documented allergies:
- allergen: Substance causing allergy (medication, food, environmental agent)
- reaction: Type of reaction (rash, anaphylaxis, GI upset, swelling, etc.)
- severity: Severity level (mild, moderate, severe, life-threatening)
- onset_date: Date allergy first observed or documented
- status: Current status (active, inactive, resolved)
- verification_status: Verification level (confirmed, unconfirmed, refuted)
Examples: "NKDA", "Penicillin allergy - anaphylaxis", "Allergic to shellfish", "Latex sensitivity"

CARE PLAN EXTRACTION:
Extract documented treatment plans:
- plan_description: Overview of care plan or treatment plan (REQUIRED)
- goals: List of care goals and objectives
- activities: List of planned activities and interventions
- period_start: Care plan start date
- period_end: Care plan end date
- status: Plan status (draft, active, completed, cancelled)
- intent: Intent (proposal, plan, order)
Examples: "Diabetes management plan", "Post-op care protocol", "CHF treatment plan"

ORGANIZATION EXTRACTION:
Extract healthcare organizations and facilities:
- name: Organization or facility name (REQUIRED)
- identifier: NPI, tax ID, or other identifier
- organization_type: Type (hospital, clinic, lab, pharmacy, payer, etc.)
- address: Physical address
- city, state, postal_code: Location details
- phone: Contact phone number
Examples: "General Hospital", "Community Clinic", "Regional Lab Services", "Springfield Medical Center"

CRITICAL for ALL extractions:
- Look for "allergy to", "allergic to", "NKDA" -> AllergyIntolerance
- Look for "care plan", "treatment plan", "protocol", "goals:" -> CarePlan
- Look for "Hospital", "Clinic", "Medical Center", "Lab" -> Organization
- Look for "referred to", "order for", "consult with" -> ServiceRequest
- Look for "ER visit", "admitted to", "seen in clinic" -> Encounter
- Look for "report shows", "results:", "findings:", "impression:" -> DiagnosticReport"""


# Exact JSON shape expected back from the model. Field names must match
# StructuredMedicalExtraction in ai_extraction.py exactly.
SCHEMA_PROMPT = """
Return valid JSON that exactly matches this schema structure.
CRITICAL: Use EXACT field names as shown - do not abbreviate or rename fields!

{
  "conditions": [
    {
      "name": "condition name",
      "status": "active",
      "evidence_type": "explicit_diagnosis",
      "confidence": 0.9,
      "onset_date": null,
      "date_precision": null,
      "icd_code": null,
      "snomed_code": null,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "medications": [
    {
      "name": "medication name",
      "generic_name": null,
      "brand_name": null,
      "dosage": "strength only e.g. 0.4 mg",
      "dosage_form": null,
      "quantity": null,
      "route": null,
      "frequency": "frequency",
      "sig": "complete verbatim instruction text",
      "refills": null,
      "prescriber": null,
      "status": "active",
      "confidence": 0.9,
      "start_date": null,
      "stop_date": null,
      "date_precision": null,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "vital_signs": [
    {
      "measurement": "vital sign type",
      "value": "measurement value",
      "unit": "unit",
      "category": "vital-signs",
      "components": [],
      "timestamp": null,
      "date_precision": null,
      "confidence": 0.9,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    },
    {
      "measurement": "Blood Pressure",
      "value": "120/80",
      "unit": "mmHg",
      "category": "vital-signs",
      "components": [
        {"measurement": "Systolic", "value": "120", "unit": "mmHg"},
        {"measurement": "Diastolic", "value": "80", "unit": "mmHg"}
      ],
      "timestamp": null,
      "date_precision": null,
      "confidence": 0.95,
      "source": {"text": "BP 120/80 mmHg", "start_index": 0, "end_index": 14}
    }
  ],
  "lab_results": [
    {
      "test_name": "lab test name",
      "value": "test value",
      "unit": "unit",
      "reference_range": null,
      "abnormal_flag": null,
      "category": "laboratory",
      "panel_name": null,
      "status": "final",
      "test_date": null,
      "date_precision": null,
      "confidence": 0.9,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "procedures": [
    {
      "name": "procedure name",
      "cpt_code": null,
      "procedure_date": null,
      "provider": null,
      "outcome": null,
      "date_precision": null,
      "confidence": 0.9,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "immunizations": [
    {
      "vaccine_name": "Influenza",
      "cvx_code": null,
      "date_administered": null,
      "date_precision": null,
      "lot_number": null,
      "manufacturer": null,
      "dose_number": null,
      "route": null,
      "site": null,
      "status": "completed",
      "is_forecast": false,
      "confidence": 0.9,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "providers": [
    {
      "name": "provider name",
      "specialty": null,
      "role": null,
      "contact_info": null,
      "confidence": 0.9,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "encounters": [
    {
      "encounter_id": null,
      "encounter_type": "office visit",
      "encounter_date": null,
      "encounter_end_date": null,
      "location": null,
      "reason": null,
      "participants": [],
      "status": null,
      "confidence": 0.9,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "service_requests": [
    {
      "request_id": null,
      "request_type": "lab test",
      "requester": null,
      "reason": null,
      "priority": null,
      "clinical_context": null,
      "request_date": null,
      "forecast_due_date": null,
      "confidence": 0.9,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "diagnostic_reports": [
    {
      "report_id": null,
      "report_type": "lab",
      "findings": "key findings",
      "conclusion": null,
      "recommendations": null,
      "status": null,
      "report_date": null,
      "ordering_provider": null,
      "confidence": 0.9,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "allergies": [
    {
      "allergy_id": null,
      "allergen": "substance name",
      "reaction": null,
      "severity": null,
      "onset_date": null,
      "status": null,
      "verification_status": null,
      "confidence": 0.9,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "care_plans": [
    {
      "plan_id": null,
      "plan_description": "care plan overview",
      "goals": [],
      "activities": [],
      "period_start": null,
      "period_end": null,
      "status": null,
      "intent": null,
      "confidence": 0.9,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "organizations": [
    {
      "organization_id": null,
      "name": "organization name",
      "role_in_document": "care_site",
      "identifier": null,
      "organization_type": null,
      "address": null,
      "city": null,
      "state": null,
      "postal_code": null,
      "phone": null,
      "confidence": 0.9,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "family_history": [
    {
      "relationship": "mother",
      "condition": "breast cancer",
      "onset_age": null,
      "deceased": false,
      "confidence": 0.9,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "physical_exam_findings": [
    {
      "body_site": "cardiovascular",
      "finding": "Regular rate and rhythm",
      "status": "normal",
      "confidence": 0.85,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "social_history": [
    {
      "category": "tobacco",
      "description": "Former smoker, quit 2015",
      "confidence": 0.9,
      "source": {"text": "exact text from document", "start_index": 0, "end_index": 10}
    }
  ],
  "clinical_date": null,
  "clinical_date_source": null,
  "extraction_timestamp": "",
  "document_type": "",
  "confidence_average": null
}

CRITICAL FIELD NAME REQUIREMENTS:
- encounters: Use "encounter_type" NOT "type"
- service_requests: Use "request_type" NOT "service" or "type"
- diagnostic_reports: Use "report_type" NOT "type"
- vital_signs: Use "measurement" NOT "type"
- Every extracted item MUST include a "source" object with exact text snippet
- date_precision MUST be null or one of: "year", "month", "day" — NEVER pad partial dates into full YYYY-MM-DD
- conditions: set "evidence_type" to explicit_diagnosis/problem_list/assessment/history. NEVER invent diagnoses from labs/vitals/BMI. If a condition is not explicitly stated by a provider, do NOT extract it.
- medications: capture the COMPLETE instruction in "sig"; keep "dosage" as strength only. Do NOT truncate the SIG. Merge brand+generic into one entry.
- lab_results: include "reference_range" and "abnormal_flag" when shown; set "category" and "panel_name" when identifiable.
- vital_signs: for blood pressure, populate "components" with systolic and diastolic entries.
- immunizations: extract vaccines into "immunizations" (NOT "procedures"); include "cvx_code" when shown, capture "lot_number"/"dose_number" when present, and set "is_forecast": true for recommended/due vaccines that were NOT administered.
- organizations: set "role_in_document"; mark fax headers / routing / boilerplate as "fax_header" or "admin".
- clinical_date: the document's primary service/visit/collection date (NOT print/fax date)
- Use exact field names as shown above - do not abbreviate or substitute"""


@lru_cache(maxsize=1)
def get_canonical_system_prompt() -> str:
    """
    Build the canonical static system prompt: comprehensive base prompt plus
    the structured-output overlay.

    Memoized so every call returns the identical string object — required for
    Anthropic prompt-cache prefix matching across chunk calls.
    """
    from apps.documents.services.ai_extraction_service import AIExtractionService

    base_prompt = AIExtractionService()._get_comprehensive_extraction_prompt()
    return f"{base_prompt}\n{STRUCTURED_OUTPUT_OVERLAY}"


def get_context_instructions(context: Optional[str]) -> str:
    """
    Return context-specific guidance for the user message.

    Variable content — must NOT be embedded in the system prompt or it
    invalidates the prompt cache prefix.
    """
    if not context:
        return ""

    from apps.documents.services.ai_extraction_service import AIExtractionService

    instructions = AIExtractionService()._get_context_specific_instructions(context)
    if instructions:
        return f"\n\nContext-Specific Instructions:\n{instructions}"
    return ""
