"""
Tests for optimistic concurrency fields in ParsedData model (Task 41.1).
Tests the auto_approved and flag_reason fields.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.patients.models import Patient
from apps.documents.models import Document, ParsedData

User = get_user_model()


class ParsedDataOptimisticConcurrencyTests(TestCase):
    """
    Tests for optimistic concurrency fields in ParsedData model (Task 41.1).
    Tests the auto_approved and flag_reason fields.
    """
    
    def setUp(self):
        """Set up test data"""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test patient
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            mrn='TEST-001'
        )
        
        # Create test document
        pdf_content = b'%PDF-1.4 fake pdf content'
        pdf_file = SimpleUploadedFile(
            'test_document.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        
        self.document = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test_document.pdf',
            file=pdf_file,
            status='completed'
        )
        
        # Create test parsed data
        self.parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json={'resourceType': 'Patient'},
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.85
        )
    
    def test_auto_approved_field_default_value(self):
        """Test that auto_approved defaults to False"""
        self.assertFalse(self.parsed_data.auto_approved)
    
    def test_auto_approved_field_can_be_set_true(self):
        """Test that auto_approved can be set to True"""
        self.parsed_data.auto_approved = True
        self.parsed_data.save()
        
        # Refresh from database
        self.parsed_data.refresh_from_db()
        self.assertTrue(self.parsed_data.auto_approved)
    
    def test_auto_approved_field_can_be_set_false(self):
        """Test that auto_approved can be explicitly set to False"""
        self.parsed_data.auto_approved = True
        self.parsed_data.save()
        
        self.parsed_data.auto_approved = False
        self.parsed_data.save()
        
        # Refresh from database
        self.parsed_data.refresh_from_db()
        self.assertFalse(self.parsed_data.auto_approved)
    
    def test_flag_reason_field_default_value(self):
        """Test that flag_reason defaults to empty string"""
        self.assertEqual(self.parsed_data.flag_reason, '')
    
    def test_flag_reason_field_can_be_set(self):
        """Test that flag_reason can be set with text"""
        reason = "Low extraction confidence (0.65 < 0.80 threshold)"
        self.parsed_data.flag_reason = reason
        self.parsed_data.save()
        
        # Refresh from database
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.flag_reason, reason)
    
    def test_flag_reason_field_can_be_blank(self):
        """Test that flag_reason can be blank"""
        self.parsed_data.flag_reason = "Some reason"
        self.parsed_data.save()
        
        # Clear the reason
        self.parsed_data.flag_reason = ""
        self.parsed_data.save()
        
        # Refresh from database
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.flag_reason, "")
    
    def test_flag_reason_field_accepts_long_text(self):
        """Test that flag_reason can store long text"""
        long_reason = "Multiple issues detected: " + "x" * 500
        self.parsed_data.flag_reason = long_reason
        self.parsed_data.save()
        
        # Refresh from database
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.flag_reason, long_reason)
    
    def test_auto_approved_and_flag_reason_together(self):
        """Test that both fields can be set together"""
        self.parsed_data.auto_approved = False
        self.parsed_data.flag_reason = "Flagged for manual review due to DOB conflict"
        self.parsed_data.save()
        
        # Refresh from database
        self.parsed_data.refresh_from_db()
        self.assertFalse(self.parsed_data.auto_approved)
        self.assertEqual(
            self.parsed_data.flag_reason,
            "Flagged for manual review due to DOB conflict"
        )
    
    def test_auto_approved_field_is_indexed(self):
        """Test that auto_approved field has database index"""
        # Check that the field has db_index=True
        field = ParsedData._meta.get_field('auto_approved')
        self.assertTrue(field.db_index)
    
    def test_create_parsed_data_with_optimistic_fields(self):
        """Test creating new ParsedData with optimistic concurrency fields"""
        # Create another document for this test
        pdf_file = SimpleUploadedFile(
            'test_document2.pdf',
            b'%PDF-1.4 fake pdf content',
            content_type='application/pdf'
        )
        
        document2 = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test_document2.pdf',
            file=pdf_file,
            status='completed'
        )
        
        # Create ParsedData with optimistic fields set
        parsed_data = ParsedData.objects.create(
            document=document2,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json={'resourceType': 'Observation'},
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.95,
            auto_approved=True,
            flag_reason=""
        )
        
        # Verify fields were set correctly
        self.assertTrue(parsed_data.auto_approved)
        self.assertEqual(parsed_data.flag_reason, "")
    
    def test_query_by_auto_approved_status(self):
        """Test querying ParsedData by auto_approved status"""
        # Create additional parsed data with different auto_approved values
        pdf_file2 = SimpleUploadedFile(
            'test_doc2.pdf',
            b'%PDF-1.4 fake',
            content_type='application/pdf'
        )
        doc2 = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test_doc2.pdf',
            file=pdf_file2
        )
        
        parsed_data2 = ParsedData.objects.create(
            document=doc2,
            patient=self.patient,
            extraction_json={'test': 'data2'},
            fhir_delta_json={'resourceType': 'Condition'},
            auto_approved=True
        )
        
        # Query for auto-approved items
        auto_approved_items = ParsedData.objects.filter(auto_approved=True)
        self.assertEqual(auto_approved_items.count(), 1)
        self.assertEqual(auto_approved_items.first().id, parsed_data2.id)
        
        # Query for non-auto-approved items
        not_auto_approved = ParsedData.objects.filter(auto_approved=False)
        self.assertIn(self.parsed_data, not_auto_approved)

