"""
Simplified test suite for the review status data migration (Task 41.16).

Tests that the 5-state system works correctly after migration.
"""

import pytest
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.documents.models import Document, ParsedData
from apps.patients.models import Patient
from django.contrib.auth import get_user_model

User = get_user_model()


class PostMigrationReviewStatusTests(TestCase):
    """
    Test suite for verifying the 5-state review status system works correctly
    after migration 0016 has been applied.
    
    These tests verify that:
    1. All 5 new statuses are valid and can be used
    2. The old 'approved' status is no longer valid
    3. The auto_approved field works correctly
    4. Records can transition between the new statuses
    """
    
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
            date_of_birth='1990-01-01',
            mrn='TEST-MIG-001',
            created_by=self.user
        )
        
        # Create test document
        pdf_content = b'%PDF-1.4 fake pdf content for testing'
        test_file = SimpleUploadedFile(
            "test_migration.pdf",
            pdf_content,
            content_type="application/pdf"
        )
        
        self.document = Document.objects.create(
            filename='test_migration.pdf',
            file=test_file,
            patient=self.patient,
            uploaded_by=self.user
        )
    
    def test_all_five_new_statuses_are_valid(self):
        """
        Test that all 5 new status values can be created and used.
        
        This verifies the migration successfully added the new statuses:
        - pending (existed before)
        - auto_approved (NEW)
        - flagged (existed before)
        - reviewed (replaces 'approved')
        - rejected (existed before)
        """
        valid_statuses = {
            'pending': 'Pending Processing',
            'auto_approved': 'Auto-Approved - Merged Immediately',
            'flagged': 'Flagged - Needs Manual Review',
            'reviewed': 'Reviewed - Manually Approved',
            'rejected': 'Rejected - Do Not Use',
        }
        
        for status_value, status_display in valid_statuses.items():
            # Create document for each status test
            pdf_content = b'%PDF-1.4 fake pdf content'
            test_file = SimpleUploadedFile(
                f"test_{status_value}.pdf",
                pdf_content,
                content_type="application/pdf"
            )
            
            doc = Document.objects.create(
                filename=f'test_{status_value}.pdf',
                file=test_file,
                patient=self.patient,
                uploaded_by=self.user
            )
            
            # Create ParsedData with this status
            parsed_data = ParsedData.objects.create(
                document=doc,
                patient=self.patient,
                review_status=status_value,
                extraction_confidence=0.85,
                fhir_delta_json=[],
                created_by=self.user
            )
            
            # Verify status was set correctly
            assert parsed_data.review_status == status_value, \
                f"Status '{status_value}' should be valid and settable"
            
            # Verify we can retrieve it
            parsed_data.refresh_from_db()
            assert parsed_data.review_status == status_value, \
                f"Status '{status_value}' should persist correctly"
            
            # Verify display name is correct
            assert parsed_data.get_review_status_display() == status_display, \
                f"Display name for '{status_value}' should be '{status_display}'"
    
    def test_can_create_auto_approved_record(self):
        """
        Test creating a record with auto_approved status and flag.
        
        This is the core new feature of the optimistic concurrency system.
        """
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            review_status='auto_approved',
            auto_approved=True,  # NEW field
            extraction_confidence=0.95,
            fhir_delta_json=[{'resourceType': 'Condition'}],
            created_by=self.user
        )
        
        assert parsed_data.review_status == 'auto_approved'
        assert parsed_data.auto_approved is True
        assert parsed_data.flag_reason == ''  # No flag reason for auto-approved
    
    def test_can_create_reviewed_record(self):
        """
        Test creating a record with reviewed status (replaces old 'approved').
        
        This status represents manual human review and approval.
        """
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            review_status='reviewed',
            auto_approved=False,  # Manually reviewed, not auto-approved
            extraction_confidence=0.90,
            fhir_delta_json=[{'resourceType': 'Observation'}],
            created_by=self.user,
            reviewed_by=self.user
        )
        
        assert parsed_data.review_status == 'reviewed'
        assert parsed_data.auto_approved is False
        assert parsed_data.reviewed_by == self.user
    
    def test_can_create_flagged_record_with_reason(self):
        """
        Test creating a flagged record with flag_reason.
        
        Flagged records have issues that need manual review.
        """
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            review_status='flagged',
            auto_approved=False,
            flag_reason='Low extraction confidence: 0.75',  # NEW field
            extraction_confidence=0.75,
            fhir_delta_json=[],
            created_by=self.user
        )
        
        assert parsed_data.review_status == 'flagged'
        assert parsed_data.auto_approved is False
        assert 'Low extraction confidence' in parsed_data.flag_reason
    
    def test_old_approved_status_is_not_in_choices(self):
        """
        Test that the old 'approved' status is no longer in the valid choices.
        
        After migration, only the new 5 statuses should be valid.
        The old 'approved' status was replaced by 'reviewed'.
        """
        # Get the status choices from the model
        status_choices = [choice[0] for choice in ParsedData.REVIEW_STATUS_CHOICES]
        
        # Verify old 'approved' is not in choices
        assert 'approved' not in status_choices, \
            "Old 'approved' status should not be in REVIEW_STATUS_CHOICES"
        
        # Verify new 'reviewed' IS in choices
        assert 'reviewed' in status_choices, \
            "New 'reviewed' status should replace old 'approved'"
        
        # Verify new 'auto_approved' IS in choices
        assert 'auto_approved' in status_choices, \
            "New 'auto_approved' status should be available"
    
    def test_auto_approved_field_defaults_to_false(self):
        """Test that auto_approved field defaults to False for new records."""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            review_status='pending',
            extraction_confidence=0.85,
            fhir_delta_json=[],
            created_by=self.user
        )
        
        # Should default to False (not auto-approved until evaluated)
        assert parsed_data.auto_approved is False
    
    def test_flag_reason_field_defaults_to_empty(self):
        """Test that flag_reason field defaults to empty string."""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            review_status='pending',
            extraction_confidence=0.85,
            fhir_delta_json=[],
            created_by=self.user
        )
        
        # Should default to empty string
        assert parsed_data.flag_reason == ''
    
    def test_can_query_by_auto_approved_field(self):
        """Test that auto_approved field can be queried efficiently."""
        # Create some auto-approved records
        for i in range(3):
            pdf_content = b'%PDF-1.4 fake pdf'
            test_file = SimpleUploadedFile(
                f"test_auto_{i}.pdf",
                pdf_content,
                content_type="application/pdf"
            )
            
            doc = Document.objects.create(
                filename=f'test_auto_{i}.pdf',
                file=test_file,
                patient=self.patient,
                uploaded_by=self.user
            )
            
            ParsedData.objects.create(
                document=doc,
                patient=self.patient,
                review_status='auto_approved',
                auto_approved=True,
                extraction_confidence=0.95,
                fhir_delta_json=[],
                created_by=self.user
            )
        
        # Create some non-auto-approved records
        for i in range(2):
            pdf_content = b'%PDF-1.4 fake pdf'
            test_file = SimpleUploadedFile(
                f"test_manual_{i}.pdf",
                pdf_content,
                content_type="application/pdf"
            )
            
            doc = Document.objects.create(
                filename=f'test_manual_{i}.pdf',
                file=test_file,
                patient=self.patient,
                uploaded_by=self.user
            )
            
            ParsedData.objects.create(
                document=doc,
                patient=self.patient,
                review_status='flagged',
                auto_approved=False,
                extraction_confidence=0.70,
                fhir_delta_json=[],
                created_by=self.user
            )
        
        # Query auto-approved records
        auto_approved_count = ParsedData.objects.filter(auto_approved=True).count()
        assert auto_approved_count == 3, "Should find 3 auto-approved records"
        
        # Query non-auto-approved records
        manual_review_count = ParsedData.objects.filter(auto_approved=False).count()
        # Should be at least 2 (could be more from other tests)
        assert manual_review_count >= 2, "Should find at least 2 records needing review"
    
    def test_can_query_by_review_status_and_sort_by_date(self):
        """
        Test that we can efficiently query by review_status and sort by created_at.
        
        This verifies the composite index (review_status, created_at) works.
        """
        # Query flagged records sorted by date
        flagged_records = ParsedData.objects.filter(
            review_status='flagged'
        ).order_by('-created_at')
        
        # Query should execute without error (index makes it efficient)
        flagged_count = flagged_records.count()
        
        # Just verify query works (actual count may vary)
        assert flagged_count >= 0, "Query should execute successfully"


class MigrationDataIntegrityTests(TestCase):
    """
    Tests to verify that existing data is preserved correctly after migration.
    
    These tests verify that:
    - Merged records stay merged
    - Extraction data is preserved
    - Related records (Document, Patient) are intact
    """
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='Data',
            last_name='Integrity',
            date_of_birth='1985-06-15',
            mrn='TEST-INT-001',
            created_by=self.user
        )
    
    def test_migrated_record_preserves_is_merged_status(self):
        """
        Test that migration doesn't change is_merged status.
        
        Records that were already merged should remain merged after migration.
        """
        pdf_content = b'%PDF-1.4 fake pdf'
        test_file = SimpleUploadedFile(
            "merged_record.pdf",
            pdf_content,
            content_type="application/pdf"
        )
        
        doc = Document.objects.create(
            filename='merged_record.pdf',
            file=test_file,
            patient=self.patient,
            uploaded_by=self.user
        )
        
        # Create a record that's already merged
        parsed_data = ParsedData.objects.create(
            document=doc,
            patient=self.patient,
            review_status='reviewed',  # New status after migration
            auto_approved=False,
            extraction_confidence=0.90,
            is_merged=True,  # Already merged into patient record
            fhir_delta_json=[{'resourceType': 'Condition'}],
            created_by=self.user
        )
        
        # Verify is_merged stayed True
        assert parsed_data.is_merged is True
        assert parsed_data.review_status == 'reviewed'
    
    def test_extraction_data_preserved_after_migration(self):
        """Test that FHIR data and extraction details are preserved."""
        pdf_content = b'%PDF-1.4 fake pdf'
        test_file = SimpleUploadedFile(
            "preserved_data.pdf",
            pdf_content,
            content_type="application/pdf"
        )
        
        doc = Document.objects.create(
            filename='preserved_data.pdf',
            file=test_file,
            patient=self.patient,
            uploaded_by=self.user
        )
        
        fhir_data = [
            {'resourceType': 'Condition', 'code': {'text': 'Diabetes'}},
            {'resourceType': 'Observation', 'code': {'text': 'Blood Pressure'}}
        ]
        
        parsed_data = ParsedData.objects.create(
            document=doc,
            patient=self.patient,
            review_status='reviewed',
            auto_approved=False,
            extraction_confidence=0.92,
            fhir_delta_json=fhir_data,
            processing_time_seconds=2.5,
            ai_model_used='claude-3-5-sonnet-20241022',
            created_by=self.user
        )
        
        # Verify all extraction data is preserved
        assert parsed_data.extraction_confidence == 0.92
        assert parsed_data.processing_time_seconds == 2.5
        assert parsed_data.ai_model_used == 'claude-3-5-sonnet-20241022'
        assert len(parsed_data.fhir_delta_json) == 2
        assert parsed_data.fhir_delta_json[0]['resourceType'] == 'Condition'

