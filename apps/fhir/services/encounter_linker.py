"""
Encounter Linker for FHIR Resource Cross-Referencing (WP2).

Resolves which Encounter a clinical resource belongs to and stamps an
``encounter`` reference onto it. Operates as a post-build pass over already
constructed FHIR resource dicts so individual resource services do not need to
change their signatures.

Matching strategy (in priority order):
    1. Explicit encounter id hint (when a resource carries one).
    2. Normalized date matching at the coarsest shared precision. This honors
       the codebase's partial-date support (year / month / day) instead of
       assuming a full ``YYYY-MM-DD`` string.
    3. Single-encounter fallback: most documents describe one visit, so an
       unmatched clinical resource is attached to the sole real Encounter.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def normalize_date_parts(raw_date: Any) -> List[str]:
    """
    Break a date-ish value into ordered [year, month, day] string components.

    Accepts full ISO datetimes ("2024-10-19T03:47:00"), ISO dates
    ("2024-10-19"), or partial dates ("2024", "2024-10"). Returns an empty list
    when nothing usable is present. This is the shared normalization primitive
    consumed by both WP2 (encounter linking) and WP3 (encounter grouping).
    """
    if not raw_date:
        return []

    text = str(raw_date).strip()
    if not text:
        return []

    # Drop any time component; we only match at date granularity.
    date_portion = text.split("T", 1)[0].strip()
    if not date_portion:
        return []

    parts = [segment for segment in date_portion.split("-") if segment != ""]
    return parts


def dates_match_at_precision(first: Any, second: Any) -> bool:
    """
    Return True when two dates agree at their coarsest shared precision.

    Examples:
        "2024" vs "2024-10-19"     -> True  (year-level match)
        "2024-10" vs "2024-10-19"  -> True  (month-level match)
        "2024-10-19" vs "2024-10-18" -> False
        "" / None                  -> False (no basis to match)
    """
    parts_a = normalize_date_parts(first)
    parts_b = normalize_date_parts(second)
    if not parts_a or not parts_b:
        return False

    shared = min(len(parts_a), len(parts_b))
    return parts_a[:shared] == parts_b[:shared]


class EncounterLinker:
    """Resolves and applies Encounter references for clinical FHIR resources."""

    # FHIR date fields to inspect per resourceType, in priority order.
    DATE_FIELDS: Dict[str, List[str]] = {
        "Observation": ["effectiveDateTime"],
        # NOTE: recordedDate is deliberately excluded — it is the processing
        # timestamp (datetime.now()), not a clinical date, so matching on it
        # would link conditions to whichever encounter happens to share today.
        "Condition": ["onsetDateTime"],
        "Procedure": ["occurrenceDateTime", "performedDateTime"],
        "MedicationStatement": ["effectiveDateTime"],
        "DiagnosticReport": ["effectiveDateTime"],
        "ServiceRequest": ["occurrenceDateTime", "authoredOn"],
        "Immunization": ["occurrenceDateTime"],
    }

    # Resource types eligible for an encounter reference.
    LINKABLE_TYPES = set(DATE_FIELDS.keys())

    def __init__(self, encounter_map: Optional[Dict[str, Any]] = None):
        """
        Args:
            encounter_map: Lookup built by FHIRProcessor mapping both date keys
                and encounter ids to Encounter resource dicts.
        """
        self.encounter_map = encounter_map or {}
        self._real_encounters = self._collect_real_encounters()

    def _collect_real_encounters(self) -> List[Dict[str, Any]]:
        """Return the unique Encounter resource dicts from the map."""
        seen_ids = set()
        unique: List[Dict[str, Any]] = []
        for value in self.encounter_map.values():
            if not isinstance(value, dict):
                continue
            if value.get("resourceType") != "Encounter":
                continue
            marker = id(value)
            if marker in seen_ids:
                continue
            seen_ids.add(marker)
            unique.append(value)
        return unique

    def find_encounter_ref(
        self,
        resource_date: Any = None,
        encounter_id_hint: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """
        Resolve the best Encounter reference for a clinical resource.

        Returns a FHIR reference dict ({"reference": "Encounter/<id>"}) or None.
        """
        if not self.encounter_map:
            return None

        # Priority 1: explicit encounter id hint.
        if encounter_id_hint and encounter_id_hint in self.encounter_map:
            enc = self.encounter_map[encounter_id_hint]
            if isinstance(enc, dict) and enc.get("id"):
                return {"reference": f"Encounter/{enc['id']}"}

        # Priority 2: normalized date matching at coarsest shared precision.
        if resource_date:
            for enc in self._real_encounters:
                enc_start = (enc.get("period") or {}).get("start")
                if enc_start and dates_match_at_precision(resource_date, enc_start):
                    if enc.get("id"):
                        return {"reference": f"Encounter/{enc['id']}"}

        # Priority 3: single-encounter fallback, but only when it is safe.
        # Attaching every resource to the lone encounter corrupts multi-date
        # documents (e.g. a visit note that also lists years of historical
        # labs). So fall back ONLY when the resource has no date of its own; a
        # resource carrying a date that did not match in Priority 2 is treated
        # as belonging to a different (unstated) encounter and left unlinked.
        if len(self._real_encounters) == 1:
            enc = self._real_encounters[0]
            if not enc.get("id"):
                return None
            if not resource_date:
                return {"reference": f"Encounter/{enc['id']}"}

        return None

    def _extract_resource_date(self, resource: Dict[str, Any]) -> Optional[str]:
        """Pull the most relevant date string from a FHIR resource dict."""
        resource_type = resource.get("resourceType")
        for field in self.DATE_FIELDS.get(resource_type, []):
            value = resource.get(field)
            if value:
                return value
        # Period-style fallbacks shared across several resource types.
        for period_field in ("effectivePeriod", "performedPeriod", "occurrencePeriod"):
            period = resource.get(period_field)
            if isinstance(period, dict) and period.get("start"):
                return period["start"]
        return None

    def link_resources(self, resources: List[Dict[str, Any]]) -> int:
        """
        Stamp encounter references onto eligible clinical resources in place.

        Returns the number of resources that received a reference. Resources
        that already carry an ``encounter`` field are left untouched.
        """
        if not self.encounter_map or not resources:
            return 0

        linked = 0
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            if resource.get("resourceType") not in self.LINKABLE_TYPES:
                continue
            if resource.get("encounter"):
                continue
            # Never link a forecast/not-administered immunization to a visit —
            # it would imply the recommended shot was given at that encounter.
            if (resource.get("resourceType") == "Immunization"
                    and resource.get("status") == "not-done"):
                continue

            resource_date = self._extract_resource_date(resource)
            enc_ref = self.find_encounter_ref(resource_date=resource_date)
            if enc_ref:
                resource["encounter"] = enc_ref
                linked += 1

        if linked:
            logger.info("EncounterLinker attached %s encounter reference(s)", linked)
        return linked
