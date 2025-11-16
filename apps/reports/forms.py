"""
Forms for report parameter selection and configuration.
"""

from django import forms
from django.core.exceptions import ValidationError
from datetime import date, timedelta

from apps.patients.models import Patient
from apps.providers.models import Provider


class BaseReportParametersForm(forms.Form):
    """Base form for common report parameters."""
    
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-input rounded-md border-gray-300',
        }),
        help_text="Start date for filtering report data"
    )
    
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-input rounded-md border-gray-300',
        }),
        help_text="End date for filtering report data"
    )
    
    format = forms.ChoiceField(
        choices=[
            ('pdf', 'PDF'),
            ('csv', 'CSV'),
            ('json', 'JSON'),
        ],
        initial='pdf',
        required=True,
        widget=forms.RadioSelect(attrs={
            'class': 'form-radio text-blue-600',
        }),
        help_text="Output format for the report"
    )
    
    def clean(self):
        """Validate date range."""
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')
        
        if date_from and date_to:
            if date_from > date_to:
                raise ValidationError("Start date must be before end date")
            
            # Check if date range is reasonable (not too large)
            # Allow up to 100 years for lifetime medical reports
            if (date_to - date_from).days > 36500:  # 100 years
                raise ValidationError("Date range cannot exceed 100 years")
        
        return cleaned_data


class PatientReportParametersForm(forms.Form):
    """Form for patient summary report parameters - simplified for dashboard report."""
    
    patient = forms.ModelChoiceField(
        queryset=Patient.objects.all(),
        required=True,
        widget=forms.Select(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm',
        }),
        help_text="Select the patient for the comprehensive dashboard report"
    )
    
    format = forms.ChoiceField(
        choices=[
            ('pdf', 'PDF Document'),
            ('csv', 'CSV Spreadsheet'),
            ('json', 'JSON Data'),
        ],
        initial='pdf',
        required=True,
        widget=forms.RadioSelect(attrs={
            'class': 'text-blue-600 focus:ring-blue-500',
        }),
        help_text="Choose the output format for your report"
    )
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Filter patients by user's organization if applicable
        if user and hasattr(user, 'organization'):
            self.fields['patient'].queryset = Patient.objects.filter(
                organization=user.organization
            ).order_by('last_name_search', 'first_name_search')
        else:
            # No organization filtering - just order all patients
            self.fields['patient'].queryset = Patient.objects.all().order_by('last_name_search', 'first_name_search')


class ProviderReportParametersForm(BaseReportParametersForm):
    """Form for provider activity report parameters."""
    
    provider = forms.ModelChoiceField(
        queryset=Provider.objects.all(),
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select rounded-md border-gray-300',
        }),
        help_text="Select a specific provider (optional)"
    )
    
    specialty = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-input rounded-md border-gray-300',
            'placeholder': 'e.g., Cardiology, Internal Medicine',
        }),
        help_text="Filter by provider specialty"
    )
    
    include_patient_list = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox text-blue-600 rounded',
        }),
        help_text="Include list of patients seen"
    )
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Filter providers by user's organization if applicable
        if user and hasattr(user, 'organization'):
            self.fields['provider'].queryset = Provider.objects.filter(
                organization=user.organization
            ).order_by('last_name', 'first_name')


class DocumentAuditParametersForm(BaseReportParametersForm):
    """Form for document processing audit report parameters."""
    
    status = forms.MultipleChoiceField(
        choices=[
            ('uploaded', 'Uploaded'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'form-checkbox text-blue-600 rounded',
        }),
        help_text="Filter by document processing status"
    )
    
    include_error_details = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox text-blue-600 rounded',
        }),
        help_text="Include detailed error messages for failed documents"
    )
    
    include_performance_metrics = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox text-blue-600 rounded',
        }),
        help_text="Include processing time and performance statistics"
    )


class ReportConfigurationForm(forms.Form):
    """Form for saving report configurations."""
    
    name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-input rounded-md border-gray-300',
            'placeholder': 'My Monthly Patient Report',
        }),
        help_text="Give this configuration a memorable name"
    )
    
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-textarea rounded-md border-gray-300',
            'rows': 3,
            'placeholder': 'Optional description of what this report includes...',
        }),
        help_text="Optional description for future reference"
    )
    
    is_favorite = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox text-blue-600 rounded',
        }),
        help_text="Mark as favorite for quick access"
    )

