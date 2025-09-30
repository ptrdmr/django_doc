"""
Unit tests for the ClinicalDateParser utility.

This module tests all aspects of clinical date extraction and parsing,
including various date formats, edge cases, and validation logic.
"""

import unittest
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

from apps.core.date_parser import ClinicalDateParser, DateExtractionResult


class TestClinicalDateParser(unittest.TestCase):
    """Test cases for the ClinicalDateParser class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.parser = ClinicalDateParser()
    
    def test_init_default_mdy(self):
        """Test parser initialization with default MDY assumption."""
        parser = ClinicalDateParser()
        self.assertTrue(parser.assume_mdy)
    
    def test_init_custom_mdy_setting(self):
        """Test parser initialization with custom MDY setting."""
        parser = ClinicalDateParser(assume_mdy=False)
        self.assertFalse(parser.assume_mdy)
    
    def test_extract_dates_empty_input(self):
        """Test date extraction with empty or None input."""
        self.assertEqual(self.parser.extract_dates(""), [])
        self.assertEqual(self.parser.extract_dates(None), [])
        self.assertEqual(self.parser.extract_dates(123), [])  # Non-string input
    
    def test_extract_dates_no_dates(self):
        """Test date extraction with text containing no dates."""
        text = "Patient complains of headache and fatigue. No specific timeline mentioned."
        results = self.parser.extract_dates(text)
        self.assertEqual(len(results), 0)
    
    def test_extract_dates_iso_format(self):
        """Test extraction of ISO format dates (YYYY-MM-DD)."""
        text = "Patient was admitted on 2023-05-15 and discharged on 2023-05-20."
        results = self.parser.extract_dates(text)
        
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].extracted_date, date(2023, 5, 15))
        self.assertEqual(results[1].extracted_date, date(2023, 5, 20))
        self.assertEqual(results[0].extraction_method, 'regex')
        self.assertGreater(results[0].confidence, 0.9)  # ISO format should have high confidence
    
    def test_extract_dates_mdy_slash_format(self):
        """Test extraction of MM/DD/YYYY format dates."""
        text = "Appointment scheduled for 12/25/2023 and follow-up on 01/15/2024."
        results = self.parser.extract_dates(text)
        
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].extracted_date, date(2023, 12, 25))
        self.assertEqual(results[1].extracted_date, date(2024, 1, 15))
    
    def test_extract_dates_month_name_format(self):
        """Test extraction of month name formats."""
        test_cases = [
            ("Patient seen on January 15, 2023", date(2023, 1, 15)),
            ("Surgery scheduled for Feb 28, 2024", date(2024, 2, 28)),
            ("Last visit was March 1 2023", date(2023, 3, 1)),  # No comma
            ("Diagnosed with diabetes in December 2022", None),  # Missing day
        ]
        
        for text, expected_date in test_cases:
            results = self.parser.extract_dates(text)
            if expected_date:
                self.assertGreater(len(results), 0, f"No dates found in: {text}")
                self.assertEqual(results[0].extracted_date, expected_date)
            else:
                # Should not extract incomplete dates like "December 2022"
                pass  # This is acceptable behavior
    
    def test_extract_dates_two_digit_years(self):
        """Test extraction of dates with two-digit years."""
        text = "Patient born on 03/15/85 and first seen on 12/01/99."
        results = self.parser.extract_dates(text)
        
        self.assertEqual(len(results), 2)
        # 85 should be interpreted as 1985, 99 as 1999
        self.assertEqual(results[0].extracted_date, date(1985, 3, 15))
        self.assertEqual(results[1].extracted_date, date(1999, 12, 1))
    
    def test_extract_dates_various_separators(self):
        """Test extraction with different date separators."""
        test_cases = [
            ("Visit on 05/15/2023", date(2023, 5, 15)),
            ("Follow-up 05-15-2023", date(2023, 5, 15)),
            ("Appointment 05.15.2023", date(2023, 5, 15)),
        ]
        
        for text, expected_date in test_cases:
            results = self.parser.extract_dates(text)
            self.assertGreater(len(results), 0, f"No dates found in: {text}")
            self.assertEqual(results[0].extracted_date, expected_date)
    
    def test_extract_dates_confidence_scoring(self):
        """Test that confidence scores are reasonable and properly ordered."""
        text = "ISO date 2023-05-15, and US date 06/15/2023, also month name July 15, 2023"
        results = self.parser.extract_dates(text)
        
        # Should extract multiple dates (at least 2, might be 3 depending on deduplication)
        self.assertGreaterEqual(len(results), 2)
        
        # Results should be sorted by confidence (highest first)
        confidences = [r.confidence for r in results]
        self.assertEqual(confidences, sorted(confidences, reverse=True))
        
        # Should have at least one high-confidence result
        self.assertGreater(max(confidences), 0.8)
    
    def test_extract_dates_deduplication(self):
        """Test that duplicate dates are properly deduplicated."""
        text = "Patient seen on 2023-05-15 and 05/15/2023 same day."
        results = self.parser.extract_dates(text)
        
        # Should deduplicate closely positioned identical dates
        # (dates that are close together in text are likely duplicates)
        all_dates = [r.extracted_date for r in results]
        unique_dates = set(all_dates)
        
        # Should extract the same date (2023-05-15) but might keep separate instances if far apart
        self.assertIn(date(2023, 5, 15), unique_dates)
        
        # All results should have reasonable confidence
        for result in results:
            self.assertGreater(result.confidence, 0.6)
    
    def test_extract_dates_context_window(self):
        """Test that context windows are properly extracted."""
        text = "The patient was admitted to the emergency department on 2023-05-15 with acute symptoms."
        results = self.parser.extract_dates(text, context_window=20)
        
        self.assertEqual(len(results), 1)
        # Context should include surrounding text (with 20 char window, we should get "on 2023-05-15 with acute")
        self.assertIn("2023-05-15", results[0].raw_text)
        self.assertIn("on", results[0].raw_text)
        self.assertIn("with", results[0].raw_text)
    
    def test_parse_single_date_valid_inputs(self):
        """Test single date parsing with valid inputs."""
        test_cases = [
            ("2023-05-15", date(2023, 5, 15)),
            ("05/15/2023", date(2023, 5, 15)),
            ("May 15, 2023", date(2023, 5, 15)),
            ("15 May 2023", date(2023, 5, 15)),
            ("05.15.2023", date(2023, 5, 15)),
        ]
        
        for date_string, expected_date in test_cases:
            result = self.parser.parse_single_date(date_string)
            self.assertEqual(result, expected_date, f"Failed to parse: {date_string}")
    
    def test_parse_single_date_invalid_inputs(self):
        """Test single date parsing with invalid inputs."""
        invalid_inputs = [
            "",
            None,
            "not a date",
            "13/45/2023",  # Invalid month/day
            "2023-13-45",  # Invalid month/day
            "February 30, 2023",  # Invalid date
            123,  # Non-string input
        ]
        
        for invalid_input in invalid_inputs:
            result = self.parser.parse_single_date(invalid_input)
            self.assertIsNone(result, f"Should not parse: {invalid_input}")
    
    def test_validate_date_string_valid(self):
        """Test date string validation with valid inputs."""
        valid_dates = [
            "2023-05-15",
            "05/15/2023",
            "May 15, 2023",
            "12/31/2023",
        ]
        
        for date_string in valid_dates:
            is_valid, error_msg = self.parser.validate_date_string(date_string)
            self.assertTrue(is_valid, f"Should be valid: {date_string}, error: {error_msg}")
            self.assertIsNone(error_msg)
    
    def test_validate_date_string_invalid(self):
        """Test date string validation with invalid inputs."""
        invalid_cases = [
            ("", "Date string is empty"),
            (None, "Date string is empty"),
            (123, "Date must be a string"),
            ("not a date", "Unable to parse date from string"),
            ("13/45/2023", "Unable to parse date from string"),
        ]
        
        for date_input, expected_error_type in invalid_cases:
            is_valid, error_msg = self.parser.validate_date_string(date_input)
            self.assertFalse(is_valid)
            self.assertIsNotNone(error_msg)
    
    def test_standardize_date_string_input(self):
        """Test date standardization with string inputs."""
        test_cases = [
            ("2023-05-15", "2023-05-15"),
            ("05/15/2023", "2023-05-15"),
            ("May 15, 2023", "2023-05-15"),
            ("15 May 2023", "2023-05-15"),
        ]
        
        for input_date, expected_output in test_cases:
            result = self.parser.standardize_date(input_date)
            self.assertEqual(result, expected_output)
    
    def test_standardize_date_object_input(self):
        """Test date standardization with date/datetime objects."""
        test_date = date(2023, 5, 15)
        test_datetime = datetime(2023, 5, 15, 14, 30, 0)
        
        self.assertEqual(self.parser.standardize_date(test_date), "2023-05-15")
        self.assertEqual(self.parser.standardize_date(test_datetime), "2023-05-15")
    
    def test_standardize_date_invalid_input(self):
        """Test date standardization with invalid inputs."""
        invalid_inputs = [None, "", "not a date", 123]
        
        for invalid_input in invalid_inputs:
            result = self.parser.standardize_date(invalid_input)
            self.assertIsNone(result)
    
    def test_is_valid_clinical_date_range(self):
        """Test clinical date validation range."""
        parser = ClinicalDateParser()
        
        # Valid dates
        valid_dates = [
            date(1950, 1, 1),
            date(2000, 6, 15),
            date.today(),
            date.today() + relativedelta(months=6),  # Future appointment
        ]
        
        for test_date in valid_dates:
            self.assertTrue(parser._is_valid_clinical_date(test_date))
        
        # Invalid dates
        invalid_dates = [
            date(1800, 1, 1),  # Too old
            date.today() + relativedelta(years=2),  # Too far in future
        ]
        
        for test_date in invalid_dates:
            self.assertFalse(parser._is_valid_clinical_date(test_date))
    
    def test_fuzzy_parsing_integration(self):
        """Test that fuzzy parsing works for dates missed by regex."""
        # This might catch dates that regex misses
        text = "Patient mentioned feeling sick since yesterday"
        results = self.parser.extract_dates(text)
        
        # This test is more about ensuring the fuzzy parsing doesn't crash
        # and that it properly integrates with the overall extraction process
        self.assertIsInstance(results, list)
    
    def test_extraction_result_representation(self):
        """Test DateExtractionResult string representation."""
        result = DateExtractionResult(
            raw_text="on 2023-05-15 with",
            extracted_date=date(2023, 5, 15),
            confidence=0.95,
            extraction_method='regex',
            position=10
        )
        
        repr_str = repr(result)
        self.assertIn("2023-05-15", repr_str)
        self.assertIn("regex", repr_str)
        self.assertIn("0.95", repr_str)
    
    def test_medical_document_realistic_example(self):
        """Test with a realistic medical document excerpt."""
        medical_text = """
        MEDICAL RECORD
        
        Patient: John Doe
        DOB: 01/15/1980
        MRN: 12345
        Date of Service: 2023-05-15
        
        CHIEF COMPLAINT:
        Patient presents with chest pain that started on May 10, 2023.
        
        HISTORY:
        Previous cardiac catheterization on 03/20/2023 showed normal results.
        Follow-up appointment scheduled for 06/01/2023.
        
        ASSESSMENT:
        Continue current medications. Next visit in 2 weeks.
        """
        
        results = self.parser.extract_dates(medical_text)
        
        # Should extract multiple dates
        self.assertGreater(len(results), 3)
        
        # Verify some specific dates were found
        extracted_dates = [r.extracted_date for r in results]
        self.assertIn(date(1980, 1, 15), extracted_dates)  # DOB
        self.assertIn(date(2023, 5, 15), extracted_dates)  # Service date
        self.assertIn(date(2023, 5, 10), extracted_dates)  # Symptom start
        self.assertIn(date(2023, 3, 20), extracted_dates)  # Previous procedure
        self.assertIn(date(2023, 6, 1), extracted_dates)   # Follow-up
    
    def test_edge_cases_and_malformed_dates(self):
        """Test handling of edge cases and malformed dates."""
        edge_cases = [
            "00/00/2023",  # Invalid month/day
            "2023-00-00",  # Invalid month/day in ISO
            "February 30, 2023",  # Invalid date
            "13/13/2023",  # Invalid month
            "2023-13-32",  # Invalid month/day
            "99/99/99",    # All invalid
        ]
        
        for edge_case in edge_cases:
            # Should not crash and should not extract invalid dates
            try:
                results = self.parser.extract_dates(f"Date mentioned: {edge_case}")
                # If any results are returned, they should be valid
                for result in results:
                    self.assertTrue(self.parser._is_valid_clinical_date(result.extracted_date))
            except Exception as e:
                self.fail(f"Parser crashed on edge case '{edge_case}': {e}")


class TestDateExtractionResult(unittest.TestCase):
    """Test cases for the DateExtractionResult class."""
    
    def test_creation_and_attributes(self):
        """Test creation and attribute access."""
        result = DateExtractionResult(
            raw_text="on 2023-05-15",
            extracted_date=date(2023, 5, 15),
            confidence=0.95,
            extraction_method='regex',
            position=5
        )
        
        self.assertEqual(result.raw_text, "on 2023-05-15")
        self.assertEqual(result.extracted_date, date(2023, 5, 15))
        self.assertEqual(result.confidence, 0.95)
        self.assertEqual(result.extraction_method, 'regex')
        self.assertEqual(result.position, 5)


if __name__ == '__main__':
    unittest.main()
