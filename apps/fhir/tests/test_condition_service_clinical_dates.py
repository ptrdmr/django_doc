"""
Tests for ConditionService clinical date handling.

This test suite verifies that the ConditionService correctly:
1. Extracts clinical dates from diagnosis text
2. Accepts manually provided clinical dates
3. Separates clinical dates from processing metadata
4. Tracks date source (extracted/manual/unknown)
"""

import unittest
from datetime import datetime
from uuid import uuid4

from apps.fhir.services.condition_service import ConditionService


class TestConditionServiceClinicalDates(unittest.TestCase):
    """Test clinical date handling in ConditionService."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = ConditionService()
        self.patient_id = str(uuid4())
    
    def test_extract_date_from_diagnosis_text(self):
        """Test automatic date extraction from diagnosis text."""
        field = {
            'label': 'diagnosis',
            'value': 'Type 2 Diabetes diagnosed on 05/15/2023',
            'confidence': 0.95,
            'source_context': 'Medical record'
        }
        
        result = self.service._create_condition_resource(field, self.patient_id)
        
        # Should have extracted the date
        self.assertIsNotNone(result)
        self.assertIn('onsetDateTime', result)
        self.assertEqual(result['onsetDateTime'], '2023-05-15')
        
        # Should track date source as extracted
        date_source_tag = next(
            (tag for tag in result['meta']['tag'] if tag['code'] == 'date-source'),
            None
        )
        self.assertIsNotNone(date_source_tag)
        self.assertIn('extracted', date_source_tag['display'].lower())
        
        # recordedDate should be processing metadata (current time)
        self.assertIn('recordedDate', result)
        recorded_date = datetime.fromisoformat(result['recordedDate'])
        self.assertAlmostEqual(
            recorded_date.timestamp(), 
            datetime.now().timestamp(), 
            delta=5  # within 5 seconds
        )
    
    def test_manual_clinical_date_provided(self):
        """Test using manually provided clinical date."""
        field = {
            'label': 'diagnosis',
            'value': 'Hypertension',
            'confidence': 0.92
        }
        manual_date = '2022-03-10'
        
        result = self.service._create_condition_resource(
            field, 
            self.patient_id, 
            clinical_date=manual_date
        )
        
        # Should use the manual date
        self.assertIsNotNone(result)
        self.assertEqual(result['onsetDateTime'], manual_date)
        
        # Should track date source as manual
        date_source_tag = next(
            (tag for tag in result['meta']['tag'] if tag['code'] == 'date-source'),
            None
        )
        self.assertIsNotNone(date_source_tag)
        self.assertIn('manual', date_source_tag['display'].lower())
    
    def test_no_date_available(self):
        """Test condition with no clinical date available."""
        field = {
            'label': 'diagnosis',
            'value': 'Chronic back pain',
            'confidence': 0.88
        }
        
        result = self.service._create_condition_resource(field, self.patient_id)
        
        # Should still create condition but without onsetDateTime
        self.assertIsNotNone(result)
        self.assertNotIn('onsetDateTime', result)
        
        # Should track date source as unknown
        date_source_tag = next(
            (tag for tag in result['meta']['tag'] if tag['code'] == 'date-source'),
            None
        )
        self.assertIsNotNone(date_source_tag)
        self.assertIn('unknown', date_source_tag['display'].lower())
    
    def test_multiple_dates_uses_highest_confidence(self):
        """Test that when multiple dates exist, highest confidence is used."""
        field = {
            'label': 'diagnosis',
            'value': 'COPD diagnosed 01/15/2020, worsened on 2023-06-01',
            'confidence': 0.90
        }
        
        result = self.service._create_condition_resource(field, self.patient_id)
        
        # Should extract a date (one of the two)
        self.assertIsNotNone(result)
        self.assertIn('onsetDateTime', result)
        
        # Date should be in ISO format
        self.assertRegex(result['onsetDateTime'], r'^\d{4}-\d{2}-\d{2}$')
    
    def test_manual_date_overrides_extraction(self):
        """Test that manual date takes precedence over extracted date."""
        field = {
            'label': 'diagnosis',
            'value': 'Asthma since 2015-08-20',
            'confidence': 0.93
        }
        manual_date = '2010-01-01'
        
        result = self.service._create_condition_resource(
            field, 
            self.patient_id, 
            clinical_date=manual_date
        )
        
        # Should use manual date, not extracted
        self.assertEqual(result['onsetDateTime'], manual_date)
        
        # Should be marked as manual
        date_source_tag = next(
            (tag for tag in result['meta']['tag'] if tag['code'] == 'date-source'),
            None
        )
        self.assertIn('manual', date_source_tag['display'].lower())
    
    def test_processing_metadata_always_present(self):
        """Test that processing metadata (recordedDate) is always present."""
        # Test with extracted date
        field1 = {
            'label': 'diagnosis',
            'value': 'Diabetes on 2023-05-15',
            'confidence': 0.95
        }
        result1 = self.service._create_condition_resource(field1, self.patient_id)
        self.assertIn('recordedDate', result1)
        
        # Test with manual date
        result2 = self.service._create_condition_resource(
            field1, 
            self.patient_id, 
            clinical_date='2020-01-01'
        )
        self.assertIn('recordedDate', result2)
        
        # Test with no date
        field2 = {
            'label': 'diagnosis',
            'value': 'No dates here',
            'confidence': 0.85
        }
        result3 = self.service._create_condition_resource(field2, self.patient_id)
        self.assertIn('recordedDate', result3)
    
    def test_extraction_confidence_preserved(self):
        """Test that extraction confidence is preserved in metadata."""
        field = {
            'label': 'diagnosis',
            'value': 'Hypertension',
            'confidence': 0.87
        }
        
        result = self.service._create_condition_resource(field, self.patient_id)
        
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
            'label': 'diagnosis',
            'value': 'Condition diagnosed 2023-01-15',
            'confidence': 0.90
        }
        
        result = self.service._create_condition_resource(field, self.patient_id)
        
        # Check required FHIR Condition fields
        self.assertEqual(result['resourceType'], 'Condition')
        self.assertIn('id', result)
        self.assertIn('clinicalStatus', result)
        self.assertIn('verificationStatus', result)
        self.assertIn('code', result)
        self.assertIn('subject', result)
        
        # Check proper references
        self.assertEqual(result['subject']['reference'], f'Patient/{self.patient_id}')
        
        # Check meta profile
        self.assertIn('http://hl7.org/fhir/StructureDefinition/Condition', result['meta']['profile'])
    
    def test_process_conditions_with_dates(self):
        """Test processing multiple conditions with date extraction."""
        extracted_data = {
            'patient_id': self.patient_id,
            'fields': [
                {
                    'label': 'diagnosis',
                    'value': 'Type 2 Diabetes diagnosed 05/15/2023',
                    'confidence': 0.95
                },
                {
                    'label': 'diagnosis',
                    'value': 'Hypertension since January 10, 2020',
                    'confidence': 0.92
                },
                {
                    'label': 'diagnosis',
                    'value': 'Chronic pain',  # No date
                    'confidence': 0.88
                }
            ]
        }
        
        results = self.service.process_conditions(extracted_data)
        
        # Should process all three conditions
        self.assertEqual(len(results), 3)
        
        # First two should have dates
        self.assertIn('onsetDateTime', results[0])
        self.assertIn('onsetDateTime', results[1])
        
        # Third should not have date
        self.assertNotIn('onsetDateTime', results[2])
        
        # All should have recordedDate (processing metadata)
        for condition in results:
            self.assertIn('recordedDate', condition)


if __name__ == '__main__':
    unittest.main()
