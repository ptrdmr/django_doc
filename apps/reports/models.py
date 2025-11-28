"""
Report models for storing report configurations and generated reports.

This module handles:
- Report configuration storage (parameters, filters, report types)
- Generated report tracking (files, formats, timestamps)
- User-specific report access and audit trails
"""

from django.db import models
from django.conf import settings
import os
from django.utils import timezone
from apps.core.models import BaseModel


class ReportConfiguration(BaseModel):
    """
    Store report configurations for reusable report generation.
    
    Allows users to save commonly used report parameters and
    quickly regenerate reports with the same settings.
    """
    name = models.CharField(
        max_length=100,
        help_text="Descriptive name for this report configuration"
    )
    
    report_type = models.CharField(
        max_length=50,
        choices=[
            ('patient_summary', 'Patient Summary Report'),
            ('provider_activity', 'Provider Activity Report'),
            ('document_audit', 'Document Processing Audit'),
        ],
        help_text="Type of report to generate"
    )
    
    parameters = models.JSONField(
        default=dict,
        help_text="Report parameters (filters, date ranges, options)"
    )
    
    description = models.TextField(
        blank=True,
        help_text="Optional description of what this report contains"
    )
    
    is_favorite = models.BooleanField(
        default=False,
        help_text="Mark as favorite for quick access"
    )
    
    class Meta:
        db_table = 'report_configurations'
        indexes = [
            models.Index(fields=['created_by', 'report_type']),
            models.Index(fields=['created_by', 'is_favorite']),
        ]
        verbose_name = "Report Configuration"
        verbose_name_plural = "Report Configurations"
        ordering = ['-is_favorite', '-created_at']
    
    def __str__(self):
        return f"{self.name} ({self.get_report_type_display()})"
    
    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('reports:config-detail', kwargs={'pk': self.pk})


class GeneratedReport(BaseModel):
    """
    Track generated reports for download and audit purposes.
    
    Stores the actual report files and metadata about when/how
    they were generated for HIPAA compliance and user convenience.
    """
    configuration = models.ForeignKey(
        ReportConfiguration,
        on_delete=models.CASCADE,
        related_name='generated_reports',
        null=True,
        blank=True,
        help_text="Configuration used to generate this report (optional for ad-hoc reports)"
    )
    
    file_path = models.CharField(
        max_length=255,
        help_text="Path to generated report file"
    )
    
    format = models.CharField(
        max_length=10,
        choices=[
            ('pdf', 'PDF'),
            ('csv', 'CSV'),
            ('json', 'JSON'),
        ],
        default='pdf',
        help_text="Report output format"
    )
    
    file_size = models.IntegerField(
        null=True,
        blank=True,
        help_text="File size in bytes"
    )
    
    generation_time = models.FloatField(
        null=True,
        blank=True,
        help_text="Time taken to generate report (seconds)"
    )
    
    parameters_snapshot = models.JSONField(
        default=dict,
        help_text="Snapshot of parameters used (for audit)"
    )
    
    error_message = models.TextField(
        blank=True,
        help_text="Error message if generation failed"
    )
    
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('generating', 'Generating'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='pending',
        help_text="Current status of report generation"
    )
    
    class Meta:
        db_table = 'generated_reports'
        indexes = [
            models.Index(fields=['created_by', 'status']),
            models.Index(fields=['configuration', '-created_at']),
            models.Index(fields=['-created_at']),
        ]
        verbose_name = "Generated Report"
        verbose_name_plural = "Generated Reports"
        ordering = ['-created_at']
    
    def __str__(self):
        config_name = self.configuration.name if self.configuration else "Ad-hoc Report"
        return f"{config_name} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
    
    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('reports:download', kwargs={'pk': self.pk})
    
    @property
    def display_name(self):
        """
        Smart display name:
        1. "John Doe - Patient Summary" (if patient report)
        2. "Provider Activity Report" (if no patient)
        """
        # 1. If we have a snapshotted patient name, use it
        if self.parameters_snapshot and self.parameters_snapshot.get('patient_name'):
            # Clean up the type: "patient_summary" -> "Patient Summary"
            type_label = self.get_type_label()
            return f"{self.parameters_snapshot['patient_name']} - {type_label}"

        # 2. If it's a saved configuration, use that name
        if self.configuration:
            return self.configuration.name

        # 3. Fallback to the generic type
        return self.get_type_label()

    def get_type_label(self):
        """Helper to get clean type label from config or filename."""
        if self.configuration:
            return self.configuration.get_report_type_display()
        
        # Fallback map for ad-hoc reports
        type_map = {
            'patient_summary': 'Patient Summary',
            'provider_activity': 'Provider Activity',
            'document_audit': 'Document Audit',
        }
        # Try to find the key in the file path or default to generic
        for key, label in type_map.items():
            if key in self.file_path:
                return label
        return "Report"

    @property
    def file_size_mb(self):
        """Get file size in megabytes."""
        if self.file_size:
            return round(self.file_size / (1024 * 1024), 2)
        return None
