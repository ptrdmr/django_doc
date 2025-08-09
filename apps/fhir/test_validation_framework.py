"""
Test suite for FHIR Data Validation Framework.

Tests the comprehensive data validation system including schema validation,
data normalization, business rules, and quality checks.
"""

import unittest
from datetime import datetime, date
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth.models import User

from apps.patients.models import Patient
from apps.fhir.services import (
    ValidationResult,
    DataNormalizer,
    DocumentSchemaValidator,
    FHIRMergeService
)


class ValidationResultTest(TestCase):
    """Test the ValidationResult class functionality."""
    
    def setUp(self):
        self.validation_result = ValidationResult()
    
    def test_initialization(self):
        """Test ValidationResult initializes with correct defaults."""
        self.assertTrue(self.validation_result.is_valid)
        self.assertEqual(self.validation_result.data, {})
        self.assertEqual(self.validation_result.errors, [])
        self.assertEqual(self.validation_result.warnings, [])
        self.assertEqual(self.validation_result.critical_errors, [])
        self.assertEqual(self.validation_result.field_errors, {})
        self.assertEqual(self.validation_result.normalized_fields, [])
        self.assertIn('validation_timestamp', self.validation_result.validation_metadata)
    
    def test_add_error(self):
        """Test adding validation errors."""
        # Regular error
        self.validation_result.add_error("Test error", "test_field")
        self.assertFalse(self.validation_result.is_valid)
        self.assertIn("Test error", self.validation_result.errors)
        self.assertIn("test_field", self.validation_result.field_errors)
        self.assertIn("Test error", self.validation_result.field_errors["test_field"])
        
        # Critical error
        self.validation_result.add_error("Critical error", "critical_field", is_critical=True)
        self.assertIn("Critical error", self.validation_result.critical_errors)
        self.assertIn("Critical error", self.validation_result.errors)
    
    def test_add_warning(self):
        """Test adding validation warnings."""
        self.validation_result.add_warning("Test warning", "warning_field")
        self.assertTrue(self.validation_result.is_valid)  # Warnings don't invalidate
        self.assertIn("Test warning", self.validation_result.warnings)
        self.assertIn("warning_field", self.validation_result.field_errors)
        self.assertIn("WARNING: Test warning", self.validation_result.field_errors["warning_field"])
    
    def test_add_normalized_field(self):
        """Test tracking field normalization."""
        self.validation_result.add_normalized_field("test_field", "original", "normalized")
        self.assertEqual(len(self.validation_result.normalized_fields), 1)
        normalized_field = self.validation_result.normalized_fields[0]
        self.assertEqual(normalized_field['field'], "test_field")
        self.assertEqual(normalized_field['original_value'], "original")
        self.assertEqual(normalized_field['normalized_value'], "normalized")
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        self.validation_result.add_error("Test error")
        self.validation_result.add_warning("Test warning")
        result_dict = self.validation_result.to_dict()
        
        self.assertIsInstance(result_dict, dict)
        self.assertIn('is_valid', result_dict)
        self.assertIn('errors', result_dict)
        self.assertIn('warnings', result_dict)
        self.assertIn('validation_metadata', result_dict)


class DataNormalizerTest(TestCase):
    """Test the DataNormalizer utility functions."""
    
    def test_normalize_date_with_date_objects(self):
        """Test date normalization with date/datetime objects."""
        test_date = date(2023, 12, 25)
        normalized = DataNormalizer.normalize_date(test_date)
        self.assertEqual(normalized, "2023-12-25")
        
        test_datetime = datetime(2023, 12, 25, 14, 30)
        normalized = DataNormalizer.normalize_date(test_datetime)
        self.assertEqual(normalized, "2023-12-25")
    
    def test_normalize_date_with_strings(self):
        """Test date normalization with various string formats."""
        # ISO format
        self.assertEqual(DataNormalizer.normalize_date("2023-12-25"), "2023-12-25")
        
        # US format
        self.assertEqual(DataNormalizer.normalize_date("12/25/2023"), "2023-12-25")
        
        # European format
        self.assertEqual(DataNormalizer.normalize_date("25/12/2023"), "2023-12-25")
        
        # Named month
        self.assertEqual(DataNormalizer.normalize_date("December 25, 2023"), "2023-12-25")
        
        # Short year
        self.assertEqual(DataNormalizer.normalize_date("12/25/23"), "2023-12-25")
    
    def test_normalize_date_invalid(self):
        """Test date normalization with invalid inputs."""
        self.assertIsNone(DataNormalizer.normalize_date(None))
        self.assertIsNone(DataNormalizer.normalize_date(""))
        self.assertIsNone(DataNormalizer.normalize_date("invalid date"))
        self.assertIsNone(DataNormalizer.normalize_date("13/45/2023"))
    
    def test_normalize_name_basic(self):
        """Test basic name normalization."""
        self.assertEqual(DataNormalizer.normalize_name("john doe"), "John Doe")
        self.assertEqual(DataNormalizer.normalize_name("  JANE   SMITH  "), "Jane Smith")
        self.assertEqual(DataNormalizer.normalize_name("mary-ann jones"), "Mary-Ann Jones")
    
    def test_normalize_name_with_titles(self):
        """Test name normalization with titles and suffixes."""
        self.assertEqual(DataNormalizer.normalize_name("dr john smith"), "Dr. John Smith")
        self.assertEqual(DataNormalizer.normalize_name("mr. robert jones jr"), "Mr. Robert Jones JR.")
        self.assertEqual(DataNormalizer.normalize_name("mrs smith sr."), "Mrs. Smith SR.")
    
    def test_normalize_name_invalid(self):
        """Test name normalization with invalid inputs."""
        self.assertIsNone(DataNormalizer.normalize_name(None))
        self.assertIsNone(DataNormalizer.normalize_name(""))
        self.assertEqual(DataNormalizer.normalize_name(123), "123")  # Converts to string
    
    def test_normalize_medical_code_loinc(self):
        """Test medical code normalization for LOINC codes."""
        # LOINC pattern
        result = DataNormalizer.normalize_medical_code("12345-6")
        self.assertEqual(result['code'], "12345-6")
        self.assertEqual(result['system'], "LOINC")
        
        # Auto-detect LOINC
        result = DataNormalizer.normalize_medical_code("789-0")
        self.assertEqual(result['system'], "LOINC")
    
    def test_normalize_medical_code_icd10(self):
        """Test medical code normalization for ICD-10 codes."""
        # ICD-10 pattern
        result = DataNormalizer.normalize_medical_code("E11.9")
        self.assertEqual(result['code'], "E11.9")
        self.assertEqual(result['system'], "ICD-10")
        
        # Auto-detect ICD-10
        result = DataNormalizer.normalize_medical_code("K25.1")
        self.assertEqual(result['system'], "ICD-10")
    
    def test_normalize_medical_code_snomed(self):
        """Test medical code normalization for SNOMED codes."""
        # SNOMED pattern (6+ digits)
        result = DataNormalizer.normalize_medical_code("123456789")
        self.assertEqual(result['code'], "123456789")
        self.assertEqual(result['system'], "SNOMED")
    
    def test_normalize_medical_code_explicit_system(self):
        """Test medical code normalization with explicit system."""
        result = DataNormalizer.normalize_medical_code("ABC123", "CUSTOM")
        self.assertEqual(result['code'], "ABC123")
        self.assertEqual(result['system'], "CUSTOM")
    
    def test_normalize_medical_code_invalid(self):
        """Test medical code normalization with invalid inputs."""
        self.assertIsNone(DataNormalizer.normalize_medical_code(None))
        self.assertIsNone(DataNormalizer.normalize_medical_code(""))
        
        # Unknown pattern
        result = DataNormalizer.normalize_medical_code("XYZ")
        self.assertEqual(result['system'], "UNKNOWN")
    
    def test_normalize_numeric_value_integers(self):
        """Test numeric value normalization for integers."""
        self.assertEqual(DataNormalizer.normalize_numeric_value(42), 42.0)
        self.assertEqual(DataNormalizer.normalize_numeric_value("123"), 123.0)
        self.assertEqual(DataNormalizer.normalize_numeric_value("123", "integer"), 123.0)
    
    def test_normalize_numeric_value_decimals(self):
        """Test numeric value normalization for decimals."""
        self.assertEqual(DataNormalizer.normalize_numeric_value(3.14), 3.14)
        self.assertEqual(DataNormalizer.normalize_numeric_value("3.14"), 3.14)
        self.assertEqual(DataNormalizer.normalize_numeric_value("123.45"), 123.45)
    
    def test_normalize_numeric_value_with_symbols(self):
        """Test numeric value normalization with extra symbols."""
        self.assertEqual(DataNormalizer.normalize_numeric_value("$123.45"), 123.45)
        self.assertEqual(DataNormalizer.normalize_numeric_value("123.45%"), 123.45)
        self.assertEqual(DataNormalizer.normalize_numeric_value("  123.45  "), 123.45)
    
    def test_normalize_numeric_value_invalid(self):
        """Test numeric value normalization with invalid inputs."""
        self.assertIsNone(DataNormalizer.normalize_numeric_value(None))
        self.assertIsNone(DataNormalizer.normalize_numeric_value(""))
        self.assertIsNone(DataNormalizer.normalize_numeric_value("not a number"))
        self.assertIsNone(DataNormalizer.normalize_numeric_value("abc123"))


class DocumentSchemaValidatorTest(TestCase):
    """Test the DocumentSchemaValidator functionality."""
    
    def setUp(self):
        self.validator = DocumentSchemaValidator()
    
    def test_initialization(self):
        """Test validator initializes with schemas."""
        self.assertIsInstance(self.validator.schemas, dict)
        self.assertIn('lab_report', self.validator.schemas)
        self.assertIn('clinical_note', self.validator.schemas)
        self.assertIn('medication_list', self.validator.schemas)
        self.assertIn('discharge_summary', self.validator.schemas)
        self.assertIn('generic', self.validator.schemas)
    
    def test_validate_schema_lab_report_valid(self):
        """Test valid lab report validation."""
        lab_data = {
            'patient_name': 'John Doe',
            'test_date': '2023-12-25',
            'tests': [
                {'name': 'Glucose', 'value': 95},
                {'name': 'Cholesterol', 'value': 180}
            ],
            'ordering_provider': 'Dr. Smith'
        }
        
        result = self.validator.validate_schema(lab_data, 'lab_report')
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(result.data, lab_data)
    
    def test_validate_schema_lab_report_missing_required(self):
        """Test lab report validation with missing required fields."""
        lab_data = {
            'patient_name': 'John Doe',
            # Missing test_date and tests
        }
        
        result = self.validator.validate_schema(lab_data, 'lab_report')
        self.assertFalse(result.is_valid)
        self.assertGreater(len(result.errors), 0)
        self.assertGreater(len(result.critical_errors), 0)
    
    def test_validate_schema_clinical_note_valid(self):
        """Test valid clinical note validation."""
        note_data = {
            'patient_name': 'Jane Smith',
            'note_date': '2023-12-25',
            'provider': 'Dr. Johnson',
            'chief_complaint': 'Chest pain',
            'assessment': 'Stable angina',
            'plan': 'Continue medications'
        }
        
        result = self.validator.validate_schema(note_data, 'clinical_note')
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.errors), 0)
    
    def test_validate_schema_medication_list_valid(self):
        """Test valid medication list validation."""
        med_data = {
            'patient_name': 'Bob Wilson',
            'list_date': '2023-12-25',
            'medications': [
                {'name': 'Aspirin', 'dosage': '81mg'},
                {'name': 'Metformin', 'dosage': '500mg'}
            ]
        }
        
        result = self.validator.validate_schema(med_data, 'medication_list')
        self.assertTrue(result.is_valid)
    
    def test_validate_schema_generic(self):
        """Test generic document validation."""
        generic_data = {
            'patient_name': 'Test Patient',
            'document_date': '2023-12-25',
            'extra_field': 'extra_value'
        }
        
        result = self.validator.validate_schema(generic_data, 'generic')
        self.assertTrue(result.is_valid)
    
    def test_validate_field_type_string_constraints(self):
        """Test string field type validation with constraints."""
        # Valid string
        error = self.validator._validate_field_type(
            'test_field', 'Valid String', 'string', 
            {'min_length': 5, 'max_length': 20}
        )
        self.assertIsNone(error)
        
        # Too short
        error = self.validator._validate_field_type(
            'test_field', 'Hi', 'string', 
            {'min_length': 5, 'max_length': 20}
        )
        self.assertIsNotNone(error)
        self.assertIn('at least 5 characters', error)
        
        # Too long
        error = self.validator._validate_field_type(
            'test_field', 'This string is way too long for the constraint', 'string', 
            {'min_length': 5, 'max_length': 20}
        )
        self.assertIsNotNone(error)
        self.assertIn('no more than 20 characters', error)
    
    def test_validate_field_type_array(self):
        """Test array field type validation."""
        # Valid array
        error = self.validator._validate_field_type('test_field', [1, 2, 3], 'array', {})
        self.assertIsNone(error)
        
        # Invalid array
        error = self.validator._validate_field_type('test_field', 'not an array', 'array', {})
        self.assertIsNotNone(error)
        self.assertIn('must be an array', error)
    
    def test_validate_field_type_number(self):
        """Test number field type validation."""
        # Valid numbers
        error = self.validator._validate_field_type('test_field', 42, 'number', {})
        self.assertIsNone(error)
        
        error = self.validator._validate_field_type('test_field', '42.5', 'number', {})
        self.assertIsNone(error)
        
        # Invalid number
        error = self.validator._validate_field_type('test_field', 'not a number', 'number', {})
        self.assertIsNotNone(error)
        self.assertIn('must be a number', error)


class FHIRMergeServiceValidationTest(TestCase):
    """Test the FHIRMergeService validation functionality."""
    
    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test patient
        self.patient = Patient.objects.create(
            mrn='TEST123',
            first_name='Test',
            last_name='Patient',
            date_of_birth='1980-01-01'
        )
        
        # Create FHIRMergeService instance
        self.merge_service = FHIRMergeService(self.patient)
    
    def test_initialization(self):
        """Test FHIRMergeService initializes correctly."""
        self.assertEqual(self.merge_service.patient, self.patient)
        self.assertIsNotNone(self.merge_service.accumulator)
        self.assertIsNotNone(self.merge_service.logger)
        self.assertIsInstance(self.merge_service.config, dict)
    
    def test_validate_data_empty_input(self):
        """Test validation with empty input."""
        result = self.merge_service.validate_data({})
        self.assertFalse(result['is_valid'])
        self.assertIn('Data is empty', result['critical_errors'])
    
    def test_validate_data_invalid_input(self):
        """Test validation with invalid input type."""
        result = self.merge_service.validate_data("not a dict")
        self.assertFalse(result['is_valid'])
        self.assertIn('Data must be a dictionary', result['critical_errors'])
    
    def test_validate_data_lab_report(self):
        """Test validation of lab report data."""
        lab_data = {
            'patient_name': 'test patient',
            'test_date': '12/25/2023',
            'tests': [
                {'name': 'Glucose', 'value': 95},
                {'name': 'Cholesterol', 'value': 180}
            ],
            'ordering_provider': 'dr. smith',
            'collection_date': '12/24/2023'
        }
        
        result = self.merge_service.validate_data(lab_data)
        
        # Should be valid
        self.assertTrue(result['is_valid'])
        
        # Check normalization occurred
        self.assertGreater(len(result['normalized_fields']), 0)
        
        # Check normalized data
        normalized_data = result['data']
        self.assertEqual(normalized_data['patient_name'], 'Test Patient')
        self.assertEqual(normalized_data['test_date'], '2023-12-25')
        self.assertEqual(normalized_data['ordering_provider'], 'Dr. Smith')
        self.assertEqual(normalized_data['collection_date'], '2023-12-24')
    
    def test_validate_data_clinical_note(self):
        """Test validation of clinical note data."""
        note_data = {
            'patient_name': 'jane doe',
            'note_date': 'December 25, 2023',
            'provider': 'dr johnson',
            'chief_complaint': 'Chest pain',
            'assessment': 'Stable angina',
            'plan': 'Continue current medications'
        }
        
        result = self.merge_service.validate_data(note_data)
        
        self.assertTrue(result['is_valid'])
        normalized_data = result['data']
        self.assertEqual(normalized_data['patient_name'], 'Jane Doe')
        self.assertEqual(normalized_data['note_date'], '2023-12-25')
        self.assertEqual(normalized_data['provider'], 'Dr. Johnson')
    
    def test_detect_document_type_lab_report(self):
        """Test document type detection for lab reports."""
        lab_data = {'tests': [], 'test_date': '2023-12-25'}
        doc_type = self.merge_service._detect_document_type(lab_data)
        self.assertEqual(doc_type, 'lab_report')
    
    def test_detect_document_type_clinical_note(self):
        """Test document type detection for clinical notes."""
        note_data = {'chief_complaint': 'Pain', 'assessment': 'Diagnosis'}
        doc_type = self.merge_service._detect_document_type(note_data)
        self.assertEqual(doc_type, 'clinical_note')
    
    def test_detect_document_type_medication_list(self):
        """Test document type detection for medication lists."""
        med_data = {'medications': []}
        doc_type = self.merge_service._detect_document_type(med_data)
        self.assertEqual(doc_type, 'medication_list')
    
    def test_detect_document_type_discharge_summary(self):
        """Test document type detection for discharge summaries."""
        discharge_data = {'admission_date': '2023-12-20', 'discharge_date': '2023-12-25'}
        doc_type = self.merge_service._detect_document_type(discharge_data)
        self.assertEqual(doc_type, 'discharge_summary')
    
    def test_detect_document_type_generic(self):
        """Test document type detection for generic documents."""
        generic_data = {'patient_name': 'Test', 'document_date': '2023-12-25'}
        doc_type = self.merge_service._detect_document_type(generic_data)
        self.assertEqual(doc_type, 'generic')
    
    def test_business_rules_validation_date_logic(self):
        """Test business rules validation for date logic."""
        data = {
            'admission_date': '2023-12-25',
            'discharge_date': '2023-12-20'  # Before admission
        }
        
        result = self.merge_service.validate_data(data)
        self.assertFalse(result['is_valid'])
        self.assertTrue(any('discharge date cannot be before admission date' in error.lower() 
                          for error in result['errors']))
    
    def test_business_rules_validation_missing_test_names(self):
        """Test business rules validation for missing test names."""
        data = {
            'patient_name': 'Test Patient',
            'test_date': '2023-12-25',
            'tests': [
                {'value': 95},  # Missing name
                {'name': 'Cholesterol', 'value': 180}
            ]
        }
        
        result = self.merge_service.validate_data(data)
        self.assertFalse(result['is_valid'])
        self.assertTrue(any('missing a name' in error for error in result['errors']))
    
    def test_range_validation_future_dates(self):
        """Test range validation for future dates."""
        future_date = (datetime.now() + timezone.timedelta(days=10)).strftime('%Y-%m-%d')
        data = {
            'patient_name': 'Test Patient',
            'test_date': future_date,
            'tests': [{'name': 'Glucose', 'value': 95}]  # Add required tests field
        }
        
        result = self.merge_service.validate_data(data)
        self.assertTrue(result['is_valid'])  # Should be valid but with warning
        self.assertTrue(any('in the future' in warning for warning in result['warnings']))
    
    def test_range_validation_old_dates(self):
        """Test range validation for very old dates."""
        data = {
            'patient_name': 'Test Patient',
            'test_date': '1850-01-01'
        }
        
        result = self.merge_service.validate_data(data)
        self.assertFalse(result['is_valid'])
        self.assertTrue(any('too far in the past' in error for error in result['errors']))
    
    def test_cross_field_validation_collection_vs_test_date(self):
        """Test cross-field validation for collection and test dates."""
        data = {
            'patient_name': 'Test Patient',
            'collection_date': '2023-12-25',
            'test_date': '2023-12-15',  # Test date before collection
            'tests': [{'name': 'Glucose', 'value': 95}]  # Add required tests field
        }
        
        result = self.merge_service.validate_data(data)
        # Should have warning about date sequence
        self.assertTrue(any('collection date' in warning.lower() for warning in result['warnings']))
    
    def test_medical_data_quality_incomplete_tests(self):
        """Test medical data quality checks for incomplete tests."""
        data = {
            'patient_name': 'Test Patient',
            'test_date': '2023-12-25',
            'tests': [
                {'name': 'Glucose', 'value': 95},
                {'name': 'Cholesterol'},  # Missing value
                {'value': 180}  # Missing name
            ]
        }
        
        result = self.merge_service.validate_data(data)
        self.assertTrue(any('incomplete information' in warning for warning in result['warnings']))
    
    def test_medical_data_quality_missing_provider(self):
        """Test medical data quality checks for missing provider info."""
        data = {
            'patient_name': 'Test Patient',
            'test_date': '2023-12-25',
            'tests': [{'name': 'Glucose', 'value': 95}]
            # No provider information
        }
        
        result = self.merge_service.validate_data(data)
        self.assertTrue(any('no provider information' in warning.lower() for warning in result['warnings']))


if __name__ == '__main__':
    unittest.main() 