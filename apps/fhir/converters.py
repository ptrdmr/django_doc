"""
FHIR Resource Converters

Standalone module containing converters that transform validated document
data into FHIR resources. Kept separate for clarity and testability.

This module now includes support for structured medical data from the new
Pydantic-based AI extraction service (Task 34).

Enhanced with comprehensive error handling and logging for Task 34.5.
"""

import logging
import time
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from uuid import uuid4

from fhir.resources.resource import Resource
from fhir.resources.condition import Condition
from fhir.resources.medicationstatement import MedicationStatement
from fhir.resources.observation import Observation
from fhir.resources.procedure import Procedure
from fhir.resources.practitioner import Practitioner
from fhir.resources.bundle import Bundle

from .validation import DataNormalizer
from .code_systems import default_code_mapper, NormalizedCode
from .fhir_models import (
    PractitionerResource,
    ConditionResource,
    ObservationResource,
    MedicationStatementResource,
)

# Import custom exceptions for enhanced error handling
from apps.documents.exceptions import (
    FHIRConversionError,
    FHIRValidationError,
    DataValidationError,
    PydanticModelError
)

# Import structured medical data models
try:
    from apps.documents.services.ai_extraction import (
        StructuredMedicalExtraction,
        MedicalCondition,
        Medication,
        VitalSign,
        LabResult,
        Procedure as MedicalProcedure,
        Provider,
        SourceContext
    )
except ImportError:
    logger.warning("Unable to import structured medical data models - structured conversion unavailable")
    StructuredMedicalExtraction = None


logger = logging.getLogger(__name__)


class BaseFHIRConverter:
    """Base class for converting document data to FHIR resources."""

    def __init__(self):
        """Initialize the base converter."""
        self.logger = logger

    def convert(self, data: Dict[str, Any], metadata: Dict[str, Any], patient) -> List[Resource]:
        """Convert document data to FHIR resources.

        Args:
            data: Validated extracted data
            metadata: Document metadata
            patient: Patient model instance

        Returns:
            List of FHIR Resource objects
        """
        raise NotImplementedError("Subclasses must implement convert method")

    def _generate_unique_id(self) -> str:
        """Generate a unique resource ID."""
        return str(uuid4())

    def _get_patient_id(self, patient) -> str:
        """Get the FHIR patient ID."""
        return str(patient.id)

    def _create_provider_resource(self, provider_name: str) -> Optional[PractitionerResource]:
        """Create a Practitioner resource from provider name.

        Args:
            provider_name: Name of the provider

        Returns:
            PractitionerResource or None if creation fails
        """
        if not provider_name or not provider_name.strip():
            return None

        try:
            name_parts = provider_name.strip().split()
            if len(name_parts) >= 2:
                first_name = name_parts[0]
                last_name = " ".join(name_parts[1:])
            else:
                first_name = provider_name
                last_name = "Unknown"

            return PractitionerResource.create_from_provider(
                first_name=first_name,
                last_name=last_name,
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create Practitioner resource: {exc}")
            return None

    def _normalize_date_for_fhir(self, date_value: Any) -> Optional[datetime]:
        """Normalize date value for FHIR usage.

        Args:
            date_value: Date in various formats

        Returns:
            datetime object or None if invalid
        """
        if not date_value:
            return None

        normalized_date_str = DataNormalizer.normalize_date(date_value)
        if normalized_date_str:
            try:
                return datetime.fromisoformat(normalized_date_str)
            except ValueError:
                return None
        return None
    
    def _normalize_code(self, code: str, system: Optional[str] = None, context: Optional[str] = None) -> Dict[str, Any]:
        """
        Normalize medical codes using the code system mapper.
        
        Args:
            code: Medical code to normalize
            system: Known code system (optional)
            context: Context for system detection (optional)
            
        Returns:
            Dictionary with normalized code information
        """
        if not code:
            return {}
            
        try:
            normalized = default_code_mapper.normalize_code(code, system, context)
            
            # Find equivalent codes in other systems
            mappings = default_code_mapper.find_equivalent_codes(
                normalized.code, 
                normalized.system,
                target_systems=['LOINC', 'SNOMED', 'ICD-10-CM'] if normalized.system not in ['LOINC', 'SNOMED', 'ICD-10-CM'] else None
            )
            
            result = {
                'coding': [{
                    'system': normalized.system_uri,
                    'code': normalized.code,
                    'display': normalized.display
                }],
                'text': normalized.display or code
            }
            
            # Add equivalent codes as additional codings
            for mapping in mappings:
                if mapping.confidence >= 0.8:  # High confidence mappings only
                    result['coding'].append({
                        'system': default_code_mapper.get_system_uri(mapping.target_system),
                        'code': mapping.target_code,
                        'display': mapping.description
                    })
            
            return result
            
        except Exception as e:
            self.logger.warning(f"Code normalization failed for '{code}': {e}")
            # Fallback to simple format
            return {
                'coding': [{
                    'code': str(code),
                    'display': str(code)
                }],
                'text': str(code)
            }


class GenericConverter(BaseFHIRConverter):
    """Generic converter for basic document types without specialized logic."""

    def convert(self, data: Dict[str, Any], metadata: Dict[str, Any], patient) -> List[Resource]:
        """Convert generic document data to FHIR resources.

        Args:
            data: Validated extracted data
            metadata: Document metadata
            patient: Patient model instance

        Returns:
            List of FHIR Resource objects
        """
        resources: List[Resource] = []
        patient_id = self._get_patient_id(patient)

        try:
            provider_fields = ["provider", "ordering_provider", "attending_physician"]
            for field in provider_fields:
                if field in data and data[field]:
                    provider = self._create_provider_resource(data[field])
                    if provider:
                        resources.append(provider)
                        break

            if "diagnosis_codes" in data and isinstance(data["diagnosis_codes"], list):
                for diagnosis in data["diagnosis_codes"]:
                    condition = self._create_condition_from_code(diagnosis, patient_id, data)
                    if condition:
                        resources.append(condition)

            self.logger.info("Generic converter created %s resources", len(resources))
            return resources
        except Exception as exc:
            self.logger.error("Generic conversion failed: %s", exc, exc_info=True)
            return []

    def _create_condition_from_code(self, diagnosis_code: Any, patient_id: str, data: Dict[str, Any]) -> Optional[ConditionResource]:
        """Create a Condition resource from a diagnosis code."""
        try:
            if isinstance(diagnosis_code, dict):
                code = diagnosis_code.get("code", "")
                display = diagnosis_code.get("display", diagnosis_code.get("description", ""))
            else:
                code = str(diagnosis_code)
                display = f"Diagnosis code {code}"

            if not code:
                return None

            onset_date: Optional[datetime] = None
            for field in ["document_date", "note_date", "admission_date"]:
                if field in data and data[field]:
                    onset_date = self._normalize_date_for_fhir(data[field])
                    break

            return ConditionResource.create_from_diagnosis(
                patient_id=patient_id,
                condition_code=code,
                condition_display=display,
                onset_date=onset_date,
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create Condition from code: {exc}")
            return None


class LabReportConverter(BaseFHIRConverter):
    """Converter for laboratory reports into Observation resources."""

    def convert(self, data: Dict[str, Any], metadata: Dict[str, Any], patient) -> List[Resource]:
        """Convert lab report data to FHIR resources."""
        resources: List[Resource] = []
        patient_id = self._get_patient_id(patient)

        try:
            # Task 35.7: Return None if no clinical date available instead of current time
            test_date = self._normalize_date_for_fhir(data.get("test_date"))

            if "ordering_provider" in data and data["ordering_provider"]:
                provider = self._create_provider_resource(data["ordering_provider"])
                if provider:
                    resources.append(provider)

            if "tests" in data and isinstance(data["tests"], list):
                for test in data["tests"]:
                    observation = self._create_observation_from_test(test, patient_id, test_date)
                    if observation:
                        resources.append(observation)

            self.logger.info("Lab report converter created %s resources", len(resources))
            return resources
        except Exception as exc:
            self.logger.error("Lab report conversion failed: %s", exc, exc_info=True)
            return []

    def _create_observation_from_test(self, test: Dict[str, Any], patient_id: str, test_date: datetime) -> Optional[ObservationResource]:
        """Create an Observation resource from a single test result."""
        try:
            test_name = test.get("name")
            test_value = test.get("value")
            test_unit = test.get("unit", test.get("units"))
            test_code = test.get("code", test.get("test_code"))

            if not test_name:
                self.logger.warning("Test missing name, skipping")
                return None

            if not test_code:
                test_code = f"LAB-{hash(test_name.lower()) % 100000:05d}"

            return ObservationResource.create_from_lab_result(
                patient_id=patient_id,
                test_code=test_code,
                test_name=test_name,
                value=test_value,
                unit=test_unit if test_unit and test_unit.strip() else None,
                observation_date=test_date,
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create Observation from test: {exc}")
            return None


class ClinicalNoteConverter(BaseFHIRConverter):
    """Converter for clinical notes into Condition/Observation resources."""

    def convert(self, data: Dict[str, Any], metadata: Dict[str, Any], patient) -> List[Resource]:
        """Convert clinical note data to FHIR resources."""
        resources: List[Resource] = []
        patient_id = self._get_patient_id(patient)

        try:
            # Task 35.7: Return None if no clinical date available instead of current time
            note_date = self._normalize_date_for_fhir(data.get("note_date"))

            if "provider" in data and data["provider"]:
                provider = self._create_provider_resource(data["provider"])
                if provider:
                    resources.append(provider)

            if "diagnosis_codes" in data and isinstance(data["diagnosis_codes"], list):
                for diagnosis in data["diagnosis_codes"]:
                    condition = self._create_condition_from_diagnosis(diagnosis, patient_id, note_date)
                    if condition:
                        resources.append(condition)

            if "assessment" in data and data["assessment"]:
                assessment_obs = self._create_assessment_observation(data["assessment"], patient_id, note_date)
                if assessment_obs:
                    resources.append(assessment_obs)

            if "plan" in data and data["plan"]:
                plan_obs = self._create_plan_observation(data["plan"], patient_id, note_date)
                if plan_obs:
                    resources.append(plan_obs)

            self.logger.info("Clinical note converter created %s resources", len(resources))
            return resources
        except Exception as exc:
            self.logger.error("Clinical note conversion failed: %s", exc, exc_info=True)
            return []

    def _create_condition_from_diagnosis(self, diagnosis: Any, patient_id: str, note_date: datetime) -> Optional[ConditionResource]:
        """Create a Condition resource from diagnosis information."""
        try:
            if isinstance(diagnosis, dict):
                code = diagnosis.get("code", "")
                display = diagnosis.get("display", diagnosis.get("description", ""))
            else:
                code = str(diagnosis)
                display = f"Clinical diagnosis: {code}"

            if not code:
                return None

            return ConditionResource.create_from_diagnosis(
                patient_id=patient_id,
                condition_code=code,
                condition_display=display,
                onset_date=note_date,
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create Condition from diagnosis: {exc}")
            return None

    def _create_assessment_observation(self, assessment: str, patient_id: str, note_date: datetime) -> Optional[ObservationResource]:
        """Create an Observation resource for a clinical assessment."""
        try:
            return ObservationResource.create_from_lab_result(
                patient_id=patient_id,
                test_code="ASSESS",
                test_name="Clinical Assessment",
                value=assessment,
                observation_date=note_date,
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create assessment observation: {exc}")
            return None

    def _create_plan_observation(self, plan: str, patient_id: str, note_date: datetime) -> Optional[ObservationResource]:
        """Create an Observation resource for a treatment plan."""
        try:
            return ObservationResource.create_from_lab_result(
                patient_id=patient_id,
                test_code="PLAN",
                test_name="Treatment Plan",
                value=plan,
                observation_date=note_date,
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create plan observation: {exc}")
            return None


class MedicationListConverter(BaseFHIRConverter):
    """Converter for medication lists into MedicationStatement resources."""

    def convert(self, data: Dict[str, Any], metadata: Dict[str, Any], patient) -> List[Resource]:
        """Convert medication list data to FHIR resources."""
        resources: List[Resource] = []
        patient_id = self._get_patient_id(patient)

        try:
            # Task 35.7: Return None if no clinical date available instead of current time
            list_date = self._normalize_date_for_fhir(data.get("list_date"))

            if "prescribing_provider" in data and data["prescribing_provider"]:
                provider = self._create_provider_resource(data["prescribing_provider"])
                if provider:
                    resources.append(provider)

            if "medications" in data and isinstance(data["medications"], list):
                for medication in data["medications"]:
                    med_statement = self._create_medication_statement(medication, patient_id, list_date)
                    if med_statement:
                        resources.append(med_statement)

            self.logger.info("Medication list converter created %s resources", len(resources))
            return resources
        except Exception as exc:
            self.logger.error("Medication list conversion failed: %s", exc, exc_info=True)
            return []

    def _create_medication_statement(self, medication: Dict[str, Any], patient_id: str, list_date: datetime) -> Optional[MedicationStatementResource]:
        """Create a MedicationStatement resource from medication information."""
        try:
            med_name = medication.get("name")
            med_code = medication.get("code", medication.get("ndc"))
            dosage = medication.get("dosage", medication.get("dose"))
            frequency = medication.get("frequency")
            status = medication.get("status", "active")

            if not med_name:
                self.logger.warning("Medication missing name, skipping")
                return None

            return MedicationStatementResource.create_from_medication(
                patient_id=patient_id,
                medication_name=med_name,
                medication_code=med_code,
                dosage=dosage,
                frequency=frequency,
                status=status,
                effective_date=list_date,
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create MedicationStatement: {exc}")
            return None


class DischargeSummaryConverter(BaseFHIRConverter):
    """Converter for discharge summaries into multiple FHIR resources."""

    def convert(self, data: Dict[str, Any], metadata: Dict[str, Any], patient) -> List[Resource]:
        """Convert discharge summary data to FHIR resources."""
        resources: List[Resource] = []
        patient_id = self._get_patient_id(patient)

        try:
            # Task 35.7: Return None if no clinical date available instead of current time
            discharge_date = self._normalize_date_for_fhir(data.get("discharge_date"))
            admission_date = self._normalize_date_for_fhir(data.get("admission_date"))

            if "attending_physician" in data and data["attending_physician"]:
                provider = self._create_provider_resource(data["attending_physician"])
                if provider:
                    resources.append(provider)

            if "diagnosis" in data and isinstance(data["diagnosis"], list):
                for diagnosis in data["diagnosis"]:
                    condition = self._create_discharge_condition(diagnosis, patient_id, discharge_date)
                    if condition:
                        resources.append(condition)

            if "procedures" in data and isinstance(data["procedures"], list):
                for procedure in data["procedures"]:
                    proc_resource = self._create_procedure_resource(
                        procedure,
                        patient_id,
                        admission_date or discharge_date,
                    )
                    if proc_resource:
                        resources.append(proc_resource)

            if "medications" in data and isinstance(data["medications"], list):
                med_converter = MedicationListConverter()
                for medication in data["medications"]:
                    med_statement = med_converter._create_medication_statement(
                        medication,
                        patient_id,
                        discharge_date,
                    )
                    if med_statement:
                        resources.append(med_statement)

            self.logger.info("Discharge summary converter created %s resources", len(resources))
            return resources
        except Exception as exc:
            self.logger.error("Discharge summary conversion failed: %s", exc, exc_info=True)
            return []

    def _create_discharge_condition(self, diagnosis: Any, patient_id: str, discharge_date: datetime) -> Optional[ConditionResource]:
        """Create a Condition resource from discharge diagnosis."""
        try:
            if isinstance(diagnosis, dict):
                code = diagnosis.get("code", "")
                display = diagnosis.get("display", diagnosis.get("description", ""))
                status = diagnosis.get("status", "active")
            else:
                code = str(diagnosis)
                display = f"Discharge diagnosis: {code}"
                status = "active"

            if not code:
                return None

            return ConditionResource.create_from_diagnosis(
                patient_id=patient_id,
                condition_code=code,
                condition_display=display,
                clinical_status=status,
                onset_date=discharge_date,
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create discharge condition: {exc}")
            return None

    def _create_procedure_resource(self, procedure: Any, patient_id: str, procedure_date: datetime) -> Optional['ProcedureResource']:
        """Create a proper Procedure resource (replaces old observation-based approach)."""
        try:
            if isinstance(procedure, dict):
                proc_name = procedure.get("name", procedure.get("description", ""))
                proc_code = procedure.get("code", "")
                provider = procedure.get("provider")
                outcome = procedure.get("outcome")
            else:
                proc_name = str(procedure)
                proc_code = None
                provider = None
                outcome = None

            if not proc_name:
                return None

            from apps.fhir.fhir_models import ProcedureResource
            
            return ProcedureResource.create_from_procedure_data(
                patient_id=patient_id,
                procedure_name=proc_name,
                procedure_code=proc_code,
                performed_date=procedure_date,
                status="completed",
                performer_name=provider,
                outcome=outcome
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create Procedure resource: {exc}")
            return None


class StructuredDataConverter(BaseFHIRConverter):
    """
    Converter for structured medical data from AI extraction service.
    
    This converter bridges the new Pydantic-based AI extraction (Task 34.1) 
    with the existing FHIR engine, maintaining minimal layers while ensuring
    comprehensive document flow integration.
    
    Flow: StructuredMedicalExtraction → Dict format → Existing FHIR engine
    """

    def convert_structured_data(self, structured_data: 'StructuredMedicalExtraction', metadata: Dict[str, Any], patient, parsed_data=None) -> List[Resource]:
        """
        Convert structured medical data from AI extraction to FHIR resources.
        
        This is the main entry point that bridges AI-extracted Pydantic models
        with the existing FHIR converter infrastructure.
        
        Enhanced with comprehensive error handling for Task 34.5.
        Updated for Task 35.7: Clinical Date Integration.
        
        Args:
            structured_data: StructuredMedicalExtraction from AI service
            metadata: Document metadata (document_id, extraction_timestamp, etc.)
            patient: Patient model instance
            parsed_data: Optional ParsedData instance containing clinical dates (Task 35)
            
        Returns:
            List of FHIR Resource objects ready for the existing FHIR engine
            
        Raises:
            FHIRConversionError: If conversion fails due to invalid data or processing errors
            DataValidationError: If input validation fails
        """
        conversion_id = str(time.time())[:10]  # Short unique ID for this conversion
        self.logger.info(f"[{conversion_id}] Starting structured data to FHIR conversion for patient {patient.id}")
        
        # Enhanced input validation
        try:
            if not structured_data:
                raise DataValidationError(
                    "structured_data cannot be None",
                    field_name="structured_data",
                    details={'conversion_id': conversion_id, 'patient_id': patient.id}
                )
                
            if StructuredMedicalExtraction is None:
                raise FHIRConversionError(
                    "Structured medical data models not available - cannot perform conversion",
                    details={'conversion_id': conversion_id, 'patient_id': patient.id}
                )
            
            if not patient:
                raise DataValidationError(
                    "Patient instance is required for FHIR conversion",
                    field_name="patient",
                    details={'conversion_id': conversion_id}
                )
            
            if not hasattr(patient, 'id') or not patient.id:
                raise DataValidationError(
                    "Patient must have a valid ID",
                    field_name="patient.id",
                    details={'conversion_id': conversion_id, 'patient_type': type(patient).__name__}
                )
            
            # Validate metadata
            if not isinstance(metadata, dict):
                self.logger.warning(f"[{conversion_id}] Invalid metadata type: {type(metadata)}, using empty dict")
                metadata = {}
            
            # Log structured data summary for debugging
            total_items = (
                len(structured_data.conditions) + len(structured_data.medications) + 
                len(structured_data.vital_signs) + len(structured_data.lab_results) + 
                len(structured_data.procedures) + len(structured_data.providers)
            )
            
            self.logger.info(f"[{conversion_id}] Processing {total_items} structured items: "
                           f"{len(structured_data.conditions)} conditions, "
                           f"{len(structured_data.medications)} medications, "
                           f"{len(structured_data.vital_signs)} vital signs, "
                           f"{len(structured_data.lab_results)} lab results, "
                           f"{len(structured_data.procedures)} procedures, "
                           f"{len(structured_data.providers)} providers")
            
        except (DataValidationError, FHIRConversionError):
            raise
        except Exception as e:
            raise DataValidationError(
                f"Unexpected validation error: {str(e)}",
                details={'conversion_id': conversion_id, 'error_type': type(e).__name__}
            )
        
        # Perform conversion with comprehensive error tracking
        try:
            start_time = time.time()
            
            # Task 35.7: Extract clinical date from ParsedData if available
            clinical_date = None
            if parsed_data and hasattr(parsed_data, 'clinical_date'):
                clinical_date = parsed_data.clinical_date
                if clinical_date:
                    self.logger.info(f"[{conversion_id}] Using clinical date from ParsedData: {clinical_date} "
                                   f"(source: {getattr(parsed_data, 'date_source', 'unknown')}, "
                                   f"status: {getattr(parsed_data, 'date_status', 'unknown')})")
                    # Add clinical date to metadata for use in resource creation
                    metadata['clinical_date'] = clinical_date
                else:
                    self.logger.debug(f"[{conversion_id}] No clinical date available in ParsedData")
            else:
                self.logger.debug(f"[{conversion_id}] No ParsedData provided for clinical date lookup")
            
            # NEW (Task 40.20): Use FHIRProcessor with our dual-format services
            # This preserves dates and uses structured-first path
            try:
                from apps.fhir.services import FHIRProcessor
                
                self.logger.info(f"[{conversion_id}] Using FHIRProcessor with dual-format services for structured data")
                
                # Prepare data for FHIRProcessor
                processor_input = {
                    'patient_id': str(patient.id),
                    'structured_data': structured_data.model_dump()  # Convert Pydantic to dict
                }
                
                # Use FHIRProcessor which has all our new dual-format services
                fhir_processor = FHIRProcessor()
                fhir_resources = fhir_processor.process_extracted_data(processor_input)
                
                # Convert dicts to fhir.resources objects for compatibility
                from fhir.resources.condition import Condition
                from fhir.resources.medicationstatement import MedicationStatement
                from fhir.resources.observation import Observation
                from fhir.resources.procedure import Procedure
                from fhir.resources.practitioner import Practitioner
                from fhir.resources.encounter import Encounter
                from fhir.resources.allergyintolerance import AllergyIntolerance
                from fhir.resources.careplan import CarePlan
                from fhir.resources.organization import Organization
                from fhir.resources.servicerequest import ServiceRequest
                from fhir.resources.diagnosticreport import DiagnosticReport
                
                resource_mapping = {
                    'Condition': Condition,
                    'MedicationStatement': MedicationStatement,
                    'Observation': Observation,
                    'Procedure': Procedure,
                    'Practitioner': Practitioner,
                    'Encounter': Encounter,
                    'AllergyIntolerance': AllergyIntolerance,
                    'CarePlan': CarePlan,
                    'Organization': Organization,
                    'ServiceRequest': ServiceRequest,
                    'DiagnosticReport': DiagnosticReport
                }
                
                resources = []
                for fhir_dict in fhir_resources:
                    resource_type = fhir_dict.get('resourceType')
                    if resource_type in resource_mapping:
                        try:
                            # Create fhir.resources object from dict
                            resource_class = resource_mapping[resource_type]
                            resource_obj = resource_class(**fhir_dict)
                            resources.append(resource_obj)
                        except Exception as res_error:
                            self.logger.warning(f"[{conversion_id}] Could not create {resource_type} resource object: {res_error}")
                            # Continue with dict if object creation fails
                            resources.append(fhir_dict)
                    else:
                        self.logger.warning(f"[{conversion_id}] Unknown resource type: {resource_type}")
                        resources.append(fhir_dict)
                
                total_conversion_time = time.time() - start_time
                
                self.logger.info(f"[{conversion_id}] Successfully converted to {len(resources)} FHIR resources "
                               f"using FHIRProcessor in {total_conversion_time:.3f}s")
                
                # Validate that we got reasonable results
                if total_items > 0 and len(resources) == 0:
                    self.logger.warning(f"[{conversion_id}] No FHIR resources created from {total_items} input items")
                
                return resources
                
            except Exception as e:
                raise FHIRConversionError(
                    f"Failed to create FHIR resources via FHIRProcessor: {str(e)}",
                    data_source="structured_fhir_processor",
                    details={
                        'conversion_id': conversion_id,
                        'error_type': type(e).__name__,
                        'input_item_count': total_items,
                        'conversion_time': time.time() - start_time
                    }
                )
            
        except (DataValidationError, FHIRConversionError):
            raise
        except Exception as e:
            raise FHIRConversionError(
                f"Unexpected error during structured data conversion: {str(e)}",
                details={
                    'conversion_id': conversion_id,
                    'error_type': type(e).__name__,
                    'patient_id': patient.id,
                    'input_item_count': total_items if 'total_items' in locals() else 0
                }
            )

    def convert(self, data: Dict[str, Any], metadata: Dict[str, Any], patient) -> List[Resource]:
        """
        Convert dictionary data to FHIR resources using existing infrastructure.
        
        This method handles the converted dictionary format and creates FHIR resources
        using the existing converter patterns and resource creation methods.
        
        Enhanced with comprehensive error handling for Task 34.5.
        
        Args:
            data: Converted structured data in dictionary format
            metadata: Document metadata
            patient: Patient model instance
            
        Returns:
            List of FHIR Resource objects
            
        Raises:
            FHIRConversionError: If resource creation fails
        """
        resources: List[Resource] = []
        conversion_errors = []
        patient_id = self._get_patient_id(patient)
        
        self.logger.debug(f"Converting dictionary data to FHIR resources for patient {patient_id}")
        
        # Track conversion statistics
        conversion_stats = {
            'conditions_attempted': 0,
            'conditions_successful': 0,
            'medications_attempted': 0,
            'medications_successful': 0,
            'vital_signs_attempted': 0,
            'vital_signs_successful': 0,
            'lab_results_attempted': 0,
            'lab_results_successful': 0,
            'procedures_attempted': 0,
            'procedures_successful': 0,
            'providers_attempted': 0,
            'providers_successful': 0
        }
        
        try:
            # Handle conditions/diagnoses with individual error tracking
            if "conditions" in data and isinstance(data["conditions"], list):
                for i, condition_data in enumerate(data["conditions"]):
                    conversion_stats['conditions_attempted'] += 1
                    try:
                        condition = self._create_condition_from_structured(condition_data, patient_id, metadata)
                        if condition:
                            resources.append(condition)
                            conversion_stats['conditions_successful'] += 1
                        else:
                            self.logger.warning(f"Condition {i} conversion returned None")
                    except Exception as e:
                        error_msg = f"Failed to create condition {i}: {str(e)}"
                        conversion_errors.append(error_msg)
                        self.logger.error(error_msg, exc_info=True)
            
            # Handle medications with individual error tracking
            if "medications" in data and isinstance(data["medications"], list):
                for i, medication_data in enumerate(data["medications"]):
                    conversion_stats['medications_attempted'] += 1
                    try:
                        medication = self._create_medication_from_structured(medication_data, patient_id, metadata)
                        if medication:
                            resources.append(medication)
                            conversion_stats['medications_successful'] += 1
                        else:
                            self.logger.warning(f"Medication {i} conversion returned None")
                    except Exception as e:
                        error_msg = f"Failed to create medication {i}: {str(e)}"
                        conversion_errors.append(error_msg)
                        self.logger.error(error_msg, exc_info=True)
            
            # Handle vital signs with individual error tracking
            if "vital_signs" in data and isinstance(data["vital_signs"], list):
                for i, vital_data in enumerate(data["vital_signs"]):
                    conversion_stats['vital_signs_attempted'] += 1
                    try:
                        observation = self._create_vital_sign_observation(vital_data, patient_id, metadata)
                        if observation:
                            resources.append(observation)
                            conversion_stats['vital_signs_successful'] += 1
                        else:
                            self.logger.warning(f"Vital sign {i} conversion returned None")
                    except Exception as e:
                        error_msg = f"Failed to create vital sign {i}: {str(e)}"
                        conversion_errors.append(error_msg)
                        self.logger.error(error_msg, exc_info=True)
            
            # Handle lab results with individual error tracking
            if "lab_results" in data and isinstance(data["lab_results"], list):
                for i, lab_data in enumerate(data["lab_results"]):
                    conversion_stats['lab_results_attempted'] += 1
                    try:
                        observation = self._create_lab_observation(lab_data, patient_id, metadata)
                        if observation:
                            resources.append(observation)
                            conversion_stats['lab_results_successful'] += 1
                        else:
                            self.logger.warning(f"Lab result {i} conversion returned None")
                    except Exception as e:
                        error_msg = f"Failed to create lab result {i}: {str(e)}"
                        conversion_errors.append(error_msg)
                        self.logger.error(error_msg, exc_info=True)
            
            # Handle procedures with individual error tracking
            if "procedures" in data and isinstance(data["procedures"], list):
                for i, procedure_data in enumerate(data["procedures"]):
                    conversion_stats['procedures_attempted'] += 1
                    try:
                        procedure = self._create_procedure_resource_structured(procedure_data, patient_id, metadata)
                        if procedure:
                            resources.append(procedure)
                            conversion_stats['procedures_successful'] += 1
                        else:
                            self.logger.warning(f"Procedure {i} conversion returned None")
                    except Exception as e:
                        error_msg = f"Failed to create procedure {i}: {str(e)}"
                        conversion_errors.append(error_msg)
                        self.logger.error(error_msg, exc_info=True)
            
            # Handle providers with individual error tracking
            if "providers" in data and isinstance(data["providers"], list):
                for i, provider_data in enumerate(data["providers"]):
                    conversion_stats['providers_attempted'] += 1
                    try:
                        practitioner = self._create_provider_from_structured(provider_data)
                        if practitioner:
                            resources.append(practitioner)
                            conversion_stats['providers_successful'] += 1
                        else:
                            self.logger.warning(f"Provider {i} conversion returned None")
                    except Exception as e:
                        error_msg = f"Failed to create provider {i}: {str(e)}"
                        conversion_errors.append(error_msg)
                        self.logger.error(error_msg, exc_info=True)
            
            # Log conversion summary
            total_attempted = sum(v for k, v in conversion_stats.items() if k.endswith('_attempted'))
            total_successful = sum(v for k, v in conversion_stats.items() if k.endswith('_successful'))
            success_rate = (total_successful / total_attempted) if total_attempted > 0 else 0
            
            self.logger.info(f"Conversion summary: {total_successful}/{total_attempted} resources created "
                           f"({success_rate:.1%} success rate)")
            
            # Log detailed breakdown
            self.logger.debug(f"Conversion breakdown: {conversion_stats}")
            
            # Handle conversion errors
            if conversion_errors:
                self.logger.warning(f"Encountered {len(conversion_errors)} conversion errors")
                if len(conversion_errors) > 5:  # Log first 5 errors to avoid spam
                    self.logger.warning(f"First 5 errors: {conversion_errors[:5]}")
                else:
                    self.logger.warning(f"All errors: {conversion_errors}")
                
                # Decide whether to raise exception based on error severity
                if total_successful == 0 and total_attempted > 0:
                    # Complete failure - raise exception
                    raise FHIRConversionError(
                        f"Failed to create any FHIR resources from {total_attempted} input items",
                        details={
                            'patient_id': patient_id,
                            'total_attempted': total_attempted,
                            'total_successful': total_successful,
                            'conversion_errors': conversion_errors[:10],  # Limit to 10 errors
                            'conversion_stats': conversion_stats
                        }
                    )
                elif success_rate < 0.5:
                    # Low success rate - log warning but continue
                    self.logger.warning(f"Low conversion success rate: {success_rate:.1%}")
            
            return resources
            
        except FHIRConversionError:
            raise
        except Exception as exc:
            raise FHIRConversionError(
                f"Unexpected error during FHIR resource conversion: {str(exc)}",
                details={
                    'patient_id': patient_id,
                    'error_type': type(exc).__name__,
                    'conversion_stats': conversion_stats,
                    'conversion_errors': conversion_errors
                }
            )

    def _convert_structured_to_dict(self, structured_data: 'StructuredMedicalExtraction') -> Dict[str, Any]:
        """
        Convert StructuredMedicalExtraction to dictionary format.
        
        This method transforms Pydantic models into the dictionary format
        that existing converters expect, preserving all relevant data.
        
        Args:
            structured_data: StructuredMedicalExtraction instance
            
        Returns:
            Dictionary with converted data in expected format
        """
        converted = {
            "extraction_timestamp": structured_data.extraction_timestamp,
            "document_type": structured_data.document_type,
            "confidence_average": structured_data.confidence_average,
            "conditions": [],
            "medications": [],
            "vital_signs": [],
            "lab_results": [],
            "procedures": [],
            "providers": []
        }
        
        # Convert conditions
        for condition in structured_data.conditions:
            converted["conditions"].append({
                "name": condition.name,
                "status": condition.status,
                "confidence": condition.confidence,
                "onset_date": condition.onset_date,
                "icd_code": condition.icd_code,
                "source_text": condition.source.text,
                "source_start": condition.source.start_index,
                "source_end": condition.source.end_index
            })
        
        # Convert medications
        for medication in structured_data.medications:
            converted["medications"].append({
                "name": medication.name,
                "dosage": medication.dosage,
                "route": medication.route,
                "frequency": medication.frequency,
                "status": medication.status,
                "confidence": medication.confidence,
                "start_date": medication.start_date,
                "stop_date": medication.stop_date,
                "source_text": medication.source.text,
                "source_start": medication.source.start_index,
                "source_end": medication.source.end_index
            })
        
        # Convert vital signs
        for vital in structured_data.vital_signs:
            converted["vital_signs"].append({
                "measurement_type": vital.measurement,  # Field is 'measurement' in Pydantic model
                "value": vital.value,
                "unit": vital.unit,
                "timestamp": vital.timestamp,
                "confidence": vital.confidence,
                "source_text": vital.source.text,
                "source_start": vital.source.start_index,
                "source_end": vital.source.end_index
            })
        
        # Convert lab results
        for lab in structured_data.lab_results:
            converted["lab_results"].append({
                "test_name": lab.test_name,
                "value": lab.value,
                "unit": lab.unit,
                "reference_range": lab.reference_range,
                "status": lab.status,
                "test_date": lab.test_date,
                "confidence": lab.confidence,
                "source_text": lab.source.text,
                "source_start": lab.source.start_index,
                "source_end": lab.source.end_index
            })
        
        # Convert procedures
        for procedure in structured_data.procedures:
            converted["procedures"].append({
                "name": procedure.name,
                "procedure_date": procedure.procedure_date,
                "provider": procedure.provider,
                "outcome": procedure.outcome,
                "confidence": procedure.confidence,
                "source_text": procedure.source.text,
                "source_start": procedure.source.start_index,
                "source_end": procedure.source.end_index
            })
        
        # Convert providers
        for provider in structured_data.providers:
            converted["providers"].append({
                "name": provider.name,
                "specialty": provider.specialty,
                "role": provider.role,
                "contact_info": provider.contact_info,
                "confidence": provider.confidence,
                "source_text": provider.source.text,
                "source_start": provider.source.start_index,
                "source_end": provider.source.end_index
            })
        
        return converted

    def _create_condition_from_structured(self, condition_data: Dict[str, Any], patient_id: str, metadata: Dict[str, Any]) -> Optional[ConditionResource]:
        """Create a Condition resource from structured condition data."""
        try:
            onset_date = None
            if condition_data.get("onset_date"):
                onset_date = self._normalize_date_for_fhir(condition_data["onset_date"])
            
            return ConditionResource.create_from_diagnosis(
                patient_id=patient_id,
                condition_code=condition_data.get("icd_code") or condition_data["name"],
                condition_display=condition_data["name"],
                clinical_status=condition_data.get("status", "active"),
                onset_date=onset_date,
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create Condition from structured data: {exc}")
            return None

    def _create_medication_from_structured(self, medication_data: Dict[str, Any], patient_id: str, metadata: Dict[str, Any]) -> Optional[MedicationStatementResource]:
        """Create a MedicationStatement resource from structured medication data."""
        try:
            effective_date = None
            if medication_data.get("start_date"):
                effective_date = self._normalize_date_for_fhir(medication_data["start_date"])
            
            # Combine dosage information
            dosage_text = ""
            if medication_data.get("dosage"):
                dosage_text = medication_data["dosage"]
            if medication_data.get("frequency"):
                dosage_text += f" {medication_data['frequency']}" if dosage_text else medication_data["frequency"]
            if medication_data.get("route"):
                dosage_text += f" via {medication_data['route']}" if dosage_text else f"via {medication_data['route']}"
            
            return MedicationStatementResource.create_from_medication(
                patient_id=patient_id,
                medication_name=medication_data["name"],
                medication_code=None,  # Could be enhanced with drug codes
                dosage=dosage_text if dosage_text else None,
                frequency=medication_data.get("frequency"),
                status=medication_data.get("status", "active"),
                effective_date=effective_date,
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create MedicationStatement from structured data: {exc}")
            return None

    def _create_vital_sign_observation(self, vital_data: Dict[str, Any], patient_id: str, metadata: Dict[str, Any]) -> Optional[ObservationResource]:
        """Create an Observation resource for vital signs from structured data.
        
        Task 35.7: Updated to use clinical dates from metadata instead of processing timestamps.
        """
        try:
            observation_date = None
            
            # Priority 1: Check if vital has its own timestamp
            if vital_data.get("timestamp"):
                observation_date = self._normalize_date_for_fhir(vital_data["timestamp"])
            
            # Priority 2: Use clinical_date from metadata (Task 35.7)
            if not observation_date and metadata.get('clinical_date'):
                observation_date = metadata['clinical_date']
                if not isinstance(observation_date, datetime):
                    observation_date = datetime.combine(observation_date, datetime.min.time())
                self.logger.debug(f"Using clinical_date from metadata for vital sign: {observation_date}")
            
            # Task 35.7: No fallback to datetime.utcnow() - leave as None if no date available
            # This ensures clear separation between clinical dates and processing metadata
            if not observation_date:
                self.logger.warning(f"No clinical date available for vital sign {vital_data.get('measurement_type')}")
            
            return ObservationResource.create_from_lab_result(
                patient_id=patient_id,
                test_code=f"VITAL-{vital_data['measurement_type'].upper().replace(' ', '-')}",
                test_name=vital_data["measurement_type"],
                value=vital_data["value"],
                unit=vital_data.get("unit"),
                observation_date=observation_date,
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create vital sign observation from structured data: {exc}")
            return None

    def _create_lab_observation(self, lab_data: Dict[str, Any], patient_id: str, metadata: Dict[str, Any]) -> Optional[ObservationResource]:
        """Create an Observation resource for lab results from structured data.
        
        Task 35.7: Updated to use clinical dates from metadata instead of processing timestamps.
        """
        try:
            test_date = None
            
            # Priority 1: Check if lab has its own test_date
            if lab_data.get("test_date"):
                test_date = self._normalize_date_for_fhir(lab_data["test_date"])
            
            # Priority 2: Use clinical_date from metadata (Task 35.7)
            if not test_date and metadata.get('clinical_date'):
                test_date = metadata['clinical_date']
                if not isinstance(test_date, datetime):
                    test_date = datetime.combine(test_date, datetime.min.time())
                self.logger.debug(f"Using clinical_date from metadata for lab result: {test_date}")
            
            # Task 35.7: No fallback to datetime.utcnow() - leave as None if no date available
            # This ensures clear separation between clinical dates and processing metadata
            if not test_date:
                self.logger.warning(f"No clinical date available for lab result {lab_data.get('test_name')}")
            
            return ObservationResource.create_from_lab_result(
                patient_id=patient_id,
                test_code=f"LAB-{hash(lab_data['test_name'].lower()) % 100000:05d}",
                test_name=lab_data["test_name"],
                value=lab_data["value"],
                unit=lab_data.get("unit"),
                observation_date=test_date,
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create lab observation from structured data: {exc}")
            return None

    def _create_procedure_resource_structured(self, procedure_data: Dict[str, Any], patient_id: str, metadata: Dict[str, Any]) -> Optional['ProcedureResource']:
        """Create a proper Procedure resource from structured data.
        
        Task 35.7: Updated to use clinical dates from metadata instead of processing timestamps.
        Replaces the old _create_procedure_observation_structured method.
        """
        try:
            procedure_date = None
            
            # Priority 1: Check if procedure has its own date
            if procedure_data.get("procedure_date"):
                procedure_date = self._normalize_date_for_fhir(procedure_data["procedure_date"])
            
            # Priority 2: Use clinical_date from metadata (Task 35.7)
            if not procedure_date and metadata.get('clinical_date'):
                procedure_date = metadata['clinical_date']
                if not isinstance(procedure_date, datetime):
                    procedure_date = datetime.combine(procedure_date, datetime.min.time())
                self.logger.debug(f"Using clinical_date from metadata for procedure: {procedure_date}")
            
            # Task 35.7: No fallback to datetime.utcnow() - leave as None if no date available
            # This ensures clear separation between clinical dates and processing metadata
            if not procedure_date:
                self.logger.warning(f"No clinical date available for procedure {procedure_data.get('name')}")
            
            from apps.fhir.fhir_models import ProcedureResource
            
            return ProcedureResource.create_from_procedure_data(
                patient_id=patient_id,
                procedure_name=procedure_data['name'],
                procedure_code=None,  # Could extract from procedure_data if available
                performed_date=procedure_date,
                status="completed",  # Could map from procedure_data.get('status')
                performer_name=procedure_data.get("provider"),
                outcome=procedure_data.get("outcome"),
                notes=None  # Could add if we have procedure notes
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create Procedure resource from structured data: {exc}")
            return None

    def _create_provider_from_structured(self, provider_data: Dict[str, Any]) -> Optional[PractitionerResource]:
        """Create a Practitioner resource from structured provider data."""
        try:
            name_parts = provider_data["name"].strip().split()
            if len(name_parts) >= 2:
                first_name = name_parts[0]
                last_name = " ".join(name_parts[1:])
            else:
                first_name = provider_data["name"]
                last_name = "Unknown"
            
            return PractitionerResource.create_from_provider(
                first_name=first_name,
                last_name=last_name,
                specialty=provider_data.get("specialty"),
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create Practitioner from structured data: {exc}")
            return None


