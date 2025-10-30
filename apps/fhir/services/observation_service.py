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
        
        Supports dual-format input:
        1. Structured Pydantic-derived dicts (primary path) - VitalSign and LabResult models
        2. Legacy 'fields' list (fallback path)
        
        Args:
            extracted_data: Dictionary containing either:
                - 'structured_data' dict with 'vital_signs' and/or 'lab_results' lists
                - 'fields' list with vital sign data (legacy format)
            
        Returns:
            List of FHIR Observation resources
        """
        observations = []
        patient_id = extracted_data.get('patient_id')
        
        if not patient_id:
            self.logger.warning("No patient_id provided for observation processing")
            return observations
        
        # PRIMARY PATH: Handle structured Pydantic data
        if 'structured_data' in extracted_data:
            structured_data = extracted_data['structured_data']
            if isinstance(structured_data, dict):
                # Process VitalSign models
                vital_signs = structured_data.get('vital_signs', [])
                if vital_signs:
                    self.logger.info(f"Processing {len(vital_signs)} vital signs via structured path")
                    for vital_dict in vital_signs:
                        if isinstance(vital_dict, dict):
                            obs_resource = self._create_observation_from_structured(vital_dict, patient_id, 'vital_sign')
                            if obs_resource:
                                observations.append(obs_resource)
                
                # Process LabResult models
                lab_results = structured_data.get('lab_results', [])
                if lab_results:
                    self.logger.info(f"Processing {len(lab_results)} lab results via structured path")
                    for lab_dict in lab_results:
                        if isinstance(lab_dict, dict):
                            obs_resource = self._create_observation_from_structured(lab_dict, patient_id, 'lab_result')
                            if obs_resource:
                                observations.append(obs_resource)
                
                if vital_signs or lab_results:
                    self.logger.info(f"Successfully processed {len(observations)} observations via structured path")
                    return observations
        
        # FALLBACK PATH: Handle legacy fields list format
        if 'fields' in extracted_data:
            self.logger.warning(f"Falling back to legacy fields processing for observations")
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
        
        self.logger.info(f"Successfully processed {len(observations)} observation resources via legacy path")
        return observations
    
    def _create_observation_from_structured(self, obs_dict: Dict[str, Any], patient_id: str, obs_type: str) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR Observation resource from structured Pydantic-derived dict.
        
        This is the primary path for processing VitalSign and LabResult Pydantic models.
        
        Args:
            obs_dict: Dictionary from VitalSign or LabResult Pydantic model
                For VitalSign: measurement, value, unit, timestamp, confidence, source
                For LabResult: test_name, value, unit, reference_range, test_date, status, confidence, source
            patient_id: Patient UUID for subject reference
            obs_type: Type indicator - 'vital_sign' or 'lab_result'
            
        Returns:
            FHIR Observation resource dictionary or None if invalid
        """
        # Extract appropriate fields based on observation type
        if obs_type == 'vital_sign':
            display_name = obs_dict.get('measurement')
            date_field = obs_dict.get('timestamp')
        elif obs_type == 'lab_result':
            display_name = obs_dict.get('test_name')
            date_field = obs_dict.get('test_date')
        else:
            self.logger.warning(f"Unknown observation type: {obs_type}")
            return None
        
        if not display_name or not isinstance(display_name, str) or not display_name.strip():
            self.logger.warning(f"Invalid or empty name in {obs_type}: {obs_dict}")
            return None
        
        # Parse effective date using ClinicalDateParser
        effective_date = None
        date_source = "structured"
        
        if date_field:
            extracted_dates = self.date_parser.extract_dates(date_field)
            if extracted_dates:
                best_date = max(extracted_dates, key=lambda x: x.confidence)
                effective_date = best_date.extracted_date.isoformat()
                self.logger.debug(f"Parsed {obs_type} date {effective_date} with confidence {best_date.confidence}")
        
        # Get LOINC code if available
        loinc_code = None
        display_lower = display_name.lower()
        for key, code in self.VITAL_LOINC_MAPPING.items():
            if key in display_lower:
                loinc_code = code
                break
        
        # Create FHIR Observation resource
        observation = {
            "resourceType": "Observation",
            "id": str(uuid4()),
            "status": "final",
            "code": {
                "text": display_name.strip()
            },
            "subject": {
                "reference": f"Patient/{patient_id}"
            },
            "meta": {
                "source": "Structured Pydantic extraction",
                "profile": ["http://hl7.org/fhir/StructureDefinition/Observation"],
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                    "code": "extraction-source",
                    "display": f"Structured {obs_type} path"
                }]
            }
        }
        
        # Add LOINC code if found
        if loinc_code:
            observation["code"]["coding"] = [{
                "system": "http://loinc.org",
                "code": loinc_code,
                "display": display_name.strip()
            }]
        
        # Add effective date if available
        if effective_date:
            observation["effectiveDateTime"] = effective_date
            observation["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "date-source",
                "display": f"Date source: {date_source}"
            })
        
        # Add value and unit
        value = obs_dict.get('value')
        unit = obs_dict.get('unit')
        
        if value:
            # Try to parse as numeric
            try:
                numeric_value = float(value.replace(',', '').strip())
                if unit:
                    observation["valueQuantity"] = {
                        "value": numeric_value,
                        "unit": unit.strip(),
                        "system": "http://unitsofmeasure.org",
                        "code": unit.strip()
                    }
                else:
                    observation["valueQuantity"] = {
                        "value": numeric_value
                    }
            except (ValueError, AttributeError):
                # Not numeric, use string value
                observation["valueString"] = str(value).strip()
        
        # Add reference range for lab results
        if obs_type == 'lab_result':
            reference_range = obs_dict.get('reference_range')
            if reference_range:
                observation["referenceRange"] = [{
                    "text": reference_range.strip()
                }]
            
            # Override status for lab results if provided
            lab_status = obs_dict.get('status')
            if lab_status:
                status_mapping = {
                    'final': 'final',
                    'preliminary': 'preliminary',
                    'amended': 'amended',
                    'corrected': 'corrected',
                    'cancelled': 'cancelled'
                }
                observation["status"] = status_mapping.get(lab_status.lower(), 'final')
        
        # Add extraction confidence
        confidence = obs_dict.get('confidence')
        if confidence is not None:
            observation["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "extraction-confidence",
                "display": f"Extraction confidence: {confidence}"
            })
        
        # Add source context if available
        source = obs_dict.get('source')
        if source and isinstance(source, dict):
            source_text = source.get('text', '')
            if source_text:
                observation["note"] = [{
                    "text": f"Source: {source_text[:200]}"
                }]
        
        self.logger.debug(f"Created Observation from structured {obs_type}: {display_name[:50]}...")
        return observation
    
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
