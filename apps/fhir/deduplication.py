"""
FHIR Data Deduplication System

Implements comprehensive deduplication algorithms for FHIR resources including:
- Exact duplicate detection using resource hashing
- Fuzzy matching for near-duplicate identification  
- Resource-specific similarity scoring
- Intelligent merging with provenance preservation

Like sorting through a pile of receipts to find duplicates - some are identical,
some are close enough, and some just look similar but are actually different.
"""

import json
import hashlib
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple

from django.utils import timezone
from django.contrib.auth.models import User
from django.core.serializers.json import DjangoJSONEncoder

from fhir.resources.bundle import Bundle, BundleEntry
from fhir.resources.resource import Resource
from fhir.resources.extension import Extension

from .bundle_utils import get_resource_hash

# Import logger from services.py
logger = logging.getLogger(__name__)


class FHIRMergeError(Exception):
    """Exception for FHIR merge operation errors."""
    pass


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
            return get_resource_hash(resource)
        except Exception as e:
            logger.error(f"Failed to generate hash for {resource.resource_type}: {str(e)}")
            # Fallback to simple string representation hash
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
