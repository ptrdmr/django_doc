"""
Test settings for the document processing pipeline.

This configuration optimizes settings for fast, reliable testing while
maintaining the necessary functionality for comprehensive pipeline testing.
"""

from .base import *

# Test Database Configuration
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
        'OPTIONS': {
            'timeout': 20,
        }
    }
}

# Disable migrations for faster testing
class DisableMigrations:
    def __contains__(self, item):
        return True
    
    def __getitem__(self, item):
        return None

MIGRATION_MODULES = DisableMigrations()

# Cache Configuration for Testing
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    },
    'ai_extraction': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'ai_extraction_test_cache',
    }
}

# Celery Test Configuration
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'

# Security Settings (relaxed for testing)
SECRET_KEY = 'test-secret-key-not-for-production'
DEBUG = True
ALLOWED_HOSTS = ['*']

# Password validation (simplified for testing)
AUTH_PASSWORD_VALIDATORS = []

# Logging Configuration for Testing
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'ERROR',  # Reduce log noise during tests
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'ERROR',
        },
        'documents': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'fhir': {
            'handlers': ['console'],
            'level': 'INFO',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'ERROR',
    },
}

# Media and Static Files for Testing
MEDIA_ROOT = '/tmp/test_media'
STATIC_ROOT = '/tmp/test_static'

# Email Backend for Testing
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# AI Service Configuration for Testing
# These should be mocked in tests, but provide fallbacks
ANTHROPIC_API_KEY = 'test-key-not-real'
OPENAI_API_KEY = 'test-key-not-real'
PERPLEXITY_API_KEY = 'test-key-not-real'

# Test-specific AI settings
AI_EXTRACTION_CACHE_TTL = 1  # Short cache for testing
AI_EXTRACTION_TIMEOUT = 10  # Faster timeout for tests
AI_EXTRACTION_MAX_RETRIES = 1  # Fewer retries for faster tests

# Performance Testing Configuration
PERFORMANCE_TEST_DOCUMENT_SIZES = [1, 5, 10]  # MB sizes for performance tests
PERFORMANCE_TEST_MAX_TIME_PER_MB = 5  # Max seconds per MB for processing

# Test File Upload Settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024 * 10  # 10MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024 * 10  # 10MB

# Disable external service calls during testing
DOCUMENT_PROCESSING_ENABLE_EXTERNAL_APIS = False

# Test Data Configuration
TEST_DATA_DIR = BASE_DIR / 'test_data'
TEST_FIXTURES_DIR = TEST_DATA_DIR / 'fixtures'
TEST_DOCUMENTS_DIR = TEST_DATA_DIR / 'documents'

# Security Testing Configuration
AUDIT_LOG_ENABLED = True
AUDIT_LOG_SENSITIVE_FIELDS = ['ssn', 'date_of_birth', 'phone']

# FHIR Testing Configuration
FHIR_VALIDATION_ENABLED = True
FHIR_BUNDLE_MAX_RESOURCES = 1000  # Limit for testing

# Frontend Testing Configuration (for Selenium tests)
SELENIUM_WEBDRIVER = 'chrome'  # or 'firefox'
SELENIUM_HEADLESS = True
SELENIUM_IMPLICIT_WAIT = 10
SELENIUM_EXPLICIT_WAIT = 30

# Test Coverage Configuration
COVERAGE_MINIMUM_PERCENT = 80
COVERAGE_EXCLUDE_PATTERNS = [
    '*/migrations/*',
    '*/venv/*',
    '*/test*',
    'manage.py',
    'meddocparser/settings/*',
]

# Test Markers Configuration
PYTEST_MARKERS = {
    'unit': 'Unit tests for individual components',
    'integration': 'Integration tests for component interaction',
    'ui': 'User interface tests with Selenium',
    'performance': 'Performance and load tests',
    'security': 'Security and audit tests',
    'e2e': 'End-to-end workflow tests',
    'slow': 'Tests that take longer than 5 seconds',
    'requires_ai': 'Tests requiring AI service mocking',
    'requires_db': 'Tests requiring database access',
}

# Mock Configuration
MOCK_AI_RESPONSES = True
MOCK_EXTERNAL_APIS = True
MOCK_FILE_UPLOADS = True

# Test Environment Flags
TESTING = True
TESTING_COMPREHENSIVE_PIPELINE = True
