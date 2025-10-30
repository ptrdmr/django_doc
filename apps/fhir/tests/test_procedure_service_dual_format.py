"""
Tests for ProcedureService dual-format support (Task 40.5)

Verifies that ProcedureService correctly processes both:
1. Structured Pydantic-derived dicts (primary path)
2. Legacy fields arrays (fallback path)
"""

import unittest
from unittest.mock import Mock, patch
from apps.fhir.services.procedure_service import ProcedureService


class ProcedureServiceDualFormatTests(unittest.TestCase):
    """Test ProcedureService with both structured and legacy input formats."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = ProcedureService()
        self.patient_id = "test-patient-proc-456"
    
    def test_structured_input_happy_path(self):
        """Test processing structured Pydantic-derived procedure data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'procedures': [
                    {
                        'name': 'Colonoscopy',
                        'procedure_date': '2024-08-15',
                        'provider': 'Dr. Smith',
                        'outcome': 'No abnormalities found',
                        'confidence': 0.97,
                        'source': {
                            'text': 'Colonoscopy performed by Dr. Smith on 08/15/2024',
                            'start_index': 100,
                            'end_index': 150
                        }
                    }
                ]
            }
        }
        
        result = self.service.process_procedures(extracted_data)
        
        # Verify resource created
        self.assertEqual(len(result), 1)
        procedure = result[0]
        
        # Verify FHIR structure
        self.assertEqual(procedure['resourceType'], 'Procedure')
        self.assertEqual(procedure['code']['text'], 'Colonoscopy')
        self.assertEqual(procedure['subject']['reference'], f'Patient/{self.patient_id}')
        self.assertEqual(procedure['status'], 'completed')
        
        # Verify performed date
        self.assertIn('performedDateTime', procedure)
        self.assertIn('2024-08-15', procedure['performedDateTime'])
        
        # Verify performer
        self.assertIn('performer', procedure)
        self.assertEqual(procedure['performer'][0]['actor']['display'], 'Dr. Smith')
        
        # Verify outcome
        self.assertIn('outcome', procedure)
        self.assertEqual(procedure['outcome']['text'], 'No abnormalities found')
        
        # Verify confidence
        confidence_tags = [tag for tag in procedure['meta']['tag'] if tag.get('code') == 'extraction-confidence']
        self.assertEqual(len(confidence_tags), 1)
        self.assertIn('0.97', confidence_tags[0]['display'])
        
        # Verify source note
        self.assertIn('note', procedure)
        self.assertIn('Colonoscopy', procedure['note'][0]['text'])
    
    def test_structured_input_minimal_data(self):
        """Test processing structured data with only required fields."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'procedures': [
                    {
                        'name': 'X-ray chest',
                        'confidence': 0.88,
                        'source': {
                            'text': 'Chest X-ray performed',
                            'start_index': 0,
                            'end_index': 21
                        }
                    }
                ]
            }
        }
        
        result = self.service.process_procedures(extracted_data)
        
        # Verify resource created with minimal data
        self.assertEqual(len(result), 1)
        procedure = result[0]
        self.assertEqual(procedure['code']['text'], 'X-ray chest')
        
        # Verify optional fields handled gracefully
        self.assertNotIn('performedDateTime', procedure)
        self.assertNotIn('performer', procedure)
        self.assertNotIn('outcome', procedure)
    
    def test_legacy_fields_format_regression(self):
        """Test that legacy fields format still works (backward compatibility)."""
        extracted_data = {
            'patient_id': self.patient_id,
            'fields': [
                {
                    'label': 'Surgical Procedure',
                    'value': 'Appendectomy performed on 2024-06-10',
                    'confidence': 0.91,
                    'source_context': 'Surgical history section'
                }
            ]
        }
        
        result = self.service.process_procedures(extracted_data)
        
        # Verify legacy processing still works
        self.assertEqual(len(result), 1)
        procedure = result[0]
        self.assertEqual(procedure['resourceType'], 'Procedure')
        self.assertEqual(procedure['code']['text'], 'Appendectomy performed on 2024-06-10')
        self.assertEqual(procedure['subject']['reference'], f'Patient/{self.patient_id}')
        
        # Verify date was extracted from text
        self.assertIn('performedDateTime', procedure)
        self.assertIn('2024-06-10', procedure['performedDateTime'])
    
    def test_structured_empty_procedures_list(self):
        """Test handling of empty procedures list in structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'procedures': []
            }
        }
        
        result = self.service.process_procedures(extracted_data)
        
        # Should return empty list, not error
        self.assertEqual(len(result), 0)
    
    def test_missing_patient_id(self):
        """Test that missing patient_id is handled gracefully."""
        extracted_data = {
            'structured_data': {
                'procedures': [{
                    'name': 'Test Procedure',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = self.service.process_procedures(extracted_data)
        
        # Should return empty list with warning logged
        self.assertEqual(len(result), 0)
    
    def test_invalid_structured_data(self):
        """Test handling of malformed structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'procedures': [
                    {
                        # Missing required 'name' field
                        'procedure_date': '2024-01-01',
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }
                ]
            }
        }
        
        result = self.service.process_procedures(extracted_data)
        
        # Should skip invalid procedure, return empty list
        self.assertEqual(len(result), 0)
    
    def test_multiple_procedures_structured(self):
        """Test processing multiple procedures from structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'procedures': [
                    {
                        'name': 'CT Scan Abdomen',
                        'procedure_date': '2024-09-01',
                        'provider': 'Dr. Johnson',
                        'confidence': 0.96,
                        'source': {'text': 'CT scan', 'start_index': 0, 'end_index': 7}
                    },
                    {
                        'name': 'Blood Draw',
                        'procedure_date': '2024-09-01',
                        'provider': 'Nurse Williams',
                        'confidence': 0.93,
                        'source': {'text': 'blood draw', 'start_index': 10, 'end_index': 20}
                    },
                    {
                        'name': 'EKG',
                        'procedure_date': '2024-09-02',
                        'provider': 'Tech Martinez',
                        'confidence': 0.94,
                        'source': {'text': 'EKG', 'start_index': 25, 'end_index': 28}
                    }
                ]
            }
        }
        
        result = self.service.process_procedures(extracted_data)
        
        # Verify all procedures processed
        self.assertEqual(len(result), 3)
        procedure_names = [p['code']['text'] for p in result]
        self.assertIn('CT Scan Abdomen', procedure_names)
        self.assertIn('Blood Draw', procedure_names)
        self.assertIn('EKG', procedure_names)
        
        # Verify performers
        for proc in result:
            self.assertIn('performer', proc)
    
    @patch('apps.fhir.services.procedure_service.ClinicalDateParser')
    def test_date_parser_used_for_structured_dates(self, mock_parser_class):
        """Test that ClinicalDateParser is used for date handling in structured path."""
        mock_parser = Mock()
        mock_date_result = Mock()
        mock_date_result.extracted_date.isoformat.return_value = '2024-08-15'
        mock_date_result.confidence = 0.95
        mock_parser.extract_dates.return_value = [mock_date_result]
        mock_parser_class.return_value = mock_parser
        
        # Create new service instance to use mocked parser
        service = ProcedureService()
        
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'procedures': [{
                    'name': 'Test Procedure',
                    'procedure_date': '08/15/2024',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = service.process_procedures(extracted_data)
        
        # Verify ClinicalDateParser was called
        mock_parser.extract_dates.assert_called_with('08/15/2024')
    
    def test_structured_path_priority_over_legacy(self):
        """Test that structured data is prioritized when both formats present."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'procedures': [{
                    'name': 'Structured Procedure',
                    'provider': 'Dr. Structured',
                    'confidence': 0.95,
                    'source': {'text': 'structured', 'start_index': 0, 'end_index': 10}
                }]
            },
            'fields': [{
                'label': 'Surgical Procedure',
                'value': 'Legacy Procedure',
                'confidence': 0.8
            }]
        }
        
        result = self.service.process_procedures(extracted_data)
        
        # Should use structured path (only 1 procedure from structured, not from fields)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['code']['text'], 'Structured Procedure')
        self.assertEqual(result[0]['performer'][0]['actor']['display'], 'Dr. Structured')


if __name__ == '__main__':
    unittest.main()

