"""
Tests for ObservationService dual-format support (Task 40.3)

Verifies that ObservationService correctly processes both:
1. Structured Pydantic-derived dicts (VitalSign and LabResult models)
2. Legacy fields arrays (fallback path)
"""

import unittest
from unittest.mock import Mock, patch
from apps.fhir.services.observation_service import ObservationService


class ObservationServiceDualFormatTests(unittest.TestCase):
    """Test ObservationService with both structured and legacy input formats."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = ObservationService()
        self.patient_id = "test-patient-789"
    
    def test_structured_vital_sign_happy_path(self):
        """Test processing structured VitalSign Pydantic data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'vital_signs': [
                    {
                        'measurement': 'Heart Rate',
                        'value': '72',
                        'unit': 'bpm',
                        'timestamp': '2024-10-15 08:30:00',
                        'confidence': 0.94,
                        'source': {
                            'text': 'HR: 72 bpm',
                            'start_index': 100,
                            'end_index': 110
                        }
                    }
                ]
            }
        }
        
        result = self.service.process_observations(extracted_data)
        
        # Verify resource created
        self.assertEqual(len(result), 1)
        observation = result[0]
        
        # Verify FHIR structure
        self.assertEqual(observation['resourceType'], 'Observation')
        self.assertEqual(observation['code']['text'], 'Heart Rate')
        self.assertEqual(observation['subject']['reference'], f'Patient/{self.patient_id}')
        self.assertEqual(observation['status'], 'final')
        
        # Verify LOINC code for heart rate
        self.assertIn('coding', observation['code'])
        self.assertEqual(observation['code']['coding'][0]['code'], '8867-4')
        self.assertEqual(observation['code']['coding'][0]['system'], 'http://loinc.org')
        
        # Verify value and unit
        self.assertIn('valueQuantity', observation)
        self.assertEqual(observation['valueQuantity']['value'], 72.0)
        self.assertEqual(observation['valueQuantity']['unit'], 'bpm')
        
        # Verify effective date
        self.assertIn('effectiveDateTime', observation)
        self.assertIn('2024-10-15', observation['effectiveDateTime'])
        
        # Verify confidence tag
        confidence_tags = [tag for tag in observation['meta']['tag'] if tag.get('code') == 'extraction-confidence']
        self.assertEqual(len(confidence_tags), 1)
        self.assertIn('0.94', confidence_tags[0]['display'])
    
    def test_structured_lab_result_happy_path(self):
        """Test processing structured LabResult Pydantic data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'lab_results': [
                    {
                        'test_name': 'Hemoglobin A1c',
                        'value': '6.5',
                        'unit': '%',
                        'reference_range': '4.0-6.0%',
                        'test_date': '2024-09-20',
                        'status': 'final',
                        'confidence': 0.97,
                        'source': {
                            'text': 'HbA1c: 6.5% (ref 4.0-6.0%)',
                            'start_index': 200,
                            'end_index': 228
                        }
                    }
                ]
            }
        }
        
        result = self.service.process_observations(extracted_data)
        
        # Verify resource created
        self.assertEqual(len(result), 1)
        observation = result[0]
        
        # Verify FHIR structure
        self.assertEqual(observation['resourceType'], 'Observation')
        self.assertEqual(observation['code']['text'], 'Hemoglobin A1c')
        self.assertEqual(observation['status'], 'final')
        
        # Verify value and unit
        self.assertIn('valueQuantity', observation)
        self.assertEqual(observation['valueQuantity']['value'], 6.5)
        self.assertEqual(observation['valueQuantity']['unit'], '%')
        
        # Verify reference range
        self.assertIn('referenceRange', observation)
        self.assertEqual(observation['referenceRange'][0]['text'], '4.0-6.0%')
        
        # Verify test date
        self.assertIn('effectiveDateTime', observation)
        self.assertIn('2024-09-20', observation['effectiveDateTime'])
    
    def test_structured_vital_sign_minimal_data(self):
        """Test VitalSign with only required fields."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'vital_signs': [
                    {
                        'measurement': 'Temperature',
                        'value': '98.6',
                        'confidence': 0.9,
                        'source': {'text': 'temp', 'start_index': 0, 'end_index': 4}
                    }
                ]
            }
        }
        
        result = self.service.process_observations(extracted_data)
        
        self.assertEqual(len(result), 1)
        observation = result[0]
        self.assertEqual(observation['code']['text'], 'Temperature')
        self.assertEqual(observation['valueQuantity']['value'], 98.6)
        
        # No unit or timestamp provided - should handle gracefully
        self.assertNotIn('unit', observation['valueQuantity'])
        self.assertNotIn('effectiveDateTime', observation)
    
    def test_structured_lab_result_with_status(self):
        """Test LabResult status mapping."""
        status_test_cases = [
            ('final', 'final'),
            ('preliminary', 'preliminary'),
            ('amended', 'amended'),
            ('corrected', 'corrected'),
            ('cancelled', 'cancelled'),
            ('unknown', 'final'),  # Default
        ]
        
        for input_status, expected_status in status_test_cases:
            extracted_data = {
                'patient_id': self.patient_id,
                'structured_data': {
                    'lab_results': [{
                        'test_name': 'Test Lab',
                        'value': '10',
                        'status': input_status,
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }]
                }
            }
            
            result = self.service.process_observations(extracted_data)
            self.assertEqual(len(result), 1)
            self.assertEqual(
                result[0]['status'],
                expected_status,
                f"Status '{input_status}' should map to '{expected_status}'"
            )
    
    def test_structured_both_vitals_and_labs(self):
        """Test processing both VitalSign and LabResult in same request."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'vital_signs': [
                    {
                        'measurement': 'Blood Pressure',
                        'value': '120/80',
                        'unit': 'mmHg',
                        'confidence': 0.92,
                        'source': {'text': 'BP: 120/80', 'start_index': 0, 'end_index': 11}
                    }
                ],
                'lab_results': [
                    {
                        'test_name': 'Glucose',
                        'value': '95',
                        'unit': 'mg/dL',
                        'confidence': 0.95,
                        'source': {'text': 'Glucose: 95 mg/dL', 'start_index': 20, 'end_index': 37}
                    }
                ]
            }
        }
        
        result = self.service.process_observations(extracted_data)
        
        # Should process both vital and lab
        self.assertEqual(len(result), 2)
        
        obs_names = [obs['code']['text'] for obs in result]
        self.assertIn('Blood Pressure', obs_names)
        self.assertIn('Glucose', obs_names)
    
    def test_legacy_fields_format_regression(self):
        """Test that legacy fields format still works."""
        extracted_data = {
            'patient_id': self.patient_id,
            'fields': [
                {
                    'label': 'Vital Sign - Heart Rate',
                    'value': 'HR: 75 bpm',
                    'confidence': 0.88
                }
            ]
        }
        
        result = self.service.process_observations(extracted_data)
        
        # Verify legacy processing still works
        self.assertEqual(len(result), 1)
        observation = result[0]
        self.assertEqual(observation['resourceType'], 'Observation')
        self.assertIn('Heart Rate', observation['code']['text'])
    
    def test_structured_empty_lists(self):
        """Test handling of empty vital_signs and lab_results lists."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'vital_signs': [],
                'lab_results': []
            }
        }
        
        result = self.service.process_observations(extracted_data)
        
        # Should return empty list, not error
        self.assertEqual(len(result), 0)
    
    def test_missing_patient_id(self):
        """Test that missing patient_id is handled gracefully."""
        extracted_data = {
            'structured_data': {
                'vital_signs': [{
                    'measurement': 'Heart Rate',
                    'value': '70',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = self.service.process_observations(extracted_data)
        
        # Should return empty list with warning logged
        self.assertEqual(len(result), 0)
    
    def test_invalid_structured_data(self):
        """Test handling of malformed structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'vital_signs': [
                    {
                        # Missing required 'measurement' field
                        'value': '100',
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }
                ]
            }
        }
        
        result = self.service.process_observations(extracted_data)
        
        # Should skip invalid observation, return empty list
        self.assertEqual(len(result), 0)
    
    def test_multiple_vital_signs_structured(self):
        """Test processing multiple vital signs from structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'vital_signs': [
                    {
                        'measurement': 'Heart Rate',
                        'value': '72',
                        'unit': 'bpm',
                        'confidence': 0.95,
                        'source': {'text': 'HR: 72', 'start_index': 0, 'end_index': 7}
                    },
                    {
                        'measurement': 'Blood Pressure',
                        'value': '120/80',
                        'unit': 'mmHg',
                        'confidence': 0.93,
                        'source': {'text': 'BP: 120/80', 'start_index': 10, 'end_index': 21}
                    },
                    {
                        'measurement': 'Temperature',
                        'value': '98.6',
                        'unit': 'F',
                        'confidence': 0.91,
                        'source': {'text': 'Temp: 98.6F', 'start_index': 25, 'end_index': 36}
                    }
                ]
            }
        }
        
        result = self.service.process_observations(extracted_data)
        
        # Verify all vital signs processed
        self.assertEqual(len(result), 3)
        vital_names = [obs['code']['text'] for obs in result]
        self.assertIn('Heart Rate', vital_names)
        self.assertIn('Blood Pressure', vital_names)
        self.assertIn('Temperature', vital_names)
    
    @patch('apps.fhir.services.observation_service.ClinicalDateParser')
    def test_date_parser_used_for_structured_dates(self, mock_parser_class):
        """Test that ClinicalDateParser is used for date handling."""
        mock_parser = Mock()
        mock_date_result = Mock()
        mock_date_result.extracted_date.isoformat.return_value = '2024-10-15'
        mock_date_result.confidence = 0.95
        mock_parser.extract_dates.return_value = [mock_date_result]
        mock_parser_class.return_value = mock_parser
        
        service = ObservationService()
        
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'vital_signs': [{
                    'measurement': 'Heart Rate',
                    'value': '70',
                    'timestamp': '10/15/2024 08:30',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = service.process_observations(extracted_data)
        
        # Verify ClinicalDateParser was called
        mock_parser.extract_dates.assert_called_with('10/15/2024 08:30')
    
    def test_structured_path_priority_over_legacy(self):
        """Test that structured data is prioritized when both formats present."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'vital_signs': [{
                    'measurement': 'Structured Vital',
                    'value': '100',
                    'confidence': 0.95,
                    'source': {'text': 'structured', 'start_index': 0, 'end_index': 10}
                }]
            },
            'fields': [{
                'label': 'Vital Sign - Legacy',
                'value': 'Legacy: 50',
                'confidence': 0.8
            }]
        }
        
        result = self.service.process_observations(extracted_data)
        
        # Should use structured path
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['code']['text'], 'Structured Vital')
    
    def test_structured_non_numeric_value(self):
        """Test handling of non-numeric observation values."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'vital_signs': [{
                    'measurement': 'General Appearance',
                    'value': 'Alert and oriented',
                    'confidence': 0.88,
                    'source': {'text': 'patient alert', 'start_index': 0, 'end_index': 13}
                }]
            }
        }
        
        result = self.service.process_observations(extracted_data)
        
        self.assertEqual(len(result), 1)
        observation = result[0]
        
        # Non-numeric value should use valueString
        self.assertIn('valueString', observation)
        self.assertEqual(observation['valueString'], 'Alert and oriented')
        self.assertNotIn('valueQuantity', observation)


if __name__ == '__main__':
    unittest.main()

