"""
Tests for HIPAA-compliant audit logging in optimistic concurrency workflow.

Task 41.28: Comprehensive test coverage for audit logging functions.
Tests verify that all review decisions, merge operations, and manual reviews
are properly logged without exposing PHI.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal

from apps.patients.models import Patient
from apps.documents.models import (
    Document, 
    ParsedData,
    audit_extraction_decision,
    audit_merge_operation,
    audit_manual_review
)
from apps.core.models import AuditLog


class AuditExtractionDecisionTestCase(TestCase):
    """Test audit_extraction_decision() function."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            mrn='TEST-001',
            date_of_birth='1980-01-01'
        )
        
        self.document = Document.objects.create(
            patient=self.patient,
            filename='test.pdf',
            uploaded_by=self.user,
            status='processing'
        )
        
        self.factory = RequestFactory()
    
    def test_audit_auto_approved_extraction(self):
        """Test audit logging for auto-approved extraction."""
        # Create ParsedData with auto-approved status
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.95,
            review_status='auto_approved',
            auto_approved=True,
            flag_reason=''
        )
        
        # Create audit log
        audit_log = audit_extraction_decision(parsed_data, request=None)
        
        # Verify audit log was created
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.event_type, 'extraction_auto_approved')
        self.assertEqual(audit_log.category, 'document_processing')
        self.assertEqual(audit_log.severity, 'info')
        self.assertEqual(audit_log.username, 'system')
        self.assertFalse(audit_log.phi_involved)
        self.assertTrue(audit_log.success)
        
        # Verify audit details contain safe data
        details = audit_log.details
        self.assertEqual(details['document_id'], self.document.id)
        self.assertEqual(details['patient_mrn'], 'TEST-001')
        self.assertEqual(details['review_status'], 'auto_approved')
        self.assertTrue(details['auto_approved'])
        self.assertEqual(details['extraction_confidence'], 0.95)
        self.assertEqual(details['resource_count'], 1)
        self.assertEqual(details['ai_model'], 'claude-3-sonnet')
        
        # Verify NO PHI in audit log
        self.assertNotIn('John', str(details))
        self.assertNotIn('Doe', str(details))
        self.assertNotIn('1980-01-01', str(details))
    
    def test_audit_flagged_extraction(self):
        """Test audit logging for flagged extraction."""
        # Create ParsedData with flagged status
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],
            ai_model_used='gpt-3.5-turbo',  # Fallback model
            extraction_confidence=0.65,
            review_status='flagged',
            auto_approved=False,
            flag_reason='Low extraction confidence (0.65 < 0.80 threshold)'
        )
        
        # Create audit log
        audit_log = audit_extraction_decision(parsed_data, request=None)
        
        # Verify audit log was created
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.event_type, 'extraction_flagged')
        self.assertEqual(audit_log.severity, 'warning')
        self.assertFalse(audit_log.phi_involved)
        
        # Verify flag reason is logged
        details = audit_log.details
        self.assertEqual(details['flag_reason'], 'Low extraction confidence (0.65 < 0.80 threshold)')
        self.assertFalse(details['auto_approved'])
        self.assertEqual(details['resource_count'], 0)
        
        # Verify NO PHI in flag reason
        self.assertNotIn('John', details['flag_reason'])
        self.assertNotIn('Doe', details['flag_reason'])
    
    def test_audit_with_request_context(self):
        """Test audit logging with HTTP request context."""
        # Create ParsedData
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Observation'}],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            review_status='auto_approved',
            auto_approved=True
        )
        
        # Create mock request
        request = self.factory.get('/test/')
        request.user = self.user
        
        # Create audit log with request
        audit_log = audit_extraction_decision(parsed_data, request=request)
        
        # Verify user context is captured
        self.assertEqual(audit_log.username, 'testuser')
        self.assertEqual(audit_log.user_email, 'test@example.com')
        self.assertIsNotNone(audit_log.ip_address)
    
    def test_audit_pending_status_not_logged(self):
        """Test that pending status doesn't create audit log."""
        # Create ParsedData with pending status
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],
            review_status='pending'
        )
        
        # Try to create audit log
        audit_log = audit_extraction_decision(parsed_data, request=None)
        
        # Should return None for pending status
        self.assertIsNone(audit_log)
    
    def test_audit_logging_failure_doesnt_break_workflow(self):
        """Test that audit logging failures don't break the workflow."""
        # Create ParsedData
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],
            review_status='auto_approved',
            auto_approved=True
        )
        
        # Simulate audit logging failure by passing invalid data
        # Mock the AuditLog.objects.create to raise an exception
        from unittest.mock import patch
        
        with patch('apps.core.models.AuditLog.objects.create', side_effect=Exception('Database error')):
            # This should not raise an exception - should catch and return None
            audit_log = audit_extraction_decision(parsed_data, request=None)
            
            # Should return None on failure but not crash
            self.assertIsNone(audit_log)


class AuditMergeOperationTestCase(TestCase):
    """Test audit_merge_operation() function."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='Jane',
            last_name='Smith',
            mrn='TEST-002',
            date_of_birth='1990-05-15'
        )
        
        self.document = Document.objects.create(
            patient=self.patient,
            filename='test.pdf',
            uploaded_by=self.user,
            status='processing'
        )
    
    def test_audit_successful_merge(self):
        """Test audit logging for successful FHIR merge."""
        # Create ParsedData
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {'resourceType': 'Condition'},
                {'resourceType': 'Observation'},
                {'resourceType': 'MedicationStatement'}
            ],
            review_status='auto_approved',
            auto_approved=True
        )
        
        # Create audit log for successful merge
        audit_log = audit_merge_operation(
            parsed_data,
            merge_success=True,
            resource_count=3,
            request=None
        )
        
        # Verify audit log was created
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.event_type, 'fhir_import')
        self.assertEqual(audit_log.category, 'data_modification')
        self.assertEqual(audit_log.severity, 'info')
        self.assertTrue(audit_log.success)
        self.assertFalse(audit_log.phi_involved)
        
        # Verify audit details
        details = audit_log.details
        self.assertEqual(details['document_id'], self.document.id)
        self.assertEqual(details['patient_mrn'], 'TEST-002')
        self.assertEqual(details['resource_count'], 3)
        self.assertTrue(details['merge_success'])
        self.assertTrue(details['auto_approved'])
        
        # Verify description
        self.assertIn('succeeded', audit_log.description)
        self.assertIn('3 resources', audit_log.description)
    
    def test_audit_failed_merge(self):
        """Test audit logging for failed FHIR merge."""
        # Create ParsedData
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],
            review_status='flagged',
            auto_approved=False
        )
        
        # Create audit log for failed merge
        audit_log = audit_merge_operation(
            parsed_data,
            merge_success=False,
            resource_count=0,
            request=None
        )
        
        # Verify audit log reflects failure
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.severity, 'error')
        self.assertFalse(audit_log.success)
        self.assertIn('failed', audit_log.description)
    
    def test_audit_merge_no_phi_exposure(self):
        """Test that merge audit logs don't expose PHI."""
        # Create ParsedData with clinical data
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={
                'conditions': ['Type 2 Diabetes', 'Hypertension'],
                'medications': ['Metformin', 'Lisinopril']
            },
            fhir_delta_json=[
                {
                    'resourceType': 'Condition',
                    'code': {
                        'coding': [{'code': 'E11.9', 'display': 'Type 2 diabetes'}]
                    }
                }
            ],
            review_status='auto_approved',
            auto_approved=True
        )
        
        # Create audit log
        audit_log = audit_merge_operation(
            parsed_data,
            merge_success=True,
            resource_count=1,
            request=None
        )
        
        # Verify NO clinical data in audit log
        details_str = str(audit_log.details)
        self.assertNotIn('Diabetes', details_str)
        self.assertNotIn('Hypertension', details_str)
        self.assertNotIn('Metformin', details_str)
        self.assertNotIn('E11.9', details_str)
        self.assertNotIn('Jane', details_str)
        self.assertNotIn('Smith', details_str)


class AuditManualReviewTestCase(TestCase):
    """Test audit_manual_review() function."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='reviewer',
            email='reviewer@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='Bob',
            last_name='Johnson',
            mrn='TEST-003',
            date_of_birth='1975-12-20'
        )
        
        self.document = Document.objects.create(
            patient=self.patient,
            filename='test.pdf',
            uploaded_by=self.user,
            status='review'
        )
        
        self.factory = RequestFactory()
    
    def test_audit_manual_approval(self):
        """Test audit logging for manual approval."""
        # Create flagged ParsedData
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}],
            review_status='flagged',
            auto_approved=False,
            flag_reason='Low confidence'
        )
        
        # Create mock request
        request = self.factory.post('/review/')
        request.user = self.user
        
        # Create audit log for manual approval
        audit_log = audit_manual_review(
            parsed_data,
            action='approved',
            user=self.user,
            notes='Verified data is correct',
            request=request
        )
        
        # Verify audit log was created
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.event_type, 'phi_update')
        self.assertEqual(audit_log.category, 'data_modification')
        self.assertTrue(audit_log.phi_involved)  # Review affects PHI
        self.assertTrue(audit_log.success)
        
        # Verify audit details
        details = audit_log.details
        self.assertEqual(details['document_id'], self.document.id)
        self.assertEqual(details['patient_mrn'], 'TEST-003')
        self.assertEqual(details['review_action'], 'approved')
        self.assertEqual(details['previous_status'], 'flagged')
        self.assertEqual(details['new_status'], 'reviewed')
        self.assertEqual(details['reviewer_username'], 'reviewer')
        self.assertTrue(details['has_notes'])
        
        # Verify reviewer identity is captured
        self.assertEqual(audit_log.username, 'reviewer')
        self.assertEqual(audit_log.user_email, 'reviewer@example.com')
        
        # Verify NO PHI in audit log (notes content not logged)
        self.assertNotIn('Verified data is correct', str(details))
        self.assertNotIn('Bob', str(details))
        self.assertNotIn('Johnson', str(details))
    
    def test_audit_manual_rejection(self):
        """Test audit logging for manual rejection."""
        # Create flagged ParsedData
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],
            review_status='flagged',
            auto_approved=False
        )
        
        # Create audit log for rejection
        audit_log = audit_manual_review(
            parsed_data,
            action='rejected',
            user=self.user,
            notes='Extraction quality too low',
            request=None
        )
        
        # Verify audit log reflects rejection
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.event_type, 'phi_update')
        self.assertTrue(audit_log.phi_involved)
        
        details = audit_log.details
        self.assertEqual(details['review_action'], 'rejected')
        self.assertEqual(details['new_status'], 'rejected')
        self.assertTrue(details['has_notes'])
    
    def test_audit_review_without_notes(self):
        """Test audit logging for review without notes."""
        # Create ParsedData
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],
            review_status='flagged'
        )
        
        # Create audit log without notes
        audit_log = audit_manual_review(
            parsed_data,
            action='approved',
            user=self.user,
            notes='',
            request=None
        )
        
        # Verify has_notes is False
        details = audit_log.details
        self.assertFalse(details['has_notes'])


class AuditIntegrationTestCase(TestCase):
    """Integration tests for audit logging in full workflow."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='integrationuser',
            email='integration@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='Alice',
            last_name='Williams',
            mrn='TEST-004',
            date_of_birth='1985-03-10'
        )
        
        self.document = Document.objects.create(
            patient=self.patient,
            filename='integration_test.pdf',
            uploaded_by=self.user,
            status='processing'
        )
        
        self.factory = RequestFactory()
    
    def test_complete_optimistic_workflow_audit_trail(self):
        """Test complete audit trail for optimistic concurrency workflow."""
        # Create ParsedData with auto-approval
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {'resourceType': 'Condition'},
                {'resourceType': 'Observation'}
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.95,
            review_status='auto_approved',
            auto_approved=True
        )
        
        # Step 1: Log extraction decision
        decision_log = audit_extraction_decision(parsed_data, request=None)
        
        # Step 2: Log merge operation
        merge_log = audit_merge_operation(
            parsed_data,
            merge_success=True,
            resource_count=2,
            request=None
        )
        
        # Verify both logs were created
        self.assertIsNotNone(decision_log)
        self.assertIsNotNone(merge_log)
        
        # Verify audit trail is complete
        audit_logs = AuditLog.objects.filter(
            patient_mrn='TEST-004'
        ).order_by('timestamp')
        
        self.assertEqual(audit_logs.count(), 2)
        self.assertEqual(audit_logs[0].event_type, 'extraction_auto_approved')
        self.assertEqual(audit_logs[1].event_type, 'fhir_import')
    
    def test_flagged_workflow_with_manual_review_audit_trail(self):
        """Test audit trail for flagged extraction with manual review."""
        # Create ParsedData with flagged status
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],
            ai_model_used='gpt-3.5-turbo',
            extraction_confidence=0.60,
            review_status='flagged',
            auto_approved=False,
            flag_reason='Low confidence'
        )
        
        # Step 1: Log extraction decision (flagged)
        decision_log = audit_extraction_decision(parsed_data, request=None)
        
        # Step 2: Log merge operation (still happens in optimistic system)
        merge_log = audit_merge_operation(
            parsed_data,
            merge_success=True,
            resource_count=0,
            request=None
        )
        
        # Step 3: Manual review and approval
        request = self.factory.post('/review/')
        request.user = self.user
        
        review_log = audit_manual_review(
            parsed_data,
            action='approved',
            user=self.user,
            notes='Manually verified',
            request=request
        )
        
        # Verify complete audit trail
        audit_logs = AuditLog.objects.filter(
            patient_mrn='TEST-004'
        ).order_by('timestamp')
        
        self.assertEqual(audit_logs.count(), 3)
        self.assertEqual(audit_logs[0].event_type, 'extraction_flagged')
        self.assertEqual(audit_logs[1].event_type, 'fhir_import')
        self.assertEqual(audit_logs[2].event_type, 'phi_update')
        
        # Verify reviewer identity in final log
        self.assertEqual(audit_logs[2].username, 'integrationuser')
    
    def test_audit_performance_under_50ms(self):
        """Test that audit logging completes quickly."""
        import time
        
        # Create ParsedData
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}],
            review_status='auto_approved',
            auto_approved=True
        )
        
        # Measure audit logging time
        start_time = time.time()
        audit_extraction_decision(parsed_data, request=None)
        end_time = time.time()
        
        duration_ms = (end_time - start_time) * 1000
        
        # Should complete in under 50ms
        self.assertLess(duration_ms, 50, 
                       f"Audit logging took {duration_ms:.2f}ms, exceeds 50ms target")

