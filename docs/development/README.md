# 👩‍💻 Development Guide

## Development Workflow

### Getting Started
1. **Task Management**: Check `.taskmaster/` for current tasks and priorities
2. **Environment Setup**: Ensure virtual environment is activated before any Python commands
3. **Documentation**: Update relevant docs when completing tasks/features
4. **Testing**: Write tests for new functionality
5. **Security**: Consider HIPAA compliance in all medical data handling

### Project Structure

```
doc2db_2025_django/
├── apps/                      # Django applications
│   ├── accounts/             # User authentication & profiles
│   ├── core/                 # Shared utilities
│   ├── documents/            # Document processing
│   ├── patients/             # Patient management
│   ├── providers/            # Provider management
│   ├── fhir/                # FHIR resource handling
│   └── reports/             # Report generation
├── docs/                     # Project documentation
├── meddocparser/            # Django project settings
│   ├── settings/            # Environment-specific settings
│   ├── celery.py           # Celery configuration
│   └── ...
├── static/                  # Static files (CSS, JS, images)
├── templates/               # Django templates
├── docker/                  # Docker configurations
└── .taskmaster/            # Task management
```

## Frontend Infrastructure - Task 2.2 Completed

### Tailwind CSS Integration

**Tailwind Configuration**
```python
# meddocparser/settings/base.py
TAILWIND_APP_NAME = 'theme'
NPM_BIN_PATH = config('NPM_BIN_PATH', default='C:/Users/Peter/AppData/Roaming/npm/npm.cmd')
NODE_PATH = config('NODE_PATH', default='C:/Program Files/nodejs/node.exe')
```

**Development Workflow**
```bash
# Start Tailwind CSS compilation in development
venv\Scripts\activate
python manage.py tailwind start

# Build for production
python manage.py tailwind build

# Install/update Tailwind dependencies
python manage.py tailwind install
```

**Custom Medical UI Components** (theme/static_src/src/styles.css)
```css
/* Medical-grade button components */
.btn-primary {
  @apply inline-flex items-center px-4 py-2 border border-transparent 
         text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 
         hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 
         focus:ring-blue-500 transition-colors;
}

/* Medical data display cards */
.card {
  @apply bg-white shadow rounded-lg border border-gray-200;
}

.card-body {
  @apply p-6;
}

/* HIPAA compliance visual indicators */
.hipaa-secure {
  @apply border-l-4 border-green-500 bg-green-50 p-4;
}

/* Status indicators for medical data */
.status-success { @apply bg-green-100 text-green-800; }
.status-warning { @apply bg-yellow-100 text-yellow-800; }
.status-error { @apply bg-red-100 text-red-800; }
```

### Template Structure

**Base Template Pattern** (templates/base.html)
```html
<!DOCTYPE html>
<html lang="en" class="h-full bg-gray-50">
<head>
    {% load tailwind_tags %}
    {% tailwind_css %}
    <!-- Security headers for HIPAA compliance -->
    <meta http-equiv="Content-Security-Policy" content="...">
    <meta http-equiv="X-Frame-Options" content="DENY">
</head>
<body class="h-full" x-data="{ sidebarOpen: false }" x-cloak>
    <!-- Responsive navigation with Alpine.js -->
    <nav class="bg-white shadow-sm border-b border-gray-200">
        <!-- Mobile-first navigation with htmx interactions -->
    </nav>
    
    <!-- Main content with breadcrumbs -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {% block breadcrumbs %}{% endblock %}
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

**Breadcrumb Component** (templates/components/breadcrumbs.html)
```html
{% if breadcrumbs %}
<nav class="flex mb-6" aria-label="Breadcrumb">
    <ol class="inline-flex items-center space-x-1 md:space-x-3">
        <!-- WCAG-compliant breadcrumb navigation -->
        {% for breadcrumb in breadcrumbs %}
            <li class="inline-flex items-center">
                {% if breadcrumb.url %}
                    <a href="{% url breadcrumb.url %}" 
                       class="text-gray-700 hover:text-blue-600">
                        {{ breadcrumb.name }}
                    </a>
                {% else %}
                    <span class="text-gray-500">{{ breadcrumb.name }}</span>
                {% endif %}
            </li>
        {% endfor %}
    </ol>
</nav>
{% endif %}
```

### Interactive Frontend (htmx + Alpine.js)

**htmx Integration**
```html
<!-- Dynamic patient search -->
<div hx-get="/patients/search/" 
     hx-trigger="keyup changed delay:300ms" 
     hx-target="#search-results"
     hx-indicator="#loading">
    <input type="text" name="q" placeholder="Search patients..." 
           class="input-search">
</div>

<!-- Loading states -->
<div id="loading" class="htmx-indicator">
    <div class="flex items-center">
        <svg class="animate-spin h-5 w-5 mr-3" viewBox="0 0 24 24">
            <!-- Loading spinner -->
        </svg>
        Processing...
    </div>
</div>
```

**Alpine.js Components**
```html
<!-- User dropdown menu -->
<div x-data="{ open: false }" class="relative">
    <button @click="open = !open" 
            @click.away="open = false"
            class="flex items-center text-sm rounded-full focus:outline-none">
        <img class="h-8 w-8 rounded-full" src="{{ user.profile_image }}" alt="">
    </button>
    
    <div x-show="open" 
         x-transition:enter="transition ease-out duration-100"
         class="origin-top-right absolute right-0 mt-2 w-48 rounded-md shadow-lg">
        <!-- Dropdown menu items -->
    </div>
</div>
```

### Dashboard UI Implementation - Task 2.4 Completed

**Professional Dashboard Template** (templates/accounts/dashboard.html)
```html
<!-- Quick Stats Cards with Medical Icons -->
<div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
    <div class="card">
        <div class="card-body flex items-center">
            <div class="flex-shrink-0">
                <div class="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
                    <svg class="w-6 h-6 text-blue-600" fill="none" stroke="currentColor">
                        <!-- Patient icon -->
                    </svg>
                </div>
            </div>
            <div class="ml-4">
                <p class="text-sm font-medium text-gray-600">Total Patients</p>
                <p class="text-2xl font-bold text-gray-900">{{ patient_count|default:0 }}</p>
            </div>
        </div>
    </div>
    <!-- Provider and Document count cards... -->
</div>

<!-- Navigation Cards for Main Modules -->
<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
    <a href="{% url 'documents:upload' %}" 
       class="card hover:shadow-lg transition-shadow group">
        <div class="card-body text-center">
            <div class="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center mx-auto mb-3">
                <!-- Upload icon -->
            </div>
            <h3 class="text-sm font-medium text-gray-900 mb-1">Upload Document</h3>
            <p class="text-xs text-gray-500">Process new medical files</p>
        </div>
    </a>
    <!-- Patient Management, Provider Directory, Analytics cards... -->
</div>
```

**Dashboard Components**
- **Stats Cards**: Patient count, provider count, documents processed with medical-grade icons
- **Quick Actions**: Four main module navigation cards with hover effects
- **Recent Activity**: Timeline component with placeholder state for activity tracking
- **System Status**: Database, processing, HIPAA compliance monitoring panel
- **Responsive Grid**: Mobile-first layout optimized for healthcare workflows

**Backend Integration** (apps/accounts/views.py)
```python
class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Ready for real data integration
        context.update({
            'patient_count': 0,  # Patient.objects.count()
            'provider_count': 0,  # Provider.objects.count() 
            'document_count': 0,  # Document.objects.count()
            'recent_activities': [],  # Activity feed data
        })
        return context
```

### Accessibility & HIPAA Compliance

**WCAG 2.1 Features**
- Focus management with visible focus rings
- Keyboard navigation support
- Screen reader compatibility (ARIA labels)
- Color contrast ratios meeting medical standards
- Skip links for main content

**Security Implementation**
- Content Security Policy headers
- X-Frame-Options protection
- Session timeout indicators
- User activity monitoring
- Secure form handling

## Coding Standards

### Django Best Practices

**Models**
```python
from django.db import models
from django_cryptography.fields import encrypt

class Patient(models.Model):
    """Patient model with HIPAA compliance."""
    
    # Encrypted PHI fields
    first_name = encrypt(models.CharField(max_length=100))
    last_name = encrypt(models.CharField(max_length=100))
    
    # Non-encrypted searchable fields
    medical_record_number = models.CharField(max_length=50, unique=True)
    date_of_birth = models.DateField()
    
    # FHIR data storage
    fhir_bundle = models.JSONField(default=dict)
    
    class Meta:
        db_table = 'patients'
        verbose_name = 'Patient'
        verbose_name_plural = 'Patients'
    
    def __str__(self):
        return f"Patient {self.medical_record_number}"
```

**Views**
```python
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView

class PatientListView(LoginRequiredMixin, ListView):
    """HIPAA-compliant patient listing."""
    
    model = Patient
    template_name = 'patients/list.html'
    context_object_name = 'patients'
    paginate_by = 25
    
    def get_queryset(self):
        """Filter by user's organization."""
        return Patient.objects.filter(
            organization=self.request.user.organization
        ).select_related('primary_provider')
```

**Security Decorators**
```python
from django_ratelimit.decorators import ratelimit
from django.contrib.auth.decorators import login_required

@login_required
@ratelimit(key='user', rate='10/m')
def sensitive_endpoint(request):
    """Rate-limited medical data endpoint."""
    # PHI handling code
    pass
```

### FHIR Data Handling

**Resource Creation**
```python
from fhir.resources.patient import Patient as FHIRPatient

def create_fhir_patient(patient_data):
    """Create FHIR Patient resource."""
    fhir_patient = FHIRPatient(**{
        "id": str(patient_data['id']),
        "name": [{
            "given": [patient_data['first_name']],
            "family": patient_data['last_name']
        }],
        "birthDate": patient_data['date_of_birth'].isoformat()
    })
    
    # Validate FHIR resource
    try:
        fhir_patient.dict()  # Validates structure
        return fhir_patient
    except ValidationError as e:
        logger.error(f"FHIR validation failed: {e}")
        raise
```

**JSONB Queries**
```python
# PostgreSQL JSONB queries for FHIR data
patients_with_diabetes = Patient.objects.filter(
    fhir_bundle__entry__contains=[{
        "resource": {
            "resourceType": "Condition",
            "code": {
                "coding": [{
                    "code": "E11.9",  # Type 2 diabetes
                    "system": "http://hl7.org/fhir/sid/icd-10"
                }]
            }
        }
    }]
)
```

### Celery Tasks

**Document Processing**
```python
from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

@shared_task(bind=True, max_retries=3)
def process_medical_document(self, document_id):
    """Process uploaded medical document."""
    try:
        document = Document.objects.get(id=document_id)
        
        # Extract text from document
        text_content = extract_text(document.file.path)
        
        # Generate FHIR resources
        fhir_resources = generate_fhir_from_text(text_content)
        
        # Update patient record
        patient = document.patient
        patient.add_fhir_resources(fhir_resources)
        
        # Update document status
        document.status = 'processed'
        document.processed_at = timezone.now()
        document.save()
        
        logger.info(f"Document {document_id} processed successfully")
        
    except Exception as exc:
        logger.error(f"Document processing failed: {exc}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2 ** self.request.retries))
        else:
            document.status = 'failed'
            document.error_message = str(exc)
            document.save()
            raise
```

## Testing Guidelines

### Test Structure
```python
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from apps.patients.models import Patient

User = get_user_model()

class PatientModelTests(TestCase):
    """Test Patient model functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            medical_record_number='MRN123',
            date_of_birth='1980-01-01'
        )
    
    def test_patient_creation(self):
        """Test patient can be created with required fields."""
        self.assertEqual(self.patient.medical_record_number, 'MRN123')
        self.assertTrue(self.patient.created_at)
    
    def test_fhir_resource_generation(self):
        """Test FHIR resource creation from patient data."""
        fhir_patient = self.patient.to_fhir()
        self.assertEqual(fhir_patient.resourceType, 'Patient')
        self.assertEqual(fhir_patient.name[0].family, 'Doe')
```

### Running Tests
```bash
# Run all tests
python manage.py test

# Run specific app tests
python manage.py test apps.patients

# Run with coverage
coverage run --source='.' manage.py test
coverage report
coverage html
```

## Security Considerations

### PHI Data Handling
- **Never log PHI data** in plain text
- **Use encryption** for all sensitive fields
- **Audit all access** to medical records
- **Minimize data exposure** in views and templates

### Code Reviews
- All security-related code must be peer-reviewed
- Check for proper authentication and authorization
- Verify HIPAA compliance requirements
- Test with realistic (but anonymized) data

### Environment Management
- **Always use virtual environment** for Python commands
- **Keep secrets in environment variables**
- **Never commit credentials** to version control
- **Use different settings** for dev/staging/production

## Task Master Integration

### Task Workflow
1. **Check current tasks**: Use `.taskmaster/` to see what needs work
2. **Update task status**: Mark tasks as in-progress when starting
3. **Document progress**: Update task details with implementation notes
4. **Mark complete**: Set status to 'done' when finished
5. **Update documentation**: Keep docs current with completed features

### Common Commands
```bash
# View current tasks
task-master list

# Get next task
task-master next

# Update task status
task-master set-status --id=1.2 --status=in-progress

# Add implementation notes
task-master update-subtask --id=1.2 --prompt="Implemented feature X with Y approach"
```

## Debugging & Troubleshooting

### Django Debug Toolbar
- Enabled in development mode
- Shows SQL queries, cache hits, template rendering time
- Access at `/__debug__/` when DEBUG=True

### Logging
```python
import logging

logger = logging.getLogger(__name__)

# Use structured logging for medical applications
logger.info('Patient record accessed', extra={
    'user_id': request.user.id,
    'patient_id': patient.id,
    'action': 'view_record'
})
```

### Common Issues

**Virtual Environment Not Activated**
```bash
# Symptoms: packages install globally, import errors
# Solution: Always activate venv first
venv\Scripts\activate
```

**Docker Container Issues**
```bash
# View container logs
docker-compose logs web

# Rebuild containers
docker-compose down
docker-compose up --build
```

**Database Migration Issues**
```bash
# Check migration status
python manage.py showmigrations

# Create new migration
python manage.py makemigrations

# Apply migrations
python manage.py migrate
```

## Recent Development Achievements

### Task 2 - User Authentication and Home Page (Complete) ✅

**Authentication System Implementation:**
- Complete django-allauth integration with 7 professional medical-grade templates
- HIPAA-compliant authentication flow (email-only, no remember-me, strong passwords)
- Professional styling with Tailwind CSS and responsive design
- Comprehensive error handling and security features

**Dashboard System Implementation:**
- Activity model with HIPAA-compliant audit logging
- BaseModel abstract class for consistent audit trails
- Dynamic dashboard with real-time activity feed
- Alpine.js integration with proper Content Security Policy
- Professional medical UI components and responsive design

**Technical Patterns Established:**
- Safe model operations with graceful fallbacks
- Performance-optimized database queries
- Tailwind CSS compilation pipeline
- Medical-grade UI component system

---

*Development documentation updated with each major feature implementation* 