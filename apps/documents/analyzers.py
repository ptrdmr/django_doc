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
        Extract text from a document file.
        
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
        self.logger.info(f"Starting text extraction for {document_path}")
        
        try:
            # Import here to avoid circular imports
            # Import from the services.py module (not the services/ package)
            extractor = self._get_pdf_extractor()
            result = extractor.extract_text(document_path)
            
            if result['success']:
                self.logger.info(f"Text extraction successful: {len(result['text'])} characters, "
                               f"{result.get('page_count', 0)} pages")
            else:
                self.logger.error(f"Text extraction failed: {result.get('error_message', 'Unknown error')}")
                self.stats['errors_encountered'].append(f"Text extraction: {result.get('error_message', 'Unknown error')}")
            
            return result
            
        except Exception as e:
            error_msg = f"Text extraction error: {str(e)}"
            self.logger.error(error_msg)
            self.stats['errors_encountered'].append(error_msg)
            
            return {
                'success': False,
                'text': '',
                'error_message': error_msg,
                'metadata': {}
            }
    
    def analyze_document_structured(self, document_content: str, context: Optional[str] = None) -> StructuredMedicalExtraction:
        """
        Analyze document content and return structured medical data using new AI extraction.
        
        This is the new method that leverages the instructor-based AI extraction service
        for structured Pydantic model responses.
        
        Args:
            document_content: The text content from the document
            context: Optional context (e.g., "Emergency Department Report")
            
        Returns:
            StructuredMedicalExtraction object with all extracted medical data
            
        Raises:
            Exception: If extraction fails completely
        """
        self.logger.info(f"Starting structured analysis for session {self.processing_session}")
        self.stats['extraction_attempts'] += 1
        
        try:
            # Use the new structured extraction service
            structured_data = extract_medical_data_structured(document_content, context)
            
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
                f"Structured extraction completed: {total_items} total items extracted "
                f"(confidence: {structured_data.confidence_average:.3f})"
            )
            
            # Detailed breakdown
            self.logger.info(
                f"Extraction breakdown - Conditions: {len(structured_data.conditions)}, "
                f"Medications: {len(structured_data.medications)}, "
                f"Vital Signs: {len(structured_data.vital_signs)}, "
                f"Lab Results: {len(structured_data.lab_results)}, "
                f"Procedures: {len(structured_data.procedures)}, "
                f"Providers: {len(structured_data.providers)}"
            )
            
            return structured_data
            
        except Exception as e:
            error_msg = f"Structured analysis failed: {str(e)}"
            self.logger.error(error_msg)
            self.stats['errors_encountered'].append(error_msg)
            raise
    
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
