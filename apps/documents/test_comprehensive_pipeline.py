"""
Comprehensive test suite for the refactored document processing pipeline.

This module implements the complete testing strategy outlined in Task 34.12,
covering all aspects of the refactored document processing pipeline from
AI extraction through FHIR conversion to review interface.

Test Categories:
1. Unit Tests - Individual component testing
2. Integration Tests - Full pipeline testing  
3. User Interface Tests - Frontend interaction testing
4. Performance Tests - Processing time benchmarks
5. Error Handling Tests - Failure scenarios and edge cases
6. Security Tests - Audit logging and HIPAA compliance
7. End-to-End Tests - Complete workflow testing
"""

import json
import time
import tempfile
import pytest
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.db import transaction
from django.urls import reverse

from fhir.resources.condition import Condition
from fhir.resources.medicationstatement import MedicationStatement
from fhir.resources.observation import Observation
from fhir.resources.encounter import Encounter

from apps.patients.models import Patient
from apps.providers.models import Provider
from apps.core.models import AuditLog
from .models import Document, ParsedData
from .services.ai_extraction import (
    StructuredMedicalExtraction,
    MedicalCondition,
    Medication,
    VitalSign,
    LabResult,
    Procedure,
    ProviderInfo,
    SourceContext,
    extract_medical_data_structured,
    extract_medical_data
)
from .analyzers import DocumentAnalyzer
from .tasks import process_document_async
from apps.fhir.converters import StructuredDataConverter
from apps.fhir.services.bundle_service import FHIRBundleService

User = get_user_model()


class TestFixtures:
    """Test data fixtures and utilities for the comprehensive test suite."""
    
    @staticmethod
    def create_test_user():
        """Create a test user for authentication."""
        return User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
    
    @staticmethod
    def create_test_patient():
        """Create a test patient for document association."""
        return Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            mrn='TEST001',
            gender='M'
        )
    
    @staticmethod
    def create_test_provider():
        """Create a test provider for document association."""
        return Provider.objects.create(
            first_name='Dr. Jane',
            last_name='Smith',
            npi='1234567890',
            specialty='Internal Medicine'
        )
    
    @staticmethod
    def create_test_document(patient=None, user=None, content=None):
        """Create a test document with sample medical content."""
        if not patient:
            patient = TestFixtures.create_test_patient()
        if not user:
            user = TestFixtures.create_test_user()
        
        if not content:
            content = """
            MEDICAL RECORD
            
            Patient: John Doe
            DOB: 01/15/1980
            MRN: TEST001
            
            CHIEF COMPLAINT:
            Follow-up for diabetes and hypertension
            
            CURRENT MEDICATIONS:
            - Metformin 500mg twice daily
            - Lisinopril 10mg once daily
            - Aspirin 81mg daily
            
            VITAL SIGNS:
            Blood Pressure: 135/85 mmHg
            Heart Rate: 78 bpm
            Temperature: 98.6°F
            Weight: 180 lbs
            
            ASSESSMENT AND PLAN:
            1. Type 2 Diabetes Mellitus - Continue Metformin, HbA1c 7.2%
            2. Essential Hypertension - Continue Lisinopril
            3. Cardiovascular prophylaxis - Continue aspirin
            
            LABORATORY RESULTS:
            Glucose: 145 mg/dL (High)
            HbA1c: 7.2% (Elevated)
            Creatinine: 1.0 mg/dL (Normal)
            """
        
        file_obj = SimpleUploadedFile(
            "test_medical_record.pdf",
            content.encode('utf-8') if isinstance(content, str) else content,
            content_type="application/pdf"
        )
        
        return Document.objects.create(
            file=file_obj,
            filename="test_medical_record.pdf",
            patient=patient,
            uploaded_by=user,
            status='uploaded',
            file_size=len(content)
        )
    
    @staticmethod
    def create_structured_medical_data():
        """Create sample structured medical data for testing."""
        return StructuredMedicalExtraction(
            conditions=[
                MedicalCondition(
                    condition_name="Type 2 Diabetes Mellitus",
                    icd_code="E11.9",
                    status="active",
                    onset_date="2020-01-15",
                    confidence=0.9,
                    source_context=SourceContext(
                        text="Type 2 Diabetes Mellitus - Continue Metformin, HbA1c 7.2%",
                        start_index=150,
                        end_index=200
                    )
                ),
                MedicalCondition(
                    condition_name="Essential Hypertension",
                    icd_code="I10",
                    status="active",
                    confidence=0.85,
                    source_context=SourceContext(
                        text="Essential Hypertension - Continue Lisinopril",
                        start_index=201,
                        end_index=240
                    )
                )
            ],
            medications=[
                Medication(
                    medication_name="Metformin",
                    dosage="500mg",
                    frequency="twice daily",
                    route="oral",
                    confidence=0.95,
                    source_context=SourceContext(
                        text="Metformin 500mg twice daily",
                        start_index=75,
                        end_index=100
                    )
                ),
                Medication(
                    medication_name="Lisinopril",
                    dosage="10mg",
                    frequency="once daily",
                    route="oral",
                    confidence=0.9,
                    source_context=SourceContext(
                        text="Lisinopril 10mg once daily",
                        start_index=101,
                        end_index=125
                    )
                )
            ],
            vital_signs=[
                VitalSign(
                    vital_type="blood_pressure",
                    value="135/85",
                    unit="mmHg",
                    confidence=0.95,
                    source_context=SourceContext(
                        text="Blood Pressure: 135/85 mmHg",
                        start_index=126,
                        end_index=150
                    )
                ),
                VitalSign(
                    vital_type="heart_rate",
                    value="78",
                    unit="bpm",
                    confidence=0.9,
                    source_context=SourceContext(
                        text="Heart Rate: 78 bpm",
                        start_index=151,
                        end_index=170
                    )
                )
            ],
            lab_results=[
                LabResult(
                    test_name="Glucose",
                    value="145",
                    unit="mg/dL",
                    reference_range="70-100",
                    status="High",
                    confidence=0.95,
                    source_context=SourceContext(
                        text="Glucose: 145 mg/dL (High)",
                        start_index=300,
                        end_index=325
                    )
                ),
                LabResult(
                    test_name="HbA1c",
                    value="7.2",
                    unit="%",
                    reference_range="<7.0",
                    status="Elevated",
                    confidence=0.9,
                    source_context=SourceContext(
                        text="HbA1c: 7.2% (Elevated)",
                        start_index=326,
                        end_index=350
                    )
                )
            ],
            procedures=[],
            providers=[
                ProviderInfo(
                    provider_name="Dr. Jane Smith",
                    specialty="Internal Medicine",
                    confidence=0.8,
                    source_context=SourceContext(
                        text="Dr. Jane Smith, Internal Medicine",
                        start_index=0,
                        end_index=30
                    )
                )
            ]
        )


# ============================================================================
# 1. UNIT TESTS - Individual Component Testing
# ============================================================================

class AIExtractionUnitTests(TestCase):
    """Unit tests for AI extraction functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.sample_text = """
        Patient has diabetes and hypertension. Currently taking Metformin 500mg 
        twice daily and Lisinopril 10mg once daily. Blood pressure is 135/85 mmHg.
        """
    
    @patch('apps.documents.services.ai_extraction.claude_client')
    def test_ai_extraction_structured_success(self, mock_claude):
        """Test successful AI extraction with structured output."""
        # Mock the AI response
        mock_response = Mock()
        mock_response.content = [Mock()]
        mock_response.content[0].text = json.dumps({
            "conditions": [
                {
                    "condition_name": "diabetes",
                    "icd_code": "E11.9",
                    "status": "active",
                    "confidence": 0.9
                },
                {
                    "condition_name": "hypertension", 
                    "icd_code": "I10",
                    "status": "active",
                    "confidence": 0.85
                }
            ],
            "medications": [
                {
                    "medication_name": "Metformin",
                    "dosage": "500mg",
                    "frequency": "twice daily",
                    "confidence": 0.95
                },
                {
                    "medication_name": "Lisinopril",
                    "dosage": "10mg", 
                    "frequency": "once daily",
                    "confidence": 0.9
                }
            ]
        })
        mock_claude.messages.create.return_value = mock_response
        
        # Test the extraction
        result = extract_medical_data_structured(self.sample_text)
        
        # Verify results
        self.assertIsInstance(result, StructuredMedicalExtraction)
        self.assertEqual(len(result.conditions), 2)
        self.assertEqual(len(result.medications), 2)
        self.assertEqual(result.conditions[0].condition_name, "diabetes")
        self.assertEqual(result.medications[0].medication_name, "Metformin")
        self.assertEqual(result.medications[0].dosage, "500mg")
    
    @patch('apps.documents.services.ai_extraction.claude_client')
    def test_ai_extraction_legacy_compatibility(self, mock_claude):
        """Test legacy AI extraction function compatibility."""
        # Mock the AI response for legacy format
        mock_response = Mock()
        mock_response.content = [Mock()]
        mock_response.content[0].text = json.dumps({
            "diagnoses": ["diabetes", "hypertension"],
            "medications": ["Metformin 500mg", "Lisinopril 10mg"],
            "procedures": [],
            "lab_results": []
        })
        mock_claude.messages.create.return_value = mock_response
        
        # Test legacy extraction
        result = extract_medical_data(self.sample_text)
        
        # Verify legacy format
        self.assertIn('diagnoses', result)
        self.assertIn('medications', result)
        self.assertIn('diabetes', result['diagnoses'])
        self.assertIn('hypertension', result['diagnoses'])
        self.assertIn('Metformin 500mg', result['medications'])
        self.assertIn('Lisinopril 10mg', result['medications'])


class FHIRConversionUnitTests(TestCase):
    """Unit tests for FHIR conversion functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.patient = TestFixtures.create_test_patient()
        self.structured_data = TestFixtures.create_structured_medical_data()
        self.converter = StructuredDataConverter()
    
    def test_fhir_conversion_conditions(self):
        """Test FHIR conversion for medical conditions."""
        # Convert structured data to FHIR
        fhir_resources = self.converter.convert_structured_data(
            self.structured_data, 
            self.patient
        )
        
        # Verify condition resources
        conditions = [r for r in fhir_resources if r.get('resourceType') == 'Condition']
        self.assertEqual(len(conditions), 2)
        
        # Check specific condition
        diabetes_condition = next(
            (c for c in conditions if 'diabetes' in c.get('code', {}).get('text', '').lower()), 
            None
        )
        self.assertIsNotNone(diabetes_condition)
        self.assertEqual(diabetes_condition['subject']['reference'], f'Patient/{self.patient.id}')
    
    def test_fhir_conversion_medications(self):
        """Test FHIR conversion for medications."""
        # Convert structured data to FHIR
        fhir_resources = self.converter.convert_structured_data(
            self.structured_data,
            self.patient
        )
        
        # Verify medication resources
        medications = [r for r in fhir_resources if r.get('resourceType') == 'MedicationStatement']
        self.assertEqual(len(medications), 2)
        
        # Check specific medication
        metformin_med = next(
            (m for m in medications if 'metformin' in m.get('medicationCodeableConcept', {}).get('text', '').lower()),
            None
        )
        self.assertIsNotNone(metformin_med)
        self.assertEqual(metformin_med['subject']['reference'], f'Patient/{self.patient.id}')
    
    def test_fhir_conversion_observations(self):
        """Test FHIR conversion for vital signs and lab results."""
        # Convert structured data to FHIR
        fhir_resources = self.converter.convert_structured_data(
            self.structured_data,
            self.patient
        )
        
        # Verify observation resources (vital signs + lab results)
        observations = [r for r in fhir_resources if r.get('resourceType') == 'Observation']
        self.assertGreaterEqual(len(observations), 4)  # 2 vitals + 2 labs
        
        # Check blood pressure observation
        bp_obs = next(
            (o for o in observations if 'blood pressure' in o.get('code', {}).get('text', '').lower()),
            None
        )
        self.assertIsNotNone(bp_obs)
        self.assertEqual(bp_obs['subject']['reference'], f'Patient/{self.patient.id}')


class DocumentProcessingTaskUnitTests(TestCase):
    """Unit tests for document processing task."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.user = TestFixtures.create_test_user()
        self.patient = TestFixtures.create_test_patient()
        self.document = TestFixtures.create_test_document(self.patient, self.user)
    
    @patch('apps.documents.analyzers.DocumentAnalyzer.analyze_document_structured')
    @patch('apps.fhir.converters.StructuredDataConverter.convert_structured_data')
    def test_process_document_success(self, mock_convert, mock_analyze):
        """Test successful document processing task."""
        # Mock the analyzer response
        mock_structured_data = TestFixtures.create_structured_medical_data()
        mock_analyze.return_value = mock_structured_data
        
        # Mock the FHIR conversion
        mock_fhir_resources = [
            {
                'resourceType': 'Condition',
                'id': 'condition-1',
                'code': {'text': 'Type 2 Diabetes Mellitus'},
                'subject': {'reference': f'Patient/{self.patient.id}'}
            },
            {
                'resourceType': 'MedicationStatement',
                'id': 'medication-1', 
                'medicationCodeableConcept': {'text': 'Metformin 500mg'},
                'subject': {'reference': f'Patient/{self.patient.id}'}
            }
        ]
        mock_convert.return_value = mock_fhir_resources
        
        # Execute the task
        result = process_document_async(self.document.id)
        
        # Verify results
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, 'review')
        self.assertTrue(hasattr(self.document, 'parsed_data'))
        
        # Verify analyzer was called
        mock_analyze.assert_called_once()
        mock_convert.assert_called_once()
    
    @patch('apps.documents.analyzers.DocumentAnalyzer.analyze_document_structured')
    def test_process_document_ai_failure(self, mock_analyze):
        """Test document processing with AI service failure."""
        # Mock AI service failure
        mock_analyze.side_effect = Exception('AI service error')
        
        # Execute the task
        with self.assertLogs('documents.tasks', level='ERROR'):
            result = process_document_async(self.document.id)
        
        # Verify error handling
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, 'failed')
        self.assertIn('AI service error', self.document.error_message)


# ============================================================================
# 2. INTEGRATION TESTS - Full Pipeline Testing
# ============================================================================

class DocumentPipelineIntegrationTests(TestCase):
    """Integration tests for the complete document processing pipeline."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = TestFixtures.create_test_user()
        self.patient = TestFixtures.create_test_patient()
        self.client.force_login(self.user)
    
    @patch('apps.documents.tasks.process_document_async.delay')
    def test_document_upload_to_processing_pipeline(self, mock_task):
        """Test complete pipeline from document upload to processing initiation."""
        # Mock the Celery task
        mock_task.return_value = Mock(id='test-task-id')
        
        # Create test file
        test_content = b"Patient has diabetes. Taking Metformin 500mg."
        test_file = SimpleUploadedFile(
            "test_doc.pdf",
            test_content,
            content_type="application/pdf"
        )
        
        # Upload document via API
        response = self.client.post(reverse('documents:upload'), {
            'file': test_file,
            'patient': self.patient.id,
        })
        
        # Verify upload success
        self.assertEqual(response.status_code, 302)  # Redirect after upload
        
        # Verify document creation
        document = Document.objects.latest('id')
        self.assertEqual(document.patient, self.patient)
        self.assertEqual(document.uploaded_by, self.user)
        self.assertEqual(document.status, 'uploaded')
        
        # Verify task was queued
        mock_task.assert_called_once_with(document.id)
    
    @patch('apps.documents.services.ai_extraction.extract_medical_data_structured')
    def test_processing_to_review_pipeline(self, mock_extraction):
        """Test pipeline from processing through to review interface."""
        # Setup document
        document = TestFixtures.create_test_document(self.patient, self.user)
        document.status = 'processing'
        document.save()
        
        # Mock AI extraction
        mock_extraction.return_value = TestFixtures.create_structured_medical_data()
        
        # Process document
        process_document_async(document.id)
        
        # Verify processing completed
        document.refresh_from_db()
        self.assertEqual(document.status, 'review')
        self.assertTrue(hasattr(document, 'parsed_data'))
        
        # Test review interface access
        response = self.client.get(reverse('documents:review', args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Type 2 Diabetes')
        self.assertContains(response, 'Metformin')


# ============================================================================
# 3. USER INTERFACE TESTS - Frontend Interaction Testing
# ============================================================================

class ReviewInterfaceTests(TestCase):
    """Tests for the document review interface functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = TestFixtures.create_test_user()
        self.patient = TestFixtures.create_test_patient()
        self.document = TestFixtures.create_test_document(self.patient, self.user)
        self.client.force_login(self.user)
        
        # Create parsed data for review
        structured_data = TestFixtures.create_structured_medical_data()
        self.parsed_data = ParsedData.objects.create(
            document=self.document,
            structured_data=structured_data.dict(),
            ai_model_used='claude-3-sonnet',
            processing_time_seconds=5.2,
            extraction_confidence=0.9
        )
        self.document.status = 'review'
        self.document.save()
    
    def test_review_interface_display(self):
        """Test that review interface displays structured data correctly."""
        response = self.client.get(reverse('documents:review', args=[self.document.pk]))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Type 2 Diabetes Mellitus')
        self.assertContains(response, 'Essential Hypertension')
        self.assertContains(response, 'Metformin')
        self.assertContains(response, 'Lisinopril')
        self.assertContains(response, 'Blood Pressure')
        self.assertContains(response, 'Glucose')
    
    def test_field_approval_endpoint(self):
        """Test field approval AJAX endpoint."""
        # Test data
        field_data = {
            'document_id': self.document.id,
            'field_name': 'Type 2 Diabetes Mellitus',
            'field_value': 'Type 2 Diabetes Mellitus',
            'confidence': '0.9',
            'snippet': 'Type 2 Diabetes Mellitus - Continue Metformin'
        }
        
        # Make AJAX request to approve field
        response = self.client.post(
            reverse('documents:approve-field', args=['test-field-id']),
            data=field_data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        self.assertEqual(response.status_code, 200)
        # Response should contain updated field card HTML
        self.assertContains(response, 'field-review-card')
    
    def test_field_edit_endpoint(self):
        """Test field value edit AJAX endpoint."""
        # Test data
        field_data = {
            'document_id': self.document.id,
            'field_name': 'Type 2 Diabetes Mellitus',
            'value': 'Type 1 Diabetes Mellitus',  # Edited value
            'confidence': '0.9',
            'snippet': 'Type 2 Diabetes Mellitus - Continue Metformin'
        }
        
        # Make AJAX request to edit field
        response = self.client.post(
            reverse('documents:update-field', args=['test-field-id']),
            data=field_data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        self.assertEqual(response.status_code, 200)
        # Response should contain updated field card HTML
        self.assertContains(response, 'field-review-card')
        self.assertContains(response, 'Type 1 Diabetes')
    
    def test_field_flag_endpoint(self):
        """Test field flagging AJAX endpoint."""
        # Test data
        field_data = {
            'document_id': self.document.id,
            'field_name': 'Type 2 Diabetes Mellitus',
            'field_value': 'Type 2 Diabetes Mellitus',
            'confidence': '0.9',
            'snippet': 'Type 2 Diabetes Mellitus - Continue Metformin',
            'reason': 'Unclear diagnosis specification'
        }
        
        # Make AJAX request to flag field
        response = self.client.post(
            reverse('documents:flag-field', args=['test-field-id']),
            data=field_data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        self.assertEqual(response.status_code, 200)
        # Response should contain updated field card HTML with flag
        self.assertContains(response, 'field-review-card')
        self.assertContains(response, 'FLAGGED')


# ============================================================================
# 4. PERFORMANCE TESTS - Processing Time Benchmarks
# ============================================================================

@pytest.mark.performance
class DocumentProcessingPerformanceTests(TestCase):
    """Performance tests for document processing pipeline."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.user = TestFixtures.create_test_user()
        self.patient = TestFixtures.create_test_patient()
    
    def create_test_document_by_size(self, size_mb):
        """Create a test document of specified size."""
        # Create content of approximately the specified size
        base_content = "Patient has diabetes. Taking Metformin 500mg twice daily. "
        content_size = size_mb * 1024 * 1024  # Convert MB to bytes
        content = (base_content * (content_size // len(base_content) + 1))[:content_size]
        
        return TestFixtures.create_test_document(
            patient=self.patient,
            user=self.user,
            content=content.encode('utf-8')
        )
    
    @patch('apps.documents.services.ai_extraction.extract_medical_data_structured')
    def test_processing_time_small_document(self, mock_extraction):
        """Test processing time for small documents (1MB)."""
        # Mock AI extraction to avoid external API calls
        mock_extraction.return_value = TestFixtures.create_structured_medical_data()
        
        # Create 1MB document
        document = self.create_test_document_by_size(1)
        
        # Measure processing time
        start_time = time.time()
        process_document_async(document.id)
        end_time = time.time()
        
        processing_time = end_time - start_time
        
        # Verify processing completed
        document.refresh_from_db()
        self.assertEqual(document.status, 'review')
        
        # Verify performance (should be under 10 seconds for 1MB)
        self.assertLess(processing_time, 10.0, 
                       f"Processing took {processing_time:.2f}s, expected <10s")
    
    @patch('apps.documents.services.ai_extraction.extract_medical_data_structured')
    def test_processing_time_medium_document(self, mock_extraction):
        """Test processing time for medium documents (5MB)."""
        # Mock AI extraction
        mock_extraction.return_value = TestFixtures.create_structured_medical_data()
        
        # Create 5MB document
        document = self.create_test_document_by_size(5)
        
        # Measure processing time
        start_time = time.time()
        process_document_async(document.id)
        end_time = time.time()
        
        processing_time = end_time - start_time
        
        # Verify processing completed
        document.refresh_from_db()
        self.assertEqual(document.status, 'review')
        
        # Verify performance (should be under 30 seconds for 5MB)
        self.assertLess(processing_time, 30.0,
                       f"Processing took {processing_time:.2f}s, expected <30s")


# ============================================================================
# 5. ERROR HANDLING TESTS - Failure Scenarios and Edge Cases
# ============================================================================

class ErrorHandlingTests(TestCase):
    """Tests for error handling in the document processing pipeline."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = TestFixtures.create_test_user()
        self.patient = TestFixtures.create_test_patient()
        self.client.force_login(self.user)
    
    def test_invalid_document_upload(self):
        """Test handling of invalid document formats."""
        # Create invalid file (text instead of PDF)
        invalid_file = SimpleUploadedFile(
            "invalid_doc.txt",
            b"This is not a PDF file",
            content_type="text/plain"
        )
        
        # Attempt upload
        response = self.client.post(reverse('documents:upload'), {
            'file': invalid_file,
            'patient': self.patient.id,
        })
        
        # Should return form with errors
        self.assertEqual(response.status_code, 200)  # Form redisplay
        self.assertContains(response, 'Invalid file format')
    
    def test_corrupted_document_processing(self):
        """Test handling of corrupted documents during processing."""
        # Create document with corrupted content
        corrupted_content = b'\x00\x01\x02\x03CORRUPTED\xFF\xFE'
        document = TestFixtures.create_test_document(
            patient=self.patient,
            user=self.user,
            content=corrupted_content
        )
        
        # Process document
        process_document_async(document.id)
        
        # Verify error handling
        document.refresh_from_db()
        self.assertEqual(document.status, 'failed')
        self.assertIsNotNone(document.error_message)
    
    @patch('apps.documents.services.ai_extraction.extract_medical_data_structured')
    def test_ai_service_failure_handling(self, mock_extraction):
        """Test handling of AI service failures."""
        # Mock AI service failure
        mock_extraction.side_effect = Exception('AI service timeout')
        
        # Create and process document
        document = TestFixtures.create_test_document(self.patient, self.user)
        
        # Process document
        process_document_async(document.id)
        
        # Verify error handling
        document.refresh_from_db()
        self.assertEqual(document.status, 'failed')
        self.assertIn('AI service timeout', document.error_message)
    
    @patch('apps.fhir.converters.StructuredDataConverter.convert_structured_data')
    def test_fhir_conversion_failure_handling(self, mock_convert):
        """Test handling of FHIR conversion failures."""
        # Mock FHIR conversion failure
        mock_convert.side_effect = Exception('FHIR validation error')
        
        # Create and process document
        document = TestFixtures.create_test_document(self.patient, self.user)
        
        # Process document with mocked AI extraction
        with patch('apps.documents.services.ai_extraction.extract_medical_data_structured') as mock_ai:
            mock_ai.return_value = TestFixtures.create_structured_medical_data()
            process_document_async(document.id)
        
        # Verify error handling
        document.refresh_from_db()
        self.assertEqual(document.status, 'failed')
        self.assertIn('FHIR validation error', document.error_message)


# ============================================================================
# 6. SECURITY TESTS - Audit Logging and HIPAA Compliance
# ============================================================================

class SecurityAndAuditTests(TestCase):
    """Tests for security features and HIPAA compliance."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = TestFixtures.create_test_user()
        self.patient = TestFixtures.create_test_patient()
        self.client.force_login(self.user)
    
    def test_audit_logging_document_creation(self):
        """Test that document creation is properly audited."""
        initial_log_count = AuditLog.objects.count()
        
        # Create and process document
        document = TestFixtures.create_test_document(self.patient, self.user)
        
        # Check audit logs
        new_logs = AuditLog.objects.filter(timestamp__gt=document.created_at)
        self.assertGreater(new_logs.count(), 0)
        
        # Verify document creation was logged
        create_logs = new_logs.filter(
            action='CREATE',
            resource_type='Document'
        )
        self.assertTrue(create_logs.exists())
    
    @patch('apps.documents.services.ai_extraction.extract_medical_data_structured')
    def test_audit_logging_document_processing(self, mock_extraction):
        """Test that document processing is properly audited."""
        # Mock AI extraction
        mock_extraction.return_value = TestFixtures.create_structured_medical_data()
        
        # Create and process document
        document = TestFixtures.create_test_document(self.patient, self.user)
        process_document_async(document.id)
        
        # Check audit logs for FHIR resource creation
        new_logs = AuditLog.objects.filter(timestamp__gt=document.created_at)
        
        # Verify FHIR resources were logged
        condition_logs = new_logs.filter(
            action='CREATE',
            resource_type='Condition'
        )
        medication_logs = new_logs.filter(
            action='CREATE', 
            resource_type='MedicationStatement'
        )
        
        self.assertTrue(condition_logs.exists())
        self.assertTrue(medication_logs.exists())
    
    def test_phi_access_logging(self):
        """Test that PHI access is properly logged."""
        # Create document with parsed data
        document = TestFixtures.create_test_document(self.patient, self.user)
        document.status = 'review'
        document.save()
        
        # Access review interface (PHI access)
        initial_log_count = AuditLog.objects.count()
        response = self.client.get(reverse('documents:review', args=[document.pk]))
        
        # Verify PHI access was logged
        new_logs = AuditLog.objects.filter(timestamp__gt=document.created_at)
        phi_access_logs = new_logs.filter(
            action='VIEW',
            resource_type='ParsedData'
        )
        
        self.assertTrue(phi_access_logs.exists())
    
    def test_user_permission_checks(self):
        """Test that proper permission checks are enforced."""
        # Create document for different user
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='otherpass123'
        )
        other_patient = Patient.objects.create(
            first_name='Jane',
            last_name='Doe',
            date_of_birth='1985-05-20',
            mrn='TEST002'
        )
        
        document = TestFixtures.create_test_document(other_patient, other_user)
        document.status = 'review'
        document.save()
        
        # Try to access as current user (should be denied)
        response = self.client.get(reverse('documents:review', args=[document.pk]))
        
        # Should be forbidden or redirected
        self.assertIn(response.status_code, [403, 302])


# ============================================================================
# 7. END-TO-END TESTS - Complete Workflow Testing
# ============================================================================

class EndToEndWorkflowTests(TestCase):
    """End-to-end tests for the complete document processing workflow."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = TestFixtures.create_test_user()
        self.patient = TestFixtures.create_test_patient()
        self.provider = TestFixtures.create_test_provider()
        self.client.force_login(self.user)
    
    @patch('apps.documents.services.ai_extraction.extract_medical_data_structured')
    @patch('apps.documents.tasks.process_document_async.delay')
    def test_complete_workflow_upload_to_fhir_bundle(self, mock_task, mock_extraction):
        """Test complete workflow from upload to FHIR bundle creation."""
        # Setup mocks
        mock_extraction.return_value = TestFixtures.create_structured_medical_data()
        mock_task.return_value = Mock(id='test-task-id')
        
        # 1. Upload document
        test_file = SimpleUploadedFile(
            "test_medical_record.pdf",
            b"Patient has diabetes. Taking Metformin 500mg.",
            content_type="application/pdf"
        )
        
        upload_response = self.client.post(reverse('documents:upload'), {
            'file': test_file,
            'patient': self.patient.id,
        })
        
        self.assertEqual(upload_response.status_code, 302)
        document = Document.objects.latest('id')
        
        # 2. Process document (simulate async completion)
        process_document_async(document.id)
        document.refresh_from_db()
        self.assertEqual(document.status, 'review')
        
        # 3. Review and approve fields
        review_response = self.client.get(reverse('documents:review', args=[document.pk]))
        self.assertEqual(review_response.status_code, 200)
        
        # Simulate field approvals
        field_approval_data = {
            'document_id': document.id,
            'field_name': 'Type 2 Diabetes Mellitus',
            'field_value': 'Type 2 Diabetes Mellitus',
            'confidence': '0.9'
        }
        
        approval_response = self.client.post(
            reverse('documents:approve-field', args=['condition-1']),
            data=field_approval_data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(approval_response.status_code, 200)
        
        # 4. Complete review and approve document
        complete_response = self.client.post(
            reverse('documents:review', args=[document.pk]),
            data={'action': 'approve'}
        )
        
        document.refresh_from_db()
        self.assertEqual(document.status, 'completed')
        
        # 5. Generate FHIR bundle
        bundle_service = FHIRBundleService()
        fhir_bundle = bundle_service.create_fhir_bundle(self.patient, [document])
        
        # Verify bundle structure
        self.assertIsNotNone(fhir_bundle)
        self.assertEqual(fhir_bundle.get('resourceType'), 'Bundle')
        self.assertTrue(len(fhir_bundle.get('entry', [])) > 0)
        
        # Verify specific resources in bundle
        entries = fhir_bundle.get('entry', [])
        resource_types = [entry.get('resource', {}).get('resourceType') for entry in entries]
        
        self.assertIn('Condition', resource_types)
        self.assertIn('MedicationStatement', resource_types)
        self.assertIn('Observation', resource_types)
    
    @patch('apps.documents.services.ai_extraction.extract_medical_data_structured')
    def test_workflow_with_field_edits_and_flags(self, mock_extraction):
        """Test workflow including field edits and flagging."""
        # Setup mock
        mock_extraction.return_value = TestFixtures.create_structured_medical_data()
        
        # Create and process document
        document = TestFixtures.create_test_document(self.patient, self.user)
        process_document_async(document.id)
        document.refresh_from_db()
        
        # Access review interface
        review_response = self.client.get(reverse('documents:review', args=[document.pk]))
        self.assertEqual(review_response.status_code, 200)
        
        # Edit a field value
        edit_data = {
            'document_id': document.id,
            'field_name': 'Type 2 Diabetes Mellitus',
            'value': 'Type 1 Diabetes Mellitus',  # Edited value
            'confidence': '0.9'
        }
        
        edit_response = self.client.post(
            reverse('documents:update-field', args=['condition-1']),
            data=edit_data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(edit_response.status_code, 200)
        
        # Flag a field
        flag_data = {
            'document_id': document.id,
            'field_name': 'Essential Hypertension',
            'field_value': 'Essential Hypertension',
            'reason': 'Needs clarification'
        }
        
        flag_response = self.client.post(
            reverse('documents:flag-field', args=['condition-2']),
            data=flag_data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(flag_response.status_code, 200)
        
        # Complete review
        complete_response = self.client.post(
            reverse('documents:review', args=[document.pk]),
            data={'action': 'approve'}
        )
        
        # Verify final state
        document.refresh_from_db()
        self.assertEqual(document.status, 'completed')


if __name__ == '__main__':
    pytest.main([__file__])
