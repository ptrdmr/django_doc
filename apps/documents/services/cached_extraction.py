"""
Prompt-cached structured extraction via the raw Anthropic SDK.

Bypasses Instructor (v1.3.3 cannot pass cache_control) and calls
client.messages.create directly with:

- Static system blocks (canonical extraction prompt + JSON schema) marked
  cache_control ephemeral. Anthropic caches the byte-identical prefix, cutting
  input cost ~90% on every chunk after the first within a 5-minute window.
- Variable content (context instructions + chunk text) ONLY in the user
  message, after the cached prefix.
- Pydantic validation in code with ONE bounded retry that feeds the
  validation error back — no silent unbounded retry loops.

Usage data (including cache_read_input_tokens) is captured per call in
last_usage for cost tracking and cache-hit verification.
"""

import json
import logging
import re
import time
from typing import Any, Dict, Optional

import anthropic
from django.conf import settings
from pydantic import ValidationError

from apps.documents.exceptions import (
    AIExtractionError,
    AIResponseParsingError,
    AIServiceRateLimitError,
    AIServiceTimeoutError,
    ConfigurationError,
    ExternalServiceError,
    PydanticModelError,
)
from apps.documents.services.extraction_prompts import (
    SCHEMA_PROMPT,
    get_canonical_system_prompt,
    get_context_instructions,
)

logger = logging.getLogger(__name__)


class CachedAnthropicExtractor:
    """
    Structured medical extraction with Anthropic prompt caching.

    Builds the static system prefix once and reuses it byte-identically for
    every call so the API-side prompt cache hits on chunks 2..N of a document.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize a raw (non-Instructor) Anthropic client with explicit
        HTTP timeouts and a single SDK-level retry.

        Raises:
            ConfigurationError: If no Anthropic API key is available.
        """
        key = api_key or getattr(settings, 'ANTHROPIC_API_KEY', None)
        if not key:
            raise ConfigurationError(
                "Anthropic API key not configured for cached extraction",
                config_key="ANTHROPIC_API_KEY",
            )

        request_timeout = float(getattr(settings, 'AI_REQUEST_TIMEOUT', 120))
        self.client = anthropic.Anthropic(
            api_key=key,
            timeout=anthropic.Timeout(
                connect=10.0,
                read=request_timeout,
                write=request_timeout,
                pool=30.0,
            ),
            max_retries=1,
        )
        self.model = getattr(settings, 'AI_MODEL_PRIMARY', 'claude-sonnet-4-5-20250929')
        self.max_tokens = getattr(settings, 'AI_MAX_TOKENS_PER_REQUEST', 4096)
        # Usage stats from the most recent API call (for cost tracking)
        self.last_usage: Dict[str, Any] = {}

    def _build_system_blocks(self) -> list:
        """
        Static system blocks with cache_control on the final block.

        cache_control on the last block caches the entire prefix up to and
        including that block. Content must be byte-identical across calls.
        """
        return [
            {
                "type": "text",
                "text": get_canonical_system_prompt(),
            },
            {
                "type": "text",
                "text": SCHEMA_PROMPT,
                "cache_control": {"type": "ephemeral"},
            },
        ]

    def _build_user_message(self, text: str, context: Optional[str]) -> str:
        """All variable content goes here, after the cached system prefix."""
        context_block = get_context_instructions(context)
        return (
            f"Extract all medical information from this clinical document:\n\n"
            f"{text}\n\n"
            f"Document context: {context or 'General clinical document'}"
            f"{context_block}\n\n"
            f"Return structured data with complete source context for each item."
        )

    def _call_api(self, system_blocks: list, messages: list, extraction_id: str) -> str:
        """
        Make one API call and return the response text.

        Maps SDK errors to domain exceptions and records usage stats.
        """
        start_time = time.time()
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=0.1,
                system=system_blocks,
                messages=messages,
            )
        except anthropic.RateLimitError as e:
            raise AIServiceRateLimitError(
                f"Claude rate limit exceeded: {str(e)}",
                ai_service="anthropic_claude",
                details={'extraction_id': extraction_id, 'api_duration': time.time() - start_time},
            )
        except anthropic.APITimeoutError as e:
            raise AIServiceTimeoutError(
                f"Claude API timeout: {str(e)}",
                ai_service="anthropic_claude",
                timeout_seconds=time.time() - start_time,
                details={'extraction_id': extraction_id},
            )
        except anthropic.APIError as e:
            raise ExternalServiceError(
                f"Claude API error: {str(e)}",
                service_name="anthropic_claude",
                details={'extraction_id': extraction_id, 'error_type': type(e).__name__},
            )

        api_duration = time.time() - start_time
        usage = getattr(response, 'usage', None)
        cache_read = getattr(usage, 'cache_read_input_tokens', 0) or 0
        cache_created = getattr(usage, 'cache_creation_input_tokens', 0) or 0
        input_tokens = getattr(usage, 'input_tokens', 0) or 0
        output_tokens = getattr(usage, 'output_tokens', 0) or 0

        self.last_usage = {
            'model': self.model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cache_read_input_tokens': cache_read,
            'cache_creation_input_tokens': cache_created,
            'api_duration_seconds': api_duration,
        }

        logger.info(
            f"[{extraction_id}] Cached extraction API call: {api_duration:.2f}s, "
            f"input={input_tokens}, output={output_tokens}, "
            f"cache_read={cache_read}, cache_created={cache_created} "
            f"({'CACHE HIT' if cache_read > 0 else 'cache miss'})"
        )

        response_text = response.content[0].text
        del response
        return response_text

    def _parse_and_validate(self, response_text: str, context: Optional[str], extraction_id: str):
        """
        Extract JSON from response text and validate against the Pydantic model.

        Raises:
            AIResponseParsingError: If no JSON object found or JSON is invalid.
            ValidationError: If JSON parses but fails Pydantic validation
                (caught by caller for the bounded retry).
        """
        from datetime import datetime

        from apps.documents.services.ai_extraction import StructuredMedicalExtraction

        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if not json_match:
            raise AIResponseParsingError(
                "No valid JSON found in Claude response",
                ai_service="anthropic_claude",
                raw_response=response_text[:500],
                expected_format="JSON object",
                details={'extraction_id': extraction_id},
            )

        try:
            json_data = json.loads(json_match.group())
        except json.JSONDecodeError as je:
            raise AIResponseParsingError(
                f"Claude response is not valid JSON: {str(je)}",
                ai_service="anthropic_claude",
                raw_response=response_text[:500],
                expected_format="JSON object",
                details={'extraction_id': extraction_id},
            )

        json_data['extraction_timestamp'] = datetime.now().isoformat()
        json_data['document_type'] = context

        # May raise pydantic.ValidationError — caller handles the bounded retry
        return StructuredMedicalExtraction(**json_data)

    def extract(self, text: str, context: Optional[str] = None,
                extraction_id: Optional[str] = None):
        """
        Run structured extraction on a chunk of document text.

        Args:
            text: Document/chunk text to extract from.
            context: Optional document-type context (variable; goes in user msg).
            extraction_id: Optional correlation ID for logging.

        Returns:
            StructuredMedicalExtraction instance.

        Raises:
            AIExtractionError subclasses on API or parsing failure.
            PydanticModelError if validation fails even after the bounded retry.
        """
        if not text or not text.strip():
            raise AIExtractionError(
                "Cannot extract from empty text",
                details={'text_length': len(text or ''), 'extraction_id': extraction_id},
            )

        extraction_id = extraction_id or str(time.time())[:10]
        system_blocks = self._build_system_blocks()
        user_message = self._build_user_message(text, context)
        messages = [{"role": "user", "content": user_message}]

        response_text = self._call_api(system_blocks, messages, extraction_id)
        self._capture_porthole(response_text, extraction_id)

        try:
            return self._parse_and_validate(response_text, context, extraction_id)
        except ValidationError as ve:
            logger.warning(
                f"[{extraction_id}] Pydantic validation failed "
                f"({len(ve.errors())} errors), attempting one bounded retry"
            )
            return self._retry_with_validation_feedback(
                system_blocks, user_message, response_text, ve, context, extraction_id
            )

    def _retry_with_validation_feedback(self, system_blocks: list, user_message: str,
                                        failed_response: str, validation_error: ValidationError,
                                        context: Optional[str], extraction_id: str):
        """
        One bounded retry: feed the validation errors back so the model can
        correct field names/types. If this also fails, raise — no further
        retries (each retry re-bills the full output and non-cached input).
        """
        error_summary = json.dumps(validation_error.errors()[:10], default=str)
        retry_messages = [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": failed_response[:20000]},
            {
                "role": "user",
                "content": (
                    "Your previous JSON response failed schema validation with these errors:\n"
                    f"{error_summary}\n\n"
                    "Return the corrected, complete JSON object using the exact field names "
                    "from the schema. Respond with ONLY the JSON object."
                ),
            },
        ]

        retry_text = self._call_api(system_blocks, retry_messages, f"{extraction_id}-retry")
        self._capture_porthole(retry_text, f"{extraction_id}-retry")

        try:
            return self._parse_and_validate(retry_text, context, extraction_id)
        except ValidationError as ve:
            raise PydanticModelError(
                f"Claude response failed Pydantic validation after bounded retry: {str(ve)}",
                model_name="StructuredMedicalExtraction",
                validation_errors=ve.errors(),
                details={'extraction_id': extraction_id, 'retried': True},
            )

    @staticmethod
    def _capture_porthole(response_text: str, extraction_id: str) -> None:
        """Capture raw response for debugging; never fails the extraction."""
        try:
            from apps.core.porthole import capture_raw_llm_response
            doc_id = extraction_id.split('_')[-1] if '_' in extraction_id else extraction_id
            capture_raw_llm_response(
                document_id=doc_id,
                raw_response=response_text,
                llm_type="claude_cached_extraction",
                parsing_successful=False,
            )
        except Exception as porthole_error:
            logger.warning(f"[{extraction_id}] Porthole capture failed: {porthole_error}")


_extractor_instance: Optional[CachedAnthropicExtractor] = None


def get_cached_extractor() -> CachedAnthropicExtractor:
    """Module-level singleton so the client and prompt strings are built once."""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = CachedAnthropicExtractor()
    return _extractor_instance
