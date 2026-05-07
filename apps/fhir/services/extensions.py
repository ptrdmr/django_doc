"""Shared FHIR extension builders for extraction provenance (confidence + source snippet)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

EXTENSION_EXTRACTION_CONFIDENCE = "http://medicaldocparser.com/fhir/extension/extraction-confidence"
EXTENSION_SOURCE_CONTEXT = "http://medicaldocparser.com/fhir/extension/source-context"


def build_extraction_extensions(
    confidence: Optional[float],
    source_text: Optional[str],
    *,
    max_snippet_chars: int = 500,
) -> List[Dict[str, Any]]:
    """
    Build FHIR R4 extension dicts carrying model confidence and source text.

    Intended for merging into Resource.extension on generated FHIR dicts.

    Args:
        confidence: Pydantic item confidence (0.0–1.0).
        source_text: Snippet from SourceContext.text when available.
        max_snippet_chars: Truncate source to limit bundle size.

    Returns:
        List of extension dictionaries suitable for FHIR JSON.
    """
    extensions: List[Dict[str, Any]] = []
    if confidence is not None:
        try:
            conf = round(float(confidence), 3)
            if 0.0 <= conf <= 1.0:
                extensions.append(
                    {"url": EXTENSION_EXTRACTION_CONFIDENCE, "valueDecimal": conf}
                )
        except (TypeError, ValueError):
            pass
    if source_text:
        snippet = str(source_text).strip()[:max_snippet_chars]
        if snippet:
            extensions.append({"url": EXTENSION_SOURCE_CONTEXT, "valueString": snippet})
    return extensions


def source_snippet_from_field(source_field: Any) -> Optional[str]:
    """
    Pull plain-text snippet from a Pydantic ``SourceContext`` dict if present.

    Args:
        source_field: Typically ``{\"text\": \"...\", \"start_index\": ...}``.
    """
    if not isinstance(source_field, dict):
        return None
    text_val = source_field.get("text")
    if text_val is None:
        return None
    snippet = str(text_val).strip()
    return snippet or None


def append_extraction_extensions(
    resource: Dict[str, Any],
    *,
    confidence: Optional[float],
    source_text: Optional[str],
) -> Dict[str, Any]:
    """Mutate ``resource`` in place: extend ``extension`` list with extraction metadata."""
    new_ext = build_extraction_extensions(confidence, source_text)
    if not new_ext:
        return resource
    existing = resource.get("extension")
    if isinstance(existing, list):
        existing.extend(new_ext)
    else:
        resource["extension"] = list(new_ext)
    return resource
