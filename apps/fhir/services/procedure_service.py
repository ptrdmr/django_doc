"""
Procedure Service for FHIR Resource Processing

This service handles the conversion of extracted procedure data into proper FHIR 
Procedure resources with performer information, dates, and outcomes.
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4
from datetime import datetime
from apps.core.date_parser import ClinicalDateParser

logger = logging.getLogger(__name__)


class ProcedureService:
    """
    Service for processing procedure data into FHIR Procedure resources.
    
    This service ensures complete capture of procedure/intervention data by properly 
    converting all extracted procedure information into structured FHIR resources.
    """
    
    def __init__(self):
        self.logger = logger
        self.date_parser = ClinicalDateParser()
        
    def process_procedures(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process all procedures from extracted data into FHIR Procedure resources.
        
        Supports dual-format input:
        1. Structured Pydantic-derived dicts (primary path)
        2. Legacy 'fields' list (fallback path)
        
        Args:
            extracted_data: Dictionary containing either:
                - 'structured_data' dict with 'procedures' list (Pydantic Procedure models)
                - 'fields' list with procedure data (legacy format)
            
        Returns:
            List of FHIR Procedure resources
        """
        procedures = []
        patient_id = extracted_data.get('patient_id')
        
        if not patient_id:
            self.logger.warning("No patient_id provided for procedure processing")
            return procedures
        
        # PRIMARY PATH: Handle structured Pydantic data
        if 'structured_data' in extracted_data:
            structured_data = extracted_data['structured_data']
            if isinstance(structured_data, dict) and 'procedures' in structured_data:
                procedures_list = structured_data['procedures']
                if procedures_list:
                    self.logger.info(f"Processing {len(procedures_list)} procedures via structured path")
                    for procedure_dict in procedures_list:
                        if isinstance(procedure_dict, dict):
                            procedure_resource = self._create_procedure_from_structured(procedure_dict, patient_id)
                            if procedure_resource:
                                procedures.append(procedure_resource)
                    self.logger.info(f"Successfully processed {len(procedures)} procedures via structured path")
                    return procedures
        
        # FALLBACK PATH: Handle legacy fields list format
        if 'fields' in extracted_data:
            self.logger.warning(f"Falling back to legacy fields processing for procedures")
            self.logger.info(f"Processing {len(extracted_data['fields'])} fields for procedures")
            
            for field in extracted_data['fields']:
                if isinstance(field, dict):
                    label = field.get('label', '').lower()
                    if 'procedure' in label or 'surgery' in label or 'intervention' in label:
                        self.logger.debug(f"Found procedure field: {label}")
                        procedure_resource = self._create_procedure_from_field(field, patient_id)
                        if procedure_resource:
                            procedures.append(procedure_resource)
                            self.logger.debug(f"Created procedure resource for {label}")
        
        self.logger.info(f"Successfully processed {len(procedures)} procedure resources via legacy path")
        return procedures
    
    def _create_procedure_from_structured(self, procedure_dict: Dict[str, Any], patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR Procedure resource from structured Pydantic-derived dict.
        
        This is the primary path for processing Procedure Pydantic models.
        
        Args:
            procedure_dict: Dictionary from Procedure Pydantic model with fields:
                - name: str (procedure name)
                - procedure_date: Optional[str] (when procedure was performed)
                - provider: Optional[str] (provider who performed it)
                - outcome: Optional[str] (outcome or result)
                - confidence: float (0.0-1.0)
                - source: dict with text, start_index, end_index
            patient_id: Patient UUID for subject reference
            
        Returns:
            FHIR Procedure resource dictionary or None if invalid
        """
        name = procedure_dict.get('name')
        if not name or not isinstance(name, str) or not name.strip():
            self.logger.warning(f"Invalid or empty procedure name: {procedure_dict}")
            return None
        
        # Parse procedure date using ClinicalDateParser
        performed_date = None
        date_source = "structured"
        raw_date = procedure_dict.get('procedure_date')
        
        if raw_date:
            # Use ClinicalDateParser for consistent date handling
            extracted_dates = self.date_parser.extract_dates(raw_date)
            if extracted_dates:
                best_date = max(extracted_dates, key=lambda x: x.confidence)
                performed_date = best_date.extracted_date.isoformat()
                self.logger.debug(f"Parsed procedure date {performed_date} with confidence {best_date.confidence}")
        
        # Create FHIR Procedure resource
        procedure = {
            "resourceType": "Procedure",
            "id": str(uuid4()),
            "status": "completed",  # Default to completed for documented procedures
            "code": {
                "text": name.strip()
            },
            "subject": {
                "reference": f"Patient/{patient_id}"
            },
            "meta": {
                "source": "Structured Pydantic extraction",
                "profile": ["http://hl7.org/fhir/StructureDefinition/Procedure"],
                "versionId": "1",
                "lastUpdated": datetime.now().isoformat(),
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                    "code": "extraction-source",
                    "display": "Structured data path"
                }]
            }
        }
        
        # Add performed date if available
        if performed_date:
            procedure["performedDateTime"] = performed_date
            procedure["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "date-source",
                "display": f"Date source: {date_source}"
            })
        
        # Add performer (provider) if available
        provider = procedure_dict.get('provider')
        if provider and isinstance(provider, str):
            procedure["performer"] = [{
                "actor": {
                    "display": provider.strip()
                }
            }]
        
        # Add outcome if available
        outcome = procedure_dict.get('outcome')
        if outcome and isinstance(outcome, str):
            procedure["outcome"] = {
                "text": outcome.strip()
            }
        
        # Add extraction confidence
        confidence = procedure_dict.get('confidence')
        if confidence is not None:
            procedure["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "extraction-confidence",
                "display": f"Extraction confidence: {confidence}"
            })
        
        # Add source context if available
        source = procedure_dict.get('source')
        if source and isinstance(source, dict):
            source_text = source.get('text', '')
            if source_text:
                procedure["note"] = [{
                    "text": f"Source: {source_text[:200]}"
                }]
        
        self.logger.debug(f"Created Procedure resource from structured data: {name[:50]}...")
        return procedure
    
    def _create_procedure_from_field(self, field: Dict[str, Any], patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR Procedure resource from a legacy field.
        
        This is the fallback path for backward compatibility.
        
        Args:
            field: Dictionary containing label, value, confidence, etc.
            patient_id: Patient UUID for subject reference
            
        Returns:
            FHIR Procedure resource dictionary or None if invalid
        """
        value = field.get('value')
        if not value or not isinstance(value, str) or not value.strip():
            self.logger.warning(f"Invalid or empty value in procedure field: {field}")
            return None
        
        # Try to extract date from value text
        performed_date = None
        date_source = "unknown"
        
        extracted_dates = self.date_parser.extract_dates(value)
        if extracted_dates:
            # Use the highest confidence date
            best_date = max(extracted_dates, key=lambda x: x.confidence)
            performed_date = best_date.extracted_date.isoformat()
            date_source = "extracted"
            self.logger.debug(f"Extracted procedure date {performed_date} with confidence {best_date.confidence}")
        
        # Create FHIR Procedure resource from field
        procedure = {
            "resourceType": "Procedure",
            "id": str(uuid4()),
            "status": "completed",
            "code": {
                "text": value.strip()
            },
            "subject": {
                "reference": f"Patient/{patient_id}"
            },
            "meta": {
                "source": field.get('source_context', 'Document extraction'),
                "profile": ["http://hl7.org/fhir/StructureDefinition/Procedure"],
                "versionId": "1",
                "lastUpdated": datetime.now().isoformat(),
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                    "code": "date-source",
                    "display": f"Date source: {date_source}"
                }]
            }
        }
        
        # Add performed date if available
        if performed_date:
            procedure["performedDateTime"] = performed_date
        
        # Add extraction confidence if available
        confidence = field.get('confidence')
        if confidence is not None:
            procedure["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "extraction-confidence",
                "display": f"Extraction confidence: {confidence}"
            })
        
        self.logger.debug(f"Created Procedure resource from legacy field: {value[:50]}...")
        return procedure

