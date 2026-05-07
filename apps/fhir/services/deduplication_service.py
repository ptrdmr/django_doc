"""Bundle-aware dedupe over ``apps.fhir.deduplication.ResourceDeduplicator``."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from fhir.resources.resource import Resource

from apps.fhir.deduplication import ResourceDeduplicator
from apps.fhir.services.extensions import EXTENSION_EXTRACTION_CONFIDENCE

logger = logging.getLogger(__name__)


def _camel_resource_package(resource_type: str) -> str:
    segments = re.findall(r"[A-Z][a-z]*|[a-z]+", resource_type)
    return "".join(s.lower() for s in segments)


def _confidence_from_resource_dict(rd: Dict[str, Any]) -> float:
    for ext in rd.get("extension") or []:
        if isinstance(ext, dict) and ext.get("url") == EXTENSION_EXTRACTION_CONFIDENCE:
            try:
                value = float(ext.get("valueDecimal", 0.0))
                if value >= 0.0:
                    return value
            except (TypeError, ValueError):
                continue
    return 0.0


def _parse_resource_dict(rd: Dict[str, Any]) -> Optional[Resource]:
    rt = rd.get("resourceType")
    if not rt:
        return None
    try:
        import importlib

        module = importlib.import_module(f"fhir.resources.{_camel_resource_package(str(rt))}")
        cls = getattr(module, str(rt))

        validator = getattr(cls, "model_validate", None)
        if callable(validator):
            return validator(rd)

        parser = getattr(cls, "parse_obj", None)
        if callable(parser):
            return parser(rd)

        return cls(**rd)
    except Exception as exc:
        logger.warning("Skipping dedupe parse for %s: %s", rt, exc)
        return None


def _dump_resource(resource: Resource) -> Dict[str, Any]:
    dumper = getattr(resource, "model_dump", None)
    if callable(dumper):
        return dumper(mode="json", exclude_none=True)

    legacy_dump = getattr(resource, "dict", None)
    if callable(legacy_dump):
        payload = legacy_dump(exclude_none=True)
        # Convert nested BaseModel descendants to plain dicts if needed downstream
        return payload  # type: ignore[return-value]

    raise TypeError("Resource instance missing serialization helpers")


class DeduplicationService:
    """Deduplicate JSON bundle entries using fuzzy/resource-hash logic."""

    def deduplicate_bundle_entries(
        self, entries: List[Dict[str, Any]], *, preserve_provenance: bool = True
    ) -> List[Dict[str, Any]]:
        if len(entries) < 2:
            return entries

        parseable_rows: List[Tuple[int, Dict[str, Any], Dict[str, Any], Resource]] = []

        for idx, shell in enumerate(entries):
            if not isinstance(shell, dict):
                # Unexpected payload – avoid mutating unknown structure.
                return entries

            rd = shell.get("resource")
            if not isinstance(rd, dict):
                continue

            parsed = _parse_resource_dict(rd)
            if parsed is None:
                continue

            parseable_rows.append((idx, shell, rd, parsed))

        if len(parseable_rows) < 2:
            return entries

        ranked = sorted(
            parseable_rows,
            key=lambda row: (-_confidence_from_resource_dict(row[2]), row[3].resource_type),
        )

        deduper = ResourceDeduplicator()
        dedupe_result = deduper.deduplicate_resources(
            [row[-1] for row in ranked], preserve_provenance=preserve_provenance
        )

        survivor_models = dedupe_result.merged_resources or []
        survivor_set = {id(res) for res in survivor_models}

        refreshed_by_index: Dict[int, Dict[str, Any]] = {}
        for idx, shell, _, model_inst in parseable_rows:
            if id(model_inst) not in survivor_set:
                continue
            new_shell = dict(shell)
            new_shell["resource"] = _dump_resource(model_inst)
            refreshed_by_index[idx] = new_shell

        output: List[Dict[str, Any]] = []

        parseable_idxs = {row[0] for row in parseable_rows}
        for idx, shell in enumerate(entries):
            if not isinstance(shell, dict):
                output.append(shell)
                continue

            refreshed = refreshed_by_index.get(idx)
            if refreshed is not None:
                output.append(refreshed)
                continue

            if idx in parseable_idxs:
                # Duplicate removed during merge — drop entry outright
                continue

            output.append(shell)

        return output
