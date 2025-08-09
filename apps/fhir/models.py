from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
import json
import uuid


class FHIRMergeConfiguration(models.Model):
    """
    Model for storing FHIR merge configuration profiles.
    
    Allows different merge behaviors for different scenarios like
    initial import, routine updates, or reconciliation operations.
    """
    
    # Profile identification
    name = models.CharField(
        max_length=100, 
        unique=True,
        help_text="Unique name for this configuration profile"
    )
    description = models.TextField(
        blank=True,
        help_text="Description of when to use this configuration"
    )
    
    # Profile metadata
    is_default = models.BooleanField(
        default=False,
        help_text="Whether this is the default configuration profile"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this configuration is currently active"
    )
    
    # Core merge behavior settings
    validate_fhir = models.BooleanField(
        default=True,
        help_text="Perform FHIR validation on resources"
    )
    resolve_conflicts = models.BooleanField(
        default=True,
        help_text="Enable automatic conflict resolution"
    )
    deduplicate_resources = models.BooleanField(
        default=True,
        help_text="Enable automatic resource deduplication"
    )
    create_provenance = models.BooleanField(
        default=True,
        help_text="Create provenance tracking for all operations"
    )
    
    # Conflict resolution settings
    CONFLICT_STRATEGIES = [
        ('newest_wins', 'Newest Data Wins'),
        ('preserve_both', 'Preserve Both Values'),
        ('manual_review', 'Flag for Manual Review'),
        ('confidence_based', 'Use Confidence Scores'),
    ]
    
    default_conflict_strategy = models.CharField(
        max_length=20,
        choices=CONFLICT_STRATEGIES,
        default='newest_wins',
        help_text="Default conflict resolution strategy"
    )
    
    # Deduplication settings
    deduplication_tolerance_hours = models.IntegerField(
        default=24,
        help_text="Time window for considering resources as potential duplicates"
    )
    near_duplicate_threshold = models.FloatField(
        default=0.9,
        help_text="Similarity threshold for near-duplicate detection (0.0-1.0)"
    )
    fuzzy_duplicate_threshold = models.FloatField(
        default=0.7,
        help_text="Similarity threshold for fuzzy duplicate detection (0.0-1.0)"
    )
    
    # Performance settings
    max_processing_time_seconds = models.IntegerField(
        default=300,
        help_text="Maximum time allowed for merge processing (seconds)"
    )
    
    # Advanced configuration (JSON field for complex settings)
    advanced_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Advanced configuration options in JSON format"
    )
    
    # Audit fields
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='created_fhir_configs',
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'fhir_merge_configurations'
        verbose_name = 'FHIR Merge Configuration'
        verbose_name_plural = 'FHIR Merge Configurations'
        ordering = ['-is_default', 'name']
    
    def __str__(self):
        return f"{self.name}" + (" (default)" if self.is_default else "")
    
    def clean(self):
        """Validate the configuration settings."""
        super().clean()
        
        # Validate threshold values
        if not (0.0 <= self.near_duplicate_threshold <= 1.0):
            raise ValidationError("Near duplicate threshold must be between 0.0 and 1.0")
        
        if not (0.0 <= self.fuzzy_duplicate_threshold <= 1.0):
            raise ValidationError("Fuzzy duplicate threshold must be between 0.0 and 1.0")
        
        if self.deduplication_tolerance_hours < 0:
            raise ValidationError("Deduplication tolerance hours must be non-negative")
        
        if self.max_processing_time_seconds <= 0:
            raise ValidationError("Max processing time must be positive")
        
        # Validate advanced config JSON
        if self.advanced_config:
            try:
                json.dumps(self.advanced_config)
            except (TypeError, ValueError) as e:
                raise ValidationError(f"Invalid JSON in advanced_config: {e}")
    
    def save(self, *args, **kwargs):
        # Ensure only one default configuration
        if self.is_default:
            FHIRMergeConfiguration.objects.filter(is_default=True).update(is_default=False)
        
        self.full_clean()
        super().save(*args, **kwargs)
    
    def to_dict(self):
        """Convert configuration to dictionary format for use in merge service."""
        base_config = {
            'profile_name': self.name,
            'validate_fhir': self.validate_fhir,
            'resolve_conflicts': self.resolve_conflicts,
            'deduplicate_resources': self.deduplicate_resources,
            'create_provenance': self.create_provenance,
            'conflict_resolution_strategy': self.default_conflict_strategy,
            'deduplication_tolerance_hours': self.deduplication_tolerance_hours,
            'near_duplicate_threshold': self.near_duplicate_threshold,
            'fuzzy_duplicate_threshold': self.fuzzy_duplicate_threshold,
            'max_processing_time_seconds': self.max_processing_time_seconds,
        }
        
        # Merge with advanced configuration
        if self.advanced_config:
            base_config.update(self.advanced_config)
        
        return base_config
    
    @classmethod
    def get_default_config(cls):
        """Get the default configuration profile."""
        try:
            return cls.objects.get(is_default=True, is_active=True)
        except cls.DoesNotExist:
            # Return a basic configuration if no default exists
            return cls(
                name='default',
                description='Default configuration',
                is_default=True,
                is_active=True
            )
    
    @classmethod
    def get_config_by_name(cls, name):
        """Get configuration by name."""
        try:
            return cls.objects.get(name=name, is_active=True)
        except cls.DoesNotExist:
            return cls.get_default_config()


class FHIRMergeConfigurationAudit(models.Model):
    """
    Audit trail for configuration changes.
    """
    configuration = models.ForeignKey(
        FHIRMergeConfiguration,
        on_delete=models.CASCADE,
        related_name='audit_trail'
    )
    
    ACTION_CHOICES = [
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('activated', 'Activated'),
        ('deactivated', 'Deactivated'),
        ('deleted', 'Deleted'),
    ]
    
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    changes = models.JSONField(
        default=dict,
        help_text="JSON representation of changes made"
    )
    performed_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'fhir_merge_configuration_audit'
        verbose_name = 'FHIR Merge Configuration Audit'
        verbose_name_plural = 'FHIR Merge Configuration Audits'
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.configuration.name} - {self.action} at {self.timestamp}"


class FHIRMergeOperation(models.Model):
    """
    Model for tracking FHIR merge operations and their status.
    
    Provides a complete audit trail of merge operations including status,
    results, errors, and performance metrics.
    """
    
    # Operation identification
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for this merge operation"
    )
    
    # Related objects
    patient = models.ForeignKey(
        'patients.Patient',
        on_delete=models.PROTECT,
        related_name='fhir_merge_operations',
        help_text="Patient this merge operation is for"
    )
    configuration = models.ForeignKey(
        FHIRMergeConfiguration,
        on_delete=models.PROTECT,
        related_name='merge_operations',
        help_text="Configuration profile used for this merge"
    )
    document = models.ForeignKey(
        'documents.Document',
        on_delete=models.PROTECT,
        related_name='fhir_merge_operations',
        null=True,
        blank=True,
        help_text="Document being merged (for single document operations)"
    )
    
    # Operation metadata
    operation_type = models.CharField(
        max_length=20,
        choices=[
            ('single_document', 'Single Document Merge'),
            ('batch_documents', 'Batch Document Merge'),
            ('reconciliation', 'Data Reconciliation'),
            ('manual_merge', 'Manual Merge Operation'),
        ],
        default='single_document',
        help_text="Type of merge operation being performed"
    )
    
    # Status tracking
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('partial_success', 'Partial Success'),
    ]
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        help_text="Current status of the merge operation"
    )
    
    # Progress tracking
    progress_percentage = models.IntegerField(
        default=0,
        help_text="Progress percentage (0-100)"
    )
    current_step = models.CharField(
        max_length=100,
        blank=True,
        help_text="Current processing step description"
    )
    
    # Timing information
    created_at = models.DateTimeField(
        default=timezone.now,
        help_text="When the operation was created"
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the operation started processing"
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the operation completed"
    )
    
    # Result tracking
    merge_result = models.JSONField(
        default=dict,
        blank=True,
        help_text="Complete merge result object with statistics"
    )
    error_details = models.JSONField(
        default=dict,
        blank=True,
        help_text="Error details if operation failed"
    )
    
    # Performance metrics
    processing_time_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Total processing time in seconds"
    )
    resources_processed = models.IntegerField(
        default=0,
        help_text="Number of FHIR resources processed"
    )
    conflicts_detected = models.IntegerField(
        default=0,
        help_text="Number of conflicts detected"
    )
    conflicts_resolved = models.IntegerField(
        default=0,
        help_text="Number of conflicts resolved"
    )
    
    # User tracking
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='created_merge_operations',
        help_text="User who initiated this operation"
    )
    
    # Webhook tracking
    webhook_sent = models.BooleanField(
        default=False,
        help_text="Whether webhook notification has been sent"
    )
    webhook_url = models.URLField(
        blank=True,
        help_text="URL to send webhook notification to"
    )
    webhook_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When webhook was sent"
    )
    
    class Meta:
        db_table = 'fhir_merge_operations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['patient', 'status']),
            models.Index(fields=['created_by', 'created_at']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['operation_type', 'status']),
        ]
    
    def __str__(self):
        return f"Merge Operation {self.id} ({self.status}) for {self.patient}"
    
    @property
    def is_completed(self):
        """Check if operation is in a completed state."""
        return self.status in ['completed', 'failed', 'cancelled', 'partial_success']
    
    @property
    def is_successful(self):
        """Check if operation completed successfully."""
        return self.status in ['completed', 'partial_success']
    
    @property
    def duration(self):
        """Get operation duration if completed."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    def update_progress(self, percentage: int, step_description: str = ''):
        """Update operation progress."""
        self.progress_percentage = max(0, min(100, percentage))
        if step_description:
            self.current_step = step_description
        self.save(update_fields=['progress_percentage', 'current_step'])
    
    def mark_started(self):
        """Mark operation as started."""
        self.status = 'processing'
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])
    
    def mark_completed(self, merge_result: dict = None, error_details: dict = None):
        """Mark operation as completed."""
        self.completed_at = timezone.now()
        if self.started_at:
            self.processing_time_seconds = (self.completed_at - self.started_at).total_seconds()
        
        if error_details:
            self.status = 'failed'
            self.error_details = error_details
        else:
            self.status = 'completed'
            if merge_result:
                self.merge_result = merge_result
                # Extract metrics from merge result
                if hasattr(merge_result, 'resources_added'):
                    self.resources_processed = merge_result.resources_added
                if hasattr(merge_result, 'conflicts_detected'):
                    self.conflicts_detected = merge_result.conflicts_detected
                if hasattr(merge_result, 'conflicts_resolved'):
                    self.conflicts_resolved = merge_result.conflicts_resolved
        
        self.progress_percentage = 100
        self.save(update_fields=[
            'status', 'completed_at', 'processing_time_seconds', 
            'merge_result', 'error_details', 'progress_percentage',
            'resources_processed', 'conflicts_detected', 'conflicts_resolved'
        ])
    
    def get_summary(self):
        """Get a summary of the operation for API responses."""
        return {
            'id': str(self.id),
            'patient_id': self.patient.id,
            'operation_type': self.operation_type,
            'status': self.status,
            'progress_percentage': self.progress_percentage,
            'current_step': self.current_step,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'processing_time_seconds': self.processing_time_seconds,
            'resources_processed': self.resources_processed,
            'conflicts_detected': self.conflicts_detected,
            'conflicts_resolved': self.conflicts_resolved,
            'is_completed': self.is_completed,
            'is_successful': self.is_successful,
        }
