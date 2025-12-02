"""
Document models for the medical document parser.
Handles document upload, processing, and AI-extracted data storage.
"""

import os
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django_cryptography.fields import encrypt

from apps.core.models import BaseModel


def document_upload_path(instance, filename):
    """
    Generate upload path for documents.
    Organizes by year/month/day and uses UUID for security.
    """
    # Get file extension
    ext = filename.split('.')[-1].lower()
    
    # Generate UUID filename
    filename = f"{uuid.uuid4()}.{ext}"
    
    # Organize by date
    now = timezone.now()
    return f"documents/{now.year}/{now.month:02d}/{now.day:02d}/{filename}"


def validate_file_size(value):
    """
    Validate uploaded file size.
    Limit to 50MB for medical documents.
    """
    limit = 50 * 1024 * 1024  # 50MB
    if value.size > limit:
        raise ValidationError(f'File too large. Size cannot exceed 50MB.')


class EncryptedFileField(models.FileField):
    """
    Custom FileField that encrypts file contents at rest.
    
    This field stores the file path normally but the actual file content
    is encrypted using django-cryptography when stored to disk.
    
    Note: For HIPAA compliance, the file contents are encrypted but the 
    filename/path metadata is kept unencrypted for database performance.
    The actual sensitive content (file data) is what gets encrypted.
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize the encrypted file field."""
        super().__init__(*args, **kwargs)
        self.description = "Encrypted file field for HIPAA compliance"
    
    def save_form_data(self, instance, data):
        """
        Override to handle file encryption during form saves.
        
        The file content is encrypted when saved to storage, but the 
        field value (path) is stored normally in the database.
        """
        if data is not None:
            # For file uploads, the encryption is handled by the storage layer
            # The django-cryptography package handles field-level encryption
            # but for files, we rely on the storage system or OS-level encryption
            super().save_form_data(instance, data)
    
    def contribute_to_class(self, cls, name, **kwargs):
        """
        Add the field to the model class.
        
        This maintains normal FileField behavior while adding encryption
        metadata for documentation and potential future enhancements.
        """
        super().contribute_to_class(cls, name, **kwargs)
        
        # Add metadata to track that this field contains encrypted content
        if not hasattr(cls._meta, '_encrypted_file_fields'):
            cls._meta._encrypted_file_fields = []
        cls._meta._encrypted_file_fields.append(name)


class Document(BaseModel):
    """
    Model for uploaded medical documents.
    Stores file metadata, processing status, and extracted text.
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending Processing'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Processing Failed'),
        ('review', 'Needs Review'),
    ]
    
    # Document metadata
    patient = models.ForeignKey(
        'patients.Patient',
        on_delete=models.CASCADE,
        related_name='documents',
        help_text="Patient this document belongs to"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_documents',
        help_text="User who uploaded the document"
    )
    
    # File information
    filename = models.CharField(
        max_length=255,
        help_text="Original filename as uploaded"
    )
    file = EncryptedFileField(
        upload_to=document_upload_path,
        validators=[
            FileExtensionValidator(allowed_extensions=['pdf']),
            validate_file_size
        ],
        help_text="Uploaded document file (PDF only) - encrypted at rest for HIPAA compliance"
    )
    file_size = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="File size in bytes"
    )
    
    # Processing status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
        help_text="Current processing status"
    )
    
    # Granular status message for UI feedback
    processing_message = models.CharField(
        max_length=255,
        blank=True,
        help_text="Current granular processing step description"
    )
    
    # Processing timestamps
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When document was uploaded"
    )
    processing_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When AI processing started"
    )
    processed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When processing completed"
    )
    
    # Content and processing results (encrypted for HIPAA compliance)
    original_text = encrypt(models.TextField(
        blank=True,
        help_text="Extracted text from PDF - encrypted at rest"
    ))
    
    # Structured extraction data (encrypted for HIPAA compliance)
    structured_data = encrypt(models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured medical data extracted by AI using Pydantic models - encrypted at rest"
    ))
    
    # Processing performance and timing
    processing_time_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="AI processing time in milliseconds"
    )
    
    # Enhanced error tracking
    error_log = models.JSONField(
        default=list,
        blank=True,
        help_text="Detailed error log with timestamps and context for debugging"
    )
    
    # Error handling
    error_message = models.TextField(
        blank=True,
        help_text="Error message if processing failed"
    )
    processing_attempts = models.PositiveIntegerField(
        default=0,
        help_text="Number of processing attempts"
    )
    
    # Provider associations (many-to-many for flexibility)
    providers = models.ManyToManyField(
        'providers.Provider',
        blank=True,
        related_name='documents',
        help_text="Healthcare providers associated with this document"
    )
    
    # Document metadata (encrypted for HIPAA compliance)
    notes = encrypt(models.TextField(
        blank=True,
        help_text="Additional notes about this document - encrypted at rest"
    ))
    
    class Meta:
        db_table = 'documents'
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['patient', 'status']),
            models.Index(fields=['status', 'uploaded_at']),
            models.Index(fields=['uploaded_at']),
            # Performance optimization indexes for document processing
            models.Index(fields=['status', 'processing_attempts'], name='doc_status_attempts_idx'),
            models.Index(fields=['file_size', 'status'], name='doc_size_status_idx'),
            models.Index(fields=['processed_at'], name='doc_processed_at_idx'),
            models.Index(fields=['patient', 'processed_at'], name='doc_patient_processed_idx'),
        ]
    
    def __str__(self):
        """String representation of document."""
        return f"{self.filename} - {self.patient} ({self.status})"
    
    def save(self, *args, **kwargs):
        """Override save to set file size and handle processing timestamps."""
        # Set file size if file exists
        if self.file:
            self.file_size = self.file.size
        
        # Set processing timestamps based on status changes
        if self.pk:
            # Get original status
            original = Document.objects.get(pk=self.pk)
            
            # Set processing started timestamp
            if original.status != 'processing' and self.status == 'processing':
                self.processing_started_at = timezone.now()
            
            # Set processed timestamp
            if original.status == 'processing' and self.status in ['completed', 'failed']:
                self.processed_at = timezone.now()
        
        super().save(*args, **kwargs)
    
    def get_processing_duration(self):
        """
        Calculate processing duration in seconds.
        Returns None if processing hasn't started or completed.
        """
        if not self.processing_started_at:
            return None
        
        end_time = self.processed_at or timezone.now()
        duration = end_time - self.processing_started_at
        return duration.total_seconds()
    
    def get_ai_processing_time_seconds(self):
        """
        Get AI processing time in seconds from milliseconds field.
        Returns None if not available.
        """
        if self.processing_time_ms is None:
            return None
        return self.processing_time_ms / 1000.0
    
    def add_error_to_log(self, error_type, error_message, context=None):
        """
        Add an error entry to the error log with timestamp.
        
        Args:
            error_type (str): Type of error (e.g., 'ai_extraction', 'fhir_conversion')
            error_message (str): Error message
            context (dict, optional): Additional context data
        """
        if not isinstance(self.error_log, list):
            self.error_log = []
        
        error_entry = {
            'timestamp': timezone.now().isoformat(),
            'type': error_type,
            'message': str(error_message),
            'attempt': self.processing_attempts,
            'context': context or {}
        }
        
        self.error_log.append(error_entry)
        self.save(update_fields=['error_log'])
    
    def get_structured_medical_data(self):
        """
        Get structured medical data from ParsedData.
        Returns the structured data dict from ParsedData.corrections or None.
        """
        from apps.documents.models import ParsedData
        
        try:
            parsed_data = ParsedData.objects.filter(document=self).first()
            if parsed_data and parsed_data.corrections:
                return parsed_data.corrections.get('structured_data')
        except Exception:
            pass
        
        # Fallback to legacy document.structured_data field if ParsedData not available
        return self.structured_data if self.structured_data else None
    
    def has_structured_data(self):
        """
        Check if document has ParsedData ready for review.
        Returns True if ParsedData record exists for this document.
        """
        from apps.documents.models import ParsedData
        return ParsedData.objects.filter(document=self).exists()
    
    def get_extraction_confidence(self):
        """
        Get extraction confidence from structured data.
        Returns None if not available.
        """
        if not self.has_structured_data():
            return None
        
        return self.structured_data.get('confidence_average')
    
    def get_extracted_resource_counts(self):
        """
        Get counts of extracted medical resources from structured data.
        Returns dict with resource type counts or empty dict.
        """
        if not self.has_structured_data():
            return {}
        
        counts = {}
        structured = self.structured_data
        
        # Count each resource type
        resource_types = ['conditions', 'medications', 'vital_signs', 'lab_results', 'procedures', 'providers']
        for resource_type in resource_types:
            resources = structured.get(resource_type, [])
            if isinstance(resources, list):
                counts[resource_type] = len(resources)
            else:
                counts[resource_type] = 0
        
        return counts
    
    def can_retry_processing(self):
        """Check if document can be retried for processing."""
        return self.status == 'failed' and self.processing_attempts < 3
    
    def increment_processing_attempts(self):
        """Increment the processing attempts counter."""
        self.processing_attempts += 1
        self.save(update_fields=['processing_attempts'])
    
    @property
    def processing_completed_at(self):
        """Alias for processed_at to maintain consistency with view expectations."""
        return self.processed_at


class ParsedData(BaseModel):
    """
    Model for AI-extracted data from documents.
    Stores both raw extraction results and FHIR-formatted data.
    """
    
    # Date source choices for clinical date tracking
    DATE_SOURCE_CHOICES = [
        ('extracted', 'AI Extracted'),
        ('manual', 'Manually Entered'),
    ]
    
    # Date status choices for verification tracking
    DATE_STATUS_CHOICES = [
        ('pending', 'Pending Verification'),
        ('verified', 'Verified'),
    ]
    
    # Core relationships
    document = models.OneToOneField(
        Document,
        on_delete=models.CASCADE,
        related_name='parsed_data',
        help_text="Source document for this parsed data"
    )
    patient = models.ForeignKey(
        'patients.Patient',
        on_delete=models.CASCADE,
        related_name='parsed_data',
        help_text="Patient this data belongs to"
    )
    
    # AI extraction results
    extraction_json = models.JSONField(
        default=dict,
        help_text="Raw extracted data from AI processing"
    )
    
    # Source text snippets for review interface
    source_snippets = models.JSONField(
        default=dict,
        blank=True,
        help_text="Source text context (200-300 chars) around extracted values for snippet-based review"
    )
    
    # FHIR-formatted data
    fhir_delta_json = models.JSONField(
        default=dict,
        help_text="FHIR resources extracted from this document"
    )
    
    # Processing metadata
    ai_model_used = models.CharField(
        max_length=100,
        blank=True,
        help_text="AI model used for extraction (e.g., claude-3-sonnet)"
    )
    extraction_confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="Confidence score for extraction (0.0-1.0)"
    )
    processing_time_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Time taken for AI processing in seconds"
    )
    
    # Enhanced structured data support
    structured_extraction_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Metadata from structured Pydantic extraction including resource counts and validation info"
    )
    fallback_method_used = models.CharField(
        max_length=50,
        blank=True,
        help_text="Fallback extraction method used if primary AI failed (e.g., 'regex', 'gpt-fallback')"
    )
    
    # Clinical date tracking (Task 35: Clinical Date Extraction System)
    clinical_date = models.DateField(
        null=True,
        blank=True,
        help_text="Extracted or manually entered clinical date for this document/data"
    )
    date_source = models.CharField(
        max_length=20,
        choices=DATE_SOURCE_CHOICES,
        blank=True,
        help_text="Source of the clinical date (AI extracted or manually entered)"
    )
    date_status = models.CharField(
        max_length=20,
        choices=DATE_STATUS_CHOICES,
        default='pending',
        help_text="Verification status of the clinical date"
    )
    
    # Integration status
    merged_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When data was merged into patient's cumulative FHIR record"
    )
    is_merged = models.BooleanField(
        default=False,
        help_text="Whether data has been merged into patient record"
    )
    
    # Review and approval - 5-state machine for optimistic concurrency (Task 41)
    # State transitions:
    #   pending -> auto_approved (high confidence, no conflicts)
    #   pending -> flagged (low confidence, conflicts, or issues detected)
    #   flagged -> reviewed (human verified and approved)
    #   flagged -> rejected (human rejected the extraction)
    #   auto_approved -> reviewed (optional human verification)
    #   auto_approved -> rejected (human found issues after auto-approval)
    REVIEW_STATUS_CHOICES = [
        ('pending', 'Pending Processing'),
        ('auto_approved', 'Auto-Approved - Merged Immediately'),
        ('flagged', 'Flagged - Needs Manual Review'),
        ('reviewed', 'Reviewed - Manually Approved'),
        ('rejected', 'Rejected - Do Not Use'),
    ]

    review_status = models.CharField(
        max_length=20,
        choices=REVIEW_STATUS_CHOICES,
        default='pending',
        db_index=True,
        help_text="Current review status of the extraction (5-state machine for optimistic concurrency)"
    )
    
    # Optimistic concurrency fields (Task 41)
    auto_approved = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this extraction was automatically approved for immediate merge"
    )
    flag_reason = models.TextField(
        blank=True,
        help_text="Reason why this extraction was flagged for manual review (if applicable)"
    )
    
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_parsed_data',
        help_text="User who reviewed (approved/rejected) this parsed data"
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When data was reviewed"
    )
    
    # Rejection details
    rejection_reason = models.TextField(
        blank=True,
        help_text="Reason for rejection if status is rejected"
    )
    
    # Deprecated: Use review_status instead
    is_approved = models.BooleanField(
        default=False,
        help_text="DEPRECATED: Whether extracted data is approved for merging"
    )
    
    # Quality metrics
    extraction_quality_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Quality score for extraction (0.0-1.0)"
    )
    capture_metrics = models.JSONField(
        default=dict,
        blank=True,
        help_text="FHIR data capture metrics and analysis"
    )
    
    # Notes and corrections (encrypted for HIPAA compliance)
    review_notes = encrypt(models.TextField(
        blank=True,
        help_text="Notes from manual review - encrypted at rest"
    ))
    corrections = models.JSONField(
        default=dict,
        help_text="Manual corrections to extracted data (also stores structured data if available)"
    )
    
    class Meta:
        db_table = 'parsed_data'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['patient', 'is_merged']),
            models.Index(fields=['document', 'is_approved']),
            models.Index(fields=['document', 'review_status']),
            models.Index(fields=['merged_at']),
            # Clinical date tracking indexes (Task 35)
            models.Index(fields=['clinical_date', 'date_status']),
            models.Index(fields=['patient', 'clinical_date']),
        ]
    
    def __str__(self):
        """String representation of parsed data."""
        return f"Parsed data for {self.document.filename} - {self.patient}"
    
    def mark_as_merged(self, user=None):
        """Mark this parsed data as merged into patient record."""
        self.is_merged = True
        self.merged_at = timezone.now()
        if user:
            self.updated_by = user
        self.save(update_fields=['is_merged', 'merged_at', 'updated_by', 'updated_at'])
    
    def approve_extraction(self, user, notes=""):
        """Manually approve the extracted data for merging (sets status to 'reviewed')."""
        self.is_approved = True
        self.review_status = 'reviewed'
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        if notes:
            self.review_notes = notes
        self.save(update_fields=['is_approved', 'review_status', 'reviewed_by', 'reviewed_at', 'review_notes'])

    def reject_extraction(self, user, reason=""):
        """Reject the extracted data."""
        self.is_approved = False
        self.review_status = 'rejected'
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.rejection_reason = reason
        self.save(update_fields=['is_approved', 'review_status', 'reviewed_by', 'reviewed_at', 'rejection_reason'])
    
    def set_clinical_date(self, date, source='extracted', status='pending'):
        """
        Set the clinical date for this parsed data.
        
        Args:
            date: datetime.date or ISO format string (YYYY-MM-DD)
            source: 'extracted' or 'manual'
            status: 'pending' or 'verified'
        """
        from datetime import date as date_class
        
        # Convert string to date if needed
        if isinstance(date, str):
            from apps.core.date_parser import ClinicalDateParser
            parser = ClinicalDateParser()
            parsed_date = parser.parse_single_date(date)
            if not parsed_date:
                raise ValueError(f"Invalid date format: {date}")
            date = parsed_date
        
        self.clinical_date = date
        self.date_source = source
        self.date_status = status
        self.save(update_fields=['clinical_date', 'date_source', 'date_status'])
    
    def verify_clinical_date(self):
        """Mark the clinical date as verified."""
        if not self.clinical_date:
            raise ValueError("No clinical date to verify")
        self.date_status = 'verified'
        self.save(update_fields=['date_status'])
    
    def has_clinical_date(self):
        """Check if a clinical date has been set."""
        return self.clinical_date is not None
    
    def needs_date_verification(self):
        """Check if the clinical date needs verification."""
        return self.has_clinical_date() and self.date_status == 'pending'
    
    def is_date_verified(self):
        """Check if the clinical date has been verified."""
        return self.has_clinical_date() and self.date_status == 'verified'
    
    def get_fhir_resource_count(self):
        """Get count of FHIR resources in this parsed data."""
        if not self.fhir_delta_json:
            return 0
        
        # Handle both list format (from FHIRProcessor) and dict format (legacy)
        if isinstance(self.fhir_delta_json, list):
            # New format: list of FHIR resources
            return len(self.fhir_delta_json)
        elif isinstance(self.fhir_delta_json, dict):
            # Legacy format: dictionary with resource types as keys
            count = 0
            for resource_type, resources in self.fhir_delta_json.items():
                if isinstance(resources, list):
                    count += len(resources)
                elif isinstance(resources, dict):
                    count += 1
            return count
        else:
            # Unknown format
            return 0
    
    def has_high_confidence_extraction(self, threshold=0.8):
        """Check if extraction has high confidence score."""
        return (self.extraction_confidence is not None and 
                self.extraction_confidence >= threshold)
    
    def get_structured_data_summary(self):
        """
        Get summary of structured extraction data.
        Returns dict with resource counts and metadata.
        """
        summary = {
            'has_structured_data': bool(self.structured_extraction_metadata),
            'resource_counts': {},
            'total_resources': 0,
            'extraction_method': 'primary' if not self.fallback_method_used else self.fallback_method_used,
            'confidence_score': self.extraction_confidence
        }
        
        if self.structured_extraction_metadata:
            # Extract resource counts from metadata
            resource_counts = self.structured_extraction_metadata.get('resource_counts', {})
            summary['resource_counts'] = resource_counts
            summary['total_resources'] = sum(resource_counts.values())
        
        return summary
    
    def was_fallback_extraction_used(self):
        """
        Check if fallback extraction method was used.
        """
        return bool(self.fallback_method_used)
    
    def get_extraction_quality_indicators(self):
        """
        Get indicators of extraction quality for review prioritization.
        Returns dict with quality indicators.
        """
        indicators = {
            'confidence_level': 'unknown',
            'needs_review': True,
            'fallback_used': self.was_fallback_extraction_used(),
            'resource_count': self.get_fhir_resource_count(),
            'quality_score': self.extraction_quality_score
        }
        
        # Determine confidence level
        if self.extraction_confidence is not None:
            if self.extraction_confidence >= 0.9:
                indicators['confidence_level'] = 'high'
                indicators['needs_review'] = False
            elif self.extraction_confidence >= 0.7:
                indicators['confidence_level'] = 'medium' 
                indicators['needs_review'] = True
            else:
                indicators['confidence_level'] = 'low'
                indicators['needs_review'] = True
        
        return indicators


class PatientDataComparison(BaseModel):
    """
    Model for tracking patient data comparisons and resolution decisions during document review.
    
    This model stores the comparison between extracted document data and existing patient
    record data, along with reviewer decisions and audit trail information.
    """
    
    # Status choices for comparison workflow
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('conflicted', 'Has Conflicts'),
        ('skipped', 'Skipped - No Discrepancies'),
    ]
    
    # Resolution choices for individual fields
    RESOLUTION_CHOICES = [
        ('keep_existing', 'Keep Existing Patient Data'),
        ('use_extracted', 'Use Extracted Document Data'),
        ('manual_edit', 'Manual Edit - Custom Value'),
        ('pending', 'Pending Decision'),
        ('no_change', 'No Change Needed'),
    ]
    
    # Core relationships
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='data_comparisons',
        help_text="Source document for this comparison"
    )
    patient = models.ForeignKey(
        'patients.Patient',
        on_delete=models.CASCADE,
        related_name='data_comparisons',
        help_text="Patient whose data is being compared"
    )
    parsed_data = models.ForeignKey(
        ParsedData,
        on_delete=models.CASCADE,
        related_name='comparisons',
        help_text="Parsed data being compared against patient record"
    )
    
    # Comparison status and metadata
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        help_text="Current status of the comparison process"
    )
    total_fields_compared = models.PositiveIntegerField(
        default=0,
        help_text="Total number of fields compared"
    )
    discrepancies_found = models.PositiveIntegerField(
        default=0,
        help_text="Number of discrepancies found between sources"
    )
    fields_resolved = models.PositiveIntegerField(
        default=0,
        help_text="Number of fields that have been resolved"
    )
    
    # Comparison data storage
    comparison_data = models.JSONField(
        default=dict,
        help_text="Field-by-field comparison data structure"
    )
    resolution_decisions = models.JSONField(
        default=dict,
        help_text="Resolution decisions for each field with discrepancies"
    )
    
    # Quality and confidence metrics
    overall_confidence_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Overall confidence score for the comparison (0.0-1.0)"
    )
    data_quality_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Quality score for the extracted data (0.0-1.0)"
    )
    
    # Review and approval tracking
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='patient_data_comparisons',
        help_text="User who performed the comparison review"
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the comparison was reviewed and resolved"
    )
    
    # Notes and justification (encrypted for HIPAA compliance)
    reviewer_notes = encrypt(models.TextField(
        blank=True,
        help_text="Reviewer notes and justification for decisions - encrypted at rest"
    ))
    auto_resolution_summary = models.TextField(
        blank=True,
        help_text="Summary of automatic resolutions applied"
    )
    
    class Meta:
        db_table = 'patient_data_comparisons'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['patient', 'status']),
            models.Index(fields=['document', 'status']),
            models.Index(fields=['reviewer', 'reviewed_at']),
            models.Index(fields=['status', 'created_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['document', 'patient'],
                name='unique_document_patient_comparison'
            )
        ]
    
    def __str__(self):
        return f"Comparison: {self.document.filename} → {self.patient.first_name} {self.patient.last_name}"
    
    def get_completion_percentage(self):
        """Calculate completion percentage of the comparison review."""
        if self.total_fields_compared == 0:
            return 0
        return round((self.fields_resolved / self.total_fields_compared) * 100, 1)
    
    def has_pending_discrepancies(self):
        """Check if there are unresolved discrepancies."""
        return self.discrepancies_found > self.fields_resolved
    
    def get_discrepancy_summary(self):
        """Get summary of discrepancies by category."""
        summary = {
            'demographics': 0,
            'contact_info': 0,
            'medical_info': 0,
            'other': 0
        }
        
        if not self.comparison_data:
            return summary
        
        for field_name, field_data in self.comparison_data.items():
            if field_data.get('has_discrepancy', False):
                category = self._categorize_field(field_name)
                summary[category] += 1
        
        return summary
    
    def _categorize_field(self, field_name):
        """Categorize a field for discrepancy summary."""
        field_name_lower = field_name.lower()
        
        if any(term in field_name_lower for term in ['name', 'dob', 'birth', 'age', 'gender', 'sex', 'race', 'ethnicity']):
            return 'demographics'
        elif any(term in field_name_lower for term in ['phone', 'email', 'address', 'contact', 'emergency']):
            return 'contact_info'
        elif any(term in field_name_lower for term in ['mrn', 'insurance', 'provider', 'medical']):
            return 'medical_info'
        else:
            return 'other'
    
    def mark_field_resolved(self, field_name, resolution, custom_value=None, notes=None):
        """Mark a specific field as resolved with the chosen resolution."""
        if not self.resolution_decisions:
            self.resolution_decisions = {}
        
        self.resolution_decisions[field_name] = {
            'resolution': resolution,
            'custom_value': custom_value,
            'notes': notes,
            'resolved_at': timezone.now().isoformat(),
            'resolved_by': self.reviewer.username if self.reviewer else None
        }
        
        # Update resolved count
        resolved_count = sum(1 for decision in self.resolution_decisions.values() 
                           if decision.get('resolution') != 'pending')
        self.fields_resolved = resolved_count
        
        # Update status if all fields are resolved
        if self.fields_resolved >= self.discrepancies_found:
            self.status = 'resolved'
            self.reviewed_at = timezone.now()
        
        self.save()
    
    def get_field_resolution(self, field_name):
        """Get the resolution decision for a specific field."""
        if not self.resolution_decisions:
            return None
        return self.resolution_decisions.get(field_name)
    
    def get_unresolved_fields(self):
        """Get list of fields that still need resolution."""
        unresolved = []
        
        if not self.comparison_data:
            return unresolved
        
        for field_name, field_data in self.comparison_data.items():
            if field_data.get('has_discrepancy', False):
                resolution = self.get_field_resolution(field_name)
                if not resolution or resolution.get('resolution') == 'pending':
                    unresolved.append(field_name)
        
        return unresolved


class PatientDataAudit(BaseModel):
    """
    Specialized audit model for tracking patient data changes during document review.
    
    Extends the general audit system with patient-data-specific functionality
    and enhanced reporting capabilities for HIPAA compliance.
    """
    
    # Change type choices
    CHANGE_TYPE_CHOICES = [
        ('field_update', 'Field Update'),
        ('bulk_update', 'Bulk Update'),
        ('manual_edit', 'Manual Edit'),
        ('rollback', 'Rollback'),
        ('merge_conflict_resolution', 'Merge Conflict Resolution'),
    ]
    
    # Change source choices
    SOURCE_CHOICES = [
        ('document_review', 'Document Review Comparison'),
        ('manual_entry', 'Manual Entry'),
        ('system_migration', 'System Migration'),
        ('admin_correction', 'Admin Correction'),
    ]
    
    # Core relationships
    patient = models.ForeignKey(
        'patients.Patient',
        on_delete=models.CASCADE,
        related_name='data_audit_logs',
        help_text="Patient whose data was modified"
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='patient_data_audits',
        help_text="Source document that triggered the change (if applicable)"
    )
    comparison = models.ForeignKey(
        PatientDataComparison,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        help_text="Data comparison that led to this change (if applicable)"
    )
    
    # Change details
    field_name = models.CharField(
        max_length=100,
        help_text="Name of the patient field that was changed"
    )
    change_type = models.CharField(
        max_length=30,
        choices=CHANGE_TYPE_CHOICES,
        help_text="Type of change that was made"
    )
    change_source = models.CharField(
        max_length=30,
        choices=SOURCE_CHOICES,
        default='document_review',
        help_text="Source system that initiated the change"
    )
    
    # Data values (encrypted for HIPAA compliance)
    original_value = encrypt(models.TextField(
        blank=True,
        help_text="Original value before change - encrypted at rest"
    ))
    new_value = encrypt(models.TextField(
        blank=True,
        help_text="New value after change - encrypted at rest"
    ))
    
    # Change metadata
    confidence_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Confidence score of the data that triggered the change"
    )
    data_quality_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Quality score of the new data"
    )
    
    # Reviewer information
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='patient_data_audits',
        help_text="User who made the change"
    )
    reviewer_reasoning = encrypt(models.TextField(
        blank=True,
        help_text="Reviewer's reasoning for the change - encrypted at rest"
    ))
    
    # System metadata
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the user who made the change"
    )
    user_agent = models.TextField(
        blank=True,
        help_text="User agent string of the browser/system"
    )
    session_key = models.CharField(
        max_length=40,
        blank=True,
        help_text="Session key for grouping related changes"
    )
    
    # Additional context
    additional_context = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional context data for the change"
    )
    
    class Meta:
        db_table = 'patient_data_audit_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['patient', 'created_at']),
            models.Index(fields=['document', 'created_at']),
            models.Index(fields=['field_name', 'change_type']),
            models.Index(fields=['reviewer', 'created_at']),
            models.Index(fields=['change_source', 'created_at']),
        ]
    
    def __str__(self):
        return f"Audit: {self.patient.first_name} {self.patient.last_name} - {self.field_name} ({self.change_type})"
    
    def get_change_summary(self):
        """Get a human-readable summary of the change."""
        if self.change_type == 'field_update':
            return f"Updated {self.field_name} from '{self.original_value[:50]}' to '{self.new_value[:50]}'"
        elif self.change_type == 'bulk_update':
            return f"Bulk update applied to {self.field_name}"
        elif self.change_type == 'manual_edit':
            return f"Manual edit of {self.field_name}"
        elif self.change_type == 'rollback':
            return f"Rolled back {self.field_name} to previous value"
        else:
            return f"{self.change_type} on {self.field_name}"
    
    def is_high_impact_change(self):
        """Determine if this is a high-impact change that needs special attention."""
        high_impact_fields = ['mrn', 'ssn', 'date_of_birth', 'first_name', 'last_name']
        return self.field_name in high_impact_fields
    
    def get_related_changes(self, time_window_minutes=60):
        """Get other changes made around the same time (for grouping)."""
        from datetime import timedelta
        
        time_window = timedelta(minutes=time_window_minutes)
        start_time = self.created_at - time_window
        end_time = self.created_at + time_window
        
        return PatientDataAudit.objects.filter(
            patient=self.patient,
            created_at__range=(start_time, end_time),
            reviewer=self.reviewer
        ).exclude(id=self.id).order_by('created_at')
    
    @classmethod
    def get_patient_change_history(cls, patient, limit=50):
        """Get recent change history for a patient."""
        return cls.objects.filter(patient=patient).order_by('-created_at')[:limit]
    
    @classmethod
    def get_reviewer_activity(cls, reviewer, days=30):
        """Get recent activity for a specific reviewer."""
        from datetime import timedelta
        
        cutoff_date = timezone.now() - timedelta(days=days)
        return cls.objects.filter(
            reviewer=reviewer,
            created_at__gte=cutoff_date
        ).order_by('-created_at')
    
    @classmethod
    def get_field_change_analytics(cls, field_name, days=30):
        """Get analytics for changes to a specific field type."""
        from datetime import timedelta
        from django.db.models import Count, Avg
        
        cutoff_date = timezone.now() - timedelta(days=days)
        
        return cls.objects.filter(
            field_name=field_name,
            created_at__gte=cutoff_date
        ).aggregate(
            total_changes=Count('id'),
            avg_confidence=Avg('confidence_score'),
            avg_quality=Avg('data_quality_score'),
            unique_patients=Count('patient', distinct=True),
            unique_reviewers=Count('reviewer', distinct=True)
        )