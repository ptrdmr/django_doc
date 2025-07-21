"""
Unit tests for FHIR Bundle Management Utilities

Tests all bundle management functions including bundle creation, resource management,
validation, and error handling scenarios.
"""

import unittest
from datetime import datetime, date
from uuid import uuid4

from fhir.resources.bundle import Bundle

from .bundle_utils import (
    create_initial_patient_bundle,
    add_resource_to_bundle,
    get_resources_by_type,
    validate_bundle_integrity,
    get_bundle_summary,
    update_resource_version,
    get_resource_hash,
    are_resources_clinically_equivalent,
    find_duplicate_resources,
    deduplicate_bundle,
    get_resource_version_history,
    get_latest_resource_version,
    add_resource_with_provenance,
    find_resource_provenance,
    get_provenance_chain,
    get_provenance_summary,
    get_all_provenance_resources,
    validate_provenance_integrity
)
from .fhir_models import (
    PatientResource,
    ConditionResource,
    ObservationResource,
    PractitionerResource,
    ProvenanceResource
)


class TestBundleUtils(unittest.TestCase):
    """Test cases for bundle management utility functions."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create test patient
        self.test_patient = PatientResource.create_from_demographics(
            mrn="TEST123",
            first_name="John",
            last_name="Doe",
            birth_date=date(1990, 1, 15),
            patient_id="patient-123"
        )
        
        # Create test condition
        self.test_condition = ConditionResource.create_from_diagnosis(
            patient_id="patient-123",
            condition_code="E11.9",
            condition_display="Type 2 diabetes mellitus",
            condition_id="condition-456"
        )
        
        # Create test observation
        self.test_observation = ObservationResource.create_from_lab_result(
            patient_id="patient-123",
            test_code="33747-0",
            test_name="Hemoglobin A1c",
            value=7.2,
            unit="%",
            observation_id="observation-789"
        )
    
    def test_create_initial_patient_bundle_success(self):
        """Test successful creation of initial patient bundle."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Check bundle structure
        self.assertIsNotNone(bundle)
        self.assertIsNotNone(bundle.id)
        self.assertEqual(bundle.type, "collection")
        self.assertIsNotNone(bundle.meta)
        self.assertEqual(bundle.meta.versionId, "1")
        
        # Check bundle entries
        self.assertEqual(len(bundle.entry), 1)
        self.assertEqual(bundle.entry[0].fullUrl, f"Patient/{self.test_patient.id}")
        self.assertEqual(bundle.entry[0].resource.id, self.test_patient.id)
    
    def test_create_initial_patient_bundle_with_custom_id(self):
        """Test bundle creation with custom bundle ID."""
        custom_bundle_id = "custom-bundle-123"
        bundle = create_initial_patient_bundle(self.test_patient, custom_bundle_id)
        
        self.assertEqual(bundle.id, custom_bundle_id)
    
    def test_create_initial_patient_bundle_invalid_patient(self):
        """Test bundle creation with invalid patient resource."""
        # Test with None patient
        with self.assertRaises(ValueError) as context:
            create_initial_patient_bundle(None)
        self.assertIn("Patient resource is required", str(context.exception))
        
        # Test with patient without ID
        invalid_patient = PatientResource()
        with self.assertRaises(ValueError) as context:
            create_initial_patient_bundle(invalid_patient)
        self.assertIn("Patient resource must have a valid ID", str(context.exception))
    
    def test_add_resource_to_bundle_new_resource(self):
        """Test adding a new resource to bundle."""
        bundle = create_initial_patient_bundle(self.test_patient)
        original_version = int(bundle.meta.versionId)
        
        # Add condition to bundle
        updated_bundle = add_resource_to_bundle(bundle, self.test_condition)
        
        # Check bundle was updated
        self.assertEqual(len(updated_bundle.entry), 2)
        self.assertEqual(int(updated_bundle.meta.versionId), original_version + 1)
        
        # Check condition was added correctly
        condition_entry = None
        for entry in updated_bundle.entry:
            if entry.resource.resource_type == "Condition":
                condition_entry = entry
                break
        
        self.assertIsNotNone(condition_entry)
        self.assertEqual(condition_entry.fullUrl, f"Condition/{self.test_condition.id}")
        self.assertEqual(condition_entry.resource.id, self.test_condition.id)
    
    def test_add_resource_to_bundle_update_existing(self):
        """Test updating an existing resource in bundle."""
        bundle = create_initial_patient_bundle(self.test_patient)
        bundle = add_resource_to_bundle(bundle, self.test_condition)
        
        # Create updated condition
        updated_condition = ConditionResource.create_from_diagnosis(
            patient_id="patient-123",
            condition_code="E11.9",
            condition_display="Type 2 diabetes mellitus - updated",
            condition_id="condition-456"  # Same ID
        )
        
        # Update the condition
        updated_bundle = add_resource_to_bundle(bundle, updated_condition, update_existing=True)
        
        # Should still have 2 entries (patient + condition)
        self.assertEqual(len(updated_bundle.entry), 2)
        
        # Find the condition and check it was updated
        condition_entry = None
        for entry in updated_bundle.entry:
            if entry.resource.resource_type == "Condition":
                condition_entry = entry
                break
        
        self.assertIsNotNone(condition_entry)
        self.assertIn("updated", condition_entry.resource.code.coding[0].display)
    
    def test_add_resource_to_bundle_invalid_inputs(self):
        """Test adding resource with invalid inputs."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Test with None bundle
        with self.assertRaises(ValueError) as context:
            add_resource_to_bundle(None, self.test_condition)
        self.assertIn("Bundle is required", str(context.exception))
        
        # Test with None resource
        with self.assertRaises(ValueError) as context:
            add_resource_to_bundle(bundle, None)
        self.assertIn("Resource is required", str(context.exception))
    
    def test_get_resources_by_type_success(self):
        """Test successful extraction of resources by type."""
        bundle = create_initial_patient_bundle(self.test_patient)
        bundle = add_resource_to_bundle(bundle, self.test_condition)
        bundle = add_resource_to_bundle(bundle, self.test_observation)
        
        # Get patients
        patients = get_resources_by_type(bundle, "Patient")
        self.assertEqual(len(patients), 1)
        self.assertEqual(patients[0].id, self.test_patient.id)
        
        # Get conditions
        conditions = get_resources_by_type(bundle, "Condition")
        self.assertEqual(len(conditions), 1)
        self.assertEqual(conditions[0].id, self.test_condition.id)
        
        # Get observations
        observations = get_resources_by_type(bundle, "Observation")
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].id, self.test_observation.id)
        
        # Get non-existent type
        procedures = get_resources_by_type(bundle, "Procedure")
        self.assertEqual(len(procedures), 0)
    
    def test_get_resources_by_type_invalid_inputs(self):
        """Test resource extraction with invalid inputs."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Test with None bundle
        with self.assertRaises(ValueError) as context:
            get_resources_by_type(None, "Patient")
        self.assertIn("Bundle is required", str(context.exception))
        
        # Test with empty resource type
        with self.assertRaises(ValueError) as context:
            get_resources_by_type(bundle, "")
        self.assertIn("Resource type is required", str(context.exception))
        
        # Test with None resource type
        with self.assertRaises(ValueError) as context:
            get_resources_by_type(bundle, None)
        self.assertIn("Resource type is required", str(context.exception))
    
    def test_validate_bundle_integrity_valid_bundle(self):
        """Test validation of a valid bundle."""
        bundle = create_initial_patient_bundle(self.test_patient)
        bundle = add_resource_to_bundle(bundle, self.test_condition)
        
        validation_result = validate_bundle_integrity(bundle)
        
        self.assertTrue(validation_result["is_valid"])
        self.assertEqual(len(validation_result["issues"]), 0)
        self.assertEqual(validation_result["resource_count"], 2)
        self.assertEqual(validation_result["resource_types"]["Patient"], 1)
        self.assertEqual(validation_result["resource_types"]["Condition"], 1)
    
    def test_validate_bundle_integrity_invalid_bundle(self):
        """Test validation of an invalid bundle."""
        # Create bundle with missing required fields (ID missing, but type provided)
        invalid_bundle = Bundle(type="collection")
        
        validation_result = validate_bundle_integrity(invalid_bundle)
        
        self.assertFalse(validation_result["is_valid"])
        self.assertGreater(len(validation_result["issues"]), 0)
        self.assertIn("Bundle missing ID", validation_result["issues"])
    
    def test_validate_bundle_integrity_none_bundle(self):
        """Test validation with None bundle."""
        with self.assertRaises(ValueError) as context:
            validate_bundle_integrity(None)
        self.assertIn("Bundle is required", str(context.exception))
    
    def test_get_bundle_summary_complete_bundle(self):
        """Test getting summary of a complete bundle."""
        bundle = create_initial_patient_bundle(self.test_patient)
        bundle = add_resource_to_bundle(bundle, self.test_condition)
        bundle = add_resource_to_bundle(bundle, self.test_observation)
        
        summary = get_bundle_summary(bundle)
        
        # Check basic info
        self.assertEqual(summary["id"], bundle.id)
        self.assertEqual(summary["type"], "collection")
        self.assertEqual(summary["version"], "3")  # Should be version 3 after 2 adds
        self.assertEqual(summary["total_entries"], 3)
        
        # Check resource types
        self.assertEqual(summary["resource_types"]["Patient"], 1)
        self.assertEqual(summary["resource_types"]["Condition"], 1)
        self.assertEqual(summary["resource_types"]["Observation"], 1)
        
        # Check patient info
        self.assertIsNotNone(summary["patient_info"])
        self.assertEqual(summary["patient_info"]["id"], "patient-123")
        self.assertEqual(summary["patient_info"]["name"], "Doe, John")
        self.assertEqual(summary["patient_info"]["mrn"], "TEST123")
    
    def test_get_bundle_summary_empty_bundle(self):
        """Test getting summary of bundle with no entries."""
        bundle = Bundle(id="empty-bundle", type="collection")
        
        summary = get_bundle_summary(bundle)
        
        self.assertEqual(summary["id"], "empty-bundle")
        self.assertEqual(summary["total_entries"], 0)
        self.assertEqual(len(summary["resource_types"]), 0)
        self.assertIsNone(summary["patient_info"])
    
    def test_get_bundle_summary_none_bundle(self):
        """Test getting summary with None bundle."""
        with self.assertRaises(ValueError) as context:
            get_bundle_summary(None)
        self.assertIn("Bundle is required", str(context.exception))


class TestResourceVersioning(unittest.TestCase):
    """Test cases for resource versioning functionality."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.test_patient = PatientResource.create_from_demographics(
            mrn="TEST123",
            first_name="John",
            last_name="Doe",
            birth_date=date(1990, 1, 15),
            patient_id="patient-123"
        )
        
        self.test_condition = ConditionResource.create_from_diagnosis(
            patient_id="patient-123",
            condition_code="E11.9",
            condition_display="Type 2 diabetes mellitus",
            condition_id="condition-456"
        )
    
    def test_update_resource_version_new_meta(self):
        """Test updating version for resource without existing meta."""
        # Remove meta to simulate new resource
        self.test_patient.meta = None
        
        updated_resource = update_resource_version(self.test_patient)
        
        self.assertIsNotNone(updated_resource.meta)
        self.assertEqual(updated_resource.meta.versionId, "1")
        self.assertIsNotNone(updated_resource.meta.lastUpdated)
        # Check if lastUpdated is a datetime object or string
        if hasattr(updated_resource.meta.lastUpdated, 'isoformat'):
            # It's a datetime object
            self.assertIsInstance(updated_resource.meta.lastUpdated, datetime)
        else:
            # It's a string
            self.assertTrue(updated_resource.meta.lastUpdated.endswith("Z"))
    
    def test_update_resource_version_existing_meta(self):
        """Test updating version for resource with existing meta."""
        # Set initial version
        self.test_patient.meta.versionId = "2"
        
        updated_resource = update_resource_version(self.test_patient)
        
        self.assertEqual(updated_resource.meta.versionId, "3")
        self.assertIsNotNone(updated_resource.meta.lastUpdated)
    
    def test_update_resource_version_none_resource(self):
        """Test updating version with None resource."""
        with self.assertRaises(ValueError) as context:
            update_resource_version(None)
        self.assertIn("Resource is required", str(context.exception))
    
    def test_get_resource_hash_success(self):
        """Test successful hash generation for resource."""
        hash_value = get_resource_hash(self.test_patient)
        
        self.assertIsNotNone(hash_value)
        self.assertEqual(len(hash_value), 64)  # SHA256 produces 64 character hex string
        self.assertIsInstance(hash_value, str)
    
    def test_get_resource_hash_consistent(self):
        """Test that hash is consistent for same resource."""
        hash1 = get_resource_hash(self.test_patient)
        hash2 = get_resource_hash(self.test_patient)
        
        self.assertEqual(hash1, hash2)
    
    def test_get_resource_hash_different_resources(self):
        """Test that different resources produce different hashes."""
        hash1 = get_resource_hash(self.test_patient)
        hash2 = get_resource_hash(self.test_condition)
        
        self.assertNotEqual(hash1, hash2)
    
    def test_get_resource_hash_excludes_meta(self):
        """Test that hash excludes meta information."""
        # Get initial hash
        hash1 = get_resource_hash(self.test_patient)
        
        # Update meta information
        self.test_patient.meta.versionId = "99"
        self.test_patient.meta.lastUpdated = "2023-01-01T00:00:00Z"
        
        # Hash should be the same
        hash2 = get_resource_hash(self.test_patient)
        
        self.assertEqual(hash1, hash2)
    
    def test_get_resource_hash_none_resource(self):
        """Test hash generation with None resource."""
        with self.assertRaises(ValueError) as context:
            get_resource_hash(None)
        self.assertIn("Resource is required", str(context.exception))


class TestClinicalEquivalence(unittest.TestCase):
    """Test cases for clinical equivalence comparison."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create test patients
        self.patient1 = PatientResource.create_from_demographics(
            mrn="TEST123",
            first_name="John",
            last_name="Doe",
            birth_date=date(1990, 1, 15),
            patient_id="patient-1"
        )
        
        self.patient2 = PatientResource.create_from_demographics(
            mrn="TEST123",  # Same MRN
            first_name="John",
            last_name="Doe",
            birth_date=date(1990, 1, 15),
            patient_id="patient-2"
        )
        
        # Create test observations
        self.observation1 = ObservationResource.create_from_lab_result(
            patient_id="patient-123",
            test_code="33747-0",
            test_name="Hemoglobin A1c",
            value=7.2,
            unit="%",
            observation_id="obs-1",
            observation_date=datetime(2023, 1, 1, 10, 0, 0)
        )
        
        self.observation2 = ObservationResource.create_from_lab_result(
            patient_id="patient-123",
            test_code="33747-0",
            test_name="Hemoglobin A1c",
            value=7.2,
            unit="%",
            observation_id="obs-2",
            observation_date=datetime(2023, 1, 1, 12, 0, 0)  # 2 hours later
        )
        
        # Create test conditions
        self.condition1 = ConditionResource.create_from_diagnosis(
            patient_id="patient-123",
            condition_code="E11.9",
            condition_display="Type 2 diabetes mellitus",
            condition_id="condition-1"
        )
        
        self.condition2 = ConditionResource.create_from_diagnosis(
            patient_id="patient-123",
            condition_code="E11.9",
            condition_display="Type 2 diabetes mellitus",
            condition_id="condition-2"
        )
    
    def test_patients_equivalent_same_mrn(self):
        """Test that patients with same MRN are equivalent."""
        result = are_resources_clinically_equivalent(self.patient1, self.patient2)
        self.assertTrue(result)
    
    def test_patients_equivalent_name_and_dob(self):
        """Test that patients with same name and DOB are equivalent."""
        # Remove MRN from both patients
        self.patient1.identifier = []
        self.patient2.identifier = []
        
        result = are_resources_clinically_equivalent(self.patient1, self.patient2)
        self.assertTrue(result)
    
    def test_patients_not_equivalent_different_mrn(self):
        """Test that patients with different MRNs are not equivalent."""
        # Change MRN for patient2
        self.patient2.identifier[0].value = "DIFFERENT123"
        
        result = are_resources_clinically_equivalent(self.patient1, self.patient2)
        self.assertFalse(result)
    
    def test_observations_equivalent_within_tolerance(self):
        """Test that observations within time tolerance are equivalent."""
        # 2 hours apart, within 24 hour default tolerance
        result = are_resources_clinically_equivalent(self.observation1, self.observation2)
        self.assertTrue(result)
    
    def test_observations_not_equivalent_outside_tolerance(self):
        """Test that observations outside time tolerance are not equivalent."""
        # 2 hours apart, but with 1 hour tolerance
        result = are_resources_clinically_equivalent(
            self.observation1, 
            self.observation2,
            tolerance_hours=1
        )
        self.assertFalse(result)
    
    def test_observations_not_equivalent_different_codes(self):
        """Test that observations with different codes are not equivalent."""
        # Change test code for observation2
        self.observation2.code.coding[0].code = "DIFFERENT"
        
        result = are_resources_clinically_equivalent(self.observation1, self.observation2)
        self.assertFalse(result)
    
    def test_conditions_equivalent_same_code(self):
        """Test that conditions with same code are equivalent."""
        result = are_resources_clinically_equivalent(self.condition1, self.condition2)
        self.assertTrue(result)
    
    def test_conditions_not_equivalent_different_codes(self):
        """Test that conditions with different codes are not equivalent."""
        # Change condition code for condition2
        self.condition2.code.coding[0].code = "DIFFERENT"
        
        result = are_resources_clinically_equivalent(self.condition1, self.condition2)
        self.assertFalse(result)
    
    def test_equivalence_different_resource_types(self):
        """Test that different resource types raise error."""
        with self.assertRaises(ValueError) as context:
            are_resources_clinically_equivalent(self.patient1, self.condition1)
        self.assertIn("Resources must be of the same type", str(context.exception))
    
    def test_equivalence_none_resources(self):
        """Test that None resources raise error."""
        with self.assertRaises(ValueError) as context:
            are_resources_clinically_equivalent(None, self.patient1)
        self.assertIn("Both resources are required", str(context.exception))
        
        with self.assertRaises(ValueError) as context:
            are_resources_clinically_equivalent(self.patient1, None)
        self.assertIn("Both resources are required", str(context.exception))


class TestDuplicateDetection(unittest.TestCase):
    """Test cases for duplicate resource detection and removal."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create test patient
        self.patient = PatientResource.create_from_demographics(
            mrn="TEST123",
            first_name="John",
            last_name="Doe",
            birth_date=date(1990, 1, 15),
            patient_id="patient-123"
        )
        
        # Create duplicate patients
        self.patient_duplicate = PatientResource.create_from_demographics(
            mrn="TEST123",  # Same MRN
            first_name="John",
            last_name="Doe",
            birth_date=date(1990, 1, 15),
            patient_id="patient-duplicate"
        )
        
        # Create duplicate conditions
        self.condition1 = ConditionResource.create_from_diagnosis(
            patient_id="patient-123",
            condition_code="E11.9",
            condition_display="Type 2 diabetes mellitus",
            condition_id="condition-1"
        )
        
        self.condition2 = ConditionResource.create_from_diagnosis(
            patient_id="patient-123",
            condition_code="E11.9",
            condition_display="Type 2 diabetes mellitus",
            condition_id="condition-2"
        )
        
        # Create unique condition
        self.condition_unique = ConditionResource.create_from_diagnosis(
            patient_id="patient-123",
            condition_code="I10",
            condition_display="Essential hypertension",
            condition_id="condition-unique"
        )
    
    def test_find_duplicate_resources_with_duplicates(self):
        """Test finding duplicate resources in bundle."""
        # Create bundle with duplicates
        bundle = create_initial_patient_bundle(self.patient)
        bundle = add_resource_to_bundle(bundle, self.patient_duplicate)
        bundle = add_resource_to_bundle(bundle, self.condition1)
        bundle = add_resource_to_bundle(bundle, self.condition2)
        bundle = add_resource_to_bundle(bundle, self.condition_unique)
        
        duplicates = find_duplicate_resources(bundle)
        
        self.assertEqual(len(duplicates), 2)  # Patient and Condition duplicates
        
        # Check patient duplicates
        patient_duplicates = [d for d in duplicates if d["resource_type"] == "Patient"]
        self.assertEqual(len(patient_duplicates), 1)
        self.assertEqual(patient_duplicates[0]["duplicate_count"], 2)
        
        # Check condition duplicates
        condition_duplicates = [d for d in duplicates if d["resource_type"] == "Condition"]
        self.assertEqual(len(condition_duplicates), 1)
        self.assertEqual(condition_duplicates[0]["duplicate_count"], 2)
    
    def test_find_duplicate_resources_no_duplicates(self):
        """Test finding duplicates when none exist."""
        bundle = create_initial_patient_bundle(self.patient)
        bundle = add_resource_to_bundle(bundle, self.condition_unique)
        
        duplicates = find_duplicate_resources(bundle)
        
        self.assertEqual(len(duplicates), 0)
    
    def test_find_duplicate_resources_empty_bundle(self):
        """Test finding duplicates in empty bundle."""
        bundle = Bundle(id="empty", type="collection")
        
        duplicates = find_duplicate_resources(bundle)
        
        self.assertEqual(len(duplicates), 0)
    
    def test_find_duplicate_resources_none_bundle(self):
        """Test finding duplicates with None bundle."""
        with self.assertRaises(ValueError) as context:
            find_duplicate_resources(None)
        self.assertIn("Bundle is required", str(context.exception))
    
    def test_deduplicate_bundle_keep_latest(self):
        """Test deduplication keeping latest versions."""
        # Create bundle with duplicates
        bundle = create_initial_patient_bundle(self.patient)
        bundle = add_resource_to_bundle(bundle, self.condition1)
        bundle = add_resource_to_bundle(bundle, self.condition2)
        
        # Update condition2 to be newer
        self.condition2.meta.lastUpdated = "2023-12-01T00:00:00Z"
        self.condition1.meta.lastUpdated = "2023-01-01T00:00:00Z"
        
        deduplicated_bundle = deduplicate_bundle(bundle, keep_latest=True)
        
        # Should have patient + 1 condition (the latest)
        self.assertEqual(len(deduplicated_bundle.entry), 2)
        
        # Check that condition2 (newer) was kept
        conditions = get_resources_by_type(deduplicated_bundle, "Condition")
        self.assertEqual(len(conditions), 1)
        self.assertEqual(conditions[0].id, self.condition2.id)
    
    def test_deduplicate_bundle_keep_first(self):
        """Test deduplication keeping first versions."""
        # Create bundle with duplicates
        bundle = create_initial_patient_bundle(self.patient)
        bundle = add_resource_to_bundle(bundle, self.condition1)
        bundle = add_resource_to_bundle(bundle, self.condition2)
        
        deduplicated_bundle = deduplicate_bundle(bundle, keep_latest=False)
        
        # Should have patient + 1 condition (the first)
        self.assertEqual(len(deduplicated_bundle.entry), 2)
        
        # Check that condition1 (first) was kept
        conditions = get_resources_by_type(deduplicated_bundle, "Condition")
        self.assertEqual(len(conditions), 1)
        self.assertEqual(conditions[0].id, self.condition1.id)
    
    def test_deduplicate_bundle_no_duplicates(self):
        """Test deduplication when no duplicates exist."""
        bundle = create_initial_patient_bundle(self.patient)
        bundle = add_resource_to_bundle(bundle, self.condition_unique)
        
        original_count = len(bundle.entry)
        deduplicated_bundle = deduplicate_bundle(bundle)
        
        # Should have same number of entries
        self.assertEqual(len(deduplicated_bundle.entry), original_count)
    
    def test_deduplicate_bundle_none_bundle(self):
        """Test deduplication with None bundle."""
        with self.assertRaises(ValueError) as context:
            deduplicate_bundle(None)
        self.assertIn("Bundle is required", str(context.exception))


class TestResourceVersionHistory(unittest.TestCase):
    """Test cases for resource version history functionality."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create test patient
        self.patient = PatientResource.create_from_demographics(
            mrn="TEST123",
            first_name="John",
            last_name="Doe",
            birth_date=date(1990, 1, 15),
            patient_id="patient-123"
        )
        
        # Create different versions of the same condition
        self.condition_v1 = ConditionResource.create_from_diagnosis(
            patient_id="patient-123",
            condition_code="E11.9",
            condition_display="Type 2 diabetes mellitus",
            condition_id="condition-123"
        )
        self.condition_v1.meta.versionId = "1"
        
        self.condition_v2 = ConditionResource.create_from_diagnosis(
            patient_id="patient-123",
            condition_code="E11.9",
            condition_display="Type 2 diabetes mellitus - updated",
            condition_id="condition-123"  # Same ID
        )
        self.condition_v2.meta.versionId = "2"
        
        self.condition_v3 = ConditionResource.create_from_diagnosis(
            patient_id="patient-123",
            condition_code="E11.9",
            condition_display="Type 2 diabetes mellitus - final",
            condition_id="condition-123"  # Same ID
        )
        self.condition_v3.meta.versionId = "3"
    
    def test_get_resource_version_history_success(self):
        """Test getting version history for a resource."""
        # Create bundle with multiple versions (using update_existing=False to preserve all versions)
        bundle = create_initial_patient_bundle(self.patient)
        bundle = add_resource_to_bundle(bundle, self.condition_v1, update_existing=False)
        bundle = add_resource_to_bundle(bundle, self.condition_v2, update_existing=False)
        bundle = add_resource_to_bundle(bundle, self.condition_v3, update_existing=False)
        
        versions = get_resource_version_history(bundle, "Condition", "condition-123")
        
        # Should get all 3 versions, sorted by version (latest first)
        self.assertEqual(len(versions), 3)
        self.assertEqual(versions[0].meta.versionId, "3")
        self.assertEqual(versions[1].meta.versionId, "2")
        self.assertEqual(versions[2].meta.versionId, "1")
    
    def test_get_resource_version_history_not_found(self):
        """Test getting version history for non-existent resource."""
        bundle = create_initial_patient_bundle(self.patient)
        
        versions = get_resource_version_history(bundle, "Condition", "nonexistent")
        
        self.assertEqual(len(versions), 0)
    
    def test_get_resource_version_history_invalid_inputs(self):
        """Test getting version history with invalid inputs."""
        bundle = create_initial_patient_bundle(self.patient)
        
        # Test with None bundle
        with self.assertRaises(ValueError) as context:
            get_resource_version_history(None, "Condition", "condition-123")
        self.assertIn("Bundle is required", str(context.exception))
        
        # Test with empty resource type
        with self.assertRaises(ValueError) as context:
            get_resource_version_history(bundle, "", "condition-123")
        self.assertIn("Resource type and ID are required", str(context.exception))
        
        # Test with empty resource ID
        with self.assertRaises(ValueError) as context:
            get_resource_version_history(bundle, "Condition", "")
        self.assertIn("Resource type and ID are required", str(context.exception))
    
    def test_get_latest_resource_version_success(self):
        """Test getting latest version of a resource."""
        # Create bundle with multiple versions (using update_existing=False to preserve all versions)
        bundle = create_initial_patient_bundle(self.patient)
        bundle = add_resource_to_bundle(bundle, self.condition_v1, update_existing=False)
        bundle = add_resource_to_bundle(bundle, self.condition_v2, update_existing=False)
        bundle = add_resource_to_bundle(bundle, self.condition_v3, update_existing=False)
        
        latest = get_latest_resource_version(bundle, "Condition", "condition-123")
        
        self.assertIsNotNone(latest)
        self.assertEqual(latest.meta.versionId, "3")
        self.assertIn("final", latest.code.coding[0].display)
    
    def test_get_latest_resource_version_not_found(self):
        """Test getting latest version for non-existent resource."""
        bundle = create_initial_patient_bundle(self.patient)
        
        latest = get_latest_resource_version(bundle, "Condition", "nonexistent")
        
        self.assertIsNone(latest)
    
    def test_get_latest_resource_version_single_version(self):
        """Test getting latest version when only one version exists."""
        bundle = create_initial_patient_bundle(self.patient)
        bundle = add_resource_to_bundle(bundle, self.condition_v1)
        
        latest = get_latest_resource_version(bundle, "Condition", "condition-123")
        
        self.assertIsNotNone(latest)
        self.assertEqual(latest.meta.versionId, "1")


class TestProvenanceTracking(unittest.TestCase):
    """Test cases for resource provenance tracking functionality."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create test patient
        self.test_patient = PatientResource.create_from_demographics(
            mrn="PROV123",
            first_name="Jane",
            last_name="Smith",
            birth_date=date(1985, 5, 20),
            patient_id="patient-prov-123"
        )
        
        # Create test condition
        self.test_condition = ConditionResource.create_from_diagnosis(
            patient_id="patient-prov-123",
            condition_code="I10",
            condition_display="Essential hypertension",
            condition_id="condition-prov-456"
        )
        
        # Create test observation
        self.test_observation = ObservationResource.create_from_lab_result(
            patient_id="patient-prov-123",
            test_code="2093-3",
            test_name="Cholesterol [Mass/volume] in Serum or Plasma",
            value=180,
            unit="mg/dL",
            observation_id="observation-prov-789"
        )
    
    def test_add_resource_with_provenance_new_resource(self):
        """Test adding a new resource with provenance tracking."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Add condition with provenance
        updated_bundle = add_resource_with_provenance(
            bundle=bundle,
            resource=self.test_condition,
            source_system="EMR-System-Test",
            responsible_party="Dr. Johnson",
            reason="Initial diagnosis",
            source_document_id="doc-123"
        )
        
        # Verify condition was added
        conditions = get_resources_by_type(updated_bundle, "Condition")
        self.assertEqual(len(conditions), 1)
        self.assertEqual(conditions[0].id, self.test_condition.id)
        
        # Verify provenance was created
        provenances = get_resources_by_type(updated_bundle, "Provenance")
        self.assertEqual(len(provenances), 1)
        
        provenance = provenances[0]
        self.assertIsInstance(provenance, ProvenanceResource)
        self.assertEqual(provenance.get_target_reference(), f"Condition/{self.test_condition.id}")
        self.assertEqual(provenance.get_source_system(), "EMR-System-Test")
        self.assertEqual(provenance.get_responsible_party(), "Dr. Johnson")
        self.assertEqual(provenance.get_activity_type(), "create")
        self.assertEqual(provenance.get_source_document_id(), "doc-123")
    
    def test_add_resource_with_provenance_update_existing(self):
        """Test updating an existing resource with provenance tracking."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Add initial condition with provenance
        bundle = add_resource_with_provenance(
            bundle=bundle,
            resource=self.test_condition,
            source_system="EMR-System-Test",
            responsible_party="Dr. Johnson",
            reason="Initial diagnosis"
        )
        
        # Create updated condition
        updated_condition = ConditionResource.create_from_diagnosis(
            patient_id="patient-prov-123",
            condition_code="I10",
            condition_display="Essential hypertension - confirmed",
            condition_id="condition-prov-456"  # Same ID
        )
        
        # Update condition with provenance
        updated_bundle = add_resource_with_provenance(
            bundle=bundle,
            resource=updated_condition,
            source_system="EMR-System-Test",
            responsible_party="Dr. Smith",
            reason="Diagnosis confirmed",
            update_existing=True
        )
        
        # Should still have 1 condition
        conditions = get_resources_by_type(updated_bundle, "Condition")
        self.assertEqual(len(conditions), 1)
        self.assertIn("confirmed", conditions[0].get_condition_display())
        
        # Should have 2 provenance resources (original + update)
        provenances = get_resources_by_type(updated_bundle, "Provenance")
        self.assertEqual(len(provenances), 2)
        
        # Find the update provenance
        update_provenance = None
        for prov in provenances:
            if prov.get_activity_type() == "update":
                update_provenance = prov
                break
        
        self.assertIsNotNone(update_provenance)
        self.assertEqual(update_provenance.get_responsible_party(), "Dr. Smith")
        self.assertIsNotNone(update_provenance.get_previous_provenance_id())
    
    def test_add_resource_with_provenance_invalid_inputs(self):
        """Test adding resource with provenance using invalid inputs."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Test with None bundle
        with self.assertRaises(ValueError) as context:
            add_resource_with_provenance(None, self.test_condition, "EMR-System")
        self.assertIn("Bundle is required", str(context.exception))
        
        # Test with None resource
        with self.assertRaises(ValueError) as context:
            add_resource_with_provenance(bundle, None, "EMR-System")
        self.assertIn("Resource is required", str(context.exception))
        
        # Test with empty source system
        with self.assertRaises(ValueError) as context:
            add_resource_with_provenance(bundle, self.test_condition, "")
        self.assertIn("Source system is required", str(context.exception))
    
    def test_find_resource_provenance_success(self):
        """Test finding provenance for a specific resource."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Add condition with provenance
        bundle = add_resource_with_provenance(
            bundle=bundle,
            resource=self.test_condition,
            source_system="EMR-System-Test",
            responsible_party="Dr. Johnson"
        )
        
        # Find provenance
        provenance = find_resource_provenance(bundle, "Condition", self.test_condition.id)
        
        self.assertIsNotNone(provenance)
        self.assertIsInstance(provenance, ProvenanceResource)
        self.assertEqual(provenance.get_target_reference(), f"Condition/{self.test_condition.id}")
        self.assertEqual(provenance.get_source_system(), "EMR-System-Test")
    
    def test_find_resource_provenance_not_found(self):
        """Test finding provenance for non-existent resource."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Try to find provenance for resource that doesn't exist
        provenance = find_resource_provenance(bundle, "Condition", "non-existent-id")
        
        self.assertIsNone(provenance)
    
    def test_find_resource_provenance_invalid_inputs(self):
        """Test finding provenance with invalid inputs."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Test with None bundle
        with self.assertRaises(ValueError):
            find_resource_provenance(None, "Condition", "some-id")
        
        # Test with empty resource type
        with self.assertRaises(ValueError):
            find_resource_provenance(bundle, "", "some-id")
        
        # Test with empty resource ID
        with self.assertRaises(ValueError):
            find_resource_provenance(bundle, "Condition", "")
    
    def test_get_provenance_chain_single_resource(self):
        """Test getting provenance chain for resource with single provenance."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Add condition with provenance
        bundle = add_resource_with_provenance(
            bundle=bundle,
            resource=self.test_condition,
            source_system="EMR-System-Test",
            responsible_party="Dr. Johnson"
        )
        
        # Get provenance chain
        chain = get_provenance_chain(bundle, "Condition", self.test_condition.id)
        
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0].get_activity_type(), "create")
        self.assertEqual(chain[0].get_source_system(), "EMR-System-Test")
    
    def test_get_provenance_chain_multiple_updates(self):
        """Test getting provenance chain for resource with multiple updates."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Add initial condition
        bundle = add_resource_with_provenance(
            bundle=bundle,
            resource=self.test_condition,
            source_system="EMR-System-Test",
            responsible_party="Dr. Johnson",
            reason="Initial diagnosis"
        )
        
        # Update condition first time
        updated_condition1 = ConditionResource.create_from_diagnosis(
            patient_id="patient-prov-123",
            condition_code="I10",
            condition_display="Essential hypertension - stage 1",
            condition_id="condition-prov-456"
        )
        
        bundle = add_resource_with_provenance(
            bundle=bundle,
            resource=updated_condition1,
            source_system="EMR-System-Test",
            responsible_party="Dr. Smith",
            reason="Staging added",
            update_existing=True
        )
        
        # Update condition second time
        updated_condition2 = ConditionResource.create_from_diagnosis(
            patient_id="patient-prov-123",
            condition_code="I10",
            condition_display="Essential hypertension - stage 1 - controlled",
            condition_id="condition-prov-456"
        )
        
        bundle = add_resource_with_provenance(
            bundle=bundle,
            resource=updated_condition2,
            source_system="EMR-System-Test",
            responsible_party="Dr. Brown",
            reason="Treatment response noted",
            update_existing=True
        )
        
        # Get provenance chain
        chain = get_provenance_chain(bundle, "Condition", self.test_condition.id)
        
        # Should have 3 provenance entries (create + 2 updates)
        self.assertEqual(len(chain), 3)
        
        # Check chronological order (oldest first)
        self.assertEqual(chain[0].get_activity_type(), "create")
        self.assertEqual(chain[0].get_responsible_party(), "Dr. Johnson")
        
        self.assertEqual(chain[1].get_activity_type(), "update")
        self.assertEqual(chain[1].get_responsible_party(), "Dr. Smith")
        
        self.assertEqual(chain[2].get_activity_type(), "update")
        self.assertEqual(chain[2].get_responsible_party(), "Dr. Brown")
        
        # Check chain links
        self.assertIsNone(chain[0].get_previous_provenance_id())  # First has no previous
        self.assertEqual(chain[1].get_previous_provenance_id(), chain[0].id)
        self.assertEqual(chain[2].get_previous_provenance_id(), chain[1].id)
    
    def test_get_provenance_chain_no_provenance(self):
        """Test getting provenance chain for resource without provenance."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Add condition without provenance (using regular add function)
        bundle = add_resource_to_bundle(bundle, self.test_condition)
        
        # Get provenance chain
        chain = get_provenance_chain(bundle, "Condition", self.test_condition.id)
        
        self.assertEqual(len(chain), 0)
    
    def test_get_provenance_summary_with_provenance(self):
        """Test getting provenance summary for resource with provenance."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Add condition with provenance
        bundle = add_resource_with_provenance(
            bundle=bundle,
            resource=self.test_condition,
            source_system="EMR-System-Test",
            responsible_party="Dr. Johnson",
            reason="Initial diagnosis",
            source_document_id="doc-123"
        )
        
        # Get summary
        summary = get_provenance_summary(bundle, "Condition", self.test_condition.id)
        
        self.assertTrue(summary["has_provenance"])
        self.assertEqual(summary["chain_length"], 1)
        self.assertEqual(len(summary["activities"]), 1)
        self.assertEqual(summary["source_systems"], ["EMR-System-Test"])
        self.assertEqual(summary["responsible_parties"], ["Dr. Johnson"])
        
        # Check activity details
        activity = summary["activities"][0]
        self.assertEqual(activity["activity_type"], "create")
        self.assertEqual(activity["source_system"], "EMR-System-Test")
        self.assertEqual(activity["responsible_party"], "Dr. Johnson")
        self.assertEqual(activity["source_document_id"], "doc-123")
    
    def test_get_provenance_summary_no_provenance(self):
        """Test getting provenance summary for resource without provenance."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Add condition without provenance
        bundle = add_resource_to_bundle(bundle, self.test_condition)
        
        # Get summary
        summary = get_provenance_summary(bundle, "Condition", self.test_condition.id)
        
        self.assertFalse(summary["has_provenance"])
        self.assertEqual(summary["chain_length"], 0)
        self.assertEqual(len(summary["activities"]), 0)
        self.assertEqual(summary["source_systems"], [])
        self.assertEqual(summary["responsible_parties"], [])
    
    def test_get_all_provenance_resources(self):
        """Test getting all provenance resources from bundle."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Add multiple resources with provenance
        bundle = add_resource_with_provenance(
            bundle=bundle,
            resource=self.test_condition,
            source_system="EMR-System-Test"
        )
        
        bundle = add_resource_with_provenance(
            bundle=bundle,
            resource=self.test_observation,
            source_system="Lab-System-Test"
        )
        
        # Get all provenance resources
        all_provenance = get_all_provenance_resources(bundle)
        
        self.assertEqual(len(all_provenance), 2)
        
        # Check that all are ProvenanceResource instances
        for prov in all_provenance:
            self.assertIsInstance(prov, ProvenanceResource)
        
        # Check different source systems
        source_systems = {prov.get_source_system() for prov in all_provenance}
        self.assertEqual(source_systems, {"EMR-System-Test", "Lab-System-Test"})
    
    def test_validate_provenance_integrity_valid_bundle(self):
        """Test provenance integrity validation on a valid bundle."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Add resources with proper provenance
        bundle = add_resource_with_provenance(
            bundle=bundle,
            resource=self.test_condition,
            source_system="EMR-System-Test"
        )
        
        bundle = add_resource_with_provenance(
            bundle=bundle,
            resource=self.test_observation,
            source_system="Lab-System-Test"
        )
        
        # Validate integrity
        validation_result = validate_provenance_integrity(bundle)
        
        self.assertTrue(validation_result["is_valid"])
        self.assertEqual(len(validation_result["issues"]), 0)
        self.assertEqual(validation_result["total_provenance_resources"], 2)
        self.assertEqual(validation_result["resources_with_provenance"], 2)  # Condition + Observation
        self.assertEqual(validation_result["resources_without_provenance"], 1)  # Patient has no provenance
        self.assertEqual(validation_result["orphaned_provenance"], 0)
        self.assertEqual(validation_result["broken_chains"], 0)
    
    def test_validate_provenance_integrity_with_issues(self):
        """Test provenance integrity validation with various issues."""
        bundle = create_initial_patient_bundle(self.test_patient)
        
        # Add condition with valid provenance
        bundle = add_resource_with_provenance(
            bundle=bundle,
            resource=self.test_condition,
            source_system="EMR-System-Test"
        )
        
        # Manually create a broken provenance (orphaned)
        orphaned_provenance = ProvenanceResource.create_for_resource(
            target_resource=self.test_observation,  # Observation not in bundle
            source_system="Lab-System-Test"
        )
        bundle = add_resource_to_bundle(bundle, orphaned_provenance)
        
        # Validate integrity
        validation_result = validate_provenance_integrity(bundle)
        
        self.assertFalse(validation_result["is_valid"])
        self.assertGreater(len(validation_result["issues"]), 0)
        self.assertEqual(validation_result["orphaned_provenance"], 1)
        
        # Check for orphaned provenance issue
        orphaned_issues = [issue for issue in validation_result["issues"] 
                          if "Orphaned provenance" in issue]
        self.assertEqual(len(orphaned_issues), 1)


class TestProvenanceResourceModel(unittest.TestCase):
    """Test cases for ProvenanceResource model functionality."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.test_patient = PatientResource.create_from_demographics(
            mrn="PROV456",
            first_name="Bob",
            last_name="Wilson",
            birth_date=date(1975, 8, 10),
            patient_id="patient-model-123"
        )
        
        self.test_condition = ConditionResource.create_from_diagnosis(
            patient_id="patient-model-123",
            condition_code="M25.511",
            condition_display="Pain in right shoulder",
            condition_id="condition-model-456"
        )
    
    def test_create_for_resource_basic(self):
        """Test basic provenance creation for a resource."""
        provenance = ProvenanceResource.create_for_resource(
            target_resource=self.test_condition,
            source_system="EMR-System-Test"
        )
        
        self.assertIsNotNone(provenance.id)
        self.assertEqual(provenance.get_target_reference(), f"Condition/{self.test_condition.id}")
        self.assertEqual(provenance.get_source_system(), "EMR-System-Test")
        self.assertEqual(provenance.get_activity_type(), "create")
        self.assertIsNotNone(provenance.occurredDateTime)
        self.assertIsNotNone(provenance.recorded)
    
    def test_create_for_resource_with_all_options(self):
        """Test provenance creation with all optional parameters."""
        test_datetime = datetime(2023, 6, 15, 14, 30, 0)
        
        provenance = ProvenanceResource.create_for_resource(
            target_resource=self.test_condition,
            source_system="EMR-System-Test",
            responsible_party="Dr. Adams",
            activity_type="update",
            provenance_id="custom-prov-id",
            occurred_at=test_datetime,
            reason="Patient follow-up",
            source_document_id="doc-789"
        )
        
        self.assertEqual(provenance.id, "custom-prov-id")
        self.assertEqual(provenance.get_responsible_party(), "Dr. Adams")
        self.assertEqual(provenance.get_activity_type(), "update")
        self.assertEqual(provenance.get_source_document_id(), "doc-789")
        # Check that the datetime is correctly set (allow for format differences)
        occurred_str = str(provenance.occurredDateTime)
        self.assertIn("2023-06-15", occurred_str)
        self.assertIn("14:30:00", occurred_str)
    
    def test_create_for_update_with_chain(self):
        """Test creating update provenance that maintains chain."""
        # Create initial provenance
        initial_provenance = ProvenanceResource.create_for_resource(
            target_resource=self.test_condition,
            source_system="EMR-System-Test",
            responsible_party="Dr. Johnson"
        )
        
        # Create update provenance
        update_provenance = ProvenanceResource.create_for_update(
            target_resource=self.test_condition,
            previous_provenance=initial_provenance,
            responsible_party="Dr. Smith",
            reason="Updated diagnosis"
        )
        
        self.assertEqual(update_provenance.get_activity_type(), "update")
        self.assertEqual(update_provenance.get_responsible_party(), "Dr. Smith")
        self.assertEqual(update_provenance.get_source_system(), "EMR-System-Test")  # Inherited
        self.assertEqual(update_provenance.get_previous_provenance_id(), initial_provenance.id)
    
    def test_provenance_helper_methods(self):
        """Test all provenance helper methods."""
        provenance = ProvenanceResource.create_for_resource(
            target_resource=self.test_condition,
            source_system="EMR-System-Test",
            responsible_party="Dr. Adams",
            activity_type="create",
            source_document_id="doc-123"
        )
        
        # Test all getter methods
        self.assertEqual(provenance.get_target_reference(), f"Condition/{self.test_condition.id}")
        self.assertEqual(provenance.get_source_system(), "EMR-System-Test")
        self.assertEqual(provenance.get_responsible_party(), "Dr. Adams")
        self.assertEqual(provenance.get_activity_type(), "create")
        self.assertEqual(provenance.get_source_document_id(), "doc-123")
        self.assertIsNone(provenance.get_previous_provenance_id())  # No previous for new resource


if __name__ == '__main__':
    unittest.main() 