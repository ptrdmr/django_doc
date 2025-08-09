"""
Conflict detection utilities for FHIR merging.
Extracted from services.py to reduce file size and improve readability.
"""

import logging
from typing import Any, Dict, List, Optional

from django.utils import timezone
from fhir.resources.resource import Resource

from .code_systems import default_code_mapper


logger = logging.getLogger(__name__)


class ConflictResult:
    """Tracks conflicts found during merge operations."""

    def __init__(self):
        self.conflicts_detected: List[ConflictDetail] = []
        self.total_conflicts = 0
        self.conflict_types: Dict[str, int] = {}
        self.resource_conflicts: Dict[str, int] = {}
        self.severity_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        self.timestamp = timezone.now()

    def add_conflict(self, conflict_detail: "ConflictDetail") -> None:
        self.conflicts_detected.append(conflict_detail)
        self.total_conflicts += 1
        self.conflict_types[conflict_detail.conflict_type] = self.conflict_types.get(conflict_detail.conflict_type, 0) + 1
        self.resource_conflicts[conflict_detail.resource_type] = self.resource_conflicts.get(conflict_detail.resource_type, 0) + 1
        if conflict_detail.severity in self.severity_counts:
            self.severity_counts[conflict_detail.severity] += 1

    def get_conflicts_by_type(self, conflict_type: str) -> List["ConflictDetail"]:
        return [c for c in self.conflicts_detected if c.conflict_type == conflict_type]

    def get_conflicts_by_resource_type(self, resource_type: str) -> List["ConflictDetail"]:
        return [c for c in self.conflicts_detected if c.resource_type == resource_type]

    def has_critical_conflicts(self) -> bool:
        return self.severity_counts["critical"] > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_conflicts": self.total_conflicts,
            "conflict_types": self.conflict_types,
            "resource_conflicts": self.resource_conflicts,
            "severity_counts": self.severity_counts,
            "conflicts_detected": [c.to_dict() for c in self.conflicts_detected],
            "timestamp": self.timestamp.isoformat(),
        }


class ConflictDetail:
    """Detailed information about a single conflict."""

    def __init__(
        self,
        conflict_type: str,
        resource_type: str,
        field_name: str,
        existing_value: Any,
        new_value: Any,
        severity: str = "medium",
        description: Optional[str] = None,
        resource_id: Optional[str] = None,
    ) -> None:
        self.conflict_type = conflict_type
        self.resource_type = resource_type
        self.field_name = field_name
        self.existing_value = existing_value
        self.new_value = new_value
        self.severity = severity
        self.description = description or f"{conflict_type} in {field_name}"
        self.resource_id = resource_id
        self.timestamp = timezone.now()
        self.resolution_strategy: Optional[str] = None
        self.resolution_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_type": self.conflict_type,
            "resource_type": self.resource_type,
            "field_name": self.field_name,
            "existing_value": str(self.existing_value),
            "new_value": str(self.new_value),
            "severity": self.severity,
            "description": self.description,
            "resource_id": self.resource_id,
            "timestamp": self.timestamp.isoformat(),
            "resolution_strategy": self.resolution_strategy,
            "resolution_result": self.resolution_result,
        }


class ConflictDetector:
    """Detects conflicts between new and existing FHIR resources."""

    def __init__(self) -> None:
        self.logger = logger

    def detect_conflicts(self, new_resource: Resource, existing_resource: Resource, resource_type: str) -> List[ConflictDetail]:
        conflicts: List[ConflictDetail] = []
        try:
            if resource_type == "Observation":
                conflicts.extend(self._detect_observation_conflicts(new_resource, existing_resource))
            elif resource_type == "Condition":
                conflicts.extend(self._detect_condition_conflicts(new_resource, existing_resource))
            elif resource_type == "MedicationStatement":
                conflicts.extend(self._detect_medication_conflicts(new_resource, existing_resource))
            elif resource_type == "Patient":
                conflicts.extend(self._detect_patient_conflicts(new_resource, existing_resource))
            else:
                conflicts.extend(self._detect_generic_conflicts(new_resource, existing_resource, resource_type))
        except Exception as exc:
            self.logger.error("Error detecting conflicts for %s: %s", resource_type, exc)
            conflicts.append(
                ConflictDetail(
                    conflict_type="detection_error",
                    resource_type=resource_type,
                    field_name="conflict_detection",
                    existing_value="unknown",
                    new_value="unknown",
                    severity="high",
                    description=f"Conflict detection failed: {exc}",
                )
            )
        return conflicts

    # --- Observation-specific helpers ---
    def _detect_observation_conflicts(self, new_obs: Resource, existing_obs: Resource) -> List[ConflictDetail]:
        conflicts: List[ConflictDetail] = []
        rid = getattr(new_obs, "id", "unknown")
        new_val = self._extract_observation_value(new_obs)
        old_val = self._extract_observation_value(existing_obs)
        if new_val is not None and old_val is not None and new_val != old_val:
            conflicts.append(ConflictDetail("value_mismatch", "Observation", "value", old_val, new_val, "medium", resource_id=rid))
        new_time = getattr(new_obs, "effectiveDateTime", None)
        old_time = getattr(existing_obs, "effectiveDateTime", None)
        if new_time and old_time and str(new_time) == str(old_time):
            conflicts.append(ConflictDetail("temporal_conflict", "Observation", "effectiveDateTime", old_time, new_time, "low", resource_id=rid))
        return conflicts

    def _extract_observation_value(self, obs: Resource) -> Optional[Any]:
        if hasattr(obs, "valueQuantity") and getattr(obs.valueQuantity, "value", None) is not None:
            return obs.valueQuantity.value
        if hasattr(obs, "valueString") and getattr(obs, "valueString", None) is not None:
            return obs.valueString
        return None
    
    def _are_codes_equivalent(self, code1: Dict[str, Any], code2: Dict[str, Any]) -> bool:
        """
        Check if two FHIR codes are equivalent using code system mapping.
        
        Args:
            code1: First FHIR code (with coding array)
            code2: Second FHIR code (with coding array)
            
        Returns:
            True if codes are equivalent, False otherwise
        """
        if not code1 or not code2:
            return False
        
        # Get coding arrays
        codings1 = code1.get('coding', [])
        codings2 = code2.get('coding', [])
        
        if not codings1 or not codings2:
            return False
        
        # Check for exact matches first
        for c1 in codings1:
            for c2 in codings2:
                if (c1.get('system') == c2.get('system') and 
                    c1.get('code') == c2.get('code')):
                    return True
        
        # Check for equivalent codes using code system mapping
        try:
            for c1 in codings1:
                if c1.get('code') and c1.get('system'):
                    # Extract system name from URI
                    system_name = self._extract_system_name(c1.get('system'))
                    if system_name:
                        # Find equivalent codes
                        mappings = default_code_mapper.find_equivalent_codes(
                            c1.get('code'), 
                            system_name
                        )
                        
                        # Check if any mapping matches codes in codings2
                        for mapping in mappings:
                            if mapping.confidence >= 0.9:  # Very high confidence only
                                target_system_uri = default_code_mapper.get_system_uri(mapping.target_system)
                                for c2 in codings2:
                                    if (c2.get('system') == target_system_uri and 
                                        c2.get('code') == mapping.target_code):
                                        return True
        except Exception as e:
            logger.warning(f"Error checking code equivalence: {e}")
        
        return False
    
    def _extract_system_name(self, system_uri: str) -> Optional[str]:
        """Extract system name from FHIR system URI."""
        if not system_uri:
            return None
        
        uri_mappings = {
            'http://loinc.org': 'LOINC',
            'http://snomed.info/sct': 'SNOMED',
            'http://hl7.org/fhir/sid/icd-10-cm': 'ICD-10-CM',
            'http://hl7.org/fhir/sid/icd-10': 'ICD-10',
            'http://www.ama-assn.org/go/cpt': 'CPT',
            'http://www.nlm.nih.gov/research/umls/rxnorm': 'RxNorm'
        }
        
        return uri_mappings.get(system_uri)

    # --- Condition-specific helpers ---
    def _detect_condition_conflicts(self, new_cond: Resource, old_cond: Resource) -> List[ConflictDetail]:
        conflicts: List[ConflictDetail] = []
        rid = getattr(new_cond, "id", "unknown")
        if getattr(new_cond, "clinicalStatus", None) and getattr(old_cond, "clinicalStatus", None):
            if new_cond.clinicalStatus != old_cond.clinicalStatus:
                conflicts.append(ConflictDetail("status_conflict", "Condition", "clinicalStatus", old_cond.clinicalStatus, new_cond.clinicalStatus, "medium", resource_id=rid))
        return conflicts

    # --- Medication-specific helpers ---
    def _detect_medication_conflicts(self, new_med: Resource, old_med: Resource) -> List[ConflictDetail]:
        conflicts: List[ConflictDetail] = []
        rid = getattr(new_med, "id", "unknown")
        if getattr(new_med, "status", None) and getattr(old_med, "status", None) and new_med.status != old_med.status:
            conflicts.append(ConflictDetail("status_conflict", "MedicationStatement", "status", old_med.status, new_med.status, "low", resource_id=rid))
        return conflicts

    # --- Patient-specific helpers ---
    def _detect_patient_conflicts(self, new_pat: Resource, old_pat: Resource) -> List[ConflictDetail]:
        conflicts: List[ConflictDetail] = []
        # Example placeholder; extend as needed
        return conflicts

    # --- Generic helpers ---
    def _detect_generic_conflicts(self, new_res: Resource, old_res: Resource, resource_type: str) -> List[ConflictDetail]:
        conflicts: List[ConflictDetail] = []
        if hasattr(new_res, "status") and hasattr(old_res, "status") and new_res.status != old_res.status:
            conflicts.append(ConflictDetail("status_conflict", resource_type, "status", getattr(old_res, "status", None), getattr(new_res, "status", None), "low"))
        return conflicts


