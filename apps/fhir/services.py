"""
FHIR Data Accumulation Service

This service handles the accumulation of FHIR resources into patient records
with proper provenance tracking, conflict resolution, and audit trails.
Follows HIPAA compliance requirements and maintains data integrity.
"""

import json
import logging
import time
from typing import Optional, List, Dict, Any, Tuple, Callable
from datetime import datetime, date
from uuid import uuid4
import re
from decimal import Decimal, InvalidOperation
import copy

from django.db import transaction
from django.utils import timezone
from django.contrib.auth.models import User
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder

from fhir.resources.bundle import Bundle, BundleEntry
from fhir.resources.resource import Resource
from fhir.resources.reference import Reference
from fhir.resources.extension import Extension

from apps.patients.models import Patient, PatientHistory
from apps.core.models import AuditLog
from apps.core.jsonb_utils import serialize_fhir_data
from .fhir_models import Meta
from .bundle_utils import (
    create_initial_patient_bundle,
    add_resource_with_provenance,
    validate_bundle_integrity,
    find_duplicate_resources,
    deduplicate_bundle,
    get_bundle_summary,
    validate_provenance_integrity,
    get_provenance_summary,
    get_latest_resource_version,
    add_resource_to_bundle,
    get_resources_by_type
)
from .validation import ValidationResult, DataNormalizer, DocumentSchemaValidator, serialize_fhir_data
from .provenance import ProvenanceTracker
from .historical_data import HistoricalResourceManager
from .deduplication import DuplicateResourceDetail, DeduplicationResult, ResourceHashGenerator, FuzzyMatcher, ResourceDeduplicator
from .validation_quality import FHIRMergeValidator, ValidationReport, ValidationSeverity, ValidationIssue, ValidationCategory
from .transaction_manager import (
    FHIRTransactionManager,
    TransactionSnapshot,
    StagingArea,
    TransactionResult,
    TransactionLockManager,
    SnapshotManager
)
from .performance_monitoring import (
    PerformanceMonitor, 
    PerformanceMetrics, 
    FHIRResourceCache, 
    BatchSizeOptimizer,
    performance_monitor,
    performance_monitor_instance
)
from .fhir_models import (
    PatientResource,
    DocumentReferenceResource,
    ConditionResource,
    ObservationResource,
    MedicationStatementResource,
    PractitionerResource,
    ProvenanceResource,
)
from .converters import (
    BaseFHIRConverter,
    GenericConverter,
    LabReportConverter,
    ClinicalNoteConverter,
    MedicationListConverter,
    DischargeSummaryConverter,
)
from .merge_handlers import (
    ResourceMergeHandlerFactory as ImportedResourceMergeHandlerFactory,
)
# Backward-compatible re-exports for tests/imports that referenced handlers here
from .merge_handlers import (
    BaseMergeHandler as _BaseMergeHandler,
    ObservationMergeHandler as _ObservationMergeHandler,
    ConditionMergeHandler as _ConditionMergeHandler,
    MedicationStatementMergeHandler as _MedicationStatementMergeHandler,
    GenericMergeHandler as _GenericMergeHandler,
    AllergyIntoleranceHandler as _AllergyIntoleranceHandler,
    ProcedureHandler as _ProcedureHandler,
    DiagnosticReportHandler as _DiagnosticReportHandler,
    CarePlanHandler as _CarePlanHandler,
)
from .conflict_detection import ConflictDetector, ConflictDetail, ConflictResult
from .conflict_resolution import (
    ConflictResolutionStrategy,
    NewestWinsStrategy,
    PreserveBothStrategy,
    ConfidenceBasedStrategy,
    ManualReviewStrategy,
    ConflictResolver,
)


logger = logging.getLogger(__name__)

# Backward-compat alias names
BaseMergeHandler = _BaseMergeHandler
ObservationMergeHandler = _ObservationMergeHandler
ConditionMergeHandler = _ConditionMergeHandler
MedicationStatementMergeHandler = _MedicationStatementMergeHandler
GenericMergeHandler = _GenericMergeHandler
AllergyIntoleranceHandler = _AllergyIntoleranceHandler
ProcedureHandler = _ProcedureHandler
DiagnosticReportHandler = _DiagnosticReportHandler
CarePlanHandler = _CarePlanHandler


def fhir_json_serializer(obj):
    """
    Custom JSON serializer for FHIR objects that handles Decimal values.
    
    Like adjustin' the carburetor on your old truck - sometimes you need
    custom parts to make different components work together properly.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


# Provenance tracking classes moved to provenance.py


# Validation classes moved to validation.py


class FHIRAccumulationError(Exception):
    """Custom exception for FHIR accumulation errors."""
    pass


class FHIRValidationError(FHIRAccumulationError):
    """Exception for FHIR validation failures."""
    pass


class FHIRAccumulator:
    """
    Service class for accumulating FHIR resources into patient records.
    
    Provides append-only accumulation with provenance tracking, conflict
    resolution, and comprehensive audit trails for HIPAA compliance.
    """
    
    def __init__(self):
        """Initialize the FHIR accumulator service."""
        self.logger = logger
        self.historical_manager = HistoricalResourceManager()
        
    def add_resources_to_patient(
        self,
        patient: Patient,
        fhir_resources: List[Dict[str, Any]],
        source_system: str,
        responsible_user: Optional[User] = None,
        source_document_id: Optional[str] = None,
        reason: str = "Document processing",
        validate_fhir: bool = True,
        resolve_conflicts: bool = True
    ) -> Dict[str, Any]:
        """
        Add FHIR resources to a patient's cumulative record.
        
        Args:
            patient: Patient object to add resources to
            fhir_resources: List of FHIR resource dictionaries
            source_system: Identifier for the source system (e.g., "DocumentAnalyzer")
            responsible_user: User responsible for the action
            source_document_id: Optional ID of source document
            reason: Reason for adding the resources
            validate_fhir: Whether to validate FHIR resources
            resolve_conflicts: Whether to automatically resolve conflicts
            
        Returns:
            Dictionary with accumulation results and metadata
            
        Raises:
            FHIRAccumulationError: If accumulation fails
            FHIRValidationError: If FHIR validation fails
        """
        if not patient:
            error_msg = "Patient is required"
            self.logger.error(error_msg)
            raise FHIRAccumulationError(error_msg)
        
        if not fhir_resources:
            self.logger.warning(f"No FHIR resources provided for patient {patient.mrn}")
            return {
                'success': True,
                'resources_added': 0,
                'resources_skipped': 0,
                'conflicts_resolved': 0,
                'bundle_version': None,
                'warnings': ['No resources provided']
            }
        
        if not source_system:
            raise FHIRAccumulationError("Source system is required")
        
        accumulation_result = {
            'success': False,
            'resources_added': 0,
            'resources_skipped': 0,
            'conflicts_resolved': 0,
            'bundle_version': None,
            'warnings': [],
            'errors': []
        }
        
        try:
            with transaction.atomic():
                # Log the start of accumulation
                AuditLog.log_event(
                    event_type='fhir_import',
                    user=responsible_user,
                    description=f"Starting FHIR accumulation for patient {patient.mrn}",
                    details={
                        'patient_mrn': patient.mrn,
                        'resource_count': len(fhir_resources),
                        'source_system': source_system,
                        'source_document_id': source_document_id,
                        'reason': reason
                    },
                    patient_mrn=patient.mrn,
                    phi_involved=True,
                    content_object=patient
                )
                
                # Validate FHIR resources if requested
                if validate_fhir:
                    validation_results = self._validate_fhir_resources(fhir_resources)
                    if not validation_results['is_valid']:
                        accumulation_result['errors'].extend(validation_results['errors'])
                        if validation_results['critical_errors']:
                            raise FHIRValidationError(
                                f"Critical FHIR validation errors: {validation_results['critical_errors']}"
                            )
                        accumulation_result['warnings'].extend(validation_results['warnings'])
                
                # Load or create patient's FHIR bundle
                bundle = self._load_patient_bundle(patient)
                
                # Convert and add each resource
                for resource_data in fhir_resources:
                    try:
                        # Convert to FHIR resource object
                        fhir_resource = self._convert_to_fhir_resource(resource_data)
                        
                        if not fhir_resource:
                            accumulation_result['resources_skipped'] += 1
                            accumulation_result['warnings'].append(
                                f"Skipped unsupported resource type: {resource_data.get('resourceType', 'Unknown')}"
                            )
                            continue
                        
                        # Check for conflicts if resolution is enabled
                        if resolve_conflicts:
                            conflict_resolution = self._resolve_resource_conflicts(bundle, fhir_resource)
                            if conflict_resolution['action'] == 'skip':
                                accumulation_result['resources_skipped'] += 1
                                accumulation_result['warnings'].append(
                                    f"Skipped duplicate resource: {fhir_resource.resource_type}/{fhir_resource.id}"
                                )
                                continue
                            elif conflict_resolution['action'] == 'merge':
                                accumulation_result['conflicts_resolved'] += 1
                                accumulation_result['warnings'].append(
                                    f"Merged conflicting resource: {fhir_resource.resource_type}/{fhir_resource.id}"
                                )
                        
                        # Preserve historical data before adding new resource
                        bundle, preservation_result = self.historical_manager.preserve_resource_history(
                            bundle=bundle,
                            new_resource=fhir_resource,
                            source_metadata={
                                'document_id': source_document_id,
                                'document_type': 'unknown',  # Could be enhanced
                                'reason': reason,
                                'source_system': source_system
                            },
                            user=responsible_user,
                            preserve_reason=f"Document processing: {reason}"
                        )
                        
                        # Track historical preservation count
                        if preservation_result.get('historical_versions_preserved', 0) > 0:
                            accumulation_result['historical_preservation_count'] = accumulation_result.get('historical_preservation_count', 0) + preservation_result.get('historical_versions_preserved', 0)
                        
                        # Update accumulation result with preservation info
                        if preservation_result.get('historical_versions_preserved', 0) > 0:
                            accumulation_result['warnings'].append(
                                f"Preserved {preservation_result['historical_versions_preserved']} historical version(s)"
                            )
                        
                        if preservation_result.get('status_transition_recorded'):
                            status_transition = preservation_result.get('status_transition', {})
                            accumulation_result['warnings'].append(
                                f"Status transition recorded: {status_transition.get('old_status')} -> {status_transition.get('new_status')}"
                            )
                        
                        # Add resource with provenance (this is now handled by historical manager)
                        # bundle = add_resource_with_provenance(
                        #     bundle=bundle,
                        #     resource=fhir_resource,
                        #     source_system=source_system,
                        #     responsible_party=responsible_user.username if responsible_user else None,
                        #     reason=reason,
                        #     source_document_id=source_document_id,
                        #     update_existing=True
                        # )
                        
                        accumulation_result['resources_added'] += 1
                        
                        self.logger.info(
                            f"Added FHIR resource {fhir_resource.resource_type}/{fhir_resource.id} "
                            f"to patient {patient.mrn}"
                        )
                        
                    except Exception as e:
                        error_msg = f"Error processing resource {resource_data.get('resourceType', 'Unknown')}: {str(e)}"
                        accumulation_result['errors'].append(error_msg)
                        accumulation_result['resources_skipped'] += 1
                        self.logger.error(error_msg, exc_info=True)
                
                # Validate final bundle integrity
                bundle_validation = validate_bundle_integrity(bundle)
                if not bundle_validation['is_valid']:
                    accumulation_result['errors'].extend(bundle_validation['issues'])
                    if any('critical' in issue.lower() for issue in bundle_validation['issues']):
                        raise FHIRAccumulationError(
                            f"Bundle integrity validation failed: {bundle_validation['issues']}"
                        )
                
                # Save the updated bundle back to patient
                patient.cumulative_fhir_json = serialize_fhir_data(bundle.dict())
                patient.save()
                
                # Record patient history for standard FHIR append
                self._record_patient_history(
                    patient=patient,
                    action='fhir_append',
                    user=responsible_user,
                    fhir_delta=fhir_resources,
                    source_document_id=source_document_id,
                    details={
                        'resources_added': accumulation_result['resources_added'],
                        'resources_skipped': accumulation_result['resources_skipped'],
                        'conflicts_resolved': accumulation_result['conflicts_resolved'],
                        'source_system': source_system,
                        'reason': reason,
                        'historical_preservation_enabled': True
                    }
                )
                
                # Record additional patient history for historical preservation if any occurred
                total_historical_preserved = accumulation_result.get('historical_preservation_count', 0)
                
                if total_historical_preserved > 0:
                    self._record_patient_history(
                        patient=patient,
                        action='fhir_history_preserved',
                        user=responsible_user,
                        fhir_delta=[],  # Historical versions are preserved, not added
                        source_document_id=source_document_id,
                        details={
                            'historical_versions_preserved': total_historical_preserved,
                            'preservation_reason': f"Document processing: {reason}",
                            'source_system': source_system,
                            'reason': reason
                        }
                    )
                
                # Get bundle version for result
                accumulation_result['bundle_version'] = bundle.meta.versionId if bundle.meta else "1"
                accumulation_result['success'] = True
                
                # Log successful completion
                AuditLog.log_event(
                    event_type='fhir_import',
                    user=responsible_user,
                    description=f"Successfully completed FHIR accumulation for patient {patient.mrn}",
                    details=accumulation_result,
                    patient_mrn=patient.mrn,
                    phi_involved=True,
                    content_object=patient,
                    success=True
                )
                
                self.logger.info(
                    f"FHIR accumulation completed for patient {patient.mrn}: "
                    f"{accumulation_result['resources_added']} added, "
                    f"{accumulation_result['resources_skipped']} skipped, "
                    f"{accumulation_result['conflicts_resolved']} conflicts resolved"
                )
                
                return accumulation_result
                
        except Exception as e:
            # Log the error
            error_msg = f"FHIR accumulation failed for patient {patient.mrn}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            
            AuditLog.log_event(
                event_type='fhir_import',
                user=responsible_user,
                description=f"FHIR accumulation failed for patient {patient.mrn}",
                details={'error': str(e), 'partial_results': accumulation_result},
                patient_mrn=patient.mrn,
                phi_involved=True,
                content_object=patient,
                success=False,
                error_message=str(e)
            )
            
            accumulation_result['errors'].append(error_msg)
            raise FHIRAccumulationError(error_msg) from e
    
    def get_patient_fhir_summary(
        self,
        patient: Patient,
        include_provenance: bool = True
    ) -> Dict[str, Any]:
        """
        Get a summary of the patient's FHIR data.
        
        Args:
            patient: Patient object
            include_provenance: Whether to include provenance information
            
        Returns:
            Dictionary with FHIR summary information
        """
        if not patient:
            raise FHIRAccumulationError("Patient is required")
        
        # Load patient's bundle
        bundle = self._load_patient_bundle(patient)
        
        # Get basic bundle summary
        summary = get_bundle_summary(bundle)
        
        # Add provenance information if requested
        if include_provenance:
            provenance_validation = validate_provenance_integrity(bundle)
            summary['provenance'] = {
                'total_provenance_resources': provenance_validation['total_provenance_resources'],
                'resources_with_provenance': provenance_validation['resources_with_provenance'],
                'resources_without_provenance': provenance_validation['resources_without_provenance'],
                'provenance_valid': provenance_validation['is_valid']
            }
        
        # Add metadata
        summary['patient_mrn'] = patient.mrn
        summary['last_updated'] = patient.updated_at.isoformat()
        summary['generated_at'] = timezone.now().isoformat()
        
        return summary
    
    def validate_patient_fhir_data(self, patient: Patient) -> Dict[str, Any]:
        """
        Validate the integrity of a patient's FHIR data.
        
        Args:
            patient: Patient object to validate
            
        Returns:
            Dictionary with validation results
        """
        if not patient:
            raise FHIRAccumulationError("Patient is required")
        
        validation_result = {
            'patient_mrn': patient.mrn,
            'is_valid': True,
            'bundle_valid': True,
            'provenance_valid': True,
            'issues': [],
            'warnings': [],
            'resource_counts': {},
            'duplicate_resources': [],
            'orphaned_provenance': []
        }
        
        try:
            # Load patient's bundle
            bundle = self._load_patient_bundle(patient)
            
            # Validate bundle integrity
            bundle_validation = validate_bundle_integrity(bundle)
            validation_result['bundle_valid'] = bundle_validation['is_valid']
            validation_result['resource_counts'] = bundle_validation['resource_counts']
            
            if not bundle_validation['is_valid']:
                validation_result['is_valid'] = False
                validation_result['issues'].extend(bundle_validation['issues'])
            
            # Validate provenance integrity
            provenance_validation = validate_provenance_integrity(bundle)
            validation_result['provenance_valid'] = provenance_validation['is_valid']
            
            if not provenance_validation['is_valid']:
                validation_result['is_valid'] = False
                validation_result['issues'].extend(provenance_validation['issues'])
            
            # Check for duplicate resources
            duplicates = find_duplicate_resources(bundle)
            if duplicates:
                validation_result['duplicate_resources'] = duplicates
                validation_result['warnings'].append(f"Found {len(duplicates)} duplicate resource groups")
            
            # Add summary information
            validation_result['total_resources'] = bundle_validation['resource_count']
            validation_result['validated_at'] = timezone.now().isoformat()
            
        except Exception as e:
            validation_result['is_valid'] = False
            validation_result['issues'].append(f"Validation error: {str(e)}")
            self.logger.error(f"FHIR validation failed for patient {patient.mrn}: {str(e)}", exc_info=True)
        
        return validation_result
    
    def get_patient_resource_timeline(
        self,
        patient: Patient,
        resource_type: str,
        resource_id: str,
        include_provenance: bool = True
    ) -> Dict[str, Any]:
        """
        Get the complete timeline of changes for a specific patient resource.
        
        Args:
            patient: Patient object
            resource_type: Type of resource
            resource_id: ID of the resource
            include_provenance: Whether to include provenance information
            
        Returns:
            Dictionary with timeline information
        """
        if not patient:
            raise FHIRAccumulationError("Patient is required")
        
        # Load patient's bundle
        bundle = self._load_patient_bundle(patient)
        
        # Use the historical manager to get timeline
        timeline = self.historical_manager.get_resource_timeline(
            bundle, resource_type, resource_id, include_provenance
        )
        
        # Add patient context
        timeline['patient_mrn'] = patient.mrn
        timeline['patient_id'] = str(patient.id)
        
        return timeline
    
    def validate_patient_historical_integrity(
        self,
        patient: Patient,
        resource_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validate the historical integrity of a patient's FHIR data.
        
        Args:
            patient: Patient object to validate
            resource_type: Optional resource type to limit validation
            
        Returns:
            Dictionary with validation results
        """
        if not patient:
            raise FHIRAccumulationError("Patient is required")
        
        # Load patient's bundle
        bundle = self._load_patient_bundle(patient)
        
        # Use the historical manager to validate
        validation_result = self.historical_manager.validate_historical_integrity(
            bundle, resource_type
        )
        
        # Add patient context
        validation_result['patient_mrn'] = patient.mrn
        validation_result['patient_id'] = str(patient.id)
        
        return validation_result
    
    def deduplicate_patient_fhir_data(
        self,
        patient: Patient,
        user: Optional[User] = None,
        keep_latest: bool = True
    ) -> Dict[str, Any]:
        """
        Remove duplicate FHIR resources from a patient's record.
        
        Args:
            patient: Patient object
            user: User performing the deduplication
            keep_latest: Whether to keep the latest version of duplicates
            
        Returns:
            Dictionary with deduplication results
        """
        if not patient:
            raise FHIRAccumulationError("Patient is required")
        
        deduplication_result = {
            'patient_mrn': patient.mrn,
            'success': False,
            'duplicates_found': 0,
            'resources_removed': 0,
            'bundle_version_before': None,
            'bundle_version_after': None
        }
        
        try:
            with transaction.atomic():
                # Load patient's bundle
                bundle = self._load_patient_bundle(patient)
                deduplication_result['bundle_version_before'] = bundle.meta.versionId if bundle.meta else "1"
                
                # Find duplicates before deduplication
                duplicates_before = find_duplicate_resources(bundle)
                deduplication_result['duplicates_found'] = len(duplicates_before)
                
                if duplicates_before:
                    # Deduplicate the bundle
                    deduplicated_bundle = deduplicate_bundle(bundle, keep_latest=keep_latest)
                    
                    # Calculate resources removed
                    resources_before = len(bundle.entry) if bundle.entry else 0
                    resources_after = len(deduplicated_bundle.entry) if deduplicated_bundle.entry else 0
                    deduplication_result['resources_removed'] = resources_before - resources_after
                    
                    # Save the deduplicated bundle with proper serialization
                    patient.cumulative_fhir_json = serialize_fhir_data(deduplicated_bundle.dict())
                    patient.save()
                    
                    deduplication_result['bundle_version_after'] = deduplicated_bundle.meta.versionId if deduplicated_bundle.meta else "1"
                    
                    # Record patient history
                    self._record_patient_history(
                        patient=patient,
                        action='fhir_deduplicate',
                        user=user,
                        details={
                            'duplicates_found': deduplication_result['duplicates_found'],
                            'resources_removed': deduplication_result['resources_removed'],
                            'keep_latest': keep_latest
                        }
                    )
                    
                    # Log the deduplication
                    AuditLog.log_event(
                        event_type='phi_update',
                        user=user,
                        description=f"Deduplicated FHIR data for patient {patient.mrn}",
                        details=deduplication_result,
                        patient_mrn=patient.mrn,
                        phi_involved=True,
                        content_object=patient
                    )
                    
                    self.logger.info(
                        f"Deduplicated FHIR data for patient {patient.mrn}: "
                        f"removed {deduplication_result['resources_removed']} duplicate resources"
                    )
                
                deduplication_result['success'] = True
                return deduplication_result
                
        except Exception as e:
            error_msg = f"FHIR deduplication failed for patient {patient.mrn}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise FHIRAccumulationError(error_msg) from e
    
    def _load_patient_bundle(self, patient: Patient) -> Bundle:
        """
        Load the patient's FHIR bundle from the cumulative_fhir_json field.
        
        Args:
            patient: Patient object
            
        Returns:
            FHIR Bundle object
        """
        if not patient.cumulative_fhir_json:
            # Create initial bundle with basic patient resource
            patient_resource = PatientResource.from_patient_model(patient)
            bundle = create_initial_patient_bundle(patient_resource)
            return bundle
        
        try:
            # Load existing bundle from JSON
            bundle_dict = patient.cumulative_fhir_json
            bundle = Bundle(**bundle_dict)
            return bundle
        except Exception as e:
            self.logger.error(
                f"Failed to load FHIR bundle for patient {patient.mrn}: {str(e)}",
                exc_info=True
            )
            # Fall back to creating new bundle
            patient_resource = PatientResource.from_patient_model(patient)
            bundle = create_initial_patient_bundle(patient_resource)
            return bundle
    
    def _validate_fhir_resources(self, fhir_resources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate FHIR resources against FHIR specification.
        
        Args:
            fhir_resources: List of FHIR resource dictionaries
            
        Returns:
            Dictionary with validation results
        """
        validation_result = {
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'critical_errors': []
        }
        
        for i, resource_data in enumerate(fhir_resources):
            try:
                resource_type = resource_data.get('resourceType')
                
                if not resource_type:
                    error_msg = f"Resource {i}: Missing resourceType"
                    validation_result['errors'].append(error_msg)
                    validation_result['critical_errors'].append(error_msg)
                    validation_result['is_valid'] = False
                    continue
                
                # Check required fields based on resource type
                if resource_type == 'Patient':
                    if not resource_data.get('id'):
                        validation_result['warnings'].append(f"Patient resource {i}: Missing ID")
                elif resource_type == 'Condition':
                    if not resource_data.get('subject'):
                        error_msg = f"Condition resource {i}: Missing subject reference"
                        validation_result['errors'].append(error_msg)
                        validation_result['is_valid'] = False
                elif resource_type == 'Observation':
                    if not resource_data.get('subject'):
                        error_msg = f"Observation resource {i}: Missing subject reference"
                        validation_result['errors'].append(error_msg)
                        validation_result['is_valid'] = False
                elif resource_type == 'MedicationStatement':
                    if not resource_data.get('subject'):
                        error_msg = f"MedicationStatement resource {i}: Missing subject reference"
                        validation_result['errors'].append(error_msg)
                        validation_result['is_valid'] = False
                
                # Validate JSON structure
                if not isinstance(resource_data, dict):
                    error_msg = f"Resource {i}: Invalid JSON structure"
                    validation_result['errors'].append(error_msg)
                    validation_result['critical_errors'].append(error_msg)
                    validation_result['is_valid'] = False
                
            except Exception as e:
                error_msg = f"Resource {i}: Validation error: {str(e)}"
                validation_result['errors'].append(error_msg)
                validation_result['is_valid'] = False
        
        return validation_result
    
    def _convert_to_fhir_resource(self, resource_data: Dict[str, Any]) -> Optional[Resource]:
        """
        Convert a resource dictionary to a FHIR resource object.
        
        Args:
            resource_data: Dictionary containing FHIR resource data
            
        Returns:
            FHIR Resource object or None if conversion fails
        """
        try:
            resource_type = resource_data.get('resourceType')
            
            if not resource_type:
                self.logger.warning("Resource missing resourceType field")
                return None
            
            # Generate ID if missing
            if not resource_data.get('id'):
                resource_data['id'] = str(uuid4())
            
            # Convert based on resource type
            if resource_type == 'Patient':
                return PatientResource(**resource_data)
            elif resource_type == 'DocumentReference':
                return DocumentReferenceResource(**resource_data)
            elif resource_type == 'Condition':
                return ConditionResource(**resource_data)
            elif resource_type == 'Observation':
                return ObservationResource(**resource_data)
            elif resource_type == 'MedicationStatement':
                return MedicationStatementResource(**resource_data)
            elif resource_type == 'Practitioner':
                return PractitionerResource(**resource_data)
            else:
                self.logger.warning(f"Unsupported resource type: {resource_type}")
                return None
                
        except Exception as e:
            self.logger.error(f"Failed to convert resource to FHIR object: {str(e)}", exc_info=True)
            return None
    
    def _resolve_resource_conflicts(
        self,
        bundle: Bundle,
        new_resource: Resource
    ) -> Dict[str, Any]:
        """
        Resolve conflicts when adding a new resource to the bundle.
        
        Args:
            bundle: Existing FHIR bundle
            new_resource: New resource to add
            
        Returns:
            Dictionary with conflict resolution action and details
        """
        conflict_resolution = {
            'action': 'add',  # 'add', 'skip', 'merge', 'update'
            'reason': 'No conflicts found',
            'existing_resource_id': None
        }
        
        # Find potential conflicts (same type and same clinical data)
        existing_resources = []
        if bundle.entry:
            for entry in bundle.entry:
                if (entry.resource and 
                    entry.resource.resource_type == new_resource.resource_type):
                    existing_resources.append(entry.resource)
        
        # Check for duplicates using business logic
        for existing_resource in existing_resources:
            try:
                # Import here to avoid circular imports
                from .bundle_utils import are_resources_clinically_equivalent
                
                if are_resources_clinically_equivalent(existing_resource, new_resource):
                    conflict_resolution['action'] = 'skip'
                    conflict_resolution['reason'] = 'Clinically equivalent resource already exists'
                    conflict_resolution['existing_resource_id'] = existing_resource.id
                    break
                    
            except Exception as e:
                self.logger.warning(f"Error comparing resources: {str(e)}")
                # Continue with other resources
        
        return conflict_resolution
    
    def _record_patient_history(
        self,
        patient: Patient,
        action: str,
        user: Optional[User] = None,
        fhir_delta: Optional[List[Dict[str, Any]]] = None,
        source_document_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Record patient history for audit trail.
        
        Args:
            patient: Patient object
            action: Action performed
            user: User who performed the action
            fhir_delta: FHIR resources added/changed
            source_document_id: Source document ID if applicable
            details: Additional details
        """
        try:
            # Create patient history record with appropriate notes
            if action == 'fhir_history_preserved' and details:
                notes = f"Historical data preservation: {details.get('historical_versions_preserved', 0)} historical_versions_preserved"
            else:
                notes = f"FHIR accumulation: {details.get('reason', 'Unknown')} via {details.get('source_system', 'Unknown')}" if details else ""
                
            history_record = PatientHistory.objects.create(
                patient=patient,
                action=action,
                changed_by=user,
                fhir_delta=fhir_delta or [],
                notes=notes
            )
            
            self.logger.info(f"Recorded patient history for {patient.mrn}: {action}")
            
        except Exception as e:
            self.logger.error(f"Failed to record patient history: {str(e)}", exc_info=True)
            # Don't raise exception - this shouldn't block the main operation


# Historical data preservation classes moved to historical_data.py


# =============================================================================
# FHIR MERGE SERVICE
# =============================================================================

class FHIRMergeError(Exception):
    """Custom exception for FHIR merge operation errors."""
    pass


class FHIRConflictError(FHIRMergeError):
    """Exception for FHIR data conflicts that cannot be automatically resolved."""
    pass


 


 


class MergeResult:
    """
    Comprehensive data class to track and summarize the results of a FHIR merge operation.
    
    Provides detailed metrics, human-readable summaries, and serialization capabilities
    for analysis and display in the user interface.
    """
    
    def __init__(self):
        # Core operation status
        self.success = False
        self.operation_type = "fhir_merge"  # Type of operation performed
        self.patient_mrn = None  # Patient identifier for tracking
        self.document_ids = []  # Source documents involved in merge
        
        # Validation results
        self.validation_report = None  # ValidationReport instance
        
        # Resource tracking
        self.resources_added = 0
        self.resources_updated = 0
        self.resources_skipped = 0
        self.resources_by_type = {}  # Track counts per resource type
        
        # Conflict tracking
        self.conflicts_detected = 0
        self.conflicts_resolved = 0
        self.conflicts_unresolved = 0
        self.critical_conflicts = 0
        
        # Deduplication tracking
        self.duplicates_removed = 0
        self.duplicates_by_type = {}  # Track duplicates per resource type
        
        # Validation tracking
        self.validation_errors = []
        self.validation_warnings = []
        self.validation_score = 100.0  # Quality score (0-100)
        
        # Error tracking
        self.merge_errors = []
        self.warning_messages = []
        self.info_messages = []
        
        # Version tracking
        self.bundle_version_before = None
        self.bundle_version_after = None
        self.bundle_size_before = 0
        self.bundle_size_after = 0
        
        # Provenance and audit
        self.provenance_resources_created = 0
        self.audit_log_ids = []
        self.transaction_id = None
        
        # Performance metrics
        self.processing_time_seconds = 0.0
        self.memory_usage_mb = 0.0
        self.api_calls_made = 0
        self.performance_metrics = None  # PerformanceMetrics instance
        
        # Timestamp tracking
        self.timestamp = timezone.now()
        self.started_at = None
        self.completed_at = None
        
        # Detailed result objects
        self.conflict_result = ConflictResult()
        self.deduplication_result = None
        self.transaction_result = None
        
        # User context
        self.performed_by_user_id = None
        self.performed_by_username = None
    
    def add_resource(self, resource_type: str, action: str = "added"):
        """Track a resource action during merge."""
        if action == "added":
            self.resources_added += 1
        elif action == "updated":
            self.resources_updated += 1
        elif action == "skipped":
            self.resources_skipped += 1
        
        # Track by resource type
        if resource_type not in self.resources_by_type:
            self.resources_by_type[resource_type] = {"added": 0, "updated": 0, "skipped": 0}
        self.resources_by_type[resource_type][action] += 1
    
    def add_duplicate_removed(self, resource_type: str):
        """Track a duplicate resource removal."""
        self.duplicates_removed += 1
        if resource_type not in self.duplicates_by_type:
            self.duplicates_by_type[resource_type] = 0
        self.duplicates_by_type[resource_type] += 1
    
    def add_validation_issue(self, issue_type: str, message: str, field: str = None, severity: str = "error"):
        """Add a validation issue to the result."""
        issue = {
            "type": issue_type,
            "message": message,
            "field": field,
            "severity": severity,
            "timestamp": timezone.now().isoformat()
        }
        
        if severity == "error":
            self.validation_errors.append(issue)
            self.validation_score = max(0, self.validation_score - 10)
        elif severity == "warning":
            self.validation_warnings.append(issue)
            self.validation_score = max(0, self.validation_score - 2)
    
    def add_merge_error(self, error_type: str, message: str, exception: Exception = None):
        """Add a merge error to the result."""
        error = {
            "type": error_type,
            "message": message,
            "exception": str(exception) if exception else None,
            "timestamp": timezone.now().isoformat()
        }
        self.merge_errors.append(error)
    
    def add_message(self, message: str, level: str = "info"):
        """Add an informational message."""
        msg = {
            "message": message,
            "timestamp": timezone.now().isoformat()
        }
        
        if level == "warning":
            self.warning_messages.append(msg)
        else:
            self.info_messages.append(msg)
    
    def set_performance_metrics(self, processing_time: float, memory_usage: float = 0.0, api_calls: int = 0):
        """Set performance metrics."""
        self.processing_time_seconds = processing_time
        self.memory_usage_mb = memory_usage
        self.api_calls_made = api_calls
    
    def get_total_resources_processed(self) -> int:
        """Get total number of resources processed."""
        return self.resources_added + self.resources_updated + self.resources_skipped
    
    def get_success_rate(self) -> float:
        """Calculate success rate as percentage."""
        total = self.get_total_resources_processed()
        if total == 0:
            return 100.0
        successful = self.resources_added + self.resources_updated
        return (successful / total) * 100.0
    
    def get_conflict_resolution_rate(self) -> float:
        """Calculate conflict resolution rate as percentage."""
        if self.conflicts_detected == 0:
            return 100.0
        return (self.conflicts_resolved / self.conflicts_detected) * 100.0
    
    def get_operation_summary(self) -> str:
        """Generate a concise operation summary."""
        total_resources = self.get_total_resources_processed()
        success_rate = self.get_success_rate()
        
        if self.success:
            status = "✅ Successful"
        elif self.merge_errors:
            status = "❌ Failed"
        else:
            status = "⚠️ Completed with issues"
        
        return (f"{status} - Processed {total_resources} resources "
                f"({success_rate:.1f}% success rate) in {self.processing_time_seconds:.2f}s")
    
    def get_detailed_summary(self) -> str:
        """Generate a comprehensive human-readable summary."""
        lines = []
        lines.append("=" * 60)
        lines.append("FHIR MERGE OPERATION SUMMARY")
        lines.append("=" * 60)
        
        # Basic info
        lines.append(f"Operation: {self.operation_type}")
        lines.append(f"Patient MRN: {self.patient_mrn}")
        lines.append(f"Timestamp: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append(f"Status: {self.get_operation_summary()}")
        
        if self.performed_by_username:
            lines.append(f"Performed by: {self.performed_by_username}")
        
        lines.append("")
        
        # Resource processing summary
        lines.append("RESOURCE PROCESSING:")
        lines.append(f"  • Resources Added: {self.resources_added}")
        lines.append(f"  • Resources Updated: {self.resources_updated}")
        lines.append(f"  • Resources Skipped: {self.resources_skipped}")
        lines.append(f"  • Total Processed: {self.get_total_resources_processed()}")
        
        if self.resources_by_type:
            lines.append("\n  By Resource Type:")
            for resource_type, counts in self.resources_by_type.items():
                total = counts["added"] + counts["updated"] + counts["skipped"]
                lines.append(f"    - {resource_type}: {total} total "
                           f"({counts['added']} added, {counts['updated']} updated, {counts['skipped']} skipped)")
        
        lines.append("")
        
        # Conflict summary
        if self.conflicts_detected > 0:
            resolution_rate = self.get_conflict_resolution_rate()
            lines.append("CONFLICT RESOLUTION:")
            lines.append(f"  • Conflicts Detected: {self.conflicts_detected}")
            lines.append(f"  • Conflicts Resolved: {self.conflicts_resolved}")
            lines.append(f"  • Conflicts Unresolved: {self.conflicts_unresolved}")
            lines.append(f"  • Critical Conflicts: {self.critical_conflicts}")
            lines.append(f"  • Resolution Rate: {resolution_rate:.1f}%")
            lines.append("")
        
        # Deduplication summary
        if self.duplicates_removed > 0:
            lines.append("DEDUPLICATION:")
            lines.append(f"  • Duplicates Removed: {self.duplicates_removed}")
            
            if self.duplicates_by_type:
                lines.append("  By Resource Type:")
                for resource_type, count in self.duplicates_by_type.items():
                    lines.append(f"    - {resource_type}: {count} duplicates")
            lines.append("")
        
        # Validation summary
        if self.validation_errors or self.validation_warnings:
            lines.append("VALIDATION:")
            lines.append(f"  • Validation Score: {self.validation_score:.1f}/100")
            lines.append(f"  • Errors: {len(self.validation_errors)}")
            lines.append(f"  • Warnings: {len(self.validation_warnings)}")
            
            if self.validation_errors:
                lines.append("  Recent Errors:")
                for error in self.validation_errors[-3:]:  # Show last 3 errors
                    lines.append(f"    - {error['message']}")
            lines.append("")
        
        # Performance metrics
        lines.append("PERFORMANCE:")
        lines.append(f"  • Processing Time: {self.processing_time_seconds:.2f} seconds")
        if self.memory_usage_mb > 0:
            lines.append(f"  • Memory Usage: {self.memory_usage_mb:.1f} MB")
        if self.api_calls_made > 0:
            lines.append(f"  • API Calls Made: {self.api_calls_made}")
        lines.append("")
        
        # Bundle versioning
        if self.bundle_version_before and self.bundle_version_after:
            lines.append("BUNDLE VERSIONING:")
            lines.append(f"  • Version Before: {self.bundle_version_before}")
            lines.append(f"  • Version After: {self.bundle_version_after}")
            lines.append(f"  • Size Before: {self.bundle_size_before} resources")
            lines.append(f"  • Size After: {self.bundle_size_after} resources")
            lines.append("")
        
        # Provenance tracking
        if self.provenance_resources_created > 0:
            lines.append("PROVENANCE:")
            lines.append(f"  • Provenance Resources Created: {self.provenance_resources_created}")
            if self.audit_log_ids:
                lines.append(f"  • Audit Log Entries: {len(self.audit_log_ids)}")
            lines.append("")
        
        # Errors and warnings
        if self.merge_errors:
            lines.append("ERRORS:")
            for error in self.merge_errors:
                lines.append(f"  • {error['type']}: {error['message']}")
            lines.append("")
        
        if self.warning_messages:
            lines.append("WARNINGS:")
            for warning in self.warning_messages[-5:]:  # Show last 5 warnings
                lines.append(f"  • {warning['message']}")
            lines.append("")
        
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    def get_ui_summary(self) -> Dict[str, Any]:
        """Generate a summary formatted for UI display."""
        return {
            "status": {
                "success": self.success,
                "summary": self.get_operation_summary(),
                "timestamp": self.timestamp.isoformat()
            },
            "metrics": {
                "resources_processed": self.get_total_resources_processed(),
                "success_rate": self.get_success_rate(),
                "processing_time": self.processing_time_seconds,
                "validation_score": self.validation_score
            },
            "details": {
                "resources": {
                    "added": self.resources_added,
                    "updated": self.resources_updated,
                    "skipped": self.resources_skipped,
                    "by_type": self.resources_by_type
                },
                "conflicts": {
                    "detected": self.conflicts_detected,
                    "resolved": self.conflicts_resolved,
                    "unresolved": self.conflicts_unresolved,
                    "critical": self.critical_conflicts,
                    "resolution_rate": self.get_conflict_resolution_rate()
                },
                "deduplication": {
                    "removed": self.duplicates_removed,
                    "by_type": self.duplicates_by_type
                }
            },
            "issues": {
                "errors": len(self.merge_errors),
                "warnings": len(self.warning_messages),
                "validation_errors": len(self.validation_errors),
                "validation_warnings": len(self.validation_warnings)
            }
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert merge result to dictionary for serialization."""
        return {
            # Basic operation info
            'success': self.success,
            'operation_type': self.operation_type,
            'patient_mrn': self.patient_mrn,
            'document_ids': self.document_ids,
            
            # Resource tracking
            'resources_added': self.resources_added,
            'resources_updated': self.resources_updated,
            'resources_skipped': self.resources_skipped,
            'resources_by_type': self.resources_by_type,
            
            # Conflict tracking
            'conflicts_detected': self.conflicts_detected,
            'conflicts_resolved': self.conflicts_resolved,
            'conflicts_unresolved': self.conflicts_unresolved,
            'critical_conflicts': self.critical_conflicts,
            
            # Deduplication tracking
            'duplicates_removed': self.duplicates_removed,
            'duplicates_by_type': self.duplicates_by_type,
            
            # Validation tracking
            'validation_errors': self.validation_errors,
            'validation_warnings': self.validation_warnings,
            'validation_score': self.validation_score,
            
            # Error tracking
            'merge_errors': self.merge_errors,
            'warning_messages': self.warning_messages,
            'info_messages': self.info_messages,
            
            # Version tracking
            'bundle_version_before': self.bundle_version_before,
            'bundle_version_after': self.bundle_version_after,
            'bundle_size_before': self.bundle_size_before,
            'bundle_size_after': self.bundle_size_after,
            
            # Provenance and audit
            'provenance_resources_created': self.provenance_resources_created,
            'audit_log_ids': self.audit_log_ids,
            'transaction_id': self.transaction_id,
            
            # Performance metrics
            'processing_time_seconds': self.processing_time_seconds,
            'memory_usage_mb': self.memory_usage_mb,
            'api_calls_made': self.api_calls_made,
            
            # Timestamps
            'timestamp': self.timestamp.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            
            # User context
            'performed_by_user_id': self.performed_by_user_id,
            'performed_by_username': self.performed_by_username,
            
            # Detailed results
            'conflict_details': self.conflict_result.to_dict() if hasattr(self.conflict_result, 'to_dict') else None,
            'deduplication_summary': self.deduplication_result.get_summary() if self.deduplication_result and hasattr(self.deduplication_result, 'get_summary') else None,
            'transaction_summary': self.transaction_result.__dict__ if self.transaction_result else None,
            
            # Calculated metrics
            'total_resources_processed': self.get_total_resources_processed(),
            'success_rate': self.get_success_rate(),
            'conflict_resolution_rate': self.get_conflict_resolution_rate()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MergeResult':
        """Create MergeResult from dictionary."""
        result = cls()
        
        # Basic fields
        for field in ['success', 'operation_type', 'patient_mrn', 'document_ids', 
                     'resources_added', 'resources_updated', 'resources_skipped',
                     'conflicts_detected', 'conflicts_resolved', 'conflicts_unresolved',
                     'critical_conflicts', 'duplicates_removed', 'validation_score',
                     'bundle_version_before', 'bundle_version_after', 'bundle_size_before',
                     'bundle_size_after', 'provenance_resources_created', 'processing_time_seconds',
                     'memory_usage_mb', 'api_calls_made', 'performed_by_user_id', 
                     'performed_by_username', 'transaction_id']:
            if field in data:
                setattr(result, field, data[field])
        
        # Complex fields
        result.resources_by_type = data.get('resources_by_type', {})
        result.duplicates_by_type = data.get('duplicates_by_type', {})
        result.validation_errors = data.get('validation_errors', [])
        result.validation_warnings = data.get('validation_warnings', [])
        result.merge_errors = data.get('merge_errors', [])
        result.warning_messages = data.get('warning_messages', [])
        result.info_messages = data.get('info_messages', [])
        result.audit_log_ids = data.get('audit_log_ids', [])
        
        # Timestamps
        if 'timestamp' in data:
            result.timestamp = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
        if 'started_at' in data and data['started_at']:
            result.started_at = datetime.fromisoformat(data['started_at'].replace('Z', '+00:00'))
        if 'completed_at' in data and data['completed_at']:
            result.completed_at = datetime.fromisoformat(data['completed_at'].replace('Z', '+00:00'))
        
        return result


class ConflictDetector:
    """
    Utility class for detecting conflicts between FHIR resources.
    
    This class provides resource-specific comparison functions to identify
    semantic equivalence, conflicts, and overlapping data between resources.
    """
    
    def __init__(self):
        self.logger = logger
    
    def detect_conflicts(
        self,
        new_resource: Resource,
        existing_resource: Resource,
        resource_type: str
    ) -> List[ConflictDetail]:
        """
        Detect conflicts between a new resource and an existing resource.
        
        Args:
            new_resource: The new FHIR resource
            existing_resource: The existing FHIR resource in the bundle
            resource_type: Type of FHIR resource
            
        Returns:
            List of ConflictDetail objects describing any conflicts found
        """
        conflicts = []
        
        try:
            # Route to resource-specific conflict detection
            if resource_type == 'Observation':
                conflicts.extend(self._detect_observation_conflicts(new_resource, existing_resource))
            elif resource_type == 'Condition':
                conflicts.extend(self._detect_condition_conflicts(new_resource, existing_resource))
            elif resource_type == 'MedicationStatement':
                conflicts.extend(self._detect_medication_conflicts(new_resource, existing_resource))
            elif resource_type == 'Patient':
                conflicts.extend(self._detect_patient_conflicts(new_resource, existing_resource))
            else:
                # Generic conflict detection for unknown resource types
                conflicts.extend(self._detect_generic_conflicts(new_resource, existing_resource, resource_type))
                
        except Exception as e:
            self.logger.error(f"Error detecting conflicts for {resource_type}: {str(e)}")
            # Create a conflict to indicate detection failed
            conflicts.append(ConflictDetail(
                conflict_type='detection_error',
                resource_type=resource_type,
                field_name='conflict_detection',
                existing_value='unknown',
                new_value='unknown',
                severity='high',
                description=f"Conflict detection failed: {str(e)}"
            ))
        
        return conflicts
    
    def _detect_observation_conflicts(
        self,
        new_obs: Resource,
        existing_obs: Resource
    ) -> List[ConflictDetail]:
        """Detect conflicts specific to Observation resources."""
        conflicts = []
        resource_id = getattr(new_obs, 'id', 'unknown')
        
        # Check for value conflicts
        new_value = self._extract_observation_value(new_obs)
        existing_value = self._extract_observation_value(existing_obs)
        
        if new_value is not None and existing_value is not None and new_value != existing_value:
            # Determine severity based on value difference
            severity = self._assess_value_conflict_severity(new_value, existing_value)
            conflicts.append(ConflictDetail(
                conflict_type='value_mismatch',
                resource_type='Observation',
                field_name='value',
                existing_value=existing_value,
                new_value=new_value,
                severity=severity,
                description=f"Different observation values: {existing_value} vs {new_value}",
                resource_id=resource_id
            ))
        
        # Check for date conflicts
        new_date = getattr(new_obs, 'effectiveDateTime', None)
        existing_date = getattr(existing_obs, 'effectiveDateTime', None)
        
        if new_date and existing_date and new_date != existing_date:
            # Check if dates are suspiciously different (same test, very different times)
            date_diff = self._calculate_date_difference_hours(new_date, existing_date)
            if date_diff > 1:  # More than 1 hour difference might be suspicious
                conflicts.append(ConflictDetail(
                    conflict_type='temporal_conflict',
                    resource_type='Observation',
                    field_name='effectiveDateTime',
                    existing_value=existing_date,
                    new_value=new_date,
                    severity='medium',
                    description=f"Different observation dates: {date_diff:.1f} hours apart",
                    resource_id=resource_id
                ))
        
        # Check for unit conflicts
        new_unit = self._extract_observation_unit(new_obs)
        existing_unit = self._extract_observation_unit(existing_obs)
        
        if new_unit and existing_unit and new_unit != existing_unit:
            conflicts.append(ConflictDetail(
                conflict_type='unit_mismatch',
                resource_type='Observation',
                field_name='unit',
                existing_value=existing_unit,
                new_value=new_unit,
                severity='high',  # Unit mismatches are serious
                description=f"Different units: {existing_unit} vs {new_unit}",
                resource_id=resource_id
            ))
        
        return conflicts
    
    def _detect_condition_conflicts(
        self,
        new_condition: Resource,
        existing_condition: Resource
    ) -> List[ConflictDetail]:
        """Detect conflicts specific to Condition resources."""
        conflicts = []
        resource_id = getattr(new_condition, 'id', 'unknown')
        
        # Check for clinical status conflicts
        new_status = getattr(new_condition, 'clinicalStatus', None)
        existing_status = getattr(existing_condition, 'clinicalStatus', None)
        
        if new_status and existing_status and new_status != existing_status:
            # Status changes can be normal progression, but flag significant conflicts
            severity = self._assess_condition_status_conflict(new_status, existing_status)
            conflicts.append(ConflictDetail(
                conflict_type='status_conflict',
                resource_type='Condition',
                field_name='clinicalStatus',
                existing_value=existing_status,
                new_value=new_status,
                severity=severity,
                description=f"Different condition status: {existing_status} vs {new_status}",
                resource_id=resource_id
            ))
        
        # Check for onset date conflicts
        new_onset = getattr(new_condition, 'onsetDateTime', None)
        existing_onset = getattr(existing_condition, 'onsetDateTime', None)
        
        if new_onset and existing_onset and new_onset != existing_onset:
            # Different onset dates for same condition could indicate data quality issues
            conflicts.append(ConflictDetail(
                conflict_type='temporal_conflict',
                resource_type='Condition',
                field_name='onsetDateTime',
                existing_value=existing_onset,
                new_value=new_onset,
                severity='medium',
                description=f"Different onset dates: {existing_onset} vs {new_onset}",
                resource_id=resource_id
            ))
        
        # Check for severity conflicts
        new_severity = getattr(new_condition, 'severity', None)
        existing_severity = getattr(existing_condition, 'severity', None)
        
        if new_severity and existing_severity and new_severity != existing_severity:
            conflicts.append(ConflictDetail(
                conflict_type='severity_conflict',
                resource_type='Condition',
                field_name='severity',
                existing_value=existing_severity,
                new_value=new_severity,
                severity='medium',
                description=f"Different severity: {existing_severity} vs {new_severity}",
                resource_id=resource_id
            ))
        
        return conflicts
    
    def _detect_medication_conflicts(
        self,
        new_med: Resource,
        existing_med: Resource
    ) -> List[ConflictDetail]:
        """Detect conflicts specific to MedicationStatement resources."""
        conflicts = []
        resource_id = getattr(new_med, 'id', 'unknown')
        
        # Check for dosage conflicts
        new_dosage = getattr(new_med, 'dosage', None)
        existing_dosage = getattr(existing_med, 'dosage', None)
        
        if new_dosage and existing_dosage and new_dosage != existing_dosage:
            conflicts.append(ConflictDetail(
                conflict_type='dosage_conflict',
                resource_type='MedicationStatement',
                field_name='dosage',
                existing_value=existing_dosage,
                new_value=new_dosage,
                severity='high',  # Dosage conflicts are critical for patient safety
                description=f"Different dosage: {existing_dosage} vs {new_dosage}",
                resource_id=resource_id
            ))
        
        # Check for status conflicts
        new_status = getattr(new_med, 'status', None)
        existing_status = getattr(existing_med, 'status', None)
        
        if new_status and existing_status and new_status != existing_status:
            conflicts.append(ConflictDetail(
                conflict_type='status_conflict',
                resource_type='MedicationStatement',
                field_name='status',
                existing_value=existing_status,
                new_value=new_status,
                severity='medium',
                description=f"Different medication status: {existing_status} vs {new_status}",
                resource_id=resource_id
            ))
        
        # Check for effective period conflicts
        new_period = getattr(new_med, 'effectivePeriod', None)
        existing_period = getattr(existing_med, 'effectivePeriod', None)
        
        if new_period and existing_period and new_period != existing_period:
            conflicts.append(ConflictDetail(
                conflict_type='temporal_conflict',
                resource_type='MedicationStatement',
                field_name='effectivePeriod',
                existing_value=existing_period,
                new_value=new_period,
                severity='medium',
                description=f"Different effective periods: {existing_period} vs {new_period}",
                resource_id=resource_id
            ))
        
        return conflicts
    
    def _detect_patient_conflicts(
        self,
        new_patient: Resource,
        existing_patient: Resource
    ) -> List[ConflictDetail]:
        """Detect conflicts specific to Patient resources."""
        conflicts = []
        resource_id = getattr(new_patient, 'id', 'unknown')
        
        # Check for demographic conflicts
        demographic_fields = ['name', 'birthDate', 'gender', 'identifier']
        
        for field in demographic_fields:
            new_value = getattr(new_patient, field, None)
            existing_value = getattr(existing_patient, field, None)
            
            if new_value and existing_value and new_value != existing_value:
                # Patient demographic conflicts are always critical
                conflicts.append(ConflictDetail(
                    conflict_type='demographic_conflict',
                    resource_type='Patient',
                    field_name=field,
                    existing_value=existing_value,
                    new_value=new_value,
                    severity='critical',
                    description=f"Patient {field} mismatch: {existing_value} vs {new_value}",
                    resource_id=resource_id
                ))
        
        return conflicts
    
    def _detect_generic_conflicts(
        self,
        new_resource: Resource,
        existing_resource: Resource,
        resource_type: str
    ) -> List[ConflictDetail]:
        """Generic conflict detection for unknown resource types."""
        conflicts = []
        resource_id = getattr(new_resource, 'id', 'unknown')
        
        # Basic comparison of common FHIR fields
        common_fields = ['status', 'effectiveDateTime', 'identifier']
        
        for field in common_fields:
            new_value = getattr(new_resource, field, None)
            existing_value = getattr(existing_resource, field, None)
            
            if new_value and existing_value and new_value != existing_value:
                conflicts.append(ConflictDetail(
                    conflict_type='field_mismatch',
                    resource_type=resource_type,
                    field_name=field,
                    existing_value=existing_value,
                    new_value=new_value,
                    severity='medium',
                    description=f"Different {field}: {existing_value} vs {new_value}",
                    resource_id=resource_id
                ))
        
        return conflicts
    
    def _extract_observation_value(self, observation: Resource) -> Any:
        """Extract the value from an Observation resource."""
        # Try different value types
        for value_field in ['valueQuantity', 'valueString', 'valueCodeableConcept', 'valueBoolean']:
            value = getattr(observation, value_field, None)
            if value is not None:
                if hasattr(value, 'value'):
                    return value.value
                return value
        return None
    
    def _extract_observation_unit(self, observation: Resource) -> str:
        """Extract the unit from an Observation resource."""
        value_quantity = getattr(observation, 'valueQuantity', None)
        if value_quantity and hasattr(value_quantity, 'unit'):
            return value_quantity.unit
        return None
    
    def _assess_value_conflict_severity(self, value1: Any, value2: Any) -> str:
        """Assess the severity of a value conflict based on difference magnitude."""
        try:
            # If both are numeric, check percentage difference
            if isinstance(value1, (int, float)) and isinstance(value2, (int, float)):
                if value1 == 0 and value2 == 0:
                    return 'low'
                elif value1 == 0 or value2 == 0:
                    return 'high'
                else:
                    percent_diff = abs(value1 - value2) / max(abs(value1), abs(value2)) * 100
                    if percent_diff > 50:
                        return 'high'
                    elif percent_diff >= 20:
                        return 'medium'
                    else:
                        return 'low'
            else:
                # Non-numeric values - any difference is medium severity
                return 'medium'
        except:
            return 'medium'
    
    def _assess_condition_status_conflict(self, status1: Any, status2: Any) -> str:
        """Assess severity of condition status conflicts."""
        # Convert to strings for comparison
        s1 = str(status1).lower()
        s2 = str(status2).lower()
        
        # Define conflict severity based on status transitions
        critical_conflicts = [
            ('active', 'resolved'),
            ('resolved', 'active'),
            ('active', 'inactive'),
            ('inactive', 'active')
        ]
        
        if (s1, s2) in critical_conflicts or (s2, s1) in critical_conflicts:
            return 'high'
        else:
            return 'medium'
    
    def _calculate_date_difference_hours(self, date1: Any, date2: Any) -> float:
        """Calculate difference between two dates in hours."""
        try:
            # Convert to datetime objects if needed
            if isinstance(date1, str):
                date1 = datetime.fromisoformat(date1.replace('Z', '+00:00'))
            if isinstance(date2, str):
                date2 = datetime.fromisoformat(date2.replace('Z', '+00:00'))
            
            diff = abs((date1 - date2).total_seconds()) / 3600
            return diff
        except:
            return 0.0
    
    def check_for_duplicates(
        self,
        new_resource: Resource,
        existing_resource: Resource,
        resource_type: str
    ) -> bool:
        """
        Check if two resources are duplicates (identical or near-identical).
        
        Args:
            new_resource: The new FHIR resource
            existing_resource: The existing FHIR resource
            resource_type: Type of FHIR resource
            
        Returns:
            True if resources are considered duplicates, False otherwise
        """
        try:
            if resource_type == 'Observation':
                return self._observations_are_duplicates(new_resource, existing_resource)
            elif resource_type == 'Condition':
                return self._conditions_are_duplicates(new_resource, existing_resource)
            elif resource_type == 'MedicationStatement':
                return self._medications_are_duplicates(new_resource, existing_resource)
            else:
                return self._generic_duplicate_check(new_resource, existing_resource)
        except Exception as e:
            self.logger.error(f"Error checking duplicates for {resource_type}: {str(e)}")
            return False
    
    def _observations_are_duplicates(self, obs1: Resource, obs2: Resource) -> bool:
        """Check if two observations are duplicates."""
        # Compare key identifying fields
        return (
            getattr(obs1, 'code', None) == getattr(obs2, 'code', None) and
            self._extract_observation_value(obs1) == self._extract_observation_value(obs2) and
            getattr(obs1, 'effectiveDateTime', None) == getattr(obs2, 'effectiveDateTime', None) and
            self._extract_observation_unit(obs1) == self._extract_observation_unit(obs2)
        )
    
    def _conditions_are_duplicates(self, cond1: Resource, cond2: Resource) -> bool:
        """Check if two conditions are duplicates based on condition code text."""
        # Extract condition code text for comparison
        code1 = None
        code2 = None
        
        # Handle different code representations
        if hasattr(cond1, 'code') and cond1.code:
            if isinstance(cond1.code, dict):
                code1 = cond1.code.get('text')
            elif hasattr(cond1.code, 'text'):
                code1 = cond1.code.text
                
        if hasattr(cond2, 'code') and cond2.code:
            if isinstance(cond2.code, dict):
                code2 = cond2.code.get('text')
            elif hasattr(cond2.code, 'text'):
                code2 = cond2.code.text
        
        # Conditions are duplicates only if they have the same condition code text
        return code1 is not None and code2 is not None and code1 == code2
    
    def _medications_are_duplicates(self, med1: Resource, med2: Resource) -> bool:
        """Check if two medication statements are duplicates."""
        return (
            getattr(med1, 'medicationCodeableConcept', None) == getattr(med2, 'medicationCodeableConcept', None) and
            getattr(med1, 'dosage', None) == getattr(med2, 'dosage', None) and
            getattr(med1, 'effectivePeriod', None) == getattr(med2, 'effectivePeriod', None)
        )
    
    def _generic_duplicate_check(self, resource1: Resource, resource2: Resource) -> bool:
        """Generic duplicate check for unknown resource types."""
        # Simple check based on common fields
        return (
            getattr(resource1, 'identifier', None) == getattr(resource2, 'identifier', None) and
            getattr(resource1, 'status', None) == getattr(resource2, 'status', None)
        )


# Data deduplication classes moved to deduplication.py


# Rest of deduplication classes moved to deduplication.py


class FHIRMergeService:
    """
    Service class for merging extracted document data into patient FHIR records.
    
    Provides comprehensive data validation, FHIR resource conversion, conflict
    detection and resolution, data deduplication, and provenance tracking.
    Uses the existing FHIRAccumulator for basic operations but adds enhanced
    merge-specific functionality.
    """
    
    def __init__(self, patient: Patient, config_profile: Optional[str] = None):
        """
        Initialize the FHIR merge service for a specific patient.
        
        Args:
            patient: Patient model instance to merge data into
            config_profile: Name of configuration profile to use (defaults to system default)
            
        Raises:
            ValueError: If patient is None or invalid
        """
        if not patient:
            raise ValueError("Patient is required")
        
        self.patient = patient
        self.fhir_bundle = patient.cumulative_fhir_json
        self.logger = logger
        self.accumulator = FHIRAccumulator()
        self.conflict_detector = ConflictDetector()
        
        # Load configuration from the configuration service
        from .configuration import MergeConfigurationService
        self.config_profile_name = config_profile
        self.config = MergeConfigurationService.get_configuration_dict(config_profile)
        
        # Initialize deduplicator with configuration
        self.deduplicator = ResourceDeduplicator(self.config)
        
        # Initialize conflict resolver with configuration
        self.conflict_resolver = ConflictResolver(self.config)
        
        # Initialize validation system with configuration
        self.validator = FHIRMergeValidator(
            auto_correct=self.config.get('auto_correct_validation_issues', True)
        )
        
        # Initialize provenance tracker for comprehensive audit trails
        self.provenance_tracker = ProvenanceTracker(self.config)
        
        # Initialize transaction manager for atomic operations and rollback capability
        self.transaction_manager = FHIRTransactionManager(
            auto_snapshot=self.config.get('auto_snapshot', True),
            snapshot_frequency_hours=self.config.get('snapshot_frequency_hours', 24),
            max_staging_time_minutes=self.config.get('max_staging_time_minutes', 30)
        )
        
        # Initialize performance monitoring and optimization
        self.performance_monitor = PerformanceMonitor()
        self.resource_cache = FHIRResourceCache(
            max_size=self.config.get('cache_max_size', 1000),
            ttl_seconds=self.config.get('cache_ttl_seconds', 3600)
        )
        self.batch_optimizer = BatchSizeOptimizer()
        self._current_metrics = None
    
    def set_configuration_profile(self, profile_name: str):
        """
        Switch to a different configuration profile.
        
        Args:
            profile_name: Name of the configuration profile to use
        """
        from .configuration import MergeConfigurationService
        
        # Load new configuration
        new_config = MergeConfigurationService.get_configuration_dict(profile_name)
        
        # Update configuration and re-initialize services that depend on config
        self.config = new_config
        self.config_profile_name = profile_name
        
        # Re-initialize services with new configuration
        self.deduplicator = ResourceDeduplicator(self.config)
        self.conflict_resolver = ConflictResolver(self.config)
        self.provenance_tracker = ProvenanceTracker(self.config)
        self.transaction_manager = FHIRTransactionManager(
            auto_snapshot=self.config.get('auto_snapshot', True),
            snapshot_frequency_hours=self.config.get('snapshot_frequency_hours', 24),
            max_staging_time_minutes=self.config.get('max_staging_time_minutes', 30)
        )
        
        self.logger.info(f"Switched to configuration profile: {profile_name}")
    
    def get_current_configuration_profile(self) -> str:
        """
        Get the name of the currently active configuration profile.
        
        Returns:
            Name of the current configuration profile
        """
        return self.config_profile_name or self.config.get('profile_name', 'default')
    
    def configure_merge_settings(self, **kwargs):
        """
        Update merge configuration settings.
        
        Args:
            **kwargs: Configuration options to update
        """
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
            else:
                self.logger.warning(f"Unknown configuration option: {key}")
    
    def merge_document_data(
        self,
        extracted_data: Dict[str, Any],
        document_metadata: Dict[str, Any],
        user: Optional[User] = None,
        **kwargs
    ) -> MergeResult:
        """
        Main entry point for merging document data into patient's FHIR record.
        
        Args:
            extracted_data: Raw extracted data from document processing
            document_metadata: Metadata about the source document
            user: User performing the merge operation
            **kwargs: Additional configuration options
            
        Returns:
            MergeResult: Comprehensive results of the merge operation
            
        Raises:
            FHIRMergeError: If merge operation fails
        """
        start_time = datetime.now()
        merge_result = MergeResult()
        
        # Initialize performance monitoring
        self._current_metrics = self.performance_monitor.start_monitoring(
            operation_id=f"merge_{self.patient.mrn}_{int(time.time())}"
        )
        
        # Initialize result with operation details
        merge_result.operation_type = "fhir_merge"
        merge_result.patient_mrn = self.patient.mrn
        merge_result.started_at = start_time
        
        # Add document metadata
        if document_metadata:
            document_id = document_metadata.get('document_id')
            if document_id:
                merge_result.document_ids = [document_id]
        
        # Add user context if provided
        if user:
            merge_result.performed_by_user_id = user.id
            merge_result.performed_by_username = user.username
        
        try:
            merge_result.add_message(f"Starting FHIR merge for patient {self.patient.mrn}")
            
            # Update configuration with any provided kwargs
            self._update_config(kwargs)
            
            # Load current bundle
            current_bundle = self._load_current_bundle()
            merge_result.bundle_version_before = current_bundle.meta.versionId if current_bundle.meta else "1"
            
            # Calculate bundle size before merge
            if current_bundle and hasattr(current_bundle, 'entry'):
                merge_result.bundle_size_before = len(current_bundle.entry or [])
            
            # Step 1: Validate extracted data
            self.logger.info(f"Starting FHIR merge for patient {self.patient.mrn}")
            merge_result.add_message("Validating extracted data")
            
            validated_data = self.validate_data(extracted_data)
            
            # Process validation results using enhanced methods
            if validated_data.get('errors'):
                for error in validated_data['errors']:
                    merge_result.add_validation_issue(
                        issue_type="validation_error",
                        message=error if isinstance(error, str) else str(error),
                        severity="error"
                    )
            
            if validated_data.get('warnings'):
                for warning in validated_data['warnings']:
                    merge_result.add_validation_issue(
                        issue_type="validation_warning", 
                        message=warning if isinstance(warning, str) else str(warning),
                        severity="warning"
                    )
            
            if validated_data.get('critical_errors'):
                for error in validated_data['critical_errors']:
                    merge_result.add_merge_error("critical_validation", str(error))
                raise FHIRMergeError(f"Critical validation errors: {validated_data['critical_errors']}")
            
            # Step 2: Convert to FHIR resources
            merge_result.add_message("Converting data to FHIR resources")
            fhir_resources = self.convert_to_fhir(validated_data['data'], document_metadata)
            
            # Step 3: Merge resources with conflict resolution
            merge_result.add_message(f"Merging {len(fhir_resources)} FHIR resources")
            merge_result = self.merge_resources(fhir_resources, document_metadata, user, merge_result)
            
            # Update final bundle information
            final_bundle = self._load_current_bundle()
            merge_result.bundle_version_after = final_bundle.meta.versionId if final_bundle.meta else "1"
            
            if final_bundle and hasattr(final_bundle, 'entry'):
                merge_result.bundle_size_after = len(final_bundle.entry or [])
            
            # Step 4: Validate merge results
            merge_result.add_message("Performing post-merge validation and quality checks")
            validation_report = self._perform_merge_validation(final_bundle)
            merge_result.validation_report = validation_report
            
            # Add validation issues to merge result
            for issue in validation_report.issues:
                if not issue.corrected:
                    merge_result.add_validation_issue(
                        issue_type=f"post_merge_{issue.category.value}",
                        message=issue.message,
                        severity=issue.severity.value,
                        resource_type=issue.resource_type,
                        resource_id=issue.resource_id,
                        field_path=issue.field_path
                    )
            
            # Log validation summary
            validation_summary = validation_report.get_summary()
            merge_result.add_message(
                f"Validation completed: Score {validation_summary['quality_score']}/100, "
                f"{validation_summary['total_issues']} issues, "
                f"{validation_summary['total_corrections']} auto-corrections"
            )
            
            # Check for critical validation issues
            if validation_report.has_critical_issues():
                critical_issues = validation_report.get_issues_by_severity(ValidationSeverity.CRITICAL)
                critical_count = len([i for i in critical_issues if not i.corrected])
                merge_result.add_merge_error(
                    "critical_validation", 
                    f"Found {critical_count} critical validation issues that require attention"
                )
            
            # Calculate processing time and completion
            end_time = datetime.now()
            merge_result.completed_at = end_time
            merge_result.processing_time_seconds = (end_time - start_time).total_seconds()
            merge_result.success = True
            
            # Add success message
            total_resources = merge_result.get_total_resources_processed()
            success_rate = merge_result.get_success_rate()
            merge_result.add_message(
                f"Successfully processed {total_resources} resources with {success_rate:.1f}% success rate"
            )
            
            # Log detailed summary
            self.logger.info(merge_result.get_operation_summary())
            
            # Log detailed summary in debug mode
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"Detailed merge summary:\n{merge_result.get_detailed_summary()}")
            
            # Record performance metrics for successful operation
            if self._current_metrics:
                self._current_metrics.total_resources_processed = total_resources
                self._current_metrics.resources_added = merge_result.resources_added
                self._current_metrics.resources_updated = merge_result.resources_updated
                self._current_metrics.conflicts_detected = merge_result.conflicts_detected
                self._current_metrics.conflicts_resolved = merge_result.conflicts_resolved
                self._current_metrics.validation_errors = len(merge_result.validation_errors)
                self._current_metrics.merge_errors = len(merge_result.merge_errors)
                
                # Add cache metrics if available
                if hasattr(self.resource_cache, '_memory_cache'):
                    cache_size = len(self.resource_cache._memory_cache)
                    # Estimate cache hit ratio based on operation
                    self._current_metrics.cache_hits = cache_size
                    self._current_metrics.cache_misses = max(0, total_resources - cache_size)
                
                self.performance_monitor.record_metrics(self._current_metrics)
                merge_result.performance_metrics = self._current_metrics.to_dict()
            
            return merge_result
            
        except Exception as e:
            end_time = datetime.now()
            merge_result.completed_at = end_time
            merge_result.processing_time_seconds = (end_time - start_time).total_seconds()
            merge_result.success = False
            
            # Add error using enhanced method
            merge_result.add_merge_error("merge_operation_failure", str(e), e)
            
            self.logger.error(f"FHIR merge failed for patient {self.patient.mrn}: {str(e)}", exc_info=True)
            
            # Log failure summary
            self.logger.error(merge_result.get_operation_summary())
            
            # Record performance metrics for failed operation
            if self._current_metrics:
                self._current_metrics.merge_errors += 1
                self.performance_monitor.record_metrics(self._current_metrics)
                merge_result.performance_metrics = self._current_metrics.to_dict()
            
            raise FHIRMergeError(f"Merge operation failed: {str(e)}") from e
    
    def get_cached_resource(self, resource_type: str, resource_id: str, version: str = None) -> Optional[Dict]:
        """
        Get a FHIR resource with caching support.
        
        Args:
            resource_type: Type of FHIR resource
            resource_id: Resource identifier
            version: Optional version identifier
            
        Returns:
            Resource data if found and cached
        """
        # Try cache first
        cached_resource = self.resource_cache.get_resource(resource_type, resource_id, version)
        if cached_resource:
            if self._current_metrics:
                self._current_metrics.cache_hits += 1
            return cached_resource
        
        # Cache miss - would need to fetch from actual source
        if self._current_metrics:
            self._current_metrics.cache_misses += 1
        
        # In a real implementation, this would fetch from the patient's FHIR bundle
        # For now, return None as this is primarily for reference caching
        return None
    
    def cache_resource(self, resource_type: str, resource_id: str, resource_data: Dict, version: str = None):
        """
        Cache a FHIR resource for future access.
        
        Args:
            resource_type: Type of FHIR resource
            resource_id: Resource identifier
            resource_data: Resource data to cache
            version: Optional version identifier
        """
        self.resource_cache.set_resource(resource_type, resource_id, resource_data, version)
    
    def optimize_batch_processing(self, resources: List[Dict]) -> List[List[Dict]]:
        """
        Optimize batch processing by determining optimal chunk sizes.
        
        Args:
            resources: List of FHIR resources to process
            
        Returns:
            List of resource chunks optimized for processing
        """
        if not resources:
            return []
        
        # Use recent performance data for optimization
        recent_performance = None
        if self._current_metrics:
            recent_performance = self._current_metrics
        
        chunks = self.batch_optimizer.chunk_resources(resources, recent_performance)
        
        self.logger.info(
            f"Optimized batch processing: {len(resources)} resources → "
            f"{len(chunks)} chunks (avg size: {len(resources)/len(chunks) if chunks else 0:.1f})"
        )
        
        return chunks
    
    def get_performance_summary(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get performance summary for this merge service.
        
        Args:
            hours: Number of hours to include in summary
            
        Returns:
            Performance summary data
        """
        return self.performance_monitor.get_performance_summary(hours)
    
    def clear_cache(self):
        """Clear all cached resources."""
        self.resource_cache.clear_all()
        self.logger.info("FHIR resource cache cleared")
    
    def merge_document_data_transactional(
        self,
        extracted_data: Dict[str, Any],
        document_metadata: Dict[str, Any],
        user: Optional[User] = None,
        staging_mode: bool = False,
        **kwargs
    ) -> TransactionResult:
        """
        Transactional version of merge_document_data with staging and rollback capability.
        
        This method provides enhanced transaction management including:
        - Automatic snapshot creation before merge
        - Staging area for pending changes 
        - Rollback capability on failure
        - Concurrent access protection
        - Atomic commit operations
        
        Args:
            extracted_data: Raw extracted data from document processing
            document_metadata: Metadata about the source document
            user: User performing the merge operation
            staging_mode: If True, changes are staged but not committed
            **kwargs: Additional configuration options
            
        Returns:
            TransactionResult: Comprehensive results including transaction details
            
        Raises:
            FHIRMergeError: If merge operation fails
            RuntimeError: If transaction management fails
        """
        if not self.config.get('use_transactions', True):
            # Fall back to non-transactional merge
            merge_result = self.merge_document_data(extracted_data, document_metadata, user, **kwargs)
            # Convert to TransactionResult format
            return TransactionResult(
                success=merge_result.success,
                transaction_id=str(uuid4()),
                changes_applied=merge_result.resources_added + merge_result.resources_updated,
                error_message="; ".join(merge_result.merge_errors) if merge_result.merge_errors else None,
                processing_time_seconds=merge_result.processing_time_seconds,
                bundle_version_before=merge_result.bundle_version_before,
                bundle_version_after=getattr(merge_result, 'bundle_version_after', merge_result.bundle_version_before)
            )
        
        operation_id = f"merge_{self.patient.mrn}_{int(time.time())}_{str(uuid4())[:8]}"
        
        def validation_callback(staging_area: StagingArea) -> Dict[str, Any]:
            """Validation callback for transaction commit."""
            try:
                # Validate final bundle integrity
                # This is a simplified validation - in production you might want more comprehensive checks
                changes_summary = staging_area.get_changes_summary()
                if changes_summary['add'] + changes_summary['update'] == 0:
                    return {'valid': False, 'errors': ['No changes to apply']}
                
                # Additional FHIR-specific validations could go here
                return {'valid': True}
                
            except Exception as e:
                return {'valid': False, 'errors': [f"Validation failed: {str(e)}"]}
        
        try:
            # Use transaction context manager for automatic staging and cleanup
            with self.transaction_manager.transaction_context(
                patient=self.patient,
                operation_id=operation_id,
                user=user,
                auto_commit=not staging_mode,
                validation_callback=validation_callback
            ) as staging_area:
                
                # Update configuration with any provided kwargs
                self._update_config(kwargs)
                
                # Step 1: Validate extracted data
                self.logger.info(f"Starting transactional FHIR merge for patient {self.patient.mrn}")
                validated_data = self.validate_data(extracted_data)
                
                if validated_data.get('critical_errors'):
                    raise FHIRMergeError(f"Critical validation errors: {validated_data['critical_errors']}")
                
                # Step 2: Convert to FHIR resources
                fhir_resources = self.convert_to_fhir(validated_data['data'], document_metadata)
                
                # Step 3: Stage the resources for merge
                for resource in fhir_resources:
                    resource_dict = resource.dict() if hasattr(resource, 'dict') else resource
                    
                    # Determine if this is an add or update operation
                    resource_id = resource_dict.get('id')
                    resource_type = resource_dict.get('resourceType')
                    
                    # Check if resource already exists in current bundle
                    existing_resource = self._find_existing_resource(resource_type, resource_id)
                    operation = 'update' if existing_resource else 'add'
                    
                    # Add to staging area
                    staging_area.add_change(
                        operation=operation,
                        resource_data=resource_dict,
                        metadata={
                            'document_id': document_metadata.get('document_id'),
                            'source_system': document_metadata.get('source_system'),
                            'extracted_at': document_metadata.get('extracted_at'),
                            'user_id': user.id if user else None
                        }
                    )
                
                # If in staging mode, return staging details without committing
                if staging_mode:
                    return TransactionResult(
                        success=True,
                        transaction_id=operation_id,
                        staging_id=staging_area.staging_id,
                        changes_applied=len(staging_area.staged_changes),
                        processing_time_seconds=0.0,  # Not yet committed
                        bundle_version_before=self.patient.cumulative_fhir_json.get('meta', {}).get('versionId', '1')
                    )
                
                # If auto_commit is True, the transaction context manager will handle the commit
                # and the result will be available after the context exits
                
        except Exception as e:
            self.logger.error(f"Transactional FHIR merge failed for patient {self.patient.mrn}: {str(e)}", exc_info=True)
            raise FHIRMergeError(f"Transactional merge operation failed: {str(e)}") from e
        
        # If we reach here, the commit was successful
        return TransactionResult(
            success=True,
            transaction_id=operation_id,
            changes_applied=len(fhir_resources),
            processing_time_seconds=0.0,  # Would be set by actual commit operation
            bundle_version_before=self.patient.cumulative_fhir_json.get('meta', {}).get('versionId', '1'),
            bundle_version_after=str(int(self.patient.cumulative_fhir_json.get('meta', {}).get('versionId', '1')) + 1)
        )
    
    def commit_staged_changes(self, staging_id: str, user: User = None) -> TransactionResult:
        """
        Commit changes from a staging area to the patient's FHIR bundle.
        
        Args:
            staging_id: Staging area identifier
            user: User performing the commit
            
        Returns:
            TransactionResult with commit details
        """
        return self.transaction_manager.commit_staging_area(staging_id, user)
    
    def rollback_staged_changes(self, staging_id: str, user: User = None) -> TransactionResult:
        """
        Rollback/discard changes in a staging area.
        
        Args:
            staging_id: Staging area identifier
            user: User performing the rollback
            
        Returns:
            TransactionResult with rollback details
        """
        return self.transaction_manager.rollback_staging_area(staging_id, user)
    
    def create_snapshot(self, reason: str = "manual_backup", user: User = None) -> TransactionSnapshot:
        """
        Create a snapshot of the patient's current FHIR bundle.
        
        Args:
            reason: Reason for creating the snapshot
            user: User creating the snapshot
            
        Returns:
            TransactionSnapshot object
        """
        return self.transaction_manager.snapshot_manager.create_snapshot(
            self.patient, reason, user
        )
    
    def restore_from_snapshot(self, snapshot_id: str, user: User = None) -> bool:
        """
        Restore patient's FHIR bundle from a snapshot.
        
        Args:
            snapshot_id: Snapshot identifier
            user: User performing the restoration
            
        Returns:
            True if restoration successful, False otherwise
        """
        return self.transaction_manager.snapshot_manager.restore_from_snapshot(
            self.patient, snapshot_id, user
        )
    
    def list_snapshots(self) -> List[Dict[str, Any]]:
        """
        List all snapshots for the patient.
        
        Returns:
            List of snapshot metadata
        """
        return self.transaction_manager.snapshot_manager.list_snapshots(self.patient.mrn)
    
    def _find_existing_resource(self, resource_type: str, resource_id: str) -> Optional[Dict[str, Any]]:
        """
        Find an existing resource in the patient's current FHIR bundle.
        
        Args:
            resource_type: Type of resource to find
            resource_id: ID of resource to find
            
        Returns:
            Resource dictionary if found, None otherwise
        """
        if not resource_id:
            return None
            
        bundle = self.patient.cumulative_fhir_json
        for entry in bundle.get('entry', []):
            resource = entry.get('resource', {})
            if (resource.get('resourceType') == resource_type and 
                resource.get('id') == resource_id):
                return resource
        
        return None
    
    def validate_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Comprehensive validation of extracted data before FHIR conversion.
        
        Performs schema validation, data type checking, range validation,
        and data normalization with detailed error tracking.
        
        Args:
            data: Raw extracted data to validate
            
        Returns:
            Dictionary with validation results and cleaned data
        """
        self.logger.info(f"Starting data validation for patient {self.patient.mrn}")
        
        # Initialize validation result
        validation_result = ValidationResult()
        
        # Basic input validation
        if not isinstance(data, dict):
            validation_result.add_error("Data must be a dictionary", is_critical=True)
            return validation_result.to_dict()
        
        if not data:
            validation_result.add_error("Data is empty", is_critical=True)
            return validation_result.to_dict()
        
        try:
            # Step 1: Determine document type for schema validation
            document_type = self._detect_document_type(data)
            self.logger.info(f"Detected document type: {document_type}")
            
            # Step 2: Schema validation
            schema_validator = DocumentSchemaValidator()
            schema_result = schema_validator.validate_schema(data, document_type)
            
            # Merge schema validation results
            validation_result.errors.extend(schema_result.errors)
            validation_result.warnings.extend(schema_result.warnings)
            validation_result.critical_errors.extend(schema_result.critical_errors)
            validation_result.field_errors.update(schema_result.field_errors)
            
            if not schema_result.is_valid:
                validation_result.is_valid = False
            
            # Step 3: Data normalization and cleanup
            normalized_data = self._normalize_data(data, validation_result)
            validation_result.data = normalized_data
            
            # Step 4: Business rule validation
            self._validate_business_rules(normalized_data, validation_result)
            
            # Step 5: Range and constraint validation
            self._validate_ranges_and_constraints(normalized_data, validation_result)
            
            # Step 6: Cross-field validation
            self._validate_cross_field_logic(normalized_data, validation_result)
            
            # Step 7: Medical data quality checks
            self._validate_medical_data_quality(normalized_data, validation_result)
            
            # Add summary information
            validation_result.validation_metadata['document_type'] = document_type
            validation_result.validation_metadata['total_fields_processed'] = len(data)
            validation_result.validation_metadata['total_fields_normalized'] = len(validation_result.normalized_fields)
            
            self.logger.info(
                f"Data validation completed for patient {self.patient.mrn}: "
                f"valid={validation_result.is_valid}, errors={len(validation_result.errors)}, "
                f"warnings={len(validation_result.warnings)}, normalized={len(validation_result.normalized_fields)}"
            )
            
            return validation_result.to_dict()
            
        except Exception as e:
            error_msg = f"Data validation failed: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            validation_result.add_error(error_msg, is_critical=True)
            return validation_result.to_dict()
    
    def _detect_document_type(self, data: Dict[str, Any]) -> str:
        """
        Detect the document type based on data content.
        
        Args:
            data: Raw extracted data
            
        Returns:
            Document type string
        """
        # Check for lab report indicators
        if ('tests' in data and isinstance(data['tests'], list)) or \
           ('lab_results' in data) or \
           ('test_date' in data) or \
           ('collection_date' in data):
            return 'lab_report'
        
        # Check for clinical note indicators
        elif ('chief_complaint' in data) or \
             ('assessment' in data) or \
             ('plan' in data) or \
             ('note_date' in data):
            return 'clinical_note'
        
        # Check for medication list indicators
        elif ('medications' in data and isinstance(data['medications'], list)) or \
             ('medication_list' in data) or \
             ('prescriptions' in data):
            return 'medication_list'
        
        # Check for discharge summary indicators
        elif ('admission_date' in data and 'discharge_date' in data) or \
             ('discharge_summary' in data) or \
             ('discharge_diagnosis' in data):
            return 'discharge_summary'
        
        # Default to generic document
        else:
            return 'generic'
    
    def _normalize_data(self, data: Dict[str, Any], validation_result: ValidationResult) -> Dict[str, Any]:
        """
        Normalize data fields using the DataNormalizer.
        
        Args:
            data: Raw data to normalize
            validation_result: Validation result to track normalization
            
        Returns:
            Normalized data dictionary
        """
        normalized_data = {}
        normalizer = DataNormalizer()
        
        for field, value in data.items():
            original_value = value
            
            # Normalize based on field name patterns
            if field in ['patient_name', 'ordering_provider', 'attending_physician', 'provider']:
                normalized_value = normalizer.normalize_name(value)
                if normalized_value and normalized_value != str(original_value):
                    validation_result.add_normalized_field(field, original_value, normalized_value)
                normalized_data[field] = normalized_value or value
            
            elif 'date' in field.lower() or field in ['test_date', 'note_date', 'list_date', 'admission_date', 'discharge_date']:
                normalized_value = normalizer.normalize_date(value)
                if normalized_value and normalized_value != str(original_value):
                    validation_result.add_normalized_field(field, original_value, normalized_value)
                normalized_data[field] = normalized_value or value
            
            elif 'code' in field.lower() or field in ['diagnosis_codes', 'procedure_codes']:
                if isinstance(value, list):
                    normalized_codes = []
                    for code in value:
                        normalized_code = normalizer.normalize_medical_code(code)
                        if normalized_code:
                            normalized_codes.append(normalized_code)
                    normalized_data[field] = normalized_codes
                else:
                    normalized_code = normalizer.normalize_medical_code(value)
                    if normalized_code and normalized_code != value:
                        validation_result.add_normalized_field(field, original_value, normalized_code)
                    normalized_data[field] = normalized_code or value
            
            elif 'value' in field.lower() or field in ['test_value', 'result_value', 'measurement']:
                normalized_value = normalizer.normalize_numeric_value(value)
                if normalized_value is not None and normalized_value != value:
                    validation_result.add_normalized_field(field, original_value, normalized_value)
                normalized_data[field] = normalized_value if normalized_value is not None else value
            
            else:
                # No specific normalization, keep original value
                normalized_data[field] = value
        
        return normalized_data
    
    def _validate_business_rules(self, data: Dict[str, Any], validation_result: ValidationResult):
        """
        Validate business rules specific to medical data.
        
        Args:
            data: Normalized data to validate
            validation_result: Validation result to update
        """
        # Validate patient name consistency with current patient
        if 'patient_name' in data and data['patient_name']:
            normalized_input_name = DataNormalizer.normalize_name(data['patient_name'])
            
            # Check against patient's current name if available
            if hasattr(self.patient, 'first_name') and hasattr(self.patient, 'last_name'):
                current_patient_name = f"{self.patient.first_name} {self.patient.last_name}"
                normalized_current_name = DataNormalizer.normalize_name(current_patient_name)
                
                if normalized_input_name and normalized_current_name:
                    # Simple name matching - could be enhanced with fuzzy matching
                    if normalized_input_name.lower() != normalized_current_name.lower():
                        validation_result.add_warning(
                            f"Patient name in document ('{normalized_input_name}') differs from "
                            f"patient record ('{normalized_current_name}')",
                            'patient_name'
                        )
        
        # Validate date logic
        if 'admission_date' in data and 'discharge_date' in data:
            admission_date = DataNormalizer.normalize_date(data['admission_date'])
            discharge_date = DataNormalizer.normalize_date(data['discharge_date'])
            
            if admission_date and discharge_date:
                try:
                    admission_dt = datetime.fromisoformat(admission_date)
                    discharge_dt = datetime.fromisoformat(discharge_date)
                    
                    if discharge_dt < admission_dt:
                        validation_result.add_error(
                            "Discharge date cannot be before admission date",
                            'discharge_date'
                        )
                except ValueError:
                    validation_result.add_warning(
                        "Could not validate date sequence due to date format issues"
                    )
        
        # Validate test results have values
        if 'tests' in data and isinstance(data['tests'], list):
            for i, test in enumerate(data['tests']):
                if isinstance(test, dict):
                    if 'name' not in test or not test['name']:
                        validation_result.add_error(
                            f"Test {i+1} is missing a name",
                            f'tests[{i}].name'
                        )
                    
                    if 'value' not in test or test['value'] is None:
                        validation_result.add_warning(
                            f"Test '{test.get('name', 'unknown')}' is missing a value",
                            f'tests[{i}].value'
                        )
        
        # Validate medications have required information
        if 'medications' in data and isinstance(data['medications'], list):
            for i, medication in enumerate(data['medications']):
                if isinstance(medication, dict):
                    if 'name' not in medication or not medication['name']:
                        validation_result.add_error(
                            f"Medication {i+1} is missing a name",
                            f'medications[{i}].name'
                        )
    
    def _validate_ranges_and_constraints(self, data: Dict[str, Any], validation_result: ValidationResult):
        """
        Validate numeric ranges and other constraints.
        
        Args:
            data: Normalized data to validate
            validation_result: Validation result to update
        """
        current_date = datetime.now().date()
        
        # Validate date ranges
        for field, value in data.items():
            if 'date' in field.lower() and value:
                try:
                    if isinstance(value, str):
                        date_value = datetime.fromisoformat(value).date()
                    elif isinstance(value, (date, datetime)):
                        date_value = value.date() if isinstance(value, datetime) else value
                    else:
                        continue
                    
                    # Check for unreasonable dates
                    if date_value.year < 1900:
                        validation_result.add_error(
                            f"Date '{field}' is too far in the past (before 1900)",
                            field
                        )
                    elif date_value > current_date:
                        validation_result.add_warning(
                            f"Date '{field}' is in the future",
                            field
                        )
                        
                except (ValueError, TypeError) as e:
                    validation_result.add_error(
                        f"Invalid date format for field '{field}': {str(e)}",
                        field
                    )
        
        # Validate test results ranges
        if 'tests' in data and isinstance(data['tests'], list):
            for i, test in enumerate(data['tests']):
                if isinstance(test, dict) and 'value' in test:
                    value = test['value']
                    test_name = test.get('name', 'unknown').lower()
                    
                    # Basic range validation for common tests
                    if 'glucose' in test_name and isinstance(value, (int, float)):
                        if value < 0 or value > 1000:
                            validation_result.add_warning(
                                f"Glucose value {value} seems out of normal range (0-1000)",
                                f'tests[{i}].value'
                            )
                    elif 'blood pressure' in test_name:
                        # Basic BP validation
                        if isinstance(value, str) and '/' in value:
                            try:
                                systolic, diastolic = map(int, value.split('/'))
                                if systolic < 50 or systolic > 300:
                                    validation_result.add_warning(
                                        f"Systolic BP {systolic} seems out of range",
                                        f'tests[{i}].value'
                                    )
                                if diastolic < 30 or diastolic > 200:
                                    validation_result.add_warning(
                                        f"Diastolic BP {diastolic} seems out of range",
                                        f'tests[{i}].value'
                                    )
                            except ValueError:
                                validation_result.add_warning(
                                    f"Blood pressure format appears invalid: {value}",
                                    f'tests[{i}].value'
                                )
    
    def _validate_cross_field_logic(self, data: Dict[str, Any], validation_result: ValidationResult):
        """
        Validate logical relationships between fields.
        
        Args:
            data: Normalized data to validate
            validation_result: Validation result to update
        """
        # Validate collection date vs test date
        if 'collection_date' in data and 'test_date' in data:
            collection_date = DataNormalizer.normalize_date(data['collection_date'])
            test_date = DataNormalizer.normalize_date(data['test_date'])
            
            if collection_date and test_date:
                try:
                    collection_dt = datetime.fromisoformat(collection_date)
                    test_dt = datetime.fromisoformat(test_date)
                    
                    # Check for unusual date sequences
                    days_diff = (test_dt - collection_dt).days
                    if days_diff > 7:
                        validation_result.add_warning(
                            "Test date is more than 7 days after collection date"
                        )
                    elif days_diff < 0:
                        validation_result.add_warning(
                            "Test date is before collection date - this may indicate a data entry error"
                        )
                except ValueError:
                    pass  # Date validation will be caught elsewhere
        
        # Validate that tests exist when test_date is provided
        if 'test_date' in data and data['test_date']:
            if 'tests' not in data or not data['tests']:
                validation_result.add_warning(
                    "Test date provided but no tests found in document"
                )
        
        # Validate that medications exist when medication-related fields are provided
        if any(field in data for field in ['prescribing_provider', 'pharmacy']) and \
           ('medications' not in data or not data['medications']):
            validation_result.add_warning(
                "Medication-related fields provided but no medications found"
            )
    
    def _validate_medical_data_quality(self, data: Dict[str, Any], validation_result: ValidationResult):
        """
        Perform medical data quality checks.
        
        Args:
            data: Normalized data to validate
            validation_result: Validation result to update
        """
        # Check for incomplete test results
        if 'tests' in data and isinstance(data['tests'], list):
            incomplete_tests = 0
            for test in data['tests']:
                if isinstance(test, dict):
                    if not test.get('value') or not test.get('name'):
                        incomplete_tests += 1
            
            if incomplete_tests > 0:
                validation_result.add_warning(
                    f"{incomplete_tests} test(s) have incomplete information"
                )
        
        # Check for medication dosage information
        if 'medications' in data and isinstance(data['medications'], list):
            medications_without_dosage = 0
            for medication in data['medications']:
                if isinstance(medication, dict):
                    if not any(key in medication for key in ['dosage', 'dose', 'strength']):
                        medications_without_dosage += 1
            
            if medications_without_dosage > 0:
                validation_result.add_warning(
                    f"{medications_without_dosage} medication(s) missing dosage information"
                )
        
        # Check for provider information completeness
        provider_fields = ['provider', 'ordering_provider', 'attending_physician', 'prescribing_provider']
        has_provider_info = any(field in data and data[field] for field in provider_fields)
        
        if not has_provider_info:
            validation_result.add_warning(
                "No provider information found in document"
            )
    
    def convert_to_fhir(self, data: Dict[str, Any], metadata: Dict[str, Any]) -> List[Resource]:
        """
        Convert validated extracted data to FHIR resources.
        
        Args:
            data: Validated extracted data
            metadata: Document metadata for context
            
        Returns:
            List of FHIR Resource objects
        """
        self.logger.info(f"Converting data to FHIR resources for patient {self.patient.mrn}")
        
        fhir_resources = []
        
        try:
            # Determine document type from metadata or data
            document_type = metadata.get('document_type') or self._detect_document_type(data)
            
            # Get the appropriate converter for this document type
            converter = self._get_converter(document_type)
            
            # Convert data using the specialized converter
            converted_resources = converter.convert(data, metadata, self.patient)
            fhir_resources.extend(converted_resources)
            
            # Always create a DocumentReference resource for provenance
            doc_ref = self._create_document_reference(metadata)
            if doc_ref:
                fhir_resources.append(doc_ref)
            
            self.logger.info(
                f"Successfully converted data to {len(fhir_resources)} FHIR resources "
                f"for patient {self.patient.mrn} using {document_type} converter"
            )
            
            return fhir_resources
            
        except Exception as e:
            error_msg = f"FHIR conversion failed for patient {self.patient.mrn}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise FHIRMergeError(error_msg) from e
    
    def _get_converter(self, document_type: str) -> 'BaseFHIRConverter':
        """
        Get the appropriate converter for the document type.
        
        Args:
            document_type: Type of document to convert
            
        Returns:
            Converter instance for the document type
        """
        converter_map = {
            'lab_report': LabReportConverter(),
            'clinical_note': ClinicalNoteConverter(),
            'medication_list': MedicationListConverter(),
            'discharge_summary': DischargeSummaryConverter(),
            'generic': GenericConverter()
        }
        
        return converter_map.get(document_type, GenericConverter())
    
    def _create_document_reference(self, metadata: Dict[str, Any]) -> Optional[DocumentReferenceResource]:
        """
        Create a DocumentReference resource for tracking the source document.
        
        Args:
            metadata: Document metadata
            
        Returns:
            DocumentReferenceResource or None if creation fails
        """
        try:
            document_title = metadata.get('document_title', 'Medical Document')
            document_type = metadata.get('document_type', 'generic')
            document_url = metadata.get('document_url', '')
            document_id = metadata.get('document_id')
            creation_date = metadata.get('creation_date')
            
            # Skip DocumentReference creation if no valid URL provided
            if not document_url or not document_url.strip():
                self.logger.info("Skipping DocumentReference creation - no document URL provided")
                return None
            
            # Parse creation date if it's a string
            if isinstance(creation_date, str):
                try:
                    creation_date = datetime.fromisoformat(creation_date.replace('Z', '+00:00'))
                except ValueError:
                    creation_date = None
            
            return DocumentReferenceResource.create_from_document(
                patient_id=str(self.patient.id),
                document_title=document_title,
                document_type=document_type,
                document_url=document_url,
                document_id=document_id,
                creation_date=creation_date
            )
            
        except Exception as e:
            self.logger.warning(f"Failed to create DocumentReference: {str(e)}")
            return None
    
    def merge_resources(
        self,
        new_resources: List[Resource],
        metadata: Dict[str, Any],
        user: Optional[User],
        merge_result: MergeResult
    ) -> MergeResult:
        """
        Merge new FHIR resources into existing patient bundle with comprehensive processing.
        
        This method implements the core algorithm for merging FHIR resources, including:
        - Resource type detection and routing to specialized handlers
        - Basic conflict detection for duplicate resources  
        - Proper integration with existing patient FHIR bundle
        - Detailed tracking of merge operations and results
        
        Args:
            new_resources: List of new FHIR resources to merge
            metadata: Document metadata including source information
            user: User performing the operation (for audit trails)
            merge_result: Current merge result to update and return
            
        Returns:
            Updated MergeResult with comprehensive merge statistics
            
        Raises:
            FHIRMergeError: If critical merge operation fails
        """
        if not new_resources:
            self.logger.warning("No resources provided for merge - nothing to do")
            return merge_result
            
        self.logger.info(f"Starting resource merge for {len(new_resources)} resources")
        
        try:
            with transaction.atomic():
                # Load current patient bundle for comparison and merging
                current_bundle = self._load_current_bundle()
                merge_context = {
                    'current_bundle': current_bundle,
                    'document_metadata': metadata,
                    'user': user,
                    'merge_timestamp': timezone.now(),
                    'conflict_resolver': self.conflict_resolver,  # Pass conflict resolver to handlers
                    'provenance_tracker': self.provenance_tracker  # Pass provenance tracker for conflict resolution
                }
                
                # Create provenance for the overall merge operation if enabled
                merge_provenance = None
                if self.config.get('create_provenance', True):
                    merge_provenance = self.provenance_tracker.create_merge_provenance(
                        target_resources=new_resources,
                        metadata=metadata,
                        user=user,
                        activity_type="merge",
                        reason=f"Merging {len(new_resources)} resources from document"
                    )
                
                # Initialize merge handler factory
                merge_handler_factory = ImportedResourceMergeHandlerFactory()
                
                # Process each new resource
                for resource in new_resources:
                    try:
                        # Detect resource type and get appropriate handler
                        resource_type = self._detect_resource_type(resource)
                        merge_handler = merge_handler_factory.get_handler(resource_type)
                        
                        self.logger.debug(f"Processing {resource_type} resource with {merge_handler.__class__.__name__}")
                        
                        # Perform merge operation for this resource
                        resource_merge_result = merge_handler.merge_resource(
                            new_resource=resource,
                            current_bundle=current_bundle,
                            context=merge_context,
                            config=self.config
                        )
                        
                        # Update overall merge result with resource-specific results
                        self._update_merge_result_from_resource_result(merge_result, resource_merge_result)
                        
                        # Track conflict details from resource merge
                        if 'conflict_details' in resource_merge_result:
                            for conflict_dict in resource_merge_result['conflict_details']:
                                conflict_detail = ConflictDetail(
                                    conflict_type=conflict_dict['conflict_type'],
                                    resource_type=conflict_dict['resource_type'],
                                    field_name=conflict_dict['field_name'],
                                    existing_value=conflict_dict['existing_value'],
                                    new_value=conflict_dict['new_value'],
                                    severity=conflict_dict['severity'],
                                    description=conflict_dict['description'],
                                    resource_id=conflict_dict.get('resource_id')
                                )
                                merge_result.conflict_result.add_conflict(conflict_detail)
                        
                    except Exception as e:
                        error_msg = f"Failed to merge {resource_type if 'resource_type' in locals() else 'unknown'} resource: {str(e)}"
                        self.logger.error(error_msg, exc_info=True)
                        merge_result.merge_errors.append(error_msg)
                        merge_result.resources_skipped += 1
                        
                        # Continue processing other resources unless it's a critical error
                        if isinstance(e, FHIRMergeError) and "critical" in str(e).lower():
                            raise
                
                # Step 4: Deduplicate resources if configured
                if self.config.get('deduplicate_resources', True):
                    dedup_result = self._perform_deduplication(current_bundle, merge_result)
                    merge_result.deduplication_result = dedup_result
                    
                    # Create provenance for deduplicated resources if enabled
                    if self.config.get('create_provenance', True) and dedup_result.duplicates_found:
                        self._create_deduplication_provenance(dedup_result, user)
                
                # Add all provenance resources to the bundle before saving
                if self.config.get('create_provenance', True) and self.provenance_tracker:
                    provenance_resources = self.provenance_tracker.get_provenance_list()
                    for provenance in provenance_resources:
                        self._add_provenance_to_bundle(current_bundle, provenance)
                    
                    self.logger.info(f"Added {len(provenance_resources)} provenance resources to bundle")
                
                # Save the updated bundle back to patient record
                self._save_updated_bundle(current_bundle, metadata, user)
                
                # Update final bundle version
                updated_bundle = self._load_current_bundle()
                merge_result.bundle_version_after = updated_bundle.meta.versionId if updated_bundle.meta else "1"
                
                self.logger.info(
                    f"Resource merge completed: {merge_result.resources_added} added, "
                    f"{merge_result.resources_updated} updated, {merge_result.resources_skipped} skipped"
                )
                
        except Exception as e:
            error_msg = f"Resource merge operation failed: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            merge_result.merge_errors.append(error_msg)
            raise FHIRMergeError(error_msg) from e
        
        return merge_result
    
    def _detect_resource_type(self, resource: Resource) -> str:
        """
        Detect the FHIR resource type from a resource object.
        
        Args:
            resource: FHIR resource to analyze
            
        Returns:
            String representing the resource type (e.g., 'Patient', 'Observation')
            
        Raises:
            ValueError: If resource type cannot be determined
        """
        if hasattr(resource, 'resource_type'):
            return resource.resource_type
        elif hasattr(resource, '__class__'):
            # Extract type from class name (e.g., 'PatientResource' -> 'Patient')
            class_name = resource.__class__.__name__
            if class_name.endswith('Resource'):
                return class_name[:-8]  # Remove 'Resource' suffix
            return class_name
        else:
            raise ValueError(f"Cannot determine resource type for: {type(resource)}")
    
    def _update_merge_result_from_resource_result(
        self,
        merge_result: MergeResult,
        resource_result: Dict[str, Any]
    ):
        """
        Update the overall merge result with results from processing a single resource.
        
        Args:
            merge_result: Overall merge result to update
            resource_result: Results from processing a single resource
        """
        # Update counters based on what happened to this resource
        if resource_result.get('action') == 'added':
            merge_result.resources_added += 1
        elif resource_result.get('action') == 'updated':
            merge_result.resources_updated += 1
        elif resource_result.get('action') == 'skipped':
            merge_result.resources_skipped += 1
        
        # Track conflicts if any were detected/resolved
        if resource_result.get('conflicts_detected', 0) > 0:
            merge_result.conflicts_detected += resource_result['conflicts_detected']
        if resource_result.get('conflicts_resolved', 0) > 0:
            merge_result.conflicts_resolved += resource_result['conflicts_resolved']
        
        # Track deduplication
        if resource_result.get('duplicates_removed', 0) > 0:
            merge_result.duplicates_removed += resource_result['duplicates_removed']
        
        # Add any errors or warnings from this resource
        merge_result.merge_errors.extend(resource_result.get('errors', []))
        merge_result.validation_warnings.extend(resource_result.get('warnings', []))
    
    def _save_updated_bundle(
        self,
        current_bundle: Bundle,
        metadata: Dict[str, Any],
        user: Optional[User]
    ) -> None:
        """
        Save the updated FHIR bundle to the patient record with proper metadata handling.
        
        This method properly handles FHIR Bundle meta objects and saves the updated
        bundle to the patient's cumulative FHIR record with appropriate metadata.
        
        Args:
            current_bundle: The updated FHIR Bundle to save
            metadata: Processing metadata including document ID and source
            user: User performing the operation (for audit tracking)
            
        Raises:
            FHIRMergeError: If saving fails for any reason
        """
        try:
            # Update bundle metadata properly using FHIR object methods
            if not current_bundle.meta:
                from fhir.resources.meta import Meta
                current_bundle.meta = Meta()
            
            # Set lastUpdated on the meta object properly
            current_bundle.meta.lastUpdated = timezone.now().isoformat()
            
            # Convert bundle to dict for storage in patient record
            # Use Django's JSON encoder to handle datetime objects properly
            bundle_dict = current_bundle.dict()
            
            # Convert any datetime objects to ISO strings for JSON serialization
            bundle_json_str = json.dumps(bundle_dict, cls=DjangoJSONEncoder)
            bundle_dict = json.loads(bundle_json_str)
            
            # Update patient's cumulative FHIR record
            if self.patient:
                self.patient.cumulative_fhir_json = serialize_fhir_data(bundle_dict)
                self.patient.save()
                
                # Log the bundle update for audit trail
                self.logger.info(
                    f"Updated cumulative FHIR bundle for patient {self.patient.mrn} "
                    f"with {len(bundle_dict.get('entry', []))} entries"
                )
                
        except Exception as e:
            error_msg = f"Failed to save updated bundle: {str(e)}"
            self.logger.error(error_msg)
            raise FHIRMergeError(error_msg) from e
    
    def _load_current_bundle(self) -> Bundle:
        """
        Load the patient's current FHIR bundle.
        
        Returns:
            Bundle: Current FHIR bundle for the patient
        """
        return self.accumulator._load_patient_bundle(self.patient)
    
    def _perform_merge_validation(self, fhir_bundle: Bundle) -> ValidationReport:
        """
        Perform comprehensive validation of the merged FHIR bundle.
        
        Args:
            fhir_bundle: FHIR bundle to validate
            
        Returns:
            ValidationReport: Comprehensive validation report
        """
        try:
            # Convert Bundle to dictionary format for validation
            if hasattr(fhir_bundle, 'dict'):
                bundle_dict = fhir_bundle.dict()
            else:
                # Handle our custom bundle format
                bundle_dict = self.patient.cumulative_fhir_json
            
            # Perform validation using the validator
            validation_report = self.validator.validate_merge_result(bundle_dict)
            
            # Log validation results
            if validation_report.has_critical_issues():
                self.logger.warning(
                    f"Critical validation issues found in FHIR bundle for patient {self.patient.mrn}"
                )
            
            self.logger.debug(
                f"Validation completed for patient {self.patient.mrn}: "
                f"Score {validation_report.overall_score}/100"
            )
            
            return validation_report
            
        except Exception as e:
            self.logger.error(f"Error during merge validation: {e}")
            # Return a minimal report with the error
            report = ValidationReport()
            report.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                category=ValidationCategory.STRUCTURE,
                message=f"Validation process failed: {str(e)}"
            ))
            report.finalize()
            return report
    
    def _update_config(self, kwargs: Dict[str, Any]):
        """
        Update merge configuration with provided options.
        
        Args:
            kwargs: Configuration options to update
        """
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
            else:
                self.logger.warning(f"Unknown configuration option: {key}")
    
    def _perform_deduplication(
        self,
        current_bundle: Bundle,
        merge_result: MergeResult
    ) -> DeduplicationResult:
        """
        Perform deduplication on the current FHIR bundle.
        
        This method extracts resources from the bundle, runs them through the
        deduplication system, and updates the bundle with the deduplicated resources.
        
        Args:
            current_bundle: FHIR Bundle to deduplicate
            merge_result: Current merge result to update with deduplication stats
            
        Returns:
            DeduplicationResult with detailed information about the operation
        """
        self.logger.info("Starting deduplication of FHIR bundle")
        
        try:
            # Extract resources from bundle (excluding Patient resource)
            bundle_resources = []
            patient_entry = None
            
            if current_bundle.entry:
                for entry in current_bundle.entry:
                    if entry.resource:
                        if entry.resource.resource_type == 'Patient':
                            patient_entry = entry
                        else:
                            bundle_resources.append(entry.resource)
            
            if not bundle_resources:
                self.logger.info("No non-Patient resources found for deduplication")
                return DeduplicationResult()  # Return empty result
            
            # Perform deduplication on the extracted resources
            dedup_result = self.deduplicator.deduplicate_resources(
                resources=bundle_resources,
                preserve_provenance=self.config.get('create_provenance', True)
            )
            
            # Update the bundle with deduplicated resources
            new_entries = []
            
            # Add patient entry back first
            if patient_entry:
                new_entries.append(patient_entry)
            
            # Add deduplicated resources back to bundle
            merged_resources = self._merge_duplicates(
                original_resources=bundle_resources,
                dedup_result=dedup_result,
                preserve_provenance=self.config.get('create_provenance', True)
            )
            
            for resource in merged_resources:
                entry = BundleEntry()
                entry.resource = resource
                new_entries.append(entry)
            
            # Update bundle with new entries
            current_bundle.entry = new_entries
            
            # Update merge result statistics
            merge_result.duplicates_removed = dedup_result.resources_removed
            
            self.logger.info(
                f"Deduplication completed: {len(dedup_result.duplicates_found)} duplicates found, "
                f"{dedup_result.resources_removed} resources removed"
            )
            
            return dedup_result
            
        except Exception as e:
            error_msg = f"Deduplication failed: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            
            # Create error result
            error_result = DeduplicationResult()
            error_result.success = False
            error_result.merge_errors.append(error_msg)
            
            # Don't fail the entire merge for deduplication errors
            merge_result.merge_errors.append(f"Deduplication warning: {error_msg}")
            
            return error_result
    
    def _merge_duplicates(
        self,
        original_resources: List[Resource],
        dedup_result: DeduplicationResult,
        preserve_provenance: bool
    ) -> List[Resource]:
        """
        Merge duplicate resources using the deduplicator's logic.
        
        This is a helper method that delegates to the ResourceDeduplicator's
        merge functionality.
        
        Args:
            original_resources: Original list of resources
            dedup_result: Deduplication result containing duplicate information
            preserve_provenance: Whether to preserve source information
            
        Returns:
            List of merged resources with duplicates removed
        """
        return self.deduplicator._merge_duplicates(
            original_resources, dedup_result, preserve_provenance
        )
    
    def _add_provenance_to_bundle(self, bundle: Bundle, provenance: ProvenanceResource):
        """
        Add a provenance resource to the FHIR bundle.
        
        Args:
            bundle: The FHIR bundle to add provenance to
            provenance: The provenance resource to add
        """
        try:
            from fhir.resources.bundle import BundleEntry
            
            # Create a bundle entry for the provenance resource
            provenance_entry = BundleEntry(
                fullUrl=f"Provenance/{provenance.id}",
                resource=provenance
            )
            
            # Add to bundle entries
            if not hasattr(bundle, 'entry') or bundle.entry is None:
                bundle.entry = []
            
            bundle.entry.append(provenance_entry)
            
            self.logger.debug(f"Added provenance resource {provenance.id} to bundle")
            
        except Exception as e:
            self.logger.error(f"Failed to add provenance {provenance.id} to bundle: {str(e)}")
            # Don't raise here - provenance failure shouldn't stop the merge
    
    def _create_deduplication_provenance(self, dedup_result: 'DeduplicationResult', user: Optional[User]):
        """
        Create comprehensive provenance for deduplication operations.
        
        Args:
            dedup_result: Results from deduplication process
            user: User performing the operation
        """
        try:
            # Group duplicates by primary resource to create provenance for each merged group
            duplicate_groups = {}
            
            for duplicate in dedup_result.duplicates_found:
                primary_id = duplicate.resource_id
                if primary_id not in duplicate_groups:
                    duplicate_groups[primary_id] = []
                duplicate_groups[primary_id].append(duplicate)
            
            # Create provenance for each primary resource that had duplicates merged
            for primary_id, duplicates in duplicate_groups.items():
                try:
                    # Create a mock resource for provenance (we need the resource to create provenance)
                    # In a real scenario, we'd get the actual merged resource from the bundle
                    mock_resource = type('MockResource', (), {
                        'resource_type': duplicates[0].resource_type,
                        'id': primary_id
                    })()
                    
                    # Create deduplication provenance using our tracker
                    provenance = self.provenance_tracker.create_deduplication_provenance(
                        merged_resource=mock_resource,
                        duplicate_details=duplicates,
                        user=user
                    )
                    
                    self.logger.info(
                        f"Created deduplication provenance {provenance.id} for {len(duplicates)} duplicates"
                    )
                    
                except Exception as e:
                    self.logger.error(f"Failed to create provenance for duplicate group {primary_id}: {str(e)}")
                    continue
                    
        except Exception as e:
            self.logger.error(f"Failed to create deduplication provenance: {str(e)}")
            # Don't raise here - provenance failure shouldn't stop the merge

    def merge_document_batch(
        self,
        documents: List,  # List[Document] - forward reference
        extracted_data_list: List[Dict[str, Any]],
        metadata_list: List[Dict[str, Any]],
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        use_transactions: bool = True,
        enable_relationship_detection: bool = True,
        max_concurrent: Optional[int] = None,
        user: Optional[User] = None
    ):
        """
        Merge data from multiple related documents in an optimized batch operation.
        
        This method extends the single-document merge capability to handle batches
        of related documents efficiently, with relationship detection, transaction
        management, and progress tracking.
        
        Args:
            documents: List of Document model instances
            extracted_data_list: List of extracted data dictionaries (one per document)
            metadata_list: List of metadata dictionaries (one per document)
            progress_callback: Optional callback for progress updates (processed, total, message)
            use_transactions: Whether to use transaction management for atomicity
            enable_relationship_detection: Whether to detect document relationships
            max_concurrent: Maximum concurrent document processing (overrides default)
            user: User performing the batch merge operation
            
        Returns:
            BatchMergeResult with comprehensive processing results
            
        Raises:
            ValueError: If input lists have mismatched lengths
            FHIRMergeError: If batch processing fails critically
        """
        # Import here to avoid circular imports
        from .batch_processing import FHIRBatchProcessor
        
        # Create batch processor with same configuration
        batch_processor = FHIRBatchProcessor(self.patient, self.config_profile_name)
        
        # Delegate to the dedicated batch processor
        return batch_processor.merge_document_batch(
            documents=documents,
            extracted_data_list=extracted_data_list,
            metadata_list=metadata_list,
            progress_callback=progress_callback,
            use_transactions=use_transactions,
            enable_relationship_detection=enable_relationship_detection,
            max_concurrent=max_concurrent
        )

    def get_batch_processing_capabilities(self) -> Dict[str, Any]:
        """
        Get information about batch processing capabilities and configuration.
        
        Returns:
            Dictionary with batch processing capabilities and current settings
        """
        from django.conf import settings
        
        return {
            'supports_batch_processing': True,
            'max_concurrent_documents': getattr(settings, 'FHIR_BATCH_MAX_CONCURRENT', 3),
            'memory_limit_mb': getattr(settings, 'FHIR_BATCH_MEMORY_LIMIT_MB', 512),
            'chunk_size': getattr(settings, 'FHIR_BATCH_CHUNK_SIZE', 10),
            'supports_relationship_detection': True,
            'supports_transaction_management': True,
            'supports_progress_tracking': True,
            'current_configuration_profile': self.get_current_configuration_profile(),
            'transaction_manager_available': hasattr(self, 'transaction_manager')
        }


# =============================================================================
# FHIR RESOURCE CONVERTERS
# =============================================================================

class BaseFHIRConverter:
    """
    Base class for converting document data to FHIR resources.
    
    Provides common functionality and defines the interface that all
    specialized converters must implement.
    """
    
    def __init__(self):
        """Initialize the base converter."""
        self.logger = logger
    
    def convert(self, data: Dict[str, Any], metadata: Dict[str, Any], patient) -> List[Resource]:
        """
        Convert document data to FHIR resources.
        
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
        """
        Create a Practitioner resource from provider name.
        
        Args:
            provider_name: Name of the provider
            
        Returns:
            PractitionerResource or None if creation fails
        """
        if not provider_name or not provider_name.strip():
            return None
        
        try:
            # Parse name - simple approach, could be enhanced
            name_parts = provider_name.strip().split()
            if len(name_parts) >= 2:
                first_name = name_parts[0]
                last_name = ' '.join(name_parts[1:])
            else:
                first_name = provider_name
                last_name = "Unknown"
            
            return PractitionerResource.create_from_provider(
                first_name=first_name,
                last_name=last_name
            )
        except Exception as e:
            self.logger.warning(f"Failed to create Practitioner resource: {str(e)}")
            return None
    
    def _normalize_date_for_fhir(self, date_value: Any) -> Optional[datetime]:
        """
        Normalize date value for FHIR usage.
        
        Args:
            date_value: Date in various formats
            
        Returns:
            datetime object or None if invalid
        """
        if not date_value:
            return None
        
        # Use the existing normalizer
        normalized_date_str = DataNormalizer.normalize_date(date_value)
        if normalized_date_str:
            try:
                return datetime.fromisoformat(normalized_date_str)
            except ValueError:
                pass
        
        return None


class GenericConverter(BaseFHIRConverter):
    """
    Generic converter for basic document types that don't have specialized logic.
    
    Handles extraction of common elements like patient demographics and
    basic clinical information that can be found in any document type.
    """
    
    def convert(self, data: Dict[str, Any], metadata: Dict[str, Any], patient) -> List[Resource]:
        """
        Convert generic document data to FHIR resources.
        
        Args:
            data: Validated extracted data
            metadata: Document metadata
            patient: Patient model instance
            
        Returns:
            List of FHIR Resource objects
        """
        resources = []
        patient_id = self._get_patient_id(patient)
        
        try:
            # Create provider resource if provider information is available
            provider_fields = ['provider', 'ordering_provider', 'attending_physician']
            for field in provider_fields:
                if field in data and data[field]:
                    provider = self._create_provider_resource(data[field])
                    if provider:
                        resources.append(provider)
                        break  # Only add one provider to avoid duplicates
            
            # Extract any diagnosis codes that might be present
            if 'diagnosis_codes' in data and isinstance(data['diagnosis_codes'], list):
                for diagnosis in data['diagnosis_codes']:
                    condition = self._create_condition_from_code(diagnosis, patient_id, data)
                    if condition:
                        resources.append(condition)
            
            self.logger.info(f"Generic converter created {len(resources)} resources")
            return resources
            
        except Exception as e:
            self.logger.error(f"Generic conversion failed: {str(e)}", exc_info=True)
            return []
    
    def _create_condition_from_code(self, diagnosis_code: Any, patient_id: str, data: Dict[str, Any]) -> Optional[ConditionResource]:
        """
        Create a Condition resource from a diagnosis code.
        
        Args:
            diagnosis_code: Diagnosis code (string or dict)
            patient_id: FHIR patient ID
            data: Document data for context
            
        Returns:
            ConditionResource or None if creation fails
        """
        try:
            if isinstance(diagnosis_code, dict):
                code = diagnosis_code.get('code', '')
                display = diagnosis_code.get('display', diagnosis_code.get('description', ''))
            else:
                code = str(diagnosis_code)
                display = f"Diagnosis code {code}"
            
            if not code:
                return None
            
            # Get document date for onset if available
            onset_date = None
            date_fields = ['document_date', 'note_date', 'admission_date']
            for field in date_fields:
                if field in data and data[field]:
                    onset_date = self._normalize_date_for_fhir(data[field])
                    break
            
            return ConditionResource.create_from_diagnosis(
                patient_id=patient_id,
                condition_code=code,
                condition_display=display,
                onset_date=onset_date
            )
            
        except Exception as e:
            self.logger.warning(f"Failed to create Condition from code: {str(e)}")
            return None


class LabReportConverter(BaseFHIRConverter):
    """
    Specialized converter for laboratory reports.
    
    Converts lab test results into FHIR Observation resources with proper
    test codes, values, units, and reference ranges.
    """
    
    def convert(self, data: Dict[str, Any], metadata: Dict[str, Any], patient) -> List[Resource]:
        """
        Convert lab report data to FHIR resources.
        
        Args:
            data: Validated lab report data
            metadata: Document metadata
            patient: Patient model instance
            
        Returns:
            List of FHIR Resource objects
        """
        resources = []
        patient_id = self._get_patient_id(patient)
        
        try:
            # Get test date
            test_date = self._normalize_date_for_fhir(data.get('test_date')) or datetime.utcnow()
            
            # Create provider resource if available
            if 'ordering_provider' in data and data['ordering_provider']:
                provider = self._create_provider_resource(data['ordering_provider'])
                if provider:
                    resources.append(provider)
            
            # Convert test results to Observation resources
            if 'tests' in data and isinstance(data['tests'], list):
                for test in data['tests']:
                    observation = self._create_observation_from_test(test, patient_id, test_date)
                    if observation:
                        resources.append(observation)
            
            self.logger.info(f"Lab report converter created {len(resources)} resources")
            return resources
            
        except Exception as e:
            self.logger.error(f"Lab report conversion failed: {str(e)}", exc_info=True)
            return []
    
    def _create_observation_from_test(self, test: Dict[str, Any], patient_id: str, test_date: datetime) -> Optional[ObservationResource]:
        """
        Create an Observation resource from a single test result.
        
        Args:
            test: Test data dictionary
            patient_id: FHIR patient ID
            test_date: Date of the test
            
        Returns:
            ObservationResource or None if creation fails
        """
        try:
            test_name = test.get('name')
            test_value = test.get('value')
            test_unit = test.get('unit', test.get('units'))
            test_code = test.get('code', test.get('test_code'))
            
            if not test_name:
                self.logger.warning("Test missing name, skipping")
                return None
            
            # Generate a test code if not provided (using a simple hash approach)
            if not test_code:
                # Create a simple code based on test name
                test_code = f"LAB-{hash(test_name.lower()) % 100000:05d}"
            
            return ObservationResource.create_from_lab_result(
                patient_id=patient_id,
                test_code=test_code,
                test_name=test_name,
                value=test_value,
                unit=test_unit if test_unit and test_unit.strip() else None,
                observation_date=test_date
            )
            
        except Exception as e:
            self.logger.warning(f"Failed to create Observation from test: {str(e)}")
            return None


class ClinicalNoteConverter(BaseFHIRConverter):
    """
    Specialized converter for clinical notes and physician documentation.
    
    Extracts diagnoses, assessments, and plans into appropriate FHIR resources.
    """
    
    def convert(self, data: Dict[str, Any], metadata: Dict[str, Any], patient) -> List[Resource]:
        """
        Convert clinical note data to FHIR resources.
        
        Args:
            data: Validated clinical note data
            metadata: Document metadata
            patient: Patient model instance
            
        Returns:
            List of FHIR Resource objects
        """
        resources = []
        patient_id = self._get_patient_id(patient)
        
        try:
            # Get note date
            note_date = self._normalize_date_for_fhir(data.get('note_date')) or datetime.utcnow()
            
            # Create provider resource
            if 'provider' in data and data['provider']:
                provider = self._create_provider_resource(data['provider'])
                if provider:
                    resources.append(provider)
            
            # Convert diagnosis codes to Condition resources
            if 'diagnosis_codes' in data and isinstance(data['diagnosis_codes'], list):
                for diagnosis in data['diagnosis_codes']:
                    condition = self._create_condition_from_diagnosis(diagnosis, patient_id, note_date)
                    if condition:
                        resources.append(condition)
            
            # Create observations for assessment notes
            if 'assessment' in data and data['assessment']:
                assessment_obs = self._create_assessment_observation(data['assessment'], patient_id, note_date)
                if assessment_obs:
                    resources.append(assessment_obs)
            
            # Create observations for plan notes
            if 'plan' in data and data['plan']:
                plan_obs = self._create_plan_observation(data['plan'], patient_id, note_date)
                if plan_obs:
                    resources.append(plan_obs)
            
            self.logger.info(f"Clinical note converter created {len(resources)} resources")
            return resources
            
        except Exception as e:
            self.logger.error(f"Clinical note conversion failed: {str(e)}", exc_info=True)
            return []
    
    def _create_condition_from_diagnosis(self, diagnosis: Any, patient_id: str, note_date: datetime) -> Optional[ConditionResource]:
        """
        Create a Condition resource from diagnosis information.
        
        Args:
            diagnosis: Diagnosis code or description
            patient_id: FHIR patient ID
            note_date: Date of the note
            
        Returns:
            ConditionResource or None if creation fails
        """
        try:
            if isinstance(diagnosis, dict):
                code = diagnosis.get('code', '')
                display = diagnosis.get('display', diagnosis.get('description', ''))
            else:
                code = str(diagnosis)
                display = f"Clinical diagnosis: {code}"
            
            if not code:
                return None
            
            return ConditionResource.create_from_diagnosis(
                patient_id=patient_id,
                condition_code=code,
                condition_display=display,
                onset_date=note_date
            )
            
        except Exception as e:
            self.logger.warning(f"Failed to create Condition from diagnosis: {str(e)}")
            return None
    
    def _create_assessment_observation(self, assessment: str, patient_id: str, note_date: datetime) -> Optional[ObservationResource]:
        """
        Create an Observation resource for clinical assessment.
        
        Args:
            assessment: Assessment text
            patient_id: FHIR patient ID
            note_date: Date of the note
            
        Returns:
            ObservationResource or None if creation fails
        """
        try:
            return ObservationResource.create_from_lab_result(
                patient_id=patient_id,
                test_code="ASSESS",
                test_name="Clinical Assessment",
                value=assessment,
                observation_date=note_date
            )
        except Exception as e:
            self.logger.warning(f"Failed to create assessment observation: {str(e)}")
            return None
    
    def _create_plan_observation(self, plan: str, patient_id: str, note_date: datetime) -> Optional[ObservationResource]:
        """
        Create an Observation resource for treatment plan.
        
        Args:
            plan: Plan text
            patient_id: FHIR patient ID
            note_date: Date of the note
            
        Returns:
            ObservationResource or None if creation fails
        """
        try:
            return ObservationResource.create_from_lab_result(
                patient_id=patient_id,
                test_code="PLAN",
                test_name="Treatment Plan",
                value=plan,
                observation_date=note_date
            )
        except Exception as e:
            self.logger.warning(f"Failed to create plan observation: {str(e)}")
            return None


class MedicationListConverter(BaseFHIRConverter):
    """
    Specialized converter for medication lists and prescription information.
    
    Converts medication data into FHIR MedicationStatement resources with
    proper dosage, frequency, and status information.
    """
    
    def convert(self, data: Dict[str, Any], metadata: Dict[str, Any], patient) -> List[Resource]:
        """
        Convert medication list data to FHIR resources.
        
        Args:
            data: Validated medication list data
            metadata: Document metadata
            patient: Patient model instance
            
        Returns:
            List of FHIR Resource objects
        """
        resources = []
        patient_id = self._get_patient_id(patient)
        
        try:
            # Get list date
            list_date = self._normalize_date_for_fhir(data.get('list_date')) or datetime.utcnow()
            
            # Create provider resource if available
            if 'prescribing_provider' in data and data['prescribing_provider']:
                provider = self._create_provider_resource(data['prescribing_provider'])
                if provider:
                    resources.append(provider)
            
            # Convert medications to MedicationStatement resources
            if 'medications' in data and isinstance(data['medications'], list):
                for medication in data['medications']:
                    med_statement = self._create_medication_statement(medication, patient_id, list_date)
                    if med_statement:
                        resources.append(med_statement)
            
            self.logger.info(f"Medication list converter created {len(resources)} resources")
            return resources
            
        except Exception as e:
            self.logger.error(f"Medication list conversion failed: {str(e)}", exc_info=True)
            return []
    
    def _create_medication_statement(self, medication: Dict[str, Any], patient_id: str, list_date: datetime) -> Optional[MedicationStatementResource]:
        """
        Create a MedicationStatement resource from medication information.
        
        Args:
            medication: Medication data dictionary
            patient_id: FHIR patient ID
            list_date: Date of the medication list
            
        Returns:
            MedicationStatementResource or None if creation fails
        """
        try:
            med_name = medication.get('name')
            med_code = medication.get('code', medication.get('ndc'))
            dosage = medication.get('dosage', medication.get('dose'))
            frequency = medication.get('frequency')
            status = medication.get('status', 'active')
            
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
                effective_date=list_date
            )
            
        except Exception as e:
            self.logger.warning(f"Failed to create MedicationStatement: {str(e)}")
            return None


class DischargeSummaryConverter(BaseFHIRConverter):
    """
    Specialized converter for discharge summaries and hospital documentation.
    
    Extracts diagnoses, procedures, medications, and encounter information
    into appropriate FHIR resources.
    """
    
    def convert(self, data: Dict[str, Any], metadata: Dict[str, Any], patient) -> List[Resource]:
        """
        Convert discharge summary data to FHIR resources.
        
        Args:
            data: Validated discharge summary data
            metadata: Document metadata
            patient: Patient model instance
            
        Returns:
            List of FHIR Resource objects
        """
        resources = []
        patient_id = self._get_patient_id(patient)
        
        try:
            # Get discharge date
            discharge_date = self._normalize_date_for_fhir(data.get('discharge_date')) or datetime.utcnow()
            admission_date = self._normalize_date_for_fhir(data.get('admission_date'))
            
            # Create provider resource
            if 'attending_physician' in data and data['attending_physician']:
                provider = self._create_provider_resource(data['attending_physician'])
                if provider:
                    resources.append(provider)
            
            # Convert discharge diagnoses to Condition resources
            if 'diagnosis' in data and isinstance(data['diagnosis'], list):
                for diagnosis in data['diagnosis']:
                    condition = self._create_discharge_condition(diagnosis, patient_id, discharge_date)
                    if condition:
                        resources.append(condition)
            
            # Convert procedures to Observation resources (simplified approach)
            if 'procedures' in data and isinstance(data['procedures'], list):
                for procedure in data['procedures']:
                    proc_obs = self._create_procedure_observation(procedure, patient_id, admission_date or discharge_date)
                    if proc_obs:
                        resources.append(proc_obs)
            
            # Convert discharge medications using medication converter logic
            if 'medications' in data and isinstance(data['medications'], list):
                med_converter = MedicationListConverter()
                for medication in data['medications']:
                    med_statement = med_converter._create_medication_statement(medication, patient_id, discharge_date)
                    if med_statement:
                        resources.append(med_statement)
            
            self.logger.info(f"Discharge summary converter created {len(resources)} resources")
            return resources
            
        except Exception as e:
            self.logger.error(f"Discharge summary conversion failed: {str(e)}", exc_info=True)
            return []
    
    def _create_discharge_condition(self, diagnosis: Any, patient_id: str, discharge_date: datetime) -> Optional[ConditionResource]:
        """
        Create a Condition resource from discharge diagnosis.
        
        Args:
            diagnosis: Diagnosis information
            patient_id: FHIR patient ID
            discharge_date: Date of discharge
            
        Returns:
            ConditionResource or None if creation fails
        """
        try:
            if isinstance(diagnosis, dict):
                code = diagnosis.get('code', '')
                display = diagnosis.get('display', diagnosis.get('description', ''))
                status = diagnosis.get('status', 'active')
            else:
                code = str(diagnosis)
                display = f"Discharge diagnosis: {code}"
                status = 'active'
            
            if not code:
                return None
            
            return ConditionResource.create_from_diagnosis(
                patient_id=patient_id,
                condition_code=code,
                condition_display=display,
                clinical_status=status,
                onset_date=discharge_date
            )
            
        except Exception as e:
            self.logger.warning(f"Failed to create discharge condition: {str(e)}")
            return None
    
    def _create_procedure_observation(self, procedure: Any, patient_id: str, procedure_date: datetime) -> Optional[ObservationResource]:
        """
        Create an Observation resource for a procedure (simplified approach).
        
        Args:
            procedure: Procedure information
            patient_id: FHIR patient ID
            procedure_date: Date of procedure
            
        Returns:
            ObservationResource or None if creation fails
        """
        try:
            if isinstance(procedure, dict):
                proc_name = procedure.get('name', procedure.get('description', ''))
                proc_code = procedure.get('code', '')
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
                observation_date=procedure_date
            )
            
        except Exception as e:
            self.logger.warning(f"Failed to create procedure observation: {str(e)}")
            return None 


# =============================================================================
# CONFLICT RESOLUTION STRATEGIES
# =============================================================================

class ConflictResolutionStrategy:
    """
    Base class for conflict resolution strategies.
    
    Each strategy defines how to resolve conflicts between new and existing
    FHIR resources based on different criteria and business rules.
    """
    
    def __init__(self, name: str):
        self.name = name
        self.logger = logger
    
    def resolve_conflict(
        self,
        conflict_detail: ConflictDetail,
        new_resource: Resource,
        existing_resource: Resource,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Resolve a specific conflict between two resources.
        
        Args:
            conflict_detail: Details about the conflict
            new_resource: The new FHIR resource
            existing_resource: The existing FHIR resource
            context: Additional context for resolution
            
        Returns:
            Dictionary containing resolution result with action and resolved_value
        """
        raise NotImplementedError("Subclasses must implement resolve_conflict")
    
    def _extract_timestamp(self, resource: Resource) -> Optional[datetime]:
        """
        Extract timestamp from a FHIR resource for comparison.
        
        Args:
            resource: FHIR resource to extract timestamp from
            
        Returns:
            Timestamp if found, None otherwise
        """
        # Try different timestamp fields based on resource type
        timestamp_fields = [
            'effectiveDateTime', 'recordedDate', 'assertedDate', 
            'onsetDateTime', 'date', 'meta.lastUpdated'
        ]
        
        for field in timestamp_fields:
            try:
                if '.' in field:
                    # Handle nested attributes like meta.lastUpdated
                    obj = resource
                    for part in field.split('.'):
                        obj = getattr(obj, part, None)
                        if obj is None:
                            break
                    if obj:
                        return obj if isinstance(obj, datetime) else datetime.fromisoformat(str(obj).replace('Z', '+00:00'))
                else:
                    value = getattr(resource, field, None)
                    if value:
                        return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            except (AttributeError, ValueError, TypeError):
                continue
        
        return None


class NewestWinsStrategy(ConflictResolutionStrategy):
    """
    Resolution strategy that prefers the newest data based on timestamps.
    
    This strategy compares timestamps and keeps the resource with the most
    recent timestamp. If timestamps are equal or missing, it defaults to
    keeping the new resource.
    """
    
    def __init__(self):
        super().__init__("newest_wins")
    
    def resolve_conflict(
        self,
        conflict_detail: ConflictDetail,
        new_resource: Resource,
        existing_resource: Resource,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Resolve conflict by keeping the newest resource based on timestamp.
        """
        self.logger.debug(f"Applying newest_wins strategy for {conflict_detail.conflict_type}")
        
        new_timestamp = self._extract_timestamp(new_resource)
        existing_timestamp = self._extract_timestamp(existing_resource)
        
        resolution_result = {
            'strategy': self.name,
            'action': 'keep_new',  # Default action
            'resolved_value': conflict_detail.new_value,
            'reasoning': 'Default to new resource',
            'timestamp_comparison': {
                'new_timestamp': new_timestamp.isoformat() if new_timestamp else None,
                'existing_timestamp': existing_timestamp.isoformat() if existing_timestamp else None
            }
        }
        
        # Compare timestamps if both exist
        if new_timestamp and existing_timestamp:
            if existing_timestamp > new_timestamp:
                resolution_result.update({
                    'action': 'keep_existing',
                    'resolved_value': conflict_detail.existing_value,
                    'reasoning': f'Existing resource is newer ({existing_timestamp} > {new_timestamp})'
                })
            else:
                resolution_result['reasoning'] = f'New resource is newer or equal ({new_timestamp} >= {existing_timestamp})'
        elif existing_timestamp and not new_timestamp:
            resolution_result.update({
                'action': 'keep_existing', 
                'resolved_value': conflict_detail.existing_value,
                'reasoning': 'Only existing resource has timestamp'
            })
        elif new_timestamp and not existing_timestamp:
            resolution_result['reasoning'] = 'Only new resource has timestamp'
        
        # Update conflict detail with resolution
        conflict_detail.resolution_strategy = self.name
        conflict_detail.resolution_result = resolution_result
        
        return resolution_result


class PreserveBothStrategy(ConflictResolutionStrategy):
    """
    Resolution strategy that preserves both conflicting values.
    
    This strategy keeps both the existing and new resources, treating them
    as different entries in a temporal sequence or alternative viewpoints.
    """
    
    def __init__(self):
        super().__init__("preserve_both")
    
    def resolve_conflict(
        self,
        conflict_detail: ConflictDetail,
        new_resource: Resource,
        existing_resource: Resource,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Resolve conflict by preserving both resources.
        """
        self.logger.debug(f"Applying preserve_both strategy for {conflict_detail.conflict_type}")
        
        resolution_result = {
            'strategy': self.name,
            'action': 'preserve_both',
            'resolved_value': {
                'existing': conflict_detail.existing_value,
                'new': conflict_detail.new_value,
                'preservation_method': 'temporal_sequence'
            },
            'reasoning': 'Both values preserved as temporal sequence',
            'metadata': {
                'conflict_preserved': True,
                'requires_clinical_review': conflict_detail.severity in ['high', 'critical']
            }
        }
        
        # Add special handling for critical conflicts
        if conflict_detail.severity == 'critical':
            resolution_result['metadata'].update({
                'flagged_for_review': True,
                'review_priority': 'high',
                'clinical_significance': 'potential_safety_issue'
            })
        
        # Update conflict detail with resolution
        conflict_detail.resolution_strategy = self.name
        conflict_detail.resolution_result = resolution_result
        
        return resolution_result


class ConfidenceBasedStrategy(ConflictResolutionStrategy):
    """
    Resolution strategy based on confidence scores of the data sources.
    
    This strategy evaluates confidence scores and selects the value from
    the source with higher confidence. Falls back to newest_wins if
    confidence scores are equal or missing.
    """
    
    def __init__(self):
        super().__init__("confidence_based")
    
    def resolve_conflict(
        self,
        conflict_detail: ConflictDetail,
        new_resource: Resource,
        existing_resource: Resource,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Resolve conflict based on confidence scores.
        """
        self.logger.debug(f"Applying confidence_based strategy for {conflict_detail.conflict_type}")
        
        # Extract confidence scores from resource metadata
        new_confidence = self._extract_confidence_score(new_resource, context)
        existing_confidence = self._extract_confidence_score(existing_resource, context)
        
        resolution_result = {
            'strategy': self.name,
            'action': 'keep_new',  # Default action
            'resolved_value': conflict_detail.new_value,
            'reasoning': 'Default to new resource',
            'confidence_comparison': {
                'new_confidence': new_confidence,
                'existing_confidence': existing_confidence
            }
        }
        
        # Compare confidence scores
        if new_confidence is not None and existing_confidence is not None:
            if existing_confidence > new_confidence:
                resolution_result.update({
                    'action': 'keep_existing',
                    'resolved_value': conflict_detail.existing_value,
                    'reasoning': f'Existing resource has higher confidence ({existing_confidence} > {new_confidence})'
                })
            elif new_confidence > existing_confidence:
                resolution_result['reasoning'] = f'New resource has higher confidence ({new_confidence} > {existing_confidence})'
            else:
                # Equal confidence - fall back to newest_wins
                fallback_strategy = NewestWinsStrategy()
                fallback_result = fallback_strategy.resolve_conflict(
                    conflict_detail, new_resource, existing_resource, context
                )
                resolution_result.update(fallback_result)
                resolution_result['strategy'] = f"{self.name}_fallback_newest_wins"
                resolution_result['reasoning'] = f"Equal confidence ({new_confidence}), fell back to newest_wins"
        else:
            # Missing confidence scores - fall back to newest_wins
            fallback_strategy = NewestWinsStrategy()
            fallback_result = fallback_strategy.resolve_conflict(
                conflict_detail, new_resource, existing_resource, context
            )
            resolution_result.update(fallback_result)
            resolution_result['strategy'] = f"{self.name}_fallback_newest_wins"
            resolution_result['reasoning'] = "Missing confidence scores, fell back to newest_wins"
        
        # Update conflict detail with resolution
        conflict_detail.resolution_strategy = self.name
        conflict_detail.resolution_result = resolution_result
        
        return resolution_result
    
    def _extract_confidence_score(self, resource: Resource, context: Dict[str, Any]) -> Optional[float]:
        """
        Extract confidence score from resource or context.
        
        Args:
            resource: FHIR resource to extract confidence from
            context: Additional context that might contain confidence information
            
        Returns:
            Confidence score as float between 0.0 and 1.0, or None if not found
        """
        # Check resource meta for confidence
        if hasattr(resource, 'meta') and resource.meta:
            for tag in getattr(resource.meta, 'tag', []):
                if tag.system == 'http://terminology.hl7.org/CodeSystem/confidence' and tag.code:
                    try:
                        return float(tag.code)
                    except ValueError:
                        pass
        
        # Check context for document-level confidence
        document_metadata = context.get('document_metadata', {})
        ai_confidence = document_metadata.get('ai_confidence_score')
        if ai_confidence is not None:
            try:
                return float(ai_confidence)
            except (ValueError, TypeError):
                pass
        
        # Check for extraction confidence in context
        extraction_confidence = context.get('extraction_confidence')
        if extraction_confidence is not None:
            try:
                return float(extraction_confidence)
            except (ValueError, TypeError):
                pass
        
        return None


class ManualReviewStrategy(ConflictResolutionStrategy):
    """
    Resolution strategy that flags conflicts for manual review.
    
    This strategy doesn't automatically resolve conflicts but marks them
    for human review, preserving both values and adding review metadata.
    """
    
    def __init__(self):
        super().__init__("manual_review")
    
    def resolve_conflict(
        self,
        conflict_detail: ConflictDetail,
        new_resource: Resource,
        existing_resource: Resource,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Flag conflict for manual review without automatic resolution.
        """
        self.logger.debug(f"Flagging {conflict_detail.conflict_type} for manual review")
        
        resolution_result = {
            'strategy': self.name,
            'action': 'flag_for_review',
            'resolved_value': None,  # No automatic resolution
            'reasoning': 'Conflict requires manual review',
            'review_metadata': {
                'flagged_at': timezone.now().isoformat(),
                'conflict_severity': conflict_detail.severity,
                'requires_clinical_review': True,
                'review_priority': self._determine_review_priority(conflict_detail),
                'both_values_preserved': True,
                'existing_value': conflict_detail.existing_value,
                'new_value': conflict_detail.new_value
            }
        }
        
        # Add additional context for reviewers
        if conflict_detail.severity == 'critical':
            resolution_result['review_metadata'].update({
                'urgent_review': True,
                'potential_safety_issue': True,
                'escalation_required': True
            })
        
        # Update conflict detail with resolution
        conflict_detail.resolution_strategy = self.name
        conflict_detail.resolution_result = resolution_result
        
        return resolution_result
    
    def _determine_review_priority(self, conflict_detail: ConflictDetail) -> str:
        """
        Determine review priority based on conflict characteristics.
        
        Args:
            conflict_detail: The conflict to assess
            
        Returns:
            Priority level: 'low', 'medium', 'high', 'urgent'
        """
        # First check severity for critical/urgent cases
        if conflict_detail.severity == 'critical':
            return 'urgent'
        elif conflict_detail.severity == 'high':
            return 'high'
        
        # Then check for special conflict types that always get medium priority
        if conflict_detail.conflict_type in ['value_mismatch', 'dosage_conflict']:
            return 'medium'
        
        # Finally fall back to severity mapping for non-special types
        severity_map = {
            'medium': 'low',  # Medium severity maps to low priority by default
            'low': 'low'
        }
        return severity_map.get(conflict_detail.severity, 'low')


class ConflictResolver:
    """
    Main conflict resolver that applies appropriate resolution strategies.
    
    This class coordinates the resolution of conflicts using different strategies
    based on configuration and conflict characteristics.
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize the conflict resolver with configuration.
        
        Args:
            config: Configuration dictionary with resolution preferences
        """
        self.config = config or {}
        self.logger = logger
        
        # Initialize available strategies
        self.strategies = {
            'newest_wins': NewestWinsStrategy(),
            'preserve_both': PreserveBothStrategy(),
            'confidence_based': ConfidenceBasedStrategy(),
            'manual_review': ManualReviewStrategy()
        }
        
        # Default strategy mappings by conflict type and severity
        self.default_strategy_mappings = {
            'critical': 'manual_review',
            'high': 'preserve_both',
            'medium': 'newest_wins',
            'low': 'newest_wins'
        }
    
    def resolve_conflicts(
        self,
        conflicts: List[ConflictDetail],
        new_resource: Resource,
        existing_resource: Resource,
        context: Dict[str, Any],
        provenance_tracker: Optional['ProvenanceTracker'] = None
    ) -> Dict[str, Any]:
        """
        Resolve a list of conflicts using appropriate strategies.
        
        Args:
            conflicts: List of conflicts to resolve
            new_resource: The new FHIR resource
            existing_resource: The existing FHIR resource
            context: Additional context for resolution
            
        Returns:
            Dictionary containing resolution summary and actions
        """
        if not conflicts:
            return {
                'total_conflicts': 0,
                'resolved_conflicts': 0,
                'unresolved_conflicts': 0,
                'resolution_actions': [],
                'overall_action': 'no_conflicts'
            }
        
        self.logger.info(f"Resolving {len(conflicts)} conflicts using configured strategies")
        
        resolution_summary = {
            'total_conflicts': len(conflicts),
            'resolved_conflicts': 0,
            'unresolved_conflicts': 0,
            'resolution_actions': [],
            'flagged_for_review': [],
            'overall_action': 'resolved'
        }
        
        for conflict in conflicts:
            try:
                # Determine strategy for this conflict
                strategy_name = self._select_strategy_for_conflict(conflict)
                strategy = self.strategies[strategy_name]
                
                # Apply resolution strategy
                resolution_result = strategy.resolve_conflict(
                    conflict, new_resource, existing_resource, context
                )
                
                # Track resolution action
                resolution_summary['resolution_actions'].append({
                    'conflict_type': conflict.conflict_type,
                    'field_name': conflict.field_name,
                    'strategy_used': strategy_name,
                    'action': resolution_result['action'],
                    'reasoning': resolution_result['reasoning']
                })
                
                # Update counters
                if resolution_result['action'] == 'flag_for_review':
                    resolution_summary['flagged_for_review'].append(conflict.to_dict())
                    resolution_summary['unresolved_conflicts'] += 1
                else:
                    resolution_summary['resolved_conflicts'] += 1
                
            except Exception as e:
                self.logger.error(f"Failed to resolve conflict {conflict.conflict_type}: {str(e)}")
                resolution_summary['unresolved_conflicts'] += 1
                resolution_summary['resolution_actions'].append({
                    'conflict_type': conflict.conflict_type,
                    'field_name': conflict.field_name,
                    'strategy_used': 'error',
                    'action': 'failed',
                    'reasoning': f'Resolution failed: {str(e)}'
                })
        
        # Determine overall action based on results
        if resolution_summary['unresolved_conflicts'] > 0:
            if any(c.severity == 'critical' for c in conflicts):
                resolution_summary['overall_action'] = 'critical_conflicts_require_review'
            else:
                resolution_summary['overall_action'] = 'partial_resolution_with_review'
        
        # Create provenance for conflict resolution if provenance tracker provided
        if provenance_tracker and resolution_summary['resolved_conflicts'] > 0:
            try:
                # Create conflict resolution provenance
                resolved_resource = new_resource  # The resource that was modified during resolution
                strategy_used = self.config.get('conflict_resolution_strategy', 'mixed')
                
                # Convert conflicts to dictionaries for provenance
                conflict_dicts = []
                for conflict in conflicts:
                    conflict_dicts.append({
                        'conflict_type': conflict.conflict_type,
                        'field_name': conflict.field_name,
                        'severity': conflict.severity,
                        'resource_type': conflict.resource_type
                    })
                
                conflict_provenance = provenance_tracker.create_conflict_resolution_provenance(
                    resolved_resource=resolved_resource,
                    conflict_details=conflict_dicts,
                    resolution_strategy=strategy_used,
                    user=context.get('user')
                )
                
                self.logger.info(f"Created conflict resolution provenance {conflict_provenance.id}")
                
            except Exception as e:
                self.logger.error(f"Failed to create conflict resolution provenance: {str(e)}")
                # Don't fail the resolution if provenance creation fails
        
        self.logger.info(
            f"Conflict resolution completed: {resolution_summary['resolved_conflicts']} resolved, "
            f"{resolution_summary['unresolved_conflicts']} require review"
        )
        
        return resolution_summary
    
    def _select_strategy_for_conflict(self, conflict: ConflictDetail) -> str:
        """
        Select the appropriate resolution strategy for a specific conflict.
        
        Args:
            conflict: The conflict to select a strategy for
            
        Returns:
            Name of the strategy to use
        """
        # Check for conflict-specific strategy in config
        conflict_type_strategies = self.config.get('conflict_type_strategies', {})
        if conflict.conflict_type in conflict_type_strategies:
            return conflict_type_strategies[conflict.conflict_type]
        
        # Check for resource-type-specific strategy
        resource_type_strategies = self.config.get('resource_type_strategies', {})
        if conflict.resource_type in resource_type_strategies:
            return resource_type_strategies[conflict.resource_type]
        
        # Use severity-based default
        severity_strategies = self.config.get('severity_strategies', self.default_strategy_mappings)
        if conflict.severity in severity_strategies:
            return severity_strategies[conflict.severity]
        
        # Fall back to global default
        default_strategy = self.config.get('conflict_resolution_strategy', 'newest_wins')
        return default_strategy if default_strategy in self.strategies else 'newest_wins'


# =============================================================================
# Data Deduplication System
# =============================================================================

 
    """
    Represents information about a detected duplicate resource.
    """
    
    def __init__(
        self,
        resource_type: str,
        resource_id: str,
        duplicate_id: str,
        similarity_score: float,
        duplicate_type: str,
        matching_fields: List[str],
        source_metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize duplicate resource detail.
        
        Args:
            resource_type: Type of FHIR resource (e.g., 'Observation')
            resource_id: ID of the original resource
            duplicate_id: ID of the duplicate resource
            similarity_score: Score from 0.0 to 1.0 indicating similarity
            duplicate_type: Type of duplicate ('exact', 'near', 'fuzzy')
            matching_fields: List of fields that matched between resources
            source_metadata: Additional metadata about the sources
        """
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.duplicate_id = duplicate_id
        self.similarity_score = similarity_score
        self.duplicate_type = duplicate_type
        self.matching_fields = matching_fields
        self.source_metadata = source_metadata or {}
        self.merge_action = None  # Will be set during processing
        self.merge_result = None  # Will be set after merging


 
    """
    Tracks the results of a deduplication operation.
    """
    
    def __init__(self):
        """Initialize deduplication result tracking."""
        self.duplicates_found = []
        self.resources_merged = 0
        self.resources_removed = 0
        self.exact_duplicates = 0
        self.near_duplicates = 0
        self.fuzzy_duplicates = 0
        self.merge_errors = []
        self.processing_time_seconds = 0.0
        self.success = False
        self.provenance_created = []
        
    def add_duplicate(self, duplicate_detail: DuplicateResourceDetail):
        """Add a duplicate resource detail to the results."""
        self.duplicates_found.append(duplicate_detail)
        
        # Update counters by duplicate type
        if duplicate_detail.duplicate_type == 'exact':
            self.exact_duplicates += 1
        elif duplicate_detail.duplicate_type == 'near':
            self.near_duplicates += 1
        elif duplicate_detail.duplicate_type == 'fuzzy':
            self.fuzzy_duplicates += 1
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of deduplication results."""
        return {
            'total_duplicates_found': len(self.duplicates_found),
            'exact_duplicates': self.exact_duplicates,
            'near_duplicates': self.near_duplicates,
            'fuzzy_duplicates': self.fuzzy_duplicates,
            'resources_merged': self.resources_merged,
            'resources_removed': self.resources_removed,
            'processing_time_seconds': self.processing_time_seconds,
            'success': self.success,
            'error_count': len(self.merge_errors)
        }


 
    """
    Generates consistent hashes for FHIR resources for exact duplicate detection.
    """
    
    @staticmethod
    def generate_resource_hash(resource: Resource, include_metadata: bool = False) -> str:
        """
        Generate a consistent hash for a FHIR resource.
        
        Args:
            resource: FHIR resource to hash
            include_metadata: Whether to include metadata fields in hash
            
        Returns:
            Hexadecimal hash string
        """
        # Use the existing get_resource_hash function from bundle_utils
        # but enhance it for our specific needs
        try:
            from .bundle_utils import get_resource_hash
            return get_resource_hash(resource)
        except Exception as e:
            logger.error(f"Failed to generate hash for {resource.resource_type}: {str(e)}")
            # Fallback to simple string representation hash
            import hashlib
            resource_str = str(resource.dict())
            return hashlib.md5(resource_str.encode()).hexdigest()


 
    """
    Implements fuzzy matching algorithms for near-duplicate FHIR resources.
    """
    
    def __init__(self, tolerance_hours: int = 24):
        """
        Initialize fuzzy matcher.
        
        Args:
            tolerance_hours: Time tolerance for temporal matching
        """
        self.tolerance_hours = tolerance_hours
        self.logger = logger
    
    def calculate_similarity(self, resource1: Resource, resource2: Resource) -> float:
        """
        Calculate similarity score between two resources of the same type.
        
        Args:
            resource1: First resource to compare
            resource2: Second resource to compare
            
        Returns:
            Similarity score from 0.0 to 1.0
        """
        if resource1.resource_type != resource2.resource_type:
            return 0.0
        
        resource_type = resource1.resource_type
        
        if resource_type == "Observation":
            return self._calculate_observation_similarity(resource1, resource2)
        elif resource_type == "Condition":
            return self._calculate_condition_similarity(resource1, resource2)
        elif resource_type == "MedicationStatement":
            return self._calculate_medication_similarity(resource1, resource2)
        elif resource_type == "Patient":
            return self._calculate_patient_similarity(resource1, resource2)
        else:
            return self._calculate_generic_similarity(resource1, resource2)
    
    def _calculate_observation_similarity(self, obs1: Resource, obs2: Resource) -> float:
        """Calculate similarity for Observation resources."""
        score = 0.0
        factors = 0
        
        # Test code similarity (highest weight)
        if hasattr(obs1, 'code') and hasattr(obs2, 'code'):
            factors += 3
            if obs1.code == obs2.code:
                score += 3.0
            elif self._codes_similar(obs1.code, obs2.code):
                score += 2.0
        
        # Subject similarity (high weight)
        if hasattr(obs1, 'subject') and hasattr(obs2, 'subject'):
            factors += 2
            if obs1.subject == obs2.subject:
                score += 2.0
        
        # Value similarity (medium weight)
        if hasattr(obs1, 'valueQuantity') and hasattr(obs2, 'valueQuantity'):
            factors += 2
            if self._values_similar(obs1.valueQuantity, obs2.valueQuantity):
                score += 2.0
        
        # Temporal similarity (medium weight)
        if hasattr(obs1, 'effectiveDateTime') and hasattr(obs2, 'effectiveDateTime'):
            factors += 1
            if self._dates_within_tolerance(obs1.effectiveDateTime, obs2.effectiveDateTime):
                score += 1.0
        
        return score / factors if factors > 0 else 0.0
    
    def _calculate_condition_similarity(self, cond1: Resource, cond2: Resource) -> float:
        """Calculate similarity for Condition resources."""
        score = 0.0
        factors = 0
        
        # Condition code (highest weight)
        if hasattr(cond1, 'code') and hasattr(cond2, 'code'):
            factors += 3
            if cond1.code == cond2.code:
                score += 3.0
            elif self._codes_similar(cond1.code, cond2.code):
                score += 2.0
        
        # Subject similarity (high weight)
        if hasattr(cond1, 'subject') and hasattr(cond2, 'subject'):
            factors += 2
            if cond1.subject == cond2.subject:
                score += 2.0
        
        # Clinical status (medium weight)
        if hasattr(cond1, 'clinicalStatus') and hasattr(cond2, 'clinicalStatus'):
            factors += 1
            if cond1.clinicalStatus == cond2.clinicalStatus:
                score += 1.0
        
        return score / factors if factors > 0 else 0.0
    
    def _calculate_medication_similarity(self, med1: Resource, med2: Resource) -> float:
        """Calculate similarity for MedicationStatement resources."""
        score = 0.0
        factors = 0
        
        # Medication code (highest weight)
        if hasattr(med1, 'medicationCodeableConcept') and hasattr(med2, 'medicationCodeableConcept'):
            factors += 3
            if med1.medicationCodeableConcept == med2.medicationCodeableConcept:
                score += 3.0
            elif self._codes_similar(med1.medicationCodeableConcept, med2.medicationCodeableConcept):
                score += 2.0
        
        # Subject similarity (high weight)
        if hasattr(med1, 'subject') and hasattr(med2, 'subject'):
            factors += 2
            if med1.subject == med2.subject:
                score += 2.0
        
        # Dosage similarity (medium weight)
        if hasattr(med1, 'dosage') and hasattr(med2, 'dosage'):
            factors += 1
            if self._dosages_similar(med1.dosage, med2.dosage):
                score += 1.0
        
        return score / factors if factors > 0 else 0.0
    
    def _calculate_patient_similarity(self, pat1: Resource, pat2: Resource) -> float:
        """Calculate similarity for Patient resources."""
        score = 0.0
        factors = 0
        
        # Name similarity (high weight)
        if hasattr(pat1, 'name') and hasattr(pat2, 'name'):
            factors += 2
            if self._names_similar(pat1.name, pat2.name):
                score += 2.0
        
        # Birth date (high weight)
        if hasattr(pat1, 'birthDate') and hasattr(pat2, 'birthDate'):
            factors += 2
            if pat1.birthDate == pat2.birthDate:
                score += 2.0
        
        # Identifier similarity (medium weight)
        if hasattr(pat1, 'identifier') and hasattr(pat2, 'identifier'):
            factors += 1
            if self._identifiers_similar(pat1.identifier, pat2.identifier):
                score += 1.0
        
        return score / factors if factors > 0 else 0.0
    
    def _calculate_generic_similarity(self, res1: Resource, res2: Resource) -> float:
        """Calculate basic similarity for unknown resource types."""
        # Convert to dictionaries and compare common fields
        dict1 = res1.dict() if hasattr(res1, 'dict') else {}
        dict2 = res2.dict() if hasattr(res2, 'dict') else {}
        
        common_fields = set(dict1.keys()) & set(dict2.keys())
        matching_fields = 0
        
        for field in common_fields:
            if dict1[field] == dict2[field]:
                matching_fields += 1
        
        return matching_fields / len(common_fields) if common_fields else 0.0
    
    def _codes_similar(self, code1: Any, code2: Any) -> bool:
        """Check if two code objects are similar."""
        # Basic implementation - can be enhanced with terminology services
        if not code1 or not code2:
            return False
            
        # Convert to dictionaries for comparison
        try:
            dict1 = code1.dict() if hasattr(code1, 'dict') else code1
            dict2 = code2.dict() if hasattr(code2, 'dict') else code2
            
            # Check if any coding systems match
            if 'coding' in dict1 and 'coding' in dict2:
                for coding1 in dict1['coding']:
                    for coding2 in dict2['coding']:
                        if coding1.get('system') == coding2.get('system'):
                            return True
            
        except Exception:
            pass
        
        return False
    
    def _values_similar(self, val1: Any, val2: Any, tolerance: float = 0.1) -> bool:
        """Check if two quantity values are similar within tolerance."""
        try:
            if hasattr(val1, 'value') and hasattr(val2, 'value'):
                num1 = float(val1.value)
                num2 = float(val2.value)
                
                # Check if units match
                unit1 = getattr(val1, 'unit', None)
                unit2 = getattr(val2, 'unit', None)
                
                if unit1 != unit2:
                    return False
                
                # Check if values are within tolerance
                if num1 == 0 and num2 == 0:
                    return True
                elif num1 == 0 or num2 == 0:
                    return abs(num1 - num2) <= tolerance
                else:
                    return abs(num1 - num2) / max(abs(num1), abs(num2)) <= tolerance
        except (ValueError, AttributeError):
            pass
        
        return False
    
    def _dates_within_tolerance(self, date1: Any, date2: Any) -> bool:
        """Check if two dates are within the configured tolerance."""
        try:
            if isinstance(date1, str):
                date1 = datetime.fromisoformat(date1.replace('Z', '+00:00'))
            if isinstance(date2, str):
                date2 = datetime.fromisoformat(date2.replace('Z', '+00:00'))
            
            if isinstance(date1, datetime) and isinstance(date2, datetime):
                diff = abs((date1 - date2).total_seconds())
                tolerance_seconds = self.tolerance_hours * 3600
                return diff <= tolerance_seconds
        except Exception:
            pass
        
        return False
    
    def _names_similar(self, names1: List[Any], names2: List[Any]) -> bool:
        """Check if patient names are similar."""
        if not names1 or not names2:
            return False
        
        # Compare first names in each list
        try:
            name1 = names1[0]
            name2 = names2[0]
            
            family1 = getattr(name1, 'family', '')
            family2 = getattr(name2, 'family', '')
            
            given1 = getattr(name1, 'given', [])
            given2 = getattr(name2, 'given', [])
            
            # Family names must match
            if family1.lower() != family2.lower():
                return False
            
            # At least one given name must match
            if given1 and given2:
                given1_lower = [g.lower() for g in given1]
                given2_lower = [g.lower() for g in given2]
                return any(g1 in given2_lower for g1 in given1_lower)
            
        except Exception:
            pass
        
        return False
    
    def _identifiers_similar(self, ids1: List[Any], ids2: List[Any]) -> bool:
        """Check if patient identifiers are similar."""
        if not ids1 or not ids2:
            return False
        
        # Look for matching identifier systems and values
        try:
            for id1 in ids1:
                for id2 in ids2:
                    system1 = getattr(id1, 'system', None)
                    system2 = getattr(id2, 'system', None)
                    value1 = getattr(id1, 'value', None)
                    value2 = getattr(id2, 'value', None)
                    
                    if system1 == system2 and value1 == value2:
                        return True
        except Exception:
            pass
        
        return False
    
    def _dosages_similar(self, dosage1: List[Any], dosage2: List[Any]) -> bool:
        """Check if medication dosages are similar."""
        # Basic implementation - can be enhanced
        if not dosage1 or not dosage2:
            return False
        
        try:
            # Compare first dosage instructions
            d1 = dosage1[0]
            d2 = dosage2[0]
            
            # Compare text instructions if available
            text1 = getattr(d1, 'text', '')
            text2 = getattr(d2, 'text', '')
            
            if text1 and text2:
                return text1.lower() == text2.lower()
        except Exception:
            pass
        
        return False


 
    """
    Main class for identifying and merging duplicate FHIR resources.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the resource deduplicator.
        
        Args:
            config: Configuration options for deduplication behavior
        """
        self.config = config or {}
        self.logger = logger
        self.hash_generator = ResourceHashGenerator()
        self.fuzzy_matcher = FuzzyMatcher(
            tolerance_hours=self.config.get('deduplication_tolerance_hours', 24)
        )
        
        # Similarity thresholds for different duplicate types
        self.exact_threshold = 1.0  # Perfect match
        self.near_threshold = self.config.get('near_duplicate_threshold', 0.9)
        self.fuzzy_threshold = self.config.get('fuzzy_duplicate_threshold', 0.7)
    
    def deduplicate_resources(
        self,
        resources: List[Resource],
        preserve_provenance: bool = True
    ) -> DeduplicationResult:
        """
        Identify and merge duplicate resources in a list.
        
        Args:
            resources: List of FHIR resources to deduplicate
            preserve_provenance: Whether to preserve source information in metadata
            
        Returns:
            DeduplicationResult with details of the operation
        """
        start_time = datetime.now()
        result = DeduplicationResult()
        
        try:
            self.logger.info(f"Starting deduplication of {len(resources)} resources")
            
            # Group resources by type for efficient comparison
            resource_groups = self._group_resources_by_type(resources)
            
            # Process each resource type group
            for resource_type, type_resources in resource_groups.items():
                if len(type_resources) < 2:
                    continue  # No duplicates possible with less than 2 resources
                
                self.logger.debug(f"Checking {len(type_resources)} {resource_type} resources for duplicates")
                
                # Find duplicates within this resource type
                duplicates = self._find_duplicates_in_group(type_resources, resource_type)
                
                # Add to overall results
                for duplicate in duplicates:
                    result.add_duplicate(duplicate)
            
            # Merge the duplicates found
            merged_resources = self._merge_duplicates(resources, result, preserve_provenance)
            
            # Update final statistics
            result.resources_removed = len(resources) - len(merged_resources)
            result.processing_time_seconds = (datetime.now() - start_time).total_seconds()
            result.success = True
            
            self.logger.info(
                f"Deduplication completed: {len(result.duplicates_found)} duplicates found, "
                f"{result.resources_removed} resources removed"
            )
            
            return result
            
        except Exception as e:
            result.processing_time_seconds = (datetime.now() - start_time).total_seconds()
            result.success = False
            result.merge_errors.append(str(e))
            
            self.logger.error(f"Deduplication failed: {str(e)}", exc_info=True)
            raise FHIRMergeError(f"Deduplication operation failed: {str(e)}") from e
    
    def _group_resources_by_type(self, resources: List[Resource]) -> Dict[str, List[Resource]]:
        """Group resources by their FHIR resource type."""
        groups = {}
        
        for resource in resources:
            resource_type = resource.resource_type
            if resource_type not in groups:
                groups[resource_type] = []
            groups[resource_type].append(resource)
        
        return groups
    
    def _find_duplicates_in_group(
        self,
        resources: List[Resource],
        resource_type: str
    ) -> List[DuplicateResourceDetail]:
        """Find duplicate resources within a group of the same type."""
        duplicates = []
        processed_pairs = set()
        
        for i in range(len(resources)):
            for j in range(i + 1, len(resources)):
                resource1 = resources[i]
                resource2 = resources[j]
                
                # Avoid duplicate comparisons
                pair_key = tuple(sorted([id(resource1), id(resource2)]))
                if pair_key in processed_pairs:
                    continue
                processed_pairs.add(pair_key)
                
                # Check for exact duplicates first (hash-based)
                hash1 = self.hash_generator.generate_resource_hash(resource1)
                hash2 = self.hash_generator.generate_resource_hash(resource2)
                
                if hash1 == hash2:
                    # Exact duplicate found
                    duplicate = DuplicateResourceDetail(
                        resource_type=resource_type,
                        resource_id=getattr(resource1, 'id', str(id(resource1))),
                        duplicate_id=getattr(resource2, 'id', str(id(resource2))),
                        similarity_score=1.0,
                        duplicate_type='exact',
                        matching_fields=['*'],  # All fields match for exact duplicates
                        source_metadata={
                            'hash': hash1,
                            'comparison_method': 'hash'
                        }
                    )
                    duplicates.append(duplicate)
                    continue
                
                # Check for fuzzy duplicates using similarity scoring
                similarity_score = self.fuzzy_matcher.calculate_similarity(resource1, resource2)
                
                if similarity_score >= self.near_threshold:
                    duplicate_type = 'near' if similarity_score >= self.near_threshold else 'fuzzy'
                    
                    # Identify matching fields for near/fuzzy duplicates
                    matching_fields = self._identify_matching_fields(resource1, resource2)
                    
                    duplicate = DuplicateResourceDetail(
                        resource_type=resource_type,
                        resource_id=getattr(resource1, 'id', str(id(resource1))),
                        duplicate_id=getattr(resource2, 'id', str(id(resource2))),
                        similarity_score=similarity_score,
                        duplicate_type=duplicate_type,
                        matching_fields=matching_fields,
                        source_metadata={
                            'comparison_method': 'fuzzy_matching',
                            'threshold_used': self.near_threshold if duplicate_type == 'near' else self.fuzzy_threshold
                        }
                    )
                    duplicates.append(duplicate)
                
                elif similarity_score >= self.fuzzy_threshold:
                    # Fuzzy duplicate
                    matching_fields = self._identify_matching_fields(resource1, resource2)
                    
                    duplicate = DuplicateResourceDetail(
                        resource_type=resource_type,
                        resource_id=getattr(resource1, 'id', str(id(resource1))),
                        duplicate_id=getattr(resource2, 'id', str(id(resource2))),
                        similarity_score=similarity_score,
                        duplicate_type='fuzzy',
                        matching_fields=matching_fields,
                        source_metadata={
                            'comparison_method': 'fuzzy_matching',
                            'threshold_used': self.fuzzy_threshold
                        }
                    )
                    duplicates.append(duplicate)
        
        return duplicates
    
    def _identify_matching_fields(self, resource1: Resource, resource2: Resource) -> List[str]:
        """Identify which fields match between two resources."""
        matching_fields = []
        
        try:
            dict1 = resource1.dict() if hasattr(resource1, 'dict') else {}
            dict2 = resource2.dict() if hasattr(resource2, 'dict') else {}
            
            common_fields = set(dict1.keys()) & set(dict2.keys())
            
            for field in common_fields:
                if dict1[field] == dict2[field]:
                    matching_fields.append(field)
        
        except Exception as e:
            self.logger.warning(f"Failed to identify matching fields: {str(e)}")
        
        return matching_fields
    
    def _merge_duplicates(
        self,
        original_resources: List[Resource],
        dedup_result: DeduplicationResult,
        preserve_provenance: bool
    ) -> List[Resource]:
        """
        Merge duplicate resources using the deduplicator's logic.
        
        This is a helper method that delegates to the ResourceDeduplicator's
        merge functionality.
        
        Args:
            original_resources: Original list of resources
            dedup_result: Deduplication result containing duplicate information
            preserve_provenance: Whether to preserve source information
            
        Returns:
            List of merged resources with duplicates removed
        """
        return self.deduplicator._merge_duplicates(
            original_resources, dedup_result, preserve_provenance
        )
    
    def _enhance_resource_with_provenance(
        self,
        primary_resource: Resource,
        duplicates: List[DuplicateResourceDetail],
        preserve_provenance: bool
    ) -> Resource:
        """Enhance a primary resource with provenance information from merged duplicates."""
        if not preserve_provenance:
            return primary_resource
        
        try:
            # Add metadata about merged duplicates
            if not hasattr(primary_resource, 'meta') or not primary_resource.meta:
                from fhir.resources.meta import Meta
                primary_resource.meta = Meta()
            
            # Create provenance extension if it doesn't exist
            if not hasattr(primary_resource.meta, 'extension'):
                primary_resource.meta.extension = []
            
            # Add deduplication provenance
            dedup_extension = Extension(
                url="http://medicaldocparser.com/fhir/extension/deduplication",
                valueString=json.dumps({
                    "merged_duplicates": len(duplicates),
                    "duplicate_types": [d.duplicate_type for d in duplicates],
                    "similarity_scores": [d.similarity_score for d in duplicates],
                    "merge_timestamp": datetime.now().isoformat()
                })
            )
            
            primary_resource.meta.extension.append(dedup_extension)
            
        except Exception as e:
            self.logger.warning(f"Failed to add provenance to merged resource: {str(e)}")
        
        return primary_resource


 


 
    """
    Specialized merge handler for Procedure resources.
    
    Handles temporal sequencing, status tracking, and outcome management
    for medical procedures.
    """
    
    def merge_resource(
        self,
        new_resource: Resource,
        current_bundle: Bundle,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge a Procedure resource with temporal and status awareness.
        """
        self.logger.debug(f"Merging Procedure resource")
        
        # Initialize result tracking
        merge_result = {
            'action': 'unknown',
            'resource_type': 'Procedure',
            'resource_id': getattr(new_resource, 'id', 'unknown'),
            'conflicts_detected': 0,
            'conflicts_resolved': 0,
            'duplicates_removed': 0,
            'errors': [],
            'warnings': [],
            'conflict_details': []
        }
        
        # Look for existing procedure with same code and patient
        existing_resource = self._find_existing_resource(
            new_resource,
            current_bundle,
            ['code', 'subject', 'performedDateTime']
        )
        
        if existing_resource:
            # Check if this is a procedure update vs new instance
            if self._is_procedure_update(new_resource, existing_resource):
                # This is an update to existing procedure (status change, outcome added)
                merged_resource = self._merge_procedure_details(new_resource, existing_resource)
                self._update_resource_in_bundle(merged_resource, current_bundle, existing_resource)
                merge_result['action'] = 'updated'
            else:
                # This is a new instance of same procedure type - add separately
                merge_result = self._add_resource_to_bundle(new_resource, current_bundle, context)
                merge_result['action'] = 'added'
        else:
            # No existing procedure - add new one
            merge_result = self._add_resource_to_bundle(new_resource, current_bundle, context)
            merge_result['action'] = 'added'
        
        return merge_result
    
    def _is_procedure_update(self, new_resource: Resource, existing_resource: Resource) -> bool:
        """
        Determine if new resource is an update to existing procedure vs new instance.
        """
        try:
            # Check if performed dates are close (within 24 hours)
            new_date = getattr(new_resource, 'performedDateTime', None)
            existing_date = getattr(existing_resource, 'performedDateTime', None)
            
            if new_date and existing_date:
                if isinstance(new_date, str):
                    new_date = datetime.fromisoformat(new_date.replace('Z', '+00:00'))
                if isinstance(existing_date, str):
                    existing_date = datetime.fromisoformat(existing_date.replace('Z', '+00:00'))
                
                time_diff = abs((new_date - existing_date).total_seconds())
                if time_diff <= 86400:  # 24 hours
                    return True
            
            # Check if new resource has more complete information (outcome, complications)
            new_outcome = getattr(new_resource, 'outcome', None)
            existing_outcome = getattr(existing_resource, 'outcome', None)
            
            if new_outcome and not existing_outcome:
                return True
            
            return False
            
        except Exception as e:
            self.logger.warning(f"Error determining procedure update: {str(e)}")
            return False
    
    def _merge_procedure_details(self, new_resource: Resource, existing_resource: Resource) -> Resource:
        """
        Merge procedure details preserving all information.
        """
        try:
            # Start with existing resource and update with new information
            merged = copy.deepcopy(existing_resource)
            
            # Update status if new resource has different status
            new_status = getattr(new_resource, 'status', None)
            if new_status:
                merged.status = new_status
            
            # Add outcome if present in new resource
            new_outcome = getattr(new_resource, 'outcome', None)
            if new_outcome:
                merged.outcome = new_outcome
            
            # Add complications if present
            new_complications = getattr(new_resource, 'complication', [])
            existing_complications = getattr(merged, 'complication', [])
            if new_complications:
                merged.complication = existing_complications + new_complications
            
            # Update performer information if more complete
            new_performer = getattr(new_resource, 'performer', [])
            if new_performer and not getattr(merged, 'performer', []):
                merged.performer = new_performer
            
            # Update metadata
            merged.meta = merged.meta or {}
            merged.meta['lastUpdated'] = datetime.utcnow().isoformat() + 'Z'
            
            return merged
            
        except Exception as e:
            self.logger.error(f"Failed to merge procedure details: {str(e)}")
            return new_resource


 
    """
    Specialized merge handler for DiagnosticReport resources.
    
    Handles complex lab reports with multiple observations, result correlation,
    and report status progression.
    """
    
    def merge_resource(
        self,
        new_resource: Resource,
        current_bundle: Bundle,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge a DiagnosticReport resource with observation correlation.
        """
        self.logger.debug(f"Merging DiagnosticReport resource")
        
        # Initialize result tracking
        merge_result = {
            'action': 'unknown',
            'resource_type': 'DiagnosticReport',
            'resource_id': getattr(new_resource, 'id', 'unknown'),
            'conflicts_detected': 0,
            'conflicts_resolved': 0,
            'duplicates_removed': 0,
            'errors': [],
            'warnings': [],
            'conflict_details': []
        }
        
        # Look for existing report with same identifier or effective date/time
        existing_resource = self._find_existing_resource(
            new_resource,
            current_bundle,
            ['identifier', 'subject', 'effectiveDateTime']
        )
        
        if existing_resource:
            # Check if this is a report update (amended, corrected, final)
            if self._is_report_update(new_resource, existing_resource):
                # Update existing report with new information
                merged_resource = self._merge_diagnostic_report_details(new_resource, existing_resource)
                self._update_resource_in_bundle(merged_resource, current_bundle, existing_resource)
                merge_result['action'] = 'updated'
                
                # Update related observations if needed
                self._update_related_observations(merged_resource, current_bundle, context)
            else:
                # This is a new report - add it
                merge_result = self._add_resource_to_bundle(new_resource, current_bundle, context)
                merge_result['action'] = 'added'
        else:
            # No existing report - add new one
            merge_result = self._add_resource_to_bundle(new_resource, current_bundle, context)
            merge_result['action'] = 'added'
        
        return merge_result
    
    def _is_report_update(self, new_resource: Resource, existing_resource: Resource) -> bool:
        """
        Determine if new report is an update to existing report.
        """
        try:
            # Check status progression (preliminary -> final, or final -> amended)
            new_status = getattr(new_resource, 'status', '')
            existing_status = getattr(existing_resource, 'status', '')
            
            status_progression = {
                'registered': 1,
                'partial': 2,
                'preliminary': 3,
                'final': 4,
                'amended': 5,
                'corrected': 6
            }
            
            new_level = status_progression.get(new_status, 0)
            existing_level = status_progression.get(existing_status, 0)
            
            if new_level > existing_level:
                return True
            
            # Check if same identifier
            new_id = getattr(new_resource, 'identifier', [])
            existing_id = getattr(existing_resource, 'identifier', [])
            
            if new_id and existing_id:
                # Simple check for matching identifier values
                new_values = {id_item.get('value') for id_item in new_id if id_item.get('value')}
                existing_values = {id_item.get('value') for id_item in existing_id if id_item.get('value')}
                
                if new_values & existing_values:  # Intersection
                    return True
            
            return False
            
        except Exception as e:
            self.logger.warning(f"Error determining report update: {str(e)}")
            return False
    
    def _merge_diagnostic_report_details(self, new_resource: Resource, existing_resource: Resource) -> Resource:
        """
        Merge diagnostic report details preserving all information.
        """
        try:
            # Start with new resource as base (it's likely more complete)
            merged = copy.deepcopy(new_resource)
            
            # Preserve any additional results from existing resource
            existing_results = getattr(existing_resource, 'result', [])
            new_results = getattr(new_resource, 'result', [])
            
            # Combine results, avoiding duplicates
            all_results = list(new_results)
            for existing_result in existing_results:
                # Simple duplicate check based on reference
                is_duplicate = any(
                    existing_result.get('reference') == new_result.get('reference')
                    for new_result in new_results
                )
                if not is_duplicate:
                    all_results.append(existing_result)
            
            if all_results:
                merged.result = all_results
            
            # Preserve conclusion if missing in new resource
            if not getattr(merged, 'conclusion', None) and getattr(existing_resource, 'conclusion', None):
                merged.conclusion = existing_resource.conclusion
            
            # Update metadata
            merged.meta = merged.meta or {}
            merged.meta['lastUpdated'] = datetime.utcnow().isoformat() + 'Z'
            
            return merged
            
        except Exception as e:
            self.logger.error(f"Failed to merge diagnostic report details: {str(e)}")
            return new_resource
    
    def _update_related_observations(self, report: Resource, current_bundle: Bundle, context: Dict[str, Any]):
        """
        Update observations referenced by this diagnostic report.
        """
        try:
            results = getattr(report, 'result', [])
            for result_ref in results:
                ref_url = result_ref.get('reference', '')
                if ref_url.startswith('#'):
                    # Internal reference - observation should be in report.contained
                    continue
                
                # Find the observation in the bundle and update its diagnostic report reference
                for entry in current_bundle.entry:
                    if (hasattr(entry, 'resource') and 
                        entry.resource.resource_type == 'Observation' and
                        ref_url.endswith(entry.resource.id)):
                        
                        # Add reference back to this diagnostic report
                        if not hasattr(entry.resource, 'derivedFrom'):
                            entry.resource.derivedFrom = []
                        
                        report_ref = {
                            'reference': f"DiagnosticReport/{report.id}",
                            'display': f"Diagnostic Report {getattr(report, 'code', {}).get('text', 'Unknown')}"
                        }
                        
                        if report_ref not in entry.resource.derivedFrom:
                            entry.resource.derivedFrom.append(report_ref)
                        break
                        
        except Exception as e:
            self.logger.warning(f"Failed to update related observations: {str(e)}")


 
    """
    Specialized merge handler for CarePlan resources.
    
    Handles care plan versioning, goal tracking, activity status updates,
    and care team relationship management.
    """
    
    def merge_resource(
        self,
        new_resource: Resource,
        current_bundle: Bundle,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge a CarePlan resource with versioning and goal tracking.
        """
        self.logger.debug(f"Merging CarePlan resource")
        
        # Initialize result tracking
        merge_result = {
            'action': 'unknown',
            'resource_type': 'CarePlan',
            'resource_id': getattr(new_resource, 'id', 'unknown'),
            'conflicts_detected': 0,
            'conflicts_resolved': 0,
            'duplicates_removed': 0,
            'errors': [],
            'warnings': [],
            'conflict_details': []
        }
        
        # Look for existing care plan with same identifier or category
        existing_resource = self._find_existing_resource(
            new_resource,
            current_bundle,
            ['identifier', 'subject', 'category']
        )
        
        if existing_resource:
            # Check if this is a care plan update or new version
            if self._is_care_plan_update(new_resource, existing_resource):
                # Update existing care plan
                merged_resource = self._merge_care_plan_details(new_resource, existing_resource)
                self._update_resource_in_bundle(merged_resource, current_bundle, existing_resource)
                merge_result['action'] = 'updated'
            else:
                # This is a new care plan version - add it and mark old one as superseded
                self._supersede_care_plan(existing_resource)
                merge_result = self._add_resource_to_bundle(new_resource, current_bundle, context)
                merge_result['action'] = 'added'
                merge_result['warnings'] = ['Previous care plan superseded by new version']
        else:
            # No existing care plan - add new one
            merge_result = self._add_resource_to_bundle(new_resource, current_bundle, context)
            merge_result['action'] = 'added'
        
        return merge_result
    
    def _is_care_plan_update(self, new_resource: Resource, existing_resource: Resource) -> bool:
        """
        Determine if new care plan is an update vs new version.
        """
        try:
            # Check status changes (active -> completed, etc.)
            new_status = getattr(new_resource, 'status', '')
            existing_status = getattr(existing_resource, 'status', '')
            
            # If status changed, this is likely an update
            if new_status != existing_status and new_status in ['completed', 'cancelled', 'on-hold']:
                return True
            
            # Check if new resource has additional activities
            new_activities = getattr(new_resource, 'activity', [])
            existing_activities = getattr(existing_resource, 'activity', [])
            
            if len(new_activities) > len(existing_activities):
                return True
            
            # Check period overlap
            new_period = getattr(new_resource, 'period', {})
            existing_period = getattr(existing_resource, 'period', {})
            
            if new_period and existing_period:
                new_start = new_period.get('start')
                existing_start = existing_period.get('start')
                
                if new_start and existing_start and new_start == existing_start:
                    return True
            
            return False
            
        except Exception as e:
            self.logger.warning(f"Error determining care plan update: {str(e)}")
            return False
    
    def _merge_care_plan_details(self, new_resource: Resource, existing_resource: Resource) -> Resource:
        """
        Merge care plan details preserving goal tracking and activity history.
        """
        try:
            # Start with existing as base and update with new information
            merged = copy.deepcopy(existing_resource)
            
            # Update status if changed
            new_status = getattr(new_resource, 'status', None)
            if new_status:
                merged.status = new_status
            
            # Merge activities, preserving existing and adding new ones
            existing_activities = getattr(merged, 'activity', [])
            new_activities = getattr(new_resource, 'activity', [])
            
            # Combine activities, updating existing ones and adding new ones
            activity_map = {}
            
            # Index existing activities
            for i, activity in enumerate(existing_activities):
                activity_id = activity.get('id') or f"activity-{i}"
                activity_map[activity_id] = activity
            
            # Process new activities
            for activity in new_activities:
                activity_id = activity.get('id') or f"new-activity-{len(activity_map)}"
                
                if activity_id in activity_map:
                    # Update existing activity
                    self._merge_activity_details(activity_map[activity_id], activity)
                else:
                    # Add new activity
                    activity_map[activity_id] = activity
            
            merged.activity = list(activity_map.values())
            
            # Merge goals
            existing_goals = getattr(merged, 'goal', [])
            new_goals = getattr(new_resource, 'goal', [])
            
            # Combine goals avoiding duplicates
            all_goals = list(existing_goals)
            for new_goal in new_goals:
                is_duplicate = any(
                    new_goal.get('reference') == existing_goal.get('reference')
                    for existing_goal in existing_goals
                )
                if not is_duplicate:
                    all_goals.append(new_goal)
            
            if all_goals:
                merged.goal = all_goals
            
            # Update care team if provided
            new_care_team = getattr(new_resource, 'careTeam', [])
            if new_care_team:
                merged.careTeam = new_care_team
            
            # Update metadata
            merged.meta = merged.meta or {}
            merged.meta['lastUpdated'] = datetime.utcnow().isoformat() + 'Z'
            
            return merged
            
        except Exception as e:
            self.logger.error(f"Failed to merge care plan details: {str(e)}")
            return new_resource
    
    def _merge_activity_details(self, existing_activity: Dict, new_activity: Dict):
        """
        Merge activity details preserving progress information.
        """
        try:
            # Update status if changed
            new_status = new_activity.get('detail', {}).get('status')
            if new_status:
                if 'detail' not in existing_activity:
                    existing_activity['detail'] = {}
                existing_activity['detail']['status'] = new_status
            
            # Update progress if provided
            new_progress = new_activity.get('progress', [])
            if new_progress:
                existing_progress = existing_activity.get('progress', [])
                existing_activity['progress'] = existing_progress + new_progress
            
            # Update outcome codes if provided
            new_outcome = new_activity.get('outcomeCodeableConcept', [])
            if new_outcome:
                existing_activity['outcomeCodeableConcept'] = new_outcome
                
        except Exception as e:
            self.logger.warning(f"Failed to merge activity details: {str(e)}")
    
    def _supersede_care_plan(self, existing_resource: Resource):
        """
        Mark existing care plan as superseded.
        """
        try:
            existing_resource.status = 'revoked'
            existing_resource.meta = existing_resource.meta or {}
            existing_resource.meta['lastUpdated'] = datetime.utcnow().isoformat() + 'Z'
            
        except Exception as e:
            self.logger.warning(f"Failed to supersede care plan: {str(e)}")


class ResourceMergeHandlerFactory:
    """
    Factory class for creating appropriate merge handlers for different FHIR resource types.
    """
    
    def __init__(self):
        from .merge_handlers import ResourceMergeHandlerFactory as _Factory
        factory = _Factory()
        # Delegate to external factory
        self._handlers = {k: v for k, v in factory._handlers.items()}
        self._generic_handler = factory._generic_handler
    
    def get_handler(self, resource_type: str):
        """
        Get the appropriate merge handler for a resource type.
        
        Args:
            resource_type: FHIR resource type string
            
        Returns:
            Appropriate merge handler instance
        """
        return self._handlers.get(resource_type, self._generic_handler)
    
    def register_handler(self, resource_type: str, handler):
        """
        Register a custom merge handler for a resource type.
        
        Args:
            resource_type: FHIR resource type string
            handler: Merge handler instance
        """
        self._handlers[resource_type] = handler
