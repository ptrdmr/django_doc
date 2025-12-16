"""
Comprehensive Unit Tests for Quality Check Logic (Task 41.17)

This test suite provides rigorous testing of the determine_review_status() method
with parametrized testing (using subTest), boundary testing, and combination scenarios.

Test Difficulty: Level 4-5 (Rigorous to Comprehensive)
Coverage Goal: 100% of quality check logic
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from apps.documents.models import Document, ParsedData
from apps.patients.models import Patient

User = get_user_model()


class QualityCheckParametrizedTests(TestCase):
    """
    Parametrized tests for quality check logic.
    Uses subTest with transaction savepoints for efficient testing of multiple scenarios.
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
            mrn='TEST-001'
        )
        
        # Counter for creating unique documents in subTests
        self.document_counter = 0
    
    def create_test_document(self):
        """Helper method to create a unique document for each subTest"""
        self.document_counter += 1
        pdf_content = b'%PDF-1.4 fake pdf content'
        pdf_file = SimpleUploadedFile(
            f'test_document_{self.document_counter}.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        
        return Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename=f'test_document_{self.document_counter}.pdf',
            file=pdf_file,
            status='completed'
        )
    
    def test_confidence_threshold_boundaries(self):
        """
        RIGOROUS: Test confidence threshold at precise boundaries.
        
        Verifies that the 0.80 threshold is correctly enforced with floating-point precision.
        Tests values just below, at, and above the threshold.
        """
        test_cases = [
            # (confidence, expected_status, should_flag)
            # Below threshold
            (0.0, 'flagged', True),
            (0.5, 'flagged', True),
            (0.79, 'flagged', True),
            (0.7999999, 'flagged', True),
            # At threshold (should pass)
            (0.80, 'auto_approved', False),
            (0.8000001, 'auto_approved', False),
            # Above threshold
            (0.85, 'auto_approved', False),
            (0.90, 'auto_approved', False),
            (0.95, 'auto_approved', False),
            (1.0, 'auto_approved', False),
            # None should flag
            (None, 'flagged', True),
        ]
        
        for confidence, expected_status, should_flag in test_cases:
            with self.subTest(confidence=confidence, expected_status=expected_status):
                # Use transaction savepoint for each subTest to handle potential errors
                with transaction.atomic():
                    # Create unique document for this subTest (unique constraint on document_id)
                    document = self.create_test_document()
                    
                    parsed_data = ParsedData.objects.create(
                        document=document,
                        patient=self.patient,
                        extraction_json={'test': 'data'},
                        fhir_delta_json=[
                            {'resourceType': 'Condition', 'id': '1'},
                            {'resourceType': 'Observation', 'id': '2'},
                            {'resourceType': 'MedicationStatement', 'id': '3'},
                        ],
                        ai_model_used='claude-3-sonnet',
                        extraction_confidence=confidence,
                        fallback_method_used=''
                    )
                    
                    status, reason = parsed_data.determine_review_status()
                    
                    self.assertEqual(status, expected_status, 
                                    f'Confidence {confidence} should result in {expected_status}')
                    
                    if should_flag:
                        self.assertIn('confidence', reason.lower(),
                                     f'Confidence {confidence} should mention confidence in flag reason')
                        if confidence is not None:
                            self.assertIn(str(confidence), reason,
                                         f'Flag reason should include actual confidence value: {confidence}')
                    else:
                        self.assertEqual(reason, '',
                                       f'Auto-approved extractions should have empty reason string')
    
    def test_ai_model_detection(self):
        """
        RIGOROUS: Test AI model detection with case-insensitive matching.
        
        Verifies that fallback (GPT) models are correctly detected and flagged.
        Tests various model name formats and case variations.
        """
        test_cases = [
            # (ai_model, expected_status, should_flag)
            # Primary models (should not flag)
            ('claude-3-sonnet', 'auto_approved', False),
            ('claude-3-opus', 'auto_approved', False),
            ('claude-3.5-sonnet', 'auto_approved', False),
            ('CLAUDE-3-SONNET', 'auto_approved', False),  # Case insensitive
            # Fallback models (should flag)
            ('gpt-3.5-turbo', 'flagged', True),
            ('gpt-4', 'flagged', True),
            ('gpt-4-turbo', 'flagged', True),
            ('GPT-4', 'flagged', True),  # Case insensitive
            # Other models (should not flag if no "gpt" in name)
            ('llama-2', 'auto_approved', False),
            ('mistral-7b', 'auto_approved', False),
        ]
        
        for ai_model, expected_status, should_flag in test_cases:
            with self.subTest(ai_model=ai_model):
                # Use transaction savepoint for each subTest to handle potential errors
                with transaction.atomic():
                    # Create unique document for this subTest (unique constraint on document_id)
                    document = self.create_test_document()
                    
                    parsed_data = ParsedData.objects.create(
                        document=document,
                        patient=self.patient,
                        extraction_json={'test': 'data'},
                        fhir_delta_json=[
                            {'resourceType': 'Condition', 'id': '1'},
                            {'resourceType': 'Observation', 'id': '2'},
                            {'resourceType': 'MedicationStatement', 'id': '3'},
                        ],
                        ai_model_used=ai_model,
                        extraction_confidence=0.92,
                        fallback_method_used=''
                    )
                    
                    status, reason = parsed_data.determine_review_status()
                    
                    self.assertEqual(status, expected_status,
                                    f'Model {ai_model} should result in {expected_status}')
                    
                    if should_flag:
                        self.assertIn('fallback', reason.lower(),
                                     f'Model {ai_model} should mention fallback in flag reason')
                        self.assertIn(ai_model, reason,
                                     f'Flag reason should include model name: {ai_model}')
    
    def test_resource_count_and_confidence_combinations(self):
        """
        RIGOROUS: Test resource count thresholds combined with confidence.
        
        Check 4: Fewer than 3 resources AND confidence < 0.95
        This tests the complex interaction between resource count and confidence.
        
        Key Rules:
        - 0 resources: Always flags (Check 3)
        - 1-2 resources: Flags if confidence < 0.95 (Check 4)
        - 3+ resources: Always passes Check 4
        """
        test_cases = [
            # (resource_count, confidence, expected_status)
            # Zero resources (always flags)
            (0, 0.95, 'flagged'),
            (0, 0.99, 'flagged'),
            (0, 1.0, 'flagged'),
            # 1 resource
            (1, 0.94, 'flagged'),  # < 0.95
            (1, 0.95, 'auto_approved'),  # >= 0.95
            (1, 0.96, 'auto_approved'),
            # 2 resources
            (2, 0.94, 'flagged'),
            (2, 0.9499999, 'flagged'),  # Just below
            (2, 0.95, 'auto_approved'),
            (2, 0.9500001, 'auto_approved'),  # Just above
            # 3 resources (always passes regardless of confidence)
            (3, 0.80, 'auto_approved'),
            (3, 0.85, 'auto_approved'),
            (3, 0.94, 'auto_approved'),
            (3, 0.95, 'auto_approved'),
            # 4+ resources (always passes)
            (4, 0.80, 'auto_approved'),
            (5, 0.80, 'auto_approved'),
            (10, 0.80, 'auto_approved'),
        ]
        
        for resource_count, confidence, expected_status in test_cases:
            with self.subTest(resource_count=resource_count, confidence=confidence):
                # Use transaction savepoint for each subTest to handle potential errors
                with transaction.atomic():
                    # Create unique document for this subTest (unique constraint on document_id)
                    document = self.create_test_document()
                    
                    # Create FHIR resources based on resource_count
                    fhir_resources = [
                        {'resourceType': 'Condition', 'id': str(i)}
                        for i in range(resource_count)
                    ]
                    
                    parsed_data = ParsedData.objects.create(
                        document=document,
                        patient=self.patient,
                        extraction_json={'test': 'data'},
                        fhir_delta_json=fhir_resources,
                        ai_model_used='claude-3-sonnet',
                        extraction_confidence=confidence,
                        fallback_method_used=''
                    )
                    
                    status, reason = parsed_data.determine_review_status()
                    
                    self.assertEqual(status, expected_status,
                                    f'{resource_count} resources with {confidence} confidence should result in {expected_status}')
                    
                    if expected_status == 'flagged':
                        if resource_count == 0:
                            self.assertIn('zero', reason.lower())
                        elif resource_count < 3 and confidence < 0.95:
                            self.assertIn('resource count', reason.lower())
                            self.assertIn(str(resource_count), reason)
                            self.assertIn(str(confidence), reason)
    
    def test_fhir_format_compatibility(self):
        """
        RIGOROUS: Test both list and dict FHIR formats are handled correctly.
        
        The system supports two formats:
        - List format: [{'resourceType': 'Condition', ...}, ...]
        - Dict format: {'Condition': [{...}], 'Observation': [{...}]}
        
        Both should correctly count resources and apply quality checks.
        """
        test_cases = [
            # List format (new format)
            [{'resourceType': 'Condition', 'id': '1'}],
            [
                {'resourceType': 'Condition', 'id': '1'},
                {'resourceType': 'Observation', 'id': '2'},
            ],
            # Dict format (legacy format)
            {'Condition': [{'id': '1'}]},
            {
                'Condition': [{'id': '1'}],
                'Observation': [{'id': '2'}],
            },
            # Empty formats
            [],
            {},
            # Dict with empty arrays
            {'Condition': [], 'Observation': []},
        ]
        
        for fhir_format in test_cases:
            with self.subTest(format=type(fhir_format).__name__, data=str(fhir_format)[:50]):
                # Use transaction savepoint for each subTest to handle potential errors
                with transaction.atomic():
                    # Create unique document for this subTest (unique constraint on document_id)
                    document = self.create_test_document()
                    
                    parsed_data = ParsedData.objects.create(
                        document=document,
                        patient=self.patient,
                        extraction_json={'test': 'data'},
                        fhir_delta_json=fhir_format,
                        ai_model_used='claude-3-sonnet',
                        extraction_confidence=0.92,
                        fallback_method_used=''
                    )
                    
                    # Calculate expected resource count
                    if isinstance(fhir_format, list):
                        expected_count = len(fhir_format)
                    elif isinstance(fhir_format, dict):
                        expected_count = sum(len(v) for v in fhir_format.values())
                    else:
                        expected_count = 0
                    
                    # Verify resource count is calculated correctly
                    actual_count = parsed_data.get_fhir_resource_count()
                    self.assertEqual(actual_count, expected_count,
                                    f'Resource count should be {expected_count} for format {type(fhir_format).__name__}')
                    
                    # Verify status determination works
                    status, reason = parsed_data.determine_review_status()
                    
                    if expected_count == 0:
                        self.assertEqual(status, 'flagged')
                        self.assertIn('zero', reason.lower())
                    else:
                        # With 0.92 confidence and >0 resources, should auto-approve if >=3 resources
                        # or flag if <3 resources (since 0.92 < 0.95)
                        if expected_count >= 3:
                            self.assertEqual(status, 'auto_approved')
                        else:
                            self.assertEqual(status, 'flagged')
                            self.assertIn('resource count', reason.lower())


class QualityCheckFlagCombinationsTests(TestCase):
    """
    Tests for multiple flag conditions occurring simultaneously.
    Verifies that the first applicable check triggers and returns the appropriate reason.
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
            mrn='TEST-001'
        )
        
        # Counter for creating unique documents
        self.document_counter = 0
    
    def create_test_document(self):
        """Helper method to create a unique document for each test"""
        self.document_counter += 1
        pdf_content = b'%PDF-1.4 fake pdf content'
        pdf_file = SimpleUploadedFile(
            f'test_document_{self.document_counter}.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        
        return Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename=f'test_document_{self.document_counter}.pdf',
            file=pdf_file,
            status='completed'
        )
    
    def test_low_confidence_and_zero_resources_returns_confidence_flag(self):
        """
        RIGOROUS: Test that Check 1 (confidence) fires before Check 3 (zero resources).
        
        When multiple conditions exist, the first check in sequence should trigger.
        Check order: confidence → fallback → zero resources → low count → conflicts
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],  # Zero resources (Check 3)
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.65,  # Low confidence (Check 1)
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        # Should return confidence flag, not zero resources flag
        self.assertIn('confidence', reason.lower())
        self.assertNotIn('zero', reason.lower())
    
    def test_low_confidence_and_fallback_model_returns_confidence_flag(self):
        """
        RIGOROUS: Test that Check 1 (confidence) fires before Check 2 (fallback).
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='gpt-4',  # Fallback model (Check 2)
            extraction_confidence=0.70,  # Low confidence (Check 1)
            fallback_method_used='gpt-fallback'
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        # Should return confidence flag, not fallback flag
        self.assertIn('confidence', reason.lower())
        self.assertNotIn('fallback', reason.lower())
    
    def test_fallback_model_and_zero_resources_returns_fallback_flag(self):
        """
        RIGOROUS: Test that Check 2 (fallback) fires before Check 3 (zero resources).
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],  # Zero resources (Check 3)
            ai_model_used='gpt-3.5-turbo',  # Fallback model (Check 2)
            extraction_confidence=0.92,  # High confidence (passes Check 1)
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        # Should return fallback flag, not zero resources flag
        self.assertIn('fallback', reason.lower())
        self.assertIn('gpt', reason.lower())
        self.assertNotIn('zero', reason.lower())
    
    def test_fallback_model_and_low_resource_count_returns_fallback_flag(self):
        """
        RIGOROUS: Test that Check 2 (fallback) fires before Check 4 (low resource count).
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {'resourceType': 'Condition', 'id': '1'},
                {'resourceType': 'Observation', 'id': '2'},
            ],  # 2 resources (would trigger Check 4 with confidence < 0.95)
            ai_model_used='gpt-4',  # Fallback model (Check 2)
            extraction_confidence=0.88,  # < 0.95 (would trigger Check 4)
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        # Should return fallback flag, not low resource count flag
        self.assertIn('fallback', reason.lower())
        self.assertNotIn('resource count', reason.lower())
    
    def test_zero_resources_and_low_resource_count_returns_zero_resources_flag(self):
        """
        RIGOROUS: Test that Check 3 (zero resources) fires before Check 4 (low count).
        
        This is a logical dependency - zero resources is a special case of low resource count.
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[],  # Zero resources (Check 3)
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.88,  # < 0.95 (would also trigger Check 4)
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        # Should return zero resources flag (more specific)
        self.assertIn('zero', reason.lower())
        # Should NOT mention "low resource count" since zero is more specific
        self.assertNotIn('low resource', reason.lower())
    
    def test_all_checks_pass_except_conflicts(self):
        """
        RIGOROUS: Test that conflicts (Check 5) can trigger even when all other checks pass.
        
        This verifies Check 5 runs last and can catch issues missed by earlier checks.
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {
                    'resourceType': 'Patient',
                    'name': [{'given': ['Jane'], 'family': 'Smith'}],  # Wrong name
                    'birthDate': '1990-05-15'  # Wrong DOB
                },
                {'resourceType': 'Condition', 'id': '1'},
                {'resourceType': 'Observation', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
            ],  # 4 resources total
            ai_model_used='claude-3-sonnet',  # Primary model (passes Check 2)
            extraction_confidence=0.96,  # High confidence (passes Check 1 and 4)
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        # Should flag due to patient conflict
        self.assertIn('conflict', reason.lower())
        # Should mention both DOB and name
        self.assertIn('dob', reason.lower())
        self.assertIn('name', reason.lower())


class QualityCheckEdgeCasesTests(TestCase):
    """
    Tests for edge cases and unusual scenarios in quality check logic.
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
            mrn='TEST-001'
        )
        
        # Counter for creating unique documents
        self.document_counter = 0
    
    def create_test_document(self):
        """Helper method to create a unique document for each test"""
        self.document_counter += 1
        pdf_content = b'%PDF-1.4 fake pdf content'
        pdf_file = SimpleUploadedFile(
            f'test_document_{self.document_counter}.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        
        return Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename=f'test_document_{self.document_counter}.pdf',
            file=pdf_file,
            status='completed'
        )
    
    def test_empty_dict_fhir_delta_json_treated_as_zero_resources(self):
        """
        RIGOROUS: Test that empty dict FHIR data is handled gracefully.
        
        Should treat empty dict as zero resources and flag accordingly.
        The fhir_delta_json field has NOT NULL constraint, so we test with empty dict.
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json={},  # Empty dict instead of None (NOT NULL constraint)
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('zero', reason.lower())
    
    def test_malformed_fhir_resources_counted_correctly(self):
        """
        RIGOROUS: Test that malformed FHIR resources still get counted.
        
        Resources without 'resourceType' or other required fields should still count
        towards the resource total for quality checks.
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {},  # Malformed resource
                {'id': '1'},  # Missing resourceType
                {'resourceType': 'Condition'},  # Missing id
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        # Should count all 3 resources, even if malformed
        resource_count = parsed_data.get_fhir_resource_count()
        self.assertEqual(resource_count, 3,
                        'Malformed resources should still be counted')
        
        # With 3 resources and 0.92 confidence, should auto-approve
        status, reason = parsed_data.determine_review_status()
        self.assertEqual(status, 'auto_approved')
    
    def test_confidence_exactly_at_secondary_threshold_095(self):
        """
        RIGOROUS: Test confidence exactly at 0.95 (Check 4 threshold).
        
        With <3 resources and confidence exactly at 0.95, should auto-approve.
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {'resourceType': 'Condition', 'id': '1'},
                {'resourceType': 'Observation', 'id': '2'},
            ],  # 2 resources
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.95,  # Exactly at threshold
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # At 0.95 threshold, should auto-approve
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_very_high_resource_count_auto_approves(self):
        """
        RIGOROUS: Test that very high resource counts always auto-approve.
        
        Even with minimum confidence (0.80), high resource counts indicate
        successful extraction and should auto-approve.
        """
        # Create 50 resources
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {'resourceType': 'Condition', 'id': str(i)}
                for i in range(50)
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.80,  # Minimum passing confidence
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_confidence_one_equals_auto_approve(self):
        """
        RIGOROUS: Test perfect confidence (1.0) with any resource count >= 1.
        
        Perfect confidence should auto-approve even with single resource.
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition', 'id': '1'}],  # 1 resource
            ai_model_used='claude-3-sonnet',
            extraction_confidence=1.0,  # Perfect confidence
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_empty_ai_model_name_does_not_flag(self):
        """
        RIGOROUS: Test that empty or None ai_model_used doesn't false-flag.
        
        Missing model name should not trigger fallback detection.
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='',  # Empty string
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        status, reason = parsed_data.determine_review_status()
        
        # Should auto-approve (not flag for fallback)
        self.assertEqual(status, 'auto_approved')
        self.assertEqual(reason, '')
    
    def test_mixed_case_gpt_in_model_name_flags(self):
        """
        RIGOROUS: Test case-insensitive GPT detection.
        
        Various capitalizations of 'gpt' should all be detected as fallback.
        """
        test_cases = [
            'GPT-4',
            'gpt-4',
            'Gpt-4',
            'GpT-3.5-turbo',
            'model-GPT-custom',
        ]
        
        for model_name in test_cases:
            with self.subTest(model=model_name):
                # Create unique document for this subTest iteration
                document = self.create_test_document()
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
                
                self.assertEqual(status, 'flagged',
                                f'Model "{model_name}" should be flagged as fallback')
                self.assertIn('fallback', reason.lower())
    
    def test_fallback_method_used_field_triggers_flag(self):
        """
        RIGOROUS: Test that fallback_method_used field also triggers flagging.
        
        This is a backward compatibility check - the old field should still work.
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='claude-3-sonnet',  # Primary model
            extraction_confidence=0.92,
            fallback_method_used='regex-fallback'  # Fallback method used
        )
        
        status, reason = parsed_data.determine_review_status()
        
        self.assertEqual(status, 'flagged')
        self.assertIn('fallback', reason.lower())
        self.assertIn('regex-fallback', reason)


class QualityCheckPerformanceTests(TestCase):
    """
    Tests for performance requirements of quality check logic.
    All checks must complete in < 100ms.
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
            mrn='TEST-001'
        )
        
        # Counter for creating unique documents
        self.document_counter = 0
    
    def create_test_document(self):
        """Helper method to create a unique document for each test"""
        self.document_counter += 1
        pdf_content = b'%PDF-1.4 fake pdf content'
        pdf_file = SimpleUploadedFile(
            f'test_document_{self.document_counter}.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        
        return Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename=f'test_document_{self.document_counter}.pdf',
            file=pdf_file,
            status='completed'
        )
    
    def test_performance_with_large_fhir_bundle(self):
        """
        RIGOROUS: Test performance with large FHIR bundles (100+ resources).
        
        Quality checks should remain fast even with large data volumes.
        Target: < 100ms
        """
        import time
        
        # Create 100 resources
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {'resourceType': 'Condition', 'id': str(i)}
                for i in range(100)
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        start_time = time.time()
        status, reason = parsed_data.determine_review_status()
        execution_time = (time.time() - start_time) * 1000  # Convert to ms
        
        self.assertLess(execution_time, 100,
                       f'Large bundle processing took {execution_time:.2f}ms, exceeds 100ms target')
        self.assertEqual(status, 'auto_approved')
    
    def test_performance_with_patient_conflict_check(self):
        """
        RIGOROUS: Test performance when conflict check runs.
        
        Conflict detection is the most expensive check (Check 5).
        Should still complete in < 100ms.
        """
        import time
        
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {
                    'resourceType': 'Patient',
                    'name': [{'given': ['John'], 'family': 'Doe'}],
                    'birthDate': '1980-01-01'
                },
                {'resourceType': 'Condition', 'id': '1'},
                {'resourceType': 'Observation', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.96,
            fallback_method_used=''
        )
        
        start_time = time.time()
        status, reason = parsed_data.determine_review_status()
        execution_time = (time.time() - start_time) * 1000  # Convert to ms
        
        self.assertLess(execution_time, 100,
                       f'Conflict check took {execution_time:.2f}ms, exceeds 100ms target')
    
    def test_performance_multiple_sequential_calls(self):
        """
        RIGOROUS: Test performance when called multiple times.
        
        Verifies no caching issues or performance degradation on repeated calls.
        """
        import time
        
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
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
        
        # Call 10 times and measure each
        execution_times = []
        for _ in range(10):
            start_time = time.time()
            status, reason = parsed_data.determine_review_status()
            execution_time = (time.time() - start_time) * 1000
            execution_times.append(execution_time)
        
        # All calls should be < 100ms
        max_time = max(execution_times)
        avg_time = sum(execution_times) / len(execution_times)
        
        self.assertLess(max_time, 100,
                       f'Maximum execution time {max_time:.2f}ms exceeds 100ms target')
        
        # Average should be significantly lower
        self.assertLess(avg_time, 50,
                       f'Average execution time {avg_time:.2f}ms is too high')


class QualityCheckDataIntegrityTests(TestCase):
    """
    Tests to verify quality checks don't modify data or have side effects.
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
            mrn='TEST-001'
        )
        
        # Counter for creating unique documents
        self.document_counter = 0
    
    def create_test_document(self):
        """Helper method to create a unique document for each test"""
        self.document_counter += 1
        pdf_content = b'%PDF-1.4 fake pdf content'
        pdf_file = SimpleUploadedFile(
            f'test_document_{self.document_counter}.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        
        return Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename=f'test_document_{self.document_counter}.pdf',
            file=pdf_file,
            status='completed'
        )
    
    def test_determine_review_status_does_not_modify_database(self):
        """
        RIGOROUS: Test that determine_review_status() is a pure read operation.
        
        Should not modify ParsedData, Patient, or any other database records.
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[{'resourceType': 'Condition'}] * 5,
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.92,
            fallback_method_used=''
        )
        
        # Capture initial state
        initial_review_status = parsed_data.review_status
        initial_auto_approved = parsed_data.auto_approved
        initial_flag_reason = parsed_data.flag_reason
        initial_updated_at = parsed_data.updated_at
        
        # Call determine_review_status
        status, reason = parsed_data.determine_review_status()
        
        # Refresh from database
        parsed_data.refresh_from_db()
        
        # Verify no fields were modified
        self.assertEqual(parsed_data.review_status, initial_review_status,
                        'review_status should not be modified')
        self.assertEqual(parsed_data.auto_approved, initial_auto_approved,
                        'auto_approved should not be modified')
        self.assertEqual(parsed_data.flag_reason, initial_flag_reason,
                        'flag_reason should not be modified')
        self.assertEqual(parsed_data.updated_at, initial_updated_at,
                        'updated_at should not be modified')
    
    def test_determine_review_status_is_idempotent(self):
        """
        RIGOROUS: Test that calling determine_review_status() multiple times
        returns the same result.
        
        Should be a pure function with no side effects.
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {'resourceType': 'Condition', 'id': '1'},
                {'resourceType': 'Observation', 'id': '2'},
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.88,
            fallback_method_used=''
        )
        
        # Call multiple times
        result1 = parsed_data.determine_review_status()
        result2 = parsed_data.determine_review_status()
        result3 = parsed_data.determine_review_status()
        
        # All results should be identical
        self.assertEqual(result1, result2)
        self.assertEqual(result2, result3)
    
    def test_determine_review_status_does_not_affect_patient_record(self):
        """
        RIGOROUS: Test that checking for conflicts doesn't modify Patient.
        
        Patient record should remain unchanged even when conflicts are detected.
        """
        document = self.create_test_document()
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=[
                {
                    'resourceType': 'Patient',
                    'name': [{'given': ['Jane'], 'family': 'Smith'}],
                    'birthDate': '1990-05-15'
                },
                {'resourceType': 'Condition', 'id': '1'},
                {'resourceType': 'Observation', 'id': '2'},
                {'resourceType': 'MedicationStatement', 'id': '3'},
            ],
            ai_model_used='claude-3-sonnet',
            extraction_confidence=0.96,
            fallback_method_used=''
        )
        
        # Capture patient state
        initial_first_name = self.patient.first_name
        initial_last_name = self.patient.last_name
        initial_dob = self.patient.date_of_birth
        initial_fhir_json = self.patient.cumulative_fhir_json.copy()
        
        # Call determine_review_status (will detect conflicts)
        status, reason = parsed_data.determine_review_status()
        
        # Verify patient was not modified
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.first_name, initial_first_name)
        self.assertEqual(self.patient.last_name, initial_last_name)
        self.assertEqual(self.patient.date_of_birth, initial_dob)
        self.assertEqual(self.patient.cumulative_fhir_json, initial_fhir_json)

