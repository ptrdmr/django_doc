"""
Observation Service for FHIR Resource Processing

This service handles the conversion of extracted vital sign data into proper FHIR 
Observation resources with LOINC codes, numeric values, and appropriate units.
"""

import logging
import re
from typing import List, Dict, Any, Optional
from uuid import uuid4
from datetime import datetime
from apps.core.date_parser import ClinicalDateParser

logger = logging.getLogger(__name__)


class ObservationService:
    """
    Service for processing vital sign data into FHIR Observation resources.
    
    This service ensures complete capture of vital sign/observation data by properly 
    converting all extracted vital information into structured FHIR resources.
    """
    
    # LOINC code mapping for common vital signs
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
    
    def __init__(self):
        self.logger = logger
        self.date_parser = ClinicalDateParser()
        
    def process_observations(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process all observations from extracted data into FHIR Observation resources.
        
        Args:
            extracted_data: Dictionary containing 'fields' list with vital sign data
            
        Returns:
            List of FHIR Observation resources
        """
        observations = []
        patient_id = extracted_data.get('patient_id')
        
        if not patient_id:
            self.logger.warning("No patient_id provided for observation processing")
            return observations
            
        # Handle fields list format (from structured extraction)
        if 'fields' in extracted_data:
            self.logger.info(f"Processing {len(extracted_data['fields'])} fields for observations")
            
            for field in extracted_data['fields']:
                if isinstance(field, dict):
                    label = field.get('label', '').lower()
                    if 'vital' in label:
                        self.logger.debug(f"Found vital sign field: {label}")
                        observation_resource = self._create_observation_resource(field, patient_id)
                        if observation_resource:
                            observations.append(observation_resource)
                            self.logger.debug(f"Created observation resource for {label}")
        
        self.logger.info(f"Successfully processed {len(observations)} observation resources")
        return observations
    
    def _create_observation_resource(self, field: Dict[str, Any], patient_id: str, clinical_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR Observation resource from a vital sign field.
        
        Args:
            field: Dictionary containing label, value, confidence, etc.
            patient_id: Patient UUID for subject reference
            clinical_date: Optional ISO format date string (YYYY-MM-DD) for when observation occurred
            
        Returns:
            FHIR Observation resource dictionary or None if invalid
        """
        value = field.get('value')
        if not value or not isinstance(value, str) or not value.strip():
            self.logger.warning(f"Invalid or empty value in vital sign field: {field}")
            return None
        
        # Extract clinical date if not provided
        effective_date = None
        date_source = "unknown"
        
        if clinical_date:
            # Manual date provided
            effective_date = clinical_date
            date_source = "manual"
        else:
            # Try to extract date from value text
            extracted_dates = self.date_parser.extract_dates(value)
            if extracted_dates:
                # Use the highest confidence date
                best_date = max(extracted_dates, key=lambda x: x.confidence)
                effective_date = best_date.extracted_date.isoformat()
                date_source = "extracted"
                self.logger.debug(f"Extracted effective date {effective_date} with confidence {best_date.confidence}")
            
        # Determine vital type from label
        label = field.get('label', '').lower()
        vital_type = None
        loinc_code = None
        
        # Find matching vital sign type and LOINC code
        for key, code in self.VITAL_LOINC_MAPPING.items():
            if key in label:
                vital_type = key
                loinc_code = code
                break
        
        if not vital_type:
            vital_type = "vital sign"
            loinc_code = None
        
        # Extract numeric value and unit if possible
        numeric_value = None
        unit = None
        
        # Try to parse numeric value and unit (e.g., "120 mmHg", "98.6 F")
        match = re.search(r'(\d+\.?\d*)\s*([a-zA-Z%/]+)?', str(value))
        if match:
            try:
                numeric_value = float(match.group(1))
                unit = match.group(2) if match.group(2) else None
            except ValueError:
                self.logger.debug(f"Could not parse numeric value from: {value}")
        
        # Create FHIR Observation resource
        observation = {
            "resourceType": "Observation",
            "id": str(uuid4()),
            "status": "final",
            "code": {
                "text": vital_type.title()
            },
            "subject": {
                "reference": f"Patient/{patient_id}"
            },
            "meta": {
                "source": field.get('source_context', 'Document extraction'),
                "profile": ["http://hl7.org/fhir/StructureDefinition/Observation"],
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                    "code": "date-source",
                    "display": f"Date source: {date_source}"
                }]
            }
        }
        
        # Add CLINICAL DATE (when observation actually occurred) if available
        # Note: If no clinical date is available, effectiveDateTime is omitted per FHIR spec
        if effective_date:
            observation["effectiveDateTime"] = effective_date
        
        # Add LOINC code if available
        if loinc_code:
            observation["code"]["coding"] = [{
                "system": "http://loinc.org",
                "code": loinc_code,
                "display": vital_type.title()
            }]
        
        # Add value based on parsed data
        if numeric_value is not None:
            if unit:
                observation["valueQuantity"] = {
                    "value": numeric_value,
                    "unit": unit,
                    "system": "http://unitsofmeasure.org",
                    "code": unit
                }
            else:
                observation["valueQuantity"] = {
                    "value": numeric_value
                }
        else:
            observation["valueString"] = value.strip()
        
        # Add extraction confidence if available
        confidence = field.get('confidence')
        if confidence is not None:
            observation["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "extraction-confidence",
                "display": f"Extraction confidence: {confidence}"
            })
            
        self.logger.debug(f"Created Observation resource for {vital_type}: {value[:50]}...")
        return observation
