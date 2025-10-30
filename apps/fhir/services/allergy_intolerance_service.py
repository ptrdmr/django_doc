"""
AllergyIntolerance Service for FHIR Resource Processing

This service handles the conversion of extracted allergy/intolerance data into proper FHIR 
AllergyIntolerance resources with allergen, reaction, severity, and verification information.
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4
from datetime import datetime
from apps.core.date_parser import ClinicalDateParser

logger = logging.getLogger(__name__)


class AllergyIntoleranceService:
    """
    Service for processing allergy/intolerance data into FHIR AllergyIntolerance resources.
    
    This service ensures complete capture of allergy data by properly converting
    all extracted allergy information into structured FHIR resources.
    """
    
    def __init__(self):
        self.logger = logger
        self.date_parser = ClinicalDateParser()
        
    def process_allergies(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process all allergies from extracted data into FHIR AllergyIntolerance resources.
        
        Supports dual-format input:
        1. Structured Pydantic-derived dicts (primary path)
        2. Legacy 'fields' list (fallback path)
        
        Args:
            extracted_data: Dictionary containing either:
                - 'structured_data' dict with 'allergies' list (Pydantic AllergyIntolerance models)
                - 'fields' list with allergy data (legacy format)
            
        Returns:
            List of FHIR AllergyIntolerance resources
        """
        allergies = []
        patient_id = extracted_data.get('patient_id')
        
        if not patient_id:
            self.logger.warning("No patient_id provided for allergy processing")
            return allergies
        
        # PRIMARY PATH: Handle structured Pydantic data
        if 'structured_data' in extracted_data:
            structured_data = extracted_data['structured_data']
            if isinstance(structured_data, dict) and 'allergies' in structured_data:
                allergies_list = structured_data['allergies']
                if allergies_list:
                    self.logger.info(f"Processing {len(allergies_list)} allergies via structured path")
                    for allergy_dict in allergies_list:
                        if isinstance(allergy_dict, dict):
                            allergy_resource = self._create_allergy_from_structured(allergy_dict, patient_id)
                            if allergy_resource:
                                allergies.append(allergy_resource)
                    self.logger.info(f"Successfully processed {len(allergies)} allergies via structured path")
                    return allergies
        
        # FALLBACK PATH: Handle legacy fields list format
        if 'fields' in extracted_data:
            self.logger.warning(f"Falling back to legacy fields processing for allergies")
            self.logger.info(f"Processing {len(extracted_data['fields'])} fields for allergies")
            
            for field in extracted_data['fields']:
                if isinstance(field, dict):
                    label = field.get('label', '').lower()
                    if 'allerg' in label or 'nkda' in label.lower():
                        self.logger.debug(f"Found allergy field: {label}")
                        allergy_resource = self._create_allergy_from_field(field, patient_id)
                        if allergy_resource:
                            allergies.append(allergy_resource)
                            self.logger.debug(f"Created allergy resource for {label}")
        
        self.logger.info(f"Successfully processed {len(allergies)} allergy resources via legacy path")
        return allergies
    
    def _create_allergy_from_structured(self, allergy_dict: Dict[str, Any], patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR AllergyIntolerance resource from structured Pydantic-derived dict.
        
        This is the primary path for processing AllergyIntolerance Pydantic models.
        
        Args:
            allergy_dict: Dictionary from AllergyIntolerance Pydantic model with fields:
                - allergen: str (substance name)
                - reaction: Optional[str] (type of reaction)
                - severity: Optional[str] (mild, moderate, severe, life-threatening)
                - onset_date: Optional[str] (when first observed)
                - status: Optional[str] (active, inactive, resolved)
                - verification_status: Optional[str] (confirmed, unconfirmed, refuted)
                - confidence: float (0.0-1.0)
                - source: dict with text, start_index, end_index
            patient_id: Patient UUID for subject reference
            
        Returns:
            FHIR AllergyIntolerance resource dictionary or None if invalid
        """
        allergen = allergy_dict.get('allergen')
        if not allergen or not isinstance(allergen, str) or not allergen.strip():
            self.logger.warning(f"Invalid or empty allergen: {allergy_dict}")
            return None
        
        # Parse onset date using ClinicalDateParser
        onset_date = None
        raw_onset = allergy_dict.get('onset_date')
        
        if raw_onset:
            extracted_dates = self.date_parser.extract_dates(raw_onset)
            if extracted_dates:
                best_date = max(extracted_dates, key=lambda x: x.confidence)
                onset_date = best_date.extracted_date.isoformat()
                self.logger.debug(f"Parsed allergy onset date {onset_date}")
        
        # Map severity to FHIR codes
        severity = allergy_dict.get('severity', '').lower()
        severity_mapping = {
            'mild': 'mild',
            'moderate': 'moderate',
            'severe': 'severe',
            'life-threatening': 'severe'  # Map to severe
        }
        fhir_severity = severity_mapping.get(severity, 'mild')
        
        # Map status to FHIR clinical status
        status = allergy_dict.get('status', 'active').lower()
        status_mapping = {
            'active': 'active',
            'inactive': 'inactive',
            'resolved': 'resolved'
        }
        clinical_status = status_mapping.get(status, 'active')
        
        # Map verification status
        verification = allergy_dict.get('verification_status', 'unconfirmed').lower()
        verification_mapping = {
            'confirmed': 'confirmed',
            'unconfirmed': 'unconfirmed',
            'refuted': 'refuted'
        }
        verification_status = verification_mapping.get(verification, 'unconfirmed')
        
        # Create FHIR AllergyIntolerance resource
        allergy = {
            "resourceType": "AllergyIntolerance",
            "id": str(uuid4()),
            "clinicalStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                    "code": clinical_status,
                    "display": clinical_status.capitalize()
                }]
            },
            "verificationStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                    "code": verification_status,
                    "display": verification_status.capitalize()
                }]
            },
            "code": {
                "text": allergen.strip()
            },
            "patient": {
                "reference": f"Patient/{patient_id}"
            },
            "meta": {
                "source": "Structured Pydantic extraction",
                "profile": ["http://hl7.org/fhir/StructureDefinition/AllergyIntolerance"],
                "versionId": "1",
                "lastUpdated": datetime.now().isoformat(),
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                    "code": "extraction-source",
                    "display": "Structured data path"
                }]
            }
        }
        
        # Add reaction if available
        reaction_text = allergy_dict.get('reaction')
        if reaction_text:
            allergy["reaction"] = [{
                "manifestation": [{
                    "text": reaction_text.strip()
                }],
                "severity": fhir_severity
            }]
        
        # Add onset date if available
        if onset_date:
            allergy["onsetDateTime"] = onset_date
        
        # Add extraction confidence
        confidence = allergy_dict.get('confidence')
        if confidence is not None:
            if "extension" not in allergy:
                allergy["extension"] = []
            allergy["extension"].append({
                "url": "http://hl7.org/fhir/StructureDefinition/data-confidence",
                "valueDecimal": confidence
            })
        
        # Add source context if available
        source = allergy_dict.get('source')
        if source and isinstance(source, dict):
            source_text = source.get('text', '')
            if source_text:
                allergy["note"] = [{
                    "text": f"Source: {source_text[:200]}"
                }]
        
        self.logger.debug(f"Created AllergyIntolerance from structured data: {allergen[:50]}...")
        return allergy
    
    def _create_allergy_from_field(self, field: Dict[str, Any], patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR AllergyIntolerance resource from a legacy field.
        
        This is the fallback path for backward compatibility.
        
        Args:
            field: Dictionary containing label, value, confidence, etc.
            patient_id: Patient UUID for subject reference
            
        Returns:
            FHIR AllergyIntolerance resource dictionary or None if invalid
        """
        value = field.get('value')
        if not value or not isinstance(value, str) or not value.strip():
            self.logger.warning(f"Invalid or empty value in allergy field: {field}")
            return None
        
        # Handle "NKDA" (No Known Drug Allergies)
        if 'nkda' in value.lower() or 'no known' in value.lower():
            self.logger.info("NKDA found - not creating allergy resource")
            return None
        
        # Create basic FHIR AllergyIntolerance resource from field
        allergy = {
            "resourceType": "AllergyIntolerance",
            "id": str(uuid4()),
            "clinicalStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                    "code": "active",
                    "display": "Active"
                }]
            },
            "verificationStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                    "code": "unconfirmed",
                    "display": "Unconfirmed"
                }]
            },
            "code": {
                "text": value.strip()
            },
            "patient": {
                "reference": f"Patient/{patient_id}"
            },
            "meta": {
                "source": field.get('source_context', 'Document extraction'),
                "profile": ["http://hl7.org/fhir/StructureDefinition/AllergyIntolerance"],
                "versionId": "1",
                "lastUpdated": datetime.now().isoformat(),
                "tag": []
            }
        }
        
        # Add extraction confidence if available
        confidence = field.get('confidence')
        if confidence is not None:
            allergy["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "extraction-confidence",
                "display": f"Extraction confidence: {confidence}"
            })
        
        self.logger.debug(f"Created AllergyIntolerance from legacy field: {value[:50]}...")
        return allergy

