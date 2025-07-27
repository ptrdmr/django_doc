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

logger = logging.getLogger(__name__)


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
                
                # Get file size
                file_size = os.path.getsize(file_path) / (1024 * 1024)  # Convert to MB
                
                result = {
                    'success': True,
                    'text': full_text,
                    'page_count': len(pdf.pages),
                    'file_size': round(file_size, 2),
                    'error_message': '',
                    'metadata': metadata
                }
                
                logger.info(f"Successfully extracted text from PDF: {file_path} "
                           f"({len(pdf.pages)} pages, {len(full_text)} characters)")
                
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
import httpx
from typing import Any, Optional
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils import timezone

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    import openai
except ImportError:
    openai = None


class DocumentAnalyzer:
    """
    AI-powered medical document analysis service.
    Handles document processing with Claude and GPT fallback.
    Designed for HIPAA compliance and medical document processing.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the DocumentAnalyzer with proper configuration.
        
        Args:
            api_key: Optional API key override for testing
        """
        self.logger = logging.getLogger(__name__)
        
        # Get API keys from settings
        self.anthropic_key = api_key or getattr(settings, 'ANTHROPIC_API_KEY', None)
        self.openai_key = getattr(settings, 'OPENAI_API_KEY', None)
        
        # More forgiving for testing - just warn instead of failing
        if not self.anthropic_key and not self.openai_key:
            self.logger.warning(
                "No AI API keys configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY for full functionality"
            )
        
        # Configuration from Django settings (must be set before initializing clients)
        self.primary_model = getattr(settings, 'AI_MODEL_PRIMARY', 'claude-3-sonnet-20240229')
        self.fallback_model = getattr(settings, 'AI_MODEL_FALLBACK', 'gpt-3.5-turbo')
        self.max_tokens = getattr(settings, 'AI_MAX_TOKENS_PER_REQUEST', 4096)
        self.timeout = getattr(settings, 'AI_REQUEST_TIMEOUT', 60)
        self.chunk_threshold = getattr(settings, 'AI_TOKEN_THRESHOLD_FOR_CHUNKING', 30000)
        self.chunk_size = getattr(settings, 'AI_CHUNK_SIZE', 15000)
        
        # Initialize AI clients after configuration is set
        self._init_ai_clients()
        
        self.logger.info(f"DocumentAnalyzer initialized with primary model: {self.primary_model}")
    
    def _init_ai_clients(self):
        """Initialize AI clients with proper error handling and timeout protection"""
        self.anthropic_client = None
        self.openai_client = None
        
        # Initialize Anthropic client with timeout protection
        if self.anthropic_key and anthropic:
            try:
                # Create httpx client with shorter timeout to prevent hanging
                http_client = httpx.Client(
                    timeout=httpx.Timeout(5.0),  # 5 second timeout for initialization
                    follow_redirects=True
                )
                self.anthropic_client = anthropic.Client(
                    api_key=self.anthropic_key, 
                    http_client=http_client
                )
                self.logger.info("Anthropic client initialized successfully")
            except Exception as e:
                self.logger.warning(f"Failed to initialize Anthropic client: {e}")
                self.anthropic_client = None
        
        # Initialize OpenAI client with timeout protection
        if self.openai_key and openai:
            try:
                self.openai_client = openai.OpenAI(
                    api_key=self.openai_key,
                    timeout=5.0  # 5 second timeout for initialization
                )
                self.logger.info("OpenAI client initialized successfully")
            except Exception as e:
                self.logger.warning(f"Failed to initialize OpenAI client: {e}")
                self.openai_client = None
    
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
            if not document_content or not document_content.strip():
                return {
                    'success': False,
                    'error': 'Document content is empty',
                    'fields': []
                }
            
            doc_length = len(document_content)
            estimated_tokens = doc_length / 4  # Rough token estimation
            
            self.logger.info(
                f"Processing document: {doc_length} characters, ~{estimated_tokens:.0f} tokens"
            )
            
            # Check if document needs chunking
            if estimated_tokens >= self.chunk_threshold:
                self.logger.info("Document requires chunking for processing")
                return self._analyze_large_document(document_content, context)
            
            # Process normal-sized document
            return self._analyze_single_document(document_content, context)
            
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
                self.logger.warning("Anthropic rate limited, returning rate limit response")
                result['model_used'] = self.primary_model
                result['processing_method'] = 'rate_limited'
                return result
            elif result.get('error') in ['authentication_error', 'api_status_error']:
                # Critical errors that won't be fixed by retrying - try fallback
                self.logger.warning(f"Anthropic critical error ({result.get('error')}), trying fallback")
            else:
                # Connection errors or other issues - try fallback
                self.logger.warning(f"Anthropic processing failed ({result.get('error', 'unknown')}), trying fallback")
        
        # Fallback to OpenAI
        if self.openai_client:
            result = self._call_openai(system_prompt, content)
            if result['success']:
                result['model_used'] = self.fallback_model
                result['processing_method'] = 'single_document_fallback'
                return result
            elif result.get('error') == 'rate_limit_exceeded':
                # Both services rate limited
                self.logger.warning("Both Anthropic and OpenAI rate limited")
                result['model_used'] = self.fallback_model
                result['processing_method'] = 'both_services_rate_limited'
                return result
            else:
                self.logger.error(f"OpenAI fallback also failed: {result.get('error', 'unknown')}")
        
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
        diag_str = re.sub(r'^\d+[\.\)]\s*', '', diag_str)
        
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
        from .prompts import MedicalPrompts
        
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
    
    @backoff.on_exception(backoff.expo, Exception, max_tries=3)
    def _call_anthropic(self, system_prompt: str, content: str) -> Dict[str, Any]:
        """
        Call Anthropic API with retry logic and rate limiting detection.
        Enhanced with proper error classification and rate limit handling.
        
        Args:
            system_prompt: System prompt for the AI
            content: Document content to analyze
            
        Returns:
            API response results with detailed error classification
        """
        try:
            response = self.anthropic_client.messages.create(
                model=self.primary_model,
                system=system_prompt,
                max_tokens=self.max_tokens,
                messages=[{
                    "role": "user",
                    "content": f"Extract medical data from this document:\n\n{content}"
                }]
            )
            
            # Parse the response
            text_response = response.content[0].text
            extracted_fields = self._parse_ai_response(text_response)
            
            return {
                'success': True,
                'fields': extracted_fields,
                'raw_response': text_response,
                'usage': {
                    'input_tokens': response.usage.input_tokens,
                    'output_tokens': response.usage.output_tokens,
                    'total_tokens': response.usage.input_tokens + response.usage.output_tokens
                }
            }
            
        except anthropic.RateLimitError as e:
            # Handle rate limiting specifically
            self.logger.warning(f"Anthropic rate limit exceeded: {e}")
            return {
                'success': False,
                'error': 'rate_limit_exceeded',
                'error_message': 'API rate limit exceeded, please try again later',
                'fields': [],
                'retry_after': getattr(e, 'retry_after', 60)  # Default 60 seconds
            }
            
        except anthropic.AuthenticationError as e:
            # Handle authentication errors
            self.logger.error(f"Anthropic authentication failed: {e}")
            return {
                'success': False,
                'error': 'authentication_error',
                'error_message': 'API authentication failed',
                'fields': []
            }
            
        except anthropic.APIConnectionError as e:
            # Handle connection errors
            self.logger.error(f"Anthropic connection error: {e}")
            return {
                'success': False,
                'error': 'connection_error',
                'error_message': 'API connection failed',
                'fields': []
            }
            
        except anthropic.APIStatusError as e:
            # Handle other API status errors
            self.logger.error(f"Anthropic API status error: {e}")
            return {
                'success': False,
                'error': 'api_status_error',
                'error_message': f'API returned status {e.status_code}',
                'fields': []
            }
            
        except Exception as e:
            # Generic fallback for unexpected errors
            self.logger.error(f"Unexpected Anthropic API error: {e}")
            return {
                'success': False,
                'error': 'unexpected_error',
                'error_message': f'Unexpected API error: {str(e)}',
                'fields': []
            }
    
    @backoff.on_exception(backoff.expo, Exception, max_tries=3)
    def _call_openai(self, system_prompt: str, content: str) -> Dict[str, Any]:
        """
        Call OpenAI API with retry logic and rate limiting detection.
        Enhanced with proper error classification and rate limit handling.
        
        Args:
            system_prompt: System prompt for the AI
            content: Document content to analyze
            
        Returns:
            API response results with detailed error classification
        """
        try:
            response = self.openai_client.chat.completions.create(
                model=self.fallback_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Extract medical data from this document:\n\n{content}"}
                ],
                max_tokens=self.max_tokens,
                temperature=0.1  # Low temperature for consistent extraction
            )
            
            # Parse the response
            text_response = response.choices[0].message.content
            extracted_fields = self._parse_ai_response(text_response)
            
            return {
                'success': True,
                'fields': extracted_fields,
                'raw_response': text_response,
                'usage': {
                    'input_tokens': response.usage.prompt_tokens,
                    'output_tokens': response.usage.completion_tokens,
                    'total_tokens': response.usage.total_tokens
                }
            }
            
        except openai.RateLimitError as e:
            # Handle rate limiting specifically
            self.logger.warning(f"OpenAI rate limit exceeded: {e}")
            return {
                'success': False,
                'error': 'rate_limit_exceeded',
                'error_message': 'API rate limit exceeded, please try again later',
                'fields': [],
                'retry_after': getattr(e, 'retry_after', 60)  # Default 60 seconds
            }
            
        except openai.AuthenticationError as e:
            # Handle authentication errors
            self.logger.error(f"OpenAI authentication failed: {e}")
            return {
                'success': False,
                'error': 'authentication_error',
                'error_message': 'API authentication failed',
                'fields': []
            }
            
        except openai.APIConnectionError as e:
            # Handle connection errors
            self.logger.error(f"OpenAI connection error: {e}")
            return {
                'success': False,
                'error': 'connection_error',
                'error_message': 'API connection failed',
                'fields': []
            }
            
        except openai.APIStatusError as e:
            # Handle other API status errors
            self.logger.error(f"OpenAI API status error: {e}")
            return {
                'success': False,
                'error': 'api_status_error',
                'error_message': f'API returned status {e.status_code}',
                'fields': []
            }
            
        except Exception as e:
            # Generic fallback for unexpected errors
            self.logger.error(f"Unexpected OpenAI API error: {e}")
            return {
                'success': False,
                'error': 'unexpected_error',
                'error_message': f'Unexpected API error: {str(e)}',
                'fields': []
            }
    
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
        from .prompts import MedicalPrompts, ChunkInfo, ContextTag
        
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
            fhir_focused=False,  # Default to standard extraction
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
        from .prompts import ConfidenceScoring
        
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
        
        while current_position < len(content):
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
            current_position = optimal_break - overlap_chars if optimal_break > overlap_chars else optimal_break
            
            # Safety break to prevent infinite loops
            if current_position >= len(content):
                break
        
        self.logger.info(f"Created {len(chunks)} medical-aware chunks with {overlap_chars} character overlap")
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
    
    def convert_to_fhir(self, extracted_fields: List[Dict]) -> Dict[str, Any]:
        """
        Convert extracted fields to basic FHIR format.
        This is a simplified implementation - full FHIR conversion is complex.
        
        Args:
            extracted_fields: List of extracted field dictionaries
            
        Returns:
            Basic FHIR-like structure
        """
        fhir_resources = {
            "resourceType": "Bundle",
            "type": "collection",
            "timestamp": timezone.now().isoformat(),
            "entry": []
        }
        
        # Basic mapping of common fields to FHIR resources
        for field in extracted_fields:
            label = field.get("label", "").lower()
            value = field.get("value")
            confidence = field.get("confidence", 0.0)
            
            if not value or confidence < 0.5:  # Skip low-confidence fields
                continue
            
            # Simple mapping - in production this would be much more sophisticated
            if any(term in label for term in ['patient', 'name']):
                # Could be part of Patient resource
                pass
            elif any(term in label for term in ['diagnosis', 'condition']):
                # Could be part of Condition resource  
                pass
            elif any(term in label for term in ['medication', 'drug']):
                # Could be part of MedicationStatement resource
                pass
            # Add more mappings as needed
        
        # For now, just store the raw extracted data
        fhir_resources["entry"] = [{
            "resource": {
                "resourceType": "DocumentReference",
                "content": extracted_fields
            }
        }]
        
        return fhir_resources


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
        Convert parsed JSON data to standardized field format.
        
        Like organizing the parts after you take apart an engine - 
        everything needs its proper place and label.
        
        Args:
            data: Parsed JSON data
            
        Returns:
            List of field dictionaries
        """
        fields = []
        
        for i, (key, value) in enumerate(data.items()):
            # Handle nested value/confidence structure
            if isinstance(value, dict) and 'value' in value and 'confidence' in value:
                fields.append({
                    "id": str(i + 1),
                    "label": key,
                    "value": value['value'],
                    "confidence": float(value['confidence'])
                })
            # Handle simple key-value pairs
            else:
                fields.append({
                    "id": str(i + 1),
                    "label": key,
                    "value": str(value) if value is not None else "",
                    "confidence": 0.9  # Default confidence for simple values
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