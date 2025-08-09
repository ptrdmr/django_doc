"""
FHIR Resource Merge Handlers

Specialized handlers that merge new FHIR resources into an existing Bundle.
Split from services.py for clarity and unit testing.
"""

import copy
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import uuid4

from fhir.resources.bundle import Bundle
from fhir.resources.resource import Resource

from .validation import DataNormalizer  # kept for potential future use


logger = logging.getLogger(__name__)


class BaseMergeHandler:
    """Base class for FHIR resource merge handlers."""

    def __init__(self):
        self.logger = logger
        # Lazy import to avoid circulars
        from .services import ConflictDetector  # noqa: WPS433 (local import by design)
        self.conflict_detector = ConflictDetector()

    def merge_resource(
        self,
        new_resource: Resource,
        current_bundle: Bundle,
        context: Dict[str, Any],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Merge a new resource into the current bundle."""
        raise NotImplementedError

    def _find_existing_resource(
        self,
        new_resource: Resource,
        current_bundle: Bundle,
        match_criteria: List[str] | None = None,
    ) -> Optional[Resource]:
        """Find an existing resource in the bundle that matches the new resource."""
        if not getattr(current_bundle, "entry", None):
            return None

        resource_type = new_resource.resource_type
        if not match_criteria:
            match_criteria = self._get_default_match_criteria(resource_type)

        for entry in current_bundle.entry:
            if hasattr(entry, "resource") and entry.resource.resource_type == resource_type:
                if self._resources_match(new_resource, entry.resource, match_criteria):
                    return entry.resource
        return None

    def _get_default_match_criteria(self, resource_type: str) -> List[str]:
        match_strategies: Dict[str, List[str]] = {
            "Patient": ["identifier", "name", "birthDate"],
            "Observation": ["code", "subject", "effectiveDateTime"],
            "Condition": ["code", "subject", "onsetDateTime"],
            "MedicationStatement": ["medicationCodeableConcept", "subject", "effectiveDateTime"],
            "Practitioner": ["identifier", "name"],
            "DocumentReference": ["identifier", "subject", "date"],
        }
        return match_strategies.get(resource_type, ["id"])

    def _resources_match(self, resource1: Resource, resource2: Resource, match_criteria: List[str]) -> bool:
        for criterion in match_criteria:
            val1 = getattr(resource1, criterion, None)
            val2 = getattr(resource2, criterion, None)
            if val1 is None or val2 is None:
                continue
            if hasattr(val1, "dict") and hasattr(val2, "dict"):
                if val1.dict() != val2.dict():
                    return False
            elif val1 != val2:
                return False
        return True

    def _add_resource_to_bundle(self, resource: Resource, bundle: Bundle, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if not hasattr(bundle, "entry") or bundle.entry is None:
                bundle.entry = []
            from fhir.resources.bundle import BundleEntry

            entry = BundleEntry()
            entry.resource = resource
            entry.fullUrl = f"urn:uuid:{getattr(resource, 'id', uuid4())}"
            bundle.entry.append(entry)

            self.logger.debug("Added %s to bundle", resource.resource_type)
            return {
                "action": "added",
                "resource_type": resource.resource_type,
                "resource_id": getattr(resource, "id", "unknown"),
                "conflicts_detected": 0,
                "conflicts_resolved": 0,
                "duplicates_removed": 0,
                "errors": [],
                "warnings": [],
            }
        except Exception as exc:
            error_msg = f"Failed to add {resource.resource_type} resource to bundle: {exc}"
            self.logger.error(error_msg)
            return {
                "action": "skipped",
                "resource_type": resource.resource_type,
                "resource_id": getattr(resource, "id", "unknown"),
                "conflicts_detected": 0,
                "conflicts_resolved": 0,
                "duplicates_removed": 0,
                "errors": [error_msg],
                "warnings": [],
            }


class ObservationMergeHandler(BaseMergeHandler):
    def merge_resource(self, new_resource: Resource, current_bundle: Bundle, context: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        merge_result: Dict[str, Any] = {
            "action": "unknown",
            "resource_type": "Observation",
            "resource_id": getattr(new_resource, "id", "unknown"),
            "conflicts_detected": 0,
            "conflicts_resolved": 0,
            "duplicates_removed": 0,
            "errors": [],
            "warnings": [],
            "conflict_details": [],
        }

        existing_resource = self._find_existing_resource(new_resource, current_bundle, ["code", "subject", "effectiveDateTime"])
        conflicts: List[Any] = []
        if existing_resource and config.get("duplicate_detection_enabled", True):
            is_duplicate = self.conflict_detector.check_for_duplicates(new_resource, existing_resource, "Observation")
            if is_duplicate:
                merge_result.update({"action": "skipped", "duplicates_removed": 1, "warnings": ["Identical observation found - skipping duplicate"]})
                return merge_result

        if existing_resource and config.get("conflict_detection_enabled", True):
            conflicts = self.conflict_detector.detect_conflicts(new_resource, existing_resource, "Observation")
            merge_result["conflicts_detected"] = len(conflicts)
            merge_result["conflict_details"] = [c.to_dict() for c in conflicts]
            if conflicts and config.get("resolve_conflicts", True):
                resolver = context.get("conflict_resolver")
                if resolver:
                    prov = context.get("provenance_tracker")
                    summary = resolver.resolve_conflicts(conflicts, new_resource, existing_resource, context, prov)
                    merge_result["conflicts_resolved"] = summary["resolved_conflicts"]
                    merge_result["resolution_actions"] = summary["resolution_actions"]
                    predominant = self._determine_predominant_action(summary["resolution_actions"])
                    if predominant == "keep_existing":
                        merge_result.update({"action": "kept_existing", "warnings": ["Existing observation kept due to conflict resolution"]})
                        return merge_result
                    if predominant == "preserve_both":
                        self._add_resource_to_bundle(new_resource, current_bundle, context)
                        merge_result.update({"action": "added_as_sequence", "warnings": ["Added as temporal sequence - both values preserved"]})
                        return merge_result

        self._add_resource_to_bundle(new_resource, current_bundle, context)
        merge_result.update({"action": "added_as_sequence" if conflicts else "added"})
        return merge_result

    def _determine_predominant_action(self, resolution_actions: List[Dict[str, Any]]) -> str:
        if not resolution_actions:
            return "keep_new"
        action_priorities = {"flag_for_review": 4, "keep_existing": 3, "preserve_both": 2, "keep_new": 1}
        predominant = "keep_new"
        highest = 0
        for info in resolution_actions:
            action = info.get("action", "keep_new")
            prio = action_priorities.get(action, 1)
            if prio > highest:
                highest = prio
                predominant = action
        return predominant


class ConditionMergeHandler(BaseMergeHandler):
    def merge_resource(self, new_resource: Resource, current_bundle: Bundle, context: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        merge_result: Dict[str, Any] = {
            "action": "unknown",
            "resource_type": "Condition",
            "resource_id": getattr(new_resource, "id", "unknown"),
            "conflicts_detected": 0,
            "conflicts_resolved": 0,
            "duplicates_removed": 0,
            "errors": [],
            "warnings": [],
            "conflict_details": [],
        }

        existing_resource = self._find_existing_resource(new_resource, current_bundle, ["code", "subject"])
        if existing_resource and config.get("duplicate_detection_enabled", True):
            if self.conflict_detector.check_for_duplicates(new_resource, existing_resource, "Condition"):
                merge_result.update({"action": "skipped", "duplicates_removed": 1, "warnings": ["Identical condition found - skipping duplicate"]})
                return merge_result

        conflicts: List[Any] = []
        if existing_resource and config.get("conflict_detection_enabled", True):
            conflicts = self.conflict_detector.detect_conflicts(new_resource, existing_resource, "Condition")
            merge_result["conflicts_detected"] = len(conflicts)
            merge_result["conflict_details"] = [c.to_dict() for c in conflicts]
            if any(c.severity == "critical" for c in conflicts):
                merge_result.update({"action": "flagged_for_review", "errors": ["Critical condition conflicts detected - manual review required"]})
                return merge_result

        if existing_resource and self._should_update_condition(new_resource, existing_resource):
            updated = self._update_existing_condition(existing_resource, new_resource, context)
            updated.update({
                "conflicts_detected": merge_result["conflicts_detected"],
                "conflicts_resolved": merge_result["conflicts_detected"],
                "conflict_details": merge_result["conflict_details"],
            })
            return updated

        if existing_resource:
            merge_result.update({"action": "skipped", "conflicts_resolved": merge_result["conflicts_detected"], "warnings": ["Existing condition kept (more recent or complete)"]})
            return merge_result

        add_res = self._add_resource_to_bundle(new_resource, current_bundle, context)
        merge_result["action"] = "added"
        return merge_result

    def _should_update_condition(self, new_condition: Resource, existing_condition: Resource) -> bool:
        new_date = getattr(new_condition, "recordedDate", None)
        existing_date = getattr(existing_condition, "recordedDate", None)
        if new_date and existing_date:
            return new_date > existing_date
        if new_date and not existing_date:
            return True
        return False

    def _update_existing_condition(self, existing_condition: Resource, new_condition: Resource, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if hasattr(new_condition, "clinicalStatus"):
                existing_condition.clinicalStatus = new_condition.clinicalStatus
            if hasattr(new_condition, "verificationStatus"):
                existing_condition.verificationStatus = new_condition.verificationStatus
            if hasattr(new_condition, "recordedDate"):
                existing_condition.recordedDate = new_condition.recordedDate
            self.logger.debug("Updated existing condition with new information")
            return {
                "action": "updated",
                "resource_type": "Condition",
                "resource_id": getattr(existing_condition, "id", "unknown"),
                "conflicts_detected": 1,
                "conflicts_resolved": 1,
                "duplicates_removed": 0,
                "errors": [],
                "warnings": [],
            }
        except Exception as exc:
            error_msg = f"Failed to update existing condition: {exc}"
            self.logger.error(error_msg)
            return {
                "action": "skipped",
                "resource_type": "Condition",
                "resource_id": getattr(new_condition, "id", "unknown"),
                "conflicts_detected": 1,
                "conflicts_resolved": 0,
                "duplicates_removed": 0,
                "errors": [error_msg],
                "warnings": [],
            }


class MedicationStatementMergeHandler(BaseMergeHandler):
    def merge_resource(self, new_resource: Resource, current_bundle: Bundle, context: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        existing = self._find_existing_resource(new_resource, current_bundle, ["medicationCodeableConcept", "subject"])
        if existing:
            return self._add_resource_to_bundle(new_resource, current_bundle, context)
        return self._add_resource_to_bundle(new_resource, current_bundle, context)


class GenericMergeHandler(BaseMergeHandler):
    def merge_resource(self, new_resource: Resource, current_bundle: Bundle, context: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.debug("Using generic merge for %s", getattr(new_resource, "resource_type", "Unknown"))
        return self._add_resource_to_bundle(new_resource, current_bundle, context)


class AllergyIntoleranceHandler(BaseMergeHandler):
    """Safety-focused handler for AllergyIntolerance resources.

    Minimal initial implementation: add resource to bundle, allowing the
    conflict detector to drive future enhancements.
    """

    def merge_resource(self, new_resource: Resource, current_bundle: Bundle, context: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        # Basic behavior: append, leaving nuanced logic to future improvements
        return self._add_resource_to_bundle(new_resource, current_bundle, context)


class ProcedureHandler(BaseMergeHandler):
    """Handler for Procedure resources with simple sequencing behavior."""

    def merge_resource(self, new_resource: Resource, current_bundle: Bundle, context: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        return self._add_resource_to_bundle(new_resource, current_bundle, context)


class DiagnosticReportHandler(BaseMergeHandler):
    """Handler for DiagnosticReport resources with basic result correlation.

    For now, we append the report; detailed correlation can be layered later.
    """

    def merge_resource(self, new_resource: Resource, current_bundle: Bundle, context: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        return self._add_resource_to_bundle(new_resource, current_bundle, context)


class CarePlanHandler(BaseMergeHandler):
    """Handler for CarePlan resources with versioning placeholder behavior."""

    def merge_resource(self, new_resource: Resource, current_bundle: Bundle, context: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        return self._add_resource_to_bundle(new_resource, current_bundle, context)


class ResourceMergeHandlerFactory:
    """Factory to obtain appropriate merge handlers by resource type."""

    def __init__(self):
        self._handlers: Dict[str, BaseMergeHandler] = {
            "Observation": ObservationMergeHandler(),
            "Condition": ConditionMergeHandler(),
            "MedicationStatement": MedicationStatementMergeHandler(),
            "AllergyIntolerance": AllergyIntoleranceHandler(),
            "Procedure": ProcedureHandler(),
            "DiagnosticReport": DiagnosticReportHandler(),
            "CarePlan": CarePlanHandler(),
        }
        self._generic_handler = GenericMergeHandler()

    def get_handler(self, resource_type: str) -> BaseMergeHandler:
        return self._handlers.get(resource_type, self._generic_handler)

    def register_handler(self, resource_type: str, handler: BaseMergeHandler) -> None:
        self._handlers[resource_type] = handler


