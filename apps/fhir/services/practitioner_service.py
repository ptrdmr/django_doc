"""
Practitioner Service for FHIR Resource Processing

This service handles the conversion of extracted provider/practitioner data into proper FHIR 
Practitioner resources with name, specialty, and credential information.
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4
from datetime import datetime
from apps.core.date_parser import ClinicalDateParser

logger = logging.getLogger(__name__)


class PractitionerService:
    """
    Service for processing provider/practitioner data into FHIR Practitioner resources.
    
    This service ensures complete capture of provider data by properly converting
    all extracted provider information into structured FHIR resources.
    """
    
    def __init__(self):
        self.logger = logger
        self.date_parser = ClinicalDateParser()
        
    def process_practitioners(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process all practitioners from extracted data into FHIR Practitioner resources.
        
        Supports dual-format input:
        1. Structured Pydantic-derived dicts (primary path)
        2. Legacy 'fields' list (fallback path)
        
        Args:
            extracted_data: Dictionary containing either:
                - 'structured_data' dict with 'providers' list (Pydantic Provider models)
                - 'fields' list with provider data (legacy format)
            
        Returns:
            List of FHIR Practitioner resources
        """
        practitioners = []
        patient_id = extracted_data.get('patient_id')
        
        if not patient_id:
            self.logger.warning("No patient_id provided for practitioner processing")
            return practitioners
        
        # PRIMARY PATH: Handle structured Pydantic data
        if 'structured_data' in extracted_data:
            structured_data = extracted_data['structured_data']
            if isinstance(structured_data, dict) and 'providers' in structured_data:
                providers_list = structured_data['providers']
                if providers_list:
                    self.logger.info(f"Processing {len(providers_list)} practitioners via structured path")
                    for provider_dict in providers_list:
                        if isinstance(provider_dict, dict):
                            practitioner_resource = self._create_practitioner_from_structured(provider_dict, patient_id)
                            if practitioner_resource:
                                practitioners.append(practitioner_resource)
                    self.logger.info(f"Successfully processed {len(practitioners)} practitioners via structured path")
                    return practitioners
        
        # FALLBACK PATH: Handle legacy fields list format
        if 'fields' in extracted_data:
            self.logger.warning(f"Falling back to legacy fields processing for practitioners")
            self.logger.info(f"Processing {len(extracted_data['fields'])} fields for practitioners")
            
            for field in extracted_data['fields']:
                if isinstance(field, dict):
                    label = field.get('label', '').lower()
                    if any(term in label for term in ['provider', 'physician', 'doctor', 'practitioner', 'nurse', 'md', 'dr']):
                        self.logger.debug(f"Found provider field: {label}")
                        practitioner_resource = self._create_practitioner_from_field(field, patient_id)
                        if practitioner_resource:
                            practitioners.append(practitioner_resource)
                            self.logger.debug(f"Created practitioner resource for {label}")
        
        self.logger.info(f"Successfully processed {len(practitioners)} practitioner resources via legacy path")
        return practitioners
    
    def _create_practitioner_from_structured(self, provider_dict: Dict[str, Any], patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR Practitioner resource from structured Pydantic-derived dict.
        
        This is the primary path for processing Provider Pydantic models.
        
        Args:
            provider_dict: Dictionary from Provider Pydantic model with fields:
                - name: str (provider name)
                - specialty: Optional[str] (medical specialty)
                - role: Optional[str] (role in patient care)
                - contact_info: Optional[str] (contact information)
                - confidence: float (0.0-1.0)
                - source: dict with text, start_index, end_index
            patient_id: Patient UUID for reference (for context/logging)
            
        Returns:
            FHIR Practitioner resource dictionary or None if invalid
        """
        name = provider_dict.get('name')
        if not name or not isinstance(name, str) or not name.strip():
            self.logger.warning(f"Invalid or empty provider name: {provider_dict}")
            return None
        
        # Parse provider name into components (family, given)
        name_parts = self._parse_provider_name(name.strip())
        
        # Create FHIR Practitioner resource
        practitioner = {
            "resourceType": "Practitioner",
            "id": str(uuid4()),
            "name": [{
                "text": name.strip(),
                "family": name_parts.get('family'),
                "given": name_parts.get('given', [])
            }],
            "meta": {
                "source": "Structured Pydantic extraction",
                "profile": ["http://hl7.org/fhir/StructureDefinition/Practitioner"],
                "versionId": "1",
                "lastUpdated": datetime.now().isoformat(),
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                    "code": "extraction-source",
                    "display": "Structured data path"
                }]
            }
        }
        
        # Add specialty as qualification if available
        specialty = provider_dict.get('specialty')
        if specialty and isinstance(specialty, str):
            practitioner["qualification"] = [{
                "code": {
                    "text": specialty.strip(),
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/practitioner-specialty",
                        "display": specialty.strip()
                    }]
                }
            }]
        
        # Add contact information if available
        contact_info = provider_dict.get('contact_info')
        if contact_info and isinstance(contact_info, str):
            # Try to determine if it's a phone number or email
            if '@' in contact_info:
                practitioner["telecom"] = [{
                    "system": "email",
                    "value": contact_info.strip()
                }]
            elif any(char.isdigit() for char in contact_info):
                practitioner["telecom"] = [{
                    "system": "phone",
                    "value": contact_info.strip()
                }]
        
        # Add role as extension if available
        role = provider_dict.get('role')
        if role and isinstance(role, str):
            if "extension" not in practitioner:
                practitioner["extension"] = []
            practitioner["extension"].append({
                "url": "http://hl7.org/fhir/StructureDefinition/practitioner-role",
                "valueString": role.strip()
            })
        
        # Add extraction confidence
        confidence = provider_dict.get('confidence')
        if confidence is not None:
            if "extension" not in practitioner:
                practitioner["extension"] = []
            practitioner["extension"].append({
                "url": "http://hl7.org/fhir/StructureDefinition/data-confidence",
                "valueDecimal": confidence
            })
        
        # Add source context if available
        source = provider_dict.get('source')
        if source and isinstance(source, dict):
            source_text = source.get('text', '')
            if source_text:
                if "note" not in practitioner:
                    practitioner["note"] = []
                practitioner["note"].append({
                    "text": f"Source: {source_text[:200]}"
                })
        
        self.logger.debug(f"Created Practitioner resource from structured data: {name[:50]}...")
        return practitioner
    
    def _parse_provider_name(self, name: str) -> Dict[str, Any]:
        """
        Parse provider name into family and given name components.
        
        Handles various formats:
        - "Last, First" or "Last, First Middle"
        - "First Last" or "First Middle Last"
        - "Dr. First Last" or "First Last, MD"
        
        Args:
            name: Provider name string
            
        Returns:
            Dictionary with 'family' and 'given' (list) components
        """
        import re
        
        # Remove common titles and credentials
        clean_name = name
        titles = ['Dr.', 'Dr', 'Doctor', 'Prof.', 'Professor']
        credentials = ['M.D.', 'MD', 'D.O.', 'DO', 'R.N.', 'RN', 'PA', 'NP', 'PhD', 'DDS']
        
        for title in titles:
            clean_name = re.sub(rf'\b{re.escape(title)}\s*', '', clean_name, flags=re.IGNORECASE)
        
        for cred in credentials:
            clean_name = re.sub(rf',?\s*{re.escape(cred)}\s*$', '', clean_name, flags=re.IGNORECASE)
        
        clean_name = clean_name.strip().strip(',').strip()
        
        # Parse name components
        if ',' in clean_name:
            # "Last, First" format
            parts = clean_name.split(',', 1)
            family = parts[0].strip()
            given_parts = parts[1].strip().split() if len(parts) > 1 else []
            return {
                'family': family,
                'given': given_parts
            }
        else:
            # "First Last" format
            parts = clean_name.split()
            if len(parts) >= 2:
                # Last part is family name
                family = parts[-1]
                given_parts = parts[:-1]
                return {
                    'family': family,
                    'given': given_parts
                }
            elif len(parts) == 1:
                # Single name - use as family name
                return {
                    'family': parts[0],
                    'given': []
                }
            else:
                return {
                    'family': clean_name,
                    'given': []
                }
    
    def _create_practitioner_from_field(self, field: Dict[str, Any], patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR Practitioner resource from a legacy field.
        
        This is the fallback path for backward compatibility.
        
        Args:
            field: Dictionary containing label, value, confidence, etc.
            patient_id: Patient UUID for reference
            
        Returns:
            FHIR Practitioner resource dictionary or None if invalid
        """
        value = field.get('value')
        if not value or not isinstance(value, str) or not value.strip():
            self.logger.warning(f"Invalid or empty value in provider field: {field}")
            return None
        
        # Parse provider name
        name_parts = self._parse_provider_name(value.strip())
        
        # Create FHIR Practitioner resource from field
        practitioner = {
            "resourceType": "Practitioner",
            "id": str(uuid4()),
            "name": [{
                "text": value.strip(),
                "family": name_parts.get('family'),
                "given": name_parts.get('given', [])
            }],
            "meta": {
                "source": field.get('source_context', 'Document extraction'),
                "profile": ["http://hl7.org/fhir/StructureDefinition/Practitioner"],
                "versionId": "1",
                "lastUpdated": datetime.now().isoformat(),
                "tag": []
            }
        }
        
        # Add extraction confidence if available
        confidence = field.get('confidence')
        if confidence is not None:
            practitioner["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "extraction-confidence",
                "display": f"Extraction confidence: {confidence}"
            })
        
        self.logger.debug(f"Created Practitioner resource from legacy field: {value[:50]}...")
        return practitioner

