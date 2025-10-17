"""
PDF text extraction services for medical document processing.
Handles robust text extraction from PDF files with error recovery.
"""

import os
import logging
import pdfplumber
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import re
from uuid import uuid4
from django.utils import timezone
import base64
import json
from django.db import transaction
from django.core.exceptions import ValidationError
from apps.core.date_parser import ClinicalDateParser

logger = logging.getLogger(__name__)


class DocumentProcessingError(Exception):
    """Custom exception for document processing failures"""
    pass


class PDFTextExtractor:
    """
    Service class for extracting text from PDF documents.
    Designed for medical documents with proper error handling.
    """
    
    def __init__(self):
        """Initialize the PDF text extractor"""
        self.supported_extensions = ['.pdf']
        self.max_file_size_mb = 50  # Maximum file size in MB
        
    def extract_text(self, file_path: str) -> Dict[str, any]:
        """
        Extract text from a PDF file with comprehensive error handling.
        
        Args:
            file_path (str): Path to the PDF file
            
        Returns:
            Dict containing:
                - success (bool): Whether extraction succeeded
                - text (str): Extracted text content
                - page_count (int): Number of pages processed
                - file_size (float): File size in MB
                - error_message (str): Error details if failed
                - metadata (dict): Additional file metadata
        """
        try:
            # Validate file existence and type
            validation_result = self._validate_file(file_path)
            if not validation_result['valid']:
                return {
                    'success': False,
                    'text': '',
                    'page_count': 0,
                    'file_size': 0,
                    'error_message': validation_result['error'],
                    'metadata': {}
                }
            
            # Extract text using pdfplumber
            with pdfplumber.open(file_path) as pdf:
                extracted_text = []
                metadata = {
                    'title': pdf.metadata.get('Title', ''),
                    'author': pdf.metadata.get('Author', ''),
                    'creator': pdf.metadata.get('Creator', ''),
                    'creation_date': pdf.metadata.get('CreationDate', ''),
                }
                
                # Process each page
                for page_num, page in enumerate(pdf.pages, 1):
                    try:
                        page_text = page.extract_text()
                        if page_text:
                            # Clean and format the text
                            cleaned_text = self._clean_text(page_text)
                            if cleaned_text.strip():
                                extracted_text.append(f"--- Page {page_num} ---\n{cleaned_text}")
                        
                    except Exception as page_error:
                        logger.warning(f"Failed to extract text from page {page_num}: {page_error}")
                        # Continue with other pages
                        continue
                
                # Combine all pages
                full_text = '\n\n'.join(extracted_text)
                page_count = len(pdf.pages)
                
                # Get file size
                file_size = os.path.getsize(file_path) / (1024 * 1024)  # Convert to MB
                
                # OCR fallback: If no embedded text found, try OCR extraction
                extraction_method = 'embedded_text'
                if not full_text.strip():
                    logger.warning(f"No embedded text found in {file_path}, attempting OCR extraction")
                    ocr_text = self.extract_with_ocr(file_path, page_count)
                    if ocr_text:
                        full_text = ocr_text
                        extraction_method = 'ocr'
                        logger.info(f"OCR extraction recovered {len(ocr_text)} characters")
                    else:
                        logger.error(f"Both embedded text and OCR extraction failed for {file_path}")
                
                # Add extraction method to metadata
                metadata['extraction_method'] = extraction_method
                
                result = {
                    'success': True,
                    'text': full_text,
                    'page_count': page_count,
                    'file_size': round(file_size, 2),
                    'error_message': '',
                    'metadata': metadata
                }
                
                logger.info(f"Successfully extracted text from PDF: {file_path} "
                           f"({page_count} pages, {len(full_text)} characters, method: {extraction_method})")
                
                return result
                
        except Exception as e:
            error_msg = f"PDF text extraction failed: {str(e)}"
            logger.error(f"Error extracting text from {file_path}: {e}")
            
            return {
                'success': False,
                'text': '',
                'page_count': 0,
                'file_size': 0,
                'error_message': error_msg,
                'metadata': {}
            }
    
    def _validate_file(self, file_path: str) -> Dict[str, any]:
        """
        Validate PDF file before processing.
        
        Args:
            file_path (str): Path to the file
            
        Returns:
            Dict with validation result and error message if any
        """
        try:
            path = Path(file_path)
            
            # Check if file exists
            if not path.exists():
                return {'valid': False, 'error': f"File not found: {file_path}"}
            
            # Check file extension
            if path.suffix.lower() not in self.supported_extensions:
                return {'valid': False, 'error': f"Unsupported file type: {path.suffix}"}
            
            # Check file size
            file_size_mb = path.stat().st_size / (1024 * 1024)
            if file_size_mb > self.max_file_size_mb:
                return {'valid': False, 
                       'error': f"File too large: {file_size_mb:.1f}MB (max {self.max_file_size_mb}MB)"}
            
            # Try to open the PDF to check if it's valid
            try:
                with pdfplumber.open(file_path) as pdf:
                    # Just check if we can access the first page
                    if len(pdf.pages) == 0:
                        return {'valid': False, 'error': "PDF file appears to be empty"}
            except Exception as pdf_error:
                return {'valid': False, 'error': f"Invalid or corrupted PDF: {str(pdf_error)}"}
            
            return {'valid': True, 'error': ''}
            
        except Exception as e:
            return {'valid': False, 'error': f"File validation error: {str(e)}"}
    
    def _clean_text(self, text: str) -> str:
        """
        Clean and format extracted text for medical document processing.
        
        Args:
            text (str): Raw extracted text
            
        Returns:
            str: Cleaned and formatted text
        """
        if not text:
            return ""
        
        # Remove excessive whitespace and normalize line breaks
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # Multiple line breaks to double
        text = re.sub(r'[ \t]+', ' ', text)  # Multiple spaces/tabs to single space
        text = re.sub(r' *\n *', '\n', text)  # Remove spaces around line breaks
        
        # Remove common PDF artifacts
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)  # Remove control chars
        text = re.sub(r'�', ' ', text)  # Remove replacement characters
        
        # Fix common spacing issues around punctuation
        text = re.sub(r'([.!?])\s*([A-Z])', r'\1 \2', text)  # Ensure space after sentence end
        text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)  # Add space between concatenated words
        
        # Clean up medical document specific patterns
        text = re.sub(r'(\d+)\s*[-/]\s*(\d+)\s*[-/]\s*(\d+)', r'\1/\2/\3', text)  # Normalize dates
        text = re.sub(r'(\d+)\.(\d+)\.(\d+)', r'\1.\2.\3', text)  # Normalize decimal numbers
        
        return text.strip()
    
    def extract_with_ocr(self, file_path: str, page_count: int) -> str:
        """
        Extract text from scanned PDF using OCR (Tesseract).
        Used as fallback when pdfplumber finds no embedded text.
        
        Args:
            file_path: Path to PDF file
            page_count: Number of pages in PDF
            
        Returns:
            str: OCR-extracted text or empty string if OCR fails
        """
        try:
            import pytesseract
            from pdf2image import convert_from_path
            from PIL import Image
            
            logger.info(f"Starting OCR extraction for {file_path} ({page_count} pages)")
            
        except ImportError as import_error:
            logger.error(f"OCR libraries not available: {import_error}")
            logger.error("Install with: pip install pytesseract pdf2image")
            return ""
        
        try:
            # Convert PDF pages to images at 300 DPI for good text recognition
            images = convert_from_path(file_path, dpi=300)
            
            ocr_text_pages = []
            for page_num, image in enumerate(images, 1):
                try:
                    # Run Tesseract OCR on the image
                    # PSM 1 = Automatic page segmentation with OSD (best for documents)
                    page_text = pytesseract.image_to_string(
                        image,
                        lang='eng',
                        config='--psm 1'
                    )
                    
                    if page_text and page_text.strip():
                        # Clean the OCR text
                        cleaned_text = self._clean_text(page_text)
                        if cleaned_text:
                            ocr_text_pages.append(f"--- Page {page_num} (OCR) ---\n{cleaned_text}")
                            logger.info(f"OCR extracted {len(cleaned_text)} chars from page {page_num}")
                    
                except Exception as page_error:
                    logger.warning(f"OCR failed for page {page_num}: {page_error}")
                    continue
            
            # Combine all OCR pages
            full_ocr_text = '\n\n'.join(ocr_text_pages)
            
            if full_ocr_text:
                logger.info(f"OCR extraction successful: {len(full_ocr_text)} total characters from {len(ocr_text_pages)} pages")
            else:
                logger.warning(f"OCR extraction produced no text for {file_path}")
            
            return full_ocr_text
            
        except Exception as ocr_error:
            logger.error(f"OCR extraction failed for {file_path}: {ocr_error}")
            return ""
    
    def extract_text_with_layout(self, file_path: str) -> Dict[str, any]:
        """
        Extract text with layout information (tables, positions, etc.).
        This method preserves more structure for complex medical documents.
        
        Args:
            file_path (str): Path to the PDF file
            
        Returns:
            Dict containing text and layout information
        """
        try:
            validation_result = self._validate_file(file_path)
            if not validation_result['valid']:
                return {
                    'success': False,
                    'text': '',
                    'tables': [],
                    'error_message': validation_result['error']
                }
            
            with pdfplumber.open(file_path) as pdf:
                extracted_text = []
                all_tables = []
                
                for page_num, page in enumerate(pdf.pages, 1):
                    try:
                        # Extract regular text
                        page_text = page.extract_text()
                        if page_text:
                            cleaned_text = self._clean_text(page_text)
                            extracted_text.append(f"--- Page {page_num} ---\n{cleaned_text}")
                        
                        # Extract tables
                        tables = page.extract_tables()
                        for table_num, table in enumerate(tables):
                            if table:
                                all_tables.append({
                                    'page': page_num,
                                    'table_number': table_num + 1,
                                    'data': table
                                })
                        
                    except Exception as page_error:
                        logger.warning(f"Failed to process page {page_num}: {page_error}")
                        continue
                
                return {
                    'success': True,
                    'text': '\n\n'.join(extracted_text),
                    'tables': all_tables,
                    'page_count': len(pdf.pages),
                    'error_message': ''
                }
                
        except Exception as e:
            logger.error(f"Layout extraction failed for {file_path}: {e}")
            return {
                'success': False,
                'text': '',
                'tables': [],
                'error_message': f"Layout extraction failed: {str(e)}"
            } 


# ============================================================================
# AI DOCUMENT ANALYSIS SERVICE
# ============================================================================

import json
import re
import backoff
from typing import Any, Optional
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils import timezone
from apps.core.services import APIUsageMonitor, error_recovery_service, context_preservation_service

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    import openai
except ImportError:
    openai = None

# Custom Exceptions
class APIRateLimitError(Exception):
    """Custom exception for API rate limit errors to trigger Celery retries."""
    pass

def _preprocess_text(text: str) -> str:
    """
    Cleans and preprocesses the raw extracted text before sending to AI.
    - Removes excessive newlines and whitespace
    - Filters out common OCR junk and artifacts
    - Normalizes text for better AI comprehension
    """
    # Simple whitespace normalization
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'(\n\s*){2,}', '\n', text)
    
    # Add more sophisticated cleaning rules here as needed
    # e.g., removing page headers/footers, specific OCR noise patterns
    
    return text.strip()

class DocumentAnalyzer:
    """
    AI-powered medical document analysis service.
    Handles document processing with Claude and GPT fallback.
    Designed for HIPAA compliance and medical document processing.
    """
    
    def __init__(self, document=None, api_key: Optional[str] = None):
        """
        Initialize the DocumentAnalyzer with proper configuration.
        
        Args:
            document: Document instance being processed (for cost monitoring)
            api_key: Optional API key override for testing
        """
        self.logger = logging.getLogger(__name__)
        
        # Store document reference for cost monitoring
        self.document = document
        self.processing_session = uuid4()  # Unique session ID for this processing run
        
        # Initialize clinical date parser for temporal data validation
        self.date_parser = ClinicalDateParser()
        
        # Initialize error recovery tracking
        self._context_key = None
        self._attempt_count = 0
        
        # Get API keys from settings
        self.anthropic_key = api_key or getattr(settings, 'ANTHROPIC_API_KEY', None)
        self.openai_key = getattr(settings, 'OPENAI_API_KEY', None)
        
        # More forgiving for testing - just warn instead of failing
        if not self.anthropic_key and not self.openai_key:
            self.logger.warning(
                "No AI API keys configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY for full functionality"
            )
        
        # Configuration from Django settings (must be set before initializing clients)
        self.primary_model = getattr(settings, 'AI_MODEL_PRIMARY', 'claude-3-5-sonnet-20240620')
        self.fallback_model = getattr(settings, 'AI_MODEL_FALLBACK', 'gpt-4o-mini')
        self.max_tokens = getattr(settings, 'AI_MAX_TOKENS', 4096)
        self.chunk_threshold = getattr(settings, 'AI_CHUNK_THRESHOLD', 30000)  # Now properly in tokens, not chars
        self.temperature = getattr(settings, 'AI_TEMPERATURE', 0.2)
        self.request_timeout = getattr(settings, 'AI_REQUEST_TIMEOUT', 120)
        
        # Initialize clients
        self.anthropic_client = self._get_anthropic_client()
        self.openai_client = self._get_openai_client()
        
        self.logger.info(f"DocumentAnalyzer initialized with primary model: {self.primary_model}")
    
    def _get_anthropic_client(self):
        """Initialize Anthropic client with timeout protection"""
        if self.anthropic_key and anthropic:
            try:
                # Use the current Anthropic client class
                return anthropic.Anthropic(
                    api_key=self.anthropic_key
                )
            except Exception as e:
                self.logger.warning(f"Failed to initialize Anthropic client: {e}")
                return None
        return None
    
    def _get_openai_client(self):
        """Initialize OpenAI client with timeout protection"""
        if self.openai_key and openai:
            try:
                return openai.OpenAI(
                    api_key=self.openai_key,
                    timeout=5.0  # 5 second timeout for initialization
                )
            except Exception as e:
                self.logger.warning(f"Failed to initialize OpenAI client: {e}")
                return None
        return None
    
    def analyze_document(self, document_content: str, context: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze medical document content using AI.
        
        Args:
            document_content: The text content from the document
            context: Optional context (e.g., "Emergency Department Report")
            
        Returns:
            Dict containing analysis results
        """
        try:
            clean_content = _preprocess_text(document_content)
            
            if not clean_content or not clean_content.strip():
                return {
                    'success': False,
                    'error': 'Document content is empty',
                    'fields': []
                }
            
            estimated_tokens = len(clean_content) // 4
            
            logger.critical(f"!!! CHUNKING CHECK !!! Content Length: {len(clean_content)} chars, Estimated Tokens: {estimated_tokens}, Threshold: {self.chunk_threshold}")
            
            # Check if document needs chunking (Flask pattern: token-based decision)
            if estimated_tokens >= self.chunk_threshold:
                self.logger.info(f"Document requires chunking: {estimated_tokens:.0f} tokens >= {self.chunk_threshold} threshold")
                return self._analyze_large_document(clean_content, context)
            
            # Process normal-sized document
            return self._analyze_single_document(clean_content, context)
            
        except Exception as e:
            self.logger.error(f"Error in document analysis: {e}", exc_info=True)
            return {
                'success': False,
                'error': f"Document analysis failed: {str(e)}",
                'fields': []
            }
    
    def _analyze_single_document(self, content: str, context: Optional[str] = None, chunk_info: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Process a single document that doesn't require chunking.
        
        Args:
            content: Document content
            context: Optional context information
            chunk_info: Optional chunk information for large document processing
            
        Returns:
            Analysis results
        """
        # Build system prompt using MediExtract system
        system_prompt = self._get_medical_extraction_prompt(context, chunk_info)
        
        # Try primary AI service (Claude)
        if self.anthropic_client:
            result = self._call_anthropic(system_prompt, content)
            if result['success']:
                result['model_used'] = self.primary_model
                result['processing_method'] = 'single_document'
                return result
            elif result.get('error') == 'rate_limit_exceeded':
                # Rate limiting - don't fallback immediately, return the rate limit info
                # This will be caught by the Celery task and retried.
                raise APIRateLimitError("Anthropic rate limit exceeded, will retry.")
            elif result.get('error') in ['authentication_error', 'api_status_error']:
                # Critical errors that won't be fixed by retrying - try fallback
                self.logger.warning(f"Anthropic critical error ({result.get('error')}), trying fallback")
            else:
                # Connection errors or other issues - try fallback
                self.logger.warning(f"Anthropic processing failed ({result.get('error', 'unknown')}), trying fallback")
        
        # Fallback to OpenAI if primary fails for a non-rate-limit reason
        if self.openai_client:
            self.logger.warning("Primary AI service failed. Falling back to OpenAI.")
        
        # Last resort: Try simplified fallback prompt if we have any working client
        if self.anthropic_client or self.openai_client:
            self.logger.warning("Primary and secondary extraction failed, trying fallback prompt")
            return self._try_fallback_extraction(content, context)
        
        return {
            'success': False,
            'error': 'all_services_failed',
            'error_message': 'All AI services and prompts failed',
            'fields': []
        }
    
    def _analyze_large_document(self, content: str, context: Optional[str] = None) -> Dict[str, Any]:
        """
        Process large documents using enhanced chunking strategy with progress tracking.
        Now with medical-aware chunking and comprehensive progress reporting.
        
        Like rebuilding a big engine - you gotta track each part as you work on it
        so you know how much progress you're making toward getting it back together.
        
        Args:
            content: Large document content
            context: Optional context information
            
        Returns:
            Combined analysis results with progress tracking and medical deduplication
        """
        start_time = timezone.now()
        
        # Split document into medical-aware chunks
        chunks = self._chunk_document(content)
        total_chunks = len(chunks)
        
        self.logger.info(f"Processing large document with {total_chunks} medical-aware chunks")
        
        # Initialize progress tracking
        processing_results = {
            'all_fields': [],
            'successful_chunks': 0,
            'failed_chunks': 0,
            'total_tokens': 0,
            'chunk_details': [],
            'processing_errors': []
        }
        
        # Process each chunk with detailed progress tracking
        for chunk_index, chunk in enumerate(chunks):
            chunk_number = chunk_index + 1
            chunk_start_time = timezone.now()
            
            try:
                self.logger.info(f"Processing medical chunk {chunk_number}/{total_chunks}")
                
                # Create enhanced chunk context and info
                chunk_context = self._create_chunk_context(context, chunk_number, total_chunks)
                chunk_info = {
                    'current': chunk_number,
                    'total': total_chunks,
                    'is_first': chunk_number == 1,
                    'is_last': chunk_number == total_chunks
                }
                
                # Process this chunk with chunk-aware prompting
                chunk_result = self._analyze_single_document(chunk, chunk_context, chunk_info)
                
                if chunk_result['success']:
                    # Add chunk tracking to each field
                    for field in chunk_result.get('fields', []):
                        field['source_chunk'] = chunk_number
                        field['chunk_context'] = chunk_context
                        field['processing_timestamp'] = timezone.now().isoformat()
                    
                    processing_results['all_fields'].extend(chunk_result.get('fields', []))
                    processing_results['total_tokens'] += chunk_result.get('usage', {}).get('total_tokens', 0)
                    processing_results['successful_chunks'] += 1
                    
                    chunk_processing_time = (timezone.now() - chunk_start_time).total_seconds()
                    
                    # Track detailed chunk information
                    chunk_detail = {
                        'chunk_number': chunk_number,
                        'success': True,
                        'fields_extracted': len(chunk_result.get('fields', [])),
                        'tokens_used': chunk_result.get('usage', {}).get('total_tokens', 0),
                        'processing_time_seconds': chunk_processing_time,
                        'model_used': chunk_result.get('model_used', 'unknown'),
                        'chunk_size_chars': len(chunk)
                    }
                    processing_results['chunk_details'].append(chunk_detail)
                    
                    self.logger.info(
                        f"Chunk {chunk_number} completed: {len(chunk_result.get('fields', []))} fields, "
                        f"{chunk_result.get('usage', {}).get('total_tokens', 0)} tokens, "
                        f"{chunk_processing_time:.1f}s"
                    )
                else:
                    # Handle chunk failure
                    processing_results['failed_chunks'] += 1
                    error_detail = {
                        'chunk_number': chunk_number,
                        'error': chunk_result.get('error', 'Unknown error'),
                        'chunk_size_chars': len(chunk)
                    }
                    processing_results['processing_errors'].append(error_detail)
                    
                    self.logger.error(f"Chunk {chunk_number} failed: {chunk_result.get('error', 'Unknown error')}")
                
                # Progress update
                progress_percent = (chunk_number / total_chunks) * 100
                self.logger.info(f"Multi-chunk progress: {progress_percent:.1f}% ({chunk_number}/{total_chunks})")
                
            except Exception as e:
                processing_results['failed_chunks'] += 1
                error_detail = {
                    'chunk_number': chunk_number,
                    'error': f"Processing exception: {str(e)}",
                    'chunk_size_chars': len(chunk)
                }
                processing_results['processing_errors'].append(error_detail)
                
                self.logger.error(f"Exception processing chunk {chunk_number}: {e}", exc_info=True)
                continue
        
        # Enhanced result reassembly with medical deduplication
        merged_fields = self._reassemble_chunk_results(processing_results['all_fields'])
        
        # Calculate total processing time
        total_processing_time = (timezone.now() - start_time).total_seconds()
        
        # Compile comprehensive results
        final_result = {
            'success': processing_results['successful_chunks'] > 0,
            'fields': merged_fields,
            'processing_method': 'medical_aware_chunked_document',
            'processing_summary': {
                'total_chunks': total_chunks,
                'successful_chunks': processing_results['successful_chunks'],
                'failed_chunks': processing_results['failed_chunks'],
                'success_rate': (processing_results['successful_chunks'] / total_chunks) * 100,
                'total_fields_before_dedup': len(processing_results['all_fields']),
                'total_fields_after_dedup': len(merged_fields),
                'deduplication_rate': ((len(processing_results['all_fields']) - len(merged_fields)) / len(processing_results['all_fields'])) * 100 if processing_results['all_fields'] else 0,
                'total_processing_time_seconds': total_processing_time,
                'average_chunk_time_seconds': total_processing_time / total_chunks if total_chunks > 0 else 0
            },
            'chunk_details': processing_results['chunk_details'],
            'processing_errors': processing_results['processing_errors'],
            'usage': {
                'total_tokens': processing_results['total_tokens'],
                'average_tokens_per_chunk': processing_results['total_tokens'] / processing_results['successful_chunks'] if processing_results['successful_chunks'] > 0 else 0
            }
        }
        
        # Log comprehensive summary
        self.logger.info(
            f"Large document processing complete: "
            f"{processing_results['successful_chunks']}/{total_chunks} chunks successful, "
            f"{len(merged_fields)} final fields after medical deduplication, "
            f"{total_processing_time:.1f}s total time"
        )
        
        return final_result
    
    def _create_chunk_context(self, base_context: Optional[str], chunk_number: int, total_chunks: int) -> str:
        """
        Create enhanced context for chunk processing.
        
        Like putting a work order on each part so the next person knows
        what they're working on and where it fits in the whole job.
        
        Args:
            base_context: Original context from user
            chunk_number: Current chunk number (1-based)
            total_chunks: Total number of chunks
            
        Returns:
            Enhanced context string for this specific chunk
        """
        chunk_context_parts = []
        
        if base_context:
            chunk_context_parts.append(base_context)
        
        # Add chunk-specific context
        chunk_info = f"Medical Document Section {chunk_number} of {total_chunks}"
        chunk_context_parts.append(chunk_info)
        
        # Add processing instructions for chunked content
        if total_chunks > 1:
            processing_note = (
                "This is part of a larger medical document. "
                "Focus on extracting complete medical information from this section. "
                "Context may continue from previous sections or extend to following sections."
            )
            chunk_context_parts.append(processing_note)
        
        return " - ".join(chunk_context_parts)
    
    def _reassemble_chunk_results(self, all_fields: List[Dict]) -> List[Dict]:
        """
        Reassemble and deduplicate results from multiple chunks with medical intelligence.
        Enhanced version of _merge_chunk_fields with additional medical context preservation.
        
        Like putting together a complete patient chart from different department reports -
        you want all the pieces but no duplicates, and the important stuff on top.
        
        Args:
            all_fields: All fields from all processed chunks
            
        Returns:
            Reassembled and deduplicated medical fields
        """
        if not all_fields:
            self.logger.warning("No fields to reassemble from chunk processing")
            return []
        
        self.logger.info(f"Reassembling {len(all_fields)} fields from multiple chunks")
        
        # Use the enhanced medical deduplication
        reassembled_fields = self._deduplicate_medical_data(all_fields)
        
        # Add reassembly metadata to fields
        for field in reassembled_fields:
            field['reassembled_from_chunks'] = True
            field['reassembly_timestamp'] = timezone.now().isoformat()
        
        # Additional post-processing for medical fields
        reassembled_fields = self._post_process_medical_fields(reassembled_fields)
        
        self.logger.info(f"Reassembly complete: {len(reassembled_fields)} final medical fields")
        return reassembled_fields
    
    def _post_process_medical_fields(self, fields: List[Dict]) -> List[Dict]:
        """
        Post-process medical fields for consistency and completeness.
        
        Like doing a final inspection on a rebuilt engine - checking that all
        the parts are properly aligned and everything looks right.
        
        Args:
            fields: Reassembled medical fields
            
        Returns:
            Post-processed medical fields
        """
        processed_fields = []
        
        for field in fields:
            # Add unique field ID for tracking
            field['field_id'] = self._generate_field_id(field)
            
            # Normalize medical values for consistency
            field['normalized_value'] = self._normalize_medical_value(
                field.get('value', ''),
                field.get('label', '')
            )
            
            # Add medical validation
            field['medical_validation'] = self._validate_medical_field(field)
            
            processed_fields.append(field)
        
        return processed_fields
    
    def _generate_field_id(self, field: Dict) -> str:
        """Generate unique ID for a medical field."""
        import hashlib
        
        # Create hash from label and value for uniqueness
        content = f"{field.get('label', '')}-{field.get('value', '')}"
        field_hash = hashlib.md5(content.encode()).hexdigest()[:8]
        return f"med_field_{field_hash}"
    
    def _normalize_medical_value(self, value: str, label: str) -> str:
        """
        Normalize medical values for consistency.
        
        Args:
            value: Raw field value
            label: Field label for context
            
        Returns:
            Normalized medical value
        """
        if not value:
            return value
        
        normalized = str(value).strip()
        
        # Date normalization
        if any(term in label.lower() for term in ['date', 'dob', 'birth']):
            normalized = self._normalize_medical_date(normalized)
        
        # Medication normalization
        elif any(term in label.lower() for term in ['medication', 'drug']):
            normalized = self._normalize_medication_value(normalized)
        
        # Diagnosis normalization
        elif any(term in label.lower() for term in ['diagnosis', 'condition']):
            normalized = self._normalize_diagnosis_value(normalized)
        
        return normalized
    
    def _normalize_medical_date(self, date_str: str) -> str:
        """Normalize medical date formats."""
        # Basic date normalization - could be enhanced with proper date parsing
        date_str = date_str.strip()
        
        # Remove common prefixes
        date_str = re.sub(r'^(born|dob|date of birth)[:]\s*', '', date_str, flags=re.IGNORECASE)
        
        return date_str
    
    def _normalize_medication_value(self, med_str: str) -> str:
        """Normalize medication value formats."""
        # Basic medication normalization
        med_str = med_str.strip()
        
        # Standardize common abbreviations
        med_str = re.sub(r'\bmg\b', 'mg', med_str, flags=re.IGNORECASE)
        med_str = re.sub(r'\bml\b', 'mL', med_str, flags=re.IGNORECASE)
        
        return med_str
    
    def _normalize_diagnosis_value(self, diag_str: str) -> str:
        """Normalize diagnosis value formats."""
        # Basic diagnosis normalization
        diag_str = diag_str.strip()
        
        # Remove numbering
        diag_str = re.sub(r'^\d+[\.\)]\s*', '', diag_str)  # Remove numbering
        diag_str = re.sub(r'\s*\([^)]*\)\s*', ' ', diag_str)  # Remove parenthetical
        diag_str = re.sub(r'\s+', ' ', diag_str).strip()  # Normalize whitespace
        
        return diag_str
    
    def _validate_medical_field(self, field: Dict) -> Dict[str, Any]:
        """
        Validate medical field for completeness and accuracy.
        
        Args:
            field: Medical field to validate
            
        Returns:
            Validation results
        """
        validation = {
            'is_complete': True,
            'has_value': bool(field.get('value', '').strip()),
            'confidence_adequate': field.get('confidence', 0) >= 0.5,
            'warnings': []
        }
        
        # Check for completeness
        if not validation['has_value']:
            validation['is_complete'] = False
            validation['warnings'].append('Field has no value')
        
        if not validation['confidence_adequate']:
            validation['warnings'].append('Low confidence score')
        
        # Add medical-specific validations
        label = field.get('label', '').lower()
        value = field.get('value', '')
        
        # Patient name validation
        if 'name' in label and len(str(value).strip()) < 2:
            validation['warnings'].append('Patient name appears incomplete')
        
        # Date validation
        if 'date' in label or 'dob' in label:
            if not re.search(r'\d', str(value)):
                validation['warnings'].append('Date field contains no numbers')
        
        return validation
    
    def _try_fallback_extraction(self, content: str, context: Optional[str] = None) -> Dict[str, Any]:
        """
        Attempt extraction using simplified fallback prompt when primary methods fail.
        
        Like using a backup generator when the main power goes out - simpler but gets
        the essential systems running.
        
        Args:
            content: Document content to process
            context: Optional context information
            
        Returns:
            Extraction results using fallback prompt
        """
        from apps.documents.prompts import MedicalPrompts
        
        # Get simplified fallback prompt
        fallback_prompt = MedicalPrompts.get_fallback_prompt()
        
        # Add context if provided
        if context:
            fallback_prompt += f"\n\nContext: This document is from {context}."
        
        # Try with Anthropic first
        if self.anthropic_client:
            try:
                result = self._call_anthropic(fallback_prompt, content)
                if result['success']:
                    result['model_used'] = self.primary_model
                    result['processing_method'] = 'fallback_prompt'
                    self.logger.info("Fallback extraction succeeded with Anthropic")
                    return result
            except Exception as e:
                self.logger.warning(f"Fallback Anthropic extraction failed: {e}")
        
        # Try with OpenAI if available
        if self.openai_client:
            try:
                result = self._call_openai(fallback_prompt, content)
                if result['success']:
                    result['model_used'] = self.fallback_model
                    result['processing_method'] = 'fallback_prompt_openai'
                    self.logger.info("Fallback extraction succeeded with OpenAI")
                    return result
            except Exception as e:
                self.logger.warning(f"Fallback OpenAI extraction failed: {e}")
        
        # If all fallback attempts fail
        return {
            'success': False,
            'error': 'Fallback prompt extraction failed with all available AI services',
            'fields': []
        }
    
    def _call_anthropic_with_recovery(self, system_prompt: str, content: str, chunk_number=None, total_chunks=None) -> Dict[str, Any]:
        """
        Call Anthropic API with comprehensive error recovery patterns.
        Like having a full roadside assistance plan when your truck breaks down.
        
        Args:
            system_prompt: System prompt for the AI
            content: Document content to analyze
            chunk_number: For chunked documents, which chunk this is
            total_chunks: Total number of chunks for this document
            
        Returns:
            API response results with intelligent error recovery
        """
        self._attempt_count += 1
        
        # Save processing context for potential recovery
        if not self._context_key:
            context_data = {
                'system_prompt': system_prompt,
                'content_length': len(content),
                'chunk_number': chunk_number,
                'total_chunks': total_chunks,
                'primary_model': self.primary_model
            }
            self._context_key = context_preservation_service.save_processing_context(
                self.document.id if self.document else 0,
                str(self.processing_session),
                context_data
            )
        
        # Check circuit breaker before attempting
        if error_recovery_service._is_circuit_open('anthropic'):
            self.logger.warning("Anthropic circuit breaker is open, skipping API call")
            return {
                'success': False,
                'error': 'circuit_breaker_open',
                'error_message': 'Service temporarily unavailable due to repeated failures',
                'fields': []
            }
        
        start_time = timezone.now()
        
        try:
            response = self.anthropic_client.messages.create(
                model=self.primary_model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system_prompt,  # MediExtract prompts already include proper JSON enforcement
                messages=[{"role": "user", "content": f"Extract medical data from this document:\n\n{content}"}]
            )
            
            end_time = timezone.now()
            
            # Calculate duration
            duration = (end_time - start_time).total_seconds()
            
            # Extract content from the first TextBlock
            response_content = ""
            if response.content and isinstance(response.content, list):
                first_text_block = next((block for block in response.content if hasattr(block, 'text')), None)
                if first_text_block:
                    response_content = first_text_block.text
            
            self.logger.info(f"Parsing response of {len(response_content)} characters")
            
            # DEBUG: Log Claude's raw response to verify JSON format
            self.logger.info(f"CLAUDE RAW RESPONSE: {response_content[:500]}...")
            
            # Comprehensive response parsing
            parsed_json = self._parse_ai_response_content(response_content)
            
            # FHIR DocumentReference data encoding fix
            if parsed_json and 'fhir_resources' in parsed_json:
                for resource in parsed_json['fhir_resources']:
                    if resource.get('resourceType') == 'DocumentReference':
                        for content_item in resource.get('content', []):
                            attachment = content_item.get('attachment', {})
                            if 'data' in attachment and isinstance(attachment['data'], (str, list, dict)):
                                try:
                                    # Convert to JSON string, then base64 encode
                                    json_data = json.dumps(attachment['data'])
                                    encoded_data = base64.b64encode(json_data.encode('utf-8')).decode('utf-8')
                                    attachment['data'] = encoded_data
                                except (TypeError, ValueError) as e:
                                    self.logger.error(f"Failed to encode DocumentReference data: {e}")

            # Extract fields and perform quality checks
            # Handle both FHIR structure and legacy fields structure
            if 'fields' in parsed_json:
                fields = parsed_json.get('fields', [])
            else:
                # CRITICAL FIX: Use ResponseParser for flat field structure conversion
                parser = ResponseParser()
                fields = parser._convert_json_to_fields(parsed_json)
                self.logger.info(f"ResponseParser converted {len(fields)} fields from flat structure")
            
            # Record success for circuit breaker
            error_recovery_service.record_success('anthropic')
            
            # Log successful API usage
            if self.document:
                try:
                    APIUsageMonitor.log_api_usage(
                        document=self.document,
                        patient=getattr(self.document, 'patient', None),
                        session_id=self.processing_session,
                        provider='anthropic',
                        model=self.primary_model,
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        total_tokens=response.usage.input_tokens + response.usage.output_tokens,
                        start_time=start_time,
                        end_time=end_time,
                        success=True,
                        chunk_number=chunk_number,
                        total_chunks=total_chunks
                    )
                except Exception as monitor_error:
                    self.logger.error(f"Failed to log API usage: {monitor_error}")
            
            # Add success info to context
            if self._context_key:
                context_preservation_service.add_attempt_to_context(self._context_key, {
                    'attempt_number': self._attempt_count,
                    'service': 'anthropic',
                    'success': True,
                    'tokens_used': response.usage.input_tokens + response.usage.output_tokens
                })
            
            return {
                'success': True,
                'fields': fields,
                'raw_response': response_content,
                'usage': {
                    'input_tokens': response.usage.input_tokens,
                    'output_tokens': response.usage.output_tokens,
                    'total_tokens': response.usage.input_tokens + response.usage.output_tokens
                }
            }
            
        except anthropic.RateLimitError as e:
            return self._handle_api_error(e, 'rate_limit_exceeded', 'anthropic', start_time, content, chunk_number, total_chunks)
            
        except anthropic.AuthenticationError as e:
            return self._handle_api_error(e, 'authentication_error', 'anthropic', start_time, content, chunk_number, total_chunks)
            
        except anthropic.APIConnectionError as e:
            return self._handle_api_error(e, 'connection_error', 'anthropic', start_time, content, chunk_number, total_chunks)
            
        except anthropic.APIStatusError as e:
            return self._handle_api_error(e, 'api_status_error', 'anthropic', start_time, content, chunk_number, total_chunks)
            
        except Exception as e:
            return self._handle_api_error(e, 'unexpected_error', 'anthropic', start_time, content, chunk_number, total_chunks)
    
    def _handle_api_error(self, exception, error_type: str, service: str, start_time, content: str, 
                         chunk_number=None, total_chunks=None) -> Dict[str, Any]:
        """
        Handle API errors with intelligent recovery strategies.
        Like having a mechanic diagnose what's wrong and recommend the right fix.
        
        Args:
            exception: The exception that occurred
            error_type: Type of error for categorization
            service: Service name ('anthropic' or 'openai')
            start_time: When the API call started
            content: Content being processed
            chunk_number: Chunk number if applicable
            total_chunks: Total chunks if applicable
            
        Returns:
            Error response with recovery recommendations
        """
        end_time = timezone.now()
        error_message = str(exception)
        
        # Categorize the error for recovery strategy
        error_category = error_recovery_service.categorize_error(error_message, error_type)
        
        # Record failure for circuit breaker
        error_recovery_service.record_failure(service, error_category)
        
        # Log failed API usage
        if self.document:
            try:
                APIUsageMonitor.log_api_usage(
                    document=self.document,
                    patient=getattr(self.document, 'patient', None),
                    session_id=self.processing_session,
                    provider=service,
                    model=self.primary_model if service == 'anthropic' else self.fallback_model,
                    input_tokens=len(content) // 4,  # Estimate token count
                    output_tokens=0,
                    total_tokens=len(content) // 4,
                    start_time=start_time,
                    end_time=end_time,
                    success=False,
                    error_message=error_message,
                    chunk_number=chunk_number,
                    total_chunks=total_chunks
                )
            except Exception as monitor_error:
                self.logger.error(f"Failed to log API usage: {monitor_error}")
        
        # Add failure info to context
        if self._context_key:
            context_preservation_service.add_attempt_to_context(self._context_key, {
                'attempt_number': self._attempt_count,
                'service': service,
                'success': False,
                'error_type': error_type,
                'error_category': error_category,
                'error_message': error_message
            })
        
        # Determine if we should retry
        should_retry = error_recovery_service.should_retry(error_category, self._attempt_count)
        retry_delay = error_recovery_service.calculate_retry_delay(error_category, self._attempt_count) if should_retry else 0
        
        self.logger.warning(f"{service} API error (attempt {self._attempt_count}): {error_message}")
        
        response = {
            'success': False,
            'error': error_type,
            'error_message': error_message,
            'error_category': error_category,
            'fields': [],
            'can_retry': should_retry,
            'retry_delay': retry_delay,
            'attempt_count': self._attempt_count
        }
        
        # Add retry-specific information
        if error_type == 'rate_limit_exceeded':
            response['retry_after'] = getattr(exception, 'retry_after', 60)
        
        return response
    
    # Keep the original method name for backward compatibility
    def _call_anthropic(self, system_prompt: str, content: str, chunk_number=None, total_chunks=None) -> Dict[str, Any]:
        """Backward compatibility wrapper for the enhanced error recovery method."""
        return self._call_anthropic_with_recovery(system_prompt, content, chunk_number, total_chunks)
    
    def _call_openai_with_recovery(self, system_prompt: str, content: str, chunk_number=None, total_chunks=None) -> Dict[str, Any]:
        """
        Call OpenAI API with comprehensive error recovery patterns.
        Like having a backup generator when the power goes out.
        
        Args:
            system_prompt: System prompt for the AI
            content: Document content to analyze
            chunk_number: For chunked documents, which chunk this is
            total_chunks: Total number of chunks for this document
            
        Returns:
            API response results with intelligent error recovery
        """
        # Check circuit breaker before attempting
        if error_recovery_service._is_circuit_open('openai'):
            self.logger.warning("OpenAI circuit breaker is open, skipping API call")
            return {
                'success': False,
                'error': 'circuit_breaker_open',
                'error_message': 'Service temporarily unavailable due to repeated failures',
                'fields': []
            }
        
        start_time = timezone.now()
        
        try:
            start_time = timezone.now()
            
            response = self.openai_client.chat.completions.create(
                model=self.fallback_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"}
            )
            
            end_time = timezone.now()
            duration = (end_time - start_time).total_seconds()
            
            response_content = response.choices[0].message.content
            
            self.logger.info(f"Parsing OpenAI response of {len(response_content)} characters")
            parsed_json = self._parse_ai_response_content(response_content)
            
            # FHIR DocumentReference data encoding fix
            if parsed_json and 'fhir_resources' in parsed_json:
                for resource in parsed_json['fhir_resources']:
                    if resource.get('resourceType') == 'DocumentReference':
                        for content_item in resource.get('content', []):
                            attachment = content_item.get('attachment', {})
                            if 'data' in attachment and isinstance(attachment['data'], (str, list, dict)):
                                try:
                                    json_data = json.dumps(attachment['data'])
                                    encoded_data = base64.b64encode(json_data.encode('utf-8')).decode('utf-8')
                                    attachment['data'] = encoded_data
                                except (TypeError, ValueError) as e:
                                    self.logger.error(f"Failed to encode DocumentReference data for OpenAI: {e}")
            
            # Handle both FHIR structure and legacy fields structure
            if 'fields' in parsed_json:
                fields = parsed_json.get('fields', [])
            else:
                # CRITICAL FIX: Use ResponseParser for flat field structure conversion
                parser = ResponseParser()
                fields = parser._convert_json_to_fields(parsed_json)
                self.logger.info(f"ResponseParser converted {len(fields)} fields from flat structure")
            
            # Record success for circuit breaker
            error_recovery_service.record_success('openai')
            
            # Log successful API usage
            if self.document:
                try:
                    APIUsageMonitor.log_api_usage(
                        document=self.document,
                        patient=getattr(self.document, 'patient', None),
                        session_id=self.processing_session,
                        provider='openai',
                        model=self.fallback_model,
                        input_tokens=response.usage.prompt_tokens,
                        output_tokens=response.usage.completion_tokens,
                        total_tokens=response.usage.total_tokens,
                        start_time=start_time,
                        end_time=end_time,
                        success=True,
                        chunk_number=chunk_number,
                        total_chunks=total_chunks
                    )
                except Exception as monitor_error:
                    self.logger.error(f"Failed to log API usage: {monitor_error}")
            
            # Add success info to context
            if self._context_key:
                context_preservation_service.add_attempt_to_context(self._context_key, {
                    'attempt_number': self._attempt_count,
                    'service': 'openai',
                    'success': True,
                    'tokens_used': response.usage.total_tokens
                })
            
            return {
                'success': True,
                'fields': fields,
                'raw_response': response_content,
                'usage': {
                    'input_tokens': response.usage.prompt_tokens,
                    'output_tokens': response.usage.completion_tokens,
                    'total_tokens': response.usage.total_tokens
                }
            }
            
        except openai.RateLimitError as e:
            return self._handle_api_error(e, 'rate_limit_exceeded', 'openai', start_time, content, chunk_number, total_chunks)
            
        except openai.AuthenticationError as e:
            return self._handle_api_error(e, 'authentication_error', 'openai', start_time, content, chunk_number, total_chunks)
            
        except openai.APIConnectionError as e:
            return self._handle_api_error(e, 'connection_error', 'openai', start_time, content, chunk_number, total_chunks)
            
        except openai.APIStatusError as e:
            return self._handle_api_error(e, 'api_status_error', 'openai', start_time, content, chunk_number, total_chunks)
            
        except Exception as e:
            return self._handle_api_error(e, 'unexpected_error', 'openai', start_time, content, chunk_number, total_chunks)
    
    # Keep the original method name for backward compatibility
    def _call_openai(self, system_prompt: str, content: str, chunk_number=None, total_chunks=None) -> Dict[str, Any]:
        """Backward compatibility wrapper for the enhanced error recovery method."""
        return self._call_openai_with_recovery(system_prompt, content, chunk_number, total_chunks)
    
    def process_with_comprehensive_recovery(self, content: str, context: Optional[str] = None) -> Dict[str, Any]:
        """
        Process document with comprehensive error recovery and graceful degradation.
        Like having a full emergency plan when everything that can go wrong does go wrong.
        
        Args:
            content: Document content to process
            context: Optional context for processing
            
        Returns:
            Processing results with comprehensive error recovery
        """
        # FIXED: Use analyze_document which includes proper chunking logic
        self.logger.info("Starting document processing with comprehensive recovery (includes chunking logic)")
        return self.analyze_document(content, context)
    

    def _extract_with_text_patterns(self, content: str) -> Dict[str, Any]:
        """
        Extract medical data using text patterns as a last resort.
        Like using a basic wrench when all your fancy tools are broken.
        
        Args:
            content: Document content to analyze
            
        Returns:
            Dictionary with any extracted fields
        """
        extracted = {}
        
        try:
            # Patient name patterns
            name_patterns = [
                r'(?:Patient|Name|PATIENT):\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
                r'(?:Name|NAME):\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
                r'([A-Z][a-z]+,\s*[A-Z][a-z]+)',  # Last, First format
            ]
            
            for pattern in name_patterns:
                match = re.search(pattern, content)
                if match:
                    extracted['patient_name'] = match.group(1).strip()
                    break
            
            # MRN patterns
            mrn_patterns = [
                r'(?:MRN|Medical Record|Record Number):\s*([A-Z0-9]+)',
                r'(?:MRN|MR#):\s*([A-Z0-9]+)',
                r'(?:ID|Patient ID):\s*([A-Z0-9]+)',
            ]
            
            for pattern in mrn_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    extracted['medical_record_number'] = match.group(1).strip()
                    break
            
            # Date patterns
            date_patterns = [
                r'(?:Date of Birth|DOB|Born):\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
                r'(\d{1,2}[/-]\d{1,2}[/-]\d{4})',  # Basic date format
            ]
            
            for pattern in date_patterns:
                match = re.search(pattern, content)
                if match:
                    extracted['date_of_birth'] = match.group(1).strip()
                    break
            
            # Diagnosis patterns
            diagnosis_patterns = [
                r'(?:Diagnosis|DIAGNOSIS|Primary Diagnosis):\s*([^\n\r]+)',
                r'(?:Impression|IMPRESSION):\s*([^\n\r]+)',
            ]
            
            for pattern in diagnosis_patterns:
                match = re.search(pattern, content)
                if match:
                    extracted['primary_diagnosis'] = match.group(1).strip()
                    break
            
            self.logger.info(f"Text pattern extraction found {len(extracted)} fields")
            
        except Exception as e:
            self.logger.error(f"Text pattern extraction failed: {e}")
        
        return extracted
    
    def _get_medical_extraction_prompt(self, context: Optional[str] = None, chunk_info: Optional[Dict] = None) -> str:
        """
        Get the system prompt for medical data extraction using MediExtract system.
        
        Enhanced with specialized medical prompts for different document types and scenarios.
        Like having the right wrench for each bolt instead of using a hammer for everything.
        
        Args:
            context: Optional context to include in prompt (e.g., "Emergency Department Report")
            chunk_info: Information about document chunking if applicable
            
        Returns:
            Specialized medical extraction prompt
        """
        from apps.documents.prompts import MedicalPrompts, ChunkInfo, ContextTag
        
        # Convert chunk info if provided
        chunk_obj = None
        if chunk_info:
            chunk_obj = ChunkInfo(
                current=chunk_info.get('current', 1),
                total=chunk_info.get('total', 1),
                is_first=chunk_info.get('is_first', False),
                is_last=chunk_info.get('is_last', False)
            )
        
        # Create context tags if context provided
        context_tags = None
        if context:
            context_tags = [ContextTag(text=context)]
        
        # Determine document type from context
        document_type = None
        if context:
            context_lower = context.lower()
            if any(term in context_lower for term in ['emergency', 'ed', 'er']):
                document_type = 'ed'
            elif any(term in context_lower for term in ['surgical', 'surgery', 'operative']):
                document_type = 'surgical'
            elif any(term in context_lower for term in ['lab', 'laboratory', 'pathology']):
                document_type = 'lab'
        
        # Get appropriate prompt from MediExtract system
        prompt = MedicalPrompts.get_extraction_prompt(
            document_type=document_type,
            chunk_info=chunk_obj,
            fhir_focused=True,  # Enable FHIR-focused extraction for proper resource arrays and temporal data
            context_tags=context_tags
        )
        
        self.logger.info(f"Using MediExtract prompt for document_type={document_type}, chunked={chunk_obj is not None}")
        return prompt
    
    def _parse_ai_response(self, response_text: str) -> List[Dict[str, Any]]:
        """
        Parse AI response text into structured fields using the robust ResponseParser.
        Enhanced with medical-specific confidence scoring and quality metrics.
        
        Uses the 5-layer parsing strategy from the ResponseParser for maximum reliability,
        then applies medical confidence calibration like tuning a carburetor for peak performance.
        
        Args:
            response_text: Raw AI response text
            
        Returns:
            List of extracted field dictionaries with calibrated confidence scores
        """
        from apps.documents.prompts import ConfidenceScoring
        
        parser = ResponseParser()
        parsed_fields = parser.extract_structured_data(response_text)
        
        # Validate the parsing results
        validation = parser.validate_parsed_fields(parsed_fields)
        
        if not validation["is_valid"]:
            self.logger.warning(f"Response parsing issues detected: {validation['issues']}")
        else:
            self.logger.info(f"Successfully parsed {validation['field_count']} fields with {validation['avg_confidence']:.2f} average confidence")
        
        # Apply medical-specific confidence calibration
        if parsed_fields:
            calibrated_fields = ConfidenceScoring.calibrate_confidence_scores(parsed_fields)
            
            # Generate quality metrics for monitoring
            quality_metrics = ConfidenceScoring.get_quality_metrics(calibrated_fields)
            
            self.logger.info(
                f"Confidence calibration complete: {quality_metrics['total_fields']} fields, "
                f"avg confidence {quality_metrics['avg_confidence']:.3f}, "
                f"quality score {quality_metrics['quality_score']:.1f}%, "
                f"{quality_metrics['requires_review_count']} require review"
            )
            
            return calibrated_fields
        
        return parsed_fields
    
    def _chunk_document(self, content: str) -> List[str]:
        """
        Split large document into manageable chunks using intelligent medical document strategy.
        Enhanced to handle medical documents with structure awareness and overlap.
        
        Like rebuilding a transmission - we gotta know which parts go together
        and keep the related pieces from getting separated.
        
        Args:
            content: Document content to chunk
            
        Returns:
            List of document chunks with overlap for context preservation
        """
        # Use enhanced medical-aware chunking
        return self._chunk_large_document_medical_aware(content)
    
    def _chunk_large_document_medical_aware(self, content: str, overlap_chars: int = 2000) -> List[str]:
        """
        Enhanced chunking strategy specifically for medical documents.
        Respects medical document structure and maintains context with overlap.
        
        Like organizing a shop manual - you don't tear apart related procedures,
        but you make sure each section has enough context to make sense.
        
        Args:
            content: Full document content 
            overlap_chars: Number of characters to overlap between chunks
            
        Returns:
            List of intelligently chunked document sections
        """
        # Use larger chunks for medical documents (120K characters as specified)
        medical_chunk_size = 120000
        
        # Step 1: Analyze document structure to find optimal split points
        structure_analysis = self._analyze_document_structure(content)
        
        # Step 2: Create chunks respecting medical section boundaries
        chunks = []
        current_position = 0
        max_iterations = (len(content) // 1000) + 100  # Safety limit based on content size
        iteration_count = 0
        
        while current_position < len(content) and iteration_count < max_iterations:
            iteration_count += 1
            # Calculate chunk end position
            chunk_end = min(current_position + medical_chunk_size, len(content))
            
            # Find optimal break point near chunk boundary
            optimal_break = self._find_optimal_break_point(
                content, current_position, chunk_end, structure_analysis
            )
            
            # Extract chunk with context preservation
            chunk_start = max(0, current_position - overlap_chars) if current_position > 0 else 0
            chunk_content = content[chunk_start:optimal_break]
            
            # Add chunk metadata for tracking
            chunk_with_metadata = self._add_chunk_metadata(
                chunk_content, len(chunks) + 1, chunk_start, optimal_break, len(content)
            )
            
            chunks.append(chunk_with_metadata)
            
            # Move to next chunk position (accounting for overlap)
            next_position = optimal_break - overlap_chars if optimal_break > overlap_chars else optimal_break
            
            # Safety check: ensure forward progress to prevent infinite loops
            if next_position <= current_position:
                # Force advancement if we're not making progress
                next_position = current_position + max(1000, medical_chunk_size // 10)
                self.logger.warning(f"Forced chunk advancement from {current_position} to {next_position} to prevent infinite loop")
            
            current_position = next_position
            
            # Safety break to prevent infinite loops
            if current_position >= len(content):
                break
        
        # Warn if we hit iteration limit (potential runaway condition)
        if iteration_count >= max_iterations:
            self.logger.error(f"Hit maximum iteration limit ({max_iterations}) during chunking - possible infinite loop prevented")
        
        self.logger.info(f"Created {len(chunks)} medical-aware chunks with {overlap_chars} character overlap after {iteration_count} iterations")
        return chunks
    
    def _analyze_document_structure(self, content: str) -> Dict[str, List[int]]:
        """
        Analyze medical document structure to identify optimal split points.
        
        Like looking at a wiring diagram before you start pulling wires -
        you gotta know where the important connections are.
        
        Args:
            content: Document content to analyze
            
        Returns:
            Dictionary mapping section types to their positions in the document
        """
        structure = {
            'patient_info_sections': [],
            'diagnosis_sections': [],
            'medication_sections': [],
            'procedure_sections': [],
            'lab_sections': [],
            'major_section_breaks': [],
            'page_breaks': [],
            'paragraph_breaks': []
        }
        
        # Medical section patterns (common in medical documents)
        patterns = {
            'patient_info_sections': [
                r'(?i)patient\s+information|demographics|patient\s+data',
                r'(?i)name:|dob:|mrn:|medical\s+record',
                r'(?i)address:|phone:|contact\s+info'
            ],
            'diagnosis_sections': [
                r'(?i)diagnosis|diagnoses|impression|assessment',
                r'(?i)chief\s+complaint|cc:|presenting\s+problem',
                r'(?i)final\s+diagnosis|working\s+diagnosis'
            ],
            'medication_sections': [
                r'(?i)medications|current\s+meds|prescriptions',
                r'(?i)drug\s+list|medication\s+list|pharmacy',
                r'(?i)dosage:|frequency:|route:'
            ],
            'procedure_sections': [
                r'(?i)procedures|operations|surgery',
                r'(?i)procedure\s+note|operative\s+report',
                r'(?i)treatment\s+plan|interventions'
            ],
            'lab_sections': [
                r'(?i)laboratory|lab\s+results|pathology',
                r'(?i)blood\s+work|culture|specimen',
                r'(?i)normal\s+range|reference\s+range'
            ]
        }
        
        # Find major section breaks (multiple newlines, page separators)
        major_breaks = [
            m.start() for m in re.finditer(r'\n\s*\n\s*\n', content)
        ]
        structure['major_section_breaks'] = major_breaks
        
        # Find page breaks
        page_breaks = [
            m.start() for m in re.finditer(r'(?i)page\s+\d+|--- page \d+ ---|new\s+page', content)
        ]
        structure['page_breaks'] = page_breaks
        
        # Find paragraph breaks
        paragraph_breaks = [
            m.start() for m in re.finditer(r'\n\s*\n', content)
        ]
        structure['paragraph_breaks'] = paragraph_breaks
        
        # Find medical section patterns
        for section_type, pattern_list in patterns.items():
            for pattern in pattern_list:
                matches = [m.start() for m in re.finditer(pattern, content)]
                structure[section_type].extend(matches)
        
        # Sort all positions for easier processing
        for key in structure:
            structure[key] = sorted(set(structure[key]))
        
        self.logger.info(f"Document structure analysis found {sum(len(v) for v in structure.values())} structural markers")
        return structure
    
    def _find_optimal_break_point(self, content: str, start_pos: int, target_end: int, 
                                  structure: Dict[str, List[int]]) -> int:
        """
        Find the best place to break a document chunk while respecting medical sections.
        
        Like finding the right place to separate two joined parts - you want
        to cut at the gasket, not through the middle of a bolt.
        
        Args:
            content: Full document content
            start_pos: Starting position for this chunk
            target_end: Desired end position
            structure: Document structure analysis results
            
        Returns:
            Optimal break position
        """
        # If we're at the end of document, use that
        if target_end >= len(content):
            return len(content)
        
        # Define search window for break point (look back up to 5000 chars)
        search_start = max(start_pos, target_end - 5000)
        search_end = min(len(content), target_end + 1000)
        
        # Priority order for break points (higher score = better break point)
        break_candidates = []
        
        # Priority 1: Major section breaks (triple newlines, page breaks)
        for pos in structure['major_section_breaks'] + structure['page_breaks']:
            if search_start <= pos <= search_end:
                break_candidates.append((pos, 100))  # Highest priority
        
        # Priority 2: End of medical sections (don't split medical content)
        medical_sections = (
            structure['diagnosis_sections'] + structure['medication_sections'] +
            structure['procedure_sections'] + structure['lab_sections']
        )
        
        for pos in medical_sections:
            if search_start <= pos <= search_end:
                # Look for section end (next major break after this section start)
                section_end = self._find_section_end(content, pos, structure)
                if section_end and search_start <= section_end <= search_end:
                    break_candidates.append((section_end, 80))  # High priority
        
        # Priority 3: Paragraph breaks
        for pos in structure['paragraph_breaks']:
            if search_start <= pos <= search_end:
                break_candidates.append((pos, 60))  # Medium priority
        
        # Priority 4: Sentence endings
        sentence_pattern = r'[.!?]\s+'
        for match in re.finditer(sentence_pattern, content[search_start:search_end]):
            actual_pos = search_start + match.end()
            break_candidates.append((actual_pos, 40))  # Lower priority
        
        # Priority 5: Line breaks
        line_breaks = [
            search_start + m.start() 
            for m in re.finditer(r'\n', content[search_start:search_end])
        ]
        for pos in line_breaks:
            break_candidates.append((pos, 20))  # Lowest priority
        
        # Select best break point
        if break_candidates:
            # Sort by priority (score) then by distance to target
            break_candidates.sort(
                key=lambda x: (-x[1], abs(x[0] - target_end))  # Higher score, closer to target
            )
            best_break = break_candidates[0][0]
            self.logger.debug(f"Selected break point at position {best_break} (score: {break_candidates[0][1]})")
            return best_break
        
        # Fallback: use target position
        self.logger.warning(f"No optimal break point found, using target position {target_end}")
        return target_end
    
    def _find_section_end(self, content: str, section_start: int, 
                          structure: Dict[str, List[int]]) -> Optional[int]:
        """
        Find where a medical section ends based on structure analysis.
        
        Args:
            content: Document content
            section_start: Where the section begins
            structure: Document structure analysis
            
        Returns:
            Position where section ends, or None if not found
        """
        # Look for next major break after this section
        all_breaks = sorted(structure['major_section_breaks'] + structure['page_breaks'])
        
        for break_pos in all_breaks:
            if break_pos > section_start:
                return break_pos
        
        # If no major break found, look for significant paragraph breaks
        significant_breaks = [
            pos for pos in structure['paragraph_breaks'] 
            if pos > section_start and self._is_significant_break(content, pos)
        ]
        
        if significant_breaks:
            return significant_breaks[0]
        
        return None
    
    def _is_significant_break(self, content: str, position: int) -> bool:
        """
        Determine if a paragraph break represents a significant section boundary.
        
        Args:
            content: Document content
            position: Position to check
            
        Returns:
            True if this is a significant break point
        """
        # Check context around the break
        context_before = content[max(0, position - 100):position].strip()
        context_after = content[position:min(len(content), position + 100)].strip()
        
        # Look for section indicators
        section_indicators = [
            r'(?i)section|chapter|part|summary|conclusion',
            r'(?i)patient|diagnosis|medication|procedure|lab',
            r'(?i)report|note|record|document'
        ]
        
        for pattern in section_indicators:
            if re.search(pattern, context_after[:50]):  # Check first 50 chars after break
                return True
        
        return False
    
    def _add_chunk_metadata(self, chunk_content: str, chunk_number: int, 
                           start_pos: int, end_pos: int, total_length: int) -> str:
        """
        Add metadata header to chunk for tracking and context.
        
        Like putting a parts label on each component so you know
        where it came from and where it goes back.
        
        Args:
            chunk_content: The chunk content
            chunk_number: Sequential chunk number
            start_pos: Starting position in original document
            end_pos: Ending position in original document
            total_length: Total document length
            
        Returns:
            Chunk with metadata header
        """
        progress_percent = (end_pos / total_length) * 100
        
        metadata_header = f"""
=== MEDICAL DOCUMENT CHUNK {chunk_number} ===
Document Progress: {progress_percent:.1f}% (chars {start_pos:,}-{end_pos:,} of {total_length:,})
Chunk Size: {len(chunk_content):,} characters
Processing Note: This is part of a larger medical document. Context may span multiple chunks.
=====================================

"""
        
        return metadata_header + chunk_content
    
    def _merge_chunk_fields(self, all_fields: List[Dict]) -> List[Dict]:
        """
        Merge and deduplicate fields from multiple chunks with medical-specific logic.
        Enhanced to handle medical data deduplication with clinical context awareness.
        
        Like sorting through a box of mixed bolts - you gotta group the similar ones
        but keep the different sizes and threading separate.
        
        Args:
            all_fields: All fields from all chunks
            
        Returns:
            Merged and deduplicated fields with medical context preservation
        """
        if not all_fields:
            return []
            
        # Enhanced medical data deduplication
        return self._deduplicate_medical_data(all_fields)
    
    def _deduplicate_medical_data(self, all_fields: List[Dict]) -> List[Dict]:
        """
        Advanced deduplication specifically designed for medical data.
        Handles medical terminology, date formats, and clinical context.
        
        Like organizing a medical chart - you keep one copy of each test result
        but make sure you don't lose important variations or updates.
        
        Args:
            all_fields: All extracted fields from all chunks
            
        Returns:
            Deduplicated fields with medical context preserved
        """
        # Group fields by medical categories
        medical_categories = {
            'patient_demographics': [],
            'diagnoses': [],
            'medications': [],
            'procedures': [],
            'lab_results': [],
            'vital_signs': [],
            'allergies': [],
            'provider_info': [],
            'dates': [],
            'other': []
        }
        
        # Categorize fields based on medical content
        for field in all_fields:
            label = field.get("label", "").lower()
            value = field.get("value", "").lower()
            category = self._categorize_medical_field(label, value)
            medical_categories[category].append(field)
        
        merged_fields = []
        
        # Process each category with appropriate deduplication strategy
        for category, fields in medical_categories.items():
            if not fields:
                continue
                
            if category == 'patient_demographics':
                merged_fields.extend(self._merge_patient_demographics(fields))
            elif category == 'diagnoses':
                merged_fields.extend(self._merge_diagnoses(fields))
            elif category == 'medications':
                merged_fields.extend(self._merge_medications(fields))
            elif category == 'lab_results':
                merged_fields.extend(self._merge_lab_results(fields))
            elif category == 'dates':
                merged_fields.extend(self._merge_dates(fields))
            else:
                # Default deduplication for other categories
                merged_fields.extend(self._merge_generic_fields(fields))
        
        # Final sort by confidence and medical importance
        merged_fields.sort(key=lambda x: (
            self._get_medical_importance(x.get("label", "")),  # Medical importance first
            -x.get("confidence", 0),  # Then confidence
            -len(str(x.get("value", "")))  # Then value completeness
        ), reverse=True)
        
        self.logger.info(f"Deduplicated {len(all_fields)} fields down to {len(merged_fields)} medical fields")
        return merged_fields
    
    def _categorize_medical_field(self, label: str, value: str) -> str:
        """
        Categorize a medical field for appropriate deduplication strategy.
        
        Args:
            label: Field label
            value: Field value
            
        Returns:
            Category name for deduplication strategy
        """
        # Patient demographics patterns
        if any(term in label for term in ['name', 'patient', 'mrn', 'ssn', 'dob', 'birth', 'age', 'gender', 'address', 'phone']):
            return 'patient_demographics'
        
        # Diagnosis patterns
        if any(term in label for term in ['diagnosis', 'condition', 'icd', 'impression', 'assessment', 'chief complaint']):
            return 'diagnoses'
        
        # Medication patterns
        if any(term in label for term in ['medication', 'drug', 'prescription', 'dosage', 'mg', 'ml', 'tablet', 'capsule']):
            return 'medications'
        
        # Lab results patterns
        if any(term in label for term in ['lab', 'blood', 'glucose', 'hemoglobin', 'cholesterol', 'test', 'result', 'level']):
            return 'lab_results'
        
        # Vital signs patterns
        if any(term in label for term in ['vital', 'blood pressure', 'bp', 'heart rate', 'temperature', 'weight', 'height']):
            return 'vital_signs'
        
        # Procedure patterns
        if any(term in label for term in ['procedure', 'surgery', 'operation', 'treatment', 'therapy']):
            return 'procedures'
        
        # Allergy patterns
        if any(term in label for term in ['allergy', 'allergic', 'reaction', 'sensitivity']):
            return 'allergies'
        
        # Provider patterns
        if any(term in label for term in ['doctor', 'physician', 'nurse', 'provider', 'practitioner']):
            return 'provider_info'
        
        # Date patterns
        if any(term in label for term in ['date', 'time', 'on', 'visit', 'admission', 'discharge']):
            return 'dates'
        
        return 'other'
    
    def _merge_patient_demographics(self, fields: List[Dict]) -> List[Dict]:
        """Merge patient demographic fields with high precision."""
        # Group by demographic type
        demo_groups = {}
        for field in fields:
            label_key = self._normalize_demographic_label(field.get("label", ""))
            if label_key not in demo_groups:
                demo_groups[label_key] = []
            demo_groups[label_key].append(field)
        
        merged = []
        for demo_type, group_fields in demo_groups.items():
            # For demographics, prefer the most complete and confident value
            best_field = max(group_fields, key=lambda f: (
                f.get("confidence", 0),
                len(str(f.get("value", "")).strip()),
                -f.get('source_chunk', 999)  # Prefer earlier chunks
            ))
            
            # Add source tracking if merged from multiple chunks
            if len(group_fields) > 1:
                sources = [f.get('source_chunk') for f in group_fields if f.get('source_chunk')]
                if sources:
                    best_field['demographics_sources'] = sorted(set(sources))
            
            merged.append(best_field)
        
        return merged
    
    def _normalize_demographic_label(self, label: str) -> str:
        """Normalize demographic labels for consistent grouping."""
        label_lower = label.lower()
        
        # Name variations
        if any(term in label_lower for term in ['name', 'patient']):
            return 'patient_name'
        
        # DOB variations  
        if any(term in label_lower for term in ['dob', 'birth', 'born']):
            return 'date_of_birth'
        
        # MRN variations
        if any(term in label_lower for term in ['mrn', 'medical record', 'record number']):
            return 'medical_record_number'
        
        # Gender variations
        if any(term in label_lower for term in ['gender', 'sex']):
            return 'gender'
        
        # Age variations
        if 'age' in label_lower:
            return 'age'
        
        return label_lower
    
    def _merge_diagnoses(self, fields: List[Dict]) -> List[Dict]:
        """Merge diagnosis fields, keeping distinct conditions separate."""
        # Group by similar diagnosis terms
        diagnosis_groups = {}
        
        for field in fields:
            value = str(field.get("value", "")).strip()
            normalized_diagnosis = self._normalize_diagnosis(value)
            
            if normalized_diagnosis not in diagnosis_groups:
                diagnosis_groups[normalized_diagnosis] = []
            diagnosis_groups[normalized_diagnosis].append(field)
        
        merged = []
        for diagnosis, group_fields in diagnosis_groups.items():
            if not diagnosis:  # Skip empty diagnoses
                continue
                
            # For diagnoses, prefer the most detailed description
            best_field = max(group_fields, key=lambda f: (
                len(str(f.get("value", "")).strip()),  # Most detailed first
                f.get("confidence", 0)
            ))
            
            # Track if this diagnosis appeared in multiple chunks
            if len(group_fields) > 1:
                sources = [f.get('source_chunk') for f in group_fields if f.get('source_chunk')]
                if sources:
                    best_field['diagnosis_confirmed_in_chunks'] = sorted(set(sources))
            
            merged.append(best_field)
        
        return merged
    
    def _normalize_diagnosis(self, diagnosis: str) -> str:
        """Normalize diagnosis text for comparison."""
        if not diagnosis:
            return ""
            
        # Remove common prefixes/suffixes
        normalized = diagnosis.lower().strip()
        normalized = re.sub(r'^\d+[\.\)]\s*', '', normalized)  # Remove numbering
        normalized = re.sub(r'\s*\([^)]*\)\s*', ' ', normalized)  # Remove parenthetical
        normalized = re.sub(r'\s+', ' ', normalized).strip()  # Normalize whitespace
        
        return normalized
    
    def _merge_medications(self, fields: List[Dict]) -> List[Dict]:
        """Merge medication fields, handling dosages and frequencies."""
        # Group by medication name (not dosage)
        med_groups = {}
        
        for field in fields:
            value = str(field.get("value", ""))
            med_name = self._extract_medication_name(value)
            
            if med_name not in med_groups:
                med_groups[med_name] = []
            med_groups[med_name].append(field)
        
        merged = []
        for med_name, group_fields in med_groups.items():
            if not med_name:
                continue
                
            # For medications, prefer the most complete dosage information
            best_field = max(group_fields, key=lambda f: (
                self._count_medication_details(f.get("value", "")),  # Most complete dosage info
                f.get("confidence", 0)
            ))
            
            merged.append(best_field)
        
        return merged
    
    def _extract_medication_name(self, medication_text: str) -> str:
        """Extract the base medication name from a medication string."""
        if not medication_text:
            return ""
            
        # Remove dosage information to get base drug name
        med_text = medication_text.lower().strip()
        
        # Remove common dosage indicators
        dosage_patterns = [
            r'\d+\s*(mg|ml|mcg|units?|iu|tablets?|capsules?|pills?)',
            r'\b(daily|twice|bid|tid|qid|prn|as needed)\b',
            r'\b(morning|evening|bedtime|with meals?)\b'
        ]
        
        for pattern in dosage_patterns:
            med_text = re.sub(pattern, '', med_text)
        
        # Clean up and get first significant word(s)
        med_text = re.sub(r'\s+', ' ', med_text).strip()
        words = med_text.split()
        
        # Return first 1-2 words (typical drug name length)
        if len(words) >= 2:
            return ' '.join(words[:2])
        elif words:
            return words[0]
        
        return ""
    
    def _count_medication_details(self, medication_text: str) -> int:
        """Count how many medication details are present."""
        details = 0
        text_lower = medication_text.lower()
        
        # Count dosage amount
        if re.search(r'\d+\s*(mg|ml|mcg|units?|iu)', text_lower):
            details += 1
        
        # Count frequency
        if any(freq in text_lower for freq in ['daily', 'twice', 'bid', 'tid', 'qid', 'prn']):
            details += 1
        
        # Count timing
        if any(time in text_lower for time in ['morning', 'evening', 'bedtime', 'meals']):
            details += 1
        
        return details
    
    def _merge_lab_results(self, fields: List[Dict]) -> List[Dict]:
        """Merge lab result fields, keeping different tests separate."""
        # Group by test type
        lab_groups = {}
        
        for field in fields:
            test_name = self._extract_lab_test_name(field.get("label", ""), field.get("value", ""))
            
            if test_name not in lab_groups:
                lab_groups[test_name] = []
            lab_groups[test_name].append(field)
        
        merged = []
        for test_name, group_fields in lab_groups.items():
            if not test_name:
                continue
                
            # For lab results, prefer the most recent or most complete result
            best_field = max(group_fields, key=lambda f: (
                f.get("confidence", 0),
                len(str(f.get("value", "")).strip())
            ))
            
            merged.append(best_field)
        
        return merged
    
    def _extract_lab_test_name(self, label: str, value: str) -> str:
        """Extract the lab test name for grouping."""
        # Look for common lab test names in label first
        test_indicators = ['glucose', 'hemoglobin', 'cholesterol', 'sodium', 'potassium', 'creatinine']
        
        label_lower = label.lower()
        for indicator in test_indicators:
            if indicator in label_lower:
                return indicator
        
        # If not in label, look in value
        value_lower = value.lower()
        for indicator in test_indicators:
            if indicator in value_lower:
                return indicator
        
        return label_lower
    
    def _merge_dates(self, fields: List[Dict]) -> List[Dict]:
        """Merge date fields, keeping distinct dates separate."""
        # Group by date type
        date_groups = {}
        
        for field in fields:
            date_type = self._categorize_date_field(field.get("label", ""))
            
            if date_type not in date_groups:
                date_groups[date_type] = []
            date_groups[date_type].append(field)
        
        merged = []
        for date_type, group_fields in date_groups.items():
            # For dates, prefer the most confident and complete value
            best_field = max(group_fields, key=lambda f: (
                f.get("confidence", 0),
                len(str(f.get("value", "")).strip())
            ))
            
            merged.append(best_field)
        
        return merged
    
    def _categorize_date_field(self, label: str) -> str:
        """Categorize date fields by type."""
        label_lower = label.lower()
        
        if any(term in label_lower for term in ['admission', 'admit']):
            return 'admission_date'
        elif any(term in label_lower for term in ['discharge']):
            return 'discharge_date'
        elif any(term in label_lower for term in ['birth', 'dob']):
            return 'birth_date'
        elif any(term in label_lower for term in ['visit', 'appointment']):
            return 'visit_date'
        else:
            return 'general_date'
    
    def _merge_generic_fields(self, fields: List[Dict]) -> List[Dict]:
        """Generic merge strategy for fields that don't fit specific medical categories."""
        # Group by normalized label
        field_groups = {}
        
        for field in fields:
            label_key = field.get("label", "").lower().strip()
            if label_key not in field_groups:
                field_groups[label_key] = []
            field_groups[label_key].append(field)
        
        merged = []
        for label_key, group_fields in field_groups.items():
            # Default strategy: highest confidence, then longest value
            best_field = max(group_fields, key=lambda f: (
                f.get("confidence", 0),
                len(str(f.get("value", "")))
            ))
            
            merged.append(best_field)
        
        return merged
    
    def _get_medical_importance(self, label: str) -> int:
        """
        Get medical importance score for field ordering.
        Higher scores for more clinically important information.
        
        Args:
            label: Field label
            
        Returns:
            Importance score (higher = more important)
        """
        label_lower = label.lower()
        
        # Critical patient identifiers (highest priority)
        if any(term in label_lower for term in ['patient name', 'mrn', 'medical record']):
            return 100
        
        # Demographics
        if any(term in label_lower for term in ['dob', 'birth', 'age', 'gender']):
            return 90
        
        # Primary diagnoses
        if any(term in label_lower for term in ['diagnosis', 'condition', 'chief complaint']):
            return 80
        
        # Medications
        if any(term in label_lower for term in ['medication', 'drug', 'prescription']):
            return 70
        
        # Lab results and vitals
        if any(term in label_lower for term in ['lab', 'blood', 'vital', 'pressure', 'heart rate']):
            return 60
        
        # Procedures
        if any(term in label_lower for term in ['procedure', 'surgery', 'treatment']):
            return 50
        
        # Provider information
        if any(term in label_lower for term in ['doctor', 'physician', 'provider']):
            return 40
        
        # Dates
        if any(term in label_lower for term in ['date', 'time']):
            return 30
        
        # Everything else
        return 10
    
    def convert_to_fhir(self, extracted_fields: List[Dict], patient_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Convert extracted medical fields to FHIR resources.
        Supports both legacy format (flat field list) and new FHIR-structured format.
        
        Args:
            extracted_fields: List of extracted field dictionaries OR FHIR-structured dict
            patient_id: Optional patient ID for resource references
            
        Returns:
            List of FHIR resource dictionaries ready for accumulation
        """
        fhir_resources = []
        
        try:
            # Detect data format and route to appropriate converter
            if self._is_fhir_structured_format(extracted_fields):
                self.logger.info("Processing FHIR-structured extraction format")
                return self._convert_fhir_structured_to_resources(extracted_fields, patient_id)
            else:
                self.logger.info("Processing legacy flat field format")
                return self._convert_legacy_fields_to_fhir(extracted_fields, patient_id)
                
        except Exception as e:
            self.logger.error(f"Error converting to FHIR: {e}", exc_info=True)
            # Fallback: create basic DocumentReference with raw data
            return [self._create_document_reference_resource(extracted_fields, patient_id)]
    
    def _is_fhir_structured_format(self, data) -> bool:
        """
        Detect if the extracted data is in FHIR-structured format.
        
        FHIR-structured format: dict with keys like "Patient", "Condition", "Observation"
        Legacy format: list of field dictionaries with "label", "value", "confidence"
        """
        if isinstance(data, dict):
            # Check if it has FHIR resource type keys
            fhir_resource_types = {'Patient', 'Condition', 'Observation', 'MedicationStatement', 
                                 'Procedure', 'AllergyIntolerance', 'Practitioner', 'Organization'}
            return any(key in fhir_resource_types for key in data.keys())
        return False
    
    def _convert_fhir_structured_to_resources(self, fhir_data: Dict, patient_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Convert FHIR-structured extraction data to FHIR resources.
        
        Args:
            fhir_data: Dictionary with FHIR resource types as keys
            patient_id: Optional patient ID for resource references
            
        Returns:
            List of FHIR resource dictionaries
        """
        fhir_resources = []
        
        # Process Patient data
        if 'Patient' in fhir_data:
            patient_resource = self._create_patient_resource_from_structured(fhir_data['Patient'], patient_id)
            if patient_resource:
                fhir_resources.append(patient_resource)
        
        # Process Condition resources (individual conditions with dates)
        if 'Condition' in fhir_data and isinstance(fhir_data['Condition'], list):
            for condition_data in fhir_data['Condition']:
                condition_resource = self._create_condition_resource_from_structured(condition_data, patient_id)
                if condition_resource:
                    fhir_resources.append(condition_resource)
        
        # Process MedicationStatement resources (individual medications with dates)
        if 'MedicationStatement' in fhir_data and isinstance(fhir_data['MedicationStatement'], list):
            for med_data in fhir_data['MedicationStatement']:
                medication_resource = self._create_medication_resource_from_structured(med_data, patient_id)
                if medication_resource:
                    fhir_resources.append(medication_resource)
        
        # Process Observation resources (individual observations with dates)
        if 'Observation' in fhir_data and isinstance(fhir_data['Observation'], list):
            for obs_data in fhir_data['Observation']:
                observation_resource = self._create_observation_resource_from_structured(obs_data, patient_id)
                if observation_resource:
                    fhir_resources.append(observation_resource)
        
        # Process Procedure resources (individual procedures with dates)
        if 'Procedure' in fhir_data and isinstance(fhir_data['Procedure'], list):
            for proc_data in fhir_data['Procedure']:
                procedure_resource = self._create_procedure_resource_from_structured(proc_data, patient_id)
                if procedure_resource:
                    fhir_resources.append(procedure_resource)
        
        # Process AllergyIntolerance resources
        if 'AllergyIntolerance' in fhir_data and isinstance(fhir_data['AllergyIntolerance'], list):
            for allergy_data in fhir_data['AllergyIntolerance']:
                allergy_resource = self._create_allergy_resource_from_structured(allergy_data, patient_id)
                if allergy_resource:
                    fhir_resources.append(allergy_resource)
        
        # Create DocumentReference for source tracking
        doc_ref_resource = self._create_document_reference_resource(fhir_data, patient_id)
        if doc_ref_resource:
            fhir_resources.append(doc_ref_resource)
        
        self.logger.info(f"Converted FHIR-structured data to {len(fhir_resources)} FHIR resources")
        return fhir_resources
    
    def _convert_legacy_fields_to_fhir(self, extracted_fields: List[Dict], patient_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Convert legacy flat field format to FHIR resources (original logic).
        
        Args:
            extracted_fields: List of extracted field dictionaries
            patient_id: Optional patient ID for resource references
            
        Returns:
            List of FHIR resource dictionaries
        """
        fhir_resources = []
        
        try:
            # Group fields by resource type
            patient_data = {}
            conditions = []
            observations = []
            medications = []
            practitioners = []
            
            for field in extracted_fields:
                label = field.get("label", "").lower()
                value = field.get("value")
                confidence = field.get("confidence", 0.0)
                
                if not value or confidence < 0.3:  # Skip very low-confidence fields
                    continue
                
                # Categorize field by medical domain
                if any(term in label for term in ['patient', 'name', 'mrn', 'dob', 'date of birth', 'gender', 'age']):
                    patient_data[label] = field
                elif any(term in label for term in ['diagnosis', 'diagnoses', 'condition', 'conditions', 'problem', 'problems', 'chief complaint']):
                    conditions.append(field)
                elif any(term in label for term in ['medication', 'drug', 'prescription', 'rx']):
                    medications.append(field)
                elif any(term in label for term in ['vital', 'blood pressure', 'temperature', 'heart rate', 'weight', 'height']):
                    observations.append(field)
                elif any(term in label for term in ['provider', 'doctor', 'physician', 'nurse', 'practitioner']):
                    practitioners.append(field)
                else:
                    # Treat as general observation
                    observations.append(field)
            
            # Create FHIR resources
            
            # 1. Create Condition resources
            for condition_field in conditions:
                condition_resource = self._create_condition_resource(condition_field, patient_id)
                if condition_resource:
                    fhir_resources.append(condition_resource)
            
            # 2. Create Observation resources  
            for obs_field in observations:
                observation_resource = self._create_observation_resource(obs_field, patient_id)
                if observation_resource:
                    fhir_resources.append(observation_resource)
            
            # 3. Create MedicationStatement resources
            for med_field in medications:
                medication_resource = self._create_medication_resource(med_field, patient_id)
                if medication_resource:
                    fhir_resources.append(medication_resource)
            
            # 4. Create Practitioner resources
            for prac_field in practitioners:
                practitioner_resource = self._create_practitioner_resource(prac_field)
                if practitioner_resource:
                    fhir_resources.append(practitioner_resource)
            
            # 5. Create DocumentReference resource for extracted data
            doc_ref_resource = self._create_document_reference_resource(extracted_fields, patient_id)
            if doc_ref_resource:
                fhir_resources.append(doc_ref_resource)
            
            self.logger.info(f"Converted {len(extracted_fields)} fields to {len(fhir_resources)} FHIR resources")
            
        except Exception as e:
            self.logger.error(f"Error converting to FHIR: {e}", exc_info=True)
            # Fallback: create basic DocumentReference with raw data
            fhir_resources = [self._create_document_reference_resource(extracted_fields, patient_id)]
        
        return fhir_resources
    
    def _create_condition_resource(self, field: Dict, patient_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a FHIR Condition resource from extracted field."""
        try:
            condition_id = str(uuid4())
            value = field.get("value", "").strip()
            
            if not value:
                return None
            
            # Basic condition resource structure
            condition = {
                "resourceType": "Condition",
                "id": condition_id,
                "meta": {
                    "versionId": "1",
                    "lastUpdated": timezone.now().isoformat()
                },
                "code": {
                    "text": value
                },
                "clinicalStatus": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                        "code": "active"
                    }]
                }
            }
            
            # Add patient reference if available
            if patient_id:
                condition["subject"] = {"reference": f"Patient/{patient_id}"}
            
            # Add confidence as extension
            confidence = field.get("confidence", 0.0)
            if confidence > 0:
                condition["extension"] = [{
                    "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
                    "valueDecimal": confidence
                }]
            
            return condition
            
        except Exception as e:
            self.logger.error(f"Error creating Condition resource: {e}")
            return None
    
    def _create_observation_resource(self, field: Dict, patient_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a FHIR Observation resource from extracted field."""
        try:
            observation_id = str(uuid4())
            value = field.get("value", "").strip()
            label = field.get("label", "").strip()
            
            if not value:
                return None
            
            # Basic observation resource structure
            observation = {
                "resourceType": "Observation",
                "id": observation_id,
                "meta": {
                    "versionId": "1",
                    "lastUpdated": timezone.now().isoformat()
                },
                "status": "final",
                "code": {
                    "text": label
                },
                "valueString": value
            }
            
            # Add patient reference if available
            if patient_id:
                observation["subject"] = {"reference": f"Patient/{patient_id}"}
            
            # Add confidence as extension
            confidence = field.get("confidence", 0.0)
            if confidence > 0:
                observation["extension"] = [{
                    "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
                    "valueDecimal": confidence
                }]
            
            return observation
            
        except Exception as e:
            self.logger.error(f"Error creating Observation resource: {e}")
            return None
    
    def _create_medication_resource(self, field: Dict, patient_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a FHIR MedicationStatement resource from extracted field."""
        try:
            medication_id = str(uuid4())
            value = field.get("value", "").strip()
            
            if not value:
                return None
            
            # Basic medication statement resource structure
            medication = {
                "resourceType": "MedicationStatement",
                "id": medication_id,
                "meta": {
                    "versionId": "1",
                    "lastUpdated": timezone.now().isoformat()
                },
                "status": "active",
                "medicationCodeableConcept": {
                    "text": value
                }
            }
            
            # Add patient reference if available
            if patient_id:
                medication["subject"] = {"reference": f"Patient/{patient_id}"}
            
            # Add confidence as extension
            confidence = field.get("confidence", 0.0)
            if confidence > 0:
                medication["extension"] = [{
                    "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
                    "valueDecimal": confidence
                }]
            
            return medication
            
        except Exception as e:
            self.logger.error(f"Error creating MedicationStatement resource: {e}")
            return None
    
    def _create_practitioner_resource(self, field: Dict) -> Optional[Dict[str, Any]]:
        """Create a FHIR Practitioner resource from extracted field."""
        try:
            practitioner_id = str(uuid4())
            value = field.get("value", "").strip()
            
            if not value:
                return None
            
            # Basic practitioner resource structure
            practitioner = {
                "resourceType": "Practitioner",
                "id": practitioner_id,
                "meta": {
                    "versionId": "1",
                    "lastUpdated": timezone.now().isoformat()
                },
                "name": [{
                    "text": value
                }]
            }
            
            # Add confidence as extension
            confidence = field.get("confidence", 0.0)
            if confidence > 0:
                practitioner["extension"] = [{
                    "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
                    "valueDecimal": confidence
                }]
            
            return practitioner
            
        except Exception as e:
            self.logger.error(f"Error creating Practitioner resource: {e}")
            return None
    
    def _create_document_reference_resource(self, extracted_fields: List[Dict], patient_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a FHIR DocumentReference resource for the extracted data."""
        try:
            doc_ref_id = str(uuid4())
            
            # Basic document reference resource structure
            doc_reference = {
                "resourceType": "DocumentReference",
                "id": doc_ref_id,
                "meta": {
                    "versionId": "1",
                    "lastUpdated": timezone.now().isoformat()
                },
                "status": "current",
                "type": {
                    "text": "Medical Document Analysis"
                },
                "content": [{
                    "attachment": {
                        "title": "Extracted Medical Data",
                        "data": extracted_fields  # Store raw extracted data
                    }
                }]
            }
            
            # Add patient reference if available
            if patient_id:
                doc_reference["subject"] = {"reference": f"Patient/{patient_id}"}
            
            return doc_reference
            
        except Exception as e:
            self.logger.error(f"Error creating DocumentReference resource: {e}")
            # Return minimal structure
            return {
                "resourceType": "DocumentReference",
                "id": str(uuid4()),
                "status": "current",
                "content": [{"attachment": {"data": extracted_fields}}]
            }
    
    # ========================================================================
    # FHIR-Structured Resource Creation Methods
    # ========================================================================
    
    def _create_patient_resource_from_structured(self, patient_data: Dict, patient_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a FHIR Patient resource from structured extraction data."""
        try:
            # Extract patient information from structured format
            name_data = patient_data.get('name', {})
            birth_date_data = patient_data.get('birthDate', {})
            gender_data = patient_data.get('gender', {})
            identifier_data = patient_data.get('identifier', {})
            
            # Create patient resource
            patient_resource = {
                "resourceType": "Patient",
                "id": patient_id or str(uuid4()),
                "meta": {
                    "versionId": "1",
                    "lastUpdated": timezone.now().isoformat()
                }
            }
            
            # Add name if available
            if name_data.get('value'):
                name_value = name_data['value']
                if ',' in name_value:
                    # "Last, First" format
                    last, first = name_value.split(',', 1)
                    patient_resource['name'] = [{
                        "family": last.strip(),
                        "given": [first.strip()]
                    }]
                else:
                    patient_resource['name'] = [{"text": name_value}]
            
            # Add birth date if available
            if birth_date_data.get('value'):
                patient_resource['birthDate'] = birth_date_data['value']
            
            # Add gender if available
            if gender_data.get('value'):
                gender = gender_data['value'].lower()
                if gender in ['male', 'female', 'other', 'unknown']:
                    patient_resource['gender'] = gender
            
            # Add identifier (MRN) if available
            if identifier_data.get('value'):
                patient_resource['identifier'] = [{
                    "type": {"text": "MR"},
                    "value": identifier_data['value']
                }]
            
            return patient_resource
            
        except Exception as e:
            self.logger.error(f"Error creating Patient resource from structured data: {e}")
            return None
    
    def _create_condition_resource_from_structured(self, condition_data: Dict, patient_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a FHIR Condition resource from structured extraction data."""
        try:
            code_data = condition_data.get('code', {})
            onset_date_data = condition_data.get('onsetDateTime', {})
            recorded_date_data = condition_data.get('recordedDate', {})
            status = condition_data.get('status', 'active')
            
            if not code_data.get('value'):
                return None
            
            condition_resource = {
                "resourceType": "Condition",
                "id": str(uuid4()),
                "meta": {
                    "versionId": "1",
                    "lastUpdated": timezone.now().isoformat()
                },
                "code": {
                    "text": code_data['value']
                },
                "clinicalStatus": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                        "code": status
                    }]
                }
            }
            
            # Add patient reference
            if patient_id:
                condition_resource["subject"] = {"reference": f"Patient/{patient_id}"}
            
            # Add onset date if available
            if onset_date_data.get('value'):
                condition_resource["onsetDateTime"] = onset_date_data['value']
            
            # Add recorded date if available
            if recorded_date_data.get('value'):
                condition_resource["recordedDate"] = recorded_date_data['value']
            
            # Add confidence as extension
            if code_data.get('confidence'):
                condition_resource["extension"] = [{
                    "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
                    "valueDecimal": code_data['confidence']
                }]
            
            return condition_resource
            
        except Exception as e:
            self.logger.error(f"Error creating Condition resource from structured data: {e}")
            return None
    
    def _create_medication_resource_from_structured(self, med_data: Dict, patient_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a FHIR MedicationStatement resource from structured extraction data."""
        try:
            medication_data = med_data.get('medication', {})
            dosage_data = med_data.get('dosage', {})
            effective_date_data = med_data.get('effectiveDateTime', {})
            effective_period_data = med_data.get('effectivePeriod', {})
            
            if not medication_data.get('value'):
                return None
            
            medication_resource = {
                "resourceType": "MedicationStatement",
                "id": str(uuid4()),
                "meta": {
                    "versionId": "1",
                    "lastUpdated": timezone.now().isoformat()
                },
                "status": "active",
                "medicationCodeableConcept": {
                    "text": medication_data['value']
                }
            }
            
            # Add patient reference
            if patient_id:
                medication_resource["subject"] = {"reference": f"Patient/{patient_id}"}
            
            # Add dosage information if available
            if dosage_data.get('value'):
                medication_resource["dosage"] = [{
                    "text": dosage_data['value']
                }]
            
            # Add effective date/period if available
            if effective_date_data.get('value'):
                medication_resource["effectiveDateTime"] = effective_date_data['value']
            elif effective_period_data:
                period = {}
                if effective_period_data.get('start', {}).get('value'):
                    period['start'] = effective_period_data['start']['value']
                if effective_period_data.get('end', {}).get('value'):
                    period['end'] = effective_period_data['end']['value']
                if period:
                    medication_resource["effectivePeriod"] = period
            
            # Add confidence as extension
            if medication_data.get('confidence'):
                medication_resource["extension"] = [{
                    "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
                    "valueDecimal": medication_data['confidence']
                }]
            
            return medication_resource
            
        except Exception as e:
            self.logger.error(f"Error creating MedicationStatement resource from structured data: {e}")
            return None
    
    def _create_observation_resource_from_structured(self, obs_data: Dict, patient_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a FHIR Observation resource from structured extraction data."""
        try:
            code_data = obs_data.get('code', {})
            value_data = obs_data.get('value', {})
            effective_date_data = obs_data.get('effectiveDateTime', {})
            
            if not code_data.get('value'):
                return None
            
            observation_resource = {
                "resourceType": "Observation",
                "id": str(uuid4()),
                "meta": {
                    "versionId": "1",
                    "lastUpdated": timezone.now().isoformat()
                },
                "status": "final",
                "code": {
                    "text": code_data['value']
                }
            }
            
            # Add patient reference
            if patient_id:
                observation_resource["subject"] = {"reference": f"Patient/{patient_id}"}
            
            # Add value if available
            if value_data.get('value'):
                observation_resource["valueString"] = value_data['value']
            
            # Add effective date if available
            if effective_date_data.get('value'):
                observation_resource["effectiveDateTime"] = effective_date_data['value']
            
            # Add confidence as extension
            if code_data.get('confidence'):
                observation_resource["extension"] = [{
                    "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
                    "valueDecimal": code_data['confidence']
                }]
            
            return observation_resource
            
        except Exception as e:
            self.logger.error(f"Error creating Observation resource from structured data: {e}")
            return None
    
    def _create_procedure_resource_from_structured(self, proc_data: Dict, patient_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a FHIR Procedure resource from structured extraction data."""
        try:
            code_data = proc_data.get('code', {})
            performed_date_data = proc_data.get('performedDateTime', {})
            performed_period_data = proc_data.get('performedPeriod', {})
            
            if not code_data.get('value'):
                return None
            
            procedure_resource = {
                "resourceType": "Procedure",
                "id": str(uuid4()),
                "meta": {
                    "versionId": "1",
                    "lastUpdated": timezone.now().isoformat()
                },
                "status": "completed",
                "code": {
                    "text": code_data['value']
                }
            }
            
            # Add patient reference
            if patient_id:
                procedure_resource["subject"] = {"reference": f"Patient/{patient_id}"}
            
            # Add performed date/period if available
            if performed_date_data.get('value'):
                procedure_resource["performedDateTime"] = performed_date_data['value']
            elif performed_period_data:
                period = {}
                if performed_period_data.get('start', {}).get('value'):
                    period['start'] = performed_period_data['start']['value']
                if performed_period_data.get('end', {}).get('value'):
                    period['end'] = performed_period_data['end']['value']
                if period:
                    procedure_resource["performedPeriod"] = period
            
            # Add confidence as extension
            if code_data.get('confidence'):
                procedure_resource["extension"] = [{
                    "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
                    "valueDecimal": code_data['confidence']
                }]
            
            return procedure_resource
            
        except Exception as e:
            self.logger.error(f"Error creating Procedure resource from structured data: {e}")
            return None
    
    def _create_allergy_resource_from_structured(self, allergy_data: Dict, patient_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a FHIR AllergyIntolerance resource from structured extraction data."""
        try:
            substance_data = allergy_data.get('substance', {})
            reaction_data = allergy_data.get('reaction', {})
            onset_date_data = allergy_data.get('onsetDateTime', {})
            
            if not substance_data.get('value'):
                return None
            
            allergy_resource = {
                "resourceType": "AllergyIntolerance",
                "id": str(uuid4()),
                "meta": {
                    "versionId": "1",
                    "lastUpdated": timezone.now().isoformat()
                },
                "patient": {"reference": f"Patient/{patient_id}"} if patient_id else {},
                "verificationStatus": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                        "code": "confirmed"
                    }]
                },
                "type": "allergy",
                "category": ["medication"],
                "code": {
                    "text": substance_data['value']
                }
            }
            
            # Add reaction if available
            if reaction_data.get('value'):
                allergy_resource["reaction"] = [{
                    "manifestation": [{
                        "text": reaction_data['value']
                    }]
                }]
            
            # Add onset date if available
            if onset_date_data.get('value'):
                allergy_resource["onsetDateTime"] = onset_date_data['value']
            
            # Add confidence as extension
            if substance_data.get('confidence'):
                allergy_resource["extension"] = [{
                    "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
                    "valueDecimal": substance_data['confidence']
                }]
            
            return allergy_resource
            
        except Exception as e:
            self.logger.error(f"Error creating AllergyIntolerance resource from structured data: {e}")
            return None
    
    # ========================================================================
    # End FHIR-Structured Resource Creation Methods
    # ========================================================================
    
    # ========================================================================
    # Temporal Data Processing Utilities
    # ========================================================================
    
    def process_temporal_data(self, fhir_resource: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process and standardize temporal data in FHIR resources.
        
        This function takes a FHIR resource and standardizes all date/time fields
        to ensure they conform to FHIR specifications (ISO 8601 format).
        
        Args:
            fhir_resource: FHIR resource dictionary
            
        Returns:
            FHIR resource with standardized temporal data
        """
        if not isinstance(fhir_resource, dict):
            return fhir_resource
        
        # Make a copy to avoid modifying the original
        processed_resource = fhir_resource.copy()
        
        try:
            # Define temporal fields by resource type
            temporal_fields_by_type = {
                'Condition': ['onsetDateTime', 'recordedDate', 'abatementDateTime'],
                'Observation': ['effectiveDateTime', 'issued'],
                'MedicationStatement': ['effectiveDateTime'],
                'Procedure': ['performedDateTime'],
                'AllergyIntolerance': ['onsetDateTime', 'recordedDate'],
                'Patient': ['birthDate'],
                'DiagnosticReport': ['effectiveDateTime', 'issued'],
                'Encounter': ['period']  # Special handling for period
            }
            
            resource_type = processed_resource.get('resourceType')
            if resource_type in temporal_fields_by_type:
                fields_to_process = temporal_fields_by_type[resource_type]
                
                for field in fields_to_process:
                    if field in processed_resource:
                        if field == 'period':
                            # Special handling for period objects
                            processed_resource[field] = self._process_period_data(processed_resource[field])
                        else:
                            # Standard date/time field processing
                            processed_resource[field] = self.parse_and_format_date(processed_resource[field])
            
            # Also process nested period fields (effectivePeriod, performedPeriod)
            period_fields = ['effectivePeriod', 'performedPeriod']
            for period_field in period_fields:
                if period_field in processed_resource:
                    processed_resource[period_field] = self._process_period_data(processed_resource[period_field])
            
            self.logger.debug(f"Processed temporal data for {resource_type} resource")
            return processed_resource
            
        except Exception as e:
            self.logger.warning(f"Error processing temporal data: {e}")
            return fhir_resource  # Return original if processing fails
    
    def parse_and_format_date(self, date_input: Any) -> Optional[str]:
        """
        Parse and format date to FHIR-compliant format (ISO 8601) using ClinicalDateParser.
        
        Integrates the ClinicalDateParser for medical-specific date validation and parsing.
        Provides confidence scoring and validates clinical date ranges.
        
        Handles various input formats:
        - ISO 8601 strings (already compliant)
        - MM/DD/YYYY format
        - DD-MM-YYYY format
        - Natural language dates
        - Date objects
        
        Args:
            date_input: Date in various formats (string, datetime, date object)
            
        Returns:
            FHIR-compliant date string (YYYY-MM-DD) or None if parsing fails
        """
        if not date_input:
            return None
        
        # Convert to string if needed
        date_str = None
        if isinstance(date_input, str):
            date_str = date_input.strip()
        elif hasattr(date_input, 'strftime'):
            # Handle datetime objects
            date_str = date_input.strftime('%Y-%m-%d')
        elif hasattr(date_input, 'isoformat'):
            # Handle date objects
            date_str = date_input.isoformat()
        else:
            self.logger.warning(f"Unsupported date input type: {type(date_input)}")
            return None
        
        if not date_str:
            return None
        
        # Quick check: if already in ISO 8601 format and valid, return it
        if self._is_iso8601_format(date_str):
            # Still validate it's a reasonable clinical date
            parsed_date = self.date_parser.parse_single_date(date_str)
            if parsed_date:
                standardized = self.date_parser.standardize_date(parsed_date)
                self.logger.debug(f"Validated ISO date '{date_str}' -> '{standardized}'")
                return standardized
            # If validation failed, fall through to extraction
        
        # Use ClinicalDateParser to extract and validate the date
        try:
            extraction_results = self.date_parser.extract_dates(date_str)
            
            if extraction_results:
                # Take the first (highest confidence) result
                best_result = extraction_results[0]
                
                # Standardize the extracted date to ISO format
                standardized = self.date_parser.standardize_date(best_result.extracted_date)
                
                # Log confidence for monitoring
                if best_result.confidence < 0.7:
                    self.logger.warning(
                        f"Low confidence ({best_result.confidence:.2f}) parsing date '{date_str}' "
                        f"-> '{standardized}'"
                    )
                else:
                    self.logger.debug(
                        f"Parsed date '{date_str}' -> '{standardized}' "
                        f"(confidence: {best_result.confidence:.2f}, method: {best_result.extraction_method})"
                    )
                
                return standardized
            else:
                self.logger.warning(f"ClinicalDateParser could not extract date from: '{date_str}'")
                return None
                
        except Exception as e:
            self.logger.error(f"Error parsing date '{date_str}' with ClinicalDateParser: {e}")
            
            # Fallback to dateutil as last resort
            try:
                from dateutil.parser import parse as dateutil_parse
                parsed_date = dateutil_parse(date_str)
                fallback_result = parsed_date.strftime('%Y-%m-%d')
                self.logger.warning(f"Used fallback parser for '{date_str}' -> '{fallback_result}'")
                return fallback_result
            except:
                self.logger.error(f"All date parsing methods failed for: '{date_str}'")
                return None
    
    def _is_iso8601_format(self, date_str: str) -> bool:
        """Check if a date string is already in ISO 8601 format."""
        import re
        
        # ISO 8601 patterns
        iso_patterns = [
            r'^\d{4}-\d{2}-\d{2}$',                          # YYYY-MM-DD
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$',       # YYYY-MM-DDTHH:MM:SS
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+$',  # YYYY-MM-DDTHH:MM:SS.fff
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$',  # With timezone
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2}$'  # With milliseconds and timezone
        ]
        
        return any(re.match(pattern, date_str) for pattern in iso_patterns)
    
    def _process_period_data(self, period_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process period objects (start/end dates).
        
        Args:
            period_data: Period object with 'start' and/or 'end' fields
            
        Returns:
            Processed period object with standardized dates
        """
        if not isinstance(period_data, dict):
            return period_data
        
        processed_period = period_data.copy()
        
        if 'start' in processed_period:
            processed_period['start'] = self.parse_and_format_date(processed_period['start'])
        
        if 'end' in processed_period:
            processed_period['end'] = self.parse_and_format_date(processed_period['end'])
        
        return processed_period
    
    def validate_fhir_temporal_compliance(self, fhir_resource: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate that temporal fields in a FHIR resource comply with FHIR specifications.
        
        Args:
            fhir_resource: FHIR resource to validate
            
        Returns:
            Dictionary with validation results:
            {
                'is_valid': bool,
                'errors': List[str],
                'warnings': List[str],
                'processed_fields': List[str]
            }
        """
        validation_result = {
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'processed_fields': []
        }
        
        if not isinstance(fhir_resource, dict):
            validation_result['is_valid'] = False
            validation_result['errors'].append("Resource is not a dictionary")
            return validation_result
        
        resource_type = fhir_resource.get('resourceType')
        if not resource_type:
            validation_result['warnings'].append("No resourceType specified")
        
        # Check common temporal fields
        temporal_fields = ['onsetDateTime', 'recordedDate', 'effectiveDateTime', 
                          'performedDateTime', 'birthDate', 'issued']
        
        for field in temporal_fields:
            if field in fhir_resource:
                field_value = fhir_resource[field]
                if field_value and isinstance(field_value, str):
                    if self._is_iso8601_format(field_value):
                        validation_result['processed_fields'].append(f"{field}: VALID")
                    else:
                        validation_result['errors'].append(f"{field}: Invalid ISO 8601 format: {field_value}")
                        validation_result['is_valid'] = False
        
        # Check period fields
        period_fields = ['period', 'effectivePeriod', 'performedPeriod']
        for field in period_fields:
            if field in fhir_resource:
                period_data = fhir_resource[field]
                if isinstance(period_data, dict):
                    for period_key in ['start', 'end']:
                        if period_key in period_data:
                            period_value = period_data[period_key]
                            if period_value and isinstance(period_value, str):
                                if self._is_iso8601_format(period_value):
                                    validation_result['processed_fields'].append(f"{field}.{period_key}: VALID")
                                else:
                                    validation_result['errors'].append(f"{field}.{period_key}: Invalid ISO 8601 format: {period_value}")
                                    validation_result['is_valid'] = False
        
        return validation_result
    
    # ========================================================================
    # End Temporal Data Processing Utilities
    # ========================================================================
    
    def _parse_ai_response_content(self, response_content: str) -> Dict[str, Any]:
        """
        Safely parses the JSON string from the AI response.
        Handles cases where the response is not valid JSON or is embedded in markdown.
        """
        # TEMPORARY DIAGNOSTIC LOG - CAPTURE RAW AI RESPONSE
        self.logger.critical(f"🔍 RAW AI RESPONSE (Length: {len(response_content)}): {response_content}")
        
        try:
            # First, try to load the entire string as JSON
            return json.loads(response_content)
        except json.JSONDecodeError as e:
            self.logger.warning(f"Failed to parse the full AI response as JSON: {e}. Trying to extract from markdown.")
            self.logger.warning(f"PROBLEMATIC RESPONSE: {response_content[:300]}...")
            # If that fails, try to extract JSON from a markdown code block
            match = re.search(r"```(json)?\s*(.*?)\s*```", response_content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(2))
                except json.JSONDecodeError as e:
                    self.logger.error(f"Failed to parse JSON from markdown block: {e}")
                    raise DocumentProcessingError("Invalid JSON structure in AI response markdown.") from e
            else:
                self.logger.error("AI response is not valid JSON and does not contain a markdown JSON block.")
                raise DocumentProcessingError("AI response is not valid JSON.")

    def _get_anthropic_client(self):
        """Initializes the Anthropic client if the API key is available."""
        if self.anthropic_key and anthropic:
            try:
                # Use the current Anthropic client class
                return anthropic.Anthropic(
                    api_key=self.anthropic_key
                )
            except Exception as e:
                self.logger.warning(f"Failed to initialize Anthropic client: {e}")
                return None
        return None

    def _convert_fhir_to_fields(self, fhir_data: Dict) -> List[Dict]:
        """
        Convert FHIR-structured data OR flat field data to the legacy fields format.
        
        Args:
            fhir_data: FHIR-structured response from AI OR flat field structure
            
        Returns:
            List of field dictionaries compatible with existing processing pipeline
        """
        fields = []
        
        # CRITICAL FIX: Handle flat field structure (new format from prompts)
        # Check if this is a flat structure (patient_name, date_of_birth, etc.)
        flat_field_indicators = ['patient_name', 'date_of_birth', 'medical_record_number', 'diagnoses', 'medications', 'allergies']
        if any(field in fhir_data for field in flat_field_indicators):
            self.logger.info("Converting flat field structure to legacy format")
            for field_name, field_data in fhir_data.items():
                if isinstance(field_data, dict) and 'value' in field_data:
                    fields.append({
                        'label': field_name,
                        'value': field_data['value'],
                        'confidence': field_data.get('confidence', 0.8),
                        'source_text': field_data.get('source_text', ''),
                        'char_position': field_data.get('char_position', 0),
                        'fhir_resource': self._map_field_to_fhir_resource(field_name),
                        'fhir_field': self._map_field_to_fhir_field(field_name)
                    })
            return fields
        
        # Convert Patient data (FHIR structure)
        if 'Patient' in fhir_data:
            patient = fhir_data['Patient']
            for key, value_obj in patient.items():
                if isinstance(value_obj, dict) and 'value' in value_obj:
                    fields.append({
                        'label': f'patient_{key}',
                        'value': value_obj['value'],
                        'confidence': value_obj.get('confidence', 0.8),
                        'source_text': value_obj.get('source_text', ''),
                        'char_position': value_obj.get('char_position', 0),
                        'fhir_resource': 'Patient',
                        'fhir_field': key
                    })
        
        # Convert Condition data (diagnoses)
        if 'Condition' in fhir_data:
            for condition in fhir_data['Condition']:
                if 'code' in condition and isinstance(condition['code'], dict):
                    fields.append({
                        'label': 'diagnosis',
                        'value': condition['code'].get('value', ''),
                        'confidence': condition['code'].get('confidence', 0.8),
                        'fhir_resource': 'Condition',
                        'status': condition.get('status', 'active')
                    })
        
        # Convert Observation data (vitals, labs)
        if 'Observation' in fhir_data:
            for observation in fhir_data['Observation']:
                if 'code' in observation and isinstance(observation['code'], dict):
                    obs_label = observation['code'].get('value', 'observation')
                    obs_value = ''
                    obs_confidence = observation['code'].get('confidence', 0.8)
                    
                    if 'value' in observation and isinstance(observation['value'], dict):
                        obs_value = observation['value'].get('value', '')
                        obs_confidence = min(obs_confidence, observation['value'].get('confidence', 0.8))
                    
                    fields.append({
                        'label': f'observation_{obs_label.lower().replace(" ", "_")}',
                        'value': obs_value,
                        'confidence': obs_confidence,
                        'fhir_resource': 'Observation',
                        'observation_type': obs_label
                    })
        
        # Convert MedicationStatement data
        if 'MedicationStatement' in fhir_data:
            for medication in fhir_data['MedicationStatement']:
                if 'medication' in medication and isinstance(medication['medication'], dict):
                    med_name = medication['medication'].get('value', '')
                    dosage = ''
                    confidence = medication['medication'].get('confidence', 0.8)
                    
                    if 'dosage' in medication and isinstance(medication['dosage'], dict):
                        dosage = medication['dosage'].get('value', '')
                        confidence = min(confidence, medication['dosage'].get('confidence', 0.7))
                    
                    fields.append({
                        'label': 'medication',
                        'value': f"{med_name}" + (f" - {dosage}" if dosage else ""),
                        'confidence': confidence,
                        'fhir_resource': 'MedicationStatement',
                        'medication_name': med_name,
                        'dosage': dosage
                    })
        
        # Convert Procedure data
        if 'Procedure' in fhir_data:
            for procedure in fhir_data['Procedure']:
                if 'code' in procedure and isinstance(procedure['code'], dict):
                    proc_name = procedure['code'].get('value', '')
                    proc_date = ''
                    confidence = procedure['code'].get('confidence', 0.8)
                    
                    if 'date' in procedure and isinstance(procedure['date'], dict):
                        proc_date = procedure['date'].get('value', '')
                        confidence = min(confidence, procedure['date'].get('confidence', 0.7))
                    
                    fields.append({
                        'label': 'procedure',
                        'value': proc_name + (f" ({proc_date})" if proc_date else ""),
                        'confidence': confidence,
                        'fhir_resource': 'Procedure',
                        'procedure_name': proc_name,
                        'procedure_date': proc_date
                    })
        
        # Convert AllergyIntolerance data
        if 'AllergyIntolerance' in fhir_data:
            for allergy in fhir_data['AllergyIntolerance']:
                if 'substance' in allergy and isinstance(allergy['substance'], dict):
                    substance = allergy['substance'].get('value', '')
                    reaction = ''
                    confidence = allergy['substance'].get('confidence', 0.8)
                    
                    if 'reaction' in allergy and isinstance(allergy['reaction'], dict):
                        reaction = allergy['reaction'].get('value', '')
                        confidence = min(confidence, allergy['reaction'].get('confidence', 0.7))
                    
                    fields.append({
                        'label': 'allergy',
                        'value': substance + (f" - {reaction}" if reaction else ""),
                        'confidence': confidence,
                        'fhir_resource': 'AllergyIntolerance',
                        'substance': substance,
                        'reaction': reaction
                    })
        
        self.logger.info(f"Converted FHIR structure to {len(fields)} fields")
        return fields
    
    def _map_field_to_fhir_resource(self, field_name: str) -> str:
        """Map field name to appropriate FHIR resource type."""
        field_mapping = {
            'patient_name': 'Patient',
            'date_of_birth': 'Patient', 
            'medical_record_number': 'Patient',
            'sex': 'Patient',
            'age': 'Patient',
            'diagnoses': 'Condition',
            'procedures': 'Procedure',
            'medications': 'MedicationStatement',
            'allergies': 'AllergyIntolerance'
        }
        return field_mapping.get(field_name, 'Unknown')
    
    def _map_field_to_fhir_field(self, field_name: str) -> str:
        """Map field name to appropriate FHIR field name."""
        field_mapping = {
            'patient_name': 'name',
            'date_of_birth': 'birthDate',
            'medical_record_number': 'identifier',
            'sex': 'gender',
            'age': 'extension',
            'diagnoses': 'code',
            'procedures': 'code',
            'medications': 'medicationCodeableConcept',
            'allergies': 'substance'
        }
        return field_mapping.get(field_name, field_name)


# ============================================================================
# MULTI-STRATEGY RESPONSE PARSER
# ============================================================================

class ResponseParser:
    """
    Multi-fallback JSON parsing strategies for AI response parsing.
    Handles medical document AI responses with 5 different fallback strategies.
    
    Like having 5 different wrenches in the toolbox - if one don't work,
    try the next one until that stubborn bolt comes loose.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def extract_structured_data(self, text_content: str) -> List[Dict[str, Any]]:
        """
        Extract structured data from AI response using multiple fallback strategies.
        
        Like troubleshooting a car that won't start - we try the obvious stuff first,
        then get more creative if that don't work.
        
        Args:
            text_content: Raw text response from AI
            
        Returns:
            List of structured fields with id, label, value, and confidence
        """
        self.logger.info(f"Parsing response of {len(text_content)} characters")
        
        # Strategy 1: Direct JSON parsing
        try:
            return self._parse_direct_json(text_content)
        except json.JSONDecodeError:
            self.logger.warning("Direct JSON parsing failed, trying sanitized approach")
        
        # Strategy 2: Sanitized JSON parsing
        try:
            return self._parse_sanitized_json(text_content)
        except json.JSONDecodeError:
            self.logger.warning("Sanitized JSON parsing failed, trying code block extraction")
        
        # Strategy 3: Code block extraction
        try:
            return self._parse_code_block_json(text_content)
        except json.JSONDecodeError:
            self.logger.warning("Code block parsing failed, trying regex extraction")
        
        # Strategy 4: Regex key-value extraction
        try:
            return self._parse_regex_patterns(text_content)
        except Exception:
            self.logger.warning("Regex parsing failed, trying medical pattern recognition")
        
        # Strategy 5: Medical pattern recognition fallback
        return self._parse_medical_patterns(text_content)
    
    def _parse_direct_json(self, text_content: str) -> List[Dict[str, Any]]:
        """
        Strategy 1: Direct JSON parsing of the response.
        
        Like checking if the engine starts with a simple key turn.
        
        Args:
            text_content: Raw response text
            
        Returns:
            Parsed fields list
            
        Raises:
            json.JSONDecodeError: If content is not valid JSON
        """
        data = json.loads(text_content.strip())
        self.logger.info("Successfully parsed response as direct JSON")
        return self._convert_json_to_fields(data)
    
    def _parse_sanitized_json(self, text_content: str) -> List[Dict[str, Any]]:
        """
        Strategy 2: Sanitized JSON parsing - clean up common formatting issues.
        
        Like cleaning the spark plugs before trying to start the engine again.
        
        Args:
            text_content: Raw response text
            
        Returns:
            Parsed fields list
            
        Raises:
            json.JSONDecodeError: If sanitized content is not valid JSON
        """
        # Remove markdown code block markers
        sanitized_text = text_content.strip()
        sanitized_text = re.sub(r'^```json\s*', '', sanitized_text)
        sanitized_text = re.sub(r'\s*```$', '', sanitized_text)
        
        # If the response starts with a curly brace, extract just the JSON portion
        if sanitized_text.startswith('{'):
            # Find matching closing bracket
            open_count = 0
            close_idx = -1
            
            for i, char in enumerate(sanitized_text):
                if char == '{':
                    open_count += 1
                elif char == '}':
                    open_count -= 1
                    if open_count == 0:
                        close_idx = i
                        break
            
            if close_idx >= 0:
                sanitized_text = sanitized_text[:close_idx + 1]
                self.logger.info("Extracted complete JSON object from sanitized text")
        
        data = json.loads(sanitized_text)
        self.logger.info("Successfully parsed sanitized JSON")
        return self._convert_json_to_fields(data)
    
    def _parse_code_block_json(self, text_content: str) -> List[Dict[str, Any]]:
        """
        Strategy 3: Extract JSON from markdown code blocks.
        
        Like looking for the problem inside the hood instead of just at the dashboard.
        
        Args:
            text_content: Raw response text
            
        Returns:
            Parsed fields list
            
        Raises:
            json.JSONDecodeError: If code block content is not valid JSON
        """
        # Look for JSON-like content between ``` markers
        json_match = re.search(r'```(?:json)?(.*?)```', text_content, re.DOTALL)
        
        if not json_match:
            raise json.JSONDecodeError("No code block found", text_content, 0)
        
        json_str = json_match.group(1).strip()
        data = json.loads(json_str)
        self.logger.info("Successfully parsed JSON from code block")
        return self._convert_json_to_fields(data)
    
    def _parse_regex_patterns(self, text_content: str) -> List[Dict[str, Any]]:
        """
        Strategy 4: Regex-based key-value extraction for non-JSON responses.
        
        Like using a wrench when the socket set ain't working.
        
        Args:
            text_content: Raw response text
            
        Returns:
            Parsed fields list
        """
        # Extract key-value pairs using regex
        pairs = re.findall(r'([A-Za-z][A-Za-z0-9\s]*?):\s*([^:\n]+)', text_content)
        
        if not pairs:
            raise ValueError("No key-value pairs found in text")
        
        fields = []
        for i, (key, value) in enumerate(pairs):
            # Clean up the key and value
            clean_key = key.strip()
            clean_value = value.strip()
            
            # Skip very short or invalid entries
            if len(clean_key) < 2 or len(clean_value) < 1:
                continue
            
            fields.append({
                "id": str(i + 1),
                "label": clean_key,
                "value": clean_value,
                "confidence": 0.7  # Lower confidence for regex extraction
            })
        
        self.logger.info(f"Extracted {len(fields)} fields using regex patterns")
        return fields
    
    def _parse_medical_patterns(self, text_content: str) -> List[Dict[str, Any]]:
        """
        Strategy 5: Medical pattern recognition fallback for difficult documents.
        
        Like pulling out the manual and doing things the old-fashioned way.
        
        Args:
            text_content: Raw response text
            
        Returns:
            Parsed fields list (may be empty if no patterns found)
        """
        medical_fields = []
        
        # Patient name patterns - enhanced for conversational text
        patient_name_patterns = [
            r'Patient:?\s*([A-Z][a-z]+,\s*[A-Z][a-z\s]+)',
            r'Name:?\s*([A-Z][a-z]+,\s*[A-Z][a-z\s]+)',
            r'patient\s+([A-Z][a-z]+,\s*[A-Z][a-z\s]+)',  # "patient Johnson, Mary"
            r'for patient\s+([A-Z][a-z]+,\s*[A-Z][a-z\s]+)',  # "for patient Johnson, Mary"
            r'([A-Z][A-Z\s]+,\s*[A-Z][A-Z\s]+)'  # All caps names
        ]
        
        for pattern in patient_name_patterns:
            match = re.search(pattern, text_content)
            if match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "patientName",
                    "value": match.group(1).strip(),
                    "confidence": 0.8
                })
                break
        
        # Date of birth patterns - enhanced for conversational text
        dob_patterns = [
            r'DOB:?\s*(\d{1,2}/\d{1,2}/\d{4})',
            r'Date of Birth:?\s*(\d{1,2}/\d{1,2}/\d{4})',
            r'Born:?\s*(\d{1,2}/\d{1,2}/\d{4})',
            r'was born on\s*(\d{1,2}/\d{1,2}/\d{4})',  # "was born on 12/05/1990"
            r'birth date:?\s*(\d{1,2}/\d{1,2}/\d{4})'
        ]
        
        for pattern in dob_patterns:
            match = re.search(pattern, text_content)
            if match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "dateOfBirth",
                    "value": match.group(1).strip(),
                    "confidence": 0.9
                })
                break
        
        # Gender/Sex patterns - enhanced for conversational text
        sex_patterns = [
            r'Sex:?\s*(Male|Female|M|F)',
            r'Gender:?\s*(Male|Female|M|F)',
            r'Patient gender is\s*(Male|Female|M|F)',  # "Patient gender is Female"
            r'gender\s+is\s*(Male|Female|M|F)'
        ]
        
        for pattern in sex_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                sex_value = match.group(1).upper()
                if sex_value in ['M', 'MALE']:
                    sex_value = 'Male'
                elif sex_value in ['F', 'FEMALE']:
                    sex_value = 'Female'
                
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "sex",
                    "value": sex_value,
                    "confidence": 0.9
                })
                break
        
        # Age patterns
        age_patterns = [
            r'Age:?\s*(\d+)\s*(?:years?|y\.?o\.?)',
            r'(\d+)\s*(?:year old|years old|yo)'
        ]
        
        for pattern in age_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "age",
                    "value": match.group(1).strip(),
                    "confidence": 0.8
                })
                break
        
        # Medical Record Number patterns - enhanced for conversational text
        mrn_patterns = [
            r'MR#:?\s*(\d+)',
            r'MRN:?\s*(\d+)',
            r'Medical Record:?\s*(\d+)',
            r'MRN\s+(\d+)\s+was assigned',  # "MRN 98765 was assigned"
            r'record number:?\s*(\d+)'
        ]
        
        for pattern in mrn_patterns:
            match = re.search(pattern, text_content)
            if match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "medicalRecordNumber",
                    "value": match.group(1).strip(),
                    "confidence": 0.9
                })
                break
        
        # Diagnosis patterns
        diagnoses = self._extract_diagnoses(text_content)
        if diagnoses:
            medical_fields.append({
                "id": str(len(medical_fields) + 1),
                "label": "diagnoses",
                "value": diagnoses,
                "confidence": 0.7
            })
        
        # Medication patterns
        medications = self._extract_medications(text_content)
        if medications:
            medical_fields.append({
                "id": str(len(medical_fields) + 1),
                "label": "medications",
                "value": medications,
                "confidence": 0.7
            })
        
        # Allergy patterns
        allergies = self._extract_allergies(text_content)
        if allergies:
            medical_fields.append({
                "id": str(len(medical_fields) + 1),
                "label": "allergies",
                "value": allergies,
                "confidence": 0.7
            })
        
        self.logger.info(f"Extracted {len(medical_fields)} fields using medical patterns")
        return medical_fields
    
    def _extract_diagnoses(self, text_content: str) -> Optional[List[str]]:
        """Extract diagnosis information from text"""
        diagnoses = []
        
        # Look for problem lists
        problem_section = re.search(
            r'PROBLEM LIST(.*?)(?:^[A-Z\s]+:|$)', 
            text_content, 
            re.MULTILINE | re.DOTALL
        )
        
        if problem_section:
            problem_text = problem_section.group(1)
            # Find all problem entries, handling blank lines between them
            problem_entries = re.findall(
                r'Problem Name:\s*([^\n]+).*?Life Cycle Status:\s*([^\n]+)', 
                problem_text, 
                re.DOTALL
            )
            
            for diagnosis, status in problem_entries:
                diagnoses.append(f"{diagnosis.strip()} ({status.strip()})")
        
        # Look for preoperative diagnosis
        preop_match = re.search(
            r'PREOPERATIVE DIAGNOSIS:(.*?)(?:POSTOPERATIVE|PROCEDURE|$)', 
            text_content, 
            re.DOTALL
        )
        
        if preop_match and preop_match.group(1).strip():
            diagnoses.append("Preoperative: " + preop_match.group(1).strip())
        
        # Look for postoperative diagnosis
        postop_match = re.search(
            r'POSTOPERATIVE DIAGNOSIS:(.*?)(?:PROCEDURE|SURGEON|$)', 
            text_content, 
            re.DOTALL
        )
        
        if postop_match and postop_match.group(1).strip():
            diagnoses.append("Postoperative: " + postop_match.group(1).strip())
        
        return diagnoses if diagnoses else None
    
    def _extract_medications(self, text_content: str) -> Optional[List[str]]:
        """Extract medication information from text"""
        medications = []
        
        # Look for medication sections
        med_patterns = [
            r'Medication Name:\s*([^\n]+).*?Ingredients:\s*([^\n]+)',
            r'Medications?:?\s*([^\n]+)',
            r'Current Medications?:?\s*([^\n]+)'
        ]
        
        for pattern in med_patterns:
            matches = re.findall(pattern, text_content, re.DOTALL)
            for match in matches:
                if isinstance(match, tuple):
                    # Handle medication name + ingredients pattern
                    med_name, ingredients = match
                    medications.append(f"{med_name.strip()} ({ingredients.strip()})")
                else:
                    # Handle simple medication pattern
                    medications.append(match.strip())
        
        return medications if medications else None
    
    def _extract_allergies(self, text_content: str) -> Optional[List[str]]:
        """Extract allergy information from text"""
        allergy_patterns = [
            r'ALLERG(?:Y|IES)(?:\s+LIST)?:?\s*([^\n]+)',
            r'Known Allergies:?\s*([^\n]+)',
            r'Drug Allergies:?\s*([^\n]+)'
        ]
        
        for pattern in allergy_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                allergy_text = match.group(1).strip()
                # Split by common delimiters
                allergies = [a.strip() for a in re.split(r'[,;]\s*', allergy_text) if a.strip()]
                return allergies if len(allergies) > 1 else [allergy_text]
        
        return None
    
    def _convert_json_to_fields(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert parsed JSON data to standardized field format with snippet support.
        
        Like organizing the parts after you take apart an engine - 
        everything needs its proper place and label, plus the manual page reference.
        
        Args:
            data: Parsed JSON data (may include snippet data)
            
        Returns:
            List of field dictionaries with snippet support
        """
        fields = []
        
        for i, (key, value) in enumerate(data.items()):
            # Handle new snippet-enhanced structure with value, confidence, source_text, char_position
            if isinstance(value, dict) and 'value' in value:
                field_dict = {
                    "id": str(i + 1),
                    "label": key,
                    "value": value['value'],
                    "confidence": float(value.get('confidence', 0.9))
                }
                
                # Add snippet data if available
                if 'source_text' in value:
                    field_dict["source_text"] = value['source_text']
                
                if 'char_position' in value:
                    field_dict["char_position"] = value['char_position']
                
                fields.append(field_dict)
                
            # Handle simple key-value pairs (legacy format)
            else:
                fields.append({
                    "id": str(i + 1),
                    "label": key,
                    "value": str(value) if value is not None else "",
                    "confidence": 0.9,  # Default confidence for simple values
                    "source_text": "",  # Empty snippet for legacy data
                    "char_position": 0   # Default position for legacy data
                })
        
        return fields
    
    def validate_parsed_fields(self, fields: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate the quality of parsed fields.
        
        Like checking that all the bolts are tight before taking the car for a spin.
        
        Args:
            fields: List of parsed field dictionaries
            
        Returns:
            Validation results
        """
        validation = {
            "is_valid": True,
            "field_count": len(fields),
            "avg_confidence": 0.0,
            "issues": [],
            "required_fields_present": []
        }
        
        if not fields:
            validation["is_valid"] = False
            validation["issues"].append("No fields extracted")
            return validation
        
        # Calculate average confidence
        confidences = [f.get("confidence", 0.0) for f in fields]
        validation["avg_confidence"] = sum(confidences) / len(confidences)
        
        # Check for required medical fields
        required_fields = ["patientName", "dateOfBirth", "medicalRecordNumber"]
        present_labels = [f.get("label", "").lower() for f in fields]
        
        for req_field in required_fields:
            if any(req_field.lower() in label for label in present_labels):
                validation["required_fields_present"].append(req_field)
        
        # Quality checks
        if validation["avg_confidence"] < 0.5:
            validation["issues"].append("Low average confidence score")
        
        if len(validation["required_fields_present"]) == 0:
            validation["issues"].append("No critical patient demographics found")
        
        return validation


class PatientDataComparisonService:
    """
    Service class for comparing extracted patient data against existing patient records.
    
    Provides comprehensive comparison logic, discrepancy detection, and smart suggestions
    for resolving data conflicts during document review process.
    """
    
    def __init__(self):
        """Initialize the patient data comparison service."""
        self.confidence_threshold_high = 0.8
        self.confidence_threshold_medium = 0.5
        self.similarity_threshold = 0.85  # For fuzzy string matching
        
    def compare_patient_data(self, document, patient):
        """
        Compare extracted patient data against existing patient record.
        
        Args:
            document: Document instance with parsed data
            patient: Patient instance to compare against
            
        Returns:
            PatientDataComparison instance with comparison results
        """
        from apps.documents.models import PatientDataComparison
        
        # Get or create comparison record
        comparison, created = PatientDataComparison.objects.get_or_create(
            document=document,
            patient=patient,
            defaults={
                'parsed_data': document.parsed_data,
                'status': 'pending'
            }
        )
        
        if not created and comparison.status == 'resolved':
            # Return existing resolved comparison
            return comparison
        
        # Extract patient demographics from document
        extracted_data = self._extract_patient_demographics(document)
        existing_data = self._get_patient_record_data(patient)
        
        # Perform field-by-field comparison
        comparison_results = self.identify_discrepancies(extracted_data, existing_data)
        
        # Generate suggestions based on comparison
        suggestions = self.generate_suggestions(comparison_results)
        
        # Update comparison record
        comparison.comparison_data = comparison_results
        comparison.total_fields_compared = len(comparison_results)
        comparison.discrepancies_found = sum(1 for field in comparison_results.values() 
                                           if field.get('has_discrepancy', False))
        comparison.overall_confidence_score = self._calculate_overall_confidence(extracted_data)
        comparison.data_quality_score = self._calculate_data_quality_score(extracted_data)
        comparison.status = 'in_progress' if comparison.discrepancies_found > 0 else 'skipped'
        comparison.save()
        
        return comparison
    
    def identify_discrepancies(self, extracted_data, patient_record):
        """
        Perform field-by-field comparison and identify discrepancies.
        
        Args:
            extracted_data: Dictionary of extracted patient data
            patient_record: Dictionary of existing patient record data
            
        Returns:
            Dictionary with comparison results for each field
        """
        comparison_results = {}
        
        # Common patient fields to compare
        field_mappings = {
            'patient_name': ['first_name', 'last_name', 'full_name'],
            'patientName': ['first_name', 'last_name', 'full_name'],
            'date_of_birth': ['date_of_birth', 'dob'],
            'dateOfBirth': ['date_of_birth', 'dob'],
            'dob': ['date_of_birth'],
            'gender': ['gender'],
            'sex': ['gender'],
            'phone': ['phone_number', 'phone'],
            'phone_number': ['phone_number', 'phone'],
            'address': ['address'],
            'email': ['email'],
            'mrn': ['mrn'],
            'ssn': ['ssn'],
            'insurance': ['insurance_info'],
        }
        
        for extracted_field, patient_field_options in field_mappings.items():
            if extracted_field in extracted_data:
                extracted_value = extracted_data[extracted_field]
                
                # Handle both old format (string) and new format (dict with value/confidence)
                if isinstance(extracted_value, dict):
                    ext_value = extracted_value.get('value', '')
                    confidence = float(extracted_value.get('confidence', 0.0))
                else:
                    ext_value = str(extracted_value) if extracted_value else ''
                    confidence = 0.5
                
                # Find matching field in patient record
                patient_value = None
                matched_field = None
                
                for field_option in patient_field_options:
                    if field_option in patient_record and patient_record[field_option]:
                        patient_value = str(patient_record[field_option])
                        matched_field = field_option
                        break
                
                # Compare values and detect discrepancies
                has_discrepancy, similarity_score = self._compare_field_values(
                    ext_value, patient_value, extracted_field
                )
                
                comparison_results[extracted_field] = {
                    'extracted_value': ext_value,
                    'patient_value': patient_value or '',
                    'matched_field': matched_field,
                    'has_discrepancy': has_discrepancy,
                    'similarity_score': similarity_score,
                    'confidence': confidence,
                    'discrepancy_type': self._classify_discrepancy(ext_value, patient_value, similarity_score),
                    'suggested_resolution': self._suggest_resolution(ext_value, patient_value, confidence, similarity_score),
                    'field_category': self._categorize_field(extracted_field)
                }
        
        return comparison_results
    
    def generate_suggestions(self, comparison_data):
        """
        Generate smart suggestions for resolving data conflicts.
        
        Args:
            comparison_data: Dictionary with comparison results
            
        Returns:
            Dictionary with suggestions for each field
        """
        suggestions = {
            'auto_resolutions': [],
            'manual_review_required': [],
            'high_confidence_updates': [],
            'low_confidence_warnings': []
        }
        
        for field_name, field_data in comparison_data.items():
            if not field_data.get('has_discrepancy', False):
                continue
                
            confidence = field_data.get('confidence', 0.0)
            similarity = field_data.get('similarity_score', 0.0)
            suggested_resolution = field_data.get('suggested_resolution', 'manual_edit')
            
            suggestion = {
                'field_name': field_name,
                'extracted_value': field_data.get('extracted_value', ''),
                'patient_value': field_data.get('patient_value', ''),
                'confidence': confidence,
                'similarity': similarity,
                'suggested_action': suggested_resolution,
                'reasoning': self._generate_suggestion_reasoning(field_data)
            }
            
            # Categorize suggestions
            if confidence >= self.confidence_threshold_high and suggested_resolution == 'use_extracted':
                suggestions['auto_resolutions'].append(suggestion)
            elif confidence >= self.confidence_threshold_high:
                suggestions['high_confidence_updates'].append(suggestion)
            elif confidence < self.confidence_threshold_medium:
                suggestions['low_confidence_warnings'].append(suggestion)
            else:
                suggestions['manual_review_required'].append(suggestion)
        
        return suggestions
    
    def validate_data_quality(self, field_data):
        """
        Validate data quality and format consistency.
        
        Args:
            field_data: Dictionary of field data to validate
            
        Returns:
            Dictionary with validation results and quality score
        """
        validation_results = {
            'overall_quality_score': 0.0,
            'field_validations': {},
            'format_issues': [],
            'completeness_score': 0.0
        }
        
        total_fields = len(field_data)
        valid_fields = 0
        
        for field_name, field_value in field_data.items():
            field_validation = self._validate_individual_field(field_name, field_value)
            validation_results['field_validations'][field_name] = field_validation
            
            if field_validation['is_valid']:
                valid_fields += 1
            else:
                validation_results['format_issues'].extend(field_validation['issues'])
        
        # Calculate scores
        validation_results['completeness_score'] = (valid_fields / total_fields) if total_fields > 0 else 0.0
        validation_results['overall_quality_score'] = self._calculate_quality_score(validation_results)
        
        return validation_results
    
    def _extract_patient_demographics(self, document):
        """Extract patient demographic data from document's parsed data."""
        if not hasattr(document, 'parsed_data') or not document.parsed_data:
            return {}
        
        extraction_data = document.parsed_data.extraction_json
        if not extraction_data:
            return {}
        
        # Handle different extraction formats
        if isinstance(extraction_data, dict):
            return extraction_data
        elif isinstance(extraction_data, list):
            # Convert list format to dictionary
            result = {}
            for item in extraction_data:
                if isinstance(item, dict) and 'label' in item:
                    result[item['label']] = item
            return result
        
        return {}
    
    def _get_patient_record_data(self, patient):
        """Extract relevant data from patient record for comparison."""
        return {
            'first_name': patient.first_name,
            'last_name': patient.last_name,
            'full_name': f"{patient.first_name} {patient.last_name}".strip(),
            'date_of_birth': patient.date_of_birth if patient.date_of_birth else '',
            'dob': patient.date_of_birth if patient.date_of_birth else '',
            'gender': patient.gender,
            'phone_number': patient.phone,  # Note: Patient model uses 'phone', not 'phone_number'
            'phone': patient.phone,
            'address': patient.address,
            'email': patient.email,
            'mrn': patient.mrn,
            'ssn': patient.ssn,
            'insurance_info': getattr(patient, 'insurance_info', ''),  # May not exist
        }
    
    def _compare_field_values(self, extracted_value, patient_value, field_name):
        """
        Compare two field values and determine if there's a discrepancy.
        
        Returns:
            Tuple of (has_discrepancy: bool, similarity_score: float)
        """
        if not extracted_value and not patient_value:
            return False, 1.0  # Both empty, no discrepancy
        
        if not extracted_value or not patient_value:
            return True, 0.0  # One empty, one has value
        
        # Normalize values for comparison
        ext_normalized = self._normalize_value(extracted_value, field_name)
        pat_normalized = self._normalize_value(patient_value, field_name)
        
        # Exact match check
        if ext_normalized == pat_normalized:
            return False, 1.0
        
        # Fuzzy string similarity for text fields
        similarity = self._calculate_string_similarity(ext_normalized, pat_normalized)
        has_discrepancy = similarity < self.similarity_threshold
        
        return has_discrepancy, similarity
    
    def _normalize_value(self, value, field_name):
        """Normalize a value for comparison based on field type."""
        if not value:
            return ''
        
        value_str = str(value).strip().lower()
        
        # Date normalization
        if any(term in field_name.lower() for term in ['date', 'dob', 'birth']):
            return self._normalize_date(value_str)
        
        # Phone number normalization
        elif any(term in field_name.lower() for term in ['phone']):
            return self._normalize_phone(value_str)
        
        # Name normalization
        elif any(term in field_name.lower() for term in ['name']):
            return self._normalize_name(value_str)
        
        # Default: lowercase and remove extra whitespace
        return re.sub(r'\s+', ' ', value_str)
    
    def _normalize_date(self, date_str):
        """Normalize date strings for comparison."""
        # Remove common separators and normalize to MMDDYYYY
        normalized = re.sub(r'[/\-\.]', '', date_str)
        
        # Try to parse and reformat common date patterns
        import datetime
        
        patterns = [
            '%m%d%Y', '%m%d%y', '%Y%m%d', '%d%m%Y',
            '%m/%d/%Y', '%m-%d-%Y', '%Y-%m-%d'
        ]
        
        for pattern in patterns:
            try:
                parsed_date = datetime.datetime.strptime(date_str, pattern)
                return parsed_date.strftime('%m%d%Y')
            except ValueError:
                continue
        
        # If parsing fails, return normalized string
        return normalized
    
    def _normalize_phone(self, phone_str):
        """Normalize phone numbers for comparison."""
        # Remove all non-digits
        digits_only = re.sub(r'\D', '', phone_str)
        
        # Handle US phone numbers (remove country code if present)
        if len(digits_only) == 11 and digits_only.startswith('1'):
            digits_only = digits_only[1:]
        
        return digits_only
    
    def _normalize_name(self, name_str):
        """Normalize names for comparison."""
        # Remove titles, suffixes, and normalize spacing
        name_normalized = re.sub(r'\b(mr|mrs|ms|dr|md|jr|sr|ii|iii)\b\.?', '', name_str)
        name_normalized = re.sub(r'\s+', ' ', name_normalized).strip()
        return name_normalized
    
    def _calculate_string_similarity(self, str1, str2):
        """Calculate similarity score between two strings using Levenshtein distance."""
        if str1 == str2:
            return 1.0
        
        if not str1 or not str2:
            return 0.0
        
        # Simple Levenshtein distance implementation
        len1, len2 = len(str1), len(str2)
        
        if len1 == 0:
            return 0.0
        if len2 == 0:
            return 0.0
        
        # Create matrix for dynamic programming
        matrix = [[0] * (len2 + 1) for _ in range(len1 + 1)]
        
        # Initialize first row and column
        for i in range(len1 + 1):
            matrix[i][0] = i
        for j in range(len2 + 1):
            matrix[0][j] = j
        
        # Fill the matrix
        for i in range(1, len1 + 1):
            for j in range(1, len2 + 1):
                if str1[i-1] == str2[j-1]:
                    cost = 0
                else:
                    cost = 1
                
                matrix[i][j] = min(
                    matrix[i-1][j] + 1,      # deletion
                    matrix[i][j-1] + 1,      # insertion
                    matrix[i-1][j-1] + cost  # substitution
                )
        
        # Calculate similarity score
        max_len = max(len1, len2)
        distance = matrix[len1][len2]
        similarity = 1.0 - (distance / max_len)
        
        return similarity
    
    def _classify_discrepancy(self, extracted_value, patient_value, similarity_score):
        """Classify the type of discrepancy found."""
        if not extracted_value and not patient_value:
            return 'no_data'
        elif not extracted_value:
            return 'missing_extracted'
        elif not patient_value:
            return 'missing_patient'
        elif similarity_score >= 0.9:
            return 'minor_difference'
        elif similarity_score >= 0.7:
            return 'moderate_difference'
        else:
            return 'major_difference'
    
    def _suggest_resolution(self, extracted_value, patient_value, confidence, similarity_score):
        """Suggest the best resolution for a discrepancy."""
        # No discrepancy
        if similarity_score >= self.similarity_threshold:
            return 'no_change'
        
        # Missing data scenarios
        if not extracted_value:
            return 'keep_existing'
        if not patient_value:
            return 'use_extracted' if confidence >= self.confidence_threshold_medium else 'manual_edit'
        
        # Both have values - use confidence and data quality to decide
        if confidence >= self.confidence_threshold_high:
            return 'use_extracted'
        elif confidence < self.confidence_threshold_medium:
            return 'manual_edit'
        else:
            # Medium confidence - prefer newer data if it seems more complete
            if len(extracted_value) > len(patient_value):
                return 'use_extracted'
            else:
                return 'keep_existing'
    
    def _categorize_field(self, field_name):
        """Categorize a field for organization purposes."""
        field_name_lower = field_name.lower()
        
        if any(term in field_name_lower for term in ['name', 'dob', 'birth', 'age', 'gender', 'sex', 'race', 'ethnicity']):
            return 'demographics'
        elif any(term in field_name_lower for term in ['phone', 'email', 'address', 'contact', 'emergency']):
            return 'contact_info'
        elif any(term in field_name_lower for term in ['mrn', 'insurance', 'provider', 'medical']):
            return 'medical_info'
        else:
            return 'other'
    
    def _calculate_overall_confidence(self, extracted_data):
        """Calculate overall confidence score for extracted data."""
        if not extracted_data:
            return 0.0
        
        confidences = []
        for field_data in extracted_data.values():
            if isinstance(field_data, dict):
                confidences.append(float(field_data.get('confidence', 0.0)))
            else:
                confidences.append(0.5)  # Default for legacy data
        
        return sum(confidences) / len(confidences) if confidences else 0.0
    
    def _calculate_data_quality_score(self, extracted_data):
        """Calculate data quality score based on completeness and format validation."""
        if not extracted_data:
            return 0.0
        
        total_score = 0.0
        field_count = 0
        
        for field_name, field_data in extracted_data.items():
            field_validation = self._validate_individual_field(field_name, field_data)
            total_score += field_validation['quality_score']
            field_count += 1
        
        return total_score / field_count if field_count > 0 else 0.0
    
    def _validate_individual_field(self, field_name, field_value):
        """Validate an individual field for format and completeness."""
        validation = {
            'is_valid': True,
            'quality_score': 1.0,
            'issues': []
        }
        
        # Extract actual value
        if isinstance(field_value, dict):
            value = field_value.get('value', '')
        else:
            value = str(field_value) if field_value else ''
        
        if not value or not value.strip():
            validation['is_valid'] = False
            validation['quality_score'] = 0.0
            validation['issues'].append('Empty value')
            return validation
        
        # Field-specific validation
        field_name_lower = field_name.lower()
        
        if 'date' in field_name_lower or 'dob' in field_name_lower or 'birth' in field_name_lower:
            validation.update(self._validate_date_field(value))
        elif 'phone' in field_name_lower:
            validation.update(self._validate_phone_field(value))
        elif 'email' in field_name_lower:
            validation.update(self._validate_email_field(value))
        elif 'name' in field_name_lower:
            validation.update(self._validate_name_field(value))
        
        return validation
    
    def _validate_date_field(self, value):
        """Validate date field format."""
        import datetime
        
        validation = {'is_valid': True, 'quality_score': 1.0, 'issues': []}
        
        # Common date patterns
        date_patterns = [
            r'\d{1,2}/\d{1,2}/\d{4}',
            r'\d{1,2}-\d{1,2}-\d{4}',
            r'\d{4}-\d{1,2}-\d{1,2}',
        ]
        
        valid_format = any(re.match(pattern, value.strip()) for pattern in date_patterns)
        if not valid_format:
            validation['is_valid'] = False
            validation['quality_score'] = 0.3
            validation['issues'].append('Invalid date format')
        
        return validation
    
    def _validate_phone_field(self, value):
        """Validate phone number format."""
        validation = {'is_valid': True, 'quality_score': 1.0, 'issues': []}
        
        # Remove all non-digits
        digits_only = re.sub(r'\D', '', value)
        
        if len(digits_only) not in [10, 11]:
            validation['is_valid'] = False
            validation['quality_score'] = 0.4
            validation['issues'].append('Invalid phone number length')
        
        return validation
    
    def _validate_email_field(self, value):
        """Validate email format."""
        validation = {'is_valid': True, 'quality_score': 1.0, 'issues': []}
        
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, value.strip()):
            validation['is_valid'] = False
            validation['quality_score'] = 0.2
            validation['issues'].append('Invalid email format')
        
        return validation
    
    def _validate_name_field(self, value):
        """Validate name field format."""
        validation = {'is_valid': True, 'quality_score': 1.0, 'issues': []}
        
        # Check for reasonable name format
        if len(value.strip()) < 2:
            validation['is_valid'] = False
            validation['quality_score'] = 0.1
            validation['issues'].append('Name too short')
        elif not re.match(r'^[a-zA-Z\s\.\-\']+$', value):
            validation['quality_score'] = 0.6
            validation['issues'].append('Name contains unusual characters')
        
        return validation
    
    def _calculate_quality_score(self, validation_results):
        """Calculate overall quality score from validation results."""
        field_validations = validation_results.get('field_validations', {})
        if not field_validations:
            return 0.0
        
        scores = [fv.get('quality_score', 0.0) for fv in field_validations.values()]
        return sum(scores) / len(scores)
    
    def _generate_suggestion_reasoning(self, field_data):
        """Generate human-readable reasoning for a suggestion."""
        confidence = field_data.get('confidence', 0.0)
        similarity = field_data.get('similarity_score', 0.0)
        suggested_resolution = field_data.get('suggested_resolution', 'manual_edit')
        
        if suggested_resolution == 'use_extracted':
            if confidence >= self.confidence_threshold_high:
                return f"High confidence extraction ({confidence:.1f}) with significant difference from existing record"
            else:
                return f"Extracted data appears more complete or recent"
        elif suggested_resolution == 'keep_existing':
            return f"Low confidence extraction ({confidence:.1f}) - existing record preferred"
        elif suggested_resolution == 'manual_edit':
            return f"Medium confidence ({confidence:.1f}) - manual review recommended"
        else:
            return "Values are similar - no change needed"


class PatientRecordUpdateService:
    """
    Service for safely updating patient records with resolved data while maintaining audit trails.
    
    Provides atomic transaction handling, comprehensive validation, and HIPAA-compliant
    audit logging for all patient record modifications during document review process.
    """
    
    def __init__(self):
        """Initialize the patient record update service."""
        self.validation_errors = []
        self.update_summary = {}
        
    def apply_comparison_resolutions(self, comparison, reviewer):
        """
        Apply all resolved field decisions to the patient record.
        
        Args:
            comparison: PatientDataComparison instance with resolved decisions
            reviewer: User performing the updates
            
        Returns:
            Dictionary with update results and summary
        """
        if not comparison.resolution_decisions:
            return {
                'success': False,
                'error': 'No resolution decisions found',
                'updates_applied': 0
            }
        
        update_results = {
            'success': True,
            'updates_applied': 0,
            'updates_skipped': 0,
            'validation_errors': [],
            'audit_entries': [],
            'updated_fields': []
        }
        
        try:
            with transaction.atomic():
                patient = comparison.patient
                
                # Track original values for audit trail
                original_values = self._capture_original_values(patient)
                
                # Apply each resolved field
                for field_name, resolution_data in comparison.resolution_decisions.items():
                    resolution = resolution_data.get('resolution')
                    
                    if resolution == 'pending':
                        update_results['updates_skipped'] += 1
                        continue
                    
                    try:
                        field_updated = self._apply_field_resolution(
                            patient, field_name, resolution_data, comparison
                        )
                        
                        if field_updated:
                            update_results['updates_applied'] += 1
                            update_results['updated_fields'].append(field_name)
                        else:
                            update_results['updates_skipped'] += 1
                            
                    except ValidationError as ve:
                        update_results['validation_errors'].append({
                            'field': field_name,
                            'error': str(ve)
                        })
                        logger.warning(f"Validation error updating field {field_name}: {ve}")
                
                # Save patient record if any updates were made
                if update_results['updates_applied'] > 0:
                    patient.updated_by = reviewer
                    patient.save()
                    
                    # Generate audit trail
                    audit_entries = self._generate_audit_trail(
                        patient, comparison, original_values, 
                        update_results['updated_fields'], reviewer
                    )
                    update_results['audit_entries'] = audit_entries
                    
                    # Update comparison status
                    comparison.status = 'resolved'
                    comparison.reviewer = reviewer
                    comparison.reviewed_at = timezone.now()
                    comparison.save()
                    
                    logger.info(f"Applied {update_results['updates_applied']} patient record updates from document {comparison.document.id}")
                
        except Exception as e:
            logger.error(f"Error applying comparison resolutions: {e}")
            update_results['success'] = False
            update_results['error'] = str(e)
        
        return update_results
    
    def _apply_field_resolution(self, patient, field_name, resolution_data, comparison):
        """
        Apply a single field resolution to the patient record.
        
        Args:
            patient: Patient instance to update
            field_name: Name of the field being updated
            resolution_data: Resolution decision data
            comparison: PatientDataComparison instance
            
        Returns:
            bool: True if field was updated, False if skipped
        """
        resolution = resolution_data.get('resolution')
        custom_value = resolution_data.get('custom_value')
        
        # Get the new value based on resolution type
        new_value = None
        
        if resolution == 'keep_existing':
            # No update needed - keep current patient record value
            return False
            
        elif resolution == 'use_extracted':
            # Use the extracted value from the document
            comparison_field = comparison.comparison_data.get(field_name, {})
            new_value = comparison_field.get('extracted_value', '')
            
        elif resolution == 'manual_edit':
            # Use the custom value provided by reviewer
            new_value = custom_value
            
        elif resolution == 'no_change':
            # No change needed
            return False
        
        if new_value is None or new_value == '':
            return False
        
        # Map field name to patient model field
        patient_field = self._map_field_to_patient_model(field_name)
        if not patient_field:
            logger.warning(f"Cannot map field {field_name} to patient model")
            return False
        
        # Validate the new value
        if not self._validate_field_value(patient_field, new_value, patient):
            return False
        
        # Apply the update
        try:
            # Handle different field types
            if patient_field in ['date_of_birth']:
                new_value = self._parse_date_value(new_value)
            elif patient_field in ['phone_number']:
                new_value = self._normalize_phone_value(new_value)
            
            setattr(patient, patient_field, new_value)
            return True
            
        except Exception as e:
            logger.error(f"Error setting field {patient_field} to {new_value}: {e}")
            return False
    
    def _map_field_to_patient_model(self, field_name):
        """Map extracted field names to patient model fields."""
        field_mapping = {
            'patient_name': None,  # Handled separately - split into first/last
            'patientName': None,   # Handled separately - split into first/last
            'date_of_birth': 'date_of_birth',
            'dateOfBirth': 'date_of_birth',
            'dob': 'date_of_birth',
            'gender': 'gender',
            'sex': 'gender',
            'phone': 'phone_number',
            'phone_number': 'phone_number',
            'address': 'address',
            'email': 'email',
            'mrn': 'mrn',
            'ssn': 'ssn',
            'insurance': 'insurance_info',
        }
        
        return field_mapping.get(field_name)
    
    def _validate_field_value(self, field_name, value, patient):
        """
        Validate a field value before applying to patient record.
        
        Args:
            field_name: Patient model field name
            value: Value to validate
            patient: Patient instance
            
        Returns:
            bool: True if valid, False otherwise
        """
        try:
            # Basic validation
            if not value or not str(value).strip():
                return False
            
            # Field-specific validation
            if field_name == 'date_of_birth':
                return self._validate_date_value(value)
            elif field_name == 'phone_number':
                return self._validate_phone_value(value)
            elif field_name == 'email':
                return self._validate_email_value(value)
            elif field_name == 'mrn':
                return self._validate_mrn_value(value, patient)
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating field {field_name}: {e}")
            return False
    
    def _validate_date_value(self, value):
        """Validate and parse date values."""
        import datetime
        
        date_formats = ['%m/%d/%Y', '%m-%d-%Y', '%Y-%m-%d', '%d/%m/%Y']
        
        for fmt in date_formats:
            try:
                datetime.datetime.strptime(str(value).strip(), fmt)
                return True
            except ValueError:
                continue
        
        return False
    
    def _validate_phone_value(self, value):
        """Validate phone number format."""
        digits_only = re.sub(r'\D', '', str(value))
        return len(digits_only) in [10, 11]
    
    def _validate_email_value(self, value):
        """Validate email format."""
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(email_pattern, str(value).strip()) is not None
    
    def _validate_mrn_value(self, value, patient):
        """Validate MRN uniqueness and format."""
        from apps.patients.models import Patient
        
        # Check format
        if not re.match(r'^[a-zA-Z0-9]{3,}$', str(value)):
            return False
        
        # Check uniqueness (excluding current patient)
        existing = Patient.objects.filter(mrn=value).exclude(id=patient.id).exists()
        return not existing
    
    def _parse_date_value(self, value):
        """Parse date value into proper format for database."""
        import datetime
        
        date_formats = ['%m/%d/%Y', '%m-%d-%Y', '%Y-%m-%d', '%d/%m/%Y']
        
        for fmt in date_formats:
            try:
                parsed_date = datetime.datetime.strptime(str(value).strip(), fmt)
                return parsed_date.date()
            except ValueError:
                continue
        
        raise ValueError(f"Cannot parse date: {value}")
    
    def _normalize_phone_value(self, value):
        """Normalize phone number for storage."""
        digits_only = re.sub(r'\D', '', str(value))
        
        # Handle US phone numbers
        if len(digits_only) == 11 and digits_only.startswith('1'):
            digits_only = digits_only[1:]
        
        # Format as (XXX) XXX-XXXX
        if len(digits_only) == 10:
            return f"({digits_only[:3]}) {digits_only[3:6]}-{digits_only[6:]}"
        
        return value  # Return original if can't format
    
    def _capture_original_values(self, patient):
        """Capture original patient values for audit trail."""
        return {
            'first_name': patient.first_name,
            'last_name': patient.last_name,
            'date_of_birth': patient.date_of_birth,
            'gender': patient.gender,
            'phone_number': patient.phone_number,
            'address': patient.address,
            'email': patient.email,
            'mrn': patient.mrn,
            'ssn': patient.ssn,
            'insurance_info': patient.insurance_info,
        }
    
    def _generate_audit_trail(self, patient, comparison, original_values, updated_fields, reviewer):
        """
        Generate comprehensive audit trail for patient record updates.
        
        Args:
            patient: Updated patient instance
            comparison: PatientDataComparison instance
            original_values: Dictionary of original field values
            updated_fields: List of fields that were updated
            reviewer: User who performed the updates
            
        Returns:
            List of audit trail entries
        """
        from apps.core.models import AuditLog
        
        audit_entries = []
        
        for field_name in updated_fields:
            patient_field = self._map_field_to_patient_model(field_name)
            if not patient_field:
                continue
            
            original_value = original_values.get(patient_field, '')
            new_value = getattr(patient, patient_field, '')
            
            # Create audit log entry
            try:
                audit_entry = AuditLog.objects.create(
                    user=reviewer,
                    patient=patient,
                    action='patient_data_update',
                    resource_type='Patient',
                    resource_id=str(patient.id),
                    ip_address=self._get_client_ip(reviewer.last_login),
                    user_agent='Document Review System',
                    details={
                        'field_name': patient_field,
                        'original_value': str(original_value) if original_value else '',
                        'new_value': str(new_value) if new_value else '',
                        'source_document': comparison.document.filename,
                        'resolution_type': comparison.get_field_resolution(field_name).get('resolution'),
                        'reasoning': comparison.get_field_resolution(field_name).get('notes', ''),
                        'confidence_score': comparison.comparison_data.get(field_name, {}).get('confidence', 0.0)
                    }
                )
                audit_entries.append(audit_entry)
                
            except Exception as e:
                logger.error(f"Error creating audit entry for field {field_name}: {e}")
        
        return audit_entries
    
    def _get_client_ip(self, request_or_last_login):
        """Get client IP address for audit logging."""
        # For now, return a placeholder since we don't have access to request
        return '127.0.0.1'  # This would be improved with proper request context
    
    def validate_batch_updates(self, update_requests):
        """
        Validate a batch of update requests before applying.
        
        Args:
            update_requests: List of update request dictionaries
            
        Returns:
            Dictionary with validation results
        """
        validation_results = {
            'is_valid': True,
            'valid_updates': [],
            'invalid_updates': [],
            'warnings': [],
            'total_requests': len(update_requests)
        }
        
        for i, update_request in enumerate(update_requests):
            try:
                patient = update_request.get('patient')
                field_name = update_request.get('field_name')
                new_value = update_request.get('new_value')
                
                if not all([patient, field_name, new_value]):
                    validation_results['invalid_updates'].append({
                        'index': i,
                        'error': 'Missing required fields (patient, field_name, new_value)'
                    })
                    continue
                
                # Validate the field value
                if self._validate_field_value(field_name, new_value, patient):
                    validation_results['valid_updates'].append(update_request)
                else:
                    validation_results['invalid_updates'].append({
                        'index': i,
                        'field_name': field_name,
                        'error': f'Invalid value for field {field_name}: {new_value}'
                    })
                    
            except Exception as e:
                validation_results['invalid_updates'].append({
                    'index': i,
                    'error': f'Validation error: {str(e)}'
                })
        
        # Set overall validation status
        validation_results['is_valid'] = len(validation_results['invalid_updates']) == 0
        
        return validation_results
    
    def apply_batch_updates(self, update_requests, reviewer):
        """
        Apply a batch of patient record updates atomically.
        
        Args:
            update_requests: List of validated update requests
            reviewer: User performing the updates
            
        Returns:
            Dictionary with batch update results
        """
        batch_results = {
            'success': True,
            'total_processed': 0,
            'successful_updates': 0,
            'failed_updates': 0,
            'audit_entries': [],
            'errors': []
        }
        
        try:
            with transaction.atomic():
                for update_request in update_requests:
                    batch_results['total_processed'] += 1
                    
                    try:
                        patient = update_request['patient']
                        field_name = update_request['field_name']
                        new_value = update_request['new_value']
                        reasoning = update_request.get('reasoning', 'Batch update')
                        
                        # Capture original value
                        original_value = getattr(patient, field_name, '')
                        
                        # Apply update
                        setattr(patient, field_name, new_value)
                        patient.updated_by = reviewer
                        patient.save()
                        
                        # Create audit entry
                        audit_entry = self._create_audit_entry(
                            patient, field_name, original_value, new_value, reviewer, reasoning
                        )
                        batch_results['audit_entries'].append(audit_entry)
                        batch_results['successful_updates'] += 1
                        
                    except Exception as update_error:
                        batch_results['failed_updates'] += 1
                        batch_results['errors'].append({
                            'patient_id': update_request.get('patient', {}).id,
                            'field_name': update_request.get('field_name'),
                            'error': str(update_error)
                        })
                        logger.error(f"Error in batch update: {update_error}")
                
        except Exception as batch_error:
            logger.error(f"Error in batch update transaction: {batch_error}")
            batch_results['success'] = False
            batch_results['error'] = str(batch_error)
        
        return batch_results
    
    def _create_audit_entry(self, patient, field_name, original_value, new_value, reviewer, reasoning):
        """Create a single audit log entry for a patient field update."""
        from apps.core.models import AuditLog
        
        return AuditLog.objects.create(
            user=reviewer,
            patient=patient,
            action='patient_field_update',
            resource_type='Patient',
            resource_id=str(patient.id),
            ip_address=self._get_client_ip(None),  # Placeholder
            user_agent='Patient Data Comparison System',
            details={
                'field_name': field_name,
                'original_value': str(original_value) if original_value else '',
                'new_value': str(new_value) if new_value else '',
                'reasoning': reasoning,
                'update_source': 'document_review_comparison'
            }
        )
    
    def rollback_patient_updates(self, patient, original_values, reviewer):
        """
        Rollback patient record to previous values.
        
        Args:
            patient: Patient instance to rollback
            original_values: Dictionary of original field values
            reviewer: User performing the rollback
            
        Returns:
            Dictionary with rollback results
        """
        rollback_results = {
            'success': True,
            'fields_rolled_back': 0,
            'errors': []
        }
        
        try:
            with transaction.atomic():
                for field_name, original_value in original_values.items():
                    try:
                        setattr(patient, field_name, original_value)
                        rollback_results['fields_rolled_back'] += 1
                        
                        # Create audit entry for rollback
                        self._create_audit_entry(
                            patient, field_name, 
                            getattr(patient, field_name), original_value,
                            reviewer, 'Rollback patient data update'
                        )
                        
                    except Exception as field_error:
                        rollback_results['errors'].append({
                            'field': field_name,
                            'error': str(field_error)
                        })
                
                patient.updated_by = reviewer
                patient.save()
                
                logger.info(f"Rolled back {rollback_results['fields_rolled_back']} fields for patient {patient.id}")
                
        except Exception as rollback_error:
            logger.error(f"Error rolling back patient updates: {rollback_error}")
            rollback_results['success'] = False
            rollback_results['error'] = str(rollback_error)
        
        return rollback_results
    
    def get_update_preview(self, comparison):
        """
        Generate a preview of what the patient record will look like after updates.
        
        Args:
            comparison: PatientDataComparison with resolution decisions
            
        Returns:
            Dictionary with preview data
        """
        if not comparison.resolution_decisions:
            return {'has_changes': False}
        
        preview = {
            'has_changes': False,
            'field_changes': [],
            'summary': {
                'total_changes': 0,
                'high_confidence_changes': 0,
                'manual_edits': 0
            }
        }
        
        patient = comparison.patient
        
        for field_name, resolution_data in comparison.resolution_decisions.items():
            resolution = resolution_data.get('resolution')
            
            if resolution in ['keep_existing', 'no_change', 'pending']:
                continue
            
            preview['has_changes'] = True
            preview['summary']['total_changes'] += 1
            
            # Get current and new values
            patient_field = self._map_field_to_patient_model(field_name)
            current_value = getattr(patient, patient_field, '') if patient_field else ''
            
            if resolution == 'use_extracted':
                comparison_field = comparison.comparison_data.get(field_name, {})
                new_value = comparison_field.get('extracted_value', '')
                confidence = comparison_field.get('confidence', 0.0)
                
                if confidence >= 0.8:
                    preview['summary']['high_confidence_changes'] += 1
                    
            elif resolution == 'manual_edit':
                new_value = resolution_data.get('custom_value', '')
                preview['summary']['manual_edits'] += 1
            else:
                continue
            
            preview['field_changes'].append({
                'field_name': field_name,
                'current_value': current_value,
                'new_value': new_value,
                'resolution_type': resolution,
                'reasoning': resolution_data.get('notes', '')
            })
        
        return preview