# apps/documents/services/ai_analyzer.py
"""
Django implementation template for DocumentAnalyzer service
Based on proven Flask patterns from example_parser.md
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils import timezone
import anthropic
import httpx
import logging
import json
from typing import Dict, Optional, List, Any

from .response_parser import ResponseParser
from .chunking import DocumentChunker
from .cost_tracking import CostTracker
from .prompts import MedicalPrompts
from .error_handling import AIServiceErrorHandler


class DocumentAnalyzer:
    """
    Django service for AI-powered medical document analysis
    Translated from Flask DocumentAnalyzer patterns
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the DocumentAnalyzer with API credentials and dependencies
        
        Args:
            api_key: Optional API key override, uses settings if not provided
        """
        self.api_key = api_key or getattr(settings, 'ANTHROPIC_API_KEY', None)
        if not self.api_key:
            raise ImproperlyConfigured("ANTHROPIC_API_KEY must be configured in Django settings")
        
        # Initialize dependencies
        self.logger = logging.getLogger(__name__)
        self.response_parser = ResponseParser()
        self.chunker = DocumentChunker()
        self.cost_tracker = CostTracker()
        self.error_handler = AIServiceErrorHandler()
        self.prompts = MedicalPrompts()
        
        # AI client configuration
        try:
            http_client = httpx.Client(
                timeout=getattr(settings, 'AI_REQUEST_TIMEOUT', 60.0),
                follow_redirects=True
            )
            self.client = anthropic.Client(api_key=self.api_key, http_client=http_client)
            self.model = getattr(settings, 'AI_MODEL_PRIMARY', 'claude-3-sonnet-20240229')
            self.max_tokens = getattr(settings, 'AI_MAX_TOKENS_PER_REQUEST', 4096)
            
            self.logger.info(f"Initialized DocumentAnalyzer with model: {self.model}")
            
        except Exception as e:
            self.logger.error(f"Error initializing Anthropic client: {e}")
            raise ImproperlyConfigured(f"Failed to initialize AI client: {e}")
    
    def analyze_document(
        self, 
        document_content: str, 
        system_prompt: Optional[str] = None,
        context_tags: Optional[List[Dict]] = None,
        fhir_focused: bool = False
    ) -> Dict[str, Any]:
        """
        Analyze a medical document using AI extraction
        
        Args:
            document_content: The text content of the document
            system_prompt: Optional custom system prompt
            context_tags: Optional context tags for enhanced extraction
            fhir_focused: Whether to use FHIR-specific extraction
            
        Returns:
            Dictionary containing analysis results
        """
        try:
            # Log document characteristics
            doc_length = len(document_content)
            estimated_tokens = doc_length / 4  # Rough estimate
            self.logger.info(
                f"Processing document: {doc_length} characters, ~{estimated_tokens:.0f} tokens"
            )
            
            # Determine if chunking is needed
            if self.chunker.should_chunk_document(document_content):
                self.logger.info("Document requires chunking for processing")
                return self._analyze_large_document(
                    document_content, system_prompt, context_tags, fhir_focused
                )
            
            # Use standard processing for normal-sized documents
            return self._analyze_single_document(
                document_content, system_prompt, context_tags, fhir_focused
            )
            
        except Exception as e:
            self.logger.error(f"Error in analyze_document: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Document analysis failed: {str(e)}",
                "error_type": type(e).__name__
            }
    
    def _analyze_single_document(
        self, 
        content: str, 
        system_prompt: Optional[str] = None,
        context_tags: Optional[List[Dict]] = None,
        fhir_focused: bool = False
    ) -> Dict[str, Any]:
        """
        Process a single document that doesn't require chunking
        
        Args:
            content: Document content
            system_prompt: Optional custom prompt
            context_tags: Optional context tags
            fhir_focused: Use FHIR-specific extraction
            
        Returns:
            Analysis results dictionary
        """
        try:
            # Select appropriate prompt
            if system_prompt is None:
                system_prompt = self.prompts.get_extraction_prompt(
                    fhir_focused=fhir_focused
                )
            
            # Enhance prompt with context if provided
            if context_tags or system_prompt != self.prompts.get_extraction_prompt():
                system_prompt = self.prompts.enhance_prompt(
                    system_prompt, context_tags
                )
            
            self.logger.info(f"Making API call with model: {self.model}")
            
            # Call AI API with error handling
            response = self.error_handler.call_ai_with_retry(
                self.client,
                model=self.model,
                system=system_prompt,
                max_tokens=self.max_tokens,
                messages=[{
                    "role": "user",
                    "content": f"Extract medical data from this document:\n\n{content}"
                }]
            )
            
            # Parse response
            text_content = response.content[0].text
            parsed_fields = self.response_parser.extract_structured_data(text_content)
            
            return {
                "success": True,
                "fields": parsed_fields,
                "raw_response": text_content,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens
                },
                "model_used": self.model,
                "processing_method": "single_document"
            }
            
        except Exception as e:
            self.logger.error(f"Error in single document analysis: {e}", exc_info=True)
            raise ValidationError(f"AI analysis failed: {str(e)}")
    
    def _analyze_large_document(
        self,
        document_content: str,
        system_prompt: Optional[str] = None,
        context_tags: Optional[List[Dict]] = None,
        fhir_focused: bool = False
    ) -> Dict[str, Any]:
        """
        Analyze a large document using chunking strategy from Flask example
        
        Args:
            document_content: The large document content
            system_prompt: Optional base system prompt
            context_tags: Optional context tags
            fhir_focused: Use FHIR-specific extraction
            
        Returns:
            Combined analysis results from all chunks
        """
        try:
            # Split document into chunks
            document_parts = self.chunker.chunk_document(document_content)
            self.logger.info(f"Split document into {len(document_parts)} parts")
            
            all_fields = []
            total_input_tokens = 0
            total_output_tokens = 0
            
            for i, part in enumerate(document_parts):
                self.logger.info(f"Processing chunk {i+1}/{len(document_parts)}")
                
                # Get chunked document prompt
                chunk_prompt = self.prompts.get_chunked_prompt(
                    part_number=i+1,
                    total_parts=len(document_parts),
                    base_prompt=system_prompt,
                    fhir_focused=fhir_focused
                )
                
                # Enhance with context if provided
                if context_tags:
                    chunk_prompt = self.prompts.enhance_prompt(chunk_prompt, context_tags)
                
                try:
                    response = self.error_handler.call_ai_with_retry(
                        self.client,
                        model=self.model,
                        system=chunk_prompt,
                        max_tokens=self.max_tokens,
                        messages=[{
                            "role": "user",
                            "content": f"Extract data from this document part:\n\n{part}"
                        }]
                    )
                    
                    # Parse chunk response
                    text_content = response.content[0].text
                    chunk_fields = self.response_parser.extract_structured_data(text_content)
                    
                    # Add chunk information to each field
                    for field in chunk_fields:
                        field['source_chunk'] = i + 1
                    
                    all_fields.extend(chunk_fields)
                    
                    # Track token usage
                    total_input_tokens += response.usage.input_tokens
                    total_output_tokens += response.usage.output_tokens
                    
                    self.logger.info(f"Successfully processed chunk {i+1}")
                    
                except Exception as e:
                    self.logger.error(f"Error processing chunk {i+1}: {e}")
                    # Continue with other chunks even if one fails
                    continue
            
            # Merge and deduplicate fields from all chunks
            merged_fields = self._merge_chunk_fields(all_fields)
            
            return {
                "success": True,
                "fields": merged_fields,
                "usage": {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens
                },
                "model_used": self.model,
                "processing_method": "chunked_document",
                "chunks_processed": len(document_parts),
                "chunks_successful": len([f for f in all_fields if 'source_chunk' in f])
            }
            
        except Exception as e:
            self.logger.error(f"Error in large document analysis: {e}", exc_info=True)
            raise ValidationError(f"Chunked analysis failed: {str(e)}")
    
    def _merge_chunk_fields(self, all_fields: List[Dict]) -> List[Dict]:
        """
        Merge and deduplicate fields from multiple document chunks
        Based on Flask merge_fields logic
        
        Args:
            all_fields: List of field dictionaries from all chunks
            
        Returns:
            List of merged and deduplicated fields
        """
        # Group fields by label (case-insensitive)
        field_groups = {}
        
        for field in all_fields:
            label_key = field.get("label", "").lower()
            if label_key not in field_groups:
                field_groups[label_key] = []
            field_groups[label_key].append(field)
        
        merged_fields = []
        
        for label_key, fields in field_groups.items():
            if not fields:
                continue
            
            # Find the best field (highest confidence, then longest value)
            best_field = max(fields, key=lambda f: (
                f.get("confidence", 0),
                len(str(f.get("value", "")))
            ))
            
            # Add source information if from multiple chunks
            if len(fields) > 1:
                source_chunks = [f.get('source_chunk') for f in fields if f.get('source_chunk')]
                best_field['merged_from_chunks'] = source_chunks
            
            merged_fields.append(best_field)
        
        # Assign sequential IDs
        for i, field in enumerate(merged_fields):
            field["id"] = str(i + 1)
        
        return merged_fields
    
    def convert_to_fhir(self, extracted_fields: List[Dict]) -> Dict[str, Any]:
        """
        Convert extracted fields to FHIR-compatible format
        
        Args:
            extracted_fields: List of extracted field dictionaries
            
        Returns:
            FHIR-compatible data structure
        """
        # TODO: Implement FHIR conversion logic
        # This would map extracted fields to proper FHIR resources
        
        fhir_bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": []
        }
        
        # Convert fields to FHIR resources based on type
        for field in extracted_fields:
            label = field.get("label", "").lower()
            value = field.get("value")
            confidence = field.get("confidence", 0.0)
            
            if not value:
                continue
            
            # Map common fields to FHIR resources
            if "patient" in label or "name" in label:
                # Add to Patient resource
                pass
            elif "diagnosis" in label or "condition" in label:
                # Add to Condition resource
                pass
            elif "medication" in label:
                # Add to MedicationStatement resource
                pass
            # Add more mappings as needed
        
        return fhir_bundle
    
    def validate_extraction(self, extracted_data: Dict, original_text: str) -> Dict[str, Any]:
        """
        Validate extracted data quality and accuracy
        
        Args:
            extracted_data: The extracted data to validate
            original_text: Original document text for cross-reference
            
        Returns:
            Validation results
        """
        validation_results = {
            "is_valid": True,
            "confidence_score": 0.0,
            "issues": [],
            "suggestions": []
        }
        
        # TODO: Implement validation logic
        # - Check for required fields
        # - Validate data formats (dates, phone numbers, etc.)
        # - Cross-reference with original text
        # - Check confidence score distribution
        
        return validation_results


# Example usage in Django views/tasks:
"""
# In a Django view or Celery task
from apps.documents.services.ai_analyzer import DocumentAnalyzer

def process_document(document):
    analyzer = DocumentAnalyzer()
    
    result = analyzer.analyze_document(
        document_content=document.original_text,
        context_tags=[{"text": "Emergency Department"}],
        fhir_focused=True
    )
    
    if result['success']:
        # Store results
        document.extraction_json = result['fields']
        document.fhir_data = analyzer.convert_to_fhir(result['fields'])
        document.ai_tokens_used = result['usage']['total_tokens']
        document.save()
    
    return result
""" 