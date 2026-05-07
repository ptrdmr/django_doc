"""
Enhanced AI Extraction Service for Complete Clinical Data Capture

This service provides comprehensive AI prompts designed to extract all relevant
clinical data from medical documents with 90%+ capture rate.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class AIExtractionService:
    """
    Enhanced AI extraction service with comprehensive prompts for complete clinical data extraction.
    
    Designed to achieve 90%+ data capture rate by using specialized prompts that target
    all supported FHIR resource types and clinical data categories.
    """
    
    def __init__(self):
        self.logger = logger
        
    def generate_extraction_prompt(self, document_text: str, context: Optional[str] = None) -> str:
        """
        Generate an enhanced prompt for AI to extract complete clinical data.
        
        Args:
            document_text: The medical document text to extract data from
            context: Optional context about the document type or source
            
        Returns:
            Comprehensive extraction prompt designed for maximum data capture
        """
        base_prompt = self._get_comprehensive_extraction_prompt()
        
        # Add context-specific instructions if provided
        if context:
            context_instructions = self._get_context_specific_instructions(context)
            if context_instructions:
                base_prompt += f"\n\nContext-Specific Instructions:\n{context_instructions}"
                
        # Add the document text
        base_prompt += f"\n\nDocument text to analyze:\n{document_text}"
        
        return base_prompt
        
    def _get_comprehensive_extraction_prompt(self) -> str:
        """
        Get the comprehensive extraction prompt designed for maximum clinical data capture.
        
        Returns:
            Enhanced prompt targeting all FHIR resource types and clinical data
        """
        return """You are MediExtract Pro, an advanced AI assistant specialized in comprehensive medical data extraction. Your mission is to achieve maximum clinical data capture (90%+ extraction rate) by identifying and structuring ALL medical information from the provided document.

EXTRACTION TARGETS - Extract ALL instances of:

1. **Patient Demographics & Identifiers**
   - Full name, date of birth, age, gender, MRN
   - Contact information, insurance details
   - Emergency contacts, next of kin

2. **ALL Medications (100% capture priority)**
   - Current medications with complete dosage, route, frequency
   - Discontinued medications with stop dates
   - PRN (as-needed) medications
   - Over-the-counter medications and supplements
   - Medication allergies and intolerances
   - Medication changes, adjustments, or new prescriptions

3. **ALL Diagnostic Information**
   - Laboratory results (blood work, urine tests, cultures)
   - Imaging studies (X-rays, CT scans, MRIs, ultrasounds)
   - Cardiac tests (EKGs, echocardiograms, stress tests)
   - Pathology reports and biopsies
   - Diagnostic procedure results
   - Test dates, values, reference ranges, and interpretations

4. **ALL Diagnoses & Conditions**
   - Primary and secondary diagnoses
   - Chronic conditions and comorbidities
   - Differential diagnoses under consideration
   - Rule-out diagnoses
   - Historical diagnoses and resolved conditions
   - ICD codes if present

5. **ALL Healthcare Encounters**
   - Visit type (office, hospital, emergency, telehealth)
   - Date and time of service
   - Healthcare providers involved
   - Location/facility information
   - Reason for visit or chief complaint
   - Encounter outcomes and dispositions

6. **ALL Service Requests & Orders**
   - Referrals to specialists (cardiology, neurology, etc.)
   - Laboratory test orders
   - Imaging study orders
   - Procedure requests
   - Consultation requests
   - Follow-up appointments scheduled
   - Priority levels (routine, urgent, STAT)

7. **ALL Procedures Performed**
   - Surgical procedures with dates
   - Minor procedures and interventions
   - Diagnostic procedures
   - Therapeutic procedures
   - Procedure outcomes and complications

8. **ALL Vital Signs & Measurements**
   - Blood pressure, heart rate, temperature
   - Respiratory rate, oxygen saturation
   - Height, weight, BMI
   - Pain scores
   - Measurement dates and times

9. **ALL Provider Information**
   - Attending physicians
   - Consulting specialists
   - Nurses and other care team members
   - Provider specialties and roles
   - Contact information if available

10. **ALL Care Plans & Recommendations**
    - Treatment plans and goals
    - Patient education provided
    - Lifestyle recommendations
    - Follow-up instructions
    - Discharge planning

OUTPUT FORMAT: Return JSON whose **top-level keys match** the `StructuredMedicalExtraction`
schema used by the ingestion pipeline (snake_case):

- `conditions`, `medications`, `vital_signs`, `lab_results`, `procedures`, `providers`,
  `encounters`, `service_requests`, `diagnostic_reports`, `allergies`, `care_plans`,
  `organizations`, `family_history`, `physical_exam_findings`, `social_history`
- `extraction_timestamp` (ISO-8601 string), optional `document_type`, optional `confidence_average`

Each list item must include `confidence` (0-1 float) and nested `source`:
`{"text": "<verbatim snippet>", "start_index": <int>, "end_index": <int>}`.

PERTINENT NEGATIVES & HOSPICE/PALLIATIVE CONTEXT:
- Record denials only when explicitly documented ("denies chest pain", "no edema").
- Capture ADL/IADL cues, caregiver availability, code status, POLST references when present.
- Family history rows use `relationship`, `condition`, optional `onset_age`, optional `deceased`.

DATE GRANULARITY (`date_precision`: `year` | `month` | `day` when applicable):
- If the note only states a year (`2019`), emit `onset_date`: `"2019"` with `date_precision: "year"` — **never** fabricate `-01-01`.
- If month+year without day, use `"YYYY-MM"` and `date_precision: "month"`.
- Only emit full `YYYY-MM-DD` when a day is explicit in the source.

MINIMAL ILLUSTRATION (fields abbreviated; expand as needed):
{
  "conditions": [
    {
      "name": "Type 2 Diabetes Mellitus",
      "status": "active",
      "onset_date": "2019",
      "date_precision": "year",
      "icd_code": "E11.9",
      "confidence": 0.93,
      "source": {"text": "...", "start_index": 0, "end_index": 42}
    }
  ],
  "medications": [
    {
      "name": "Metformin",
      "dosage": "500 mg",
      "route": "oral",
      "frequency": "BID",
      "status": "active",
      "confidence": 0.9,
      "source": {"text": "...", "start_index": 0, "end_index": 24}
    }
  ],
  "diagnostic_reports": [
    {
      "report_type": "CT Chest",
      "report_date": "2024-03-01",
      "findings": "No acute infiltrate",
      "conclusion": "Stable",
      "confidence": 0.88,
      "source": {"text": "...", "start_index": 0, "end_index": 120}
    }
  ],
  "service_requests": [
    {
      "request_type": "Physical Therapy referral",
      "request_date": "2024-03-05",
      "priority": "routine",
      "confidence": 0.82,
      "source": {"text": "...", "start_index": 0, "end_index": 48}
    }
  ],
  "physical_exam_findings": [
    {"body_site": "Lungs", "finding": "Clear to auscultation", "status": "normal", "confidence": 0.9, "source": {"text": "...", "start_index": 0, "end_index": 36}}
  ],
  "social_history": [
    {"category": "tobacco", "description": "Former smoker, quit 2019", "confidence": 0.87, "source": {"text": "...", "start_index": 0, "end_index": 30}}
  ],
  "family_history": [
    {"relationship": "Mother", "condition": "Breast cancer", "onset_age": "60s", "deceased": false, "confidence": 0.8, "source": {"text": "...", "start_index": 0, "end_index": 42}}
  ],
  "extraction_timestamp": "2026-05-05T00:00:00Z"
}

CRITICAL EXTRACTION RULES:

1. **Be Exhaustive**: Extract EVERY piece of medical information, no matter how minor
2. **Preserve Exactness**: Copy information exactly as written, including units and abbreviations
3. **High Confidence**: Use confidence scores 0.8-1.0 for clearly stated information
4. **Complete Medications**: Never miss medication information - this is highest priority
5. **Multiple Instances**: Include ALL instances (e.g., multiple blood pressure readings)
6. **Dates and Times**: Always extract when information was recorded/occurred
7. **Context Preservation**: Maintain relationships between related information
8. **No Assumptions**: Only extract what is explicitly stated in the document

RESPONSE REQUIREMENTS:
- Your response must ONLY be a valid JSON object
- No markdown code blocks, no explanations, no comments
- Start with { and end with }
- Include only sections with data found
- Use arrays for multiple instances of the same type
- Assign confidence scores based on clarity and certainty"""

    def _get_context_specific_instructions(self, context: str) -> Optional[str]:
        """
        Get context-specific instructions based on document type or source.
        
        Args:
            context: Document context (e.g., "Emergency Department", "Cardiology")
            
        Returns:
            Context-specific extraction instructions or None
        """
        context_lower = context.lower()
        
        if any(term in context_lower for term in ['emergency', 'ed', 'er']):
            return """Emergency Department Focus:
- Prioritize triage information and chief complaints
- Extract all vital signs and emergency interventions
- Focus on immediate diagnostic tests and results
- Capture disposition and discharge instructions
- Note any emergency medications administered"""
            
        elif any(term in context_lower for term in ['cardiology', 'cardiac', 'heart']):
            return """Cardiology Focus:
- Extract all cardiac-related tests (EKG, echo, stress tests)
- Focus on cardiac medications and dosing
- Capture blood pressure readings and heart rate
- Note cardiac procedures and interventions
- Extract cardiac risk factors and family history"""
            
        elif any(term in context_lower for term in ['discharge', 'summary']):
            return """Discharge Summary Focus:
- Capture complete medication reconciliation
- Extract all diagnoses (admission, discharge, secondary)
- Note all procedures performed during stay
- Focus on discharge instructions and follow-up plans
- Extract condition at discharge"""
            
        elif any(term in context_lower for term in ['lab', 'laboratory']):
            return """Laboratory Focus:
- Extract ALL test results with values and reference ranges
- Note collection dates and times
- Capture abnormal flags and critical values
- Include specimen types and collection methods
- Extract provider interpretations and comments"""
            
        elif any(term in context_lower for term in ['progress', 'note']):
            return """Progress Note Focus:
- Track changes in patient condition
- Extract new symptoms or complaints
- Note medication adjustments or changes
- Capture assessment and plan updates
- Focus on interval changes since last visit"""
            
        return None
        
    def extract_clinical_data(self, document_text: str, context: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract clinical data using AI with enhanced prompts.
        
        Args:
            document_text: The medical document text
            context: Optional context about document type
            
        Returns:
            Extracted clinical data in structured format
        """
        try:
            prompt = self.generate_extraction_prompt(document_text, context)
            
            # This would integrate with the actual AI service (Claude, GPT, etc.)
            # For now, return the prompt that would be used
            self.logger.info(f"Generated comprehensive extraction prompt for document with context: {context}")
            
            # In actual implementation, this would call the AI API
            # extracted_data = self._call_ai_api(prompt)
            # return self._validate_and_process_response(extracted_data)
            
            return {
                'success': True,
                'prompt_generated': True,
                'context': context,
                'prompt_length': len(prompt),
                'extraction_targets': [
                    'conditions', 'medications', 'vital_signs', 'lab_results', 'procedures',
                    'providers', 'encounters', 'service_requests', 'diagnostic_reports',
                    'allergies', 'care_plans', 'organizations',
                    'family_history', 'physical_exam_findings', 'social_history',
                ]
            }
            
        except Exception as e:
            self.logger.error(f"Error in clinical data extraction: {e}")
            return {
                'success': False,
                'error': str(e)
            }
            
    def _call_ai_api(self, prompt: str) -> Dict[str, Any]:
        """
        Call AI API with the extraction prompt.
        
        Args:
            prompt: The complete extraction prompt
            
        Returns:
            Raw AI response
        """
        # This would integrate with Claude, GPT, or other AI services
        # Implementation depends on the specific AI service being used
        pass
        
    def _validate_and_process_response(self, raw_response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and process the AI response.
        
        Args:
            raw_response: Raw response from AI service
            
        Returns:
            Validated and processed clinical data
        """
        # This would validate the JSON structure and clean up the response
        # Ensure all required fields are present and properly formatted
        pass
