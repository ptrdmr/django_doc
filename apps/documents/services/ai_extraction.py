"""
AI Extraction Service with Instructor-based Structured Data Extraction

This service uses the instructor library to provide structured medical data extraction
from clinical documents with Pydantic validation and type safety.
"""

import logging
import json
import instructor
from typing import List, Optional, Dict, Any
from openai import OpenAI
from pydantic import BaseModel, Field, validator
from django.conf import settings

logger = logging.getLogger(__name__)

# Initialize instructor-patched OpenAI client
try:
    client = instructor.patch(OpenAI(api_key=getattr(settings, 'OPENAI_API_KEY', None)))
except Exception as e:
    logger.warning(f"Failed to initialize OpenAI client: {e}")
    client = None


class SourceContext(BaseModel):
    """Context information about where data was extracted from in the source text."""
    text: str = Field(description="The exact text snippet from the document")
    start_index: int = Field(description="Start position in the source text", ge=0)
    end_index: int = Field(description="End position in the source text", ge=0)
    
    @validator('end_index')
    def end_after_start(cls, v, values):
        if 'start_index' in values and v < values['start_index']:
            raise ValueError('end_index must be >= start_index')
        return v


class MedicalCondition(BaseModel):
    """A medical condition, diagnosis, or clinical finding."""
    name: str = Field(description="The medical condition or diagnosis name")
    status: str = Field(
        description="Status of the condition",
        default="active",
        pattern="^(active|resolved|suspected|ruled_out|chronic)$"
    )
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0)
    onset_date: Optional[str] = Field(default=None, description="When the condition was first diagnosed (YYYY-MM-DD)")
    icd_code: Optional[str] = Field(default=None, description="ICD-10 code if mentioned")
    source: SourceContext = Field(description="Source context in the document")


class Medication(BaseModel):
    """A medication, drug, or therapeutic substance."""
    name: str = Field(description="The medication name")
    dosage: Optional[str] = Field(default=None, description="Dosage amount (e.g., '500mg', '10 units')")
    route: Optional[str] = Field(default=None, description="Route of administration (e.g., 'oral', 'IV', 'topical')")
    frequency: Optional[str] = Field(default=None, description="Dosing frequency (e.g., 'twice daily', 'PRN')")
    status: str = Field(
        description="Medication status",
        default="active",
        pattern="^(active|discontinued|prescribed|held|unknown)$"
    )
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0)
    start_date: Optional[str] = Field(default=None, description="When medication was started (YYYY-MM-DD)")
    stop_date: Optional[str] = Field(default=None, description="When medication was stopped (YYYY-MM-DD)")
    source: SourceContext = Field(description="Source context in the document")


class VitalSign(BaseModel):
    """A vital sign measurement."""
    measurement_type: str = Field(description="Type of vital sign (e.g., 'blood_pressure', 'temperature')")
    value: str = Field(description="The measured value")
    unit: Optional[str] = Field(default=None, description="Unit of measurement")
    timestamp: Optional[str] = Field(default=None, description="When the measurement was taken (YYYY-MM-DD HH:MM)")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0)
    source: SourceContext = Field(description="Source context in the document")


class LabResult(BaseModel):
    """A laboratory test result."""
    test_name: str = Field(description="Name of the laboratory test")
    value: str = Field(description="Test result value")
    unit: Optional[str] = Field(default=None, description="Unit of measurement")
    reference_range: Optional[str] = Field(default=None, description="Normal reference range")
    status: Optional[str] = Field(default=None, description="Result status (e.g., 'normal', 'abnormal', 'critical')")
    test_date: Optional[str] = Field(default=None, description="Date test was performed (YYYY-MM-DD)")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0)
    source: SourceContext = Field(description="Source context in the document")


class Procedure(BaseModel):
    """A medical procedure or intervention."""
    name: str = Field(description="Name of the procedure")
    procedure_date: Optional[str] = Field(default=None, description="Date procedure was performed (YYYY-MM-DD)")
    provider: Optional[str] = Field(default=None, description="Provider who performed the procedure")
    outcome: Optional[str] = Field(default=None, description="Outcome or result of the procedure")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0)
    source: SourceContext = Field(description="Source context in the document")


class Provider(BaseModel):
    """A healthcare provider."""
    name: str = Field(description="Provider's name")
    specialty: Optional[str] = Field(default=None, description="Medical specialty")
    role: Optional[str] = Field(default=None, description="Role in patient care")
    contact_info: Optional[str] = Field(default=None, description="Contact information if available")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0)
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
    confidence_average: Optional[float] = Field(default=None, description="Average confidence across all extractions")
    
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
    Extract structured medical data using instructor and GPT.
    
    Args:
        text: The medical document text to analyze
        context: Optional context about the document type or source
        
    Returns:
        StructuredMedicalExtraction object with all extracted data
        
    Raises:
        Exception: If the AI service fails or response is invalid
    """
    if not client:
        raise Exception("OpenAI client not properly initialized")
    
    # Build the extraction prompt
    system_prompt = """You are MediExtract Pro, an expert medical data extraction AI. 

Your task is to extract ALL medical information from clinical documents with the highest possible accuracy and completeness. 

CRITICAL REQUIREMENTS:
1. Extract EVERY piece of medical information mentioned
2. Provide exact source context for each extracted item
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

    try:
        extraction = client.chat.completions.create(
            model="gpt-3.5-turbo",
            response_model=StructuredMedicalExtraction,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,  # Low temperature for consistent extraction
            max_tokens=4000
        )
        
        # Set extraction timestamp
        from datetime import datetime
        extraction.extraction_timestamp = datetime.now().isoformat()
        extraction.document_type = context
        
        logger.info(f"Successfully extracted {len(extraction.conditions)} conditions, "
                   f"{len(extraction.medications)} medications, "
                   f"{len(extraction.vital_signs)} vital signs from document")
        
        return extraction
        
    except Exception as e:
        logger.error(f"Structured extraction failed: {e}")
        raise


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
    from datetime import datetime
    
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
