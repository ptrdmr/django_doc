"""
Tests for ObservationService clinical date handling.

This test suite verifies that the ObservationService correctly:
1. Extracts clinical dates from vital sign text
2. Accepts manually provided clinical dates
3. Separates clinical dates from processing metadata
4. Tracks date source (extracted/manual/unknown)
"""

import unittest
from datetime import datetime
from uuid import uuid4

from apps.fhir.services.observation_service import ObservationService


class TestObservationServiceClinicalDates(unittest.TestCase):
    """Test clinical date handling in ObservationService."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = ObservationService()
        self.patient_id = str(uuid4())
    
    def test_extract_date_from_vital_text(self):
        """Test automatic date extraction from vital sign text."""
        field = {
            'label': 'vital sign',
            'value': 'Blood pressure 120/80 mmHg on 05/15/2023',
            'confidence': 0.95,
            'source_context': 'Medical record'
        }
        
        result = self.service._create_observation_resource(field, self.patient_id)
        
        # Should have extracted the date
        self.assertIsNotNone(result)
        self.assertIn('effectiveDateTime', result)
        self.assertEqual(result['effectiveDateTime'], '2023-05-15')
        
        # Should track date source as extracted
        date_source_tag = next(
            (tag for tag in result['meta']['tag'] if tag['code'] == 'date-source'),
            None
        )
        self.assertIsNotNone(date_source_tag)
        self.assertIn('extracted', date_source_tag['display'].lower())
    
    def test_manual_clinical_date_provided(self):
        """Test using manually provided clinical date."""
        field = {
            'label': 'vital sign - heart rate',
            'value': '72 bpm',
            'confidence': 0.92
        }
        manual_date = '2022-03-10'
        
        result = self.service._create_observation_resource(
            field, 
            self.patient_id, 
            clinical_date=manual_date
        )
        
        # Should use the manual date
        self.assertIsNotNone(result)
        self.assertEqual(result['effectiveDateTime'], manual_date)
        
        # Should track date source as manual
        date_source_tag = next(
            (tag for tag in result['meta']['tag'] if tag['code'] == 'date-source'),
            None
        )
        self.assertIsNotNone(date_source_tag)
        self.assertIn('manual', date_source_tag['display'].lower())
    
    def test_no_date_available(self):
        """Test observation with no clinical date available."""
        field = {
            'label': 'vital sign - temperature',
            'value': 'Normal body temperature',
            'confidence': 0.88
        }
        
        result = self.service._create_observation_resource(field, self.patient_id)
        
        # Should still create observation but without effectiveDateTime
        self.assertIsNotNone(result)
        self.assertNotIn('effectiveDateTime', result)
        
        # Should track date source as unknown
        date_source_tag = next(
            (tag for tag in result['meta']['tag'] if tag['code'] == 'date-source'),
            None
        )
        self.assertIsNotNone(date_source_tag)
        self.assertIn('unknown', date_source_tag['display'].lower())
    
    def test_date_with_vital_value_parsing(self):
        """Test date extraction with complex vital sign values."""
        field = {
            'label': 'vital sign - blood pressure',
            'value': 'Systolic: 120 mmHg, Diastolic: 80 mmHg, measured on 2023-06-01',
            'confidence': 0.90
        }
        
        result = self.service._create_observation_resource(field, self.patient_id)
        
        # Should extract both date and value
        self.assertIsNotNone(result)
        self.assertIn('effectiveDateTime', result)
        self.assertEqual(result['effectiveDateTime'], '2023-06-01')
        
        # Should also parse the value
        self.assertTrue(
            'valueQuantity' in result or 'valueString' in result
        )
    
    def test_manual_date_overrides_extraction(self):
        """Test that manual date takes precedence over extracted date."""
        field = {
            'label': 'vital sign',
            'value': 'Weight 180 lbs recorded 2023-08-20',
            'confidence': 0.93
        }
        manual_date = '2023-07-01'
        
        result = self.service._create_observation_resource(
            field, 
            self.patient_id, 
            clinical_date=manual_date
        )
        
        # Should use manual date, not extracted
        self.assertEqual(result['effectiveDateTime'], manual_date)
        
        # Should be marked as manual
        date_source_tag = next(
            (tag for tag in result['meta']['tag'] if tag['code'] == 'date-source'),
            None
        )
        self.assertIn('manual', date_source_tag['display'].lower())
    
    def test_loinc_code_mapping_preserved(self):
        """Test that LOINC code mapping still works with date extraction."""
        field = {
            'label': 'vital sign - heart rate',
            'value': 'Pulse 72 bpm on 2023-05-15',
            'confidence': 0.95
        }
        
        result = self.service._create_observation_resource(field, self.patient_id)
        
        # Should have LOINC code for heart rate
        self.assertIn('coding', result['code'])
        self.assertEqual(result['code']['coding'][0]['code'], '8867-4')
        
        # Should also have date
        self.assertIn('effectiveDateTime', result)
    
    def test_value_parsing_with_dates(self):
        """Test that numeric value parsing works alongside date extraction."""
        field = {
            'label': 'vital sign - temperature',
            'value': 'Temperature 98.6 F measured on January 15, 2023',
            'confidence': 0.91
        }
        
        result = self.service._create_observation_resource(field, self.patient_id)
        
        # Should parse both value and date
        self.assertIn('valueQuantity', result)
        self.assertEqual(result['valueQuantity']['value'], 98.6)
        self.assertEqual(result['valueQuantity']['unit'], 'F')
        
        self.assertIn('effectiveDateTime', result)
        self.assertEqual(result['effectiveDateTime'], '2023-01-15')
    
    def test_extraction_confidence_preserved(self):
        """Test that extraction confidence is preserved in metadata."""
        field = {
            'label': 'vital sign',
            'value': 'BP 120/80',
            'confidence': 0.87
        }
        
        result = self.service._create_observation_resource(field, self.patient_id)
        
        # Should have extraction confidence tag
        extraction_tag = next(
            (tag for tag in result['meta']['tag'] if tag['code'] == 'extraction-confidence'),
            None
        )
        self.assertIsNotNone(extraction_tag)
        self.assertIn('0.87', extraction_tag['display'])
    
    def test_fhir_structure_compliance(self):
        """Test that resulting FHIR structure follows specification."""
        field = {
            'label': 'vital sign',
            'value': 'Heart rate 72 bpm on 2023-01-15',
            'confidence': 0.90
        }
        
        result = self.service._create_observation_resource(field, self.patient_id)
        
        # Check required FHIR Observation fields
        self.assertEqual(result['resourceType'], 'Observation')
        self.assertIn('id', result)
        self.assertIn('status', result)
        self.assertEqual(result['status'], 'final')
        self.assertIn('code', result)
        self.assertIn('subject', result)
        
        # Check proper references
        self.assertEqual(result['subject']['reference'], f'Patient/{self.patient_id}')
        
        # Check meta profile
        self.assertIn('http://hl7.org/fhir/StructureDefinition/Observation', result['meta']['profile'])
    
    def test_process_observations_with_dates(self):
        """Test processing multiple observations with date extraction."""
        extracted_data = {
            'patient_id': self.patient_id,
            'fields': [
                {
                    'label': 'vital sign - blood pressure',
                    'value': 'BP 120/80 mmHg on 05/15/2023',
                    'confidence': 0.95
                },
                {
                    'label': 'vital sign - temperature',
                    'value': 'Temp 98.6 F measured January 10, 2023',
                    'confidence': 0.92
                },
                {
                    'label': 'vital sign - heart rate',
                    'value': '72 bpm',  # No date
                    'confidence': 0.88
                }
            ]
        }
        
        results = self.service.process_observations(extracted_data)
        
        # Should process all three observations
        self.assertEqual(len(results), 3)
        
        # First two should have dates
        self.assertIn('effectiveDateTime', results[0])
        self.assertIn('effectiveDateTime', results[1])
        
        # Third should not have date
        self.assertNotIn('effectiveDateTime', results[2])
        
        # All should have proper FHIR structure
        for observation in results:
            self.assertEqual(observation['resourceType'], 'Observation')
            self.assertIn('meta', observation)
    
    def test_multiple_dates_uses_highest_confidence(self):
        """Test that when multiple dates exist, highest confidence is used."""
        field = {
            'label': 'vital sign',
            'value': 'Initial reading 01/15/2020, follow-up on 2023-06-01',
            'confidence': 0.90
        }
        
        result = self.service._create_observation_resource(field, self.patient_id)
        
        # Should extract a date (one of the two)
        self.assertIsNotNone(result)
        self.assertIn('effectiveDateTime', result)
        
        # Date should be in ISO format
        self.assertRegex(result['effectiveDateTime'], r'^\d{4}-\d{2}-\d{2}$')


if __name__ == '__main__':
    unittest.main()
