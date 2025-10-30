"""
Encounter Service for FHIR Resource Processing

This service handles the conversion of extracted encounter data into proper FHIR 
Encounter resources for visits, appointments, and healthcare interactions.
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4
from datetime import datetime
from apps.core.date_parser import ClinicalDateParser

logger = logging.getLogger(__name__)


class EncounterService:
    """
    Service for processing encounter data into FHIR Encounter resources.
    
    Handles various types of healthcare encounters including office visits,
    hospital admissions, emergency department visits, and telehealth encounters.
    """
    
    def __init__(self):
        self.logger = logger
        self.date_parser = ClinicalDateParser()
        
    def process_encounters(self, extracted_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process encounter data with complete visit and interaction information.
        
        Supports dual-format input:
        1. Structured Pydantic-derived dicts (primary path) - when Encounter model exists
        2. Legacy encounter/visit/appointment structures (fallback path)
        
        Args:
            extracted_data: Dictionary containing either:
                - 'structured_data' dict with 'encounters' list (future Encounter Pydantic models)
                - 'encounter', 'visit', or 'appointment' objects (legacy formats)
            
        Returns:
            FHIR Encounter resource or None if no encounter data found
        """
        patient_id = extracted_data.get('patient_id')
        
        if not patient_id:
            self.logger.warning("No patient_id provided for encounter processing")
            return None
        
        # PRIMARY PATH: Handle structured Pydantic data (when Encounter model is created in Phase 2)
        if 'structured_data' in extracted_data:
            structured_data = extracted_data['structured_data']
            if isinstance(structured_data, dict):
                # Check if encounters key exists (indicates structured format is intended)
                if 'encounters' in structured_data:
                    encounters_list = structured_data['encounters']
                    if encounters_list and len(encounters_list) > 0:
                        self.logger.info(f"Processing {len(encounters_list)} encounters via structured path")
                        # Process first encounter (typically documents have one primary encounter)
                        encounter_dict = encounters_list[0]
                        if isinstance(encounter_dict, dict):
                            encounter_resource = self._create_encounter_from_structured(encounter_dict, patient_id)
                            if encounter_resource:
                                self.logger.info(f"Successfully processed encounter via structured path")
                                return encounter_resource
                            else:
                                # Structured data was invalid, don't fall back to legacy
                                self.logger.warning(f"Invalid structured encounter data, no fallback")
                                return None
                    else:
                        # Encounters list is empty - structured format but no data
                        self.logger.info(f"No encounters in structured data")
                        return None
        
        # FALLBACK PATH: Handle legacy encounter data structures (only if structured_data not present)
        self.logger.warning(f"Falling back to legacy encounter processing")
        encounter_data = self._extract_encounter_data(extracted_data)
        
        if encounter_data:
            try:
                encounter_resource = self._create_encounter(encounter_data, patient_id)
                if encounter_resource:
                    self.logger.info(f"Created Encounter for: {encounter_data.get('type', 'Unknown encounter type')} via legacy path")
                    return encounter_resource
            except Exception as e:
                self.logger.error(f"Failed to create Encounter: {e}")
                
        return None
    
    def _create_encounter_from_structured(self, encounter_dict: Dict[str, Any], patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR Encounter resource from structured Pydantic-derived dict.
        
        This is the primary path for processing Encounter Pydantic models (once created in Phase 2).
        
        Args:
            encounter_dict: Dictionary from Encounter Pydantic model with fields:
                - encounter_id: Optional[str]
                - encounter_type: str (visit type)
                - encounter_date: Optional[str] (start date)
                - encounter_end_date: Optional[str] (end date)
                - location: Optional[str]
                - reason: Optional[str]
                - participants: List[str] (provider names)
                - status: Optional[str]
                - confidence: float
                - source: dict with text, start_index, end_index
            patient_id: Patient UUID for subject reference
            
        Returns:
            FHIR Encounter resource dictionary or None if invalid
        """
        encounter_type = encounter_dict.get('encounter_type')
        if not encounter_type or not isinstance(encounter_type, str):
            self.logger.warning(f"Invalid or missing encounter_type in structured data: {encounter_dict}")
            return None
        
        # Parse dates using ClinicalDateParser
        start_date = None
        end_date = None
        
        raw_start = encounter_dict.get('encounter_date')
        if raw_start:
            extracted_dates = self.date_parser.extract_dates(raw_start)
            if extracted_dates:
                best_date = max(extracted_dates, key=lambda x: x.confidence)
                start_date = best_date.extracted_date.isoformat()
                self.logger.debug(f"Parsed encounter start date {start_date}")
        
        raw_end = encounter_dict.get('encounter_end_date')
        if raw_end:
            extracted_dates = self.date_parser.extract_dates(raw_end)
            if extracted_dates:
                best_date = max(extracted_dates, key=lambda x: x.confidence)
                end_date = best_date.extracted_date.isoformat()
                self.logger.debug(f"Parsed encounter end date {end_date}")
        
        # Map encounter type to FHIR class codes
        type_lower = encounter_type.lower()
        type_mapping = {
            'office visit': ('AMB', 'Ambulatory'),
            'ambulatory': ('AMB', 'Ambulatory'),
            'outpatient': ('AMB', 'Ambulatory'),
            'emergency': ('EMER', 'Emergency'),
            'er': ('EMER', 'Emergency'),
            'inpatient': ('IMP', 'Inpatient encounter'),
            'hospital': ('IMP', 'Inpatient encounter'),
            'telehealth': ('VR', 'Virtual'),
            'virtual': ('VR', 'Virtual'),
            'home': ('HH', 'Home health')
        }
        
        class_code, class_display = ('AMB', 'Ambulatory')  # Default
        for key, (code, display) in type_mapping.items():
            if key in type_lower:
                class_code, class_display = code, display
                break
        
        # Map encounter status
        enc_status = encounter_dict.get('status', 'finished').lower()
        status_mapping = {
            'planned': 'planned',
            'arrived': 'arrived',
            'in-progress': 'in-progress',
            'onleave': 'onleave',
            'finished': 'finished',
            'cancelled': 'cancelled'
        }
        fhir_status = status_mapping.get(enc_status, 'finished')
        
        # Create FHIR Encounter resource
        encounter = {
            "resourceType": "Encounter",
            "id": encounter_dict.get('encounter_id') or str(uuid4()),
            "status": fhir_status,
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": class_code,
                "display": class_display
            },
            "subject": {
                "reference": f"Patient/{patient_id}"
            },
            "meta": {
                "source": "Structured Pydantic extraction",
                "profile": ["http://hl7.org/fhir/StructureDefinition/Encounter"],
                "versionId": "1",
                "lastUpdated": datetime.now().isoformat(),
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                    "code": "extraction-source",
                    "display": "Structured encounter path"
                }]
            }
        }
        
        # Add period if dates available
        if start_date or end_date:
            encounter["period"] = {}
            if start_date:
                encounter["period"]["start"] = start_date
            if end_date:
                encounter["period"]["end"] = end_date
        
        # Add location
        location = encounter_dict.get('location')
        if location:
            encounter["location"] = [{
                "location": {
                    "display": location.strip()
                }
            }]
        
        # Add reason for encounter
        reason = encounter_dict.get('reason')
        if reason:
            encounter["reasonCode"] = [{
                "text": reason.strip()
            }]
        
        # Add participants (providers)
        participants = encounter_dict.get('participants', [])
        if participants and isinstance(participants, list):
            encounter["participant"] = []
            for provider_name in participants:
                if provider_name and isinstance(provider_name, str):
                    encounter["participant"].append({
                        "individual": {
                            "display": provider_name.strip()
                        },
                        "type": [{
                            "coding": [{
                                "system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
                                "code": "ATND",
                                "display": "attender"
                            }]
                        }]
                    })
        
        # Add extraction confidence
        confidence = encounter_dict.get('confidence')
        if confidence is not None:
            encounter["extension"] = [{
                "url": "http://hl7.org/fhir/StructureDefinition/data-confidence",
                "valueDecimal": confidence
            }]
        
        # Add source context if available
        source = encounter_dict.get('source')
        if source and isinstance(source, dict):
            source_text = source.get('text', '')
            if source_text:
                if "note" not in encounter:
                    encounter["note"] = []
                encounter["note"].append({
                    "text": f"Source: {source_text[:200]}"
                })
        
        self.logger.debug(f"Created Encounter from structured data: {encounter_type[:50]}...")
        return encounter
        
    def _extract_encounter_data(self, extracted_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract encounter data from various possible structures in extracted data.
        
        Args:
            extracted_data: Raw extracted data that may contain encounter information
            
        Returns:
            Normalized encounter dictionary or None
        """
        encounter_data = None
        
        # Handle direct encounter object
        if 'encounter' in extracted_data and isinstance(extracted_data['encounter'], dict):
            encounter_data = extracted_data['encounter'].copy()
            
        # Handle visit information
        elif 'visit' in extracted_data and isinstance(extracted_data['visit'], dict):
            encounter_data = self._convert_visit_to_encounter(extracted_data['visit'])
            
        # Handle appointment information
        elif 'appointment' in extracted_data and isinstance(extracted_data['appointment'], dict):
            encounter_data = self._convert_appointment_to_encounter(extracted_data['appointment'])
            
        # Try to infer encounter from document metadata or fields
        else:
            encounter_data = self._infer_encounter_from_data(extracted_data)
            
        # Enhance encounter data with additional information from extracted data
        if encounter_data:
            encounter_data = self._enhance_encounter_data(encounter_data, extracted_data)
            
        return encounter_data
        
    def _convert_visit_to_encounter(self, visit: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a visit dictionary to encounter format.
        
        Args:
            visit: Visit data dictionary
            
        Returns:
            Encounter data dictionary
        """
        return {
            'type': visit.get('type', 'AMB'),
            'type_display': visit.get('type_display', 'Ambulatory'),
            'date': visit.get('date', visit.get('visit_date')),
            'end_date': visit.get('end_date'),
            'location': visit.get('location'),
            'provider': visit.get('provider'),
            'reason': visit.get('reason', visit.get('chief_complaint')),
            'source': 'visit_conversion'
        }
        
    def _convert_appointment_to_encounter(self, appointment: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert an appointment dictionary to encounter format.
        
        Args:
            appointment: Appointment data dictionary
            
        Returns:
            Encounter data dictionary
        """
        return {
            'type': 'AMB',
            'type_display': 'Ambulatory',
            'date': appointment.get('date', appointment.get('appointment_date')),
            'end_date': appointment.get('end_date'),
            'location': appointment.get('location'),
            'provider': appointment.get('provider'),
            'reason': appointment.get('reason', appointment.get('purpose')),
            'source': 'appointment_conversion'
        }
        
    def _infer_encounter_from_data(self, extracted_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Infer encounter information from other extracted data.
        
        Args:
            extracted_data: Raw extracted data
            
        Returns:
            Inferred encounter data dictionary or None
        """
        encounter_info = {}
        
        # Look for date information
        date_fields = ['document_date', 'visit_date', 'date_of_service', 'encounter_date']
        encounter_date = None
        
        for field in date_fields:
            if field in extracted_data and extracted_data[field]:
                encounter_date = extracted_data[field]
                break
                
        # Look in fields array for date information
        if not encounter_date and 'fields' in extracted_data:
            for field in extracted_data['fields']:
                if isinstance(field, dict):
                    label = field.get('label', '').lower()
                    if any(term in label for term in ['date', 'visit', 'encounter', 'service']):
                        encounter_date = field.get('value')
                        break
                        
        if encounter_date:
            encounter_info['date'] = encounter_date
            
        # Infer encounter type from document type or content
        encounter_type = self._infer_encounter_type(extracted_data)
        if encounter_type:
            encounter_info.update(encounter_type)
            
        # Look for provider information
        provider_info = self._extract_provider_info(extracted_data)
        if provider_info:
            encounter_info['provider'] = provider_info
            
        # Look for location information
        location_info = self._extract_location_info(extracted_data)
        if location_info:
            encounter_info['location'] = location_info
            
        # Look for chief complaint or reason for visit
        reason = self._extract_encounter_reason(extracted_data)
        if reason:
            encounter_info['reason'] = reason
            
        encounter_info['source'] = 'data_inference'
        
        return encounter_info if encounter_info else None
        
    def _infer_encounter_type(self, extracted_data: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """
        Infer the encounter type from document type or content.
        
        Args:
            extracted_data: Raw extracted data
            
        Returns:
            Dictionary with type and type_display or None
        """
        # Check document type
        doc_type = extracted_data.get('document_type', '').lower()
        
        if any(term in doc_type for term in ['discharge', 'hospital', 'admission']):
            return {'type': 'IMP', 'type_display': 'Inpatient encounter'}
        elif any(term in doc_type for term in ['emergency', 'er', 'ed']):
            return {'type': 'EMER', 'type_display': 'Emergency'}
        elif any(term in doc_type for term in ['outpatient', 'clinic', 'office']):
            return {'type': 'AMB', 'type_display': 'Ambulatory'}
        elif any(term in doc_type for term in ['telehealth', 'telemedicine', 'virtual']):
            return {'type': 'VR', 'type_display': 'Virtual'}
        elif any(term in doc_type for term in ['home', 'house call']):
            return {'type': 'HH', 'type_display': 'Home health'}
        else:
            # Default to ambulatory
            return {'type': 'AMB', 'type_display': 'Ambulatory'}
            
    def _extract_provider_info(self, extracted_data: Dict[str, Any]) -> Optional[str]:
        """
        Extract provider information from extracted data.
        
        Args:
            extracted_data: Raw extracted data
            
        Returns:
            Provider name or None
        """
        # Look for direct provider fields
        provider_fields = ['provider', 'physician', 'doctor', 'attending', 'practitioner']
        
        for field in provider_fields:
            if field in extracted_data and extracted_data[field]:
                return str(extracted_data[field])
                
        # Look in fields array
        if 'fields' in extracted_data:
            for field in extracted_data['fields']:
                if isinstance(field, dict):
                    label = field.get('label', '').lower()
                    if any(term in label for term in ['provider', 'physician', 'doctor', 'md', 'dr']):
                        return field.get('value')
                        
        return None
        
    def _extract_location_info(self, extracted_data: Dict[str, Any]) -> Optional[str]:
        """
        Extract location information from extracted data.
        
        Args:
            extracted_data: Raw extracted data
            
        Returns:
            Location name or None
        """
        # Look for direct location fields
        location_fields = ['location', 'facility', 'hospital', 'clinic', 'department']
        
        for field in location_fields:
            if field in extracted_data and extracted_data[field]:
                return str(extracted_data[field])
                
        # Look in fields array
        if 'fields' in extracted_data:
            for field in extracted_data['fields']:
                if isinstance(field, dict):
                    label = field.get('label', '').lower()
                    if any(term in label for term in ['location', 'facility', 'hospital', 'clinic']):
                        return field.get('value')
                        
        return None
        
    def _extract_encounter_reason(self, extracted_data: Dict[str, Any]) -> Optional[str]:
        """
        Extract reason for encounter from extracted data.
        
        Args:
            extracted_data: Raw extracted data
            
        Returns:
            Encounter reason or None
        """
        # Look for direct reason fields
        reason_fields = ['chief_complaint', 'reason_for_visit', 'presenting_complaint', 'reason']
        
        for field in reason_fields:
            if field in extracted_data and extracted_data[field]:
                return str(extracted_data[field])
                
        # Look in fields array
        if 'fields' in extracted_data:
            for field in extracted_data['fields']:
                if isinstance(field, dict):
                    label = field.get('label', '').lower()
                    if any(term in label for term in ['chief complaint', 'reason', 'presenting', 'complaint']):
                        return field.get('value')
                        
        # Use primary diagnosis as reason if available
        if 'diagnoses' in extracted_data and extracted_data['diagnoses']:
            if isinstance(extracted_data['diagnoses'], list) and len(extracted_data['diagnoses']) > 0:
                return str(extracted_data['diagnoses'][0])
            elif isinstance(extracted_data['diagnoses'], str):
                return extracted_data['diagnoses']
                
        return None
        
    def _enhance_encounter_data(self, encounter_data: Dict[str, Any], extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enhance encounter data with additional information from extracted data.
        
        Args:
            encounter_data: Base encounter data
            extracted_data: Full extracted data
            
        Returns:
            Enhanced encounter data
        """
        enhanced = encounter_data.copy()
        
        # Add provider if not present
        if not enhanced.get('provider'):
            provider = self._extract_provider_info(extracted_data)
            if provider:
                enhanced['provider'] = provider
                
        # Add location if not present
        if not enhanced.get('location'):
            location = self._extract_location_info(extracted_data)
            if location:
                enhanced['location'] = location
                
        # Add reason if not present
        if not enhanced.get('reason'):
            reason = self._extract_encounter_reason(extracted_data)
            if reason:
                enhanced['reason'] = reason
                
        return enhanced
        
    def _create_encounter(self, encounter_data: Dict[str, Any], patient_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        Create an Encounter resource from encounter information.
        
        Args:
            encounter_data: Encounter data dictionary
            patient_id: Patient ID for the resource
            
        Returns:
            FHIR Encounter resource or None if creation fails
        """
        try:
            encounter_id = str(uuid4())
            
            # Create basic Encounter resource structure
            encounter_resource = {
                "resourceType": "Encounter",
                "id": encounter_id,
                "status": encounter_data.get('status', 'finished'),
                "class": {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": encounter_data.get('type', 'AMB'),
                    "display": encounter_data.get('type_display', 'Ambulatory')
                },
                "meta": {
                    "versionId": "1",
                    "lastUpdated": datetime.now().isoformat(),
                    "source": f"EncounterService-{encounter_data.get('source', 'unknown')}"
                }
            }
            
            # Add patient reference if available
            if patient_id:
                encounter_resource["subject"] = {
                    "reference": f"Patient/{patient_id}"
                }
                
            # Add period (start and end times)
            period = {}
            if encounter_data.get('date'):
                period["start"] = encounter_data['date']
                
            if encounter_data.get('end_date'):
                period["end"] = encounter_data['end_date']
                
            if period:
                encounter_resource["period"] = period
                
            # Add reason for encounter
            if encounter_data.get('reason'):
                encounter_resource["reasonCode"] = [{
                    "text": encounter_data['reason']
                }]
                
            # Add location
            if encounter_data.get('location'):
                encounter_resource["location"] = [{
                    "location": {
                        "display": encounter_data['location']
                    }
                }]
                
            # Add participant (provider)
            if encounter_data.get('provider'):
                encounter_resource["participant"] = [{
                    "individual": {
                        "display": encounter_data['provider']
                    },
                    "type": [{
                        "coding": [{
                            "system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
                            "code": "ATND",
                            "display": "attender"
                        }]
                    }]
                }]
                
            # Add service type if it can be inferred
            service_type = self._determine_service_type(encounter_data)
            if service_type:
                encounter_resource["serviceType"] = {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/service-type",
                        "code": service_type['code'],
                        "display": service_type['display']
                    }]
                }
                
            # Add confidence as extension if available
            if encounter_data.get('confidence'):
                encounter_resource["extension"] = [{
                    "url": "http://hl7.org/fhir/StructureDefinition/data-confidence",
                    "valueDecimal": encounter_data['confidence']
                }]
                
            return encounter_resource
            
        except Exception as e:
            self.logger.error(f"Failed to create Encounter: {e}")
            return None
            
    def _determine_service_type(self, encounter_data: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """
        Determine the appropriate service type for an encounter.
        
        Args:
            encounter_data: Encounter data dictionary
            
        Returns:
            Dictionary with service type code and display, or None
        """
        encounter_type = encounter_data.get('type', '').lower()
        reason = encounter_data.get('reason', '').lower()
        provider = encounter_data.get('provider', '').lower()
        
        # Check for specific service types based on various indicators
        if any(term in reason for term in ['cardiology', 'heart', 'cardiac']):
            return {'code': '165', 'display': 'Cardiology'}
        elif any(term in reason for term in ['neurology', 'neuro', 'brain']):
            return {'code': '315', 'display': 'Neurology'}
        elif any(term in provider for term in ['cardiologist']):
            return {'code': '165', 'display': 'Cardiology'}
        elif any(term in provider for term in ['neurologist']):
            return {'code': '315', 'display': 'Neurology'}
        elif encounter_type == 'emer':
            return {'code': '663', 'display': 'Emergency Department'}
        else:
            return {'code': '124', 'display': 'General Practice'}
