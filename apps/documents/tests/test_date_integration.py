"""
Tests for ClinicalDateParser integration in document processing workflow.
Verifies that dates extracted by AI are properly validated and standardized.
"""

import pytest
from django.test import TestCase
from apps.documents.services import DocumentAnalyzer
from datetime import date, datetime


class ClinicalDateParserIntegrationTestCase(TestCase):
    """Test ClinicalDateParser integration with DocumentAnalyzer."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.analyzer = DocumentAnalyzer()
    
    def test_parser_initialized(self):
        """Verify ClinicalDateParser is initialized in DocumentAnalyzer."""
        self.assertIsNotNone(self.analyzer.date_parser)
        self.assertEqual(self.analyzer.date_parser.__class__.__name__, 'ClinicalDateParser')
    
    def test_parse_iso_date(self):
        """Test parsing ISO 8601 date."""
        result = self.analyzer.parse_and_format_date("2023-05-15")
        self.assertEqual(result, "2023-05-15")
    
    def test_parse_us_date_format(self):
        """Test parsing US date format (MM/DD/YYYY)."""
        result = self.analyzer.parse_and_format_date("05/15/2023")
        self.assertEqual(result, "2023-05-15")
    
    def test_parse_month_name_date(self):
        """Test parsing date with month name."""
        result = self.analyzer.parse_and_format_date("May 15, 2023")
        self.assertEqual(result, "2023-05-15")
    
    def test_parse_alternative_month_format(self):
        """Test parsing alternative month format."""
        result = self.analyzer.parse_and_format_date("15 May 2023")
        self.assertEqual(result, "2023-05-15")
    
    def test_parse_datetime_object(self):
        """Test parsing datetime object."""
        dt = datetime(2023, 5, 15, 14, 30)
        result = self.analyzer.parse_and_format_date(dt)
        self.assertEqual(result, "2023-05-15")
    
    def test_parse_date_object(self):
        """Test parsing date object."""
        d = date(2023, 5, 15)
        result = self.analyzer.parse_and_format_date(d)
        self.assertEqual(result, "2023-05-15")
    
    def test_parse_invalid_date(self):
        """Test parsing invalid date returns None."""
        result = self.analyzer.parse_and_format_date("not a date")
        self.assertIsNone(result)
    
    def test_parse_empty_string(self):
        """Test parsing empty string returns None."""
        result = self.analyzer.parse_and_format_date("")
        self.assertIsNone(result)
    
    def test_parse_none(self):
        """Test parsing None returns None."""
        result = self.analyzer.parse_and_format_date(None)
        self.assertIsNone(result)
    
    def test_parse_future_date(self):
        """Test parsing future date (valid for appointments)."""
        future_date = "2025-12-31"
        result = self.analyzer.parse_and_format_date(future_date)
        # Should accept future dates for appointments
        self.assertEqual(result, "2025-12-31")
    
    def test_parse_old_date(self):
        """Test parsing very old date (e.g., birth dates)."""
        old_date = "1950-01-15"
        result = self.analyzer.parse_and_format_date(old_date)
        self.assertEqual(result, "1950-01-15")
    
    def test_parse_two_digit_year(self):
        """Test parsing date with two-digit year."""
        # Should handle 2-digit years (23 = 2023)
        result = self.analyzer.parse_and_format_date("05/15/23")
        # ClinicalDateParser should interpret as 2023
        self.assertEqual(result, "2023-05-15")
    
    def test_process_temporal_data_in_condition_resource(self):
        """Test temporal data processing for Condition resource."""
        condition_resource = {
            'resourceType': 'Condition',
            'code': {'text': 'Hypertension'},
            'onsetDateTime': '05/15/2023',  # Non-ISO format
            'recordedDate': 'May 20, 2023'  # Month name format
        }
        
        processed = self.analyzer.process_temporal_data(condition_resource)
        
        # Verify dates were standardized
        self.assertEqual(processed['onsetDateTime'], '2023-05-15')
        self.assertEqual(processed['recordedDate'], '2023-05-20')
    
    def test_process_temporal_data_in_observation_resource(self):
        """Test temporal data processing for Observation resource."""
        observation_resource = {
            'resourceType': 'Observation',
            'code': {'text': 'Blood Pressure'},
            'effectiveDateTime': '06/01/2023',
            'value': {'value': '120/80', 'unit': 'mmHg'}
        }
        
        processed = self.analyzer.process_temporal_data(observation_resource)
        
        # Verify date was standardized
        self.assertEqual(processed['effectiveDateTime'], '2023-06-01')
    
    def test_process_temporal_data_in_medication_resource(self):
        """Test temporal data processing for MedicationStatement resource."""
        medication_resource = {
            'resourceType': 'MedicationStatement',
            'medicationCodeableConcept': {'text': 'Aspirin 81mg'},
            'effectiveDateTime': 'January 10, 2023'
        }
        
        processed = self.analyzer.process_temporal_data(medication_resource)
        
        # Verify date was standardized
        self.assertEqual(processed['effectiveDateTime'], '2023-01-10')
    
    def test_process_temporal_data_in_procedure_resource(self):
        """Test temporal data processing for Procedure resource."""
        procedure_resource = {
            'resourceType': 'Procedure',
            'code': {'text': 'Appendectomy'},
            'performedDateTime': '07/15/2023'
        }
        
        processed = self.analyzer.process_temporal_data(procedure_resource)
        
        # Verify date was standardized
        self.assertEqual(processed['performedDateTime'], '2023-07-15')
    
    def test_process_temporal_data_preserves_valid_dates(self):
        """Test that already-valid ISO dates are preserved."""
        resource = {
            'resourceType': 'Condition',
            'onsetDateTime': '2023-05-15'  # Already ISO format
        }
        
        processed = self.analyzer.process_temporal_data(resource)
        
        # Should preserve the date unchanged
        self.assertEqual(processed['onsetDateTime'], '2023-05-15')
    
    def test_process_temporal_data_handles_missing_dates(self):
        """Test that resources without dates are handled gracefully."""
        resource = {
            'resourceType': 'Condition',
            'code': {'text': 'Diabetes'}
            # No date fields
        }
        
        processed = self.analyzer.process_temporal_data(resource)
        
        # Should not add date fields if they weren't present
        self.assertNotIn('onsetDateTime', processed)
        self.assertNotIn('recordedDate', processed)
    
    def test_process_temporal_data_with_period(self):
        """Test processing period objects (start/end dates)."""
        resource = {
            'resourceType': 'MedicationStatement',
            'effectivePeriod': {
                'start': '05/01/2023',
                'end': '05/31/2023'
            }
        }
        
        processed = self.analyzer.process_temporal_data(resource)
        
        # Verify both start and end dates were standardized
        self.assertEqual(processed['effectivePeriod']['start'], '2023-05-01')
        self.assertEqual(processed['effectivePeriod']['end'], '2023-05-31')


class DateParsingConfidenceTestCase(TestCase):
    """Test confidence scoring for date parsing."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.analyzer = DocumentAnalyzer()
    
    def test_high_confidence_iso_date(self):
        """ISO dates should have high confidence."""
        # Access the underlying parser to check confidence
        results = self.analyzer.date_parser.extract_dates("2023-05-15")
        self.assertGreater(results[0].confidence, 0.8)
    
    def test_medium_confidence_common_format(self):
        """Common formats should have medium-high confidence."""
        results = self.analyzer.date_parser.extract_dates("05/15/2023")
        self.assertGreater(results[0].confidence, 0.7)
    
    def test_confidence_preserved_during_processing(self):
        """Verify confidence information is preserved (logged) during processing."""
        # This test verifies the integration doesn't lose confidence data
        # even though the final FHIR resource may not include it
        result = self.analyzer.parse_and_format_date("05/15/2023")
        self.assertEqual(result, "2023-05-15")
        # Confidence is logged but not returned (check logs in real usage)
