"""
Integration test for DocumentAnalyzer with MediExtract prompt system.

Quick test to verify that our prompt system integrates properly with 
the DocumentAnalyzer without any import or configuration issues.

Like doing a quick engine start test after installing new parts.
"""

import unittest
from unittest.mock import Mock, patch
from django.test import TestCase


class TestDocumentAnalyzerPromptIntegration(TestCase):
    """Test DocumentAnalyzer integration with MediExtract prompt system."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.api_key = "test_key_for_integration"
    
    @patch('apps.documents.services.anthropic')
    @patch('apps.documents.services.openai')
    def test_document_analyzer_prompt_generation(self, mock_openai, mock_anthropic):
        """Test that DocumentAnalyzer can generate prompts using MediExtract system."""
        # Mock the anthropic/openai modules to avoid import errors
        mock_anthropic.Client = Mock()
        mock_openai.OpenAI = Mock()
        
        from apps.documents.services import DocumentAnalyzer
        
        # Create analyzer instance with mocked dependencies
        with patch.object(DocumentAnalyzer, '_init_ai_clients'):
            analyzer = DocumentAnalyzer(api_key=self.api_key)
            analyzer.logger = Mock()
        
        # Test basic prompt generation
        prompt = analyzer._get_medical_extraction_prompt()
        
        # Verify prompt contains MediExtract content
        self.assertIn("MediExtract", prompt)
        self.assertIn("medical documents", prompt)
        self.assertIn("JSON object", prompt)
    
    @patch('apps.documents.services.anthropic')
    @patch('apps.documents.services.openai')
    def test_document_analyzer_context_prompt(self, mock_openai, mock_anthropic):
        """Test that DocumentAnalyzer generates context-aware prompts."""
        # Mock the dependencies
        mock_anthropic.Client = Mock()
        mock_openai.OpenAI = Mock()
        
        from apps.documents.services import DocumentAnalyzer
        
        with patch.object(DocumentAnalyzer, '_init_ai_clients'):
            analyzer = DocumentAnalyzer(api_key=self.api_key)
            analyzer.logger = Mock()
        
        # Test context-aware prompt generation
        context = "Emergency Department Report"
        prompt = analyzer._get_medical_extraction_prompt(context)
        
        # Verify context is included
        self.assertIn("Context:", prompt)
        self.assertIn("Emergency Department Report", prompt)
    
    @patch('apps.documents.services.anthropic')
    @patch('apps.documents.services.openai')
    def test_document_analyzer_chunked_prompt(self, mock_openai, mock_anthropic):
        """Test that DocumentAnalyzer generates chunked document prompts."""
        # Mock the dependencies
        mock_anthropic.Client = Mock()
        mock_openai.OpenAI = Mock()
        
        from apps.documents.services import DocumentAnalyzer
        
        with patch.object(DocumentAnalyzer, '_init_ai_clients'):
            analyzer = DocumentAnalyzer(api_key=self.api_key)
            analyzer.logger = Mock()
        
        # Test chunked document prompt generation
        chunk_info = {
            'current': 2,
            'total': 5,
            'is_first': False,
            'is_last': False
        }
        
        prompt = analyzer._get_medical_extraction_prompt(
            context="Medical Report",
            chunk_info=chunk_info
        )
        
        # Verify chunking information is included
        self.assertIn("part 2 of 5", prompt)
        self.assertIn("document section", prompt)
    
    def test_prompt_fallback_method_exists(self):
        """Test that fallback extraction method exists."""
        from apps.documents.services import DocumentAnalyzer
        
        # Verify the fallback method exists and is callable
        self.assertTrue(hasattr(DocumentAnalyzer, '_try_fallback_extraction'))
        self.assertTrue(callable(getattr(DocumentAnalyzer, '_try_fallback_extraction')))
    
    def test_confidence_scoring_integration(self):
        """Test that confidence scoring can be imported and used."""
        from apps.documents.prompts import ConfidenceScoring
        
        # Test basic confidence scoring functionality
        test_fields = [
            {"label": "Patient Name", "value": "Smith, John", "confidence": 0.8},
            {"label": "Date of Birth", "value": "01/15/1980", "confidence": 0.7}
        ]
        
        calibrated = ConfidenceScoring.calibrate_confidence_scores(test_fields)
        
        # Verify calibration works
        self.assertEqual(len(calibrated), 2)
        for field in calibrated:
            self.assertIn('confidence_level', field)
            self.assertIn('requires_review', field)
    
    def test_medical_prompts_selection(self):
        """Test that medical prompt selection works for different document types."""
        from apps.documents.prompts import MedicalPrompts
        
        # Test different document type prompts
        ed_prompt = MedicalPrompts.get_extraction_prompt(document_type='ed')
        surgical_prompt = MedicalPrompts.get_extraction_prompt(document_type='surgical')
        lab_prompt = MedicalPrompts.get_extraction_prompt(document_type='lab')
        
        # Verify document-specific content
        self.assertIn("Emergency Department", ed_prompt)
        self.assertIn("surgical documentation", surgical_prompt)
        self.assertIn("laboratory documentation", lab_prompt)
        
        # All should be different
        self.assertNotEqual(ed_prompt, surgical_prompt)
        self.assertNotEqual(surgical_prompt, lab_prompt)
        self.assertNotEqual(ed_prompt, lab_prompt)


if __name__ == '__main__':
    unittest.main() 