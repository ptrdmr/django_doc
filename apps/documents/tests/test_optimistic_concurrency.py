"""
Tests for optimistic concurrency features in ParsedData model.
- Task 41.1: auto_approved and flag_reason fields
- Task 41.2: 5-state review_status choices
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

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


class CheckQuickConflictsTests(TestCase):
    """
    Tests for the check_quick_conflicts() method in ParsedData model (Task 41.4).
    Tests patient data conflict detection with performance validation.
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
    
    def test_no_conflict_when_demographics_match(self):
        """Test that matching demographics return no conflict"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{
                'resourceType': 'Patient',
                'name': [{'given': ['John'], 'family': 'Doe'}],
                'birthDate': '1980-01-01'
            }],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92
        )
        
        has_conflict, reason = parsed_data.check_quick_conflicts()
        
        self.assertFalse(has_conflict)
        self.assertEqual(reason, '')
    
    def test_conflict_when_dob_mismatches(self):
        """Test that DOB mismatch triggers conflict"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{
                'resourceType': 'Patient',
                'name': [{'given': ['John'], 'family': 'Doe'}],
                'birthDate': '1985-05-15'  # Different DOB
            }],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92
        )
        
        has_conflict, reason = parsed_data.check_quick_conflicts()
        
        self.assertTrue(has_conflict)
        self.assertIn('DOB mismatch', reason)
        self.assertIn('1985-05-15', reason)
        self.assertIn('1980-01-01', reason)
    
    def test_conflict_when_name_completely_different(self):
        """Test that completely different name triggers conflict"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{
                'resourceType': 'Patient',
                'name': [{'given': ['Jane'], 'family': 'Smith'}],  # Completely different name
                'birthDate': '1980-01-01'
            }],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92
        )
        
        has_conflict, reason = parsed_data.check_quick_conflicts()
        
        self.assertTrue(has_conflict)
        self.assertIn('Name mismatch', reason)
        self.assertIn('Jane Smith', reason)
        self.assertIn('John Doe', reason)
    
    def test_no_conflict_with_middle_name_variation(self):
        """Test that middle name variations don't trigger false conflicts"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{
                'resourceType': 'Patient',
                'name': [{'given': ['John', 'Michael'], 'family': 'Doe'}],  # Added middle name
                'birthDate': '1980-01-01'
            }],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92
        )
        
        has_conflict, reason = parsed_data.check_quick_conflicts()
        
        # Should NOT conflict - John Doe matches John Michael Doe
        self.assertFalse(has_conflict)
        self.assertEqual(reason, '')
    
    def test_no_conflict_with_nickname_variation(self):
        """Test that reasonable name variations don't trigger conflicts"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{
                'resourceType': 'Patient',
                'name': [{'given': ['J'], 'family': 'Doe'}],  # Initial only
                'birthDate': '1980-01-01'
            }],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92
        )
        
        has_conflict, reason = parsed_data.check_quick_conflicts()
        
        # Should NOT conflict - partial match is acceptable
        self.assertFalse(has_conflict)
        self.assertEqual(reason, '')
    
    def test_no_conflict_when_no_patient_resource_in_fhir(self):
        """Test that missing Patient resource doesn't trigger conflict"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{
                'resourceType': 'Observation',  # No Patient resource
                'code': {'text': 'Blood Pressure'}
            }],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92
        )
        
        has_conflict, reason = parsed_data.check_quick_conflicts()
        
        # Should NOT conflict - can't check if no demographics extracted
        self.assertFalse(has_conflict)
        self.assertEqual(reason, '')
    
    def test_no_conflict_when_fhir_data_empty(self):
        """Test that empty FHIR data doesn't trigger conflict"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],  # Empty
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92
        )
        
        has_conflict, reason = parsed_data.check_quick_conflicts()
        
        self.assertFalse(has_conflict)
        self.assertEqual(reason, '')
    
    def test_multiple_conflicts_reported_together(self):
        """Test that multiple conflicts are reported in a single reason string"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{
                'resourceType': 'Patient',
                'name': [{'given': ['Jane'], 'family': 'Smith'}],  # Wrong name
                'birthDate': '1985-05-15'  # Wrong DOB
            }],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92
        )
        
        has_conflict, reason = parsed_data.check_quick_conflicts()
        
        self.assertTrue(has_conflict)
        # Should contain both conflicts
        self.assertIn('DOB mismatch', reason)
        self.assertIn('Name mismatch', reason)
        self.assertIn(';', reason)  # Multiple conflicts separated by semicolon
    
    def test_check_quick_conflicts_performance(self):
        """Test that check_quick_conflicts executes in < 100ms"""
        import time
        
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{
                'resourceType': 'Patient',
                'name': [{'given': ['John'], 'family': 'Doe'}],
                'birthDate': '1980-01-01'
            }],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92
        )
        
        # Measure execution time
        start_time = time.time()
        has_conflict, reason = parsed_data.check_quick_conflicts()
        execution_time = (time.time() - start_time) * 1000  # Convert to ms
        
        # Should complete in < 100ms
        self.assertLess(execution_time, 100,
                       f"check_quick_conflicts took {execution_time:.2f}ms, exceeds 100ms target")
    
    def test_dict_format_fhir_patient_resource_handled(self):
        """Test that legacy dict format FHIR data is handled correctly"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json={
                'Patient': [{
                    'resourceType': 'Patient',
                    'name': [{'given': ['John'], 'family': 'Doe'}],
                    'birthDate': '1980-01-01'
                }]
            },  # Dict format
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92
        )
        
        has_conflict, reason = parsed_data.check_quick_conflicts()
        
        self.assertFalse(has_conflict)
        self.assertEqual(reason, '')
    
    def test_case_insensitive_name_comparison(self):
        """Test that name comparison is case-insensitive"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{
                'resourceType': 'Patient',
                'name': [{'given': ['JOHN'], 'family': 'DOE'}],  # All caps
                'birthDate': '1980-01-01'
            }],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92
        )
        
        has_conflict, reason = parsed_data.check_quick_conflicts()
        
        # Should NOT conflict - case-insensitive match
        self.assertFalse(has_conflict)
        self.assertEqual(reason, '')
    
    def test_integration_with_determine_review_status(self):
        """Test that conflicts detected by check_quick_conflicts trigger flagging in determine_review_status"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {
                    'resourceType': 'Patient',
                    'name': [{'given': ['Jane'], 'family': 'Smith'}],
                    'birthDate': '1985-05-15'
                },
                {'resourceType': 'Observation', 'id': '1'},
                {'resourceType': 'Condition', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
            ],  # 4 resources total - passes resource count check
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,  # High confidence - passes confidence check
            fallback_method_used=''  # Primary model - passes fallback check
        )
        
        # Even with high confidence and good resource count,
        # patient conflict should trigger flagging
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('Patient data conflict', reason)
        self.assertIn('DOB mismatch', reason)


class ReviewStatusChoicesTests(TestCase):
    """
    Tests for the 5-state review_status machine in ParsedData model (Task 41.2).
    States: pending, auto_approved, flagged, reviewed, rejected
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
    
    def test_review_status_choices_contains_all_5_states(self):
        """Test that REVIEW_STATUS_CHOICES contains exactly 5 states"""
        choices = ParsedData.REVIEW_STATUS_CHOICES
        self.assertEqual(len(choices), 5)
        
        # Extract choice keys
        choice_keys = [choice[0] for choice in choices]
        
        # Verify all 5 states exist
        self.assertIn('pending', choice_keys)
        self.assertIn('auto_approved', choice_keys)
        self.assertIn('flagged', choice_keys)
        self.assertIn('reviewed', choice_keys)
        self.assertIn('rejected', choice_keys)
    
    def test_review_status_default_is_pending(self):
        """Test that new ParsedData defaults to 'pending' status"""
        self.assertEqual(self.parsed_data.review_status, 'pending')
    
    def test_review_status_can_be_set_to_pending(self):
        """Test that review_status can be set to 'pending'"""
        self.parsed_data.review_status = 'pending'
        self.parsed_data.save()
        
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.review_status, 'pending')
    
    def test_review_status_can_be_set_to_auto_approved(self):
        """Test that review_status can be set to 'auto_approved'"""
        self.parsed_data.review_status = 'auto_approved'
        self.parsed_data.save()
        
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.review_status, 'auto_approved')
    
    def test_review_status_can_be_set_to_flagged(self):
        """Test that review_status can be set to 'flagged'"""
        self.parsed_data.review_status = 'flagged'
        self.parsed_data.save()
        
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.review_status, 'flagged')
    
    def test_review_status_can_be_set_to_reviewed(self):
        """Test that review_status can be set to 'reviewed'"""
        self.parsed_data.review_status = 'reviewed'
        self.parsed_data.save()
        
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.review_status, 'reviewed')
    
    def test_review_status_can_be_set_to_rejected(self):
        """Test that review_status can be set to 'rejected'"""
        self.parsed_data.review_status = 'rejected'
        self.parsed_data.save()
        
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.review_status, 'rejected')
    
    def test_approve_extraction_sets_status_to_reviewed(self):
        """Test that approve_extraction() sets status to 'reviewed' (not 'approved')"""
        self.parsed_data.approve_extraction(self.user, "Test approval")
        
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.review_status, 'reviewed')
        self.assertTrue(self.parsed_data.is_approved)
        self.assertEqual(self.parsed_data.reviewed_by, self.user)
        self.assertIsNotNone(self.parsed_data.reviewed_at)
    
    def test_reject_extraction_sets_status_to_rejected(self):
        """Test that reject_extraction() sets status to 'rejected'"""
        self.parsed_data.reject_extraction(self.user, "Test rejection reason")
        
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.review_status, 'rejected')
        self.assertFalse(self.parsed_data.is_approved)
        self.assertEqual(self.parsed_data.reviewed_by, self.user)
        self.assertEqual(self.parsed_data.rejection_reason, "Test rejection reason")
    
    def test_query_by_review_status(self):
        """Test querying ParsedData by different review_status values"""
        # Create additional parsed data with different statuses
        statuses_to_test = ['auto_approved', 'flagged', 'reviewed', 'rejected']
        
        for i, status in enumerate(statuses_to_test):
            pdf_file = SimpleUploadedFile(
                f'test_doc_{i}.pdf',
                b'%PDF-1.4 fake',
                content_type='application/pdf'
            )
            doc = Document.objects.create(
                patient=self.patient,
                uploaded_by=self.user,
                filename=f'test_doc_{i}.pdf',
                file=pdf_file
            )
            ParsedData.objects.create(
                document=doc,
                patient=self.patient,
                extraction_json={'test': f'data_{i}'},
                fhir_delta_json={'resourceType': 'Observation'},
                review_status=status
            )
        
        # Query for each status and verify count
        self.assertEqual(ParsedData.objects.filter(review_status='pending').count(), 1)
        self.assertEqual(ParsedData.objects.filter(review_status='auto_approved').count(), 1)
        self.assertEqual(ParsedData.objects.filter(review_status='flagged').count(), 1)
        self.assertEqual(ParsedData.objects.filter(review_status='reviewed').count(), 1)
        self.assertEqual(ParsedData.objects.filter(review_status='rejected').count(), 1)
    
    def test_review_status_field_is_indexed(self):
        """Test that review_status field has database index"""
        field = ParsedData._meta.get_field('review_status')
        self.assertTrue(field.db_index)
    
    def test_old_approved_status_not_in_choices(self):
        """Test that the old 'approved' status is NOT in the choices"""
        choice_keys = [choice[0] for choice in ParsedData.REVIEW_STATUS_CHOICES]
        self.assertNotIn('approved', choice_keys)
    
    def test_state_transition_pending_to_auto_approved(self):
        """Test state transition: pending -> auto_approved"""
        self.assertEqual(self.parsed_data.review_status, 'pending')
        
        self.parsed_data.review_status = 'auto_approved'
        self.parsed_data.auto_approved = True
        self.parsed_data.save()
        
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.review_status, 'auto_approved')
        self.assertTrue(self.parsed_data.auto_approved)
    
    def test_state_transition_pending_to_flagged(self):
        """Test state transition: pending -> flagged"""
        self.assertEqual(self.parsed_data.review_status, 'pending')
        
        self.parsed_data.review_status = 'flagged'
        self.parsed_data.flag_reason = "Low confidence extraction"
        self.parsed_data.save()
        
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.review_status, 'flagged')
        self.assertEqual(self.parsed_data.flag_reason, "Low confidence extraction")
    
    def test_state_transition_flagged_to_reviewed(self):
        """Test state transition: flagged -> reviewed (human approval)"""
        self.parsed_data.review_status = 'flagged'
        self.parsed_data.save()
        
        # Human reviews and approves
        self.parsed_data.approve_extraction(self.user, "Verified by human")
        
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.review_status, 'reviewed')
    
    def test_state_transition_flagged_to_rejected(self):
        """Test state transition: flagged -> rejected (human rejection)"""
        self.parsed_data.review_status = 'flagged'
        self.parsed_data.save()
        
        # Human reviews and rejects
        self.parsed_data.reject_extraction(self.user, "Data quality issues")
        
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.review_status, 'rejected')
    
    def test_invalid_status_value_raises_error(self):
        """Test that setting an invalid status value raises ValidationError"""
        from django.core.exceptions import ValidationError
        
        # Try to set invalid status
        self.parsed_data.review_status = 'invalid_status'
        
        # Django should raise ValidationError on full_clean()
        with self.assertRaises(ValidationError) as context:
            self.parsed_data.full_clean()
        
        # Verify the error is for review_status field
        self.assertIn('review_status', context.exception.message_dict)
    
    def test_old_approved_status_is_invalid(self):
        """Test that the old 'approved' status is no longer valid"""
        from django.core.exceptions import ValidationError
        
        # Try to set old 'approved' status
        self.parsed_data.review_status = 'approved'
        
        # Should raise ValidationError
        with self.assertRaises(ValidationError) as context:
            self.parsed_data.full_clean()
        
        self.assertIn('review_status', context.exception.message_dict)
    
    def test_review_status_choices_have_correct_display_names(self):
        """Test that all status choices have appropriate display names"""
        choices_dict = dict(ParsedData.REVIEW_STATUS_CHOICES)
        
        # Verify display names are meaningful
        self.assertEqual(choices_dict['pending'], 'Pending Processing')
        self.assertEqual(choices_dict['auto_approved'], 'Auto-Approved - Merged Immediately')
        self.assertEqual(choices_dict['flagged'], 'Flagged - Needs Manual Review')
        self.assertEqual(choices_dict['reviewed'], 'Reviewed - Manually Approved')
        self.assertEqual(choices_dict['rejected'], 'Rejected - Do Not Use')
    
    def test_multiple_parsed_data_can_have_different_statuses(self):
        """Test that different ParsedData records can have different statuses simultaneously"""
        # Create 5 documents with different statuses
        statuses = ['pending', 'auto_approved', 'flagged', 'reviewed', 'rejected']
        created_records = []
        
        for i, status in enumerate(statuses):
            pdf_file = SimpleUploadedFile(
                f'multi_status_{i}.pdf',
                b'%PDF-1.4 fake',
                content_type='application/pdf'
            )
            doc = Document.objects.create(
                patient=self.patient,
                uploaded_by=self.user,
                filename=f'multi_status_{i}.pdf',
                file=pdf_file
            )
            parsed = ParsedData.objects.create(
                document=doc,
                patient=self.patient,
                extraction_json={'test': f'data_{i}'},
                fhir_delta_json={'resourceType': 'Observation'},
                review_status=status
            )
            created_records.append(parsed)
        
        # Verify all records exist with correct statuses
        for i, status in enumerate(statuses):
            created_records[i].refresh_from_db()
            self.assertEqual(created_records[i].review_status, status)
    
    def test_status_persists_across_save_operations(self):
        """Test that status doesn't get reset when updating other fields"""
        # Set to auto_approved
        self.parsed_data.review_status = 'auto_approved'
        self.parsed_data.auto_approved = True
        self.parsed_data.save()
        
        # Update a different field
        self.parsed_data.extraction_confidence = 0.95
        self.parsed_data.save()
        
        # Status should remain unchanged
        self.parsed_data.refresh_from_db()
        self.assertEqual(self.parsed_data.review_status, 'auto_approved')
        self.assertTrue(self.parsed_data.auto_approved)


class DetermineReviewStatusTests(TestCase):
    """
    Tests for the determine_review_status() method in ParsedData model (Task 41.3).
    Tests all flag conditions and auto-approval logic.
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
    
    def test_high_confidence_with_resources_auto_approves(self):
        """Test that high confidence extraction with resources is auto-approved"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {'resourceType': 'Condition', 'id': '1'},
                {'resourceType': 'Observation', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_low_confidence_flags_for_review(self):
        """Test that low confidence (<0.80) triggers flagging"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.65,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('0.65', reason)
        self.assertIn('0.80', reason)
        self.assertIn('confidence', reason.lower())
    
    def test_none_confidence_flags_for_review(self):
        """Test that missing confidence score triggers flagging"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=None,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('unknown', reason.lower())
        self.assertIn('confidence', reason.lower())
    
    def test_fallback_method_flags_for_review(self):
        """Test that using fallback extraction method triggers flagging"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}],
            ai_model_used='gpt-3.5-turbo',
            extraction_confidence=0.85,
            fallback_method_used='gpt-fallback'
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('gpt-fallback', reason)
        self.assertIn('fallback', reason.lower())
    
    def test_zero_resources_flags_for_review(self):
        """Test that zero extracted resources triggers flagging"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],  # Empty list
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('zero', reason.lower())
        self.assertIn('resources', reason.lower())
    
    def test_low_resource_count_with_medium_confidence_flags(self):
        """Test that <3 resources with <0.95 confidence triggers flagging"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {'resourceType': 'Condition', 'id': '1'},
                {'resourceType': 'Observation', 'id': '2'},
            ],  # Only 2 resources
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.88,  # < 0.95
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('2', reason)  # Resource count
        self.assertIn('0.88', reason)  # Confidence
        self.assertIn('resource count', reason.lower())
    
    def test_low_resource_count_with_high_confidence_auto_approves(self):
        """Test that <3 resources with >=0.95 confidence auto-approves"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {'resourceType': 'Condition', 'id': '1'},
                {'resourceType': 'Observation', 'id': '2'},
            ],  # Only 2 resources
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.96,  # >= 0.95
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_exactly_3_resources_with_medium_confidence_auto_approves(self):
        """Test that exactly 3 resources with any confidence auto-approves"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {'resourceType': 'Condition', 'id': '1'},
                {'resourceType': 'Observation', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
            ],  # Exactly 3 resources
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.82,  # < 0.95 but >= 0.80
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_confidence_at_threshold_boundary_80(self):
        """Test extraction with confidence exactly at 0.80 threshold"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.80,  # Exactly at threshold
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # At threshold should auto-approve
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_confidence_just_below_threshold(self):
        """Test extraction with confidence just below 0.80 threshold"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.79,  # Just below threshold
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('0.79', reason)
    
    def test_multiple_flag_conditions_returns_first_match(self):
        """Test that when multiple flag conditions exist, first one is returned"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],  # Zero resources
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.65,  # Low confidence
            fallback_method_used='regex'  # Fallback used
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # Should return first flag condition (low confidence)
        self.assertEqual(status, 'flagged')
        self.assertIn('confidence', reason.lower())
    
    def test_determine_review_status_performance(self):
        """Test that determine_review_status executes in < 100ms"""
        import time
        
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 10,
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        # Measure execution time
        start_time = time.time()
        status, reason = parsed_data.determine_review_status()
        execution_time = (time.time() - start_time) * 1000  # Convert to ms
        
        # Should complete in < 100ms
        self.assertLess(execution_time, 100, 
                       f"determine_review_status took {execution_time:.2f}ms, exceeds 100ms target")
    
    def test_dict_format_fhir_resources_counted_correctly(self):
        """Test that legacy dict format FHIR resources are counted correctly"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json={
                'Condition': [{'id': '1'}, {'id': '2'}],
                'Observation': [{'id': '3'}],
            },  # Dict format with 3 total resources
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.85,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # Should auto-approve (3 resources, good confidence)
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')

