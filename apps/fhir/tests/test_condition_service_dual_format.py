"""
Tests for ConditionService dual-format support (Task 40.1)

Verifies that ConditionService correctly processes both:
1. Structured Pydantic-derived dicts (primary path)
2. Legacy fields arrays (fallback path)
"""

import unittest
from unittest.mock import Mock, patch
from apps.fhir.services.condition_service import ConditionService


class ConditionServiceDualFormatTests(unittest.TestCase):
    """Test ConditionService with both structured and legacy input formats."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = ConditionService()
        self.patient_id = "test-patient-123"
    
    def test_structured_input_happy_path(self):
        """Test processing structured Pydantic-derived condition data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'conditions': [
                    {
                        'name': 'Type 2 Diabetes Mellitus',
                        'status': 'active',
                        'onset_date': '2020-03-15',
                        'icd_code': 'E11.9',
                        'confidence': 0.95,
                        'source': {
                            'text': 'Patient has history of Type 2 Diabetes Mellitus',
                            'start_index': 100,
                            'end_index': 150
                        }
                    }
                ]
            }
        }
        
        result = self.service.process_conditions(extracted_data)
        
        # Verify resource created
        self.assertEqual(len(result), 1)
        condition = result[0]
        
        # Verify FHIR structure
        self.assertEqual(condition['resourceType'], 'Condition')
        self.assertEqual(condition['code']['text'], 'Type 2 Diabetes Mellitus')
        self.assertEqual(condition['subject']['reference'], f'Patient/{self.patient_id}')
        
        # Verify ICD code included
        self.assertIn('coding', condition['code'])
        self.assertEqual(condition['code']['coding'][0]['code'], 'E11.9')
        self.assertEqual(condition['code']['coding'][0]['system'], 'http://hl7.org/fhir/sid/icd-10')
        
        # Verify clinical status mapped correctly
        self.assertEqual(condition['clinicalStatus']['coding'][0]['code'], 'active')
        
        # Verify onset date included
        self.assertIn('onsetDateTime', condition)
        self.assertIn('2020-03-15', condition['onsetDateTime'])
        
        # Verify confidence tag
        confidence_tags = [tag for tag in condition['meta']['tag'] if tag.get('code') == 'extraction-confidence']
        self.assertEqual(len(confidence_tags), 1)
        self.assertIn('0.95', confidence_tags[0]['display'])
        
        # Verify source note
        self.assertIn('note', condition)
        self.assertIn('Type 2 Diabetes Mellitus', condition['note'][0]['text'])
    
    def test_structured_input_minimal_data(self):
        """Test processing structured data with only required fields."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'conditions': [
                    {
                        'name': 'Hypertension',
                        'status': 'active',
                        'confidence': 0.8,
                        'source': {
                            'text': 'Hypertension noted',
                            'start_index': 0,
                            'end_index': 20
                        }
                    }
                ]
            }
        }
        
        result = self.service.process_conditions(extracted_data)
        
        # Verify resource created with minimal data
        self.assertEqual(len(result), 1)
        condition = result[0]
        self.assertEqual(condition['code']['text'], 'Hypertension')
        
        # Verify optional fields handled gracefully (no ICD code, no onset date)
        self.assertNotIn('onsetDateTime', condition)
    
    def test_structured_input_status_mapping(self):
        """Test that condition status is correctly mapped to FHIR codes."""
        status_test_cases = [
            ('active', 'active'),
            ('inactive', 'inactive'),
            ('resolved', 'resolved'),
            ('remission', 'remission'),
            ('unknown_status', 'active'),  # Default fallback
        ]
        
        for input_status, expected_code in status_test_cases:
            extracted_data = {
                'patient_id': self.patient_id,
                'structured_data': {
                    'conditions': [{
                        'name': 'Test Condition',
                        'status': input_status,
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }]
                }
            }
            
            result = self.service.process_conditions(extracted_data)
            self.assertEqual(len(result), 1)
            self.assertEqual(
                result[0]['clinicalStatus']['coding'][0]['code'],
                expected_code,
                f"Status '{input_status}' should map to '{expected_code}'"
            )
    
    def test_legacy_fields_format_regression(self):
        """Test that legacy fields format still works (backward compatibility)."""
        extracted_data = {
            'patient_id': self.patient_id,
            'fields': [
                {
                    'label': 'Primary Diagnosis',
                    'value': 'Chronic Kidney Disease Stage 3',
                    'confidence': 0.88,
                    'source_context': 'Medical history section'
                }
            ]
        }
        
        result = self.service.process_conditions(extracted_data)
        
        # Verify legacy processing still works
        self.assertEqual(len(result), 1)
        condition = result[0]
        self.assertEqual(condition['resourceType'], 'Condition')
        self.assertEqual(condition['code']['text'], 'Chronic Kidney Disease Stage 3')
        self.assertEqual(condition['subject']['reference'], f'Patient/{self.patient_id}')
    
    def test_structured_input_empty_conditions_list(self):
        """Test handling of empty conditions list in structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'conditions': []
            }
        }
        
        result = self.service.process_conditions(extracted_data)
        
        # Should return empty list, not error
        self.assertEqual(len(result), 0)
    
    def test_missing_patient_id(self):
        """Test that missing patient_id is handled gracefully."""
        extracted_data = {
            'structured_data': {
                'conditions': [{
                    'name': 'Test Condition',
                    'status': 'active',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = self.service.process_conditions(extracted_data)
        
        # Should return empty list with warning logged
        self.assertEqual(len(result), 0)
    
    def test_invalid_structured_data(self):
        """Test handling of malformed structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'conditions': [
                    {
                        # Missing required 'name' field
                        'status': 'active',
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }
                ]
            }
        }
        
        result = self.service.process_conditions(extracted_data)
        
        # Should skip invalid condition, return empty list
        self.assertEqual(len(result), 0)
    
    def test_multiple_conditions_structured(self):
        """Test processing multiple conditions from structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'conditions': [
                    {
                        'name': 'Type 2 Diabetes',
                        'status': 'active',
                        'icd_code': 'E11.9',
                        'confidence': 0.95,
                        'source': {'text': 'diabetes', 'start_index': 0, 'end_index': 8}
                    },
                    {
                        'name': 'Hypertension',
                        'status': 'active',
                        'icd_code': 'I10',
                        'confidence': 0.92,
                        'source': {'text': 'hypertension', 'start_index': 10, 'end_index': 22}
                    },
                    {
                        'name': 'Hyperlipidemia',
                        'status': 'active',
                        'icd_code': 'E78.5',
                        'confidence': 0.88,
                        'source': {'text': 'high cholesterol', 'start_index': 25, 'end_index': 41}
                    }
                ]
            }
        }
        
        result = self.service.process_conditions(extracted_data)
        
        # Verify all conditions processed
        self.assertEqual(len(result), 3)
        condition_names = [c['code']['text'] for c in result]
        self.assertIn('Type 2 Diabetes', condition_names)
        self.assertIn('Hypertension', condition_names)
        self.assertIn('Hyperlipidemia', condition_names)
    
    @patch('apps.fhir.services.condition_service.ClinicalDateParser')
    def test_date_parser_used_for_structured_dates(self, mock_parser_class):
        """Test that ClinicalDateParser is used for date handling in structured path."""
        mock_parser = Mock()
        mock_date_result = Mock()
        mock_date_result.extracted_date.isoformat.return_value = '2020-03-15'
        mock_date_result.confidence = 0.95
        mock_parser.extract_dates.return_value = [mock_date_result]
        mock_parser_class.return_value = mock_parser
        
        # Create new service instance to use mocked parser
        service = ConditionService()
        
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'conditions': [{
                    'name': 'Test Condition',
                    'status': 'active',
                    'onset_date': '03/15/2020',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = service.process_conditions(extracted_data)
        
        # Verify ClinicalDateParser was called
        mock_parser.extract_dates.assert_called_once_with('03/15/2020')
    
    def test_structured_path_priority_over_legacy(self):
        """Test that structured data is prioritized when both formats present."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'conditions': [{
                    'name': 'Structured Condition',
                    'status': 'active',
                    'confidence': 0.95,
                    'source': {'text': 'structured', 'start_index': 0, 'end_index': 10}
                }]
            },
            'fields': [{
                'label': 'Primary Diagnosis',
                'value': 'Legacy Condition',
                'confidence': 0.8
            }]
        }
        
        result = self.service.process_conditions(extracted_data)
        
        # Should use structured path (only 1 condition from structured, not from fields)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['code']['text'], 'Structured Condition')


if __name__ == '__main__':
    unittest.main()

