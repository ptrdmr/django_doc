"""Smoke tests for extraction-related FHIR helpers (no external AI calls)."""

import unittest
from uuid import UUID, uuid4

from apps.fhir.services.condition_service import ConditionService
from apps.fhir.services.deduplication_service import DeduplicationService
from apps.fhir.services.family_history_service import FamilyHistoryService
from apps.fhir.services.observation_service import ObservationService


def _valid_uuid_str() -> str:
    return str(uuid4())


class ExtractionPipelineWiringTests(unittest.TestCase):
    """Covers family history, structured observations, dedupe, partial dates."""

    def setUp(self) -> None:
        self.patient_id = _valid_uuid_str()
        UUID(self.patient_id)  # sanity – must be UUID string for references

    def test_family_history_maps_structured_row(self) -> None:
        service = FamilyHistoryService()
        structured = {
            "family_history": [
                {
                    "relationship": "Mother",
                    "condition": "Breast cancer",
                    "onset_age": "60s",
                    "deceased": False,
                    "confidence": 0.88,
                    "source": {
                        "text": "Mother: breast cancer in 60s",
                        "start_index": 0,
                        "end_index": 26,
                    },
                }
            ]
        }
        bundle = service.process_family_history(
            {"patient_id": self.patient_id, "structured_data": structured}
        )
        self.assertEqual(len(bundle), 1)
        resource = bundle[0]
        self.assertEqual(resource["resourceType"], "FamilyMemberHistory")
        ext_urls = {ext.get("url", "") for ext in resource.get("extension", [])}
        self.assertIn(
            "http://medicaldocparser.com/fhir/extension/extraction-confidence", ext_urls
        )

    def test_observation_exam_and_social_lists(self) -> None:
        service = ObservationService()
        payload = {
            "patient_id": self.patient_id,
            "structured_data": {
                "physical_exam_findings": [
                    {
                        "finding": "Lungs clear",
                        "body_site": "Chest",
                        "status": "normal",
                        "confidence": 0.9,
                        "source": {
                            "text": "Lungs clear to auscultation",
                            "start_index": 0,
                            "end_index": 6,
                        },
                    }
                ],
                "social_history": [
                    {
                        "category": "tobacco",
                        "description": "Quit smoking in 2019",
                        "confidence": 0.85,
                        "source": {"text": "Former smoker", "start_index": 0, "end_index": 4},
                    }
                ],
            },
        }
        observations = service.process_observations(payload)
        self.assertEqual(len(observations), 2)
        category_codes = []
        for observation in observations:
            for cat in observation.get("category", []):
                for coding in cat.get("coding", []):
                    if coding.get("code"):
                        category_codes.append(coding["code"])
        self.assertIn("exam", category_codes)
        self.assertIn("social-history", category_codes)

    def test_bundle_dedupe_prefers_high_confidence_condition(self) -> None:
        base_condition = {
            "resourceType": "Condition",
            "clinicalStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                        "code": "active",
                    }
                ]
            },
            "verificationStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                        "code": "confirmed",
                    }
                ]
            },
            "code": {
                "text": "Type 2 diabetes mellitus",
                "coding": [
                    {"system": "http://hl7.org/fhir/sid/icd-10", "code": "E11.9"}
                ],
            },
            "subject": {"reference": f"Patient/{self.patient_id}"},
        }

        low_conf = dict(base_condition)
        low_conf["id"] = "cond-low"
        low_conf["extension"] = [
            {
                "url": "http://medicaldocparser.com/fhir/extension/extraction-confidence",
                "valueDecimal": 0.55,
            }
        ]

        high_conf = dict(base_condition)
        high_conf["id"] = "cond-high"
        high_conf["extension"] = [
            {
                "url": "http://medicaldocparser.com/fhir/extension/extraction-confidence",
                "valueDecimal": 0.95,
            }
        ]

        entries = [
            {"fullUrl": "urn:uuid:low", "resource": low_conf},
            {"fullUrl": "urn:uuid:high", "resource": high_conf},
        ]

        service = DeduplicationService()
        merged_entries = service.deduplicate_bundle_entries(entries)
        remaining_ids = {entry["resource"]["id"] for entry in merged_entries}

        self.assertNotIn("cond-low", remaining_ids)
        self.assertIn("cond-high", remaining_ids)

    def test_condition_year_only_onset_without_padding(self) -> None:
        service = ConditionService()
        structured = {
            "conditions": [
                {
                    "name": "Hypertension",
                    "status": "active",
                    "onset_date": "2019",
                    "date_precision": "year",
                    "confidence": 0.9,
                    "source": {"text": "HTN since 2019", "start_index": 0, "end_index": 14},
                }
            ]
        }
        rows = service.process_conditions(
            {"patient_id": self.patient_id, "structured_data": structured}
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["onsetDateTime"], "2019")
