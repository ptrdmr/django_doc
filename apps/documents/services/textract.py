"""
AWS Textract OCR service for medical document processing.
Provides structured data containers and service classes for Textract integration.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import logging
from statistics import mean

logger = logging.getLogger(__name__)


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
