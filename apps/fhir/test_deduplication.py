"""
Test suite for FHIR Data Deduplication System

Tests the comprehensive deduplication functionality including:
- Hash-based exact duplicate detection
- Fuzzy matching for near-duplicates
- Resource merging and provenance tracking
- Integration with FHIRMergeService
"""

import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from fhir.resources.bundle import Bundle, BundleEntry
from fhir.resources.observation import Observation
from fhir.resources.condition import Condition
from fhir.resources.medicationstatement import MedicationStatement
from fhir.resources.patient import Patient as FHIRPatient
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.quantity import Quantity
from fhir.resources.reference import Reference

from apps.patients.models import Patient
from apps.fhir.services import (
    ResourceHashGenerator,
    FuzzyMatcher,
    ResourceDeduplicator,
    DuplicateResourceDetail,
    DeduplicationResult,
    FHIRMergeService
)


class ResourceHashGeneratorTest(TestCase):
    """Test the ResourceHashGenerator for consistent hash generation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.hash_generator = ResourceHashGenerator()
    
    def test_generate_consistent_hash_for_identical_resources(self):
        """Test that identical resources generate the same hash."""
        # Create two identical observation resources
        obs1 = Observation(
            id="test-obs-1",
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7", display="Weight")]),
            valueQuantity=Quantity(value=70, unit="kg")
        )
        
        obs2 = Observation(
            id="test-obs-1",  # Same ID
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7", display="Weight")]),
            valueQuantity=Quantity(value=70, unit="kg")
        )
        
        hash1 = self.hash_generator.generate_resource_hash(obs1)
        hash2 = self.hash_generator.generate_resource_hash(obs2)
        
        self.assertEqual(hash1, hash2, "Identical resources should generate the same hash")
        self.assertIsInstance(hash1, str, "Hash should be a string")
        self.assertGreater(len(hash1), 0, "Hash should not be empty")
    
    def test_generate_different_hash_for_different_resources(self):
        """Test that different resources generate different hashes."""
        obs1 = Observation(
            id="test-obs-1",
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")]),
            valueQuantity=Quantity(value=70, unit="kg")
        )
        
        obs2 = Observation(
            id="test-obs-2",
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")]),
            valueQuantity=Quantity(value=75, unit="kg")  # Different value
        )
        
        hash1 = self.hash_generator.generate_resource_hash(obs1)
        hash2 = self.hash_generator.generate_resource_hash(obs2)
        
        self.assertNotEqual(hash1, hash2, "Different resources should generate different hashes")
    
    def test_handle_resource_without_hash_method(self):
        """Test handling of resources that might not have standard hash methods."""
        # Create a mock resource
        mock_resource = Mock()
        mock_resource.resource_type = "TestResource"
        mock_resource.dict.return_value = {"id": "test", "type": "test"}
        
        # Should not raise an exception
        hash_result = self.hash_generator.generate_resource_hash(mock_resource)
        self.assertIsInstance(hash_result, str)


class FuzzyMatcherTest(TestCase):
    """Test the FuzzyMatcher for similarity calculation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.fuzzy_matcher = FuzzyMatcher(tolerance_hours=24)
    
    def test_calculate_observation_similarity_identical(self):
        """Test similarity calculation for identical observations."""
        obs1 = Observation(
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")]),
            subject=Reference(reference="Patient/123"),
            valueQuantity=Quantity(value=70, unit="kg"),
            effectiveDateTime="2024-01-01T10:00:00Z"
        )
        
        obs2 = Observation(
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")]),
            subject=Reference(reference="Patient/123"),
            valueQuantity=Quantity(value=70, unit="kg"),
            effectiveDateTime="2024-01-01T11:00:00Z"  # 1 hour difference
        )
        
        similarity = self.fuzzy_matcher.calculate_similarity(obs1, obs2)
        self.assertGreaterEqual(similarity, 0.8, "Identical observations should have high similarity")
    
    def test_calculate_observation_similarity_different_codes(self):
        """Test similarity calculation for observations with different codes."""
        obs1 = Observation(
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")]),  # Weight
            subject=Reference(reference="Patient/123")
        )
        
        obs2 = Observation(
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="8302-2")]),   # Height
            subject=Reference(reference="Patient/123")
        )
        
        similarity = self.fuzzy_matcher.calculate_similarity(obs1, obs2)
        self.assertLessEqual(similarity, 0.5, "Observations with different codes should have low similarity")
    
    def test_calculate_condition_similarity(self):
        """Test similarity calculation for conditions."""
        cond1 = Condition(
            subject=Reference(reference="Patient/123"),
            code=CodeableConcept(coding=[Coding(system="http://snomed.info/sct", code="44054006")])
        )
        
        cond2 = Condition(
            subject=Reference(reference="Patient/123"),
            code=CodeableConcept(coding=[Coding(system="http://snomed.info/sct", code="44054006")])
        )
        
        similarity = self.fuzzy_matcher.calculate_similarity(cond1, cond2)
        self.assertGreaterEqual(similarity, 0.8, "Identical conditions should have high similarity")
    
    def test_calculate_similarity_different_resource_types(self):
        """Test that different resource types return 0 similarity."""
        obs = Observation(
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")])
        )
        cond = Condition(
            subject=Reference(reference="Patient/123"),
            code=CodeableConcept(coding=[Coding(system="http://snomed.info/sct", code="44054006")])
        )
        
        similarity = self.fuzzy_matcher.calculate_similarity(obs, cond)
        self.assertEqual(similarity, 0.0, "Different resource types should have 0 similarity")
    
    def test_values_similar_within_tolerance(self):
        """Test value similarity detection within tolerance."""
        val1 = Quantity(value=70.0, unit="kg")
        val2 = Quantity(value=70.5, unit="kg")  # 0.7% difference
        
        result = self.fuzzy_matcher._values_similar(val1, val2, tolerance=0.1)
        self.assertTrue(result, "Values within tolerance should be considered similar")
    
    def test_values_different_units(self):
        """Test that values with different units are not similar."""
        val1 = Quantity(value=70, unit="kg")
        val2 = Quantity(value=70, unit="lb")
        
        result = self.fuzzy_matcher._values_similar(val1, val2)
        self.assertFalse(result, "Values with different units should not be similar")
    
    def test_dates_within_tolerance(self):
        """Test date similarity within time tolerance."""
        date1 = "2024-01-01T10:00:00Z"
        date2 = "2024-01-01T12:00:00Z"  # 2 hours difference
        
        result = self.fuzzy_matcher._dates_within_tolerance(date1, date2)
        self.assertTrue(result, "Dates within 24-hour tolerance should be similar")
    
    def test_dates_outside_tolerance(self):
        """Test that dates outside tolerance are not similar."""
        date1 = "2024-01-01T10:00:00Z"
        date2 = "2024-01-03T10:00:00Z"  # 2 days difference
        
        result = self.fuzzy_matcher._dates_within_tolerance(date1, date2)
        self.assertFalse(result, "Dates outside tolerance should not be similar")


class ResourceDeduplicatorTest(TestCase):
    """Test the complete ResourceDeduplicator functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            'deduplication_tolerance_hours': 24,
            'near_duplicate_threshold': 0.9,
            'fuzzy_duplicate_threshold': 0.7
        }
        self.deduplicator = ResourceDeduplicator(self.config)
    
    def test_group_resources_by_type(self):
        """Test grouping resources by type."""
        obs1 = Observation(
            id="obs1",
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")])
        )
        
        obs2 = Observation(
            id="obs2",
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")])
        )
        
        cond1 = Condition(
            id="cond1",
            subject=Reference(reference="Patient/123"),
            code=CodeableConcept(coding=[Coding(system="http://snomed.info/sct", code="44054006")])
        )
        
        resources = [obs1, obs2, cond1]
        groups = self.deduplicator._group_resources_by_type(resources)
        
        self.assertEqual(len(groups), 2, "Should have 2 resource types")
        self.assertEqual(len(groups['Observation']), 2, "Should have 2 observations")
        self.assertEqual(len(groups['Condition']), 1, "Should have 1 condition")
    
    def test_find_exact_duplicates(self):
        """Test finding exact duplicate resources."""
        # Create two identical observations
        obs1 = Observation(
            id="obs1",
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")]),
            valueQuantity=Quantity(value=70, unit="kg")
        )
        
        obs2 = Observation(
            id="obs2",  # Different ID but same content
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")]),
            valueQuantity=Quantity(value=70, unit="kg")
        )
        
        # Mock the hash generator to return the same hash
        with patch.object(self.deduplicator.hash_generator, 'generate_resource_hash') as mock_hash:
            mock_hash.return_value = "same-hash"
            
            duplicates = self.deduplicator._find_duplicates_in_group([obs1, obs2], "Observation")
            
            self.assertEqual(len(duplicates), 1, "Should find 1 duplicate pair")
            duplicate = duplicates[0]
            self.assertEqual(duplicate.duplicate_type, 'exact', "Should be exact duplicate")
            self.assertEqual(duplicate.similarity_score, 1.0, "Exact duplicates should have 1.0 similarity")
    
    def test_find_near_duplicates(self):
        """Test finding near-duplicate resources."""
        obs1 = Observation(
            id="obs1",
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")])
        )
        
        obs2 = Observation(
            id="obs2",
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")])
        )
        
        resources = [obs1, obs2]
        
        # Mock different hashes but high similarity
        with patch.object(self.deduplicator.hash_generator, 'generate_resource_hash') as mock_hash, \
             patch.object(self.deduplicator.fuzzy_matcher, 'calculate_similarity') as mock_similarity:
            
            mock_hash.side_effect = ["hash1", "hash2"]  # Different hashes
            mock_similarity.return_value = 0.95  # High similarity
            
            duplicates = self.deduplicator._find_duplicates_in_group(resources, "Observation")
            
            self.assertEqual(len(duplicates), 1, "Should find 1 near-duplicate pair")
            duplicate = duplicates[0]
            self.assertEqual(duplicate.duplicate_type, 'near', "Should be near duplicate")
            self.assertEqual(duplicate.similarity_score, 0.95, "Should preserve similarity score")
    
    def test_deduplicate_empty_resources(self):
        """Test deduplication with empty resource list."""
        result = self.deduplicator.deduplicate_resources([])
        
        self.assertTrue(result.success, "Empty deduplication should succeed")
        self.assertEqual(len(result.duplicates_found), 0, "Should find no duplicates")
        self.assertEqual(result.resources_removed, 0, "Should remove no resources")
    
    def test_deduplicate_single_resource(self):
        """Test deduplication with single resource."""
        obs = Observation(
            id="single-obs",
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")])
        )
        
        result = self.deduplicator.deduplicate_resources([obs])
        
        self.assertTrue(result.success, "Single resource deduplication should succeed")
        self.assertEqual(len(result.duplicates_found), 0, "Should find no duplicates")
        self.assertEqual(result.resources_removed, 0, "Should remove no resources")
    
    def test_enhance_resource_with_provenance(self):
        """Test adding provenance information to merged resources."""
        obs = Observation(
            id="primary-obs",
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")])
        )
        
        duplicate_detail = DuplicateResourceDetail(
            resource_type="Observation",
            resource_id="primary-obs",
            duplicate_id="duplicate-obs",
            similarity_score=1.0,
            duplicate_type="exact",
            matching_fields=["*"]
        )
        
        enhanced = self.deduplicator._enhance_resource_with_provenance(
            obs, [duplicate_detail], preserve_provenance=True
        )
        
        # Check that meta information was added
        self.assertIsNotNone(enhanced.meta, "Should have meta information")
        # Note: The actual provenance structure depends on FHIR library implementation


class FHIRMergeServiceDeduplicationTest(TestCase):
    """Test deduplication integration with FHIRMergeService."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a test patient
        self.patient = Patient.objects.create(
            mrn="TEST-001",
            first_name="John",
            last_name="Doe",
            date_of_birth="1980-01-01",
            cumulative_fhir_json={}
        )
        
        self.merge_service = FHIRMergeService(self.patient)
    
    def test_deduplicator_initialization(self):
        """Test that deduplicator is properly initialized."""
        self.assertIsNotNone(self.merge_service.deduplicator, "Deduplicator should be initialized")
        self.assertIsInstance(self.merge_service.deduplicator, ResourceDeduplicator)
    
    def test_perform_deduplication_empty_bundle(self):
        """Test deduplication with empty bundle."""
        bundle = Bundle(type="collection")
        bundle.entry = []
        
        from apps.fhir.services import MergeResult
        merge_result = MergeResult()
        
        dedup_result = self.merge_service._perform_deduplication(bundle, merge_result)
        
        self.assertIsNotNone(dedup_result, "Should return deduplication result")
        self.assertEqual(len(dedup_result.duplicates_found), 0, "Should find no duplicates in empty bundle")
    
    def test_perform_deduplication_with_patient_only(self):
        """Test deduplication with bundle containing only patient."""
        bundle = Bundle(type="collection")
        
        # Add patient entry
        patient_entry = BundleEntry()
        patient_resource = FHIRPatient()
        patient_resource.id = "patient-123"
        patient_entry.resource = patient_resource
        bundle.entry = [patient_entry]
        
        from apps.fhir.services import MergeResult
        merge_result = MergeResult()
        
        dedup_result = self.merge_service._perform_deduplication(bundle, merge_result)
        
        self.assertIsNotNone(dedup_result, "Should return deduplication result")
        self.assertEqual(len(dedup_result.duplicates_found), 0, "Should find no duplicates with patient only")
    
    def test_perform_deduplication_with_clinical_resources(self):
        """Test deduplication with bundle containing clinical resources."""
        bundle = Bundle(type="collection")
        
        # Add patient entry
        patient_entry = BundleEntry()
        patient_resource = FHIRPatient()
        patient_resource.id = "patient-123"
        patient_entry.resource = patient_resource
        
        # Add observation entries (potential duplicates)
        obs1_entry = BundleEntry()
        obs1 = Observation(
            id="obs-1",
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")])
        )
        obs1_entry.resource = obs1
        
        obs2_entry = BundleEntry()
        obs2 = Observation(
            id="obs-2",
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code="29463-7")])
        )
        obs2_entry.resource = obs2
        
        bundle.entry = [patient_entry, obs1_entry, obs2_entry]
        
        from apps.fhir.services import MergeResult
        merge_result = MergeResult()
        
        # Mock the deduplicator to find duplicates
        with patch.object(self.merge_service.deduplicator, 'deduplicate_resources') as mock_dedupe:
            mock_result = DeduplicationResult()
            mock_result.success = True
            mock_result.resources_removed = 1
            mock_result.duplicates_found = [
                DuplicateResourceDetail(
                    resource_type="Observation",
                    resource_id="obs-1",
                    duplicate_id="obs-2",
                    similarity_score=1.0,
                    duplicate_type="exact",
                    matching_fields=["*"]
                )
            ]
            mock_dedupe.return_value = mock_result
            
            dedup_result = self.merge_service._perform_deduplication(bundle, merge_result)
            
            # Verify deduplication was called with correct resources
            mock_dedupe.assert_called_once()
            call_args = mock_dedupe.call_args[1]  # Get keyword arguments
            self.assertEqual(len(call_args['resources']), 2, "Should pass 2 observations for deduplication")
            
            # Check results
            self.assertEqual(dedup_result.resources_removed, 1, "Should report 1 resource removed")
            self.assertEqual(merge_result.duplicates_removed, 1, "Should update merge result")
    
    def test_deduplication_error_handling(self):
        """Test that deduplication errors don't fail the entire merge."""
        bundle = Bundle(type="collection")
        
        from apps.fhir.services import MergeResult
        merge_result = MergeResult()
        
        # Mock the deduplicator to raise an exception
        with patch.object(self.merge_service.deduplicator, 'deduplicate_resources') as mock_dedupe:
            mock_dedupe.side_effect = Exception("Deduplication test error")
            
            # Should not raise an exception
            dedup_result = self.merge_service._perform_deduplication(bundle, merge_result)
            
            # Check error handling
            self.assertFalse(dedup_result.success, "Deduplication result should indicate failure")
            self.assertGreater(len(merge_result.merge_errors), 0, "Should add error to merge result")
            self.assertIn("Deduplication warning", merge_result.merge_errors[0], "Should indicate it's a warning")


class DeduplicationIntegrationTest(TestCase):
    """Integration tests for the complete deduplication workflow."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.patient = Patient.objects.create(
            mrn="INT-TEST-001",
            first_name="Jane",
            last_name="Smith",
            date_of_birth="1985-05-15"
        )
    
    def test_complete_merge_with_deduplication(self):
        """Test the complete merge workflow including deduplication."""
        merge_service = FHIRMergeService(self.patient)
        
        # Sample extracted data with potential duplicates
        extracted_data = {
            "document_type": "lab_report",
            "patient": {
                "name": "Jane Smith",
                "mrn": "INT-TEST-001"
            },
            "lab_results": [
                {
                    "test_name": "Hemoglobin",
                    "value": "12.5",
                    "unit": "g/dL",
                    "reference_range": "12.0-16.0",
                    "date": "2024-01-15"
                },
                {
                    "test_name": "Hemoglobin",  # Potential duplicate
                    "value": "12.5",
                    "unit": "g/dL",
                    "reference_range": "12.0-16.0",
                    "date": "2024-01-15"
                }
            ]
        }
        
        document_metadata = {
            "document_id": "test-doc-001",
            "source": "test_lab",
            "uploaded_at": timezone.now().isoformat()
        }
        
        # Enable deduplication in configuration
        merge_service.config['deduplicate_resources'] = True
        
        # Perform the merge (this will include deduplication)
        try:
            result = merge_service.merge_document_data(extracted_data, document_metadata)
            
            # Check that merge was successful
            self.assertTrue(result.success, f"Merge should succeed. Errors: {result.merge_errors}")
            
            # Check that deduplication was performed
            self.assertIsNotNone(result.deduplication_result, "Should have deduplication result")
            
            # Check overall result
            self.assertGreaterEqual(result.resources_added, 1, "Should add at least 1 resource")
            
        except Exception as e:
            self.fail(f"Integration test failed with exception: {str(e)}")
    
    def test_deduplication_disabled(self):
        """Test that deduplication can be disabled."""
        merge_service = FHIRMergeService(self.patient)
        
        # Disable deduplication
        merge_service.config['deduplicate_resources'] = False
        
        extracted_data = {
            "document_type": "clinical_note",
            "patient": {"name": "Jane Smith", "mrn": "INT-TEST-001"},
            "conditions": [{"name": "Hypertension", "status": "active"}]
        }
        
        document_metadata = {"document_id": "test-doc-002"}
        
        result = merge_service.merge_document_data(extracted_data, document_metadata)
        
        # When deduplication is disabled, deduplication_result should be None
        self.assertIsNone(result.deduplication_result, "Should not have deduplication result when disabled")
        self.assertTrue(result.success, "Merge should still succeed")


class DeduplicationResultTest(TestCase):
    """Test the DeduplicationResult class functionality."""
    
    def test_initialization(self):
        """Test DeduplicationResult initialization."""
        result = DeduplicationResult()
        
        self.assertEqual(len(result.duplicates_found), 0, "Should start with no duplicates")
        self.assertEqual(result.resources_merged, 0, "Should start with 0 merged")
        self.assertEqual(result.resources_removed, 0, "Should start with 0 removed")
        self.assertFalse(result.success, "Should start as not successful")
    
    def test_add_duplicate(self):
        """Test adding duplicate details."""
        result = DeduplicationResult()
        
        exact_duplicate = DuplicateResourceDetail(
            resource_type="Observation",
            resource_id="obs-1",
            duplicate_id="obs-2",
            similarity_score=1.0,
            duplicate_type="exact",
            matching_fields=["*"]
        )
        
        near_duplicate = DuplicateResourceDetail(
            resource_type="Condition",
            resource_id="cond-1",
            duplicate_id="cond-2",
            similarity_score=0.95,
            duplicate_type="near",
            matching_fields=["code", "subject"]
        )
        
        result.add_duplicate(exact_duplicate)
        result.add_duplicate(near_duplicate)
        
        self.assertEqual(len(result.duplicates_found), 2, "Should have 2 duplicates")
        self.assertEqual(result.exact_duplicates, 1, "Should have 1 exact duplicate")
        self.assertEqual(result.near_duplicates, 1, "Should have 1 near duplicate")
        self.assertEqual(result.fuzzy_duplicates, 0, "Should have 0 fuzzy duplicates")
    
    def test_get_summary(self):
        """Test getting summary of deduplication results."""
        result = DeduplicationResult()
        result.resources_merged = 5
        result.resources_removed = 2
        result.processing_time_seconds = 1.5
        result.success = True
        
        summary = result.get_summary()
        
        self.assertEqual(summary['resources_merged'], 5, "Should report merged count")
        self.assertEqual(summary['resources_removed'], 2, "Should report removed count")
        self.assertEqual(summary['processing_time_seconds'], 1.5, "Should report processing time")
        self.assertTrue(summary['success'], "Should report success status")
        self.assertEqual(summary['error_count'], 0, "Should report error count")


if __name__ == '__main__':
    import django
    django.setup()
    
    import unittest
    unittest.main() 