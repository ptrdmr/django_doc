"""
FHIR Merge Validation and Quality Checks

This module provides comprehensive validation and quality checking for FHIR merge results,
including structural validation, reference integrity, logical consistency checks, and
automatic correction of minor issues.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime, timedelta
from enum import Enum
import uuid

from .bundle_utils import get_resources_by_type
from .fhir_models import PatientResource

logger = logging.getLogger(__name__)


class ValidationSeverity(Enum):
    """Severity levels for validation issues."""
    INFO = "info"
    WARNING = "warning" 
    ERROR = "error"
    CRITICAL = "critical"


class ValidationCategory(Enum):
    """Categories of validation issues."""
    STRUCTURE = "structure"
    REFERENCES = "references"
    LOGIC = "logic"
    COMPLETENESS = "completeness"
    CONSISTENCY = "consistency"
    SAFETY = "safety"


class ValidationIssue:
    """Represents a single validation issue found during merge validation."""
    
    def __init__(
        self,
        severity: ValidationSeverity,
        category: ValidationCategory,
        message: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        field_path: Optional[str] = None,
        auto_correctable: bool = False,
        correction_description: Optional[str] = None
    ):
        self.id = str(uuid.uuid4())
        self.severity = severity
        self.category = category
        self.message = message
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.field_path = field_path
        self.auto_correctable = auto_correctable
        self.correction_description = correction_description
        self.timestamp = datetime.now()
        self.corrected = False
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert validation issue to dictionary format."""
        return {
            'id': self.id,
            'severity': self.severity.value,
            'category': self.category.value,
            'message': self.message,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'field_path': self.field_path,
            'auto_correctable': self.auto_correctable,
            'correction_description': self.correction_description,
            'timestamp': self.timestamp.isoformat(),
            'corrected': self.corrected
        }


class ValidationReport:
    """Comprehensive report of validation results and quality metrics."""
    
    def __init__(self):
        self.issues: List[ValidationIssue] = []
        self.corrections_applied: List[ValidationIssue] = []
        self.resources_validated = 0
        self.validation_start_time = datetime.now()
        self.validation_end_time: Optional[datetime] = None
        self.overall_score: Optional[float] = None
        
    def add_issue(self, issue: ValidationIssue):
        """Add a validation issue to the report."""
        self.issues.append(issue)
        logger.debug(f"Validation issue added: {issue.severity.value} - {issue.message}")
    
    def add_correction(self, issue: ValidationIssue):
        """Record that an automatic correction was applied."""
        issue.corrected = True
        self.corrections_applied.append(issue)
        logger.info(f"Auto-correction applied: {issue.correction_description}")
    
    def finalize(self):
        """Finalize the validation report and calculate metrics."""
        self.validation_end_time = datetime.now()
        self.overall_score = self._calculate_quality_score()
    
    def _calculate_quality_score(self) -> float:
        """Calculate overall quality score (0-100) based on validation results."""
        if self.resources_validated == 0:
            return 100.0
            
        # Weight different severity levels
        severity_weights = {
            ValidationSeverity.CRITICAL: 20,
            ValidationSeverity.ERROR: 10,
            ValidationSeverity.WARNING: 3,
            ValidationSeverity.INFO: 1
        }
        
        total_penalty = 0
        for issue in self.issues:
            if not issue.corrected:
                total_penalty += severity_weights.get(issue.severity, 1)
        
        # Calculate score (penalize more heavily for more resources)
        max_possible_penalty = self.resources_validated * 5  # Baseline expectation
        score = max(0, 100 - (total_penalty / max(max_possible_penalty, 1)) * 100)
        return round(score, 2)
    
    def get_issues_by_severity(self, severity: ValidationSeverity) -> List[ValidationIssue]:
        """Get all issues of a specific severity level."""
        return [issue for issue in self.issues if issue.severity == severity]
    
    def get_issues_by_category(self, category: ValidationCategory) -> List[ValidationIssue]:
        """Get all issues of a specific category."""
        return [issue for issue in self.issues if issue.category == category]
    
    def has_critical_issues(self) -> bool:
        """Check if there are any uncorrected critical issues."""
        return any(
            issue.severity == ValidationSeverity.CRITICAL and not issue.corrected
            for issue in self.issues
        )
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of validation results."""
        severity_counts = {}
        category_counts = {}
        
        for issue in self.issues:
            if not issue.corrected:
                severity_counts[issue.severity.value] = severity_counts.get(issue.severity.value, 0) + 1
                category_counts[issue.category.value] = category_counts.get(issue.category.value, 0) + 1
        
        return {
            'total_issues': len([i for i in self.issues if not i.corrected]),
            'total_corrections': len(self.corrections_applied),
            'resources_validated': self.resources_validated,
            'quality_score': self.overall_score,
            'severity_breakdown': severity_counts,
            'category_breakdown': category_counts,
            'has_critical_issues': self.has_critical_issues(),
            'validation_duration_seconds': (
                (self.validation_end_time - self.validation_start_time).total_seconds()
                if self.validation_end_time else None
            )
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert validation report to dictionary format."""
        return {
            'summary': self.get_summary(),
            'issues': [issue.to_dict() for issue in self.issues],
            'corrections_applied': [issue.to_dict() for issue in self.corrections_applied],
            'validation_start_time': self.validation_start_time.isoformat(),
            'validation_end_time': self.validation_end_time.isoformat() if self.validation_end_time else None
        }


class FHIRMergeValidator:
    """
    Comprehensive validator for FHIR merge results.
    
    Performs post-merge validation of FHIR bundles to ensure data quality,
    referential integrity, logical consistency, and clinical safety.
    """
    
    def __init__(self, auto_correct: bool = True):
        """
        Initialize the FHIR merge validator.
        
        Args:
            auto_correct: Whether to automatically correct minor issues
        """
        self.auto_correct = auto_correct
        self.logger = logger
        
    def validate_merge_result(self, fhir_bundle: Dict[str, Any]) -> ValidationReport:
        """
        Perform comprehensive validation of a FHIR bundle after merge.
        
        Args:
            fhir_bundle: FHIR bundle to validate
            
        Returns:
            ValidationReport: Comprehensive validation report
        """
        report = ValidationReport()
        
        try:
            self.logger.info("Starting FHIR merge validation")
            
            # Count resources for scoring
            resources = self._get_all_resources(fhir_bundle)
            report.resources_validated = len(resources)
            
            # Perform different types of validation
            self._validate_bundle_structure(fhir_bundle, report)
            self._validate_references(fhir_bundle, report)
            self._validate_resource_completeness(fhir_bundle, report)
            self._validate_logical_consistency(fhir_bundle, report)
            self._validate_clinical_safety(fhir_bundle, report)
            
            # Apply automatic corrections if enabled
            if self.auto_correct:
                self._apply_automatic_corrections(fhir_bundle, report)
            
            report.finalize()
            
            self.logger.info(
                f"FHIR validation completed. Score: {report.overall_score}/100, "
                f"Issues: {len(report.issues)}, Corrections: {len(report.corrections_applied)}"
            )
            
            return report
            
        except Exception as e:
            self.logger.error(f"Error during FHIR validation: {e}")
            report.add_issue(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                category=ValidationCategory.STRUCTURE,
                message=f"Validation process failed: {str(e)}"
            ))
            report.finalize()
            return report
    
    def _get_all_resources(self, fhir_bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract all resources from FHIR bundle."""
        resources = []
        
        # Handle different bundle structures
        if 'entry' in fhir_bundle:
            # Standard FHIR Bundle format
            for entry in fhir_bundle.get('entry', []):
                if 'resource' in entry:
                    resources.append(entry['resource'])
        else:
            # Our custom format with resource types as keys
            for resource_type, resource_list in fhir_bundle.items():
                if isinstance(resource_list, list):
                    resources.extend(resource_list)
        
        return resources
    
    def _validate_bundle_structure(self, fhir_bundle: Dict[str, Any], report: ValidationReport):
        """Validate basic FHIR bundle structure."""
        self.logger.debug("Validating bundle structure")
        
        # Check if bundle is empty
        resources = self._get_all_resources(fhir_bundle)
        if not resources:
            report.add_issue(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category=ValidationCategory.STRUCTURE,
                message="FHIR bundle is empty",
                auto_correctable=False
            ))
            return
        
        # Validate each resource has required fields
        for resource in resources:
            self._validate_resource_structure(resource, report)
    
    def _validate_resource_structure(self, resource: Dict[str, Any], report: ValidationReport):
        """Validate individual resource structure."""
        resource_type = resource.get('resourceType')
        resource_id = resource.get('id')
        
        if not resource_type:
            report.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                category=ValidationCategory.STRUCTURE,
                message="Resource missing resourceType field",
                resource_id=resource_id,
                field_path="resourceType",
                auto_correctable=False
            ))
        
        if not resource_id:
            report.add_issue(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category=ValidationCategory.STRUCTURE,
                message="Resource missing id field",
                resource_type=resource_type,
                field_path="id",
                auto_correctable=True,
                correction_description="Generate UUID for missing resource ID"
            ))
    
    def _validate_references(self, fhir_bundle: Dict[str, Any], report: ValidationReport):
        """Validate referential integrity within the bundle."""
        self.logger.debug("Validating references")
        
        resources = self._get_all_resources(fhir_bundle)
        resource_ids = {res.get('id') for res in resources if res.get('id')}
        
        for resource in resources:
            self._check_resource_references(resource, resource_ids, report)
    
    def _check_resource_references(self, resource: Dict[str, Any], available_ids: Set[str], report: ValidationReport):
        """Check all references in a resource for validity."""
        resource_type = resource.get('resourceType')
        resource_id = resource.get('id')
        
        # Common reference fields to check
        reference_fields = [
            'subject', 'patient', 'encounter', 'performer', 'asserter',
            'requester', 'basedOn', 'partOf', 'focus', 'context'
        ]
        
        for field in reference_fields:
            if field in resource:
                ref_value = resource[field]
                if isinstance(ref_value, dict) and 'reference' in ref_value:
                    ref_id = ref_value['reference'].split('/')[-1]  # Extract ID from reference
                    if ref_id not in available_ids:
                        report.add_issue(ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            category=ValidationCategory.REFERENCES,
                            message=f"Reference to non-existent resource: {ref_value['reference']}",
                            resource_type=resource_type,
                            resource_id=resource_id,
                            field_path=field,
                            auto_correctable=False
                        ))
    
    def _validate_resource_completeness(self, fhir_bundle: Dict[str, Any], report: ValidationReport):
        """Validate that resources have essential clinical information."""
        self.logger.debug("Validating resource completeness")
        
        resources = self._get_all_resources(fhir_bundle)
        
        for resource in resources:
            resource_type = resource.get('resourceType')
            
            if resource_type == 'Observation':
                self._validate_observation_completeness(resource, report)
            elif resource_type == 'Condition':
                self._validate_condition_completeness(resource, report)
            elif resource_type == 'MedicationStatement':
                self._validate_medication_completeness(resource, report)
    
    def _validate_observation_completeness(self, observation: Dict[str, Any], report: ValidationReport):
        """Validate Observation resource completeness."""
        obs_id = observation.get('id')
        
        # Check for essential fields
        if 'code' not in observation:
            report.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                category=ValidationCategory.COMPLETENESS,
                message="Observation missing code field",
                resource_type="Observation",
                resource_id=obs_id,
                field_path="code",
                auto_correctable=False
            ))
        
        # Check for value
        value_fields = ['valueQuantity', 'valueString', 'valueBoolean', 'valueCodeableConcept']
        if not any(field in observation for field in value_fields):
            report.add_issue(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category=ValidationCategory.COMPLETENESS,
                message="Observation missing value field",
                resource_type="Observation",
                resource_id=obs_id,
                field_path="value[x]",
                auto_correctable=False
            ))
    
    def _validate_condition_completeness(self, condition: Dict[str, Any], report: ValidationReport):
        """Validate Condition resource completeness."""
        condition_id = condition.get('id')
        
        if 'code' not in condition:
            report.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                category=ValidationCategory.COMPLETENESS,
                message="Condition missing code field",
                resource_type="Condition",
                resource_id=condition_id,
                field_path="code",
                auto_correctable=False
            ))
        
        if 'clinicalStatus' not in condition:
            report.add_issue(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category=ValidationCategory.COMPLETENESS,
                message="Condition missing clinical status",
                resource_type="Condition",
                resource_id=condition_id,
                field_path="clinicalStatus",
                auto_correctable=True,
                correction_description="Set default clinical status to 'active'"
            ))
    
    def _validate_medication_completeness(self, medication: Dict[str, Any], report: ValidationReport):
        """Validate MedicationStatement resource completeness."""
        med_id = medication.get('id')
        
        if 'medicationCodeableConcept' not in medication and 'medicationReference' not in medication:
            report.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                category=ValidationCategory.COMPLETENESS,
                message="MedicationStatement missing medication information",
                resource_type="MedicationStatement",
                resource_id=med_id,
                field_path="medication[x]",
                auto_correctable=False
            ))
    
    def _validate_logical_consistency(self, fhir_bundle: Dict[str, Any], report: ValidationReport):
        """Validate logical consistency between related resources."""
        self.logger.debug("Validating logical consistency")
        
        resources = self._get_all_resources(fhir_bundle)
        observations = [r for r in resources if r.get('resourceType') == 'Observation']
        
        # Check temporal consistency for lab results
        self._check_temporal_consistency(observations, report)
    
    def _check_temporal_consistency(self, observations: List[Dict[str, Any]], report: ValidationReport):
        """Check temporal consistency of observations."""
        # Group observations by patient and code
        grouped_obs = {}
        
        for obs in observations:
            patient_ref = obs.get('subject', {}).get('reference', '')
            code = obs.get('code', {})
            code_key = str(code)  # Simple grouping by code
            
            key = f"{patient_ref}_{code_key}"
            if key not in grouped_obs:
                grouped_obs[key] = []
            grouped_obs[key].append(obs)
        
        # Check for temporal inconsistencies
        for obs_group in grouped_obs.values():
            if len(obs_group) > 1:
                self._check_observation_sequence(obs_group, report)
    
    def _check_observation_sequence(self, observations: List[Dict[str, Any]], report: ValidationReport):
        """Check if observation sequence makes clinical sense."""
        # Sort by effective date
        dated_obs = []
        for obs in observations:
            effective_date = obs.get('effectiveDateTime')
            if effective_date:
                try:
                    date_obj = datetime.fromisoformat(effective_date.replace('Z', '+00:00'))
                    dated_obs.append((date_obj, obs))
                except ValueError:
                    continue
        
        if len(dated_obs) < 2:
            return
        
        dated_obs.sort(key=lambda x: x[0])
        
        # Check for suspiciously close observations (within 1 minute)
        for i in range(1, len(dated_obs)):
            prev_date, prev_obs = dated_obs[i-1]
            curr_date, curr_obs = dated_obs[i]
            
            if (curr_date - prev_date).total_seconds() < 60:
                report.add_issue(ValidationIssue(
                    severity=ValidationSeverity.INFO,
                    category=ValidationCategory.LOGIC,
                    message=f"Observations very close in time (within 1 minute)",
                    resource_type="Observation",
                    resource_id=curr_obs.get('id'),
                    auto_correctable=False
                ))
    
    def _validate_clinical_safety(self, fhir_bundle: Dict[str, Any], report: ValidationReport):
        """Validate clinical safety aspects of the data."""
        self.logger.debug("Validating clinical safety")
        
        resources = self._get_all_resources(fhir_bundle)
        
        # Check for critical lab values without proper status
        for resource in resources:
            if resource.get('resourceType') == 'Observation':
                self._check_critical_values(resource, report)
    
    def _check_critical_values(self, observation: Dict[str, Any], report: ValidationReport):
        """Check for critical lab values that need attention."""
        obs_id = observation.get('id')
        value_qty = observation.get('valueQuantity', {})
        
        if not value_qty:
            return
        
        value = value_qty.get('value')
        unit = value_qty.get('unit', '').lower()
        
        # Define critical thresholds for common lab values
        critical_thresholds = {
            'glucose': {'value': 400, 'units': ['mg/dl', 'mg/dl']},
            'potassium': {'value': 6.0, 'units': ['meq/l', 'mmol/l']},
            'creatinine': {'value': 5.0, 'units': ['mg/dl']},
        }
        
        # Simple check for glucose as example
        if value and isinstance(value, (int, float)):
            if 'glucose' in str(observation.get('code', {})).lower() and value > 400:
                if unit in ['mg/dl', 'mg/dl']:
                    report.add_issue(ValidationIssue(
                        severity=ValidationSeverity.CRITICAL,
                        category=ValidationCategory.SAFETY,
                        message=f"Critical glucose value detected: {value} {unit}",
                        resource_type="Observation",
                        resource_id=obs_id,
                        field_path="valueQuantity.value",
                        auto_correctable=False
                    ))
    
    def _apply_automatic_corrections(self, fhir_bundle: Dict[str, Any], report: ValidationReport):
        """Apply automatic corrections for correctable issues."""
        self.logger.debug("Applying automatic corrections")
        
        correctable_issues = [issue for issue in report.issues if issue.auto_correctable]
        
        for issue in correctable_issues:
            if self._apply_correction(fhir_bundle, issue):
                report.add_correction(issue)
    
    def _apply_correction(self, fhir_bundle: Dict[str, Any], issue: ValidationIssue) -> bool:
        """Apply a specific automatic correction."""
        try:
            if issue.field_path == "id" and "missing id field" in issue.message:
                # Generate UUID for missing resource ID
                resources = self._get_all_resources(fhir_bundle)
                for resource in resources:
                    if resource.get('resourceType') == issue.resource_type and not resource.get('id'):
                        resource['id'] = str(uuid.uuid4())
                        return True
            
            elif issue.field_path == "clinicalStatus" and issue.resource_type == "Condition":
                # Set default clinical status
                resources = self._get_all_resources(fhir_bundle)
                for resource in resources:
                    if (resource.get('resourceType') == 'Condition' and 
                        resource.get('id') == issue.resource_id and
                        'clinicalStatus' not in resource):
                        resource['clinicalStatus'] = {
                            'coding': [{
                                'system': 'http://terminology.hl7.org/CodeSystem/condition-clinical',
                                'code': 'active',
                                'display': 'Active'
                            }]
                        }
                        return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to apply correction for issue {issue.id}: {e}")
            return False
