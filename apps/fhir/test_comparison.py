from datetime import datetime, timedelta, timezone

from django.test import TestCase

from fhir.resources.fhirtypes import DateTime
from fhir.resources.reference import Reference
from fhir.resources.bundle import Bundle, BundleEntry
from apps.fhir.fhir_models import ObservationResource

from .comparison import (
    is_semantically_equal,
    resource_completeness_score,
    pick_more_specific,
    generate_resource_diff,
    extract_fields,
    extract_bundle_data_points,
)


class ComparisonUtilsTests(TestCase):
    def _make_observation(self, code: str, value: float, unit: str, dt: datetime) -> ObservationResource:
        # Use our custom ObservationResource so helpers like get_value_with_unit exist
        obs = ObservationResource(
            **{
                "status": "final",
                "code": {
                    "coding": [{"system": "http://loinc.org", "code": code}],
                },
                "subject": {"reference": "Patient/123"},
                "effectiveDateTime": DateTime.validate(dt.replace(tzinfo=timezone.utc).isoformat()),
                "valueQuantity": {
                    "value": value,
                    "unit": unit,
                    "system": "http://unitsofmeasure.org",
                },
            }
        )
        return obs

    def test_semantic_equality_within_tolerance(self):
        now = datetime.now(timezone.utc)
        obs1 = self._make_observation("718-7", 5.1, "g/dL", now)
        obs2 = self._make_observation("718-7", 5.1, "g/dL", now + timedelta(hours=2))
        self.assertTrue(is_semantically_equal(obs1, obs2, tolerance_hours=24))

    def test_completeness_scoring_and_pick_more_specific(self):
        now = datetime.now(timezone.utc)
        base = self._make_observation("718-7", 5.1, "g/dL", now)
        richer = self._make_observation("718-7", 5.1, "g/dL", now + timedelta(hours=1))
        # Add performer to increase specificity
        richer.performer = [Reference(reference="Practitioner/abc")]

        self.assertGreater(resource_completeness_score(richer), resource_completeness_score(base))
        self.assertIs(pick_more_specific(base, richer), richer)

    def test_generate_resource_diff(self):
        now = datetime.now(timezone.utc)
        old = self._make_observation("718-7", 5.1, "g/dL", now)
        new = self._make_observation("718-7", 5.4, "g/dL", now + timedelta(hours=1))
        diff = generate_resource_diff(old, new)
        self.assertIn("changed", diff)
        # valueQuantity.value should be different
        changed_keys = diff["changed"].keys()
        self.assertTrue(any("valueQuantity.value" in k for k in changed_keys))

    def test_extract_fields_and_bundle_points(self):
        now = datetime.now(timezone.utc)
        obs = self._make_observation("718-7", 5.1, "g/dL", now)
        fields = ["code.coding.0.code", "valueQuantity.value", "subject.reference"]
        out = extract_fields(obs, fields)
        self.assertEqual(out["code.coding.0.code"], "718-7")
        self.assertEqual(out["subject.reference"], "Patient/123")

        bundle = Bundle.construct()  # type: ignore
        bundle.type = "collection"
        bundle.entry = []
        # Proper BundleEntry with resource attached
        bundle.entry.append(BundleEntry(resource=obs))  # type: ignore

        points = extract_bundle_data_points(bundle, "Observation", fields)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["code.coding.0.code"], "718-7")


