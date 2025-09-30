"""
Clinical Date Parser for extracting and parsing dates from medical documents.

This module provides utilities for extracting clinical dates from text content,
distinguishing between clinical dates (when events happened) and processing 
metadata (when data was recorded/processed).

Key Features:
- Regex-based extraction for common date formats
- Fuzzy date parsing with dateutil
- Clinical date validation and standardization
- Support for relative date expressions (future NLP extension)
- HIPAA-compliant logging integration
"""

import re
import logging
from datetime import datetime, date
from typing import List, Optional, Dict, Tuple, Union
from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)


class DateExtractionResult:
    """
    Container for date extraction results with metadata.
    
    Attributes:
        raw_text: Original text that contained the date
        extracted_date: Parsed date object
        confidence: Confidence score (0.0-1.0)
        extraction_method: Method used ('regex', 'fuzzy', 'nlp')
        position: Character position in source text
    """
    
    def __init__(self, raw_text: str, extracted_date: date, 
                 confidence: float, extraction_method: str, position: int = 0):
        self.raw_text = raw_text
        self.extracted_date = extracted_date
        self.confidence = confidence
        self.extraction_method = extraction_method
        self.position = position
    
    def __repr__(self):
        return f"DateExtractionResult(date={self.extracted_date}, method={self.extraction_method}, confidence={self.confidence})"


class ClinicalDateParser:
    """
    Parser for extracting and validating clinical dates from medical text.
    
    This class handles various date formats commonly found in medical documents
    and provides standardized date extraction with confidence scoring.
    """
    
    # Common date patterns in medical documents
    DATE_PATTERNS = [
        # MM/DD/YYYY and MM/DD/YY formats
        (r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b', 'mdy_slash'),
        # DD/MM/YYYY and DD/MM/YY formats (less common in US medical records)
        (r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b', 'dmy_slash'),
        # YYYY-MM-DD ISO format
        (r'\b(\d{4})-(\d{2})-(\d{2})\b', 'iso_format'),
        # MM-DD-YYYY format
        (r'\b(\d{1,2})-(\d{1,2})-(\d{2,4})\b', 'mdy_dash'),
        # Month DD, YYYY format
        (r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})\b', 'month_name'),
        # DD Month YYYY format
        (r'\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})\b', 'day_month'),
        # MM.DD.YYYY format (dot separated)
        (r'\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b', 'mdy_dot'),
    ]
    
    # Month name mappings for parsing
    MONTH_NAMES = {
        'jan': 1, 'january': 1,
        'feb': 2, 'february': 2,
        'mar': 3, 'march': 3,
        'apr': 4, 'april': 4,
        'may': 5,
        'jun': 6, 'june': 6,
        'jul': 7, 'july': 7,
        'aug': 8, 'august': 8,
        'sep': 9, 'september': 9,
        'oct': 10, 'october': 10,
        'nov': 11, 'november': 11,
        'dec': 12, 'december': 12,
    }
    
    def __init__(self, assume_mdy: bool = True):
        """
        Initialize the clinical date parser.
        
        Args:
            assume_mdy: Whether to assume MM/DD/YYYY format for ambiguous dates.
                       True for US medical records, False for international.
        """
        self.assume_mdy = assume_mdy
        self.compiled_patterns = [(re.compile(pattern, re.IGNORECASE), name) 
                                for pattern, name in self.DATE_PATTERNS]
    
    def extract_dates(self, text: str, context_window: int = 50) -> List[DateExtractionResult]:
        """
        Extract all dates from the given text.
        
        Args:
            text: Input text to extract dates from
            context_window: Number of characters around date for context
            
        Returns:
            List of DateExtractionResult objects sorted by confidence
        """
        if not text or not isinstance(text, str):
            return []
        
        results = []
        
        # First pass: regex-based extraction
        regex_results = self._extract_with_regex(text, context_window)
        results.extend(regex_results)
        
        # Second pass: fuzzy extraction for missed dates
        fuzzy_results = self._extract_with_fuzzy_parsing(text, results, context_window)
        results.extend(fuzzy_results)
        
        # Sort by confidence (highest first) and remove duplicates
        results = self._deduplicate_results(results)
        results.sort(key=lambda x: x.confidence, reverse=True)
        
        logger.debug(f"Extracted {len(results)} dates from text (length: {len(text)})")
        return results
    
    def _extract_with_regex(self, text: str, context_window: int) -> List[DateExtractionResult]:
        """Extract dates using regex patterns."""
        results = []
        
        for pattern, pattern_name in self.compiled_patterns:
            for match in pattern.finditer(text):
                try:
                    parsed_date = self._parse_regex_match(match, pattern_name)
                    if parsed_date and self._is_valid_clinical_date(parsed_date):
                        confidence = self._calculate_regex_confidence(match, pattern_name)
                        context = self._extract_context(text, match.start(), context_window)
                        
                        result = DateExtractionResult(
                            raw_text=context,
                            extracted_date=parsed_date,
                            confidence=confidence,
                            extraction_method='regex',
                            position=match.start()
                        )
                        results.append(result)
                        
                except (ValueError, TypeError) as e:
                    logger.debug(f"Failed to parse regex match '{match.group()}': {e}")
                    continue
        
        return results
    
    def _extract_with_fuzzy_parsing(self, text: str, existing_results: List[DateExtractionResult], 
                                  context_window: int) -> List[DateExtractionResult]:
        """
        Extract dates using fuzzy parsing for patterns missed by regex.
        
        This method attempts to find dates in text that might not match
        exact regex patterns but are still parseable by dateutil.
        """
        results = []
        
        # Get positions already covered by regex results
        covered_ranges = [(r.position, r.position + len(r.raw_text)) for r in existing_results]
        
        # Split text into words and look for potential date candidates
        words = re.findall(r'\S+', text)
        current_pos = 0
        
        for word in words:
            # Find word position in text
            word_pos = text.find(word, current_pos)
            if word_pos == -1:
                continue
            current_pos = word_pos + len(word)
            
            # Skip if this position is already covered
            if any(start <= word_pos <= end for start, end in covered_ranges):
                continue
            
            # Try to parse as date
            try:
                parsed_date = dateutil_parser.parse(word, fuzzy=False)
                if isinstance(parsed_date, datetime):
                    parsed_date = parsed_date.date()
                
                if self._is_valid_clinical_date(parsed_date):
                    confidence = self._calculate_fuzzy_confidence(word, parsed_date)
                    context = self._extract_context(text, word_pos, context_window)
                    
                    result = DateExtractionResult(
                        raw_text=context,
                        extracted_date=parsed_date,
                        confidence=confidence,
                        extraction_method='fuzzy',
                        position=word_pos
                    )
                    results.append(result)
                    
            except (ValueError, TypeError, OverflowError):
                # Not a valid date, continue
                continue
        
        return results
    
    def _parse_regex_match(self, match: re.Match, pattern_name: str) -> Optional[date]:
        """Parse a regex match into a date object."""
        groups = match.groups()
        
        try:
            if pattern_name == 'iso_format':
                # YYYY-MM-DD
                year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                return date(year, month, day)
            
            elif pattern_name in ['mdy_slash', 'mdy_dash', 'mdy_dot']:
                # MM/DD/YYYY or MM-DD-YYYY or MM.DD.YYYY
                month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
                if year < 100:  # Handle 2-digit years
                    year = 2000 + year if year < 50 else 1900 + year
                return date(year, month, day)
            
            elif pattern_name == 'month_name':
                # Month DD, YYYY
                month_str, day, year = groups[0].lower(), int(groups[1]), int(groups[2])
                month = self.MONTH_NAMES.get(month_str[:3])
                if month:
                    return date(year, month, day)
            
            elif pattern_name == 'day_month':
                # DD Month YYYY
                day, month_str, year = int(groups[0]), groups[1].lower(), int(groups[2])
                month = self.MONTH_NAMES.get(month_str[:3])
                if month:
                    return date(year, month, day)
            
            # Add handling for other patterns as needed
            
        except (ValueError, TypeError, IndexError) as e:
            logger.debug(f"Error parsing date from match {match.group()}: {e}")
            return None
        
        return None
    
    def _is_valid_clinical_date(self, parsed_date: date) -> bool:
        """
        Validate if a date is reasonable for clinical data.
        
        Args:
            parsed_date: Date to validate
            
        Returns:
            True if date is within reasonable clinical range
        """
        if not isinstance(parsed_date, date):
            return False
        
        # Define reasonable range for clinical dates
        earliest_valid = date(1900, 1, 1)  # Medical records shouldn't be older than this
        latest_valid = date.today() + relativedelta(years=1)  # Allow future appointments
        
        return earliest_valid <= parsed_date <= latest_valid
    
    def _calculate_regex_confidence(self, match: re.Match, pattern_name: str) -> float:
        """Calculate confidence score for regex-based extractions."""
        base_confidence = {
            'iso_format': 0.95,      # YYYY-MM-DD is very reliable
            'month_name': 0.90,      # Month names are quite reliable
            'mdy_slash': 0.85,       # Common US format
            'day_month': 0.85,       # Unambiguous format
            'mdy_dash': 0.80,        # Less common but clear
            'mdy_dot': 0.75,         # Less common format
            'dmy_slash': 0.70,       # Ambiguous with US format
        }.get(pattern_name, 0.60)
        
        # Adjust based on context clues (future enhancement)
        # For now, return base confidence
        return base_confidence
    
    def _calculate_fuzzy_confidence(self, word: str, parsed_date: date) -> float:
        """Calculate confidence score for fuzzy parsing results."""
        # Base confidence for fuzzy parsing is lower
        base_confidence = 0.60
        
        # Increase confidence for certain patterns
        if len(word) >= 8:  # Longer strings are more likely to be intentional dates
            base_confidence += 0.10
        
        if any(sep in word for sep in ['/', '-', '.']):  # Has date separators
            base_confidence += 0.15
        
        return min(base_confidence, 0.85)  # Cap at 0.85 for fuzzy results
    
    def _extract_context(self, text: str, position: int, window: int) -> str:
        """Extract context window around a date position."""
        start = max(0, position - window)
        end = min(len(text), position + window * 2)  # Extend end window for more context
        return text[start:end].strip()
    
    def _deduplicate_results(self, results: List[DateExtractionResult]) -> List[DateExtractionResult]:
        """
        Remove duplicate date extractions, keeping the highest confidence result.
        
        Args:
            results: List of extraction results
            
        Returns:
            Deduplicated list with highest confidence results
        """
        # Group by extracted date and proximity (within 20 characters)
        deduplicated = []
        for result in results:
            # Check if we already have this date from a nearby position
            duplicate_found = False
            for existing in deduplicated:
                if (existing.extracted_date == result.extracted_date and 
                    abs(existing.position - result.position) < 20):
                    # Keep the higher confidence result
                    if result.confidence > existing.confidence:
                        deduplicated.remove(existing)
                        deduplicated.append(result)
                    duplicate_found = True
                    break
            
            if not duplicate_found:
                deduplicated.append(result)
        
        return deduplicated
    
    def parse_single_date(self, date_string: str) -> Optional[date]:
        """
        Parse a single date string into a date object.
        
        Args:
            date_string: String containing a date
            
        Returns:
            Parsed date object or None if parsing fails
        """
        if not date_string or not isinstance(date_string, str):
            return None
        
        # First try with our regex patterns
        for pattern, pattern_name in self.compiled_patterns:
            match = pattern.search(date_string.strip())
            if match:
                parsed_date = self._parse_regex_match(match, pattern_name)
                if parsed_date and self._is_valid_clinical_date(parsed_date):
                    return parsed_date
        
        # Fall back to dateutil fuzzy parsing
        try:
            parsed_date = dateutil_parser.parse(date_string.strip(), fuzzy=True)
            if isinstance(parsed_date, datetime):
                parsed_date = parsed_date.date()
            
            if self._is_valid_clinical_date(parsed_date):
                return parsed_date
        except (ValueError, TypeError, OverflowError):
            pass
        
        return None
    
    def validate_date_string(self, date_string: str) -> Tuple[bool, Optional[str]]:
        """
        Validate a date string and return validation result.
        
        Args:
            date_string: Date string to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not date_string:
            return False, "Date string is empty"
        
        if not isinstance(date_string, str):
            return False, "Date must be a string"
        
        parsed_date = self.parse_single_date(date_string)
        if not parsed_date:
            return False, "Unable to parse date from string"
        
        if not self._is_valid_clinical_date(parsed_date):
            return False, "Date is outside valid clinical range (1900-present)"
        
        return True, None
    
    def standardize_date(self, date_input: Union[str, date, datetime]) -> Optional[str]:
        """
        Standardize a date input to ISO format string (YYYY-MM-DD).
        
        Args:
            date_input: Date as string, date object, or datetime object
            
        Returns:
            ISO format date string or None if parsing fails
        """
        if isinstance(date_input, str):
            parsed_date = self.parse_single_date(date_input)
            if parsed_date:
                return parsed_date.isoformat()
        elif isinstance(date_input, datetime):
            return date_input.date().isoformat()
        elif isinstance(date_input, date):
            return date_input.isoformat()
        
        return None
