"""
Tests for FHIR merge operation API endpoints.
"""

import json
import uuid
from unittest.mock import patch, Mock
from django.test import TestCase, Client
from django.contrib.auth.models import User, Permission
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from apps.patients.models import Patient
from apps.documents.models import Document
from .models import FHIRMergeConfiguration, FHIRMergeOperation
from .configuration import MergeConfigurationService


class FHIRMergeAPITestCase(TestCase):
    """Test case for FHIR merge operation API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        
        # Create test users
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.superuser = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpass123'
        )
        
        # Add permissions
        self.user.user_permissions.add(
            Permission.objects.get(codename='add_fhirmergeoperation'),
            Permission.objects.get(codename='change_fhirmergeoperation'),
            Permission.objects.get(codename='view_patient'),
        )
        
        # Create test patient
        self.patient = Patient.objects.create(
            first_name='Test',
            last_name='Patient',
            date_of_birth='1990-01-01',
            mrn='TEST001',
            created_by=self.user
        )
        
        # Create test document
        self.document = Document.objects.create(
            patient=self.patient,
            file_name='test_document.pdf',
            uploaded_by=self.user,
            status='completed'
        )
        
        # Create default configuration
        self.config = MergeConfigurationService.create_default_configurations()[0]
    
    def test_trigger_merge_operation_success(self):
        """Test successful merge operation trigger."""
        self.client.login(username='testuser', password='testpass123')
        
        data = {
            'patient_id': self.patient.id,
            'document_id': self.document.id,
            'operation_type': 'single_document',
            'async': False  # Synchronous for testing
        }
        
        with patch('apps.fhir.merge_api_views._execute_merge_operation_sync') as mock_execute:
            mock_execute.return_value = {
                'success': True,
                'message': 'Merge completed successfully',
                'merge_result': {'resources_added': 1}
            }
            
            response = self.client.post(
                reverse('fhir:api_trigger_merge_operation'),
                data=json.dumps(data),
                content_type='application/json'
            )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        
        self.assertEqual(response_data['status'], 'success')
        self.assertIn('operation_id', response_data)
        
        # Verify operation was created
        operation = FHIRMergeOperation.objects.get(id=response_data['operation_id'])
        self.assertEqual(operation.patient, self.patient)
        self.assertEqual(operation.document, self.document)
        self.assertEqual(operation.status, 'completed')
    
    def test_trigger_merge_operation_missing_patient_id(self):
        """Test merge operation trigger with missing patient_id."""
        self.client.login(username='testuser', password='testpass123')
        
        data = {
            'document_id': self.document.id,
            'operation_type': 'single_document'
        }
        
        response = self.client.post(
            reverse('fhir:api_trigger_merge_operation'),
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'error')
        self.assertIn('patient_id is required', response_data['message'])
    
    def test_trigger_merge_operation_invalid_patient(self):
        """Test merge operation trigger with invalid patient ID."""
        self.client.login(username='testuser', password='testpass123')
        
        data = {
            'patient_id': 99999,
            'document_id': self.document.id,
            'operation_type': 'single_document'
        }
        
        response = self.client.post(
            reverse('fhir:api_trigger_merge_operation'),
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 404)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'error')
        self.assertIn('not found', response_data['message'])
    
    def test_trigger_merge_operation_permission_denied(self):
        """Test merge operation trigger without proper permissions."""
        # Create user without permissions
        user_no_perms = User.objects.create_user(
            username='noperms',
            email='noperms@example.com',
            password='testpass123'
        )
        
        self.client.login(username='noperms', password='testpass123')
        
        data = {
            'patient_id': self.patient.id,
            'document_id': self.document.id,
            'operation_type': 'single_document'
        }
        
        response = self.client.post(
            reverse('fhir:api_trigger_merge_operation'),
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 403)
    
    def test_trigger_merge_operation_batch(self):
        """Test batch merge operation trigger."""
        self.client.login(username='testuser', password='testpass123')
        
        # Create additional documents
        doc2 = Document.objects.create(
            patient=self.patient,
            file_name='test_document2.pdf',
            uploaded_by=self.user,
            status='completed'
        )
        
        data = {
            'patient_id': self.patient.id,
            'document_ids': [self.document.id, doc2.id],
            'operation_type': 'batch_documents',
            'async': False
        }
        
        with patch('apps.fhir.merge_api_views._execute_merge_operation_sync') as mock_execute:
            mock_execute.return_value = {
                'success': True,
                'message': 'Batch merge completed successfully',
                'merge_result': {'resources_added': 2}
            }
            
            response = self.client.post(
                reverse('fhir:api_trigger_merge_operation'),
                data=json.dumps(data),
                content_type='application/json'
            )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'success')
    
    def test_trigger_merge_operation_async(self):
        """Test asynchronous merge operation trigger."""
        self.client.login(username='testuser', password='testpass123')
        
        data = {
            'patient_id': self.patient.id,
            'document_id': self.document.id,
            'operation_type': 'single_document',
            'async': True
        }
        
        response = self.client.post(
            reverse('fhir:api_trigger_merge_operation'),
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 202)
        response_data = json.loads(response.content)
        
        self.assertEqual(response_data['status'], 'success')
        self.assertIn('queued successfully', response_data['message'])
        
        # Verify operation was created with queued status
        operation = FHIRMergeOperation.objects.get(id=response_data['operation_id'])
        self.assertEqual(operation.status, 'queued')
    
    def test_get_merge_operation_status(self):
        """Test getting merge operation status."""
        self.client.login(username='testuser', password='testpass123')
        
        # Create test operation
        operation = FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            document=self.document,
            operation_type='single_document',
            status='processing',
            progress_percentage=50,
            current_step='Merging data',
            created_by=self.user
        )
        
        response = self.client.get(
            reverse('fhir:api_get_merge_operation_status', args=[operation.id])
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        
        self.assertEqual(response_data['status'], 'success')
        self.assertEqual(response_data['data']['status'], 'processing')
        self.assertEqual(response_data['data']['progress_percentage'], 50)
        self.assertEqual(response_data['data']['current_step'], 'Merging data')
    
    def test_get_merge_operation_result(self):
        """Test getting merge operation result."""
        self.client.login(username='testuser', password='testpass123')
        
        # Create completed operation
        operation = FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            document=self.document,
            operation_type='single_document',
            status='completed',
            progress_percentage=100,
            merge_result={'resources_added': 3, 'conflicts_resolved': 1},
            created_by=self.user
        )
        
        response = self.client.get(
            reverse('fhir:api_get_merge_operation_result', args=[operation.id])
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        
        self.assertEqual(response_data['status'], 'success')
        self.assertEqual(response_data['data']['operation']['status'], 'completed')
        self.assertEqual(response_data['data']['merge_result']['resources_added'], 3)
        self.assertEqual(response_data['data']['merge_result']['conflicts_resolved'], 1)
    
    def test_get_merge_operation_result_not_completed(self):
        """Test getting result of incomplete operation."""
        self.client.login(username='testuser', password='testpass123')
        
        # Create pending operation
        operation = FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            document=self.document,
            operation_type='single_document',
            status='pending',
            created_by=self.user
        )
        
        response = self.client.get(
            reverse('fhir:api_get_merge_operation_result', args=[operation.id])
        )
        
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'error')
        self.assertIn('not yet completed', response_data['message'])
    
    def test_list_merge_operations(self):
        """Test listing merge operations."""
        self.client.login(username='testuser', password='testpass123')
        
        # Create test operations
        operation1 = FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            operation_type='single_document',
            status='completed',
            created_by=self.user
        )
        
        operation2 = FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            operation_type='batch_documents',
            status='pending',
            created_by=self.user
        )
        
        response = self.client.get(reverse('fhir:api_list_merge_operations'))
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        
        self.assertEqual(response_data['status'], 'success')
        self.assertEqual(len(response_data['data']), 2)
        self.assertIn('pagination', response_data)
    
    def test_list_merge_operations_filtered(self):
        """Test listing merge operations with filters."""
        self.client.login(username='testuser', password='testpass123')
        
        # Create test operations
        FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            operation_type='single_document',
            status='completed',
            created_by=self.user
        )
        
        FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            operation_type='single_document',
            status='pending',
            created_by=self.user
        )
        
        # Filter by status
        response = self.client.get(
            reverse('fhir:api_list_merge_operations') + '?status=completed'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        
        self.assertEqual(response_data['status'], 'success')
        self.assertEqual(len(response_data['data']), 1)
        self.assertEqual(response_data['data'][0]['status'], 'completed')
        
        # Filter by patient
        response = self.client.get(
            reverse('fhir:api_list_merge_operations') + f'?patient_id={self.patient.id}'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertEqual(len(response_data['data']), 2)
    
    def test_cancel_merge_operation(self):
        """Test cancelling a merge operation."""
        self.client.login(username='testuser', password='testpass123')
        
        # Create queued operation
        operation = FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            operation_type='single_document',
            status='queued',
            created_by=self.user
        )
        
        response = self.client.post(
            reverse('fhir:api_cancel_merge_operation', args=[operation.id])
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        
        self.assertEqual(response_data['status'], 'success')
        self.assertIn('cancelled successfully', response_data['message'])
        
        # Verify operation was cancelled
        operation.refresh_from_db()
        self.assertEqual(operation.status, 'cancelled')
        self.assertIsNotNone(operation.completed_at)
    
    def test_cancel_merge_operation_invalid_status(self):
        """Test cancelling operation in invalid status."""
        self.client.login(username='testuser', password='testpass123')
        
        # Create completed operation
        operation = FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            operation_type='single_document',
            status='completed',
            created_by=self.user
        )
        
        response = self.client.post(
            reverse('fhir:api_cancel_merge_operation', args=[operation.id])
        )
        
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'error')
        self.assertIn('Cannot cancel', response_data['message'])
    
    def test_rate_limiting(self):
        """Test rate limiting functionality."""
        self.client.login(username='testuser', password='testpass123')
        
        # Create many recent operations to trigger rate limit
        for i in range(15):  # Exceeds default limit of 10
            FHIRMergeOperation.objects.create(
                patient=self.patient,
                configuration=self.config,
                operation_type='single_document',
                status='completed',
                created_by=self.user,
                created_at=timezone.now() - timedelta(minutes=30)
            )
        
        data = {
            'patient_id': self.patient.id,
            'document_id': self.document.id,
            'operation_type': 'single_document'
        }
        
        response = self.client.post(
            reverse('fhir:api_trigger_merge_operation'),
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 429)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'error')
        self.assertIn('Rate limit exceeded', response_data['message'])
    
    def test_webhook_notification(self):
        """Test webhook notification functionality."""
        self.client.login(username='testuser', password='testpass123')
        
        webhook_url = 'https://example.com/webhook'
        
        data = {
            'patient_id': self.patient.id,
            'document_id': self.document.id,
            'operation_type': 'single_document',
            'webhook_url': webhook_url,
            'async': False
        }
        
        with patch('apps.fhir.merge_api_views._execute_merge_operation_sync') as mock_execute, \
             patch('apps.fhir.merge_api_views.requests.post') as mock_post:
            
            mock_execute.return_value = {
                'success': True,
                'message': 'Merge completed successfully',
                'merge_result': {'resources_added': 1}
            }
            mock_post.return_value.status_code = 200
            
            response = self.client.post(
                reverse('fhir:api_trigger_merge_operation'),
                data=json.dumps(data),
                content_type='application/json'
            )
        
        self.assertEqual(response.status_code, 200)
        
        # Verify webhook was called
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], webhook_url)
        self.assertIn('operation_id', call_args[1]['json'])
        self.assertIn('status', call_args[1]['json'])
    
    def test_authentication_required(self):
        """Test that authentication is required for all endpoints."""
        data = {
            'patient_id': self.patient.id,
            'document_id': self.document.id,
            'operation_type': 'single_document'
        }
        
        # Test without authentication
        response = self.client.post(
            reverse('fhir:api_trigger_merge_operation'),
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_invalid_json_request(self):
        """Test handling of invalid JSON requests."""
        self.client.login(username='testuser', password='testpass123')
        
        response = self.client.post(
            reverse('fhir:api_trigger_merge_operation'),
            data='invalid json',
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'error')
        self.assertIn('Invalid JSON', response_data['message'])
    
    def test_pagination(self):
        """Test pagination in list operations."""
        self.client.login(username='testuser', password='testpass123')
        
        # Create 25 operations
        for i in range(25):
            FHIRMergeOperation.objects.create(
                patient=self.patient,
                configuration=self.config,
                operation_type='single_document',
                status='completed',
                created_by=self.user
            )
        
        # Test first page
        response = self.client.get(
            reverse('fhir:api_list_merge_operations') + '?page=1&page_size=10'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        
        self.assertEqual(len(response_data['data']), 10)
        self.assertEqual(response_data['pagination']['current_page'], 1)
        self.assertEqual(response_data['pagination']['total_pages'], 3)
        self.assertTrue(response_data['pagination']['has_next'])
        self.assertFalse(response_data['pagination']['has_previous'])
        
        # Test second page
        response = self.client.get(
            reverse('fhir:api_list_merge_operations') + '?page=2&page_size=10'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        
        self.assertEqual(len(response_data['data']), 10)
        self.assertEqual(response_data['pagination']['current_page'], 2)
        self.assertTrue(response_data['pagination']['has_next'])
        self.assertTrue(response_data['pagination']['has_previous'])


class FHIRMergeOperationModelTestCase(TestCase):
    """Test case for FHIRMergeOperation model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='Test',
            last_name='Patient',
            date_of_birth='1990-01-01',
            mrn='TEST001',
            created_by=self.user
        )
        
        self.config = MergeConfigurationService.create_default_configurations()[0]
    
    def test_operation_creation(self):
        """Test creating a merge operation."""
        operation = FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            operation_type='single_document',
            created_by=self.user
        )
        
        self.assertIsNotNone(operation.id)
        self.assertEqual(operation.status, 'pending')
        self.assertEqual(operation.progress_percentage, 0)
        self.assertFalse(operation.is_completed)
        self.assertFalse(operation.is_successful)
    
    def test_update_progress(self):
        """Test updating operation progress."""
        operation = FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            operation_type='single_document',
            created_by=self.user
        )
        
        operation.update_progress(50, "Processing data")
        
        self.assertEqual(operation.progress_percentage, 50)
        self.assertEqual(operation.current_step, "Processing data")
    
    def test_mark_started(self):
        """Test marking operation as started."""
        operation = FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            operation_type='single_document',
            created_by=self.user
        )
        
        operation.mark_started()
        
        self.assertEqual(operation.status, 'processing')
        self.assertIsNotNone(operation.started_at)
    
    def test_mark_completed_success(self):
        """Test marking operation as completed successfully."""
        operation = FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            operation_type='single_document',
            created_by=self.user
        )
        
        operation.mark_started()
        merge_result = {'resources_added': 3, 'conflicts_resolved': 1}
        operation.mark_completed(merge_result=merge_result)
        
        self.assertEqual(operation.status, 'completed')
        self.assertEqual(operation.progress_percentage, 100)
        self.assertEqual(operation.merge_result, merge_result)
        self.assertIsNotNone(operation.completed_at)
        self.assertIsNotNone(operation.processing_time_seconds)
        self.assertTrue(operation.is_completed)
        self.assertTrue(operation.is_successful)
    
    def test_mark_completed_failure(self):
        """Test marking operation as failed."""
        operation = FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            operation_type='single_document',
            created_by=self.user
        )
        
        operation.mark_started()
        error_details = {'error': 'Something went wrong', 'type': 'ValueError'}
        operation.mark_completed(error_details=error_details)
        
        self.assertEqual(operation.status, 'failed')
        self.assertEqual(operation.progress_percentage, 100)
        self.assertEqual(operation.error_details, error_details)
        self.assertIsNotNone(operation.completed_at)
        self.assertTrue(operation.is_completed)
        self.assertFalse(operation.is_successful)
    
    def test_get_summary(self):
        """Test getting operation summary."""
        operation = FHIRMergeOperation.objects.create(
            patient=self.patient,
            configuration=self.config,
            operation_type='single_document',
            status='processing',
            progress_percentage=75,
            current_step='Resolving conflicts',
            created_by=self.user
        )
        
        summary = operation.get_summary()
        
        self.assertEqual(summary['patient_id'], self.patient.id)
        self.assertEqual(summary['operation_type'], 'single_document')
        self.assertEqual(summary['status'], 'processing')
        self.assertEqual(summary['progress_percentage'], 75)
        self.assertEqual(summary['current_step'], 'Resolving conflicts')
        self.assertFalse(summary['is_completed'])
        self.assertFalse(summary['is_successful'])
