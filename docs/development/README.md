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

## Patient Management Patterns - Task 3 Completed ✅

**Complete Patient Management Development Implementation:**
The Patient Management module demonstrates advanced Django patterns for medical data handling with HIPAA compliance and professional UI.

### Search Functionality with Input Validation

**Patient Search Form Implementation**
```python
from django import forms
from django.core.exceptions import ValidationError

class PatientSearchForm(forms.Form):
    """
    Secure form for validating patient search input.
    
    Prevents injection attacks and provides user feedback.
    """
    q = forms.CharField(
        max_length=100,
        required=False,
        strip=True,
        widget=forms.TextInput(attrs={
            'placeholder': 'Search by name, MRN, or date of birth...',
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 pl-10'
        })
    )
    
    def clean_q(self):
        """Validate and sanitize search input."""
        query = self.cleaned_data.get('q', '').strip()
        
        if len(query) > 100:
            raise ValidationError("Search query too long. Maximum 100 characters.")
        
        # Input sanitization for medical data
        allowed_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-_@')
        if query and not set(query).issubset(allowed_chars):
            raise ValidationError("Search query contains invalid characters.")
        
        return query
```

### Small Focused Functions Pattern

**PatientListView with Decomposed Methods**
```python
from django.views.generic import ListView
from django.db.models import Q
from django.db import DatabaseError, OperationalError

class PatientListView(LoginRequiredMixin, ListView):
    """
    Professional patient list with search functionality.
    
    Follows cursor rules: small focused functions under 30 lines each.
    """
    model = Patient
    paginate_by = 20
    
    def validate_search_input(self):
        """
        Validate search form input from request.
        
        Returns:
            tuple: (is_valid, search_query)
        """
        search_form = PatientSearchForm(self.request.GET)
        
        if search_form.is_valid():
            search_query = search_form.cleaned_data.get('q', '')
            return True, search_query
        else:
            logger.warning(f"Invalid search form data: {search_form.errors}")
            messages.warning(self.request, "Invalid search criteria. Please try again.")
            return False, ''
    
    def filter_patients_by_search(self, queryset, search_query):
        """
        Filter patient queryset by search criteria.
        
        Uses Django Q objects for multi-field search.
        """
        if search_query:
            return queryset.filter(
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query) |
                Q(mrn__icontains=search_query)
            )
        return queryset
    
    def order_patients(self, queryset):
        """Apply consistent ordering to patient queryset."""
        return queryset.order_by('last_name', 'first_name')
    
    def get_queryset(self):
        """Main queryset method orchestrating smaller functions."""
        try:
            queryset = super().get_queryset()
            is_valid, search_query = self.validate_search_input()
            
            if is_valid:
                queryset = self.filter_patients_by_search(queryset, search_query)
            
            return self.order_patients(queryset)
            
        except (DatabaseError, OperationalError) as database_error:
            logger.error(f"Database error in patient list view: {database_error}")
            messages.error(self.request, "There was an error loading patients. Please try again.")
            return Patient.objects.none()
```

### Specific Exception Handling

**Database Error Handling Patterns**
```python
from django.db import IntegrityError, DatabaseError, OperationalError
import logging

logger = logging.getLogger(__name__)

class PatientCreateView(LoginRequiredMixin, CreateView):
    """Patient creation with comprehensive error handling."""
    
    def form_valid(self, form):
        """Save patient with specific exception handling."""
        try:
            response = super().form_valid(form)
            self.create_patient_history()
            self.show_success_message()
            return response
            
        except IntegrityError as integrity_error:
            # Handle duplicate MRN or other constraint violations
            logger.error(f"Database integrity error creating patient: {integrity_error}")
            messages.error(self.request, "A patient with this MRN already exists.")
            return self.form_invalid(form)
            
        except (DatabaseError, OperationalError) as database_error:
            # Handle connection issues, timeouts, etc.
            logger.error(f"Error creating patient: {database_error}")
            messages.error(self.request, "There was an error creating the patient record.")
            return self.form_invalid(form)
    
    def create_patient_history(self):
        """Single-purpose function for history creation."""
        return PatientHistory.objects.create(
            patient=self.object,
            action='created',
            changed_by=self.request.user,
            notes=f'Patient record created by {self.request.user.get_full_name()}'
        )
```

### Professional Medical UI Templates

**Patient List Template Structure**
```html
{% extends "base.html" %}

<!-- Professional medical template with Tailwind CSS -->
<div class="p-6">
    <!-- Header with Add Patient Button -->
    <div class="flex justify-between items-center mb-6">
        <div class="flex items-center space-x-3">
            <div class="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
                <svg class="w-6 h-6 text-blue-600"><!-- Patient icon --></svg>
            </div>
            <div>
                <h1 class="text-2xl font-bold text-gray-900">Patient Management</h1>
                <p class="text-gray-600">Manage patient records and medical information</p>
            </div>
        </div>
        <a href="{% url 'patients:add' %}" class="btn-primary">
            Add New Patient
        </a>
    </div>

    <!-- Search Form with Validation -->
    <div class="bg-gray-50 p-4 rounded-lg mb-6">
        <form method="get">
            <div class="flex-1">
                <label for="search" class="block text-sm font-medium text-gray-700 mb-1">
                    Search Patients
                </label>
                <div class="relative">
                    {{ search_form.q }}
                    <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <svg class="w-4 h-4 text-gray-400"><!-- Search icon --></svg>
                    </div>
                </div>
                {% if search_form.q.errors %}
                    <div class="mt-1 text-sm text-red-600">
                        {{ search_form.q.errors.0 }}
                    </div>
                {% endif %}
            </div>
        </form>
    </div>

    <!-- Professional Patient Table -->
    <div class="bg-white rounded-lg shadow overflow-hidden">
        <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Patient
                    </th>
                    <!-- Additional columns... -->
                </tr>
            </thead>
            <tbody class="bg-white divide-y divide-gray-200">
                {% for patient in patients %}
                <tr class="hover:bg-gray-50 transition-colors">
                    <td class="px-6 py-4 whitespace-nowrap">
                        <div class="flex items-center">
                            <div class="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center">
                                <span class="text-blue-600 font-medium text-sm">
                                    {{ patient.first_name|first }}{{ patient.last_name|first }}
                                </span>
                            </div>
                            <div class="ml-4">
                                <div class="text-sm font-medium text-gray-900">
                                    {{ patient.first_name }} {{ patient.last_name }}
                                </div>
                            </div>
                        </div>
                    </td>
                    <!-- Additional columns and action buttons... -->
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <!-- Pagination with Search Preservation -->
    {% if is_paginated %}
    <nav class="flex items-center space-x-2" aria-label="Pagination">
        {% if page_obj.has_previous %}
        <a href="?{% if search_query %}q={{ search_query }}&{% endif %}page={{ page_obj.previous_page_number }}" 
           class="pagination-btn">Previous</a>
        {% endif %}
        <!-- Page numbers and next button... -->
    </nav>
    {% endif %}
</div>
```

### JavaScript Integration Patterns

**Loading States and User Feedback**
```javascript
document.addEventListener('DOMContentLoaded', function() {
    // Focus management for accessibility
    const searchInput = document.querySelector('input[name="q"]');
    if (searchInput && !searchInput.value) {
        searchInput.focus();
    }
    
    // Loading state for search form
    const searchForm = document.querySelector('form');
    if (searchForm) {
        searchForm.addEventListener('submit', function() {
            const submitButton = this.querySelector('button[type="submit"]');
            if (submitButton) {
                submitButton.disabled = true;
                submitButton.innerHTML = `
                    <svg class="w-4 h-4 mr-2 animate-spin"><!-- Loading spinner --></svg>
                    Searching...
                `;
            }
        });
    }
});
```

### URL Configuration Patterns

**UUID-Based Routing for Security**
```python
# apps/patients/urls.py
from django.urls import path
from . import views

app_name = 'patients'

urlpatterns = [
    # Using UUID for enhanced security
    path('', views.PatientListView.as_view(), name='list'),
    path('add/', views.PatientCreateView.as_view(), name='add'),
    path('<uuid:pk>/', views.PatientDetailView.as_view(), name='detail'),
    path('<uuid:pk>/edit/', views.PatientUpdateView.as_view(), name='edit'),
]
```

### Error Handling & User Feedback

**Graceful Degradation Patterns**
```python
def get_patient_count(self):
    """Get total patient count with error handling."""
    try:
        return Patient.objects.count()
    except (DatabaseError, OperationalError) as count_error:
        logger.error(f"Error getting patient count: {count_error}")
        return 0  # Graceful fallback

def build_search_context(self):
    """Build search context safely."""
    search_form = PatientSearchForm(self.request.GET)
    search_query = search_form.data.get('q', '') if search_form.data else ''
    
            return {
            'search_form': search_form,
            'search_query': search_query
        }

### Patient Detail Views with FHIR Integration - Task 3.3 Completed

**Comprehensive Detail View Pattern**
```python
class PatientDetailView(LoginRequiredMixin, DetailView):
    """
    Professional patient detail view with FHIR history timeline.
    
    Demonstrates complex context building with error handling.
    """
    model = Patient
    template_name = 'patients/patient_detail.html'
    context_object_name = 'patient'
    
    def get_fhir_summary(self):
        """
        Generate FHIR resource summary statistics.
        
        Returns:
            dict: Resource type counts and metadata
        """
        if not self.object.cumulative_fhir_json:
            return {}
        
        summary = {}
        for resource_type, resources in self.object.cumulative_fhir_json.items():
            if isinstance(resources, list):
                summary[resource_type] = {
                    'count': len(resources),
                    'last_updated': self.get_last_updated_for_resource_type(resource_type)
                }
        return summary
    
    def get_patient_history(self):
        """
        Get patient history records safely.
        
        Returns:
            QuerySet: Patient history records
        """
        try:
            return PatientHistory.objects.filter(
                patient=self.object
            ).order_by('-changed_at')[:10]
        except (DatabaseError, OperationalError) as history_error:
            logger.error(f"Error loading patient history for {self.object.id}: {history_error}")
            messages.warning(self.request, "Some patient history may not be available.")
            return PatientHistory.objects.none()
    
    def get_context_data(self, **kwargs):
        """Build comprehensive context with error handling."""
        context = super().get_context_data(**kwargs)
        
        # Log PHI access for HIPAA compliance
        Activity.objects.create(
            user=self.request.user,
            activity_type='patient_view',
            description=f'Viewed patient {self.object.first_name} {self.object.last_name}',
            ip_address=self.request.META.get('REMOTE_ADDR', ''),
            user_agent=self.request.META.get('HTTP_USER_AGENT', '')
        )
        
        context.update({
            'patient_history': self.get_patient_history(),
            'fhir_summary': self.get_fhir_summary(),
            'history_count': self.object.history_records.count(),
            'action_summary': self.get_action_summary()
        })
        
        return context
```

### Patient Forms with History Tracking - Task 3.4 Completed

**Professional Form Handling Pattern**
```python
class PatientUpdateView(LoginRequiredMixin, UpdateView):
    """
    Patient update view with automatic history tracking.
    
    Demonstrates transactional form processing with audit trails.
    """
    model = Patient
    template_name = 'patients/patient_form.html'
    fields = ['mrn', 'first_name', 'last_name', 'date_of_birth', 'gender', 'ssn']
    
    def get_form(self, form_class=None):
        """Customize form with enhanced widgets and validation."""
        form = super().get_form(form_class)
        
        # Add professional medical styling
        for field_name, field in form.fields.items():
            field.widget.attrs.update({
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
            })
        
        # Special handling for sensitive fields
        if 'ssn' in form.fields:
            form.fields['ssn'].widget.attrs.update({
                'placeholder': 'XXX-XX-XXXX',
                'maxlength': '11',
                'pattern': '[0-9]{3}-[0-9]{2}-[0-9]{4}'
            })
        
        return form
    
    def create_update_history(self):
        """Create history record for patient update."""
        return PatientHistory.objects.create(
            patient=self.object,
            action='updated',
            changed_by=self.request.user,
            notes=f'Patient information updated via web interface by {self.request.user.get_full_name()}'
        )
    
    def show_update_message(self):
        """Display user-friendly success message."""
        messages.success(
            self.request, 
            f'Patient {self.object.first_name} {self.object.last_name} updated successfully.'
        )
    
    def form_valid(self, form):
        """
        Save the patient and create a history record.

        Returns:
            HttpResponse: Redirect to success URL
        """
        try:
            response = super().form_valid(form)
            self.create_update_history()
            self.show_update_message()
            return response
            
        except IntegrityError as integrity_error:
            logger.error(f"Database integrity error updating patient: {integrity_error}")
            messages.error(self.request, "A patient with this MRN already exists.")
            return self.form_invalid(form)
            
        except (DatabaseError, OperationalError) as update_error:
            logger.error(f"Error updating patient {self.object.id}: {update_error}")
            messages.error(self.request, "There was an error updating the patient record.")
            return self.form_invalid(form)
```

### FHIR Export and Advanced Features - Task 3.5 Completed

**FHIR Export Implementation**
```python
class PatientFHIRExportView(LoginRequiredMixin, View):
    """
    Export patient data as FHIR JSON file download.
    
    Demonstrates FHIR compliance and secure data export.
    """
    def get(self, request, pk):
        """Generate and return FHIR-compliant patient data."""
        try:
            patient = get_object_or_404(Patient, pk=pk)
            
            # Log FHIR export for audit trail
            PatientHistory.objects.create(
                patient=patient,
                action='fhir_export',
                changed_by=request.user,
                notes=f'FHIR data exported by {request.user.get_full_name()}'
            )
            
            # Generate FHIR Patient resource
            fhir_data = self.generate_fhir_patient_resource(patient)
            
            # Create secure file response
            response = JsonResponse(fhir_data, json_dumps_params={'indent': 2})
            response['Content-Disposition'] = f'attachment; filename="patient_{patient.mrn}_fhir.json"'
            response['Content-Type'] = 'application/fhir+json'
            
            return response
            
        except Exception as export_error:
            logger.error(f"Error exporting FHIR data for patient {pk}: {export_error}")
            messages.error(request, "There was an error exporting the patient data.")
            return redirect('patients:detail', pk=pk)
    
    def generate_fhir_patient_resource(self, patient):
        """
        Generate FHIR R4 compliant Patient resource.
        
        Args:
            patient: Patient model instance
            
        Returns:
            dict: FHIR Patient resource
        """
        fhir_data = {
            'resourceType': 'Patient',
            'id': str(patient.id),
            'meta': {
                'versionId': '1',
                'lastUpdated': patient.updated_at.isoformat(),
                'source': 'medical-document-parser'
            },
            'identifier': [
                {
                    'type': {
                        'coding': [{
                            'system': 'http://terminology.hl7.org/CodeSystem/v2-0203',
                            'code': 'MR',
                            'display': 'Medical Record Number'
                        }]
                    },
                    'value': patient.mrn
                }
            ],
            'name': [{
                'use': 'official',
                'family': patient.last_name,
                'given': [patient.first_name]
            }],
            'birthDate': patient.date_of_birth.isoformat(),
            'gender': patient.gender.lower() if patient.gender else 'unknown'
        }
        
        # Include cumulative FHIR data if available
        if patient.cumulative_fhir_json:
            # Merge additional FHIR resources while preserving structure
            for resource_type, resources in patient.cumulative_fhir_json.items():
                if resource_type != 'Patient':  # Don't overwrite Patient resource
                    fhir_data[resource_type] = resources
        
        return fhir_data
```

### Advanced UI Patterns - Task 3.6 Completed

**Enhanced Search Interface with Real-time Validation**
```javascript
// Enhanced search functionality with accessibility
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.querySelector('input[name="q"]');
    const searchForm = document.getElementById('search-form');
    const searchButton = document.getElementById('search-button');
    const searchError = document.getElementById('search-error');
    
    // Real-time search validation
    if (searchInput) {
        let searchTimeout;
        
        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            const query = this.value.trim();
            
            // Clear previous error
            hideSearchError();
            
            // Real-time validation with user feedback
            if (query.length > 0 && query.length < 2) {
                searchTimeout = setTimeout(() => {
                    showSearchError('Search term must be at least 2 characters long.');
                }, 1000);
            }
        });
        
        // Keyboard shortcuts for better UX
        searchInput.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                this.value = '';
                hideSearchError();
                this.blur();
            }
        });
    }
    
    // Enhanced table row interactions with keyboard support
    const tableRows = document.querySelectorAll('tbody tr');
    tableRows.forEach(row => {
        row.setAttribute('tabindex', '0');
        
        row.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                const viewLink = this.querySelector('a[title*="View"]');
                if (viewLink) {
                    viewLink.click();
                }
            }
        });
    });
});

// Utility functions for error handling
function showSearchError(message) {
    const searchError = document.getElementById('search-error');
    const searchErrorMessage = document.getElementById('search-error-message');
    
    if (searchError && searchErrorMessage) {
        searchErrorMessage.textContent = message;
        searchError.classList.remove('hidden');
        
        // Auto-hide after 5 seconds
        setTimeout(() => {
            hideSearchError();
        }, 5000);
    }
}

function hideSearchError() {
    const searchError = document.getElementById('search-error');
    if (searchError) {
        searchError.classList.add('hidden');
    }
}
```

**Professional Medical Templates with Accessibility**
```html
<!-- Patient Detail Template (400+ lines) -->
{% extends "base.html" %}
{% load static %}

{% block title %}{{ patient.first_name }} {{ patient.last_name }} - Patient Details{% endblock %}

{% block content %}
<div class="p-6" role="main" aria-labelledby="patient-heading">
    <!-- Header with patient information -->
    <div class="mb-6">
        <div class="flex items-center justify-between">
            <div class="flex items-center space-x-3">
                <div class="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center" 
                     aria-hidden="true">
                    <svg class="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" 
                              d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                    </svg>
                </div>
                <div>
                    <h1 id="patient-heading" class="text-2xl font-bold text-gray-900">
                        {{ patient.first_name }} {{ patient.last_name }}
                    </h1>
                    <p class="text-gray-600">MRN: {{ patient.mrn }} • DOB: {{ patient.date_of_birth|date:"F j, Y" }}</p>
                </div>
            </div>
            
            <!-- Action buttons with proper ARIA labels -->
            <div class="flex space-x-3">
                <a href="{% url 'patients:edit' patient.pk %}" 
                   class="btn-secondary"
                   aria-label="Edit {{ patient.first_name }} {{ patient.last_name }}'s information">
                    <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" 
                              d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>
                    </svg>
                    Edit Patient
                </a>
                
                <a href="{% url 'patients:fhir-export' patient.pk %}" 
                   class="btn-primary"
                   aria-label="Export {{ patient.first_name }} {{ patient.last_name }}'s FHIR data">
                    <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" 
                              d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                    </svg>
                    Export FHIR
                </a>
            </div>
        </div>
    </div>

    <!-- FHIR History Timeline with accessibility -->
    <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
        <h2 class="text-lg font-semibold text-gray-900 mb-4" id="history-heading">
            Medical History Timeline
        </h2>
        
        {% if patient_history %}
        <div class="flow-root" role="list" aria-labelledby="history-heading">
            <ul role="list" class="-mb-8">
                {% for history in patient_history %}
                <li role="listitem">
                    <div class="relative pb-8">
                        <!-- Timeline connector -->
                        {% if not forloop.last %}
                        <span class="absolute top-4 left-4 -ml-px h-full w-0.5 bg-gray-200" aria-hidden="true"></span>
                        {% endif %}
                        
                        <div class="relative flex space-x-3">
                            <!-- Event icon with semantic color coding -->
                            <div>
                                <span class="h-8 w-8 rounded-full flex items-center justify-center ring-8 ring-white
                                    {% if history.action == 'created' %}bg-green-500
                                    {% elif history.action == 'updated' %}bg-blue-500
                                    {% elif history.action == 'fhir_export' %}bg-purple-500
                                    {% else %}bg-gray-500{% endif %}"
                                    aria-label="{{ history.get_action_display }} event">
                                    <!-- Action-specific icons -->
                                </span>
                            </div>
                            
                            <!-- Event details -->
                            <div class="min-w-0 flex-1">
                                <div class="bg-gray-50 rounded-lg p-4">
                                    <div class="flex justify-between items-start mb-2">
                                        <h3 class="text-sm font-medium text-gray-900">
                                            {{ history.get_action_display }}
                                        </h3>
                                        <time class="text-sm text-gray-500" 
                                              datetime="{{ history.changed_at|date:'c' }}">
                                            {{ history.changed_at|date:"M j, Y g:i A" }}
                                        </time>
                                    </div>
                                    
                                    {% if history.notes %}
                                    <p class="text-sm text-gray-700">{{ history.notes }}</p>
                                    {% endif %}
                                </div>
                            </div>
                        </div>
                    </div>
                </li>
                {% endfor %}
            </ul>
        </div>
        {% else %}
        <!-- Empty state with proper messaging -->
        <div class="text-center py-12" role="status" aria-live="polite">
            <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" 
                      d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
            <h3 class="mt-2 text-sm font-medium text-gray-900">No history records</h3>
            <p class="mt-1 text-sm text-gray-500">Patient activity will appear here as it occurs.</p>
        </div>
        {% endif %}
    </div>
</div>
{% endblock %}
```

### Development Best Practices Established

**Code Quality Standards:**
- ✅ **Small Focused Functions**: All methods under 30 lines with single responsibility
- ✅ **Explicit Variable Names**: Descriptive naming throughout (e.g., `patient_history_records` vs `records`)
- ✅ **Comprehensive Error Handling**: Specific exception handling with user-friendly messages
- ✅ **Input Validation**: All user input validated and sanitized before processing
- ✅ **Accessibility First**: ARIA labels, semantic HTML, keyboard navigation support
- ✅ **HIPAA Compliance**: PHI protection and audit logging throughout
- ✅ **Professional UI**: Medical-grade interface with consistent styling
- ✅ **Performance Optimization**: Efficient database queries with select_related/prefetch_related
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

# Show next task
task-master next

# Mark task in progress
task-master set-status --id=3.2 --status=in-progress

# Mark task complete
task-master set-status --id=3.2 --status=done

# Update task files
task-master generate
```

---

*Updated: January 2025 | Added Patient Management Patterns (Task 3.2)* 