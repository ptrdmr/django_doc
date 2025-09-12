"""
Snippet extraction and processing utilities for document review.
Provides utilities for extracting, validating, and formatting text snippets 
around extracted medical data values.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple, Any
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe


logger = logging.getLogger(__name__)


class SnippetExtractor:
    """
    Utility class for extracting text snippets around target values.
    
    Like having a precision tool for cutting exact lengths - 
    gets you just the right amount of context without the fluff.
    """
    
    def __init__(self, default_snippet_length: int = 250):
        """
        Initialize snippet extractor with default settings.
        
        Args:
            default_snippet_length: Default total length for extracted snippets
        """
        self.default_snippet_length = default_snippet_length
        self.min_snippet_length = 100
        self.max_snippet_length = 400
        
    def extract_snippet(
        self, 
        full_text: str, 
        target_value: str, 
        snippet_length: Optional[int] = None,
        char_position: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract a text snippet around a target value.
        
        Args:
            full_text: Complete document text
            target_value: The extracted value to find context for
            snippet_length: Total length of snippet to extract (default: class default)
            char_position: Optional known position of target value
            
        Returns:
            Dict with snippet_text, actual_position, and metadata
        """
        if not full_text or not target_value:
            return {
                'snippet_text': '',
                'actual_position': 0,
                'found': False,
                'error': 'Missing full_text or target_value'
            }
        
        snippet_length = snippet_length or self.default_snippet_length
        
        # Find the target value in the text
        if char_position is not None:
            # Use provided position if available
            actual_position = char_position
            if not self._validate_position(full_text, target_value, char_position):
                # Position doesn't match - search for it
                actual_position = self._find_target_position(full_text, target_value)
        else:
            # Search for the target value
            actual_position = self._find_target_position(full_text, target_value)
        
        if actual_position == -1:
            return {
                'snippet_text': '',
                'actual_position': -1,
                'found': False,
                'error': f'Target value "{target_value}" not found in text'
            }
        
        # Calculate snippet boundaries
        half_length = snippet_length // 2
        start_pos = max(0, actual_position - half_length)
        end_pos = min(len(full_text), actual_position + len(target_value) + half_length)
        
        # Extract snippet
        snippet_text = full_text[start_pos:end_pos]
        
        # Clean up the snippet
        cleaned_snippet = self._clean_snippet(snippet_text)
        
        return {
            'snippet_text': cleaned_snippet,
            'actual_position': actual_position,
            'start_position': start_pos,
            'end_position': end_pos,
            'found': True,
            'target_value': target_value,
            'snippet_length': len(cleaned_snippet)
        }
    
    def _find_target_position(self, full_text: str, target_value: str) -> int:
        """
        Find the position of target value in text using smart matching.
        
        Args:
            full_text: Complete text to search
            target_value: Value to find
            
        Returns:
            Character position of target value, or -1 if not found
        """
        # Strategy 1: Exact match
        position = full_text.find(target_value)
        if position != -1:
            return position
        
        # Strategy 2: Case-insensitive match
        position = full_text.lower().find(target_value.lower())
        if position != -1:
            return position
        
        # Strategy 3: Partial match for medical terms
        # Handle common medical abbreviations and variations
        clean_target = re.sub(r'[^\w\s]', '', target_value.lower())
        clean_text = full_text.lower()
        
        # Look for partial matches
        words = clean_target.split()
        if len(words) > 1:
            # Try to find a phrase containing most of the words
            for i in range(len(words) - 1):
                phrase = ' '.join(words[i:i+2])
                position = clean_text.find(phrase)
                if position != -1:
                    return position
        
        # Strategy 4: Word boundary matching
        target_words = target_value.split()
        if target_words:
            first_word = target_words[0]
            pattern = r'\b' + re.escape(first_word) + r'\b'
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                return match.start()
        
        logger.warning(f"Could not find target value '{target_value}' in document text")
        return -1
    
    def _validate_position(self, full_text: str, target_value: str, position: int) -> bool:
        """
        Validate that target value actually exists at the given position.
        
        Args:
            full_text: Complete text
            target_value: Value to validate
            position: Claimed position
            
        Returns:
            True if target value exists at position (with some tolerance)
        """
        if position < 0 or position >= len(full_text):
            return False
        
        # Check exact match
        end_pos = position + len(target_value)
        if end_pos <= len(full_text):
            actual_text = full_text[position:end_pos]
            if actual_text == target_value:
                return True
            
            # Check case-insensitive match
            if actual_text.lower() == target_value.lower():
                return True
        
        # Allow some tolerance for position accuracy
        tolerance = min(50, len(target_value))
        start_search = max(0, position - tolerance)
        end_search = min(len(full_text), position + len(target_value) + tolerance)
        
        search_area = full_text[start_search:end_search]
        return target_value.lower() in search_area.lower()
    
    def _clean_snippet(self, snippet_text: str) -> str:
        """
        Clean and normalize snippet text for display.
        
        Args:
            snippet_text: Raw snippet text
            
        Returns:
            Cleaned snippet text
        """
        if not snippet_text:
            return ""
        
        # Normalize whitespace while preserving structure
        cleaned = re.sub(r'\s+', ' ', snippet_text.strip())
        
        # Preserve important line breaks for medical documents
        cleaned = re.sub(r'\s*\n\s*', '\n', cleaned)
        
        # Limit excessive line breaks
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        
        return cleaned


class SnippetValidator:
    """
    Validation utilities for snippet data structures.
    
    Like a quality control inspector - makes sure all the parts
    are present and properly formed before they go to assembly.
    """
    
    @staticmethod
    def validate_snippet_data(snippet_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate snippet data structure and content.
        
        Args:
            snippet_data: Dictionary containing snippet information
            
        Returns:
            Validation result with is_valid flag and any issues
        """
        validation = {
            'is_valid': True,
            'issues': [],
            'warnings': []
        }
        
        # Check required fields
        required_fields = ['source_text']
        for field in required_fields:
            if field not in snippet_data:
                validation['is_valid'] = False
                validation['issues'].append(f"Missing required field: {field}")
        
        # Validate source_text
        source_text = snippet_data.get('source_text', '')
        if not isinstance(source_text, str):
            validation['is_valid'] = False
            validation['issues'].append("source_text must be a string")
        elif len(source_text.strip()) == 0:
            validation['warnings'].append("source_text is empty")
        elif len(source_text) < 50:
            validation['warnings'].append(f"source_text is quite short ({len(source_text)} chars)")
        elif len(source_text) > 500:
            validation['warnings'].append(f"source_text is quite long ({len(source_text)} chars)")
        
        # Validate char_position if provided
        char_position = snippet_data.get('char_position')
        if char_position is not None:
            if not isinstance(char_position, (int, float)):
                validation['issues'].append("char_position must be a number")
            elif char_position < 0:
                validation['issues'].append("char_position cannot be negative")
        
        return validation
    
    @staticmethod
    def validate_snippets_collection(snippets: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate a collection of snippets for a document.
        
        Args:
            snippets: Dictionary mapping field names to snippet data
            
        Returns:
            Overall validation result
        """
        validation = {
            'is_valid': True,
            'field_count': len(snippets),
            'valid_fields': [],
            'invalid_fields': [],
            'warnings': []
        }
        
        if not snippets:
            validation['warnings'].append("No snippet data provided")
            return validation
        
        # Validate each field's snippet data
        for field_name, snippet_data in snippets.items():
            field_validation = SnippetValidator.validate_snippet_data(snippet_data)
            
            if field_validation['is_valid']:
                validation['valid_fields'].append(field_name)
            else:
                validation['invalid_fields'].append({
                    'field_name': field_name,
                    'issues': field_validation['issues']
                })
                validation['is_valid'] = False
            
            # Collect warnings
            validation['warnings'].extend([
                f"{field_name}: {warning}" for warning in field_validation['warnings']
            ])
        
        return validation


class SnippetFormatter:
    """
    Formatting utilities for displaying snippets in the UI.
    
    Like a good paint job - makes everything look professional
    and easy to read.
    """
    
    @staticmethod
    def format_snippet_for_display(
        snippet_text: str, 
        target_value: str,
        highlight_target: bool = True
    ) -> str:
        """
        Format snippet text for HTML display with optional highlighting.
        
        Args:
            snippet_text: The snippet text to format
            target_value: The extracted value within the snippet
            highlight_target: Whether to highlight the target value
            
        Returns:
            HTML-safe formatted snippet
        """
        if not snippet_text:
            return mark_safe('<em class="text-gray-500">No context available</em>')
        
        # Escape HTML for safety
        safe_snippet = escape(snippet_text)
        
        if highlight_target and target_value:
            # Highlight the target value within the snippet
            safe_target = escape(target_value)
            
            # Try exact match first
            if safe_target in safe_snippet:
                highlighted = safe_snippet.replace(
                    safe_target, 
                    f'<mark class="bg-yellow-200 font-medium">{safe_target}</mark>'
                )
            else:
                # Try case-insensitive match
                pattern = re.escape(safe_target)
                highlighted = re.sub(
                    pattern, 
                    f'<mark class="bg-yellow-200 font-medium">{safe_target}</mark>',
                    safe_snippet,
                    flags=re.IGNORECASE
                )
        else:
            highlighted = safe_snippet
        
        # Preserve line breaks for readability
        formatted = highlighted.replace('\n', '<br>')
        
        return mark_safe(f'<span class="snippet-display">{formatted}</span>')
    
    @staticmethod
    def format_confidence_indicator(confidence: float) -> str:
        """
        Format confidence score as a styled indicator.
        
        Args:
            confidence: Confidence score (0.0-1.0)
            
        Returns:
            HTML for confidence indicator
        """
        if confidence >= 0.8:
            css_class = "bg-green-100 text-green-800"
            level = "High"
        elif confidence >= 0.5:
            css_class = "bg-yellow-100 text-yellow-800"
            level = "Medium"
        else:
            css_class = "bg-red-100 text-red-800"
            level = "Low"
        
        percentage = int(confidence * 100)
        
        return mark_safe(
            f'<span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium {css_class}">'
            f'{level} ({percentage}%)'
            f'</span>'
        )
    
    @staticmethod
    def truncate_snippet(snippet_text: str, max_length: int = 200, preserve_words: bool = True) -> str:
        """
        Truncate snippet to specified length while preserving readability.
        
        Args:
            snippet_text: Text to truncate
            max_length: Maximum length
            preserve_words: Whether to break on word boundaries
            
        Returns:
            Truncated text with ellipsis if needed
        """
        if not snippet_text or len(snippet_text) <= max_length:
            return snippet_text
        
        if preserve_words:
            # Find the last complete word within the limit
            truncated = snippet_text[:max_length]
            last_space = truncated.rfind(' ')
            
            if last_space > max_length * 0.8:  # If we can keep most of the text
                return truncated[:last_space] + '...'
        
        # Simple character truncation
        return snippet_text[:max_length] + '...'


class SnippetPositionCalculator:
    """
    Utilities for calculating character positions in document text.
    
    Like a surveyor's tool - helps you find exactly where things are
    in the landscape of text.
    """
    
    @staticmethod
    def calculate_relative_position(
        full_text: str, 
        snippet_start: int, 
        target_value: str
    ) -> int:
        """
        Calculate relative position of target within a snippet.
        
        Args:
            full_text: Complete document text
            snippet_start: Starting position of snippet in full text
            target_value: Value to find relative position for
            
        Returns:
            Relative position within snippet, or -1 if not found
        """
        # Extract snippet from full text
        snippet_length = 300  # Default snippet length
        snippet_end = min(len(full_text), snippet_start + snippet_length)
        snippet = full_text[snippet_start:snippet_end]
        
        # Find target within snippet
        relative_pos = snippet.find(target_value)
        
        if relative_pos == -1:
            # Try case-insensitive
            relative_pos = snippet.lower().find(target_value.lower())
        
        return relative_pos
    
    @staticmethod
    def estimate_position_from_content(full_text: str, target_value: str) -> int:
        """
        Estimate character position of target value in full text.
        
        Args:
            full_text: Complete document text
            target_value: Value to locate
            
        Returns:
            Estimated character position
        """
        extractor = SnippetExtractor()
        return extractor._find_target_position(full_text, target_value)
    
    @staticmethod
    def get_line_and_column(full_text: str, char_position: int) -> Tuple[int, int]:
        """
        Convert character position to line and column numbers.
        
        Args:
            full_text: Complete document text
            char_position: Character position to convert
            
        Returns:
            Tuple of (line_number, column_number) - 1-indexed
        """
        if char_position < 0 or char_position >= len(full_text):
            return (1, 1)
        
        # Count lines and calculate column
        text_up_to_position = full_text[:char_position]
        line_number = text_up_to_position.count('\n') + 1
        
        # Find column by looking back to last newline
        last_newline = text_up_to_position.rfind('\n')
        if last_newline == -1:
            column_number = char_position + 1
        else:
            column_number = char_position - last_newline
        
        return (line_number, column_number)


class SnippetHelper:
    """
    High-level helper functions for common snippet operations.
    
    Like a Swiss Army knife - has the most common tools you need
    all in one convenient package.
    """
    
    @staticmethod
    def create_snippet_from_field(
        full_text: str,
        field_label: str,
        field_value: str,
        confidence: float,
        char_position: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Create complete snippet data for a field.
        
        Args:
            full_text: Complete document text
            field_label: Label for the field
            field_value: Extracted value
            confidence: Confidence score
            char_position: Optional known position
            
        Returns:
            Complete snippet data structure
        """
        extractor = SnippetExtractor()
        snippet_result = extractor.extract_snippet(
            full_text, field_value, char_position=char_position
        )
        
        return {
            'field_label': field_label,
            'field_value': field_value,
            'confidence': confidence,
            'source_text': snippet_result['snippet_text'],
            'char_position': snippet_result['actual_position'],
            'snippet_found': snippet_result['found'],
            'metadata': {
                'snippet_length': snippet_result.get('snippet_length', 0),
                'start_position': snippet_result.get('start_position', 0),
                'end_position': snippet_result.get('end_position', 0)
            }
        }
    
    @staticmethod
    def validate_and_format_snippets(snippets_data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate and format snippet data for UI display.
        
        Args:
            snippets_data: Raw snippet data from database
            
        Returns:
            Processed snippet data ready for UI
        """
        validator = SnippetValidator()
        formatter = SnippetFormatter()
        
        # Validate the collection
        validation = validator.validate_snippets_collection(snippets_data)
        
        if not validation['is_valid']:
            logger.warning(f"Snippet validation issues: {validation}")
        
        # Format each snippet for display
        formatted_snippets = {}
        for field_name, snippet_data in snippets_data.items():
            source_text = snippet_data.get('source_text', '')
            char_position = snippet_data.get('char_position', 0)
            
            formatted_snippets[field_name] = {
                'source_text': source_text,
                'char_position': char_position,
                'formatted_html': formatter.format_snippet_for_display(
                    source_text, 
                    snippet_data.get('target_value', ''),
                    highlight_target=True
                ),
                'validation': validator.validate_snippet_data(snippet_data)
            }
        
        return {
            'snippets': formatted_snippets,
            'validation': validation
        }
    
    @staticmethod
    def get_snippet_stats(snippets_data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate statistics about snippet data quality.
        
        Args:
            snippets_data: Snippet data to analyze
            
        Returns:
            Statistics dictionary
        """
        if not snippets_data:
            return {
                'total_snippets': 0,
                'avg_snippet_length': 0,
                'snippets_with_position': 0,
                'empty_snippets': 0
            }
        
        total = len(snippets_data)
        snippet_lengths = []
        with_position = 0
        empty_count = 0
        
        for snippet_data in snippets_data.values():
            source_text = snippet_data.get('source_text', '')
            snippet_lengths.append(len(source_text))
            
            if snippet_data.get('char_position') is not None:
                with_position += 1
            
            if not source_text.strip():
                empty_count += 1
        
        avg_length = sum(snippet_lengths) / len(snippet_lengths) if snippet_lengths else 0
        
        return {
            'total_snippets': total,
            'avg_snippet_length': round(avg_length, 1),
            'snippets_with_position': with_position,
            'empty_snippets': empty_count,
            'position_coverage': round((with_position / total) * 100, 1) if total > 0 else 0,
            'content_coverage': round(((total - empty_count) / total) * 100, 1) if total > 0 else 0
        }
