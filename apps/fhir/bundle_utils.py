"""
FHIR Bundle Management Utilities

This module provides utility functions for managing FHIR Bundles in the medical
document parser application. Handles bundle creation, resource management,
versioning, deduplication, and proper FHIR structure maintenance.

All functions follow FHIR R4 Bundle specification and include comprehensive
error handling and validation.
"""

from typing import Optional, List, Dict, Any, Union, Type, Tuple
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import json
import hashlib

from fhir.resources.bundle import Bundle
from fhir.resources.bundle import BundleEntry
from fhir.resources.meta import Meta
from fhir.resources.resource import Resource

from .fhir_models import (
    PatientResource,
    DocumentReferenceResource,
    ConditionResource,
    ObservationResource,
    MedicationStatementResource,
    PractitionerResource,
    ProvenanceResource
)
from apps.core.jsonb_utils import get_reference_value


def create_initial_patient_bundle(
    patient_resource: PatientResource,
    bundle_id: Optional[str] = None
) -> Bundle:
    """
    Create a new FHIR Bundle initialized with a Patient resource.
    
    Args:
        patient_resource: Patient resource to include in the bundle
        bundle_id: Optional bundle ID, generates UUID if not provided
        
    Returns:
        Bundle: FHIR Bundle containing the patient resource
        
    Raises:
        ValueError: If patient_resource is None or invalid
    """
    if not patient_resource:
        raise ValueError("Patient resource is required")
    
    if not hasattr(patient_resource, 'id') or not patient_resource.id:
        raise ValueError("Patient resource must have a valid ID")
    
    # Generate bundle ID if not provided
    if not bundle_id:
        bundle_id = str(uuid4())
    
    # Create bundle metadata
    bundle_meta = Meta(
        versionId="1",
        lastUpdated=datetime.utcnow().isoformat() + "Z"
    )
    
    # Create bundle entry for patient
    patient_entry = BundleEntry(
        fullUrl=f"Patient/{patient_resource.id}",
        resource=patient_resource
    )
    
    # Create the bundle
    bundle = Bundle(
        id=bundle_id,
        meta=bundle_meta,
        type="collection",
        entry=[patient_entry]
    )
    
    return bundle


def add_resource_to_bundle(
    bundle: Bundle,
    resource: Resource,
    update_existing: bool = True
) -> Bundle:
    """
    Add or update a resource in an existing FHIR Bundle.
    
    Args:
        bundle: Existing FHIR Bundle
        resource: FHIR resource to add or update
        update_existing: If True, update existing resource; if False, create new entry
        
    Returns:
        Bundle: Updated FHIR Bundle
        
    Raises:
        ValueError: If bundle or resource is invalid
    """
    if not bundle:
        raise ValueError("Bundle is required")
    
    if not resource:
        raise ValueError("Resource is required")
    
    if not hasattr(resource, 'resource_type'):
        raise ValueError("Resource must have a valid resource_type")
    
    if not hasattr(resource, 'id') or not resource.id:
        raise ValueError("Resource must have a valid ID")
    
    # Initialize entries if None
    if not bundle.entry:
        bundle.entry = []
    
    # Look for existing resource
    existing_entry_index = None
    for index, entry in enumerate(bundle.entry):
        if (entry.resource and 
            entry.resource.resource_type == resource.resource_type and
            entry.resource.id == resource.id):
            existing_entry_index = index
            break
    
    # Create new entry
    new_entry = BundleEntry(
        fullUrl=f"{resource.resource_type}/{resource.id}",
        resource=resource
    )
    
    if existing_entry_index is not None and update_existing:
        # Update existing entry
        bundle.entry[existing_entry_index] = new_entry
    else:
        # Add new entry
        bundle.entry.append(new_entry)
    
    # Update bundle metadata
    if bundle.meta:
        # Increment version
        current_version = int(bundle.meta.versionId) if bundle.meta.versionId else 1
        bundle.meta.versionId = str(current_version + 1)
        bundle.meta.lastUpdated = datetime.utcnow().isoformat() + "Z"
    else:
        bundle.meta = Meta(
            versionId="2",
            lastUpdated=datetime.utcnow().isoformat() + "Z"
        )
    
    return bundle


def get_resources_by_type(
    bundle: Bundle,
    resource_type: str
) -> List[Resource]:
    """
    Extract all resources of a specific type from a FHIR Bundle.
    
    Args:
        bundle: FHIR Bundle to search
        resource_type: Type of resource to extract (e.g., "Patient", "Condition")
        
    Returns:
        List of resources matching the specified type
        
    Raises:
        ValueError: If bundle is invalid or resource_type is empty
    """
    if not bundle:
        raise ValueError("Bundle is required")
    
    if not resource_type or not resource_type.strip():
        raise ValueError("Resource type is required")
    
    if not bundle.entry:
        return []
    
    matching_resources = []
    
    for entry in bundle.entry:
        if (entry.resource and 
            entry.resource.resource_type == resource_type.strip()):
            matching_resources.append(entry.resource)
    
    return matching_resources


def validate_bundle_integrity(bundle: Bundle) -> Dict[str, Any]:
    """
    Validate the integrity of a FHIR Bundle structure.
    
    Args:
        bundle: FHIR Bundle to validate
        
    Returns:
        Dictionary with validation results and any issues found
        
    Raises:
        ValueError: If bundle is None
    """
    if not bundle:
        raise ValueError("Bundle is required")
    
    validation_result = {
        "is_valid": True,
        "issues": [],
        "resource_count": 0,
        "resource_types": {}
    }
    
    # Check bundle ID
    if not bundle.id:
        validation_result["issues"].append("Bundle missing ID")
        validation_result["is_valid"] = False
    
    # Check bundle type
    if not bundle.type:
        validation_result["issues"].append("Bundle missing type")
        validation_result["is_valid"] = False
    
    # Validate entries
    if bundle.entry:
        validation_result["resource_count"] = len(bundle.entry)
        
        for index, entry in enumerate(bundle.entry):
            # Check entry has resource
            if not entry.resource:
                validation_result["issues"].append(f"Entry {index} missing resource")
                validation_result["is_valid"] = False
                continue
            
            # Check resource has ID
            if not entry.resource.id:
                validation_result["issues"].append(
                    f"Entry {index} resource missing ID"
                )
                validation_result["is_valid"] = False
            
            # Check fullUrl matches resource
            expected_url = f"{entry.resource.resource_type}/{entry.resource.id}"
            if entry.fullUrl != expected_url:
                validation_result["issues"].append(
                    f"Entry {index} fullUrl mismatch: expected {expected_url}, "
                    f"got {entry.fullUrl}"
                )
                validation_result["is_valid"] = False
            
            # Count resource types
            resource_type = entry.resource.resource_type
            if resource_type in validation_result["resource_types"]:
                validation_result["resource_types"][resource_type] += 1
            else:
                validation_result["resource_types"][resource_type] = 1
    
    return validation_result


def get_bundle_summary(bundle: Bundle) -> Dict[str, Any]:
    """
    Generate a summary of bundle contents and metadata.
    
    Args:
        bundle: FHIR Bundle to summarize
        
    Returns:
        Dictionary with bundle summary information
        
    Raises:
        ValueError: If bundle is None
    """
    if not bundle:
        raise ValueError("Bundle is required")
    
    summary = {
        "id": bundle.id,
        "type": bundle.type,
        "version": bundle.meta.versionId if bundle.meta else None,
        "last_updated": bundle.meta.lastUpdated if bundle.meta else None,
        "total_entries": len(bundle.entry) if bundle.entry else 0,
        "resource_types": {},
        "patient_info": None
    }
    
    if bundle.entry:
        # Count resource types and find patient
        for entry in bundle.entry:
            if entry.resource:
                resource_type = entry.resource.resource_type
                if resource_type in summary["resource_types"]:
                    summary["resource_types"][resource_type] += 1
                else:
                    summary["resource_types"][resource_type] = 1
                
                # Extract patient information
                if resource_type == "Patient":
                    patient = entry.resource
                    summary["patient_info"] = {
                        "id": patient.id,
                        "name": patient.get_display_name() if hasattr(patient, 'get_display_name') else "Unknown",
                        "mrn": patient.get_mrn() if hasattr(patient, 'get_mrn') else None,
                        "birth_date": patient.birthDate if hasattr(patient, 'birthDate') else None
                    }
    
    return summary


# =============================================================================
# Resource Versioning and Deduplication Functions
# =============================================================================

def update_resource_version(resource: Resource) -> Resource:
    """
    Update a resource's version information in its meta field.
    
    Args:
        resource: FHIR resource to update
        
    Returns:
        Resource with updated version information
        
    Raises:
        ValueError: If resource is invalid
    """
    if not resource:
        raise ValueError("Resource is required")
    
    current_timestamp = datetime.utcnow().isoformat() + "Z"
    
    if not resource.meta:
        # Create new meta with version 1
        resource.meta = Meta(
            versionId="1",
            lastUpdated=current_timestamp
        )
    else:
        # Increment existing version
        current_version = int(resource.meta.versionId) if resource.meta.versionId else 1
        resource.meta.versionId = str(current_version + 1)
        resource.meta.lastUpdated = current_timestamp
    
    return resource


def get_resource_hash(resource: Resource) -> str:
    """
    Generate a hash for a resource based on its clinically relevant content.
    
    Args:
        resource: FHIR resource to hash
        
    Returns:
        SHA256 hash of the resource's content
        
    Raises:
        ValueError: If resource is invalid
    """
    if not resource:
        raise ValueError("Resource is required")
    
    # Create a dictionary with only clinically relevant fields
    # (excluding meta, id, and other administrative fields)
    clinical_content = {}
    
    # Convert resource to dict and extract relevant fields
    resource_dict = resource.dict()
    
    # Remove administrative fields that shouldn't affect clinical equivalence
    fields_to_exclude = {'id', 'meta', 'implicitRules', 'language'}
    
    for key, value in resource_dict.items():
        if key not in fields_to_exclude and value is not None:
            clinical_content[key] = value
    
    # Convert to JSON string with sorted keys for consistent hashing
    content_json = json.dumps(clinical_content, sort_keys=True, default=str)
    
    # Generate hash
    return hashlib.sha256(content_json.encode('utf-8')).hexdigest()


def are_resources_clinically_equivalent(
    resource1: Resource,
    resource2: Resource,
    tolerance_hours: int = 24
) -> bool:
    """
    Check if two resources are clinically equivalent based on business rules.
    
    Args:
        resource1: First resource to compare
        resource2: Second resource to compare
        tolerance_hours: Time tolerance for considering observations equivalent
        
    Returns:
        True if resources are clinically equivalent
        
    Raises:
        ValueError: If resources are invalid or different types
    """
    if not resource1 or not resource2:
        raise ValueError("Both resources are required")
    
    if resource1.resource_type != resource2.resource_type:
        raise ValueError("Resources must be of the same type")
    
    resource_type = resource1.resource_type
    
    # Use different comparison logic based on resource type
    if resource_type == "Patient":
        return _compare_patients(resource1, resource2)
    elif resource_type == "Observation":
        return _compare_observations(resource1, resource2, tolerance_hours)
    elif resource_type == "Condition":
        return _compare_conditions(resource1, resource2)
    elif resource_type == "MedicationStatement":
        return _compare_medications(resource1, resource2)
    elif resource_type == "DocumentReference":
        return _compare_document_references(resource1, resource2)
    elif resource_type == "Practitioner":
        return _compare_practitioners(resource1, resource2)
    else:
        # For unknown resource types, use hash comparison
        return get_resource_hash(resource1) == get_resource_hash(resource2)


def _compare_patients(patient1: PatientResource, patient2: PatientResource) -> bool:
    """
    Compare two patient resources for clinical equivalence.
    
    Args:
        patient1: First patient resource
        patient2: Second patient resource
        
    Returns:
        True if patients are clinically equivalent
    """
    # Compare MRN (most definitive identifier)
    mrn1 = patient1.get_mrn()
    mrn2 = patient2.get_mrn()
    
    # If both have MRNs, they must match
    if mrn1 and mrn2:
        return mrn1 == mrn2
    
    # If only one has MRN, fall back to name and birth date
    # If neither has MRN, also fall back to name and birth date
    name1 = patient1.get_display_name()
    name2 = patient2.get_display_name()
    
    birth1 = patient1.birthDate
    birth2 = patient2.birthDate
    
    return name1 == name2 and birth1 == birth2


def _compare_observations(
    obs1: ObservationResource,
    obs2: ObservationResource,
    tolerance_hours: int
) -> bool:
    """
    Compare two observation resources for clinical equivalence.
    
    Args:
        obs1: First observation resource
        obs2: Second observation resource
        tolerance_hours: Time tolerance for considering observations equivalent
        
    Returns:
        True if observations are clinically equivalent
    """
    # Compare test codes
    code1 = obs1.code.coding[0].code if obs1.code and obs1.code.coding else None
    code2 = obs2.code.coding[0].code if obs2.code and obs2.code.coding else None
    
    if code1 != code2:
        return False
    
    # Compare patient references using helper
    subj1 = getattr(obs1, 'subject', None)
    subj2 = getattr(obs2, 'subject', None)
    ref1 = get_reference_value(subj1)
    ref2 = get_reference_value(subj2)
    if ref1 != ref2:
        return False
    
    # Compare effective dates within tolerance
    if obs1.effectiveDateTime and obs2.effectiveDateTime:
        try:
            # Handle both datetime objects and strings
            if isinstance(obs1.effectiveDateTime, datetime):
                date1 = obs1.effectiveDateTime if obs1.effectiveDateTime.tzinfo else obs1.effectiveDateTime.replace(tzinfo=timezone.utc)
            else:
                date1 = datetime.fromisoformat(obs1.effectiveDateTime.replace('Z', '+00:00'))
                
            if isinstance(obs2.effectiveDateTime, datetime):
                date2 = obs2.effectiveDateTime if obs2.effectiveDateTime.tzinfo else obs2.effectiveDateTime.replace(tzinfo=timezone.utc)
            else:
                date2 = datetime.fromisoformat(obs2.effectiveDateTime.replace('Z', '+00:00'))
            
            time_diff = abs((date1 - date2).total_seconds() / 3600)  # Convert to hours
            
            if time_diff > tolerance_hours:
                return False
        except (ValueError, AttributeError, TypeError):
            # If date parsing fails, consider them different
            return False
    
    # Compare values
    # Value comparison with fallback
    value1 = getattr(obs1, 'get_value_with_unit', lambda: None)()
    if value1 is None and hasattr(obs1, 'valueQuantity') and obs1.valueQuantity:
        v = obs1.valueQuantity
        value1 = f"{getattr(v, 'value', None)} {getattr(v, 'unit', '')}".strip()
    value2 = getattr(obs2, 'get_value_with_unit', lambda: None)()
    if value2 is None and hasattr(obs2, 'valueQuantity') and obs2.valueQuantity:
        v = obs2.valueQuantity
        value2 = f"{getattr(v, 'value', None)} {getattr(v, 'unit', '')}".strip()
    
    return value1 == value2


def _compare_conditions(cond1: ConditionResource, cond2: ConditionResource) -> bool:
    """
    Compare two condition resources for clinical equivalence.
    
    Args:
        cond1: First condition resource
        cond2: Second condition resource
        
    Returns:
        True if conditions are clinically equivalent
    """
    # Compare condition codes - check multiple code representations
    # Try wrapper helper method first
    code1 = getattr(cond1, 'get_condition_code', lambda: None)()
    code2 = getattr(cond2, 'get_condition_code', lambda: None)()
    
    # Fallback to code.coding[0].code if available
    if code1 is None and getattr(cond1, 'code', None) and getattr(cond1.code, 'coding', None):
        code1 = cond1.code.coding[0].code
    if code2 is None and getattr(cond2, 'code', None) and getattr(cond2.code, 'coding', None):
        code2 = cond2.code.coding[0].code
    
    # Fallback to code.text if coding not available
    if code1 is None and getattr(cond1, 'code', None):
        code1 = getattr(cond1.code, 'text', None)
    if code2 is None and getattr(cond2, 'code', None):
        code2 = getattr(cond2.code, 'text', None)
    
    # If we still don't have codes, try dict access for code.text
    if code1 is None and hasattr(cond1, 'code') and isinstance(cond1.code, dict):
        code1 = cond1.code.get('text')
    if code2 is None and hasattr(cond2, 'code') and isinstance(cond2.code, dict):
        code2 = cond2.code.get('text')
    
    # Compare the extracted codes
    if code1 != code2:
        return False
    
    # Compare patient references
    subj1 = getattr(cond1, 'subject', None)
    subj2 = getattr(cond2, 'subject', None)
    ref1 = getattr(subj1, 'reference', None) if subj1 is not None and hasattr(subj1, 'reference') else (subj1.get('reference') if isinstance(subj1, dict) else None)
    ref2 = getattr(subj2, 'reference', None) if subj2 is not None and hasattr(subj2, 'reference') else (subj2.get('reference') if isinstance(subj2, dict) else None)
    if ref1 != ref2:
        return False
    
    # Compare clinical status
    status1 = cond1.clinicalStatus.coding[0].code if getattr(cond1, 'clinicalStatus', None) and cond1.clinicalStatus.coding else None
    status2 = cond2.clinicalStatus.coding[0].code if getattr(cond2, 'clinicalStatus', None) and cond2.clinicalStatus.coding else None
    
    return status1 == status2


def _compare_medications(med1: MedicationStatementResource, med2: MedicationStatementResource) -> bool:
    """
    Compare two medication statement resources for clinical equivalence.
    
    Args:
        med1: First medication statement resource
        med2: Second medication statement resource
        
    Returns:
        True if medication statements are clinically equivalent
    """
    # Compare medication names
    name1 = med1.get_medication_name()
    name2 = med2.get_medication_name()
    
    if name1 != name2:
        return False
    
    # Compare patient references
    if med1.subject != med2.subject:
        return False
    
    # Compare status
    if med1.status != med2.status:
        return False
    
    # Compare dosage text
    dosage1 = med1.get_dosage_text()
    dosage2 = med2.get_dosage_text()
    
    return dosage1 == dosage2


def _compare_document_references(doc1: DocumentReferenceResource, doc2: DocumentReferenceResource) -> bool:
    """
    Compare two document reference resources for clinical equivalence.
    
    Args:
        doc1: First document reference resource
        doc2: Second document reference resource
        
    Returns:
        True if document references are clinically equivalent
    """
    # Compare document URLs (most definitive identifier)
    url1 = doc1.get_document_url()
    url2 = doc2.get_document_url()
    
    if url1 and url2 and url1 == url2:
        return True
    
    # Compare patient references and document types
    if doc1.subject != doc2.subject:
        return False
    
    # Compare document types
    type1 = doc1.type.coding[0].code if doc1.type and doc1.type.coding else None
    type2 = doc2.type.coding[0].code if doc2.type and doc2.type.coding else None
    
    return type1 == type2


def _compare_practitioners(prac1: PractitionerResource, prac2: PractitionerResource) -> bool:
    """
    Compare two practitioner resources for clinical equivalence.
    
    Args:
        prac1: First practitioner resource
        prac2: Second practitioner resource
        
    Returns:
        True if practitioners are clinically equivalent
    """
    # Compare NPI (most definitive identifier)
    npi1 = prac1.get_npi()
    npi2 = prac2.get_npi()
    
    if npi1 and npi2 and npi1 == npi2:
        return True
    
    # Compare names
    name1 = prac1.get_display_name()
    name2 = prac2.get_display_name()
    
    return name1 == name2


def find_duplicate_resources(bundle: Bundle) -> List[Dict[str, Any]]:
    """
    Find duplicate resources in a bundle based on clinical equivalence.
    
    Args:
        bundle: FHIR Bundle to check for duplicates
        
    Returns:
        List of duplicate resource groups with details
        
    Raises:
        ValueError: If bundle is invalid
    """
    if not bundle:
        raise ValueError("Bundle is required")
    
    if not bundle.entry:
        return []
    
    duplicates = []
    
    # Group resources by type
    resource_groups = {}
    for entry in bundle.entry:
        if entry.resource:
            resource_type = entry.resource.resource_type
            if resource_type not in resource_groups:
                resource_groups[resource_type] = []
            resource_groups[resource_type].append(entry.resource)
    
    # Check for duplicates within each resource type
    for resource_type, resources in resource_groups.items():
        if len(resources) < 2:
            continue
            
        # Compare each resource with every other resource
        for i in range(len(resources)):
            duplicate_group = [resources[i]]
            
            for j in range(i + 1, len(resources)):
                try:
                    if are_resources_clinically_equivalent(resources[i], resources[j]):
                        duplicate_group.append(resources[j])
                except ValueError:
                    # Skip comparison if resources are incompatible
                    continue
            
            # If we found duplicates, add to results
            if len(duplicate_group) > 1:
                duplicates.append({
                    "resource_type": resource_type,
                    "duplicate_count": len(duplicate_group),
                    "resources": duplicate_group,
                    "recommended_action": "merge"
                })
    
    return duplicates


def deduplicate_bundle(bundle: Bundle, keep_latest: bool = True) -> Bundle:
    """
    Remove duplicate resources from a bundle, keeping the latest version.
    
    Args:
        bundle: FHIR Bundle to deduplicate
        keep_latest: If True, keep the latest version; if False, keep the first
        
    Returns:
        Bundle with duplicates removed
        
    Raises:
        ValueError: If bundle is invalid
    """
    if not bundle:
        raise ValueError("Bundle is required")
    
    if not bundle.entry:
        return bundle
    
    # Find duplicates
    duplicates = find_duplicate_resources(bundle)
    
    if not duplicates:
        return bundle
    
    # Create a set of resource IDs to remove
    resources_to_remove = set()
    
    for duplicate_group in duplicates:
        resources = duplicate_group["resources"]
        
        if keep_latest:
            # Sort by lastUpdated timestamp (most recent first)
            sorted_resources = sorted(
                resources,
                key=lambda r: r.meta.lastUpdated if r.meta and r.meta.lastUpdated else "1970-01-01T00:00:00Z",
                reverse=True
            )
            # Remove all but the first (latest)
            for resource in sorted_resources[1:]:
                resources_to_remove.add(resource.id)
        else:
            # Keep the first, remove the rest
            for resource in resources[1:]:
                resources_to_remove.add(resource.id)
    
    # Create new bundle without the duplicate resources
    deduplicated_entries = []
    for entry in bundle.entry:
        if entry.resource and entry.resource.id not in resources_to_remove:
            deduplicated_entries.append(entry)
    
    # Update bundle
    bundle.entry = deduplicated_entries
    
    # Update bundle metadata
    bundle = update_resource_version(bundle)
    
    return bundle


def get_resource_version_history(
    bundle: Bundle,
    resource_type: str,
    resource_id: str
) -> List[Resource]:
    """
    Get the version history for a specific resource in a bundle.
    
    Args:
        bundle: FHIR Bundle to search
        resource_type: Type of resource to find
        resource_id: ID of the resource
        
    Returns:
        List of resource versions sorted by version (latest first)
        
    Raises:
        ValueError: If bundle is invalid or parameters are missing
    """
    if not bundle:
        raise ValueError("Bundle is required")
    
    if not resource_type or not resource_id:
        raise ValueError("Resource type and ID are required")
    
    if not bundle.entry:
        return []
    
    # Find all versions of the resource
    versions = []
    
    for entry in bundle.entry:
        if (entry.resource and 
            entry.resource.resource_type == resource_type and 
            entry.resource.id == resource_id):
            versions.append(entry.resource)
    
    # Sort by version ID (latest first)
    # Handle both integer versions and historical versions like "1.historical"
    def get_sort_key(resource):
        if not resource.meta or not resource.meta.versionId:
            return 0
        
        version_str = str(resource.meta.versionId)
        # Extract the numeric part before any period
        numeric_part = version_str.split('.')[0]
        try:
            return int(numeric_part)
        except (ValueError, TypeError):
            return 0
    
    versions.sort(key=get_sort_key, reverse=True)
    
    return versions


def get_latest_resource_version(
    bundle: Bundle,
    resource_type: str,
    resource_id: str
) -> Optional[Resource]:
    """
    Get the latest version of a specific resource from a bundle.
    
    Args:
        bundle: FHIR Bundle to search
        resource_type: Type of resource to find
        resource_id: ID of the resource
        
    Returns:
        Latest version of the resource or None if not found
        
    Raises:
        ValueError: If bundle is invalid or parameters are missing
    """
    versions = get_resource_version_history(bundle, resource_type, resource_id)
    
    return versions[0] if versions else None


# =============================================================================
# Resource Provenance Tracking Functions  
# =============================================================================

def add_resource_with_provenance(
    bundle: Bundle,
    resource: Resource,
    source_system: str,
    responsible_party: Optional[str] = None,
    reason: Optional[str] = None,
    source_document_id: Optional[str] = None,
    update_existing: bool = True
) -> Bundle:
    """
    Add a resource to the bundle along with its provenance tracking information.
    
    Args:
        bundle: Existing FHIR Bundle
        resource: FHIR resource to add
        source_system: Identifier for the source system
        responsible_party: Optional identifier for responsible person/system
        reason: Optional reason for adding the resource
        source_document_id: Optional ID of source document
        update_existing: If True, update existing resource; if False, create new entry
        
    Returns:
        Updated FHIR Bundle with resource and provenance
        
    Raises:
        ValueError: If bundle, resource, or source_system is invalid
    """
    if not bundle:
        raise ValueError("Bundle is required")
    
    if not resource:
        raise ValueError("Resource is required")
    
    if not source_system or not source_system.strip():
        raise ValueError("Source system is required")
    
    # Check if this is an update to existing resource
    existing_provenance = None
    if update_existing:
        existing_provenance = find_resource_provenance(bundle, resource.resource_type, resource.id)
    
    # Add the resource to the bundle
    bundle = add_resource_to_bundle(bundle, resource, update_existing)
    
    # Create appropriate provenance
    if existing_provenance:
        # This is an update - create update provenance with chain
        provenance = ProvenanceResource.create_for_update(
            target_resource=resource,
            previous_provenance=existing_provenance,
            responsible_party=responsible_party,
            reason=reason or "Resource updated"
        )
    else:
        # This is a new resource - create initial provenance
        provenance = ProvenanceResource.create_for_resource(
            target_resource=resource,
            source_system=source_system,
            responsible_party=responsible_party,
            activity_type="create",
            reason=reason or "Resource created",
            source_document_id=source_document_id
        )
    
    # Add provenance to bundle
    bundle = add_resource_to_bundle(bundle, provenance, False)  # Always create new provenance entry
    
    return bundle


def find_resource_provenance(
    bundle: Bundle,
    resource_type: str,
    resource_id: str
) -> Optional[ProvenanceResource]:
    """
    Find the most recent provenance resource for a specific target resource.
    
    Args:
        bundle: FHIR Bundle to search
        resource_type: Type of the target resource
        resource_id: ID of the target resource
        
    Returns:
        Most recent ProvenanceResource or None if not found
        
    Raises:
        ValueError: If bundle, resource_type, or resource_id is invalid
    """
    if not bundle:
        raise ValueError("Bundle is required")
    
    if not resource_type or not resource_type.strip():
        raise ValueError("Resource type is required")
    
    if not resource_id or not resource_id.strip():
        raise ValueError("Resource ID is required")
    
    target_reference = f"{resource_type.strip()}/{resource_id.strip()}"
    
    # Get all provenance resources
    provenance_resources = get_resources_by_type(bundle, "Provenance")
    
    # Find provenance resources targeting our resource
    matching_provenances = []
    for provenance in provenance_resources:
        if isinstance(provenance, ProvenanceResource):
            target_ref = provenance.get_target_reference()
            if target_ref == target_reference:
                matching_provenances.append(provenance)
    
    # Return the most recent one (highest version or latest timestamp)
    if not matching_provenances:
        return None
    
    # Sort by timestamp (most recent first)
    matching_provenances.sort(
        key=lambda p: p.recorded if p.recorded else "",
        reverse=True
    )
    
    return matching_provenances[0]


def get_provenance_chain(
    bundle: Bundle,
    resource_type: str,
    resource_id: str
) -> List[ProvenanceResource]:
    """
    Get the complete provenance chain for a specific resource.
    
    Args:
        bundle: FHIR Bundle to search
        resource_type: Type of the target resource
        resource_id: ID of the target resource
        
    Returns:
        List of ProvenanceResource objects in chronological order (oldest first)
        
    Raises:
        ValueError: If bundle, resource_type, or resource_id is invalid
    """
    if not bundle:
        raise ValueError("Bundle is required")
    
    if not resource_type or not resource_type.strip():
        raise ValueError("Resource type is required")
    
    if not resource_id or not resource_id.strip():
        raise ValueError("Resource ID is required")
    
    # Find the most recent provenance
    current_provenance = find_resource_provenance(bundle, resource_type, resource_id)
    
    if not current_provenance:
        return []
    
    # Build chain by following previous provenance references
    provenance_chain = [current_provenance]
    
    while True:
        previous_id = current_provenance.get_previous_provenance_id()
        if not previous_id:
            break
            
        # Find the previous provenance in the bundle
        previous_provenance = None
        provenance_resources = get_resources_by_type(bundle, "Provenance")
        
        for provenance in provenance_resources:
            if isinstance(provenance, ProvenanceResource) and provenance.id == previous_id:
                previous_provenance = provenance
                break
        
        if not previous_provenance:
            break
            
        provenance_chain.append(previous_provenance)
        current_provenance = previous_provenance
    
    # Return in chronological order (oldest first)
    provenance_chain.reverse()
    return provenance_chain


def get_provenance_summary(
    bundle: Bundle,
    resource_type: str,
    resource_id: str
) -> Dict[str, Any]:
    """
    Get a summary of provenance information for a specific resource.
    
    Args:
        bundle: FHIR Bundle to search
        resource_type: Type of the target resource
        resource_id: ID of the target resource
        
    Returns:
        Dictionary with provenance summary information
        
    Raises:
        ValueError: If bundle, resource_type, or resource_id is invalid
    """
    if not bundle:
        raise ValueError("Bundle is required")
    
    if not resource_type or not resource_type.strip():
        raise ValueError("Resource type is required")
    
    if not resource_id or not resource_id.strip():
        raise ValueError("Resource ID is required")
    
    target_reference = f"{resource_type.strip()}/{resource_id.strip()}"
    
    # Get provenance chain
    provenance_chain = get_provenance_chain(bundle, resource_type, resource_id)
    
    if not provenance_chain:
        return {
            "target_resource": target_reference,
            "has_provenance": False,
            "chain_length": 0,
            "activities": [],
            "source_systems": [],
            "responsible_parties": []
        }
    
    # Extract information from chain
    activities = []
    source_systems = set()
    responsible_parties = set()
    
    for provenance in provenance_chain:
        activity_info = {
            "id": provenance.id,
            "activity_type": provenance.get_activity_type(),
            "occurred_at": provenance.occurredDateTime,
            "recorded_at": provenance.recorded,
            "source_system": provenance.get_source_system(),
            "responsible_party": provenance.get_responsible_party(),
            "source_document_id": provenance.get_source_document_id()
        }
        activities.append(activity_info)
        
        if activity_info["source_system"]:
            source_systems.add(activity_info["source_system"])
        if activity_info["responsible_party"]:
            responsible_parties.add(activity_info["responsible_party"])
    
    return {
        "target_resource": target_reference,
        "has_provenance": True,
        "chain_length": len(provenance_chain),
        "created_at": provenance_chain[0].occurredDateTime if provenance_chain else None,
        "last_updated_at": provenance_chain[-1].occurredDateTime if provenance_chain else None,
        "activities": activities,
        "source_systems": list(source_systems),
        "responsible_parties": list(responsible_parties)
    }


def get_all_provenance_resources(bundle: Bundle) -> List[ProvenanceResource]:
    """
    Get all provenance resources from the bundle.
    
    Args:
        bundle: FHIR Bundle to search
        
    Returns:
        List of all ProvenanceResource objects in the bundle
        
    Raises:
        ValueError: If bundle is invalid
    """
    if not bundle:
        raise ValueError("Bundle is required")
    
    provenance_resources = get_resources_by_type(bundle, "Provenance")
    return [p for p in provenance_resources if isinstance(p, ProvenanceResource)]


def validate_provenance_integrity(bundle: Bundle) -> Dict[str, Any]:
    """
    Validate the integrity of provenance tracking in the bundle.
    
    Args:
        bundle: FHIR Bundle to validate
        
    Returns:
        Dictionary with validation results and any issues found
        
    Raises:
        ValueError: If bundle is invalid
    """
    if not bundle:
        raise ValueError("Bundle is required")
    
    validation_result = {
        "is_valid": True,
        "issues": [],
        "total_provenance_resources": 0,
        "resources_with_provenance": 0,
        "resources_without_provenance": 0,
        "orphaned_provenance": 0,
        "broken_chains": 0
    }
    
    # Get all resources and provenance
    all_provenance = get_all_provenance_resources(bundle)
    validation_result["total_provenance_resources"] = len(all_provenance)
    
    if not bundle.entry:
        return validation_result
    
    # Check each non-provenance resource for provenance
    resources_with_provenance = set()
    provenance_targets = set()
    
    for provenance in all_provenance:
        target_ref = provenance.get_target_reference()
        if target_ref:
            provenance_targets.add(target_ref)
            resources_with_provenance.add(target_ref)
        
        # Validate provenance structure
        if not target_ref:
            validation_result["issues"].append(f"Provenance {provenance.id} missing target reference")
            validation_result["is_valid"] = False
        
        if not provenance.get_source_system():
            validation_result["issues"].append(f"Provenance {provenance.id} missing source system")
            validation_result["is_valid"] = False
    
    # Check for resources without provenance
    all_resources = set()
    for entry in bundle.entry:
        if entry.resource and entry.resource.resource_type != "Provenance":
            resource_ref = f"{entry.resource.resource_type}/{entry.resource.id}"
            all_resources.add(resource_ref)
    
    resources_without_provenance = all_resources - resources_with_provenance
    validation_result["resources_with_provenance"] = len(resources_with_provenance)
    validation_result["resources_without_provenance"] = len(resources_without_provenance)
    
    # Check for orphaned provenance (targeting non-existent resources)
    orphaned_targets = provenance_targets - all_resources
    validation_result["orphaned_provenance"] = len(orphaned_targets)
    
    if orphaned_targets:
        validation_result["issues"].extend([
            f"Orphaned provenance targeting non-existent resource: {target}"
            for target in orphaned_targets
        ])
        validation_result["is_valid"] = False
    
    # Check for broken provenance chains
    for provenance in all_provenance:
        previous_id = provenance.get_previous_provenance_id()
        if previous_id:
            # Check if referenced provenance exists
            previous_exists = any(p.id == previous_id for p in all_provenance)
            if not previous_exists:
                validation_result["issues"].append(
                    f"Provenance {provenance.id} references non-existent previous provenance {previous_id}"
                )
                validation_result["broken_chains"] += 1
                validation_result["is_valid"] = False
    
    return validation_result


# =============================================================================
# Patient Summary Generation Functions
# =============================================================================

def generate_patient_summary(
    bundle: Bundle,
    patient_id: str,
    date_range: Optional[Tuple[datetime, datetime]] = None,
    clinical_domains: Optional[List[str]] = None,
    max_items_per_domain: int = 10
) -> Dict[str, Any]:
    """
    Generate a comprehensive patient summary from FHIR bundle data.
    
    Args:
        bundle: FHIR Bundle containing patient data
        patient_id: ID of the patient to generate summary for
        date_range: Optional tuple of (start_date, end_date) for filtering
        clinical_domains: Optional list of domains to include 
                         (e.g., ['conditions', 'medications', 'observations'])
        max_items_per_domain: Maximum number of items to include per domain
        
    Returns:
        Dictionary containing structured patient summary
        
    Raises:
        ValueError: If bundle is invalid or patient not found
    """
    if not bundle:
        raise ValueError("Bundle is required")
    
    if not patient_id:
        raise ValueError("Patient ID is required")
    
    # Find the patient resource
    patient_resources = get_resources_by_type(bundle, "Patient")
    patient = None
    
    for resource in patient_resources:
        if resource.id == patient_id:
            patient = resource
            break
    
    if not patient:
        raise ValueError(f"Patient with ID {patient_id} not found in bundle")
    
    # Default to all clinical domains if not specified
    if not clinical_domains:
        clinical_domains = ['demographics', 'conditions', 'medications', 'observations', 'documents']
    
    summary = {
        'patient_id': patient_id,
        'generated_at': datetime.utcnow().isoformat() + "Z",
        'date_range': {
            'start': date_range[0].isoformat() + "Z" if date_range and date_range[0] else None,
            'end': date_range[1].isoformat() + "Z" if date_range and date_range[1] else None
        },
        'clinical_domains': clinical_domains,
        'data': {}
    }
    
    # Generate each requested domain
    if 'demographics' in clinical_domains:
        summary['data']['demographics'] = _extract_demographics(patient)
    
    if 'conditions' in clinical_domains:
        summary['data']['conditions'] = _extract_conditions_summary(
            bundle, patient_id, date_range, max_items_per_domain
        )
    
    if 'medications' in clinical_domains:
        summary['data']['medications'] = _extract_medications_summary(
            bundle, patient_id, date_range, max_items_per_domain
        )
    
    if 'observations' in clinical_domains:
        summary['data']['observations'] = _extract_observations_summary(
            bundle, patient_id, date_range, max_items_per_domain
        )
    
    if 'documents' in clinical_domains:
        summary['data']['documents'] = _extract_documents_summary(
            bundle, patient_id, date_range, max_items_per_domain
        )
    
    if 'practitioners' in clinical_domains:
        summary['data']['practitioners'] = _extract_practitioners_summary(bundle)
    
    return summary


def _extract_demographics(patient: PatientResource) -> Dict[str, Any]:
    """
    Extract demographic information from patient resource.
    
    Args:
        patient: Patient resource
        
    Returns:
        Dictionary with demographic information
    """
    demographics = {
        'name': patient.get_display_name(),
        'mrn': patient.get_mrn(),
        'birth_date': patient.birthDate if hasattr(patient, 'birthDate') else None,
        'gender': patient.gender if hasattr(patient, 'gender') else None,
        'contact_info': {},
        'address': None
    }
    
    # Extract contact information
    if hasattr(patient, 'telecom') and patient.telecom:
        for contact in patient.telecom:
            if contact.system == "phone":
                demographics['contact_info']['phone'] = contact.value
            elif contact.system == "email":
                demographics['contact_info']['email'] = contact.value
    
    # Extract address
    if hasattr(patient, 'address') and patient.address and len(patient.address) > 0:
        address = patient.address[0]
        demographics['address'] = {
            'line': address.line[0] if address.line else None,
            'city': address.city if hasattr(address, 'city') else None,
            'state': address.state if hasattr(address, 'state') else None,
            'postal_code': address.postalCode if hasattr(address, 'postalCode') else None
        }
    
    return demographics


def _extract_conditions_summary(
    bundle: Bundle,
    patient_id: str,
    date_range: Optional[Tuple[datetime, datetime]] = None,
    max_items: int = 10
) -> Dict[str, Any]:
    """
    Extract and prioritize conditions from the bundle.
    
    Args:
        bundle: FHIR Bundle
        patient_id: Patient ID
        date_range: Optional date range filter
        max_items: Maximum number of conditions to return
        
    Returns:
        Dictionary with conditions summary
    """
    conditions_resources = get_resources_by_type(bundle, "Condition")
    
    # Filter for this patient
    patient_conditions = []
    for condition in conditions_resources:
        if condition.subject and condition.subject.reference == f"Patient/{patient_id}":
            patient_conditions.append(condition)
    
    # Apply date filter if provided
    if date_range:
        filtered_conditions = []
        for condition in patient_conditions:
            condition_date = _get_condition_date(condition)
            if condition_date and date_range[0] <= condition_date <= date_range[1]:
                filtered_conditions.append(condition)
        patient_conditions = filtered_conditions
    
    # Sort by clinical relevance (active first, then by date)
    patient_conditions.sort(key=lambda c: (
        _get_condition_priority(c),
        _get_condition_date(c) or datetime.min
    ), reverse=True)
    
    # Limit results
    patient_conditions = patient_conditions[:max_items]
    
    # Format for summary
    conditions_summary = {
        'total_count': len(patient_conditions),
        'active_count': len([c for c in patient_conditions if _is_condition_active(c)]),
        'items': []
    }
    
    for condition in patient_conditions:
        condition_item = {
            'id': condition.id,
            'code': condition.get_condition_code() if hasattr(condition, 'get_condition_code') else None,
            'display': condition.get_condition_display() if hasattr(condition, 'get_condition_display') else None,
            'clinical_status': _get_condition_status(condition),
            'onset_date': _get_condition_date(condition).isoformat() + "Z" if _get_condition_date(condition) else None,
            'severity': _get_condition_severity(condition),
            'last_updated': condition.meta.lastUpdated if condition.meta else None
        }
        conditions_summary['items'].append(condition_item)
    
    return conditions_summary


def _extract_medications_summary(
    bundle: Bundle,
    patient_id: str,
    date_range: Optional[Tuple[datetime, datetime]] = None,
    max_items: int = 10
) -> Dict[str, Any]:
    """
    Extract and prioritize medications from the bundle.
    
    Args:
        bundle: FHIR Bundle
        patient_id: Patient ID
        date_range: Optional date range filter
        max_items: Maximum number of medications to return
        
    Returns:
        Dictionary with medications summary
    """
    medication_resources = get_resources_by_type(bundle, "MedicationStatement")
    
    # Filter for this patient
    patient_medications = []
    for medication in medication_resources:
        if medication.subject and medication.subject.reference == f"Patient/{patient_id}":
            patient_medications.append(medication)
    
    # Apply date filter if provided
    if date_range:
        filtered_medications = []
        for medication in patient_medications:
            med_date = _get_medication_date(medication)
            if med_date and date_range[0] <= med_date <= date_range[1]:
                filtered_medications.append(medication)
        patient_medications = filtered_medications
    
    # Sort by status (active first) and date
    patient_medications.sort(key=lambda m: (
        _get_medication_priority(m),
        _get_medication_date(m) or datetime.min
    ), reverse=True)
    
    # Limit results
    patient_medications = patient_medications[:max_items]
    
    # Format for summary
    medications_summary = {
        'total_count': len(patient_medications),
        'active_count': len([m for m in patient_medications if _is_medication_active(m)]),
        'items': []
    }
    
    for medication in patient_medications:
        medication_item = {
            'id': medication.id,
            'name': medication.get_medication_name() if hasattr(medication, 'get_medication_name') else None,
            'status': _get_medication_status(medication),
            'dosage': medication.get_dosage_text() if hasattr(medication, 'get_dosage_text') else None,
            'effective_date': _get_medication_date(medication).isoformat() + "Z" if _get_medication_date(medication) else None,
            'last_updated': medication.meta.lastUpdated if medication.meta else None
        }
        medications_summary['items'].append(medication_item)
    
    return medications_summary


def _extract_observations_summary(
    bundle: Bundle,
    patient_id: str,
    date_range: Optional[Tuple[datetime, datetime]] = None,
    max_items: int = 10
) -> Dict[str, Any]:
    """
    Extract and prioritize observations from the bundle.
    
    Args:
        bundle: FHIR Bundle
        patient_id: Patient ID
        date_range: Optional date range filter
        max_items: Maximum number of observations to return
        
    Returns:
        Dictionary with observations summary
    """
    observation_resources = get_resources_by_type(bundle, "Observation")
    
    # Filter for this patient
    patient_observations = []
    for observation in observation_resources:
        if observation.subject and observation.subject.reference == f"Patient/{patient_id}":
            patient_observations.append(observation)
    
    # Apply date filter if provided
    if date_range:
        filtered_observations = []
        for observation in patient_observations:
            obs_date = _get_observation_date(observation)
            if obs_date:
                # Normalize to timezone-aware
                if obs_date.tzinfo is None:
                    obs_date = obs_date.replace(tzinfo=timezone.utc)
                start = date_range[0].replace(tzinfo=timezone.utc) if date_range[0].tzinfo is None else date_range[0]
                end = date_range[1].replace(tzinfo=timezone.utc) if date_range[1].tzinfo is None else date_range[1]
                if start <= obs_date <= end:
                    filtered_observations.append(observation)
        patient_observations = filtered_observations
    
    # Sort by date (most recent first)
    patient_observations.sort(key=lambda o: _get_observation_date(o) or datetime.min, reverse=True)
    
    # Group by test type and get latest for each
    observation_groups = {}
    for observation in patient_observations:
        test_name = observation.get_test_name() if hasattr(observation, 'get_test_name') else 'Unknown'
        if test_name not in observation_groups:
            observation_groups[test_name] = []
        observation_groups[test_name].append(observation)
    
    # Get most recent observation for each test type
    recent_observations = []
    for test_name, obs_list in observation_groups.items():
        # Sort by date and take the most recent
        obs_list.sort(key=lambda o: _get_observation_date(o) or datetime.min, reverse=True)
        recent_observations.append(obs_list[0])
    
    # Sort by clinical priority and limit
    recent_observations.sort(key=lambda o: (
        _get_observation_priority(o),
        _get_observation_date(o) or datetime.min
    ), reverse=True)
    
    recent_observations = recent_observations[:max_items]
    
    # Format for summary
    observations_summary = {
        'total_count': len(patient_observations),
        'unique_tests': len(observation_groups),
        'items': []
    }
    
    for observation in recent_observations:
        observation_item = {
            'id': observation.id,
            'test_name': observation.get_test_name() if hasattr(observation, 'get_test_name') else 'Unknown',
            'value': observation.get_value_with_unit() if hasattr(observation, 'get_value_with_unit') else 'No value',
            'status': observation.status if hasattr(observation, 'status') else 'unknown',
            'effective_date': _get_observation_date(observation).isoformat() + "Z" if _get_observation_date(observation) else None,
            'category': _get_observation_category(observation),
            'last_updated': observation.meta.lastUpdated if observation.meta else None
        }
        observations_summary['items'].append(observation_item)
    
    return observations_summary


def _extract_documents_summary(
    bundle: Bundle,
    patient_id: str,
    date_range: Optional[Tuple[datetime, datetime]] = None,
    max_items: int = 10
) -> Dict[str, Any]:
    """
    Extract and prioritize documents from the bundle.
    
    Args:
        bundle: FHIR Bundle
        patient_id: Patient ID
        date_range: Optional date range filter
        max_items: Maximum number of documents to return
        
    Returns:
        Dictionary with documents summary
    """
    document_resources = get_resources_by_type(bundle, "DocumentReference")
    
    # Filter for this patient
    patient_documents = []
    for document in document_resources:
        if document.subject and document.subject.reference == f"Patient/{patient_id}":
            patient_documents.append(document)
    
    # Apply date filter if provided
    if date_range:
        filtered_documents = []
        for document in patient_documents:
            doc_date = _get_document_date(document)
            if doc_date and date_range[0] <= doc_date <= date_range[1]:
                filtered_documents.append(document)
        patient_documents = filtered_documents
    
    # Sort by date (most recent first)
    patient_documents.sort(key=lambda d: (_get_document_date(d) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    
    # Limit results
    patient_documents = patient_documents[:max_items]
    
    # Format for summary
    documents_summary = {
        'total_count': len(patient_documents),
        'items': []
    }
    
    for document in patient_documents:
        document_item = {
            'id': document.id,
            'title': _get_document_title(document),
            'type': _get_document_type(document),
            'date': _get_document_date(document).isoformat() + "Z" if _get_document_date(document) else None,
            'status': document.status if hasattr(document, 'status') else 'unknown',
            'url': document.get_document_url() if hasattr(document, 'get_document_url') else None,
            'last_updated': document.meta.lastUpdated if document.meta else None
        }
        documents_summary['items'].append(document_item)
    
    return documents_summary


def _extract_practitioners_summary(bundle: Bundle) -> Dict[str, Any]:
    """
    Extract practitioners from the bundle.
    
    Args:
        bundle: FHIR Bundle
        
    Returns:
        Dictionary with practitioners summary
    """
    practitioner_resources = get_resources_by_type(bundle, "Practitioner")
    
    practitioners_summary = {
        'total_count': len(practitioner_resources),
        'items': []
    }
    
    for practitioner in practitioner_resources:
        practitioner_item = {
            'id': practitioner.id,
            'name': practitioner.get_display_name() if hasattr(practitioner, 'get_display_name') else 'Unknown',
            'npi': practitioner.get_npi() if hasattr(practitioner, 'get_npi') else None,
            'specialties': _get_practitioner_specialties(practitioner),
            'last_updated': practitioner.meta.lastUpdated if practitioner.meta else None
        }
        practitioners_summary['items'].append(practitioner_item)
    
    return practitioners_summary


# =============================================================================
# Helper Functions for Data Extraction
# =============================================================================

def _get_condition_date(condition: ConditionResource) -> Optional[datetime]:
    """Get the most relevant date for a condition."""
    if hasattr(condition, 'onsetDateTime') and condition.onsetDateTime:
        try:
            date_str = str(condition.onsetDateTime)
            if date_str.endswith('Z'):
                date_str = date_str.replace('Z', '+00:00')
            return datetime.fromisoformat(date_str)
        except (ValueError, AttributeError):
            pass
    
    # Fall back to meta.lastUpdated
    if condition.meta and condition.meta.lastUpdated:
        try:
            date_str = str(condition.meta.lastUpdated)
            if date_str.endswith('Z'):
                date_str = date_str.replace('Z', '+00:00')
            return datetime.fromisoformat(date_str)
        except (ValueError, AttributeError):
            pass
    
    return None


def _get_condition_priority(condition: ConditionResource) -> int:
    """Get priority score for condition sorting (higher = more important)."""
    if _is_condition_active(condition):
        return 100  # Active conditions highest priority
    else:
        return 50   # Resolved conditions lower priority


def _is_condition_active(condition: ConditionResource) -> bool:
    """Check if condition is currently active."""
    if hasattr(condition, 'clinicalStatus') and condition.clinicalStatus:
        if condition.clinicalStatus.coding:
            status_code = condition.clinicalStatus.coding[0].code
            return status_code in ['active', 'recurring']
    return False


def _get_condition_status(condition: ConditionResource) -> str:
    """Get the clinical status of a condition."""
    if hasattr(condition, 'clinicalStatus') and condition.clinicalStatus:
        if condition.clinicalStatus.coding:
            return condition.clinicalStatus.coding[0].code
    return 'unknown'


def _get_condition_severity(condition: ConditionResource) -> Optional[str]:
    """Get the severity of a condition."""
    if hasattr(condition, 'severity') and condition.severity:
        if condition.severity.coding:
            return condition.severity.coding[0].display
    return None


def _get_medication_date(medication: MedicationStatementResource) -> Optional[datetime]:
    """Get the most relevant date for a medication."""
    if hasattr(medication, 'effectiveDateTime') and medication.effectiveDateTime:
        try:
            date_str = str(medication.effectiveDateTime)
            if date_str.endswith('Z'):
                date_str = date_str.replace('Z', '+00:00')
            return datetime.fromisoformat(date_str)
        except (ValueError, AttributeError):
            pass
    
    # Fall back to meta.lastUpdated
    if medication.meta and medication.meta.lastUpdated:
        try:
            date_str = str(medication.meta.lastUpdated)
            if date_str.endswith('Z'):
                date_str = date_str.replace('Z', '+00:00')
            return datetime.fromisoformat(date_str)
        except (ValueError, AttributeError):
            pass
    
    return None


def _get_medication_priority(medication: MedicationStatementResource) -> int:
    """Get priority score for medication sorting (higher = more important)."""
    if _is_medication_active(medication):
        return 100  # Active medications highest priority
    else:
        return 50   # Stopped medications lower priority


def _is_medication_active(medication: MedicationStatementResource) -> bool:
    """Check if medication is currently active."""
    if hasattr(medication, 'status') and medication.status:
        return medication.status in ['active', 'intended']
    return False


def _get_medication_status(medication: MedicationStatementResource) -> str:
    """Get the status of a medication."""
    if hasattr(medication, 'status') and medication.status:
        return medication.status
    return 'unknown'


def _get_observation_date(observation: ObservationResource) -> Optional[datetime]:
    """Get the most relevant date for an observation."""
    if hasattr(observation, 'effectiveDateTime') and observation.effectiveDateTime:
        try:
            date_str = str(observation.effectiveDateTime)
            if date_str.endswith('Z'):
                date_str = date_str.replace('Z', '+00:00')
            return datetime.fromisoformat(date_str)
        except (ValueError, AttributeError):
            pass
    
    # Fall back to meta.lastUpdated
    if observation.meta and observation.meta.lastUpdated:
        try:
            date_str = str(observation.meta.lastUpdated)
            if date_str.endswith('Z'):
                date_str = date_str.replace('Z', '+00:00')
            return datetime.fromisoformat(date_str)
        except (ValueError, AttributeError):
            pass
    
    return None


def _get_observation_priority(observation: ObservationResource) -> int:
    """Get priority score for observation sorting (higher = more important)."""
    # Prioritize by test type - labs and vitals are more important
    test_name = observation.get_test_name() if hasattr(observation, 'get_test_name') else ''
    test_name_lower = test_name.lower()
    
    # High priority lab values
    if any(keyword in test_name_lower for keyword in ['glucose', 'hemoglobin', 'creatinine', 'cholesterol']):
        return 90
    
    # Vital signs
    if any(keyword in test_name_lower for keyword in ['blood pressure', 'heart rate', 'temperature', 'weight']):
        return 85
    
    # Other lab results
    if any(keyword in test_name_lower for keyword in ['lab', 'test', 'level']):
        return 80
    
    # Default priority
    return 50


def _get_observation_category(observation: ObservationResource) -> str:
    """Get the category of an observation."""
    if hasattr(observation, 'category') and observation.category:
        for category in observation.category:
            if category.coding:
                return category.coding[0].display or category.coding[0].code
    return 'unknown'


def _get_document_date(document: DocumentReferenceResource) -> Optional[datetime]:
    """Get the most relevant date for a document."""
    if hasattr(document, 'date') and document.date:
        try:
            date_str = str(document.date)
            if date_str.endswith('Z'):
                date_str = date_str.replace('Z', '+00:00')
            return datetime.fromisoformat(date_str)
        except (ValueError, AttributeError):
            pass
    
    # Fall back to meta.lastUpdated
    if document.meta and document.meta.lastUpdated:
        try:
            date_str = str(document.meta.lastUpdated)
            if date_str.endswith('Z'):
                date_str = date_str.replace('Z', '+00:00')
            return datetime.fromisoformat(date_str)
        except (ValueError, AttributeError):
            pass
    
    return None


def _get_document_title(document: DocumentReferenceResource) -> str:
    """Get the title of a document."""
    if hasattr(document, 'content') and document.content:
        for content in document.content:
            # Handle FHIR DocumentReferenceContent object
            if hasattr(content, 'attachment') and content.attachment:
                attachment = content.attachment
                if hasattr(attachment, 'title') and attachment.title:
                    return attachment.title
    
    if hasattr(document, 'type') and document.type:
        if document.type.coding:
            return document.type.coding[0].display or document.type.coding[0].code
    
    return 'Unknown Document'


def _get_document_type(document: DocumentReferenceResource) -> str:
    """Get the type of a document."""
    if hasattr(document, 'type') and document.type:
        if document.type.coding:
            return document.type.coding[0].code or document.type.coding[0].display
    return 'unknown'


def _get_practitioner_specialties(practitioner: PractitionerResource) -> List[str]:
    """Get the specialties of a practitioner."""
    specialties = []
    if hasattr(practitioner, 'qualification') and practitioner.qualification:
        for qualification in practitioner.qualification:
            if qualification.code and qualification.code.coding:
                for coding in qualification.code.coding:
                    if coding.display:
                        specialties.append(coding.display)
    return specialties


def generate_clinical_summary_report(
    bundle: Bundle,
    patient_id: str,
    report_type: str = "comprehensive"
) -> Dict[str, Any]:
    """
    Generate a clinical summary report optimized for healthcare providers.
    
    Args:
        bundle: FHIR Bundle containing patient data
        patient_id: ID of the patient
        report_type: Type of report ('comprehensive', 'recent', 'problems_focused')
        
    Returns:
        Dictionary containing clinical summary report
    """
    # Set date range and domains based on report type
    if report_type == "recent":
        # Last 30 days
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        date_range = (start_date, end_date)
        domains = ['conditions', 'medications', 'observations']
        max_items = 5
    elif report_type == "problems_focused":
        # Focus on active problems
        date_range = None
        domains = ['conditions', 'medications']
        max_items = 15
    else:  # comprehensive
        date_range = None
        domains = ['demographics', 'conditions', 'medications', 'observations', 'documents', 'practitioners']
        max_items = 20
    
    # Generate the summary
    summary = generate_patient_summary(
        bundle=bundle,
        patient_id=patient_id,
        date_range=date_range,
        clinical_domains=domains,
        max_items_per_domain=max_items
    )
    
    # Add report metadata
    summary['report_type'] = report_type
    summary['report_title'] = f"Clinical Summary - {report_type.replace('_', ' ').title()}"
    
    return summary 