"""
Tests for Encounter Pydantic model (Task 40.9)

Verifies that the Encounter Pydantic model:
1. Validates correctly with valid data
2. Rejects invalid data appropriately
3. Serializes/deserializes properly
4. Integrates into StructuredMedicalExtraction
"""

import unittest
from pydantic import ValidationError
from apps.documents.services.ai_extraction import Encounter, StructuredMedicalExtraction, SourceContext


class EncounterPydanticModelTests(unittest.TestCase):
    """Test Encounter Pydantic model validation and integration."""
    
    def test_encounter_model_valid_full_data(self):
        """Test Encounter model with all fields populated."""
        encounter = Encounter(
            encounter_id='enc-001',
            encounter_type='office visit',
            encounter_date='2024-10-20 09:00:00',
            encounter_end_date='2024-10-20 09:45:00',
            location='Main Street Clinic',
            reason='Annual physical examination',
            participants=['Dr. Sarah Johnson', 'Nurse Mary Smith'],
            status='finished',
            confidence=0.96,
            source=SourceContext(
                text='Patient seen for annual physical at Main Street Clinic',
                start_index=50,
                end_index=105
            )
        )
        
        # Verify all fields set correctly
        self.assertEqual(encounter.encounter_id, 'enc-001')
        self.assertEqual(encounter.encounter_type, 'office visit')
        self.assertEqual(encounter.encounter_date, '2024-10-20 09:00:00')
        self.assertEqual(encounter.encounter_end_date, '2024-10-20 09:45:00')
        self.assertEqual(encounter.location, 'Main Street Clinic')
        self.assertEqual(encounter.reason, 'Annual physical examination')
        self.assertEqual(len(encounter.participants), 2)
        self.assertIn('Dr. Sarah Johnson', encounter.participants)
        self.assertEqual(encounter.status, 'finished')
        self.assertEqual(encounter.confidence, 0.96)
    
    def test_encounter_model_minimal_required_data(self):
        """Test Encounter model with only required fields."""
        encounter = Encounter(
            encounter_type='emergency',
            confidence=0.85,
            source=SourceContext(
                text='ER visit',
                start_index=0,
                end_index=8
            )
        )
        
        # Verify required field
        self.assertEqual(encounter.encounter_type, 'emergency')
        
        # Verify optional fields default properly
        self.assertIsNone(encounter.encounter_id)
        self.assertIsNone(encounter.encounter_date)
        self.assertIsNone(encounter.encounter_end_date)
        self.assertIsNone(encounter.location)
        self.assertIsNone(encounter.reason)
        self.assertEqual(encounter.participants, [])
        self.assertIsNone(encounter.status)
    
    def test_encounter_model_missing_required_field(self):
        """Test that missing encounter_type raises ValidationError."""
        with self.assertRaises(ValidationError) as context:
            Encounter(
                # Missing required encounter_type
                encounter_date='2024-10-20',
                confidence=0.9,
                source=SourceContext(text='test', start_index=0, end_index=4)
            )
        
        # Verify error message mentions the missing field
        self.assertIn('encounter_type', str(context.exception))
    
    def test_encounter_model_invalid_confidence(self):
        """Test that confidence outside 0.0-1.0 range raises ValidationError."""
        with self.assertRaises(ValidationError):
            Encounter(
                encounter_type='office visit',
                confidence=1.5,  # Invalid: > 1.0
                source=SourceContext(text='test', start_index=0, end_index=4)
            )
        
        with self.assertRaises(ValidationError):
            Encounter(
                encounter_type='office visit',
                confidence=-0.1,  # Invalid: < 0.0
                source=SourceContext(text='test', start_index=0, end_index=4)
            )
    
    def test_encounter_serialization(self):
        """Test that Encounter serializes to dict correctly."""
        encounter = Encounter(
            encounter_type='telehealth',
            encounter_date='2024-10-15',
            location='Virtual',
            participants=['Dr. Chen'],
            confidence=0.92,
            source=SourceContext(text='virtual visit', start_index=10, end_index=23)
        )
        
        encounter_dict = encounter.model_dump()
        
        # Verify dict structure
        self.assertIsInstance(encounter_dict, dict)
        self.assertEqual(encounter_dict['encounter_type'], 'telehealth')
        self.assertEqual(encounter_dict['encounter_date'], '2024-10-15')
        self.assertEqual(encounter_dict['location'], 'Virtual')
        self.assertIn('Dr. Chen', encounter_dict['participants'])
        self.assertEqual(encounter_dict['confidence'], 0.92)
    
    def test_encounter_deserialization(self):
        """Test that Encounter can be created from dict."""
        encounter_dict = {
            'encounter_type': 'inpatient',
            'encounter_date': '2024-09-01',
            'encounter_end_date': '2024-09-05',
            'location': 'General Hospital',
            'reason': 'Pneumonia treatment',
            'participants': ['Dr. Smith', 'Dr. Jones'],
            'status': 'finished',
            'confidence': 0.94,
            'source': {
                'text': 'Admitted for pneumonia',
                'start_index': 100,
                'end_index': 122
            }
        }
        
        encounter = Encounter(**encounter_dict)
        
        # Verify deserialization worked
        self.assertEqual(encounter.encounter_type, 'inpatient')
        self.assertEqual(encounter.encounter_date, '2024-09-01')
        self.assertEqual(len(encounter.participants), 2)
    
    def test_encounter_in_structured_extraction(self):
        """Test Encounter integration into StructuredMedicalExtraction."""
        extraction = StructuredMedicalExtraction(
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[],
            procedures=[],
            providers=[],
            encounters=[
                Encounter(
                    encounter_type='office visit',
                    encounter_date='2024-10-20',
                    location='Primary Care Clinic',
                    confidence=0.95,
                    source=SourceContext(text='office visit', start_index=0, end_index=12)
                )
            ],
            extraction_timestamp='2024-10-29T12:00:00',
            document_type='clinical_note'
        )
        
        # Verify encounter in extraction
        self.assertEqual(len(extraction.encounters), 1)
        self.assertEqual(extraction.encounters[0].encounter_type, 'office visit')
        self.assertEqual(extraction.encounters[0].location, 'Primary Care Clinic')
    
    def test_confidence_average_includes_encounters(self):
        """Test that confidence_average calculation includes encounters."""
        extraction = StructuredMedicalExtraction(
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[],
            procedures=[],
            providers=[],
            encounters=[
                Encounter(
                    encounter_type='office visit',
                    confidence=0.90,
                    source=SourceContext(text='test', start_index=0, end_index=4)
                ),
                Encounter(
                    encounter_type='emergency',
                    confidence=0.80,
                    source=SourceContext(text='test', start_index=5, end_index=9)
                )
            ],
            extraction_timestamp='2024-10-29T12:00:00'
        )
        
        # Confidence average should be (0.90 + 0.80) / 2 = 0.85
        self.assertEqual(extraction.confidence_average, 0.850)


if __name__ == '__main__':
    unittest.main()

