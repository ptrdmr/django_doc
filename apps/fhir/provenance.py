"""
FHIR Provenance Tracking System

Comprehensive provenance tracking system for FHIR merge operations.
Handles creation and management of FHIR Provenance resources throughout
the merge process, maintaining complete audit trails.
"""

import json
import logging
from typing import Optional, List, Dict, Any

from django.utils import timezone
from django.contrib.auth.models import User

from fhir.resources.resource import Resource
from fhir.resources.reference import Reference
from fhir.resources.extension import Extension

from .fhir_models import ProvenanceResource


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
