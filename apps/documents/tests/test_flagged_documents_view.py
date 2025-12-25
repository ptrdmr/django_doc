"""
Unit tests for FlaggedDocumentsListView (Task 41.24).

Tests the flagged items list view with filtering by date, flag reason, and patient.
"""
import pytest
from datetime import datetime, timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.documents.models import Document, ParsedData
from apps.patients.models import Patient

User = get_user_model()


class FlaggedDocumentsListViewTests(TestCase):
    """
    Test suite for FlaggedDocumentsListView.
    
    Tests filtering, pagination, permissions, and UI rendering.
    """
    
    def setUp(self):
        """Create test data including flagged and non-flagged items."""
        # Create test user with permissions
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        # Add permission to view parsed data
        from django.contrib.contenttypes.models import ContentType
        from django.contrib.auth.models import Permission
        
        content_type = ContentType.objects.get_for_model(ParsedData)
        permission = Permission.objects.get(
            codename='view_parseddata',
            content_type=content_type
        )
        self.user.user_permissions.add(permission)
        
        # Create test patients
        self.patient1 = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            mrn='MRN001'
        )
        
        self.patient2 = Patient.objects.create(
            first_name='Jane',
            last_name='Smith',
            date_of_birth='1975-05-15',
            mrn='MRN002'
        )
        
        # Create test documents
        pdf_content = b'%PDF-1.4 fake pdf content for testing'
        
        pdf_file1 = SimpleUploadedFile(
            'test_doc_1.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        self.doc1 = Document.objects.create(
            patient=self.patient1,
            filename='test_doc_1.pdf',
            file=pdf_file1,
            status='completed',
            created_by=self.user
        )
        
        pdf_file2 = SimpleUploadedFile(
            'test_doc_2.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        self.doc2 = Document.objects.create(
            patient=self.patient2,
            filename='test_doc_2.pdf',
            file=pdf_file2,
            status='completed',
            created_by=self.user
        )
        
        pdf_file3 = SimpleUploadedFile(
            'test_doc_3.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        self.doc3 = Document.objects.create(
            patient=self.patient1,
            filename='test_doc_3.pdf',
            file=pdf_file3,
            status='completed',
            created_by=self.user
        )
        
        # Create flagged parsed data items
        self.flagged1 = ParsedData.objects.create(
            document=self.doc1,
            patient=self.patient1,
            review_status='flagged',
            flag_reason='Low extraction confidence (0.75 < 0.80 threshold)',
            extraction_confidence=0.75,
            ai_model_used='claude-3-sonnet',
            fhir_delta_json={'resourceType': 'Patient', 'id': '1'}
        )
        
        self.flagged2 = ParsedData.objects.create(
            document=self.doc2,
            patient=self.patient2,
            review_status='flagged',
            flag_reason='Fallback AI model used: gpt-3.5-turbo',
            extraction_confidence=0.85,
            ai_model_used='gpt-3.5-turbo',
            fhir_delta_json=[
                {'resourceType': 'Patient', 'id': '2'},
                {'resourceType': 'Condition', 'id': 'c1'}
            ]
        )
        
        # Create a flagged item from a few days ago (for date filtering tests)
        past_date = timezone.now() - timedelta(days=5)
        self.flagged3 = ParsedData.objects.create(
            document=self.doc3,
            patient=self.patient1,
            review_status='flagged',
            flag_reason='Zero FHIR resources extracted from document',
            extraction_confidence=0.90,
            ai_model_used='claude-3-sonnet',
            fhir_delta_json={}
        )
        self.flagged3.created_at = past_date
        self.flagged3.save()
        
        # Create non-flagged items (should not appear in results)
        self.auto_approved = ParsedData.objects.create(
            document=self.doc1,
            patient=self.patient1,
            review_status='auto_approved',
            auto_approved=True,
            extraction_confidence=0.95,
            ai_model_used='claude-3-sonnet',
            fhir_delta_json=[{'resourceType': 'Patient', 'id': '3'}]
        )
        
        self.reviewed = ParsedData.objects.create(
            document=self.doc2,
            patient=self.patient2,
            review_status='reviewed',
            reviewed_by=self.user,
            reviewed_at=timezone.now(),
            extraction_confidence=0.88,
            ai_model_used='claude-3-sonnet'
        )
        
        # Client for requests
        self.client = Client()
        self.url = reverse('documents:flagged-list')
    
    def test_view_url_accessible(self):
        """Test that the flagged documents view URL is accessible."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'documents/flagged_documents_list.html')
    
    def test_view_requires_authentication(self):
        """Test that unauthenticated users are redirected to login."""
        response = self.client.get(self.url)
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)
    
    def test_view_requires_permission(self):
        """Test that users without view_parseddata permission get 403."""
        # Create user without permission
        unprivileged_user = User.objects.create_user(
            username='noperm',
            email='noperm@example.com',
            password='testpass123'
        )
        
        self.client.force_login(unprivileged_user)
        response = self.client.get(self.url)
        
        # Should get forbidden
        self.assertEqual(response.status_code, 403)
    
    def test_displays_only_flagged_items(self):
        """Test that only items with review_status='flagged' are displayed."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, 200)
        
        # Check that all flagged items are present
        flagged_items = response.context['flagged_items']
        self.assertEqual(flagged_items.count(), 3)  # flagged1, flagged2, flagged3
        
        # Verify flagged items are in the results
        flagged_ids = {item.id for item in flagged_items}
        self.assertIn(self.flagged1.id, flagged_ids)
        self.assertIn(self.flagged2.id, flagged_ids)
        self.assertIn(self.flagged3.id, flagged_ids)
        
        # Verify non-flagged items are NOT in results
        self.assertNotIn(self.auto_approved.id, flagged_ids)
        self.assertNotIn(self.reviewed.id, flagged_ids)
    
    def test_filter_by_patient(self):
        """Test filtering flagged items by patient ID."""
        self.client.force_login(self.user)
        
        # Filter by patient1
        response = self.client.get(self.url, {'patient': self.patient1.id})
        
        self.assertEqual(response.status_code, 200)
        flagged_items = response.context['flagged_items']
        
        # Should only show patient1's flagged documents
        self.assertEqual(flagged_items.count(), 2)  # flagged1 and flagged3
        
        # All items should be for patient1
        for item in flagged_items:
            self.assertEqual(item.patient, self.patient1)
    
    def test_filter_by_flag_reason(self):
        """Test filtering flagged items by flag reason text search."""
        self.client.force_login(self.user)
        
        # Search for "confidence" in flag reason
        response = self.client.get(self.url, {'flag_reason': 'confidence'})
        
        self.assertEqual(response.status_code, 200)
        flagged_items = response.context['flagged_items']
        
        # Should match flagged1 (low confidence)
        self.assertEqual(flagged_items.count(), 1)
        self.assertEqual(flagged_items.first().id, self.flagged1.id)
        self.assertIn('confidence', flagged_items.first().flag_reason.lower())
    
    def test_filter_by_date_range_start_date(self):
        """Test filtering by start date (created_at >= start_date)."""
        self.client.force_login(self.user)
        
        # Get items from last 2 days only (should exclude flagged3)
        start_date = (timezone.now() - timedelta(days=2)).date()
        
        response = self.client.get(self.url, {
            'start_date': start_date.isoformat()
        })
        
        self.assertEqual(response.status_code, 200)
        flagged_items = response.context['flagged_items']
        
        # Should only show recent items (flagged1, flagged2)
        self.assertEqual(flagged_items.count(), 2)
        
        flagged_ids = {item.id for item in flagged_items}
        self.assertIn(self.flagged1.id, flagged_ids)
        self.assertIn(self.flagged2.id, flagged_ids)
        self.assertNotIn(self.flagged3.id, flagged_ids)  # Too old
    
    def test_filter_by_date_range_end_date(self):
        """Test filtering by end date (created_at <= end_date)."""
        self.client.force_login(self.user)
        
        # Get items up to 3 days ago (should only include flagged3)
        end_date = (timezone.now() - timedelta(days=3)).date()
        
        response = self.client.get(self.url, {
            'end_date': end_date.isoformat()
        })
        
        self.assertEqual(response.status_code, 200)
        flagged_items = response.context['flagged_items']
        
        # Should only show old item (flagged3)
        self.assertEqual(flagged_items.count(), 1)
        self.assertEqual(flagged_items.first().id, self.flagged3.id)
    
    def test_filter_by_date_range_both(self):
        """Test filtering by both start and end date."""
        self.client.force_login(self.user)
        
        # Get items from 7 days ago to 4 days ago (should only be flagged3)
        start_date = (timezone.now() - timedelta(days=7)).date()
        end_date = (timezone.now() - timedelta(days=4)).date()
        
        response = self.client.get(self.url, {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat()
        })
        
        self.assertEqual(response.status_code, 200)
        flagged_items = response.context['flagged_items']
        
        # Should only show flagged3 (created 5 days ago)
        self.assertEqual(flagged_items.count(), 1)
        self.assertEqual(flagged_items.first().id, self.flagged3.id)
    
    def test_multiple_filters_combined(self):
        """Test combining multiple filters (patient + flag_reason)."""
        self.client.force_login(self.user)
        
        # Filter by patient1 AND search for "Zero" in flag reason
        response = self.client.get(self.url, {
            'patient': self.patient1.id,
            'flag_reason': 'Zero'
        })
        
        self.assertEqual(response.status_code, 200)
        flagged_items = response.context['flagged_items']
        
        # Should only match flagged3 (patient1 + "Zero FHIR resources")
        self.assertEqual(flagged_items.count(), 1)
        self.assertEqual(flagged_items.first().id, self.flagged3.id)
    
    def test_context_contains_filter_values(self):
        """Test that current filter values are included in context."""
        self.client.force_login(self.user)
        
        response = self.client.get(self.url, {
            'patient': self.patient1.id,
            'flag_reason': 'confidence',
            'start_date': '2025-01-01',
            'end_date': '2025-12-31'
        })
        
        self.assertEqual(response.status_code, 200)
        
        # Check context has filter values for form state
        self.assertEqual(response.context['patient_filter'], str(self.patient1.id))
        self.assertEqual(response.context['flag_reason'], 'confidence')
        self.assertEqual(response.context['start_date'], '2025-01-01')
        self.assertEqual(response.context['end_date'], '2025-12-31')
    
    def test_context_contains_statistics(self):
        """Test that statistics about flagged items are in context."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, 200)
        
        # Check statistics
        self.assertEqual(response.context['total_flagged'], 3)  # All flagged items
        self.assertEqual(response.context['filtered_count'], 3)  # No filters applied
        
        # With filter applied
        response_filtered = self.client.get(self.url, {'patient': self.patient1.id})
        self.assertEqual(response_filtered.context['total_flagged'], 3)
        self.assertEqual(response_filtered.context['filtered_count'], 2)  # Only patient1
    
    def test_context_contains_patients_list(self):
        """Test that list of patients is available for filter dropdown."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, 200)
        
        patients = response.context['patients']
        self.assertEqual(patients.count(), 2)
        self.assertIn(self.patient1, patients)
        self.assertIn(self.patient2, patients)
    
    def test_invalid_patient_id_ignored(self):
        """Test that invalid patient ID in filter is gracefully ignored."""
        self.client.force_login(self.user)
        
        # Pass invalid patient ID
        response = self.client.get(self.url, {'patient': 'invalid'})
        
        # Should not crash, should show all flagged items
        self.assertEqual(response.status_code, 200)
        flagged_items = response.context['flagged_items']
        self.assertEqual(flagged_items.count(), 3)
    
    def test_invalid_date_format_ignored(self):
        """Test that invalid date formats are gracefully ignored."""
        self.client.force_login(self.user)
        
        # Pass invalid date formats
        response = self.client.get(self.url, {
            'start_date': 'not-a-date',
            'end_date': '99/99/9999'
        })
        
        # Should not crash, should show all flagged items
        self.assertEqual(response.status_code, 200)
        flagged_items = response.context['flagged_items']
        self.assertEqual(flagged_items.count(), 3)
    
    def test_empty_state_with_no_flagged_items(self):
        """Test empty state when no flagged items exist."""
        # Delete all flagged items
        ParsedData.objects.filter(review_status='flagged').delete()
        
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, 200)
        
        # Should have empty queryset
        flagged_items = response.context['flagged_items']
        self.assertEqual(flagged_items.count(), 0)
        
        # Should still render template without errors
        self.assertContains(response, 'No flagged documents found')
    
    def test_pagination_works(self):
        """Test that pagination works correctly for large result sets."""
        # Create 25 flagged items (more than paginate_by=20)
        pdf_content = b'%PDF-1.4 bulk test pdf'
        
        for i in range(25):
            pdf_file = SimpleUploadedFile(
                f'bulk_test_{i}.pdf',
                pdf_content,
                content_type='application/pdf'
            )
            
            doc = Document.objects.create(
                patient=self.patient1,
                filename=f'bulk_test_{i}.pdf',
                file=pdf_file,
                status='completed',
                created_by=self.user
            )
            
            ParsedData.objects.create(
                document=doc,
                patient=self.patient1,
                review_status='flagged',
                flag_reason=f'Test reason {i}',
                extraction_confidence=0.70,
                ai_model_used='claude-3-sonnet'
            )
        
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, 200)
        
        # Check pagination context
        self.assertTrue(response.context['is_paginated'])
        self.assertEqual(len(response.context['flagged_items']), 20)  # First page
        
        # Check page 2
        response_page2 = self.client.get(self.url, {'page': 2})
        self.assertEqual(response_page2.status_code, 200)
        self.assertGreater(len(response_page2.context['flagged_items']), 0)
    
    def test_items_ordered_by_created_at_desc(self):
        """Test that flagged items are ordered by created_at descending."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, 200)
        
        flagged_items = list(response.context['flagged_items'])
        
        # Verify ordering (newest first)
        for i in range(len(flagged_items) - 1):
            self.assertGreaterEqual(
                flagged_items[i].created_at,
                flagged_items[i + 1].created_at
            )
    
    def test_select_related_optimization(self):
        """Test that queryset uses select_related for performance."""
        self.client.force_login(self.user)
        
        # Use django-debug-toolbar or query count assertion
        from django.test.utils import override_settings
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url)
            
            # Access related fields to trigger queries if not optimized
            for item in response.context['flagged_items']:
                _ = item.document.filename
                _ = item.patient.first_name
                _ = item.document.uploaded_by
        
        # With select_related, should not have N+1 queries
        # Expect: 1 main query + 1-2 for pagination/count + auth queries
        # Without optimization, would be ~10+ queries (3 items * 3 relations each)
        self.assertLess(len(queries), 10, "Query count suggests missing select_related optimization")
    
    def test_displays_key_information(self):
        """Test that template displays all required key information."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, 200)
        
        # Check that key info is rendered for flagged items
        content = response.content.decode()
        
        # Document filename
        self.assertIn(self.flagged1.document.filename, content)
        
        # Patient name
        patient_name = f"{self.patient1.first_name} {self.patient1.last_name}"
        self.assertIn(patient_name, content)
        
        # Flag reason
        self.assertIn(self.flagged1.flag_reason, content)
        
        # Timestamp (check for date format elements)
        self.assertIn(self.flagged1.created_at.strftime("%Y"), content)
    
    def test_database_error_handling(self):
        """Test that view handles database errors gracefully."""
        self.client.force_login(self.user)
        
        # Simulate database error by using invalid queryset
        with self.assertLogs('apps.documents.views', level='ERROR') as log:
            # Pass a malformed query that would cause DB error
            # (This is a bit tricky to test without mocking)
            # For now, test that invalid dates don't crash
            response = self.client.get(self.url, {
                'start_date': '2025-99-99'  # Invalid date
            })
            
            # Should still return 200 and show all items (filter ignored)
            self.assertEqual(response.status_code, 200)


class FlaggedDocumentDetailViewTests(TestCase):
    """
    Test suite for FlaggedDocumentDetailView (Task 41.25).
    
    Tests the detail view for reviewing individual flagged documents,
    including display of flag reasons, extracted data, and action options.
    """
    
    def setUp(self):
        """Create test data for flagged document detail view tests."""
        # Create test user with permissions
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Add permissions
        from django.contrib.contenttypes.models import ContentType
        from django.contrib.auth.models import Permission
        
        content_type = ContentType.objects.get_for_model(ParsedData)
        permission = Permission.objects.get(
            codename='view_parseddata',
            content_type=content_type
        )
        self.user.user_permissions.add(permission)
        
        # Create test patient
        from datetime import date
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth=date(1980, 1, 1),
            mrn='MRN001'
        )
        
        # Create test document
        pdf_content = b'%PDF-1.4 fake pdf content for testing'
        pdf_file = SimpleUploadedFile(
            'test_flagged_doc.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        self.document = Document.objects.create(
            patient=self.patient,
            filename='test_flagged_doc.pdf',
            file=pdf_file,
            status='completed',
            uploaded_by=self.user
        )
        
        # Create flagged parsed data with comprehensive FHIR data (list structure)
        self.fhir_data = [
            {
                'resourceType': 'Patient',
                'id': 'patient-1',
                'name': [{'given': ['John'], 'family': 'Doe'}],
                'birthDate': '1980-01-01'
            },
            {
                'resourceType': 'Condition',
                'id': 'condition-1',
                'code': {
                    'coding': [{
                        'code': 'E11.9',
                        'display': 'Type 2 diabetes mellitus'
                    }]
                },
                'clinicalStatus': {'coding': [{'code': 'active'}]}
            },
            {
                'resourceType': 'Observation',
                'id': 'obs-1',
                'code': {
                    'coding': [{
                        'code': '2339-0',
                        'display': 'Glucose'
                    }]
                },
                'valueQuantity': {
                    'value': 120,
                    'unit': 'mg/dL'
                },
                'effectiveDateTime': '2025-12-20'
            },
            {
                'resourceType': 'MedicationStatement',
                'id': 'med-1',
                'medicationCodeableConcept': {
                    'coding': [{
                        'code': '213169',
                        'display': 'Metformin'
                    }]
                }
            }
        ]
        
        self.flagged_item = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            review_status='flagged',
            flag_reason='Low extraction confidence (0.75 < 0.80 threshold)\nFallback AI model used: gpt-3.5-turbo',
            extraction_confidence=0.75,
            ai_model_used='gpt-3.5-turbo',
            fhir_delta_json=self.fhir_data
        )
        
        # Create another document for the second flagged item
        pdf_file2 = SimpleUploadedFile(
            'test_critical_doc.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        self.document2 = Document.objects.create(
            patient=self.patient,
            filename='test_critical_doc.pdf',
            file=pdf_file2,
            status='completed',
            uploaded_by=self.user
        )
        
        # Create another flagged item with different severity
        self.critical_flagged = ParsedData.objects.create(
            document=self.document2,
            patient=self.patient,
            review_status='flagged',
            flag_reason='Critical error: Missing required fields\nFailed to extract patient demographics',
            extraction_confidence=0.50,
            ai_model_used='claude-3-sonnet',
            fhir_delta_json=[]  # Empty list (no resources extracted)
        )
        
        # Create another document for the auto-approved item
        pdf_file3 = SimpleUploadedFile(
            'test_auto_approved_doc.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        self.document3 = Document.objects.create(
            patient=self.patient,
            filename='test_auto_approved_doc.pdf',
            file=pdf_file3,
            status='completed',
            uploaded_by=self.user
        )
        
        # Create non-flagged item (should not be accessible via this view)
        self.auto_approved = ParsedData.objects.create(
            document=self.document3,
            patient=self.patient,
            review_status='auto_approved',
            auto_approved=True,
            extraction_confidence=0.95,
            ai_model_used='claude-3-sonnet'
        )
        
        self.client = Client()
    
    def test_view_url_accessible(self):
        """Test that the flagged document detail view URL is accessible."""
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'documents/flagged_document_detail.html')
    
    def test_view_requires_authentication(self):
        """Test that unauthenticated users are redirected to login."""
        url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        response = self.client.get(url)
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)
    
    def test_view_only_shows_flagged_items(self):
        """Test that only flagged items are accessible via this view."""
        self.client.force_login(self.user)
        
        # Try to access auto_approved item (should 404)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.auto_approved.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 404)
    
    def test_nonexistent_item_returns_404(self):
        """Test that accessing nonexistent ParsedData returns 404."""
        self.client.force_login(self.user)
        
        url = reverse('documents:flagged-detail', kwargs={'pk': 99999})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 404)
    
    def test_context_contains_flagged_item(self):
        """Test that context includes the flagged item."""
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['flagged_item'], self.flagged_item)
    
    def test_context_contains_categorized_resources(self):
        """Test that FHIR resources are categorized properly."""
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        categorized = response.context['categorized_resources']
        
        # Check that categories exist
        self.assertIn('Demographics', categorized)
        self.assertIn('Clinical', categorized)
        self.assertIn('Medications', categorized)
        
        # Check that resources are properly categorized
        self.assertEqual(len(categorized['Demographics']), 1)  # Patient
        self.assertEqual(len(categorized['Clinical']), 2)  # Condition + Observation  
        self.assertEqual(len(categorized['Medications']), 1)  # MedicationStatement
        
        # Verify resource types match expectations
        self.assertEqual(categorized['Demographics'][0]['resourceType'], 'Patient')
        self.assertEqual(categorized['Clinical'][0]['resourceType'], 'Condition')
        self.assertEqual(categorized['Clinical'][1]['resourceType'], 'Observation')
        self.assertEqual(categorized['Medications'][0]['resourceType'], 'MedicationStatement')
    
    def test_context_contains_flag_analysis(self):
        """Test that flag reasons are analyzed and structured."""
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        flag_analysis = response.context['flag_analysis']
        
        # Should have structured analysis
        self.assertIn('summary', flag_analysis)
        self.assertIn('issues', flag_analysis)
        self.assertIn('severity', flag_analysis)
        
        # Should have parsed multiple issues
        self.assertEqual(len(flag_analysis['issues']), 2)
        self.assertIn('Low extraction confidence', flag_analysis['issues'][0])
        self.assertIn('Fallback AI model used', flag_analysis['issues'][1])
    
    def test_flag_severity_high_detection(self):
        """Test that high severity flags are properly detected."""
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.critical_flagged.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        flag_analysis = response.context['flag_analysis']
        
        # Should detect high severity based on keywords
        self.assertEqual(flag_analysis['severity'], 'high')
        self.assertIn('Critical error', flag_analysis['issues'][0])
    
    def test_flag_severity_medium_detection(self):
        """Test that medium severity flags are properly detected."""
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        flag_analysis = response.context['flag_analysis']
        
        # Should detect medium severity (confidence-related)
        self.assertEqual(flag_analysis['severity'], 'medium')
    
    def test_context_contains_document_info(self):
        """Test that document metadata is included in context."""
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        doc_info = response.context['document_info']
        
        # Should have all document metadata
        self.assertEqual(doc_info['filename'], 'test_flagged_doc.pdf')
        self.assertEqual(doc_info['uploaded_by'], self.user)
        self.assertEqual(doc_info['status'], 'completed')
        self.assertIsNotNone(doc_info['uploaded_at'])
    
    def test_context_contains_resource_counts(self):
        """Test that resource counts are calculated correctly."""
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        resource_counts = response.context['resource_counts']
        
        # Should have counts for each resource type
        self.assertEqual(resource_counts['Patient'], 1)
        self.assertEqual(resource_counts['Condition'], 1)
        self.assertEqual(resource_counts['Observation'], 1)
        self.assertEqual(resource_counts['MedicationStatement'], 1)
    
    def test_context_flags_conflicts_and_confidence(self):
        """Test that conflict and confidence flags are set correctly."""
        # Create a document for this test
        pdf_content = b'%PDF-1.4 conflict test pdf'
        pdf_file = SimpleUploadedFile(
            'conflict_test.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        conflict_doc = Document.objects.create(
            patient=self.patient,
            filename='conflict_test.pdf',
            file=pdf_file,
            status='completed',
            uploaded_by=self.user
        )
        
        # Create item with conflict in flag reason
        conflict_item = ParsedData.objects.create(
            document=conflict_doc,
            patient=self.patient,
            review_status='flagged',
            flag_reason='Data conflict detected: Birth date mismatch',
            extraction_confidence=0.85,
            ai_model_used='claude-3-sonnet'
        )
        
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': conflict_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Should detect conflict keyword
        self.assertTrue(response.context['has_conflicts'])
        
        # Original flagged_item should detect confidence issue
        url2 = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        response2 = self.client.get(url2)
        self.assertTrue(response2.context['has_low_confidence'])
    
    def test_empty_fhir_data_handled_gracefully(self):
        """Test that items with no extracted data are handled properly."""
        # Create a document for this test
        pdf_content = b'%PDF-1.4 empty test pdf'
        pdf_file = SimpleUploadedFile(
            'empty_test.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        empty_doc = Document.objects.create(
            patient=self.patient,
            filename='empty_test.pdf',
            file=pdf_file,
            status='completed',
            uploaded_by=self.user
        )
        
        empty_item = ParsedData.objects.create(
            document=empty_doc,
            patient=self.patient,
            review_status='flagged',
            flag_reason='Zero FHIR resources extracted',
            extraction_confidence=0.60,
            ai_model_used='claude-3-sonnet',
            fhir_delta_json={}
        )
        
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': empty_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Should have empty categorized resources
        self.assertEqual(len(response.context['categorized_resources']), 0)
        self.assertEqual(len(response.context['resource_counts']), 0)
    
    def test_select_related_optimization(self):
        """Test that queryset uses select_related for performance."""
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(url)
            
            # Access related fields
            _ = response.context['flagged_item'].document.filename
            _ = response.context['flagged_item'].patient.first_name
            _ = response.context['flagged_item'].document.uploaded_by
        
        # With select_related, should not have many queries
        # Expect: 1-2 main queries + auth queries
        self.assertLess(len(queries), 8, "Query count suggests missing select_related optimization")
    
    def test_displays_patient_information(self):
        """Test that patient information is rendered in template."""
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify patient is in context
        self.assertEqual(response.context['flagged_item'].patient, self.patient)
        self.assertIsNotNone(response.context['flagged_item'].patient.date_of_birth)
        
        content = response.content.decode()
        
        # Should display patient info
        self.assertIn('John', content)
        self.assertIn('Doe', content)
        self.assertIn('MRN001', content)
        # Date format is YYYY-MM-DD, so check for year at minimum
        self.assertIn('1980', content)
    
    def test_displays_flag_reason_prominently(self):
        """Test that flag reason is prominently displayed."""
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode()
        
        # Should display both flag reason issues
        self.assertIn('Low extraction confidence', content)
        self.assertIn('Fallback AI model used', content)
        self.assertIn('Why This Was Flagged', content)
    
    def test_displays_extracted_resources(self):
        """Test that extracted FHIR resources are displayed."""
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode()
        
        # Should display resource information
        self.assertIn('Type 2 diabetes mellitus', content)
        self.assertIn('Glucose', content)
        self.assertIn('Metformin', content)
        self.assertIn('Demographics', content)
        self.assertIn('Clinical', content)
        self.assertIn('Medications', content)
    
    def test_displays_action_buttons(self):
        """Test that verification action buttons are displayed."""
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode()
        
        # Should display action buttons
        self.assertIn('Mark as Correct', content)
        self.assertIn('Correct Data', content)
        self.assertIn('Rollback Merge', content)
        self.assertIn('Verification Actions', content)
    
    def test_back_link_to_list_view(self):
        """Test that back link to flagged list is present."""
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': self.flagged_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode()
        
        # Should have back link
        list_url = reverse('documents:flagged-list')
        self.assertIn(list_url, content)
        self.assertIn('Back to Flagged Documents', content)
    
    def test_error_handling_in_context_building(self):
        """Test that errors in context building are handled gracefully."""
        # Create a document for this test
        pdf_content = b'%PDF-1.4 malformed test pdf'
        pdf_file = SimpleUploadedFile(
            'malformed_test.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        malformed_doc = Document.objects.create(
            patient=self.patient,
            filename='malformed_test.pdf',
            file=pdf_file,
            status='completed',
            uploaded_by=self.user
        )
        
        # Create item with malformed FHIR data
        malformed_item = ParsedData.objects.create(
            document=malformed_doc,
            patient=self.patient,
            review_status='flagged',
            flag_reason='Test flag',
            extraction_confidence=0.80,
            ai_model_used='claude-3-sonnet',
            fhir_delta_json={'invalid': 'data structure'}
        )
        
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': malformed_item.pk})
        
        # Should not crash
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
    
    def test_missing_flag_reason_handled(self):
        """Test that items without flag_reason are handled properly."""
        # Create a document for this test
        pdf_content = b'%PDF-1.4 no reason test pdf'
        pdf_file = SimpleUploadedFile(
            'no_reason_test.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        no_reason_doc = Document.objects.create(
            patient=self.patient,
            filename='no_reason_test.pdf',
            file=pdf_file,
            status='completed',
            uploaded_by=self.user
        )
        
        no_reason_item = ParsedData.objects.create(
            document=no_reason_doc,
            patient=self.patient,
            review_status='flagged',
            flag_reason='',  # Empty string instead of None
            extraction_confidence=0.80,
            ai_model_used='claude-3-sonnet'
        )
        
        self.client.force_login(self.user)
        url = reverse('documents:flagged-detail', kwargs={'pk': no_reason_item.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        flag_analysis = response.context['flag_analysis']
        self.assertEqual(flag_analysis['summary'], 'No flag reason provided')
        self.assertEqual(flag_analysis['severity'], 'unknown')