# 🔗 Integration Guide - Putting It All Together

## Overview

This guide shows how to integrate all the Flask-to-Django templates into a cohesive AI document processing system. Follow this sequence to implement the complete solution.

## Implementation Sequence

### Phase 1: Foundation Services (Dependencies)

These services must be created first as they are dependencies for the main DocumentAnalyzer:

1. **Response Parser** (`response_parser_template.py`)
   - Multi-strategy JSON parsing
   - Medical pattern recognition fallback
   - No external dependencies

2. **Document Chunker** (create from Flask patterns)
   - Token-based document splitting
   - Overlap handling for context preservation

3. **Cost Tracker** (create from Flask patterns)
   - API usage logging
   - Token cost calculation

4. **Error Handler** (create from Flask patterns)
   - Retry logic with exponential backoff
   - Service health monitoring

5. **Medical Prompts** (from `ai-prompts-library.md`)
   - System prompts for different extraction types
   - Context enhancement utilities

### Phase 2: Core Service

6. **AI Analyzer** (`ai_analyzer_template.py`)
   - Main document processing orchestrator
   - Integrates all foundation services

### Phase 3: Django Integration

7. **Celery Tasks** (`celery_tasks_template.py`)
   - Async processing workflows
   - Error handling and retries

8. **Django Views** (create using patterns from guide)
   - htmx integration for real-time updates
   - File upload handling

## File Structure After Implementation

```
apps/
├── documents/
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ai_analyzer.py           # Main DocumentAnalyzer class
│   │   ├── response_parser.py       # Multi-strategy parsing
│   │   ├── chunking.py             # Document splitting logic
│   │   ├── cost_tracking.py        # API usage and cost tracking
│   │   ├── error_handling.py       # Retry and error management
│   │   └── prompts.py              # Medical prompt management
│   ├── tasks.py                    # Celery background tasks
│   ├── views.py                    # Django views with htmx
│   └── models.py                   # Updated with AI fields
```

## Step-by-Step Implementation

### Step 1: Create Service Directory

```bash
# Create the services directory structure
mkdir -p apps/documents/services
touch apps/documents/services/__init__.py
```

### Step 2: Implement Foundation Services

Copy and adapt the templates in this order:

```python
# apps/documents/services/response_parser.py
# Use: docs/development/templates/response_parser_template.py
# No modifications needed - copy as-is

# apps/documents/services/chunking.py
# Extract from Flask example_parser.md chunking logic
class DocumentChunker:
    def __init__(self, chunk_size: int = 120000):
        self.chunk_size = chunk_size
    
    def should_chunk_document(self, content: str) -> bool:
        """Check if document needs chunking based on token estimation"""
        estimated_tokens = len(content) / 4
        return estimated_tokens > 150000
    
    def chunk_document(self, content: str) -> List[str]:
        """Split document into overlapping chunks"""
        # Implementation from Flask example
        pass

# apps/documents/services/prompts.py
# Extract from docs/development/ai-prompts-library.md
class MedicalPrompts:
    def get_extraction_prompt(self, fhir_focused: bool = False) -> str:
        """Get appropriate extraction prompt"""
        if fhir_focused:
            return MEDIEXTRACT_FHIR_PROMPT
        return MEDIEXTRACT_SYSTEM_PROMPT
    
    def enhance_prompt(self, base_prompt: str, context_tags: List[Dict]) -> str:
        """Add context tags to prompt"""
        # Implementation here
        pass

# apps/documents/services/cost_tracking.py
class CostTracker:
    def log_usage(self, document, model: str, usage_data: Dict) -> Decimal:
        """Log API usage and calculate costs"""
        # Implementation here
        pass

# apps/documents/services/error_handling.py
class AIServiceErrorHandler:
    def call_ai_with_retry(self, client, **kwargs):
        """Call AI API with retry logic"""
        # Implementation with exponential backoff
        pass
```

### Step 3: Implement Main AI Analyzer

```python
# apps/documents/services/ai_analyzer.py
# Use: docs/development/templates/ai_analyzer_template.py
# Modify import paths to match your Django app structure
```

### Step 4: Update Django Models

Add AI processing fields to your Document model:

```python
# apps/documents/models.py
class Document(BaseModel):
    # ... existing fields ...
    
    # AI Processing Fields
    ai_processing_started_at = models.DateTimeField(null=True, blank=True)
    ai_processing_completed_at = models.DateTimeField(null=True, blank=True)
    ai_model_used = models.CharField(max_length=100, blank=True)
    ai_tokens_used = models.IntegerField(null=True, blank=True)
    ai_estimated_cost = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    
    # Processing Results
    extraction_json = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True)

class ParsedData(BaseModel):
    """Store structured extraction results"""
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='parsed_data')
    patient = models.ForeignKey('patients.Patient', on_delete=models.CASCADE)
    
    extraction_json = models.JSONField(default=list)
    fhir_delta_json = models.JSONField(default=dict)
    confidence_score = models.FloatField(default=0.0)
    processing_method = models.CharField(max_length=50, default='unknown')
    chunks_processed = models.IntegerField(default=1)

class APIUsageLog(models.Model):
    """Track AI API usage for cost management"""
    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    model = models.CharField(max_length=100)
    input_tokens = models.IntegerField()
    output_tokens = models.IntegerField()
    total_tokens = models.IntegerField()
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=6)
    timestamp = models.DateTimeField(auto_now_add=True)
```

### Step 5: Implement Celery Tasks

```python
# apps/documents/tasks.py
# Use: docs/development/templates/celery_tasks_template.py
# Ensure imports match your Django structure
```

### Step 6: Create Django Views

```python
# apps/documents/views.py
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django_htmx import htmx

from .tasks import process_document_with_ai
from .models import Document
from .forms import DocumentUploadForm

@login_required
@htmx.requires_htmx
def upload_document(request):
    """Handle document upload with real-time processing"""
    if request.method == 'POST':
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            document = form.save(commit=False)
            document.uploaded_by = request.user
            document.status = 'pending'
            document.save()
            
            # Start AI processing
            task = process_document_with_ai.delay(
                document_id=document.id,
                context_tags=[{"text": "Emergency Department"}]
            )
            
            return render(request, 'documents/upload_success.html', {
                'document': document,
                'task_id': task.id
            })
    else:
        form = DocumentUploadForm()
    
    return render(request, 'documents/upload_form.html', {
        'form': form
    })

@login_required
def check_processing_status(request, document_id):
    """Check AI processing status via AJAX"""
    document = get_object_or_404(Document, id=document_id)
    
    return JsonResponse({
        'status': document.status,
        'progress': {
            'completed': document.status == 'completed',
            'failed': document.status == 'failed',
            'processing': document.status == 'processing'
        }
    })
```

### Step 7: Configure Settings

```python
# settings/base.py

# AI Configuration
ANTHROPIC_API_KEY = config('ANTHROPIC_API_KEY')
AI_MODEL_PRIMARY = config('AI_MODEL_PRIMARY', default='claude-3-sonnet-20240229')
AI_MAX_TOKENS_PER_REQUEST = config('AI_MAX_TOKENS_PER_REQUEST', default=4096, cast=int)
AI_REQUEST_TIMEOUT = config('AI_REQUEST_TIMEOUT', default=60.0, cast=float)

# Celery Task Routing
CELERY_TASK_ROUTES = {
    'apps.documents.tasks.process_document_with_ai': {'queue': 'ai_processing'},
    'apps.documents.tasks.batch_process_documents': {'queue': 'ai_processing'},
    'apps.documents.tasks.reprocess_failed_documents': {'queue': 'maintenance'},
}

# Worker Configuration for AI Processing
CELERY_TASK_TIME_LIMIT = 1800  # 30 minutes
CELERY_TASK_SOFT_TIME_LIMIT = 1620  # 27 minutes
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # One task at a time
```

## Testing Strategy

### Unit Tests

```python
# tests/test_ai_analyzer.py
from django.test import TestCase
from apps.documents.services.ai_analyzer import DocumentAnalyzer

class DocumentAnalyzerTests(TestCase):
    def setUp(self):
        self.analyzer = DocumentAnalyzer()
    
    def test_analyze_small_document(self):
        """Test processing of small documents"""
        content = "Patient: John Doe, DOB: 01/01/1980, MRN: 12345"
        result = self.analyzer.analyze_document(content)
        
        self.assertTrue(result['success'])
        self.assertGreater(len(result['fields']), 0)
    
    def test_analyze_large_document(self):
        """Test chunking strategy for large documents"""
        content = "A" * 500000  # Large document
        result = self.analyzer.analyze_document(content)
        
        self.assertEqual(result['processing_method'], 'chunked_document')
```

### Integration Tests

```python
# tests/test_processing_workflow.py
from django.test import TestCase
from apps.documents.tasks import process_document_with_ai
from apps.documents.models import Document

class ProcessingWorkflowTests(TestCase):
    def test_end_to_end_processing(self):
        """Test complete document processing workflow"""
        # Create test document
        document = Document.objects.create(
            original_text="Patient: Jane Smith...",
            status='pending'
        )
        
        # Process with AI
        result = process_document_with_ai(document.id)
        
        # Verify results
        document.refresh_from_db()
        self.assertEqual(document.status, 'completed')
        self.assertIsNotNone(document.extraction_json)
```

## Monitoring and Maintenance

### Health Checks

```python
# apps/documents/management/commands/check_ai_health.py
from django.core.management.base import BaseCommand
from apps.documents.services.ai_analyzer import DocumentAnalyzer

class Command(BaseCommand):
    def handle(self, *args, **options):
        """Check AI service health"""
        try:
            analyzer = DocumentAnalyzer()
            # Test with simple content
            result = analyzer.analyze_document("Test document")
            self.stdout.write("AI service is healthy")
        except Exception as e:
            self.stdout.write(f"AI service error: {e}")
```

### Cost Monitoring

```python
# Periodic task to monitor costs
@shared_task
def monitor_daily_costs():
    """Monitor daily AI API costs"""
    from datetime import timedelta
    from django.utils import timezone
    
    today = timezone.now().date()
    daily_cost = APIUsageLog.objects.filter(
        timestamp__date=today
    ).aggregate(
        total_cost=models.Sum('estimated_cost')
    )['total_cost'] or 0
    
    if daily_cost > Decimal('50.00'):  # Alert threshold
        # Send alert notification
        pass
```

## Performance Optimization

### Database Indexes

```python
# Add to your models.py
class Meta:
    indexes = [
        models.Index(fields=['status', 'created_at']),
        models.Index(fields=['ai_processing_started_at']),
        models.Index(fields=['uploaded_by', 'status']),
    ]
```

### Caching Strategy

```python
# Cache frequently accessed prompts
from django.core.cache import cache

class MedicalPrompts:
    def get_extraction_prompt(self, fhir_focused: bool = False) -> str:
        cache_key = f"prompt_extraction_fhir_{fhir_focused}"
        prompt = cache.get(cache_key)
        
        if not prompt:
            prompt = self._load_prompt(fhir_focused)
            cache.set(cache_key, prompt, 3600)  # Cache for 1 hour
        
        return prompt
```

This integration guide provides a complete roadmap for implementing the Flask AI patterns in Django while maintaining the proven functionality and adding Django-specific benefits like async processing, proper error handling, and scalable architecture. 