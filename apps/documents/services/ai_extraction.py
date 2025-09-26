"""
AI Extraction Service with Instructor-based Structured Data Extraction

This service uses the instructor library with Anthropic Claude (primary) and OpenAI (fallback)
to provide structured medical data extraction from clinical documents with Pydantic validation.
Follows the project's established AI service patterns and configuration.

Enhanced with comprehensive error handling and logging for Task 34.5.
"""

import logging
import json
import instructor
import time
import re
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from pydantic import BaseModel, Field, validator, ValidationError
from django.conf import settings
import anthropic
from openai import OpenAI

# Import custom exceptions for enhanced error handling
from apps.documents.exceptions import (
    AIExtractionError,
    AIServiceTimeoutError,
    AIServiceRateLimitError,
    AIResponseParsingError,
    PydanticModelError,
    ConfigurationError,
    ExternalServiceError
)

logger = logging.getLogger(__name__)

# Import enhanced prompting service for comprehensive data capture
# Note: This import is now handled locally in each function to avoid scope issues

# Initialize AI clients following project patterns with enhanced error handling
def _initialize_ai_clients():
    """Initialize AI clients with comprehensive error handling and validation."""
    anthropic_client = None
    openai_client = None
    
    try:
        # Validate configuration
        anthropic_key = getattr(settings, 'ANTHROPIC_API_KEY', None)
        openai_key = getattr(settings, 'OPENAI_API_KEY', None)
        
        if not anthropic_key and not openai_key:
            raise ConfigurationError(
                "No AI service API keys configured",
                config_key="ANTHROPIC_API_KEY, OPENAI_API_KEY",
                details={
                    'available_settings': dir(settings),
                    'has_anthropic_key': bool(anthropic_key),
                    'has_openai_key': bool(openai_key)
                }
            )
        
        # Initialize Anthropic Claude (primary)
        if anthropic_key:
            try:
                anthropic_client = anthropic.Anthropic(api_key=anthropic_key)
                logger.info("Anthropic Claude client initialized successfully (primary)")
            except Exception as e:
                logger.error(f"Failed to initialize Anthropic client: {e}")
                anthropic_client = None
        
        # Initialize OpenAI (fallback)
        if openai_key:
            try:
                openai_client = instructor.patch(OpenAI(api_key=openai_key))
                logger.info("OpenAI client initialized successfully (fallback)")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                openai_client = None
        
        # Try to patch Anthropic client with instructor for Pydantic support
        if anthropic_client:
            try:
                anthropic_client = instructor.patch(anthropic_client)
                logger.info("Anthropic Claude client patched with instructor for Pydantic support")
            except Exception as e:
                logger.warning(f"Could not patch Anthropic client with instructor: {e}, using manual JSON parsing")
                # anthropic_client remains unpatched - will use manual JSON parsing
        
        if not anthropic_client and not openai_client:
            raise ConfigurationError(
                "Failed to initialize any AI clients",
                details={'anthropic_available': bool(anthropic_key), 'openai_available': bool(openai_key)}
            )
        
        logger.info(f"AI clients initialized - Claude: {bool(anthropic_client)}, OpenAI: {bool(openai_client)}")
        return anthropic_client, openai_client
        
    except ConfigurationError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error initializing AI clients: {e}")
        raise ConfigurationError(
            f"Failed to initialize AI clients: {str(e)}",
            details={'exception_type': type(e).__name__}
        )

# Initialize clients
try:
    anthropic_client, openai_client = _initialize_ai_clients()
except ConfigurationError as e:
    logger.warning(f"AI client initialization failed: {e}")
    anthropic_client = None
    openai_client = None


class SourceContext(BaseModel):
    """Context information about where data was extracted from in the source text."""
    text: str = Field(description="The exact text snippet from the document")
    start_index: int = Field(description="Approximate start position in source text", ge=0, default=0)
    end_index: int = Field(description="Approximate end position in source text", ge=0, default=0)
    
    @validator('end_index')
    def end_after_start(cls, v, values):
        if 'start_index' in values and v < values['start_index'] and v != 0:
            v = values['start_index'] + len(values.get('text', ''))
        return v


class MedicalCondition(BaseModel):
    """A medical condition, diagnosis, or clinical finding."""
    name: str = Field(description="The medical condition or diagnosis name")
    status: str = Field(
        description="Status of the condition",
        default="active"
    )
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    onset_date: Optional[str] = Field(default=None, description="When condition was diagnosed")
    icd_code: Optional[str] = Field(default=None, description="ICD-10 code if mentioned")
    source: SourceContext = Field(description="Source context in the document")


class Medication(BaseModel):
    """A medication, drug, or therapeutic substance."""
    name: str = Field(description="The medication name")
    dosage: Optional[str] = Field(default=None, description="Dosage amount")
    route: Optional[str] = Field(default=None, description="Route of administration")
    frequency: Optional[str] = Field(default=None, description="Dosing frequency")
    status: str = Field(description="Medication status", default="active")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    start_date: Optional[str] = Field(default=None, description="When medication was started")
    stop_date: Optional[str] = Field(default=None, description="When medication was stopped")
    source: SourceContext = Field(description="Source context in the document")


class VitalSign(BaseModel):
    """A vital sign measurement."""
    measurement: str = Field(description="Type of vital sign")
    value: str = Field(description="The measured value")
    unit: Optional[str] = Field(default=None, description="Unit of measurement")
    timestamp: Optional[str] = Field(default=None, description="When measurement was taken")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class LabResult(BaseModel):
    """A laboratory test result."""
    test_name: str = Field(description="Name of the laboratory test")
    value: str = Field(description="Test result value")
    unit: Optional[str] = Field(default=None, description="Unit of measurement")
    reference_range: Optional[str] = Field(default=None, description="Normal reference range")
    status: Optional[str] = Field(default=None, description="Result status")
    test_date: Optional[str] = Field(default=None, description="Date test was performed")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class Procedure(BaseModel):
    """A medical procedure or intervention."""
    name: str = Field(description="Name of the procedure")
    procedure_date: Optional[str] = Field(default=None, description="Date procedure was performed")
    provider: Optional[str] = Field(default=None, description="Provider who performed procedure")
    outcome: Optional[str] = Field(default=None, description="Outcome or result")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class Provider(BaseModel):
    """A healthcare provider."""
    name: str = Field(description="Provider's name")
    specialty: Optional[str] = Field(default=None, description="Medical specialty")
    role: Optional[str] = Field(default=None, description="Role in patient care")
    contact_info: Optional[str] = Field(default=None, description="Contact information")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class StructuredMedicalExtraction(BaseModel):
    """Complete structured medical data extraction from a clinical document."""
    
    # Core medical data
    conditions: List[MedicalCondition] = Field(
        default_factory=list,
        description="All medical conditions, diagnoses, and clinical findings"
    )
    medications: List[Medication] = Field(
        default_factory=list,
        description="All medications, drugs, and therapeutic substances"
    )
    vital_signs: List[VitalSign] = Field(
        default_factory=list,
        description="All vital sign measurements"
    )
    lab_results: List[LabResult] = Field(
        default_factory=list,
        description="All laboratory test results"
    )
    procedures: List[Procedure] = Field(
        default_factory=list,
        description="All medical procedures and interventions"
    )
    providers: List[Provider] = Field(
        default_factory=list,
        description="All healthcare providers mentioned"
    )
    
    # Metadata
    extraction_timestamp: str = Field(description="When this extraction was performed")
    document_type: Optional[str] = Field(default=None, description="Type of clinical document")
    confidence_average: Optional[float] = Field(default=None, description="Average confidence")
    
    @validator('confidence_average', always=True)
    def calculate_average_confidence(cls, v, values):
        """Calculate average confidence across all extracted items."""
        all_items = []
        for field_name in ['conditions', 'medications', 'vital_signs', 'lab_results', 'procedures', 'providers']:
            items = values.get(field_name, [])
            all_items.extend(item.confidence for item in items)
        
        if all_items:
            return round(sum(all_items) / len(all_items), 3)
        return 0.0


def extract_medical_data_structured(text: str, context: Optional[str] = None) -> StructuredMedicalExtraction:
    """
    Extract structured medical data using Claude (primary) or OpenAI (fallback) with instructor.
    
    Enhanced with comprehensive error handling, retry logic, graceful degradation, and intelligent caching.
    
    Args:
        text: The medical document text to analyze
        context: Optional context about the document type or source
        
    Returns:
        StructuredMedicalExtraction object with all extracted data
        
    Raises:
        AIExtractionError: If extraction fails completely
        AIServiceTimeoutError: If AI service requests timeout
        AIServiceRateLimitError: If rate limits are exceeded
        AIResponseParsingError: If response cannot be parsed
        PydanticModelError: If data validation fails
        ConfigurationError: If AI services are not configured
    """
    from django.utils import timezone
    from apps.documents.cache import get_document_cache
    
    document_cache = get_document_cache()
    extraction_id = str(time.time())[:10]  # Short unique ID for this extraction
    logger.info(f"[{extraction_id}] Starting structured medical data extraction with caching")
    
    # Validate inputs
    if not text or not text.strip():
        raise AIExtractionError(
            "Cannot extract from empty text",
            details={'text_length': len(text), 'extraction_id': extraction_id}
        )
    
    if len(text) > 50000:  # Reasonable limit to prevent excessive API costs
        logger.warning(f"[{extraction_id}] Text is very long ({len(text)} chars), truncating to 50000")
        text = text[:50000]
    
    # Check if any AI clients are available
    if not anthropic_client and not openai_client:
        raise ConfigurationError(
            "No AI services available for extraction",
            details={'anthropic_available': False, 'openai_available': False}
        )
    
    # Performance Optimization: Check cache for existing extraction results
    primary_model = getattr(settings, 'AI_MODEL_PRIMARY', 'claude-3-5-sonnet-20240620')
    cache_context = {
        'ai_model': primary_model,
        'context': context or '',
        'extraction_version': '2.0'
    }
    cache_key = document_cache.get_ai_extraction_cache_key(text, primary_model, cache_context)
    
    # Try to get cached result first
    cached_result = document_cache.get_cached_ai_extraction(cache_key)
    if cached_result:
        logger.info(f"[{extraction_id}] Using cached AI extraction result (cache hit)")
        try:
            # Reconstruct StructuredMedicalExtraction from cached data
            cached_structured_data = cached_result.get('structured_data')
            if cached_structured_data:
                return StructuredMedicalExtraction.model_validate(cached_structured_data)
        except Exception as cache_error:
            logger.warning(f"[{extraction_id}] Cache result invalid, proceeding with fresh extraction: {cache_error}")
            # Continue with fresh extraction if cache is corrupted
    # Use comprehensive prompts for maximum data capture (90%+ target)
    # Try to use comprehensive prompts, fall back to basic prompts if not available
    try:
        from apps.documents.services.ai_extraction_service import AIExtractionService
        prompt_service = AIExtractionService()
        use_comprehensive = True
    except ImportError:
        prompt_service = None
        use_comprehensive = False
        logger.warning("AIExtractionService not available - using fallback prompts")
    
    if use_comprehensive and prompt_service:
        try:
            # Use comprehensive prompt from ai_extraction_service.py for maximum data capture
            comprehensive_prompt = prompt_service._get_comprehensive_extraction_prompt()
            
            # Add context-specific instructions if available
            context_instructions = ""
            if context:
                context_specific = prompt_service._get_context_specific_instructions(context)
                if context_specific:
                    context_instructions = f"\n\nContext-Specific Instructions:\n{context_specific}"
            
            # Build enhanced system prompt with comprehensive extraction targets
            system_prompt = f"""{comprehensive_prompt}{context_instructions}

CRITICAL REQUIREMENTS FOR STRUCTURED OUTPUT:
1. Extract EVERY piece of medical information mentioned
2. Provide source context for each extracted item (use exact text snippets)
3. Assign accurate confidence scores based on clarity and certainty
4. Use proper medical terminology and classifications
5. Include dates, values, and units exactly as written

CONFIDENCE SCORING:
- 0.9-1.0: Information explicitly and clearly stated
- 0.7-0.9: Information clearly implied or inferred  
- 0.5-0.7: Information mentioned but with some ambiguity
- 0.3-0.5: Information suggested but unclear
- 0.1-0.3: Information possibly mentioned but very unclear

STRUCTURED OUTPUT PRIORITY:
- Medications (highest priority): names, dosages, routes, frequencies with source context
- Conditions: diagnoses, symptoms, clinical findings with source context
- Vital signs: all measurements with values, units, and source context
- Lab results: test names, values, reference ranges, dates with source context
- Procedures: surgical and diagnostic procedures with dates and source context
- Providers: all healthcare professionals mentioned with source context"""
            
            logger.info(f"[{extraction_id}] Using comprehensive extraction prompts (90%+ data capture target)")
            
        except Exception as e:
            logger.warning(f"[{extraction_id}] Error using comprehensive prompts: {e}, falling back to standard prompt")
            use_comprehensive = False  # Disable for this session
    
    if not use_comprehensive:
        # Fallback to standard prompt
        system_prompt = """You are MediExtract Pro, an expert medical data extraction AI. 

Your task is to extract ALL medical information from clinical documents with the highest possible accuracy and completeness. 

CRITICAL REQUIREMENTS:
1. Extract EVERY piece of medical information mentioned
2. Provide source context for each extracted item (use the exact text snippet)
3. Assign accurate confidence scores based on clarity
4. Use proper medical terminology and classifications
5. Include dates, values, and units exactly as written

CONFIDENCE SCORING:
- 0.9-1.0: Information explicitly and clearly stated
- 0.7-0.9: Information clearly implied or inferred
- 0.5-0.7: Information mentioned but with some ambiguity
- 0.3-0.5: Information suggested but unclear
- 0.1-0.3: Information possibly mentioned but very unclear

Focus on:
- Medications (highest priority): names, dosages, routes, frequencies
- Conditions: diagnoses, symptoms, clinical findings
- Vital signs: all measurements with values and units
- Lab results: test names, values, reference ranges, dates
- Procedures: surgical and diagnostic procedures with dates
- Providers: all healthcare professionals mentioned"""
        
        logger.info(f"[{extraction_id}] Using standard extraction prompts")

    user_prompt = f"""Extract all medical information from this clinical document:

{text}

Document context: {context or 'General clinical document'}

Return structured data with complete source context for each item."""

    # Try Claude first (primary AI service)
    claude_errors = []
    if anthropic_client:
        try:
            logger.info(f"[{extraction_id}] Attempting structured extraction with Claude (primary)")
            
            start_time = time.time()
            
            # Try instructor-based approach first (if Claude client was successfully patched)
            try:
                # Check if Claude client has instructor capabilities
                if hasattr(anthropic_client, 'chat') and hasattr(anthropic_client.chat, 'completions'):
                    logger.info(f"[{extraction_id}] Using instructor-patched Claude for Pydantic extraction")
                    
                    extraction = anthropic_client.chat.completions.create(
                        model=getattr(settings, 'AI_MODEL_PRIMARY', 'claude-3-5-sonnet-20240620'),
                        response_model=StructuredMedicalExtraction,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.1,
                        max_tokens=getattr(settings, 'AI_MAX_TOKENS_PER_REQUEST', 4096)
                    )
                    
                    api_duration = time.time() - start_time
                    
                    # Set extraction timestamp and document type
                    extraction.extraction_timestamp = datetime.now().isoformat()
                    extraction.document_type = context
                    
                    total_items = (len(extraction.conditions) + len(extraction.medications) + 
                                 len(extraction.vital_signs) + len(extraction.lab_results) + 
                                 len(extraction.procedures) + len(extraction.providers))
                    
                    logger.info(f"[{extraction_id}] Claude instructor extraction successful: {total_items} items, "
                               f"confidence {extraction.confidence_average:.3f} in {api_duration:.2f}s")
                    
                    # Performance Optimization: Cache successful extraction result
                    try:
                        cache_data = {
                            'structured_data': extraction.model_dump(),
                            'extraction_metadata': {
                                'total_items': total_items,
                                'confidence_average': extraction.confidence_average,
                                'extraction_timestamp': extraction.extraction_timestamp,
                                'ai_service': 'claude_instructor',
                                'processing_time': api_duration
                            }
                        }
                        document_cache.cache_ai_extraction(cache_key, cache_data)
                        logger.info(f"[{extraction_id}] Cached successful extraction result")
                    except Exception as cache_error:
                        logger.warning(f"[{extraction_id}] Failed to cache extraction result: {cache_error}")
                        # Don't fail the extraction if caching fails
                    
                    return extraction
                
                else:
                    # Fall back to manual JSON parsing approach
                    raise Exception("Claude client not instructor-patched, using manual JSON parsing")
                    
            except Exception as instructor_error:
                logger.info(f"[{extraction_id}] Instructor approach failed: {instructor_error}, falling back to manual JSON parsing")
                
                # Fallback: Manual JSON parsing approach (original implementation)
                # Create a detailed schema prompt for Claude
                schema_prompt = f"""
Return valid JSON that exactly matches this schema structure:

{{
  "conditions": [
    {{
      "name": "condition name",
      "status": "active",
      "confidence": 0.9,
      "onset_date": null,
      "icd_code": null,
      "source": {{"text": "exact text from document", "start_index": 0, "end_index": 10}}
    }}
  ],
  "medications": [
    {{
      "name": "medication name",
      "dosage": "dosage amount",
      "route": null,
      "frequency": "frequency",
      "status": "active",
      "confidence": 0.9,
      "start_date": null,
      "stop_date": null,
      "source": {{"text": "exact text from document", "start_index": 0, "end_index": 10}}
    }}
  ],
  "vital_signs": [],
  "lab_results": [],
  "procedures": [],
  "providers": [],
  "extraction_timestamp": "",
  "document_type": "",
  "confidence_average": null
}}

CRITICAL: Every extracted item MUST include a "source" object with the exact text snippet."""
                
                # Reset start time for manual approach
                start_time = time.time()
                
                try:
                    response = anthropic_client.messages.create(
                        model=getattr(settings, 'AI_MODEL_PRIMARY', 'claude-3-5-sonnet-20240620'),
                        max_tokens=getattr(settings, 'AI_MAX_TOKENS_PER_REQUEST', 4096),
                        temperature=0.1,
                        system=system_prompt,
                        messages=[
                            {"role": "user", "content": user_prompt + "\n\n" + schema_prompt}
                        ]
                    )
                    api_duration = time.time() - start_time
                    
                    logger.info(f"[{extraction_id}] Claude manual JSON API call completed in {api_duration:.2f}s")
                    
                except anthropic.RateLimitError as e:
                    raise AIServiceRateLimitError(
                        f"Claude rate limit exceeded: {str(e)}",
                        ai_service="anthropic_claude",
                        details={'extraction_id': extraction_id, 'api_duration': time.time() - start_time}
                    )
                except anthropic.APITimeoutError as e:
                    raise AIServiceTimeoutError(
                        f"Claude API timeout: {str(e)}",
                        ai_service="anthropic_claude",
                        timeout_seconds=time.time() - start_time,
                        details={'extraction_id': extraction_id}
                    )
                except anthropic.APIError as e:
                    raise ExternalServiceError(
                        f"Claude API error: {str(e)}",
                        service_name="anthropic_claude",
                        details={'extraction_id': extraction_id, 'error_type': type(e).__name__}
                    )
                
                # Parse Claude's manual JSON response
                try:
                    response_text = response.content[0].text
                    logger.debug(f"[{extraction_id}] Claude manual response length: {len(response_text)} chars")
                    
                    # PORTHOLE: Capture raw Claude response for debugging
                    try:
                        from apps.core.porthole import capture_raw_llm_response
                        # Extract document ID from extraction_id if possible
                        doc_id = extraction_id.split('_')[-1] if '_' in extraction_id else extraction_id
                        capture_raw_llm_response(
                            document_id=doc_id,
                            raw_response=response_text,
                            llm_type="claude_manual_json",
                            parsing_successful=False  # Will update if parsing succeeds
                        )
                    except Exception as porthole_error:
                        logger.warning(f"[{extraction_id}] Porthole capture failed: {porthole_error}")
                    
                    # Try to extract JSON from the response
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if not json_match:
                        raise AIResponseParsingError(
                            "No valid JSON found in Claude response",
                            ai_service="anthropic_claude",
                            raw_response=response_text,
                            expected_format="JSON object",
                            details={'extraction_id': extraction_id}
                        )
                    
                    json_data = json.loads(json_match.group())
                    
                    # Set extraction timestamp and document type
                    json_data['extraction_timestamp'] = datetime.now().isoformat()
                    json_data['document_type'] = context
                    
                    # Parse into Pydantic model with detailed error handling
                    try:
                        extraction = StructuredMedicalExtraction(**json_data)
                    except ValidationError as ve:
                        raise PydanticModelError(
                            f"Claude response failed Pydantic validation: {str(ve)}",
                            model_name="StructuredMedicalExtraction",
                            validation_errors=ve.errors(),
                            details={'extraction_id': extraction_id, 'raw_data_keys': list(json_data.keys())}
                        )
                    
                    total_items = (len(extraction.conditions) + len(extraction.medications) + 
                                 len(extraction.vital_signs) + len(extraction.lab_results) + 
                                 len(extraction.procedures) + len(extraction.providers))
                    
                    logger.info(f"[{extraction_id}] Claude manual extraction successful: {total_items} items, "
                               f"confidence {extraction.confidence_average:.3f}")
                    
                    # Performance Optimization: Cache successful extraction result
                    try:
                        cache_data = {
                            'structured_data': extraction.model_dump(),
                            'extraction_metadata': {
                                'total_items': total_items,
                                'confidence_average': extraction.confidence_average,
                                'extraction_timestamp': extraction.extraction_timestamp,
                                'ai_service': 'claude'
                            }
                        }
                        document_cache.cache_ai_extraction(cache_key, cache_data)
                        logger.info(f"[{extraction_id}] Cached successful extraction result")
                    except Exception as cache_error:
                        logger.warning(f"[{extraction_id}] Failed to cache extraction result: {cache_error}")
                        # Don't fail the extraction if caching fails
                    
                    return extraction
                    
                except json.JSONDecodeError as je:
                    raise AIResponseParsingError(
                        f"Claude response is not valid JSON: {str(je)}",
                        ai_service="anthropic_claude",
                        raw_response=response_text[:500],  # Truncated for logging
                        expected_format="JSON object",
                        details={'extraction_id': extraction_id}
                    )
                
        except (AIServiceRateLimitError, AIServiceTimeoutError, ExternalServiceError, 
                AIResponseParsingError, PydanticModelError) as specific_error:
            # Re-raise specific errors
            claude_errors.append(str(specific_error))
            logger.warning(f"[{extraction_id}] Claude extraction failed with specific error: {specific_error}")
            raise
        except Exception as e:
            claude_errors.append(str(e))
            logger.warning(f"[{extraction_id}] Claude extraction failed with unexpected error: {e}, trying OpenAI fallback")
    
    # Try OpenAI as fallback
    openai_errors = []
    if openai_client:
        try:
            logger.info(f"[{extraction_id}] Attempting structured extraction with OpenAI (fallback)")
            
            start_time = time.time()
            try:
                extraction = openai_client.chat.completions.create(
                    model=getattr(settings, 'AI_MODEL_FALLBACK', 'gpt-4o-mini'),
                    response_model=StructuredMedicalExtraction,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.1,
                    max_tokens=getattr(settings, 'AI_MAX_TOKENS_PER_REQUEST', 4096)
                )
                api_duration = time.time() - start_time
                
                logger.info(f"[{extraction_id}] OpenAI API call completed in {api_duration:.2f}s")
                
            except Exception as openai_exc:
                # Handle various OpenAI-specific errors
                error_str = str(openai_exc).lower()
                
                if 'rate limit' in error_str or 'quota' in error_str:
                    raise AIServiceRateLimitError(
                        f"OpenAI rate limit exceeded: {str(openai_exc)}",
                        ai_service="openai_gpt",
                        details={'extraction_id': extraction_id, 'api_duration': time.time() - start_time}
                    )
                elif 'timeout' in error_str:
                    raise AIServiceTimeoutError(
                        f"OpenAI API timeout: {str(openai_exc)}",
                        ai_service="openai_gpt",
                        timeout_seconds=time.time() - start_time,
                        details={'extraction_id': extraction_id}
                    )
                else:
                    raise ExternalServiceError(
                        f"OpenAI API error: {str(openai_exc)}",
                        service_name="openai_gpt",
                        details={'extraction_id': extraction_id, 'error_type': type(openai_exc).__name__}
                    )
            
            # Validate the extraction result
            if not extraction:
                raise AIResponseParsingError(
                    "OpenAI returned empty extraction result",
                    ai_service="openai_gpt",
                    expected_format="StructuredMedicalExtraction",
                    details={'extraction_id': extraction_id}
                )
            
            # Set extraction timestamp and document type
            extraction.extraction_timestamp = datetime.now().isoformat()
            extraction.document_type = context
            
            total_items = (len(extraction.conditions) + len(extraction.medications) + 
                         len(extraction.vital_signs) + len(extraction.lab_results) + 
                         len(extraction.procedures) + len(extraction.providers))
            
            logger.info(f"[{extraction_id}] OpenAI extraction successful: {total_items} items, "
                       f"confidence {extraction.confidence_average:.3f}")
            
            # Performance Optimization: Cache successful extraction result
            try:
                cache_data = {
                    'structured_data': extraction.model_dump(),
                    'extraction_metadata': {
                        'total_items': total_items,
                        'confidence_average': extraction.confidence_average,
                        'extraction_timestamp': extraction.extraction_timestamp,
                        'ai_service': 'openai'
                    }
                }
                document_cache.cache_ai_extraction(cache_key, cache_data)
                logger.info(f"[{extraction_id}] Cached successful OpenAI extraction result")
            except Exception as cache_error:
                logger.warning(f"[{extraction_id}] Failed to cache extraction result: {cache_error}")
                # Don't fail the extraction if caching fails
            
            return extraction
            
        except (AIServiceRateLimitError, AIServiceTimeoutError, ExternalServiceError, 
                AIResponseParsingError) as specific_error:
            # Re-raise specific errors
            openai_errors.append(str(specific_error))
            logger.error(f"[{extraction_id}] OpenAI extraction failed with specific error: {specific_error}")
            raise
        except Exception as e:
            openai_errors.append(str(e))
            logger.error(f"[{extraction_id}] OpenAI extraction failed with unexpected error: {e}")
    
    # If both services fail, provide comprehensive error information
    all_errors = claude_errors + openai_errors
    error_summary = {
        'claude_available': bool(anthropic_client),
        'openai_available': bool(openai_client),
        'claude_errors': claude_errors,
        'openai_errors': openai_errors,
        'extraction_id': extraction_id,
        'text_length': len(text),
        'context': context
    }
    
    raise AIExtractionError(
        f"All AI extraction services failed. Errors: {'; '.join(all_errors[:3])}",  # Limit to first 3 errors
        details=error_summary
    )


def extract_medical_data(text: str, context: Optional[str] = None) -> Dict[str, Any]:
    """
    Legacy-compatible extraction function that returns a dictionary format.
    
    This function provides backward compatibility while using the new structured extraction.
    
    Args:
        text: The medical document text to analyze
        context: Optional context about the document type or source
        
    Returns:
        Dictionary with extracted medical data in legacy format
    """
    try:
        # Use the new structured extraction with enhanced error tracking
        structured_data = extract_medical_data_structured(text, context)
        
        # Convert to legacy format for backward compatibility
        legacy_format = {
            "diagnoses": [condition.name for condition in structured_data.conditions],
            "medications": [
                f"{med.name} {med.dosage or ''} {med.frequency or ''}".strip()
                for med in structured_data.medications
            ],
            "procedures": [proc.name for proc in structured_data.procedures],
            "lab_results": [
                {
                    "test": lab.test_name,
                    "value": lab.value,
                    "unit": lab.unit or "",
                    "reference_range": lab.reference_range or ""
                }
                for lab in structured_data.lab_results
            ],
            "vital_signs": [
                {
                    "type": vital.measurement_type,
                    "value": vital.value,
                    "unit": vital.unit or ""
                }
                for vital in structured_data.vital_signs
            ],
            "providers": [
                {
                    "name": provider.name,
                    "specialty": provider.specialty or "",
                    "role": provider.role or ""
                }
                for provider in structured_data.providers
            ],
            # Metadata
            "extraction_confidence": structured_data.confidence_average,
            "extraction_timestamp": structured_data.extraction_timestamp,
            "total_items_extracted": (
                len(structured_data.conditions) + 
                len(structured_data.medications) + 
                len(structured_data.vital_signs) + 
                len(structured_data.lab_results) + 
                len(structured_data.procedures) + 
                len(structured_data.providers)
            ),
            "extraction_method": "structured_ai",
            "error_recovery_used": False
        }
        
        logger.info(f"Converted structured data to legacy format: {legacy_format['total_items_extracted']} total items")
        return legacy_format
        
    except (AIServiceRateLimitError, AIServiceTimeoutError) as rate_error:
        # For rate limiting, don't fallback immediately - let caller handle retry
        logger.warning(f"Rate limiting in legacy extraction: {rate_error}")
        raise
    except (AIExtractionError, AIResponseParsingError, PydanticModelError) as ai_error:
        logger.warning(f"AI extraction failed in legacy method: {ai_error}, falling back to regex extraction")
        # Fallback to basic extraction for AI-specific errors
        fallback_result = legacy_extract_medical_data(text, context)
        fallback_result["error_recovery_used"] = True
        fallback_result["original_error"] = str(ai_error)
        return fallback_result
    except Exception as e:
        logger.error(f"Unexpected error in legacy extraction: {e}")
        # Fallback to basic extraction for any other errors
        fallback_result = legacy_extract_medical_data(text, context)
        fallback_result["error_recovery_used"] = True
        fallback_result["original_error"] = str(e)
        return fallback_result


def legacy_extract_medical_data(text: str, context: Optional[str] = None) -> Dict[str, Any]:
    """
    Fallback extraction method that uses simpler text analysis.
    
    Args:
        text: The medical document text to analyze
        context: Optional context about the document type or source
        
    Returns:
        Basic dictionary with extracted medical data
    """
    logger.warning("Using fallback legacy extraction method")
    
    # Simple keyword-based extraction as fallback
    import re
    
    # Basic medication pattern matching
    medication_patterns = [
        r'\b\w+\s+\d+\s*mg\b',  # Drug name + dosage
        r'\b\w+\s+\d+\s*mcg\b',
        r'\b\w+\s+\d+\s*units?\b'
    ]
    
    medications = []
    for pattern in medication_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        medications.extend(matches)
    
    # Basic diagnosis pattern matching
    diagnosis_patterns = [
        r'(?:diagnosis|dx|impression):\s*([^.\n]+)',
        r'(?:condition|disease):\s*([^.\n]+)'
    ]
    
    diagnoses = []
    for pattern in diagnosis_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        diagnoses.extend([match.strip() for match in matches])
    
    return {
        "diagnoses": list(set(diagnoses)) if diagnoses else ["No diagnoses extracted"],
        "medications": list(set(medications)) if medications else ["No medications extracted"],
        "procedures": [],
        "lab_results": [],
        "vital_signs": [],
        "providers": [],
        "extraction_confidence": 0.3,  # Low confidence for fallback method
        "extraction_timestamp": datetime.now().isoformat(),
        "total_items_extracted": len(set(diagnoses)) + len(set(medications)),
        "fallback_method": True
    }


# Export the main functions for external use
__all__ = [
    'extract_medical_data',
    'extract_medical_data_structured',
    'StructuredMedicalExtraction',
    'MedicalCondition',
    'Medication',
    'VitalSign', 
    'LabResult',
    'Procedure',
    'Provider',
    'SourceContext',
    'COMPREHENSIVE_PROMPTS_AVAILABLE'
]
