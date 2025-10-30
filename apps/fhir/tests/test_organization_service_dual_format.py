"""
Tests for OrganizationService dual-format support (Task 40.19)
"""

import unittest
from apps.fhir.services.organization_service import OrganizationService


class OrganizationServiceDualFormatTests(unittest.TestCase):
    """Test OrganizationService with both structured and legacy input formats."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = OrganizationService()
        self.patient_id = "test-patient-org-777"
    
    def test_structured_input_happy_path(self):
        """Test processing structured Organization data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'organizations': [{
                    'name': 'General Hospital',
                    'identifier': '1234567890',
                    'organization_type': 'hospital',
                    'address': '123 Medical Dr',
                    'city': 'Springfield',
                    'state': 'IL',
                    'postal_code': '62701',
                    'phone': '217-555-1000',
                    'confidence': 0.96,
                    'source': {'text': 'General Hospital', 'start_index': 0, 'end_index': 16}
                }]
            }
        }
        
        result = self.service.process_organizations(extracted_data)
        
        self.assertEqual(len(result), 1)
        org = result[0]
        self.assertEqual(org['resourceType'], 'Organization')
        self.assertEqual(org['name'], 'General Hospital')
        self.assertIn('identifier', org)
        self.assertIn('type', org)
        self.assertIn('address', org)
        self.assertIn('telecom', org)
    
    def test_structured_minimal_data(self):
        """Test with only required field."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'organizations': [{
                    'name': 'Community Clinic',
                    'confidence': 0.88,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = self.service.process_organizations(extracted_data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'Community Clinic')
    
    def test_organization_type_mapping(self):
        """Test organization type mapping."""
        type_cases = [
            ('hospital', 'prov'),
            ('clinic', 'prov'),
            ('lab', 'dept'),
            ('pharmacy', 'prov'),
        ]
        
        for org_type, expected_code in type_cases:
            extracted_data = {
                'patient_id': self.patient_id,
                'structured_data': {
                    'organizations': [{
                        'name': 'Test Org',
                        'organization_type': org_type,
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }]
                }
            }
            
            result = self.service.process_organizations(extracted_data)
            self.assertEqual(result[0]['type'][0]['coding'][0]['code'], expected_code)
    
    def test_legacy_fields_regression(self):
        """Test backward compatibility."""
        extracted_data = {
            'patient_id': self.patient_id,
            'fields': [{
                'label': 'Hospital',
                'value': 'Memorial Hospital',
                'confidence': 0.91
            }]
        }
        
        result = self.service.process_organizations(extracted_data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'Memorial Hospital')
    
    def test_empty_list(self):
        """Test empty list handling."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {'organizations': []}
        }
        
        result = self.service.process_organizations(extracted_data)
        self.assertEqual(len(result), 0)
    
    def test_missing_patient_id(self):
        """Test missing patient_id."""
        extracted_data = {
            'structured_data': {
                'organizations': [{
                    'name': 'Test',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = self.service.process_organizations(extracted_data)
        self.assertEqual(len(result), 0)


if __name__ == '__main__':
    unittest.main()

