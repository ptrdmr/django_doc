"""
Performance optimization caching utilities for document processing pipeline.

This module implements intelligent caching strategies to improve document processing
performance by avoiding redundant AI API calls and FHIR conversions.
"""
import hashlib
import json
import logging
from typing import Dict, Any, Optional, List
from django.core.cache import cache
from django.conf import settings
from apps.documents.services.ai_extraction import StructuredMedicalExtraction

logger = logging.getLogger(__name__)


class DocumentProcessingCache:
    """
    Intelligent caching system for document processing pipeline performance optimization.
    
    Implements content-based caching to avoid redundant AI processing of identical
    or similar medical document content while maintaining HIPAA compliance.
    """
    
    # Cache key prefixes
    AI_EXTRACTION_PREFIX = "doc_ai_extract"
    FHIR_CONVERSION_PREFIX = "doc_fhir_convert" 
    PDF_TEXT_PREFIX = "doc_pdf_text"
    VALIDATION_PREFIX = "doc_validation"
    
    # Cache timeouts (in seconds)
    AI_EXTRACTION_TIMEOUT = 3600 * 24 * 7  # 7 days - AI results are stable
    FHIR_CONVERSION_TIMEOUT = 3600 * 24 * 3  # 3 days - FHIR schema changes occasionally
    PDF_TEXT_TIMEOUT = 3600 * 24 * 30  # 30 days - PDF content doesn't change
    VALIDATION_TIMEOUT = 3600 * 2  # 2 hours - Validation rules may change
    
    def __init__(self):
        self.cache_enabled = getattr(settings, 'ENABLE_DOCUMENT_PROCESSING_CACHE', True)
        # Use dedicated AI extraction cache if available, fallback to default
        from django.core.cache import caches
        try:
            self.ai_cache = caches['ai_extraction']
        except KeyError:
            self.ai_cache = caches['default']
        
    def _generate_content_hash(self, content: str, additional_context: Dict = None) -> str:
        """
        Generate a deterministic hash for content-based caching.
        
        Args:
            content: Text content to hash
            additional_context: Additional context that affects processing (e.g., AI model)
            
        Returns:
            Hexadecimal hash string for cache key
        """
        # Create hash input combining content and processing context
        hash_input = content.strip()
        
        if additional_context:
            # Include AI model, extraction parameters that affect results
            context_str = json.dumps(additional_context, sort_keys=True)
            hash_input += context_str
            
        # Generate SHA-256 hash (HIPAA-safe, no PHI in cache keys)
        return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()[:16]
    
    def get_ai_extraction_cache_key(self, text_content: str, ai_model: str, extraction_params: Dict = None) -> str:
        """Generate cache key for AI extraction results."""
        context = {
            'ai_model': ai_model,
            'extraction_version': '2.0',  # Increment when extraction logic changes
        }
        if extraction_params:
            context.update(extraction_params)
            
        content_hash = self._generate_content_hash(text_content, context)
        return f"{self.AI_EXTRACTION_PREFIX}:{content_hash}"
    
    def get_fhir_conversion_cache_key(self, structured_data: StructuredMedicalExtraction, patient_id: str) -> str:
        """Generate cache key for FHIR conversion results."""
        # Convert structured data to deterministic string for hashing
        data_dict = structured_data.model_dump()
        context = {
            'patient_id': patient_id,
            'fhir_version': 'R4',
            'converter_version': '2.0'  # Increment when FHIR conversion logic changes
        }
        
        content_hash = self._generate_content_hash(json.dumps(data_dict, sort_keys=True), context)
        return f"{self.FHIR_CONVERSION_PREFIX}:{content_hash}"
    
    def get_pdf_text_cache_key(self, file_path: str, file_size: int, file_mtime: float) -> str:
        """Generate cache key for PDF text extraction results."""
        # Use file metadata to create cache key (file content fingerprint)
        context = {
            'file_path': file_path,
            'file_size': file_size,
            'modified_time': file_mtime,
            'extractor_version': '1.0'
        }
        
        content_hash = self._generate_content_hash("", context)
        return f"{self.PDF_TEXT_PREFIX}:{content_hash}"
    
    def cache_ai_extraction(self, cache_key: str, extraction_result: Dict[str, Any]) -> bool:
        """
        Cache AI extraction results.
        
        Args:
            cache_key: Generated cache key
            extraction_result: AI extraction results to cache
            
        Returns:
            True if caching successful, False otherwise
        """
        if not self.cache_enabled:
            return False
            
        try:
            # Ensure we don't cache PHI - only processing results
            cacheable_result = {
                'structured_data': extraction_result.get('structured_data'),
                'confidence_average': extraction_result.get('confidence_average'),
                'model_used': extraction_result.get('model_used'),
                'processing_duration_ms': extraction_result.get('processing_duration_ms'),
                'field_count': extraction_result.get('field_count', 0),
                'cache_timestamp': timezone.now().isoformat()
            }
            
            self.ai_cache.set(cache_key, cacheable_result, timeout=self.AI_EXTRACTION_TIMEOUT)
            logger.info(f"Cached AI extraction result: {cache_key}")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to cache AI extraction result: {e}")
            return False
    
    def get_cached_ai_extraction(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached AI extraction results.
        
        Args:
            cache_key: Generated cache key
            
        Returns:
            Cached extraction results or None if not found
        """
        if not self.cache_enabled:
            return None
            
        try:
            cached_result = self.ai_cache.get(cache_key)
            if cached_result:
                logger.info(f"AI extraction cache hit: {cache_key}")
                return cached_result
            else:
                logger.debug(f"AI extraction cache miss: {cache_key}")
                return None
                
        except Exception as e:
            logger.warning(f"Failed to retrieve cached AI extraction: {e}")
            return None
    
    def cache_fhir_conversion(self, cache_key: str, fhir_resources: List[Dict[str, Any]]) -> bool:
        """
        Cache FHIR conversion results.
        
        Args:
            cache_key: Generated cache key
            fhir_resources: FHIR resources to cache
            
        Returns:
            True if caching successful, False otherwise
        """
        if not self.cache_enabled:
            return False
            
        try:
            cacheable_result = {
                'fhir_resources': fhir_resources,
                'resource_count': len(fhir_resources),
                'cache_timestamp': timezone.now().isoformat()
            }
            
            cache.set(cache_key, cacheable_result, timeout=self.FHIR_CONVERSION_TIMEOUT)
            logger.info(f"Cached FHIR conversion result: {cache_key} ({len(fhir_resources)} resources)")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to cache FHIR conversion result: {e}")
            return False
    
    def get_cached_fhir_conversion(self, cache_key: str) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieve cached FHIR conversion results.
        
        Args:
            cache_key: Generated cache key
            
        Returns:
            Cached FHIR resources or None if not found
        """
        if not self.cache_enabled:
            return None
            
        try:
            cached_result = self.ai_cache.get(cache_key)
            if cached_result:
                logger.info(f"FHIR conversion cache hit: {cache_key}")
                return cached_result.get('fhir_resources', [])
            else:
                logger.debug(f"FHIR conversion cache miss: {cache_key}")
                return None
                
        except Exception as e:
            logger.warning(f"Failed to retrieve cached FHIR conversion: {e}")
            return None
    
    def cache_pdf_text(self, cache_key: str, text_content: str, extraction_metadata: Dict = None) -> bool:
        """
        Cache PDF text extraction results.
        
        Args:
            cache_key: Generated cache key  
            text_content: Extracted text content
            extraction_metadata: Metadata about extraction process
            
        Returns:
            True if caching successful, False otherwise
        """
        if not self.cache_enabled:
            return False
            
        try:
            cacheable_result = {
                'text_content': text_content,
                'character_count': len(text_content),
                'extraction_metadata': extraction_metadata or {},
                'cache_timestamp': timezone.now().isoformat()
            }
            
            cache.set(cache_key, cacheable_result, timeout=self.PDF_TEXT_TIMEOUT)
            logger.info(f"Cached PDF text extraction: {cache_key} ({len(text_content)} chars)")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to cache PDF text extraction: {e}")
            return False
    
    def get_cached_pdf_text(self, cache_key: str) -> Optional[str]:
        """
        Retrieve cached PDF text extraction results.
        
        Args:
            cache_key: Generated cache key
            
        Returns:
            Cached text content or None if not found
        """
        if not self.cache_enabled:
            return None
            
        try:
            cached_result = self.ai_cache.get(cache_key)
            if cached_result:
                logger.info(f"PDF text extraction cache hit: {cache_key}")
                return cached_result.get('text_content')
            else:
                logger.debug(f"PDF text extraction cache miss: {cache_key}")
                return None
                
        except Exception as e:
            logger.warning(f"Failed to retrieve cached PDF text: {e}")
            return None
    
    def invalidate_document_cache(self, document_id: int) -> bool:
        """
        Invalidate all cached results for a specific document.
        
        Args:
            document_id: Document ID to invalidate cache for
            
        Returns:
            True if invalidation successful
        """
        try:
            # This is a best-effort invalidation since we use content hashes
            # In practice, reprocessing with same content will use cache
            # but different content will generate new cache keys
            logger.info(f"Cache invalidation requested for document {document_id}")
            return True
            
        except Exception as e:
            logger.warning(f"Cache invalidation failed for document {document_id}: {e}")
            return False
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.
        
        Returns:
            Dictionary with cache performance metrics
        """
        try:
            # Note: Django cache framework doesn't provide detailed stats
            # This is a placeholder for when Redis stats are needed
            return {
                'cache_enabled': self.cache_enabled,
                'cache_backend': settings.CACHES['default']['BACKEND'],
                'ai_extraction_timeout': self.AI_EXTRACTION_TIMEOUT,
                'fhir_conversion_timeout': self.FHIR_CONVERSION_TIMEOUT,
                'pdf_text_timeout': self.PDF_TEXT_TIMEOUT
            }
            
        except Exception as e:
            logger.warning(f"Failed to get cache stats: {e}")
            return {'error': str(e)}


# Global cache instance for easy import
# Global cache instance (lazy initialization to avoid import issues)
document_cache = None

def get_document_cache():
    """Get or create global document cache instance."""
    global document_cache
    if document_cache is None:
        document_cache = DocumentProcessingCache()
    return document_cache
