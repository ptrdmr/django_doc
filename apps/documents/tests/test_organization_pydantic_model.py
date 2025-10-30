"""
Tests for Organization Pydantic model (Task 40.15)

Verifies that the Organization Pydantic model:
1. Validates correctly with valid data
2. Rejects invalid data appropriately
3. Serializes/deserializes properly
4. Integrates into StructuredMedicalExtraction
"""

import unittest
from pydantic import ValidationError
from apps.documents.services.ai_extraction import Organization, StructuredMedicalExtraction, SourceContext


class OrganizationPydanticModelTests(unittest.TestCase):
    """Test Organization Pydantic model validation and integration."""
    
    def test_organization_model_valid_full_data(self):
        """Test Organization model with all fields populated."""
        organization = Organization(
            organization_id='org-001',
            name='General Hospital',
            identifier='1234567890',
            organization_type='hospital',
            address='123 Medical Center Drive',
            city='Springfield',
            state='IL',
            postal_code='62701',
            phone='217-555-1000',
            confidence=0.96,
            source=SourceContext(
                text='General Hospital, 123 Medical Center Dr, Springfield IL 62701',
                start_index=250,
                end_index=313
            )
        )
        
        # Verify all fields
        self.assertEqual(organization.organization_id, 'org-001')
        self.assertEqual(organization.name, 'General Hospital')
        self.assertEqual(organization.identifier, '1234567890')
        self.assertEqual(organization.organization_type, 'hospital')
        self.assertEqual(organization.address, '123 Medical Center Drive')
        self.assertEqual(organization.city, 'Springfield')
        self.assertEqual(organization.state, 'IL')
        self.assertEqual(organization.postal_code, '62701')
        self.assertEqual(organization.phone, '217-555-1000')
        self.assertEqual(organization.confidence, 0.96)
    
    def test_organization_model_minimal_required_data(self):
        """Test Organization model with only required fields."""
        organization = Organization(
            name='Community Clinic',
            confidence=0.88,
            source=SourceContext(
                text='Community Clinic',
                start_index=0,
                end_index=16
            )
        )
        
        # Verify required field
        self.assertEqual(organization.name, 'Community Clinic')
        
        # Verify optional fields default properly
        self.assertIsNone(organization.organization_id)
        self.assertIsNone(organization.identifier)
        self.assertIsNone(organization.organization_type)
        self.assertIsNone(organization.address)
        self.assertIsNone(organization.city)
        self.assertIsNone(organization.state)
        self.assertIsNone(organization.postal_code)
        self.assertIsNone(organization.phone)
    
    def test_organization_model_missing_required_field(self):
        """Test that missing name raises ValidationError."""
        with self.assertRaises(ValidationError) as context:
            Organization(
                # Missing required name
                organization_type='clinic',
                confidence=0.9,
                source=SourceContext(text='test', start_index=0, end_index=4)
            )
        
        self.assertIn('name', str(context.exception))
    
    def test_organization_model_invalid_confidence(self):
        """Test that confidence outside 0.0-1.0 range raises ValidationError."""
        with self.assertRaises(ValidationError):
            Organization(
                name='Test Hospital',
                confidence=-0.5,  # Invalid
                source=SourceContext(text='test', start_index=0, end_index=4)
            )
    
    def test_organization_serialization(self):
        """Test that Organization serializes to dict correctly."""
        organization = Organization(
            name='University Medical Center',
            organization_type='hospital',
            city='Chicago',
            state='IL',
            confidence=0.94,
            source=SourceContext(text='UMC Chicago', start_index=100, end_index=111)
        )
        
        org_dict = organization.model_dump()
        
        # Verify dict structure
        self.assertIsInstance(org_dict, dict)
        self.assertEqual(org_dict['name'], 'University Medical Center')
        self.assertEqual(org_dict['organization_type'], 'hospital')
        self.assertEqual(org_dict['city'], 'Chicago')
        self.assertEqual(org_dict['state'], 'IL')
    
    def test_organization_deserialization(self):
        """Test that Organization can be created from dict."""
        org_dict = {
            'name': 'Regional Lab Services',
            'identifier': '9876543210',
            'organization_type': 'lab',
            'address': '456 Lab Way',
            'city': 'Springfield',
            'postal_code': '62702',
            'phone': '217-555-2000',
            'confidence': 0.92,
            'source': {
                'text': 'Regional Lab Services',
                'start_index': 300,
                'end_index': 321
            }
        }
        
        organization = Organization(**org_dict)
        
        self.assertEqual(organization.name, 'Regional Lab Services')
        self.assertEqual(organization.organization_type, 'lab')
    
    def test_organization_in_structured_extraction(self):
        """Test Organization integration into StructuredMedicalExtraction."""
        extraction = StructuredMedicalExtraction(
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[],
            procedures=[],
            providers=[],
            encounters=[],
            service_requests=[],
            diagnostic_reports=[],
            allergies=[],
            care_plans=[],
            organizations=[
                Organization(
                    name='Memorial Hospital',
                    organization_type='hospital',
                    confidence=0.95,
                    source=SourceContext(text='Memorial Hospital', start_index=0, end_index=17)
                )
            ],
            extraction_timestamp='2024-10-29T12:00:00'
        )
        
        self.assertEqual(len(extraction.organizations), 1)
        self.assertEqual(extraction.organizations[0].name, 'Memorial Hospital')
    
    def test_confidence_average_includes_organizations(self):
        """Test that confidence_average calculation includes organizations."""
        extraction = StructuredMedicalExtraction(
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[],
            procedures=[],
            providers=[],
            encounters=[],
            service_requests=[],
            diagnostic_reports=[],
            allergies=[],
            care_plans=[],
            organizations=[
                Organization(
                    name='Org 1',
                    confidence=0.65,
                    source=SourceContext(text='test1', start_index=0, end_index=5)
                ),
                Organization(
                    name='Org 2',
                    confidence=0.95,
                    source=SourceContext(text='test2', start_index=6, end_index=11)
                )
            ],
            extraction_timestamp='2024-10-29T12:00:00'
        )
        
        # Confidence average should be (0.65 + 0.95) / 2 = 0.80
        self.assertEqual(extraction.confidence_average, 0.800)


if __name__ == '__main__':
    unittest.main()

