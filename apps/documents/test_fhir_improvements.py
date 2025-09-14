"""
Comprehensive tests for FHIR Bundle Structure Improvements.

Tests the new FHIR-focused extraction, structured resource creation,
temporal data processing, and backward compatibility.
"""

import json
import uuid
from datetime import datetime, date
from django.test import TestCase
from django.utils import timezone
from unittest.mock import Mock, patch, MagicMock

from apps.documents.services import DocumentAnalyzer
from apps.documents.models import Document, ParsedData
from apps.patients.models import Patient
from apps.providers.models import Provider
from apps.core.models import User


class TestFHIRStructuredExtraction(TestCase):
    """Test the new FHIR-structured extraction format processing."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            mrn='TEST123',
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            gender='M',
            created_by=self.user
        )
        
        self.document = Document.objects.create(
            patient=self.patient,
            filename='test_document.pdf',
            status='completed',
            original_text='Test medical document content',
            uploaded_by=self.user
        )
        
        self.analyzer = DocumentAnalyzer(document=self.document)
    
    def test_fhir_format_detection(self):
        """Test detection of FHIR-structured vs legacy format."""
        # FHIR-structured format
        fhir_structured = {
            "Patient": {"name": {"value": "Doe, John"}},
            "Condition": [{"code": {"value": "Hypertension"}}]
        }
        
        # Legacy format
        legacy_format = [
            {"label": "patientName", "value": "John Doe", "confidence": 0.9},
            {"label": "diagnoses", "value": "Hypertension; Diabetes", "confidence": 0.8}
        ]
        
        self.assertTrue(self.analyzer._is_fhir_structured_format(fhir_structured))
        self.assertFalse(self.analyzer._is_fhir_structured_format(legacy_format))
    
    def test_patient_resource_creation_from_structured(self):
        """Test Patient resource creation from structured data."""
        patient_data = {
            "name": {"value": "Doe, John", "confidence": 0.9},
            "birthDate": {"value": "1980-01-15", "confidence": 0.9},
            "gender": {"value": "male", "confidence": 0.8},
            "identifier": {"value": "TEST123", "confidence": 0.9}
        }
        
        patient_resource = self.analyzer._create_patient_resource_from_structured(
            patient_data, str(self.patient.id)
        )
        
        self.assertIsNotNone(patient_resource)
        self.assertEqual(patient_resource['resourceType'], 'Patient')
        self.assertEqual(patient_resource['name'][0]['family'], 'Doe')
        self.assertEqual(patient_resource['name'][0]['given'], ['John'])
        self.assertEqual(patient_resource['birthDate'], '1980-01-15')
        self.assertEqual(patient_resource['gender'], 'male')
        self.assertEqual(patient_resource['identifier'][0]['value'], 'TEST123')
    
    def test_condition_resource_creation_with_dates(self):
        """Test Condition resource creation with temporal data."""
        condition_data = {
            "code": {"value": "Hypertension", "confidence": 0.8},
            "status": "active",
            "onsetDateTime": {"value": "2023-06-15", "confidence": 0.7},
            "recordedDate": {"value": "2023-06-20", "confidence": 0.8}
        }
        
        condition_resource = self.analyzer._create_condition_resource_from_structured(
            condition_data, str(self.patient.id)
        )
        
        self.assertIsNotNone(condition_resource)
        self.assertEqual(condition_resource['resourceType'], 'Condition')
        self.assertEqual(condition_resource['code']['text'], 'Hypertension')
        self.assertEqual(condition_resource['onsetDateTime'], '2023-06-15')
        self.assertEqual(condition_resource['recordedDate'], '2023-06-20')
        self.assertEqual(condition_resource['subject']['reference'], f'Patient/{self.patient.id}')
    
    def test_medication_resource_creation_with_periods(self):
        """Test MedicationStatement resource creation with effective periods."""
        medication_data = {
            "medication": {"value": "Lisinopril 10mg", "confidence": 0.9},
            "dosage": {"value": "Once daily", "confidence": 0.8},
            "effectivePeriod": {
                "start": {"value": "2023-06-01", "confidence": 0.8},
                "end": {"value": "2023-12-01", "confidence": 0.7}
            }
        }
        
        med_resource = self.analyzer._create_medication_resource_from_structured(
            medication_data, str(self.patient.id)
        )
        
        self.assertIsNotNone(med_resource)
        self.assertEqual(med_resource['resourceType'], 'MedicationStatement')
        self.assertEqual(med_resource['medicationCodeableConcept']['text'], 'Lisinopril 10mg')
        self.assertEqual(med_resource['dosage'][0]['text'], 'Once daily')
        self.assertEqual(med_resource['effectivePeriod']['start'], '2023-06-01')
        self.assertEqual(med_resource['effectivePeriod']['end'], '2023-12-01')
    
    def test_multiple_conditions_from_structured_array(self):
        """Test processing multiple conditions from FHIR-structured array."""
        fhir_data = {
            "Condition": [
                {"code": {"value": "Hypertension", "confidence": 0.8}},
                {"code": {"value": "Diabetes Type 2", "confidence": 0.9}},
                {"code": {"value": "Heart murmur", "confidence": 0.7}}
            ]
        }
        
        fhir_resources = self.analyzer._convert_fhir_structured_to_resources(
            fhir_data, str(self.patient.id)
        )
        
        # Should create 3 Condition resources + 1 DocumentReference
        condition_resources = [r for r in fhir_resources if r['resourceType'] == 'Condition']
        self.assertEqual(len(condition_resources), 3)
        
        condition_texts = [r['code']['text'] for r in condition_resources]
        self.assertIn('Hypertension', condition_texts)
        self.assertIn('Diabetes Type 2', condition_texts)
        self.assertIn('Heart murmur', condition_texts)
    
    def test_backward_compatibility_with_legacy_format(self):
        """Test that legacy format still works with new converter."""
        legacy_fields = [
            {"label": "patientName", "value": "John Doe", "confidence": 0.9},
            {"label": "diagnoses", "value": "Hypertension; Diabetes", "confidence": 0.8},
            {"label": "medications", "value": "Lisinopril 10mg; Metformin 500mg", "confidence": 0.9}
        ]
        
        fhir_resources = self.analyzer.convert_to_fhir(legacy_fields, str(self.patient.id))
        
        self.assertGreater(len(fhir_resources), 0)
        
        # Should still create proper resource types
        resource_types = {r['resourceType'] for r in fhir_resources}
        self.assertIn('Condition', resource_types)
        self.assertIn('MedicationStatement', resource_types)
        self.assertIn('DocumentReference', resource_types)


class TestTemporalDataProcessing(TestCase):
    """Test temporal data processing utilities."""
    
    def setUp(self):
        """Set up test analyzer."""
        self.analyzer = DocumentAnalyzer()
    
    def test_parse_and_format_date_various_formats(self):
        """Test date parsing with various input formats."""
        test_cases = [
            # (input, expected_output)
            ('01/15/1980', '1980-01-15'),  # MM/DD/YYYY
            ('15/01/1980', '1980-01-15'),  # DD/MM/YYYY (ambiguous, but should work)
            ('1980-01-15', '1980-01-15'),  # Already ISO 8601
            ('January 15, 1980', '1980-01-15'),  # Natural language
            ('Jan 15, 1980', '1980-01-15'),   # Abbreviated month
            ('15 January 1980', '1980-01-15'), # European format
        ]
        
        for input_date, expected in test_cases:
            with self.subTest(input_date=input_date):
                result = self.analyzer.parse_and_format_date(input_date)
                self.assertEqual(result, expected, f"Failed to parse {input_date}")
    
    def test_iso8601_format_detection(self):
        """Test ISO 8601 format detection."""
        valid_iso_dates = [
            '2023-06-15',
            '2023-06-15T14:30:00',
            '2023-06-15T14:30:00.123',
            '2023-06-15T14:30:00+05:00',
            '2023-06-15T14:30:00.123+05:00'
        ]
        
        invalid_iso_dates = [
            '06/15/2023',
            '15-06-2023',
            'June 15, 2023',
            '2023/06/15'
        ]
        
        for valid_date in valid_iso_dates:
            with self.subTest(date=valid_date):
                self.assertTrue(self.analyzer._is_iso8601_format(valid_date))
        
        for invalid_date in invalid_iso_dates:
            with self.subTest(date=invalid_date):
                self.assertFalse(self.analyzer._is_iso8601_format(invalid_date))
    
    def test_process_temporal_data_condition(self):
        """Test temporal data processing for Condition resources."""
        condition_resource = {
            "resourceType": "Condition",
            "code": {"text": "Hypertension"},
            "onsetDateTime": "01/15/2023",  # Non-ISO format
            "recordedDate": "2023-01-20"    # Already ISO format
        }
        
        processed = self.analyzer.process_temporal_data(condition_resource)
        
        self.assertEqual(processed['onsetDateTime'], '2023-01-15')
        self.assertEqual(processed['recordedDate'], '2023-01-20')  # Should remain unchanged
    
    def test_process_period_data(self):
        """Test processing of period objects."""
        period_data = {
            "start": "01/15/2023",
            "end": "06/15/2023"
        }
        
        processed_period = self.analyzer._process_period_data(period_data)
        
        self.assertEqual(processed_period['start'], '2023-01-15')
        self.assertEqual(processed_period['end'], '2023-06-15')
    
    def test_validate_fhir_temporal_compliance(self):
        """Test FHIR temporal compliance validation."""
        # Valid resource
        valid_resource = {
            "resourceType": "Condition",
            "onsetDateTime": "2023-01-15",
            "recordedDate": "2023-01-20T14:30:00"
        }
        
        # Invalid resource
        invalid_resource = {
            "resourceType": "Condition",
            "onsetDateTime": "01/15/2023",  # Invalid format
            "recordedDate": "not-a-date"    # Invalid format
        }
        
        valid_result = self.analyzer.validate_fhir_temporal_compliance(valid_resource)
        invalid_result = self.analyzer.validate_fhir_temporal_compliance(invalid_resource)
        
        self.assertTrue(valid_result['is_valid'])
        self.assertEqual(len(valid_result['errors']), 0)
        
        self.assertFalse(invalid_result['is_valid'])
        self.assertGreater(len(invalid_result['errors']), 0)


class TestFHIRConverterCompatibility(TestCase):
    """Test FHIR converter compatibility with both formats."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com', 
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            mrn='TEST123',
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            gender='M',
            created_by=self.user
        )
        
        self.document = Document.objects.create(
            patient=self.patient,
            filename='test_document.pdf',
            status='completed',
            original_text='Test content',
            uploaded_by=self.user
        )
        
        self.analyzer = DocumentAnalyzer(document=self.document)
    
    def test_convert_fhir_structured_format(self):
        """Test conversion of FHIR-structured format."""
        fhir_structured_data = {
            "Patient": {
                "name": {"value": "Doe, John", "confidence": 0.9},
                "birthDate": {"value": "1980-01-15", "confidence": 0.9}
            },
            "Condition": [
                {
                    "code": {"value": "Hypertension", "confidence": 0.8},
                    "onsetDateTime": {"value": "2023-06-15", "confidence": 0.7}
                },
                {
                    "code": {"value": "Diabetes Type 2", "confidence": 0.9},
                    "onsetDateTime": {"value": "2023-07-01", "confidence": 0.8}
                }
            ],
            "MedicationStatement": [
                {
                    "medication": {"value": "Lisinopril 10mg", "confidence": 0.9},
                    "effectiveDateTime": {"value": "2023-06-15", "confidence": 0.8}
                }
            ]
        }
        
        fhir_resources = self.analyzer.convert_to_fhir(fhir_structured_data, str(self.patient.id))
        
        # Verify resource types and counts
        resource_types = [r['resourceType'] for r in fhir_resources]
        
        self.assertIn('Patient', resource_types)
        self.assertIn('Condition', resource_types)
        self.assertIn('MedicationStatement', resource_types)
        self.assertIn('DocumentReference', resource_types)
        
        # Should have 2 Condition resources
        conditions = [r for r in fhir_resources if r['resourceType'] == 'Condition']
        self.assertEqual(len(conditions), 2)
        
        # Verify temporal data is included
        hypertension_condition = next(r for r in conditions if r['code']['text'] == 'Hypertension')
        self.assertEqual(hypertension_condition['onsetDateTime'], '2023-06-15')
    
    def test_convert_legacy_format(self):
        """Test conversion of legacy flat field format."""
        legacy_data = [
            {"label": "patientName", "value": "John Doe", "confidence": 0.9},
            {"label": "diagnoses", "value": "Hypertension; Diabetes", "confidence": 0.8},
            {"label": "medications", "value": "Lisinopril 10mg", "confidence": 0.9}
        ]
        
        fhir_resources = self.analyzer.convert_to_fhir(legacy_data, str(self.patient.id))
        
        # Should still create proper resources
        resource_types = [r['resourceType'] for r in fhir_resources]
        self.assertIn('Condition', resource_types)
        self.assertIn('MedicationStatement', resource_types)
        self.assertIn('DocumentReference', resource_types)
    
    def test_allergy_resource_creation(self):
        """Test AllergyIntolerance resource creation."""
        allergy_data = {
            "substance": {"value": "Penicillin", "confidence": 0.9},
            "reaction": {"value": "Rash", "confidence": 0.8},
            "onsetDateTime": {"value": "2020-03-15", "confidence": 0.7}
        }
        
        allergy_resource = self.analyzer._create_allergy_resource_from_structured(
            allergy_data, str(self.patient.id)
        )
        
        self.assertIsNotNone(allergy_resource)
        self.assertEqual(allergy_resource['resourceType'], 'AllergyIntolerance')
        self.assertEqual(allergy_resource['code']['text'], 'Penicillin')
        self.assertEqual(allergy_resource['reaction'][0]['manifestation'][0]['text'], 'Rash')
        self.assertEqual(allergy_resource['onsetDateTime'], '2020-03-15')
    
    def test_procedure_resource_creation(self):
        """Test Procedure resource creation with performed dates."""
        procedure_data = {
            "code": {"value": "Echocardiogram", "confidence": 0.9},
            "performedDateTime": {"value": "2023-08-15", "confidence": 0.8}
        }
        
        procedure_resource = self.analyzer._create_procedure_resource_from_structured(
            procedure_data, str(self.patient.id)
        )
        
        self.assertIsNotNone(procedure_resource)
        self.assertEqual(procedure_resource['resourceType'], 'Procedure')
        self.assertEqual(procedure_resource['code']['text'], 'Echocardiogram')
        self.assertEqual(procedure_resource['performedDateTime'], '2023-08-15')
        self.assertEqual(procedure_resource['status'], 'completed')


class TestFHIRIntegrationWorkflow(TestCase):
    """Test the complete FHIR processing workflow."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            mrn='TEST123',
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            gender='M',
            created_by=self.user
        )
        
        self.document = Document.objects.create(
            patient=self.patient,
            filename='test_document.pdf',
            status='completed',
            original_text='Test medical document with patient John Doe, diagnosed with hypertension on 06/15/2023.',
            uploaded_by=self.user
        )
    
    @patch('apps.documents.services.DocumentAnalyzer._call_openai_with_recovery')
    def test_end_to_end_fhir_processing(self, mock_ai_service):
        """Test complete end-to-end FHIR processing with new format."""
        # Mock AI response in FHIR-structured format
        mock_ai_response = {
            "Patient": {
                "name": {"value": "Doe, John", "confidence": 0.9, "source_text": "patient John Doe", "char_position": 20},
                "birthDate": {"value": "1980-01-15", "confidence": 0.8, "source_text": "born 01/15/1980", "char_position": 45},
                "gender": {"value": "male", "confidence": 0.8, "source_text": "male patient", "char_position": 10},
                "identifier": {"value": "TEST123", "confidence": 0.9, "source_text": "MRN TEST123", "char_position": 5}
            },
            "Condition": [
                {
                    "code": {"value": "Hypertension", "confidence": 0.8, "source_text": "diagnosed with hypertension", "char_position": 60},
                    "onsetDateTime": {"value": "2023-06-15", "confidence": 0.7, "source_text": "on 06/15/2023", "char_position": 85}
                }
            ]
        }
        
        mock_ai_service.return_value = {
            'success': True,
            'content': json.dumps(mock_ai_response),
            'model_used': 'test-model',
            'usage': {'total_tokens': 100}
        }
        
        # Process document
        analyzer = DocumentAnalyzer(document=self.document)
        result = analyzer.analyze_document(self.document.original_text)
        
        self.assertTrue(result['success'])
        
        # Convert to FHIR
        fhir_resources = analyzer.convert_to_fhir(result['fields'], str(self.patient.id))
        
        # Verify results
        self.assertGreater(len(fhir_resources), 0)
        
        # Should have Patient and Condition resources
        resource_types = [r['resourceType'] for r in fhir_resources]
        self.assertIn('Patient', resource_types)
        self.assertIn('Condition', resource_types)
        
        # Verify temporal data is included
        condition = next(r for r in fhir_resources if r['resourceType'] == 'Condition')
        self.assertEqual(condition['onsetDateTime'], '2023-06-15')
    
    def test_parsed_data_creation_with_new_format(self):
        """Test ParsedData creation with FHIR-structured format."""
        fhir_structured_fields = {
            "Patient": {"name": {"value": "Doe, John", "confidence": 0.9}},
            "Condition": [{"code": {"value": "Hypertension", "confidence": 0.8}}]
        }
        
        # Create ParsedData as would be done in the task
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json=fhir_structured_fields,
            fhir_delta_json=[],  # Would be populated by FHIR conversion
            extraction_confidence=0.85,
            ai_model_used='test-model'
        )
        
        self.assertIsNotNone(parsed_data)
        self.assertEqual(parsed_data.extraction_confidence, 0.85)
        self.assertFalse(parsed_data.is_approved)  # Should require review


class TestDataMigrationCommand(TestCase):
    """Test the data migration management command."""
    
    def setUp(self):
        """Set up test data for migration testing."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            mrn='TEST123',
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            gender='M',
            created_by=self.user
        )
        
        # Create document with legacy-style ParsedData
        self.document = Document.objects.create(
            patient=self.patient,
            filename='legacy_document.pdf',
            status='completed',
            original_text='Legacy medical document content',
            uploaded_by=self.user
        )
        
        # Create legacy-format ParsedData
        legacy_fields = [
            {"label": "diagnoses", "value": "Hypertension; Diabetes", "confidence": 0.8},
            {"label": "medications", "value": "Lisinopril; Metformin", "confidence": 0.9}
        ]
        
        self.parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json=legacy_fields,
            fhir_delta_json=[],  # Legacy format
            extraction_confidence=0.85,
            is_approved=True,
            is_merged=True
        )
    
    def test_migration_command_dry_run(self):
        """Test migration command in dry run mode."""
        from django.core.management import call_command
        from io import StringIO
        
        out = StringIO()
        call_command('reprocess_fhir_extraction', '--dry-run', '--document-ids', str(self.document.id), stdout=out)
        
        output = out.getvalue()
        self.assertIn('Would reprocess', output)
        self.assertIn(str(self.document.id), output)
    
    @patch('apps.documents.services.DocumentAnalyzer.analyze_document')
    def test_migration_command_execution(self, mock_analyze):
        """Test actual migration command execution."""
        # Mock the AI analysis to return FHIR-structured format
        mock_analyze.return_value = {
            'success': True,
            'fields': {
                "Condition": [
                    {"code": {"value": "Hypertension", "confidence": 0.8}},
                    {"code": {"value": "Diabetes Type 2", "confidence": 0.9}}
                ]
            },
            'model_used': 'test-model'
        }
        
        from django.core.management import call_command
        from io import StringIO
        
        out = StringIO()
        call_command('reprocess_fhir_extraction', '--document-ids', str(self.document.id), '--force', stdout=out)
        
        # Verify ParsedData was updated
        self.parsed_data.refresh_from_db()
        
        # Should have new FHIR-structured extraction_json
        extraction_json = self.parsed_data.extraction_json
        self.assertIsInstance(extraction_json, dict)
        self.assertIn('Condition', extraction_json)
        
        # Should be reset for re-review
        self.assertFalse(self.parsed_data.is_approved)
        self.assertFalse(self.parsed_data.is_merged)


class TestFHIRResourceValidation(TestCase):
    """Test FHIR resource validation and compliance."""
    
    def setUp(self):
        """Set up test analyzer."""
        self.analyzer = DocumentAnalyzer()
    
    def test_fhir_resource_structure_validation(self):
        """Test that generated FHIR resources have proper structure."""
        condition_data = {
            "code": {"value": "Hypertension", "confidence": 0.8},
            "onsetDateTime": {"value": "2023-06-15", "confidence": 0.7}
        }
        
        condition_resource = self.analyzer._create_condition_resource_from_structured(
            condition_data, "patient-123"
        )
        
        # Verify required FHIR fields
        self.assertIn('resourceType', condition_resource)
        self.assertIn('id', condition_resource)
        self.assertIn('meta', condition_resource)
        self.assertIn('code', condition_resource)
        self.assertIn('clinicalStatus', condition_resource)
        self.assertIn('subject', condition_resource)
        
        # Verify FHIR compliance
        self.assertEqual(condition_resource['resourceType'], 'Condition')
        self.assertEqual(condition_resource['subject']['reference'], 'Patient/patient-123')
        self.assertIn('coding', condition_resource['clinicalStatus'])
    
    def test_confidence_score_preservation(self):
        """Test that confidence scores are preserved in FHIR resources."""
        medication_data = {
            "medication": {"value": "Aspirin 81mg", "confidence": 0.95}
        }
        
        med_resource = self.analyzer._create_medication_resource_from_structured(
            medication_data, "patient-123"
        )
        
        # Verify confidence is stored in extension
        self.assertIn('extension', med_resource)
        confidence_extension = med_resource['extension'][0]
        self.assertEqual(confidence_extension['valueDecimal'], 0.95)
    
    def test_empty_or_invalid_data_handling(self):
        """Test handling of empty or invalid structured data."""
        # Empty condition data
        empty_condition = {"code": {"value": "", "confidence": 0.1}}
        condition_resource = self.analyzer._create_condition_resource_from_structured(empty_condition)
        self.assertIsNone(condition_resource)
        
        # Missing required fields
        incomplete_medication = {"dosage": {"value": "Once daily"}}  # No medication name
        med_resource = self.analyzer._create_medication_resource_from_structured(incomplete_medication)
        self.assertIsNone(med_resource)
    
    def test_date_format_standardization(self):
        """Test that various date formats are standardized to ISO 8601."""
        test_dates = [
            "01/15/2023",      # MM/DD/YYYY
            "15/01/2023",      # DD/MM/YYYY  
            "January 15, 2023", # Natural language
            "2023-01-15"       # Already ISO 8601
        ]
        
        for input_date in test_dates:
            with self.subTest(input_date=input_date):
                formatted_date = self.analyzer.parse_and_format_date(input_date)
                
                # Should be in YYYY-MM-DD format
                self.assertIsNotNone(formatted_date)
                self.assertRegex(formatted_date, r'^\d{4}-\d{2}-\d{2}$')


class TestErrorHandlingAndFallbacks(TestCase):
    """Test error handling and fallback mechanisms."""
    
    def setUp(self):
        """Set up test analyzer."""
        self.analyzer = DocumentAnalyzer()
    
    def test_malformed_fhir_data_handling(self):
        """Test handling of malformed FHIR-structured data."""
        malformed_data = {
            "Condition": "not-an-array",  # Should be array
            "Patient": ["not-a-dict"]     # Should be dict
        }
        
        # Should not crash, should handle gracefully
        try:
            fhir_resources = self.analyzer._convert_fhir_structured_to_resources(malformed_data)
            # Should create at least a DocumentReference as fallback
            self.assertGreater(len(fhir_resources), 0)
        except Exception as e:
            self.fail(f"Should handle malformed data gracefully, but raised: {e}")
    
    def test_date_parsing_error_handling(self):
        """Test handling of unparseable dates."""
        invalid_dates = [
            "not-a-date",
            "32/13/2023",  # Invalid date
            "",            # Empty string
            None           # None value
        ]
        
        for invalid_date in invalid_dates:
            with self.subTest(date=invalid_date):
                result = self.analyzer.parse_and_format_date(invalid_date)
                # Should return None for invalid dates, not crash
                self.assertIsNone(result)
    
    def test_temporal_processing_error_recovery(self):
        """Test that temporal processing errors don't break the resource."""
        resource_with_bad_date = {
            "resourceType": "Condition",
            "code": {"text": "Hypertension"},
            "onsetDateTime": "invalid-date-format"
        }
        
        # Should return original resource if temporal processing fails
        processed = self.analyzer.process_temporal_data(resource_with_bad_date)
        self.assertEqual(processed['resourceType'], 'Condition')
        self.assertEqual(processed['code']['text'], 'Hypertension')
        # Bad date should be handled gracefully (either fixed or left as-is)
