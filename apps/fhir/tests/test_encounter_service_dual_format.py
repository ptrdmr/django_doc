"""
Tests for EncounterService dual-format support (Task 40.4)

Verifies that EncounterService correctly processes both:
1. Structured Pydantic-derived dicts (primary path - for future Encounter model)
2. Legacy encounter/visit/appointment structures (fallback path)
"""

import unittest
from unittest.mock import Mock, patch
from apps.fhir.services.encounter_service import EncounterService


class EncounterServiceDualFormatTests(unittest.TestCase):
    """Test EncounterService with both structured and legacy input formats."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = EncounterService()
        self.patient_id = "test-patient-encounter-123"
    
    def test_structured_input_happy_path(self):
        """Test processing structured Pydantic-derived encounter data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'encounters': [
                    {
                        'encounter_id': 'enc-001',
                        'encounter_type': 'office visit',
                        'encounter_date': '2024-10-20 09:00:00',
                        'encounter_end_date': '2024-10-20 09:45:00',
                        'location': 'Main Street Clinic',
                        'reason': 'Annual physical examination',
                        'participants': ['Dr. Sarah Johnson', 'Nurse Mary Smith'],
                        'status': 'finished',
                        'confidence': 0.96,
                        'source': {
                            'text': 'Patient seen for annual physical at Main Street Clinic',
                            'start_index': 50,
                            'end_index': 105
                        }
                    }
                ]
            }
        }
        
        result = self.service.process_encounters(extracted_data)
        
        # Verify resource created
        self.assertIsNotNone(result)
        
        # Verify FHIR structure
        self.assertEqual(result['resourceType'], 'Encounter')
        self.assertEqual(result['id'], 'enc-001')
        self.assertEqual(result['status'], 'finished')
        self.assertEqual(result['subject']['reference'], f'Patient/{self.patient_id}')
        
        # Verify class mapping
        self.assertEqual(result['class']['code'], 'AMB')
        self.assertEqual(result['class']['display'], 'Ambulatory')
        
        # Verify period with both start and end
        self.assertIn('period', result)
        self.assertIn('2024-10-20', result['period']['start'])
        self.assertIn('2024-10-20', result['period']['end'])
        
        # Verify location
        self.assertIn('location', result)
        self.assertEqual(result['location'][0]['location']['display'], 'Main Street Clinic')
        
        # Verify reason
        self.assertIn('reasonCode', result)
        self.assertEqual(result['reasonCode'][0]['text'], 'Annual physical examination')
        
        # Verify participants
        self.assertIn('participant', result)
        self.assertEqual(len(result['participant']), 2)
        participant_names = [p['individual']['display'] for p in result['participant']]
        self.assertIn('Dr. Sarah Johnson', participant_names)
        self.assertIn('Nurse Mary Smith', participant_names)
        
        # Verify confidence
        self.assertIn('extension', result)
        self.assertEqual(result['extension'][0]['valueDecimal'], 0.96)
    
    def test_structured_input_minimal_data(self):
        """Test processing structured data with only required fields."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'encounters': [{
                    'encounter_type': 'emergency',
                    'confidence': 0.85,
                    'source': {'text': 'ER visit', 'start_index': 0, 'end_index': 8}
                }]
            }
        }
        
        result = self.service.process_encounters(extracted_data)
        
        # Verify resource created with minimal data
        self.assertIsNotNone(result)
        self.assertEqual(result['class']['code'], 'EMER')
        self.assertEqual(result['class']['display'], 'Emergency')
        
        # Verify optional fields handled gracefully
        self.assertNotIn('period', result)
        self.assertNotIn('location', result)
        self.assertNotIn('reasonCode', result)
        self.assertNotIn('participant', result)
    
    def test_structured_encounter_type_mapping(self):
        """Test that encounter types are correctly mapped to FHIR class codes."""
        type_test_cases = [
            ('office visit', 'AMB', 'Ambulatory'),
            ('outpatient', 'AMB', 'Ambulatory'),
            ('emergency', 'EMER', 'Emergency'),
            ('er visit', 'EMER', 'Emergency'),
            ('inpatient', 'IMP', 'Inpatient encounter'),
            ('hospital admission', 'IMP', 'Inpatient encounter'),
            ('telehealth', 'VR', 'Virtual'),
            ('virtual visit', 'VR', 'Virtual'),
            ('home health', 'HH', 'Home health'),
            ('unknown type', 'AMB', 'Ambulatory'),  # Default
        ]
        
        for enc_type, expected_code, expected_display in type_test_cases:
            extracted_data = {
                'patient_id': self.patient_id,
                'structured_data': {
                    'encounters': [{
                        'encounter_type': enc_type,
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }]
                }
            }
            
            result = self.service.process_encounters(extracted_data)
            self.assertIsNotNone(result)
            self.assertEqual(
                result['class']['code'],
                expected_code,
                f"Encounter type '{enc_type}' should map to code '{expected_code}'"
            )
            self.assertEqual(result['class']['display'], expected_display)
    
    def test_structured_status_mapping(self):
        """Test encounter status mapping."""
        status_test_cases = [
            ('planned', 'planned'),
            ('arrived', 'arrived'),
            ('in-progress', 'in-progress'),
            ('finished', 'finished'),
            ('cancelled', 'cancelled'),
            ('unknown', 'finished'),  # Default
        ]
        
        for input_status, expected_status in status_test_cases:
            extracted_data = {
                'patient_id': self.patient_id,
                'structured_data': {
                    'encounters': [{
                        'encounter_type': 'office visit',
                        'status': input_status,
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }]
                }
            }
            
            result = self.service.process_encounters(extracted_data)
            self.assertEqual(
                result['status'],
                expected_status,
                f"Status '{input_status}' should map to '{expected_status}'"
            )
    
    def test_legacy_encounter_format_regression(self):
        """Test that legacy encounter format still works."""
        extracted_data = {
            'patient_id': self.patient_id,
            'encounter': {
                'type': 'AMB',
                'type_display': 'Ambulatory',
                'date': '2024-10-15',
                'location': 'Family Practice Clinic'
            }
        }
        
        result = self.service.process_encounters(extracted_data)
        
        # Verify legacy processing still works
        self.assertIsNotNone(result)
        self.assertEqual(result['resourceType'], 'Encounter')
        self.assertEqual(result['class']['code'], 'AMB')
    
    def test_structured_empty_encounters_list(self):
        """Test handling of empty encounters list."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'encounters': []
            }
        }
        
        result = self.service.process_encounters(extracted_data)
        
        # Should return None for empty list
        self.assertIsNone(result)
    
    def test_missing_patient_id(self):
        """Test that missing patient_id is handled gracefully."""
        extracted_data = {
            'structured_data': {
                'encounters': [{
                    'encounter_type': 'office visit',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = self.service.process_encounters(extracted_data)
        
        # Should return None with warning logged
        self.assertIsNone(result)
    
    def test_invalid_structured_data(self):
        """Test handling of malformed structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'encounters': [
                    {
                        # Missing required 'encounter_type' field
                        'location': 'Test Clinic',
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }
                ]
            }
        }
        
        result = self.service.process_encounters(extracted_data)
        
        # Should return None for invalid encounter
        self.assertIsNone(result)
    
    def test_multiple_participants_handling(self):
        """Test proper handling of multiple participants list."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'encounters': [{
                    'encounter_type': 'inpatient',
                    'participants': [
                        'Dr. John Doe',
                        'Dr. Jane Smith',
                        'Nurse Bob Wilson',
                        'Resident Alice Brown'
                    ],
                    'confidence': 0.92,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = self.service.process_encounters(extracted_data)
        
        self.assertIsNotNone(result)
        self.assertIn('participant', result)
        self.assertEqual(len(result['participant']), 4)
        
        # Verify all participants have proper structure
        for participant in result['participant']:
            self.assertIn('individual', participant)
            self.assertIn('display', participant['individual'])
            self.assertIn('type', participant)
            self.assertEqual(participant['type'][0]['coding'][0]['code'], 'ATND')
    
    @patch('apps.fhir.services.encounter_service.ClinicalDateParser')
    def test_date_parser_used_for_structured_dates(self, mock_parser_class):
        """Test that ClinicalDateParser is used for date handling."""
        mock_parser = Mock()
        mock_date_result = Mock()
        mock_date_result.extracted_date.isoformat.return_value = '2024-10-20'
        mock_date_result.confidence = 0.95
        mock_parser.extract_dates.return_value = [mock_date_result]
        mock_parser_class.return_value = mock_parser
        
        service = EncounterService()
        
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'encounters': [{
                    'encounter_type': 'office visit',
                    'encounter_date': '10/20/2024 09:00',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = service.process_encounters(extracted_data)
        
        # Verify ClinicalDateParser was called
        mock_parser.extract_dates.assert_called()
    
    def test_structured_path_priority_over_legacy(self):
        """Test that structured data is prioritized when both formats present."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'encounters': [{
                    'encounter_type': 'Structured Encounter',
                    'location': 'Structured Clinic',
                    'confidence': 0.95,
                    'source': {'text': 'structured', 'start_index': 0, 'end_index': 10}
                }]
            },
            'encounter': {
                'type': 'AMB',
                'location': 'Legacy Clinic'
            }
        }
        
        result = self.service.process_encounters(extracted_data)
        
        # Should use structured path
        self.assertIsNotNone(result)
        self.assertEqual(result['location'][0]['location']['display'], 'Structured Clinic')


if __name__ == '__main__':
    unittest.main()

