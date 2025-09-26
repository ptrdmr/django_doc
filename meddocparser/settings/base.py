"""
Base Django settings for meddocparser project.
Common settings that apply to all environments.
"""

import os
from pathlib import Path
from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='django-insecure-1_cetv@zjka1+ol0=k%()s&%l96s1bhd1y%k(!4j_!we9lbgi*')

# Application definition
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',  # Required for django-allauth
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'drf_spectacular',  # API documentation
    'django_htmx',
    'corsheaders',
    'django_extensions',
    'django_celery_beat',  # For Celery beat scheduler
    # Frontend & UI
    'tailwind',
    'theme',  # Our Tailwind theme app
    # Authentication & Security
    'allauth',
    'allauth.account',
    'django_otp',
    'axes',  # Failed login monitoring
    'django_cryptography',  # Field-level encryption for PHI
    # Development & monitoring
    'debug_toolbar',  # Development only
]

LOCAL_APPS = [
    'apps.accounts',
    'apps.core',
    'apps.documents',
    'apps.patients',
    'apps.providers',
    'apps.fhir',
    'apps.reports',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# Note: Encryption configuration removed for now
# TODO: Add field-level encryption in future iterations

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'apps.core.middleware.SecurityHeadersMiddleware',  # Custom security headers & CSP
    'apps.core.middleware.RateLimitingMiddleware',     # Rate limiting for security
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',    # Allauth middleware
    'axes.middleware.AxesMiddleware',                   # Failed login monitoring
    'apps.documents.middleware.StructuredDataValidationMiddleware',  # Document validation middleware
    'apps.core.middleware.AuditLoggingMiddleware',     # HIPAA audit logging
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
    'debug_toolbar.middleware.DebugToolbarMiddleware',  # Development only
]

ROOT_URLCONF = 'meddocparser.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'meddocparser.wsgi.application'

# Password validation - Enhanced for HIPAA compliance
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 12,  # Enhanced for HIPAA compliance
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
    # Custom HIPAA-compliant validators
    {
        'NAME': 'apps.core.validators.SpecialCharacterValidator',
    },
    {
        'NAME': 'apps.core.validators.UppercaseValidator',
    },
    {
        'NAME': 'apps.core.validators.LowercaseValidator',
    },
    {
        'NAME': 'apps.core.validators.NoSequentialCharactersValidator',
    },
    {
        'NAME': 'apps.core.validators.NoRepeatingCharactersValidator',
        'OPTIONS': {
            'max_repeating': 3,
        }
    },
    {
        'NAME': 'apps.core.validators.NoPersonalInfoValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/New_York'  # Adjust based on your primary location
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Site ID for django-allauth
SITE_ID = 1

# ============================================================================
# HIPAA COMPLIANCE SECURITY SETTINGS
# ============================================================================

# SSL/TLS Security
SECURE_SSL_REDIRECT = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# Session Security for HIPAA
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 3600  # 1 hour timeout
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_SAMESITE = 'Strict'

# CSRF Protection
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Strict'
CSRF_USE_SESSIONS = True

# Additional Security Headers
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# File Upload Security
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB max in memory
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB max total
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000
FILE_UPLOAD_PERMISSIONS = 0o644

# Allowed file types for medical documents
ALLOWED_DOCUMENT_TYPES = [
    'application/pdf',
    'image/jpeg',
    'image/png',
    'image/tiff',
    'text/plain',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
]

# Maximum file size for uploads (50MB for medical documents)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

# ============================================================================
# HIPAA AUDIT LOGGING CONFIGURATION
# ============================================================================

# PHI Access Tracking
AUDIT_LOG_ENABLED = True
AUDIT_LOG_DB_TABLE = 'audit_logs'
AUDIT_LOG_RETENTION_DAYS = 2555  # 7 years as per HIPAA requirements

# User Activity Monitoring
TRACK_USER_ACTIVITY = True
FAILED_LOGIN_ATTEMPTS_LIMIT = 5
ACCOUNT_LOCKOUT_DURATION = 30  # minutes

# Data Retention Policies
DOCUMENT_RETENTION_DAYS = 2555  # 7 years for medical records
AUDIT_LOG_RETENTION_DAYS = 2555  # 7 years for audit logs
TEMP_FILE_CLEANUP_HOURS = 24  # Clean temporary files after 24 hours

# ============================================================================
# DJANGO-AXES CONFIGURATION (Failed Login Monitoring)
# ============================================================================

AXES_ENABLED = True
AXES_FAILURE_LIMIT = 5  # Lock after 5 failed attempts
AXES_COOLOFF_TIME = 1  # 1 hour lockout
AXES_LOCKOUT_TEMPLATE = 'accounts/lockout.html'
AXES_LOCKOUT_URL = '/accounts/lockout/'
AXES_RESET_ON_SUCCESS = True

# ============================================================================
# DJANGO-ALLAUTH CONFIGURATION (Enhanced Authentication)
# ============================================================================

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
    'axes.backends.AxesBackend',  # Failed login monitoring
]

# Allauth settings for HIPAA compliance
ACCOUNT_AUTHENTICATION_METHOD = 'email'
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_EMAIL_VERIFICATION = 'mandatory'
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True
ACCOUNT_SESSION_REMEMBER = None  # Disable remember me
ACCOUNT_PASSWORD_MIN_LENGTH = 12
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = False  # Require manual login after confirmation
ACCOUNT_PREVENT_ENUMERATION = True  # Don't reveal if email exists
ACCOUNT_LOGOUT_REDIRECT_URL = '/accounts/login/'  # Redirect after logout
LOGIN_REDIRECT_URL = '/dashboard/'  # Redirect after successful login
LOGOUT_REDIRECT_URL = '/accounts/login/'  # Redirect after logout

# Rate limiting for failed login attempts (new format)
ACCOUNT_RATE_LIMITS = {
    'login_failed': '5/5m',  # 5 attempts per 5 minutes
}

# Email settings for account verification
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'  # Development only
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@meddocparser.com')

# ============================================================================
# DJANGO-OTP CONFIGURATION (Two-Factor Authentication)
# ============================================================================

OTP_TOTP_ISSUER = 'Medical Document Parser'
OTP_LOGIN_URL = '/accounts/login/'

# ============================================================================
# RATE LIMITING CONFIGURATION
# ============================================================================

# API rate limiting for HIPAA compliance - disabled for development
# RATELIMIT_ENABLE = True
# RATELIMIT_USE_CACHE = 'default'
# RATELIMIT_VIEW = 'core.views.ratelimited'

# ============================================================================
# ENCRYPTION CONFIGURATION
# ============================================================================

# Field-level encryption for PHI using django-cryptography
# IMPORTANT: These keys should be stored securely and not committed to version control
# Generate a new key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FIELD_ENCRYPTION_KEYS = [
    # Primary encryption key - should be loaded from environment variable
    config(
        'FIELD_ENCRYPTION_KEY',
        default='gAAAAABhZ2J3X4K5l9m8n7o6p5q4r3s2t1u0v9w8x7y6z5A4B3C2D1E0F9G8H7I6J5K4L3M2N1O0P9Q8R7S6T5U4V3W2X1Y0Z9='  # Default for development only
    ),
]

# Argon2 password hashing (HIPAA-compliant)
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

# ============================================================================
# CELERY CONFIGURATION
# ============================================================================

# Redis Configuration
REDIS_URL = config('REDIS_URL', default='redis://localhost:6379/0')

# Celery Settings
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL

# Celery JSON serialization (safer for medical data)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'

# Celery timezone configuration
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True

# Task result expiration
CELERY_RESULT_EXPIRES = 3600  # 1 hour

# Task routing for different queues
CELERY_TASK_ROUTES = {
    'apps.documents.tasks.*': {'queue': 'document_processing'},
    'apps.fhir.tasks.*': {'queue': 'fhir_processing'},
    'apps.core.tasks.*': {'queue': 'general'},
}

# Celery beat schedule (for periodic tasks)
CELERY_BEAT_SCHEDULE = {
    # Example: Clean up old processed documents every day at midnight
    'cleanup-old-documents': {
        'task': 'apps.documents.tasks.cleanup_old_documents',
        'schedule': 3600.0 * 24,  # Every 24 hours
    },
}

# Worker configuration for medical document processing
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # Process one task at a time
CELERY_WORKER_MAX_TASKS_PER_CHILD = 50  # Restart worker after 50 tasks

# Task time limits (medical documents can be large)
CELERY_TASK_TIME_LIMIT = 600  # 10 minutes
CELERY_TASK_SOFT_TIME_LIMIT = 540  # 9 minutes

# Cache backend configuration - using Redis for performance and persistence
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'TIMEOUT': 3600,  # 1 hour default timeout for AI extraction results
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'SERIALIZER': 'django_redis.serializers.json.JSONSerializer',
            'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 20,
                'retry_on_timeout': True,
            }
        },
        'KEY_PREFIX': 'meddocparser',
        'VERSION': 1,
    },
    # Separate cache for AI extraction results with longer timeout
    'ai_extraction': {
        'BACKEND': 'django_redis.cache.RedisCache', 
        'LOCATION': REDIS_URL + '/1',  # Use database 1 for AI cache
        'TIMEOUT': 86400,  # 24 hours for AI extraction results
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'SERIALIZER': 'django_redis.serializers.json.JSONSerializer',
            'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
        },
        'KEY_PREFIX': 'ai_extract',
        'VERSION': 1,
    }
}

# Use database sessions for development (more reliable than cache sessions)
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# ============================================================================
# END CELERY CONFIGURATION
# ============================================================================

# Logging Configuration for HIPAA Audit Trail
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
            'filename': BASE_DIR / 'logs' / 'meddocparser.log',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': False,
        },
        'meddocparser': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': False,
        },
        'celery': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# ============================================================================
# AI PROCESSING CONFIGURATION
# ============================================================================

# AI API Keys and Model Configuration
ANTHROPIC_API_KEY = config('ANTHROPIC_API_KEY', default=None)
OPENAI_API_KEY = config('OPENAI_API_KEY', default=None)

# AI Model Configuration  
AI_MODEL_PRIMARY = config('AI_MODEL_PRIMARY', default='claude-3-5-sonnet-20240620')
AI_MODEL_FALLBACK = config('AI_MODEL_FALLBACK', default='gpt-4o-mini')

# Token Limits and Cost Controls
AI_MAX_TOKENS_PER_REQUEST = config('AI_MAX_TOKENS_PER_REQUEST', default=8192, cast=int)
AI_TOKEN_THRESHOLD_FOR_CHUNKING = config('AI_TOKEN_THRESHOLD_FOR_CHUNKING', default=20000, cast=int)  # Lower threshold for better chunking
AI_DAILY_COST_LIMIT = config('AI_DAILY_COST_LIMIT', default=100.00, cast=float)

# Request Timeouts and Retry Configuration
AI_REQUEST_TIMEOUT = config('AI_REQUEST_TIMEOUT', default=60, cast=int)
AI_MAX_RETRIES = config('AI_MAX_RETRIES', default=3, cast=int)

# Document Processing Settings
AI_CHUNK_SIZE = config('AI_CHUNK_SIZE', default=15000, cast=int)  # Characters per chunk - more manageable size
AI_CHUNK_OVERLAP = config('AI_CHUNK_OVERLAP', default=2000, cast=int)  # Overlap for context

# FHIR Processing Configuration
FHIR_VALIDATION_ENABLED = config('FHIR_VALIDATION_ENABLED', default=True, cast=bool)
FHIR_STRICT_MODE = config('FHIR_STRICT_MODE', default=False, cast=bool)

# ============================================================================
# REST FRAMEWORK CONFIGURATION
# ============================================================================

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',  # Anonymous users
        'user': '1000/hour'  # Authenticated users
    }
}

# ============================================================================
# DRF-SPECTACULAR CONFIGURATION (API Documentation)
# ============================================================================

SPECTACULAR_SETTINGS = {
    'TITLE': 'Medical Document Parser API',
    'DESCRIPTION': 'HIPAA-compliant medical document processing and FHIR conversion API',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SCHEMA_PATH_PREFIX': '/api/',
}

# ============================================================================
# TAILWIND CSS CONFIGURATION
# ============================================================================

# Tailwind configuration for medical UI
TAILWIND_APP_NAME = 'theme'

# Node.js and npm paths for Tailwind (explicit paths for Windows)
NPM_BIN_PATH = config('NPM_BIN_PATH', default='C:/Users/Peter/AppData/Roaming/npm/npm.cmd')
NODE_PATH = config('NODE_PATH', default='C:/Program Files/nodejs/node.exe')

# Internal IPs for development (allows Tailwind to work)
INTERNAL_IPS = [
    '127.0.0.1',
    'localhost',
] 