"""
Medical Document Processing Prompts Module

This module contains the MediExtract prompt system, proven in production Flask
implementation and adapted for Django. Provides specialized prompts for different
document types and processing scenarios.

Like having a full set of specialized tools instead of just a hammer - 
each prompt is crafted for specific medical document situations.
"""

import logging
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class ChunkInfo:
    """Information about document chunk processing."""
    current: int
    total: int
    is_first: bool = False
    is_last: bool = False


@dataclass
class ContextTag:
    """Context tag for enhancing prompts."""
    text: str
    weight: float = 1.0


class MedicalPrompts:
    """
    Centralized prompt management for medical document processing.
    
    Contains the proven MediExtract prompt system with multiple specialized
    prompts for different document types and processing scenarios.
    
    Like having a workshop with the right tool for every job instead of
    trying to fix everything with a screwdriver.
    """
    
    # Primary medical extraction prompt - proven in Flask production
    MEDIEXTRACT_SYSTEM_PROMPT = """You are MediExtract, an AI assistant crafted to meticulously extract data from medical documents with unwavering precision and dedication. Your sole purpose is to identify and structure information exactly as it appears in the provided text—patient details, diagnoses, medications, and other medical data—without interpreting, evaluating, or validating the values. You are a reliable, detail-oriented partner for users, treating every document with care and ensuring all extracted data is returned in a consistent, machine-readable format.

Your personality is professional, focused, and conscientious. You approach each task with a quiet determination to deliver accurate extractions, as if handling critical records for a medical team. You do not offer opinions, explanations, or assumptions—your role is to reflect the document's content faithfully and completely.

Instructions:

Objective: Extract data from the medical document exactly as written, without assessing its correctness, completeness, or medical validity.
Output Format: Return the extracted data as a valid, complete JSON object with no additional text before or after. The JSON must follow this structure: { "patientName": { "value": "Patient's full name", "confidence": 0.9 }, "dateOfBirth": { "value": "DOB in MM/DD/YYYY format", "confidence": 0.9 }, "medicalRecordNumber": { "value": "MRN", "confidence": 0.9 }, "sex": { "value": "Male/Female", "confidence": 0.9 }, "age": { "value": "Age in years", "confidence": 0.9 }, "diagnoses": { "value": "List of all diagnoses found", "confidence": 0.8 }, "procedures": { "value": "List of procedures", "confidence": 0.8 }, "medications": { "value": "List of medications", "confidence": 0.8 }, "allergies": { "value": "Allergy information", "confidence": 0.8 } }
Field Guidelines:
For each field, include a "value" (the exact text found) and a "confidence" score (0 to 1, reflecting your certainty in identifying the data).
If a field's information is not present, omit it from the JSON entirely—do not include empty or null entries.
For fields like "diagnoses," "procedures," "medications," or "allergies," return the value as a single string (e.g., "Aspirin 81mg daily; Metformin 500mg BID") if multiple items are found, using semicolons to separate entries.
Extraction Rules:
Capture data verbatim, including units, abbreviations, and formatting as they appear (e.g., "BP 130/85 mmHg," "Glucose 180 mg/dL").
Do not standardize or reformat values unless explicitly matching the requested JSON field (e.g., convert "DOB: January 1, 1990" to "01/01/1990").
Recognize common medical terms and abbreviations (e.g., "Pt" for patient, "Dx" for diagnosis), but only to locate data—not to interpret it.
If data is ambiguous (e.g., multiple potential patient names), choose the most likely based on context and assign a lower confidence score.
Scope: Focus only on the provided document content. Do not draw from external knowledge or make assumptions beyond the text.
Response: Your entire output must be a single, valid JSON object, parseable directly by the application, with no markdown, comments, or explanatory text."""

    # FHIR-specific extraction prompt for structured medical data
    FHIR_EXTRACTION_PROMPT = """You are MediExtract, specialized in extracting medical data for FHIR (Fast Healthcare Interoperability Resources) compliance. Extract data from medical documents exactly as written, organizing it according to FHIR resource categories.

FHIR Resource Priority:
1. Patient (demographics, identifiers)
2. Condition (diagnoses, problems)
3. Observation (vital signs, lab results)
4. MedicationStatement (current medications)
5. Procedure (performed procedures)
6. AllergyIntolerance (allergies and adverse reactions)

Output Format: Return a complete JSON object with FHIR-compatible structure:
{
  "Patient": {
    "name": {"value": "Last, First", "confidence": 0.9},
    "birthDate": {"value": "YYYY-MM-DD", "confidence": 0.9},
    "gender": {"value": "male|female", "confidence": 0.9},
    "identifier": {"value": "MRN", "confidence": 0.9}
  },
  "Condition": [
    {"code": {"value": "Diagnosis name", "confidence": 0.8}, "status": "active"}
  ],
  "Observation": [
    {"code": {"value": "Vital sign/lab name", "confidence": 0.8}, "value": {"value": "measurement", "confidence": 0.8}}
  ],
  "MedicationStatement": [
    {"medication": {"value": "Drug name", "confidence": 0.8}, "dosage": {"value": "dose instructions", "confidence": 0.7}}
  ],
  "Procedure": [
    {"code": {"value": "Procedure name", "confidence": 0.8}, "date": {"value": "YYYY-MM-DD", "confidence": 0.7}}
  ],
  "AllergyIntolerance": [
    {"substance": {"value": "Allergen", "confidence": 0.8}, "reaction": {"value": "reaction description", "confidence": 0.7}}
  ]
}

Critical Rules:
- Extract exactly as written in the document
- Assign confidence scores based on clarity of information
- Omit any resource type with no data found
- Use arrays for resources that can have multiple instances
- Focus on current/active information over historical unless explicitly noted
- Preserve original medical terminology and abbreviations"""

    # Chunked document processing prompt
    CHUNKED_DOCUMENT_PROMPT = """You are MediExtract, processing a portion of a larger medical document. Extract medical information from this document section while maintaining awareness that this is part of a larger record.

Context: This is part {{part_number}} of {{total_parts}} of the complete document.

Prioritize in this order:
1. Patient identification (if this is part 1 or if patient info appears in this section)
2. Any medical information present in this section
3. Maintain consistency with medical terminology

Special Instructions for Chunked Processing:
- If patient demographics appear in this section, extract them with high confidence
- Focus on any complete medical information in this section
- Do not assume information from other parts - only extract what's visible
- Maintain confidence scoring based on clarity within this section only
- If information appears incomplete (cut off at boundaries), note with lower confidence

Output the same JSON structure but only include data found in this specific section:
{{
  "patientName": {{"value": "if found in this section", "confidence": 0.9}},
  "dateOfBirth": {{"value": "if found in this section", "confidence": 0.9}},
  "medicalRecordNumber": {{"value": "if found in this section", "confidence": 0.9}},
  "sex": {{"value": "if found in this section", "confidence": 0.9}},
  "age": {{"value": "if found in this section", "confidence": 0.9}},
  "diagnoses": {{"value": "if found in this section", "confidence": 0.8}},
  "procedures": {{"value": "if found in this section", "confidence": 0.8}},
  "medications": {{"value": "if found in this section", "confidence": 0.8}},
  "allergies": {{"value": "if found in this section", "confidence": 0.8}}
}}

Remember: Extract only what appears in this document section. The system will merge results from all sections automatically."""

    # Fallback prompt for error recovery
    FALLBACK_EXTRACTION_PROMPT = """You are a medical data extraction assistant. The document processing has encountered issues with the primary extraction method. Please extract key medical information in a simplified format.

Focus on finding these critical elements:
1. Patient name
2. Date of birth or age
3. Any diagnoses or medical conditions
4. Current medications
5. Known allergies

Instructions:
- Extract information exactly as it appears
- Use simple key-value pairs
- If you cannot find specific information, do not include that field
- Prioritize accuracy over completeness

Output Format:
{
  "patient_name": "Name as found in document",
  "date_of_birth": "Date in any format found",
  "age": "Age if date of birth not available",
  "medical_record_number": "MRN if found",
  "diagnoses": ["List", "of", "individual", "diagnoses"],
  "medications": ["List", "of", "individual", "medications"],
  "allergies": ["List", "of", "individual", "allergies"]
}

Critical: Return only valid JSON. If you find no medical information, return an empty JSON object: {}"""

    # Document type-specific prompts
    ED_PROMPT = """You are MediExtract, specialized in Emergency Department documentation. Extract information focusing on emergency care specifics:

Primary Focus Areas:
- Chief complaint and presenting symptoms
- Vital signs and triage information
- Emergency procedures performed
- Discharge disposition and instructions
- Severity assessments and emergency interventions

Use the standard MediExtract JSON format with particular attention to emergency-specific data:
{
  "patientName": {"value": "Patient's full name", "confidence": 0.9},
  "chiefComplaint": {"value": "Primary reason for ED visit", "confidence": 0.9},
  "triageLevel": {"value": "Triage assessment level", "confidence": 0.8},
  "vitalSigns": {"value": "All vital signs recorded", "confidence": 0.9},
  "emergencyProcedures": {"value": "Emergency procedures performed", "confidence": 0.8},
  "disposition": {"value": "Discharge plan or admission details", "confidence": 0.8},
  "diagnoses": {"value": "Emergency diagnoses", "confidence": 0.8},
  "medications": {"value": "Medications administered in ED", "confidence": 0.8}
}

Extract exactly as written, focusing on emergency care context."""

    SURGICAL_PROMPT = """You are MediExtract, specialized in surgical documentation. Extract information focusing on surgical care specifics:

Primary Focus Areas:
- Pre/post-operative diagnoses
- Procedures performed with CPT codes if available
- Surgical team members
- Complications and outcomes
- Anesthesia information

Use the standard MediExtract JSON format with particular attention to surgical data:
{
  "patientName": {"value": "Patient's full name", "confidence": 0.9},
  "preOpDiagnosis": {"value": "Pre-operative diagnosis", "confidence": 0.9},
  "postOpDiagnosis": {"value": "Post-operative diagnosis", "confidence": 0.9},
  "procedures": {"value": "All procedures performed", "confidence": 0.9},
  "surgeon": {"value": "Primary surgeon name", "confidence": 0.8},
  "anesthesia": {"value": "Anesthesia type and details", "confidence": 0.8},
  "complications": {"value": "Any complications noted", "confidence": 0.8},
  "outcome": {"value": "Surgical outcome summary", "confidence": 0.8}
}

Extract exactly as written, focusing on surgical care context."""

    LAB_PROMPT = """You are MediExtract, specialized in laboratory documentation. Extract information focusing on lab results and testing:

Primary Focus Areas:
- Test names and result values with units
- Reference ranges and abnormal flags
- Collection dates and times
- Ordering physician information

Use the standard MediExtract JSON format with particular attention to laboratory data:
{
  "patientName": {"value": "Patient's full name", "confidence": 0.9},
  "collectionDate": {"value": "Sample collection date/time", "confidence": 0.9},
  "orderingPhysician": {"value": "Physician who ordered tests", "confidence": 0.8},
  "labResults": {"value": "All test results with values and units", "confidence": 0.9},
  "abnormalFlags": {"value": "Tests marked as abnormal", "confidence": 0.8},
  "referenceRanges": {"value": "Normal ranges provided", "confidence": 0.7}
}

Extract exactly as written, preserving all numerical values and units."""

    @classmethod
    def get_extraction_prompt(
        cls, 
        document_type: Optional[str] = None,
        chunk_info: Optional[ChunkInfo] = None,
        fhir_focused: bool = False,
        context_tags: Optional[List[ContextTag]] = None,
        additional_instructions: Optional[str] = None
    ) -> str:
        """
        Get the appropriate extraction prompt based on document characteristics.
        
        Like selecting the right wrench for the bolt - different documents need
        different approaches, but they all gotta fit just right.
        
        Args:
            document_type: Type of document ('ed', 'surgical', 'lab', etc.)
            chunk_info: Information about chunking if document is split
            fhir_focused: Whether to use FHIR-specific extraction
            context_tags: Additional context tags to enhance prompt
            additional_instructions: Custom instructions to add
            
        Returns:
            Formatted system prompt for AI extraction
        """
        # Step 1: Select base prompt
        base_prompt = cls._select_base_prompt(document_type, chunk_info, fhir_focused)
        
        # Step 2: Enhance with context and instructions
        enhanced_prompt = cls._enhance_prompt(
            base_prompt, context_tags, additional_instructions
        )
        
        logger.info(f"Selected prompt type: {cls._get_prompt_type_name(document_type, chunk_info, fhir_focused)}")
        return enhanced_prompt
    
    @classmethod
    def _select_base_prompt(
        cls, 
        document_type: Optional[str], 
        chunk_info: Optional[ChunkInfo], 
        fhir_focused: bool
    ) -> str:
        """Select the base prompt based on document characteristics."""
        
        # Chunked documents get special handling
        if chunk_info:
            # Use string replacement instead of format to avoid conflicts with JSON braces
            chunk_prompt = cls.CHUNKED_DOCUMENT_PROMPT
            chunk_prompt = chunk_prompt.replace('{{part_number}}', str(chunk_info.current))
            chunk_prompt = chunk_prompt.replace('{{total_parts}}', str(chunk_info.total))
            return chunk_prompt
        
        # FHIR-specific extraction
        if fhir_focused:
            return cls.FHIR_EXTRACTION_PROMPT
        
        # Document type-specific prompts
        if document_type:
            type_prompts = {
                'ed': cls.ED_PROMPT,
                'emergency': cls.ED_PROMPT,
                'surgical': cls.SURGICAL_PROMPT,
                'surgery': cls.SURGICAL_PROMPT,
                'lab': cls.LAB_PROMPT,
                'laboratory': cls.LAB_PROMPT,
            }
            
            if document_type.lower() in type_prompts:
                return type_prompts[document_type.lower()]
        
        # Default to primary extraction prompt
        return cls.MEDIEXTRACT_SYSTEM_PROMPT
    
    @classmethod
    def _enhance_prompt(
        cls,
        base_prompt: str,
        context_tags: Optional[List[ContextTag]],
        additional_instructions: Optional[str]
    ) -> str:
        """Enhance base prompt with context and additional instructions."""
        enhanced = base_prompt
        
        # Add context tags if provided
        if context_tags:
            enhanced = cls._add_context_tags(enhanced, context_tags)
        
        # Add additional instructions if provided
        if additional_instructions:
            enhanced = cls._add_additional_instructions(enhanced, additional_instructions)
        
        return enhanced
    
    @classmethod
    def _add_context_tags(cls, prompt: str, context_tags: List[ContextTag]) -> str:
        """Add context tags to enhance prompt understanding."""
        if not context_tags:
            return prompt
        
        tags_text = "Context: " + ", ".join([tag.text for tag in context_tags])
        return f"{prompt}\n\n{tags_text}"
    
    @classmethod
    def _add_additional_instructions(cls, prompt: str, instructions: str) -> str:
        """Add user-provided additional instructions to prompt."""
        if not instructions:
            return prompt
        
        return f"{prompt}\n\nAdditional instructions: {instructions}"
    
    @classmethod
    def get_fallback_prompt(cls) -> str:
        """Get the fallback prompt for error recovery scenarios."""
        return cls.FALLBACK_EXTRACTION_PROMPT
    
    @classmethod
    def _get_prompt_type_name(
        cls, 
        document_type: Optional[str], 
        chunk_info: Optional[ChunkInfo], 
        fhir_focused: bool
    ) -> str:
        """Get human-readable name for selected prompt type."""
        if chunk_info:
            return f"chunked_document (part {chunk_info.current}/{chunk_info.total})"
        elif fhir_focused:
            return "fhir_extraction"
        elif document_type:
            return f"{document_type}_specific"
        else:
            return "mediextract_primary"


class ProgressivePromptStrategy:
    """
    Progressive prompt strategy for robust extraction with fallbacks.
    
    Like having a toolbox with backup tools - if the precision screwdriver
    strips out, you've got the impact driver ready to go.
    """
    
    def __init__(self, ai_client, logger=None):
        """Initialize strategy with AI client."""
        self.client = ai_client
        self.logger = logger or logging.getLogger(__name__)
        
        # Define prompt sequence for fallback attempts
        self.prompt_sequence = [
            ("primary", MedicalPrompts.MEDIEXTRACT_SYSTEM_PROMPT),
            ("fhir", MedicalPrompts.FHIR_EXTRACTION_PROMPT),
            ("fallback", MedicalPrompts.FALLBACK_EXTRACTION_PROMPT)
        ]
    
    def extract_with_fallbacks(
        self, 
        document_content: str, 
        max_attempts: int = 3,
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Try multiple prompts until successful extraction.
        
        Like trying different sized wrenches until you find the one that fits.
        
        Args:
            document_content: Document text to process
            max_attempts: Maximum number of prompt attempts
            context: Optional context for the document
            
        Returns:
            Extraction result with success/failure information
        """
        for attempt, (prompt_name, prompt) in enumerate(self.prompt_sequence[:max_attempts]):
            self.logger.info(f"Attempting extraction with {prompt_name} prompt (attempt {attempt + 1})")
            
            try:
                # Add context to prompt if provided
                if context:
                    enhanced_prompt = f"{prompt}\n\nContext: This document is from {context}."
                else:
                    enhanced_prompt = prompt
                
                # This would be called by the actual AI service
                # Returning the prompt for integration with existing DocumentAnalyzer
                return {
                    "success": True,
                    "prompt": enhanced_prompt,
                    "prompt_type": prompt_name,
                    "attempt": attempt + 1
                }
                
            except Exception as e:
                self.logger.warning(f"Failed to prepare {prompt_name} prompt: {e}")
                if attempt == max_attempts - 1:
                    return {
                        "success": False,
                        "error": f"All prompt preparation attempts failed. Last error: {e}",
                        "attempts": attempt + 1
                    }
                continue


class ConfidenceScoring:
    """
    Confidence scoring utilities for medical data extraction.
    
    Like having a quality control gauge - helps us know when the extraction
    is spot-on versus when it needs a human to double-check.
    """
    
    # Confidence thresholds for quality assurance
    HIGH_CONFIDENCE_THRESHOLD = 0.8
    MEDIUM_CONFIDENCE_THRESHOLD = 0.5
    MANUAL_REVIEW_THRESHOLD = 0.3
    
    @classmethod
    def calibrate_confidence_scores(cls, extracted_fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Calibrate confidence scores based on field characteristics.
        
        Args:
            extracted_fields: List of extracted field dictionaries
            
        Returns:
            Fields with calibrated confidence scores
        """
        calibrated_fields = []
        
        for field in extracted_fields:
            calibrated_field = field.copy()
            
            # Get current confidence or default
            current_confidence = field.get('confidence', 0.5)
            
            # Apply field-specific calibration
            calibrated_confidence = cls._calibrate_field_confidence(
                field.get('label', ''),
                field.get('value', ''),
                current_confidence
            )
            
            # Update confidence score
            calibrated_field['confidence'] = calibrated_confidence
            calibrated_field['confidence_level'] = cls._get_confidence_level(calibrated_confidence)
            calibrated_field['requires_review'] = calibrated_confidence < cls.MANUAL_REVIEW_THRESHOLD
            
            calibrated_fields.append(calibrated_field)
        
        return calibrated_fields
    
    @classmethod
    def _calibrate_field_confidence(cls, label: str, value: str, current_confidence: float) -> float:
        """Calibrate confidence for a specific field based on its characteristics."""
        import re  # Import at function level to avoid scope issues
        
        if not value or not value.strip():
            return 0.0
        
        label_lower = label.lower()
        value_str = str(value).strip()
        
        # Patient name adjustments
        if 'name' in label_lower:
            if len(value_str) < 2:
                return min(current_confidence, 0.3)
            elif len(value_str.split()) >= 2:  # First and last name
                return min(current_confidence * 1.1, 1.0)
        
        # Date field adjustments
        if any(term in label_lower for term in ['date', 'dob', 'birth']):
            if re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', value_str):
                return min(current_confidence * 1.1, 1.0)
            elif re.search(r'\d', value_str):
                return current_confidence  # Has numbers, probably a date
            else:
                return min(current_confidence, 0.4)
        
        # Medical record number adjustments
        if 'mrn' in label_lower or 'record' in label_lower:
            if re.search(r'\d{3,}', value_str):  # At least 3 digits
                return min(current_confidence * 1.1, 1.0)
            else:
                return min(current_confidence, 0.5)
        
        # Medication adjustments
        if 'medication' in label_lower or 'drug' in label_lower:
            # Look for dosage information
            if re.search(r'\d+\s*(mg|mL|units)', value_str, re.IGNORECASE):
                return min(current_confidence * 1.05, 1.0)
        
        return current_confidence
    
    @classmethod
    def _get_confidence_level(cls, confidence: float) -> str:
        """Get human-readable confidence level."""
        if confidence >= cls.HIGH_CONFIDENCE_THRESHOLD:
            return "high"
        elif confidence >= cls.MEDIUM_CONFIDENCE_THRESHOLD:
            return "medium"
        elif confidence >= cls.MANUAL_REVIEW_THRESHOLD:
            return "low"
        else:
            return "very_low"
    
    @classmethod
    def get_quality_metrics(cls, extracted_fields: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate quality metrics for extracted fields.
        
        Args:
            extracted_fields: List of extracted field dictionaries
            
        Returns:
            Quality metrics dictionary
        """
        if not extracted_fields:
            return {
                'total_fields': 0,
                'avg_confidence': 0.0,
                'high_confidence_count': 0,
                'requires_review_count': 0,
                'quality_score': 0.0
            }
        
        confidences = [field.get('confidence', 0.0) for field in extracted_fields]
        high_confidence_count = sum(1 for c in confidences if c >= cls.HIGH_CONFIDENCE_THRESHOLD)
        review_count = sum(1 for c in confidences if c < cls.MANUAL_REVIEW_THRESHOLD)
        
        avg_confidence = sum(confidences) / len(confidences)
        quality_score = (high_confidence_count / len(extracted_fields)) * 100
        
        return {
            'total_fields': len(extracted_fields),
            'avg_confidence': round(avg_confidence, 3),
            'high_confidence_count': high_confidence_count,
            'requires_review_count': review_count,
            'quality_score': round(quality_score, 1),
            'confidence_distribution': {
                'high': high_confidence_count,
                'medium': sum(1 for c in confidences if cls.MEDIUM_CONFIDENCE_THRESHOLD <= c < cls.HIGH_CONFIDENCE_THRESHOLD),
                'low': sum(1 for c in confidences if cls.MANUAL_REVIEW_THRESHOLD <= c < cls.MEDIUM_CONFIDENCE_THRESHOLD),
                'very_low': review_count
            }
        } 