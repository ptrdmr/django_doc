"""
AI Extraction Service with Instructor-based Structured Data Extraction

This service uses the instructor library with Anthropic Claude (primary) and OpenAI (fallback)
to provide structured medical data extraction from clinical documents with Pydantic validation.
Follows the project's established AI service patterns and configuration.
"""

import logging
import json
import instructor
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from pydantic import BaseModel, Field, validator
from django.conf import settings
import anthropic
from openai import OpenAI

logger = logging.getLogger(__name__)

# Initialize AI clients following project patterns
try:
    # Primary: Anthropic Claude (following project's AI_MODEL_PRIMARY setting)
    anthropic_client = anthropic.Anthropic(
        api_key=getattr(settings, 'ANTHROPIC_API_KEY', None)
    ) if getattr(settings, 'ANTHROPIC_API_KEY', None) else None
    
    # Fallback: OpenAI (following project's AI_MODEL_FALLBACK setting)
    openai_client = instructor.patch(OpenAI(
        api_key=getattr(settings, 'OPENAI_API_KEY', None)
    )) if getattr(settings, 'OPENAI_API_KEY', None) else None
    
except Exception as e:
    logger.warning(f"Failed to initialize AI clients: {e}")
    anthropic_client = None
    openai_client = None


class SourceContext(BaseModel):
    """Context information about where data was extracted from in the source text."""
    text: str = Field(description="The exact text snippet from the document")
    start_index: int = Field(description="Approximate start position in source text", ge=0, default=0)
    end_index: int = Field(description="Approximate end position in source text", ge=0, default=0)
    
    @validator('end_index')
    def end_after_start(cls, v, values):
        if 'start_index' in values and v < values['start_index'] and v != 0:
            v = values['start_index'] + len(values.get('text', ''))
        return v


class MedicalCondition(BaseModel):
    """A medical condition, diagnosis, or clinical finding."""
    name: str = Field(description="The medical condition or diagnosis name")
    status: str = Field(
        description="Status of the condition",
        default="active"
    )
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    onset_date: Optional[str] = Field(default=None, description="When condition was diagnosed")
    icd_code: Optional[str] = Field(default=None, description="ICD-10 code if mentioned")
    source: SourceContext = Field(description="Source context in the document")


class Medication(BaseModel):
    """A medication, drug, or therapeutic substance."""
    name: str = Field(description="The medication name")
    dosage: Optional[str] = Field(default=None, description="Dosage amount")
    route: Optional[str] = Field(default=None, description="Route of administration")
    frequency: Optional[str] = Field(default=None, description="Dosing frequency")
    status: str = Field(description="Medication status", default="active")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    start_date: Optional[str] = Field(default=None, description="When medication was started")
    stop_date: Optional[str] = Field(default=None, description="When medication was stopped")
    source: SourceContext = Field(description="Source context in the document")


class VitalSign(BaseModel):
    """A vital sign measurement."""
    measurement_type: str = Field(description="Type of vital sign")
    value: str = Field(description="The measured value")
    unit: Optional[str] = Field(default=None, description="Unit of measurement")
    timestamp: Optional[str] = Field(default=None, description="When measurement was taken")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class LabResult(BaseModel):
    """A laboratory test result."""
    test_name: str = Field(description="Name of the laboratory test")
    value: str = Field(description="Test result value")
    unit: Optional[str] = Field(default=None, description="Unit of measurement")
    reference_range: Optional[str] = Field(default=None, description="Normal reference range")
    status: Optional[str] = Field(default=None, description="Result status")
    test_date: Optional[str] = Field(default=None, description="Date test was performed")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class Procedure(BaseModel):
    """A medical procedure or intervention."""
    name: str = Field(description="Name of the procedure")
    procedure_date: Optional[str] = Field(default=None, description="Date procedure was performed")
    provider: Optional[str] = Field(default=None, description="Provider who performed procedure")
    outcome: Optional[str] = Field(default=None, description="Outcome or result")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class Provider(BaseModel):
    """A healthcare provider."""
    name: str = Field(description="Provider's name")
    specialty: Optional[str] = Field(default=None, description="Medical specialty")
    role: Optional[str] = Field(default=None, description="Role in patient care")
    contact_info: Optional[str] = Field(default=None, description="Contact information")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class StructuredMedicalExtraction(BaseModel):
    """Complete structured medical data extraction from a clinical document."""
    
    # Core medical data
    conditions: List[MedicalCondition] = Field(
        default_factory=list,
        description="All medical conditions, diagnoses, and clinical findings"
    )
    medications: List[Medication] = Field(
        default_factory=list,
        description="All medications, drugs, and therapeutic substances"
    )
    vital_signs: List[VitalSign] = Field(
        default_factory=list,
        description="All vital sign measurements"
    )
    lab_results: List[LabResult] = Field(
        default_factory=list,
        description="All laboratory test results"
    )
    procedures: List[Procedure] = Field(
        default_factory=list,
        description="All medical procedures and interventions"
    )
    providers: List[Provider] = Field(
        default_factory=list,
        description="All healthcare providers mentioned"
    )
    
    # Metadata
    extraction_timestamp: str = Field(description="When this extraction was performed")
    document_type: Optional[str] = Field(default=None, description="Type of clinical document")
    confidence_average: Optional[float] = Field(default=None, description="Average confidence")
    
    @validator('confidence_average', always=True)
    def calculate_average_confidence(cls, v, values):
        """Calculate average confidence across all extracted items."""
        all_items = []
        for field_name in ['conditions', 'medications', 'vital_signs', 'lab_results', 'procedures', 'providers']:
            items = values.get(field_name, [])
            all_items.extend(item.confidence for item in items)
        
        if all_items:
            return round(sum(all_items) / len(all_items), 3)
        return 0.0


def extract_medical_data_structured(text: str, context: Optional[str] = None) -> StructuredMedicalExtraction:
    """
    Extract structured medical data using Claude (primary) or OpenAI (fallback) with instructor.
    
    Args:
        text: The medical document text to analyze
        context: Optional context about the document type or source
        
    Returns:
        StructuredMedicalExtraction object with all extracted data
        
    Raises:
        Exception: If both AI services fail or response is invalid
    """
    # Build the extraction prompt
    system_prompt = """You are MediExtract Pro, an expert medical data extraction AI. 

Your task is to extract ALL medical information from clinical documents with the highest possible accuracy and completeness. 

CRITICAL REQUIREMENTS:
1. Extract EVERY piece of medical information mentioned
2. Provide source context for each extracted item (use the exact text snippet)
3. Assign accurate confidence scores based on clarity
4. Use proper medical terminology and classifications
5. Include dates, values, and units exactly as written

CONFIDENCE SCORING:
- 0.9-1.0: Information explicitly and clearly stated
- 0.7-0.9: Information clearly implied or inferred
- 0.5-0.7: Information mentioned but with some ambiguity
- 0.3-0.5: Information suggested but unclear
- 0.1-0.3: Information possibly mentioned but very unclear

Focus on:
- Medications (highest priority): names, dosages, routes, frequencies
- Conditions: diagnoses, symptoms, clinical findings
- Vital signs: all measurements with values and units
- Lab results: test names, values, reference ranges, dates
- Procedures: surgical and diagnostic procedures with dates
- Providers: all healthcare professionals mentioned"""

    user_prompt = f"""Extract all medical information from this clinical document:

{text}

Document context: {context or 'General clinical document'}

Return structured data with complete source context for each item."""

    # Try Claude first (primary AI service)
    if anthropic_client:
        try:
            logger.info("Attempting structured extraction with Claude (primary)")
            
            # Claude doesn't directly support instructor, so we'll use it conventionally
            # and parse the JSON response into our Pydantic model
            # Create a detailed schema prompt for Claude
            schema_prompt = f"""
Return valid JSON that exactly matches this schema structure:

{{
  "conditions": [
    {{
      "name": "condition name",
      "status": "active",
      "confidence": 0.9,
      "onset_date": null,
      "icd_code": null,
      "source": {{"text": "exact text from document", "start_index": 0, "end_index": 10}}
    }}
  ],
  "medications": [
    {{
      "name": "medication name",
      "dosage": "dosage amount",
      "route": null,
      "frequency": "frequency",
      "status": "active",
      "confidence": 0.9,
      "start_date": null,
      "stop_date": null,
      "source": {{"text": "exact text from document", "start_index": 0, "end_index": 10}}
    }}
  ],
  "vital_signs": [],
  "lab_results": [],
  "procedures": [],
  "providers": [],
  "extraction_timestamp": "",
  "document_type": "",
  "confidence_average": null
}}

CRITICAL: Every extracted item MUST include a "source" object with the exact text snippet."""

            response = anthropic_client.messages.create(
                model=getattr(settings, 'AI_MODEL_PRIMARY', 'claude-3-5-sonnet-20240620'),
                max_tokens=getattr(settings, 'AI_MAX_TOKENS_PER_REQUEST', 4096),
                temperature=0.1,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt + "\n\n" + schema_prompt}
                ]
            )
            
            # Parse Claude's response
            response_text = response.content[0].text
            
            # Try to extract JSON from the response
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_data = json.loads(json_match.group())
                
                # Set extraction timestamp and document type
                json_data['extraction_timestamp'] = datetime.now().isoformat()
                json_data['document_type'] = context
                
                # Parse into Pydantic model
                extraction = StructuredMedicalExtraction(**json_data)
                
                logger.info(f"Claude extraction successful: {len(extraction.conditions)} conditions, "
                           f"{len(extraction.medications)} medications")
                return extraction
            else:
                raise ValueError("No valid JSON found in Claude response")
                
        except Exception as e:
            logger.warning(f"Claude extraction failed: {e}, trying OpenAI fallback")
    
    # Try OpenAI as fallback
    if openai_client:
        try:
            logger.info("Attempting structured extraction with OpenAI (fallback)")
            
            extraction = openai_client.chat.completions.create(
                model=getattr(settings, 'AI_MODEL_FALLBACK', 'gpt-4o-mini'),
                response_model=StructuredMedicalExtraction,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=getattr(settings, 'AI_MAX_TOKENS_PER_REQUEST', 4096)
            )
            
            # Set extraction timestamp and document type
            extraction.extraction_timestamp = datetime.now().isoformat()
            extraction.document_type = context
            
            logger.info(f"OpenAI extraction successful: {len(extraction.conditions)} conditions, "
                       f"{len(extraction.medications)} medications")
            return extraction
            
        except Exception as e:
            logger.error(f"OpenAI extraction also failed: {e}")
    
    # If both services fail, raise an exception
    raise Exception("Both Claude and OpenAI extraction services failed")


def extract_medical_data(text: str, context: Optional[str] = None) -> Dict[str, Any]:
    """
    Legacy-compatible extraction function that returns a dictionary format.
    
    This function provides backward compatibility while using the new structured extraction.
    
    Args:
        text: The medical document text to analyze
        context: Optional context about the document type or source
        
    Returns:
        Dictionary with extracted medical data in legacy format
    """
    try:
        # Use the new structured extraction
        structured_data = extract_medical_data_structured(text, context)
        
        # Convert to legacy format for backward compatibility
        legacy_format = {
            "diagnoses": [condition.name for condition in structured_data.conditions],
            "medications": [
                f"{med.name} {med.dosage or ''} {med.frequency or ''}".strip()
                for med in structured_data.medications
            ],
            "procedures": [proc.name for proc in structured_data.procedures],
            "lab_results": [
                {
                    "test": lab.test_name,
                    "value": lab.value,
                    "unit": lab.unit or "",
                    "reference_range": lab.reference_range or ""
                }
                for lab in structured_data.lab_results
            ],
            "vital_signs": [
                {
                    "type": vital.measurement_type,
                    "value": vital.value,
                    "unit": vital.unit or ""
                }
                for vital in structured_data.vital_signs
            ],
            "providers": [
                {
                    "name": provider.name,
                    "specialty": provider.specialty or "",
                    "role": provider.role or ""
                }
                for provider in structured_data.providers
            ],
            # Metadata
            "extraction_confidence": structured_data.confidence_average,
            "extraction_timestamp": structured_data.extraction_timestamp,
            "total_items_extracted": (
                len(structured_data.conditions) + 
                len(structured_data.medications) + 
                len(structured_data.vital_signs) + 
                len(structured_data.lab_results) + 
                len(structured_data.procedures) + 
                len(structured_data.providers)
            )
        }
        
        logger.info(f"Converted structured data to legacy format: {legacy_format['total_items_extracted']} total items")
        return legacy_format
        
    except Exception as e:
        logger.error(f"Medical data extraction failed: {e}")
        # Fallback to basic extraction if structured extraction fails
        return legacy_extract_medical_data(text, context)


def legacy_extract_medical_data(text: str, context: Optional[str] = None) -> Dict[str, Any]:
    """
    Fallback extraction method that uses simpler text analysis.
    
    Args:
        text: The medical document text to analyze
        context: Optional context about the document type or source
        
    Returns:
        Basic dictionary with extracted medical data
    """
    logger.warning("Using fallback legacy extraction method")
    
    # Simple keyword-based extraction as fallback
    import re
    
    # Basic medication pattern matching
    medication_patterns = [
        r'\b\w+\s+\d+\s*mg\b',  # Drug name + dosage
        r'\b\w+\s+\d+\s*mcg\b',
        r'\b\w+\s+\d+\s*units?\b'
    ]
    
    medications = []
    for pattern in medication_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        medications.extend(matches)
    
    # Basic diagnosis pattern matching
    diagnosis_patterns = [
        r'(?:diagnosis|dx|impression):\s*([^.\n]+)',
        r'(?:condition|disease):\s*([^.\n]+)'
    ]
    
    diagnoses = []
    for pattern in diagnosis_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        diagnoses.extend([match.strip() for match in matches])
    
    return {
        "diagnoses": list(set(diagnoses)) if diagnoses else ["No diagnoses extracted"],
        "medications": list(set(medications)) if medications else ["No medications extracted"],
        "procedures": [],
        "lab_results": [],
        "vital_signs": [],
        "providers": [],
        "extraction_confidence": 0.3,  # Low confidence for fallback method
        "extraction_timestamp": datetime.now().isoformat(),
        "total_items_extracted": len(set(diagnoses)) + len(set(medications)),
        "fallback_method": True
    }


# Export the main functions for external use
__all__ = [
    'extract_medical_data',
    'extract_medical_data_structured',
    'StructuredMedicalExtraction',
    'MedicalCondition',
    'Medication',
    'VitalSign',
    'LabResult',
    'Procedure',
    'Provider',
    'SourceContext'
]
