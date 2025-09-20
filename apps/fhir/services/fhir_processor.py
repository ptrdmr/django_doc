"""
Comprehensive FHIR Processing Pipeline

This module provides the main FHIRProcessor class that integrates all individual
FHIR resource services to process extracted clinical data into complete FHIR resources.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from .medication_service import MedicationService
from .diagnostic_report_service import DiagnosticReportService
from .service_request_service import ServiceRequestService
from .encounter_service import EncounterService
from .condition_service import ConditionService
from .observation_service import ObservationService

logger = logging.getLogger(__name__)


class FHIRProcessor:
    """
    Main FHIR processing pipeline that orchestrates all individual resource services
    to convert extracted clinical data into comprehensive FHIR resources.
    
    This processor is designed to achieve 90%+ data capture by processing all
    supported FHIR resource types through specialized service classes.
    """
    
    def __init__(self):
        """Initialize all resource service instances."""
        self.medication_service = MedicationService()
        self.diagnostic_report_service = DiagnosticReportService()
        self.service_request_service = ServiceRequestService()
        self.encounter_service = EncounterService()
        self.condition_service = ConditionService()
        self.observation_service = ObservationService()
        
        # TODO: Initialize additional services when implemented
        # self.care_plan_service = CarePlanService()
        # self.organization_service = OrganizationService()
        # self.practitioner_service = PractitionerService()
        # self.procedure_service = ProcedureService()
        # self.allergy_service = AllergyService()
        
        logger.info("FHIRProcessor initialized with all available resource services")
    
    def process_extracted_data(self, extracted_data: Dict[str, Any], 
                             patient_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Process all extracted clinical data into FHIR resources.
        
        Args:
            extracted_data: Dictionary containing extracted clinical data from AI
            patient_id: Optional patient ID to associate with resources
            
        Returns:
            List of FHIR resource dictionaries
        """
        if not extracted_data:
            logger.warning("No extracted data provided to process")
            return []
            
        logger.info(f"Processing extracted data with {len(extracted_data)} categories")
        fhir_resources = []
        processing_stats = {
            'total_categories': len(extracted_data),
            'processed_categories': 0,
            'total_resources': 0,
            'errors': []
        }
        
        # Ensure patient_id is available in the data
        if patient_id:
            extracted_data['patient_id'] = patient_id
        
        try:
            # Process medications (highest priority for 100% capture)
            medications = self._process_medications(extracted_data)
            if medications:
                fhir_resources.extend(medications)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(medications)} medication resources")
            
            # Process diagnostic reports
            diagnostic_reports = self._process_diagnostic_reports(extracted_data)
            if diagnostic_reports:
                fhir_resources.extend(diagnostic_reports)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(diagnostic_reports)} diagnostic report resources")
            
            # Process service requests
            service_requests = self._process_service_requests(extracted_data)
            if service_requests:
                fhir_resources.extend(service_requests)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(service_requests)} service request resources")
            
            # Process encounter information
            encounter = self._process_encounter(extracted_data)
            if encounter:
                fhir_resources.append(encounter)
                processing_stats['processed_categories'] += 1
                logger.info("Processed encounter resource")
            
            # Process conditions (diagnosis fields)
            conditions = self._process_conditions(extracted_data)
            if conditions:
                fhir_resources.extend(conditions)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(conditions)} condition resources")
            
            # Process observations (vital sign fields)
            observations = self._process_observations(extracted_data)
            if observations:
                fhir_resources.extend(observations)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(observations)} observation resources")
            
            # TODO: Process additional resource types when services are implemented
            # care_plans = self._process_care_plans(extracted_data)
            # organizations = self._process_organizations(extracted_data)
            # practitioners = self._process_practitioners(extracted_data)
            # procedures = self._process_procedures(extracted_data)
            # allergies = self._process_allergies(extracted_data)
            
            processing_stats['total_resources'] = len(fhir_resources)
            
            logger.info(
                f"FHIR processing completed: {processing_stats['total_resources']} resources "
                f"from {processing_stats['processed_categories']} categories"
            )
            
            # Add processing metadata to each resource
            self._add_processing_metadata(fhir_resources, processing_stats)
            
            return fhir_resources
            
        except Exception as e:
            logger.error(f"Error during FHIR processing: {e}")
            processing_stats['errors'].append(str(e))
            raise
    
    def _process_medications(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process medication data using MedicationService."""
        try:
            return self.medication_service.process_medications(extracted_data)
        except Exception as e:
            logger.error(f"Error processing medications: {e}")
            return []
    
    def _process_diagnostic_reports(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process diagnostic report data using DiagnosticReportService."""
        try:
            return self.diagnostic_report_service.process_diagnostic_reports(extracted_data)
        except Exception as e:
            logger.error(f"Error processing diagnostic reports: {e}")
            return []
    
    def _process_service_requests(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process service request data using ServiceRequestService."""
        try:
            return self.service_request_service.process_service_requests(extracted_data)
        except Exception as e:
            logger.error(f"Error processing service requests: {e}")
            return []
    
    def _process_encounter(self, extracted_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process encounter data using EncounterService."""
        try:
            return self.encounter_service.process_encounters(extracted_data)
        except Exception as e:
            logger.error(f"Error processing encounter: {e}")
            return None
    
    def _process_conditions(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process condition data using ConditionService."""
        try:
            return self.condition_service.process_conditions(extracted_data)
        except Exception as e:
            logger.error(f"Error processing conditions: {e}")
            return []
    
    def _process_observations(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process observation data using ObservationService."""
        try:
            return self.observation_service.process_observations(extracted_data)
        except Exception as e:
            logger.error(f"Error processing observations: {e}")
            return []
    
    # TODO: Implement additional processing methods when services are available
    # def _process_care_plans(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    #     """Process care plan data using CarePlanService."""
    #     try:
    #         return self.care_plan_service.process_care_plans(extracted_data)
    #     except Exception as e:
    #         logger.error(f"Error processing care plans: {e}")
    #         return []
    
    # def _process_organizations(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    #     """Process organization data using OrganizationService."""
    #     try:
    #         return self.organization_service.process_organizations(extracted_data)
    #     except Exception as e:
    #         logger.error(f"Error processing organizations: {e}")
    #         return []
    
    # def _process_practitioners(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    #     """Process practitioner data using PractitionerService."""
    #     try:
    #         return self.practitioner_service.process_practitioners(extracted_data)
    #     except Exception as e:
    #         logger.error(f"Error processing practitioners: {e}")
    #         return []
    
    # def _process_procedures(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    #     """Process procedure data using ProcedureService."""
    #     try:
    #         return self.procedure_service.process_procedures(extracted_data)
    #     except Exception as e:
    #         logger.error(f"Error processing procedures: {e}")
    #         return []
    
    # def _process_allergies(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    #     """Process allergy data using AllergyService."""
    #     try:
    #         return self.allergy_service.process_allergies(extracted_data)
    #     except Exception as e:
    #         logger.error(f"Error processing allergies: {e}")
    #         return []
    
    def _add_processing_metadata(self, fhir_resources: List[Dict[str, Any]], 
                               processing_stats: Dict[str, Any]) -> None:
        """
        Add processing metadata to each FHIR resource for tracking and debugging.
        
        Args:
            fhir_resources: List of FHIR resources to add metadata to
            processing_stats: Processing statistics to include in metadata
        """
        processing_timestamp = datetime.utcnow().isoformat() + 'Z'
        
        for resource in fhir_resources:
            if 'meta' not in resource:
                resource['meta'] = {}
            
            # Add processing metadata
            resource['meta'].update({
                'lastUpdated': processing_timestamp,
                'source': 'FHIRProcessor',
                'versionId': '1',
                'tag': [
                    {
                        'system': 'http://terminology.hl7.org/CodeSystem/v3-ActReason',
                        'code': 'TREAT',
                        'display': 'Treatment'
                    }
                ]
            })
            
            # Add extension with processing stats
            if 'extension' not in resource:
                resource['extension'] = []
            
            resource['extension'].append({
                'url': 'http://meddocparser.local/fhir/StructureDefinition/processing-metadata',
                'extension': [
                    {
                        'url': 'processingTimestamp',
                        'valueDateTime': processing_timestamp
                    },
                    {
                        'url': 'totalResourcesProcessed',
                        'valueInteger': processing_stats['total_resources']
                    },
                    {
                        'url': 'processingVersion',
                        'valueString': '1.0.0'
                    }
                ]
            })
    
    def get_supported_resource_types(self) -> List[str]:
        """
        Get list of currently supported FHIR resource types.
        
        Returns:
            List of supported FHIR resource type names
        """
        supported_types = [
            'MedicationStatement',
            'DiagnosticReport', 
            'ServiceRequest',
            'Encounter'
        ]
        
        # TODO: Add additional types when services are implemented
        # supported_types.extend([
        #     'CarePlan',
        #     'Organization', 
        #     'Practitioner',
        #     'Procedure',
        #     'AllergyIntolerance'
        # ])
        
        return supported_types
    
    def validate_processing_capabilities(self) -> Dict[str, Any]:
        """
        Validate that all required services are properly initialized.
        
        Returns:
            Dictionary with validation results
        """
        validation_results = {
            'valid': True,
            'services_initialized': [],
            'missing_services': [],
            'errors': []
        }
        
        # Check required services
        required_services = [
            ('medication_service', 'MedicationService'),
            ('diagnostic_report_service', 'DiagnosticReportService'),
            ('service_request_service', 'ServiceRequestService'),
            ('encounter_service', 'EncounterService')
        ]
        
        for attr_name, service_name in required_services:
            if hasattr(self, attr_name) and getattr(self, attr_name) is not None:
                validation_results['services_initialized'].append(service_name)
            else:
                validation_results['missing_services'].append(service_name)
                validation_results['valid'] = False
        
        if not validation_results['valid']:
            validation_results['errors'].append(
                f"Missing required services: {', '.join(validation_results['missing_services'])}"
            )
        
        return validation_results
