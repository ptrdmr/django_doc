"""
FHIR Services Package

This package contains specialized services for processing different FHIR resource types.
Each service handles the conversion of extracted medical data into proper FHIR resources.
"""

from .medication_service import MedicationService
from .diagnostic_report_service import DiagnosticReportService
from .service_request_service import ServiceRequestService
from .encounter_service import EncounterService

__all__ = [
    'MedicationService',
    'DiagnosticReportService',
    'ServiceRequestService',
    'EncounterService',
]
