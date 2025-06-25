"""
Development settings for meddocparser project.
These settings are optimized for local development and testing.
"""

from .base import *
from decouple import config

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0']

# Database Configuration - supports both SQLite and PostgreSQL
# Use environment variable DB_ENGINE to switch between databases
# Default: SQLite for quick development
# Set DB_ENGINE=postgresql to use PostgreSQL with JSONB support
db_engine = config('DB_ENGINE', default='sqlite')

if db_engine == 'postgresql':
    # PostgreSQL for testing JSONB functionality
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
    # SQLite for development simplicity
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
    print("💾 Using SQLite database for development")

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
CELERY_TASK_ALWAYS_EAGER = True  # Execute tasks synchronously in development

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