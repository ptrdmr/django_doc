"""
Tests for MedicationService dual-format support (Task 40.2)

Verifies that MedicationService correctly processes both:
1. Structured Pydantic-derived dicts (primary path)
2. Legacy extraction formats (fallback path)
"""

import unittest
from unittest.mock import Mock, patch
from apps.fhir.services.medication_service import MedicationService


class MedicationServiceDualFormatTests(unittest.TestCase):
    """Test MedicationService with both structured and legacy input formats."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = MedicationService()
        self.patient_id = "test-patient-456"
    
    def test_structured_input_happy_path(self):
        """Test processing structured Pydantic-derived medication data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'medications': [
                    {
                        'name': 'Metformin',
                        'dosage': '500mg',
                        'route': 'oral',
                        'frequency': 'twice daily',
                        'status': 'active',
                        'start_date': '2023-01-15',
                        'confidence': 0.96,
                        'source': {
                            'text': 'Patient taking Metformin 500mg twice daily',
                            'start_index': 50,
                            'end_index': 93
                        }
                    }
                ]
            }
        }
        
        result = self.service.process_medications(extracted_data)
        
        # Verify resource created
        self.assertEqual(len(result), 1)
        medication = result[0]
        
        # Verify FHIR structure
        self.assertEqual(medication['resourceType'], 'MedicationStatement')
        self.assertEqual(medication['medicationCodeableConcept']['text'], 'Metformin')
        self.assertEqual(medication['subject']['reference'], f'Patient/{self.patient_id}')
        self.assertEqual(medication['status'], 'active')
        
        # Verify dosage information
        self.assertIn('dosage', medication)
        self.assertEqual(medication['dosage'][0]['text'], '500mg')
        self.assertEqual(medication['dosage'][0]['route']['text'], 'oral')
        self.assertEqual(medication['dosage'][0]['timing']['code']['text'], 'twice daily')
        
        # Verify effective period with start date
        self.assertIn('effectivePeriod', medication)
        self.assertIn('2023-01-15', medication['effectivePeriod']['start'])
        
        # Verify confidence tag
        confidence_tags = [tag for tag in medication['meta']['tag'] if tag.get('code') == 'extraction-confidence']
        self.assertEqual(len(confidence_tags), 1)
        self.assertIn('0.96', confidence_tags[0]['display'])
        
        # Verify source note
        self.assertIn('note', medication)
        self.assertIn('Metformin', medication['note'][0]['text'])
    
    def test_structured_input_minimal_data(self):
        """Test processing structured data with only required fields."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'medications': [
                    {
                        'name': 'Aspirin',
                        'status': 'active',
                        'confidence': 0.85,
                        'source': {
                            'text': 'Aspirin',
                            'start_index': 0,
                            'end_index': 7
                        }
                    }
                ]
            }
        }
        
        result = self.service.process_medications(extracted_data)
        
        # Verify resource created with minimal data
        self.assertEqual(len(result), 1)
        medication = result[0]
        self.assertEqual(medication['medicationCodeableConcept']['text'], 'Aspirin')
        
        # Verify optional fields handled gracefully
        self.assertNotIn('dosage', medication)
        self.assertNotIn('effectivePeriod', medication)
    
    def test_structured_input_with_stop_date(self):
        """Test medication with both start and stop dates."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'medications': [
                    {
                        'name': 'Amoxicillin',
                        'dosage': '500mg',
                        'status': 'completed',
                        'start_date': '2024-05-01',
                        'stop_date': '2024-05-10',
                        'confidence': 0.92,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }
                ]
            }
        }
        
        result = self.service.process_medications(extracted_data)
        
        self.assertEqual(len(result), 1)
        medication = result[0]
        
        # Verify status mapped correctly
        self.assertEqual(medication['status'], 'completed')
        
        # Verify both dates in effective period
        self.assertIn('effectivePeriod', medication)
        self.assertIn('2024-05-01', medication['effectivePeriod']['start'])
        self.assertIn('2024-05-10', medication['effectivePeriod']['end'])
    
    def test_structured_input_status_mapping(self):
        """Test that medication status is correctly mapped to FHIR codes."""
        status_test_cases = [
            ('active', 'active'),
            ('stopped', 'stopped'),
            ('completed', 'completed'),
            ('on-hold', 'on-hold'),
            ('intended', 'intended'),
            ('unknown', 'active'),  # Default fallback
        ]
        
        for input_status, expected_code in status_test_cases:
            extracted_data = {
                'patient_id': self.patient_id,
                'structured_data': {
                    'medications': [{
                        'name': 'Test Med',
                        'status': input_status,
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }]
                }
            }
            
            result = self.service.process_medications(extracted_data)
            self.assertEqual(len(result), 1)
            self.assertEqual(
                result[0]['status'],
                expected_code,
                f"Status '{input_status}' should map to '{expected_code}'"
            )
    
    def test_legacy_format_regression(self):
        """Test that legacy medication formats still work (backward compatibility)."""
        extracted_data = {
            'patient_id': self.patient_id,
            'medications': [
                {
                    'name': 'Lisinopril 10mg once daily',
                    'confidence': 0.88
                }
            ]
        }
        
        result = self.service.process_medications(extracted_data)
        
        # Verify legacy processing still works
        self.assertEqual(len(result), 1)
        medication = result[0]
        self.assertEqual(medication['resourceType'], 'MedicationStatement')
        self.assertIn('Lisinopril', medication['medicationCodeableConcept']['text'])
    
    def test_structured_input_empty_medications_list(self):
        """Test handling of empty medications list in structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'medications': []
            }
        }
        
        result = self.service.process_medications(extracted_data)
        
        # Should return empty list, not error
        self.assertEqual(len(result), 0)
    
    def test_missing_patient_id(self):
        """Test that missing patient_id is handled gracefully."""
        extracted_data = {
            'structured_data': {
                'medications': [{
                    'name': 'Test Medication',
                    'status': 'active',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = self.service.process_medications(extracted_data)
        
        # Should return empty list with warning logged
        self.assertEqual(len(result), 0)
    
    def test_invalid_structured_data(self):
        """Test handling of malformed structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'medications': [
                    {
                        # Missing required 'name' field
                        'dosage': '100mg',
                        'status': 'active',
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }
                ]
            }
        }
        
        result = self.service.process_medications(extracted_data)
        
        # Should skip invalid medication, return empty list
        self.assertEqual(len(result), 0)
    
    def test_multiple_medications_structured(self):
        """Test processing multiple medications from structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'medications': [
                    {
                        'name': 'Metformin',
                        'dosage': '500mg',
                        'frequency': 'twice daily',
                        'status': 'active',
                        'confidence': 0.95,
                        'source': {'text': 'metformin', 'start_index': 0, 'end_index': 9}
                    },
                    {
                        'name': 'Lisinopril',
                        'dosage': '10mg',
                        'frequency': 'once daily',
                        'status': 'active',
                        'confidence': 0.93,
                        'source': {'text': 'lisinopril', 'start_index': 10, 'end_index': 20}
                    },
                    {
                        'name': 'Atorvastatin',
                        'dosage': '20mg',
                        'frequency': 'once daily at bedtime',
                        'status': 'active',
                        'confidence': 0.91,
                        'source': {'text': 'atorvastatin', 'start_index': 21, 'end_index': 33}
                    }
                ]
            }
        }
        
        result = self.service.process_medications(extracted_data)
        
        # Verify all medications processed
        self.assertEqual(len(result), 3)
        med_names = [m['medicationCodeableConcept']['text'] for m in result]
        self.assertIn('Metformin', med_names)
        self.assertIn('Lisinopril', med_names)
        self.assertIn('Atorvastatin', med_names)
    
    @patch('apps.fhir.services.medication_service.ClinicalDateParser')
    def test_date_parser_used_for_structured_dates(self, mock_parser_class):
        """Test that ClinicalDateParser is used for date handling in structured path."""
        mock_parser = Mock()
        mock_date_result = Mock()
        mock_date_result.extracted_date.isoformat.return_value = '2023-01-15'
        mock_date_result.confidence = 0.95
        mock_parser.extract_dates.return_value = [mock_date_result]
        mock_parser_class.return_value = mock_parser
        
        # Create new service instance to use mocked parser
        service = MedicationService()
        
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'medications': [{
                    'name': 'Test Medication',
                    'status': 'active',
                    'start_date': '01/15/2023',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = service.process_medications(extracted_data)
        
        # Verify ClinicalDateParser was called for start_date
        mock_parser.extract_dates.assert_called_with('01/15/2023')
    
    def test_structured_path_priority_over_legacy(self):
        """Test that structured data is prioritized when both formats present."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'medications': [{
                    'name': 'Structured Medication',
                    'status': 'active',
                    'confidence': 0.95,
                    'source': {'text': 'structured', 'start_index': 0, 'end_index': 10}
                }]
            },
            'medications': [
                {
                    'name': 'Legacy Medication'
                }
            ]
        }
        
        result = self.service.process_medications(extracted_data)
        
        # Should use structured path (only 1 medication from structured, not from legacy)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['medicationCodeableConcept']['text'], 'Structured Medication')


if __name__ == '__main__':
    unittest.main()

