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
    
    # File information
    filename = models.CharField(
        max_length=255,
        help_text="Original filename as uploaded"
    )
    file = models.FileField(
        upload_to=document_upload_path,
        validators=[
            FileExtensionValidator(allowed_extensions=['pdf']),
            validate_file_size
        ],
        help_text="Uploaded document file (PDF only)"
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
    
    # Content and processing results
    original_text = models.TextField(
        blank=True,
        help_text="Extracted text from PDF"
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
    
    # Document metadata
    notes = models.TextField(
        blank=True,
        help_text="Additional notes about this document"
    )
    
    class Meta:
        db_table = 'documents'
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['patient', 'status']),
            models.Index(fields=['status', 'uploaded_at']),
            models.Index(fields=['uploaded_at']),
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
    
    def can_retry_processing(self):
        """Check if document can be retried for processing."""
        return self.status == 'failed' and self.processing_attempts < 3
    
    def increment_processing_attempts(self):
        """Increment the processing attempts counter."""
        self.processing_attempts += 1
        self.save(update_fields=['processing_attempts'])


class ParsedData(BaseModel):
    """
    Model for AI-extracted data from documents.
    Stores both raw extraction results and FHIR-formatted data.
    """
    
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
    
    # Review and approval
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_parsed_data',
        help_text="User who reviewed this parsed data"
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When data was reviewed"
    )
    is_approved = models.BooleanField(
        default=False,
        help_text="Whether extracted data is approved for merging"
    )
    
    # Quality metrics
    extraction_quality_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Quality score for extraction (0.0-1.0)"
    )
    
    # Notes and corrections
    review_notes = models.TextField(
        blank=True,
        help_text="Notes from manual review"
    )
    corrections = models.JSONField(
        default=dict,
        help_text="Manual corrections to extracted data"
    )
    
    class Meta:
        db_table = 'parsed_data'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['patient', 'is_merged']),
            models.Index(fields=['document', 'is_approved']),
            models.Index(fields=['merged_at']),
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
        """Approve the extracted data for merging."""
        self.is_approved = True
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        if notes:
            self.review_notes = notes
        self.save(update_fields=['is_approved', 'reviewed_by', 'reviewed_at', 'review_notes'])
    
    def get_fhir_resource_count(self):
        """Get count of FHIR resources in this parsed data."""
        if not self.fhir_delta_json:
            return 0
        
        count = 0
        for resource_type, resources in self.fhir_delta_json.items():
            if isinstance(resources, list):
                count += len(resources)
            elif isinstance(resources, dict):
                count += 1
        return count
    
    def has_high_confidence_extraction(self, threshold=0.8):
        """Check if extraction has high confidence score."""
        return (self.extraction_confidence is not None and 
                self.extraction_confidence >= threshold)
