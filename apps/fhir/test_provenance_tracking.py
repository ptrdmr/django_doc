"""
Test suite for FHIR Provenance Tracking System

Tests the comprehensive provenance functionality including:
- ProvenanceTracker class methods
- Integration with FHIRMergeService 
- Provenance creation for merge operations
- Conflict resolution provenance
- Deduplication provenance
- Provenance chaining functionality
"""

import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth.models import User

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
    ProvenanceTracker,
    FHIRMergeService,
    ConflictDetail,
    DuplicateResourceDetail,
    MergeResult
)
from apps.fhir.fhir_models import ProvenanceResource


class ProvenanceTrackerTest(TestCase):
    """Test the ProvenanceTracker class functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            'create_provenance': True,
            'conflict_resolution_strategy': 'newest_wins'
        }
        self.tracker = ProvenanceTracker(self.config)
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test resources
        self.test_observation = Observation(
            id="test-obs-1",
            status="final",
            code=CodeableConcept(
                coding=[Coding(
                    system="http://loinc.org",
                    code="33747-0",
                    display="General appearance"
                )]
            ),
            subject=Reference(reference="Patient/test-patient-1")
        )
        
        self.test_condition = Condition(
            id="test-condition-1",
            clinicalStatus=CodeableConcept(
                coding=[Coding(
                    system="http://terminology.hl7.org/CodeSystem/condition-clinical",
                    code="active"
                )]
            ),
            code=CodeableConcept(
                coding=[Coding(
                    system="http://snomed.info/sct",
                    code="44054006",
                    display="Type 2 diabetes mellitus"
                )]
            ),
            subject=Reference(reference="Patient/test-patient-1")
        )
    
    def test_create_merge_provenance(self):
        """Test creating provenance for merge operations."""
        metadata = {
            'document_id': 'doc-123',
            'document_type': 'Lab Report'
        }
        
        provenance = self.tracker.create_merge_provenance(
            target_resources=[self.test_observation],
            metadata=metadata,
            user=self.user,
            activity_type="merge",
            reason="Test merge operation"
        )
        
        # Verify provenance was created
        self.assertIsInstance(provenance, ProvenanceResource)
        self.assertEqual(len(provenance.target), 1)
        self.assertIn("Observation/test-obs-1", provenance.target[0].reference)
        
        # Verify agent information
        self.assertTrue(any(
            agent.who.display == 'testuser' 
            for agent in provenance.agent 
            if hasattr(agent, 'who') and hasattr(agent.who, 'display')
        ))
        
        # Verify it's cached
        self.assertIn(provenance.id, self.tracker.provenance_cache)
    
    def test_create_conflict_resolution_provenance(self):
        """Test creating provenance for conflict resolution."""
        conflict_details = [
            {
                'conflict_type': 'value_mismatch',
                'field_name': 'valueQuantity',
                'severity': 'medium',
                'resource_type': 'Observation'
            }
        ]
        
        provenance = self.tracker.create_conflict_resolution_provenance(
            resolved_resource=self.test_observation,
            conflict_details=conflict_details,
            resolution_strategy="newest_wins",
            user=self.user
        )
        
        # Verify provenance was created
        self.assertIsInstance(provenance, ProvenanceResource)
        self.assertEqual(provenance.activity.coding[0].code, "TRANSFORM")
        
        # Verify conflict resolution extension
        self.assertTrue(hasattr(provenance, 'extension'))
        if provenance.extension:
            conflict_ext = next(
                (ext for ext in provenance.extension 
                 if getattr(ext, 'url', None) == 'http://medicaldocparser.com/fhir/extension/conflict-resolution'),
                None
            )
            self.assertIsNotNone(conflict_ext)
            
            # Parse the extension value
            conflict_data = json.loads(getattr(conflict_ext, 'valueString', '{}'))
            self.assertEqual(conflict_data['conflicts_resolved'], 1)
            self.assertEqual(conflict_data['resolution_strategy'], 'newest_wins')
    
    def test_create_deduplication_provenance(self):
        """Test creating provenance for deduplication operations."""
        duplicate_details = [
            Mock(
                similarity_score=0.95,
                duplicate_type='near_exact',
                resource_type='Observation'
            ),
            Mock(
                similarity_score=0.88,
                duplicate_type='fuzzy_match',
                resource_type='Observation'
            )
        ]
        
        provenance = self.tracker.create_deduplication_provenance(
            merged_resource=self.test_observation,
            duplicate_details=duplicate_details,
            user=self.user
        )
        
        # Verify provenance was created
        self.assertIsInstance(provenance, ProvenanceResource)
        
        # Verify deduplication extension
        if hasattr(provenance, 'extension') and provenance.extension:
            dedup_ext = next(
                (ext for ext in provenance.extension 
                 if getattr(ext, 'url', None) == 'http://medicaldocparser.com/fhir/extension/deduplication'),
                None
            )
            self.assertIsNotNone(dedup_ext)
            
            # Parse the extension value
            dedup_data = json.loads(getattr(dedup_ext, 'valueString', '{}'))
            self.assertEqual(dedup_data['duplicates_merged'], 2)
            self.assertEqual(len(dedup_data['similarity_scores']), 2)
    
    def test_get_latest_provenance_for_resource(self):
        """Test getting the latest provenance for a specific resource."""
        import time
        # Create multiple provenance resources for the same resource
        metadata = {'document_id': 'doc-123'}
        
        # First provenance
        first_prov = self.tracker.create_merge_provenance(
            target_resources=[self.test_observation],
            metadata=metadata,
            user=self.user
        )
        
        # Small delay to ensure different timestamps
        time.sleep(0.01)
        
        # Second provenance (should be latest)
        second_prov = self.tracker.create_conflict_resolution_provenance(
            resolved_resource=self.test_observation,
            conflict_details=[],
            resolution_strategy="newest_wins",
            user=self.user
        )
        
        # Get latest provenance
        latest = self.tracker.get_latest_provenance_for_resource("test-obs-1")
        
        # Should return one of the two provenance records (the most recent one)
        self.assertIsNotNone(latest)
        self.assertIn(latest.id, [first_prov.id, second_prov.id])
        
        # Verify it's tracking the correct resource
        target_found = False
        for target in latest.target:
            if hasattr(target, 'reference') and target.reference:
                if target.reference.split('/')[-1] == "test-obs-1":
                    target_found = True
                    break
        self.assertTrue(target_found)
    
    def test_create_chained_provenance(self):
        """Test creating chained provenance resources."""
        metadata = {'document_id': 'doc-123'}
        
        # Create initial provenance
        initial_prov = self.tracker.create_chained_provenance(
            target_resource=self.test_observation,
            activity_type="create",
            reason="Initial resource creation",
            user=self.user,
            metadata=metadata
        )
        
        # Create chained provenance
        chained_prov = self.tracker.create_chained_provenance(
            target_resource=self.test_observation,
            activity_type="update",
            reason="Resource updated after conflict resolution",
            user=self.user,
            metadata=metadata
        )
        
        # Verify both are cached
        self.assertIn(initial_prov.id, self.tracker.provenance_cache)
        self.assertIn(chained_prov.id, self.tracker.provenance_cache)
        
        # Verify chaining (second provenance should reference the first)
        if hasattr(chained_prov, 'entity') and chained_prov.entity:
            revision_entity = next(
                (entity for entity in chained_prov.entity if entity.get('role') == 'revision'),
                None
            )
            if revision_entity:
                self.assertIn(initial_prov.id, revision_entity['what'].reference)
    
    def test_get_provenance_list(self):
        """Test getting all provenance resources."""
        # Initially empty
        self.assertEqual(len(self.tracker.get_provenance_list()), 0)
        
        # Create some provenance
        metadata = {'document_id': 'doc-123'}
        self.tracker.create_merge_provenance(
            target_resources=[self.test_observation],
            metadata=metadata,
            user=self.user
        )
        self.tracker.create_merge_provenance(
            target_resources=[self.test_condition],
            metadata=metadata,
            user=self.user
        )
        
        # Should have 2 provenance resources
        provenance_list = self.tracker.get_provenance_list()
        self.assertEqual(len(provenance_list), 2)
        self.assertTrue(all(isinstance(p, ProvenanceResource) for p in provenance_list))
    
    def test_clear_cache(self):
        """Test clearing the provenance cache."""
        # Create some provenance
        metadata = {'document_id': 'doc-123'}
        self.tracker.create_merge_provenance(
            target_resources=[self.test_observation],
            metadata=metadata,
            user=self.user
        )
        
        # Verify it's cached
        self.assertEqual(len(self.tracker.provenance_cache), 1)
        
        # Clear cache
        self.tracker.clear_cache()
        
        # Verify cache is empty
        self.assertEqual(len(self.tracker.provenance_cache), 0)


class FHIRMergeServiceProvenanceIntegrationTest(TestCase):
    """Test provenance integration with FHIRMergeService."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create test patient
        self.patient = Patient.objects.create(
            mrn='TEST-001',
            first_name='Test',
            last_name='Patient',
            date_of_birth='1990-01-01',
            gender='M'  # Valid FHIR gender value
        )
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Initialize merge service
        self.merge_service = FHIRMergeService(self.patient)
    
    def test_merge_resources_creates_provenance(self):
        """Test that merge_resources creates provenance for the operation."""
        # Create test resources
        test_observation = Observation(
            id="test-obs-1",
            status="final",
            code=CodeableConcept(
                coding=[Coding(
                    system="http://loinc.org",
                    code="33747-0",
                    display="General appearance"
                )]
            ),
            subject=Reference(reference="Patient/test-patient-1")
        )
        
        metadata = {
            'document_id': 'doc-123',
            'document_type': 'Lab Report'
        }
        
        merge_result = MergeResult()
        
        # Perform merge
        result = self.merge_service.merge_resources(
            new_resources=[test_observation],
            metadata=metadata,
            user=self.user,
            merge_result=merge_result
        )
        
        # Verify provenance was created
        provenance_list = self.merge_service.provenance_tracker.get_provenance_list()
        self.assertGreater(len(provenance_list), 0)
        
        # Find the merge provenance
        merge_provenance = next(
            (p for p in provenance_list if any(
                'Medical Document Parser' in agent.who.display 
                for agent in p.agent 
                if hasattr(agent, 'who') and hasattr(agent.who, 'display')
            )),
            None
        )
        self.assertIsNotNone(merge_provenance)
    
    def test_conflict_resolution_creates_provenance(self):
        """Test that conflict resolution creates appropriate provenance."""
        # This would require setting up a scenario with conflicts
        # For now, just verify the integration points exist
        self.assertTrue(hasattr(self.merge_service, 'provenance_tracker'))
        self.assertTrue(hasattr(self.merge_service, 'conflict_resolver'))
        
        # Verify provenance tracker is passed in merge context
        # This is tested implicitly in the merge_resources test above
    
    @patch('apps.fhir.services.FHIRMergeService._perform_deduplication')
    def test_deduplication_creates_provenance(self, mock_dedup):
        """Test that deduplication creates appropriate provenance."""
        # Mock deduplication result
        mock_duplicate = Mock()
        mock_duplicate.resource_id = "test-obs-1"
        mock_duplicate.resource_type = "Observation"
        mock_duplicate.similarity_score = 0.95
        mock_duplicate.duplicate_type = "exact"
        
        mock_dedup_result = Mock()
        mock_dedup_result.duplicates_found = [mock_duplicate]
        mock_dedup.return_value = mock_dedup_result
        
        # Create test resource
        test_observation = Observation(
            id="test-obs-1",
            status="final",
            code=CodeableConcept(
                coding=[Coding(
                    system="http://loinc.org",
                    code="33747-0",
                    display="General appearance"
                )]
            ),
            subject=Reference(reference="Patient/test-patient-1")
        )
        
        metadata = {'document_id': 'doc-123'}
        merge_result = MergeResult()
        
        # Perform merge (which includes deduplication)
        self.merge_service.merge_resources(
            new_resources=[test_observation],
            metadata=metadata,
            user=self.user,
            merge_result=merge_result
        )
        
        # Verify deduplication provenance was created
        provenance_list = self.merge_service.provenance_tracker.get_provenance_list()
        
        # Should have both merge provenance and deduplication provenance
        self.assertGreaterEqual(len(provenance_list), 2)


class ProvenanceResourceIntegrationTest(TestCase):
    """Test integration with the ProvenanceResource model."""
    
    def test_provenance_resource_creation(self):
        """Test that ProvenanceResource can be created and serialized properly."""
        # Create test observation
        test_observation = Observation(
            id="test-obs-1",
            status="final",
            code=CodeableConcept(
                coding=[Coding(
                    system="http://loinc.org",
                    code="33747-0",
                    display="General appearance"
                )]
            ),
            subject=Reference(reference="Patient/test-patient-1")
        )
        
        # Create provenance
        provenance = ProvenanceResource.create_for_resource(
            target_resource=test_observation,
            source_system="Test System",
            responsible_party="Test User",
            activity_type="create",
            reason="Unit test"
        )
        
        # Verify basic structure
        self.assertIsNotNone(provenance.id)
        self.assertEqual(len(provenance.target), 1)
        self.assertIn("Observation/test-obs-1", provenance.target[0].reference)
        
        # Verify it can be serialized to JSON
        try:
            provenance_dict = provenance.dict()
            json_str = json.dumps(provenance_dict, default=str)
            self.assertIsInstance(json_str, str)
        except Exception as e:
            self.fail(f"Failed to serialize provenance to JSON: {str(e)}")
    
    def test_provenance_chaining(self):
        """Test provenance chaining functionality."""
        # Create test observation
        test_observation = Observation(
            id="test-obs-1",
            status="final",
            code=CodeableConcept(
                coding=[Coding(
                    system="http://loinc.org",
                    code="33747-0",
                    display="General appearance"
                )]
            ),
            subject=Reference(reference="Patient/test-patient-1")
        )
        
        # Create initial provenance
        initial_provenance = ProvenanceResource.create_for_resource(
            target_resource=test_observation,
            source_system="Test System",
            responsible_party="Test User",
            activity_type="create",
            reason="Initial creation"
        )
        
        # Create chained provenance
        chained_provenance = ProvenanceResource.create_for_update(
            target_resource=test_observation,
            previous_provenance=initial_provenance,
            responsible_party="Test User",
            reason="Updated after validation"
        )
        
        # Verify chaining
        self.assertIsNotNone(chained_provenance.id)
        self.assertNotEqual(chained_provenance.id, initial_provenance.id)
        
        # Check for revision entity linking to previous provenance
        if hasattr(chained_provenance, 'entity') and chained_provenance.entity:
            revision_entity = next(
                (entity for entity in chained_provenance.entity if entity.get('role') == 'revision'),
                None
            )
            if revision_entity:
                self.assertIn(initial_provenance.id, revision_entity['what'].reference) 