"""
FHIR Services Package

This package contains specialized services for processing different FHIR resource types.
Each service handles the conversion of extracted medical data into proper FHIR resources.
"""

from .condition_service import ConditionService
from .medication_service import MedicationService
from .observation_service import ObservationService
from .diagnostic_report_service import DiagnosticReportService
from .service_request_service import ServiceRequestService
from .encounter_service import EncounterService
from .procedure_service import ProcedureService
from .practitioner_service import PractitionerService
from .allergy_intolerance_service import AllergyIntoleranceService
from .care_plan_service import CarePlanService
from .organization_service import OrganizationService
from .fhir_processor import FHIRProcessor
from .metrics_service import FHIRMetricsService

__all__ = [
    'ConditionService',
    'MedicationService',
    'ObservationService',
    'DiagnosticReportService',
    'ServiceRequestService',
    'EncounterService',
    'ProcedureService',
    'PractitionerService',
    'AllergyIntoleranceService',
    'CarePlanService',
    'OrganizationService',
    'FHIRProcessor',
    'FHIRMetricsService',
]
