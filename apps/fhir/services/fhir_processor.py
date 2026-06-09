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
from .procedure_service import ProcedureService
from .practitioner_service import PractitionerService
from .allergy_intolerance_service import AllergyIntoleranceService
from .care_plan_service import CarePlanService
from .organization_service import OrganizationService
from .family_history_service import FamilyHistoryService
from .immunization_service import ImmunizationService
from .encounter_linker import EncounterLinker

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
        self.procedure_service = ProcedureService()
        self.practitioner_service = PractitionerService()
        self.allergy_service = AllergyIntoleranceService()
        self.care_plan_service = CarePlanService()
        self.organization_service = OrganizationService()
        self.family_history_service = FamilyHistoryService()
        self.immunization_service = ImmunizationService()

        logger.info("FHIRProcessor initialized with 13 resource services.")
    
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
        
        # Ensure patient_id is available in the data. Callers may pass it either
        # as the positional arg OR embedded in extracted_data (the converter path
        # does the latter), so resolve a single effective id for internal use.
        if patient_id:
            extracted_data['patient_id'] = patient_id
        effective_patient_id = extracted_data.get('patient_id')
        
        try:
            # ──────────────────────────────────────────────────────────────
            # PHASE 1: Foundation resources (WP2)
            # Encounters first so downstream clinical resources can be linked
            # to them. Practitioners and Organizations are independent context.
            # ──────────────────────────────────────────────────────────────
            encounters = self._process_encounters(extracted_data)

            # Synthesize a minimal Encounter when the document describes clinical
            # activity but the AI did not extract an explicit encounter. This
            # gives clinical resources something to attach to (single-visit docs).
            if not encounters:
                synthesized = self._synthesize_encounter_if_warranted(extracted_data)
                if synthesized:
                    encounters = [synthesized]

            if encounters:
                fhir_resources.extend(encounters)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(encounters)} encounter resource(s)")

            encounter_map = self._build_encounter_map(encounters or [])

            practitioners = self._process_practitioners(extracted_data)
            if practitioners:
                fhir_resources.extend(practitioners)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(practitioners)} practitioner resources")

            organizations = self._process_organizations(extracted_data)
            if organizations:
                fhir_resources.extend(organizations)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(organizations)} organization resources")

            # ──────────────────────────────────────────────────────────────
            # PHASE 2: Clinical resources (encounter-aware via post-link pass)
            # ──────────────────────────────────────────────────────────────
            clinical_resources: List[Dict[str, Any]] = []

            medications = self._process_medications(extracted_data)
            if medications:
                clinical_resources.extend(medications)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(medications)} medication resources")

            # Observations captured separately to feed DiagnosticReport synthesis.
            observations = self._process_observations(extracted_data)
            if observations:
                clinical_resources.extend(observations)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(observations)} observation resources")

            conditions = self._process_conditions(extracted_data)
            if conditions:
                clinical_resources.extend(conditions)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(conditions)} condition resources")

            # Immunizations BEFORE procedures so vaccine items can be claimed and
            # excluded from the Procedure list (prevents double-counting, D1).
            immunizations = self._process_immunizations(extracted_data)
            claimed_vaccines = self._collect_claimed_vaccines(immunizations)
            if immunizations:
                clinical_resources.extend(immunizations)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(immunizations)} immunization resources")

            procedures = self._process_procedures(extracted_data, claimed_vaccines)
            if procedures:
                clinical_resources.extend(procedures)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(procedures)} procedure resources")

            # Explicit diagnostic reports (existing behavior)
            diagnostic_reports = self._process_diagnostic_reports(extracted_data)
            if diagnostic_reports:
                clinical_resources.extend(diagnostic_reports)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(diagnostic_reports)} diagnostic report resources")

            # Synthesize lab-panel DiagnosticReports from lab observations (B1).
            # Pass explicit reports so already-reported labs are not duplicated.
            synthesized_reports = self._synthesize_lab_panels(
                extracted_data, observations, effective_patient_id, diagnostic_reports
            )
            if synthesized_reports:
                clinical_resources.extend(synthesized_reports)
                processing_stats['processed_categories'] += 1
                logger.info(
                    f"Synthesized {len(synthesized_reports)} lab-panel diagnostic report(s)"
                )

            service_requests = self._process_service_requests(extracted_data)
            if service_requests:
                clinical_resources.extend(service_requests)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(service_requests)} service request resources")

            allergies = self._process_allergies(extracted_data)
            if allergies:
                clinical_resources.extend(allergies)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(allergies)} allergy resources")

            care_plans = self._process_care_plans(extracted_data)
            if care_plans:
                clinical_resources.extend(care_plans)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(care_plans)} care plan resources")

            family_history_resources = self._process_family_history(extracted_data)
            if family_history_resources:
                clinical_resources.extend(family_history_resources)
                processing_stats['processed_categories'] += 1
                logger.info(f"Processed {len(family_history_resources)} family history resources")

            # Cross-reference clinical resources to encounters (B10)
            if encounter_map:
                linker = EncounterLinker(encounter_map)
                linker.link_resources(clinical_resources)

            fhir_resources.extend(clinical_resources)

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
    
    def _process_encounters(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process encounter data using EncounterService."""
        try:
            return self.encounter_service.process_encounters(extracted_data)
        except Exception as e:
            logger.error(f"Error processing encounters: {e}")
            return []
    
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
    
    def _process_procedures(self, extracted_data: Dict[str, Any],
                            claimed_vaccines: Optional[set] = None) -> List[Dict[str, Any]]:
        """Process procedure data using ProcedureService.

        Args:
            extracted_data: Extracted clinical data.
            claimed_vaccines: Lowercased vaccine names already represented as
                Immunization resources; matching procedures are skipped to
                prevent double-counting (D1 contract).
        """
        try:
            return self.procedure_service.process_procedures(
                extracted_data, claimed_vaccines=claimed_vaccines
            )
        except Exception as e:
            logger.error(f"Error processing procedures: {e}")
            return []

    def _process_immunizations(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process immunization data using ImmunizationService (D1)."""
        try:
            return self.immunization_service.process_immunizations(extracted_data)
        except Exception as e:
            logger.error(f"Error processing immunizations: {e}")
            return []

    def _collect_claimed_vaccines(self, immunizations: List[Dict[str, Any]]) -> set:
        """Build the lowercased vaccine-name set claimed by Immunization resources.

        ProcedureService uses this to skip vaccine administrations it would
        otherwise mis-capture as Procedures.
        """
        claimed = set()
        for imm in immunizations or []:
            if not isinstance(imm, dict):
                continue
            vaccine_code = imm.get('vaccineCode', {}) or {}
            text = (vaccine_code.get('text') or '').strip().lower()
            if text:
                claimed.add(text)
        return claimed

    def _build_encounter_map(self, encounters: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build a lookup mapping date keys and ids to Encounter resources.

        Both the encounter id and its period start date (full ISO string) are
        registered so EncounterLinker can resolve references by either path.
        """
        encounter_map: Dict[str, Any] = {}
        for enc in encounters:
            if not isinstance(enc, dict) or enc.get('resourceType') != 'Encounter':
                continue
            enc_id = enc.get('id')
            if enc_id:
                encounter_map[enc_id] = enc
            start_date = (enc.get('period') or {}).get('start')
            if start_date:
                encounter_map[str(start_date)[:10]] = enc
        return encounter_map

    def _synthesize_encounter_if_warranted(
        self, extracted_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Synthesize a minimal Encounter from document metadata when none exist.

        Returns None unless the document carries a clinical date AND at least one
        clinical resource group, so we don't fabricate visits for pure
        administrative documents.
        """
        try:
            return self.encounter_service.synthesize_encounter(extracted_data)
        except Exception as e:
            logger.error(f"Error synthesizing encounter: {e}")
            return None

    def _synthesize_lab_panels(self, extracted_data: Dict[str, Any],
                               observations: List[Dict[str, Any]],
                               patient_id: Optional[str],
                               explicit_reports: Optional[List[Dict[str, Any]]] = None
                               ) -> List[Dict[str, Any]]:
        """Group lab Observations into panel DiagnosticReports (B1)."""
        try:
            structured = extracted_data.get('structured_data')
            if not isinstance(structured, dict):
                return []
            return self.diagnostic_report_service.synthesize_lab_panels(
                structured, observations or [], patient_id, explicit_reports or []
            )
        except Exception as e:
            logger.error(f"Error synthesizing lab panels: {e}")
            return []
    
    def _process_practitioners(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process practitioner data using PractitionerService."""
        try:
            return self.practitioner_service.process_practitioners(extracted_data)
        except Exception as e:
            logger.error(f"Error processing practitioners: {e}")
            return []
    
    def _process_allergies(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process allergy data using AllergyIntoleranceService."""
        try:
            return self.allergy_service.process_allergies(extracted_data)
        except Exception as e:
            logger.error(f"Error processing allergies: {e}")
            return []
    
    def _process_care_plans(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process care plan data using CarePlanService."""
        try:
            return self.care_plan_service.process_care_plans(extracted_data)
        except Exception as e:
            logger.error(f"Error processing care plans: {e}")
            return []
    
    def _process_organizations(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process organization data using OrganizationService."""
        try:
            return self.organization_service.process_organizations(extracted_data)
        except Exception as e:
            logger.error(f"Error processing organizations: {e}")
            return []

    def _process_family_history(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Family history narratives via FamilyHistoryService."""
        try:
            return self.family_history_service.process_family_history(extracted_data)
        except Exception as exc:
            logger.error("Error processing family history: %s", exc)
            return []

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
            'Condition',
            'MedicationStatement',
            'Observation',
            'DiagnosticReport',
            'ServiceRequest',
            'Encounter',
            'Procedure',
            'Practitioner',
            'AllergyIntolerance',
            'CarePlan',
            'Organization',
            'FamilyMemberHistory',
            'Immunization',
        ]
        
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
            ('condition_service', 'ConditionService'),
            ('medication_service', 'MedicationService'),
            ('observation_service', 'ObservationService'),
            ('diagnostic_report_service', 'DiagnosticReportService'),
            ('service_request_service', 'ServiceRequestService'),
            ('encounter_service', 'EncounterService'),
            ('procedure_service', 'ProcedureService'),
            ('practitioner_service', 'PractitionerService'),
            ('allergy_service', 'AllergyIntoleranceService'),
            ('care_plan_service', 'CarePlanService'),
            ('organization_service', 'OrganizationService'),
            ('family_history_service', 'FamilyHistoryService'),
            ('immunization_service', 'ImmunizationService'),
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
