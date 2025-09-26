"""
Performance optimization utilities for document processing pipeline.

This module provides parallel processing capabilities and performance monitoring
for handling large medical documents efficiently while maintaining HIPAA compliance.
"""
import os
import time
import logging
import asyncio
from typing import List, Dict, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.conf import settings
from django.utils import timezone
from celery import group
from celery.result import GroupResult

logger = logging.getLogger(__name__)


class DocumentChunker:
    """
    Intelligent document chunking for parallel processing of large medical documents.
    
    Splits documents at natural boundaries (sentences, paragraphs) to maintain
    medical context while enabling parallel AI processing.
    """
    
    def __init__(self, max_chunk_size: int = None):
        """
        Initialize chunker with configurable chunk size.
        
        Args:
            max_chunk_size: Maximum characters per chunk (defaults to settings value)
        """
        self.max_chunk_size = max_chunk_size or getattr(
            settings, 'AI_TOKEN_THRESHOLD_FOR_CHUNKING', 20000
        )
        
    def chunk_text(self, text: str, preserve_context: bool = True) -> List[Dict[str, Any]]:
        """
        Split text into optimally-sized chunks for parallel processing.
        
        Args:
            text: Medical document text to chunk
            preserve_context: Whether to include overlapping context between chunks
            
        Returns:
            List of chunk dictionaries with text, start_index, end_index, overlap_text
        """
        if len(text) <= self.max_chunk_size:
            return [{
                'text': text,
                'start_index': 0,
                'end_index': len(text),
                'chunk_id': 0,
                'overlap_text': None
            }]
        
        chunks = []
        overlap_size = 200 if preserve_context else 0
        
        # Split at sentence boundaries to preserve medical context
        sentences = self._split_into_sentences(text)
        current_chunk = ""
        chunk_start = 0
        chunk_id = 0
        
        for sentence in sentences:
            # Check if adding this sentence would exceed chunk size
            if len(current_chunk) + len(sentence) > self.max_chunk_size and current_chunk:
                # Save current chunk
                chunk_end = chunk_start + len(current_chunk)
                overlap_text = text[max(0, chunk_end - overlap_size):chunk_end] if preserve_context else None
                
                chunks.append({
                    'text': current_chunk,
                    'start_index': chunk_start,
                    'end_index': chunk_end,
                    'chunk_id': chunk_id,
                    'overlap_text': overlap_text
                })
                
                # Start new chunk with overlap if requested
                if preserve_context and overlap_text:
                    current_chunk = overlap_text + sentence
                    chunk_start = chunk_end - overlap_size
                else:
                    current_chunk = sentence
                    chunk_start = chunk_end
                    
                chunk_id += 1
            else:
                current_chunk += sentence
        
        # Add final chunk if there's remaining text
        if current_chunk:
            chunks.append({
                'text': current_chunk,
                'start_index': chunk_start,
                'end_index': chunk_start + len(current_chunk),
                'chunk_id': chunk_id,
                'overlap_text': None
            })
        
        logger.info(f"Split {len(text)} chars into {len(chunks)} chunks (max: {self.max_chunk_size})")
        return chunks
    
    def _split_into_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences, preserving medical abbreviations.
        
        Args:
            text: Text to split
            
        Returns:
            List of sentences
        """
        import re
        
        # Medical abbreviations that shouldn't trigger sentence splits
        medical_abbrevs = r'\b(?:Dr|Mr|Mrs|Ms|vs|etc|i\.e|e\.g|mg|ml|cc|mcg)\.'
        
        # Replace medical abbreviations temporarily
        text_protected = re.sub(medical_abbrevs, lambda m: m.group().replace('.', '~PERIOD~'), text)
        
        # Split on sentence boundaries
        sentences = re.split(r'[.!?]+\s+', text_protected)
        
        # Restore periods and clean up
        sentences = [s.replace('~PERIOD~', '.') + '. ' for s in sentences if s.strip()]
        
        return sentences


class ParallelDocumentProcessor:
    """
    Parallel processing manager for large document extraction operations.
    
    Coordinates multiple AI extraction tasks to process large documents efficiently
    while respecting API rate limits and maintaining result consistency.
    """
    
    def __init__(self, max_workers: int = None):
        """
        Initialize parallel processor.
        
        Args:
            max_workers: Maximum concurrent workers (defaults to CPU count)
        """
        self.max_workers = max_workers or min(4, (os.cpu_count() or 1) + 1)
        self.chunker = DocumentChunker()
        
    def process_document_parallel(self, document_id: int, chunk_size: int = None) -> Dict[str, Any]:
        """
        Process a large document using parallel AI extraction.
        
        Args:
            document_id: ID of document to process
            chunk_size: Optional chunk size override
            
        Returns:
            Aggregated extraction results from all chunks
        """
        from apps.documents.models import Document
        from apps.documents.services.text_extraction import extract_text_from_file
        from apps.documents.tasks import process_document_chunk
        
        start_time = time.time()
        logger.info(f"Starting parallel processing for document {document_id}")
        
        try:
            # Get document and extract text
            document = Document.objects.get(id=document_id)
            text = extract_text_from_file(document.file.path)
            
            # Check if chunking is needed
            chunk_threshold = chunk_size or getattr(settings, 'AI_TOKEN_THRESHOLD_FOR_CHUNKING', 20000)
            
            if len(text) <= chunk_threshold:
                logger.info(f"Document {document_id} small enough for single processing")
                # Use standard single-threaded processing
                from apps.documents.tasks import process_document
                return process_document.delay(document_id).get()
            
            # Chunk the document
            chunks = self.chunker.chunk_text(text, preserve_context=True)
            logger.info(f"Processing document {document_id} in {len(chunks)} parallel chunks")
            
            # Create Celery group for parallel processing
            chunk_tasks = []
            for i, chunk in enumerate(chunks):
                chunk_tasks.append(
                    process_document_chunk.s(
                        document_id=document_id,
                        chunk_text=chunk['text'],
                        chunk_id=chunk['chunk_id'],
                        chunk_metadata=chunk
                    )
                )
            
            # Execute chunks in parallel
            job = group(chunk_tasks)
            result = job.apply_async()
            
            # Collect results with timeout
            chunk_results = result.get(timeout=600)  # 10 minute timeout
            
            # Aggregate results
            aggregated_result = self._aggregate_chunk_results(chunk_results, document_id)
            
            processing_time = time.time() - start_time
            logger.info(f"Parallel processing completed for document {document_id} in {processing_time:.2f}s")
            
            return aggregated_result
            
        except Exception as e:
            logger.error(f"Parallel processing failed for document {document_id}: {e}")
            raise
    
    def _aggregate_chunk_results(self, chunk_results: List[Dict], document_id: int) -> Dict[str, Any]:
        """
        Aggregate extraction results from multiple document chunks.
        
        Args:
            chunk_results: List of extraction results from each chunk
            document_id: ID of source document
            
        Returns:
            Aggregated extraction result
        """
        from collections import defaultdict
        
        aggregated = {
            'conditions': [],
            'medications': [],
            'vital_signs': [],
            'lab_results': [],
            'procedures': [],
            'providers': [],
            'extraction_metadata': {
                'total_chunks': len(chunk_results),
                'processing_method': 'parallel',
                'aggregated_at': timezone.now().isoformat(),
                'document_id': document_id
            }
        }
        
        # Aggregate each data type
        for chunk_result in chunk_results:
            if chunk_result and isinstance(chunk_result, dict):
                for key in ['conditions', 'medications', 'vital_signs', 'lab_results', 'procedures', 'providers']:
                    if key in chunk_result:
                        aggregated[key].extend(chunk_result[key])
        
        # Deduplicate similar items
        aggregated = self._deduplicate_extracted_data(aggregated)
        
        logger.info(f"Aggregated {len(chunk_results)} chunks into {sum(len(v) for k, v in aggregated.items() if isinstance(v, list))} total items")
        
        return aggregated
    
    def _deduplicate_extracted_data(self, aggregated_data: Dict) -> Dict:
        """
        Remove duplicate medical items across chunks using fuzzy matching.
        
        Args:
            aggregated_data: Aggregated extraction results
            
        Returns:
            Deduplicated extraction results
        """
        from difflib import SequenceMatcher
        
        def is_similar(a: str, b: str, threshold: float = 0.85) -> bool:
            """Check if two medical terms are similar enough to be duplicates."""
            return SequenceMatcher(None, a.lower(), b.lower()).ratio() > threshold
        
        for data_type in ['conditions', 'medications', 'procedures']:
            if data_type in aggregated_data:
                items = aggregated_data[data_type]
                deduplicated = []
                
                for item in items:
                    # Extract name for comparison
                    item_name = item.get('name', str(item)) if isinstance(item, dict) else str(item)
                    
                    # Check if similar item already exists
                    is_duplicate = False
                    for existing in deduplicated:
                        existing_name = existing.get('name', str(existing)) if isinstance(existing, dict) else str(existing)
                        if is_similar(item_name, existing_name):
                            is_duplicate = True
                            break
                    
                    if not is_duplicate:
                        deduplicated.append(item)
                
                logger.info(f"Deduplicated {data_type}: {len(items)} -> {len(deduplicated)} items")
                aggregated_data[data_type] = deduplicated
        
        return aggregated_data


class PerformanceMonitor:
    """
    Performance monitoring and benchmarking for document processing operations.
    
    Tracks processing times, cache hit rates, and system performance metrics
    to identify optimization opportunities.
    """
    
    @staticmethod
    def timing_decorator(operation_name: str):
        """
        Decorator to time function execution and log performance metrics.
        
        Args:
            operation_name: Name of the operation for logging
        """
        def decorator(func: Callable):
            def wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = func(*args, **kwargs)
                    execution_time = time.time() - start_time
                    logger.info(f"Performance [{operation_name}]: {execution_time:.3f}s")
                    return result
                except Exception as e:
                    execution_time = time.time() - start_time
                    logger.error(f"Performance [{operation_name}] FAILED after {execution_time:.3f}s: {e}")
                    raise
            return wrapper
        return decorator
    
    @staticmethod
    def log_cache_performance(operation: str, cache_hit: bool, execution_time: float = None):
        """
        Log cache performance metrics.
        
        Args:
            operation: Name of the cached operation
            cache_hit: Whether the cache was hit or missed
            execution_time: Optional execution time for cache misses
        """
        status = "HIT" if cache_hit else "MISS"
        time_str = f" ({execution_time:.3f}s)" if execution_time else ""
        logger.info(f"Cache [{operation}]: {status}{time_str}")
    
    @staticmethod
    def benchmark_document_processing(document_sizes: List[int] = None) -> Dict[str, Any]:
        """
        Run benchmark tests on document processing performance.
        
        Args:
            document_sizes: List of document sizes to test (in MB)
            
        Returns:
            Benchmark results
        """
        if not document_sizes:
            document_sizes = [1, 5, 10, 20]  # Default test sizes in MB
        
        results = {
            'benchmark_timestamp': timezone.now().isoformat(),
            'test_sizes_mb': document_sizes,
            'results': []
        }
        
        for size_mb in document_sizes:
            # Generate test content of specified size
            test_content = "Sample medical text content. " * (size_mb * 1024 * 1024 // 30)
            
            start_time = time.time()
            # Run extraction test
            try:
                from apps.documents.services.ai_extraction import extract_medical_data
                extract_medical_data(test_content)
                processing_time = time.time() - start_time
                
                results['results'].append({
                    'size_mb': size_mb,
                    'processing_time_seconds': round(processing_time, 2),
                    'chars_per_second': round(len(test_content) / processing_time, 2),
                    'status': 'success'
                })
                
            except Exception as e:
                processing_time = time.time() - start_time
                results['results'].append({
                    'size_mb': size_mb,
                    'processing_time_seconds': round(processing_time, 2),
                    'status': 'failed',
                    'error': str(e)
                })
        
        logger.info(f"Benchmark completed: {len(results['results'])} tests")
        return results


# Global instances for easy access
document_chunker = DocumentChunker()
parallel_processor = ParallelDocumentProcessor()
performance_monitor = PerformanceMonitor()
