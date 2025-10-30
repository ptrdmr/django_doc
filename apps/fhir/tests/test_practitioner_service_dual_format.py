"""
Tests for PractitionerService dual-format support (Task 40.6)

Verifies that PractitionerService correctly processes both:
1. Structured Pydantic-derived dicts (primary path)
2. Legacy fields arrays (fallback path)
"""

import unittest
from apps.fhir.services.practitioner_service import PractitionerService


class PractitionerServiceDualFormatTests(unittest.TestCase):
    """Test PractitionerService with both structured and legacy input formats."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = PractitionerService()
        self.patient_id = "test-patient-prac-789"
    
    def test_structured_input_happy_path(self):
        """Test processing structured Pydantic-derived provider data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'providers': [
                    {
                        'name': 'Dr. Sarah Johnson',
                        'specialty': 'Cardiology',
                        'role': 'Attending Physician',
                        'contact_info': '555-1234',
                        'confidence': 0.98,
                        'source': {
                            'text': 'Attending physician: Dr. Sarah Johnson, Cardiology',
                            'start_index': 100,
                            'end_index': 151
                        }
                    }
                ]
            }
        }
        
        result = self.service.process_practitioners(extracted_data)
        
        # Verify resource created
        self.assertEqual(len(result), 1)
        practitioner = result[0]
        
        # Verify FHIR structure
        self.assertEqual(practitioner['resourceType'], 'Practitioner')
        self.assertEqual(practitioner['name'][0]['text'], 'Dr. Sarah Johnson')
        
        # Verify name parsing (Dr. Sarah Johnson → given: ['Sarah'], family: 'Johnson')
        self.assertEqual(practitioner['name'][0]['family'], 'Johnson')
        self.assertIn('Sarah', practitioner['name'][0]['given'])
        
        # Verify specialty as qualification
        self.assertIn('qualification', practitioner)
        self.assertEqual(practitioner['qualification'][0]['code']['text'], 'Cardiology')
        
        # Verify role as extension
        self.assertIn('extension', practitioner)
        role_ext = [ext for ext in practitioner['extension'] if 'practitioner-role' in ext['url']]
        self.assertEqual(len(role_ext), 1)
        self.assertEqual(role_ext[0]['valueString'], 'Attending Physician')
        
        # Verify contact as telecom
        self.assertIn('telecom', practitioner)
        self.assertEqual(practitioner['telecom'][0]['system'], 'phone')
        self.assertEqual(practitioner['telecom'][0]['value'], '555-1234')
        
        # Verify confidence
        confidence_ext = [ext for ext in practitioner['extension'] if 'data-confidence' in ext['url']]
        self.assertEqual(len(confidence_ext), 1)
        self.assertEqual(confidence_ext[0]['valueDecimal'], 0.98)
    
    def test_structured_input_minimal_data(self):
        """Test processing structured data with only required fields."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'providers': [
                    {
                        'name': 'Dr. Smith',
                        'confidence': 0.85,
                        'source': {
                            'text': 'Dr. Smith',
                            'start_index': 0,
                            'end_index': 9
                        }
                    }
                ]
            }
        }
        
        result = self.service.process_practitioners(extracted_data)
        
        # Verify resource created with minimal data
        self.assertEqual(len(result), 1)
        practitioner = result[0]
        self.assertEqual(practitioner['name'][0]['text'], 'Dr. Smith')
        self.assertEqual(practitioner['name'][0]['family'], 'Smith')
        
        # Verify optional fields handled gracefully
        self.assertNotIn('qualification', practitioner)
        self.assertNotIn('telecom', practitioner)
    
    def test_name_parsing_various_formats(self):
        """Test provider name parsing handles different formats."""
        name_test_cases = [
            ('Dr. John Doe', 'Doe', ['John']),
            ('Smith, Jane', 'Smith', ['Jane']),
            ('Robert James Wilson', 'Wilson', ['Robert', 'James']),
            ('Dr. Emily Chen, MD', 'Chen', ['Emily']),
            ('SingleName', 'SingleName', []),
        ]
        
        for input_name, expected_family, expected_given in name_test_cases:
            extracted_data = {
                'patient_id': self.patient_id,
                'structured_data': {
                    'providers': [{
                        'name': input_name,
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }]
                }
            }
            
            result = self.service.process_practitioners(extracted_data)
            self.assertEqual(len(result), 1)
            self.assertEqual(
                result[0]['name'][0]['family'],
                expected_family,
                f"Name '{input_name}' should parse family as '{expected_family}'"
            )
            self.assertEqual(result[0]['name'][0]['given'], expected_given)
    
    def test_contact_info_email_detection(self):
        """Test that email contact info is properly detected."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'providers': [{
                    'name': 'Dr. Jones',
                    'contact_info': 'dr.jones@clinic.com',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = self.service.process_practitioners(extracted_data)
        
        self.assertEqual(len(result), 1)
        practitioner = result[0]
        
        # Verify email system detected
        self.assertIn('telecom', practitioner)
        self.assertEqual(practitioner['telecom'][0]['system'], 'email')
        self.assertEqual(practitioner['telecom'][0]['value'], 'dr.jones@clinic.com')
    
    def test_legacy_fields_format_regression(self):
        """Test that legacy fields format still works (backward compatibility)."""
        extracted_data = {
            'patient_id': self.patient_id,
            'fields': [
                {
                    'label': 'Attending Physician',
                    'value': 'Dr. Michael Brown',
                    'confidence': 0.92,
                    'source_context': 'Provider section'
                }
            ]
        }
        
        result = self.service.process_practitioners(extracted_data)
        
        # Verify legacy processing still works
        self.assertEqual(len(result), 1)
        practitioner = result[0]
        self.assertEqual(practitioner['resourceType'], 'Practitioner')
        self.assertEqual(practitioner['name'][0]['text'], 'Dr. Michael Brown')
        self.assertEqual(practitioner['name'][0]['family'], 'Brown')
        self.assertIn('Michael', practitioner['name'][0]['given'])
    
    def test_structured_empty_providers_list(self):
        """Test handling of empty providers list in structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'providers': []
            }
        }
        
        result = self.service.process_practitioners(extracted_data)
        
        # Should return empty list, not error
        self.assertEqual(len(result), 0)
    
    def test_missing_patient_id(self):
        """Test that missing patient_id is handled gracefully."""
        extracted_data = {
            'structured_data': {
                'providers': [{
                    'name': 'Dr. Test',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = self.service.process_practitioners(extracted_data)
        
        # Should return empty list with warning logged
        self.assertEqual(len(result), 0)
    
    def test_invalid_structured_data(self):
        """Test handling of malformed structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'providers': [
                    {
                        # Missing required 'name' field
                        'specialty': 'Cardiology',
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }
                ]
            }
        }
        
        result = self.service.process_practitioners(extracted_data)
        
        # Should skip invalid provider, return empty list
        self.assertEqual(len(result), 0)
    
    def test_multiple_practitioners_structured(self):
        """Test processing multiple practitioners from structured data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'providers': [
                    {
                        'name': 'Dr. Alice Cooper',
                        'specialty': 'Internal Medicine',
                        'confidence': 0.96,
                        'source': {'text': 'Dr. Cooper', 'start_index': 0, 'end_index': 10}
                    },
                    {
                        'name': 'Nurse Bob Wilson',
                        'role': 'Primary Care Nurse',
                        'confidence': 0.93,
                        'source': {'text': 'Nurse Wilson', 'start_index': 15, 'end_index': 27}
                    },
                    {
                        'name': 'Dr. Carol Martinez',
                        'specialty': 'Neurology',
                        'role': 'Consulting Neurologist',
                        'confidence': 0.94,
                        'source': {'text': 'Dr. Martinez', 'start_index': 30, 'end_index': 42}
                    }
                ]
            }
        }
        
        result = self.service.process_practitioners(extracted_data)
        
        # Verify all practitioners processed
        self.assertEqual(len(result), 3)
        practitioner_names = [p['name'][0]['text'] for p in result]
        self.assertIn('Dr. Alice Cooper', practitioner_names)
        self.assertIn('Nurse Bob Wilson', practitioner_names)
        self.assertIn('Dr. Carol Martinez', practitioner_names)
    
    def test_structured_path_priority_over_legacy(self):
        """Test that structured data is prioritized when both formats present."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'providers': [{
                    'name': 'Dr. Structured Provider',
                    'specialty': 'Structured Specialty',
                    'confidence': 0.95,
                    'source': {'text': 'structured', 'start_index': 0, 'end_index': 10}
                }]
            },
            'fields': [{
                'label': 'Physician',
                'value': 'Dr. Legacy Provider',
                'confidence': 0.8
            }]
        }
        
        result = self.service.process_practitioners(extracted_data)
        
        # Should use structured path
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'][0]['text'], 'Dr. Structured Provider')
        self.assertEqual(result[0]['qualification'][0]['code']['text'], 'Structured Specialty')


if __name__ == '__main__':
    unittest.main()

