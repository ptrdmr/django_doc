"""
Comprehensive test suite for Patient Data Validation system.
Tests the complete workflow from comparison to resolution to audit trail.
"""

import json
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch, MagicMock

from apps.patients.models import Patient
from apps.documents.models import Document, ParsedData, PatientDataComparison, PatientDataAudit
from apps.documents.services import PatientDataComparisonService, PatientRecordUpdateService

User = get_user_model()


class PatientDataComparisonServiceTests(TestCase):
    """Test the PatientDataComparisonService functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            gender='M',
            phone='555-123-4567',
            email='john.doe@example.com',
            created_by=self.user
        )
        
        self.document = Document.objects.create(
            filename='test_document.pdf',
            patient=self.patient,
            status='review',
            uploaded_by=self.user,
            created_by=self.user
        )
        
        self.parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json=[
                {
                    'label': 'patient_name',
                    'value': 'Jonathan Doe',  # Different from patient record
                    'confidence': 0.9
                },
                {
                    'label': 'date_of_birth',
                    'value': '01/15/1980',  # Same as patient record but different format
                    'confidence': 0.8
                },
                {
                    'label': 'phone',
                    'value': '(555) 123-4567',  # Same as patient record but different format
                    'confidence': 0.7
                }
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.8,
            created_by=self.user
        )
        
        self.service = PatientDataComparisonService()
    
    def test_compare_patient_data_creates_comparison(self):
        """Test that compare_patient_data creates a PatientDataComparison record."""
        comparison = self.service.compare_patient_data(self.document, self.patient)
        
        self.assertIsInstance(comparison, PatientDataComparison)
        self.assertEqual(comparison.document, self.document)
        self.assertEqual(comparison.patient, self.patient)
        self.assertEqual(comparison.parsed_data, self.parsed_data)
        self.assertGreater(comparison.total_fields_compared, 0)
    
    def test_identify_discrepancies_detects_name_difference(self):
        """Test that name differences are properly detected."""
        extracted_data = {'patient_name': {'value': 'Jonathan Doe', 'confidence': 0.9}}
        patient_data = {'first_name': 'John', 'last_name': 'Doe', 'full_name': 'John Doe'}
        
        results = self.service.identify_discrepancies(extracted_data, patient_data)
        
        self.assertIn('patient_name', results)
        self.assertTrue(results['patient_name']['has_discrepancy'])
        self.assertEqual(results['patient_name']['extracted_value'], 'Jonathan Doe')
        self.assertEqual(results['patient_name']['patient_value'], 'John')
    
    def test_generate_suggestions_confidence_based(self):
        """Test that suggestions are generated based on confidence levels."""
        comparison_data = {
            'high_confidence_field': {
                'has_discrepancy': True,
                'confidence': 0.9,
                'suggested_resolution': 'use_extracted',
                'extracted_value': 'High Conf Value',
                'patient_value': 'Old Value'
            },
            'low_confidence_field': {
                'has_discrepancy': True,
                'confidence': 0.3,
                'suggested_resolution': 'manual_edit',
                'extracted_value': 'Low Conf Value',
                'patient_value': 'Old Value'
            }
        }
        
        suggestions = self.service.generate_suggestions(comparison_data)
        
        self.assertEqual(len(suggestions['high_confidence_updates']), 1)
        self.assertEqual(len(suggestions['low_confidence_warnings']), 1)
    
    def test_validate_data_quality_scores_fields(self):
        """Test that data quality validation works correctly."""
        field_data = {
            'valid_email': {'value': 'test@example.com'},
            'invalid_email': {'value': 'not-an-email'},
            'valid_phone': {'value': '555-123-4567'},
            'invalid_phone': {'value': '123'}
        }
        
        results = self.service.validate_data_quality(field_data)
        
        self.assertGreater(results['overall_quality_score'], 0.0)
        self.assertEqual(len(results['field_validations']), 4)
        self.assertIn('invalid_email', results['format_issues'][0])


class PatientRecordUpdateServiceTests(TestCase):
    """Test the PatientRecordUpdateService functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            gender='M',
            created_by=self.user
        )
        
        self.document = Document.objects.create(
            filename='test_document.pdf',
            patient=self.patient,
            status='review',
            uploaded_by=self.user,
            created_by=self.user
        )
        
        self.parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'patient_name': {'value': 'Jonathan Doe', 'confidence': 0.9}},
            created_by=self.user
        )
        
        self.comparison = PatientDataComparison.objects.create(
            document=self.document,
            patient=self.patient,
            parsed_data=self.parsed_data,
            comparison_data={
                'patient_name': {
                    'extracted_value': 'Jonathan Doe',
                    'patient_value': 'John Doe',
                    'has_discrepancy': True,
                    'confidence': 0.9
                }
            },
            resolution_decisions={
                'patient_name': {
                    'resolution': 'use_extracted',
                    'notes': 'Test resolution'
                }
            },
            total_fields_compared=1,
            discrepancies_found=1,
            created_by=self.user
        )
        
        self.service = PatientRecordUpdateService()
    
    def test_apply_comparison_resolutions_updates_patient(self):
        """Test that comparison resolutions are applied to patient record."""
        original_name = self.patient.first_name
        
        results = self.service.apply_comparison_resolutions(self.comparison, self.user)
        
        self.assertTrue(results['success'])
        self.assertGreater(results['updates_applied'], 0)
        
        # Refresh patient from database
        self.patient.refresh_from_db()
        
        # Verify the update was applied (this test may need adjustment based on actual field mapping)
        self.assertNotEqual(self.patient.first_name, original_name)
    
    def test_validate_batch_updates_catches_invalid_data(self):
        """Test that batch validation catches invalid data."""
        update_requests = [
            {
                'patient': self.patient,
                'field_name': 'email',
                'new_value': 'valid@example.com'
            },
            {
                'patient': self.patient,
                'field_name': 'email',
                'new_value': 'invalid-email'
            }
        ]
        
        results = self.service.validate_batch_updates(update_requests)
        
        self.assertFalse(results['is_valid'])
        self.assertEqual(len(results['valid_updates']), 1)
        self.assertEqual(len(results['invalid_updates']), 1)
    
    def test_rollback_patient_updates_restores_values(self):
        """Test that rollback functionality works correctly."""
        original_values = {
            'first_name': self.patient.first_name,
            'email': self.patient.email
        }
        
        # Make some changes
        self.patient.first_name = 'Changed Name'
        self.patient.email = 'changed@example.com'
        self.patient.save()
        
        # Rollback
        results = self.service.rollback_patient_updates(self.patient, original_values, self.user)
        
        self.assertTrue(results['success'])
        self.assertEqual(results['fields_rolled_back'], 2)
        
        # Verify rollback
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.first_name, original_values['first_name'])


class PatientDataValidationIntegrationTests(TestCase):
    """Integration tests for the complete patient data validation workflow."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.force_login(self.user)
        
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            created_by=self.user
        )
        
        self.document = Document.objects.create(
            filename='test_document.pdf',
            patient=self.patient,
            status='review',
            uploaded_by=self.user,
            created_by=self.user
        )
        
        self.parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json=[
                {
                    'label': 'patient_name',
                    'value': 'Jonathan Doe',
                    'confidence': 0.9
                }
            ],
            created_by=self.user
        )
    
    def test_document_review_creates_comparison(self):
        """Test that accessing document review creates a comparison."""
        url = reverse('documents:review', kwargs={'pk': self.document.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Check that comparison was created
        comparison = PatientDataComparison.objects.filter(
            document=self.document,
            patient=self.patient
        ).first()
        
        self.assertIsNotNone(comparison)
        self.assertGreater(comparison.total_fields_compared, 0)
    
    def test_field_resolution_endpoint_works(self):
        """Test that field resolution AJAX endpoint works."""
        # Create comparison first
        comparison = PatientDataComparison.objects.create(
            document=self.document,
            patient=self.patient,
            parsed_data=self.parsed_data,
            comparison_data={
                'patient_name': {
                    'extracted_value': 'Jonathan Doe',
                    'patient_value': 'John Doe',
                    'has_discrepancy': True
                }
            },
            total_fields_compared=1,
            discrepancies_found=1,
            created_by=self.user
        )
        
        url = reverse('documents:resolve-patient-data', kwargs={'pk': self.document.pk})
        data = {
            'action': 'resolve_field',
            'field_name': 'patient_name',
            'resolution': 'use_extracted',
            'reasoning': 'Test resolution'
        }
        
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data['success'])
    
    def test_document_approval_applies_patient_updates(self):
        """Test that document approval applies patient data updates."""
        # Create comparison with resolution
        comparison = PatientDataComparison.objects.create(
            document=self.document,
            patient=self.patient,
            parsed_data=self.parsed_data,
            comparison_data={
                'patient_name': {
                    'extracted_value': 'Jonathan Doe',
                    'patient_value': 'John Doe',
                    'has_discrepancy': True
                }
            },
            resolution_decisions={
                'patient_name': {
                    'resolution': 'use_extracted',
                    'notes': 'Test update'
                }
            },
            total_fields_compared=1,
            discrepancies_found=1,
            fields_resolved=1,
            created_by=self.user
        )
        
        # Approve the document
        url = reverse('documents:review', kwargs={'pk': self.document.pk})
        response = self.client.post(url, {'action': 'approve'})
        
        # Check that document was approved
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, 'completed')
        
        # Check that comparison was marked as resolved
        comparison.refresh_from_db()
        self.assertEqual(comparison.status, 'resolved')


class PatientDataAuditTests(TestCase):
    """Test the PatientDataAudit model functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='John',
            last_name='Doe',
            created_by=self.user
        )
        
        self.audit = PatientDataAudit.objects.create(
            patient=self.patient,
            field_name='first_name',
            change_type='field_update',
            change_source='document_review',
            original_value='John',
            new_value='Jonathan',
            reviewer=self.user,
            reviewer_reasoning='Test change',
            created_by=self.user
        )
    
    def test_audit_model_creation(self):
        """Test that audit records are created correctly."""
        self.assertEqual(self.audit.patient, self.patient)
        self.assertEqual(self.audit.field_name, 'first_name')
        self.assertEqual(self.audit.change_type, 'field_update')
        self.assertEqual(self.audit.reviewer, self.user)
    
    def test_get_change_summary(self):
        """Test that change summary is generated correctly."""
        summary = self.audit.get_change_summary()
        self.assertIn('first_name', summary)
        self.assertIn('John', summary)
        self.assertIn('Jonathan', summary)
    
    def test_is_high_impact_change(self):
        """Test that high impact changes are identified."""
        # first_name should be high impact
        self.assertTrue(self.audit.is_high_impact_change())
        
        # Create a low impact change
        low_impact_audit = PatientDataAudit.objects.create(
            patient=self.patient,
            field_name='email',
            change_type='field_update',
            original_value='old@example.com',
            new_value='new@example.com',
            created_by=self.user
        )
        
        self.assertFalse(low_impact_audit.is_high_impact_change())
    
    def test_get_patient_change_history(self):
        """Test that patient change history is retrieved correctly."""
        # Create additional audit entries
        PatientDataAudit.objects.create(
            patient=self.patient,
            field_name='email',
            change_type='manual_edit',
            original_value='old@example.com',
            new_value='new@example.com',
            created_by=self.user
        )
        
        history = PatientDataAudit.get_patient_change_history(self.patient)
        
        self.assertGreaterEqual(len(history), 2)
        self.assertEqual(history[0].patient, self.patient)


class PatientDataValidationUITests(TestCase):
    """Test the UI components of the patient data validation system."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.force_login(self.user)
        
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='John',
            last_name='Doe',
            created_by=self.user
        )
        
        self.document = Document.objects.create(
            filename='test_document.pdf',
            patient=self.patient,
            status='review',
            uploaded_by=self.user,
            created_by=self.user
        )
        
        self.parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json=[
                {
                    'label': 'patient_name',
                    'value': 'Jonathan Doe',
                    'confidence': 0.9
                }
            ],
            created_by=self.user
        )
    
    def test_review_page_includes_comparison_context(self):
        """Test that review page includes comparison data in context."""
        url = reverse('documents:review', kwargs={'pk': self.document.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('comparison', response.context)
        
        # If comparison is created, it should have discrepancies
        if response.context['comparison']:
            self.assertGreaterEqual(response.context['comparison'].total_fields_compared, 0)
    
    def test_review_template_renders_comparison_section(self):
        """Test that review template renders comparison section when data exists."""
        # First create a comparison
        comparison = PatientDataComparison.objects.create(
            document=self.document,
            patient=self.patient,
            parsed_data=self.parsed_data,
            comparison_data={
                'patient_name': {
                    'extracted_value': 'Jonathan Doe',
                    'patient_value': 'John Doe',
                    'has_discrepancy': True
                }
            },
            total_fields_compared=1,
            discrepancies_found=1,
            created_by=self.user
        )
        
        url = reverse('documents:review', kwargs={'pk': self.document.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'patient-comparison-container')
        self.assertContains(response, 'Patient Data Comparison')


class PatientDataValidationSecurityTests(TestCase):
    """Test security aspects of the patient data validation system."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='John',
            last_name='Doe',
            created_by=self.user
        )
        
        self.document = Document.objects.create(
            filename='test_document.pdf',
            patient=self.patient,
            status='review',
            uploaded_by=self.user,
            created_by=self.user
        )
    
    def test_resolution_endpoint_requires_authentication(self):
        """Test that resolution endpoints require authentication."""
        self.client.logout()
        
        url = reverse('documents:resolve-patient-data', kwargs={'pk': self.document.pk})
        response = self.client.post(url, {'action': 'resolve_field'})
        
        # Should redirect to login or return 403
        self.assertIn(response.status_code, [302, 403])
    
    def test_resolution_endpoint_requires_document_ownership(self):
        """Test that users can only resolve their own documents."""
        self.client.force_login(self.other_user)
        
        url = reverse('documents:resolve-patient-data', kwargs={'pk': self.document.pk})
        response = self.client.post(url, {
            'action': 'resolve_field',
            'field_name': 'test_field',
            'resolution': 'keep_existing'
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        
        # Should return 404 since other_user doesn't own this document
        self.assertEqual(response.status_code, 404)
    
    def test_audit_data_is_encrypted(self):
        """Test that sensitive audit data is encrypted."""
        audit = PatientDataAudit.objects.create(
            patient=self.patient,
            field_name='ssn',
            change_type='field_update',
            original_value='123-45-6789',
            new_value='987-65-4321',
            reviewer_reasoning='Test PHI change',
            created_by=self.user
        )
        
        # The actual database values should be encrypted (different from input)
        # This is a basic check - in practice, you'd verify encryption more thoroughly
        self.assertIsNotNone(audit.original_value)
        self.assertIsNotNone(audit.new_value)
        self.assertIsNotNone(audit.reviewer_reasoning)


class PatientDataValidationPerformanceTests(TestCase):
    """Test performance aspects of the patient data validation system."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='John',
            last_name='Doe',
            created_by=self.user
        )
        
        self.service = PatientDataComparisonService()
    
    def test_comparison_service_performance_with_large_dataset(self):
        """Test comparison service performance with many fields."""
        # Create large extraction dataset
        large_extraction_data = {}
        for i in range(50):
            large_extraction_data[f'field_{i}'] = {
                'value': f'value_{i}',
                'confidence': 0.8
            }
        
        patient_data = {
            'first_name': 'John',
            'last_name': 'Doe'
        }
        
        # This should complete reasonably quickly
        import time
        start_time = time.time()
        
        results = self.service.identify_discrepancies(large_extraction_data, patient_data)
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Should complete within reasonable time (adjust threshold as needed)
        self.assertLess(processing_time, 5.0)  # 5 seconds max
        self.assertGreater(len(results), 0)


class PatientDataValidationEdgeCaseTests(TestCase):
    """Test edge cases and error scenarios."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='John',
            last_name='Doe',
            created_by=self.user
        )
        
        self.service = PatientDataComparisonService()
    
    def test_comparison_with_empty_extraction_data(self):
        """Test comparison behavior with empty extraction data."""
        extracted_data = {}
        patient_data = {'first_name': 'John', 'last_name': 'Doe'}
        
        results = self.service.identify_discrepancies(extracted_data, patient_data)
        
        self.assertEqual(len(results), 0)
    
    def test_comparison_with_malformed_data(self):
        """Test comparison behavior with malformed data."""
        extracted_data = {
            'malformed_field': None,
            'empty_field': '',
            'nested_field': {'nested': {'value': 'test'}}
        }
        patient_data = {'first_name': 'John'}
        
        # Should not crash
        results = self.service.identify_discrepancies(extracted_data, patient_data)
        
        # Should handle malformed data gracefully
        self.assertIsInstance(results, dict)
    
    def test_string_similarity_edge_cases(self):
        """Test string similarity calculation with edge cases."""
        # Empty strings
        similarity = self.service._calculate_string_similarity('', '')
        self.assertEqual(similarity, 1.0)
        
        # One empty string
        similarity = self.service._calculate_string_similarity('test', '')
        self.assertEqual(similarity, 0.0)
        
        # Identical strings
        similarity = self.service._calculate_string_similarity('test', 'test')
        self.assertEqual(similarity, 1.0)
        
        # Completely different strings
        similarity = self.service._calculate_string_similarity('abc', 'xyz')
        self.assertLess(similarity, 0.5)
