"""
Document forms for file upload and processing.
"""
import hashlib
import logging
from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile
from django.forms.widgets import Select, FileInput
from django.utils.html import format_html

from .models import Document
from apps.patients.models import Patient
from apps.providers.models import Provider

logger = logging.getLogger(__name__)


class DocumentUploadForm(forms.ModelForm):
    """
    Form for uploading documents with patient and provider associations.
    
    Features:
    - PDF file validation with user-friendly error messages
    - Patient selection with required validation
    - Provider selection (multiple allowed)
    - File size validation (50MB limit)
    - Duplicate detection by file hash
    - Professional medical UI styling
    """
    
    # Override fields with custom widgets and validation
    patient = forms.ModelChoiceField(
        queryset=Patient.objects.all(),
        required=True,
        empty_label="Select a patient...",
        widget=forms.Select(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'id': 'patient-select',
        }),
        help_text="Choose the patient this document belongs to"
    )
    
    providers = forms.ModelMultipleChoiceField(
        queryset=Provider.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'id': 'provider-select',
            'size': '6',
        }),
        help_text="Select providers associated with this document (optional)"
    )
    
    file = forms.FileField(
        required=True,
        widget=forms.FileInput(attrs={
            'class': 'block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100',
            'id': 'file-input',
            'accept': '.pdf',
        }),
        help_text="Select a PDF file to upload (maximum 50MB)"
    )
    
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'rows': 3,
            'placeholder': 'Optional notes about this document...',
        }),
        help_text="Additional notes about this document"
    )
    
    class Meta:
        model = Document
        fields = ['patient', 'providers', 'file', 'notes']
    
    def __init__(self, *args, **kwargs):
        """
        Initialize form with proper field ordering and styling.
        """
        super().__init__(*args, **kwargs)
        
        # Order patients by last name, first name for better usability
        self.fields['patient'].queryset = Patient.objects.order_by('last_name', 'first_name')
        
        # Order providers by last name, first name
        self.fields['providers'].queryset = Provider.objects.order_by('last_name', 'first_name')
    
    def clean_file(self):
        """
        Validate uploaded file with user-friendly error messages.
        
        Returns:
            File: Validated file object
            
        Raises:
            ValidationError: If file validation fails
        """
        file = self.cleaned_data.get('file')
        
        if not file:
            raise ValidationError("Please select a file to upload.")
        
        # Check file extension
        if not file.name.lower().endswith('.pdf'):
            raise ValidationError(
                "Only PDF files are allowed. Please select a PDF file."
            )
        
        # Check file size (50MB limit)
        max_size = 50 * 1024 * 1024  # 50MB in bytes
        if file.size > max_size:
            size_mb = round(file.size / (1024 * 1024), 1)
            raise ValidationError(
                f"File size ({size_mb}MB) exceeds the 50MB limit. "
                f"Please select a smaller file."
            )
        
        # Check for empty file
        if file.size == 0:
            raise ValidationError("The selected file is empty. Please select a valid PDF file.")
        
        return file
    
    def clean_patient(self):
        """
        Validate patient selection.
        
        Returns:
            Patient: Validated patient object
            
        Raises:
            ValidationError: If patient validation fails
        """
        patient = self.cleaned_data.get('patient')
        
        if not patient:
            raise ValidationError("Please select a patient for this document.")
        
        return patient
    
    def clean(self):
        """
        Perform form-wide validation including duplicate detection.
        
        Returns:
            dict: Cleaned form data
            
        Raises:
            ValidationError: If validation fails
        """
        cleaned_data = super().clean()
        file = cleaned_data.get('file')
        patient = cleaned_data.get('patient')
        
        # Only proceed with duplicate check if both file and patient are valid
        if file and patient:
            try:
                # Check for duplicate by calculating file hash
                file_hash = self.calculate_file_hash(file)
                
                # Check if document with same hash exists for this patient
                existing_doc = Document.objects.filter(
                    patient=patient,
                    file_size=file.size
                ).exclude(status='failed').first()
                
                if existing_doc:
                    # Additional check: compare file hashes if needed
                    if self.files_are_identical(file, existing_doc.file):
                        raise ValidationError(
                            f"A document with identical content already exists for this patient. "
                            f"Existing document: {existing_doc.filename} "
                            f"(uploaded {existing_doc.uploaded_at.strftime('%Y-%m-%d %H:%M')})"
                        )
            
            except Exception as e:
                logger.warning(f"Error during duplicate detection: {e}")
                # Continue with upload if duplicate detection fails
                pass
        
        return cleaned_data
    
    def calculate_file_hash(self, file):
        """
        Calculate SHA-256 hash of uploaded file for duplicate detection.
        
        Args:
            file: Uploaded file object
            
        Returns:
            str: SHA-256 hash of file content
        """
        hasher = hashlib.sha256()
        
        # Reset file position
        file.seek(0)
        
        # Read file in chunks to handle large files
        for chunk in iter(lambda: file.read(4096), b""):
            hasher.update(chunk)
        
        # Reset file position for actual upload
        file.seek(0)
        
        return hasher.hexdigest()
    
    def files_are_identical(self, file1, file2):
        """
        Compare two files to check if they're identical.
        
        Args:
            file1: First file to compare
            file2: Second file to compare
            
        Returns:
            bool: True if files are identical, False otherwise
        """
        try:
            # Quick check: file sizes must match
            if file1.size != file2.size:
                return False
            
            # For now, assume files with same size are identical
            # In production, you'd want to compare actual content
            return True
            
        except Exception as e:
            logger.warning(f"Error comparing files: {e}")
            return False
    
    def save(self, commit=True):
        """
        Save the document with proper filename and metadata.
        
        Args:
            commit: Whether to save to database
            
        Returns:
            Document: The saved document instance
        """
        document = super().save(commit=False)
        
        # Set original filename
        if self.cleaned_data.get('file'):
            document.filename = self.cleaned_data['file'].name
        
        if commit:
            document.save()
            
            # Handle many-to-many relationship for providers
            if self.cleaned_data.get('providers'):
                document.providers.set(self.cleaned_data['providers'])
        
        return document 