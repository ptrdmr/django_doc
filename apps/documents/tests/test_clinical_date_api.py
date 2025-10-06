"""
Tests for clinical date API endpoints (Task 35.6).

Tests the save_clinical_date and verify_clinical_date endpoints,
including validation, permissions, audit logging, and HIPAA compliance.
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User, Permission
from django.utils import timezone
from datetime import date, timedelta
from apps.documents.models import Document, ParsedData
from apps.patients.models import Patient
from apps.core.models import AuditLog


class ClinicalDateAPITestCase(TestCase):
    """Test suite for clinical date management API endpoints."""
    
    def setUp(self):
        """Set up test data for clinical date API tests."""
        # Create test user with permissions
        self.user = User.objects.create_user(
            username='testdoctor',
            password='testpass123',
            email='doctor@test.com'
        )
        
        # Grant necessary permissions
        self.change_perm = Permission.objects.get(codename='change_document')
        self.user.user_permissions.add(self.change_perm)
        
        # Create test patient
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            mrn='TEST001',
            date_of_birth=date(1980, 1, 1)
        )
        
        # Create test document
        self.document = Document.objects.create(
            patient=self.patient,
            filename='test_medical_document.pdf',
            status='completed',
            uploaded_by=self.user
        )
        
        # Create test parsed data
        self.parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'diagnosis': 'Diabetes diagnosed on May 15, 2023'},
            fhir_delta_json={},
            extraction_confidence=0.9
        )
        
        # Set up client
        self.client = Client()
        self.client.force_login(self.user)
    
    def test_save_clinical_date_success(self):
        """Test successfully saving a clinical date."""
        response = self.client.post('/documents/clinical-date/save/', {
            'parsed_data_id': self.parsed_data.id,
            'clinical_date': '2023-05-15',
            'document_id': self.document.id
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['clinical_date'], '2023-05-15')
        self.assertEqual(data['date_source'], 'manual')
        self.assertEqual(data['date_status'], 'pending')
        
        # Verify database update
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.clinical_date, date(2023, 5, 15))
        self.assertEqual(self.parsed_data.date_source, 'manual')
        self.assertEqual(self.parsed_data.date_status, 'pending')
    
    def test_save_clinical_date_missing_parameters(self):
        """Test error handling when required parameters are missing."""
        # Missing clinical_date
        response = self.client.post('/documents/clinical-date/save/', {
            'parsed_data_id': self.parsed_data.id,
            'document_id': self.document.id
        })
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Missing required parameters', data['error'])
    
    def test_save_clinical_date_invalid_format(self):
        """Test error handling for invalid date formats."""
        # Truly invalid format that parser cannot handle
        response = self.client.post('/documents/clinical-date/save/', {
            'parsed_data_id': self.parsed_data.id,
            'clinical_date': 'not-a-date-at-all',  # Completely invalid
            'document_id': self.document.id
        })
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Invalid', data['error'])
    
    def test_save_clinical_date_future_date(self):
        """Test that future dates are rejected."""
        future_date = (timezone.now().date() + timedelta(days=30)).isoformat()
        
        response = self.client.post('/documents/clinical-date/save/', {
            'parsed_data_id': self.parsed_data.id,
            'clinical_date': future_date,
            'document_id': self.document.id
        })
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('future', data['error'].lower())
    
    def test_save_clinical_date_too_old(self):
        """Test that dates before 1900 are rejected."""
        response = self.client.post('/documents/clinical-date/save/', {
            'parsed_data_id': self.parsed_data.id,
            'clinical_date': '1850-01-01',
            'document_id': self.document.id
        })
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        # Parser may reject as invalid format or our code may reject as too old
        self.assertIn('error', data)
    
    def test_save_clinical_date_no_permission(self):
        """Test that users without permission cannot save dates."""
        # Create user without permissions
        unprivileged_user = User.objects.create_user(
            username='unprivileged',
            password='testpass123'
        )
        
        # Login as unprivileged user
        self.client.force_login(unprivileged_user)
        
        response = self.client.post('/documents/clinical-date/save/', {
            'parsed_data_id': self.parsed_data.id,
            'clinical_date': '2023-05-15',
            'document_id': self.document.id
        })
        
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Permission denied', data['error'])
    
    def test_save_clinical_date_audit_logging(self):
        """Test that clinical date changes are properly logged for HIPAA compliance."""
        # Clear any existing audit logs
        AuditLog.objects.all().delete()
        
        # Save clinical date
        self.client.post('/documents/clinical-date/save/', {
            'parsed_data_id': self.parsed_data.id,
            'clinical_date': '2023-05-15',
            'document_id': self.document.id
        })
        
        # Verify audit log was created
        audit_logs = AuditLog.objects.filter(
            user=self.user,
            event_type='phi_update'
        )
        
        self.assertEqual(audit_logs.count(), 1)
        
        audit_log = audit_logs.first()
        self.assertEqual(audit_log.user, self.user)
        self.assertTrue(audit_log.phi_involved)
        self.assertEqual(audit_log.patient_mrn, 'TEST001')
        self.assertEqual(audit_log.severity, 'info')
        
        # Check details
        self.assertIn('clinical_date', audit_log.details)
        self.assertEqual(audit_log.details['clinical_date'], '2023-05-15')
        self.assertEqual(audit_log.details['date_source'], 'manual')
        self.assertEqual(audit_log.details['date_status'], 'pending')
    
    def test_save_clinical_date_update_existing(self):
        """Test updating an existing clinical date."""
        # First, set an initial date
        self.parsed_data.set_clinical_date(
            date='2023-05-01',
            source='extracted',
            status='pending'
        )
        
        # Update to a new date
        response = self.client.post('/documents/clinical-date/save/', {
            'parsed_data_id': self.parsed_data.id,
            'clinical_date': '2023-05-15',
            'document_id': self.document.id
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify the date was updated
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.clinical_date, date(2023, 5, 15))
        self.assertEqual(self.parsed_data.date_source, 'manual')  # Changed from extracted to manual
        self.assertEqual(self.parsed_data.date_status, 'pending')  # Reset to pending
    
    def test_verify_clinical_date_success(self):
        """Test successfully verifying a clinical date."""
        # Set up a pending date
        self.parsed_data.set_clinical_date(
            date='2023-05-15',
            source='manual',
            status='pending'
        )
        
        response = self.client.post('/documents/clinical-date/verify/', {
            'parsed_data_id': self.parsed_data.id,
            'document_id': self.document.id
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['date_status'], 'verified')
        
        # Verify database update
        self.parsed_data.refresh_from_db()
        self.assertTrue(self.parsed_data.is_date_verified())
    
    def test_verify_clinical_date_no_date(self):
        """Test error when trying to verify a non-existent date."""
        # Ensure no date exists
        self.assertFalse(self.parsed_data.has_clinical_date())
        
        response = self.client.post('/documents/clinical-date/verify/', {
            'parsed_data_id': self.parsed_data.id,
            'document_id': self.document.id
        })
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('No clinical date to verify', data['error'])
    
    def test_verify_clinical_date_missing_parameters(self):
        """Test error when required parameters are missing."""
        response = self.client.post('/documents/clinical-date/verify/', {
            'parsed_data_id': self.parsed_data.id
            # Missing document_id
        })
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Missing required parameters', data['error'])
    
    def test_verify_clinical_date_no_permission(self):
        """Test that users without permission cannot verify dates."""
        # Set up a pending date
        self.parsed_data.set_clinical_date(
            date='2023-05-15',
            source='manual',
            status='pending'
        )
        
        # Create user without permissions
        unprivileged_user = User.objects.create_user(
            username='unprivileged',
            password='testpass123'
        )
        
        # Login as unprivileged user
        self.client.force_login(unprivileged_user)
        
        response = self.client.post('/documents/clinical-date/verify/', {
            'parsed_data_id': self.parsed_data.id,
            'document_id': self.document.id
        })
        
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Permission denied', data['error'])
    
    def test_verify_clinical_date_audit_logging(self):
        """Test that date verification is properly logged for HIPAA compliance."""
        # Set up a pending date
        self.parsed_data.set_clinical_date(
            date='2023-05-15',
            source='manual',
            status='pending'
        )
        
        # Clear any existing audit logs
        AuditLog.objects.all().delete()
        
        # Verify clinical date
        self.client.post('/documents/clinical-date/verify/', {
            'parsed_data_id': self.parsed_data.id,
            'document_id': self.document.id
        })
        
        # Verify audit log was created
        audit_logs = AuditLog.objects.filter(
            user=self.user,
            event_type='phi_update'
        )
        
        self.assertEqual(audit_logs.count(), 1)
        
        audit_log = audit_logs.first()
        self.assertEqual(audit_log.user, self.user)
        self.assertTrue(audit_log.phi_involved)
        self.assertEqual(audit_log.patient_mrn, 'TEST001')
        self.assertEqual(audit_log.severity, 'info')
        
        # Check details
        self.assertIn('action', audit_log.details)
        self.assertEqual(audit_log.details['action'], 'verify')
        self.assertEqual(audit_log.details['previous_status'], 'pending')
        self.assertEqual(audit_log.details['new_status'], 'verified')
    
    def test_save_clinical_date_document_not_found(self):
        """Test error when document doesn't exist."""
        response = self.client.post('/documents/clinical-date/save/', {
            'parsed_data_id': self.parsed_data.id,
            'clinical_date': '2023-05-15',
            'document_id': 99999  # Non-existent
        })
        
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('not found', data['error'].lower())
    
    def test_save_clinical_date_parsed_data_not_found(self):
        """Test error when parsed data doesn't exist."""
        response = self.client.post('/documents/clinical-date/save/', {
            'parsed_data_id': 99999,  # Non-existent
            'clinical_date': '2023-05-15',
            'document_id': self.document.id
        })
        
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('not found', data['error'].lower())
    
    def test_clinical_date_workflow_integration(self):
        """Test complete workflow: save, verify, update."""
        # Step 1: Save initial date
        response = self.client.post('/documents/clinical-date/save/', {
            'parsed_data_id': self.parsed_data.id,
            'clinical_date': '2023-05-15',
            'document_id': self.document.id
        })
        self.assertEqual(response.status_code, 200)
        
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.date_status, 'pending')
        
        # Step 2: Verify the date
        response = self.client.post('/documents/clinical-date/verify/', {
            'parsed_data_id': self.parsed_data.id,
            'document_id': self.document.id
        })
        self.assertEqual(response.status_code, 200)
        
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.date_status, 'verified')
        
        # Step 3: Update the date (should reset to pending)
        response = self.client.post('/documents/clinical-date/save/', {
            'parsed_data_id': self.parsed_data.id,
            'clinical_date': '2023-05-20',
            'document_id': self.document.id
        })
        self.assertEqual(response.status_code, 200)
        
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.clinical_date, date(2023, 5, 20))
        self.assertEqual(self.parsed_data.date_status, 'pending')  # Reset to pending
    
    def test_save_clinical_date_requires_post(self):
        """Test that GET requests are not allowed."""
        response = self.client.get('/documents/clinical-date/save/')
        # Should be 405 Method Not Allowed or redirect
        self.assertNotEqual(response.status_code, 200)
    
    def test_verify_clinical_date_requires_post(self):
        """Test that GET requests are not allowed for verification."""
        response = self.client.get('/documents/clinical-date/verify/')
        # Should be 405 Method Not Allowed
        self.assertEqual(response.status_code, 405)

