"""
Test suite for FHIR Historical Data Preservation functionality.

Tests the HistoricalResourceManager and its integration with FHIRAccumulator
to ensure historical data is properly preserved, versioned, and never lost.
"""

import unittest
from datetime import datetime, date
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from apps.patients.models import Patient, PatientHistory
from apps.fhir.services import (
    HistoricalResourceManager,
    FHIRAccumulator,
    FHIRAccumulationError
)
from apps.fhir.fhir_models import (
    ConditionResource,
    ObservationResource,
    MedicationStatementResource,
    Meta
)
from apps.fhir.bundle_utils import (
    create_initial_patient_bundle,
    add_resource_to_bundle
)

from fhir.resources.bundle import Bundle
from fhir.resources.extension import Extension


class TestHistoricalResourceManager(TestCase):
    """
    Test suite for the HistoricalResourceManager class.
    
    Tests the core functionality of preserving historical FHIR resource versions.
    """
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testdoc',
            email='doc@test.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            mrn='TEST123',
            first_name='John',
            last_name='Doe',
            date_of_birth=date(1980, 1, 1),
            gender='M',
            cumulative_fhir_json={}
        )
        
        self.historical_manager = HistoricalResourceManager()
        
        # Create a test bundle with patient
        from apps.fhir.fhir_models import PatientResource
        patient_resource = PatientResource.from_patient_model(self.patient)
        self.bundle = create_initial_patient_bundle(patient_resource)
        
        # Source metadata for testing
        self.source_metadata = {
            'document_id': 'test-doc-123',
            'document_type': 'lab_report',
            'reason': 'Test data preservation',
            'source_system': 'Test System'
        }
    
    def test_preserve_new_resource_no_existing(self):
        """Test preserving a new resource when no existing version exists."""
        # Create a new condition
        condition = ConditionResource(
            id=str(uuid4()),
            clinicalStatus={'coding': [{'code': 'active'}]},
            code={'coding': [{'system': 'http://snomed.info/sct', 'code': '38341003'}]},
            subject={'reference': f'Patient/{self.patient.id}'},
            recordedDate='2023-01-15'
        )
        
        # Preserve resource history
        updated_bundle, result = self.historical_manager.preserve_resource_history(
            bundle=self.bundle,
            new_resource=condition,
            source_metadata=self.source_metadata,
            user=self.user,
            preserve_reason="New condition"
        )
        
        # Should have added the new resource without creating historical version
        self.assertEqual(result['historical_versions_preserved'], 0)
        self.assertTrue(result['new_version_added'])
        self.assertFalse(result['version_chain_maintained'])
        
        # Bundle should contain the patient and the new condition
        condition_resources = [
            entry.resource for entry in updated_bundle.entry 
            if entry.resource.resource_type == 'Condition'
        ]
        self.assertEqual(len(condition_resources), 1)
        self.assertEqual(condition_resources[0].id, condition.id)
    
    def test_preserve_existing_resource_creates_historical_version(self):
        """Test that updating an existing resource creates a historical version."""
        # First, add a condition to the bundle
        original_condition = ConditionResource(
            id='condition-123',
            clinicalStatus={'coding': [{'code': 'active'}]},
            code={'coding': [{'system': 'http://snomed.info/sct', 'code': '38341003'}]},
            subject={'reference': f'Patient/{self.patient.id}'},
            recordedDate='2023-01-15'
        )
        
        # Set initial metadata
        original_condition.meta = Meta(versionId="1", lastUpdated="2023-01-15T10:00:00Z")
        
        # Add to bundle
        self.bundle = add_resource_to_bundle(self.bundle, original_condition)
        
        # Now create an updated version
        updated_condition = ConditionResource(
            id='condition-123',  # Same ID
            clinicalStatus={'coding': [{'code': 'resolved'}]},  # Different status
            code={'coding': [{'system': 'http://snomed.info/sct', 'code': '38341003'}]},
            subject={'reference': f'Patient/{self.patient.id}'},
            recordedDate='2023-06-01'  # Different date
        )
        
        # Preserve resource history
        updated_bundle, result = self.historical_manager.preserve_resource_history(
            bundle=self.bundle,
            new_resource=updated_condition,
            source_metadata=self.source_metadata,
            user=self.user,
            preserve_reason="Status update"
        )
        
        # Should have preserved the historical version
        self.assertEqual(result['historical_versions_preserved'], 1)
        self.assertTrue(result['new_version_added'])
        self.assertTrue(result['version_chain_maintained'])
        self.assertTrue(result['status_transition_recorded'])
        
        # Check status transition details
        status_transition = result.get('status_transition', {})
        self.assertEqual(status_transition['old_status'], 'active')
        self.assertEqual(status_transition['new_status'], 'resolved')
        
        # Bundle should now contain both versions: historical and current
        condition_resources = [
            entry.resource for entry in updated_bundle.entry 
            if entry.resource.resource_type == 'Condition'
        ]
        self.assertEqual(len(condition_resources), 2)
        
        # Check that we have one historical and one current version
        historical_versions = [
            r for r in condition_resources 
            if self.historical_manager._is_historical_version(r)
        ]
        current_versions = [
            r for r in condition_resources 
            if not self.historical_manager._is_historical_version(r)
        ]
        
        self.assertEqual(len(historical_versions), 1)
        self.assertEqual(len(current_versions), 1)
        
        # Historical version should have the original status
        historical_condition = historical_versions[0]
        historical_status = self.historical_manager._extract_resource_status(historical_condition)
        self.assertEqual(historical_status, 'active')
        
        # Current version should have the updated status
        current_condition = current_versions[0]
        current_status = self.historical_manager._extract_resource_status(current_condition)
        self.assertEqual(current_status, 'resolved')
    
    def test_version_chain_maintenance(self):
        """Test that version chains are properly maintained."""
        # Create initial resource
        condition = ConditionResource(
            id='condition-version-test',
            clinicalStatus={'coding': [{'code': 'active'}]},
            code={'coding': [{'system': 'http://snomed.info/sct', 'code': '38341003'}]},
            subject={'reference': f'Patient/{self.patient.id}'},
            recordedDate='2023-01-15'
        )
        condition.meta = Meta(versionId="1", lastUpdated="2023-01-15T10:00:00Z")
        
        # Add to bundle
        self.bundle = add_resource_to_bundle(self.bundle, condition)
        
        # Create multiple updates
        for i in range(2, 5):  # Versions 2, 3, 4
            updated_condition = ConditionResource(
                id='condition-version-test',
                clinicalStatus={'coding': [{'code': f'status-{i}'}]},
                code={'coding': [{'system': 'http://snomed.info/sct', 'code': '38341003'}]},
                subject={'reference': f'Patient/{self.patient.id}'},
                recordedDate=f'2023-0{i}-01'
            )
            
            self.bundle, result = self.historical_manager.preserve_resource_history(
                bundle=self.bundle,
                new_resource=updated_condition,
                source_metadata=self.source_metadata,
                user=self.user,
                preserve_reason=f"Update {i}"
            )
        
        # Should have 4 total versions: 3 historical + 1 current
        condition_resources = [
            entry.resource for entry in self.bundle.entry 
            if entry.resource.resource_type == 'Condition' and entry.resource.id == 'condition-version-test'
        ]
        self.assertEqual(len(condition_resources), 4)
        
        # Check version numbers
        version_numbers = []
        for resource in condition_resources:
            if resource.meta and resource.meta.versionId:
                base_version = resource.meta.versionId.split('.')[0]
                version_numbers.append(int(base_version))
        
        version_numbers.sort()
        self.assertEqual(version_numbers, [1, 2, 3, 4])
    
    def test_get_resource_timeline(self):
        """Test getting a complete timeline of resource changes."""
        # Create and update a condition multiple times
        condition_id = 'timeline-test-condition'
        
        # Initial version
        condition = ConditionResource(
            id=condition_id,
            clinicalStatus={'coding': [{'code': 'active'}]},
            code={'coding': [{'system': 'http://snomed.info/sct', 'code': '38341003'}]},
            subject={'reference': f'Patient/{self.patient.id}'},
            recordedDate='2023-01-15'
        )
        condition.meta = Meta(versionId="1", lastUpdated="2023-01-15T10:00:00Z")
        self.bundle = add_resource_to_bundle(self.bundle, condition)
        
        # Update 1: Change status to resolved
        updated_condition = ConditionResource(
            id=condition_id,
            clinicalStatus={'coding': [{'code': 'resolved'}]},
            code={'coding': [{'system': 'http://snomed.info/sct', 'code': '38341003'}]},
            subject={'reference': f'Patient/{self.patient.id}'},
            recordedDate='2023-06-01'
        )
        
        self.bundle, _ = self.historical_manager.preserve_resource_history(
            bundle=self.bundle,
            new_resource=updated_condition,
            source_metadata=self.source_metadata,
            user=self.user,
            preserve_reason="Status change to resolved"
        )
        
        # Get timeline
        timeline = self.historical_manager.get_resource_timeline(
            bundle=self.bundle,
            resource_type='Condition',
            resource_id=condition_id,
            include_provenance=False
        )
        
        # Check timeline structure
        self.assertEqual(timeline['resource_type'], 'Condition')
        self.assertEqual(timeline['resource_id'], condition_id)
        self.assertEqual(len(timeline['versions']), 2)
        
        # Check status transitions
        self.assertEqual(len(timeline['status_transitions']), 1)
        transition = timeline['status_transitions'][0]
        self.assertEqual(transition['from_status'], 'active')
        self.assertEqual(transition['to_status'], 'resolved')
    
    def test_historical_integrity_validation(self):
        """Test validation of historical data integrity."""
        # Create a bundle with some version issues
        condition = ConditionResource(
            id='integrity-test',
            clinicalStatus={'coding': [{'code': 'active'}]},
            code={'coding': [{'system': 'http://snomed.info/sct', 'code': '38341003'}]},
            subject={'reference': f'Patient/{self.patient.id}'},
            recordedDate='2023-01-15'
        )
        
        # Create resource with invalid version ID to test validation
        condition.meta = Meta(versionId="invalid-version", lastUpdated="2023-01-15T10:00:00Z")
        self.bundle = add_resource_to_bundle(self.bundle, condition)
        
        # Validate integrity
        validation_result = self.historical_manager.validate_historical_integrity(
            bundle=self.bundle,
            resource_type='Condition'
        )
        
        # Should detect the invalid version format
        self.assertFalse(validation_result['is_valid'])
        self.assertTrue(len(validation_result['version_chain_issues']) > 0)
        self.assertIn('Invalid version ID format', validation_result['version_chain_issues'][0])
    
    def test_status_tracking_for_different_resource_types(self):
        """Test status tracking works for different resource types."""
        # Test Condition
        condition = ConditionResource(
            id='status-test-condition',
            clinicalStatus={'coding': [{'code': 'active'}]},
            code={'coding': [{'system': 'http://snomed.info/sct', 'code': '38341003'}]},
            subject={'reference': f'Patient/{self.patient.id}'}
        )
        
        self.assertTrue(
            self.historical_manager._is_status_tracked_resource(condition.resource_type)
        )
        
        status = self.historical_manager._extract_resource_status(condition)
        self.assertEqual(status, 'active')
        
        # Test MedicationStatement
        medication = MedicationStatementResource(
            id='status-test-med',
            status='active',
            medication={'concept': {'coding': [{'display': 'Test Med'}]}},
            subject={'reference': f'Patient/{self.patient.id}'}
        )
        
        self.assertTrue(
            self.historical_manager._is_status_tracked_resource(medication.resource_type)
        )
        
        status = self.historical_manager._extract_resource_status(medication)
        self.assertEqual(status, 'active')
        
        # Test non-status-tracked resource (like Patient)
        self.assertFalse(
            self.historical_manager._is_status_tracked_resource('Patient')
        )


class TestFHIRAccumulatorHistoricalIntegration(TestCase):
    """
    Test suite for historical data preservation integration with FHIRAccumulator.
    
    Tests the complete flow of historical preservation during resource accumulation.
    """
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testdoc',
            email='doc@test.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            mrn='ACCUM-TEST-123',
            first_name='Jane',
            last_name='Smith',
            date_of_birth=date(1985, 5, 15),
            gender='F',
            cumulative_fhir_json={}
        )
        
        self.accumulator = FHIRAccumulator()
    
    def test_accumulator_preserves_history_on_update(self):
        """Test that FHIRAccumulator preserves history when updating resources."""
        # Add initial condition
        initial_condition_data = {
            'resourceType': 'Condition',
            'id': 'accumulator-condition-test',
            'clinicalStatus': {'coding': [{'code': 'active'}]},
            'code': {'coding': [{'system': 'http://snomed.info/sct', 'code': '38341003'}]},
            'subject': {'reference': f'Patient/{self.patient.id}'},
            'recordedDate': '2023-01-15'
        }
        
        # First accumulation
        result1 = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=[initial_condition_data],
            source_system='Test System',
            responsible_user=self.user,
            source_document_id='doc-1',
            reason='Initial condition'
        )
        
        self.assertTrue(result1['success'])
        self.assertEqual(result1['resources_added'], 1)
        
        # Update the same condition with different status
        updated_condition_data = {
            'resourceType': 'Condition',
            'id': 'accumulator-condition-test',  # Same ID
            'clinicalStatus': {'coding': [{'code': 'resolved'}]},  # Different status
            'code': {'coding': [{'system': 'http://snomed.info/sct', 'code': '38341003'}]},
            'subject': {'reference': f'Patient/{self.patient.id}'},
            'recordedDate': '2023-06-01'
        }
        
        # Second accumulation (should preserve history)
        result2 = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=[updated_condition_data],
            source_system='Test System',
            responsible_user=self.user,
            source_document_id='doc-2',
            reason='Status update'
        )
        
        self.assertTrue(result2['success'])
        self.assertEqual(result2['resources_added'], 1)
        
        # Check that historical preservation warnings are present
        historical_warnings = [
            warning for warning in result2.get('warnings', [])
            if 'historical version' in warning.lower()
        ]
        self.assertTrue(len(historical_warnings) > 0)
        
        # Verify PatientHistory records were created
        history_records = PatientHistory.objects.filter(patient=self.patient)
        
        # Should have at least:
        # 1. fhir_append for initial condition
        # 2. fhir_append for updated condition  
        # 3. fhir_history_preserved for the historical preservation
        self.assertGreaterEqual(history_records.count(), 3)
        
        # Check for historical preservation record
        preservation_records = history_records.filter(action='fhir_history_preserved')
        self.assertGreater(preservation_records.count(), 0)
        
        preservation_record = preservation_records.first()
        self.assertIn('historical_versions_preserved', preservation_record.notes)
    
    def test_get_patient_resource_timeline_integration(self):
        """Test getting resource timeline through FHIRAccumulator."""
        condition_id = 'timeline-integration-test'
        
        # Add initial condition
        initial_data = {
            'resourceType': 'Condition',
            'id': condition_id,
            'clinicalStatus': {'coding': [{'code': 'active'}]},
            'code': {'coding': [{'system': 'http://snomed.info/sct', 'code': '38341003'}]},
            'subject': {'reference': f'Patient/{self.patient.id}'},
            'recordedDate': '2023-01-15'
        }
        
        self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=[initial_data],
            source_system='Test System',
            responsible_user=self.user,
            source_document_id='doc-1'
        )
        
        # Update condition
        updated_data = {
            'resourceType': 'Condition',
            'id': condition_id,
            'clinicalStatus': {'coding': [{'code': 'resolved'}]},
            'code': {'coding': [{'system': 'http://snomed.info/sct', 'code': '38341003'}]},
            'subject': {'reference': f'Patient/{self.patient.id}'},
            'recordedDate': '2023-06-01'
        }
        
        self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=[updated_data],
            source_system='Test System',
            responsible_user=self.user,
            source_document_id='doc-2'
        )
        
        # Get timeline through accumulator
        timeline = self.accumulator.get_patient_resource_timeline(
            patient=self.patient,
            resource_type='Condition',
            resource_id=condition_id,
            include_provenance=False
        )
        
        # Verify timeline structure
        self.assertEqual(timeline['resource_type'], 'Condition')
        self.assertEqual(timeline['resource_id'], condition_id)
        self.assertEqual(timeline['patient_mrn'], self.patient.mrn)
        
        # Should have versions (both historical and current)
        self.assertGreaterEqual(len(timeline['versions']), 2)
        
        # Should have status transitions
        self.assertGreaterEqual(len(timeline['status_transitions']), 1)
    
    def test_validate_patient_historical_integrity_integration(self):
        """Test historical integrity validation through FHIRAccumulator."""
        # Add some resources to create history
        condition_data = {
            'resourceType': 'Condition',
            'id': 'integrity-validation-test',
            'clinicalStatus': {'coding': [{'code': 'active'}]},
            'code': {'coding': [{'system': 'http://snomed.info/sct', 'code': '38341003'}]},
            'subject': {'reference': f'Patient/{self.patient.id}'},
            'recordedDate': '2023-01-15'
        }
        
        self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=[condition_data],
            source_system='Test System',
            responsible_user=self.user
        )
        
        # Validate historical integrity
        validation_result = self.accumulator.validate_patient_historical_integrity(
            patient=self.patient
        )
        
        # Should be valid for a properly constructed patient record
        self.assertTrue(validation_result['is_valid'])
        self.assertEqual(validation_result['patient_mrn'], self.patient.mrn)
        self.assertIn('Condition', validation_result['resource_counts'])
    
    def test_complex_historical_scenario_lab_results(self):
        """Test complex scenario with lab results showing value changes over time."""
        observation_id = 'glucose-trend-test'
        
        # Simulate glucose readings over time
        glucose_readings = [
            {'date': '2023-01-15', 'value': 95, 'unit': 'mg/dL'},
            {'date': '2023-02-15', 'value': 110, 'unit': 'mg/dL'}, 
            {'date': '2023-03-15', 'value': 125, 'unit': 'mg/dL'},
            {'date': '2023-04-15', 'value': 140, 'unit': 'mg/dL'},  # Getting higher
            {'date': '2023-05-15', 'value': 105, 'unit': 'mg/dL'}   # Back to normal
        ]
        
        for i, reading in enumerate(glucose_readings):
            observation_data = {
                'resourceType': 'Observation',
                'id': observation_id,
                'status': 'final',
                'code': {'coding': [{'system': 'http://loinc.org', 'code': '2345-7', 'display': 'Glucose'}]},
                'subject': {'reference': f'Patient/{self.patient.id}'},
                'effectiveDateTime': reading['date'],
                'valueQuantity': {
                    'value': reading['value'],
                    'unit': reading['unit'],
                    'system': 'http://unitsofmeasure.org'
                }
            }
            
            result = self.accumulator.add_resources_to_patient(
                patient=self.patient,
                fhir_resources=[observation_data],
                source_system='Lab System',
                responsible_user=self.user,
                source_document_id=f'lab-{i+1}',
                reason=f'Glucose reading {i+1}'
            )
            
            self.assertTrue(result['success'])
        
        # Get timeline to verify all values are preserved
        timeline = self.accumulator.get_patient_resource_timeline(
            patient=self.patient,
            resource_type='Observation',
            resource_id=observation_id,
            include_provenance=False
        )
        
        # Should have all 5 versions (4 historical + 1 current)
        self.assertEqual(len(timeline['versions']), 5)
        
        # Verify historical integrity
        validation_result = self.accumulator.validate_patient_historical_integrity(
            patient=self.patient,
            resource_type='Observation'
        )
        
        self.assertTrue(validation_result['is_valid'])
        
        # Verify all glucose values are preserved in the bundle
        self.patient.refresh_from_db()
        bundle_data = self.patient.cumulative_fhir_json
        
        observation_entries = [
            entry for entry in bundle_data.get('entry', [])
            if (entry.get('resource', {}).get('resourceType') == 'Observation' and
                entry.get('resource', {}).get('id') == observation_id)
        ]
        
        # Should have all 5 versions
        self.assertEqual(len(observation_entries), 5)
        
        # Extract all glucose values
        glucose_values = []
        for entry in observation_entries:
            resource = entry.get('resource', {})
            value_quantity = resource.get('valueQuantity', {})
            if value_quantity.get('value'):
                glucose_values.append(value_quantity['value'])
        
        glucose_values.sort()  # Sort to check all values are present
        expected_values = sorted([reading['value'] for reading in glucose_readings])
        self.assertEqual(glucose_values, expected_values)


if __name__ == '__main__':
    unittest.main()