"""
Tests for patient detail view flagged extractions count.
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User, Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.patients.models import Patient
from apps.documents.models import Document, ParsedData
from django.utils import timezone


class PatientDetailFlaggedCountTests(TestCase):
    """Test cases for flagged extractions count in patient detail view."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        # Create superuser to bypass all permission checks
        self.user = User.objects.create_superuser(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.force_login(self.user)
        
        # Create test patients
        self.patient1 = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            mrn='TEST-001',
            date_of_birth='1980-01-01',
            gender='M'
        )
        
        self.patient2 = Patient.objects.create(
            first_name='Jane',
            last_name='Smith',
            mrn='TEST-002',
            date_of_birth='1985-05-15',
            gender='F'
        )
    
    def test_patient_detail_shows_zero_flagged_count(self):
        """Test that patient detail shows zero flagged count when none exist."""
        response = self.client.get(reverse('patients:detail', args=[self.patient1.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('flagged_extractions_count', response.context)
        self.assertEqual(response.context['flagged_extractions_count'], 0)
    
    def test_patient_detail_shows_flagged_count_for_specific_patient(self):
        """Test that patient detail shows correct flagged count for specific patient."""
        # Create flagged document for patient1
        fake_file = SimpleUploadedFile("test.pdf", b"fake pdf content", content_type="application/pdf")
        document = Document.objects.create(
            patient=self.patient1,
            filename='test.pdf',
            file=fake_file,
            status='completed',
            uploaded_by=self.user
        )
        
        ParsedData.objects.create(
            document=document,
            patient=self.patient1,
            review_status='flagged',
            flag_reason='Low confidence',
            extraction_confidence=0.75,
            ai_model_used='claude-3-sonnet',
            raw_extracted_data={'test': 'data'},
            fhir_resources={'resourceType': 'Bundle', 'entry': []},
            extracted_at=timezone.now()
        )
        
        # Check patient1 detail page
        response = self.client.get(reverse('patients:detail', args=[self.patient1.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['flagged_extractions_count'], 1)
        
        # Check patient2 detail page (should be 0)
        response = self.client.get(reverse('patients:detail', args=[self.patient2.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['flagged_extractions_count'], 0)
    
    def test_patient_detail_counts_multiple_flagged_documents(self):
        """Test that patient detail correctly counts multiple flagged documents."""
        # Create two flagged documents for patient1
        for i in range(2):
            fake_file = SimpleUploadedFile(f"test{i}.pdf", b"fake pdf content", content_type="application/pdf")
            document = Document.objects.create(
                patient=self.patient1,
                filename=f'test{i}.pdf',
                file=fake_file,
                status='completed',
                uploaded_by=self.user
            )
            
            ParsedData.objects.create(
                document=document,
                patient=self.patient1,
                review_status='flagged',
                flag_reason='Test flag',
                extraction_confidence=0.70,
                ai_model_used='claude-3-sonnet',
                raw_extracted_data={'test': 'data'},
                fhir_resources={'resourceType': 'Bundle', 'entry': []},
                extracted_at=timezone.now()
            )
        
        response = self.client.get(reverse('patients:detail', args=[self.patient1.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['flagged_extractions_count'], 2)
    
    def test_patient_detail_ignores_auto_approved_extractions(self):
        """Test that patient detail only counts flagged, not auto-approved extractions."""
        # Create auto-approved document
        fake_file = SimpleUploadedFile("test.pdf", b"fake pdf content", content_type="application/pdf")
        document = Document.objects.create(
            patient=self.patient1,
            filename='test.pdf',
            file=fake_file,
            status='completed',
            uploaded_by=self.user
        )
        
        ParsedData.objects.create(
            document=document,
            patient=self.patient1,
            review_status='auto_approved',
            extraction_confidence=0.95,
            ai_model_used='claude-3-sonnet',
            raw_extracted_data={'test': 'data'},
            fhir_resources={'resourceType': 'Bundle', 'entry': []},
            extracted_at=timezone.now()
        )
        
        response = self.client.get(reverse('patients:detail', args=[self.patient1.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['flagged_extractions_count'], 0)
    
    def test_patient_detail_badge_not_shown_when_zero_flagged(self):
        """Test that flagged badge is not shown when count is zero."""
        response = self.client.get(reverse('patients:detail', args=[self.patient1.pk]))
        self.assertEqual(response.status_code, 200)
        # Badge should not appear in HTML when count is 0
        self.assertNotContains(response, 'extractions need manual review')
    
    def test_patient_detail_badge_shown_when_flagged_exist(self):
        """Test that flagged badge is shown when flagged extractions exist."""
        # Create flagged document
        fake_file = SimpleUploadedFile("test.pdf", b"fake pdf content", content_type="application/pdf")
        document = Document.objects.create(
            patient=self.patient1,
            filename='test.pdf',
            file=fake_file,
            status='completed',
            uploaded_by=self.user
        )
        
        ParsedData.objects.create(
            document=document,
            patient=self.patient1,
            review_status='flagged',
            flag_reason='Low confidence',
            extraction_confidence=0.75,
            ai_model_used='claude-3-sonnet',
            raw_extracted_data={'test': 'data'},
            fhir_resources={'resourceType': 'Bundle', 'entry': []},
            extracted_at=timezone.now()
        )
        
        response = self.client.get(reverse('patients:detail', args=[self.patient1.pk]))
        self.assertEqual(response.status_code, 200)
        # Badge should appear in HTML
        self.assertContains(response, 'extraction needs manual review')
    
    def test_patient_detail_badge_plural_text(self):
        """Test that badge uses correct plural text for multiple flagged extractions."""
        # Create two flagged documents
        for i in range(2):
            document = Document.objects.create(
                patient=self.patient1,
                file=f'test{i}.pdf',
                status='completed',
                uploaded_by=self.user
            )
            
            ParsedData.objects.create(
                document=document,
                patient=self.patient1,
                review_status='flagged',
                flag_reason='Test',
                extraction_confidence=0.75,
                ai_model_used='claude-3-sonnet',
                raw_extracted_data={'test': 'data'},
                fhir_resources={'resourceType': 'Bundle', 'entry': []},
                extracted_at=timezone.now()
            )
        
        response = self.client.get(reverse('patients:detail', args=[self.patient1.pk]))
        self.assertEqual(response.status_code, 200)
        # Should use plural form
        self.assertContains(response, 'extractions need manual review')
        self.assertNotContains(response, '1 extraction needs manual review')
    
    def test_patient_detail_counts_distinct_documents(self):
        """Test that count is based on distinct documents, not total ParsedData records."""
        # Create one document with multiple ParsedData records (shouldn't happen in practice, but test edge case)
        fake_file = SimpleUploadedFile("test.pdf", b"fake pdf content", content_type="application/pdf")
        document = Document.objects.create(
            patient=self.patient1,
            filename='test.pdf',
            file=fake_file,
            status='completed',
            uploaded_by=self.user
        )
        
        # Create two ParsedData records for same document (edge case)
        for i in range(2):
            ParsedData.objects.create(
                document=document,
                patient=self.patient1,
                review_status='flagged',
                flag_reason=f'Test {i}',
                extraction_confidence=0.75,
                ai_model_used='claude-3-sonnet',
                raw_extracted_data={'test': f'data{i}'},
                fhir_resources={'resourceType': 'Bundle', 'entry': []},
                extracted_at=timezone.now()
            )
        
        response = self.client.get(reverse('patients:detail', args=[self.patient1.pk]))
        self.assertEqual(response.status_code, 200)
        # Should count as 1 document, not 2 ParsedData records
        self.assertEqual(response.context['flagged_extractions_count'], 1)

