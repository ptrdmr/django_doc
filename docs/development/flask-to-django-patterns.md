# 🔄 Flask to Django Translation Patterns

## Overview

This guide shows how to translate common Flask patterns used in the successful `example_parser.md` to Django equivalents, maintaining the same functionality while following Django best practices.

## Core Pattern Translations

### 1. Class-Based Services

**Flask Pattern**:
```python
# example_parser.md
class DocumentAnalyzer:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
        # ... initialization
    
    def analyze_document(self, document_content, system_prompt=None):
        # ... method implementation
```

**Django Equivalent**:
```python
# apps/documents/services/ai_analyzer.py
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

class DocumentAnalyzer:
    def __init__(self, api_key=None):
        self.api_key = api_key or getattr(settings, 'ANTHROPIC_API_KEY', None)
        if not self.api_key:
            raise ImproperlyConfigured("ANTHROPIC_API_KEY must be configured in Django settings")
        # ... initialization
    
    def analyze_document(self, document_content, system_prompt=None):
        # ... method implementation
```

**Key Changes**:
- `os.getenv()` → `settings.ANTHROPIC_API_KEY`
- Environment variables → Django settings
- Generic exceptions → Django-specific exceptions

### 2. Error Handling Patterns

**Flask Pattern**:
```python
try:
    response = self.client.messages.create(...)
    return {"success": True, "data": response}
except anthropic.APIConnectionError as conn_err:
    logger.error(f"Connection error: {conn_err}")
    return {"success": False, "error": "Connection error"}
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    return {"success": False, "error": str(e)}
```

**Django Equivalent**:
```python
from django.core.exceptions import ValidationError
from django.db import transaction
import logging

logger = logging.getLogger(__name__)

try:
    with transaction.atomic():
        response = self.client.messages.create(...)
        return {"success": True, "data": response}
except anthropic.APIConnectionError as conn_err:
    logger.error(f"Connection error: {conn_err}", exc_info=True)
    raise ValidationError("Unable to connect to AI service. Please try again.")
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    raise ValidationError(f"Processing failed: {str(e)}")
```

**Key Changes**:
- Dictionary return values → Django exceptions
- Generic error handling → Specific Django exception types
- Added database transaction safety
- Enhanced logging with `exc_info=True`

### 3. File Handling

**Flask Pattern**:
```python
@app.route('/api/analyze', methods=['POST'])
def analyze_document():
    file = request.files['file']
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as temp_file:
        file.save(temp_file.name)
        # ... process file
        os.unlink(temp_file.name)
```

**Django Equivalent**:
```python
# apps/documents/views.py
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import tempfile
import os

class DocumentUploadView(LoginRequiredMixin, CreateView):
    def form_valid(self, form):
        uploaded_file = form.cleaned_data['file']
        
        # Store file properly in Django
        file_name = default_storage.save(
            f'documents/{uploaded_file.name}',
            ContentFile(uploaded_file.read())
        )
        
        try:
            # Process the file
            file_path = default_storage.path(file_name)
            # ... process file
        finally:
            # Clean up
            default_storage.delete(file_name)
```

**Key Changes**:
- Flask file handling → Django file storage
- Manual temp files → Django's file storage system
- Direct file access → Django storage abstraction

### 4. Configuration Management

**Flask Pattern**:
```python
# Direct environment variable access
api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
model = os.getenv("AI_MODEL", "claude-3-sonnet-20240229")
```

**Django Equivalent**:
```python
# settings/base.py
from decouple import config

ANTHROPIC_API_KEY = config('ANTHROPIC_API_KEY')
AI_MODEL_PRIMARY = config('AI_MODEL_PRIMARY', default='claude-3-sonnet-20240229')

# apps/documents/services/config.py
from django.conf import settings

class AIConfig:
    @classmethod
    def get_api_key(cls):
        return settings.ANTHROPIC_API_KEY
    
    @classmethod
    def get_primary_model(cls):
        return getattr(settings, 'AI_MODEL_PRIMARY', 'claude-3-sonnet-20240229')
```

**Key Changes**:
- Direct env access → Django settings system
- Scattered config → Centralized configuration
- Runtime config → Settings-based config

### 5. Logging Patterns

**Flask Pattern**:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

logger.info(f"Document content length: {doc_length} characters")
```

**Django Equivalent**:
```python
# settings/base.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'logs/ai_processing.log',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'apps.documents.services': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}

# In your service
import logging
logger = logging.getLogger(__name__)

logger.info("Document content length: %d characters", doc_length, 
           extra={'document_id': document.id, 'user_id': user.id})
```

**Key Changes**:
- Basic logging → Django logging configuration
- Simple log messages → Structured logging with context
- No log formatting → Comprehensive formatter setup

### 6. Request/Response Patterns

**Flask Pattern**:
```python
@app.route('/api/analyze', methods=['POST'])
def analyze_document():
    return jsonify({
        "success": True,
        "fields": parsed_fields,
        "usage": usage_data
    })
```

**Django Equivalent**:
```python
# apps/documents/views.py
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

@method_decorator(csrf_exempt, name='dispatch')
class DocumentAnalysisAPIView(View):
    def post(self, request):
        try:
            # ... processing logic
            return JsonResponse({
                "success": True,
                "fields": parsed_fields,
                "usage": usage_data
            })
        except ValidationError as e:
            return JsonResponse({
                "success": False,
                "errors": e.messages
            }, status=400)
```

**Key Changes**:
- Flask routes → Django views
- `jsonify()` → `JsonResponse()`
- Route decorators → Django view decorators

### 7. Database Integration

**Flask Pattern** (if it existed):
```python
# Would be something like:
# db.session.add(record)
# db.session.commit()
```

**Django Pattern**:
```python
# apps/documents/models.py
from django.db import models, transaction
from apps.core.models import BaseModel

class ParsedData(BaseModel):
    document = models.ForeignKey('Document', on_delete=models.CASCADE)
    extraction_json = models.JSONField()
    fhir_delta_json = models.JSONField()
    confidence_score = models.FloatField()

# In service
@transaction.atomic
def save_extraction_results(self, document, extraction_data):
    parsed_data = ParsedData.objects.create(
        document=document,
        extraction_json=extraction_data['fields'],
        fhir_delta_json=self.convert_to_fhir(extraction_data['fields']),
        confidence_score=self.calculate_avg_confidence(extraction_data['fields'])
    )
    return parsed_data
```

**Key Changes**:
- No database in Flask → Django ORM
- Manual SQL → Model-based operations
- No transactions → Atomic transactions

### 8. Background Processing

**Flask Pattern**:
```python
# Synchronous processing in Flask
def analyze_document():
    result = analyzer.analyze_document(content)  # Blocks request
    return jsonify(result)
```

**Django Pattern**:
```python
# apps/documents/tasks.py
from celery import shared_task

@shared_task(bind=True)
def process_document_async(self, document_id):
    """Asynchronous document processing"""
    document = Document.objects.get(id=document_id)
    analyzer = DocumentAnalyzer()
    
    try:
        result = analyzer.analyze_document(document.original_text)
        # ... handle result
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60, max_retries=3)

# In view
def upload_document(request):
    document = Document.objects.create(...)
    process_document_async.delay(document.id)  # Non-blocking
    return JsonResponse({"status": "processing", "document_id": document.id})
```

**Key Changes**:
- Synchronous processing → Asynchronous with Celery
- Request blocking → Immediate response with status
- No retry logic → Built-in Celery retry

### 9. Testing Patterns

**Flask Pattern**:
```python
import unittest
from app import app

class TestDocumentAnalysis(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
    
    def test_analyze_endpoint(self):
        response = self.app.post('/api/analyze', data={'file': file_data})
        self.assertEqual(response.status_code, 200)
```

**Django Pattern**:
```python
# apps/documents/tests.py
from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from .models import Document

class DocumentAnalysisTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('testuser', 'test@example.com', 'pass')
        self.client.login(username='testuser', password='pass')
    
    def test_document_upload_and_processing(self):
        file_content = b"Sample medical document content"
        uploaded_file = SimpleUploadedFile("test.txt", file_content, content_type="text/plain")
        
        response = self.client.post('/documents/upload/', {'file': uploaded_file})
        self.assertEqual(response.status_code, 302)  # Redirect after successful upload
        
        # Verify document was created
        self.assertTrue(Document.objects.filter(uploaded_by=self.user).exists())
```

**Key Changes**:
- `unittest` → Django `TestCase`
- Flask test client → Django test client
- Manual data setup → Django fixtures and ORM

### 10. Service Layer Architecture

**Flask Pattern**:
```python
# Everything in app.py or minimal organization
class DocumentAnalyzer:
    def __init__(self):
        # ... setup
    
    def analyze_document(self):
        # ... all logic here
```

**Django Pattern**:
```python
# Organized service layer
# apps/documents/services/__init__.py
from .ai_analyzer import DocumentAnalyzer
from .response_parser import ResponseParser
from .chunking import DocumentChunker
from .cost_tracking import CostTracker

# apps/documents/services/base.py
class BaseService:
    """Base service class with common functionality"""
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__module__)

# apps/documents/services/ai_analyzer.py
class DocumentAnalyzer(BaseService):
    def __init__(self):
        super().__init__()
        self.parser = ResponseParser()
        self.chunker = DocumentChunker()
        self.cost_tracker = CostTracker()
```

**Key Changes**:
- Monolithic structure → Organized service layer
- Single file → Multiple specialized services
- No inheritance → Base service class with common functionality

## Common Gotchas & Solutions

### 1. Path Handling

**Problem**: Flask uses simple file paths, Django has complex media handling
```python
# ❌ Don't do this in Django
file_path = f"/uploads/{filename}"
```

**Solution**: Use Django storage system
```python
# ✅ Do this instead
from django.core.files.storage import default_storage
file_path = default_storage.path(filename)
```

### 2. Settings Access

**Problem**: Direct environment variable access
```python
# ❌ Don't do this in Django
api_key = os.getenv("API_KEY")
```

**Solution**: Use Django settings
```python
# ✅ Do this instead
from django.conf import settings
api_key = settings.API_KEY
```

### 3. Error Handling

**Problem**: Returning error dictionaries
```python
# ❌ Flask style
return {"success": False, "error": "Something went wrong"}
```

**Solution**: Raise Django exceptions
```python
# ✅ Django style
from django.core.exceptions import ValidationError
raise ValidationError("Something went wrong")
```

### 4. Database Transactions

**Problem**: No transaction management
```python
# ❌ No transaction safety
record.save()
other_record.save()  # If this fails, first save is still committed
```

**Solution**: Use atomic transactions
```python
# ✅ Transaction safety
from django.db import transaction

@transaction.atomic
def save_multiple_records():
    record.save()
    other_record.save()  # If this fails, both operations are rolled back
```

## Migration Checklist

When converting Flask patterns to Django:

- [ ] Replace `os.getenv()` with Django settings
- [ ] Convert route functions to Django views
- [ ] Replace direct file handling with Django storage
- [ ] Add proper error handling with Django exceptions
- [ ] Implement database models and ORM usage
- [ ] Set up proper logging configuration
- [ ] Add background task processing with Celery
- [ ] Create comprehensive test suite
- [ ] Organize code into proper service layer
- [ ] Add proper authentication and permissions

## Next Steps

1. Use this guide when implementing each Flask pattern from `example_parser.md`
2. Test each pattern thoroughly in Django context
3. Add Django-specific optimizations (caching, database optimization, etc.)
4. Follow Django security best practices

---

**Remember**: The goal is to maintain the proven functionality of the Flask example while gaining the benefits of Django's robust framework and ecosystem. 