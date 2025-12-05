"""
Tests for idempotent FHIR merge in Patient model (Task 41.6).
Tests the refactored add_fhir_resources() method with composite key matching.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model

from apps.patients.models import Patient, PatientHistory

User = get_user_model()


class IdempotentFHIRMergeTests(TestCase):
    """
    Tests for idempotent FHIR merging using composite key matching (Task 41.6).
    Verifies that add_fhir_resources() now updates instead of duplicating.
    """
    
    def setUp(self):
        """Set up test data"""
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            mrn='TEST-001'
        )
    
    def test_same_document_processed_twice_updates_not_duplicates(self):
        """Test idempotency: processing same document twice updates, not duplicates"""
        # First processing of document 1
        resources_v1 = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetes'}, 'version': 1},
        ]
        
        self.patient.add_fhir_resources(resources_v1, document_id=1)
        
        # Verify 1 resource added
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 1)
        self.assertEqual(bundle['entry'][0]['resource']['version'], 1)
        
        # Second processing of same document (updated data)
        resources_v2 = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetes Type 2'}, 'version': 2},
        ]
        
        self.patient.add_fhir_resources(resources_v2, document_id=1)
        
        # Verify still only 1 resource (updated, not duplicated)
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 1)
        
        # Verify it's the updated version
        condition = bundle['entry'][0]['resource']
        self.assertEqual(condition['code']['text'], 'Diabetes Type 2')
        self.assertEqual(condition['version'], 2)
    
    def test_different_documents_both_added(self):
        """Test that resources from different documents are all added"""
        # Document 1
        resources_doc1 = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetes'}},
        ]
        self.patient.add_fhir_resources(resources_doc1, document_id=1)
        
        # Document 2  
        resources_doc2 = [
            {'resourceType': 'Condition', 'code': {'text': 'Hypertension'}},
        ]
        self.patient.add_fhir_resources(resources_doc2, document_id=2)
        
        # Both should exist (different documents, different sources)
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 2)
    
    def test_same_document_different_resource_types_all_tracked(self):
        """Test that same document can have multiple resource types tracked independently"""
        # First merge: Condition
        resources1 = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetes'}},
        ]
        self.patient.add_fhir_resources(resources1, document_id=1)
        
        # Second merge: Observation (same document)
        resources2 = [
            {'resourceType': 'Observation', 'code': {'text': 'Blood Pressure'}},
        ]
        self.patient.add_fhir_resources(resources2, document_id=1)
        
        # Both should exist (different resource types)
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 2)
        
        # Update the Condition
        resources3 = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetes Type 2'}},
        ]
        self.patient.add_fhir_resources(resources3, document_id=1)
        
        # Should still be 2 resources (Condition updated, Observation unchanged)
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 2)
        
        # Verify Condition was updated
        condition = [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'Condition'][0]
        self.assertEqual(condition['code']['text'], 'Diabetes Type 2')
    
    def test_resources_tagged_with_composite_key_components(self):
        """Test that resources are tagged with meta.source for composite key"""
        resources = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetes'}},
        ]
        
        self.patient.add_fhir_resources(resources, document_id=42)
        
        bundle = self.patient.encrypted_fhir_bundle
        resource = bundle['entry'][0]['resource']
        
        # Verify composite key component
        self.assertEqual(resource['meta']['source'], 'document_42')
        self.assertEqual(resource['resourceType'], 'Condition')
    
    def test_audit_trail_includes_merge_statistics(self):
        """Test that audit record includes added/updated counts"""
        resources = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetes'}},
        ]
        
        self.patient.add_fhir_resources(resources, document_id=1)
        
        # Check audit record
        audit = PatientHistory.objects.latest('created_at')
        self.assertEqual(audit.action, 'fhir_merge')
        self.assertIn('added_count', audit.fhir_delta)
        self.assertIn('updated_count', audit.fhir_delta)
        self.assertEqual(audit.fhir_delta['added_count'], 1)
        self.assertEqual(audit.fhir_delta['updated_count'], 0)
    
    def test_backward_compatibility_without_document_id(self):
        """Test that method still works without document_id (backward compatibility)"""
        resources = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetes'}},
        ]
        
        # Should work without document_id (no composite key matching)
        result = self.patient.add_fhir_resources(resources, document_id=None)
        
        self.assertTrue(result)
        
        # Verify resource added
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 1)
        
        # Meta.source should be 'direct_entry'
        self.assertEqual(bundle['entry'][0]['resource']['meta']['source'], 'direct_entry')
    
    def test_without_document_id_always_appends(self):
        """Test that without document_id, resources are always appended (no deduplication)"""
        resources1 = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetes'}},
        ]
        
        # Add twice without document_id
        self.patient.add_fhir_resources(resources1, document_id=None)
        self.patient.add_fhir_resources(resources1, document_id=None)
        
        # Should create duplicates (no composite key matching without document_id)
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 2)

