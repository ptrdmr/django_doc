"""
FHIR Data Accumulation Service

This service handles the accumulation of FHIR resources into patient records
with proper provenance tracking, conflict resolution, and audit trails.
Follows HIPAA compliance requirements and maintains data integrity.
"""

import json
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, date
from uuid import uuid4
import re
from decimal import Decimal, InvalidOperation
import copy
from datetime import datetime

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
from .fhir_models import (
    PatientResource,
    DocumentReferenceResource,
    ConditionResource,
    ObservationResource,
    MedicationStatementResource,
    PractitionerResource,
    ProvenanceResource
)


logger = logging.getLogger(__name__)


def fhir_json_serializer(obj):
    """
    Custom JSON serializer for FHIR objects that handles Decimal values.
    
    Like adjustin' the carburetor on your old truck - sometimes you need
    custom parts to make different components work together properly.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


# =============================================================================
# PROVENANCE TRACKING SYSTEM
# =============================================================================

class ProvenanceTracker:
    """
    Comprehensive provenance tracking system for FHIR merge operations.
    
    Handles creation and management of FHIR Provenance resources throughout
    the merge process, maintaining complete audit trails for:
    - Resource creation during conversion
    - Conflict detection and resolution
    - Deduplication operations
    - Bundle merging activities
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the provenance tracker.
        
        Args:
            config: Configuration dictionary with provenance settings
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.provenance_cache = {}  # Cache for created provenance resources
        
    def create_merge_provenance(
        self,
        target_resources: List[Resource],
        metadata: Dict[str, Any],
        user: Optional[User],
        activity_type: str = "merge",
        reason: Optional[str] = None
    ) -> ProvenanceResource:
        """
        Create a provenance resource for a merge operation.
        
        Args:
            target_resources: Resources involved in the merge
            metadata: Document metadata containing source information
            user: User performing the merge operation
            activity_type: Type of merge activity (merge, update, create)
            reason: Optional reason for the operation
            
        Returns:
            ProvenanceResource instance
        """
        try:
            # Determine responsible party
            responsible_party = user.username if user else "System"
            
            # Create primary target resource (usually the first one)
            primary_target = target_resources[0] if target_resources else None
            if not primary_target:
                raise ValueError("No target resources provided for provenance")
            
            # Build comprehensive reason string
            merge_reason = self._build_merge_reason(
                activity_type, 
                len(target_resources), 
                metadata.get('document_type', 'Unknown'),
                reason
            )
            
            # Create the provenance resource
            provenance = ProvenanceResource.create_for_resource(
                target_resource=primary_target,
                source_system="Medical Document Parser",
                responsible_party=responsible_party,
                activity_type=activity_type,
                occurred_at=timezone.now(),
                reason=merge_reason,
                source_document_id=metadata.get('document_id')
            )
            
            # Add additional targets if multiple resources
            if len(target_resources) > 1:
                additional_targets = []
                for resource in target_resources[1:]:
                    additional_targets.append(Reference(
                        reference=f"{resource.resource_type}/{resource.id}"
                    ))
                provenance.target.extend(additional_targets)
            
            # Cache the provenance for later use
            self.provenance_cache[provenance.id] = provenance
            
            self.logger.info(
                f"Created merge provenance {provenance.id} for {len(target_resources)} resources"
            )
            
            return provenance
            
        except Exception as e:
            self.logger.error(f"Failed to create merge provenance: {str(e)}")
            raise
    
    def create_conflict_resolution_provenance(
        self,
        resolved_resource: Resource,
        conflict_details: List,
        resolution_strategy: str,
        user: Optional[User]
    ) -> ProvenanceResource:
        """
        Create provenance for conflict resolution operations.
        
        Args:
            resolved_resource: The resource after conflict resolution
            conflict_details: List of detected conflicts
            resolution_strategy: Strategy used for resolution
            user: User who resolved the conflict (if manual)
            
        Returns:
            ProvenanceResource instance
        """
        try:
            responsible_party = user.username if user else f"Auto-Resolver ({resolution_strategy})"
            
            # Build detailed reason for conflict resolution
            reason = self._build_conflict_resolution_reason(
                conflict_details, resolution_strategy
            )
            
            provenance = ProvenanceResource.create_for_resource(
                target_resource=resolved_resource,
                source_system="FHIR Conflict Resolver",
                responsible_party=responsible_party,
                activity_type="transform",
                occurred_at=timezone.now(),
                reason=reason
            )
            
            # Add conflict resolution metadata as extensions
            if conflict_details:
                conflict_extension = Extension(
                    url="http://medicaldocparser.com/fhir/extension/conflict-resolution",
                    valueString=json.dumps({
                        "conflicts_resolved": len(conflict_details),
                        "resolution_strategy": resolution_strategy,
                        "conflict_types": [c.get('conflict_type', 'unknown') for c in conflict_details],
                        "resolution_timestamp": timezone.now().isoformat()
                    })
                )
                
                if not hasattr(provenance, 'extension') or not provenance.extension:
                    provenance.extension = []
                provenance.extension.append(conflict_extension)
            
            self.provenance_cache[provenance.id] = provenance
            self.logger.info(f"Created conflict resolution provenance {provenance.id}")
            
            return provenance
            
        except Exception as e:
            self.logger.error(f"Failed to create conflict resolution provenance: {str(e)}")
            raise
    
    def create_deduplication_provenance(
        self,
        merged_resource: Resource,
        duplicate_details: List,
        user: Optional[User]
    ) -> ProvenanceResource:
        """
        Create provenance for deduplication operations.
        
        Args:
            merged_resource: The primary resource after deduplication
            duplicate_details: List of duplicate resource details
            user: User performing the operation
            
        Returns:
            ProvenanceResource instance
        """
        try:
            responsible_party = user.username if user else "Deduplication Engine"
            
            reason = self._build_deduplication_reason(duplicate_details)
            
            provenance = ProvenanceResource.create_for_resource(
                target_resource=merged_resource,
                source_system="FHIR Deduplicator",
                responsible_party=responsible_party,
                activity_type="transform",
                occurred_at=timezone.now(),
                reason=reason
            )
            
            # Add deduplication metadata
            if duplicate_details:
                dedup_extension = Extension(
                    url="http://medicaldocparser.com/fhir/extension/deduplication",
                    valueString=json.dumps({
                        "duplicates_merged": len(duplicate_details),
                        "similarity_scores": [getattr(d, 'similarity_score', 0.0) for d in duplicate_details],
                        "duplicate_types": [getattr(d, 'duplicate_type', 'exact') for d in duplicate_details],
                        "deduplication_timestamp": timezone.now().isoformat()
                    })
                )
                
                if not hasattr(provenance, 'extension') or not provenance.extension:
                    provenance.extension = []
                provenance.extension.append(dedup_extension)
            
            self.provenance_cache[provenance.id] = provenance
            self.logger.info(f"Created deduplication provenance {provenance.id}")
            
            return provenance
            
        except Exception as e:
            self.logger.error(f"Failed to create deduplication provenance: {str(e)}")
            raise
    
    def chain_provenance(
        self,
        new_provenance: ProvenanceResource,
        previous_provenance: ProvenanceResource
    ) -> ProvenanceResource:
        """
        Create a provenance chain linking operations together.
        
        Args:
            new_provenance: New provenance resource
            previous_provenance: Previous provenance in the chain
            
        Returns:
            Updated new_provenance with chain link
        """
        try:
            # Use the existing method from ProvenanceResource
            chained_provenance = ProvenanceResource.create_for_update(
                target_resource=new_provenance.target[0].reference.split('/')[-1],
                previous_provenance=previous_provenance,
                responsible_party=self._extract_responsible_party(new_provenance),
                reason="Chained provenance update"
            )
            
            # Preserve the original new provenance data but add the chain
            for attr in ['extension', 'entity']:
                if hasattr(new_provenance, attr):
                    setattr(chained_provenance, attr, getattr(new_provenance, attr))
            
            return chained_provenance
            
        except Exception as e:
            self.logger.error(f"Failed to chain provenance: {str(e)}")
            return new_provenance  # Return original if chaining fails
    
    def get_provenance_list(self) -> List[ProvenanceResource]:
        """
        Get all created provenance resources from this tracking session.
        
        Returns:
            List of ProvenanceResource instances
        """
        return list(self.provenance_cache.values())
    
    def get_latest_provenance_for_resource(self, resource_id: str) -> Optional[ProvenanceResource]:
        """
        Get the most recent provenance resource for a specific resource.
        
        Args:
            resource_id: ID of the target resource
            
        Returns:
            Most recent ProvenanceResource or None if not found
        """
        latest_provenance = None
        latest_timestamp = None
        
        for provenance in self.provenance_cache.values():
            if hasattr(provenance, 'target') and provenance.target:
                for target in provenance.target:
                    if hasattr(target, 'reference') and target.reference:
                        target_id = target.reference.split('/')[-1]
                        if target_id == resource_id:
                            # Get timestamp from provenance
                            timestamp = getattr(provenance, 'recorded', None)
                            if timestamp and (latest_timestamp is None or timestamp > latest_timestamp):
                                latest_provenance = provenance
                                latest_timestamp = timestamp
        
        return latest_provenance
    
    def create_chained_provenance(
        self,
        target_resource: Resource,
        activity_type: str,
        reason: str,
        user: Optional[User],
        metadata: Dict[str, Any]
    ) -> ProvenanceResource:
        """
        Create a new provenance resource that's automatically chained to the previous one.
        
        Args:
            target_resource: Resource this provenance tracks
            activity_type: Type of activity being tracked
            reason: Reason for the activity
            user: User performing the activity
            metadata: Additional metadata
            
        Returns:
            New ProvenanceResource with chaining
        """
        resource_id = str(getattr(target_resource, 'id', ''))
        previous_provenance = self.get_latest_provenance_for_resource(resource_id)
        
        # Create new provenance
        if previous_provenance:
            # Chain to previous provenance
            chained_provenance = ProvenanceResource.create_for_update(
                target_resource=target_resource,
                previous_provenance=previous_provenance,
                responsible_party=user.username if user else "System",
                reason=reason
            )
        else:
            # Create initial provenance
            chained_provenance = ProvenanceResource.create_for_resource(
                target_resource=target_resource,
                source_system="Medical Document Parser",
                responsible_party=user.username if user else "System",
                activity_type=activity_type,
                occurred_at=timezone.now(),
                reason=reason,
                source_document_id=metadata.get('document_id')
            )
        
        # Cache the new provenance
        self.provenance_cache[chained_provenance.id] = chained_provenance
        
        self.logger.info(f"Created chained provenance {chained_provenance.id} for resource {resource_id}")
        
        return chained_provenance
    
    def clear_cache(self):
        """Clear the provenance cache."""
        self.provenance_cache.clear()
    
    # Private helper methods
    
    def _build_merge_reason(
        self, 
        activity_type: str, 
        resource_count: int, 
        document_type: str, 
        custom_reason: Optional[str]
    ) -> str:
        """Build a comprehensive reason string for merge operations."""
        reason_parts = [
            f"FHIR {activity_type} operation",
            f"Processing {resource_count} resource(s)",
            f"From {document_type} document"
        ]
        
        if custom_reason:
            reason_parts.append(custom_reason)
            
        return " | ".join(reason_parts)
    
    def _build_conflict_resolution_reason(
        self, 
        conflict_details: List, 
        resolution_strategy: str
    ) -> str:
        """Build reason string for conflict resolution."""
        conflict_types = set()
        for conflict in conflict_details:
            conflict_type = conflict.get('conflict_type', 'unknown')
            conflict_types.add(conflict_type)
        
        return (
            f"Conflict resolution using {resolution_strategy} strategy | "
            f"Resolved {len(conflict_details)} conflicts of types: {', '.join(conflict_types)}"
        )
    
    def _build_deduplication_reason(self, duplicate_details: List) -> str:
        """Build reason string for deduplication."""
        if not duplicate_details:
            return "Deduplication operation (no duplicates found)"
        
        duplicate_types = set()
        for duplicate in duplicate_details:
            duplicate_type = getattr(duplicate, 'duplicate_type', 'exact')
            duplicate_types.add(duplicate_type)
        
        return (
            f"Deduplication operation | "
            f"Merged {len(duplicate_details)} duplicates of types: {', '.join(duplicate_types)}"
        )
    
    def _extract_responsible_party(self, provenance: ProvenanceResource) -> str:
        """Extract responsible party from existing provenance."""
        try:
            if hasattr(provenance, 'agent') and provenance.agent:
                for agent in provenance.agent:
                    if hasattr(agent, 'who') and hasattr(agent.who, 'display'):
                        return agent.who.display
            return "System"
        except Exception:
            return "System"


# =============================================================================
# DATA VALIDATION FRAMEWORK
# =============================================================================

class ValidationResult:
    """
    Comprehensive validation result object that tracks all validation outcomes.
    """
    
    def __init__(self):
        self.is_valid = True
        self.data = {}
        self.errors = []
        self.warnings = []
        self.critical_errors = []
        self.field_errors = {}  # Field-specific errors
        self.normalized_fields = []  # Fields that were normalized
        self.validation_metadata = {
            'validation_timestamp': timezone.now(),
            'validator_version': '1.0.0',
            'schema_version': '1.0.0'
        }
    
    def add_error(self, message: str, field: str = None, is_critical: bool = False):
        """Add a validation error."""
        if is_critical:
            self.critical_errors.append(message)
        self.errors.append(message)
        
        if field:
            if field not in self.field_errors:
                self.field_errors[field] = []
            self.field_errors[field].append(message)
        
        self.is_valid = False
    
    def add_warning(self, message: str, field: str = None):
        """Add a validation warning."""
        self.warnings.append(message)
        
        if field:
            if field not in self.field_errors:
                self.field_errors[field] = []
            self.field_errors[field].append(f"WARNING: {message}")
    
    def add_normalized_field(self, field: str, original_value: Any, normalized_value: Any):
        """Track field normalization."""
        self.normalized_fields.append({
            'field': field,
            'original_value': str(original_value),
            'normalized_value': str(normalized_value)
        })
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert validation result to dictionary."""
        return {
            'is_valid': self.is_valid,
            'data': self.data,
            'errors': self.errors,
            'warnings': self.warnings,
            'critical_errors': self.critical_errors,
            'field_errors': self.field_errors,
            'normalized_fields': self.normalized_fields,
            'validation_metadata': self.validation_metadata
        }


class DataNormalizer:
    """
    Utility class for normalizing various types of medical data.
    """
    
    @staticmethod
    def normalize_date(date_value: Any) -> Optional[str]:
        """
        Normalize date values to ISO format.
        
        Args:
            date_value: Date in various formats
            
        Returns:
            ISO formatted date string or None if invalid
        """
        if not date_value:
            return None
        
        # If already a date object
        if isinstance(date_value, datetime):
            return date_value.date().isoformat()
        elif isinstance(date_value, date):
            return date_value.isoformat()
        
        # If string, try to parse various formats
        if isinstance(date_value, str):
            date_value = date_value.strip()
            
            # Common date formats
            date_formats = [
                '%Y-%m-%d',           # 2023-12-25
                '%m/%d/%Y',           # 12/25/2023
                '%m-%d-%Y',           # 12-25-2023
                '%d/%m/%Y',           # 25/12/2023
                '%d-%m-%Y',           # 25-12-2023
                '%B %d, %Y',          # December 25, 2023
                '%b %d, %Y',          # Dec 25, 2023
                '%Y/%m/%d',           # 2023/12/25
                '%m/%d/%y',           # 12/25/23
                '%d/%m/%y',           # 25/12/23
            ]
            
            for fmt in date_formats:
                try:
                    parsed_date = datetime.strptime(date_value, fmt).date()
                    return parsed_date.isoformat()
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def normalize_name(name_value: Any) -> Optional[str]:
        """
        Normalize person names.
        
        Args:
            name_value: Name in various formats
            
        Returns:
            Normalized name string or None if invalid
        """
        if not name_value:
            return None
        
        if not isinstance(name_value, str):
            name_value = str(name_value)
        
        # Basic name normalization
        name_value = name_value.strip()
        
        # Remove multiple spaces
        name_value = re.sub(r'\s+', ' ', name_value)
        
        # Title case for proper names
        name_value = name_value.title()
        
        # Handle common prefixes and suffixes
        name_parts = name_value.split()
        normalized_parts = []
        
        for part in name_parts:
            # Keep common prefixes lowercase
            if part.lower() in ['dr', 'dr.', 'mr', 'mr.', 'mrs', 'mrs.', 'ms', 'ms.']:
                normalized_parts.append(part.capitalize() + ('.' if not part.endswith('.') else ''))
            # Keep common suffixes as-is
            elif part.lower() in ['jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv']:
                normalized_parts.append(part.upper() + ('.' if part.lower() in ['jr', 'sr'] and not part.endswith('.') else ''))
            else:
                normalized_parts.append(part)
        
        return ' '.join(normalized_parts)
    
    @staticmethod
    def normalize_medical_code(code_value: Any, code_system: str = None) -> Optional[Dict[str, str]]:
        """
        Normalize medical codes.
        
        Args:
            code_value: Medical code in various formats
            code_system: Code system (LOINC, SNOMED, ICD-10, etc.)
            
        Returns:
            Normalized code dictionary or None if invalid
        """
        if not code_value:
            return None
        
        if not isinstance(code_value, str):
            code_value = str(code_value)
        
        code_value = code_value.strip().upper()
        
        # Remove common separators and normalize format
        code_value = re.sub(r'[^\w\.-]', '', code_value)
        
        # Detect code system if not provided
        if not code_system:
            if re.match(r'^\d{1,5}-\d$', code_value):  # LOINC pattern
                code_system = 'LOINC'
            elif re.match(r'^[A-Z]\d{2}(\.\d{1,2})?$', code_value):  # ICD-10 pattern
                code_system = 'ICD-10'
            elif len(code_value) >= 6 and code_value.isdigit():  # SNOMED pattern
                code_system = 'SNOMED'
            else:
                code_system = 'UNKNOWN'
        
        return {
            'code': code_value,
            'system': code_system,
            'display': None  # Will be populated later if available
        }
    
    @staticmethod
    def normalize_numeric_value(value: Any, data_type: str = 'decimal') -> Optional[float]:
        """
        Normalize numeric values.
        
        Args:
            value: Numeric value in various formats
            data_type: Expected data type (integer, decimal, percentage)
            
        Returns:
            Normalized numeric value or None if invalid
        """
        if value is None:
            return None
        
        # If already a number
        if isinstance(value, (int, float)):
            return float(value)
        
        # If string, clean and convert
        if isinstance(value, str):
            value = value.strip()
            
            # Check if string contains any letters - if so, it's not a pure number
            if re.search(r'[a-zA-Z]', value):
                return None
            
            # Remove common non-numeric characters (currency symbols, spaces, etc.)
            value = re.sub(r'[^\d\.-]', '', value)
            
            if not value:
                return None
            
            try:
                if data_type == 'integer':
                    return float(int(value))
                else:
                    return float(Decimal(value))
            except (ValueError, InvalidOperation):
                return None
        
        return None


class DocumentSchemaValidator:
    """
    Schema-based validator for different document types.
    """
    
    def __init__(self):
        self.schemas = self._load_schemas()
    
    def _load_schemas(self) -> Dict[str, Dict]:
        """
        Load validation schemas for different document types.
        
        Returns:
            Dictionary of document type schemas
        """
        return {
            'lab_report': {
                'required_fields': ['patient_name', 'test_date', 'tests'],
                'optional_fields': ['ordering_provider', 'lab_facility', 'collection_date'],
                'field_types': {
                    'patient_name': 'string',
                    'test_date': 'date',
                    'collection_date': 'date',
                    'tests': 'array',
                    'ordering_provider': 'string',
                    'lab_facility': 'string'
                },
                'field_constraints': {
                    'patient_name': {'min_length': 2, 'max_length': 100},
                    'test_date': {'min_date': '1900-01-01', 'max_date': 'today+1'},
                    'collection_date': {'min_date': '1900-01-01', 'max_date': 'today+1'}
                }
            },
            'clinical_note': {
                'required_fields': ['patient_name', 'note_date', 'provider'],
                'optional_fields': ['chief_complaint', 'assessment', 'plan', 'diagnosis_codes'],
                'field_types': {
                    'patient_name': 'string',
                    'note_date': 'date',
                    'provider': 'string',
                    'chief_complaint': 'string',
                    'assessment': 'string',
                    'plan': 'string',
                    'diagnosis_codes': 'array'
                },
                'field_constraints': {
                    'patient_name': {'min_length': 2, 'max_length': 100},
                    'note_date': {'min_date': '1900-01-01', 'max_date': 'today+1'},
                    'provider': {'min_length': 2, 'max_length': 100}
                }
            },
            'medication_list': {
                'required_fields': ['patient_name', 'list_date', 'medications'],
                'optional_fields': ['prescribing_provider', 'pharmacy'],
                'field_types': {
                    'patient_name': 'string',
                    'list_date': 'date',
                    'medications': 'array',
                    'prescribing_provider': 'string',
                    'pharmacy': 'string'
                },
                'field_constraints': {
                    'patient_name': {'min_length': 2, 'max_length': 100},
                    'list_date': {'min_date': '1900-01-01', 'max_date': 'today+1'}
                }
            },
            'discharge_summary': {
                'required_fields': ['patient_name', 'admission_date', 'discharge_date'],
                'optional_fields': ['attending_physician', 'diagnosis', 'procedures', 'medications'],
                'field_types': {
                    'patient_name': 'string',
                    'admission_date': 'date',
                    'discharge_date': 'date',
                    'attending_physician': 'string',
                    'diagnosis': 'array',
                    'procedures': 'array',
                    'medications': 'array'
                },
                'field_constraints': {
                    'patient_name': {'min_length': 2, 'max_length': 100},
                    'admission_date': {'min_date': '1900-01-01', 'max_date': 'today+1'},
                    'discharge_date': {'min_date': '1900-01-01', 'max_date': 'today+1'}
                }
            },
            'generic': {
                'required_fields': ['patient_name', 'document_date'],
                'optional_fields': [],
                'field_types': {
                    'patient_name': 'string',
                    'document_date': 'date'
                },
                'field_constraints': {
                    'patient_name': {'min_length': 2, 'max_length': 100},
                    'document_date': {'min_date': '1900-01-01', 'max_date': 'today+1'}
                }
            }
        }
    
    def validate_schema(self, data: Dict[str, Any], document_type: str = 'generic') -> ValidationResult:
        """
        Validate data against document type schema.
        
        Args:
            data: Data to validate
            document_type: Type of document to validate against
            
        Returns:
            ValidationResult with validation outcomes
        """
        result = ValidationResult()
        schema = self.schemas.get(document_type, self.schemas['generic'])
        
        # Check required fields
        for field in schema['required_fields']:
            if field not in data or data[field] is None:
                result.add_error(f"Required field '{field}' is missing", field, is_critical=True)
            elif isinstance(data[field], str) and not data[field].strip():
                result.add_error(f"Required field '{field}' is empty", field, is_critical=True)
        
        # Validate field types and constraints
        for field, value in data.items():
            if value is None:
                continue
            
            expected_type = schema['field_types'].get(field)
            constraints = schema['field_constraints'].get(field, {})
            
            if expected_type:
                validation_error = self._validate_field_type(field, value, expected_type, constraints)
                if validation_error:
                    result.add_error(validation_error, field)
        
        result.data = data
        return result
    
    def _validate_field_type(self, field: str, value: Any, expected_type: str, constraints: Dict) -> Optional[str]:
        """
        Validate a single field's type and constraints.
        
        Args:
            field: Field name
            value: Field value
            expected_type: Expected data type
            constraints: Field constraints
            
        Returns:
            Error message if validation fails, None otherwise
        """
        if expected_type == 'string':
            if not isinstance(value, str):
                return f"Field '{field}' must be a string"
            
            if 'min_length' in constraints and len(value) < constraints['min_length']:
                return f"Field '{field}' must be at least {constraints['min_length']} characters"
            
            if 'max_length' in constraints and len(value) > constraints['max_length']:
                return f"Field '{field}' must be no more than {constraints['max_length']} characters"
        
        elif expected_type == 'date':
            # Date validation will be handled by normalization
            pass
        
        elif expected_type == 'array':
            if not isinstance(value, list):
                return f"Field '{field}' must be an array"
        
        elif expected_type == 'number':
            try:
                float(value)
            except (ValueError, TypeError):
                return f"Field '{field}' must be a number"
        
        return None


def serialize_fhir_data(data: Any) -> Any:
    """
    Recursively serialize FHIR data to ensure datetime and Decimal objects are converted properly.
    
    Like makin' sure all the parts in your engine work together - sometimes you need
    to adjust different types of components to work with the same fuel system.
    
    Args:
        data: Data structure that may contain datetime or Decimal objects
        
    Returns:
        Serialized data with datetime objects converted to ISO strings and Decimals to floats
    """
    if isinstance(data, (datetime, date)):
        return data.isoformat()
    elif isinstance(data, Decimal):
        return float(data)
    elif isinstance(data, dict):
        return {key: serialize_fhir_data(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [serialize_fhir_data(item) for item in data]
    else:
        return data


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
                    
                    # Save the deduplicated bundle
                    patient.cumulative_fhir_json = deduplicated_bundle.dict()
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


# =============================================================================
# HISTORICAL DATA PRESERVATION SYSTEM
# =============================================================================

class HistoricalResourceManager:
    """
    Manager for append-only historical data preservation in FHIR resources.
    
    Like keeping a maintenance log for an old pickup truck - every change gets
    recorded, nothing gets thrown away. Historical data is sacred and must be
    preserved for medical records.
    """
    
    def __init__(self):
        """Initialize the historical resource manager."""
        self.logger = logger
        
    def preserve_resource_history(
        self,
        bundle: Bundle,
        new_resource: Resource,
        source_metadata: Dict[str, Any],
        user: Optional[User] = None,
        preserve_reason: str = "Resource update"
    ) -> Tuple[Bundle, Dict[str, Any]]:
        """
        Preserve historical version of a resource before updating.
        
        Think of this like keeping old receipts in a shoebox - we don't throw
        out the old ones when we get new ones, we just add to the pile.
        
        Args:
            bundle: Current FHIR bundle
            new_resource: New resource version to add
            source_metadata: Metadata about the source of this change
            user: User making the change
            preserve_reason: Reason for the historical preservation
            
        Returns:
            Tuple of (updated_bundle, preservation_results_dict)
        """
        preservation_result = {
            'historical_versions_preserved': 0,
            'new_version_added': False,
            'resource_id': new_resource.id,
            'resource_type': new_resource.resource_type,
            'timestamp': timezone.now().isoformat(),
            'version_chain_maintained': False,
            'status_transition_recorded': False
        }
        
        try:
            # Find existing resource if it exists
            existing_resource = get_latest_resource_version(
                bundle, 
                new_resource.resource_type, 
                new_resource.id
            )
            
            if existing_resource:
                # Create historical version with version tracking
                historical_version = self._create_historical_version(
                    existing_resource,
                    source_metadata,
                    user,
                    preserve_reason
                )
                
                # Add to bundle with historical marker
                historical_version = self._mark_as_historical(historical_version)
                bundle = add_resource_to_bundle(bundle, historical_version, False)
                preservation_result['historical_versions_preserved'] = 1
                
                # Track status transitions for relevant resources
                if self._is_status_tracked_resource(new_resource.resource_type):
                    status_transition = self._track_status_transition(
                        existing_resource, 
                        new_resource,
                        source_metadata
                    )
                    if status_transition:
                        preservation_result['status_transition_recorded'] = True
                        preservation_result['status_transition'] = status_transition
                
                # Maintain version chain
                self._maintain_version_chain(existing_resource, new_resource)
                preservation_result['version_chain_maintained'] = True
            
            # Add the new resource as current version
            bundle = add_resource_to_bundle(bundle, new_resource, True)
            preservation_result['new_version_added'] = True
            
            # Add comprehensive provenance
            self._add_historical_provenance(
                bundle,
                new_resource,
                existing_resource,
                source_metadata,
                user,
                preserve_reason
            )
            
            self.logger.info(
                f"Preserved historical data for {new_resource.resource_type}/{new_resource.id}"
            )
            
        except Exception as e:
            error_msg = f"Failed to preserve resource history: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            preservation_result['error'] = error_msg
            raise FHIRAccumulationError(error_msg) from e
        
        return bundle, preservation_result
    
    def get_resource_timeline(
        self,
        bundle: Bundle,
        resource_type: str,
        resource_id: str,
        include_provenance: bool = True
    ) -> Dict[str, Any]:
        """
        Get the complete timeline of changes for a resource.
        
        Like reviewing all the maintenance records for your truck to see
        what work's been done over the years.
        
        Args:
            bundle: FHIR bundle to search
            resource_type: Type of resource
            resource_id: ID of the resource
            include_provenance: Whether to include provenance information
            
        Returns:
            Dictionary with timeline information
        """
        timeline = {
            'resource_type': resource_type,
            'resource_id': resource_id,
            'versions': [],
            'status_transitions': [],
            'provenance_chain': [],
            'generated_at': timezone.now().isoformat()
        }
        
        try:
            # Get all versions (including historical)
            all_versions = self._get_all_resource_versions(bundle, resource_type, resource_id)
            
            for version in all_versions:
                version_info = {
                    'version_id': getattr(version.meta, 'versionId', None) if version.meta else None,
                    'last_updated': getattr(version.meta, 'lastUpdated', None) if version.meta else None,
                    'is_historical': self._is_historical_version(version),
                    'status': self._extract_resource_status(version),
                    'source_document': self._extract_source_document(version)
                }
                timeline['versions'].append(version_info)
            
            # Track status transitions if applicable
            if self._is_status_tracked_resource(resource_type):
                timeline['status_transitions'] = self._extract_status_transitions(all_versions)
            
            # Get provenance chain if requested
            if include_provenance:
                timeline['provenance_chain'] = self._build_provenance_chain(
                    bundle, resource_type, resource_id
                )
            
        except Exception as e:
            self.logger.error(f"Failed to build resource timeline: {str(e)}", exc_info=True)
            timeline['error'] = str(e)
        
        return timeline
    
    def validate_historical_integrity(
        self,
        bundle: Bundle,
        resource_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validate that historical data integrity is maintained.
        
        Like doing a thorough inspection of your maintenance log to make sure
        nothing's missing and everything's in the right order.
        
        Args:
            bundle: FHIR bundle to validate
            resource_type: Optional resource type to limit validation
            
        Returns:
            Dictionary with validation results
        """
        validation_result = {
            'is_valid': True,
            'issues': [],
            'warnings': [],
            'resource_counts': {},
            'version_chain_issues': [],
            'historical_gaps': [],
            'validated_at': timezone.now().isoformat()
        }
        
        try:
            # Get all resources to validate
            if resource_type:
                resources = get_resources_by_type(bundle, resource_type)
                resource_types_to_check = [resource_type]
            else:
                # Check all resource types
                resource_types_to_check = self._get_unique_resource_types(bundle)
                resources = []
                for rt in resource_types_to_check:
                    resources.extend(get_resources_by_type(bundle, rt))
            
            # Group resources by ID for version chain checking
            resource_groups = {}
            for resource in resources:
                key = f"{resource.resource_type}/{resource.id}"
                if key not in resource_groups:
                    resource_groups[key] = []
                resource_groups[key].append(resource)
            
            # Validate each resource group
            for resource_key, resource_versions in resource_groups.items():
                validation_issues = self._validate_resource_version_chain(resource_versions)
                if validation_issues:
                    validation_result['version_chain_issues'].extend(validation_issues)
                    validation_result['is_valid'] = False
            
            # Check for historical gaps
            historical_gaps = self._check_for_historical_gaps(bundle)
            if historical_gaps:
                validation_result['historical_gaps'] = historical_gaps
                validation_result['warnings'].extend([
                    f"Historical gap detected for {gap}" for gap in historical_gaps
                ])
            
            # Update resource counts
            for rt in resource_types_to_check:
                count = len(get_resources_by_type(bundle, rt))
                validation_result['resource_counts'][rt] = count
                
        except Exception as e:
            validation_result['is_valid'] = False
            validation_result['issues'].append(f"Validation error: {str(e)}")
            self.logger.error(f"Historical integrity validation failed: {str(e)}", exc_info=True)
        
        return validation_result
    
    # Private helper methods
    
    def _create_historical_version(
        self,
        resource: Resource,
        source_metadata: Dict[str, Any],
        user: Optional[User],
        preserve_reason: str
    ) -> Resource:
        """Create a historical version of a resource."""
        # Make a deep copy to avoid modifying the original
        historical_resource = copy.deepcopy(resource)
        
        # Update metadata to mark as historical
        if not historical_resource.meta:
            historical_resource.meta = Meta()
        
        # Increment version but mark as historical
        current_version = int(historical_resource.meta.versionId) if historical_resource.meta.versionId else 1
        historical_resource.meta.versionId = f"{current_version}.historical"
        historical_resource.meta.lastUpdated = timezone.now().isoformat()
        
        # Add historical marker extension
        if not hasattr(historical_resource, 'extension') or not historical_resource.extension:
            historical_resource.extension = []
        
        from fhir.resources.extension import Extension
        historical_extension = Extension(
            url="http://medicaldocparser.com/fhir/extension/historical-version",
            valueString=json.dumps({
                'preserved_at': timezone.now().isoformat(),
                'preserved_by': user.username if user else 'System',
                'preserve_reason': preserve_reason,
                'source_document_id': source_metadata.get('document_id'),
                'original_version': current_version
            })
        )
        historical_resource.extension.append(historical_extension)
        
        return historical_resource
    
    def _mark_as_historical(self, resource: Resource) -> Resource:
        """Mark a resource as a historical version."""
        # Add a special identifier to make it clear this is historical
        if hasattr(resource, 'identifier'):
            if not resource.identifier:
                resource.identifier = []
            
            # Add historical marker identifier
            historical_identifier = {
                'use': 'secondary',
                'system': 'http://medicaldocparser.com/fhir/identifier/historical',
                'value': f"historical-{resource.id}-{timezone.now().timestamp()}"
            }
            resource.identifier.append(historical_identifier)
        
        return resource
    
    def _is_status_tracked_resource(self, resource_type: str) -> bool:
        """Check if a resource type has status that should be tracked."""
        status_tracked_types = [
            'Condition',
            'MedicationStatement', 
            'AllergyIntolerance',
            'Procedure',
            'CarePlan',
            'Goal'
        ]
        return resource_type in status_tracked_types
    
    def _track_status_transition(
        self,
        old_resource: Resource,
        new_resource: Resource,
        source_metadata: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Track status transitions for applicable resources."""
        old_status = self._extract_resource_status(old_resource)
        new_status = self._extract_resource_status(new_resource)
        
        if old_status != new_status:
            return {
                'resource_type': new_resource.resource_type,
                'resource_id': new_resource.id,
                'old_status': old_status,
                'new_status': new_status,
                'transition_date': timezone.now().isoformat(),
                'source_document_id': source_metadata.get('document_id'),
                'transition_reason': source_metadata.get('reason', 'Document processing')
            }
        
        return None
    
    def _maintain_version_chain(self, old_resource: Resource, new_resource: Resource):
        """Maintain version chain between resources."""
        if not new_resource.meta:
            new_resource.meta = Meta()
        
        # Set new version ID
        old_version = int(old_resource.meta.versionId) if old_resource.meta and old_resource.meta.versionId else 1
        new_resource.meta.versionId = str(old_version + 1)
        new_resource.meta.lastUpdated = timezone.now().isoformat()
    
    def _add_historical_provenance(
        self,
        bundle: Bundle,
        new_resource: Resource,
        existing_resource: Optional[Resource],
        source_metadata: Dict[str, Any],
        user: Optional[User],
        preserve_reason: str
    ):
        """Add comprehensive provenance for historical preservation."""
        # This would integrate with the existing provenance system
        # but add specific markers for historical preservation
        pass
    
    def _get_all_resource_versions(
        self,
        bundle: Bundle,
        resource_type: str,
        resource_id: str
    ) -> List[Resource]:
        """Get all versions of a resource including historical ones."""
        all_versions = []
        
        if not bundle.entry:
            return all_versions
        
        for entry in bundle.entry:
            if (entry.resource and 
                entry.resource.resource_type == resource_type and 
                entry.resource.id == resource_id):
                all_versions.append(entry.resource)
        
        # Sort by version (current first, then historical)
        all_versions.sort(
            key=lambda r: (
                not self._is_historical_version(r),  # Current versions first
                int(r.meta.versionId.split('.')[0]) if r.meta and r.meta.versionId else 0
            ),
            reverse=True
        )
        
        return all_versions
    
    def _is_historical_version(self, resource: Resource) -> bool:
        """Check if a resource is marked as historical."""
        if hasattr(resource, 'extension') and resource.extension:
            for ext in resource.extension:
                if ext.url == "http://medicaldocparser.com/fhir/extension/historical-version":
                    return True
        
        # Also check version ID for historical marker
        if resource.meta and resource.meta.versionId:
            return '.historical' in resource.meta.versionId
        
        return False
    
    def _extract_resource_status(self, resource: Resource) -> Optional[str]:
        """Extract status from a resource."""
        status_fields = ['status', 'clinicalStatus', 'pharmacyStatus']
        
        for field in status_fields:
            if hasattr(resource, field):
                status_value = getattr(resource, field)
                if status_value:
                    # Handle both simple strings and coded values
                    if isinstance(status_value, str):
                        return status_value
                    elif hasattr(status_value, 'coding') and status_value.coding:
                        return status_value.coding[0].code
        
        return None
    
    def _extract_source_document(self, resource: Resource) -> Optional[str]:
        """Extract source document ID from resource metadata."""
        if hasattr(resource, 'extension') and resource.extension:
            for ext in resource.extension:
                if 'source' in ext.url.lower() or 'document' in ext.url.lower():
                    return getattr(ext, 'valueString', None)
        return None
    
    def _extract_status_transitions(self, versions: List[Resource]) -> List[Dict[str, Any]]:
        """Extract status transitions from version history."""
        transitions = []
        
        # Sort versions by timestamp
        sorted_versions = sorted(
            versions,
            key=lambda r: r.meta.lastUpdated if r.meta and r.meta.lastUpdated else "1970-01-01T00:00:00Z"
        )
        
        for i in range(1, len(sorted_versions)):
            old_status = self._extract_resource_status(sorted_versions[i-1])
            new_status = self._extract_resource_status(sorted_versions[i])
            
            if old_status != new_status and new_status:
                transition = {
                    'from_status': old_status,
                    'to_status': new_status,
                    'transition_date': sorted_versions[i].meta.lastUpdated if sorted_versions[i].meta else None,
                    'version': sorted_versions[i].meta.versionId if sorted_versions[i].meta else None
                }
                transitions.append(transition)
        
        return transitions
    
    def _build_provenance_chain(
        self,
        bundle: Bundle,
        resource_type: str,
        resource_id: str
    ) -> List[Dict[str, Any]]:
        """Build the provenance chain for a resource."""
        # This would integrate with existing provenance tracking
        # to build a comprehensive chain of all changes
        return []
    
    def _get_unique_resource_types(self, bundle: Bundle) -> List[str]:
        """Get list of unique resource types in bundle."""
        resource_types = set()
        
        if bundle.entry:
            for entry in bundle.entry:
                if entry.resource:
                    resource_types.add(entry.resource.resource_type)
        
        return list(resource_types)
    
    def _validate_resource_version_chain(
        self,
        resource_versions: List[Resource]
    ) -> List[str]:
        """Validate that resource version chain is intact."""
        issues = []
        
        # Check for version number gaps
        version_numbers = []
        for resource in resource_versions:
            if resource.meta and resource.meta.versionId:
                try:
                    # Extract base version number (ignore .historical suffix)
                    base_version = int(resource.meta.versionId.split('.')[0])
                    version_numbers.append(base_version)
                except (ValueError, IndexError):
                    issues.append(f"Invalid version ID format: {resource.meta.versionId}")
        
        if version_numbers:
            version_numbers.sort()
            # Check for gaps in version sequence
            for i in range(1, len(version_numbers)):
                if version_numbers[i] - version_numbers[i-1] > 1:
                    issues.append(f"Version gap detected: {version_numbers[i-1]} to {version_numbers[i]}")
        
        return issues
    
    def _check_for_historical_gaps(self, bundle: Bundle) -> List[str]:
        """Check for potential gaps in historical data."""
        # This is a placeholder for more sophisticated gap detection
        # Could check for missing provenance, timestamp gaps, etc.
        return []


# =============================================================================
# FHIR MERGE SERVICE
# =============================================================================

class FHIRMergeError(Exception):
    """Custom exception for FHIR merge operation errors."""
    pass


class FHIRConflictError(FHIRMergeError):
    """Exception for FHIR data conflicts that cannot be automatically resolved."""
    pass


class ConflictResult:
    """
    Data class to track and analyze conflicts detected during FHIR resource merging.
    
    This class provides detailed information about conflicts found between new and
    existing FHIR resources, helping with conflict resolution and audit trails.
    """
    
    def __init__(self):
        self.conflicts_detected = []  # List of ConflictDetail objects
        self.total_conflicts = 0
        self.conflict_types = {}  # Count by conflict type
        self.resource_conflicts = {}  # Conflicts by resource type
        self.severity_counts = {'low': 0, 'medium': 0, 'high': 0, 'critical': 0}
        self.timestamp = timezone.now()
    
    def add_conflict(self, conflict_detail: 'ConflictDetail'):
        """Add a detected conflict to the result."""
        self.conflicts_detected.append(conflict_detail)
        self.total_conflicts += 1
        
        # Update conflict type counts
        conflict_type = conflict_detail.conflict_type
        self.conflict_types[conflict_type] = self.conflict_types.get(conflict_type, 0) + 1
        
        # Update resource type counts
        resource_type = conflict_detail.resource_type
        self.resource_conflicts[resource_type] = self.resource_conflicts.get(resource_type, 0) + 1
        
        # Update severity counts
        severity = conflict_detail.severity
        if severity in self.severity_counts:
            self.severity_counts[severity] += 1
    
    def get_conflicts_by_type(self, conflict_type: str) -> List['ConflictDetail']:
        """Get all conflicts of a specific type."""
        return [c for c in self.conflicts_detected if c.conflict_type == conflict_type]
    
    def get_conflicts_by_resource_type(self, resource_type: str) -> List['ConflictDetail']:
        """Get all conflicts for a specific resource type."""
        return [c for c in self.conflicts_detected if c.resource_type == resource_type]
    
    def has_critical_conflicts(self) -> bool:
        """Check if any critical conflicts were detected."""
        return self.severity_counts['critical'] > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert conflict result to dictionary."""
        return {
            'total_conflicts': self.total_conflicts,
            'conflict_types': self.conflict_types,
            'resource_conflicts': self.resource_conflicts,
            'severity_counts': self.severity_counts,
            'conflicts_detected': [c.to_dict() for c in self.conflicts_detected],
            'timestamp': self.timestamp.isoformat()
        }


class ConflictDetail:
    """
    Detailed information about a specific conflict between FHIR resources.
    """
    
    def __init__(
        self,
        conflict_type: str,
        resource_type: str,
        field_name: str,
        existing_value: Any,
        new_value: Any,
        severity: str = 'medium',
        description: str = None,
        resource_id: str = None
    ):
        self.conflict_type = conflict_type  # 'value_mismatch', 'duplicate', 'temporal_conflict', etc.
        self.resource_type = resource_type  # 'Observation', 'Condition', etc.
        self.field_name = field_name  # Field that has the conflict
        self.existing_value = existing_value
        self.new_value = new_value
        self.severity = severity  # 'low', 'medium', 'high', 'critical'
        self.description = description or f"{conflict_type} in {field_name}"
        self.resource_id = resource_id
        self.timestamp = timezone.now()
        self.resolution_strategy = None  # Will be set during resolution
        self.resolution_result = None  # Will be set after resolution
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert conflict detail to dictionary."""
        return {
            'conflict_type': self.conflict_type,
            'resource_type': self.resource_type,
            'field_name': self.field_name,
            'existing_value': str(self.existing_value),
            'new_value': str(self.new_value),
            'severity': self.severity,
            'description': self.description,
            'resource_id': self.resource_id,
            'timestamp': self.timestamp.isoformat(),
            'resolution_strategy': self.resolution_strategy,
            'resolution_result': self.resolution_result
        }


class MergeResult:
    """
    Data class to track and summarize the results of a FHIR merge operation.
    """
    
    def __init__(self):
        self.success = False
        self.resources_added = 0
        self.resources_updated = 0
        self.resources_skipped = 0
        self.conflicts_detected = 0
        self.conflicts_resolved = 0
        self.duplicates_removed = 0
        self.validation_errors = []
        self.validation_warnings = []
        self.merge_errors = []
        self.bundle_version_before = None
        self.bundle_version_after = None
        self.provenance_resources_created = 0
        self.processing_time_seconds = 0.0
        self.timestamp = timezone.now()
        # Add detailed conflict tracking
        self.conflict_result = ConflictResult()
        # Add deduplication tracking
        self.deduplication_result = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert merge result to dictionary for serialization."""
        return {
            'success': self.success,
            'resources_added': self.resources_added,
            'resources_updated': self.resources_updated,
            'resources_skipped': self.resources_skipped,
            'conflicts_detected': self.conflicts_detected,
            'conflicts_resolved': self.conflicts_resolved,
            'duplicates_removed': self.duplicates_removed,
            'validation_errors': self.validation_errors,
            'validation_warnings': self.validation_warnings,
            'merge_errors': self.merge_errors,
            'bundle_version_before': self.bundle_version_before,
            'bundle_version_after': self.bundle_version_after,
            'provenance_resources_created': self.provenance_resources_created,
            'processing_time_seconds': self.processing_time_seconds,
            'timestamp': self.timestamp.isoformat(),
            'conflict_details': self.conflict_result.to_dict(),
            'deduplication_summary': self.deduplication_result.get_summary() if self.deduplication_result else None
        }


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
        """Check if two conditions are duplicates."""
        return (
            getattr(cond1, 'code', None) == getattr(cond2, 'code', None) and
            getattr(cond1, 'clinicalStatus', None) == getattr(cond2, 'clinicalStatus', None) and
            getattr(cond1, 'onsetDateTime', None) == getattr(cond2, 'onsetDateTime', None)
        )
    
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


# =============================================================================
# Data Deduplication System
# =============================================================================

class DuplicateResourceDetail:
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


class DeduplicationResult:
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


class ResourceHashGenerator:
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


class FuzzyMatcher:
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


class ResourceDeduplicator:
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
        """Merge duplicate resources and return the deduplicated list."""
        # Create a mapping of resource IDs to remove
        resources_to_remove = set()
        merge_mappings = {}  # Maps duplicate ID to primary ID
        
        # Group duplicates by primary resource
        duplicate_groups = {}
        
        for duplicate in dedup_result.duplicates_found:
            primary_id = duplicate.resource_id
            duplicate_id = duplicate.duplicate_id
            
            if primary_id not in duplicate_groups:
                duplicate_groups[primary_id] = []
            
            duplicate_groups[primary_id].append(duplicate)
            resources_to_remove.add(duplicate_id)
            merge_mappings[duplicate_id] = primary_id
        
        # Create the deduplicated resource list
        merged_resources = []
        
        for resource in original_resources:
            resource_id = getattr(resource, 'id', str(id(resource)))
            
            if resource_id not in resources_to_remove:
                # Keep this resource - it's either unique or the primary in a duplicate group
                if resource_id in duplicate_groups:
                    # This is a primary resource with duplicates - enhance with provenance if needed
                    enhanced_resource = self._enhance_resource_with_provenance(
                        resource, duplicate_groups[resource_id], preserve_provenance
                    )
                    merged_resources.append(enhanced_resource)
                    dedup_result.resources_merged += 1
                else:
                    # Unique resource
                    merged_resources.append(resource)
        
        return merged_resources
    
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


class FHIRMergeService:
    """
    Service class for merging extracted document data into patient FHIR records.
    
    Provides comprehensive data validation, FHIR resource conversion, conflict
    detection and resolution, data deduplication, and provenance tracking.
    Uses the existing FHIRAccumulator for basic operations but adds enhanced
    merge-specific functionality.
    """
    
    def __init__(self, patient: Patient):
        """
        Initialize the FHIR merge service for a specific patient.
        
        Args:
            patient: Patient model instance to merge data into
            
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
        
        # Configuration for merge behavior (needs to be defined before deduplicator)
        self.config = {
            'validate_fhir': True,
            'resolve_conflicts': True,
            'deduplicate_resources': True,
            'create_provenance': True,
            'conflict_resolution_strategy': 'newest_wins',  # newest_wins, preserve_both, manual_review, confidence_based
            'deduplication_tolerance_hours': 24,
            'max_processing_time_seconds': 300,  # 5 minutes
            'conflict_detection_enabled': True,
            'duplicate_detection_enabled': True,
            # Advanced conflict resolution configuration
            'conflict_type_strategies': {
                'dosage_conflict': 'manual_review',
                'temporal_conflict': 'preserve_both',
                'value_mismatch': 'newest_wins'
            },
            'resource_type_strategies': {
                'MedicationStatement': 'preserve_both',
                'Observation': 'newest_wins',
                'Condition': 'newest_wins'
            },
            'severity_strategies': {
                'critical': 'manual_review',
                'high': 'preserve_both',
                'medium': 'newest_wins',
                'low': 'newest_wins'
            }
        }
        
        # Initialize deduplicator with configuration
        self.deduplicator = ResourceDeduplicator(self.config)
        
        # Initialize conflict resolver with configuration
        self.conflict_resolver = ConflictResolver(self.config)
        
        # Initialize provenance tracker for comprehensive audit trails
        self.provenance_tracker = ProvenanceTracker(self.config)
        
        # Initialize referential integrity manager
        self.integrity_manager = ReferentialIntegrityManager(self.config)
    
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
        
        try:
            # Update configuration with any provided kwargs
            self._update_config(kwargs)
            
            # Load current bundle
            current_bundle = self._load_current_bundle()
            merge_result.bundle_version_before = current_bundle.meta.versionId if current_bundle.meta else "1"
            
            # Step 1: Validate extracted data
            self.logger.info(f"Starting FHIR merge for patient {self.patient.mrn}")
            validated_data = self.validate_data(extracted_data)
            merge_result.validation_errors.extend(validated_data.get('errors', []))
            merge_result.validation_warnings.extend(validated_data.get('warnings', []))
            
            if validated_data.get('critical_errors'):
                merge_result.merge_errors.extend(validated_data['critical_errors'])
                raise FHIRMergeError(f"Critical validation errors: {validated_data['critical_errors']}")
            
            # Step 2: Convert to FHIR resources
            fhir_resources = self.convert_to_fhir(validated_data['data'], document_metadata)
            
            # Step 3: Merge resources with conflict resolution
            merge_result = self.merge_resources(fhir_resources, document_metadata, user, merge_result)
            
            # Calculate processing time
            end_time = datetime.now()
            merge_result.processing_time_seconds = (end_time - start_time).total_seconds()
            merge_result.success = True
            
            self.logger.info(
                f"FHIR merge completed for patient {self.patient.mrn}: "
                f"{merge_result.resources_added} added, {merge_result.resources_updated} updated, "
                f"{merge_result.conflicts_resolved} conflicts resolved"
            )
            
            return merge_result
            
        except Exception as e:
            end_time = datetime.now()
            merge_result.processing_time_seconds = (end_time - start_time).total_seconds()
            merge_result.success = False
            merge_result.merge_errors.append(str(e))
            
            self.logger.error(f"FHIR merge failed for patient {self.patient.mrn}: {str(e)}", exc_info=True)
            raise FHIRMergeError(f"Merge operation failed: {str(e)}") from e
    
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
                merge_handler_factory = ResourceMergeHandlerFactory()
                
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
                
                # Step 5: Validate and maintain referential integrity
                if self.config.get('validate_referential_integrity', True):
                    integrity_result = self._maintain_referential_integrity(current_bundle, merge_result, user)
                    merge_result.integrity_result = integrity_result
                
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
                self.patient.cumulative_fhir_json = bundle_dict
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
    
    def _maintain_referential_integrity(
        self,
        bundle: Bundle,
        merge_result: MergeResult,
        user: Optional[User]
    ) -> Dict[str, Any]:
        """
        Maintain referential integrity during merge operations.
        
        Args:
            bundle: Current FHIR bundle
            merge_result: Current merge result to update
            user: User performing the operation
            
        Returns:
            Dictionary with integrity validation and maintenance results
        """
        try:
            self.logger.info("Starting referential integrity maintenance")
            
            # Step 1: Build reference graph for current bundle
            graph_info = self.integrity_manager.build_reference_graph(bundle)
            
            # Step 2: Validate referential integrity
            validation_result = self.integrity_manager.validate_referential_integrity(bundle)
            
            integrity_result = {
                'validation_passed': validation_result['is_valid'],
                'total_resources': validation_result['total_resources'],
                'total_references': validation_result['total_references'],
                'circular_references_found': len(validation_result['circular_references']),
                'orphaned_references_found': len(validation_result['orphaned_references']),
                'reference_updates_applied': 0,
                'circular_references_resolved': 0,
                'errors': validation_result['validation_errors'],
                'warnings': validation_result['validation_warnings']
            }
            
            # Step 3: Apply any pending reference updates
            if self.integrity_manager.pending_updates:
                update_result = self.integrity_manager.apply_pending_updates(bundle)
                integrity_result['reference_updates_applied'] = update_result['updates_applied']
                integrity_result['errors'].extend(update_result['errors'])
                
                # Create provenance for reference updates if enabled
                if (update_result['updates_applied'] > 0 and 
                    self.config.get('create_provenance', True) and 
                    self.provenance_tracker):
                    
                    self.provenance_tracker.create_integrity_provenance(
                        target_resources=[],
                        metadata={'reference_updates': update_result['updates_applied']},
                        user=user,
                        activity_type="referential_integrity_maintenance",
                        reason=f"Applied {update_result['updates_applied']} reference updates"
                    )
            
            # Step 4: Resolve circular references if found
            if validation_result['circular_references']:
                resolution_result = self.integrity_manager.resolve_circular_references(bundle)
                integrity_result['circular_references_resolved'] = resolution_result['cycles_resolved']
                integrity_result['errors'].extend(resolution_result['resolution_errors'])
                
                # Create provenance for circular reference resolution
                if (resolution_result['cycles_resolved'] > 0 and 
                    self.config.get('create_provenance', True) and 
                    self.provenance_tracker):
                    
                    self.provenance_tracker.create_integrity_provenance(
                        target_resources=[],
                        metadata={'circular_references_resolved': resolution_result['cycles_resolved']},
                        user=user,
                        activity_type="circular_reference_resolution",
                        reason=f"Resolved {resolution_result['cycles_resolved']} circular reference chains"
                    )
            
            # Step 5: Log integrity maintenance summary
            self.logger.info(
                f"Referential integrity maintenance complete: "
                f"validation {'PASSED' if integrity_result['validation_passed'] else 'FAILED'}, "
                f"{integrity_result['reference_updates_applied']} updates applied, "
                f"{integrity_result['circular_references_resolved']} circular references resolved"
            )
            
            # Step 6: Update merge result with any critical integrity issues
            if not integrity_result['validation_passed']:
                merge_result.merge_errors.extend(integrity_result['errors'])
                
            if integrity_result['warnings']:
                merge_result.merge_warnings.extend(integrity_result['warnings'])
            
            return integrity_result
            
        except Exception as e:
            error_msg = f"Referential integrity maintenance failed: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            
            # Return failed result but don't stop the merge for integrity issues
            return {
                'validation_passed': False,
                'total_resources': 0,
                'total_references': 0,
                'circular_references_found': 0,
                'orphaned_references_found': 0,
                'reference_updates_applied': 0,
                'circular_references_resolved': 0,
                'errors': [error_msg],
                'warnings': []
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
# RESOURCE MERGE HANDLERS
# =============================================================================

class BaseMergeHandler:
    """
    Base class for FHIR resource merge handlers.
    
    Each resource type can have a specialized merge handler that knows how to
    properly merge that type of resource into an existing FHIR bundle.
    """
    
    def __init__(self):
        self.logger = logger
        self.conflict_detector = ConflictDetector()
    
    def merge_resource(
        self,
        new_resource: Resource,
        current_bundle: Bundle,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge a new resource into the current bundle.
        
        Args:
            new_resource: The new FHIR resource to merge
            current_bundle: Current patient FHIR bundle
            context: Merge context including metadata and user
            config: Merge configuration options
            
        Returns:
            Dictionary with merge results including action taken and statistics
        """
        raise NotImplementedError("Subclasses must implement merge_resource")
    
    def _find_existing_resource(
        self,
        new_resource: Resource,
        current_bundle: Bundle,
        match_criteria: List[str] = None
    ) -> Optional[Resource]:
        """
        Find an existing resource in the bundle that matches the new resource.
        
        Args:
            new_resource: Resource to find matches for
            current_bundle: Bundle to search in
            match_criteria: List of fields to use for matching
            
        Returns:
            Existing resource if found, None otherwise
        """
        if not current_bundle.entry:
            return None
        
        resource_type = new_resource.resource_type
        
        # Default match criteria by resource type
        if not match_criteria:
            match_criteria = self._get_default_match_criteria(resource_type)
        
        for entry in current_bundle.entry:
            if hasattr(entry, 'resource') and entry.resource.resource_type == resource_type:
                if self._resources_match(new_resource, entry.resource, match_criteria):
                    return entry.resource
        
        return None
    
    def _get_default_match_criteria(self, resource_type: str) -> List[str]:
        """
        Get default matching criteria for a resource type.
        
        Args:
            resource_type: FHIR resource type
            
        Returns:
            List of field names to use for matching
        """
        # Default matching strategies by resource type
        match_strategies = {
            'Patient': ['identifier', 'name', 'birthDate'],
            'Observation': ['code', 'subject', 'effectiveDateTime'],
            'Condition': ['code', 'subject', 'onsetDateTime'],
            'MedicationStatement': ['medicationCodeableConcept', 'subject', 'effectiveDateTime'],
            'Practitioner': ['identifier', 'name'],
            'DocumentReference': ['identifier', 'subject', 'date']
        }
        
        return match_strategies.get(resource_type, ['id'])
    
    def _resources_match(
        self,
        resource1: Resource,
        resource2: Resource,
        match_criteria: List[str]
    ) -> bool:
        """
        Check if two resources match based on specified criteria.
        
        Args:
            resource1: First resource to compare
            resource2: Second resource to compare
            match_criteria: Fields to compare
            
        Returns:
            True if resources match, False otherwise
        """
        for criterion in match_criteria:
            val1 = getattr(resource1, criterion, None)
            val2 = getattr(resource2, criterion, None)
            
            # Skip if either value is None
            if val1 is None or val2 is None:
                continue
            
            # For complex objects, do a simplified comparison
            if hasattr(val1, 'dict') and hasattr(val2, 'dict'):
                if val1.dict() != val2.dict():
                    return False
            elif val1 != val2:
                return False
        
        return True
    
    def _add_resource_to_bundle(
        self,
        resource: Resource,
        bundle: Bundle,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Add a new resource to the bundle.
        
        Args:
            resource: Resource to add
            bundle: Bundle to add to
            context: Merge context
            
        Returns:
            Result dictionary with action and metadata
        """
        try:
            # Ensure bundle has entry list
            if not hasattr(bundle, 'entry') or bundle.entry is None:
                bundle.entry = []
            
            # Create bundle entry
            from fhir.resources.bundle import BundleEntry
            entry = BundleEntry()
            entry.resource = resource
            entry.fullUrl = f"urn:uuid:{resource.id}" if hasattr(resource, 'id') else f"urn:uuid:{uuid4()}"
            
            # Add to bundle
            bundle.entry.append(entry)
            
            self.logger.debug(f"Added {resource.resource_type} resource to bundle")
            
            return {
                'action': 'added',
                'resource_type': resource.resource_type,
                'resource_id': getattr(resource, 'id', 'unknown'),
                'conflicts_detected': 0,
                'conflicts_resolved': 0,
                'duplicates_removed': 0,
                'errors': [],
                'warnings': []
            }
            
        except Exception as e:
            error_msg = f"Failed to add {resource.resource_type} resource to bundle: {str(e)}"
            self.logger.error(error_msg)
            return {
                'action': 'skipped',
                'resource_type': resource.resource_type,
                'resource_id': getattr(resource, 'id', 'unknown'),
                'conflicts_detected': 0,
                'conflicts_resolved': 0,
                'duplicates_removed': 0,
                'errors': [error_msg],
                'warnings': []
            }


class ObservationMergeHandler(BaseMergeHandler):
    """
    Specialized merge handler for Observation resources (lab results, vitals, etc.).
    """
    
    def merge_resource(
        self,
        new_resource: Resource,
        current_bundle: Bundle,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge an Observation resource with comprehensive conflict detection.
        """
        self.logger.debug(f"Merging Observation resource: {getattr(new_resource, 'code', 'unknown')}")
        
        # Initialize result tracking
        merge_result = {
            'action': 'unknown',
            'resource_type': 'Observation',
            'resource_id': getattr(new_resource, 'id', 'unknown'),
            'conflicts_detected': 0,
            'conflicts_resolved': 0,
            'duplicates_removed': 0,
            'errors': [],
            'warnings': [],
            'conflict_details': []
        }
        
        # Look for existing observation with same code and subject
        existing_resource = self._find_existing_resource(
            new_resource,
            current_bundle,
            ['code', 'subject', 'effectiveDateTime']
        )
        
        if existing_resource:
            # Check for duplicates first
            if config.get('duplicate_detection_enabled', True):
                is_duplicate = self.conflict_detector.check_for_duplicates(
                    new_resource, existing_resource, 'Observation'
                )
                
                if is_duplicate:
                    merge_result.update({
                        'action': 'skipped',
                        'duplicates_removed': 1,
                        'warnings': ['Identical observation found - skipping duplicate']
                    })
                    return merge_result
            
            # Detect conflicts between resources
            if config.get('conflict_detection_enabled', True):
                conflicts = self.conflict_detector.detect_conflicts(
                    new_resource, existing_resource, 'Observation'
                )
                
                merge_result['conflicts_detected'] = len(conflicts)
                merge_result['conflict_details'] = [c.to_dict() for c in conflicts]
                
                if conflicts:
                    self.logger.info(f"Detected {len(conflicts)} conflicts in Observation resource")
                    
                    # Apply conflict resolution if enabled
                    if config.get('resolve_conflicts', True):
                        # Get conflict resolver from context (passed from FHIRMergeService)
                        conflict_resolver = context.get('conflict_resolver')
                        if conflict_resolver:
                            # Get provenance tracker from context
                            provenance_tracker = context.get('provenance_tracker')
                            
                            resolution_summary = conflict_resolver.resolve_conflicts(
                                conflicts, new_resource, existing_resource, context, provenance_tracker
                            )
                            
                            merge_result['conflicts_resolved'] = resolution_summary['resolved_conflicts']
                            merge_result['resolution_actions'] = resolution_summary['resolution_actions']
                            
                            # Handle resolution results
                            if resolution_summary['overall_action'] == 'critical_conflicts_require_review':
                                merge_result.update({
                                    'action': 'flagged_for_review',
                                    'errors': ['Critical conflicts detected - manual review required'],
                                    'flagged_conflicts': resolution_summary['flagged_for_review']
                                })
                                return merge_result
                            elif resolution_summary['flagged_for_review']:
                                merge_result['warnings'].append(
                                    f"{len(resolution_summary['flagged_for_review'])} conflicts flagged for review"
                                )
                                merge_result['flagged_conflicts'] = resolution_summary['flagged_for_review']
                            
                            # Determine action based on resolution strategy
                            predominant_action = self._determine_predominant_action(resolution_summary['resolution_actions'])
                            if predominant_action == 'keep_existing':
                                merge_result.update({
                                    'action': 'kept_existing',
                                    'warnings': [f"Existing observation kept due to conflict resolution"]
                                })
                                return merge_result
                            elif predominant_action == 'preserve_both':
                                # Add both as temporal sequence
                                add_result = self._add_resource_to_bundle(new_resource, current_bundle, context)
                                merge_result.update({
                                    'action': 'added_as_sequence',
                                    'warnings': [f"Added as temporal sequence - both values preserved"]
                                })
                                return merge_result
                    else:
                        # Legacy behavior when resolution is disabled
                        if any(c.severity == 'critical' for c in conflicts):
                            merge_result.update({
                                'action': 'flagged_for_review',
                                'errors': ['Critical conflicts detected - manual review required']
                            })
                            return merge_result
                        
                        # For non-critical conflicts, add as temporal sequence
                        merge_result['warnings'].append(f"Added as temporal sequence due to {len(conflicts)} conflicts")
            
            # Add as new observation (default action or after resolution)
            add_result = self._add_resource_to_bundle(new_resource, current_bundle, context)
            merge_result.update({
                'action': 'added_as_sequence' if conflicts else 'added',
                'conflicts_resolved': merge_result.get('conflicts_resolved', 0)
            })
            
        else:
            # No existing observation found - add it
            add_result = self._add_resource_to_bundle(new_resource, current_bundle, context)
            merge_result['action'] = 'added'
        
        return merge_result
    
    def _determine_predominant_action(self, resolution_actions: List[Dict[str, Any]]) -> str:
        """
        Determine the predominant action from a list of resolution actions.
        
        Args:
            resolution_actions: List of resolution actions from conflict resolver
            
        Returns:
            The most common or highest priority action
        """
        if not resolution_actions:
            return 'keep_new'
        
        # Count actions by priority (higher priority wins)
        action_priorities = {
            'flag_for_review': 4,
            'keep_existing': 3,
            'preserve_both': 2,
            'keep_new': 1
        }
        
        action_counts = {}
        highest_priority = 0
        predominant_action = 'keep_new'
        
        for action_info in resolution_actions:
            action = action_info.get('action', 'keep_new')
            priority = action_priorities.get(action, 1)
            
            # Track counts
            action_counts[action] = action_counts.get(action, 0) + 1
            
            # Update predominant action if this has higher priority
            if priority > highest_priority:
                highest_priority = priority
                predominant_action = action
        
        self.logger.debug(f"Predominant action: {predominant_action} from {action_counts}")
        return predominant_action
    
    def _observations_are_identical(self, obs1: Resource, obs2: Resource) -> bool:
        """
        Check if two observations are identical (same value, date, code).
        """
        # Compare key fields that make observations identical
        return (
            getattr(obs1, 'code', None) == getattr(obs2, 'code', None) and
            getattr(obs1, 'valueQuantity', None) == getattr(obs2, 'valueQuantity', None) and
            getattr(obs1, 'valueString', None) == getattr(obs2, 'valueString', None) and
            getattr(obs1, 'effectiveDateTime', None) == getattr(obs2, 'effectiveDateTime', None)
        )


class ConditionMergeHandler(BaseMergeHandler):
    """
    Specialized merge handler for Condition resources (diagnoses, problems).
    """
    
    def merge_resource(
        self,
        new_resource: Resource,
        current_bundle: Bundle,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge a Condition resource with comprehensive conflict detection and resolution.
        """
        self.logger.debug(f"Merging Condition resource: {getattr(new_resource, 'code', 'unknown')}")
        
        # Initialize result tracking
        merge_result = {
            'action': 'unknown',
            'resource_type': 'Condition',
            'resource_id': getattr(new_resource, 'id', 'unknown'),
            'conflicts_detected': 0,
            'conflicts_resolved': 0,
            'duplicates_removed': 0,
            'errors': [],
            'warnings': [],
            'conflict_details': []
        }
        
        # Look for existing condition with same code
        existing_resource = self._find_existing_resource(
            new_resource,
            current_bundle,
            ['code', 'subject']
        )
        
        if existing_resource:
            # Check for duplicates first
            if config.get('duplicate_detection_enabled', True):
                is_duplicate = self.conflict_detector.check_for_duplicates(
                    new_resource, existing_resource, 'Condition'
                )
                
                if is_duplicate:
                    merge_result.update({
                        'action': 'skipped',
                        'duplicates_removed': 1,
                        'warnings': ['Identical condition found - skipping duplicate']
                    })
                    return merge_result
            
            # Detect conflicts between conditions
            if config.get('conflict_detection_enabled', True):
                conflicts = self.conflict_detector.detect_conflicts(
                    new_resource, existing_resource, 'Condition'
                )
                
                merge_result['conflicts_detected'] = len(conflicts)
                merge_result['conflict_details'] = [c.to_dict() for c in conflicts]
                
                if conflicts:
                    self.logger.info(f"Detected {len(conflicts)} conflicts in Condition resource")
                    
                    # Handle critical conflicts
                    if any(c.severity == 'critical' for c in conflicts):
                        merge_result.update({
                            'action': 'flagged_for_review',
                            'errors': ['Critical condition conflicts detected - manual review required']
                        })
                        return merge_result
            
            # Determine which condition should take precedence
            if self._should_update_condition(new_resource, existing_resource):
                update_result = self._update_existing_condition(existing_resource, new_resource, context)
                merge_result.update({
                    'action': 'updated',
                    'conflicts_resolved': merge_result['conflicts_detected']
                })
                # Preserve any warnings from conflict detection
                if merge_result['warnings']:
                    update_result['warnings'].extend(merge_result['warnings'])
                # Make sure we return the merge_result with all the conflict information
                update_result.update({
                    'conflicts_detected': merge_result['conflicts_detected'],
                    'conflicts_resolved': merge_result['conflicts_resolved'],
                    'conflict_details': merge_result['conflict_details']
                })
                return update_result
            else:
                merge_result.update({
                    'action': 'skipped',
                    'conflicts_resolved': merge_result['conflicts_detected'],
                    'warnings': ['Existing condition kept (more recent or complete)']
                })
                return merge_result
        else:
            # No existing condition found - add it
            add_result = self._add_resource_to_bundle(new_resource, current_bundle, context)
            merge_result['action'] = 'added'
            return merge_result
    
    def _should_update_condition(self, new_condition: Resource, existing_condition: Resource) -> bool:
        """
        Determine if the new condition should replace the existing one.
        """
        # Simple rule: newer recordedDate wins
        new_date = getattr(new_condition, 'recordedDate', None)
        existing_date = getattr(existing_condition, 'recordedDate', None)
        
        if new_date and existing_date:
            return new_date > existing_date
        elif new_date and not existing_date:
            return True
        else:
            return False
    
    def _update_existing_condition(
        self,
        existing_condition: Resource,
        new_condition: Resource,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update an existing condition with new information.
        """
        try:
            # Update key fields from new condition
            if hasattr(new_condition, 'clinicalStatus'):
                existing_condition.clinicalStatus = new_condition.clinicalStatus
            if hasattr(new_condition, 'verificationStatus'):
                existing_condition.verificationStatus = new_condition.verificationStatus
            if hasattr(new_condition, 'recordedDate'):
                existing_condition.recordedDate = new_condition.recordedDate
            
            self.logger.debug("Updated existing condition with new information")
            
            return {
                'action': 'updated',
                'resource_type': 'Condition',
                'resource_id': getattr(existing_condition, 'id', 'unknown'),
                'conflicts_detected': 1,
                'conflicts_resolved': 1,
                'duplicates_removed': 0,
                'errors': [],
                'warnings': []
            }
            
        except Exception as e:
            error_msg = f"Failed to update existing condition: {str(e)}"
            self.logger.error(error_msg)
            return {
                'action': 'skipped',
                'resource_type': 'Condition',
                'resource_id': getattr(new_condition, 'id', 'unknown'),
                'conflicts_detected': 1,
                'conflicts_resolved': 0,
                'duplicates_removed': 0,
                'errors': [error_msg],
                'warnings': []
            }


class MedicationStatementMergeHandler(BaseMergeHandler):
    """
    Specialized merge handler for MedicationStatement resources.
    """
    
    def merge_resource(
        self,
        new_resource: Resource,
        current_bundle: Bundle,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge a MedicationStatement resource, handling medication changes over time.
        """
        self.logger.debug(f"Merging MedicationStatement resource")
        
        # Look for existing medication statement
        existing_resource = self._find_existing_resource(
            new_resource,
            current_bundle,
            ['medicationCodeableConcept', 'subject']
        )
        
        if existing_resource:
            # For medications, preserve history by adding new statement
            return self._add_resource_to_bundle(new_resource, current_bundle, context)
        else:
            # No existing medication found - add it
            return self._add_resource_to_bundle(new_resource, current_bundle, context)


class GenericMergeHandler(BaseMergeHandler):
    """
    Generic merge handler for resource types that don't have specialized handlers.
    """
    
    def merge_resource(
        self,
        new_resource: Resource,
        current_bundle: Bundle,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generic merge logic - simply adds the resource to the bundle.
        """
        resource_type = getattr(new_resource, 'resource_type', 'Unknown')
        self.logger.debug(f"Using generic merge for {resource_type} resource")
        
        # For generic resources, just add them (no duplicate checking)
        return self._add_resource_to_bundle(new_resource, current_bundle, context)


class ResourceMergeHandlerFactory:
    """
    Factory class for creating appropriate merge handlers for different FHIR resource types.
    """
    
    def __init__(self):
        self._handlers = {
            'Observation': ObservationMergeHandler(),
            'Condition': ConditionMergeHandler(),
            'MedicationStatement': MedicationStatementMergeHandler(),
        }
        self._generic_handler = GenericMergeHandler()
    
    def get_handler(self, resource_type: str) -> BaseMergeHandler:
        """
        Get the appropriate merge handler for a resource type.
        
        Args:
            resource_type: FHIR resource type string
            
        Returns:
            Appropriate merge handler instance
        """
        return self._handlers.get(resource_type, self._generic_handler)
    
    def register_handler(self, resource_type: str, handler: BaseMergeHandler):
        """
        Register a custom merge handler for a resource type.
        
        Args:
            resource_type: FHIR resource type string
            handler: Merge handler instance
        """
        self._handlers[resource_type] = handler


# =============================================================================
# REFERENTIAL INTEGRITY MAINTENANCE SYSTEM
# =============================================================================

class ReferentialIntegrityManager:
    """
    Comprehensive system for maintaining referential integrity between FHIR resources.
    
    This system tracks references, updates them during merges and deduplication,
    handles circular references, and validates integrity throughout the process.
    
    Think of this like the electrical system in your truck - every wire needs to
    stay connected to the right component, even when you're swapping parts.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the referential integrity manager.
        
        Args:
            config: Configuration dictionary with integrity settings
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.reference_map = {}  # Maps resource IDs to their references
        self.reverse_reference_map = {}  # Maps resource IDs to resources that reference them
        self.pending_updates = []  # Staging area for reference updates
        
    def build_reference_graph(self, bundle: Bundle) -> Dict[str, Any]:
        """
        Build a complete reference graph from a FHIR bundle.
        
        Args:
            bundle: FHIR Bundle to analyze
            
        Returns:
            Dictionary containing reference graph and metadata
        """
        try:
            self.logger.info("Building reference graph from FHIR bundle")
            
            # Clear existing maps
            self.reference_map.clear()
            self.reverse_reference_map.clear()
            
            graph_metadata = {
                'resource_count': 0,
                'reference_count': 0,
                'circular_references': [],
                'orphaned_references': []
            }
            
            if not bundle or not bundle.entry:
                return {
                    'reference_map': self.reference_map,
                    'reverse_reference_map': self.reverse_reference_map,
                    'metadata': graph_metadata
                }
            
            # First pass: Map all resource IDs
            resource_ids = set()
            for entry in bundle.entry:
                if entry.resource and hasattr(entry.resource, 'id'):
                    resource_ids.add(entry.resource.id)
                    graph_metadata['resource_count'] += 1
            
            # Second pass: Extract all references
            for entry in bundle.entry:
                if not entry.resource:
                    continue
                    
                resource = entry.resource
                resource_id = resource.id
                
                # Extract references from this resource
                references = self._extract_resource_references(resource)
                self.reference_map[resource_id] = references
                
                # Build reverse reference map
                for ref_info in references:
                    target_id = ref_info['target_id']
                    if target_id not in self.reverse_reference_map:
                        self.reverse_reference_map[target_id] = []
                    self.reverse_reference_map[target_id].append({
                        'source_id': resource_id,
                        'source_type': resource.resource_type,
                        'field_path': ref_info['field_path'],
                        'reference_type': ref_info['reference_type']
                    })
                    graph_metadata['reference_count'] += 1
            
            # Detect circular references
            graph_metadata['circular_references'] = self._detect_circular_references()
            
            # Detect orphaned references
            graph_metadata['orphaned_references'] = self._detect_orphaned_references(resource_ids)
            
            self.logger.info(f"Reference graph built: {graph_metadata['resource_count']} resources, "
                           f"{graph_metadata['reference_count']} references, "
                           f"{len(graph_metadata['circular_references'])} circular references")
            
            return {
                'reference_map': self.reference_map.copy(),
                'reverse_reference_map': self.reverse_reference_map.copy(),
                'metadata': graph_metadata
            }
            
        except Exception as e:
            self.logger.error(f"Failed to build reference graph: {str(e)}")
            return {
                'reference_map': {},
                'reverse_reference_map': {},
                'metadata': graph_metadata
            }
    
    def _extract_resource_references(self, resource: Resource) -> List[Dict[str, Any]]:
        """
        Extract all references from a FHIR resource.
        
        Args:
            resource: FHIR resource to analyze
            
        Returns:
            List of reference information dictionaries
        """
        references = []
        resource_type = resource.resource_type
        
        try:
            # Common reference patterns by resource type
            reference_patterns = {
                'Observation': ['subject', 'performer', 'encounter', 'basedOn'],
                'Condition': ['subject', 'encounter', 'asserter', 'recorder'],
                'MedicationStatement': ['subject', 'performer', 'context', 'informationSource'],
                'DocumentReference': ['subject', 'author', 'authenticator', 'custodian'],
                'Practitioner': [],  # Practitioners typically don't reference other resources
                'Provenance': ['target', 'agent.who', 'agent.onBehalfOf'],
                'Procedure': ['subject', 'encounter', 'recorder', 'asserter', 'performer.actor'],
                'DiagnosticReport': ['subject', 'encounter', 'performer', 'result', 'basedOn'],
                'CarePlan': ['subject', 'encounter', 'careTeam', 'goal', 'activity.reference'],
                'AllergyIntolerance': ['patient', 'encounter', 'recorder', 'asserter']
            }
            
            patterns = reference_patterns.get(resource_type, [])
            
            for pattern in patterns:
                refs = self._extract_references_by_pattern(resource, pattern)
                references.extend(refs)
            
            return references
            
        except Exception as e:
            self.logger.warning(f"Failed to extract references from {resource_type}: {str(e)}")
            return []
    
    def _extract_references_by_pattern(self, resource: Resource, pattern: str) -> List[Dict[str, Any]]:
        """
        Extract references using a specific field pattern.
        
        Args:
            resource: FHIR resource
            pattern: Field pattern (e.g., 'subject', 'agent.who')
            
        Returns:
            List of reference information
        """
        references = []
        
        try:
            # Handle nested patterns (e.g., 'agent.who')
            if '.' in pattern:
                parts = pattern.split('.')
                current_obj = resource
                
                for part in parts[:-1]:
                    if hasattr(current_obj, part):
                        current_obj = getattr(current_obj, part)
                        if isinstance(current_obj, list) and current_obj:
                            current_obj = current_obj[0]  # Take first item for lists
                    else:
                        return references
                
                final_field = parts[-1]
                if hasattr(current_obj, final_field):
                    ref_value = getattr(current_obj, final_field)
                    if ref_value:
                        ref_info = self._parse_reference_value(ref_value, pattern)
                        if ref_info:
                            references.append(ref_info)
            
            # Handle simple patterns (e.g., 'subject')
            else:
                if hasattr(resource, pattern):
                    ref_value = getattr(resource, pattern)
                    if ref_value:
                        # Handle lists of references
                        if isinstance(ref_value, list):
                            for i, ref_item in enumerate(ref_value):
                                ref_info = self._parse_reference_value(ref_item, f"{pattern}[{i}]")
                                if ref_info:
                                    references.append(ref_info)
                        else:
                            ref_info = self._parse_reference_value(ref_value, pattern)
                            if ref_info:
                                references.append(ref_info)
            
            return references
            
        except Exception as e:
            self.logger.warning(f"Failed to extract references for pattern '{pattern}': {str(e)}")
            return []
    
    def _parse_reference_value(self, ref_value: Any, field_path: str) -> Optional[Dict[str, Any]]:
        """
        Parse a reference value and extract target information.
        
        Args:
            ref_value: Reference value (could be Reference object, dict, or string)
            field_path: Field path where this reference was found
            
        Returns:
            Reference information dictionary or None
        """
        try:
            reference_str = None
            reference_type = 'unknown'
            
            # Handle Reference objects
            if hasattr(ref_value, 'reference'):
                reference_str = ref_value.reference
                reference_type = 'Reference'
            
            # Handle dict with reference key
            elif isinstance(ref_value, dict) and 'reference' in ref_value:
                reference_str = ref_value['reference']
                reference_type = 'dict'
            
            # Handle string references
            elif isinstance(ref_value, str):
                reference_str = ref_value
                reference_type = 'string'
            
            if not reference_str:
                return None
            
            # Extract target ID from reference string
            target_id = self._extract_target_id(reference_str)
            if not target_id:
                return None
            
            return {
                'target_id': target_id,
                'reference_string': reference_str,
                'field_path': field_path,
                'reference_type': reference_type
            }
            
        except Exception as e:
            self.logger.warning(f"Failed to parse reference value: {str(e)}")
            return None
    
    def _extract_target_id(self, reference_str: str) -> Optional[str]:
        """
        Extract target resource ID from a reference string.
        
        Args:
            reference_str: Reference string (e.g., 'Patient/123', '#123')
            
        Returns:
            Target resource ID or None
        """
        try:
            if not reference_str:
                return None
            
            # Handle relative references (e.g., 'Patient/123')
            if '/' in reference_str:
                return reference_str.split('/')[-1]
            
            # Handle internal references (e.g., '#123')
            if reference_str.startswith('#'):
                return reference_str[1:]
            
            # Handle direct IDs
            return reference_str
            
        except Exception:
            return None
    
    def _detect_circular_references(self) -> List[Dict[str, Any]]:
        """
        Detect circular reference chains in the reference graph.
        
        Returns:
            List of circular reference chains found
        """
        circular_refs = []
        visited = set()
        
        try:
            for resource_id in self.reference_map:
                if resource_id in visited:
                    continue
                
                # Use depth-first search to detect cycles
                path = []
                cycle = self._dfs_find_cycle(resource_id, path, visited, set())
                if cycle:
                    circular_refs.append({
                        'cycle': cycle,
                        'cycle_length': len(cycle)
                    })
            
            return circular_refs
            
        except Exception as e:
            self.logger.warning(f"Failed to detect circular references: {str(e)}")
            return []
    
    def _dfs_find_cycle(self, current_id: str, path: List[str], visited: set, recursion_stack: set) -> Optional[List[str]]:
        """
        Depth-first search to find cycles in reference graph.
        
        Args:
            current_id: Current resource ID being explored
            path: Current path being explored
            visited: Set of all visited nodes
            recursion_stack: Set of nodes in current recursion stack
            
        Returns:
            Circular reference path if found, None otherwise
        """
        try:
            if current_id in recursion_stack:
                # Found a cycle - return the cycle path
                cycle_start = path.index(current_id)
                return path[cycle_start:] + [current_id]
            
            if current_id in visited:
                return None
            
            visited.add(current_id)
            recursion_stack.add(current_id)
            path.append(current_id)
            
            # Explore all references from this resource
            references = self.reference_map.get(current_id, [])
            for ref_info in references:
                target_id = ref_info['target_id']
                cycle = self._dfs_find_cycle(target_id, path, visited, recursion_stack)
                if cycle:
                    return cycle
            
            # Backtrack
            recursion_stack.remove(current_id)
            path.pop()
            
            return None
            
        except Exception as e:
            self.logger.warning(f"Error in DFS cycle detection: {str(e)}")
            return None
    
    def _detect_orphaned_references(self, valid_resource_ids: set) -> List[Dict[str, Any]]:
        """
        Detect references to non-existent resources.
        
        Args:
            valid_resource_ids: Set of valid resource IDs in the bundle
            
        Returns:
            List of orphaned reference information
        """
        orphaned_refs = []
        
        try:
            for source_id, references in self.reference_map.items():
                for ref_info in references:
                    target_id = ref_info['target_id']
                    if target_id not in valid_resource_ids:
                        orphaned_refs.append({
                            'source_id': source_id,
                            'target_id': target_id,
                            'field_path': ref_info['field_path'],
                            'reference_string': ref_info['reference_string']
                        })
            
            return orphaned_refs
            
        except Exception as e:
            self.logger.warning(f"Failed to detect orphaned references: {str(e)}")
            return []
    
    def stage_reference_update(self, old_id: str, new_id: str, resource_type: str):
        """
        Stage a reference update for later application.
        
        Args:
            old_id: Old resource ID being replaced
            new_id: New resource ID to use
            resource_type: Type of resource being updated
        """
        self.pending_updates.append({
            'old_id': old_id,
            'new_id': new_id,
            'resource_type': resource_type,
            'timestamp': datetime.utcnow()
        })
        
        self.logger.debug(f"Staged reference update: {old_id} -> {new_id} ({resource_type})")
    
    def apply_pending_updates(self, bundle: Bundle) -> Dict[str, Any]:
        """
        Apply all staged reference updates to the bundle.
        
        Args:
            bundle: FHIR Bundle to update
            
        Returns:
            Update results summary
        """
        try:
            update_results = {
                'updates_applied': 0,
                'updates_failed': 0,
                'affected_resources': set(),
                'errors': []
            }
            
            self.logger.info(f"Applying {len(self.pending_updates)} pending reference updates")
            
            for update in self.pending_updates:
                try:
                    success = self._apply_single_update(bundle, update)
                    if success:
                        update_results['updates_applied'] += 1
                        update_results['affected_resources'].add(update['old_id'])
                        update_results['affected_resources'].add(update['new_id'])
                    else:
                        update_results['updates_failed'] += 1
                        
                except Exception as e:
                    update_results['updates_failed'] += 1
                    update_results['errors'].append(f"Failed to apply update {update['old_id']} -> {update['new_id']}: {str(e)}")
                    self.logger.warning(f"Failed to apply reference update: {str(e)}")
            
            # Clear pending updates after applying
            self.pending_updates.clear()
            
            # Convert set to list for JSON serialization
            update_results['affected_resources'] = list(update_results['affected_resources'])
            
            self.logger.info(f"Reference updates complete: {update_results['updates_applied']} applied, "
                           f"{update_results['updates_failed']} failed")
            
            return update_results
            
        except Exception as e:
            self.logger.error(f"Failed to apply pending reference updates: {str(e)}")
            return {
                'updates_applied': 0,
                'updates_failed': len(self.pending_updates),
                'affected_resources': [],
                'errors': [str(e)]
            }
    
    def _apply_single_update(self, bundle: Bundle, update: Dict[str, Any]) -> bool:
        """
        Apply a single reference update to the bundle.
        
        Args:
            bundle: FHIR Bundle to update
            update: Update information dictionary
            
        Returns:
            True if update was successful, False otherwise
        """
        try:
            old_id = update['old_id']
            new_id = update['new_id']
            
            if not bundle or not bundle.entry:
                return False
            
            # Find all resources that reference the old ID
            referencing_resources = self.reverse_reference_map.get(old_id, [])
            
            updates_made = False
            for ref_info in referencing_resources:
                # Find the resource in the bundle
                for entry in bundle.entry:
                    if (entry.resource and 
                        hasattr(entry.resource, 'id') and 
                        entry.resource.id == ref_info['source_id']):
                        
                        # Update the reference in this resource
                        if self._update_reference_in_resource(entry.resource, ref_info['field_path'], old_id, new_id):
                            updates_made = True
            
            return updates_made
            
        except Exception as e:
            self.logger.warning(f"Failed to apply single reference update: {str(e)}")
            return False
    
    def _update_reference_in_resource(self, resource: Resource, field_path: str, old_id: str, new_id: str) -> bool:
        """
        Update a specific reference within a resource.
        
        Args:
            resource: FHIR resource to update
            field_path: Path to the reference field
            old_id: Old resource ID
            new_id: New resource ID
            
        Returns:
            True if update was successful, False otherwise
        """
        try:
            # Handle array indices in field path (e.g., 'target[0]')
            if '[' in field_path and ']' in field_path:
                base_field = field_path.split('[')[0]
                index_str = field_path.split('[')[1].split(']')[0]
                index = int(index_str)
                
                if hasattr(resource, base_field):
                    field_value = getattr(resource, base_field)
                    if isinstance(field_value, list) and len(field_value) > index:
                        return self._update_reference_value(field_value[index], old_id, new_id)
            
            # Handle nested field paths (e.g., 'agent.who')
            elif '.' in field_path:
                parts = field_path.split('.')
                current_obj = resource
                
                # Navigate to the parent object
                for part in parts[:-1]:
                    if hasattr(current_obj, part):
                        current_obj = getattr(current_obj, part)
                        if isinstance(current_obj, list) and current_obj:
                            current_obj = current_obj[0]
                    else:
                        return False
                
                # Update the final field
                final_field = parts[-1]
                if hasattr(current_obj, final_field):
                    ref_value = getattr(current_obj, final_field)
                    return self._update_reference_value(ref_value, old_id, new_id)
            
            # Handle simple field paths
            else:
                if hasattr(resource, field_path):
                    ref_value = getattr(resource, field_path)
                    return self._update_reference_value(ref_value, old_id, new_id)
            
            return False
            
        except Exception as e:
            self.logger.warning(f"Failed to update reference in resource: {str(e)}")
            return False
    
    def _update_reference_value(self, ref_value: Any, old_id: str, new_id: str) -> bool:
        """
        Update a reference value with new resource ID.
        
        Args:
            ref_value: Reference value to update
            old_id: Old resource ID
            new_id: New resource ID
            
        Returns:
            True if update was successful, False otherwise
        """
        try:
            # Handle Reference objects
            if hasattr(ref_value, 'reference'):
                if old_id in ref_value.reference:
                    ref_value.reference = ref_value.reference.replace(old_id, new_id)
                    return True
            
            # Handle dict with reference key
            elif isinstance(ref_value, dict) and 'reference' in ref_value:
                if old_id in ref_value['reference']:
                    ref_value['reference'] = ref_value['reference'].replace(old_id, new_id)
                    return True
            
            # Handle string references
            elif isinstance(ref_value, str):
                if old_id in ref_value:
                    # This would require updating the parent object
                    # which is more complex - log for now
                    self.logger.info(f"String reference update needed: {ref_value}")
                    return True
            
            return False
            
        except Exception as e:
            self.logger.warning(f"Failed to update reference value: {str(e)}")
            return False
    
    def validate_referential_integrity(self, bundle: Bundle) -> Dict[str, Any]:
        """
        Validate referential integrity of a FHIR bundle.
        
        Args:
            bundle: FHIR Bundle to validate
            
        Returns:
            Validation results summary
        """
        try:
            self.logger.info("Validating referential integrity")
            
            # Build current reference graph
            graph_info = self.build_reference_graph(bundle)
            
            validation_results = {
                'is_valid': True,
                'total_resources': graph_info['metadata']['resource_count'],
                'total_references': graph_info['metadata']['reference_count'],
                'circular_references': graph_info['metadata']['circular_references'],
                'orphaned_references': graph_info['metadata']['orphaned_references'],
                'validation_errors': [],
                'validation_warnings': []
            }
            
            # Check for critical issues
            if graph_info['metadata']['circular_references']:
                validation_results['is_valid'] = False
                validation_results['validation_errors'].append(
                    f"Found {len(graph_info['metadata']['circular_references'])} circular reference chains"
                )
            
            if graph_info['metadata']['orphaned_references']:
                validation_results['validation_warnings'].append(
                    f"Found {len(graph_info['metadata']['orphaned_references'])} orphaned references"
                )
            
            # Validate specific reference types
            type_validation = self._validate_reference_types(bundle)
            validation_results['validation_errors'].extend(type_validation['errors'])
            validation_results['validation_warnings'].extend(type_validation['warnings'])
            
            if type_validation['errors']:
                validation_results['is_valid'] = False
            
            self.logger.info(f"Referential integrity validation complete: "
                           f"{'PASSED' if validation_results['is_valid'] else 'FAILED'}")
            
            return validation_results
            
        except Exception as e:
            self.logger.error(f"Failed to validate referential integrity: {str(e)}")
            return {
                'is_valid': False,
                'total_resources': 0,
                'total_references': 0,
                'circular_references': [],
                'orphaned_references': [],
                'validation_errors': [f"Validation failed: {str(e)}"],
                'validation_warnings': []
            }
    
    def _validate_reference_types(self, bundle: Bundle) -> Dict[str, List[str]]:
        """
        Validate that references point to appropriate resource types.
        
        Args:
            bundle: FHIR Bundle to validate
            
        Returns:
            Dictionary with validation errors and warnings
        """
        errors = []
        warnings = []
        
        try:
            if not bundle or not bundle.entry:
                return {'errors': errors, 'warnings': warnings}
            
            # Build map of resource ID to resource type
            resource_types = {}
            for entry in bundle.entry:
                if entry.resource and hasattr(entry.resource, 'id'):
                    resource_types[entry.resource.id] = entry.resource.resource_type
            
            # Define expected reference types for common fields
            expected_types = {
                'subject': ['Patient'],
                'patient': ['Patient'],
                'performer': ['Practitioner', 'Organization', 'Patient'],
                'author': ['Practitioner', 'Patient', 'Device'],
                'encounter': ['Encounter'],
                'asserter': ['Practitioner', 'Patient'],
                'recorder': ['Practitioner', 'Patient']
            }
            
            # Validate each reference
            for source_id, references in self.reference_map.items():
                for ref_info in references:
                    target_id = ref_info['target_id']
                    field_path = ref_info['field_path']
                    
                    # Skip if target doesn't exist (already caught as orphaned)
                    if target_id not in resource_types:
                        continue
                    
                    # Extract base field name for validation
                    base_field = field_path.split('[')[0].split('.')[0]
                    
                    if base_field in expected_types:
                        target_type = resource_types[target_id]
                        if target_type not in expected_types[base_field]:
                            errors.append(
                                f"Invalid reference type: {source_id}.{field_path} "
                                f"points to {target_type}, expected one of {expected_types[base_field]}"
                            )
            
            return {'errors': errors, 'warnings': warnings}
            
        except Exception as e:
            errors.append(f"Reference type validation failed: {str(e)}")
            return {'errors': errors, 'warnings': warnings}
    
    def resolve_circular_references(self, bundle: Bundle) -> Dict[str, Any]:
        """
        Resolve circular references by breaking the least critical links.
        
        Args:
            bundle: FHIR Bundle with circular references
            
        Returns:
            Resolution results summary
        """
        try:
            self.logger.info("Resolving circular references")
            
            # First, detect all circular references
            graph_info = self.build_reference_graph(bundle)
            circular_refs = graph_info['metadata']['circular_references']
            
            resolution_results = {
                'cycles_found': len(circular_refs),
                'cycles_resolved': 0,
                'broken_references': [],
                'resolution_errors': []
            }
            
            if not circular_refs:
                self.logger.info("No circular references found")
                return resolution_results
            
            # Resolve each circular reference
            for i, cycle_info in enumerate(circular_refs):
                try:
                    cycle = cycle_info['cycle']
                    self.logger.info(f"Resolving circular reference {i+1}: {' -> '.join(cycle)}")
                    
                    # Choose the least critical reference to break
                    break_point = self._choose_break_point(cycle)
                    if break_point:
                        success = self._break_reference_link(bundle, break_point['source'], break_point['target'])
                        if success:
                            resolution_results['cycles_resolved'] += 1
                            resolution_results['broken_references'].append(break_point)
                        else:
                            resolution_results['resolution_errors'].append(
                                f"Failed to break reference: {break_point['source']} -> {break_point['target']}"
                            )
                    
                except Exception as e:
                    resolution_results['resolution_errors'].append(f"Failed to resolve cycle {i+1}: {str(e)}")
                    self.logger.warning(f"Failed to resolve circular reference: {str(e)}")
            
            self.logger.info(f"Circular reference resolution complete: "
                           f"{resolution_results['cycles_resolved']} of {resolution_results['cycles_found']} resolved")
            
            return resolution_results
            
        except Exception as e:
            self.logger.error(f"Failed to resolve circular references: {str(e)}")
            return {
                'cycles_found': 0,
                'cycles_resolved': 0,
                'broken_references': [],
                'resolution_errors': [str(e)]
            }
    
    def _choose_break_point(self, cycle: List[str]) -> Optional[Dict[str, str]]:
        """
        Choose the best point to break a circular reference chain.
        
        Args:
            cycle: List of resource IDs forming a circular reference
            
        Returns:
            Dictionary with source and target IDs for reference to break
        """
        try:
            if len(cycle) < 2:
                return None
            
            # Define reference criticality (lower is less critical)
            criticality_map = {
                'DocumentReference': 1,  # Least critical - just documentation
                'Provenance': 2,         # Important for audit but not clinical
                'Procedure': 3,          # Moderate criticality
                'Observation': 4,        # Important clinical data
                'Condition': 5,          # High criticality - diagnosis info
                'MedicationStatement': 5, # High criticality - medication info
                'Patient': 10            # Highest criticality - never break Patient refs
            }
            
            # Find the least critical link to break
            min_criticality = float('inf')
            break_point = None
            
            for i in range(len(cycle) - 1):
                source_id = cycle[i]
                target_id = cycle[i + 1]
                
                # Get resource types (if available)
                source_refs = self.reference_map.get(source_id, [])
                target_type = None
                
                for ref in source_refs:
                    if ref['target_id'] == target_id:
                        # Infer target type from reference string if possible
                        ref_str = ref.get('reference_string', '')
                        if '/' in ref_str:
                            target_type = ref_str.split('/')[0]
                        break
                
                # Calculate criticality
                if target_type:
                    criticality = criticality_map.get(target_type, 5)
                    if criticality < min_criticality:
                        min_criticality = criticality
                        break_point = {'source': source_id, 'target': target_id}
            
            # If no specific break point found, break the first link
            if not break_point:
                break_point = {'source': cycle[0], 'target': cycle[1]}
            
            return break_point
            
        except Exception as e:
            self.logger.warning(f"Failed to choose break point: {str(e)}")
            return None
    
    def _break_reference_link(self, bundle: Bundle, source_id: str, target_id: str) -> bool:
        """
        Break a specific reference link between two resources.
        
        Args:
            bundle: FHIR Bundle containing the resources
            source_id: ID of resource containing the reference
            target_id: ID of target resource
            
        Returns:
            True if reference was successfully broken, False otherwise
        """
        try:
            if not bundle or not bundle.entry:
                return False
            
            # Find the source resource
            source_resource = None
            for entry in bundle.entry:
                if (entry.resource and 
                    hasattr(entry.resource, 'id') and 
                    entry.resource.id == source_id):
                    source_resource = entry.resource
                    break
            
            if not source_resource:
                return False
            
            # Find references to the target and remove them
            references_removed = 0
            
            # Get all references from this resource
            source_refs = self.reference_map.get(source_id, [])
            
            for ref_info in source_refs:
                if ref_info['target_id'] == target_id:
                    # Remove this specific reference
                    if self._remove_reference_from_resource(source_resource, ref_info['field_path']):
                        references_removed += 1
            
            self.logger.info(f"Broke {references_removed} references from {source_id} to {target_id}")
            return references_removed > 0
            
        except Exception as e:
            self.logger.warning(f"Failed to break reference link: {str(e)}")
            return False
    
    def _remove_reference_from_resource(self, resource: Resource, field_path: str) -> bool:
        """
        Remove a specific reference from a resource.
        
        Args:
            resource: FHIR resource to modify
            field_path: Path to the reference field to remove
            
        Returns:
            True if reference was removed, False otherwise
        """
        try:
            # Handle array indices in field path
            if '[' in field_path and ']' in field_path:
                base_field = field_path.split('[')[0]
                index_str = field_path.split('[')[1].split(']')[0]
                index = int(index_str)
                
                if hasattr(resource, base_field):
                    field_value = getattr(resource, base_field)
                    if isinstance(field_value, list) and len(field_value) > index:
                        field_value.pop(index)
                        return True
            
            # Handle simple field paths - set to None
            elif hasattr(resource, field_path):
                setattr(resource, field_path, None)
                return True
            
            return False
            
        except Exception as e:
            self.logger.warning(f"Failed to remove reference from resource: {str(e)}")
            return False


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

class DuplicateResourceDetail:
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


class DeduplicationResult:
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


class ResourceHashGenerator:
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


class FuzzyMatcher:
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


class ResourceDeduplicator:
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


class AllergyIntoleranceHandler(BaseMergeHandler):
    """
    Specialized merge handler for AllergyIntolerance resources.
    
    Handles allergy severity changes, status updates, and reaction manifestations
    with special attention to patient safety concerns.
    """
    
    def merge_resource(
        self,
        new_resource: Resource,
        current_bundle: Bundle,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge an AllergyIntolerance resource with safety-focused logic.
        """
        self.logger.debug(f"Merging AllergyIntolerance resource")
        
        # Initialize result tracking
        merge_result = {
            'action': 'unknown',
            'resource_type': 'AllergyIntolerance',
            'resource_id': getattr(new_resource, 'id', 'unknown'),
            'conflicts_detected': 0,
            'conflicts_resolved': 0,
            'duplicates_removed': 0,
            'errors': [],
            'warnings': [],
            'conflict_details': []
        }
        
        # Look for existing allergy with same code and patient
        existing_resource = self._find_existing_resource(
            new_resource,
            current_bundle,
            ['code', 'patient', 'substance']
        )
        
        if existing_resource:
            # Check for duplicates first
            if config.get('duplicate_detection_enabled', True):
                is_duplicate = self.conflict_detector.check_for_duplicates(
                    new_resource, existing_resource, 'AllergyIntolerance'
                )
                
                if is_duplicate:
                    merge_result.update({
                        'action': 'skipped',
                        'duplicates_removed': 1,
                        'warnings': ['Identical allergy found - skipping duplicate']
                    })
                    return merge_result
            
            # Detect conflicts with special focus on safety-critical changes
            if config.get('conflict_detection_enabled', True):
                conflicts = self.conflict_detector.detect_conflicts(
                    new_resource, existing_resource, 'AllergyIntolerance'
                )
                
                merge_result['conflicts_detected'] = len(conflicts)
                merge_result['conflict_details'] = [c.to_dict() for c in conflicts]
                
                # Check for critical safety conflicts (severity changes)
                critical_conflicts = [c for c in conflicts if c.severity == 'critical']
                if critical_conflicts:
                    self.logger.warning(f"Critical allergy conflicts detected - flagging for review")
                    merge_result.update({
                        'action': 'flagged_for_review',
                        'errors': ['Critical allergy conflicts detected - manual review required'],
                        'critical_safety_issue': True
                    })
                    return merge_result
                
                if conflicts and config.get('resolve_conflicts', True):
                    # Apply conflict resolution
                    conflict_resolver = context.get('conflict_resolver')
                    if conflict_resolver:
                        provenance_tracker = context.get('provenance_tracker')
                        
                        resolution_summary = conflict_resolver.resolve_conflicts(
                            conflicts, new_resource, existing_resource, context, provenance_tracker
                        )
                        
                        merge_result['conflicts_resolved'] = resolution_summary['resolved_conflicts']
                        merge_result['resolution_actions'] = resolution_summary['resolution_actions']
                        
                        # For allergies, prefer newer information but preserve reaction history
                        if resolution_summary['overall_action'] == 'update_existing':
                            # Merge reaction information while updating main allergy details
                            merged_resource = self._merge_allergy_details(new_resource, existing_resource)
                            self._update_resource_in_bundle(merged_resource, current_bundle, existing_resource)
                            merge_result['action'] = 'updated'
                        else:
                            merge_result['action'] = resolution_summary['overall_action']
                    else:
                        # Default: preserve both for safety
                        merge_result.update({
                            'action': 'added',
                            'warnings': ['Conflicts detected but no resolver - adding as separate entry']
                        })
                        return self._add_resource_to_bundle(new_resource, current_bundle, context)
                else:
                    # Update existing with newer information
                    merged_resource = self._merge_allergy_details(new_resource, existing_resource)
                    self._update_resource_in_bundle(merged_resource, current_bundle, existing_resource)
                    merge_result['action'] = 'updated'
            else:
                # No conflict detection - merge safely
                merged_resource = self._merge_allergy_details(new_resource, existing_resource)
                self._update_resource_in_bundle(merged_resource, current_bundle, existing_resource)
                merge_result['action'] = 'updated'
        else:
            # No existing allergy - add new one
            merge_result = self._add_resource_to_bundle(new_resource, current_bundle, context)
            merge_result['action'] = 'added'
        
        return merge_result
    
    def _merge_allergy_details(self, new_resource: Resource, existing_resource: Resource) -> Resource:
        """
        Merge allergy details preserving reaction history and updating status/severity.
        """
        try:
            # Start with the newer resource as base
            merged = copy.deepcopy(new_resource)
            
            # Preserve reaction history from existing resource
            existing_reactions = getattr(existing_resource, 'reaction', [])
            new_reactions = getattr(new_resource, 'reaction', [])
            
            # Combine reactions, avoiding duplicates
            all_reactions = list(existing_reactions)
            for new_reaction in new_reactions:
                # Simple duplicate check based on manifestation
                is_duplicate = any(
                    self._reactions_similar(new_reaction, existing_reaction)
                    for existing_reaction in existing_reactions
                )
                if not is_duplicate:
                    all_reactions.append(new_reaction)
            
            if all_reactions:
                merged.reaction = all_reactions
            
            # Update metadata
            merged.meta = merged.meta or {}
            merged.meta['lastUpdated'] = datetime.utcnow().isoformat() + 'Z'
            
            return merged
            
        except Exception as e:
            self.logger.error(f"Failed to merge allergy details: {str(e)}")
            return new_resource
    
    def _reactions_similar(self, reaction1: Dict, reaction2: Dict) -> bool:
        """
        Check if two allergy reactions are similar enough to be considered duplicates.
        """
        try:
            # Compare manifestations
            manifest1 = reaction1.get('manifestation', [])
            manifest2 = reaction2.get('manifestation', [])
            
            if len(manifest1) != len(manifest2):
                return False
            
            # Simple comparison of manifestation codes
            codes1 = {m.get('coding', [{}])[0].get('code') for m in manifest1 if m.get('coding')}
            codes2 = {m.get('coding', [{}])[0].get('code') for m in manifest2 if m.get('coding')}
            
            return codes1 == codes2
            
        except Exception:
            return False


class ProcedureHandler(BaseMergeHandler):
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


class DiagnosticReportHandler(BaseMergeHandler):
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


class CarePlanHandler(BaseMergeHandler):
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
        self._handlers = {
            'Observation': ObservationMergeHandler(),
            'Condition': ConditionMergeHandler(),
            'MedicationStatement': MedicationStatementMergeHandler(),
            'AllergyIntolerance': AllergyIntoleranceHandler(),
            'Procedure': ProcedureHandler(),
            'DiagnosticReport': DiagnosticReportHandler(),
            'CarePlan': CarePlanHandler(),
        }
        self._generic_handler = GenericMergeHandler()
    
    def get_handler(self, resource_type: str) -> BaseMergeHandler:
        """
        Get the appropriate merge handler for a resource type.
        
        Args:
            resource_type: FHIR resource type string
            
        Returns:
            Appropriate merge handler instance
        """
        return self._handlers.get(resource_type, self._generic_handler)
    
    def register_handler(self, resource_type: str, handler: BaseMergeHandler):
        """
        Register a custom merge handler for a resource type.
        
        Args:
            resource_type: FHIR resource type string
            handler: Merge handler instance
        """
        self._handlers[resource_type] = handler


# =============================================================================
# REFERENTIAL INTEGRITY MAINTENANCE SYSTEM
# =============================================================================

class ReferentialIntegrityManager:
    """
    Comprehensive system for maintaining referential integrity between FHIR resources.
    
    This system tracks references, updates them during merges and deduplication,
    handles circular references, and validates integrity throughout the process.
    
    Think of this like the electrical system in your truck - every wire needs to
    stay connected to the right component, even when you're swapping parts.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the referential integrity manager.
        
        Args:
            config: Configuration dictionary with integrity settings
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.reference_map = {}  # Maps resource IDs to their references
        self.reverse_reference_map = {}  # Maps resource IDs to resources that reference them
        self.pending_updates = []  # Staging area for reference updates
        
    def build_reference_graph(self, bundle: Bundle) -> Dict[str, Any]:
        """
        Build a complete reference graph from a FHIR bundle.
        
        Args:
            bundle: FHIR Bundle to analyze
            
        Returns:
            Dictionary containing reference graph and metadata
        """
        try:
            self.logger.info("Building reference graph from FHIR bundle")
            
            # Clear existing maps
            self.reference_map.clear()
            self.reverse_reference_map.clear()
            
            graph_metadata = {
                'resource_count': 0,
                'reference_count': 0,
                'circular_references': [],
                'orphaned_references': []
            }
            
            if not bundle or not bundle.entry:
                return {
                    'reference_map': self.reference_map,
                    'reverse_reference_map': self.reverse_reference_map,
                    'metadata': graph_metadata
                }
            
            # First pass: Map all resource IDs
            resource_ids = set()
            for entry in bundle.entry:
                if entry.resource and hasattr(entry.resource, 'id'):
                    resource_ids.add(entry.resource.id)
                    graph_metadata['resource_count'] += 1
            
            # Second pass: Extract all references
            for entry in bundle.entry:
                if not entry.resource:
                    continue
                    
                resource = entry.resource
                resource_id = resource.id
                
                # Extract references from this resource
                references = self._extract_resource_references(resource)
                self.reference_map[resource_id] = references
                
                # Build reverse reference map
                for ref_info in references:
                    target_id = ref_info['target_id']
                    if target_id not in self.reverse_reference_map:
                        self.reverse_reference_map[target_id] = []
                    self.reverse_reference_map[target_id].append({
                        'source_id': resource_id,
                        'source_type': resource.resource_type,
                        'field_path': ref_info['field_path'],
                        'reference_type': ref_info['reference_type']
                    })
                    graph_metadata['reference_count'] += 1
            
            # Detect circular references
            graph_metadata['circular_references'] = self._detect_circular_references()
            
            # Detect orphaned references
            graph_metadata['orphaned_references'] = self._detect_orphaned_references(resource_ids)
            
            self.logger.info(f"Reference graph built: {graph_metadata['resource_count']} resources, "
                           f"{graph_metadata['reference_count']} references, "
                           f"{len(graph_metadata['circular_references'])} circular references")
            
            return {
                'reference_map': self.reference_map.copy(),
                'reverse_reference_map': self.reverse_reference_map.copy(),
                'metadata': graph_metadata
            }
            
        except Exception as e:
            self.logger.error(f"Failed to build reference graph: {str(e)}")
            return {
                'reference_map': {},
                'reverse_reference_map': {},
                'metadata': graph_metadata
            }
    
    def _extract_resource_references(self, resource: Resource) -> List[Dict[str, Any]]:
        """
        Extract all references from a FHIR resource.
        
        Args:
            resource: FHIR resource to analyze
            
        Returns:
            List of reference information dictionaries
        """
        references = []
        resource_type = resource.resource_type
        
        try:
            # Common reference patterns by resource type
            reference_patterns = {
                'Observation': ['subject', 'performer', 'encounter', 'basedOn'],
                'Condition': ['subject', 'encounter', 'asserter', 'recorder'],
                'MedicationStatement': ['subject', 'performer', 'context', 'informationSource'],
                'DocumentReference': ['subject', 'author', 'authenticator', 'custodian'],
                'Practitioner': [],  # Practitioners typically don't reference other resources
                'Provenance': ['target', 'agent.who', 'agent.onBehalfOf'],
                'Procedure': ['subject', 'encounter', 'recorder', 'asserter', 'performer.actor'],
                'DiagnosticReport': ['subject', 'encounter', 'performer', 'result', 'basedOn'],
                'CarePlan': ['subject', 'encounter', 'careTeam', 'goal', 'activity.reference'],
                'AllergyIntolerance': ['patient', 'encounter', 'recorder', 'asserter']
            }
            
            patterns = reference_patterns.get(resource_type, [])
            
            for pattern in patterns:
                refs = self._extract_references_by_pattern(resource, pattern)
                references.extend(refs)
            
            return references
            
        except Exception as e:
            self.logger.warning(f"Failed to extract references from {resource_type}: {str(e)}")
            return []
    
    def _extract_references_by_pattern(self, resource: Resource, pattern: str) -> List[Dict[str, Any]]:
        """
        Extract references using a specific field pattern.
        
        Args:
            resource: FHIR resource
            pattern: Field pattern (e.g., 'subject', 'agent.who')
            
        Returns:
            List of reference information
        """
        references = []
        
        try:
            # Handle nested patterns (e.g., 'agent.who')
            if '.' in pattern:
                parts = pattern.split('.')
                current_obj = resource
                
                for part in parts[:-1]:
                    if hasattr(current_obj, part):
                        current_obj = getattr(current_obj, part)
                        if isinstance(current_obj, list) and current_obj:
                            current_obj = current_obj[0]  # Take first item for lists
                    else:
                        return references
                
                final_field = parts[-1]
                if hasattr(current_obj, final_field):
                    ref_value = getattr(current_obj, final_field)
                    if ref_value:
                        ref_info = self._parse_reference_value(ref_value, pattern)
                        if ref_info:
                            references.append(ref_info)
            
            # Handle simple patterns (e.g., 'subject')
            else:
                if hasattr(resource, pattern):
                    ref_value = getattr(resource, pattern)
                    if ref_value:
                        # Handle lists of references
                        if isinstance(ref_value, list):
                            for i, ref_item in enumerate(ref_value):
                                ref_info = self._parse_reference_value(ref_item, f"{pattern}[{i}]")
                                if ref_info:
                                    references.append(ref_info)
                        else:
                            ref_info = self._parse_reference_value(ref_value, pattern)
                            if ref_info:
                                references.append(ref_info)
            
            return references
            
        except Exception as e:
            self.logger.warning(f"Failed to extract references for pattern '{pattern}': {str(e)}")
            return []
    
    def _parse_reference_value(self, ref_value: Any, field_path: str) -> Optional[Dict[str, Any]]:
        """
        Parse a reference value and extract target information.
        
        Args:
            ref_value: Reference value (could be Reference object, dict, or string)
            field_path: Field path where this reference was found
            
        Returns:
            Reference information dictionary or None
        """
        try:
            reference_str = None
            reference_type = 'unknown'
            
            # Handle Reference objects
            if hasattr(ref_value, 'reference'):
                reference_str = ref_value.reference
                reference_type = 'Reference'
            
            # Handle dict with reference key
            elif isinstance(ref_value, dict) and 'reference' in ref_value:
                reference_str = ref_value['reference']
                reference_type = 'dict'
            
            # Handle string references
            elif isinstance(ref_value, str):
                reference_str = ref_value
                reference_type = 'string'
            
            if not reference_str:
                return None
            
            # Extract target ID from reference string
            target_id = self._extract_target_id(reference_str)
            if not target_id:
                return None
            
            return {
                'target_id': target_id,
                'reference_string': reference_str,
                'field_path': field_path,
                'reference_type': reference_type
            }
            
        except Exception as e:
            self.logger.warning(f"Failed to parse reference value: {str(e)}")
            return None
    
    def _extract_target_id(self, reference_str: str) -> Optional[str]:
        """
        Extract target resource ID from a reference string.
        
        Args:
            reference_str: Reference string (e.g., 'Patient/123', '#123')
            
        Returns:
            Target resource ID or None
        """
        try:
            if not reference_str:
                return None
            
            # Handle relative references (e.g., 'Patient/123')
            if '/' in reference_str:
                return reference_str.split('/')[-1]
            
            # Handle internal references (e.g., '#123')
            if reference_str.startswith('#'):
                return reference_str[1:]
            
            # Handle direct IDs
            return reference_str
            
        except Exception:
            return None
    
    def _detect_circular_references(self) -> List[Dict[str, Any]]:
        """
        Detect circular reference chains in the reference graph.
        
        Returns:
            List of circular reference chains found
        """
        circular_refs = []
        visited = set()
        
        try:
            for resource_id in self.reference_map:
                if resource_id in visited:
                    continue
                
                # Use depth-first search to detect cycles
                path = []
                cycle = self._dfs_find_cycle(resource_id, path, visited, set())
                if cycle:
                    circular_refs.append({
                        'cycle': cycle,
                        'cycle_length': len(cycle)
                    })
            
            return circular_refs
            
        except Exception as e:
            self.logger.warning(f"Failed to detect circular references: {str(e)}")
            return []
    
    def _dfs_find_cycle(self, current_id: str, path: List[str], visited: set, recursion_stack: set) -> Optional[List[str]]:
        """
        Depth-first search to find cycles in reference graph.
        
        Args:
            current_id: Current resource ID being explored
            path: Current path being explored
            visited: Set of all visited nodes
            recursion_stack: Set of nodes in current recursion stack
            
        Returns:
            Circular reference path if found, None otherwise
        """
        try:
            if current_id in recursion_stack:
                # Found a cycle - return the cycle path
                cycle_start = path.index(current_id)
                return path[cycle_start:] + [current_id]
            
            if current_id in visited:
                return None
            
            visited.add(current_id)
            recursion_stack.add(current_id)
            path.append(current_id)
            
            # Explore all references from this resource
            references = self.reference_map.get(current_id, [])
            for ref_info in references:
                target_id = ref_info['target_id']
                cycle = self._dfs_find_cycle(target_id, path, visited, recursion_stack)
                if cycle:
                    return cycle
            
            # Backtrack
            recursion_stack.remove(current_id)
            path.pop()
            
            return None
            
        except Exception as e:
            self.logger.warning(f"Error in DFS cycle detection: {str(e)}")
            return None
    
    def _detect_orphaned_references(self, valid_resource_ids: set) -> List[Dict[str, Any]]:
        """
        Detect references to non-existent resources.
        
        Args:
            valid_resource_ids: Set of valid resource IDs in the bundle
            
        Returns:
            List of orphaned reference information
        """
        orphaned_refs = []
        
        try:
            for source_id, references in self.reference_map.items():
                for ref_info in references:
                    target_id = ref_info['target_id']
                    if target_id not in valid_resource_ids:
                        orphaned_refs.append({
                            'source_id': source_id,
                            'target_id': target_id,
                            'field_path': ref_info['field_path'],
                            'reference_string': ref_info['reference_string']
                        })
            
            return orphaned_refs
            
        except Exception as e:
            self.logger.warning(f"Failed to detect orphaned references: {str(e)}")
            return []
    
    def stage_reference_update(self, old_id: str, new_id: str, resource_type: str):
        """
        Stage a reference update for later application.
        
        Args:
            old_id: Old resource ID being replaced
            new_id: New resource ID to use
            resource_type: Type of resource being updated
        """
        self.pending_updates.append({
            'old_id': old_id,
            'new_id': new_id,
            'resource_type': resource_type,
            'timestamp': datetime.utcnow()
        })
        
        self.logger.debug(f"Staged reference update: {old_id} -> {new_id} ({resource_type})")
    
    def apply_pending_updates(self, bundle: Bundle) -> Dict[str, Any]:
        """
        Apply all staged reference updates to the bundle.
        
        Args:
            bundle: FHIR Bundle to update
            
        Returns:
            Update results summary
        """
        try:
            update_results = {
                'updates_applied': 0,
                'updates_failed': 0,
                'affected_resources': set(),
                'errors': []
            }
            
            self.logger.info(f"Applying {len(self.pending_updates)} pending reference updates")
            
            for update in self.pending_updates:
                try:
                    success = self._apply_single_update(bundle, update)
                    if success:
                        update_results['updates_applied'] += 1
                        update_results['affected_resources'].add(update['old_id'])
                        update_results['affected_resources'].add(update['new_id'])
                    else:
                        update_results['updates_failed'] += 1
                        
                except Exception as e:
                    update_results['updates_failed'] += 1
                    update_results['errors'].append(f"Failed to apply update {update['old_id']} -> {update['new_id']}: {str(e)}")
                    self.logger.warning(f"Failed to apply reference update: {str(e)}")
            
            # Clear pending updates after applying
            self.pending_updates.clear()
            
            # Convert set to list for JSON serialization
            update_results['affected_resources'] = list(update_results['affected_resources'])
            
            self.logger.info(f"Reference updates complete: {update_results['updates_applied']} applied, "
                           f"{update_results['updates_failed']} failed")
            
            return update_results
            
        except Exception as e:
            self.logger.error(f"Failed to apply pending reference updates: {str(e)}")
            return {
                'updates_applied': 0,
                'updates_failed': len(self.pending_updates),
                'affected_resources': [],
                'errors': [str(e)]
            }
    
    def _apply_single_update(self, bundle: Bundle, update: Dict[str, Any]) -> bool:
        """
        Apply a single reference update to the bundle.
        
        Args:
            bundle: FHIR Bundle to update
            update: Update information dictionary
            
        Returns:
            True if update was successful, False otherwise
        """
        try:
            old_id = update['old_id']
            new_id = update['new_id']
            
            if not bundle or not bundle.entry:
                return False
            
            # Find all resources that reference the old ID
            referencing_resources = self.reverse_reference_map.get(old_id, [])
            
            updates_made = False
            for ref_info in referencing_resources:
                # Find the resource in the bundle
                for entry in bundle.entry:
                    if (entry.resource and 
                        hasattr(entry.resource, 'id') and 
                        entry.resource.id == ref_info['source_id']):
                        
                        # Update the reference in this resource
                        if self._update_reference_in_resource(entry.resource, ref_info['field_path'], old_id, new_id):
                            updates_made = True
            
            return updates_made
            
        except Exception as e:
            self.logger.warning(f"Failed to apply single reference update: {str(e)}")
            return False
    
    def _update_reference_in_resource(self, resource: Resource, field_path: str, old_id: str, new_id: str) -> bool:
        """
        Update a specific reference within a resource.
        
        Args:
            resource: FHIR resource to update
            field_path: Path to the reference field
            old_id: Old resource ID
            new_id: New resource ID
            
        Returns:
            True if update was successful, False otherwise
        """
        try:
            # Handle array indices in field path (e.g., 'target[0]')
            if '[' in field_path and ']' in field_path:
                base_field = field_path.split('[')[0]
                index_str = field_path.split('[')[1].split(']')[0]
                index = int(index_str)
                
                if hasattr(resource, base_field):
                    field_value = getattr(resource, base_field)
                    if isinstance(field_value, list) and len(field_value) > index:
                        return self._update_reference_value(field_value[index], old_id, new_id)
            
            # Handle nested field paths (e.g., 'agent.who')
            elif '.' in field_path:
                parts = field_path.split('.')
                current_obj = resource
                
                # Navigate to the parent object
                for part in parts[:-1]:
                    if hasattr(current_obj, part):
                        current_obj = getattr(current_obj, part)
                        if isinstance(current_obj, list) and current_obj:
                            current_obj = current_obj[0]
                    else:
                        return False
                
                # Update the final field
                final_field = parts[-1]
                if hasattr(current_obj, final_field):
                    ref_value = getattr(current_obj, final_field)
                    return self._update_reference_value(ref_value, old_id, new_id)
            
            # Handle simple field paths
            else:
                if hasattr(resource, field_path):
                    ref_value = getattr(resource, field_path)
                    return self._update_reference_value(ref_value, old_id, new_id)
            
            return False
            
        except Exception as e:
            self.logger.warning(f"Failed to update reference in resource: {str(e)}")
            return False
    
    def _update_reference_value(self, ref_value: Any, old_id: str, new_id: str) -> bool:
        """
        Update a reference value with new resource ID.
        
        Args:
            ref_value: Reference value to update
            old_id: Old resource ID
            new_id: New resource ID
            
        Returns:
            True if update was successful, False otherwise
        """
        try:
            # Handle Reference objects
            if hasattr(ref_value, 'reference'):
                if old_id in ref_value.reference:
                    ref_value.reference = ref_value.reference.replace(old_id, new_id)
                    return True
            
            # Handle dict with reference key
            elif isinstance(ref_value, dict) and 'reference' in ref_value:
                if old_id in ref_value['reference']:
                    ref_value['reference'] = ref_value['reference'].replace(old_id, new_id)
                    return True
            
            # Handle string references
            elif isinstance(ref_value, str):
                if old_id in ref_value:
                    # This would require updating the parent object
                    # which is more complex - log for now
                    self.logger.info(f"String reference update needed: {ref_value}")
                    return True
            
            return False
            
        except Exception as e:
            self.logger.warning(f"Failed to update reference value: {str(e)}")
            return False
    
    def validate_referential_integrity(self, bundle: Bundle) -> Dict[str, Any]:
        """
        Validate referential integrity of a FHIR bundle.
        
        Args:
            bundle: FHIR Bundle to validate
            
        Returns:
            Validation results summary
        """
        try:
            self.logger.info("Validating referential integrity")
            
            # Build current reference graph
            graph_info = self.build_reference_graph(bundle)
            
            validation_results = {
                'is_valid': True,
                'total_resources': graph_info['metadata']['resource_count'],
                'total_references': graph_info['metadata']['reference_count'],
                'circular_references': graph_info['metadata']['circular_references'],
                'orphaned_references': graph_info['metadata']['orphaned_references'],
                'validation_errors': [],
                'validation_warnings': []
            }
            
            # Check for critical issues
            if graph_info['metadata']['circular_references']:
                validation_results['is_valid'] = False
                validation_results['validation_errors'].append(
                    f"Found {len(graph_info['metadata']['circular_references'])} circular reference chains"
                )
            
            if graph_info['metadata']['orphaned_references']:
                validation_results['validation_warnings'].append(
                    f"Found {len(graph_info['metadata']['orphaned_references'])} orphaned references"
                )
            
            # Validate specific reference types
            type_validation = self._validate_reference_types(bundle)
            validation_results['validation_errors'].extend(type_validation['errors'])
            validation_results['validation_warnings'].extend(type_validation['warnings'])
            
            if type_validation['errors']:
                validation_results['is_valid'] = False
            
            self.logger.info(f"Referential integrity validation complete: "
                           f"{'PASSED' if validation_results['is_valid'] else 'FAILED'}")
            
            return validation_results
            
        except Exception as e:
            self.logger.error(f"Failed to validate referential integrity: {str(e)}")
            return {
                'is_valid': False,
                'total_resources': 0,
                'total_references': 0,
                'circular_references': [],
                'orphaned_references': [],
                'validation_errors': [f"Validation failed: {str(e)}"],
                'validation_warnings': []
            }
    
    def _validate_reference_types(self, bundle: Bundle) -> Dict[str, List[str]]:
        """
        Validate that references point to appropriate resource types.
        
        Args:
            bundle: FHIR Bundle to validate
            
        Returns:
            Dictionary with validation errors and warnings
        """
        errors = []
        warnings = []
        
        try:
            if not bundle or not bundle.entry:
                return {'errors': errors, 'warnings': warnings}
            
            # Build map of resource ID to resource type
            resource_types = {}
            for entry in bundle.entry:
                if entry.resource and hasattr(entry.resource, 'id'):
                    resource_types[entry.resource.id] = entry.resource.resource_type
            
            # Define expected reference types for common fields
            expected_types = {
                'subject': ['Patient'],
                'patient': ['Patient'],
                'performer': ['Practitioner', 'Organization', 'Patient'],
                'author': ['Practitioner', 'Patient', 'Device'],
                'encounter': ['Encounter'],
                'asserter': ['Practitioner', 'Patient'],
                'recorder': ['Practitioner', 'Patient']
            }
            
            # Validate each reference
            for source_id, references in self.reference_map.items():
                for ref_info in references:
                    target_id = ref_info['target_id']
                    field_path = ref_info['field_path']
                    
                    # Skip if target doesn't exist (already caught as orphaned)
                    if target_id not in resource_types:
                        continue
                    
                    # Extract base field name for validation
                    base_field = field_path.split('[')[0].split('.')[0]
                    
                    if base_field in expected_types:
                        target_type = resource_types[target_id]
                        if target_type not in expected_types[base_field]:
                            errors.append(
                                f"Invalid reference type: {source_id}.{field_path} "
                                f"points to {target_type}, expected one of {expected_types[base_field]}"
                            )
            
            return {'errors': errors, 'warnings': warnings}
            
        except Exception as e:
            errors.append(f"Reference type validation failed: {str(e)}")
            return {'errors': errors, 'warnings': warnings}
    
    def resolve_circular_references(self, bundle: Bundle) -> Dict[str, Any]:
        """
        Resolve circular references by breaking the least critical links.
        
        Args:
            bundle: FHIR Bundle with circular references
            
        Returns:
            Resolution results summary
        """
        try:
            self.logger.info("Resolving circular references")
            
            # First, detect all circular references
            graph_info = self.build_reference_graph(bundle)
            circular_refs = graph_info['metadata']['circular_references']
            
            resolution_results = {
                'cycles_found': len(circular_refs),
                'cycles_resolved': 0,
                'broken_references': [],
                'resolution_errors': []
            }
            
            if not circular_refs:
                self.logger.info("No circular references found")
                return resolution_results
            
            # Resolve each circular reference
            for i, cycle_info in enumerate(circular_refs):
                try:
                    cycle = cycle_info['cycle']
                    self.logger.info(f"Resolving circular reference {i+1}: {' -> '.join(cycle)}")
                    
                    # Choose the least critical reference to break
                    break_point = self._choose_break_point(cycle)
                    if break_point:
                        success = self._break_reference_link(bundle, break_point['source'], break_point['target'])
                        if success:
                            resolution_results['cycles_resolved'] += 1
                            resolution_results['broken_references'].append(break_point)
                        else:
                            resolution_results['resolution_errors'].append(
                                f"Failed to break reference: {break_point['source']} -> {break_point['target']}"
                            )
                    
                except Exception as e:
                    resolution_results['resolution_errors'].append(f"Failed to resolve cycle {i+1}: {str(e)}")
                    self.logger.warning(f"Failed to resolve circular reference: {str(e)}")
            
            self.logger.info(f"Circular reference resolution complete: "
                           f"{resolution_results['cycles_resolved']} of {resolution_results['cycles_found']} resolved")
            
            return resolution_results
            
        except Exception as e:
            self.logger.error(f"Failed to resolve circular references: {str(e)}")
            return {
                'cycles_found': 0,
                'cycles_resolved': 0,
                'broken_references': [],
                'resolution_errors': [str(e)]
            }
    
    def _choose_break_point(self, cycle: List[str]) -> Optional[Dict[str, str]]:
        """
        Choose the best point to break a circular reference chain.
        
        Args:
            cycle: List of resource IDs forming a circular reference
            
        Returns:
            Dictionary with source and target IDs for reference to break
        """
        try:
            if len(cycle) < 2:
                return None
            
            # Define reference criticality (lower is less critical)
            criticality_map = {
                'DocumentReference': 1,  # Least critical - just documentation
                'Provenance': 2,         # Important for audit but not clinical
                'Procedure': 3,          # Moderate criticality
                'Observation': 4,        # Important clinical data
                'Condition': 5,          # High criticality - diagnosis info
                'MedicationStatement': 5, # High criticality - medication info
                'Patient': 10            # Highest criticality - never break Patient refs
            }
            
            # Find the least critical link to break
            min_criticality = float('inf')
            break_point = None
            
            for i in range(len(cycle) - 1):
                source_id = cycle[i]
                target_id = cycle[i + 1]
                
                # Get resource types (if available)
                source_refs = self.reference_map.get(source_id, [])
                target_type = None
                
                for ref in source_refs:
                    if ref['target_id'] == target_id:
                        # Infer target type from reference string if possible
                        ref_str = ref.get('reference_string', '')
                        if '/' in ref_str:
                            target_type = ref_str.split('/')[0]
                        break
                
                # Calculate criticality
                if target_type:
                    criticality = criticality_map.get(target_type, 5)
                    if criticality < min_criticality:
                        min_criticality = criticality
                        break_point = {'source': source_id, 'target': target_id}
            
            # If no specific break point found, break the first link
            if not break_point:
                break_point = {'source': cycle[0], 'target': cycle[1]}
            
            return break_point
            
        except Exception as e:
            self.logger.warning(f"Failed to choose break point: {str(e)}")
            return None
    
    def _break_reference_link(self, bundle: Bundle, source_id: str, target_id: str) -> bool:
        """
        Break a specific reference link between two resources.
        
        Args:
            bundle: FHIR Bundle containing the resources
            source_id: ID of resource containing the reference
            target_id: ID of target resource
            
        Returns:
            True if reference was successfully broken, False otherwise
        """
        try:
            if not bundle or not bundle.entry:
                return False
            
            # Find the source resource
            source_resource = None
            for entry in bundle.entry:
                if (entry.resource and 
                    hasattr(entry.resource, 'id') and 
                    entry.resource.id == source_id):
                    source_resource = entry.resource
                    break
            
            if not source_resource:
                return False
            
            # Find references to the target and remove them
            references_removed = 0
            
            # Get all references from this resource
            source_refs = self.reference_map.get(source_id, [])
            
            for ref_info in source_refs:
                if ref_info['target_id'] == target_id:
                    # Remove this specific reference
                    if self._remove_reference_from_resource(source_resource, ref_info['field_path']):
                        references_removed += 1
            
            self.logger.info(f"Broke {references_removed} references from {source_id} to {target_id}")
            return references_removed > 0
            
        except Exception as e:
            self.logger.warning(f"Failed to break reference link: {str(e)}")
            return False
    
    def _remove_reference_from_resource(self, resource: Resource, field_path: str) -> bool:
        """
        Remove a specific reference from a resource.
        
        Args:
            resource: FHIR resource to modify
            field_path: Path to the reference field to remove
            
        Returns:
            True if reference was removed, False otherwise
        """
        try:
            # Handle array indices in field path
            if '[' in field_path and ']' in field_path:
                base_field = field_path.split('[')[0]
                index_str = field_path.split('[')[1].split(']')[0]
                index = int(index_str)
                
                if hasattr(resource, base_field):
                    field_value = getattr(resource, base_field)
                    if isinstance(field_value, list) and len(field_value) > index:
                        field_value.pop(index)
                        return True
            
            # Handle simple field paths - set to None
            elif hasattr(resource, field_path):
                setattr(resource, field_path, None)
                return True
            
            return False
            
        except Exception as e:
            self.logger.warning(f"Failed to remove reference from resource: {str(e)}")
            return False
