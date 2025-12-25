"""
Tests for dashboard views.
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.patients.models import Patient
from apps.providers.models import Provider
from apps.documents.models import Document, ParsedData
from django.utils import timezone


class DashboardViewTests(TestCase):
    """Test cases for the main dashboard view."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.force_login(self.user)
        self.dashboard_url = reverse('accounts:dashboard')
        
        # Create test patient
        self.patient = Patient.objects.create(
            first_name='Test',
            last_name='Patient',
            mrn='TEST-001',
            date_of_birth='1980-01-01',
            gender='M'
        )
    
    def test_dashboard_loads_successfully(self):
        """Test that dashboard page loads without errors."""
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/dashboard.html')
    
    def test_dashboard_shows_patient_count(self):
        """Test that dashboard displays correct patient count."""
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('patient_count', response.context)
        self.assertEqual(response.context['patient_count'], 1)
    
    def test_dashboard_shows_flagged_count_zero(self):
        """Test that dashboard shows zero flagged extractions when none exist."""
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('flagged_extractions_count', response.context)
        self.assertEqual(response.context['flagged_extractions_count'], 0)
    
    def test_dashboard_shows_flagged_count_with_flagged_data(self):
        """Test that dashboard shows correct flagged count when flagged data exists."""
        # Create a document
        fake_file = SimpleUploadedFile("test.pdf", b"fake pdf content", content_type="application/pdf")
        document = Document.objects.create(
            patient=self.patient,
            filename='test.pdf',
            file=fake_file,
            status='completed',
            uploaded_by=self.user
        )
        
        # Create flagged parsed data
        ParsedData.objects.create(
            document=document,
            patient=self.patient,
            review_status='flagged',
            flag_reason='Low confidence score',
            extraction_confidence=0.75,
            ai_model_used='claude-3-sonnet',
            raw_extracted_data={'test': 'data'},
            fhir_resources={'resourceType': 'Bundle', 'entry': []},
            extracted_at=timezone.now()
        )
        
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['flagged_extractions_count'], 1)
    
    def test_dashboard_counts_multiple_flagged_extractions(self):
        """Test that dashboard correctly counts multiple flagged extractions."""
        # Create two documents with flagged data
        for i in range(2):
            fake_file = SimpleUploadedFile(f"test{i}.pdf", b"fake pdf content", content_type="application/pdf")
            document = Document.objects.create(
                patient=self.patient,
                filename=f'test{i}.pdf',
                file=fake_file,
                status='completed',
                uploaded_by=self.user
            )
            
            ParsedData.objects.create(
                document=document,
                patient=self.patient,
                review_status='flagged',
                flag_reason='Test flag',
                extraction_confidence=0.70,
                ai_model_used='claude-3-sonnet',
                raw_extracted_data={'test': 'data'},
                fhir_resources={'resourceType': 'Bundle', 'entry': []},
                extracted_at=timezone.now()
            )
        
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['flagged_extractions_count'], 2)
    
    def test_dashboard_ignores_non_flagged_extractions(self):
        """Test that dashboard only counts flagged extractions, not auto-approved ones."""
        # Create document with auto-approved data
        fake_file = SimpleUploadedFile("test.pdf", b"fake pdf content", content_type="application/pdf")
        document = Document.objects.create(
            patient=self.patient,
            filename='test.pdf',
            file=fake_file,
            status='completed',
            uploaded_by=self.user
        )
        
        ParsedData.objects.create(
            document=document,
            patient=self.patient,
            review_status='auto_approved',
            extraction_confidence=0.95,
            ai_model_used='claude-3-sonnet',
            raw_extracted_data={'test': 'data'},
            fhir_resources={'resourceType': 'Bundle', 'entry': []},
            extracted_at=timezone.now()
        )
        
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['flagged_extractions_count'], 0)
    
    def test_dashboard_requires_authentication(self):
        """Test that dashboard requires user to be logged in."""
        self.client.logout()
        response = self.client.get(self.dashboard_url)
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

