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
    
    def test_same_document_multiple_resource_types_in_single_call(self):
        """Test that a document with multiple resource types is handled in one call"""
        resources = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetes'}},
            {'resourceType': 'Observation', 'code': {'text': 'Blood Pressure'}},
        ]
        self.patient.add_fhir_resources(resources, document_id=1)
        
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 2)
        
        # Reprocess: updated Condition, same Observation
        resources_v2 = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetes Type 2'}},
            {'resourceType': 'Observation', 'code': {'text': 'Blood Pressure Updated'}},
        ]
        self.patient.add_fhir_resources(resources_v2, document_id=1)
        
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 2)
        
        condition = [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'Condition'][0]
        self.assertEqual(condition['code']['text'], 'Diabetes Type 2')
        
        observation = [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'Observation'][0]
        self.assertEqual(observation['code']['text'], 'Blood Pressure Updated')
    
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
        """Test that audit record includes added/replaced counts"""
        resources = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetes'}},
        ]
        
        self.patient.add_fhir_resources(resources, document_id=1)
        
        # Check audit record
        audit = PatientHistory.objects.latest('created_at')
        self.assertEqual(audit.action, 'fhir_merge')
        self.assertIn('added_count', audit.fhir_delta)
        self.assertIn('replaced_count', audit.fhir_delta)
        self.assertEqual(audit.fhir_delta['added_count'], 1)
        self.assertEqual(audit.fhir_delta['replaced_count'], 0)
    
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
    
    def test_reprocess_multiple_same_type_resources(self):
        """Reprocessing a document with 5 Conditions replaces all 5, no stale entries"""
        conditions_v1 = [
            {'resourceType': 'Condition', 'code': {'text': f'Condition-v1-{i}'}}
            for i in range(5)
        ]
        self.patient.add_fhir_resources(conditions_v1, document_id=1)
        
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 5)
        
        # Reprocess with updated data
        conditions_v2 = [
            {'resourceType': 'Condition', 'code': {'text': f'Condition-v2-{i}'}}
            for i in range(5)
        ]
        self.patient.add_fhir_resources(conditions_v2, document_id=1)
        
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 5, "Reprocessing must not create duplicates")
        
        texts = sorted(e['resource']['code']['text'] for e in bundle['entry'])
        expected = sorted(f'Condition-v2-{i}' for i in range(5))
        self.assertEqual(texts, expected, "All entries must reflect the v2 data, no stale v1 remnants")
    
    def test_reprocess_changes_resource_count(self):
        """Reprocessing may yield a different number of resources than the first run"""
        # First processing: 3 Conditions
        resources_v1 = [
            {'resourceType': 'Condition', 'code': {'text': f'C-{i}'}}
            for i in range(3)
        ]
        self.patient.add_fhir_resources(resources_v1, document_id=1)
        
        self.patient.refresh_from_db()
        self.assertEqual(len(self.patient.encrypted_fhir_bundle['entry']), 3)
        
        # Reprocess: now 5 Conditions (AI found more on second pass)
        resources_v2 = [
            {'resourceType': 'Condition', 'code': {'text': f'C-new-{i}'}}
            for i in range(5)
        ]
        self.patient.add_fhir_resources(resources_v2, document_id=1)
        
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 5, "Count must match incoming set, not accumulate")
        
        texts = sorted(e['resource']['code']['text'] for e in bundle['entry'])
        expected = sorted(f'C-new-{i}' for i in range(5))
        self.assertEqual(texts, expected)
    
    def test_reprocess_mixed_types_multiple_per_type(self):
        """Reprocessing replaces the full resource set from that document, preserving other docs"""
        # Document 1: 3 Conditions + 2 Observations
        doc1_v1 = [
            {'resourceType': 'Condition', 'code': {'text': f'C1-{i}'}} for i in range(3)
        ] + [
            {'resourceType': 'Observation', 'code': {'text': f'O1-{i}'}} for i in range(2)
        ]
        self.patient.add_fhir_resources(doc1_v1, document_id=1)
        
        # Document 2: 1 Condition (should survive doc-1 reprocessing)
        doc2 = [{'resourceType': 'Condition', 'code': {'text': 'C2-only'}}]
        self.patient.add_fhir_resources(doc2, document_id=2)
        
        self.patient.refresh_from_db()
        self.assertEqual(len(self.patient.encrypted_fhir_bundle['entry']), 6)
        
        # Reprocess document 1: now 4 Conditions + 1 Observation
        doc1_v2 = [
            {'resourceType': 'Condition', 'code': {'text': f'C1-new-{i}'}} for i in range(4)
        ] + [
            {'resourceType': 'Observation', 'code': {'text': 'O1-new-0'}},
        ]
        self.patient.add_fhir_resources(doc1_v2, document_id=1)
        
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        
        # 5 from doc 1 (replaced) + 1 from doc 2 (untouched) = 6
        self.assertEqual(len(bundle['entry']), 6)
        
        doc1_entries = [
            e for e in bundle['entry']
            if e['resource']['meta']['source'] == 'document_1'
        ]
        doc2_entries = [
            e for e in bundle['entry']
            if e['resource']['meta']['source'] == 'document_2'
        ]
        
        self.assertEqual(len(doc1_entries), 5, "Doc 1 should have exactly 5 new resources")
        self.assertEqual(len(doc2_entries), 1, "Doc 2 must be untouched by doc 1 reprocess")
        self.assertEqual(doc2_entries[0]['resource']['code']['text'], 'C2-only')
        
        doc1_conditions = [e for e in doc1_entries if e['resource']['resourceType'] == 'Condition']
        doc1_observations = [e for e in doc1_entries if e['resource']['resourceType'] == 'Observation']
        self.assertEqual(len(doc1_conditions), 4)
        self.assertEqual(len(doc1_observations), 1)
    
    def test_reprocess_audit_trail_records_replaced_count(self):
        """Audit trail must distinguish first processing from reprocessing"""
        resources = [
            {'resourceType': 'Condition', 'code': {'text': f'C-{i}'}}
            for i in range(3)
        ]
        self.patient.add_fhir_resources(resources, document_id=1)
        
        first_audit = PatientHistory.objects.latest('created_at')
        self.assertEqual(first_audit.fhir_delta['added_count'], 3)
        self.assertEqual(first_audit.fhir_delta['replaced_count'], 0)
        
        # Reprocess
        resources_v2 = [
            {'resourceType': 'Condition', 'code': {'text': f'C-v2-{i}'}}
            for i in range(3)
        ]
        self.patient.add_fhir_resources(resources_v2, document_id=1)
        
        reprocess_audit = PatientHistory.objects.latest('created_at')
        self.assertEqual(reprocess_audit.fhir_delta['added_count'], 3)
        self.assertEqual(reprocess_audit.fhir_delta['replaced_count'], 3)

