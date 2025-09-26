"""
Test suite for data validation middleware.

Tests validation functions, middleware behavior, and integration with the document processing pipeline.
"""

import json
import time
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth import get_user_model
from django.http import HttpResponse, JsonResponse
from django.core.exceptions import ValidationError
from pydantic import ValidationError as PydanticValidationError

from .middleware import (
    StructuredDataValidationMiddleware,
    DataValidationService,
    validate_structured_data,
    validate_document_upload_data,
    validate_ai_extraction_input,
    validate_fhir_conversion_input
)
from .services.ai_extraction import (
    StructuredMedicalExtraction,
    MedicalCondition,
    Medication,
    VitalSign,
    SourceContext
)
from .models import Document
from apps.patients.models import Patient

User = get_user_model()


class DataValidationServiceTests(TestCase):
    """Test the DataValidationService class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.validator = DataValidationService()
        self.sample_source = SourceContext(
            text="Patient has diabetes",
            start_index=0,
            end_index=20
        )
    
    def test_validate_text_quality_valid_text(self):
        """Test text quality validation with valid medical text."""
        text = "Patient John Doe has been diagnosed with diabetes mellitus type 2. Current medications include Metformin 500mg daily."
        
        is_valid, issues = self.validator.validate_text_quality(text)
        
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)
    
    def test_validate_text_quality_empty_text(self):
        """Test text quality validation with empty text."""
        text = ""
        
        is_valid, issues = self.validator.validate_text_quality(text)
        
        self.assertFalse(is_valid)
        self.assertIn("Text is empty", issues[0])
    
    def test_validate_text_quality_short_text(self):
        """Test text quality validation with text that's too short."""
        text = "Short text"
        
        is_valid, issues = self.validator.validate_text_quality(text)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("too short" in issue for issue in issues))
    
    def test_validate_text_quality_error_indicators(self):
        """Test text quality validation with error indicators."""
        text = "PDF extraction failed - unable to read file content. The document appears corrupted."
        
        is_valid, issues = self.validator.validate_text_quality(text)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("error indicator" in issue for issue in issues))
    
    def test_validate_text_quality_limited_medical_content(self):
        """Test text quality validation with limited medical content."""
        text = "This is a long document about non-medical topics. It contains general information about various subjects but has no medical terminology or clinical information whatsoever."
        
        is_valid, issues = self.validator.validate_text_quality(text)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("Limited medical content" in issue for issue in issues))
    
    def test_validate_structured_extraction_valid_data(self):
        """Test structured extraction validation with valid data."""
        structured_data = StructuredMedicalExtraction(
            conditions=[
                MedicalCondition(
                    name="Diabetes Type 2",
                    confidence=0.9,
                    source=self.sample_source
                )
            ],
            medications=[
                Medication(
                    name="Metformin",
                    dosage="500mg",
                    confidence=0.8,
                    source=self.sample_source
                )
            ]
        )
        
        is_valid, issues = self.validator.validate_structured_extraction(structured_data)
        
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)
    
    def test_validate_structured_extraction_empty_data(self):
        """Test structured extraction validation with no medical data."""
        structured_data = StructuredMedicalExtraction()
        
        is_valid, issues = self.validator.validate_structured_extraction(structured_data)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("No medical data extracted" in issue for issue in issues))
    
    def test_validate_structured_extraction_low_confidence(self):
        """Test structured extraction validation with low confidence."""
        structured_data = StructuredMedicalExtraction(
            conditions=[
                MedicalCondition(
                    name="Possible condition",
                    confidence=0.1,  # Very low confidence
                    source=self.sample_source
                )
            ]
        )
        
        is_valid, issues = self.validator.validate_structured_extraction(structured_data)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("Low confidence score" in issue for issue in issues))
    
    def test_validate_fhir_resources_valid(self):
        """Test FHIR resource validation with valid resources."""
        fhir_resources = [
            {
                "resourceType": "Condition",
                "subject": {"reference": "Patient/123"},
                "code": {"text": "Diabetes"},
                "clinicalStatus": {"coding": [{"code": "active"}]}
            },
            {
                "resourceType": "MedicationStatement",
                "subject": {"reference": "Patient/123"},
                "medicationCodeableConcept": {"text": "Metformin"},
                "status": "active"
            }
        ]
        
        is_valid, issues = self.validator.validate_fhir_resources(fhir_resources)
        
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)
    
    def test_validate_fhir_resources_missing_required_fields(self):
        """Test FHIR resource validation with missing required fields."""
        fhir_resources = [
            {
                "resourceType": "Condition",
                # Missing subject and code
            }
        ]
        
        is_valid, issues = self.validator.validate_fhir_resources(fhir_resources)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("Missing required" in issue for issue in issues))
    
    def test_validate_fhir_resources_empty_list(self):
        """Test FHIR resource validation with empty resource list."""
        fhir_resources = []
        
        is_valid, issues = self.validator.validate_fhir_resources(fhir_resources)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("No FHIR resources provided" in issue for issue in issues))
    
    def test_validate_processing_completeness_valid(self):
        """Test processing completeness validation with valid data."""
        document_data = {
            'original_text': 'Sample medical text',
            'structured_data': {
                'conditions': [{'name': 'Diabetes'}],
                'medications': [{'name': 'Metformin'}]
            },
            'fhir_resources': [
                {'resourceType': 'Condition', 'code': {'text': 'Diabetes'}}
            ],
            'status': 'processed'
        }
        
        is_valid, issues = self.validator.validate_processing_completeness(document_data)
        
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)
    
    def test_validate_processing_completeness_missing_fields(self):
        """Test processing completeness validation with missing required fields."""
        document_data = {
            'status': 'processed'
            # Missing original_text, structured_data, fhir_resources
        }
        
        is_valid, issues = self.validator.validate_processing_completeness(document_data)
        
        self.assertFalse(is_valid)
        self.assertTrue(len(issues) >= 3)  # Should have multiple missing field issues
    
    def test_validate_processing_completeness_with_errors(self):
        """Test processing completeness validation with processing errors."""
        document_data = {
            'original_text': 'Sample text',
            'structured_data': {},
            'fhir_resources': [],
            'status': 'processed',
            'error_log': [
                {'error': 'AI extraction failed', 'timestamp': '2025-09-24T12:00:00Z'}
            ]
        }
        
        is_valid, issues = self.validator.validate_processing_completeness(document_data)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("completed with" in issue and "errors" in issue for issue in issues))


class StructuredDataValidationMiddlewareTests(TestCase):
    """Test the StructuredDataValidationMiddleware class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()
        self.middleware = StructuredDataValidationMiddleware()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_process_request_document_upload(self):
        """Test middleware processing for document upload requests."""
        request = self.factory.post('/documents/upload/', {'file': 'test.pdf'})
        request.user = self.user
        
        self.middleware.process_request(request)
        
        self.assertTrue(hasattr(request, 'validation_context'))
        self.assertTrue(request.validation_context['document_processing'])
        self.assertEqual(request.validation_context['pipeline_stage'], 'upload')
    
    def test_process_request_non_document(self):
        """Test middleware processing for non-document requests."""
        request = self.factory.get('/patients/')
        request.user = self.user
        
        self.middleware.process_request(request)
        
        self.assertTrue(hasattr(request, 'validation_context'))
        self.assertFalse(request.validation_context.get('document_processing', False))
    
    @patch('apps.core.models.AuditLog.objects.create')
    def test_process_response_with_validation_context(self, mock_audit_create):
        """Test middleware response processing with validation context."""
        request = self.factory.post('/documents/upload/')
        request.user = self.user
        
        # Set up validation context
        self.middleware.process_request(request)
        request.validation_context['validations_performed'] = ['text_quality', 'structured_data']
        request.validation_context['validation_errors'] = []
        
        response = HttpResponse("Success")
        
        result = self.middleware.process_response(request, response)
        
        self.assertEqual(result, response)
        mock_audit_create.assert_called_once()
    
    def test_is_document_processing_request(self):
        """Test document processing request detection."""
        test_cases = [
            ('/documents/upload/', True),
            ('/documents/process/', True),
            ('/api/documents/', True),
            ('/api/validate/', True),
            ('/patients/', False),
            ('/admin/', False),
        ]
        
        for path, expected in test_cases:
            request = self.factory.get(path)
            result = self.middleware._is_document_processing_request(request)
            self.assertEqual(result, expected, f"Failed for path: {path}")


class ValidationDecoratorTests(TestCase):
    """Test the validation decorator functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_validate_structured_data_decorator_success(self):
        """Test validation decorator with successful validation."""
        @validate_structured_data('text')
        def test_view(request):
            return HttpResponse("Success")
        
        request = self.factory.post('/test/')
        request.user = self.user
        request.validation_context = {
            'validations_performed': [],
            'validation_errors': []
        }
        
        response = test_view(request)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('text', request.validation_context['validations_performed'])
    
    def test_validate_structured_data_decorator_with_validation_error(self):
        """Test validation decorator with validation error."""
        @validate_structured_data('full')
        def test_view(request):
            # Simulate a view that triggers validation error
            from .exceptions import DataValidationError
            raise DataValidationError("Test validation error")
        
        request = self.factory.post('/test/')
        request.user = self.user
        request.validation_context = {
            'validations_performed': [],
            'validation_errors': []
        }
        
        with self.assertRaises(ValidationError):
            test_view(request)
        
        self.assertIn("Test validation error", request.validation_context['validation_errors'][0])


class UtilityFunctionTests(TestCase):
    """Test utility validation functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.sample_source = SourceContext(
            text="Sample medical text",
            start_index=0,
            end_index=20
        )
    
    def test_validate_document_upload_data_valid(self):
        """Test document upload data validation with valid data."""
        document_data = {
            'original_text': 'Patient John Doe has diabetes and takes Metformin 500mg daily.',
            'structured_data': {
                'conditions': [{'name': 'Diabetes', 'confidence': 0.9}],
                'medications': [{'name': 'Metformin', 'dosage': '500mg', 'confidence': 0.8}],
                'vital_signs': [],
                'lab_results': [],
                'procedures': [],
                'providers': [],
                'confidence_average': 0.85
            },
            'fhir_resources': [
                {
                    'resourceType': 'Condition',
                    'subject': {'reference': 'Patient/123'},
                    'code': {'text': 'Diabetes'},
                    'clinicalStatus': {'coding': [{'code': 'active'}]}
                }
            ]
        }
        
        results = validate_document_upload_data(document_data)
        
        self.assertTrue(results['is_valid'])
        self.assertEqual(len(results['issues']), 0)
        self.assertGreater(results['validation_time_ms'], 0)
    
    def test_validate_document_upload_data_invalid_text(self):
        """Test document upload data validation with invalid text."""
        document_data = {
            'original_text': 'Short',  # Too short
            'structured_data': {},
            'fhir_resources': []
        }
        
        results = validate_document_upload_data(document_data)
        
        self.assertFalse(results['is_valid'])
        self.assertTrue(len(results['issues']) > 0)
    
    def test_validate_ai_extraction_input_valid(self):
        """Test AI extraction input validation with valid text."""
        text = "Patient has diabetes mellitus and hypertension. Currently prescribed Metformin 500mg and Lisinopril 10mg daily."
        
        is_valid = validate_ai_extraction_input(text, "test-doc-123")
        
        self.assertTrue(is_valid)
    
    def test_validate_ai_extraction_input_invalid(self):
        """Test AI extraction input validation with invalid text."""
        text = "Short"  # Too short and no medical content
        
        is_valid = validate_ai_extraction_input(text, "test-doc-123")
        
        self.assertFalse(is_valid)
    
    def test_validate_fhir_conversion_input_valid(self):
        """Test FHIR conversion input validation with valid structured data."""
        structured_data = StructuredMedicalExtraction(
            conditions=[
                MedicalCondition(
                    name="Diabetes Type 2",
                    confidence=0.9,
                    source=self.sample_source
                )
            ],
            medications=[
                Medication(
                    name="Metformin",
                    dosage="500mg",
                    confidence=0.8,
                    source=self.sample_source
                )
            ]
        )
        
        is_valid = validate_fhir_conversion_input(structured_data)
        
        self.assertTrue(is_valid)
    
    def test_validate_fhir_conversion_input_empty(self):
        """Test FHIR conversion input validation with empty structured data."""
        structured_data = StructuredMedicalExtraction()
        
        is_valid = validate_fhir_conversion_input(structured_data)
        
        self.assertFalse(is_valid)


class MiddlewareIntegrationTests(TestCase):
    """Test middleware integration with Django request/response cycle."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()
        self.middleware = StructuredDataValidationMiddleware()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_middleware_request_response_cycle(self):
        """Test complete middleware request/response cycle."""
        # Create a mock view function
        def mock_view(request):
            return HttpResponse("Success")
        
        # Set up middleware with the mock view
        middleware_instance = StructuredDataValidationMiddleware(mock_view)
        
        # Create request
        request = self.factory.post('/documents/upload/', {'file': 'test.pdf'})
        request.user = self.user
        
        # Process through middleware
        response = middleware_instance(request)
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(hasattr(request, 'validation_context'))
    
    @override_settings(DEBUG=True)
    def test_middleware_debug_headers(self):
        """Test middleware adds debug headers in development."""
        def mock_view(request):
            return HttpResponse("Success")
        
        middleware_instance = StructuredDataValidationMiddleware(mock_view)
        
        request = self.factory.post('/documents/upload/')
        request.user = self.user
        
        response = middleware_instance(request)
        
        # Check for debug headers
        self.assertIn('X-Validation-Time-MS', response)
        self.assertIn('X-Validations-Count', response)
    
    @patch('apps.core.models.AuditLog.objects.create')
    def test_middleware_audit_logging(self, mock_audit_create):
        """Test middleware creates audit logs for validation events."""
        def mock_view(request):
            # Add some validation activity to the context
            request.validation_context['validations_performed'].append('test_validation')
            return HttpResponse("Success")
        
        middleware_instance = StructuredDataValidationMiddleware(mock_view)
        
        request = self.factory.post('/documents/upload/')
        request.user = self.user
        
        response = middleware_instance(request)
        
        # Verify audit log was created
        mock_audit_create.assert_called_once()
        call_args = mock_audit_create.call_args[1]
        self.assertEqual(call_args['action'], 'DATA_VALIDATION')
        self.assertEqual(call_args['user'], self.user)


class ValidationIntegrationTests(TestCase):
    """Test validation integration with document processing components."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.patient = Patient.objects.create(
            first_name="John",
            last_name="Doe", 
            date_of_birth="1980-01-01",
            mrn="TEST123"
        )
        
        self.sample_source = SourceContext(
            text="Patient has diabetes",
            start_index=0,
            end_index=20
        )
    
    def test_validation_with_document_model(self):
        """Test validation integration with Document model."""
        document = Document.objects.create(
            filename="test.pdf",
            patient=self.patient,
            original_text="Patient John Doe has diabetes mellitus type 2 and takes Metformin 500mg daily.",
            status="pending"
        )
        
        # Test text quality validation
        validator = DataValidationService()
        is_valid, issues = validator.validate_text_quality(document.original_text)
        
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)
    
    def test_validation_with_pydantic_models(self):
        """Test validation integration with Pydantic models."""
        # Create valid structured data
        structured_data = StructuredMedicalExtraction(
            conditions=[
                MedicalCondition(
                    name="Diabetes Type 2",
                    confidence=0.9,
                    source=self.sample_source
                )
            ],
            medications=[
                Medication(
                    name="Metformin",
                    dosage="500mg",
                    frequency="daily",
                    confidence=0.8,
                    source=self.sample_source
                )
            ]
        )
        
        # Test structured data validation
        validator = DataValidationService()
        is_valid, issues = validator.validate_structured_extraction(structured_data)
        
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)
    
    def test_validation_error_recovery(self):
        """Test validation error recovery mechanisms."""
        # Test with invalid structured data that should trigger recovery
        invalid_data = {
            'conditions': 'not a list',  # Invalid type
            'medications': []
        }
        
        try:
            structured_data = StructuredMedicalExtraction(**invalid_data)
            self.fail("Should have raised validation error")
        except PydanticValidationError as e:
            # This is expected - validation should catch the error
            self.assertIn("conditions", str(e))
    
    def test_validation_performance(self):
        """Test validation performance with realistic data sizes."""
        # Create structured data with many resources
        large_structured_data = StructuredMedicalExtraction(
            conditions=[
                MedicalCondition(
                    name=f"Condition {i}",
                    confidence=0.8,
                    source=self.sample_source
                ) for i in range(50)
            ],
            medications=[
                Medication(
                    name=f"Medication {i}",
                    dosage="500mg",
                    confidence=0.8,
                    source=self.sample_source
                ) for i in range(30)
            ]
        )
        
        # Measure validation time
        start_time = time.time()
        validator = DataValidationService()
        is_valid, issues = validator.validate_structured_extraction(large_structured_data)
        validation_time = (time.time() - start_time) * 1000
        
        # Validation should complete quickly even with large datasets
        self.assertLess(validation_time, 100)  # Should complete in under 100ms
        self.assertTrue(is_valid)


class ValidationErrorHandlingTests(TestCase):
    """Test error handling in validation components."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.validator = DataValidationService()
    
    def test_validation_with_malformed_data(self):
        """Test validation handles malformed data gracefully."""
        malformed_data = {
            'conditions': None,  # Should be a list
            'medications': 'invalid',  # Should be a list
            'confidence_average': 'not_a_number'  # Should be float
        }
        
        # Validation should not crash, but should detect issues
        try:
            structured_data = StructuredMedicalExtraction(**malformed_data)
            self.fail("Should have raised validation error")
        except PydanticValidationError:
            # Expected behavior
            pass
    
    def test_validation_with_network_errors(self):
        """Test validation behavior during network/service errors."""
        # Simulate a scenario where external validation services are unavailable
        with patch('apps.documents.middleware.logger') as mock_logger:
            # Test that validation continues even if logging fails
            result = validate_ai_extraction_input("Valid medical text about diabetes and medications")
            
            # Should still return a valid result
            self.assertTrue(result)
    
    def test_validation_exception_handling(self):
        """Test validation exception handling and logging."""
        validator = DataValidationService()
        
        # Test with data that will cause internal validation errors
        with patch.object(validator, '_validate_conditions', side_effect=Exception("Test error")):
            structured_data = StructuredMedicalExtraction(
                conditions=[
                    MedicalCondition(
                        name="Test condition",
                        confidence=0.8,
                        source=SourceContext(text="test", start_index=0, end_index=4)
                    )
                ]
            )
            
            # Should handle exception gracefully
            is_valid, issues = validator.validate_structured_extraction(structured_data)
            
            # Should still provide some validation result
            self.assertIsInstance(is_valid, bool)
            self.assertIsInstance(issues, list)


class MedicalDataValidationTests(TestCase):
    """Test medical-specific validation logic."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.validator = DataValidationService()
        self.sample_source = SourceContext(
            text="Sample text",
            start_index=0,
            end_index=10
        )
    
    def test_condition_validation(self):
        """Test medical condition validation."""
        conditions = [
            MedicalCondition(name="", confidence=0.8, source=self.sample_source),  # Invalid: empty name
            MedicalCondition(name="Diabetes", confidence=0.05, source=self.sample_source),  # Invalid: low confidence
            MedicalCondition(name="Valid Condition", confidence=0.8, source=self.sample_source),  # Valid
        ]
        
        issues = []
        self.validator._validate_conditions(conditions, issues)
        
        # Should have 2 issues (empty name and low confidence)
        self.assertEqual(len(issues), 2)
        self.assertTrue(any("invalid name" in issue for issue in issues))
        self.assertTrue(any("very low confidence" in issue for issue in issues))
    
    def test_medication_validation(self):
        """Test medication validation."""
        medications = [
            Medication(name="", confidence=0.8, source=self.sample_source),  # Invalid: empty name
            Medication(name="Metformin", dosage="unclear dosage", confidence=0.8, source=self.sample_source),  # Invalid: unclear dosage
            Medication(name="Valid Med", dosage="500mg", confidence=0.8, source=self.sample_source),  # Valid
        ]
        
        issues = []
        self.validator._validate_medications(medications, issues)
        
        # Should have 2 issues (empty name and unclear dosage)
        self.assertEqual(len(issues), 2)
        self.assertTrue(any("invalid name" in issue for issue in issues))
        self.assertTrue(any("dosage may be incomplete" in issue for issue in issues))
    
    def test_vital_signs_validation(self):
        """Test vital signs validation."""
        vital_signs = [
            VitalSign(measurement="", value="120", confidence=0.8, source=self.sample_source),  # Invalid: empty measurement
            VitalSign(measurement="Blood Pressure", value="", confidence=0.8, source=self.sample_source),  # Invalid: empty value
            VitalSign(measurement="Heart Rate", value="72 bpm", confidence=0.8, source=self.sample_source),  # Valid
        ]
        
        issues = []
        self.validator._validate_vital_signs(vital_signs, issues)
        
        # Should have 2 issues (empty measurement and empty value)
        self.assertEqual(len(issues), 2)
        self.assertTrue(any("invalid measurement type" in issue for issue in issues))
        self.assertTrue(any("has no value" in issue for issue in issues))


class ValidationPerformanceTests(TestCase):
    """Test validation performance and scalability."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.validator = DataValidationService()
    
    def test_large_text_validation_performance(self):
        """Test validation performance with large text inputs."""
        # Create large medical text (simulating a comprehensive medical report)
        large_text = "Patient medical history. " * 1000  # ~25KB of text
        
        start_time = time.time()
        is_valid, issues = self.validator.validate_text_quality(large_text)
        validation_time = (time.time() - start_time) * 1000
        
        # Should complete quickly even with large text
        self.assertLess(validation_time, 50)  # Under 50ms
        self.assertTrue(is_valid)
    
    def test_many_resources_validation_performance(self):
        """Test validation performance with many medical resources."""
        # Create structured data with many resources
        sample_source = SourceContext(text="test", start_index=0, end_index=4)
        
        structured_data = StructuredMedicalExtraction(
            conditions=[
                MedicalCondition(
                    name=f"Condition {i}",
                    confidence=0.8,
                    source=sample_source
                ) for i in range(100)
            ],
            medications=[
                Medication(
                    name=f"Medication {i}",
                    dosage="500mg",
                    confidence=0.8,
                    source=sample_source
                ) for i in range(50)
            ]
        )
        
        start_time = time.time()
        is_valid, issues = self.validator.validate_structured_extraction(structured_data)
        validation_time = (time.time() - start_time) * 1000
        
        # Should handle large datasets efficiently
        self.assertLess(validation_time, 200)  # Under 200ms
        self.assertTrue(is_valid)


class ValidationConfigurationTests(TestCase):
    """Test validation configuration and customization."""
    
    def test_validation_threshold_configuration(self):
        """Test custom validation threshold configuration."""
        validator = DataValidationService()
        
        # Test with custom thresholds
        validator.min_confidence_threshold = 0.8
        
        structured_data = StructuredMedicalExtraction(
            conditions=[
                MedicalCondition(
                    name="Low confidence condition",
                    confidence=0.5,  # Below custom threshold
                    source=SourceContext(text="test", start_index=0, end_index=4)
                )
            ]
        )
        
        is_valid, issues = validator.validate_structured_extraction(structured_data)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("Low confidence score" in issue for issue in issues))
    
    def test_validation_rules_customization(self):
        """Test customization of validation rules."""
        middleware = StructuredDataValidationMiddleware()
        
        # Customize validation rules
        middleware.validation_rules['text_quality']['min_length'] = 100
        
        # Test with text that would be valid under normal rules but invalid under custom rules
        text = "Patient has diabetes."  # ~20 characters
        
        validator = DataValidationService()
        validator.min_text_length = 100  # Apply custom rule
        
        is_valid, issues = validator.validate_text_quality(text)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("too short" in issue for issue in issues))
