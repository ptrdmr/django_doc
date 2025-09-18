"""
DocumentAnalyzer - Refactored Core Document Processing Pipeline

This module contains the refactored DocumentAnalyzer class focused solely on text extraction
and structured AI processing. FHIR conversion has been moved to apps/fhir/converters.py
as part of Task 34 pipeline refactoring.

Key Features:
- Clean text extraction from uploaded documents
- Structured medical data extraction using AI services
- Error handling and graceful degradation
- Backward compatibility with existing API
- Comprehensive logging for audit trails

Author: Task 34.2 - Refactor DocumentAnalyzer class
Date: 2025-09-17 07:19:02
"""

import logging
import time
from typing import Dict, Any, Optional, List, Union
from django.conf import settings
from uuid import uuid4

# Import the new structured AI extraction service
from .services.ai_extraction import (
    extract_medical_data,
    extract_medical_data_structured,
    StructuredMedicalExtraction
)

# Import custom exceptions for enhanced error handling
from .exceptions import (
    DocumentProcessingError,
    PDFExtractionError,
    AIExtractionError,
    AIServiceTimeoutError,
    AIServiceRateLimitError,
    ConfigurationError,
    categorize_exception,
    get_recovery_strategy
)

logger = logging.getLogger(__name__)


class DocumentAnalyzer:
    """
    Refactored DocumentAnalyzer focused on text extraction and structured AI processing.
    
    This class handles:
    1. Text extraction from various document formats
    2. Structured medical data extraction using AI
    3. Error handling and graceful degradation
    4. Comprehensive logging for audit trails
    
    FHIR conversion has been moved to apps/fhir/converters.py for better separation of concerns.
    """
    
    def __init__(self, document=None):
        """
        Initialize the DocumentAnalyzer.
        
        Args:
            document: Optional Document instance for context and audit logging
        """
        self.logger = logging.getLogger(__name__)
        self.document = document
        self.processing_session = uuid4()  # Unique session ID for tracking
        
        self.logger.info(f"DocumentAnalyzer initialized for session {self.processing_session}")
        
        # Track processing statistics for this session
        self.stats = {
            'session_id': str(self.processing_session),
            'document_id': document.id if document else None,
            'start_time': time.time(),
            'extraction_attempts': 0,
            'successful_extractions': 0,
            'errors_encountered': []
        }
    
    def extract_text(self, document_path: str) -> Dict[str, Any]:
        """
        Extract text from a document file with comprehensive error handling.
        
        Currently supports PDF files via the existing PDFTextExtractor.
        Future enhancements could add support for other document formats.
        
        Args:
            document_path: Path to the document file
            
        Returns:
            Dict containing extraction results with keys:
            - success: bool
            - text: str (extracted text)
            - error_message: str (if extraction failed)
            - metadata: dict (file information)
        """
        session_id = str(self.processing_session)
        self.logger.info(f"[{session_id}] Starting text extraction for {document_path}")
        
        try:
            # Validate input
            if not document_path:
                raise PDFExtractionError(
                    "Document path is required for text extraction",
                    file_path=document_path,
                    details={'session_id': session_id}
                )
            
            # Validate file existence
            import os
            if not os.path.exists(document_path):
                raise PDFExtractionError(
                    f"Document file not found: {document_path}",
                    file_path=document_path,
                    details={'session_id': session_id, 'file_exists': False}
                )
            
            # Check file size
            file_size = os.path.getsize(document_path)
            if file_size == 0:
                raise PDFExtractionError(
                    "Document file is empty",
                    file_path=document_path,
                    details={'session_id': session_id, 'file_size': file_size}
                )
            
            # Log file information
            self.logger.info(f"[{session_id}] Processing file: {os.path.basename(document_path)} "
                           f"({file_size / 1024:.1f} KB)")
            
            # Perform text extraction
            start_time = time.time()
            
            try:
                extractor = self._get_pdf_extractor()
                result = extractor.extract_text(document_path)
                
                extraction_time = time.time() - start_time
                
                # Enhanced result validation
                if not result.get('success', False):
                    error_msg = result.get('error_message', 'Unknown PDF extraction error')
                    raise PDFExtractionError(
                        f"PDF extraction failed: {error_msg}",
                        file_path=document_path,
                        details={
                            'session_id': session_id,
                            'file_size': file_size,
                            'extraction_time': extraction_time,
                            'extractor_result': result
                        }
                    )
                
                # Validate extracted text
                extracted_text = result.get('text', '')
                if not extracted_text or not extracted_text.strip():
                    raise PDFExtractionError(
                        "PDF extraction returned no text content",
                        file_path=document_path,
                        details={
                            'session_id': session_id,
                            'file_size': file_size,
                            'page_count': result.get('page_count', 0),
                            'extraction_time': extraction_time
                        }
                    )
                
                # Success logging
                self.logger.info(f"[{session_id}] Text extraction successful: {len(extracted_text)} characters, "
                               f"{result.get('page_count', 0)} pages in {extraction_time:.2f}s")
                
                # Update stats
                self.stats['successful_extractions'] += 1
                
                return result
                
            except PDFExtractionError:
                raise
            except ImportError as import_error:
                raise ConfigurationError(
                    f"PDF extractor not available: {str(import_error)}",
                    details={'session_id': session_id, 'missing_component': 'PDFTextExtractor'}
                )
            except Exception as extractor_error:
                error_info = categorize_exception(extractor_error)
                raise PDFExtractionError(
                    f"Unexpected PDF extraction error: {str(extractor_error)}",
                    file_path=document_path,
                    details={
                        'session_id': session_id,
                        'file_size': file_size,
                        'error_category': error_info.get('category', 'unknown'),
                        'error_type': type(extractor_error).__name__
                    }
                ) from extractor_error
            
        except (PDFExtractionError, ConfigurationError) as expected_error:
            # Log and track expected errors
            self.logger.error(f"[{session_id}] {expected_error}")
            self.stats['errors_encountered'].append({
                'step': 'text_extraction',
                'error_type': type(expected_error).__name__,
                'error_code': expected_error.error_code if hasattr(expected_error, 'error_code') else None,
                'error_message': str(expected_error),
                'timestamp': time.time(),
                'recovery_strategy': get_recovery_strategy(expected_error.error_code) if hasattr(expected_error, 'error_code') else 'manual_intervention'
            })
            
            # Return structured error response for backward compatibility
            return {
                'success': False,
                'text': '',
                'error_message': str(expected_error),
                'metadata': {
                    'file_path': document_path,
                    'error_type': type(expected_error).__name__,
                    'error_code': expected_error.error_code if hasattr(expected_error, 'error_code') else None,
                    'session_id': session_id
                }
            }
        except Exception as unexpected_error:
            # Handle completely unexpected errors
            error_info = categorize_exception(unexpected_error)
            self.logger.error(f"[{session_id}] Unexpected error during text extraction: {unexpected_error}", 
                            exc_info=True)
            
            self.stats['errors_encountered'].append({
                'step': 'text_extraction',
                'error_type': type(unexpected_error).__name__,
                'error_message': str(unexpected_error),
                'timestamp': time.time(),
                'error_category': error_info.get('category', 'unknown')
            })
            
            return {
                'success': False,
                'text': '',
                'error_message': f"Unexpected text extraction error: {str(unexpected_error)}",
                'metadata': {
                    'file_path': document_path,
                    'error_type': type(unexpected_error).__name__,
                    'session_id': session_id,
                    'error_category': error_info.get('category', 'unknown')
                }
            }
    
    def analyze_document_structured(self, document_content: str, context: Optional[str] = None) -> StructuredMedicalExtraction:
        """
        Analyze document content and return structured medical data using new AI extraction.
        
        This method leverages the instructor-based AI extraction service for structured 
        Pydantic model responses with comprehensive error handling and recovery.
        
        Args:
            document_content: The text content from the document
            context: Optional context (e.g., "Emergency Department Report")
            
        Returns:
            StructuredMedicalExtraction object with all extracted medical data
            
        Raises:
            AIExtractionError: For AI service-related failures
            AIServiceTimeoutError: For timeout issues
            AIServiceRateLimitError: For rate limiting issues
            ConfigurationError: For missing API keys or service configuration
            DocumentProcessingError: For general processing failures
        """
        session_id = str(self.processing_session)
        self.logger.info(f"[{session_id}] Starting structured analysis")
        self.stats['extraction_attempts'] += 1
        
        try:
            # Input validation
            if not document_content or not document_content.strip():
                raise AIExtractionError(
                    "Document content is empty or invalid",
                    details={
                        'session_id': session_id,
                        'content_length': len(document_content) if document_content else 0,
                        'context': context
                    }
                )
            
            # Log analysis details
            content_length = len(document_content)
            self.logger.info(f"[{session_id}] Analyzing {content_length} characters of text content")
            
            if context:
                self.logger.info(f"[{session_id}] Using context: {context}")
            
            # Use the new structured extraction service with comprehensive error handling
            start_time = time.time()
            
            try:
                structured_data = extract_medical_data_structured(document_content, context)
                
                analysis_time = time.time() - start_time
                
                # Validate returned data
                if not structured_data:
                    raise AIExtractionError(
                        "AI extraction returned no structured data",
                        details={
                            'session_id': session_id,
                            'content_length': content_length,
                            'context': context,
                            'analysis_time': analysis_time
                        }
                    )
                
                # Validate data structure
                if not hasattr(structured_data, 'conditions'):
                    raise AIExtractionError(
                        "Invalid structured data format returned",
                        details={
                            'session_id': session_id,
                            'data_type': type(structured_data).__name__,
                            'analysis_time': analysis_time
                        }
                    )
                
                self.stats['successful_extractions'] += 1
                
                # Log extraction summary
                total_items = (
                    len(structured_data.conditions) + 
                    len(structured_data.medications) + 
                    len(structured_data.vital_signs) + 
                    len(structured_data.lab_results) + 
                    len(structured_data.procedures) + 
                    len(structured_data.providers)
                )
                
                self.logger.info(
                    f"[{session_id}] Structured extraction completed in {analysis_time:.2f}s: "
                    f"{total_items} total items extracted (confidence: {structured_data.confidence_average:.3f})"
                )
                
                # Detailed breakdown
                self.logger.info(
                    f"[{session_id}] Extraction breakdown - Conditions: {len(structured_data.conditions)}, "
                    f"Medications: {len(structured_data.medications)}, "
                    f"Vital Signs: {len(structured_data.vital_signs)}, "
                    f"Lab Results: {len(structured_data.lab_results)}, "
                    f"Procedures: {len(structured_data.procedures)}, "
                    f"Providers: {len(structured_data.providers)}"
                )
                
                return structured_data
                
            except (AIExtractionError, AIServiceTimeoutError, AIServiceRateLimitError) as ai_error:
                # Re-raise specific AI errors to allow proper handling upstream
                self.logger.error(f"[{session_id}] AI extraction failed: {ai_error}")
                self.stats['errors_encountered'].append({
                    'step': 'structured_analysis',
                    'error_type': type(ai_error).__name__,
                    'error_message': str(ai_error),
                    'timestamp': time.time(),
                    'recovery_strategy': get_recovery_strategy(ai_error.error_code) if hasattr(ai_error, 'error_code') else 'retry_later'
                })
                raise
            except ImportError as import_error:
                raise ConfigurationError(
                    f"AI extraction service not available: {str(import_error)}",
                    details={'session_id': session_id, 'missing_component': 'StructuredMedicalExtraction'}
                )
            except Exception as unexpected_error:
                error_info = categorize_exception(unexpected_error)
                self.logger.error(f"[{session_id}] Unexpected error in structured analysis: {unexpected_error}", 
                                exc_info=True)
                
                self.stats['errors_encountered'].append({
                    'step': 'structured_analysis',
                    'error_type': type(unexpected_error).__name__,
                    'error_message': str(unexpected_error),
                    'timestamp': time.time(),
                    'error_category': error_info.get('category', 'unknown')
                })
                
                raise AIExtractionError(
                    f"Unexpected error during structured analysis: {str(unexpected_error)}",
                    details={
                        'session_id': session_id,
                        'content_length': content_length,
                        'context': context,
                        'error_category': error_info.get('category', 'unknown'),
                        'error_type': type(unexpected_error).__name__
                    }
                ) from unexpected_error
                
        except (AIExtractionError, ConfigurationError) as expected_error:
            # Log and track expected errors
            self.logger.error(f"[{session_id}] {expected_error}")
            self.stats['errors_encountered'].append({
                'step': 'structured_analysis',
                'error_type': type(expected_error).__name__,
                'error_code': expected_error.error_code if hasattr(expected_error, 'error_code') else None,
                'error_message': str(expected_error),
                'timestamp': time.time(),
                'recovery_strategy': get_recovery_strategy(expected_error.error_code) if hasattr(expected_error, 'error_code') else 'manual_intervention'
            })
            raise
        except Exception as unexpected_error:
            # Handle completely unexpected errors
            error_info = categorize_exception(unexpected_error)
            self.logger.error(f"[{session_id}] Unexpected error in analysis setup: {unexpected_error}", 
                            exc_info=True)
            
            self.stats['errors_encountered'].append({
                'step': 'structured_analysis_setup',
                'error_type': type(unexpected_error).__name__,
                'error_message': str(unexpected_error),
                'timestamp': time.time(),
                'error_category': error_info.get('category', 'unknown')
            })
            
            raise DocumentProcessingError(
                f"Failed to perform structured analysis: {str(unexpected_error)}",
                details={
                    'session_id': session_id,
                    'error_category': error_info.get('category', 'unknown'),
                    'error_type': type(unexpected_error).__name__
                }
            ) from unexpected_error
    
    def analyze(self, document) -> Dict[str, Any]:
        """
        Legacy-compatible analyze method for backward compatibility.
        
        This method maintains the existing API while using the new structured extraction
        internally. It extracts text from the document and processes it with AI.
        
        Args:
            document: Document instance or file path
            
        Returns:
            Dict containing analysis results in legacy format for compatibility
        """
        self.logger.info(f"Starting legacy-compatible analysis for session {self.processing_session}")
        
        try:
            # Handle different input types
            if hasattr(document, 'file') and hasattr(document.file, 'path'):
                # Django Document model
                document_path = document.file.path
                context = getattr(document, 'document_type', None)
            elif isinstance(document, str):
                # File path string
                document_path = document
                context = None
            else:
                raise ValueError(f"Unsupported document type: {type(document)}")
            
            # Extract text from document
            text_result = self.extract_text(document_path)
            
            if not text_result['success']:
                return {
                    'success': False,
                    'error': text_result['error_message'],
                    'fields': []
                }
            
            # Extract medical data using the legacy-compatible method
            extracted_data = self.extract_medical_data(text_result['text'], context)
            
            # Return in legacy format
            return {
                'success': True,
                'fields': self._convert_to_legacy_fields(extracted_data),
                'processing_method': 'structured_extraction',
                'model_used': 'claude_openai_fallback',
                'usage': {
                    'total_tokens': 0,  # Not tracked in new system
                    'prompt_tokens': 0,
                    'completion_tokens': 0
                },
                'extraction_confidence': extracted_data.get('extraction_confidence', 0.0),
                'total_items_extracted': extracted_data.get('total_items_extracted', 0)
            }
            
        except Exception as e:
            error_msg = f"Document analysis failed: {str(e)}"
            self.logger.error(error_msg)
            self.stats['errors_encountered'].append(error_msg)
            
            return {
                'success': False,
                'error': error_msg,
                'fields': []
            }
    
    def extract_medical_data(self, text: str, context: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract medical data from text using the new AI extraction service.
        
        This method uses the legacy-compatible extraction function while leveraging
        the new structured extraction internally.
        
        Args:
            text: The document text to analyze
            context: Optional context about the document type
            
        Returns:
            Dict with extracted medical data in legacy format
        """
        self.logger.info(f"Extracting medical data for session {self.processing_session}")
        self.stats['extraction_attempts'] += 1
        
        try:
            # Use the new AI extraction service (legacy-compatible mode)
            extracted_data = extract_medical_data(text, context)
            
            self.stats['successful_extractions'] += 1
            
            self.logger.info(
                f"Medical data extraction completed: {extracted_data.get('total_items_extracted', 0)} items "
                f"(confidence: {extracted_data.get('extraction_confidence', 0.0):.3f})"
            )
            
            return extracted_data
            
        except Exception as e:
            error_msg = f"Medical data extraction failed: {str(e)}"
            self.logger.error(error_msg)
            self.stats['errors_encountered'].append(error_msg)
            
            # Return empty result for graceful degradation
            return {
                'diagnoses': [],
                'medications': [],
                'procedures': [],
                'lab_results': [],
                'vital_signs': [],
                'providers': [],
                'extraction_confidence': 0.0,
                'total_items_extracted': 0,
                'error': error_msg
            }
    
    def _get_pdf_extractor(self):
        """
        Get PDFTextExtractor instance. Separated for easier testing.
        
        Returns:
            PDFTextExtractor instance
        """
        # Import from the services.py module (not the services/ package)
        import importlib.util
        import os
        spec = importlib.util.spec_from_file_location("services_py", os.path.join(os.path.dirname(__file__), "services.py"))
        services_py = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(services_py)
        return services_py.PDFTextExtractor()
    
    def _convert_to_legacy_fields(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert extracted data to legacy field format for backward compatibility.
        
        Args:
            extracted_data: Dictionary from extract_medical_data
            
        Returns:
            List of field dictionaries in legacy format
        """
        fields = []
        
        # Convert diagnoses
        for diagnosis in extracted_data.get('diagnoses', []):
            fields.append({
                'label': 'diagnosis',
                'value': diagnosis,
                'confidence': extracted_data.get('extraction_confidence', 0.8),
                'category': 'medical_condition'
            })
        
        # Convert medications
        for medication in extracted_data.get('medications', []):
            fields.append({
                'label': 'medication',
                'value': medication,
                'confidence': extracted_data.get('extraction_confidence', 0.8),
                'category': 'medication'
            })
        
        # Convert procedures
        for procedure in extracted_data.get('procedures', []):
            fields.append({
                'label': 'procedure',
                'value': procedure,
                'confidence': extracted_data.get('extraction_confidence', 0.8),
                'category': 'procedure'
            })
        
        # Convert lab results
        for lab_result in extracted_data.get('lab_results', []):
            if isinstance(lab_result, dict):
                fields.append({
                    'label': 'lab_result',
                    'value': f"{lab_result.get('test', '')} {lab_result.get('value', '')} {lab_result.get('unit', '')}".strip(),
                    'confidence': extracted_data.get('extraction_confidence', 0.8),
                    'category': 'lab_result'
                })
        
        # Convert vital signs
        for vital_sign in extracted_data.get('vital_signs', []):
            if isinstance(vital_sign, dict):
                fields.append({
                    'label': 'vital_sign',
                    'value': f"{vital_sign.get('type', '')} {vital_sign.get('value', '')} {vital_sign.get('unit', '')}".strip(),
                    'confidence': extracted_data.get('extraction_confidence', 0.8),
                    'category': 'vital_sign'
                })
        
        # Convert providers
        for provider in extracted_data.get('providers', []):
            if isinstance(provider, dict):
                fields.append({
                    'label': 'provider',
                    'value': f"{provider.get('name', '')} ({provider.get('specialty', '')})".strip(),
                    'confidence': extracted_data.get('extraction_confidence', 0.8),
                    'category': 'provider'
                })
        
        self.logger.info(f"Converted {len(fields)} items to legacy field format")
        return fields
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """
        Get processing statistics for this analyzer session.
        
        Returns:
            Dict with processing statistics and metrics
        """
        current_time = time.time()
        self.stats['total_processing_time'] = current_time - self.stats['start_time']
        self.stats['success_rate'] = (
            self.stats['successful_extractions'] / max(self.stats['extraction_attempts'], 1)
        )
        
        return self.stats.copy()
    
    def __del__(self):
        """Log session summary when analyzer is destroyed."""
        if hasattr(self, 'stats') and self.stats:
            stats = self.get_processing_stats()
            self.logger.info(
                f"DocumentAnalyzer session {self.processing_session} completed: "
                f"{stats['successful_extractions']}/{stats['extraction_attempts']} successful extractions "
                f"in {stats['total_processing_time']:.2f}s"
            )
            
            if stats['errors_encountered']:
                self.logger.warning(f"Errors in session {self.processing_session}: {stats['errors_encountered']}")


# Export the main class
__all__ = ['DocumentAnalyzer']
