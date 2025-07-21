# 🤖 AI Document Parser - Django Implementation Guide

## Overview

This guide translates the proven Flask DocumentAnalyzer patterns into Django-compatible implementations for our medical document processing system.

## Flask → Django Architecture Translation

### 1. Core Service Class Pattern

**Flask Pattern (Proven Working)**:
```python
# example_parser.md - DocumentAnalyzer class
class DocumentAnalyzer:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
        self.client = anthropic.Client(api_key=self.api_key, http_client=http_client)
        self.model = "claude-3-sonnet-20240229"
```

**Django Equivalent**:
```python
# apps/documents/services/ai_analyzer.py
from django.conf import settings
import anthropic
import httpx
import logging

class DocumentAnalyzer:
    """Django service for AI-powered medical document analysis"""
    
    def __init__(self, api_key=None):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY must be set in Django settings")
        
        try:
            http_client = httpx.Client(timeout=60.0, follow_redirects=True)
            self.client = anthropic.Client(api_key=self.api_key, http_client=http_client)
            self.model = getattr(settings, 'AI_MODEL_PRIMARY', 'claude-3-sonnet-20240229')
            self.logger = logging.getLogger(__name__)
        except Exception as e:
            self.logger.error(f"Error initializing Anthropic client: {e}")
            raise
```

### 2. Celery Task Integration

**Django Pattern**:
```python
# apps/documents/tasks.py
from celery import shared_task
from .services.ai_analyzer import DocumentAnalyzer
from .models import Document, ParsedData

@shared_task(bind=True)
def process_document_with_ai(self, document_id):
    """Process document using AI analyzer service"""
    try:
        document = Document.objects.get(id=document_id)
        document.status = 'processing'
        document.save(update_fields=['status'])
        
        # Initialize analyzer
        analyzer = DocumentAnalyzer()
        
        # Extract text (already implemented in Task 6.4)
        text_content = document.original_text
        
        # Process with AI
        result = analyzer.analyze_document(text_content)
        
        if result['success']:
            # Store parsed data
            ParsedData.objects.create(
                document=document,
                patient=document.patient,
                extraction_json=result['fields'],
                fhir_delta_json=analyzer.convert_to_fhir(result['fields'])
            )
            
            document.status = 'completed'
            document.processed_at = timezone.now()
        else:
            document.status = 'failed'
            document.error_message = result.get('error', 'Unknown error')
            
        document.save()
        return result
        
    except Exception as exc:
        document.status = 'failed'
        document.save()
        raise self.retry(exc=exc, countdown=300, max_retries=3)
```

## Key Implementation Components

### 1. System Prompts Management

**Location**: `apps/documents/services/prompts.py`

```python
class MedicalPrompts:
    """Centralized medical document processing prompts"""
    
    BASE_SYSTEM_PROMPT = """You are MediExtract, an AI assistant crafted to meticulously extract data from medical documents with unwavering precision and dedication..."""
    
    FHIR_EXTRACTION_PROMPT = """Extract data from the medical document exactly as written, without assessing its correctness, completeness, or medical validity.
    Output Format: Return the extracted data as a valid, complete JSON object with no additional text before or after..."""
    
    @classmethod
    def get_system_prompt(cls, prompt_type='base', context_tags=None):
        """Get system prompt with optional context"""
        prompt = cls.BASE_SYSTEM_PROMPT
        
        if context_tags:
            tags_text = "Context: " + ", ".join([tag["text"] for tag in context_tags])
            prompt = f"{prompt}\n\n{tags_text}"
            
        return prompt
```

### 2. Multi-Strategy Response Parsing

**Location**: `apps/documents/services/response_parser.py`

```python
class ResponseParser:
    """Multi-fallback JSON parsing strategies from Flask example"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def extract_structured_data(self, text_content):
        """Extract structured data using multiple fallback strategies"""
        
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
```

### 3. Document Chunking Algorithm

**Location**: `apps/documents/services/chunking.py`

```python
class DocumentChunker:
    """Large document chunking strategy from Flask example"""
    
    def __init__(self, chunk_size=120000, token_threshold=150000):
        self.chunk_size = chunk_size  # characters
        self.token_threshold = token_threshold  # estimated tokens
        
    def should_chunk_document(self, content):
        """Determine if document needs chunking"""
        estimated_tokens = len(content) / 4  # 4 chars per token estimate
        return estimated_tokens > self.token_threshold
    
    def chunk_document(self, content):
        """Split document into logical chunks"""
        if not self.should_chunk_document(content):
            return [content]
        
        # Try to split by multiple newlines (section breaks)
        sections = re.split(r'\n\s*\n\s*\n', content)
        
        # If sections too large, split by double newlines
        if max(len(s) for s in sections) > self.chunk_size:
            temp_sections = []
            for section in sections:
                if len(section) > self.chunk_size:
                    subsections = re.split(r'\n\s*\n', section)
                    temp_sections.extend(subsections)
                else:
                    temp_sections.append(section)
            sections = temp_sections
        
        # Final processing to ensure no chunk exceeds limit
        final_chunks = self._process_oversized_chunks(sections)
        return self._combine_chunks_optimally(final_chunks)
```

### 4. Error Handling & Retry Logic

**Location**: `apps/documents/services/error_handling.py`

```python
import backoff
from anthropic import APIConnectionError, APIError

class AIServiceErrorHandler:
    """Comprehensive error handling from Flask patterns"""
    
    @backoff.on_exception(backoff.expo, APIConnectionError, max_tries=3)
    def call_ai_with_retry(self, client, **kwargs):
        """Call AI API with exponential backoff retry"""
        try:
            return client.messages.create(**kwargs)
        except APIConnectionError as conn_err:
            self.logger.error(f"Connection error to Anthropic API: {conn_err}")
            raise
        except APIError as api_err:
            self.logger.error(f"API error: {api_err}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected AI API error: {e}")
            raise
    
    def handle_processing_error(self, document, error, task_instance=None):
        """Handle document processing errors with appropriate user feedback"""
        document.status = 'failed'
        document.error_message = self._get_user_friendly_error(error)
        document.save()
        
        if task_instance:
            # Retry logic for Celery tasks
            if isinstance(error, APIConnectionError):
                # Network issues - retry with longer delay
                raise task_instance.retry(exc=error, countdown=600, max_retries=5)
            elif isinstance(error, APIError):
                # API issues - shorter retry
                raise task_instance.retry(exc=error, countdown=300, max_retries=3)
            else:
                # Other errors - don't retry
                raise error
```

### 5. Cost Tracking & Token Management

**Location**: `apps/documents/models.py` (addition)

```python
class APIUsageLog(models.Model):
    """Track AI API usage and costs"""
    document = models.ForeignKey(Document, on_delete=models.CASCADE, null=True)
    model = models.CharField(max_length=50)
    input_tokens = models.IntegerField()
    output_tokens = models.IntegerField()
    total_tokens = models.IntegerField()
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=6)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'api_usage_logs'
```

**Service**: `apps/documents/services/cost_tracking.py`

```python
class CostTracker:
    """Track and manage AI API costs"""
    
    TOKEN_COSTS = {
        'claude-3-sonnet-20240229': {'input': 0.000003, 'output': 0.000015},
        'claude-3-opus-20240229': {'input': 0.000015, 'output': 0.000075},
        'gpt-3.5-turbo': {'input': 0.0000015, 'output': 0.000002},
    }
    
    def calculate_cost(self, model, input_tokens, output_tokens):
        """Calculate estimated cost for API usage"""
        if model not in self.TOKEN_COSTS:
            return 0.0
        
        costs = self.TOKEN_COSTS[model]
        return (input_tokens * costs['input']) + (output_tokens * costs['output'])
    
    def log_usage(self, document, model, usage_data):
        """Log API usage for cost tracking"""
        cost = self.calculate_cost(
            model, 
            usage_data['input_tokens'], 
            usage_data['output_tokens']
        )
        
        APIUsageLog.objects.create(
            document=document,
            model=model,
            input_tokens=usage_data['input_tokens'],
            output_tokens=usage_data['output_tokens'],
            total_tokens=usage_data['input_tokens'] + usage_data['output_tokens'],
            estimated_cost=cost
        )
        
        return cost
```

## Settings Configuration

**Add to `meddocparser/settings/base.py`**:

```python
# AI Processing Settings
ANTHROPIC_API_KEY = config('ANTHROPIC_API_KEY')
OPENAI_API_KEY = config('OPENAI_API_KEY', default=None)

# AI Model Configuration
AI_MODEL_PRIMARY = config('AI_MODEL_PRIMARY', default='claude-3-sonnet-20240229')
AI_MODEL_FALLBACK = config('AI_MODEL_FALLBACK', default='gpt-3.5-turbo')

# Token Limits and Cost Controls
AI_MAX_TOKENS_PER_REQUEST = config('AI_MAX_TOKENS_PER_REQUEST', default=4096, cast=int)
AI_TOKEN_THRESHOLD_FOR_CHUNKING = config('AI_TOKEN_THRESHOLD_FOR_CHUNKING', default=150000, cast=int)
AI_DAILY_COST_LIMIT = config('AI_DAILY_COST_LIMIT', default=100.00, cast=float)

# Request Timeouts
AI_REQUEST_TIMEOUT = config('AI_REQUEST_TIMEOUT', default=60, cast=int)
AI_MAX_RETRIES = config('AI_MAX_RETRIES', default=3, cast=int)
```

## Integration Points

### 1. Document Model Updates

```python
# apps/documents/models.py additions
class Document(BaseModel):
    # ... existing fields ...
    
    # AI Processing fields
    ai_processing_started_at = models.DateTimeField(null=True, blank=True)
    ai_processing_completed_at = models.DateTimeField(null=True, blank=True)
    ai_model_used = models.CharField(max_length=50, blank=True)
    ai_tokens_used = models.IntegerField(default=0)
    ai_estimated_cost = models.DecimalField(max_digits=10, decimal_places=6, default=0.00)
    
    def start_ai_processing(self):
        """Mark AI processing as started"""
        self.ai_processing_started_at = timezone.now()
        self.status = 'processing'
        self.save(update_fields=['ai_processing_started_at', 'status'])
```

### 2. Celery Task Integration

**Update `apps/documents/tasks.py`**:

```python
from .services.ai_analyzer import DocumentAnalyzer
from .services.cost_tracking import CostTracker

@shared_task(bind=True)
def process_document_with_ai(self, document_id):
    """Enhanced document processing with Flask patterns"""
    document = Document.objects.get(id=document_id)
    document.start_ai_processing()
    
    try:
        analyzer = DocumentAnalyzer()
        cost_tracker = CostTracker()
        
        result = analyzer.analyze_document(document.original_text)
        
        if result['success']:
            # Track costs
            cost = cost_tracker.log_usage(
                document, 
                analyzer.model, 
                result['usage']
            )
            
            # Update document
            document.ai_processing_completed_at = timezone.now()
            document.ai_model_used = analyzer.model
            document.ai_tokens_used = result['usage']['input_tokens'] + result['usage']['output_tokens']
            document.ai_estimated_cost = cost
            document.status = 'completed'
            
            # Store results
            ParsedData.objects.create(
                document=document,
                patient=document.patient,
                extraction_json=result['fields'],
                fhir_delta_json=analyzer.convert_to_fhir(result['fields'])
            )
        else:
            document.status = 'failed'
            document.error_message = result.get('error')
            
        document.save()
        return result
        
    except Exception as exc:
        # Use error handler for consistent error management
        error_handler = AIServiceErrorHandler()
        error_handler.handle_processing_error(document, exc, self)
```

## Testing Strategy

### 1. Unit Tests for Services

```python
# apps/documents/tests/test_ai_analyzer.py
class DocumentAnalyzerTests(TestCase):
    def setUp(self):
        self.analyzer = DocumentAnalyzer()
        self.sample_text = "Sample medical document content..."
    
    @patch('anthropic.Client.messages.create')
    def test_successful_analysis(self, mock_create):
        # Test successful document analysis
        pass
    
    def test_chunking_decision(self):
        # Test document chunking logic
        pass
    
    def test_response_parsing_fallbacks(self):
        # Test all 5 parsing strategies
        pass
```

### 2. Integration Tests

```python
# apps/documents/tests/test_integration.py
class AIProcessingIntegrationTests(TestCase):
    def test_complete_document_processing_workflow(self):
        # Test end-to-end processing
        pass
    
    def test_cost_tracking_accuracy(self):
        # Test cost calculation and logging
        pass
```

## Performance Monitoring

### 1. Metrics to Track

- Processing time per document
- Token usage and costs
- Success/failure rates
- Chunking frequency
- Parsing strategy success rates

### 2. Logging Configuration

```python
# Enhanced logging for AI processing
LOGGING = {
    'loggers': {
        'apps.documents.services': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
        'ai_processing': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': True,
        },
    }
}
```

---

**Next Steps**: 
1. Implement each service class following these patterns
2. Create comprehensive tests
3. Set up monitoring and cost tracking
4. Integrate with existing Celery task system

**Reference**: See `example_parser.md` for original Flask implementation details. 