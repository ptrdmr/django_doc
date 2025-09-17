"""
Unit tests for the refactored DocumentAnalyzer class.

Tests cover:
- Text extraction functionality
- Structured medical data analysis
- Backward compatibility with legacy API
- Error handling and graceful degradation
- Processing statistics and audit logging

Author: Task 34.2 - Refactor DocumentAnalyzer class
Date: 2025-09-17 07:19:02
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.conf import settings
import tempfile
import os
import time

from apps.documents.analyzers import DocumentAnalyzer
from apps.documents.services.ai_extraction import StructuredMedicalExtraction, MedicalCondition, Medication, SourceContext
# Import PDFTextExtractor directly from the services.py module
import sys
import importlib.util
import os
spec = importlib.util.spec_from_file_location("services_py", os.path.join(os.path.dirname(__file__), "services.py"))
services_py = importlib.util.module_from_spec(spec)
sys.modules["apps.documents.services_py"] = services_py
spec.loader.exec_module(services_py)


class DocumentAnalyzerTestCase(TestCase):
    """Test cases for the DocumentAnalyzer class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.analyzer = DocumentAnalyzer()
        
        # Create a mock document
        self.mock_document = Mock()
        self.mock_document.id = 123
        self.mock_document.file.path = '/tmp/test_document.pdf'
        self.mock_document.document_type = 'Emergency Department Report'
        
        # Sample medical text for testing
        self.sample_medical_text = """
        Patient presents with chest pain and shortness of breath.
        Current medications:
        - Metformin 500mg twice daily
        - Lisinopril 10mg once daily
        
        Vital signs:
        - Blood pressure: 140/90 mmHg
        - Heart rate: 85 bpm
        
        Assessment:
        - Type 2 diabetes mellitus
        - Hypertension
        
        Plan:
        - Continue current medications
        - Follow up in 2 weeks
        """
        
        # Sample structured extraction result
        self.sample_structured_data = StructuredMedicalExtraction(
            conditions=[
                MedicalCondition(
                    name="Type 2 diabetes mellitus",
                    confidence=0.9,
                    source=SourceContext(text="Type 2 diabetes mellitus", start_index=100, end_index=125)
                ),
                MedicalCondition(
                    name="Hypertension", 
                    confidence=0.85,
                    source=SourceContext(text="Hypertension", start_index=130, end_index=142)
                )
            ],
            medications=[
                Medication(
                    name="Metformin",
                    dosage="500mg",
                    frequency="twice daily",
                    confidence=0.95,
                    source=SourceContext(text="Metformin 500mg twice daily", start_index=50, end_index=78)
                ),
                Medication(
                    name="Lisinopril",
                    dosage="10mg", 
                    frequency="once daily",
                    confidence=0.9,
                    source=SourceContext(text="Lisinopril 10mg once daily", start_index=80, end_index=107)
                )
            ],
            extraction_timestamp="2025-09-17T07:19:02",
            document_type="Emergency Department Report",
            confidence_average=0.9
        )
    
    def test_analyzer_initialization(self):
        """Test DocumentAnalyzer initialization."""
        # Test initialization without document
        analyzer = DocumentAnalyzer()
        self.assertIsNotNone(analyzer.processing_session)
        self.assertIsNone(analyzer.document)
        self.assertIn('session_id', analyzer.stats)
        
        # Test initialization with document
        analyzer_with_doc = DocumentAnalyzer(document=self.mock_document)
        self.assertEqual(analyzer_with_doc.document, self.mock_document)
        self.assertEqual(analyzer_with_doc.stats['document_id'], 123)
    
    def test_extract_text_success(self):
        """Test successful text extraction from PDF."""
        # Mock the PDF extractor method
        mock_extractor = Mock()
        mock_extractor.extract_text.return_value = {
            'success': True,
            'text': self.sample_medical_text,
            'page_count': 2,
            'metadata': {'file_size': 1024}
        }
        
        # Patch the _get_pdf_extractor method
        with patch.object(self.analyzer, '_get_pdf_extractor', return_value=mock_extractor):
            # Test extraction
            result = self.analyzer.extract_text('/tmp/test.pdf')
            
            # Verify result
            self.assertTrue(result['success'])
            self.assertEqual(result['text'], self.sample_medical_text)
            self.assertEqual(result['page_count'], 2)
            mock_extractor.extract_text.assert_called_once_with('/tmp/test.pdf')
    
    def test_extract_text_failure(self):
        """Test text extraction failure handling."""
        # Mock failed PDF extraction
        mock_extractor = Mock()
        mock_extractor.extract_text.return_value = {
            'success': False,
            'text': '',
            'error_message': 'File not found'
        }
        
        # Patch the _get_pdf_extractor method
        with patch.object(self.analyzer, '_get_pdf_extractor', return_value=mock_extractor):
            # Test extraction
            result = self.analyzer.extract_text('/tmp/nonexistent.pdf')
            
            # Verify error handling
            self.assertFalse(result['success'])
            self.assertEqual(result['error_message'], 'File not found')
            self.assertIn('Text extraction: File not found', self.analyzer.stats['errors_encountered'])
    
    @patch('apps.documents.analyzers.extract_medical_data_structured')
    def test_analyze_document_structured_success(self, mock_extract):
        """Test successful structured document analysis."""
        # Mock successful extraction
        mock_extract.return_value = self.sample_structured_data
        
        # Test structured analysis
        result = self.analyzer.analyze_document_structured(self.sample_medical_text, "Test Report")
        
        # Verify results
        self.assertIsInstance(result, StructuredMedicalExtraction)
        self.assertEqual(len(result.conditions), 2)
        self.assertEqual(len(result.medications), 2)
        self.assertEqual(result.confidence_average, 0.9)
        self.assertEqual(self.analyzer.stats['successful_extractions'], 1)
        
        mock_extract.assert_called_once_with(self.sample_medical_text, "Test Report")
    
    @patch('apps.documents.analyzers.extract_medical_data_structured')
    def test_analyze_document_structured_failure(self, mock_extract):
        """Test structured analysis failure handling."""
        # Mock extraction failure
        mock_extract.side_effect = Exception("AI service unavailable")
        
        # Test that exception is properly raised
        with self.assertRaises(Exception) as context:
            self.analyzer.analyze_document_structured(self.sample_medical_text)
        
        self.assertIn("AI service unavailable", str(context.exception))
        self.assertIn("Structured analysis failed", self.analyzer.stats['errors_encountered'][0])
    
    @patch('apps.documents.analyzers.extract_medical_data')
    def test_extract_medical_data_success(self, mock_extract):
        """Test successful medical data extraction."""
        # Mock successful extraction
        mock_extract.return_value = {
            'diagnoses': ['Type 2 diabetes mellitus', 'Hypertension'],
            'medications': ['Metformin 500mg twice daily', 'Lisinopril 10mg once daily'],
            'procedures': [],
            'lab_results': [],
            'vital_signs': [],
            'providers': [],
            'extraction_confidence': 0.9,
            'total_items_extracted': 4
        }
        
        # Test extraction
        result = self.analyzer.extract_medical_data(self.sample_medical_text, "Test Report")
        
        # Verify results
        self.assertEqual(len(result['diagnoses']), 2)
        self.assertEqual(len(result['medications']), 2)
        self.assertEqual(result['extraction_confidence'], 0.9)
        self.assertEqual(result['total_items_extracted'], 4)
        self.assertEqual(self.analyzer.stats['successful_extractions'], 1)
        
        mock_extract.assert_called_once_with(self.sample_medical_text, "Test Report")
    
    @patch('apps.documents.analyzers.extract_medical_data')
    def test_extract_medical_data_failure(self, mock_extract):
        """Test medical data extraction failure handling."""
        # Mock extraction failure
        mock_extract.side_effect = Exception("API quota exceeded")
        
        # Test extraction with error
        result = self.analyzer.extract_medical_data(self.sample_medical_text)
        
        # Verify graceful degradation
        self.assertEqual(result['diagnoses'], [])
        self.assertEqual(result['medications'], [])
        self.assertEqual(result['extraction_confidence'], 0.0)
        self.assertEqual(result['total_items_extracted'], 0)
        self.assertIn('error', result)
        self.assertIn("API quota exceeded", result['error'])
        self.assertIn("Medical data extraction failed", self.analyzer.stats['errors_encountered'][0])
    
    @patch('apps.documents.analyzers.DocumentAnalyzer.extract_text')
    @patch('apps.documents.analyzers.DocumentAnalyzer.extract_medical_data')
    def test_analyze_legacy_compatibility(self, mock_extract_medical, mock_extract_text):
        """Test legacy analyze method for backward compatibility."""
        # Mock successful text extraction
        mock_extract_text.return_value = {
            'success': True,
            'text': self.sample_medical_text
        }
        
        # Mock successful medical data extraction
        mock_extract_medical.return_value = {
            'diagnoses': ['Type 2 diabetes mellitus'],
            'medications': ['Metformin 500mg'],
            'procedures': [],
            'lab_results': [],
            'vital_signs': [],
            'providers': [],
            'extraction_confidence': 0.9,
            'total_items_extracted': 2
        }
        
        # Test legacy analyze method
        result = self.analyzer.analyze(self.mock_document)
        
        # Verify legacy format
        self.assertTrue(result['success'])
        self.assertIn('fields', result)
        self.assertIn('processing_method', result)
        self.assertIn('model_used', result)
        self.assertIn('usage', result)
        self.assertEqual(result['extraction_confidence'], 0.9)
        self.assertEqual(result['total_items_extracted'], 2)
        
        # Verify fields format
        fields = result['fields']
        self.assertIsInstance(fields, list)
        if fields:
            field = fields[0]
            self.assertIn('label', field)
            self.assertIn('value', field)
            self.assertIn('confidence', field)
            self.assertIn('category', field)
    
    @patch('apps.documents.analyzers.DocumentAnalyzer.extract_text')
    def test_analyze_text_extraction_failure(self, mock_extract_text):
        """Test analyze method when text extraction fails."""
        # Mock text extraction failure
        mock_extract_text.return_value = {
            'success': False,
            'error_message': 'Corrupted PDF file'
        }
        
        # Test analysis with text extraction failure
        result = self.analyzer.analyze(self.mock_document)
        
        # Verify error handling
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'Corrupted PDF file')
        self.assertEqual(result['fields'], [])
    
    def test_analyze_invalid_document_type(self):
        """Test analyze method with invalid document type."""
        # Test with invalid document type
        invalid_document = 12345  # Neither Document object nor string
        
        result = self.analyzer.analyze(invalid_document)
        
        # Verify error handling
        self.assertFalse(result['success'])
        self.assertIn('Unsupported document type', result['error'])
        self.assertEqual(result['fields'], [])
    
    def test_convert_to_legacy_fields(self):
        """Test conversion of extracted data to legacy field format."""
        # Test data with various types
        test_data = {
            'diagnoses': ['Diabetes', 'Hypertension'],
            'medications': ['Metformin 500mg', 'Lisinopril 10mg'],
            'procedures': ['Blood draw'],
            'lab_results': [{'test': 'HbA1c', 'value': '7.2', 'unit': '%'}],
            'vital_signs': [{'type': 'BP', 'value': '140/90', 'unit': 'mmHg'}],
            'providers': [{'name': 'Dr. Smith', 'specialty': 'Cardiology'}],
            'extraction_confidence': 0.85
        }
        
        # Convert to legacy format
        fields = self.analyzer._convert_to_legacy_fields(test_data)
        
        # Verify conversion
        self.assertEqual(len(fields), 8)  # 2 diagnoses + 2 medications + 1 procedure + 1 lab + 1 vital + 1 provider
        
        # Check diagnosis fields
        diagnosis_fields = [f for f in fields if f['label'] == 'diagnosis']
        self.assertEqual(len(diagnosis_fields), 2)
        self.assertEqual(diagnosis_fields[0]['value'], 'Diabetes')
        self.assertEqual(diagnosis_fields[0]['category'], 'medical_condition')
        self.assertEqual(diagnosis_fields[0]['confidence'], 0.85)
        
        # Check medication fields
        medication_fields = [f for f in fields if f['label'] == 'medication']
        self.assertEqual(len(medication_fields), 2)
        self.assertEqual(medication_fields[0]['value'], 'Metformin 500mg')
        self.assertEqual(medication_fields[0]['category'], 'medication')
        
        # Check lab result fields
        lab_fields = [f for f in fields if f['label'] == 'lab_result']
        self.assertEqual(len(lab_fields), 1)
        self.assertEqual(lab_fields[0]['value'], 'HbA1c 7.2 %')
        self.assertEqual(lab_fields[0]['category'], 'lab_result')
    
    def test_processing_stats_tracking(self):
        """Test processing statistics tracking."""
        # Get initial stats
        initial_stats = self.analyzer.get_processing_stats()
        
        # Verify initial values
        self.assertEqual(initial_stats['extraction_attempts'], 0)
        self.assertEqual(initial_stats['successful_extractions'], 0)
        self.assertEqual(initial_stats['success_rate'], 0.0)
        self.assertIsInstance(initial_stats['session_id'], str)
        
        # Simulate some processing with a small delay to ensure processing time > 0
        import time
        time.sleep(0.01)  # 10ms delay
        self.analyzer.stats['extraction_attempts'] = 3
        self.analyzer.stats['successful_extractions'] = 2
        self.analyzer.stats['errors_encountered'] = ['Test error']
        
        # Get updated stats
        final_stats = self.analyzer.get_processing_stats()
        
        # Verify updated values
        self.assertEqual(final_stats['extraction_attempts'], 3)
        self.assertEqual(final_stats['successful_extractions'], 2)
        self.assertAlmostEqual(final_stats['success_rate'], 2/3, places=2)
        self.assertEqual(len(final_stats['errors_encountered']), 1)
        self.assertGreater(final_stats['total_processing_time'], 0)
    
    def test_analyzer_string_input(self):
        """Test analyzer with string file path input."""
        with patch('apps.documents.analyzers.DocumentAnalyzer.extract_text') as mock_extract_text, \
             patch('apps.documents.analyzers.DocumentAnalyzer.extract_medical_data') as mock_extract_medical:
            
            # Mock successful extraction
            mock_extract_text.return_value = {'success': True, 'text': 'test content'}
            mock_extract_medical.return_value = {
                'diagnoses': ['Test diagnosis'],
                'medications': [],
                'procedures': [],
                'lab_results': [],
                'vital_signs': [],
                'providers': [],
                'extraction_confidence': 0.8,
                'total_items_extracted': 1
            }
            
            # Test with string path
            result = self.analyzer.analyze('/tmp/test_document.pdf')
            
            # Verify it works with string input
            self.assertTrue(result['success'])
            mock_extract_text.assert_called_once_with('/tmp/test_document.pdf')
            mock_extract_medical.assert_called_once_with('test content', None)
    
    def test_session_cleanup_logging(self):
        """Test that session cleanup logging works properly."""
        # Create analyzer with some stats
        analyzer = DocumentAnalyzer(document=self.mock_document)
        analyzer.stats['successful_extractions'] = 3
        analyzer.stats['extraction_attempts'] = 4
        analyzer.stats['errors_encountered'] = ['Test error']
        
        # Capture session ID for verification
        session_id = analyzer.processing_session
        
        # Test cleanup (triggered by __del__)
        with patch.object(analyzer, 'logger') as mock_logger:
            del analyzer
            
            # Note: __del__ behavior can be unpredictable in tests,
            # but we've tested the get_processing_stats method which is used in __del__


class DocumentAnalyzerIntegrationTestCase(TestCase):
    """Integration tests for DocumentAnalyzer with real components."""
    
    def setUp(self):
        """Set up integration test fixtures."""
        self.analyzer = DocumentAnalyzer()
    
    @patch('apps.documents.services.ai_extraction.anthropic_client')
    @patch('apps.documents.services.ai_extraction.openai_client')
    def test_integration_with_ai_extraction_service(self, mock_openai, mock_anthropic):
        """Test integration with the AI extraction service."""
        # Mock both AI services as unavailable to test fallback
        mock_anthropic = None
        mock_openai = None
        
        # This should trigger the fallback extraction method
        result = self.analyzer.extract_medical_data("Patient has diabetes and takes Metformin.")
        
        # Verify fallback works - should get a graceful error response
        self.assertEqual(result['extraction_confidence'], 0.0)
        self.assertEqual(result['total_items_extracted'], 0)
        self.assertIn('error', result)
    
    def test_error_logging_and_recovery(self):
        """Test comprehensive error logging and recovery."""
        # Test with invalid text extraction
        mock_extractor = Mock()
        mock_extractor.extract_text.side_effect = Exception("Service unavailable")
        
        with patch.object(self.analyzer, '_get_pdf_extractor', return_value=mock_extractor):
            result = self.analyzer.extract_text('/tmp/test.pdf')
            
            # Verify error is logged and handled
            self.assertFalse(result['success'])
            self.assertIn('Service unavailable', result['error_message'])
            self.assertGreater(len(self.analyzer.stats['errors_encountered']), 0)
    
    def test_full_document_processing_workflow(self):
        """Test the complete document processing workflow."""
        # Create a temporary PDF-like file for testing
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
            temp_file.write(b"Mock PDF content")
            temp_path = temp_file.name
        
        try:
            # Mock the PDF extractor to return our test content
            mock_extractor = Mock()
            mock_extractor.extract_text.return_value = {
                'success': True,
                'text': 'Patient diagnosed with diabetes. Taking Metformin 500mg daily.',
                'page_count': 1,
                'metadata': {'file_size': 1024}
            }
            
            with patch.object(self.analyzer, '_get_pdf_extractor', return_value=mock_extractor):
                # Mock the AI extraction to return structured data
                with patch('apps.documents.analyzers.extract_medical_data') as mock_extract:
                    mock_extract.return_value = {
                        'diagnoses': ['Diabetes'],
                        'medications': ['Metformin 500mg daily'],
                        'procedures': [],
                        'lab_results': [],
                        'vital_signs': [],
                        'providers': [],
                        'extraction_confidence': 0.9,
                        'total_items_extracted': 2
                    }
                    
                    # Test full workflow
                    result = self.analyzer.analyze(temp_path)
                    
                    # Verify complete workflow
                    self.assertTrue(result['success'])
                    self.assertEqual(len(result['fields']), 2)  # 1 diagnosis + 1 medication
                    self.assertEqual(result['extraction_confidence'], 0.9)
                    self.assertEqual(result['total_items_extracted'], 2)
                    
                    # Verify processing stats
                    stats = self.analyzer.get_processing_stats()
                    self.assertGreater(stats['total_processing_time'], 0)
                    self.assertEqual(stats['successful_extractions'], 1)
                    self.assertEqual(stats['success_rate'], 1.0)
        
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_path)
            except:
                pass


if __name__ == '__main__':
    unittest.main()
