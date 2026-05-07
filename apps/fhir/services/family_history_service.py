"""Convert structured ``FamilyMemberHistory`` Pydantic dicts → FHIR R4."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from apps.fhir.services.extensions import append_extraction_extensions, source_snippet_from_field

logger = logging.getLogger(__name__)


class FamilyHistoryService:
    """Build ``FamilyMemberHistory`` resources from ``structured_data.family_history``."""

    def process_family_history(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        resources: List[Dict[str, Any]] = []
        patient_id = extracted_data.get("patient_id")
        if not patient_id:
            logger.warning("No patient_id provided for FamilyMemberHistory processing")
            return resources

        structured = extracted_data.get("structured_data")
        if not isinstance(structured, dict):
            return resources

        rows = structured.get("family_history") or []
        if not isinstance(rows, list) or not rows:
            return resources

        for row in rows:
            if isinstance(row, dict):
                fh = self._create_from_structured(row, str(patient_id))
                if fh:
                    resources.append(fh)

        logger.info("Processed %s FamilyMemberHistory resource(s)", len(resources))
        return resources

    def _create_from_structured(
        self, row: Dict[str, Any], patient_id: str
    ) -> Optional[Dict[str, Any]]:
        relationship = (row.get("relationship") or "").strip()
        condition_text = (row.get("condition") or "").strip()
        if not relationship or not condition_text:
            logger.debug("Skipping family history row missing relationship/condition keys")
            return None

        resource: Dict[str, Any] = {
            "resourceType": "FamilyMemberHistory",
            "id": str(uuid4()),
            "status": "completed",
            "patient": {"reference": f"Patient/{patient_id}"},
            "relationship": {"text": relationship},
            "condition": [
                {
                    "code": {"text": condition_text},
                }
            ],
            "meta": {
                "source": "Structured Pydantic extraction",
                "lastUpdated": datetime.now().isoformat(),
                "versionId": str(uuid4()),
                "tag": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                        "code": "extraction-source",
                        "display": "Structured family_history path",
                    }
                ],
            },
        }

        onset_age = row.get("onset_age")
        if onset_age:
            cleaned = str(onset_age).strip()
            if cleaned:
                resource["condition"][0]["onsetString"] = cleaned

        if row.get("deceased") is True:
            resource["deceasedBoolean"] = True
        elif row.get("deceased") is False:
            resource["deceasedBoolean"] = False

        snippet = source_snippet_from_field(row.get("source"))
        append_extraction_extensions(resource, confidence=row.get("confidence"), source_text=snippet)
        return resource
