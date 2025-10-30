"""
Tests for AllergyIntolerance Pydantic model (Task 40.13)

Verifies that the AllergyIntolerance Pydantic model:
1. Validates correctly with valid data
2. Rejects invalid data appropriately
3. Serializes/deserializes properly
4. Integrates into StructuredMedicalExtraction
"""

import unittest
from pydantic import ValidationError
from apps.documents.services.ai_extraction import AllergyIntolerance, StructuredMedicalExtraction, SourceContext


class AllergyIntolerancePydanticModelTests(unittest.TestCase):
    """Test AllergyIntolerance Pydantic model validation and integration."""
    
    def test_allergy_model_valid_full_data(self):
        """Test AllergyIntolerance model with all fields populated."""
        allergy = AllergyIntolerance(
            allergy_id='allergy-001',
            allergen='Penicillin',
            reaction='Anaphylaxis',
            severity='severe',
            onset_date='2015-06-10',
            status='active',
            verification_status='confirmed',
            confidence=0.98,
            source=SourceContext(
                text='Patient has severe penicillin allergy with anaphylaxis',
                start_index=150,
                end_index=203
            )
        )
        
        # Verify all fields set correctly
        self.assertEqual(allergy.allergy_id, 'allergy-001')
        self.assertEqual(allergy.allergen, 'Penicillin')
        self.assertEqual(allergy.reaction, 'Anaphylaxis')
        self.assertEqual(allergy.severity, 'severe')
        self.assertEqual(allergy.onset_date, '2015-06-10')
        self.assertEqual(allergy.status, 'active')
        self.assertEqual(allergy.verification_status, 'confirmed')
        self.assertEqual(allergy.confidence, 0.98)
    
    def test_allergy_model_minimal_required_data(self):
        """Test AllergyIntolerance model with only required fields."""
        allergy = AllergyIntolerance(
            allergen='Shellfish',
            confidence=0.85,
            source=SourceContext(
                text='Shellfish allergy',
                start_index=0,
                end_index=16
            )
        )
        
        # Verify required field
        self.assertEqual(allergy.allergen, 'Shellfish')
        
        # Verify optional fields default properly
        self.assertIsNone(allergy.allergy_id)
        self.assertIsNone(allergy.reaction)
        self.assertIsNone(allergy.severity)
        self.assertIsNone(allergy.onset_date)
        self.assertIsNone(allergy.status)
        self.assertIsNone(allergy.verification_status)
    
    def test_allergy_model_missing_required_field(self):
        """Test that missing allergen raises ValidationError."""
        with self.assertRaises(ValidationError) as context:
            AllergyIntolerance(
                # Missing required allergen
                reaction='Rash',
                confidence=0.9,
                source=SourceContext(text='test', start_index=0, end_index=4)
            )
        
        # Verify error message mentions the missing field
        self.assertIn('allergen', str(context.exception))
    
    def test_allergy_model_invalid_confidence(self):
        """Test that confidence outside 0.0-1.0 range raises ValidationError."""
        with self.assertRaises(ValidationError):
            AllergyIntolerance(
                allergen='Peanuts',
                confidence=1.5,  # Invalid: > 1.0
                source=SourceContext(text='test', start_index=0, end_index=4)
            )
    
    def test_allergy_serialization(self):
        """Test that AllergyIntolerance serializes to dict correctly."""
        allergy = AllergyIntolerance(
            allergen='Latex',
            reaction='Contact dermatitis',
            severity='moderate',
            status='active',
            confidence=0.92,
            source=SourceContext(text='latex allergy', start_index=50, end_index=63)
        )
        
        allergy_dict = allergy.model_dump()
        
        # Verify dict structure
        self.assertIsInstance(allergy_dict, dict)
        self.assertEqual(allergy_dict['allergen'], 'Latex')
        self.assertEqual(allergy_dict['reaction'], 'Contact dermatitis')
        self.assertEqual(allergy_dict['severity'], 'moderate')
        self.assertEqual(allergy_dict['confidence'], 0.92)
    
    def test_allergy_deserialization(self):
        """Test that AllergyIntolerance can be created from dict."""
        allergy_dict = {
            'allergen': 'Bee venom',
            'reaction': 'Anaphylaxis',
            'severity': 'life-threatening',
            'onset_date': '2018-07-15',
            'status': 'active',
            'verification_status': 'confirmed',
            'confidence': 0.96,
            'source': {
                'text': 'Bee sting allergy confirmed',
                'start_index': 100,
                'end_index': 127
            }
        }
        
        allergy = AllergyIntolerance(**allergy_dict)
        
        # Verify deserialization worked
        self.assertEqual(allergy.allergen, 'Bee venom')
        self.assertEqual(allergy.severity, 'life-threatening')
    
    def test_allergy_in_structured_extraction(self):
        """Test AllergyIntolerance integration into StructuredMedicalExtraction."""
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
            allergies=[
                AllergyIntolerance(
                    allergen='Sulfa drugs',
                    reaction='Rash',
                    status='active',
                    confidence=0.94,
                    source=SourceContext(text='sulfa allergy', start_index=0, end_index=13)
                )
            ],
            extraction_timestamp='2024-10-29T12:00:00',
            document_type='allergy_list'
        )
        
        # Verify allergy in extraction
        self.assertEqual(len(extraction.allergies), 1)
        self.assertEqual(extraction.allergies[0].allergen, 'Sulfa drugs')
        self.assertEqual(extraction.allergies[0].reaction, 'Rash')
    
    def test_confidence_average_includes_allergies(self):
        """Test that confidence_average calculation includes allergies."""
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
            allergies=[
                AllergyIntolerance(
                    allergen='Eggs',
                    confidence=0.75,
                    source=SourceContext(text='test1', start_index=0, end_index=5)
                ),
                AllergyIntolerance(
                    allergen='Milk',
                    confidence=0.85,
                    source=SourceContext(text='test2', start_index=6, end_index=11)
                )
            ],
            extraction_timestamp='2024-10-29T12:00:00'
        )
        
        # Confidence average should be (0.75 + 0.85) / 2 = 0.80
        self.assertEqual(extraction.confidence_average, 0.800)


if __name__ == '__main__':
    unittest.main()

