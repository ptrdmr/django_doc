"""
Medication Service for FHIR Resource Processing

This service handles the conversion of extracted medication data into proper FHIR 
MedicationStatement resources with complete dosage, route, and schedule information.
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4
from datetime import datetime
from apps.core.date_parser import ClinicalDateParser

logger = logging.getLogger(__name__)


class MedicationService:
    """
    Service for processing medication data into FHIR MedicationStatement resources.
    
    This service ensures 100% capture of medication data by properly converting
    all extracted medication information into structured FHIR resources.
    """
    
    def __init__(self):
        self.logger = logger
        self.date_parser = ClinicalDateParser()
        
    def process_medications(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process all medications with complete dosage and schedule information.
        
        Supports dual-format input:
        1. Structured Pydantic-derived dicts (primary path)
        2. Legacy extraction formats (fallback path)
        
        Args:
            extracted_data: Dictionary containing either:
                - 'structured_data' dict with 'medications' list (Pydantic Medication models)
                - 'medications' list or 'fields' list (legacy formats)
            
        Returns:
            List of FHIR MedicationStatement resources
        """
        medications = []
        patient_id = extracted_data.get('patient_id')
        
        if not patient_id:
            self.logger.warning("No patient_id provided for medication processing")
            return medications
        
        # PRIMARY PATH: Handle structured Pydantic data
        if 'structured_data' in extracted_data:
            structured_data = extracted_data['structured_data']
            if isinstance(structured_data, dict) and 'medications' in structured_data:
                medications_list = structured_data['medications']
                if medications_list:
                    self.logger.info(f"Processing {len(medications_list)} medications via structured path")
                    for med_dict in medications_list:
                        if isinstance(med_dict, dict):
                            med_resource = self._create_medication_from_structured(med_dict, patient_id)
                            if med_resource:
                                medications.append(med_resource)
                    self.logger.info(f"Successfully processed {len(medications)} medications via structured path")
                    return medications
        
        # FALLBACK PATH: Handle legacy formats
        self.logger.warning(f"Falling back to legacy processing for medications")
        medication_data = self._extract_medication_data(extracted_data)
        
        for med_data in medication_data:
            try:
                med_resource = self._create_medication_statement(med_data, patient_id)
                if med_resource:
                    medications.append(med_resource)
                    self.logger.info(f"Created MedicationStatement for: {med_data.get('name', 'Unknown medication')}")
            except Exception as e:
                self.logger.error(f"Failed to create MedicationStatement for {med_data}: {e}")
                continue
                
        self.logger.info(f"Processed {len(medications)} medications from {len(medication_data)} extracted entries via legacy path")
        return medications
    
    def _create_medication_from_structured(self, med_dict: Dict[str, Any], patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR MedicationStatement resource from structured Pydantic-derived dict.
        
        This is the primary path for processing Medication Pydantic models.
        
        Args:
            med_dict: Dictionary from Medication Pydantic model with fields:
                - name: str (medication name)
                - dosage: Optional[str] (dosage amount)
                - route: Optional[str] (route of administration)
                - frequency: Optional[str] (dosing frequency)
                - status: str (active, stopped, etc.)
                - start_date: Optional[str] (when started)
                - stop_date: Optional[str] (when stopped)
                - confidence: float (0.0-1.0)
                - source: dict with text, start_index, end_index
            patient_id: Patient UUID for subject reference
            
        Returns:
            FHIR MedicationStatement resource dictionary or None if invalid
        """
        name = med_dict.get('name')
        if not name or not isinstance(name, str) or not name.strip():
            self.logger.warning(f"Invalid or empty medication name: {med_dict}")
            return None
        
        # Parse dates using ClinicalDateParser
        start_date = None
        stop_date = None
        
        raw_start = med_dict.get('start_date')
        if raw_start:
            extracted_dates = self.date_parser.extract_dates(raw_start)
            if extracted_dates:
                best_date = max(extracted_dates, key=lambda x: x.confidence)
                start_date = best_date.extracted_date.isoformat()
                self.logger.debug(f"Parsed medication start date {start_date}")
        
        raw_stop = med_dict.get('stop_date')
        if raw_stop:
            extracted_dates = self.date_parser.extract_dates(raw_stop)
            if extracted_dates:
                best_date = max(extracted_dates, key=lambda x: x.confidence)
                stop_date = best_date.extracted_date.isoformat()
                self.logger.debug(f"Parsed medication stop date {stop_date}")
        
        # Map medication status
        med_status = med_dict.get('status', 'active').lower()
        status_mapping = {
            'active': 'active',
            'stopped': 'stopped',
            'completed': 'completed',
            'on-hold': 'on-hold',
            'intended': 'intended'
        }
        fhir_status = status_mapping.get(med_status, 'active')
        
        # Create FHIR MedicationStatement resource
        medication = {
            "resourceType": "MedicationStatement",
            "id": str(uuid4()),
            "status": fhir_status,
            "medicationCodeableConcept": {
                "text": name.strip()
            },
            "subject": {
                "reference": f"Patient/{patient_id}"
            },
            "meta": {
                "source": "Structured Pydantic extraction",
                "profile": ["http://hl7.org/fhir/StructureDefinition/MedicationStatement"],
                "versionId": "1",
                "lastUpdated": datetime.now().isoformat(),
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                    "code": "extraction-source",
                    "display": "Structured data path"
                }]
            }
        }
        
        # Add dosage information if available
        dosage_info = {}
        
        dosage = med_dict.get('dosage')
        if dosage:
            dosage_info["text"] = dosage.strip()
        
        frequency = med_dict.get('frequency')
        if frequency:
            dosage_info["timing"] = {
                "code": {
                    "text": frequency.strip()
                }
            }
        
        route = med_dict.get('route')
        if route:
            dosage_info["route"] = {
                "text": route.strip()
            }
        
        # Add dosage to resource if we have any dosage information
        if dosage_info:
            medication["dosage"] = [dosage_info]
        
        # Add effective period if dates available
        if start_date or stop_date:
            medication["effectivePeriod"] = {}
            if start_date:
                medication["effectivePeriod"]["start"] = start_date
            if stop_date:
                medication["effectivePeriod"]["end"] = stop_date
        
        # Add extraction confidence
        confidence = med_dict.get('confidence')
        if confidence is not None:
            medication["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "extraction-confidence",
                "display": f"Extraction confidence: {confidence}"
            })
        
        # Add source context if available
        source = med_dict.get('source')
        if source and isinstance(source, dict):
            source_text = source.get('text', '')
            if source_text:
                medication["note"] = [{
                    "text": f"Source: {source_text[:200]}"
                }]
        
        self.logger.debug(f"Created MedicationStatement from structured data: {name[:50]}...")
        return medication
        
    def _extract_medication_data(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract medication data from various possible structures in extracted data.
        
        Args:
            extracted_data: Raw extracted data that may contain medications in different formats
            
        Returns:
            List of normalized medication dictionaries
        """
        medication_data = []
        
        # Handle direct medications list
        if 'medications' in extracted_data and isinstance(extracted_data['medications'], list):
            medication_data.extend(extracted_data['medications'])
            
        # Handle medication fields from document analyzer
        if 'fields' in extracted_data:
            for field in extracted_data['fields']:
                if isinstance(field, dict):
                    label = field.get('label', '').lower()
                    if any(term in label for term in ['medication', 'drug', 'prescription']):
                        # Convert field to medication format
                        med_data = self._convert_field_to_medication(field)
                        if med_data:
                            medication_data.append(med_data)
                            
        # Handle string-based medication lists (semicolon or comma separated)
        if 'medications' in extracted_data and isinstance(extracted_data['medications'], str):
            string_meds = self._parse_medication_string(extracted_data['medications'])
            medication_data.extend(string_meds)
            
        return medication_data
        
    def _convert_field_to_medication(self, field: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert a document analyzer field into a medication dictionary.
        
        Args:
            field: Field dictionary from document analyzer
            
        Returns:
            Normalized medication dictionary or None
        """
        value = field.get('value', '')
        if not value:
            return None
            
        # Parse medication information from the field value
        med_info = self._parse_medication_text(value)
        if med_info['name']:
            return {
                'name': med_info['name'],
                'dosage': med_info.get('dosage'),
                'route': med_info.get('route'),
                'schedule': med_info.get('schedule'),
                'confidence': field.get('confidence', 0.8),
                'source': 'document_field'
            }
        return None
        
    def _parse_medication_string(self, medication_string: str) -> List[Dict[str, Any]]:
        """
        Parse a semicolon or comma-separated string of medications.
        
        Args:
            medication_string: String containing multiple medications
            
        Returns:
            List of medication dictionaries
        """
        medications = []
        
        # Split by semicolon or comma
        separators = [';', ',']
        items = [medication_string]
        
        for sep in separators:
            new_items = []
            for item in items:
                new_items.extend([i.strip() for i in item.split(sep) if i.strip()])
            items = new_items
            
        for item in items:
            med_info = self._parse_medication_text(item)
            if med_info['name']:
                medications.append({
                    'name': med_info['name'],
                    'dosage': med_info.get('dosage'),
                    'route': med_info.get('route'),
                    'schedule': med_info.get('schedule'),
                    'source': 'string_parsing'
                })
                
        return medications
        
    def _parse_medication_text(self, text: str) -> Dict[str, Any]:
        """
        Parse medication information from a text string.
        
        Args:
            text: Text containing medication information
            
        Returns:
            Dictionary with parsed medication components
        """
        import re
        
        text = text.strip()
        if not text:
            return {'name': None}
            
        # Initialize result
        result = {
            'name': None,
            'dosage': None,
            'route': None,
            'schedule': None
        }
        
        # Common dosage patterns
        dosage_patterns = [
            r'(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|units?|iu)\b',
            r'(\d+(?:\.\d+)?/\d+(?:\.\d+)?)\s*(mg|mcg|g|ml)\b',
            r'(\d+)\s*(tablet|capsule|pill)s?\b'
        ]
        
        # Common route patterns
        route_patterns = [
            r'\b(oral|orally|po|by mouth)\b',
            r'\b(iv|intravenous|intravenously)\b',
            r'\b(im|intramuscular|intramuscularly)\b',
            r'\b(sc|sq|subcutaneous|subcutaneously)\b',
            r'\b(topical|topically)\b',
            r'\b(sublingual|sl)\b'
        ]
        
        # Common schedule patterns (ordered from most specific to least specific)
        schedule_patterns = [
            r'\b(with meals|after meals|before meals)\b',
            r'\b(as needed|prn|p\.r\.n\.)\b',
            r'\b(every \d+ hours?|q\d+h)\b',
            r'\b(four times daily|qid|q\.i\.d\.)\b',
            r'\b(three times daily|tid|t\.i\.d\.)\b',
            r'\b(twice daily|bid|b\.i\.d\.)\b',
            r'\b(once daily|daily|qd|q24h)\b'
        ]
        
        text_lower = text.lower()
        
        # Extract dosage
        for pattern in dosage_patterns:
            match = re.search(pattern, text_lower)
            if match:
                result['dosage'] = match.group(0)
                break
                
        # Extract route
        for pattern in route_patterns:
            match = re.search(pattern, text_lower)
            if match:
                result['route'] = match.group(1)
                break
                
        # Extract schedule
        for pattern in schedule_patterns:
            match = re.search(pattern, text_lower)
            if match:
                result['schedule'] = match.group(0)
                break
                
        # Extract medication name (everything before the first dosage, route, or schedule indicator)
        name_text = text
        
        # Find the first occurrence of any dosage, route, or schedule pattern
        # and use everything before it as the medication name
        first_match_pos = len(text)
        
        # Check dosage patterns
        for pattern in dosage_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                first_match_pos = min(first_match_pos, match.start())
                
        # Check route patterns  
        for pattern in route_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                first_match_pos = min(first_match_pos, match.start())
                
        # Check schedule patterns
        for pattern in schedule_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                first_match_pos = min(first_match_pos, match.start())
                
        # Extract the medication name (everything before the first pattern match)
        if first_match_pos < len(text):
            name_text = text[:first_match_pos].strip()
        else:
            name_text = text.strip()
            
        # Clean up the name
        name_text = re.sub(r'\s+', ' ', name_text).strip()
        name_text = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', name_text)
        
        if name_text:
            result['name'] = name_text
        else:
            # Fallback: use the original text as name
            result['name'] = text
            
        return result
        
    def _create_medication_statement(self, med_data: Dict[str, Any], patient_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        Create a MedicationStatement resource from medication information.
        
        Args:
            med_data: Medication data dictionary
            patient_id: Patient ID for the resource
            
        Returns:
            FHIR MedicationStatement resource or None if creation fails
        """
        try:
            med_name = med_data.get('name')
            if not med_name:
                self.logger.warning("Medication missing name, skipping")
                return None
                
            medication_id = str(uuid4())
            
            # Create basic MedicationStatement resource structure
            med_resource = {
                "resourceType": "MedicationStatement",
                "id": medication_id,
                "status": "active",
                "medicationCodeableConcept": {
                    "text": med_name
                },
                "meta": {
                    "versionId": "1",
                    "lastUpdated": datetime.now().isoformat(),
                    "source": f"MedicationService-{med_data.get('source', 'unknown')}"
                }
            }
            
            # Add patient reference if available
            if patient_id:
                med_resource["subject"] = {
                    "reference": f"Patient/{patient_id}"
                }
                
            # Add dosage information if available
            dosage_info = {}
            
            if med_data.get('dosage'):
                dosage_info["text"] = med_data['dosage']
                
            if med_data.get('schedule'):
                dosage_info["timing"] = {
                    "code": {
                        "text": med_data['schedule']
                    }
                }
                
            if med_data.get('route'):
                dosage_info["route"] = {
                    "text": med_data['route']
                }
                
            # Add dosage to resource if we have any dosage information
            if dosage_info:
                med_resource["dosage"] = [dosage_info]
                
            # Add medication code if available
            if med_data.get('code'):
                med_resource["medicationCodeableConcept"]["coding"] = [{
                    "code": med_data['code'],
                    "display": med_name
                }]
                
            # Add confidence as extension if available
            if med_data.get('confidence'):
                med_resource["extension"] = [{
                    "url": "http://hl7.org/fhir/StructureDefinition/data-confidence",
                    "valueDecimal": med_data['confidence']
                }]
                
            return med_resource
            
        except Exception as e:
            self.logger.error(f"Failed to create MedicationStatement: {e}")
            return None
