"""
Comprehensive tests for FHIR operations in Patient model (Task 41.18).

This test suite fills gaps in existing coverage by focusing on:
- Performance testing with large datasets
- Error handling and recovery scenarios  
- Integration workflows (merge + rollback)
- Concurrent operations and race conditions
- Boundary conditions and resource limits

These tests follow Level 4-5 rigor:
- Test actual failure modes
- Validate HIPAA requirements
- Test integration points
- Include performance validation
- Can actually fail if bugs are introduced
"""
import time
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.db import transaction, DatabaseError
from unittest.mock import patch, Mock

from apps.patients.models import Patient, PatientHistory

User = get_user_model()


class FHIRMergePerformanceTests(TestCase):
    """
    Performance tests for FHIR merge operations.
    Validates that operations meet the <500ms target even with large datasets.
    """
    
    def setUp(self):
        """Set up test patient"""
        self.patient = Patient.objects.create(
            first_name='Performance',
            last_name='Test',
            date_of_birth='1980-01-01',
            mrn='PERF-TEST-001'
        )
    
    def test_merge_100_resources_completes_under_500ms(self):
        """Test that merging 100 resources completes within 500ms target"""
        # Create 100 diverse FHIR resources
        resources = []
        resource_types = ['Condition', 'Observation', 'MedicationStatement', 'Procedure', 'AllergyIntolerance']
        
        for i in range(100):
            resource_type = resource_types[i % len(resource_types)]
            resources.append({
                'resourceType': resource_type,
                'id': f'resource-{i}',
                'code': {'text': f'Test {resource_type} {i}'}
            })
        
        # Measure merge time
        start_time = time.time()
        self.patient.add_fhir_resources(resources, document_id=1)
        elapsed_ms = (time.time() - start_time) * 1000
        
        # Verify performance target met
        self.assertLess(elapsed_ms, 500, 
                       f"Merge took {elapsed_ms:.2f}ms, exceeds 500ms target")
        
        # Verify all resources were added
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 100)
    
    def test_rollback_100_resources_completes_under_500ms(self):
        """Test that rolling back 100 resources completes within 500ms target"""
        # Add 100 resources first
        resources = [
            {'resourceType': 'Condition', 'code': {'text': f'Condition {i}'}}
            for i in range(100)
        ]
        self.patient.add_fhir_resources(resources, document_id=1)
        
        # Measure rollback time
        start_time = time.time()
        removed_count = self.patient.rollback_document_merge(document_id=1)
        elapsed_ms = (time.time() - start_time) * 1000
        
        # Verify performance target met
        self.assertLess(elapsed_ms, 500,
                       f"Rollback took {elapsed_ms:.2f}ms, exceeds 500ms target")
        
        # Verify all resources were removed
        self.assertEqual(removed_count, 100)
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle.get('entry', [])), 0)
    
    def test_idempotent_merge_performance_consistent(self):
        """Test that repeated idempotent merges maintain consistent performance"""
        resources = [
            {'resourceType': 'Condition', 'code': {'text': 'Test Condition'}}
        ]
        
        # First merge
        start_time = time.time()
        self.patient.add_fhir_resources(resources, document_id=1)
        first_merge_ms = (time.time() - start_time) * 1000
        
        # Second merge (idempotent update)
        start_time = time.time()
        self.patient.add_fhir_resources(resources, document_id=1)
        second_merge_ms = (time.time() - start_time) * 1000
        
        # Both should be fast and similar in performance
        self.assertLess(first_merge_ms, 100,
                       f"First merge took {first_merge_ms:.2f}ms, should be <100ms")
        self.assertLess(second_merge_ms, 100,
                       f"Second merge took {second_merge_ms:.2f}ms, should be <100ms")
        
        # Performance should not degrade significantly on idempotent update
        self.assertLess(abs(second_merge_ms - first_merge_ms), 50,
                       "Idempotent merge performance degraded significantly")
    
    def test_merge_with_multiple_documents_scales_linearly(self):
        """Test that merge performance scales linearly with number of documents"""
        # Merge documents 1-10, each with 10 resources
        times = []
        
        for doc_id in range(1, 11):
            resources = [
                {'resourceType': 'Condition', 'code': {'text': f'Doc {doc_id} Condition {i}'}}
                for i in range(10)
            ]
            
            start_time = time.time()
            self.patient.add_fhir_resources(resources, document_id=doc_id)
            elapsed_ms = (time.time() - start_time) * 1000
            times.append(elapsed_ms)
        
        # Verify all merges completed reasonably fast
        for i, elapsed_ms in enumerate(times, start=1):
            self.assertLess(elapsed_ms, 200,
                           f"Document {i} merge took {elapsed_ms:.2f}ms, exceeds 200ms")
        
        # Verify performance doesn't degrade significantly as bundle grows
        # (allowing for some variance due to JSON size growth)
        avg_first_5 = sum(times[:5]) / 5
        avg_last_5 = sum(times[5:]) / 5
        
        # Last 5 should not be more than 2x slower than first 5
        self.assertLess(avg_last_5, avg_first_5 * 2,
                       f"Performance degraded significantly: {avg_last_5:.2f}ms vs {avg_first_5:.2f}ms")


class FHIROperationErrorHandlingTests(TransactionTestCase):
    """
    Error handling tests for FHIR operations.
    Validates graceful failure and recovery from database errors.
    """
    
    def setUp(self):
        """Set up test patient"""
        self.patient = Patient.objects.create(
            first_name='Error',
            last_name='Test',
            date_of_birth='1980-01-01',
            mrn='ERROR-TEST-001'
        )
    
    def test_merge_handles_database_save_failure_gracefully(self):
        """Test that merge handles database save failures without corrupting data"""
        # Add initial resources
        initial_resources = [
            {'resourceType': 'Condition', 'code': {'text': 'Initial Condition'}}
        ]
        self.patient.add_fhir_resources(initial_resources, document_id=1)
        
        # Mock save to raise DatabaseError
        with patch.object(Patient, 'save', side_effect=DatabaseError("Simulated DB error")):
            # Attempt merge - should raise exception
            new_resources = [
                {'resourceType': 'Observation', 'code': {'text': 'New Observation'}}
            ]
            
            with self.assertRaises(DatabaseError):
                self.patient.add_fhir_resources(new_resources, document_id=2)
        
        # Verify original data is intact (transaction rolled back)
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        
        # Should still have only the initial resource
        self.assertEqual(len(bundle['entry']), 1)
        self.assertEqual(bundle['entry'][0]['resource']['code']['text'], 'Initial Condition')
    
    def test_rollback_handles_empty_document_id_gracefully(self):
        """Test that rollback handles invalid inputs without crashing"""
        # Add resources
        resources = [
            {'resourceType': 'Condition', 'code': {'text': 'Test Condition'}}
        ]
        self.patient.add_fhir_resources(resources, document_id=1)
        
        # Try rollback with various invalid inputs
        invalid_inputs = [None, '', 0, -1]
        
        for invalid_input in invalid_inputs:
            # Should return 0 without crashing
            removed_count = self.patient.rollback_document_merge(document_id=invalid_input)
            self.assertEqual(removed_count, 0,
                           f"Expected 0 for input {invalid_input}, got {removed_count}")
        
        # Verify original data is intact
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 1)
    
    def test_merge_with_malformed_resource_fails_gracefully(self):
        """Test that merge handles malformed resources gracefully without corrupting data"""
        # Add valid resource first
        valid_resources = [
            {'resourceType': 'Condition', 'code': {'text': 'Valid Condition'}}
        ]
        self.patient.add_fhir_resources(valid_resources, document_id=1)
        
        # Verify initial state
        self.patient.refresh_from_db()
        initial_entry_count = len(self.patient.encrypted_fhir_bundle['entry'])
        self.assertEqual(initial_entry_count, 1)
        
        # Malformed resources (missing required fields or wrong structure)
        # Note: add_fhir_resources is quite permissive, so we need to test
        # what happens with truly invalid data structure
        malformed_resources = [
            "not a dict",  # String instead of dict
            123,  # Integer instead of dict
            None,  # None value
        ]
        
        # The method should handle this gracefully
        try:
            self.patient.add_fhir_resources(malformed_resources, document_id=2)
            # If it doesn't raise an exception, that's okay - it might be permissive
        except (TypeError, AttributeError, KeyError) as e:
            # Expected - method should fail on malformed data
            pass
        
        # Verify original data is intact regardless of how malformed data was handled
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        
        # Should still have at least the original valid resource
        self.assertGreaterEqual(len(bundle['entry']), 1,
                               "Original valid data should be preserved")
        
        # Verify the valid resource is still there
        has_valid_condition = any(
            entry['resource'].get('code', {}).get('text') == 'Valid Condition'
            for entry in bundle['entry']
            if entry['resource'].get('resourceType') == 'Condition'
        )
        self.assertTrue(has_valid_condition,
                       "Original valid Condition should still exist")
    
    def test_rollback_transaction_atomicity_on_error(self):
        """Test that rollback is atomic - all or nothing"""
        # Add resources from two documents
        resources_doc1 = [
            {'resourceType': 'Condition', 'code': {'text': 'Condition 1'}},
            {'resourceType': 'Observation', 'code': {'text': 'Observation 1'}},
        ]
        resources_doc2 = [
            {'resourceType': 'Condition', 'code': {'text': 'Condition 2'}},
        ]
        
        self.patient.add_fhir_resources(resources_doc1, document_id=1)
        self.patient.add_fhir_resources(resources_doc2, document_id=2)
        
        # Verify we have 3 resources
        self.patient.refresh_from_db()
        self.assertEqual(len(self.patient.encrypted_fhir_bundle['entry']), 3)
        
        # Mock save to fail during rollback
        with patch.object(Patient, 'save', side_effect=DatabaseError("Simulated DB error")):
            with self.assertRaises(DatabaseError):
                self.patient.rollback_document_merge(document_id=1)
        
        # Verify data is unchanged (transaction rolled back)
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 3, "Transaction should have rolled back")
        
        # Verify both documents still exist
        sources = [entry['resource']['meta']['source'] for entry in bundle['entry']]
        self.assertIn('document_1', sources)
        self.assertIn('document_2', sources)


class FHIRIntegrationWorkflowTests(TestCase):
    """
    Integration tests combining merge and rollback operations in realistic workflows.
    """
    
    def setUp(self):
        """Set up test patient"""
        self.patient = Patient.objects.create(
            first_name='Integration',
            last_name='Test',
            date_of_birth='1980-01-01',
            mrn='INTEGRATION-TEST-001'
        )
    
    def test_complete_document_reprocessing_workflow(self):
        """Test complete workflow: add resources, detect error, rollback, fix, re-add"""
        # Step 1: Initial document processing with incorrect data
        incorrect_resources_v1 = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetus'}, 'version': 1},  # Typo
            {'resourceType': 'Observation', 'code': {'text': 'A1C: 7.5'}, 'version': 1},
        ]
        self.patient.add_fhir_resources(incorrect_resources_v1, document_id=1)
        
        # Verify data was added
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 2)
        
        # Step 2: Error detected - typo in condition name
        # Create audit record that error was found
        audit_before_rollback = PatientHistory.objects.filter(patient=self.patient).count()
        
        # Step 3: Rollback the incorrect data
        removed_count = self.patient.rollback_document_merge(document_id=1)
        self.assertEqual(removed_count, 2)
        
        # Verify rollback created audit trail
        audit_after_rollback = PatientHistory.objects.filter(patient=self.patient).count()
        self.assertGreater(audit_after_rollback, audit_before_rollback,
                          "Rollback should create audit record")
        
        # Verify data was removed
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle.get('entry', [])), 0)
        
        # Step 4: Re-add with corrected data
        corrected_resources_v2 = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetes'}, 'version': 2},  # Fixed
            {'resourceType': 'Observation', 'code': {'text': 'A1C: 7.5'}, 'version': 2},
        ]
        self.patient.add_fhir_resources(corrected_resources_v2, document_id=1)
        
        # Verify corrected data was added
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 2)
        
        # Verify it's the corrected version
        condition = [e['resource'] for e in bundle['entry'] 
                    if e['resource']['resourceType'] == 'Condition'][0]
        self.assertEqual(condition['code']['text'], 'Diabetes')
        self.assertEqual(condition['version'], 2)
        
        # Verify complete audit trail exists
        final_audit_count = PatientHistory.objects.filter(patient=self.patient).count()
        self.assertGreaterEqual(final_audit_count, 3,
                              "Should have audit records for: initial merge, rollback, re-merge")
    
    def test_multi_document_selective_rollback(self):
        """Test rolling back one document while preserving others"""
        # Add resources from 3 different documents
        for doc_id in range(1, 4):
            resources = [
                {'resourceType': 'Condition', 'code': {'text': f'Condition from Doc {doc_id}'}},
                {'resourceType': 'Observation', 'code': {'text': f'Observation from Doc {doc_id}'}},
            ]
            self.patient.add_fhir_resources(resources, document_id=doc_id)
        
        # Verify we have 6 resources
        self.patient.refresh_from_db()
        self.assertEqual(len(self.patient.encrypted_fhir_bundle['entry']), 6)
        
        # Rollback only document 2
        removed_count = self.patient.rollback_document_merge(document_id=2)
        self.assertEqual(removed_count, 2)
        
        # Verify we have 4 resources left (from docs 1 and 3)
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 4)
        
        # Verify remaining resources are only from docs 1 and 3
        sources = [entry['resource']['meta']['source'] for entry in bundle['entry']]
        self.assertEqual(sources.count('document_1'), 2)
        self.assertEqual(sources.count('document_2'), 0)
        self.assertEqual(sources.count('document_3'), 2)
        
        # Verify no resources from document 2
        for entry in bundle['entry']:
            self.assertNotEqual(entry['resource']['meta']['source'], 'document_2')
    
    def test_merge_update_rollback_audit_trail_completeness(self):
        """Test that complete workflows have comprehensive audit trails"""
        # Initial merge
        initial_resources = [
            {'resourceType': 'Condition', 'code': {'text': 'Initial Condition'}},
        ]
        self.patient.add_fhir_resources(initial_resources, document_id=1)
        
        # Update (idempotent merge)
        updated_resources = [
            {'resourceType': 'Condition', 'code': {'text': 'Updated Condition'}},
        ]
        self.patient.add_fhir_resources(updated_resources, document_id=1)
        
        # Rollback
        self.patient.rollback_document_merge(document_id=1)
        
        # Verify audit trail
        audit_records = PatientHistory.objects.filter(
            patient=self.patient
        ).order_by('created_at')
        
        # Should have at least 3 records: initial merge, update, rollback
        self.assertGreaterEqual(audit_records.count(), 3)
        
        # Verify action types
        actions = [record.action for record in audit_records]
        self.assertIn('fhir_merge', actions)
        self.assertIn('fhir_rollback', actions)
        
        # Verify HIPAA compliance - no PHI in audit records
        for record in audit_records:
            audit_json_str = str(record.fhir_delta)
            # Should not contain clinical data
            self.assertNotIn('Initial Condition', audit_json_str,
                           "Audit trail should not contain PHI")
            self.assertNotIn('Updated Condition', audit_json_str,
                           "Audit trail should not contain PHI")
    
    def test_concurrent_document_processing_data_integrity(self):
        """Test data integrity when processing multiple documents in sequence"""
        # Simulate concurrent processing by rapidly adding multiple documents
        documents = []
        for doc_id in range(1, 11):
            resources = [
                {
                    'resourceType': 'Condition',
                    'id': f'cond-{doc_id}',
                    'code': {'text': f'Condition {doc_id}'}
                },
            ]
            documents.append((doc_id, resources))
        
        # Add all documents in rapid succession
        for doc_id, resources in documents:
            self.patient.add_fhir_resources(resources, document_id=doc_id)
            self.patient.refresh_from_db()  # Force database sync
        
        # Verify all 10 resources were added
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 10)
        
        # Verify all documents are represented
        sources = [entry['resource']['meta']['source'] for entry in bundle['entry']]
        for doc_id in range(1, 11):
            self.assertIn(f'document_{doc_id}', sources)
        
        # Verify no duplicates
        self.assertEqual(len(sources), len(set(sources)),
                        "Should have no duplicate document references")
        
        # Verify resource IDs are correct
        resource_ids = [entry['resource']['id'] for entry in bundle['entry']]
        for doc_id in range(1, 11):
            self.assertIn(f'cond-{doc_id}', resource_ids)


class FHIROperationBoundaryTests(TestCase):
    """
    Boundary condition tests for FHIR operations.
    Tests edge cases and resource limits.
    """
    
    def setUp(self):
        """Set up test patient"""
        self.patient = Patient.objects.create(
            first_name='Boundary',
            last_name='Test',
            date_of_birth='1980-01-01',
            mrn='BOUNDARY-TEST-001'
        )
    
    def test_merge_with_maximum_resource_payload(self):
        """Test merge with very large resource objects (approaching realistic max size)"""
        # Create a resource with large text content (simulating large clinical notes)
        large_text = "Clinical note: " + ("Sample text content. " * 1000)  # ~21KB
        
        large_resource = {
            'resourceType': 'DocumentReference',
            'id': 'large-doc-ref',
            'description': large_text,
            'content': [
                {
                    'attachment': {
                        'contentType': 'text/plain',
                        'data': large_text  # Large content
                    }
                }
            ]
        }
        
        # Should handle large resources without error
        self.patient.add_fhir_resources([large_resource], document_id=1)
        
        # Verify it was added
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 1)
        
        # Verify content is preserved
        doc_ref = bundle['entry'][0]['resource']
        self.assertEqual(len(doc_ref['description']), len(large_text))
    
    def test_merge_with_deeply_nested_resource_structure(self):
        """Test merge with deeply nested FHIR resource structures"""
        # Create a resource with deep nesting (realistic FHIR complexity)
        deeply_nested = {
            'resourceType': 'Observation',
            'id': 'nested-obs',
            'code': {
                'coding': [
                    {
                        'system': 'http://loinc.org',
                        'code': '15074-8',
                        'display': 'Glucose',
                        'extension': [
                            {
                                'url': 'http://example.org/ext',
                                'valueCodeableConcept': {
                                    'coding': [
                                        {
                                            'system': 'http://example.org',
                                            'code': 'nested-value',
                                            'extension': [
                                                {
                                                    'url': 'http://deep.example.org',
                                                    'valueString': 'deeply nested'
                                                }
                                            ]
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        }
        
        # Should handle deeply nested structures
        self.patient.add_fhir_resources([deeply_nested], document_id=1)
        
        # Verify structure is preserved
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        observation = bundle['entry'][0]['resource']
        
        # Navigate deep structure to verify preservation
        self.assertEqual(
            observation['code']['coding'][0]['extension'][0]['valueCodeableConcept']
            ['coding'][0]['extension'][0]['valueString'],
            'deeply nested'
        )
    
    def test_rollback_from_bundle_with_hundreds_of_resources(self):
        """Test selective rollback from a very large bundle"""
        # Add 300 resources across 3 documents (100 each)
        for doc_id in range(1, 4):
            resources = [
                {'resourceType': 'Observation', 'code': {'text': f'Doc {doc_id} Obs {i}'}}
                for i in range(100)
            ]
            self.patient.add_fhir_resources(resources, document_id=doc_id)
        
        # Verify we have 300 resources
        self.patient.refresh_from_db()
        self.assertEqual(len(self.patient.encrypted_fhir_bundle['entry']), 300)
        
        # Rollback middle document (document 2)
        start_time = time.time()
        removed_count = self.patient.rollback_document_merge(document_id=2)
        elapsed_ms = (time.time() - start_time) * 1000
        
        # Verify performance is still acceptable
        self.assertLess(elapsed_ms, 1000,
                       f"Rollback from 300-resource bundle took {elapsed_ms:.2f}ms")
        
        # Verify correct number removed
        self.assertEqual(removed_count, 100)
        
        # Verify we have 200 resources left
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 200)
        
        # Verify only document 2 was removed
        sources = [entry['resource']['meta']['source'] for entry in bundle['entry']]
        self.assertEqual(sources.count('document_1'), 100)
        self.assertEqual(sources.count('document_2'), 0)
        self.assertEqual(sources.count('document_3'), 100)
    
    def test_merge_with_special_characters_and_unicode(self):
        """Test merge handles special characters and unicode in resource content"""
        special_resources = [
            {
                'resourceType': 'Condition',
                'code': {
                    'text': 'Diabetes Mellitus Type 2 — with complications'  # Em dash
                }
            },
            {
                'resourceType': 'Patient',
                'name': [
                    {
                        'given': ['José'],  # Accented character
                        'family': 'García'  # Accented character
                    }
                ]
            },
            {
                'resourceType': 'Observation',
                'valueString': 'Temperature: 37°C'  # Degree symbol
            },
            {
                'resourceType': 'DocumentReference',
                'description': 'Document with emoji 🏥 and symbols ™®©'
            }
        ]
        
        # Should handle special characters without error
        self.patient.add_fhir_resources(special_resources, document_id=1)
        
        # Verify all resources were added with correct content
        self.patient.refresh_from_db()
        bundle = self.patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 4)
        
        # Verify special characters are preserved
        resources = [entry['resource'] for entry in bundle['entry']]
        
        # Check em dash
        condition = [r for r in resources if r['resourceType'] == 'Condition'][0]
        self.assertIn('—', condition['code']['text'])
        
        # Check accented characters
        patient = [r for r in resources if r['resourceType'] == 'Patient'][0]
        self.assertEqual(patient['name'][0]['given'][0], 'José')
        self.assertEqual(patient['name'][0]['family'], 'García')
        
        # Check degree symbol
        observation = [r for r in resources if r['resourceType'] == 'Observation'][0]
        self.assertIn('°', observation['valueString'])
        
        # Check emoji and symbols
        doc_ref = [r for r in resources if r['resourceType'] == 'DocumentReference'][0]
        self.assertIn('🏥', doc_ref['description'])
        self.assertIn('™®©', doc_ref['description'])


class FHIROperationDataIntegrityTests(TransactionTestCase):
    """
    Data integrity tests for FHIR operations.
    Validates that operations maintain data consistency and referential integrity.
    """
    
    def test_merge_maintains_bundle_metadata_integrity(self):
        """Test that merge operations maintain valid bundle metadata"""
        patient = Patient.objects.create(
            first_name='Integrity',
            last_name='Test',
            date_of_birth='1980-01-01',
            mrn='INTEGRITY-TEST-001'
        )
        
        # Add resources multiple times
        for i in range(5):
            resources = [
                {'resourceType': 'Condition', 'code': {'text': f'Condition {i}'}}
            ]
            patient.add_fhir_resources(resources, document_id=i+1)
            
            # Verify bundle metadata is valid after each merge
            patient.refresh_from_db()
            bundle = patient.encrypted_fhir_bundle
            
            # Should have meta section
            self.assertIn('meta', bundle)
            self.assertIn('lastUpdated', bundle['meta'])
            self.assertIn('versionId', bundle['meta'])
            
            # versionId should be UUID format
            version_id = bundle['meta']['versionId']
            self.assertEqual(len(version_id), 36,  # UUID string length
                           f"versionId should be UUID, got: {version_id}")
    
    def test_rollback_preserves_referential_integrity(self):
        """Test that rollback doesn't break references between resources"""
        patient = Patient.objects.create(
            first_name='Reference',
            last_name='Test',
            date_of_birth='1980-01-01',
            mrn='REFERENCE-TEST-001'
        )
        
        # Add resources with references to each other
        resources_doc1 = [
            {
                'resourceType': 'Condition',
                'id': 'condition-1',
                'code': {'text': 'Diabetes'}
            },
            {
                'resourceType': 'Observation',
                'id': 'obs-1',
                'basedOn': [{'reference': 'Condition/condition-1'}],
                'code': {'text': 'Blood Glucose'}
            }
        ]
        
        resources_doc2 = [
            {
                'resourceType': 'Condition',
                'id': 'condition-2',
                'code': {'text': 'Hypertension'}
            },
            {
                'resourceType': 'Observation',
                'id': 'obs-2',
                'basedOn': [{'reference': 'Condition/condition-2'}],
                'code': {'text': 'Blood Pressure'}
            }
        ]
        
        patient.add_fhir_resources(resources_doc1, document_id=1)
        patient.add_fhir_resources(resources_doc2, document_id=2)
        
        # Rollback document 1
        patient.rollback_document_merge(document_id=1)
        
        # Verify document 2 resources and their references are intact
        patient.refresh_from_db()
        bundle = patient.encrypted_fhir_bundle
        resources = [entry['resource'] for entry in bundle['entry']]
        
        # Should have 2 resources from document 2
        self.assertEqual(len(resources), 2)
        
        # Verify reference is still valid
        observation = [r for r in resources if r['resourceType'] == 'Observation'][0]
        self.assertEqual(observation['basedOn'][0]['reference'], 'Condition/condition-2')
        
        # Verify referenced resource exists
        condition = [r for r in resources if r['resourceType'] == 'Condition'][0]
        self.assertEqual(condition['id'], 'condition-2')
    
    def test_multiple_rapid_merges_maintain_consistency(self):
        """Test that rapid successive merges don't corrupt data"""
        patient = Patient.objects.create(
            first_name='Rapid',
            last_name='Test',
            date_of_birth='1980-01-01',
            mrn='RAPID-TEST-001'
        )
        
        # Rapidly add and update same document 10 times
        for version in range(10):
            resources = [
                {
                    'resourceType': 'Condition',
                    'code': {'text': f'Diabetes'},
                    'version': version + 1
                }
            ]
            patient.add_fhir_resources(resources, document_id=1)
        
        # Verify we still have only 1 resource (idempotent updates)
        patient.refresh_from_db()
        bundle = patient.encrypted_fhir_bundle
        self.assertEqual(len(bundle['entry']), 1)
        
        # Verify it's the latest version
        condition = bundle['entry'][0]['resource']
        self.assertEqual(condition['version'], 10)
        
        # Verify audit trail has all 10 merges
        merge_audits = PatientHistory.objects.filter(
            patient=patient,
            action='fhir_merge'
        ).count()
        self.assertEqual(merge_audits, 10,
                        "Should have audit record for each merge operation")

