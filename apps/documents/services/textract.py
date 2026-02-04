"""
AWS Textract OCR service for medical document processing.
Provides structured data containers and service classes for Textract integration.

HIPAA Compliance Note:
- This service processes document bytes but NEVER logs document content
- Audit logging captures metadata only (page count, confidence, job IDs)
- All PHI remains in memory during processing and is not persisted by this service
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import logging
import time
from statistics import mean

import boto3
from botocore.exceptions import ClientError, BotoCoreError
from django.conf import settings

logger = logging.getLogger(__name__)


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class TextractError(Exception):
    """Base exception for Textract-related errors."""
    pass


class TextractDocumentTooLargeError(TextractError):
    """Raised when document exceeds sync processing limit (5MB)."""
    
    def __init__(self, size_bytes: int, limit_bytes: int = 5 * 1024 * 1024):
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            f"Document size ({size_bytes:,} bytes) exceeds sync limit "
            f"({limit_bytes:,} bytes). Use async processing."
        )


class TextractConfigurationError(TextractError):
    """Raised when AWS credentials or configuration are missing."""
    pass


class TextractAPIError(TextractError):
    """Raised when Textract API returns an error."""
    
    def __init__(self, message: str, error_code: str = None, request_id: str = None):
        self.error_code = error_code
        self.request_id = request_id
        super().__init__(message)


@dataclass
class TextractBlock:
    """
    Represents a single block from Textract response.
    
    Textract returns blocks of type: PAGE, LINE, WORD, TABLE, CELL, etc.
    This dataclass normalizes the block structure for easier processing.
    """
    block_type: str
    text: str = ""
    confidence: float = 0.0
    page: int = 1
    geometry: Dict[str, Any] = field(default_factory=dict)
    relationships: List[str] = field(default_factory=list)
    id: str = ""
    
    @classmethod
    def from_textract_block(cls, block: Dict[str, Any]) -> 'TextractBlock':
        """
        Create a TextractBlock from a raw Textract API block.
        
        Args:
            block: Raw block dictionary from Textract response
            
        Returns:
            TextractBlock instance
        """
        return cls(
            block_type=block.get('BlockType', 'UNKNOWN'),
            text=block.get('Text', ''),
            confidence=block.get('Confidence', 0.0),
            page=block.get('Page', 1),
            geometry=block.get('Geometry', {}),
            relationships=[
                rel.get('Ids', []) 
                for rel in block.get('Relationships', [])
            ],
            id=block.get('Id', '')
        )


@dataclass
class TextractResult:
    """
    Structured container for parsed AWS Textract response.
    
    Holds extracted text organized by page, raw blocks for advanced processing,
    confidence metrics, and metadata for audit logging.
    
    Attributes:
        pages: List of extracted text strings, one per page
        blocks: List of TextractBlock objects for advanced processing
        confidence: Average confidence score across all text blocks (0-100)
        page_count: Total number of pages in the document
        extraction_time_ms: Time taken for Textract processing in milliseconds
        job_id: Async job ID (None for sync processing)
        document_metadata: Additional Textract document metadata
    """
    pages: List[str] = field(default_factory=list)
    blocks: List[TextractBlock] = field(default_factory=list)
    confidence: float = 0.0
    page_count: int = 0
    extraction_time_ms: int = 0
    job_id: Optional[str] = None
    document_metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_response(
        cls,
        response: Dict[str, Any],
        extraction_time_ms: int = 0,
        job_id: Optional[str] = None
    ) -> 'TextractResult':
        """
        Parse a Textract API response into a TextractResult.
        
        Handles both sync (AnalyzeDocument) and async (GetDocumentAnalysis) 
        response formats. For async responses with pagination, pass the 
        combined blocks from all pages.
        
        Args:
            response: Raw Textract API response dictionary, or dict with 
                      combined 'Blocks' from paginated async responses
            extraction_time_ms: Processing time in milliseconds
            job_id: Async job ID if applicable
            
        Returns:
            TextractResult with parsed pages, blocks, and metrics
        """
        raw_blocks = response.get('Blocks', [])
        
        # Parse blocks into typed objects
        blocks = [
            TextractBlock.from_textract_block(block) 
            for block in raw_blocks
        ]
        
        # Determine page count from PAGE blocks
        page_blocks = [b for b in blocks if b.block_type == 'PAGE']
        page_count = len(page_blocks) if page_blocks else 1
        
        # Extract text organized by page
        pages = cls._extract_pages_text(blocks, page_count)
        
        # Calculate average confidence from LINE and WORD blocks
        text_blocks = [b for b in blocks if b.block_type in ('LINE', 'WORD')]
        confidence = 0.0
        if text_blocks:
            confidences = [b.confidence for b in text_blocks if b.confidence > 0]
            if confidences:
                confidence = round(mean(confidences), 2)
        
        # Extract document metadata
        document_metadata = {
            'document_type': response.get('DocumentMetadata', {}),
            'analyze_document_model_version': response.get('AnalyzeDocumentModelVersion', ''),
            'status_message': response.get('StatusMessage', ''),
        }
        
        return cls(
            pages=pages,
            blocks=blocks,
            confidence=confidence,
            page_count=page_count,
            extraction_time_ms=extraction_time_ms,
            job_id=job_id,
            document_metadata=document_metadata
        )
    
    @classmethod
    def from_paginated_responses(
        cls,
        responses: List[Dict[str, Any]],
        extraction_time_ms: int = 0,
        job_id: Optional[str] = None
    ) -> 'TextractResult':
        """
        Parse multiple paginated Textract async responses into a single result.
        
        Async Textract jobs may return results across multiple API calls
        using NextToken pagination. This method combines all blocks.
        
        Args:
            responses: List of raw Textract GetDocumentAnalysis responses
            extraction_time_ms: Total processing time in milliseconds
            job_id: Async job ID
            
        Returns:
            TextractResult with combined data from all response pages
        """
        # Combine all blocks from paginated responses
        all_blocks = []
        for response in responses:
            all_blocks.extend(response.get('Blocks', []))
        
        # Create combined response dict
        combined_response = {'Blocks': all_blocks}
        
        # Preserve metadata from first response
        if responses:
            combined_response['DocumentMetadata'] = responses[0].get('DocumentMetadata', {})
            combined_response['AnalyzeDocumentModelVersion'] = responses[0].get(
                'AnalyzeDocumentModelVersion', ''
            )
        
        return cls.from_response(
            combined_response,
            extraction_time_ms=extraction_time_ms,
            job_id=job_id
        )
    
    @staticmethod
    def _extract_pages_text(blocks: List[TextractBlock], page_count: int) -> List[str]:
        """
        Extract text from blocks organized by page number.
        
        Groups LINE blocks by page and concatenates them with newlines.
        
        Args:
            blocks: List of TextractBlock objects
            page_count: Expected number of pages
            
        Returns:
            List of text strings, one per page
        """
        # Initialize pages list
        pages: List[str] = [''] * page_count
        
        # Group LINE blocks by page
        for block in blocks:
            if block.block_type == 'LINE' and block.text:
                page_idx = block.page - 1  # Convert 1-indexed to 0-indexed
                if 0 <= page_idx < page_count:
                    if pages[page_idx]:
                        pages[page_idx] += '\n' + block.text
                    else:
                        pages[page_idx] = block.text
        
        return pages
    
    def get_full_text(self, include_page_separators: bool = True) -> str:
        """
        Get the full extracted text from all pages.
        
        Args:
            include_page_separators: If True, add page separators matching
                                     the existing OCR format
                                     
        Returns:
            Combined text from all pages
        """
        if not self.pages:
            return ''
        
        if include_page_separators:
            formatted_pages = []
            for i, page_text in enumerate(self.pages, 1):
                if page_text.strip():
                    formatted_pages.append(f"--- Page {i} (OCR) ---\n{page_text}")
            return '\n\n'.join(formatted_pages)
        else:
            return '\n\n'.join(page for page in self.pages if page.strip())
    
    def get_lines_by_page(self, page_number: int) -> List[TextractBlock]:
        """
        Get all LINE blocks for a specific page.
        
        Args:
            page_number: 1-indexed page number
            
        Returns:
            List of LINE TextractBlock objects for the page
        """
        return [
            block for block in self.blocks 
            if block.block_type == 'LINE' and block.page == page_number
        ]
    
    def get_tables(self) -> List[TextractBlock]:
        """
        Get all TABLE blocks from the extraction.
        
        Returns:
            List of TABLE TextractBlock objects
        """
        return [block for block in self.blocks if block.block_type == 'TABLE']
    
    def get_forms(self) -> List[TextractBlock]:
        """
        Get all KEY_VALUE_SET blocks (form fields) from the extraction.
        
        Returns:
            List of KEY_VALUE_SET TextractBlock objects
        """
        return [block for block in self.blocks if block.block_type == 'KEY_VALUE_SET']
    
    def to_audit_dict(self) -> Dict[str, Any]:
        """
        Create a dict suitable for HIPAA audit logging.
        
        Contains only metadata - NO extracted text or PHI.
        
        Returns:
            Dict with audit-safe metadata
        """
        return {
            'page_count': self.page_count,
            'confidence': self.confidence,
            'extraction_time_ms': self.extraction_time_ms,
            'job_id': self.job_id,
            'block_count': len(self.blocks),
            'table_count': len(self.get_tables()),
            'form_field_count': len(self.get_forms()),
        }
    
    def __repr__(self) -> str:
        return (
            f"TextractResult(pages={self.page_count}, "
            f"confidence={self.confidence}%, "
            f"blocks={len(self.blocks)}, "
            f"job_id={self.job_id})"
        )


# =============================================================================
# TEXTRACT SERVICE
# =============================================================================

class TextractService:
    """
    Service for AWS Textract OCR operations.
    
    Provides synchronous document analysis for documents under 5MB using the
    AnalyzeDocument API with TABLES and FORMS feature extraction.
    
    HIPAA Compliance:
    - No PHI is logged; only metadata (page counts, confidence scores, job IDs)
    - Document bytes are processed in memory only
    - AWS credentials support both IAM roles (production) and env vars (development)
    
    Usage:
        service = TextractService()
        result = service.analyze_document_sync(document_bytes)
        text = result.get_full_text()
    
    Attributes:
        region: AWS region for Textract API calls
        feature_types: List of Textract features to extract (TABLES, FORMS)
    """
    
    # Textract sync API limit is 5MB
    SYNC_SIZE_LIMIT_BYTES = 5 * 1024 * 1024
    
    def __init__(self, region: str = None, feature_types: List[str] = None):
        """
        Initialize the TextractService.
        
        Args:
            region: AWS region. Defaults to settings.AWS_DEFAULT_REGION
            feature_types: Textract features to extract. 
                          Defaults to settings.TEXTRACT_FEATURE_TYPES
        
        Raises:
            TextractConfigurationError: If OCR is disabled in settings
        """
        if not getattr(settings, 'OCR_ENABLED', True):
            raise TextractConfigurationError("OCR is disabled in settings (OCR_ENABLED=False)")
        
        self.region = region or getattr(settings, 'AWS_DEFAULT_REGION', 'us-east-1')
        self.feature_types = feature_types or getattr(
            settings, 'TEXTRACT_FEATURE_TYPES', ['TABLES', 'FORMS']
        )
        
        # Initialize boto3 client lazily
        self._textract_client = None
        
        logger.info(
            "TextractService initialized: region=%s, features=%s",
            self.region,
            self.feature_types
        )
    
    @property
    def textract_client(self):
        """
        Lazy initialization of boto3 Textract client.
        
        Supports both explicit credentials (development) and IAM roles (production).
        
        Returns:
            boto3 Textract client
            
        Raises:
            TextractConfigurationError: If credentials cannot be resolved
        """
        if self._textract_client is None:
            try:
                # Check for explicit credentials in settings
                aws_access_key = getattr(settings, 'AWS_ACCESS_KEY_ID', None)
                aws_secret_key = getattr(settings, 'AWS_SECRET_ACCESS_KEY', None)
                
                if aws_access_key and aws_secret_key:
                    # Use explicit credentials (development/testing)
                    self._textract_client = boto3.client(
                        'textract',
                        region_name=self.region,
                        aws_access_key_id=aws_access_key,
                        aws_secret_access_key=aws_secret_key
                    )
                    logger.debug("Textract client initialized with explicit credentials")
                else:
                    # Use IAM role or default credential chain (production)
                    self._textract_client = boto3.client(
                        'textract',
                        region_name=self.region
                    )
                    logger.debug("Textract client initialized with default credential chain")
                    
            except (ClientError, BotoCoreError) as e:
                logger.error("Failed to initialize Textract client: %s", str(e))
                raise TextractConfigurationError(
                    f"Failed to initialize AWS Textract client: {str(e)}"
                ) from e
        
        return self._textract_client
    
    def analyze_document_sync(self, document_bytes: bytes) -> TextractResult:
        """
        Analyze a document synchronously using Textract AnalyzeDocument API.
        
        This method is suitable for documents under 5MB. For larger documents,
        use the async workflow (start_async_analysis + get_async_result).
        
        Args:
            document_bytes: The document content as bytes (PDF or image)
            
        Returns:
            TextractResult containing extracted text, blocks, and metadata
            
        Raises:
            TextractDocumentTooLargeError: If document exceeds 5MB limit
            TextractAPIError: If Textract API returns an error
            TextractConfigurationError: If AWS credentials are invalid
        """
        # Validate document size
        doc_size = len(document_bytes)
        if doc_size > self.SYNC_SIZE_LIMIT_BYTES:
            logger.warning(
                "Document too large for sync processing: %d bytes (limit: %d)",
                doc_size,
                self.SYNC_SIZE_LIMIT_BYTES
            )
            raise TextractDocumentTooLargeError(doc_size, self.SYNC_SIZE_LIMIT_BYTES)
        
        # Log operation start (no PHI - just size metadata)
        logger.info(
            "Starting sync Textract analysis: size=%d bytes, features=%s",
            doc_size,
            self.feature_types
        )
        
        start_time = time.time()
        
        try:
            response = self.textract_client.analyze_document(
                Document={'Bytes': document_bytes},
                FeatureTypes=self.feature_types
            )
            
            # Calculate processing time
            extraction_time_ms = int((time.time() - start_time) * 1000)
            
            # Parse response into TextractResult
            result = TextractResult.from_response(
                response,
                extraction_time_ms=extraction_time_ms
            )
            
            # Log success (metadata only - no PHI)
            logger.info(
                "Sync Textract analysis complete: pages=%d, confidence=%.1f%%, "
                "blocks=%d, time=%dms",
                result.page_count,
                result.confidence,
                len(result.blocks),
                extraction_time_ms
            )
            
            return result
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            request_id = e.response.get('ResponseMetadata', {}).get('RequestId', 'Unknown')
            
            # Handle specific Textract errors
            if error_code == 'InvalidParameterException':
                logger.error(
                    "Textract invalid parameter: %s (request_id=%s)",
                    error_message,
                    request_id
                )
            elif error_code == 'UnsupportedDocumentException':
                logger.error(
                    "Textract unsupported document format (request_id=%s)",
                    request_id
                )
            elif error_code in ('ThrottlingException', 'ProvisionedThroughputExceededException'):
                logger.warning(
                    "Textract throttled: %s (request_id=%s)",
                    error_code,
                    request_id
                )
            elif error_code == 'AccessDeniedException':
                logger.error(
                    "Textract access denied - check IAM permissions (request_id=%s)",
                    request_id
                )
            else:
                logger.error(
                    "Textract API error: %s - %s (request_id=%s)",
                    error_code,
                    error_message,
                    request_id
                )
            
            raise TextractAPIError(
                f"Textract API error: {error_message}",
                error_code=error_code,
                request_id=request_id
            ) from e
            
        except BotoCoreError as e:
            logger.error("Textract boto3 error: %s", str(e))
            raise TextractAPIError(f"AWS SDK error: {str(e)}") from e

    def extract_text_from_result(self, result: TextractResult) -> str:
        """
        Convert a TextractResult into plain text with OCR page separators.
        
        This preserves reading order by sorting LINE blocks by geometry
        and falls back to WORD blocks when LINE blocks are unavailable.
        
        Args:
            result: Parsed TextractResult instance
            
        Returns:
            Combined text with page separators in the format:
            '--- Page N (OCR) ---'
        """
        if not result or not result.blocks:
            return ''
        
        page_count = result.page_count or 1
        formatted_pages: List[str] = []
        
        for page_number in range(1, page_count + 1):
            page_text = self._build_page_text(result, page_number)
            if page_text:
                formatted_pages.append(
                    f"--- Page {page_number} (OCR) ---\n{page_text}"
                )
        
        return '\n\n'.join(formatted_pages)

    def _build_page_text(self, result: TextractResult, page_number: int) -> str:
        """
        Build text for a single page from Textract blocks.
        
        Args:
            result: TextractResult containing parsed blocks
            page_number: 1-indexed page number to extract
            
        Returns:
            Page text string (empty if no content found)
        """
        line_blocks = self._get_sorted_blocks(result, page_number, 'LINE')
        word_blocks = self._get_unreferenced_word_blocks(result, page_number, line_blocks)
        
        fragments = self._build_text_fragments(line_blocks, word_blocks)
        if not fragments:
            return ''
        
        return self._build_text_from_fragments(fragments)

    def _get_unreferenced_word_blocks(
        self,
        result: TextractResult,
        page_number: int,
        line_blocks: List[TextractBlock]
    ) -> List[TextractBlock]:
        """
        Return WORD blocks not already referenced by LINE blocks.
        
        This captures table cells that Textract may not include in LINE blocks.
        """
        line_word_ids = self._collect_word_ids_from_lines(line_blocks)
        
        return [
            block for block in result.blocks
            if (
                block.block_type == 'WORD'
                and block.page == page_number
                and block.text
                and (not block.id or block.id not in line_word_ids)
            )
        ]

    @staticmethod
    def _collect_word_ids_from_lines(line_blocks: List[TextractBlock]) -> set:
        """
        Collect WORD block IDs referenced by LINE blocks.
        """
        word_ids = set()
        for line in line_blocks:
            for rel_ids in line.relationships:
                if isinstance(rel_ids, list):
                    word_ids.update(rel_ids)
                elif rel_ids:
                    word_ids.add(rel_ids)
        return word_ids

    def _build_text_fragments(
        self,
        line_blocks: List[TextractBlock],
        word_blocks: List[TextractBlock]
    ) -> List[tuple]:
        """
        Build (text, top, left) fragments from LINE and WORD blocks.
        """
        fragments: List[tuple] = []
        
        for block in line_blocks + word_blocks:
            if block.text:
                top, left = self._geometry_sort_key(block)
                fragments.append((block.text, top, left))
        
        return sorted(fragments, key=lambda fragment: (fragment[1], fragment[2]))

    @staticmethod
    def _build_text_from_fragments(fragments: List[tuple]) -> str:
        """
        Group fragments by vertical position and build readable lines.
        """
        if not fragments:
            return ''
        
        line_merge_threshold = 0.01
        lines: List[str] = []
        current_top = None
        current_parts: List[str] = []
        
        for text, top, _left in fragments:
            if current_top is None:
                current_top = top
                current_parts = [text]
                continue
            
            if abs(top - current_top) <= line_merge_threshold:
                current_parts.append(text)
            else:
                lines.append(' '.join(current_parts).strip())
                current_parts = [text]
                current_top = top
        
        if current_parts:
            lines.append(' '.join(current_parts).strip())
        
        return '\n'.join(line for line in lines if line)

    def _get_sorted_blocks(
        self,
        result: TextractResult,
        page_number: int,
        block_type: str
    ) -> List[TextractBlock]:
        """
        Get blocks of a given type for a page, sorted by geometry.
        
        Args:
            result: TextractResult containing parsed blocks
            page_number: 1-indexed page number to extract
            block_type: Textract block type to filter (e.g., 'LINE', 'WORD')
            
        Returns:
            Sorted list of TextractBlock objects
        """
        blocks = [
            block for block in result.blocks
            if block.block_type == block_type and block.page == page_number
        ]
        
        return sorted(
            blocks,
            key=self._geometry_sort_key
        )

    @staticmethod
    def _geometry_sort_key(block: TextractBlock) -> tuple:
        """
        Sort key for blocks based on Textract geometry (top-to-bottom, left-to-right).
        
        Args:
            block: TextractBlock with geometry data
            
        Returns:
            Tuple suitable for sorting (top, left)
        """
        bounding_box = block.geometry.get('BoundingBox', {}) if block.geometry else {}
        top = round(bounding_box.get('Top', 0.0), 4)
        left = round(bounding_box.get('Left', 0.0), 4)
        return (top, left)
    
    def is_sync_eligible(self, document_bytes: bytes) -> bool:
        """
        Check if a document is eligible for synchronous processing.
        
        Args:
            document_bytes: The document content as bytes
            
        Returns:
            True if document is under 5MB and can use sync API
        """
        return len(document_bytes) <= self.SYNC_SIZE_LIMIT_BYTES
    
    def get_size_limit_mb(self) -> float:
        """
        Get the sync processing size limit in megabytes.
        
        Returns:
            Size limit in MB (currently 5.0)
        """
        return self.SYNC_SIZE_LIMIT_BYTES / (1024 * 1024)
