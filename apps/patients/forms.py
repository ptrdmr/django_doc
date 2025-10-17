"""
Forms for the patients app.
Handles encrypted fields and date conversion for HIPAA-compliant patient data.
"""

from django import forms
from django.core.exceptions import ValidationError
from datetime import datetime, date
from .models import Patient


class PatientForm(forms.ModelForm):
    """
    Form for creating and editing Patient records.
    Handles date_of_birth conversion between DateField and encrypted CharField.
    """
    
    # Override date_of_birth to use DateField in the form
    date_of_birth = forms.DateField(
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm'
            }
        ),
        required=False,
        help_text="Patient's date of birth"
    )
    
    class Meta:
        model = Patient
        fields = ['mrn', 'first_name', 'last_name', 'date_of_birth', 'gender', 'ssn', 'address', 'phone', 'email']
        widgets = {
            'mrn': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm',
                'placeholder': 'Medical Record Number'
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm',
                'placeholder': 'First Name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm',
                'placeholder': 'Last Name'
            }),
            'gender': forms.Select(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm'
            }),
            'ssn': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm',
                'placeholder': '123-45-6789',
                'pattern': r'\d{3}-\d{2}-\d{4}'
            }),
            'address': forms.Textarea(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm',
                'rows': 3,
                'placeholder': 'Street address, city, state, ZIP'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm',
                'placeholder': '(555) 123-4567',
                'type': 'tel'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm',
                'placeholder': 'patient@example.com'
            }),
        }
        help_texts = {
            'mrn': 'Unique medical record number for this patient',
            'ssn': 'Social Security Number (optional, encrypted)',
            'address': 'Patient address (encrypted)',
            'phone': 'Patient phone number (encrypted)',
            'email': 'Patient email address (encrypted)',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # If editing an existing patient, populate date_of_birth from the encrypted field
        if self.instance and self.instance.pk:
            dob = self.instance.get_date_of_birth()
            if dob:
                self.fields['date_of_birth'].initial = dob
    
    def clean_date_of_birth(self):
        """Validate date of birth."""
        dob = self.cleaned_data.get('date_of_birth')
        if dob:
            # Validate that date is not in the future
            if dob > date.today():
                raise ValidationError("Date of birth cannot be in the future.")
            
            # Validate reasonable age range (not older than 150 years)
            if dob < date(1850, 1, 1):
                raise ValidationError("Date of birth is too far in the past.")
        
        return dob
    
    def clean_ssn(self):
        """Validate and format SSN."""
        ssn = self.cleaned_data.get('ssn')
        if ssn:
            # Remove any non-digit characters
            ssn_digits = ''.join(filter(str.isdigit, ssn))
            
            # Validate length
            if len(ssn_digits) != 9:
                raise ValidationError("SSN must contain exactly 9 digits.")
            
            # Format as XXX-XX-XXXX
            return f"{ssn_digits[:3]}-{ssn_digits[3:5]}-{ssn_digits[5:]}"
        
        return ssn
    
    def clean_mrn(self):
        """Validate MRN uniqueness, checking both active and soft-deleted patients."""
        mrn = self.cleaned_data.get('mrn')
        if mrn:
            # Check for uniqueness in active patients
            queryset = Patient.objects.filter(mrn=mrn)
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            
            if queryset.exists():
                raise ValidationError("A patient with this MRN already exists.")
            
            # Also check soft-deleted patients (they still block MRN reuse at DB level)
            soft_deleted_queryset = Patient.all_objects.filter(mrn=mrn, deleted_at__isnull=False)
            if self.instance and self.instance.pk:
                soft_deleted_queryset = soft_deleted_queryset.exclude(pk=self.instance.pk)
            
            if soft_deleted_queryset.exists():
                from django.conf import settings
                if settings.DEBUG:
                    raise ValidationError(
                        f"A patient with MRN '{mrn}' was previously deleted but still exists in the database. "
                        "Please permanently remove soft-deleted patients using the cleanup utility before reusing this MRN."
                    )
                else:
                    raise ValidationError("A patient with this MRN already exists.")
        
        return mrn
    
    def save(self, commit=True):
        """Save the patient with proper date conversion."""
        patient = super().save(commit=False)
        
        # Convert date_of_birth to string format for encrypted storage
        dob = self.cleaned_data.get('date_of_birth')
        if dob:
            patient.set_date_of_birth(dob)
        else:
            patient.date_of_birth = None
        
        if commit:
            patient.save()
        
        return patient
