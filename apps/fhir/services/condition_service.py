"""
Condition Service for FHIR Resource Processing

This service handles the conversion of extracted diagnosis data into proper FHIR 
Condition resources with clinical status, verification status, and proper coding.
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4
from datetime import datetime
from apps.core.date_parser import ClinicalDateParser

logger = logging.getLogger(__name__)


class ConditionService:
    """
    Service for processing diagnosis data into FHIR Condition resources.
    
    This service ensures complete capture of diagnosis/condition data by properly 
    converting all extracted diagnosis information into structured FHIR resources.
    """
    
    def __init__(self):
        self.logger = logger
        self.date_parser = ClinicalDateParser()
        
    def process_conditions(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process all conditions from extracted data into FHIR Condition resources.
        
        Args:
            extracted_data: Dictionary containing 'fields' list with diagnosis data
            
        Returns:
            List of FHIR Condition resources
        """
        conditions = []
        patient_id = extracted_data.get('patient_id')
        
        if not patient_id:
            self.logger.warning("No patient_id provided for condition processing")
            return conditions
            
        # Handle fields list format (from structured extraction)
        if 'fields' in extracted_data:
            self.logger.info(f"Processing {len(extracted_data['fields'])} fields for conditions")
            
            for field in extracted_data['fields']:
                if isinstance(field, dict):
                    label = field.get('label', '').lower()
                    if 'diagnosis' in label:
                        self.logger.debug(f"Found diagnosis field: {label}")
                        condition_resource = self._create_condition_resource(field, patient_id)
                        if condition_resource:
                            conditions.append(condition_resource)
                            self.logger.debug(f"Created condition resource for {label}")
        
        self.logger.info(f"Successfully processed {len(conditions)} condition resources")
        return conditions
    
    def _create_condition_resource(self, field: Dict[str, Any], patient_id: str, clinical_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR Condition resource from a diagnosis field.
        
        Args:
            field: Dictionary containing label, value, confidence, etc.
            patient_id: Patient UUID for subject reference
            clinical_date: Optional ISO format date string (YYYY-MM-DD) for when condition occurred
            
        Returns:
            FHIR Condition resource dictionary or None if invalid
        """
        value = field.get('value')
        if not value or not isinstance(value, str) or not value.strip():
            self.logger.warning(f"Invalid or empty value in diagnosis field: {field}")
            return None
        
        # Extract clinical date if not provided
        onset_date = None
        date_source = "unknown"
        
        if clinical_date:
            # Manual date provided
            onset_date = clinical_date
            date_source = "manual"
        else:
            # Try to extract date from value text
            extracted_dates = self.date_parser.extract_dates(value)
            if extracted_dates:
                # Use the highest confidence date
                best_date = max(extracted_dates, key=lambda x: x.confidence)
                onset_date = best_date.extracted_date.isoformat()
                date_source = "extracted"
                self.logger.debug(f"Extracted onset date {onset_date} with confidence {best_date.confidence}")
            
        # Create FHIR Condition resource from diagnosis field
        condition = {
            "resourceType": "Condition",
            "id": str(uuid4()),
            "clinicalStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                    "display": "Active"
                }]
            },
            "verificationStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                    "display": "Confirmed"
                }]
            },
            "code": {
                "text": value.strip()
            },
            "subject": {
                "reference": f"Patient/{patient_id}"
            },
            # PROCESSING METADATA (when this was recorded in system)
            "recordedDate": datetime.now().isoformat(),
            "meta": {
                "source": field.get('source_context', 'Document extraction'),
                "profile": ["http://hl7.org/fhir/StructureDefinition/Condition"],
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                    "code": "date-source",
                    "display": f"Date source: {date_source}"
                }]
            }
        }
        
        # Add CLINICAL DATE (when condition actually occurred) if available
        if onset_date:
            condition["onsetDateTime"] = onset_date
        
        # Add extraction confidence if available
        confidence = field.get('confidence')
        if confidence is not None:
            condition["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "extraction-confidence",
                "display": f"Extraction confidence: {confidence}"
            })
        
        self.logger.debug(f"Created Condition resource for diagnosis: {value[:50]}...")
        return condition
