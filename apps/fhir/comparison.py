"""
FHIR Resource Comparison Utilities

Small, focused helpers for comparing FHIR resources, generating structured diffs,
and extracting data points from bundles. Designed for reuse across merge,
deduplication, and validation flows.

Rules followed:
- No third-party deps (stdlib + existing project modules only)
- Functions are small and explicit, with clear names and docstrings
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional, Union
from datetime import datetime

from fhir.resources.resource import Resource
from fhir.resources.bundle import Bundle

from .bundle_utils import (
    are_resources_clinically_equivalent,
    get_resources_by_type,
)
from .deduplication import ResourceHashGenerator


def is_semantically_equal(
    first: Resource, second: Resource, tolerance_hours: int = 24
) -> bool:
    """
    Determine if two FHIR resources are clinically/semantically equivalent.

    Inputs:
      - first: FHIR Resource
      - second: FHIR Resource
      - tolerance_hours: time tolerance for Observation comparisons

    Returns:
      - bool: True if semantically equivalent, else False
    """
    return are_resources_clinically_equivalent(first, second, tolerance_hours)


def _to_plain_dict(resource: Union[Resource, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Convert a FHIR Resource (or dict) to a plain dict with volatile fields removed.

    Removes: meta, id, contained to minimize noise for diffs/scoring.
    """
    if isinstance(resource, dict):
        data = dict(resource)
    else:
        # Use model_dump if available, else dict(); fall back to .dict(exclude_none=True)
        try:
            data = resource.dict(exclude_none=True)  # type: ignore[attr-defined]
        except Exception:
            try:
                data = resource.model_dump(exclude_none=True)  # type: ignore[attr-defined]
            except Exception:
                # Last resort: serialize to JSON and back is avoided (no jsonlib here)
                data = {k: getattr(resource, k, None) for k in dir(resource) if not k.startswith("_")}

    for key in ("meta", "id", "contained"):
        if key in data:
            data.pop(key, None)
    return data


def _flatten_for_scoring(obj: Any, path_prefix: str = "") -> List[Tuple[str, Any]]:
    """
    Flatten nested dict/list to (path, value) leaves for scoring.
    Paths are dotted (e.g., "code.coding.0.code").
    """
    leaves: List[Tuple[str, Any]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            leaves.extend(_flatten_for_scoring(value, f"{path_prefix}{key}."))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            leaves.extend(_flatten_for_scoring(value, f"{path_prefix}{idx}."))
    else:
        leaves.append((path_prefix[:-1] if path_prefix.endswith(".") else path_prefix, obj))
    return leaves


def resource_completeness_score(resource: Resource) -> float:
    """
    Compute a simple completeness score for a resource.

    Heuristic scoring:
      - Base: count of non-empty leaves (after removing volatile fields)
      - Small weights for clinically relevant keys (code, value[x], status, dates)

    Returns:
      - float score; higher means more specific/complete
    """
    data = _to_plain_dict(resource)
    leaves = _flatten_for_scoring(data)

    score = 0.0
    for path, value in leaves:
        # Count non-empty scalars
        if value not in (None, "", [], {}):
            score += 1.0

        # Add tiny weights for clinically relevant fields
        key = path.split(".")[-1]
        if key in {"code", "status", "category"}:
            score += 0.5
        if key.startswith("value"):
            score += 0.5
        if key in {"effectiveDateTime", "issued", "recordedDate", "onsetDateTime", "date", "authoredOn"}:
            score += 0.5
        if key in {"performer", "asserter"}:
            score += 0.25

    return score


def _get_resource_timestamp(resource: Resource) -> Optional[datetime]:
    """
    Extract a best-effort timestamp from common fields, returning the most relevant
    datetime if present and parsable.
    """
    data = _to_plain_dict(resource)
    candidates = [
        ("effectiveDateTime", data.get("effectiveDateTime")),
        ("issued", data.get("issued")),
        ("recordedDate", data.get("recordedDate")),
        ("onsetDateTime", data.get("onsetDateTime")),
        ("date", data.get("date")),
        ("authoredOn", data.get("authoredOn")),
    ]
    for _, value in candidates:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                # Support "Z" suffix
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except Exception:
                continue
    return None


def pick_more_specific(resource_a: Resource, resource_b: Resource) -> Resource:
    """
    Return the more specific/complete resource using heuristic scoring.

    Tie breakers:
      1) More recent timestamp (best-effort)
      2) Presence of performer/asserter
      3) Stable hash (ResourceHashGenerator) for deterministic selection
    """
    score_a = resource_completeness_score(resource_a)
    score_b = resource_completeness_score(resource_b)
    if score_a > score_b:
        return resource_a
    if score_b > score_a:
        return resource_b

    # Tie-breaker #1: recency
    ts_a = _get_resource_timestamp(resource_a)
    ts_b = _get_resource_timestamp(resource_b)
    if ts_a and ts_b:
        if ts_a > ts_b:
            return resource_a
        if ts_b > ts_a:
            return resource_b
    elif ts_a and not ts_b:
        return resource_a
    elif ts_b and not ts_a:
        return resource_b

    # Tie-breaker #2: presence of performer/asserter
    data_a = _to_plain_dict(resource_a)
    data_b = _to_plain_dict(resource_b)
    has_actor_a = any(k in data_a for k in ("performer", "asserter"))
    has_actor_b = any(k in data_b for k in ("performer", "asserter"))
    if has_actor_a and not has_actor_b:
        return resource_a
    if has_actor_b and not has_actor_a:
        return resource_b

    # Tie-breaker #3: deterministic hash
    hash_a = ResourceHashGenerator.generate_hash(resource_a)
    hash_b = ResourceHashGenerator.generate_hash(resource_b)
    return resource_a if hash_a <= hash_b else resource_b


def _normalize_datetime(value: Any) -> Any:
    """Normalize datetime-like strings to ISO format for diff stability."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except Exception:
            return value
    return value


def _dict_for_diff(resource: Union[Resource, Dict[str, Any]]) -> Dict[str, Any]:
    data = _to_plain_dict(resource)
    # Normalize common datetime fields recursively
    def _walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items() if k not in {"meta", "id", "contained", "versionId", "lastUpdated"}}
        if isinstance(obj, list):
            return [_walk(v) for v in obj]
        return _normalize_datetime(obj)

    return _walk(data)


def generate_resource_diff(
    old: Union[Resource, Dict[str, Any]], new: Union[Resource, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """
    Generate a structured diff between two resources.

    Returns a dict with keys: added, removed, changed.
    Each is a dict keyed by dotted paths.
    """
    old_dict = _dict_for_diff(old)
    new_dict = _dict_for_diff(new)

    added: Dict[str, Any] = {}
    removed: Dict[str, Any] = {}
    changed: Dict[str, Dict[str, Any]] = {}

    def _walk(o: Any, n: Any, prefix: str = "") -> None:
        if isinstance(o, dict) and isinstance(n, dict):
            o_keys = set(o.keys())
            n_keys = set(n.keys())
            for key in sorted(o_keys - n_keys):
                removed[f"{prefix}{key}"] = o[key]
            for key in sorted(n_keys - o_keys):
                added[f"{prefix}{key}"] = n[key]
            for key in sorted(o_keys & n_keys):
                _walk(o[key], n[key], f"{prefix}{key}.")
        elif isinstance(o, list) and isinstance(n, list):
            # Compare by position (simple, stable behavior)
            max_len = max(len(o), len(n))
            for idx in range(max_len):
                path = f"{prefix}{idx}"
                if idx >= len(o):
                    added[path] = n[idx]
                elif idx >= len(n):
                    removed[path] = o[idx]
                else:
                    _walk(o[idx], n[idx], f"{path}.")
        else:
            if o != n:
                path = prefix[:-1] if prefix.endswith(".") else prefix
                changed[path] = {"from": o, "to": n}

    _walk(old_dict, new_dict)
    return {"added": added, "removed": removed, "changed": changed}


def _get_by_path(obj: Any, path: str) -> Any:
    current = obj
    for token in path.split("."):
        if token == "":
            continue
        if isinstance(current, dict):
            current = current.get(token)
        elif isinstance(current, list):
            try:
                idx = int(token)
                current = current[idx]
            except Exception:
                return None
        else:
            return None
        if current is None:
            return None
    return current


def extract_fields(resource: Resource, fields: List[str]) -> Dict[str, Any]:
    """
    Extract specific dotted-path fields from a resource into a dict.
    Missing fields are omitted.
    """
    data = _to_plain_dict(resource)
    result: Dict[str, Any] = {}
    for field in fields:
        value = _get_by_path(data, field)
        if value is not None:
            result[field] = value
    return result


def extract_bundle_data_points(
    bundle: Bundle, resource_type: str, fields: List[str]
) -> List[Dict[str, Any]]:
    """
    Extract selected fields for each resource of a type from a bundle.

    Returns list of dicts, one per resource, containing requested fields.
    """
    resources = get_resources_by_type(bundle, resource_type)
    points: List[Dict[str, Any]] = []
    for res in resources:
        points.append(extract_fields(res, fields))
    return points


__all__ = [
    "is_semantically_equal",
    "resource_completeness_score",
    "pick_more_specific",
    "generate_resource_diff",
    "extract_fields",
    "extract_bundle_data_points",
]


