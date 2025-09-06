"""
Unit tests for MedicationService

Tests the comprehensive medication processing functionality to ensure 100% capture
of medication data from various input formats.
"""

import unittest
from unittest.mock import patch, MagicMock
from django.test import TestCase

from apps.fhir.services.medication_service import MedicationService


class MedicationServiceTests(TestCase):
    """Test cases for MedicationService functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = MedicationService()
        
    def test_process_medications_complete_data(self):
        """Test processing medications with complete data."""
        test_data = {
            'patient_id': '123',
            'medications': [
                {
                    'name': 'Lisinopril',
                    'dosage': '10mg',
                    'route': 'oral',
                    'schedule': 'once daily'
                },
                {
                    'name': 'Metformin',
                    'dosage': '500mg',
                    'route': 'oral',
                    'schedule': 'twice daily'
                }
            ]
        }
        
        result = self.service.process_medications(test_data)
        
        self.assertEqual(len(result), 2)
        
        # Check first medication
        med1 = result[0]
        self.assertEqual(med1['resourceType'], 'MedicationStatement')
        self.assertEqual(med1['medicationCodeableConcept']['text'], 'Lisinopril')
        self.assertEqual(med1['subject']['reference'], 'Patient/123')
        self.assertEqual(med1['dosage'][0]['text'], '10mg')
        self.assertEqual(med1['dosage'][0]['route']['text'], 'oral')
        self.assertEqual(med1['dosage'][0]['timing']['code']['text'], 'once daily')
        
        # Check second medication
        med2 = result[1]
        self.assertEqual(med2['resourceType'], 'MedicationStatement')
        self.assertEqual(med2['medicationCodeableConcept']['text'], 'Metformin')
        self.assertEqual(med2['dosage'][0]['text'], '500mg')
        
    def test_process_medications_partial_data(self):
        """Test processing medications with partial data."""
        test_data = {
            'patient_id': '123',
            'medications': [
                {
                    'name': 'Aspirin',
                    'dosage': '81mg'
                    # Missing route and schedule
                },
                {
                    'name': 'Vitamin D'
                    # Missing dosage, route, and schedule
                }
            ]
        }
        
        result = self.service.process_medications(test_data)
        
        self.assertEqual(len(result), 2)
        
        # Check first medication (partial data)
        med1 = result[0]
        self.assertEqual(med1['resourceType'], 'MedicationStatement')
        self.assertEqual(med1['medicationCodeableConcept']['text'], 'Aspirin')
        self.assertEqual(med1['dosage'][0]['text'], '81mg')
        self.assertNotIn('route', med1['dosage'][0])
        self.assertNotIn('timing', med1['dosage'][0])
        
        # Check second medication (minimal data)
        med2 = result[1]
        self.assertEqual(med2['resourceType'], 'MedicationStatement')
        self.assertEqual(med2['medicationCodeableConcept']['text'], 'Vitamin D')
        self.assertNotIn('dosage', med2)
        
    def test_process_medications_from_fields(self):
        """Test processing medications from document analyzer fields format."""
        test_data = {
            'patient_id': '456',
            'fields': [
                {
                    'label': 'Medication',
                    'value': 'Lisinopril 10mg once daily by mouth',
                    'confidence': 0.95
                },
                {
                    'label': 'Current Drug',
                    'value': 'Metformin 500mg twice daily',
                    'confidence': 0.88
                },
                {
                    'label': 'Diagnosis',  # Should be ignored
                    'value': 'Hypertension',
                    'confidence': 0.92
                }
            ]
        }
        
        result = self.service.process_medications(test_data)
        
        self.assertEqual(len(result), 2)
        
        # Check medication parsed from field
        med1 = result[0]
        self.assertEqual(med1['resourceType'], 'MedicationStatement')
        self.assertEqual(med1['medicationCodeableConcept']['text'], 'Lisinopril')
        self.assertEqual(med1['dosage'][0]['text'], '10mg')
        self.assertEqual(med1['dosage'][0]['route']['text'], 'oral')
        self.assertEqual(med1['dosage'][0]['timing']['code']['text'], 'once daily')
        self.assertEqual(med1['extension'][0]['valueDecimal'], 0.95)
        
    def test_process_medications_from_string(self):
        """Test processing medications from semicolon-separated string."""
        test_data = {
            'patient_id': '789',
            'medications': 'Lisinopril 10mg daily; Metformin 500mg twice daily; Aspirin 81mg once daily'
        }
        
        result = self.service.process_medications(test_data)
        
        self.assertEqual(len(result), 3)
        
        # Check parsed medications
        med_names = [med['medicationCodeableConcept']['text'] for med in result]
        self.assertIn('Lisinopril', med_names)
        self.assertIn('Metformin', med_names)
        self.assertIn('Aspirin', med_names)
        
    def test_parse_medication_text_complex(self):
        """Test parsing complex medication text."""
        test_cases = [
            {
                'text': 'Lisinopril 10mg oral once daily',
                'expected': {
                    'name': 'Lisinopril',
                    'dosage': '10mg',
                    'route': 'oral',
                    'schedule': 'once daily'
                }
            },
            {
                'text': 'Metformin 500mg twice daily by mouth with meals',
                'expected': {
                    'name': 'Metformin',
                    'dosage': '500mg',
                    'route': 'by mouth',
                    'schedule': 'with meals'
                }
            },
            {
                'text': 'Insulin 20 units subcutaneous twice daily',
                'expected': {
                    'name': 'Insulin',
                    'dosage': '20 units',
                    'route': 'subcutaneous',
                    'schedule': 'twice daily'
                }
            },
            {
                'text': 'Aspirin 81mg daily as needed',
                'expected': {
                    'name': 'Aspirin',
                    'dosage': '81mg',
                    'route': None,
                    'schedule': 'as needed'
                }
            }
        ]
        
        for case in test_cases:
            with self.subTest(text=case['text']):
                result = self.service._parse_medication_text(case['text'])
                self.assertEqual(result['name'], case['expected']['name'])
                self.assertEqual(result['dosage'], case['expected']['dosage'])
                self.assertEqual(result['route'], case['expected']['route'])
                self.assertEqual(result['schedule'], case['expected']['schedule'])
                
    def test_parse_medication_text_edge_cases(self):
        """Test parsing edge cases in medication text."""
        # Empty text
        result = self.service._parse_medication_text('')
        self.assertIsNone(result['name'])
        
        # Only medication name
        result = self.service._parse_medication_text('Lisinopril')
        self.assertEqual(result['name'], 'Lisinopril')
        self.assertIsNone(result['dosage'])
        
        # Complex dosage
        result = self.service._parse_medication_text('Warfarin 2.5/5mg alternating daily')
        self.assertEqual(result['name'], 'Warfarin')
        self.assertEqual(result['dosage'], '2.5/5mg')
        
        # Multiple routes (should pick first)
        result = self.service._parse_medication_text('Medication oral IV daily')
        self.assertEqual(result['route'], 'oral')
        
    def test_extract_medication_data_mixed_sources(self):
        """Test extracting medication data from mixed sources."""
        test_data = {
            'patient_id': '999',
            'medications': [
                {'name': 'Direct Med 1', 'dosage': '10mg'}
            ],
            'fields': [
                {
                    'label': 'medication',
                    'value': 'Field Med 2 20mg daily',
                    'confidence': 0.9
                }
            ]
        }
        
        result = self.service._extract_medication_data(test_data)
        
        self.assertEqual(len(result), 2)
        
        # Check direct medication
        direct_med = next((m for m in result if m['name'] == 'Direct Med 1'), None)
        self.assertIsNotNone(direct_med)
        self.assertEqual(direct_med['dosage'], '10mg')
        
        # Check field medication
        field_med = next((m for m in result if m['name'] == 'Field Med 2'), None)
        self.assertIsNotNone(field_med)
        self.assertEqual(field_med['dosage'], '20mg')
        
    def test_create_medication_statement_minimal(self):
        """Test creating MedicationStatement with minimal data."""
        med_data = {'name': 'Test Medication'}
        
        result = self.service._create_medication_statement(med_data, '123')
        
        self.assertIsNotNone(result)
        self.assertEqual(result['resourceType'], 'MedicationStatement')
        self.assertEqual(result['medicationCodeableConcept']['text'], 'Test Medication')
        self.assertEqual(result['subject']['reference'], 'Patient/123')
        self.assertEqual(result['status'], 'active')
        self.assertIn('meta', result)
        
    def test_create_medication_statement_no_name(self):
        """Test creating MedicationStatement with no name should return None."""
        med_data = {'dosage': '10mg'}  # No name
        
        result = self.service._create_medication_statement(med_data, '123')
        
        self.assertIsNone(result)
        
    def test_create_medication_statement_no_patient(self):
        """Test creating MedicationStatement without patient ID."""
        med_data = {'name': 'Test Medication', 'dosage': '10mg'}
        
        result = self.service._create_medication_statement(med_data, None)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['resourceType'], 'MedicationStatement')
        self.assertNotIn('subject', result)
        
    def test_parse_medication_string_various_separators(self):
        """Test parsing medication strings with various separators."""
        test_cases = [
            'Med1 10mg; Med2 20mg; Med3 30mg',
            'Med1 10mg, Med2 20mg, Med3 30mg',
            'Med1 10mg;Med2 20mg,Med3 30mg'  # Mixed separators
        ]
        
        for med_string in test_cases:
            with self.subTest(string=med_string):
                result = self.service._parse_medication_string(med_string)
                self.assertEqual(len(result), 3)
                
                med_names = [med['name'] for med in result]
                self.assertIn('Med1', med_names)
                self.assertIn('Med2', med_names)
                self.assertIn('Med3', med_names)
                
    def test_convert_field_to_medication(self):
        """Test converting document analyzer field to medication format."""
        field = {
            'label': 'Current Medication',
            'value': 'Lisinopril 10mg daily oral',
            'confidence': 0.92
        }
        
        result = self.service._convert_field_to_medication(field)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'Lisinopril')
        self.assertEqual(result['dosage'], '10mg')
        self.assertEqual(result['route'], 'oral')
        self.assertEqual(result['schedule'], 'daily')
        self.assertEqual(result['confidence'], 0.92)
        self.assertEqual(result['source'], 'document_field')
        
    def test_convert_field_to_medication_empty_value(self):
        """Test converting field with empty value returns None."""
        field = {
            'label': 'Medication',
            'value': '',
            'confidence': 0.8
        }
        
        result = self.service._convert_field_to_medication(field)
        
        self.assertIsNone(result)
        
    @patch('apps.fhir.services.medication_service.logger')
    def test_error_handling_in_process_medications(self, mock_logger):
        """Test error handling when processing medications."""
        # Create a service that will raise an exception
        service = MedicationService()
        
        # Mock _create_medication_statement to raise an exception
        with patch.object(service, '_create_medication_statement', side_effect=Exception('Test error')):
            test_data = {
                'patient_id': '123',
                'medications': [{'name': 'Test Med'}]
            }
            
            result = service.process_medications(test_data)
            
            # Should return empty list and log error
            self.assertEqual(len(result), 0)
            mock_logger.error.assert_called()
            
    def test_medication_with_confidence_extension(self):
        """Test that confidence values are added as extensions."""
        med_data = {
            'name': 'Test Medication',
            'dosage': '10mg',
            'confidence': 0.95
        }
        
        result = self.service._create_medication_statement(med_data, '123')
        
        self.assertIsNotNone(result)
        self.assertIn('extension', result)
        self.assertEqual(len(result['extension']), 1)
        self.assertEqual(result['extension'][0]['url'], 'http://hl7.org/fhir/StructureDefinition/data-confidence')
        self.assertEqual(result['extension'][0]['valueDecimal'], 0.95)
        
    def test_medication_with_code(self):
        """Test creating medication with coding information."""
        med_data = {
            'name': 'Lisinopril',
            'code': '29046004',
            'dosage': '10mg'
        }
        
        result = self.service._create_medication_statement(med_data, '123')
        
        self.assertIsNotNone(result)
        self.assertIn('coding', result['medicationCodeableConcept'])
        self.assertEqual(len(result['medicationCodeableConcept']['coding']), 1)
        self.assertEqual(result['medicationCodeableConcept']['coding'][0]['code'], '29046004')
        self.assertEqual(result['medicationCodeableConcept']['coding'][0]['display'], 'Lisinopril')
        
    def test_comprehensive_medication_processing(self):
        """Test comprehensive medication processing with real-world data."""
        test_data = {
            'patient_id': '12345',
            'medications': [
                {
                    'name': 'Lisinopril',
                    'dosage': '10mg',
                    'route': 'oral',
                    'schedule': 'once daily',
                    'code': '29046004'
                }
            ],
            'fields': [
                {
                    'label': 'Current Medications',
                    'value': 'Metformin 500mg twice daily with meals; Aspirin 81mg daily',
                    'confidence': 0.88
                },
                {
                    'label': 'PRN Medication',
                    'value': 'Albuterol inhaler 2 puffs as needed for shortness of breath',
                    'confidence': 0.92
                }
            ]
        }
        
        result = self.service.process_medications(test_data)
        
        # Should have 4 medications: 1 direct + 2 from first field + 1 from second field
        self.assertEqual(len(result), 4)
        
        # Check that all medications are properly formatted FHIR resources
        for med in result:
            self.assertEqual(med['resourceType'], 'MedicationStatement')
            self.assertIn('medicationCodeableConcept', med)
            self.assertIn('text', med['medicationCodeableConcept'])
            self.assertEqual(med['subject']['reference'], 'Patient/12345')
            self.assertIn('meta', med)
            
        # Check specific medications
        med_names = [med['medicationCodeableConcept']['text'] for med in result]
        self.assertIn('Lisinopril', med_names)
        self.assertIn('Metformin', med_names)
        self.assertIn('Aspirin', med_names)
        self.assertIn('Albuterol', med_names)
