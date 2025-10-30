"""
Tests for AllergyIntoleranceService dual-format support (Task 40.17)

Verifies that AllergyIntoleranceService correctly processes both:
1. Structured Pydantic-derived dicts (primary path)
2. Legacy fields arrays (fallback path)
"""

import unittest
from apps.fhir.services.allergy_intolerance_service import AllergyIntoleranceService


class AllergyIntoleranceServiceDualFormatTests(unittest.TestCase):
    """Test AllergyIntoleranceService with both structured and legacy input formats."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = AllergyIntoleranceService()
        self.patient_id = "test-patient-allergy-999"
    
    def test_structured_input_happy_path(self):
        """Test processing structured Pydantic-derived allergy data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'allergies': [
                    {
                        'allergen': 'Penicillin',
                        'reaction': 'Anaphylaxis',
                        'severity': 'severe',
                        'onset_date': '2015-06-10',
                        'status': 'active',
                        'verification_status': 'confirmed',
                        'confidence': 0.98,
                        'source': {
                            'text': 'Severe penicillin allergy confirmed',
                            'start_index': 100,
                            'end_index': 136
                        }
                    }
                ]
            }
        }
        
        result = self.service.process_allergies(extracted_data)
        
        self.assertEqual(len(result), 1)
        allergy = result[0]
        
        # Verify FHIR structure
        self.assertEqual(allergy['resourceType'], 'AllergyIntolerance')
        self.assertEqual(allergy['code']['text'], 'Penicillin')
        self.assertEqual(allergy['patient']['reference'], f'Patient/{self.patient_id}')
        
        # Verify clinical status
        self.assertEqual(allergy['clinicalStatus']['coding'][0]['code'], 'active')
        
        # Verify verification status
        self.assertEqual(allergy['verificationStatus']['coding'][0]['code'], 'confirmed')
        
        # Verify reaction with severity
        self.assertIn('reaction', allergy)
        self.assertEqual(allergy['reaction'][0]['manifestation'][0]['text'], 'Anaphylaxis')
        self.assertEqual(allergy['reaction'][0]['severity'], 'severe')
        
        # Verify onset date
        self.assertIn('onsetDateTime', allergy)
        self.assertIn('2015-06-10', allergy['onsetDateTime'])
    
    def test_structured_minimal_data(self):
        """Test with only required fields."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'allergies': [{
                    'allergen': 'Shellfish',
                    'confidence': 0.85,
                    'source': {'text': 'shellfish allergy', 'start_index': 0, 'end_index': 17}
                }]
            }
        }
        
        result = self.service.process_allergies(extracted_data)
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['code']['text'], 'Shellfish')
    
    def test_severity_mapping(self):
        """Test severity mapping."""
        severity_cases = [
            ('mild', 'mild'),
            ('moderate', 'moderate'),
            ('severe', 'severe'),
            ('life-threatening', 'severe'),
        ]
        
        for input_severity, expected_fhir in severity_cases:
            extracted_data = {
                'patient_id': self.patient_id,
                'structured_data': {
                    'allergies': [{
                        'allergen': 'Test',
                        'reaction': 'Rash',
                        'severity': input_severity,
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }]
                }
            }
            
            result = self.service.process_allergies(extracted_data)
            self.assertEqual(result[0]['reaction'][0]['severity'], expected_fhir)
    
    def test_status_mapping(self):
        """Test status mapping."""
        for status in ['active', 'inactive', 'resolved']:
            extracted_data = {
                'patient_id': self.patient_id,
                'structured_data': {
                    'allergies': [{
                        'allergen': 'Test',
                        'status': status,
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }]
                }
            }
            
            result = self.service.process_allergies(extracted_data)
            self.assertEqual(result[0]['clinicalStatus']['coding'][0]['code'], status)
    
    def test_legacy_fields_regression(self):
        """Test backward compatibility with legacy fields."""
        extracted_data = {
            'patient_id': self.patient_id,
            'fields': [{
                'label': 'Allergies',
                'value': 'Latex allergy',
                'confidence': 0.88
            }]
        }
        
        result = self.service.process_allergies(extracted_data)
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['code']['text'], 'Latex allergy')
    
    def test_nkda_handling(self):
        """Test that NKDA doesn't create allergy resource."""
        extracted_data = {
            'patient_id': self.patient_id,
            'fields': [{
                'label': 'Allergies',
                'value': 'NKDA',
                'confidence': 0.95
            }]
        }
        
        result = self.service.process_allergies(extracted_data)
        
        # NKDA should not create resource
        self.assertEqual(len(result), 0)
    
    def test_empty_allergies_list(self):
        """Test empty list handling."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'allergies': []
            }
        }
        
        result = self.service.process_allergies(extracted_data)
        self.assertEqual(len(result), 0)
    
    def test_missing_patient_id(self):
        """Test missing patient_id handling."""
        extracted_data = {
            'structured_data': {
                'allergies': [{
                    'allergen': 'Test',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = self.service.process_allergies(extracted_data)
        self.assertEqual(len(result), 0)


if __name__ == '__main__':
    unittest.main()

