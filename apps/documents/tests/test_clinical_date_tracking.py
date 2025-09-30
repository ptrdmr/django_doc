"""
Tests for clinical date tracking functionality in ParsedData model (Task 35.4).
"""

from datetime import date, timedelta
from django.test import TestCase
from django.contrib.auth import get_user_model

from apps.documents.models import Document, ParsedData
from apps.patients.models import Patient

User = get_user_model()


class ClinicalDateTrackingTestCase(TestCase):
    """Test suite for clinical date tracking in ParsedData model."""
    
    def setUp(self):
        """Create test user, patient, and document."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth=date(1980, 1, 1),
            mrn='TEST001'
        )
        
        # Create a test PDF file
        from django.core.files.uploadedfile import SimpleUploadedFile
        test_pdf = SimpleUploadedFile(
            "test_document.pdf",
            b"fake pdf content",
            content_type="application/pdf"
        )
        
        self.document = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test_document.pdf',
            file=test_pdf,
            status='completed'
        )
        
        self.parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json={'test': 'fhir'}
        )
    
    def test_clinical_date_field_exists(self):
        """Test that clinical_date field can be set and retrieved."""
        test_date = date(2023, 5, 15)
        self.parsed_data.clinical_date = test_date
        self.parsed_data.save()
        
        # Retrieve from database
        retrieved = ParsedData.objects.get(id=self.parsed_data.id)
        self.assertEqual(retrieved.clinical_date, test_date)
    
    def test_date_source_choices(self):
        """Test that date_source field accepts valid choices."""
        # Test 'extracted' choice
        self.parsed_data.date_source = 'extracted'
        self.parsed_data.save()
        retrieved = ParsedData.objects.get(id=self.parsed_data.id)
        self.assertEqual(retrieved.date_source, 'extracted')
        
        # Test 'manual' choice
        self.parsed_data.date_source = 'manual'
        self.parsed_data.save()
        retrieved = ParsedData.objects.get(id=self.parsed_data.id)
        self.assertEqual(retrieved.date_source, 'manual')
    
    def test_date_status_default(self):
        """Test that date_status defaults to 'pending'."""
        # Create a new document (ParsedData has OneToOne relationship with Document)
        from django.core.files.uploadedfile import SimpleUploadedFile
        test_pdf = SimpleUploadedFile(
            "test_document2.pdf",
            b"fake pdf content 2",
            content_type="application/pdf"
        )
        
        new_document = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test_document2.pdf',
            file=test_pdf,
            status='completed'
        )
        
        # Create new ParsedData instance
        new_parsed_data = ParsedData.objects.create(
            document=new_document,
            patient=self.patient,
            extraction_json={'test': 'data2'},
            fhir_delta_json={'test': 'fhir2'}
        )
        
        # Should default to 'pending'
        self.assertEqual(new_parsed_data.date_status, 'pending')
    
    def test_date_status_choices(self):
        """Test that date_status field accepts valid choices."""
        # Test 'pending' choice
        self.parsed_data.date_status = 'pending'
        self.parsed_data.save()
        retrieved = ParsedData.objects.get(id=self.parsed_data.id)
        self.assertEqual(retrieved.date_status, 'pending')
        
        # Test 'verified' choice
        self.parsed_data.date_status = 'verified'
        self.parsed_data.save()
        retrieved = ParsedData.objects.get(id=self.parsed_data.id)
        self.assertEqual(retrieved.date_status, 'verified')
    
    def test_set_clinical_date_with_date_object(self):
        """Test set_clinical_date method with date object."""
        test_date = date(2023, 7, 1)
        self.parsed_data.set_clinical_date(
            date=test_date,
            source='extracted',
            status='pending'
        )
        
        retrieved = ParsedData.objects.get(id=self.parsed_data.id)
        self.assertEqual(retrieved.clinical_date, test_date)
        self.assertEqual(retrieved.date_source, 'extracted')
        self.assertEqual(retrieved.date_status, 'pending')
    
    def test_set_clinical_date_with_string(self):
        """Test set_clinical_date method with ISO format string."""
        self.parsed_data.set_clinical_date(
            date='2023-08-15',
            source='manual',
            status='verified'
        )
        
        retrieved = ParsedData.objects.get(id=self.parsed_data.id)
        self.assertEqual(retrieved.clinical_date, date(2023, 8, 15))
        self.assertEqual(retrieved.date_source, 'manual')
        self.assertEqual(retrieved.date_status, 'verified')
    
    def test_set_clinical_date_invalid_string(self):
        """Test set_clinical_date method with invalid date string."""
        with self.assertRaises(ValueError):
            self.parsed_data.set_clinical_date(
                date='invalid-date',
                source='manual'
            )
    
    def test_verify_clinical_date(self):
        """Test verify_clinical_date method."""
        # Set a pending clinical date
        self.parsed_data.set_clinical_date(
            date=date(2023, 9, 1),
            source='extracted',
            status='pending'
        )
        
        # Verify it
        self.parsed_data.verify_clinical_date()
        
        retrieved = ParsedData.objects.get(id=self.parsed_data.id)
        self.assertEqual(retrieved.date_status, 'verified')
    
    def test_verify_clinical_date_without_date(self):
        """Test verify_clinical_date raises error when no date is set."""
        with self.assertRaises(ValueError) as context:
            self.parsed_data.verify_clinical_date()
        
        self.assertIn('No clinical date to verify', str(context.exception))
    
    def test_has_clinical_date(self):
        """Test has_clinical_date method."""
        # Initially no date
        self.assertFalse(self.parsed_data.has_clinical_date())
        
        # Set a date
        self.parsed_data.clinical_date = date(2023, 10, 1)
        self.parsed_data.save()
        
        # Now should return True
        self.assertTrue(self.parsed_data.has_clinical_date())
    
    def test_needs_date_verification(self):
        """Test needs_date_verification method."""
        # No date - should not need verification
        self.assertFalse(self.parsed_data.needs_date_verification())
        
        # Set pending date - should need verification
        self.parsed_data.set_clinical_date(
            date=date(2023, 11, 1),
            source='extracted',
            status='pending'
        )
        self.assertTrue(self.parsed_data.needs_date_verification())
        
        # Verify the date - should not need verification anymore
        self.parsed_data.verify_clinical_date()
        self.assertFalse(self.parsed_data.needs_date_verification())
    
    def test_is_date_verified(self):
        """Test is_date_verified method."""
        # No date - not verified
        self.assertFalse(self.parsed_data.is_date_verified())
        
        # Pending date - not verified
        self.parsed_data.set_clinical_date(
            date=date(2023, 12, 1),
            source='manual',
            status='pending'
        )
        self.assertFalse(self.parsed_data.is_date_verified())
        
        # Verified date - is verified
        self.parsed_data.verify_clinical_date()
        self.assertTrue(self.parsed_data.is_date_verified())
    
    def test_clinical_date_indexing(self):
        """Test that database indexes are working for clinical date queries."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        # Create multiple ParsedData instances with different dates
        # Each needs its own document due to OneToOne relationship
        for i in range(5):
            test_pdf = SimpleUploadedFile(
                f"test_indexing_{i}.pdf",
                b"fake pdf content",
                content_type="application/pdf"
            )
            
            test_document = Document.objects.create(
                patient=self.patient,
                uploaded_by=self.user,
                filename=f'test_indexing_{i}.pdf',
                file=test_pdf,
                status='completed'
            )
            
            test_date = date(2023, 1, 1) + timedelta(days=i*30)
            ParsedData.objects.create(
                document=test_document,
                patient=self.patient,
                extraction_json={'index': i},
                fhir_delta_json={'index': i},
                clinical_date=test_date,
                date_source='extracted',
                date_status='pending' if i % 2 == 0 else 'verified'
            )
        
        # Query by clinical date
        results = ParsedData.objects.filter(
            clinical_date__gte=date(2023, 2, 1),
            clinical_date__lte=date(2023, 6, 1)
        )
        self.assertEqual(results.count(), 3)  # Should get 3 records
        
        # Query by patient and clinical date
        patient_results = ParsedData.objects.filter(
            patient=self.patient,
            clinical_date__isnull=False
        )
        self.assertEqual(patient_results.count(), 5)
        
        # Query by date status
        pending_results = ParsedData.objects.filter(
            date_status='pending',
            clinical_date__isnull=False
        )
        self.assertEqual(pending_results.count(), 3)  # 0, 2, 4 are pending
    
    def test_workflow_extracted_date_pending(self):
        """Test typical workflow: AI extracts date, needs verification."""
        # AI extraction sets clinical date
        self.parsed_data.set_clinical_date(
            date='2024-01-15',
            source='extracted',
            status='pending'
        )
        
        # Check it needs verification
        self.assertTrue(self.parsed_data.needs_date_verification())
        self.assertFalse(self.parsed_data.is_date_verified())
        
        # Verify the date
        self.parsed_data.verify_clinical_date()
        
        # Check verification complete
        self.assertFalse(self.parsed_data.needs_date_verification())
        self.assertTrue(self.parsed_data.is_date_verified())
    
    def test_workflow_manual_entry_verified(self):
        """Test typical workflow: Manual entry, immediately verified."""
        # User manually enters date
        self.parsed_data.set_clinical_date(
            date='2024-02-20',
            source='manual',
            status='verified'
        )
        
        # Should be immediately verified
        self.assertFalse(self.parsed_data.needs_date_verification())
        self.assertTrue(self.parsed_data.is_date_verified())
        self.assertEqual(self.parsed_data.date_source, 'manual')
