"""
FHIR Historical Data Preservation System

Manager for append-only historical data preservation in FHIR resources.
Like keeping a maintenance log for an old pickup truck - every change gets
recorded, nothing gets thrown away. Historical data is sacred and must be
preserved for medical records.
"""

import json
import copy
import logging
from typing import Optional, List, Dict, Any, Tuple

from django.utils import timezone
from django.contrib.auth.models import User

from fhir.resources.bundle import Bundle
from fhir.resources.resource import Resource
from fhir.resources.extension import Extension

from .fhir_models import Meta
from .bundle_utils import (
    get_latest_resource_version,
    add_resource_to_bundle,
    get_resources_by_type
)

# Import logger from services.py
logger = logging.getLogger(__name__)


class FHIRAccumulationError(Exception):
    """Exception for FHIR data accumulation errors."""
    pass


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
