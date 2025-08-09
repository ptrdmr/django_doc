"""
Conflict resolution strategies and resolver for FHIR resource merging.
Split from services.py for clarity and testability.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from django.utils import timezone
from fhir.resources.resource import Resource

if TYPE_CHECKING:  # avoid circular imports at runtime
    from .services import ConflictDetail  # noqa: F401
    from .provenance import ProvenanceTracker  # noqa: F401


logger = logging.getLogger(__name__)


class ConflictResolutionStrategy:
    def __init__(self, name: str):
        self.name = name
        self.logger = logger

    def resolve_conflict(
        self,
        conflict_detail: "ConflictDetail",
        new_resource: Resource,
        existing_resource: Resource,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def _extract_timestamp(self, resource: Resource) -> Optional[datetime]:
        timestamp_fields = [
            "effectiveDateTime",
            "recordedDate",
            "assertedDate",
            "onsetDateTime",
            "date",
            "meta.lastUpdated",
        ]
        for field in timestamp_fields:
            try:
                if "." in field:
                    obj: Any = resource
                    for part in field.split("."):
                        obj = getattr(obj, part, None)
                        if obj is None:
                            break
                    if obj:
                        return obj if isinstance(obj, datetime) else datetime.fromisoformat(str(obj).replace("Z", "+00:00"))
                else:
                    value = getattr(resource, field, None)
                    if value:
                        return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except (AttributeError, ValueError, TypeError):
                continue
        return None


class NewestWinsStrategy(ConflictResolutionStrategy):
    def __init__(self):
        super().__init__("newest_wins")

    def resolve_conflict(self, conflict_detail: "ConflictDetail", new_resource: Resource, existing_resource: Resource, context: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.debug("Applying newest_wins strategy for %s", conflict_detail.conflict_type)
        new_ts = self._extract_timestamp(new_resource)
        old_ts = self._extract_timestamp(existing_resource)
        result: Dict[str, Any] = {
            "strategy": self.name,
            "action": "keep_new",
            "resolved_value": conflict_detail.new_value,
            "reasoning": "Default to new resource",
            "timestamp_comparison": {
                "new_timestamp": new_ts.isoformat() if new_ts else None,
                "existing_timestamp": old_ts.isoformat() if old_ts else None,
            },
        }
        if new_ts and old_ts and old_ts > new_ts:
            result.update({
                "action": "keep_existing",
                "resolved_value": conflict_detail.existing_value,
                "reasoning": f"Existing resource is newer ({old_ts} > {new_ts})",
            })
        elif old_ts and not new_ts:
            result.update({"action": "keep_existing", "resolved_value": conflict_detail.existing_value, "reasoning": "Only existing resource has timestamp"})
        return result


class PreserveBothStrategy(ConflictResolutionStrategy):
    def __init__(self):
        super().__init__("preserve_both")

    def resolve_conflict(self, conflict_detail: "ConflictDetail", new_resource: Resource, existing_resource: Resource, context: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.debug("Applying preserve_both strategy for %s", conflict_detail.conflict_type)
        result = {
            "strategy": self.name,
            "action": "preserve_both",
            "resolved_value": {
                "existing": conflict_detail.existing_value,
                "new": conflict_detail.new_value,
                "preservation_method": "temporal_sequence",
            },
            "reasoning": "Both values preserved as temporal sequence",
            "metadata": {
                "conflict_preserved": True,
                "requires_clinical_review": conflict_detail.severity in ["high", "critical"],
            },
        }
        if conflict_detail.severity == "critical":
            result["metadata"].update({"flagged_for_review": True, "review_priority": "high", "clinical_significance": "potential_safety_issue"})
        return result


class ConfidenceBasedStrategy(ConflictResolutionStrategy):
    def __init__(self):
        super().__init__("confidence_based")

    def resolve_conflict(self, conflict_detail: "ConflictDetail", new_resource: Resource, existing_resource: Resource, context: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.debug("Applying confidence_based strategy for %s", conflict_detail.conflict_type)
        new_conf = self._extract_confidence_score(new_resource, context)
        old_conf = self._extract_confidence_score(existing_resource, context)
        result: Dict[str, Any] = {
            "strategy": self.name,
            "action": "keep_new",
            "resolved_value": conflict_detail.new_value,
            "reasoning": "Default to new resource",
            "confidence_comparison": {"new_confidence": new_conf, "existing_confidence": old_conf},
        }
        if new_conf is not None and old_conf is not None:
            if old_conf > new_conf:
                result.update({"action": "keep_existing", "resolved_value": conflict_detail.existing_value, "reasoning": f"Existing resource has higher confidence ({old_conf} > {new_conf})"})
            elif new_conf == old_conf:
                fb = NewestWinsStrategy().resolve_conflict(conflict_detail, new_resource, existing_resource, context)
                result.update(fb)
                result["strategy"] = f"{self.name}_fallback_newest_wins"
                result["reasoning"] = f"Equal confidence ({new_conf}), fell back to newest_wins"
        else:
            fb = NewestWinsStrategy().resolve_conflict(conflict_detail, new_resource, existing_resource, context)
            result.update(fb)
            result["strategy"] = f"{self.name}_fallback_newest_wins"
            result["reasoning"] = "Missing confidence scores, fell back to newest_wins"
        return result

    def _extract_confidence_score(self, resource: Resource, context: Dict[str, Any]) -> Optional[float]:
        if hasattr(resource, "meta") and resource.meta:
            for tag in getattr(resource.meta, "tag", []):
                if getattr(tag, "system", None) == "http://terminology.hl7.org/CodeSystem/confidence" and getattr(tag, "code", None):
                    try:
                        return float(tag.code)
                    except ValueError:
                        pass
        doc_meta = context.get("document_metadata", {})
        ai_conf = doc_meta.get("ai_confidence_score")
        if ai_conf is not None:
            try:
                return float(ai_conf)
            except (ValueError, TypeError):
                pass
        extr_conf = context.get("extraction_confidence")
        if extr_conf is not None:
            try:
                return float(extr_conf)
            except (ValueError, TypeError):
                pass
        return None


class ManualReviewStrategy(ConflictResolutionStrategy):
    def __init__(self):
        super().__init__("manual_review")

    def resolve_conflict(self, conflict_detail: "ConflictDetail", new_resource: Resource, existing_resource: Resource, context: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.debug("Flagging %s for manual review", conflict_detail.conflict_type)
        result = {
            "strategy": self.name,
            "action": "flag_for_review",
            "resolved_value": None,
            "reasoning": "Conflict requires manual review",
            "review_metadata": {
                "flagged_at": timezone.now().isoformat(),
                "conflict_severity": conflict_detail.severity,
                "requires_clinical_review": True,
                "review_priority": self._determine_review_priority(conflict_detail),
                "both_values_preserved": True,
                "existing_value": conflict_detail.existing_value,
                "new_value": conflict_detail.new_value,
            },
        }
        if conflict_detail.severity == "critical":
            result["review_metadata"].update({"urgent_review": True, "potential_safety_issue": True, "escalation_required": True})
        return result

    def _determine_review_priority(self, conflict_detail: "ConflictDetail") -> str:
        if conflict_detail.severity == "critical":
            return "urgent"
        if conflict_detail.severity == "high":
            return "high"
        if conflict_detail.conflict_type in ["value_mismatch", "dosage_conflict"]:
            return "medium"
        return {"medium": "low", "low": "low"}.get(conflict_detail.severity, "low")


class ConflictResolver:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.logger = logger
        self.strategies = {
            "newest_wins": NewestWinsStrategy(),
            "preserve_both": PreserveBothStrategy(),
            "confidence_based": ConfidenceBasedStrategy(),
            "manual_review": ManualReviewStrategy(),
        }
        self.default_strategy_mappings = {"critical": "manual_review", "high": "preserve_both", "medium": "newest_wins", "low": "newest_wins"}

    def resolve_conflicts(
        self,
        conflicts: List["ConflictDetail"],
        new_resource: Resource,
        existing_resource: Resource,
        context: Dict[str, Any],
        provenance_tracker: Optional["ProvenanceTracker"] = None,
    ) -> Dict[str, Any]:
        if not conflicts:
            return {"total_conflicts": 0, "resolved_conflicts": 0, "unresolved_conflicts": 0, "resolution_actions": [], "overall_action": "no_conflicts"}
        self.logger.info("Resolving %s conflicts using configured strategies", len(conflicts))
        summary: Dict[str, Any] = {"total_conflicts": len(conflicts), "resolved_conflicts": 0, "unresolved_conflicts": 0, "resolution_actions": [], "flagged_for_review": [], "overall_action": "resolved"}
        for conflict in conflicts:
            try:
                strat_name = self._select_strategy_for_conflict(conflict)
                strat = self.strategies[strat_name]
                res = strat.resolve_conflict(conflict, new_resource, existing_resource, context)
                summary["resolution_actions"].append({"conflict_type": conflict.conflict_type, "field_name": conflict.field_name, "strategy_used": strat_name, "action": res["action"], "reasoning": res["reasoning"]})
                if res["action"] == "flag_for_review":
                    summary["flagged_for_review"].append(conflict.to_dict())
                    summary["unresolved_conflicts"] += 1
                else:
                    summary["resolved_conflicts"] += 1
            except Exception as exc:
                self.logger.error("Failed to resolve conflict %s: %s", conflict.conflict_type, exc)
                summary["unresolved_conflicts"] += 1
                summary["resolution_actions"].append({"conflict_type": conflict.conflict_type, "field_name": conflict.field_name, "strategy_used": "error", "action": "failed", "reasoning": f"Resolution failed: {exc}"})
        if summary["unresolved_conflicts"] > 0:
            summary["overall_action"] = "critical_conflicts_require_review" if any(c.severity == "critical" for c in conflicts) else "partial_resolution_with_review"
        if provenance_tracker and summary["resolved_conflicts"] > 0:
            try:
                conflict_dicts = [{"conflict_type": c.conflict_type, "field_name": c.field_name, "severity": c.severity, "resource_type": c.resource_type} for c in conflicts]
                provenance_tracker.create_conflict_resolution_provenance(
                    resolved_resource=new_resource,
                    conflict_details=conflict_dicts,
                    resolution_strategy=self.config.get("conflict_resolution_strategy", "mixed"),
                    user=context.get("user"),
                )
            except Exception as exc:
                self.logger.error("Failed to create conflict resolution provenance: %s", exc)
        self.logger.info("Conflict resolution completed: %s resolved, %s require review", summary["resolved_conflicts"], summary["unresolved_conflicts"])
        return summary

    def _select_strategy_for_conflict(self, conflict: "ConflictDetail") -> str:
        ctype_map = self.config.get("conflict_type_strategies", {})
        if conflict.conflict_type in ctype_map:
            return ctype_map[conflict.conflict_type]
        rtype_map = self.config.get("resource_type_strategies", {})
        if conflict.resource_type in rtype_map:
            return rtype_map[conflict.resource_type]
        severity_map = self.config.get("severity_strategies", self.default_strategy_mappings)
        if conflict.severity in severity_map:
            return severity_map[conflict.severity]
        default_strategy = self.config.get("conflict_resolution_strategy", "newest_wins")
        return default_strategy if default_strategy in self.strategies else "newest_wins"


