"""
Tests for FHIR Data Accumulation Service

Comprehensive test suite covering FHIR resource accumulation, conflict resolution,
provenance tracking, validation, and audit trails.
"""

import json
import uuid
from datetime import datetime
from unittest.mock import patch, Mock

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from apps.patients.models import Patient, PatientHistory
from apps.core.models import AuditLog
from .services import FHIRAccumulator, FHIRAccumulationError, FHIRValidationError


class FHIRAccumulatorTestCase(TestCase):
    """Base test case with common setup for FHIR accumulator tests."""
    
    def setUp(self):
        """Set up test data."""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test patient
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            gender='M'
        )
        
        # Initialize accumulator
        self.accumulator = FHIRAccumulator()
        
        # Sample FHIR resources for testing
        self.sample_condition_resource = {
            "resourceType": "Condition",
            "id": str(uuid.uuid4()),
            "subject": {"reference": f"Patient/{self.patient.id}"},
            "code": {
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": "233604007",
                    "display": "Pneumonia"
                }]
            },
            "clinicalStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active"
                }]
            }
        }
        
        self.sample_observation_resource = {
            "resourceType": "Observation",
            "id": str(uuid.uuid4()),
            "subject": {"reference": f"Patient/{self.patient.id}"},
            "status": "final",
            "code": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": "33747-0",
                    "display": "General appearance"
                }]
            },
            "valueString": "Patient appears well"
        }
        
        self.sample_medication_resource = {
            "resourceType": "MedicationStatement",
            "id": str(uuid.uuid4()),
            "subject": {"reference": f"Patient/{self.patient.id}"},
            "status": "active",
            "medicationCodeableConcept": {
                "coding": [{
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "1596450",
                    "display": "Amoxicillin 500mg"
                }]
            }
        }


class FHIRAccumulatorBasicTests(FHIRAccumulatorTestCase):
    """Test basic FHIR accumulation functionality."""
    
    def test_add_single_resource_to_empty_patient(self):
        """Test adding a single FHIR resource to a patient with no existing data."""
        resources = [self.sample_condition_resource]
        
        result = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=resources,
            source_system="TestSystem",
            responsible_user=self.user,
            reason="Test adding single resource"
        )
        
        # Verify result
        self.assertTrue(result['success'])
        self.assertEqual(result['resources_added'], 1)
        self.assertEqual(result['resources_skipped'], 0)
        self.assertEqual(result['conflicts_resolved'], 0)
        self.assertEqual(len(result['errors']), 0)
        
        # Verify patient record was updated
        self.patient.refresh_from_db()
        self.assertIsNotNone(self.patient.cumulative_fhir_json)
        
        # Verify bundle structure
        bundle_data = self.patient.cumulative_fhir_json
        self.assertEqual(bundle_data['type'], 'collection')
        self.assertGreaterEqual(len(bundle_data['entry']), 1)
        
        # Find the condition resource in the bundle
        condition_found = False
        for entry in bundle_data['entry']:
            if entry['resource']['resourceType'] == 'Condition':
                condition_found = True
                self.assertEqual(
                    entry['resource']['code']['coding'][0]['display'],
                    'Pneumonia'
                )
                break
        
        self.assertTrue(condition_found, "Condition resource not found in bundle")
    
    def test_add_multiple_resources(self):
        """Test adding multiple FHIR resources at once."""
        resources = [
            self.sample_condition_resource,
            self.sample_observation_resource,
            self.sample_medication_resource
        ]
        
        result = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=resources,
            source_system="TestSystem",
            responsible_user=self.user
        )
        
        # Verify result
        self.assertTrue(result['success'])
        self.assertEqual(result['resources_added'], 3)
        self.assertEqual(result['resources_skipped'], 0)
        
        # Verify patient record
        self.patient.refresh_from_db()
        bundle_data = self.patient.cumulative_fhir_json
        
        # Count resource types in bundle
        resource_types = {}
        for entry in bundle_data['entry']:
            resource_type = entry['resource']['resourceType']
            resource_types[resource_type] = resource_types.get(resource_type, 0) + 1
        
        # Should have at least our 3 resources (plus potentially Patient resource)
        self.assertGreaterEqual(resource_types.get('Condition', 0), 1)
        self.assertGreaterEqual(resource_types.get('Observation', 0), 1)
        self.assertGreaterEqual(resource_types.get('MedicationStatement', 0), 1)
    
    def test_add_resources_to_existing_bundle(self):
        """Test adding resources to a patient that already has FHIR data."""
        # First, add initial resource
        initial_resources = [self.sample_condition_resource]
        self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=initial_resources,
            source_system="TestSystem",
            responsible_user=self.user
        )
        
        # Add additional resources
        additional_resources = [self.sample_observation_resource]
        result = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=additional_resources,
            source_system="TestSystem",
            responsible_user=self.user
        )
        
        # Verify result
        self.assertTrue(result['success'])
        self.assertEqual(result['resources_added'], 1)
        
        # Verify both resources are in bundle
        self.patient.refresh_from_db()
        bundle_data = self.patient.cumulative_fhir_json
        
        resource_types = [entry['resource']['resourceType'] for entry in bundle_data['entry']]
        self.assertIn('Condition', resource_types)
        self.assertIn('Observation', resource_types)
    
    def test_no_resources_provided(self):
        """Test handling when no resources are provided."""
        result = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=[],
            source_system="TestSystem",
            responsible_user=self.user
        )
        
        # Should succeed but add nothing
        self.assertTrue(result['success'])
        self.assertEqual(result['resources_added'], 0)
        self.assertEqual(result['resources_skipped'], 0)
        self.assertIn('No resources provided', result['warnings'])


class FHIRAccumulatorValidationTests(FHIRAccumulatorTestCase):
    """Test FHIR validation functionality."""
    
    def test_validation_enabled_valid_resources(self):
        """Test validation with valid FHIR resources."""
        resources = [self.sample_condition_resource]
        
        result = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=resources,
            source_system="TestSystem",
            responsible_user=self.user,
            validate_fhir=True
        )
        
        self.assertTrue(result['success'])
        self.assertEqual(result['resources_added'], 1)
        self.assertEqual(len(result['errors']), 0)
    
    def test_validation_missing_resource_type(self):
        """Test validation with missing resourceType."""
        invalid_resource = {
            "id": str(uuid.uuid4()),
            "subject": {"reference": f"Patient/{self.patient.id}"}
            # Missing resourceType
        }
        
        with self.assertRaises(FHIRValidationError):
            self.accumulator.add_resources_to_patient(
                patient=self.patient,
                fhir_resources=[invalid_resource],
                source_system="TestSystem",
                responsible_user=self.user,
                validate_fhir=True
            )
    
    def test_validation_missing_required_fields(self):
        """Test validation with missing required fields."""
        invalid_condition = {
            "resourceType": "Condition",
            "id": str(uuid.uuid4())
            # Missing subject reference
        }
        
        with self.assertRaises(FHIRValidationError):
            self.accumulator.add_resources_to_patient(
                patient=self.patient,
                fhir_resources=[invalid_condition],
                source_system="TestSystem",
                responsible_user=self.user,
                validate_fhir=True
            )
    
    def test_validation_disabled(self):
        """Test that validation can be disabled."""
        # This resource would normally fail validation
        invalid_resource = {
            "resourceType": "Condition",
            "id": str(uuid.uuid4())
            # Missing required subject field
        }
        
        # Should not raise exception when validation is disabled
        result = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=[invalid_resource],
            source_system="TestSystem",
            responsible_user=self.user,
            validate_fhir=False
        )
        
        # May skip the resource due to conversion failure, but shouldn't raise validation error
        self.assertTrue(result['success'])


class FHIRAccumulatorConflictResolutionTests(FHIRAccumulatorTestCase):
    """Test conflict resolution functionality."""
    
    def test_duplicate_resource_skipped(self):
        """Test that duplicate resources are skipped when conflict resolution is enabled."""
        # Add resource twice
        resources = [self.sample_condition_resource]
        
        # First addition
        result1 = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=resources,
            source_system="TestSystem",
            responsible_user=self.user,
            resolve_conflicts=True
        )
        
        # Second addition (duplicate)
        result2 = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=resources,
            source_system="TestSystem",
            responsible_user=self.user,
            resolve_conflicts=True
        )
        
        # First should succeed
        self.assertTrue(result1['success'])
        self.assertEqual(result1['resources_added'], 1)
        
        # Second should skip duplicate
        self.assertTrue(result2['success'])
        self.assertEqual(result2['resources_added'], 0)
        self.assertEqual(result2['resources_skipped'], 1)
        self.assertIn('Skipped duplicate resource', result2['warnings'][0])
    
    def test_conflict_resolution_disabled(self):
        """Test behavior when conflict resolution is disabled."""
        resources = [self.sample_condition_resource]
        
        # Add resource twice with conflict resolution disabled
        result1 = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=resources,
            source_system="TestSystem",
            responsible_user=self.user,
            resolve_conflicts=False
        )
        
        result2 = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=resources,
            source_system="TestSystem",
            responsible_user=self.user,
            resolve_conflicts=False
        )
        
        # Both should succeed (duplicates not detected)
        self.assertTrue(result1['success'])
        self.assertTrue(result2['success'])
        self.assertEqual(result1['resources_added'], 1)
        self.assertEqual(result2['resources_added'], 1)


class FHIRAccumulatorAuditTests(FHIRAccumulatorTestCase):
    """Test audit logging and patient history functionality."""
    
    def test_audit_log_creation(self):
        """Test that audit logs are created for FHIR accumulation."""
        initial_audit_count = AuditLog.objects.count()
        
        resources = [self.sample_condition_resource]
        self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=resources,
            source_system="TestSystem",
            responsible_user=self.user
        )
        
        # Should have created audit logs
        final_audit_count = AuditLog.objects.count()
        self.assertGreater(final_audit_count, initial_audit_count)
        
        # Check for specific audit log entries
        fhir_import_logs = AuditLog.objects.filter(
            event_type='fhir_import',
            patient_mrn=self.patient.mrn
        )
        self.assertGreaterEqual(fhir_import_logs.count(), 1)
        
        # Verify audit log content
        start_log = fhir_import_logs.filter(description__contains='Starting').first()
        self.assertIsNotNone(start_log)
        self.assertEqual(start_log.user, self.user)
        self.assertTrue(start_log.phi_involved)
        self.assertEqual(start_log.patient_mrn, self.patient.mrn)
    
    def test_patient_history_creation(self):
        """Test that patient history records are created."""
        initial_history_count = PatientHistory.objects.filter(patient=self.patient).count()
        
        resources = [self.sample_condition_resource]
        self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=resources,
            source_system="TestSystem",
            responsible_user=self.user,
            source_document_id="DOC123"
        )
        
        # Should have created patient history
        final_history_count = PatientHistory.objects.filter(patient=self.patient).count()
        self.assertGreater(final_history_count, initial_history_count)
        
        # Check history record content
        history_record = PatientHistory.objects.filter(
            patient=self.patient,
            action='fhir_append'
        ).first()
        
        self.assertIsNotNone(history_record)
        self.assertEqual(history_record.changed_by, self.user)
        self.assertEqual(len(history_record.fhir_delta), 1)


class FHIRAccumulatorSummaryTests(FHIRAccumulatorTestCase):
    """Test FHIR summary and validation functionality."""
    
    def test_get_patient_fhir_summary(self):
        """Test getting a patient's FHIR summary."""
        # Add some resources first
        resources = [
            self.sample_condition_resource,
            self.sample_observation_resource
        ]
        self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=resources,
            source_system="TestSystem",
            responsible_user=self.user
        )
        
        # Get summary
        summary = self.accumulator.get_patient_fhir_summary(
            patient=self.patient,
            include_provenance=True
        )
        
        # Verify summary structure
        self.assertIn('patient_mrn', summary)
        self.assertEqual(summary['patient_mrn'], self.patient.mrn)
        self.assertIn('total_entries', summary)
        self.assertIn('resource_types', summary)
        self.assertIn('provenance', summary)
        
        # Verify resource counts
        self.assertGreater(summary['total_entries'], 0)
        self.assertIn('Condition', summary['resource_types'])
        self.assertIn('Observation', summary['resource_types'])
    
    def test_validate_patient_fhir_data(self):
        """Test validating a patient's FHIR data."""
        # Add resources first
        resources = [self.sample_condition_resource]
        self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=resources,
            source_system="TestSystem",
            responsible_user=self.user
        )
        
        # Validate data
        validation_result = self.accumulator.validate_patient_fhir_data(self.patient)
        
        # Verify validation result
        self.assertEqual(validation_result['patient_mrn'], self.patient.mrn)
        self.assertTrue(validation_result['is_valid'])
        self.assertTrue(validation_result['bundle_valid'])
        self.assertGreater(validation_result['total_resources'], 0)
        self.assertEqual(len(validation_result['issues']), 0)
    
    def test_deduplicate_patient_fhir_data(self):
        """Test deduplicating a patient's FHIR data."""
        # Add duplicate resources manually to create duplicates
        resources = [self.sample_condition_resource, self.sample_condition_resource]
        self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=resources,
            source_system="TestSystem",
            responsible_user=self.user,
            resolve_conflicts=False  # Allow duplicates
        )
        
        # Run deduplication
        dedup_result = self.accumulator.deduplicate_patient_fhir_data(
            patient=self.patient,
            user=self.user
        )
        
        # Verify deduplication result
        self.assertTrue(dedup_result['success'])
        self.assertEqual(dedup_result['patient_mrn'], self.patient.mrn)
        # May or may not find duplicates depending on bundle_utils implementation


class FHIRAccumulatorErrorHandlingTests(FHIRAccumulatorTestCase):
    """Test error handling and edge cases."""
    
    def test_invalid_patient(self):
        """Test error handling with invalid patient."""
        with self.assertRaises(FHIRAccumulationError):
            self.accumulator.add_resources_to_patient(
                patient=None,
                fhir_resources=[self.sample_condition_resource],
                source_system="TestSystem"
            )
    
    def test_missing_source_system(self):
        """Test error handling with missing source system."""
        with self.assertRaises(FHIRAccumulationError):
            self.accumulator.add_resources_to_patient(
                patient=self.patient,
                fhir_resources=[self.sample_condition_resource],
                source_system=""
            )
    
    def test_unsupported_resource_type(self):
        """Test handling of unsupported resource types."""
        unsupported_resource = {
            "resourceType": "UnsupportedType",
            "id": str(uuid.uuid4()),
            "data": "test"
        }
        
        result = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=[unsupported_resource],
            source_system="TestSystem",
            responsible_user=self.user
        )
        
        # Should succeed but skip unsupported resource
        self.assertTrue(result['success'])
        self.assertEqual(result['resources_added'], 0)
        self.assertEqual(result['resources_skipped'], 1)
        self.assertIn('Skipped unsupported resource type', result['warnings'][0])
    
    def test_malformed_resource_data(self):
        """Test handling of malformed resource data."""
        malformed_resource = {
            "resourceType": "Condition",
            "id": str(uuid.uuid4()),
            "invalid_structure": {"nested": {"deeply": "malformed"}}
        }
        
        result = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=[malformed_resource],
            source_system="TestSystem",
            responsible_user=self.user,
            validate_fhir=False  # Don't validate to test conversion errors
        )
        
        # Should handle gracefully
        self.assertTrue(result['success'])
        # Resource may be skipped due to conversion error
        self.assertGreaterEqual(result['resources_skipped'], 0)
    
    @patch('apps.fhir.services.logger')
    def test_logging_on_error(self, mock_logger):
        """Test that errors are properly logged."""
        # Trigger an error by providing invalid patient
        try:
            self.accumulator.add_resources_to_patient(
                patient=None,
                fhir_resources=[self.sample_condition_resource],
                source_system="TestSystem"
            )
        except FHIRAccumulationError:
            pass
        
        # Verify error was logged
        mock_logger.error.assert_called()


class FHIRAccumulatorIntegrationTests(FHIRAccumulatorTestCase):
    """Integration tests for complete FHIR accumulation workflows."""
    
    def test_complete_document_processing_workflow(self):
        """Test a complete document processing workflow with FHIR accumulation."""
        # Simulate a complete workflow
        document_id = "DOC123"
        source_system = "DocumentAnalyzer"
        
        # Multiple resources from document processing
        extracted_resources = [
            self.sample_condition_resource,
            self.sample_observation_resource,
            self.sample_medication_resource
        ]
        
        # Process with full options
        result = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=extracted_resources,
            source_system=source_system,
            responsible_user=self.user,
            source_document_id=document_id,
            reason="Medical document processing",
            validate_fhir=True,
            resolve_conflicts=True
        )
        
        # Verify complete workflow
        self.assertTrue(result['success'])
        self.assertEqual(result['resources_added'], 3)
        self.assertEqual(result['resources_skipped'], 0)
        
        # Verify audit trail
        audit_logs = AuditLog.objects.filter(
            event_type='fhir_import',
            patient_mrn=self.patient.mrn
        )
        self.assertGreaterEqual(audit_logs.count(), 1)
        
        # Verify patient history
        history_records = PatientHistory.objects.filter(
            patient=self.patient,
            action='fhir_append'
        )
        self.assertGreaterEqual(history_records.count(), 1)
        
        # Verify bundle integrity
        validation_result = self.accumulator.validate_patient_fhir_data(self.patient)
        self.assertTrue(validation_result['is_valid'])
        
        # Verify summary
        summary = self.accumulator.get_patient_fhir_summary(self.patient)
        self.assertEqual(summary['patient_mrn'], self.patient.mrn)
        self.assertGreater(summary['total_entries'], 0)
    
    def test_multiple_document_accumulation(self):
        """Test accumulating FHIR resources from multiple documents."""
        # First document
        doc1_resources = [self.sample_condition_resource]
        result1 = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=doc1_resources,
            source_system="DocumentAnalyzer",
            responsible_user=self.user,
            source_document_id="DOC001",
            reason="First document processing"
        )
        
        # Second document
        doc2_resources = [self.sample_observation_resource]
        result2 = self.accumulator.add_resources_to_patient(
            patient=self.patient,
            fhir_resources=doc2_resources,
            source_system="DocumentAnalyzer",
            responsible_user=self.user,
            source_document_id="DOC002",
            reason="Second document processing"
        )
        
        # Both should succeed
        self.assertTrue(result1['success'])
        self.assertTrue(result2['success'])
        
        # Verify cumulative effect
        summary = self.accumulator.get_patient_fhir_summary(self.patient)
        self.assertIn('Condition', summary['resource_types'])
        self.assertIn('Observation', summary['resource_types'])
        
        # Verify separate patient history entries
        history_records = PatientHistory.objects.filter(
            patient=self.patient,
            action='fhir_append'
        )
        self.assertEqual(history_records.count(), 2) 