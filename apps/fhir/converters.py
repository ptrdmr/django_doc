"""
FHIR Resource Converters

Standalone module containing converters that transform validated document
data into FHIR resources. Kept separate for clarity and testability.

This module now includes support for structured medical data from the new
Pydantic-based AI extraction service (Task 34).
"""

import logging
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
            test_date = self._normalize_date_for_fhir(data.get("test_date")) or datetime.utcnow()

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
            note_date = self._normalize_date_for_fhir(data.get("note_date")) or datetime.utcnow()

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
            list_date = self._normalize_date_for_fhir(data.get("list_date")) or datetime.utcnow()

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
            discharge_date = self._normalize_date_for_fhir(data.get("discharge_date")) or datetime.utcnow()
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
                    proc_obs = self._create_procedure_observation(
                        procedure,
                        patient_id,
                        admission_date or discharge_date,
                    )
                    if proc_obs:
                        resources.append(proc_obs)

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

    def _create_procedure_observation(self, procedure: Any, patient_id: str, procedure_date: datetime) -> Optional[ObservationResource]:
        """Create an Observation resource for a procedure (simplified)."""
        try:
            if isinstance(procedure, dict):
                proc_name = procedure.get("name", procedure.get("description", ""))
                proc_code = procedure.get("code", "")
            else:
                proc_name = str(procedure)
                proc_code = f"PROC-{hash(proc_name.lower()) % 100000:05d}"

            if not proc_name:
                return None

            return ObservationResource.create_from_lab_result(
                patient_id=patient_id,
                test_code=proc_code or f"PROC-{hash(proc_name.lower()) % 100000:05d}",
                test_name=f"Procedure: {proc_name}",
                value="Performed",
                observation_date=procedure_date,
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create procedure observation: {exc}")
            return None


class StructuredDataConverter(BaseFHIRConverter):
    """
    Converter for structured medical data from AI extraction service.
    
    This converter bridges the new Pydantic-based AI extraction (Task 34.1) 
    with the existing FHIR engine, maintaining minimal layers while ensuring
    comprehensive document flow integration.
    
    Flow: StructuredMedicalExtraction → Dict format → Existing FHIR engine
    """

    def convert_structured_data(self, structured_data: 'StructuredMedicalExtraction', metadata: Dict[str, Any], patient) -> List[Resource]:
        """
        Convert structured medical data from AI extraction to FHIR resources.
        
        This is the main entry point that bridges AI-extracted Pydantic models
        with the existing FHIR converter infrastructure.
        
        Args:
            structured_data: StructuredMedicalExtraction from AI service
            metadata: Document metadata (document_id, extraction_timestamp, etc.)
            patient: Patient model instance
            
        Returns:
            List of FHIR Resource objects ready for the existing FHIR engine
            
        Raises:
            ValueError: If structured_data is None or invalid
            ImportError: If structured data models not available
        """
        if not structured_data:
            raise ValueError("structured_data cannot be None")
            
        if StructuredMedicalExtraction is None:
            raise ImportError("Structured medical data models not available")
        
        self.logger.info(f"Converting structured data to FHIR for patient {patient.id}")
        
        try:
            # Convert structured data to dictionary format that existing converters expect
            converted_data = self._convert_structured_to_dict(structured_data)
            
            # Use the existing convert method with the converted data
            resources = self.convert(converted_data, metadata, patient)
            
            self.logger.info(f"Successfully converted structured data to {len(resources)} FHIR resources")
            return resources
            
        except Exception as e:
            self.logger.error(f"Failed to convert structured data: {e}", exc_info=True)
            raise

    def convert(self, data: Dict[str, Any], metadata: Dict[str, Any], patient) -> List[Resource]:
        """
        Convert dictionary data to FHIR resources using existing infrastructure.
        
        This method handles the converted dictionary format and creates FHIR resources
        using the existing converter patterns and resource creation methods.
        
        Args:
            data: Converted structured data in dictionary format
            metadata: Document metadata
            patient: Patient model instance
            
        Returns:
            List of FHIR Resource objects
        """
        resources: List[Resource] = []
        patient_id = self._get_patient_id(patient)
        
        try:
            # Handle conditions/diagnoses
            if "conditions" in data and isinstance(data["conditions"], list):
                for condition_data in data["conditions"]:
                    condition = self._create_condition_from_structured(condition_data, patient_id, metadata)
                    if condition:
                        resources.append(condition)
            
            # Handle medications
            if "medications" in data and isinstance(data["medications"], list):
                for medication_data in data["medications"]:
                    medication = self._create_medication_from_structured(medication_data, patient_id, metadata)
                    if medication:
                        resources.append(medication)
            
            # Handle vital signs
            if "vital_signs" in data and isinstance(data["vital_signs"], list):
                for vital_data in data["vital_signs"]:
                    observation = self._create_vital_sign_observation(vital_data, patient_id, metadata)
                    if observation:
                        resources.append(observation)
            
            # Handle lab results
            if "lab_results" in data and isinstance(data["lab_results"], list):
                for lab_data in data["lab_results"]:
                    observation = self._create_lab_observation(lab_data, patient_id, metadata)
                    if observation:
                        resources.append(observation)
            
            # Handle procedures
            if "procedures" in data and isinstance(data["procedures"], list):
                for procedure_data in data["procedures"]:
                    observation = self._create_procedure_observation_structured(procedure_data, patient_id, metadata)
                    if observation:
                        resources.append(observation)
            
            # Handle providers
            if "providers" in data and isinstance(data["providers"], list):
                for provider_data in data["providers"]:
                    practitioner = self._create_provider_from_structured(provider_data)
                    if practitioner:
                        resources.append(practitioner)
            
            self.logger.info(f"Structured data converter created {len(resources)} resources")
            return resources
            
        except Exception as exc:
            self.logger.error(f"Structured data conversion failed: {exc}", exc_info=True)
            return []

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
                "measurement_type": vital.measurement_type,
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
        """Create an Observation resource for vital signs from structured data."""
        try:
            observation_date = None
            if vital_data.get("timestamp"):
                observation_date = self._normalize_date_for_fhir(vital_data["timestamp"])
            
            return ObservationResource.create_from_lab_result(
                patient_id=patient_id,
                test_code=f"VITAL-{vital_data['measurement_type'].upper().replace(' ', '-')}",
                test_name=vital_data["measurement_type"],
                value=vital_data["value"],
                unit=vital_data.get("unit"),
                observation_date=observation_date or datetime.utcnow(),
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create vital sign observation from structured data: {exc}")
            return None

    def _create_lab_observation(self, lab_data: Dict[str, Any], patient_id: str, metadata: Dict[str, Any]) -> Optional[ObservationResource]:
        """Create an Observation resource for lab results from structured data."""
        try:
            test_date = None
            if lab_data.get("test_date"):
                test_date = self._normalize_date_for_fhir(lab_data["test_date"])
            
            return ObservationResource.create_from_lab_result(
                patient_id=patient_id,
                test_code=f"LAB-{hash(lab_data['test_name'].lower()) % 100000:05d}",
                test_name=lab_data["test_name"],
                value=lab_data["value"],
                unit=lab_data.get("unit"),
                observation_date=test_date or datetime.utcnow(),
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create lab observation from structured data: {exc}")
            return None

    def _create_procedure_observation_structured(self, procedure_data: Dict[str, Any], patient_id: str, metadata: Dict[str, Any]) -> Optional[ObservationResource]:
        """Create an Observation resource for procedures from structured data."""
        try:
            procedure_date = None
            if procedure_data.get("procedure_date"):
                procedure_date = self._normalize_date_for_fhir(procedure_data["procedure_date"])
            
            return ObservationResource.create_from_lab_result(
                patient_id=patient_id,
                test_code=f"PROC-{hash(procedure_data['name'].lower()) % 100000:05d}",
                test_name=f"Procedure: {procedure_data['name']}",
                value=procedure_data.get("outcome", "Performed"),
                observation_date=procedure_date or datetime.utcnow(),
            )
        except Exception as exc:
            self.logger.warning(f"Failed to create procedure observation from structured data: {exc}")
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


