"""
Comprehensive test suite for snippet extraction and storage functionality.
Tests all components of the snippet-based review system.
"""

import json
import time
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from .models import Document, ParsedData
from .snippet_utils import (
    SnippetExtractor, SnippetValidator, SnippetFormatter, 
    SnippetPositionCalculator, SnippetHelper
)
from .services import DocumentAnalyzer, ResponseParser
from apps.patients.models import Patient


User = get_user_model()


class SnippetUtilitiesTestCase(TestCase):
    """Test suite for snippet utility functions."""
    
    def setUp(self):
        """Set up test data."""
        self.sample_text = """
        Patient: John Doe
        Date of Birth: 01/15/1980
        Medical Record Number: MRN-12345
        
        Chief Complaint: Patient presents with chest pain and shortness of breath.
        
        Assessment: Patient has a history of Hypertension diagnosed in 2018. 
        Current blood pressure is elevated at 150/95 mmHg.
        
        Medications:
        - Lisinopril 10mg daily
        - Aspirin 81mg daily
        
        Allergies: NKDA (No Known Drug Allergies)
        """
        self.extractor = SnippetExtractor()
        self.validator = SnippetValidator()
        self.formatter = SnippetFormatter()
    
    def test_snippet_extractor_basic_functionality(self):
        """Test basic snippet extraction."""
        result = self.extractor.extract_snippet(
            self.sample_text, 
            "Hypertension", 
            snippet_length=200
        )
        
        self.assertTrue(result['found'])
        self.assertIn("Hypertension", result['snippet_text'])
        self.assertGreater(result['actual_position'], 0)
        self.assertEqual(result['target_value'], "Hypertension")
    
    def test_snippet_extractor_with_position(self):
        """Test snippet extraction with known position."""
        # Find Hypertension position first
        position = self.sample_text.find("Hypertension")
        
        result = self.extractor.extract_snippet(
            self.sample_text, 
            "Hypertension", 
            char_position=position
        )
        
        self.assertTrue(result['found'])
        self.assertEqual(result['actual_position'], position)
        self.assertIn("Hypertension", result['snippet_text'])
    
    def test_snippet_extractor_target_not_found(self):
        """Test snippet extraction with non-existent target."""
        result = self.extractor.extract_snippet(
            self.sample_text, 
            "NonExistentValue"
        )
        
        self.assertFalse(result['found'])
        self.assertEqual(result['actual_position'], -1)
        self.assertIn("not found", result['error'])
    
    def test_snippet_validator_valid_data(self):
        """Test snippet validator with valid data."""
        valid_snippet = {
            'source_text': 'Patient has a history of Hypertension diagnosed in 2018.',
            'char_position': 123
        }
        
        validation = self.validator.validate_snippet_data(valid_snippet)
        
        self.assertTrue(validation['is_valid'])
        self.assertEqual(len(validation['issues']), 0)
    
    def test_snippet_validator_invalid_data(self):
        """Test snippet validator with invalid data."""
        invalid_snippet = {
            'char_position': -5  # Invalid negative position
        }
        
        validation = self.validator.validate_snippet_data(invalid_snippet)
        
        self.assertFalse(validation['is_valid'])
        self.assertGreater(len(validation['issues']), 0)
    
    def test_snippet_formatter_html_output(self):
        """Test snippet formatter HTML generation."""
        formatted = self.formatter.format_snippet_for_display(
            "Patient has Hypertension diagnosed",
            "Hypertension",
            highlight_target=True
        )
        
        self.assertIn('<mark class="bg-yellow-200', str(formatted))
        self.assertIn('Hypertension', str(formatted))
    
    def test_confidence_indicator_formatting(self):
        """Test confidence indicator styling."""
        high_conf = self.formatter.format_confidence_indicator(0.9)
        medium_conf = self.formatter.format_confidence_indicator(0.6)
        low_conf = self.formatter.format_confidence_indicator(0.3)
        
        self.assertIn('green', str(high_conf))
        self.assertIn('High', str(high_conf))
        self.assertIn('yellow', str(medium_conf))
        self.assertIn('Medium', str(medium_conf))
        self.assertIn('red', str(low_conf))
        self.assertIn('Low', str(low_conf))


class ParsedDataModelTestCase(TestCase):
    """Test suite for ParsedData model with snippet support."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            medical_record_number='MRN-12345'
        )
        self.document = Document.objects.create(
            filename='test_document.pdf',
            patient=self.patient,
            uploaded_by=self.user,
            status='completed'
        )
    
    def test_parsed_data_with_snippets_creation(self):
        """Test creating ParsedData with snippet information."""
        snippet_data = {
            'patientName': {
                'source_text': 'Patient: John Doe\nDate of Birth: 01/15/1980',
                'char_position': 9
            },
            'diagnosis': {
                'source_text': 'Assessment: Patient has a history of Hypertension diagnosed in 2018.',
                'char_position': 45
            }
        }
        
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json=[
                {'label': 'patientName', 'value': 'John Doe', 'confidence': 0.9},
                {'label': 'diagnosis', 'value': 'Hypertension', 'confidence': 0.8}
            ],
            source_snippets=snippet_data,
            extraction_confidence=0.85
        )
        
        # Verify data was saved correctly
        self.assertEqual(parsed_data.source_snippets['patientName']['char_position'], 9)
        self.assertIn('John Doe', parsed_data.source_snippets['patientName']['source_text'])
        self.assertIn('Hypertension', parsed_data.source_snippets['diagnosis']['source_text'])
    
    def test_parsed_data_backward_compatibility(self):
        """Test that ParsedData works without snippet data (backward compatibility)."""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json=[
                {'label': 'patientName', 'value': 'John Doe', 'confidence': 0.9}
            ],
            # No source_snippets provided - should default to empty dict
            extraction_confidence=0.85
        )
        
        # Verify defaults work correctly
        self.assertEqual(parsed_data.source_snippets, {})
        self.assertIsInstance(parsed_data.source_snippets, dict)


class ResponseParserTestCase(TestCase):
    """Test suite for response parsing with snippet support."""
    
    def setUp(self):
        """Set up test data."""
        self.parser = ResponseParser()
    
    def test_parse_response_with_snippets(self):
        """Test parsing AI response that includes snippet data."""
        response_with_snippets = json.dumps({
            "patientName": {
                "value": "John Doe",
                "confidence": 0.9,
                "source_text": "Patient: John Doe\nDate of Birth: 01/15/1980",
                "char_position": 9
            },
            "diagnosis": {
                "value": "Hypertension",
                "confidence": 0.8,
                "source_text": "Assessment: Patient has a history of Hypertension diagnosed in 2018.",
                "char_position": 45
            }
        })
        
        fields = self.parser.extract_structured_data(response_with_snippets)
        
        # Verify snippet data is preserved
        self.assertEqual(len(fields), 2)
        
        patient_field = next(f for f in fields if f['label'] == 'patientName')
        self.assertEqual(patient_field['value'], 'John Doe')
        self.assertEqual(patient_field['source_text'], 'Patient: John Doe\nDate of Birth: 01/15/1980')
        self.assertEqual(patient_field['char_position'], 9)
        
        diagnosis_field = next(f for f in fields if f['label'] == 'diagnosis')
        self.assertEqual(diagnosis_field['value'], 'Hypertension')
        self.assertIn('Hypertension', diagnosis_field['source_text'])
        self.assertEqual(diagnosis_field['char_position'], 45)
    
    def test_parse_legacy_response_format(self):
        """Test parsing legacy response format without snippets."""
        legacy_response = json.dumps({
            "patientName": "John Doe",
            "diagnosis": "Hypertension"
        })
        
        fields = self.parser.extract_structured_data(legacy_response)
        
        # Verify backward compatibility
        self.assertEqual(len(fields), 2)
        
        patient_field = next(f for f in fields if f['label'] == 'patientName')
        self.assertEqual(patient_field['value'], 'John Doe')
        self.assertEqual(patient_field['source_text'], '')  # Empty for legacy
        self.assertEqual(patient_field['char_position'], 0)  # Default for legacy


class DocumentProcessingTestCase(TestCase):
    """Test suite for document processing with snippet support."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            medical_record_number='MRN-12345'
        )
        self.document = Document.objects.create(
            filename='test_document.pdf',
            patient=self.patient,
            uploaded_by=self.user,
            status='processing'
        )
    
    @patch('apps.documents.services.DocumentAnalyzer.analyze_document')
    def test_document_processing_stores_snippets(self, mock_analyze):
        """Test that document processing correctly stores snippet data."""
        # Mock AI response with snippet data
        mock_analyze.return_value = {
            'success': True,
            'fields': [
                {
                    'id': '1',
                    'label': 'patientName',
                    'value': 'John Doe',
                    'confidence': 0.9,
                    'source_text': 'Patient: John Doe\nDate of Birth: 01/15/1980',
                    'char_position': 9
                },
                {
                    'id': '2',
                    'label': 'diagnosis',
                    'value': 'Hypertension',
                    'confidence': 0.8,
                    'source_text': 'Assessment: Patient has a history of Hypertension diagnosed in 2018.',
                    'char_position': 45
                }
            ],
            'confidence': 0.85,
            'model_used': 'claude-3-sonnet',
            'processing_time': 2.5
        }
        
        # Import and call the task
        from .tasks import process_document_async
        result = process_document_async(self.document.id)
        
        # Verify ParsedData was created with snippet information
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, 'review')  # Should be set to review
        
        parsed_data = ParsedData.objects.get(document=self.document)
        
        # Check snippet data was stored
        self.assertIn('patientName', parsed_data.source_snippets)
        self.assertIn('diagnosis', parsed_data.source_snippets)
        
        patient_snippet = parsed_data.source_snippets['patientName']
        self.assertEqual(patient_snippet['char_position'], 9)
        self.assertIn('John Doe', patient_snippet['source_text'])
        
        diagnosis_snippet = parsed_data.source_snippets['diagnosis']
        self.assertEqual(diagnosis_snippet['char_position'], 45)
        self.assertIn('Hypertension', diagnosis_snippet['source_text'])


class ParsedDataAPITestCase(TestCase):
    """Test suite for ParsedData API endpoint."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            medical_record_number='MRN-12345'
        )
        self.document = Document.objects.create(
            filename='test_document.pdf',
            patient=self.patient,
            uploaded_by=self.user,
            status='completed'
        )
        self.parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json=[
                {'label': 'patientName', 'value': 'John Doe', 'confidence': 0.9},
                {'label': 'diagnosis', 'value': 'Hypertension', 'confidence': 0.8}
            ],
            source_snippets={
                'patientName': {
                    'source_text': 'Patient: John Doe\nDate of Birth: 01/15/1980',
                    'char_position': 9
                },
                'diagnosis': {
                    'source_text': 'Assessment: Patient has a history of Hypertension diagnosed in 2018.',
                    'char_position': 45
                }
            },
            extraction_confidence=0.85
        )
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
    
    def test_api_returns_snippet_data(self):
        """Test that API endpoint returns snippet data."""
        response = self.client.get(reverse('documents:api-parsed-data', args=[self.document.id]))
        
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        
        # Check snippet data is included
        parsed_data = data['data']
        self.assertIn('source_snippets', parsed_data)
        
        snippets = parsed_data['source_snippets']
        self.assertIn('patientName', snippets)
        self.assertIn('diagnosis', snippets)
        
        # Verify snippet content
        patient_snippet = snippets['patientName']
        self.assertEqual(patient_snippet['char_position'], 9)
        self.assertIn('John Doe', patient_snippet['source_text'])
    
    def test_api_returns_snippet_stats(self):
        """Test that API endpoint returns snippet statistics."""
        response = self.client.get(reverse('documents:api-parsed-data', args=[self.document.id]))
        
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn('snippet_stats', data)
        
        stats = data['snippet_stats']
        self.assertEqual(stats['total_snippets'], 2)
        self.assertEqual(stats['snippets_with_position'], 2)
        self.assertEqual(stats['empty_snippets'], 0)
    
    def test_api_handles_missing_parsed_data(self):
        """Test API response when no parsed data exists."""
        # Create document without parsed data
        doc_without_data = Document.objects.create(
            filename='no_data.pdf',
            patient=self.patient,
            uploaded_by=self.user,
            status='completed'
        )
        
        response = self.client.get(reverse('documents:api-parsed-data', args=[doc_without_data.id]))
        
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('No parsed data available', data['error'])


class SnippetHelperTestCase(TestCase):
    """Test suite for high-level snippet helper functions."""
    
    def test_create_snippet_from_field(self):
        """Test creating complete snippet data from field information."""
        full_text = "Patient: John Doe has a diagnosis of Hypertension."
        
        snippet_data = SnippetHelper.create_snippet_from_field(
            full_text=full_text,
            field_label='diagnosis',
            field_value='Hypertension',
            confidence=0.8
        )
        
        self.assertEqual(snippet_data['field_label'], 'diagnosis')
        self.assertEqual(snippet_data['field_value'], 'Hypertension')
        self.assertEqual(snippet_data['confidence'], 0.8)
        self.assertTrue(snippet_data['snippet_found'])
        self.assertIn('Hypertension', snippet_data['source_text'])
    
    def test_validate_and_format_snippets(self):
        """Test validation and formatting of snippet collections."""
        snippets_data = {
            'patientName': {
                'source_text': 'Patient: John Doe\nDate of Birth: 01/15/1980',
                'char_position': 9,
                'target_value': 'John Doe'
            },
            'diagnosis': {
                'source_text': 'Assessment: Patient has a history of Hypertension diagnosed in 2018.',
                'char_position': 45,
                'target_value': 'Hypertension'
            }
        }
        
        result = SnippetHelper.validate_and_format_snippets(snippets_data)
        
        self.assertIn('snippets', result)
        self.assertIn('validation', result)
        
        # Check validation results
        validation = result['validation']
        self.assertTrue(validation['is_valid'])
        self.assertEqual(validation['field_count'], 2)
        
        # Check formatted snippets
        formatted_snippets = result['snippets']
        self.assertIn('patientName', formatted_snippets)
        self.assertIn('diagnosis', formatted_snippets)
    
    def test_snippet_stats_generation(self):
        """Test snippet statistics generation."""
        snippets_data = {
            'field1': {
                'source_text': 'Some text content here',
                'char_position': 10
            },
            'field2': {
                'source_text': 'Another piece of text',
                'char_position': 25
            },
            'field3': {
                'source_text': '',  # Empty snippet
                'char_position': None
            }
        }
        
        stats = SnippetHelper.get_snippet_stats(snippets_data)
        
        self.assertEqual(stats['total_snippets'], 3)
        self.assertEqual(stats['snippets_with_position'], 2)
        self.assertEqual(stats['empty_snippets'], 1)
        self.assertEqual(stats['position_coverage'], 66.7)  # 2/3 * 100
        self.assertEqual(stats['content_coverage'], 66.7)  # 2/3 * 100


class DocumentAnalyzerSnippetTestCase(TestCase):
    """Test suite for DocumentAnalyzer snippet integration."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            medical_record_number='MRN-12345'
        )
        self.document = Document.objects.create(
            filename='test_document.pdf',
            patient=self.patient,
            uploaded_by=self.user,
            status='processing'
        )
    
    @patch('apps.documents.services.DocumentAnalyzer._call_anthropic')
    def test_analyzer_processes_snippet_responses(self, mock_anthropic):
        """Test that DocumentAnalyzer correctly processes responses with snippet data."""
        # Mock Anthropic response with snippet format
        mock_anthropic.return_value = {
            'success': True,
            'response_text': json.dumps({
                "patientName": {
                    "value": "John Doe",
                    "confidence": 0.9,
                    "source_text": "Patient: John Doe\nDate of Birth: 01/15/1980",
                    "char_position": 9
                },
                "diagnosis": {
                    "value": "Hypertension",
                    "confidence": 0.8,
                    "source_text": "Assessment: Patient has a history of Hypertension diagnosed in 2018.",
                    "char_position": 45
                }
            }),
            'model_used': 'claude-3-sonnet',
            'usage': {'total_tokens': 1000}
        }
        
        analyzer = DocumentAnalyzer(document=self.document)
        result = analyzer.analyze_document("Patient: John Doe has Hypertension")
        
        # Verify snippet data is correctly processed
        self.assertTrue(result['success'])
        self.assertEqual(len(result['fields']), 2)
        
        # Check that fields include snippet data
        patient_field = next(f for f in result['fields'] if f['label'] == 'patientName')
        self.assertIn('source_text', patient_field)
        self.assertIn('char_position', patient_field)
        self.assertIn('John Doe', patient_field['source_text'])
    
    @patch('apps.documents.services.DocumentAnalyzer._call_anthropic')
    def test_analyzer_handles_legacy_responses(self, mock_anthropic):
        """Test that DocumentAnalyzer handles legacy responses without snippet data."""
        # Mock legacy response format
        mock_anthropic.return_value = {
            'success': True,
            'response_text': json.dumps({
                "patientName": "John Doe",
                "diagnosis": "Hypertension"
            }),
            'model_used': 'claude-3-sonnet',
            'usage': {'total_tokens': 800}
        }
        
        analyzer = DocumentAnalyzer(document=self.document)
        result = analyzer.analyze_document("Patient: John Doe has Hypertension")
        
        # Verify legacy format is handled correctly
        self.assertTrue(result['success'])
        self.assertEqual(len(result['fields']), 2)
        
        # Check that fields get default snippet values
        patient_field = next(f for f in result['fields'] if f['label'] == 'patientName')
        self.assertEqual(patient_field['source_text'], '')  # Default empty
        self.assertEqual(patient_field['char_position'], 0)  # Default position


class EndToEndSnippetTestCase(TestCase):
    """End-to-end integration tests for snippet functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
        
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            medical_record_number='MRN-12345'
        )
    
    def test_snippet_data_flow_from_processing_to_api(self):
        """Test complete data flow from document processing to API retrieval."""
        # Create document with parsed data including snippets
        document = Document.objects.create(
            filename='test_document.pdf',
            patient=self.patient,
            uploaded_by=self.user,
            status='completed'
        )
        
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json=[
                {
                    'label': 'patientName',
                    'value': 'John Doe',
                    'confidence': 0.9,
                    'source_text': 'Patient: John Doe\nDate of Birth: 01/15/1980',
                    'char_position': 9
                }
            ],
            source_snippets={
                'patientName': {
                    'source_text': 'Patient: John Doe\nDate of Birth: 01/15/1980',
                    'char_position': 9
                }
            },
            extraction_confidence=0.9
        )
        
        # Test API retrieval
        response = self.client.get(reverse('documents:api-parsed-data', args=[document.id]))
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Verify complete data flow
        self.assertTrue(data['success'])
        self.assertIn('source_snippets', data['data'])
        
        snippets = data['data']['source_snippets']
        self.assertIn('patientName', snippets)
        
        patient_snippet = snippets['patientName']
        self.assertEqual(patient_snippet['char_position'], 9)
        self.assertIn('John Doe', patient_snippet['source_text'])
    
    def test_snippet_utilities_integration(self):
        """Test integration between different snippet utility classes."""
        test_text = "Patient: John Doe has been diagnosed with Hypertension in 2018."
        
        # Test SnippetExtractor
        extractor = SnippetExtractor()
        extraction_result = extractor.extract_snippet(test_text, "Hypertension")
        
        self.assertTrue(extraction_result['found'])
        
        # Test SnippetValidator
        validator = SnippetValidator()
        snippet_data = {
            'source_text': extraction_result['snippet_text'],
            'char_position': extraction_result['actual_position']
        }
        validation = validator.validate_snippet_data(snippet_data)
        
        self.assertTrue(validation['is_valid'])
        
        # Test SnippetFormatter
        formatter = SnippetFormatter()
        formatted = formatter.format_snippet_for_display(
            snippet_data['source_text'],
            "Hypertension",
            highlight_target=True
        )
        
        self.assertIn('<mark', str(formatted))
        self.assertIn('Hypertension', str(formatted))


class SnippetEdgeCaseTestCase(TestCase):
    """Test suite for edge cases and error handling in snippet functionality."""
    
    def test_snippet_extraction_edge_cases(self):
        """Test snippet extraction with various edge cases."""
        extractor = SnippetExtractor()
        
        # Test with empty text
        result = extractor.extract_snippet("", "target")
        self.assertFalse(result['found'])
        
        # Test with target at beginning of text
        result = extractor.extract_snippet("Hypertension is a condition", "Hypertension")
        self.assertTrue(result['found'])
        self.assertEqual(result['actual_position'], 0)
        
        # Test with target at end of text
        result = extractor.extract_snippet("Patient has Hypertension", "Hypertension")
        self.assertTrue(result['found'])
        
        # Test with Unicode characters
        unicode_text = "Patient: José García has диабет"
        result = extractor.extract_snippet(unicode_text, "José García")
        self.assertTrue(result['found'])
    
    def test_position_calculator_edge_cases(self):
        """Test position calculator with edge cases."""
        calc = SnippetPositionCalculator()
        
        # Test line/column calculation
        text = "Line 1\nLine 2\nTarget here"
        position = text.find("Target")
        line, col = calc.get_line_and_column(text, position)
        
        self.assertEqual(line, 3)  # Third line
        self.assertGreater(col, 0)  # Some column position
        
        # Test invalid positions
        line, col = calc.get_line_and_column(text, -1)
        self.assertEqual(line, 1)
        self.assertEqual(col, 1)
        
        line, col = calc.get_line_and_column(text, len(text) + 10)
        self.assertEqual(line, 1)
        self.assertEqual(col, 1)
    
    def test_formatter_safety(self):
        """Test that formatter properly escapes HTML for security."""
        formatter = SnippetFormatter()
        
        # Test with potentially dangerous HTML
        malicious_snippet = "Patient: <script>alert('xss')</script> John Doe"
        formatted = formatter.format_snippet_for_display(
            malicious_snippet,
            "John Doe"
        )
        
        # Verify HTML is escaped
        formatted_str = str(formatted)
        self.assertNotIn('<script>', formatted_str)
        self.assertIn('&lt;script&gt;', formatted_str)
    
    def test_validator_comprehensive_checks(self):
        """Test validator with comprehensive edge cases."""
        validator = SnippetValidator()
        
        # Test empty collection
        empty_validation = validator.validate_snippets_collection({})
        self.assertTrue(empty_validation['is_valid'])  # Empty is valid
        self.assertEqual(empty_validation['field_count'], 0)
        
        # Test mixed valid/invalid data
        mixed_data = {
            'valid_field': {
                'source_text': 'Valid snippet text',
                'char_position': 10
            },
            'invalid_field': {
                'source_text': 123,  # Invalid type
                'char_position': -5   # Invalid position
            }
        }
        
        validation = validator.validate_snippets_collection(mixed_data)
        self.assertFalse(validation['is_valid'])
        self.assertEqual(len(validation['valid_fields']), 1)
        self.assertEqual(len(validation['invalid_fields']), 1)


class PerformanceTestCase(TestCase):
    """Test suite for performance aspects of snippet functionality."""
    
    def test_large_document_snippet_extraction(self):
        """Test snippet extraction performance with large documents."""
        # Create a large document (simulate ~100KB of text)
        large_text = "Medical record data. " * 5000  # ~100KB
        large_text += "Patient has severe Hypertension requiring immediate treatment."
        
        extractor = SnippetExtractor()
        
        # Time the extraction (should be fast)
        import time
        start_time = time.time()
        
        result = extractor.extract_snippet(large_text, "Hypertension")
        
        end_time = time.time()
        extraction_time = end_time - start_time
        
        # Verify extraction worked and was reasonably fast
        self.assertTrue(result['found'])
        self.assertLess(extraction_time, 1.0)  # Should take less than 1 second
    
    def test_multiple_snippets_processing(self):
        """Test processing multiple snippets efficiently."""
        # Create multiple field data
        snippets_data = {}
        for i in range(50):  # Test with 50 fields
            snippets_data[f'field_{i}'] = {
                'source_text': f'Field {i} content with some medical data here',
                'char_position': i * 10
            }
        
        # Test validation performance
        validator = SnippetValidator()
        start_time = time.time()
        
        validation = validator.validate_snippets_collection(snippets_data)
        
        end_time = time.time()
        validation_time = end_time - start_time
        
        # Verify validation worked and was fast
        self.assertTrue(validation['is_valid'])
        self.assertEqual(validation['field_count'], 50)
        self.assertLess(validation_time, 1.0)  # Should be fast even with many fields
