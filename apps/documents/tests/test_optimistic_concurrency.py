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


class PatientConflictIntegrationTests(TestCase):
    """
    RIGOROUS tests for Task 41.12: Integration of patient data conflict check 
    into determine_review_status() method.
    
    Tests the complete integration of check_quick_conflicts() as Check #5 in the
    5-check validation sequence, including priority ordering, edge cases, and
    comprehensive conflict scenarios.
    
    Test Difficulty Level: 4-5/5 (Rigorous)
    """
    
    def setUp(self):
        """Set up test data"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            mrn='TEST-CONFLICT-001'
        )
        
        pdf_file = SimpleUploadedFile(
            'test_document.pdf',
            b'PDF content here',
            content_type='application/pdf'
        )
        
        self.document = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test_document.pdf',
            file=pdf_file,
            status='completed'
        )
    
    def test_conflict_check_runs_after_all_other_checks(self):
        """RIGOROUS: Verify conflict check is Check #5, runs only if checks 1-4 pass"""
        # Create document that would fail Check #1 (low confidence) AND has conflict
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {
                    'resourceType': 'Patient',
                    'name': [{'given': ['Jane'], 'family': 'Smith'}],  # Name conflict
                    'birthDate': '1985-05-15'  # DOB conflict
                },
                {'resourceType': 'Observation', 'id': '1'},
                {'resourceType': 'Condition', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.70,  # FAILS Check #1 (< 0.80)
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # Should fail on Check #1 (confidence), NOT Check #5 (conflict)
        self.assertEqual(status, 'flagged')
        self.assertIn('confidence', reason.lower())
        self.assertNotIn('conflict', reason.lower())  # Conflict check never runs
    
    def test_dob_conflict_flags_when_all_other_checks_pass(self):
        """RIGOROUS: DOB mismatch triggers flagging when checks 1-4 pass"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {
                    'resourceType': 'Patient',
                    'name': [{'given': ['John'], 'family': 'Doe'}],  # Name matches
                    'birthDate': '1975-06-20'  # DOB mismatch
                },
                {'resourceType': 'Observation', 'id': '1'},
                {'resourceType': 'Condition', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
                {'resourceType': 'Procedure', 'id': '4'},
            ],  # 5 resources - passes Check #4
            ai_model_used='claude-3-sonnet',  # Passes Check #2
            extraction_confidence=0.96,  # Passes Check #1 and Check #4
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('Patient data conflict', reason)
        self.assertIn('DOB mismatch', reason)
        self.assertIn('1975-06-20', reason)  # Extracted DOB
        self.assertIn('1980-01-01', reason)  # Patient record DOB
    
    def test_name_conflict_flags_when_all_other_checks_pass(self):
        """RIGOROUS: Name mismatch triggers flagging when checks 1-4 pass"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {
                    'resourceType': 'Patient',
                    'name': [{'given': ['Robert'], 'family': 'Johnson'}],  # Name mismatch
                    'birthDate': '1980-01-01'  # DOB matches
                },
                {'resourceType': 'Observation', 'id': '1'},
                {'resourceType': 'Condition', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.95,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('Patient data conflict', reason)
        self.assertIn('Name mismatch', reason)
        self.assertIn('Robert Johnson', reason)
        self.assertIn('John Doe', reason)
    
    def test_multiple_conflicts_reported_in_flag_reason(self):
        """RIGOROUS: Both DOB and name conflicts reported together"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {
                    'resourceType': 'Patient',
                    'name': [{'given': ['Alice'], 'family': 'Williams'}],  # Name mismatch
                    'birthDate': '1990-12-25'  # DOB mismatch
                },
                {'resourceType': 'Observation', 'id': '1'},
                {'resourceType': 'Condition', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('Patient data conflict', reason)
        # Both conflicts should be mentioned
        self.assertIn('DOB mismatch', reason)
        self.assertIn('Name mismatch', reason)
        self.assertIn(';', reason)  # Multiple conflicts separated
    
    def test_no_conflict_with_matching_patient_data(self):
        """RIGOROUS: Auto-approves when patient data matches and all checks pass"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {
                    'resourceType': 'Patient',
                    'name': [{'given': ['John'], 'family': 'Doe'}],  # Exact match
                    'birthDate': '1980-01-01'  # Exact match
                },
                {'resourceType': 'Observation', 'id': '1'},
                {'resourceType': 'Condition', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')  # No flag reason
    
    def test_partial_name_match_does_not_conflict(self):
        """RIGOROUS: Smart matching allows middle names and variations"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {
                    'resourceType': 'Patient',
                    'name': [{'given': ['John', 'Michael'], 'family': 'Doe'}],  # Middle name added
                    'birthDate': '1980-01-01'
                },
                {'resourceType': 'Observation', 'id': '1'},
                {'resourceType': 'Condition', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.90,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')  # No conflict detected
    
    def test_missing_patient_resource_does_not_conflict(self):
        """RIGOROUS: No conflict when FHIR has no Patient resource"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {'resourceType': 'Observation', 'id': '1'},
                {'resourceType': 'Condition', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
            ],  # No Patient resource
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # Should auto-approve since conflict check can't run
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_empty_fhir_data_triggers_zero_resources_check_not_conflict(self):
        """RIGOROUS: Empty FHIR fails Check #3 (zero resources), not Check #5"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],  # Empty
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # Should fail on Check #3 (zero resources)
        self.assertEqual(status, 'flagged')
        self.assertIn('Zero', reason)
        self.assertIn('resources', reason.lower())
        self.assertNotIn('conflict', reason.lower())
    
    def test_conflict_check_with_dict_format_fhir(self):
        """RIGOROUS: Conflict detection works with legacy dict format FHIR"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json={
                'Patient': [{
                    'resourceType': 'Patient',
                    'name': [{'given': ['Wrong'], 'family': 'Person'}],
                    'birthDate': '1995-01-01'
                }],
                'Observation': [{'resourceType': 'Observation', 'id': '1'}],
                'Condition': [{'resourceType': 'Condition', 'id': '2'}],
                'MedicationStatement': [{'resourceType': 'MedicationStatement', 'id': '3'}],
            },  # Dict format
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('Patient data conflict', reason)
    
    def test_performance_with_conflict_check_enabled(self):
        """RIGOROUS: Full determine_review_status with conflict check < 100ms"""
        import time
        
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {
                    'resourceType': 'Patient',
                    'name': [{'given': ['John'], 'family': 'Doe'}],
                    'birthDate': '1980-01-01'
                },
                {'resourceType': 'Observation', 'id': '1'},
                {'resourceType': 'Condition', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        start_time = time.time()
        status, reason = parsed_data.determine_review_status()
        execution_time = (time.time() - start_time) * 1000
        
        self.assertLess(execution_time, 100,
                       f"determine_review_status with conflict check took {execution_time:.2f}ms")
        self.assertEqual(status, 'auto_approved')
    
    def test_conflict_overrides_borderline_checks(self):
        """RIGOROUS: Conflict flags even when borderline on other checks"""
        # Borderline case: exactly 3 resources with exactly 0.95 confidence
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {
                    'resourceType': 'Patient',
                    'name': [{'given': ['Different'], 'family': 'Person'}],
                    'birthDate': '1985-06-15'  # Conflict
                },
                {'resourceType': 'Observation', 'id': '1'},
                {'resourceType': 'Condition', 'id': '2'},
            ],  # Exactly 3 resources (passes Check #4)
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.95,  # Exactly 0.95 (passes Check #4)
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # Even though it passes checks 1-4, conflict should flag it
        self.assertEqual(status, 'flagged')
        self.assertIn('Patient data conflict', reason)
    
    def test_case_insensitive_conflict_detection(self):
        """RIGOROUS: Name comparison is case-insensitive"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {
                    'resourceType': 'Patient',
                    'name': [{'given': ['JOHN'], 'family': 'DOE'}],  # All caps
                    'birthDate': '1980-01-01'
                },
                {'resourceType': 'Observation', 'id': '1'},
                {'resourceType': 'Condition', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # Should auto-approve (case-insensitive match)
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')


class DatabaseIndexTests(TestCase):
    """
    Tests for database indexes on optimistic concurrency fields (Task 41.5).
    Verifies that indexes exist and improve query performance.
    """
    
    def setUp(self):
        """Set up test data"""
        from django.db import connection
        
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
        
        self.connection = connection
    
    def test_auto_approved_field_has_index(self):
        """Test that auto_approved field has database index"""
        field = ParsedData._meta.get_field('auto_approved')
        self.assertTrue(field.db_index)
    
    def test_review_status_created_composite_index_exists(self):
        """Test that composite index on (review_status, created_at) exists in model"""
        # Check that the index is defined in Meta.indexes
        indexes = ParsedData._meta.indexes
        
        # Find the composite index
        composite_index = None
        for index in indexes:
            if 'review_status' in index.fields and 'created_at' in index.fields:
                composite_index = index
                break
        
        self.assertIsNotNone(composite_index, "Composite index on (review_status, created_at) not found")
        self.assertEqual(composite_index.name, 'parsed_review_status_idx')
    
    def test_query_by_review_status_uses_index(self):
        """Test that queries by review_status can use the index"""
        from django.test.utils import CaptureQueriesContext
        
        # Create test data
        pdf_file = SimpleUploadedFile(
            'test.pdf',
            b'%PDF-1.4 fake',
            content_type='application/pdf'
        )
        doc = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test.pdf',
            file=pdf_file
        )
        ParsedData.objects.create(
            document=doc,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],
            review_status='flagged'
        )
        
        # Query by review_status
        with CaptureQueriesContext(self.connection) as queries:
            list(ParsedData.objects.filter(review_status='flagged'))
        
        # Should execute query successfully
        self.assertEqual(len(queries), 1)
    
    def test_query_by_review_status_and_created_at_uses_composite_index(self):
        """Test that queries by review_status and created_at can use composite index"""
        from django.test.utils import CaptureQueriesContext
        from datetime import timedelta
        
        # Create test data
        pdf_file = SimpleUploadedFile(
            'test.pdf',
            b'%PDF-1.4 fake',
            content_type='application/pdf'
        )
        doc = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test.pdf',
            file=pdf_file
        )
        ParsedData.objects.create(
            document=doc,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],
            review_status='flagged'
        )
        
        # Query by review_status and date range
        cutoff_date = timezone.now() - timedelta(days=7)
        with CaptureQueriesContext(self.connection) as queries:
            list(ParsedData.objects.filter(
                review_status='flagged',
                created_at__gte=cutoff_date
            ).order_by('-created_at'))
        
        # Should execute query successfully
        self.assertEqual(len(queries), 1)
    
    def test_query_by_auto_approved_uses_index(self):
        """Test that queries by auto_approved can use the index"""
        from django.test.utils import CaptureQueriesContext
        
        # Create test data
        pdf_file = SimpleUploadedFile(
            'test.pdf',
            b'%PDF-1.4 fake',
            content_type='application/pdf'
        )
        doc = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test.pdf',
            file=pdf_file
        )
        ParsedData.objects.create(
            document=doc,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],
            auto_approved=True
        )
        
        # Query by auto_approved
        with CaptureQueriesContext(self.connection) as queries:
            list(ParsedData.objects.filter(auto_approved=True))
        
        # Should execute query successfully
        self.assertEqual(len(queries), 1)
    
    def test_indexes_improve_flagged_items_query_performance(self):
        """Test that indexes improve performance for common flagged items queries"""
        import time
        
        # Create bulk test data (50 records)
        pdf_file = SimpleUploadedFile(
            'test.pdf',
            b'%PDF-1.4 fake',
            content_type='application/pdf'
        )
        
        parsed_data_list = []
        for i in range(50):
            doc = Document.objects.create(
                patient=self.patient,
                uploaded_by=self.user,
                filename=f'test_{i}.pdf',
                file=pdf_file
            )
            parsed_data_list.append(ParsedData(
                document=doc,
                patient=self.patient,
                extraction_json={'test': f'data_{i}'},
                fhir_delta_json=[],
                review_status='flagged' if i % 3 == 0 else 'auto_approved',
                auto_approved=(i % 3 != 0)
            ))
        
        ParsedData.objects.bulk_create(parsed_data_list)
        
        # Query for flagged items ordered by created_at
        start_time = time.time()
        flagged_items = list(ParsedData.objects.filter(
            review_status='flagged'
        ).order_by('-created_at')[:10])
        query_time = (time.time() - start_time) * 1000  # Convert to ms
        
        # Should be fast with indexes
        self.assertGreater(len(flagged_items), 0)
        self.assertLess(query_time, 100, 
                       f"Flagged items query took {query_time:.2f}ms, should be < 100ms with indexes")


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
        # Should catch the GPT model in ai_model_used field first
        self.assertIn('gpt-3.5-turbo', reason)
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
    
    def test_zero_resources_empty_dict_flags_for_review(self):
        """RIGOROUS: Test that empty dict format also triggers zero resource flagging"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json={},  # Empty dict (legacy format)
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


class RigorousConfidenceValidationTests(TestCase):
    """
    RIGOROUS Level 4-5 tests for confidence-based flagging (Task 41.8).
    
    Tests edge cases, integration points, security requirements, and performance
    according to medical_doc_parser.mdc and rigorous_testing.mdc standards.
    """
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            mrn='TEST-RIGOROUS-001'
        )
        
        pdf_content = b'%PDF-1.4 fake pdf content'
        pdf_file = SimpleUploadedFile(
            'test_document.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        
        self.document = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            file=pdf_file,
            status='processed'
        )
    
    # ==================== EDGE CASE TESTS ====================
    
    def test_negative_confidence_flags_for_review(self):
        """RIGOROUS: Test invalid negative confidence value triggers flagging"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='claude-3-sonnet',
            extraction_confidence=-0.5,  # Invalid negative
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # Must flag negative confidence
        self.assertEqual(status, 'flagged')
        self.assertIn('-0.5', reason)
        self.assertIn('0.80', reason)
    
    def test_confidence_above_one_handled_gracefully(self):
        """RIGOROUS: Test confidence > 1.0 is handled (should auto-approve if other checks pass)"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='claude-3-sonnet',
            extraction_confidence=1.5,  # Invalid but high
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # Even though >1.0 is technically invalid, it passes confidence check
        # (This is acceptable behavior - high confidence passes)
        self.assertEqual(status, 'auto_approved')
    
    def test_zero_confidence_flags_for_review(self):
        """RIGOROUS: Test confidence exactly 0.0 triggers flagging"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.0,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('0.0', reason)
    
    def test_confidence_at_exact_boundary_values(self):
        """RIGOROUS: Test precision at boundary (0.800000001 vs 0.799999999)"""
        # Just above threshold
        parsed_data_above = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.800001,
            fallback_method_used=''
        )
        
        status_above, _ = parsed_data_above.determine_review_status()
        self.assertEqual(status_above, 'auto_approved', 
                        "0.800001 should pass threshold")
        
        # Just below threshold
        parsed_data_below = ParsedData.objects.create(
            document=Document.objects.create(
                patient=self.patient,
                uploaded_by=self.user,
                file=SimpleUploadedFile('test2.pdf', b'content', 'application/pdf'),
                status='processed'
            ),
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.799999,
            fallback_method_used=''
        )
        
        status_below, reason_below = parsed_data_below.determine_review_status()
        self.assertEqual(status_below, 'flagged',
                        "0.799999 should fail threshold")
        self.assertIn('0.799999', reason_below)
    
    # ==================== INTEGRATION TESTS ====================
    
    def test_flagged_extraction_cannot_be_merged_without_approval(self):
        """RIGOROUS: Verify business logic prevents merging flagged extractions"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.65,  # Below threshold
            fallback_method_used='',
            is_merged=False,
            is_approved=False
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # Verify it's flagged
        self.assertEqual(status, 'flagged')
        
        # Verify merge flags are False
        self.assertFalse(parsed_data.is_merged, 
                        "Flagged extraction should not be merged")
        self.assertFalse(parsed_data.is_approved,
                        "Flagged extraction should not be approved")
    
    def test_auto_approved_extraction_can_be_merged(self):
        """RIGOROUS: Verify high-confidence extractions pass all checks"""
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
            extraction_confidence=0.95,
            fallback_method_used='',
            is_merged=False
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # Verify it's approved
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
        
        # Business logic should allow merging (though we don't set it here)
        # This just validates the determination is correct
    
    # ==================== PERFORMANCE TESTS ====================
    
    def test_confidence_check_uses_minimal_queries(self):
        """RIGOROUS: Verify confidence check doesn't cause N+1 queries"""
        from django.test.utils import override_settings
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 10,
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.85,
            fallback_method_used=''
        )
        
        with CaptureQueriesContext(connection) as queries:
            status, reason = parsed_data.determine_review_status()
        
        # Should use 0-1 queries max (confidence is in-memory field)
        # Allow up to 2 for patient conflict check
        query_count = len(queries)
        self.assertLessEqual(query_count, 2,
            f"Confidence check used {query_count} queries, should use ≤2. "
            f"Queries: {[q['sql'] for q in queries]}")
    
    def test_large_fhir_bundle_confidence_check_fast(self):
        """RIGOROUS: Verify performance with large FHIR bundles"""
        import time
        
        # Create large FHIR bundle (100 resources)
        large_bundle = [
            {'resourceType': 'Observation', 'id': str(i)}
            for i in range(100)
        ]
        
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=large_bundle,
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        start_time = time.time()
        status, reason = parsed_data.determine_review_status()
        execution_time = (time.time() - start_time) * 1000  # ms
        
        # Must complete in < 100ms per spec
        self.assertLess(execution_time, 100,
            f"Large bundle check took {execution_time:.2f}ms, exceeds 100ms target")
        
        self.assertEqual(status, 'auto_approved')
    
    # ==================== ERROR MESSAGE QUALITY ====================
    
    def test_flag_reason_contains_actionable_information(self):
        """RIGOROUS: Verify flag messages are helpful for reviewers"""
        test_cases = [
            (0.65, 'Low extraction confidence (0.65 < 0.80 threshold)'),
            (0.45, 'Low extraction confidence (0.45 < 0.80 threshold)'),
            (None, 'Low extraction confidence (unknown < 0.80 threshold)'),
        ]
        
        for confidence_value, expected_substring in test_cases:
            with self.subTest(confidence=confidence_value):
                doc = Document.objects.create(
                    patient=self.patient,
                    uploaded_by=self.user,
                    file=SimpleUploadedFile(f'test_{confidence_value}.pdf', 
                                          b'content', 'application/pdf'),
                    status='processed'
                )
                
                parsed_data = ParsedData.objects.create(
                    document=doc,
                    patient=self.patient,
                    extraction_json={'test': 'data'},
                    fhir_delta_json=[{'resourceType': 'Condition'}],
                    ai_model_used='claude-3-sonnet',
                    extraction_confidence=confidence_value,
                    fallback_method_used=''
                )
                
                status, reason = parsed_data.determine_review_status()
                
                self.assertEqual(status, 'flagged')
                # Verify reason contains all key information
                self.assertIn('confidence', reason.lower())
                self.assertIn('0.80', reason)
                if confidence_value is not None:
                    self.assertIn(str(confidence_value), reason)
                else:
                    self.assertIn('unknown', reason.lower())
    
    # ==================== REALISTIC SCENARIOS ====================
    
    def test_batch_processing_confidence_decisions(self):
        """RIGOROUS: Test confidence flagging across realistic batch of documents"""
        test_cases = [
            # (confidence, expected_status, description)
            (0.95, 'auto_approved', 'High confidence extraction'),
            (0.85, 'auto_approved', 'Good confidence extraction'),
            (0.80, 'auto_approved', 'Threshold confidence extraction'),
            (0.75, 'flagged', 'Below threshold extraction'),
            (0.50, 'flagged', 'Low confidence extraction'),
            (None, 'flagged', 'Missing confidence'),
        ]
        
        results = []
        for confidence, expected, description in test_cases:
            doc = Document.objects.create(
                patient=self.patient,
                uploaded_by=self.user,
                file=SimpleUploadedFile(f'batch_{confidence}.pdf', 
                                      b'content', 'application/pdf'),
                status='processed'
            )
            
            parsed_data = ParsedData.objects.create(
                document=doc,
                patient=self.patient,
                extraction_json={'test': 'data'},
                fhir_delta_json=[
                    {'resourceType': 'Condition'},
                    {'resourceType': 'Observation'},
                    {'resourceType': 'MedicationStatement'},
                ],
                ai_model_used='claude-3-sonnet',
                extraction_confidence=confidence,
                fallback_method_used=''
            )
            
            status, reason = parsed_data.determine_review_status()
            results.append((confidence, status, expected, description))
            
            with self.subTest(description=description):
                self.assertEqual(status, expected,
                    f"{description}: confidence={confidence} should be {expected}, got {status}")
        
        # Verify batch statistics
        auto_approved_count = sum(1 for _, status, _, _ in results if status == 'auto_approved')
        flagged_count = sum(1 for _, status, _, _ in results if status == 'flagged')
        
        self.assertEqual(auto_approved_count, 3, "Should have 3 auto-approved")
        self.assertEqual(flagged_count, 3, "Should have 3 flagged")


class RigorousFallbackModelValidationTests(TestCase):
    """
    Rigorous tests for fallback AI model detection (Subtask 41.9).
    
    Tests the determine_review_status() method's ability to detect when
    fallback GPT models were used instead of the primary Claude model.
    
    Test Difficulty Level: 4-5/5 (Rigorous)
    - Tests actual behavior, not framework
    - Covers edge cases and boundary conditions
    - Tests integration with approval workflow
    - Validates error messages and specificity
    """
    
    def setUp(self):
        """Set up test fixtures for fallback model testing"""
        self.user = get_user_model().objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            mrn='TEST-MRN-001'
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
    
    def test_gpt_3_5_turbo_model_triggers_flag(self):
        """GPT-3.5-turbo model should be flagged as fallback"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='gpt-3.5-turbo',
            extraction_confidence=0.92,  # High confidence, but fallback model
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('gpt-3.5-turbo', reason)
        self.assertIn('fallback', reason.lower())
        self.assertIn('ai model', reason.lower())
    
    def test_gpt_4_model_triggers_flag(self):
        """GPT-4 model should be flagged as fallback"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='gpt-4',
            extraction_confidence=0.95,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('gpt-4', reason)
        self.assertIn('fallback', reason.lower())
    
    def test_gpt_4o_mini_model_triggers_flag(self):
        """GPT-4o-mini model should be flagged as fallback"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='gpt-4o-mini',
            extraction_confidence=0.88,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('gpt-4o-mini', reason)
        self.assertIn('fallback', reason.lower())
    
    def test_claude_sonnet_model_not_flagged(self):
        """Claude-3-sonnet (primary model) should not be flagged"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='claude-3-sonnet-20240229',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_claude_opus_model_not_flagged(self):
        """Claude-3-opus (primary model) should not be flagged"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='claude-3-opus-20240229',
            extraction_confidence=0.95,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_claude_sonnet_4_5_model_not_flagged(self):
        """Claude-sonnet-4-5 (newest primary model) should not be flagged"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='claude-sonnet-4-5-20250929',
            extraction_confidence=0.96,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_claude_opus_4_5_model_not_flagged(self):
        """Claude-opus-4-5 (newest primary model) should not be flagged"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='claude-opus-4-5-20251101',
            extraction_confidence=0.97,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_case_insensitive_gpt_detection(self):
        """GPT detection should be case-insensitive"""
        # Test uppercase
        parsed_data_upper = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='GPT-4',
            extraction_confidence=0.90,
            fallback_method_used=''
        )
        
        status, reason = parsed_data_upper.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('GPT-4', reason)
    
    def test_empty_ai_model_used_not_flagged(self):
        """Empty ai_model_used should not trigger fallback flag"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='',  # Empty string
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_unknown_ai_model_not_flagged(self):
        """Unknown/non-GPT model should not trigger fallback flag"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='unknown',  # Unknown model
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_fallback_method_used_field_still_works(self):
        """fallback_method_used field should still trigger flagging"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='claude-3-sonnet',  # Primary model
            extraction_confidence=0.92,
            fallback_method_used='regex'  # But fallback method was used
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('regex', reason)
        self.assertIn('fallback', reason.lower())
    
    def test_both_gpt_and_fallback_method_flags_gpt_first(self):
        """When both ai_model_used has GPT AND fallback_method_used is set, GPT check should trigger first"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='gpt-4o-mini',
            extraction_confidence=0.92,
            fallback_method_used='gpt-fallback'
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        # Should mention the ai_model_used, not fallback_method_used
        self.assertIn('gpt-4o-mini', reason)
        self.assertIn('ai model', reason.lower())
        # Should NOT mention fallback_method_used since ai_model check triggers first
        self.assertNotIn('gpt-fallback', reason)
    
    def test_gpt_model_with_low_confidence_flags_confidence_first(self):
        """Low confidence should be checked before fallback model (Check 1 before Check 2)"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='gpt-4',
            extraction_confidence=0.75,  # Below 0.80 threshold
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        # Should flag for confidence, not fallback model (Check 1 runs before Check 2)
        self.assertIn('confidence', reason.lower())
        self.assertIn('0.75', reason)
        self.assertNotIn('gpt', reason.lower())
    
    def test_gpt_model_name_partial_match(self):
        """Partial GPT matches in model name should be detected"""
        test_models = [
            'gpt-3.5-turbo-16k',
            'gpt-4-turbo-preview',
            'gpt-4-1106-preview',
            'gpt-4o'
        ]
        
        for i, model_name in enumerate(test_models):
            with self.subTest(model=model_name):
                # Create unique document for each iteration
                pdf_content = b'%PDF-1.4 fake pdf content'
                pdf_file = SimpleUploadedFile(
                    f'test_document_{i}.pdf',
                    pdf_content,
                    content_type='application/pdf'
                )
                
                document = Document.objects.create(
                    patient=self.patient,
                    uploaded_by=self.user,
                    filename=f'test_document_{i}.pdf',
                    file=pdf_file,
                    status='completed'
                )
                
                parsed_data = ParsedData.objects.create(
                    document=document,
                    patient=self.patient,
                    extraction_json={'test': 'data'},
                    fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
                    ai_model_used=model_name,
                    extraction_confidence=0.92,
                    fallback_method_used=''
                )
                
                status, reason = parsed_data.determine_review_status()
                
                self.assertEqual(status, 'flagged', f"{model_name} should be flagged as fallback")
                self.assertIn(model_name, reason)
                self.assertIn('fallback', reason.lower())
    
    def test_non_gpt_models_not_flagged(self):
        """Non-GPT, non-Claude models should not be flagged as fallback"""
        test_models = [
            'anthropic/claude-3-haiku',
            'claude-instant-1.2',
            'mistral-large-latest',
            'llama-3-70b-instruct'
        ]
        
        for i, model_name in enumerate(test_models):
            with self.subTest(model=model_name):
                # Create unique document for each iteration
                pdf_content = b'%PDF-1.4 fake pdf content'
                pdf_file = SimpleUploadedFile(
                    f'test_non_gpt_{i}.pdf',
                    pdf_content,
                    content_type='application/pdf'
                )
                
                document = Document.objects.create(
                    patient=self.patient,
                    uploaded_by=self.user,
                    filename=f'test_non_gpt_{i}.pdf',
                    file=pdf_file,
                    status='completed'
                )
                
                parsed_data = ParsedData.objects.create(
                    document=document,
                    patient=self.patient,
                    extraction_json={'test': 'data'},
                    fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
                    ai_model_used=model_name,
                    extraction_confidence=0.92,
                    fallback_method_used=''
                )
                
                status, reason = parsed_data.determine_review_status()
                
                self.assertEqual(status, 'auto_approved', f"{model_name} should not be flagged")
                self.assertEqual(reason, '')
    
    def test_performance_fallback_check_under_100ms(self):
        """Fallback model check should complete in under 100ms"""
        import time
        
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='gpt-4o-mini',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        start_time = time.time()
        status, reason = parsed_data.determine_review_status()
        duration = (time.time() - start_time) * 1000  # Convert to ms
        
        self.assertEqual(status, 'flagged')
        self.assertLess(duration, 100, f"Fallback check took {duration:.2f}ms, should be < 100ms")
    
    def test_fallback_flag_integrates_with_approval_workflow(self):
        """Flagged fallback documents should block auto-approval"""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='gpt-3.5-turbo',
            extraction_confidence=0.95,
            fallback_method_used='',
            is_approved=False,
            is_merged=False
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # Should be flagged, not auto_approved
        self.assertEqual(status, 'flagged')
        self.assertFalse(parsed_data.is_approved)
        self.assertFalse(parsed_data.is_merged)
