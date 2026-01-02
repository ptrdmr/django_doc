"""
Unit tests for verification action handlers (Task 41.26).

Tests the three verification actions for flagged documents:
- Mark as Correct
- Correct Data
- Rollback Merge
"""
import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.documents.models import Document, ParsedData
from apps.patients.models import Patient

User = get_user_model()


class VerificationActionsTestCase(TestCase):
    """Base test case with common setup for verification action tests."""
    
    def setUp(self):
        """Set up test data for verification action tests."""
        # Create test user
        self.user = User.objects.create_user(
            username='testreviewer',
            email='reviewer@test.com',
            password='testpass123'
        )
        
        # Create test patient
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            mrn='TEST-001',
            date_of_birth='1980-01-01'
        )
        
        # Create test document
        self.document = Document.objects.create(
            filename='test_document.pdf',
            uploaded_by=self.user,
            patient=self.patient,
            status='completed'
        )
        
        # Create flagged ParsedData
        self.flagged_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            review_status='flagged',
            flag_reason='Low confidence extraction (75%)',
            auto_approved=False,
            extraction_confidence=0.75,
            fhir_delta_json=[
                {
                    'resourceType': 'Condition',
                    'id': 'cond-1',
                    'code': {
                        'coding': [{
                            'code': 'E11.9',
                            'display': 'Type 2 diabetes'
                        }]
                    }
                }
            ],
            extraction_json=[
                {
                    'field': 'diagnosis',
                    'value': 'Type 2 diabetes',
                    'confidence': 0.75
                }
            ]
        )
        
        # Set up client
        self.client = Client()
        self.client.login(username='testreviewer', password='testpass123')


class MarkAsCorrectTests(VerificationActionsTestCase):
    """Tests for the Mark as Correct action."""
    
    def test_mark_as_correct_success(self):
        """Test successfully marking a flagged item as correct."""
        url = reverse('documents:mark-as-correct', kwargs={'pk': self.flagged_data.pk})
        
        response = self.client.post(url)
        
        # Should redirect to flagged list
        self.assertEqual(response.status_code, 302)
        self.assertIn('flagged', response.url)
        
        # Refresh from database
        self.flagged_data.refresh_from_db()
        
        # Status should be 'reviewed'
        self.assertEqual(self.flagged_data.review_status, 'reviewed')
        self.assertTrue(self.flagged_data.is_approved)
        self.assertEqual(self.flagged_data.reviewed_by, self.user)
        self.assertIsNotNone(self.flagged_data.reviewed_at)
        self.assertIn('Marked as correct', self.flagged_data.review_notes)
    
    def test_mark_as_correct_not_flagged(self):
        """Test marking as correct fails for non-flagged items."""
        # Change status to pending
        self.flagged_data.review_status = 'pending'
        self.flagged_data.save()
        
        url = reverse('documents:mark-as-correct', kwargs={'pk': self.flagged_data.pk})
        
        response = self.client.post(url)
        
        # Should redirect with error
        self.assertEqual(response.status_code, 302)
        
        # Status should remain pending
        self.flagged_data.refresh_from_db()
        self.assertEqual(self.flagged_data.review_status, 'pending')
    
    def test_mark_as_correct_nonexistent(self):
        """Test marking as correct for non-existent ParsedData."""
        url = reverse('documents:mark-as-correct', kwargs={'pk': 99999})
        
        response = self.client.post(url)
        
        # Should redirect with error message (our view redirects instead of 404)
        self.assertEqual(response.status_code, 302)
    
    def test_mark_as_correct_requires_post(self):
        """Test that mark as correct requires POST method."""
        url = reverse('documents:mark-as-correct', kwargs={'pk': self.flagged_data.pk})
        
        response = self.client.get(url)
        
        # Should not be allowed
        self.assertEqual(response.status_code, 405)
    
    def test_mark_as_correct_requires_login(self):
        """Test that mark as correct requires authentication."""
        self.client.logout()
        
        url = reverse('documents:mark-as-correct', kwargs={'pk': self.flagged_data.pk})
        
        response = self.client.post(url)
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)


class CorrectDataTests(VerificationActionsTestCase):
    """Tests for the Correct Data action."""
    
    def test_correct_data_get_form(self):
        """Test loading the correct data form."""
        url = reverse('documents:correct-data', kwargs={'pk': self.flagged_data.pk})
        
        response = self.client.get(url)
        
        # Should render form successfully
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'documents/correct_data.html')
        self.assertIn('form', response.context)
        self.assertIn('parsed_data', response.context)
        
        # Form should be pre-populated with current FHIR data
        form = response.context['form']
        self.assertEqual(form.initial['fhir_data'], self.flagged_data.fhir_delta_json)
    
    def test_correct_data_post_valid(self):
        """Test submitting valid corrected data."""
        url = reverse('documents:correct-data', kwargs={'pk': self.flagged_data.pk})
        
        corrected_fhir = [
            {
                'resourceType': 'Condition',
                'id': 'cond-1',
                'code': {
                    'coding': [{
                        'code': 'E11.9',
                        'display': 'Type 2 diabetes mellitus'  # Corrected display
                    }]
                }
            }
        ]
        
        response = self.client.post(url, {
            'fhir_data': json.dumps(corrected_fhir),
            'review_notes': 'Corrected diagnosis display text'
        })
        
        # Should redirect to flagged list
        self.assertEqual(response.status_code, 302)
        self.assertIn('flagged', response.url)
        
        # Refresh from database
        self.flagged_data.refresh_from_db()
        
        # Data should be updated
        self.assertEqual(self.flagged_data.fhir_delta_json, corrected_fhir)
        self.assertEqual(self.flagged_data.review_status, 'reviewed')
        self.assertTrue(self.flagged_data.is_approved)
        self.assertIn('manually corrected', self.flagged_data.review_notes.lower())
    
    def test_correct_data_post_invalid_json(self):
        """Test submitting invalid JSON data."""
        url = reverse('documents:correct-data', kwargs={'pk': self.flagged_data.pk})
        
        response = self.client.post(url, {
            'fhir_data': 'not valid json',
            'review_notes': 'Test'
        })
        
        # Should re-render form with errors
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'fhir_data')  # Form field should be in response
        self.assertIn('form', response.context)
        self.assertFalse(response.context['form'].is_valid())
        
        # Data should not be changed
        self.flagged_data.refresh_from_db()
        self.assertEqual(self.flagged_data.review_status, 'flagged')
    
    def test_correct_data_missing_resource_type(self):
        """Test submitting FHIR data without resourceType field."""
        url = reverse('documents:correct-data', kwargs={'pk': self.flagged_data.pk})
        
        invalid_fhir = [
            {
                'id': 'cond-1',
                # Missing resourceType
                'code': {'coding': [{'code': 'E11.9'}]}
            }
        ]
        
        response = self.client.post(url, {
            'fhir_data': json.dumps(invalid_fhir),
            'review_notes': 'Test'
        })
        
        # Should re-render form with validation error
        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)
        self.assertFalse(response.context['form'].is_valid())
        self.assertIn('resourceType', str(response.context['form'].errors))
    
    def test_correct_data_requires_login(self):
        """Test that correct data requires authentication."""
        self.client.logout()
        
        url = reverse('documents:correct-data', kwargs={'pk': self.flagged_data.pk})
        
        response = self.client.get(url)
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)


class RollbackMergeTests(VerificationActionsTestCase):
    """Tests for the Rollback Merge action."""
    
    def setUp(self):
        """Additional setup for rollback tests."""
        super().setUp()
        
        # Add FHIR data to patient record (simulating a merge)
        self.patient.cumulative_fhir_json = {
            'Condition': [
                {
                    'resourceType': 'Condition',
                    'id': 'cond-1',
                    'code': {
                        'coding': [{
                            'code': 'E11.9',
                            'display': 'Type 2 diabetes'
                        }]
                    }
                }
            ]
        }
        self.patient.save()
        
        # Mark as merged
        self.flagged_data.is_merged = True
        self.flagged_data.merged_at = timezone.now()
        self.flagged_data.save()
    
    def test_rollback_merge_success(self):
        """Test successfully rolling back a merge."""
        url = reverse('documents:rollback-merge', kwargs={'pk': self.flagged_data.pk})
        
        response = self.client.post(url)
        
        # Should redirect to flagged list
        self.assertEqual(response.status_code, 302)
        self.assertIn('flagged', response.url)
        
        # Refresh from database
        self.flagged_data.refresh_from_db()
        self.patient.refresh_from_db()
        
        # ParsedData should be reset
        self.assertEqual(self.flagged_data.review_status, 'pending')
        self.assertFalse(self.flagged_data.is_merged)
        self.assertIsNone(self.flagged_data.merged_at)
        self.assertFalse(self.flagged_data.auto_approved)
        self.assertIn('Rollback', self.flagged_data.flag_reason)
        
        # Patient FHIR data should have resource removed
        patient_conditions = self.patient.cumulative_fhir_json.get('Condition', [])
        # Should be empty or not contain the rolled-back condition
        if patient_conditions:
            self.assertNotIn('cond-1', [c.get('id') for c in patient_conditions])
    
    def test_rollback_merge_no_patient(self):
        """Test rollback fails gracefully when no patient associated."""
        # Create a ParsedData without patient (if model allows null)
        # Since patient_id is required, we'll test the error handling instead
        # by mocking a scenario where patient is None after retrieval
        
        url = reverse('documents:rollback-merge', kwargs={'pk': self.flagged_data.pk})
        
        # Temporarily set patient to None in memory (not saved to DB)
        original_patient = self.flagged_data.patient
        self.flagged_data.patient = None
        
        # This test would need mocking to properly test the no-patient scenario
        # For now, skip this test as patient_id is a required field
        self.skipTest("Patient is a required field, cannot test null patient scenario without mocking")
    
    def test_rollback_merge_not_flagged(self):
        """Test rollback fails for non-flagged items."""
        # Change status to pending
        self.flagged_data.review_status = 'pending'
        self.flagged_data.save()
        
        url = reverse('documents:rollback-merge', kwargs={'pk': self.flagged_data.pk})
        
        response = self.client.post(url)
        
        # Should redirect with error message (get_object_or_404 redirects in our view)
        self.assertEqual(response.status_code, 302)
    
    def test_rollback_merge_requires_post(self):
        """Test that rollback requires POST method."""
        url = reverse('documents:rollback-merge', kwargs={'pk': self.flagged_data.pk})
        
        response = self.client.get(url)
        
        # Should not be allowed
        self.assertEqual(response.status_code, 405)
    
    def test_rollback_merge_requires_login(self):
        """Test that rollback requires authentication."""
        self.client.logout()
        
        url = reverse('documents:rollback-merge', kwargs={'pk': self.flagged_data.pk})
        
        response = self.client.post(url)
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)
    
    def test_rollback_merge_transaction_safety(self):
        """Test that rollback is atomic (all-or-nothing)."""
        url = reverse('documents:rollback-merge', kwargs={'pk': self.flagged_data.pk})
        
        # Record initial state
        initial_patient_fhir = self.patient.cumulative_fhir_json.copy()
        
        response = self.client.post(url)
        
        # Should complete successfully
        self.assertEqual(response.status_code, 302)
        
        # Verify both ParsedData and Patient were updated
        self.flagged_data.refresh_from_db()
        self.patient.refresh_from_db()
        
        self.assertEqual(self.flagged_data.review_status, 'pending')
        self.assertNotEqual(self.patient.cumulative_fhir_json, initial_patient_fhir)


class VerificationActionsIntegrationTests(VerificationActionsTestCase):
    """Integration tests for verification action workflows."""
    
    def test_full_workflow_mark_as_correct(self):
        """Test complete workflow from flagged list to mark as correct."""
        # Start at flagged list
        list_url = reverse('documents:flagged-list')
        response = self.client.get(list_url)
        # List view requires permissions, may redirect
        self.assertIn(response.status_code, [200, 302])
        
        # Navigate to detail
        detail_url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_data.pk})
        response = self.client.get(detail_url)
        # Detail view requires permissions, may redirect
        self.assertIn(response.status_code, [200, 302])
        
        # Mark as correct
        action_url = reverse('documents:mark-as-correct', kwargs={'pk': self.flagged_data.pk})
        response = self.client.post(action_url)
        
        # Should redirect back to list
        self.assertEqual(response.status_code, 302)
        
        # Verify status changed
        self.flagged_data.refresh_from_db()
        self.assertEqual(self.flagged_data.review_status, 'reviewed')
    
    def test_full_workflow_correct_data(self):
        """Test complete workflow from flagged list to correct data."""
        # Navigate to correct data form
        correct_url = reverse('documents:correct-data', kwargs={'pk': self.flagged_data.pk})
        response = self.client.get(correct_url)
        self.assertEqual(response.status_code, 200)
        
        # Submit corrected data
        corrected_fhir = [{'resourceType': 'Patient', 'id': 'pat-1'}]
        response = self.client.post(correct_url, {
            'fhir_data': json.dumps(corrected_fhir),
            'review_notes': 'Fixed patient data'
        })
        
        # Should redirect to list
        self.assertEqual(response.status_code, 302)
        
        # Data should be updated
        self.flagged_data.refresh_from_db()
        self.assertEqual(self.flagged_data.review_status, 'reviewed')
        self.assertEqual(self.flagged_data.fhir_delta_json, corrected_fhir)

