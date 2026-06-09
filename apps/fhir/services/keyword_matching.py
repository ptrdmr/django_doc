"""
Keyword matching helpers for FHIR resource services (WP2 hardening).

Centralizes two things that were previously duplicated and fragile:

1. ``VACCINE_KEYWORDS`` — the single source of truth for recognizing vaccine
   entries, shared by ImmunizationService and ProcedureService so the
   "convert to Immunization" and "skip as Procedure" decisions can never drift
   out of sync (which would otherwise drop or double-count a vaccine).

2. ``word_match`` / ``contains_any_keyword`` — token-boundary matching so short
   keywords stop false-matching unrelated text. Raw substring matching caused
   real defects: ``"reflux"`` contains ``"flu"``, ``"fasting"`` contains
   ``"ast"``, ``"cobalt"`` contains ``"alt"``, ``"tdap"`` contains ``"td"``.
   Matching on word boundaries eliminates that whole class of bug.
"""

import re
from typing import Iterable, Optional

# Single source of truth for vaccine recognition. Imported by both
# ImmunizationService and ProcedureService.
VACCINE_KEYWORDS = (
    "vaccine", "vaccination", "immunization", "immunisation", "toxoid",
    "influenza", "flu", "flu shot", "covid", "covid-19", "sars-cov-2",
    "tdap", "tetanus", "dtap", "mmr", "varicella", "hepatitis",
    "pneumococcal", "pneumovax", "prevnar", "shingrix", "shingles", "zoster",
    "hpv", "gardasil", "meningococcal", "polio", "rotavirus", "rsv", "booster",
)


def word_match(text: str, keyword: str) -> bool:
    """
    Return True when ``keyword`` appears in ``text`` on word boundaries.

    Unlike ``keyword in text``, this will not match ``"flu"`` inside
    ``"reflux"`` or ``"ast"`` inside ``"fasting"``. ``keyword`` may contain
    spaces, hyphens, or digits (e.g. ``"sars-cov-2"``, ``"flu shot"``); it is
    regex-escaped before matching.

    Args:
        text: Haystack (matched case-insensitively).
        keyword: Needle token/phrase.

    Returns:
        True on a boundary match, else False.
    """
    if not text or not keyword:
        return False
    return re.search(_boundary_pattern(keyword), text.lower()) is not None


def _boundary_pattern(keyword: str) -> str:
    """Build a word-boundary regex for ``keyword`` allowing a plural ``s``.

    The leading ``\\b`` is what prevents the false matches (``"ast"`` inside
    ``"fasting"``, ``"alt"`` inside ``"cobalt"``). The optional trailing ``s``
    lets singular keywords still match pluralized lab/analyte names
    (``"triglyceride"`` -> ``"Triglycerides"``, ``"platelet"`` -> ``"Platelets"``).
    """
    return r"\b" + re.escape(keyword.lower()) + r"s?\b"


def contains_any_keyword(text: str, keywords: Iterable[str]) -> bool:
    """Return True when any keyword matches ``text`` on word boundaries."""
    if not text:
        return False
    lowered = text.lower()
    return any(
        re.search(_boundary_pattern(kw), lowered)
        for kw in keywords
        if kw
    )


def is_vaccine_name(name: Optional[str],
                    claimed_names: Optional[Iterable[str]] = None) -> bool:
    """
    Return True when ``name`` describes a vaccine.

    A name qualifies if it matches a known vaccine keyword on a word boundary,
    or matches (on a word boundary) one of the ``claimed_names`` already emitted
    as Immunization resources. Claimed names shorter than 3 characters are
    ignored to avoid spurious matches.

    Args:
        name: Candidate procedure/vaccine name.
        claimed_names: Optional iterable of vaccine names already represented as
            Immunization resources (lowercased or mixed case both accepted).

    Returns:
        True when the name should be treated as a vaccine.
    """
    if not name or not str(name).strip():
        return False
    lowered = str(name).strip().lower()

    if claimed_names:
        for claimed in claimed_names:
            claimed_norm = (claimed or "").strip().lower()
            if len(claimed_norm) >= 3 and word_match(lowered, claimed_norm):
                return True

    return contains_any_keyword(lowered, VACCINE_KEYWORDS)
