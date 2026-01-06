"""
Development settings for meddocparser project.
These settings are optimized for local development and testing.
"""

from .base import *
from decouple import config

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# ALLOWED_HOSTS from environment variable (supports comma-separated list)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,0.0.0.0').split(',')

# Add ngrok hostname from environment variable for development
NGROK_HOSTNAME = config('NGROK_HOSTNAME', default=None)
if NGROK_HOSTNAME:
    ALLOWED_HOSTS.append(NGROK_HOSTNAME)
    # Also allow the ngrok.pizza domain if that's what's being used
    if 'ngrok.pizza' in NGROK_HOSTNAME:
        ALLOWED_HOSTS.append('.ngrok.pizza')


# Database Configuration - ALWAYS use PostgreSQL for this medical application
# PostgreSQL is required for JSONB support and HIPAA compliance
# SQLite is NOT suitable for production medical data
db_engine = config('DB_ENGINE', default='postgresql')

if db_engine == 'postgresql':
    # PostgreSQL for JSONB functionality and production-like development
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME', default='meddocparser_dev'),
            'USER': config('DB_USER', default='postgres'),
            'PASSWORD': config('DB_PASSWORD', default='password'),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default='5432'),
            'OPTIONS': {
                # No SSL requirement for development
                'sslmode': 'prefer',
            },
            'CONN_MAX_AGE': 60,
        }
    }
    print("💾 Using PostgreSQL database for development")
else:
    # SQLite fallback (NOT RECOMMENDED for medical data)
    # Only use for quick testing of non-medical features
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
    print("⚠️  WARNING: Using SQLite database (NOT suitable for medical data or JSONB features)")

# Development-friendly security settings (less strict)
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0

# CORS settings for development
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

# Email backend for development (console output)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Django Extensions (helpful for development)
if 'django_extensions' in INSTALLED_APPS:
    SHELL_PLUS_PRINT_SQL = True

# Development logging - more verbose
LOGGING['handlers']['console'] = {
    'level': 'DEBUG',
    'class': 'logging.StreamHandler',
    'formatter': 'verbose',
}

LOGGING['root']['handlers'].append('console')
LOGGING['loggers']['django']['handlers'].append('console')
LOGGING['loggers']['meddocparser']['handlers'].append('console')

# Cache - use Redis cache from base.py (needed for django-ratelimit)
# Note: DummyCache doesn't work with django-ratelimit, so we use the Redis cache from base.py
# CACHES = {
#     'default': {
#         'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
#     }
# }

# Debug toolbar (uncomment when django-debug-toolbar is installed)
# if DEBUG:
#     INSTALLED_APPS += ['debug_toolbar']
#     MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')
#     INTERNAL_IPS = ['127.0.0.1']

# Celery settings for development (if using Redis locally)
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
# CELERY_TASK_ALWAYS_EAGER = True  # Execute tasks synchronously in development

# Use Redis for Celery in development (needed for async document processing)
# Comment out the lines below to use Redis instead of memory for task queue testing
# CELERY_BROKER_URL = 'memory://'
# CELERY_RESULT_BACKEND = 'cache+memory://'
# CELERY_TASK_ALWAYS_EAGER = True  # Execute tasks synchronously
# CELERY_EAGER_PROPAGATES_EXCEPTIONS = True  # Show exceptions immediately

# JSONB Configuration for PostgreSQL
if db_engine == 'postgresql':
    # Enable JSONB field optimizations
    DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
    
    # Add PostgreSQL-specific logging
    LOGGING['loggers']['django.db.backends'] = {
        'level': 'DEBUG',
        'handlers': ['console'],
        'propagate': False,
    } 

# ============================================================================
# AI PROCESSING CONFIGURATION (Development Overrides)
# ============================================================================
# Use Claude Sonnet 4.5 for robust medical document processing
AI_MODEL_PRIMARY = 'claude-sonnet-4-5-20250929'
AI_MODEL_FALLBACK = 'gpt-4o-mini'
AI_MAX_TOKENS = 4096
AI_CHUNK_THRESHOLD = 1000000 # NUCLEAR: 1M tokens to force no chunking
AI_REQUEST_TIMEOUT = 120 # Longer timeout for local debugging 