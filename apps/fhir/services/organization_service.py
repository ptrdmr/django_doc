"""
Organization Service for FHIR Resource Processing

This service handles the conversion of extracted organization data into proper FHIR 
Organization resources with name, type, address, and contact information.
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4
from datetime import datetime
from apps.core.date_parser import ClinicalDateParser

logger = logging.getLogger(__name__)


class OrganizationService:
    """
    Service for processing organization data into FHIR Organization resources.
    
    This service ensures complete capture of organization data by properly converting
    all extracted healthcare facility information into structured FHIR resources.
    """
    
    def __init__(self):
        self.logger = logger
        self.date_parser = ClinicalDateParser()
        
    def process_organizations(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process all organizations from extracted data into FHIR Organization resources.
        
        Supports dual-format input:
        1. Structured Pydantic-derived dicts (primary path)
        2. Legacy 'fields' list (fallback path)
        
        Args:
            extracted_data: Dictionary containing either:
                - 'structured_data' dict with 'organizations' list (Pydantic Organization models)
                - 'fields' list with organization data (legacy format)
            
        Returns:
            List of FHIR Organization resources
        """
        organizations = []
        patient_id = extracted_data.get('patient_id')
        
        if not patient_id:
            self.logger.warning("No patient_id provided for organization processing")
            return organizations
        
        # PRIMARY PATH: Handle structured Pydantic data
        if 'structured_data' in extracted_data:
            structured_data = extracted_data['structured_data']
            if isinstance(structured_data, dict) and 'organizations' in structured_data:
                orgs_list = structured_data['organizations']
                if orgs_list:
                    self.logger.info(f"Processing {len(orgs_list)} organizations via structured path")
                    for org_dict in orgs_list:
                        if isinstance(org_dict, dict):
                            org_resource = self._create_organization_from_structured(org_dict, patient_id)
                            if org_resource:
                                organizations.append(org_resource)
                    self.logger.info(f"Successfully processed {len(organizations)} organizations via structured path")
                    return organizations
        
        # FALLBACK PATH: Handle legacy fields list format
        if 'fields' in extracted_data:
            self.logger.warning(f"Falling back to legacy fields processing for organizations")
            self.logger.info(f"Processing {len(extracted_data['fields'])} fields for organizations")
            
            for field in extracted_data['fields']:
                if isinstance(field, dict):
                    label = field.get('label', '').lower()
                    if any(term in label for term in ['hospital', 'clinic', 'facility', 'organization', 'lab', 'center']):
                        self.logger.debug(f"Found organization field: {label}")
                        org_resource = self._create_organization_from_field(field, patient_id)
                        if org_resource:
                            organizations.append(org_resource)
                            self.logger.debug(f"Created organization resource for {label}")
        
        self.logger.info(f"Successfully processed {len(organizations)} organization resources via legacy path")
        return organizations
    
    def _create_organization_from_structured(self, org_dict: Dict[str, Any], patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR Organization resource from structured Pydantic-derived dict.
        
        Args:
            org_dict: Dictionary from Organization Pydantic model with fields:
                - name: str (organization name)
                - identifier: Optional[str] (NPI, tax ID, etc.)
                - organization_type: Optional[str] (hospital, clinic, lab, etc.)
                - address: Optional[str]
                - city, state, postal_code: Optional[str]
                - phone: Optional[str]
                - confidence: float (0.0-1.0)
                - source: dict
            patient_id: Patient UUID (for context/logging)
            
        Returns:
            FHIR Organization resource or None
        """
        name = org_dict.get('name')
        if not name or not isinstance(name, str) or not name.strip():
            self.logger.warning(f"Invalid or empty organization name: {org_dict}")
            return None
        
        # Create FHIR Organization resource
        organization = {
            "resourceType": "Organization",
            "id": str(uuid4()),
            "name": name.strip(),
            "meta": {
                "source": "Structured Pydantic extraction",
                "profile": ["http://hl7.org/fhir/StructureDefinition/Organization"],
                "versionId": "1",
                "lastUpdated": datetime.now().isoformat(),
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                    "code": "extraction-source",
                    "display": "Structured data path"
                }]
            }
        }
        
        # Add identifier if available
        identifier = org_dict.get('identifier')
        if identifier and isinstance(identifier, str):
            organization["identifier"] = [{
                "value": identifier.strip()
            }]
        
        # Add organization type if available
        org_type = org_dict.get('organization_type')
        if org_type and isinstance(org_type, str):
            type_mapping = {
                'hospital': ('prov', 'Healthcare Provider'),
                'clinic': ('prov', 'Healthcare Provider'),
                'lab': ('dept', 'Hospital Department'),
                'pharmacy': ('prov', 'Healthcare Provider'),
                'payer': ('pay', 'Payer')
            }
            
            type_lower = org_type.lower()
            code, display = ('prov', 'Healthcare Provider')  # Default
            for key, (c, d) in type_mapping.items():
                if key in type_lower:
                    code, display = c, d
                    break
            
            organization["type"] = [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/organization-type",
                    "code": code,
                    "display": display
                }],
                "text": org_type.strip()
            }]
        
        # Build address if components available
        address_parts = []
        line_parts = []
        
        address = org_dict.get('address')
        if address:
            line_parts.append(address.strip())
        
        city = org_dict.get('city')
        state = org_dict.get('state')
        postal_code = org_dict.get('postal_code')
        
        if line_parts or city or state or postal_code:
            org_address = {}
            if line_parts:
                org_address["line"] = line_parts
            if city:
                org_address["city"] = city.strip()
            if state:
                org_address["state"] = state.strip()
            if postal_code:
                org_address["postalCode"] = postal_code.strip()
            
            organization["address"] = [org_address]
        
        # Add telecom (phone) if available
        phone = org_dict.get('phone')
        if phone and isinstance(phone, str):
            organization["telecom"] = [{
                "system": "phone",
                "value": phone.strip()
            }]
        
        # Add confidence
        confidence = org_dict.get('confidence')
        if confidence is not None:
            if "extension" not in organization:
                organization["extension"] = []
            organization["extension"].append({
                "url": "http://hl7.org/fhir/StructureDefinition/data-confidence",
                "valueDecimal": confidence
            })
        
        # Add source context
        source = org_dict.get('source')
        if source and isinstance(source, dict):
            source_text = source.get('text', '')
            if source_text:
                if "contact" not in organization:
                    organization["contact"] = []
                organization["contact"].append({
                    "purpose": {
                        "text": f"Source: {source_text[:200]}"
                    }
                })
        
        self.logger.debug(f"Created Organization from structured data: {name[:50]}...")
        return organization
    
    def _create_organization_from_field(self, field: Dict[str, Any], patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR Organization resource from a legacy field.
        
        Args:
            field: Dictionary containing label, value, confidence, etc.
            patient_id: Patient UUID (for context)
            
        Returns:
            FHIR Organization resource or None
        """
        value = field.get('value')
        if not value or not isinstance(value, str) or not value.strip():
            self.logger.warning(f"Invalid or empty value in organization field: {field}")
            return None
        
        # Create basic Organization from field
        organization = {
            "resourceType": "Organization",
            "id": str(uuid4()),
            "name": value.strip(),
            "meta": {
                "source": field.get('source_context', 'Document extraction'),
                "profile": ["http://hl7.org/fhir/StructureDefinition/Organization"],
                "versionId": "1",
                "lastUpdated": datetime.now().isoformat(),
                "tag": []
            }
        }
        
        # Add confidence if available
        confidence = field.get('confidence')
        if confidence is not None:
            organization["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "extraction-confidence",
                "display": f"Extraction confidence: {confidence}"
            })
        
        self.logger.debug(f"Created Organization from legacy field: {value[:50]}...")
        return organization

