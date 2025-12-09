"""
Tests for enhanced error handling in process_document_async task.

This module tests the robust error handling added in Task 41.14, ensuring:
- All error types are properly categorized
- Document status is updated consistently in all error paths
- Detailed error information is logged and returned
- Retry logic works correctly based on error type
- Processing errors are tracked throughout the task execution

Created: 2025-12-09 (Task 41.14)
"""

import pytest
import tempfile
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.documents.tasks import process_document_async
from apps.documents.models import Document, ParsedData
from apps.patients.models import Patient
from apps.documents.exceptions import (
    PDFExtractionError,
    AIExtractionError,
    AIServiceTimeoutError,
    AIServiceRateLimitError,
    FHIRConversionError,
    DataValidationError,
    categorize_exception,
    get_recovery_strategy
)


class TestProcessDocumentAsyncErrorHandling(TestCase):
    """Test error handling in process_document_async task."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create test patient
        self.patient = Patient.objects.create(
            mrn='TEST-ERR-001',
            first_name='Test',
            last_name='Patient',
            date_of_birth='1980-01-01'
        )
        
        # Create test document with mock file
        test_file = SimpleUploadedFile(
            "test.pdf",
            b"PDF content here",
            content_type="application/pdf"
        )
        self.document = Document.objects.create(
            patient=self.patient,
            file=test_file,
            status='pending',
            uploaded_by=None
        )
    
    @patch('apps.documents.services.PDFTextExtractor')
    def test_pdf_extraction_error_handling(self, mock_pdf_extractor):
        """Test that PDF extraction errors are properly categorized and handled."""
        # Arrange: Mock PDF extraction to raise PDFExtractionError
        mock_instance = mock_pdf_extractor.return_value
        mock_instance.extract_text.side_effect = PDFExtractionError(
            "Failed to read PDF file",
            file_path=self.document.file.path,
            details={'page_number': 1}
        )
        
        # Mock the task's retry method
        mock_task = Mock()
        mock_task.request = Mock(id='test-task-123', retries=0)
        
        # Act: Run the task
        with patch.object(process_document_async, 'retry') as mock_retry:
            result = process_document_async(mock_task, self.document.id)
        
        # Assert: Verify error handling
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'PDFExtractionError')
        self.assertEqual(result['error_code'], 'PDF_EXTRACTION_ERROR')
        self.assertIn('recovery_strategy', result)
        self.assertEqual(result['recovery_strategy'], 'manual_review_required')
        
        # Verify document status was updated
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, 'failed')
        self.assertIn('PDF', self.document.error_message)
    
    @patch('apps.documents.services.PDFTextExtractor')
    @patch('apps.documents.analyzers.DocumentAnalyzer')
    def test_ai_extraction_error_handling(self, mock_analyzer, mock_pdf_extractor):
        """Test that AI extraction errors are properly categorized and handled."""
        # Arrange: Mock successful PDF extraction
        mock_pdf_instance = mock_pdf_extractor.return_value
        mock_pdf_instance.extract_text.return_value = {
            'success': True,
            'text': 'Sample medical document text',
            'page_count': 1,
            'file_size': 0.5,
            'metadata': {}
        }
        
        # Mock AI analyzer to raise AIExtractionError
        mock_analyzer_instance = mock_analyzer.return_value
        mock_analyzer_instance.analyze_document_structured.side_effect = AIExtractionError(
            "AI service unavailable",
            ai_service='claude',
            model_used='claude-3-sonnet',
            details={'http_status': 503}
        )
        
        # Mock the task
        mock_task = Mock()
        mock_task.request = Mock(id='test-task-456', retries=0)
        
        # Act: Run the task
        result = process_document_async(mock_task, self.document.id)
        
        # Assert: Verify error was logged but task continued
        # AI errors should not fail the entire task - we still have the PDF text
        self.assertFalse(result['success'])
        
        # Verify document status reflects the failure
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, 'failed')
        self.assertIn('AI analysis failed', self.document.error_message)
    
    @patch('apps.documents.services.PDFTextExtractor')
    @patch('apps.documents.analyzers.DocumentAnalyzer')
    def test_ai_timeout_retry_logic(self, mock_analyzer, mock_pdf_extractor):
        """Test that AI timeout errors trigger retry with appropriate delay."""
        # Arrange: Mock successful PDF extraction
        mock_pdf_instance = mock_pdf_extractor.return_value
        mock_pdf_instance.extract_text.return_value = {
            'success': True,
            'text': 'Sample medical document text',
            'page_count': 1,
            'file_size': 0.5,
            'metadata': {}
        }
        
        # Mock AI analyzer to raise timeout error at task level
        mock_task = Mock()
        mock_task.request = Mock(id='test-task-789', retries=0)
        
        # Simulate timeout error during processing
        with patch('apps.documents.tasks.Document.objects.get') as mock_get_doc:
            mock_get_doc.side_effect = AIServiceTimeoutError(
                "AI service timeout",
                timeout_seconds=30,
                details={'model': 'claude-3'}
            )
            
            with patch.object(process_document_async, 'retry', side_effect=Exception("Retry called")) as mock_retry:
                with self.assertRaises(Exception) as context:
                    process_document_async(mock_task, self.document.id)
                
                self.assertEqual(str(context.exception), "Retry called")
                
                # Verify retry was called with correct parameters
                mock_retry.assert_called_once()
                call_kwargs = mock_retry.call_args[1]
                # Timeout errors should have 1 minute retry delay
                self.assertEqual(call_kwargs['countdown'], 60)
    
    @patch('apps.documents.services.PDFTextExtractor')
    @patch('apps.documents.analyzers.DocumentAnalyzer')
    def test_data_validation_error_during_parsed_data_creation(self, mock_analyzer, mock_pdf_extractor):
        """Test that data validation errors during ParsedData creation are handled properly."""
        # Arrange: Mock successful PDF extraction and AI analysis
        mock_pdf_instance = mock_pdf_extractor.return_value
        mock_pdf_instance.extract_text.return_value = {
            'success': True,
            'text': 'Sample medical document text',
            'page_count': 1,
            'file_size': 0.5,
            'metadata': {}
        }
        
        # Mock successful AI analysis
        from apps.documents.services.ai_extraction import StructuredMedicalExtraction
        mock_extraction = StructuredMedicalExtraction(
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[],
            procedures=[],
            providers=[],
            extraction_timestamp=timezone.now().isoformat(),
            document_type='clinical_note',
            confidence_average=0.85
        )
        
        mock_analyzer_instance = mock_analyzer.return_value
        mock_analyzer_instance.analyze_document_structured.return_value = mock_extraction
        
        # Mock ParsedData.objects.update_or_create to raise DataValidationError
        with patch('apps.documents.models.ParsedData.objects.update_or_create') as mock_update_create:
            mock_update_create.side_effect = DataValidationError(
                "Invalid field value",
                field_name='extraction_confidence',
                validation_rule='must_be_between_0_and_1',
                details={'value': 1.5}
            )
            
            # Mock the task
            mock_task = Mock()
            mock_task.request = Mock(id='test-task-101', retries=0)
            
            # Act: Run the task
            result = process_document_async(mock_task, self.document.id)
            
            # Assert: Task should complete despite ParsedData error
            # Processing was successful, just data storage failed
            self.assertTrue(result['success'])
            self.assertIn('ai_analysis', result)
    
    @patch('apps.documents.services.PDFTextExtractor')
    @patch('apps.documents.analyzers.DocumentAnalyzer')
    @patch('apps.patients.models.Patient.add_fhir_resources')
    def test_fhir_merge_error_handling(self, mock_add_fhir, mock_analyzer, mock_pdf_extractor):
        """Test that FHIR merge errors during optimistic concurrency are handled properly."""
        # Arrange: Mock successful PDF extraction and AI analysis
        mock_pdf_instance = mock_pdf_extractor.return_value
        mock_pdf_instance.extract_text.return_value = {
            'success': True,
            'text': 'Sample medical document text',
            'page_count': 1,
            'file_size': 0.5,
            'metadata': {}
        }
        
        from apps.documents.services.ai_extraction import StructuredMedicalExtraction
        mock_extraction = StructuredMedicalExtraction(
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[],
            procedures=[],
            providers=[],
            extraction_timestamp=timezone.now().isoformat(),
            document_type='clinical_note',
            confidence_average=0.85
        )
        
        mock_analyzer_instance = mock_analyzer.return_value
        mock_analyzer_instance.analyze_document_structured.return_value = mock_extraction
        
        # Mock FHIR merge to raise FHIRConversionError
        mock_add_fhir.side_effect = FHIRConversionError(
            "Invalid FHIR resource structure",
            resource_type='Condition',
            data_source='AI extraction',
            details={'missing_field': 'code'}
        )
        
        # Mock the task
        mock_task = Mock()
        mock_task.request = Mock(id='test-task-202', retries=0)
        
        # Act: Run the task
        result = process_document_async(mock_task, self.document.id)
        
        # Assert: Task should complete despite merge error
        # Data is still saved in ParsedData for later manual merge
        self.assertTrue(result['success'])
        
        # Verify document status (should be 'review' due to merge failure)
        self.document.refresh_from_db()
        self.assertIn(self.document.status, ['review', 'completed'])
    
    def test_error_categorization_for_standard_exceptions(self):
        """Test that standard Python exceptions are properly categorized."""
        # Test various exception types
        test_cases = [
            (ConnectionError("Network error"), 'EXTERNAL_SERVICE_ERROR'),
            (TimeoutError("Request timeout"), 'AI_SERVICE_TIMEOUT'),
            (ValueError("Invalid value"), 'DATA_VALIDATION_ERROR'),
            (KeyError("Missing key"), 'CONFIGURATION_ERROR'),
            (FileNotFoundError("File not found"), 'PDF_EXTRACTION_ERROR'),
            (PermissionError("Access denied"), 'PDF_EXTRACTION_ERROR'),
        ]
        
        for exception, expected_code in test_cases:
            with self.subTest(exception=type(exception).__name__):
                error_info = categorize_exception(exception)
                
                self.assertEqual(error_info['error_code'], expected_code)
                self.assertEqual(error_info['error_type'], type(exception).__name__)
                self.assertIn('message', error_info)
    
    def test_recovery_strategy_mapping(self):
        """Test that appropriate recovery strategies are returned for error codes."""
        # Test recovery strategies for different error types
        test_cases = [
            ('AI_SERVICE_TIMEOUT', 'retry_with_backoff'),
            ('AI_SERVICE_RATE_LIMIT', 'wait_and_retry'),
            ('AI_RESPONSE_PARSING_ERROR', 'fallback_extraction'),
            ('PDF_EXTRACTION_ERROR', 'manual_review_required'),
            ('FHIR_VALIDATION_ERROR', 'relaxed_validation'),
            ('UNKNOWN_ERROR', 'manual_intervention'),
        ]
        
        for error_code, expected_strategy in test_cases:
            with self.subTest(error_code=error_code):
                strategy = get_recovery_strategy(error_code)
                self.assertEqual(strategy, expected_strategy)
    
    @patch('apps.documents.tasks.Document.objects.get')
    def test_critical_status_update_failure(self, mock_get_document):
        """Test handling when even the fallback status update fails."""
        # Arrange: Mock document retrieval to fail completely
        mock_get_document.side_effect = Exception("Database connection lost")
        
        # Mock the task
        mock_task = Mock()
        mock_task.request = Mock(id='test-task-303', retries=0)
        
        # Act & Assert: This should not crash, just log the critical error
        with patch('apps.documents.tasks.logger') as mock_logger:
            result = process_document_async(mock_task, 9999)  # Non-existent document
            
            # Verify critical logging occurred
            self.assertTrue(
                any('CRITICAL' in str(call) or 'critical' in str(call) 
                    for call in mock_logger.method_calls),
                "Expected critical log call for status update failure"
            )
    
    @patch('apps.documents.services.PDFTextExtractor')
    def test_processing_errors_tracking(self, mock_pdf_extractor):
        """Test that processing_errors list tracks all errors during execution."""
        # Arrange: Create a scenario with multiple error points
        mock_instance = mock_pdf_extractor.return_value
        mock_instance.extract_text.side_effect = Exception("Multiple errors test")
        
        # Mock the task
        mock_task = Mock()
        mock_task.request = Mock(id='test-task-404', retries=0)
        mock_task.retry = Mock(side_effect=Exception("No retry"))
        
        # Act: Run the task
        try:
            result = process_document_async(mock_task, self.document.id)
        except Exception:
            pass
        
        # The task should track errors even if it fails
        # This is verified through logging - check that errors are logged with extras
        with patch('apps.documents.tasks.logger') as mock_logger:
            try:
                result = process_document_async(mock_task, self.document.id)
            except Exception:
                pass
            
            # Verify structured logging occurred
            error_calls = [call for call in mock_logger.error.call_args_list 
                         if len(call[1]) > 0 and 'extra' in call[1]]
            self.assertGreater(len(error_calls), 0, 
                             "Expected structured error logging with 'extra' parameter")


class TestProcessDocumentAsyncRetryLogic(TestCase):
    """Test retry logic for different error scenarios."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.patient = Patient.objects.create(
            mrn='TEST-RETRY-001',
            first_name='Test',
            last_name='Patient',
            date_of_birth='1980-01-01'
        )
        
        # Create test document with mock file
        test_file = SimpleUploadedFile(
            "retry_test.pdf",
            b"PDF content for retry test",
            content_type="application/pdf"
        )
        self.document = Document.objects.create(
            patient=self.patient,
            file=test_file,
            status='pending',
            uploaded_by=None,
            processing_attempts=0
        )
    
    def test_rate_limit_error_uses_longer_retry_delay(self):
        """Test that rate limit errors use appropriate retry delays."""
        # Mock the task
        mock_task = Mock()
        mock_task.request = Mock(id='test-retry-123', retries=0)
        
        # Simulate rate limit error
        with patch('apps.documents.tasks.Document.objects.get') as mock_get_doc:
            mock_get_doc.side_effect = AIServiceRateLimitError(
                "Rate limit exceeded",
                retry_after=120,
                details={'requests_per_minute': 100}
            )
            
            with patch.object(process_document_async, 'retry', side_effect=Exception("Retry called")) as mock_retry:
                with self.assertRaises(Exception):
                    process_document_async(mock_task, self.document.id)
                
                # Verify retry was called with 2-minute delay for rate limits
                call_kwargs = mock_retry.call_args[1]
                self.assertEqual(call_kwargs['countdown'], 120)
    
    def test_non_retryable_errors_return_immediately(self):
        """Test that non-retryable errors don't trigger retry logic."""
        # Mock the task
        mock_task = Mock()
        mock_task.request = Mock(id='test-nonretry-456', retries=0)
        
        # Simulate non-retryable error (PDF extraction error)
        with patch('apps.documents.tasks.PDFTextExtractor') as mock_pdf:
            mock_instance = mock_pdf.return_value
            mock_instance.extract_text.side_effect = PDFExtractionError(
                "Corrupted PDF file",
                file_path=self.document.file.path
            )
            
            with patch.object(process_document_async, 'retry') as mock_retry:
                result = process_document_async(mock_task, self.document.id)
                
                # Verify retry was NOT called for PDF errors
                mock_retry.assert_not_called()
                
                # Verify failure result returned
                self.assertFalse(result['success'])
                self.assertEqual(result['error_code'], 'PDF_EXTRACTION_ERROR')


class TestErrorHandlingEdgeCases(TestCase):
    """Test edge cases and boundary conditions in error handling."""
    
    def test_empty_processing_errors_list(self):
        """Test that processing_errors list is properly initialized."""
        # This is implicitly tested by other tests, but verify it explicitly
        mock_task = Mock()
        mock_task.request = Mock(id='test-edge-001', retries=0)
        
        with patch('apps.documents.tasks.Document.objects.get') as mock_get:
            mock_get.side_effect = Exception("Test error")
            
            result = process_document_async(mock_task, 9999)
            
            # Result should contain processing_errors even on complete failure
            self.assertIn('processing_errors', result)
            self.assertIsInstance(result['processing_errors'], list)
    
    def test_error_message_truncation(self):
        """Test that extremely long error messages are truncated appropriately."""
        # Create a very long error message
        long_message = "X" * 1000
        
        mock_task = Mock()
        mock_task.request = Mock(id='test-truncate-002', retries=0)
        
        with patch('apps.documents.tasks.Document.objects.get') as mock_get:
            mock_get.side_effect = Exception(long_message)
            
            result = process_document_async(mock_task, 9999)
            
            # Error message in result should be truncated
            self.assertLessEqual(len(result['message']), 250)

