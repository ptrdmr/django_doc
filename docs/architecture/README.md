# 🏗️ System Architecture

## Overview

The Medical Document Parser follows a modern Django architecture optimized for HIPAA compliance and medical data processing.

## High-Level Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   User Interface│    │   Django Apps   │    │   Data Layer    │
│                 │    │                 │    │                 │
│ • Web UI        │◄──►│ • accounts      │◄──►│ • PostgreSQL    │
│ • REST API      │    │ • patients      │    │ • Redis Cache   │
│ • Admin Portal  │    │ • providers     │    │ • File Storage  │
│                 │    │ • documents     │    │                 │
└─────────────────┘    │ • fhir          │    └─────────────────┘
                       │ • reports       │           │
┌─────────────────┐    │ • core          │           │
│ Background Tasks│◄───┤                 │           │
│                 │    └─────────────────┘           │
│ • Document Proc │                                  │
│ • FHIR Conversion│                                  │
│ • Report Gen    │                                  │
│ • Notifications │                                  │
└─────────────────┘                                  │
         │                                           │
         ▼                                           ▼
┌─────────────────┐                        ┌─────────────────┐
│ External APIs   │                        │ Security Layer  │
│                 │                        │                 │
│ • FHIR Servers  │                        │ • 2FA           │
│ • Email Service │                        │ • Encryption    │
│ • Audit Logging │                        │ • Audit Trails  │
└─────────────────┘                        └─────────────────┘
```

## Component Overview

### Django Applications

- **accounts**: User authentication, profiles, HIPAA-compliant user management
- **core**: Shared utilities, base models, common functionality
- **documents**: Document upload, processing, storage management
- **patients**: Patient data models, FHIR patient resources ✅ **Models Complete**
- **providers**: Healthcare provider management and relationships
- **fhir**: FHIR resource generation and validation
- **reports**: Report generation and analytics

### Authentication System - Task 2 Completed ✅

### Authentication System Implementation
**Complete django-allauth Integration:**
- Email-only authentication (no username) for HIPAA compliance
- Strong password requirements (12+ characters minimum)
- Email verification required for account activation
- No "remember me" functionality for security compliance
- Complete password reset workflow with email verification

**Professional Authentication Templates (7/7):**
- `login.html` - Professional blue medical login with HIPAA notices
- `signup.html` - Green registration with email verification requirements
- `password_reset.html` - Purple password reset request form
- `password_reset_done.html` - Confirmation and next steps guidance
- `password_reset_from_key.html` - Set new password form with validation
- `password_reset_from_key_done.html` - Success confirmation with next actions
- `logout.html` - Red logout confirmation with security reminders

**Security Features:**
- CSRF protection on all forms
- Session security with automatic timeout
- Account lockout after failed login attempts
- HIPAA compliance notices throughout authentication flow
- Audit logging for all authentication events

### Dashboard System - Task 2.5 Completed ✅

**Activity Model Implementation:**
```python
# apps/core/models.py
class Activity(models.Model):
    """HIPAA-compliant activity tracking for audit trail"""
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    activity_type = models.CharField(max_length=50)  # login, logout, document_upload, etc.
    description = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    related_object_type = models.CharField(max_length=50, blank=True)
    related_object_id = models.CharField(max_length=50, blank=True)
```

**BaseModel Abstract Class:**
```python
class BaseModel(models.Model):
    """Base model with consistent audit fields for all medical data"""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True)
    
    class Meta:
        abstract = True
```

**Dashboard Backend Features:**
- Dynamic model counting with graceful error handling
- Real-time activity feed with 20-entry pagination
- Safe model operations with fallbacks when models unavailable
- Performance-optimized database queries with select_related
- HIPAA-compliant audit logging for all user interactions

**Frontend Integration:**
- Alpine.js for client-side interactivity with proper CSP configuration
- Tailwind CSS compilation pipeline for professional medical styling
- Responsive design optimized for healthcare professionals
- Scrollable activity feed with professional UI components

### Patient Management System - Task 3.1 Completed ✅

**Patient Model Implementation:**
```python
# apps/patients/models.py
class Patient(MedicalRecord):
    """Core patient data model with FHIR integration"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mrn = models.CharField(max_length=50, unique=True)  # Medical Record Number
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES)
    ssn = models.CharField(max_length=11, blank=True)
    
    # FHIR Integration - Cumulative patient data
    cumulative_fhir_json = models.JSONField(default=dict, blank=True)
    
    # Soft delete functionality
    deleted_at = models.DateTimeField(null=True, blank=True)
    objects = SoftDeleteManager()
    all_objects = models.Manager()
```

**PatientHistory Model for Audit Trail:**
```python
class PatientHistory(models.Model):
    """HIPAA-compliant audit trail for patient data changes"""
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='history')
    # document = models.ForeignKey('documents.Document', on_delete=models.PROTECT, null=True)
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    fhir_version = models.CharField(max_length=20, default='R4')
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(User, on_delete=models.PROTECT)
    fhir_delta = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
```

**Key Features:**
- **UUID Primary Keys**: Enhanced security and FHIR compatibility
- **MRN Uniqueness**: Medical Record Number as unique identifier
- **Soft Delete**: Prevents accidental deletion of medical records
- **FHIR Integration**: JSONB field for cumulative FHIR bundle storage
- **Audit Trail**: Complete history tracking for HIPAA compliance
- **Database Optimization**: Indexes on MRN, date of birth, and names
- **Security Ready**: Comprehensive comments for future PHI encryption

**Database Schema:**
- `patients_patient` table with UUID primary key and optimized indexes
- `patients_patienthistory` table for complete audit trail
- Foreign key relationships with proper CASCADE protection
- JSONB fields for flexible FHIR data storage

### Technology Stack Details

**Backend Framework**
- Django 5.0 with REST Framework
- Python 3.12+ for optimal performance

**Database Layer**
- PostgreSQL 15+ with JSONB for FHIR data
- Redis for caching and session storage

**Security & Compliance**
- django-allauth for enhanced authentication
- django-otp for two-factor authentication
- django-axes for failed login monitoring
- Field-level encryption for PHI data

**Async Processing**
- Celery with Redis broker
- Background tasks for document processing
- FHIR resource generation pipelines

## Data Flow

1. **Document Upload** → Validation → Secure Storage
2. **Background Processing** → Text Extraction → Medical Entity Recognition
3. **FHIR Conversion** → Resource Generation → Validation
4. **Patient History** → Cumulative Records → Provenance Tracking

## Deployment Architecture

### Development
- SQLite for rapid development
- Django development server
- Local Redis instance

### Production
- PostgreSQL with SSL
- Gunicorn WSGI server
- Nginx reverse proxy
- Docker containers
- Redis cluster for high availability

---

*Documentation automatically updated when architecture changes are made.* 