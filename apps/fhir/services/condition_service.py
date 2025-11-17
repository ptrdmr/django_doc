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
        
        Supports dual-format input:
        1. Structured Pydantic-derived dicts (primary path)
        2. Legacy 'fields' list (fallback path)
        
        Args:
            extracted_data: Dictionary containing either:
                - 'structured_data' dict with 'conditions' list (Pydantic MedicalCondition models)
                - 'fields' list with diagnosis data (legacy format)
            
        Returns:
            List of FHIR Condition resources
        """
        conditions = []
        patient_id = extracted_data.get('patient_id')
        
        if not patient_id:
            self.logger.warning("No patient_id provided for condition processing")
            return conditions
        
        # PRIMARY PATH: Handle structured Pydantic data
        if 'structured_data' in extracted_data:
            structured_data = extracted_data['structured_data']
            if isinstance(structured_data, dict) and 'conditions' in structured_data:
                conditions_list = structured_data['conditions']
                if conditions_list:
                    self.logger.info(f"Processing {len(conditions_list)} conditions via structured path")
                    for condition_dict in conditions_list:
                        if isinstance(condition_dict, dict):
                            condition_resource = self._create_condition_from_structured(condition_dict, patient_id)
                            if condition_resource:
                                conditions.append(condition_resource)
                    self.logger.info(f"Successfully processed {len(conditions)} conditions via structured path")
                    return conditions
        
        # FALLBACK PATH: Handle legacy fields list format
        if 'fields' in extracted_data:
            self.logger.warning(f"Falling back to legacy fields processing for conditions")
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
        
        self.logger.info(f"Successfully processed {len(conditions)} condition resources via legacy path")
        return conditions
    
    def _create_condition_from_structured(self, condition_dict: Dict[str, Any], patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR Condition resource from structured Pydantic-derived dict.
        
        This is the primary path for processing MedicalCondition Pydantic models.
        
        Args:
            condition_dict: Dictionary from MedicalCondition Pydantic model with fields:
                - name: str (condition name)
                - status: str (active, inactive, resolved)
                - onset_date: Optional[str] (ISO format date)
                - icd_code: Optional[str] (ICD-10 code)
                - confidence: float (0.0-1.0)
                - source: dict with text, start_index, end_index
            patient_id: Patient UUID for subject reference
            
        Returns:
            FHIR Condition resource dictionary or None if invalid
        """
        name = condition_dict.get('name')
        if not name or not isinstance(name, str) or not name.strip():
            self.logger.warning(f"Invalid or empty name in condition: {condition_dict}")
            return None
        
        # Parse onset date using ClinicalDateParser
        onset_date = None
        date_source = "structured"
        raw_onset = condition_dict.get('onset_date')
        
        if raw_onset:
            import re
            
            # Handle partial dates that date parser can't process
            # Year-only format (e.g., "2018")
            if re.match(r'^\d{4}$', str(raw_onset)):
                onset_date = f"{raw_onset}-01-01"  # Default to January 1st
                date_source = "partial_year"
                self.logger.debug(f"Converted year-only date '{raw_onset}' to {onset_date}")
            
            # Year-month format (e.g., "2018-02" or "2018/02")
            elif re.match(r'^\d{4}[-/]\d{1,2}$', str(raw_onset)):
                # Normalize separator to dash and pad month
                parts = re.split(r'[-/]', str(raw_onset))
                year, month = parts[0], parts[1].zfill(2)
                onset_date = f"{year}-{month}-01"  # Default to 1st of month
                date_source = "partial_year_month"
                self.logger.debug(f"Converted year-month date '{raw_onset}' to {onset_date}")
            
            else:
                # Use ClinicalDateParser for complete dates
                extracted_dates = self.date_parser.extract_dates(str(raw_onset))
                if extracted_dates:
                    best_date = max(extracted_dates, key=lambda x: x.confidence)
                    onset_date = best_date.extracted_date.isoformat()
                    date_source = "full_date_parsed"
                    self.logger.debug(f"Parsed structured onset date {onset_date} with confidence {best_date.confidence}")
        
        # Map condition status to FHIR clinical status
        condition_status = condition_dict.get('status', 'active').lower()
        status_mapping = {
            'active': 'active',
            'inactive': 'inactive',
            'resolved': 'resolved',
            'recurrence': 'recurrence',
            'remission': 'remission'
        }
        clinical_status_code = status_mapping.get(condition_status, 'active')
        
        # Create FHIR Condition resource
        condition = {
            "resourceType": "Condition",
            "id": str(uuid4()),
            "clinicalStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": clinical_status_code,
                    "display": clinical_status_code.capitalize()
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
                "text": name.strip()
            },
            "subject": {
                "reference": f"Patient/{patient_id}"
            },
            "recordedDate": datetime.now().isoformat(),
            "meta": {
                "source": "Structured Pydantic extraction",
                "profile": ["http://hl7.org/fhir/StructureDefinition/Condition"],
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                    "code": "extraction-source",
                    "display": "Structured data path"
                }]
            }
        }
        
        # Add ICD code if available
        icd_code = condition_dict.get('icd_code')
        if icd_code:
            condition["code"]["coding"] = [{
                "system": "http://hl7.org/fhir/sid/icd-10",
                "code": icd_code.strip(),
                "display": name.strip()
            }]
        
        # Add onset date if available
        if onset_date:
            condition["onsetDateTime"] = onset_date
            condition["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "date-source",
                "display": f"Date source: {date_source}"
            })
            
            # Add date precision metadata for tracking
            precision = "day"  # Default
            if date_source == "partial_year":
                precision = "year"
            elif date_source == "partial_year_month":
                precision = "month"
            
            condition["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "date-precision",
                "display": f"Date precision: {precision}"
            })
        
        # Add extraction confidence
        confidence = condition_dict.get('confidence')
        if confidence is not None:
            condition["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "extraction-confidence",
                "display": f"Extraction confidence: {confidence}"
            })
        
        # Add source context if available
        source = condition_dict.get('source')
        if source and isinstance(source, dict):
            source_text = source.get('text', '')
            if source_text:
                condition["note"] = [{
                    "text": f"Source: {source_text[:200]}"  # Limit length
                }]
        
        self.logger.debug(f"Created Condition resource from structured data: {name[:50]}...")
        return condition
    
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
