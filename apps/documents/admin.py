from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils import timezone

from .models import Document, ParsedData, PatientDataComparison, PatientDataAudit


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    """
    Admin configuration for Document model.
    Provides comprehensive management of uploaded documents.
    """
    
    list_display = [
        'filename',
        'patient',
        'status',
        'file_size_display',
        'uploaded_at',
        'processing_duration_display',
        'processing_attempts',
        'has_parsed_data',
    ]
    
    list_filter = [
        'status',
        'uploaded_at',
        'processed_at',
        'processing_attempts',
    ]
    
    search_fields = [
        'filename',
        'patient__first_name',
        'patient__last_name',
        'patient__mrn',
        'notes',
    ]
    
    readonly_fields = [
        'uploaded_at',
        'processing_started_at',
        'processed_at',
        'file_size',
        'processing_duration_display',
        'view_file_link',
    ]
    
    fieldsets = [
        ('Document Information', {
            'fields': [
                'filename',
                'patient',
                'file',
                'view_file_link',
                'file_size',
                'notes',
            ]
        }),
        ('Processing Status', {
            'fields': [
                'status',
                'processing_attempts',
                'error_message',
            ]
        }),
        ('Timestamps', {
            'fields': [
                'uploaded_at',
                'processing_started_at',
                'processed_at',
                'processing_duration_display',
            ]
        }),
        ('Associations', {
            'fields': [
                'providers',
            ]
        }),
        ('Content', {
            'fields': [
                'original_text',
            ],
            'classes': ['collapse'],
        }),
    ]
    
    filter_horizontal = ['providers']
    
    actions = ['mark_for_reprocessing', 'reset_processing_attempts']
    
    def file_size_display(self, obj):
        """Display file size in human-readable format."""
        if not obj.file_size:
            return '-'
        
        size = obj.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    file_size_display.short_description = 'File Size'
    
    def processing_duration_display(self, obj):
        """Display processing duration in human-readable format."""
        duration = obj.get_processing_duration()
        if duration is None:
            return '-'
        
        if duration < 60:
            return f"{duration:.1f}s"
        elif duration < 3600:
            minutes = duration / 60
            return f"{minutes:.1f}m"
        else:
            hours = duration / 3600
            return f"{hours:.1f}h"
    processing_duration_display.short_description = 'Processing Duration'
    
    def has_parsed_data(self, obj):
        """Check if document has associated parsed data."""
        return hasattr(obj, 'parsed_data') and obj.parsed_data is not None
    has_parsed_data.boolean = True
    has_parsed_data.short_description = 'Has Parsed Data'
    
    def view_file_link(self, obj):
        """Provide link to view the uploaded file."""
        if obj.file:
            return format_html(
                '<a href="{}" target="_blank">View File</a>',
                obj.file.url
            )
        return '-'
    view_file_link.short_description = 'File'
    
    def mark_for_reprocessing(self, request, queryset):
        """Action to mark documents for reprocessing."""
        count = 0
        for doc in queryset:
            if doc.can_retry_processing():
                doc.status = 'pending'
                doc.error_message = ''
                doc.save(update_fields=['status', 'error_message'])
                count += 1
        
        self.message_user(request, f'{count} documents marked for reprocessing.')
    mark_for_reprocessing.short_description = 'Mark selected documents for reprocessing'
    
    def reset_processing_attempts(self, request, queryset):
        """Action to reset processing attempts counter."""
        count = queryset.update(processing_attempts=0)
        self.message_user(request, f'{count} documents had processing attempts reset.')
    reset_processing_attempts.short_description = 'Reset processing attempts'


@admin.register(ParsedData)
class ParsedDataAdmin(admin.ModelAdmin):
    """
    Admin configuration for ParsedData model.
    Provides management of AI-extracted data.
    """
    
    list_display = [
        'document',
        'patient',
        'ai_model_used',
        'extraction_confidence',
        'review_status',
        'is_approved',  # Deprecated but keeping for reference
        'is_merged',
        'fhir_resource_count',
        'created_at',
    ]
    
    list_filter = [
        'review_status',
        'is_approved',
        'is_merged',
        'ai_model_used',
        'created_at',
        'merged_at',
        'reviewed_at',
    ]
    
    search_fields = [
        'document__filename',
        'patient__first_name',
        'patient__last_name',
        'patient__mrn',
        'ai_model_used',
        'review_notes',
        'rejection_reason',
    ]
    
    readonly_fields = [
        'created_at',
        'updated_at',
        'merged_at',
        'reviewed_at',
        'fhir_resource_count',
        'processing_time_display',
        'view_document_link',
    ]
    
    fieldsets = [
        ('Basic Information', {
            'fields': [
                'document',
                'view_document_link',
                'patient',
                'created_at',
                'updated_at',
            ]
        }),
        ('AI Processing', {
            'fields': [
                'ai_model_used',
                'extraction_confidence',
                'processing_time_display',
                'extraction_quality_score',
            ]
        }),
        ('Review and Approval', {
            'fields': [
                'review_status',
                'is_approved',
                'reviewed_by',
                'reviewed_at',
                'review_notes',
                'rejection_reason',
            ]
        }),
        ('Integration Status', {
            'fields': [
                'is_merged',
                'merged_at',
                'fhir_resource_count',
            ]
        }),
        ('Data Content', {
            'fields': [
                'extraction_json',
                'fhir_delta_json',
                'corrections',
            ],
            'classes': ['collapse'],
        }),
    ]
    
    actions = ['approve_extraction', 'mark_as_merged']
    
    def fhir_resource_count(self, obj):
        """Display count of FHIR resources."""
        return obj.get_fhir_resource_count()
    fhir_resource_count.short_description = 'FHIR Resources'
    
    def processing_time_display(self, obj):
        """Display processing time in human-readable format."""
        if not obj.processing_time_seconds:
            return '-'
        
        time = obj.processing_time_seconds
        if time < 60:
            return f"{time:.1f}s"
        elif time < 3600:
            minutes = time / 60
            return f"{minutes:.1f}m"
        else:
            hours = time / 3600
            return f"{hours:.1f}h"
    processing_time_display.short_description = 'Processing Time'
    
    def view_document_link(self, obj):
        """Provide link to view the source document."""
        if obj.document:
            url = reverse('admin:documents_document_change', args=[obj.document.id])
            return format_html(
                '<a href="{}">View Document</a>',
                url
            )
        return '-'
    view_document_link.short_description = 'Source Document'
    
    def approve_extraction(self, request, queryset):
        """Action to manually approve extracted data (sets status to 'reviewed')."""
        count = 0
        for parsed_data in queryset:
            # Only approve if not already reviewed or rejected
            if parsed_data.review_status not in ('reviewed', 'rejected'):
                parsed_data.approve_extraction(request.user, "Approved via admin action")
                count += 1
        
        self.message_user(request, f'{count} extractions approved (status set to reviewed).')
    approve_extraction.short_description = 'Approve selected extractions (manual review)'
    
    def mark_as_merged(self, request, queryset):
        """Action to mark data as merged."""
        count = 0
        for parsed_data in queryset:
            if not parsed_data.is_merged:
                parsed_data.mark_as_merged(request.user)
                count += 1
        
        self.message_user(request, f'{count} parsed data marked as merged.')
    mark_as_merged.short_description = 'Mark selected data as merged'


@admin.register(PatientDataComparison)
class PatientDataComparisonAdmin(admin.ModelAdmin):
    """
    Admin configuration for PatientDataComparison model.
    Provides management of patient data comparison and resolution workflow.
    """
    
    list_display = [
        'document',
        'patient',
        'status',
        'completion_percentage_display',
        'discrepancies_found',
        'fields_resolved',
        'reviewer',
        'created_at',
    ]
    
    list_filter = [
        'status',
        'created_at',
        'reviewed_at',
        'reviewer',
        'overall_confidence_score',
    ]
    
    search_fields = [
        'document__filename',
        'patient__first_name',
        'patient__last_name',
        'patient__mrn',
        'reviewer__username',
        'reviewer_notes',
    ]
    
    readonly_fields = [
        'created_at',
        'updated_at',
        'reviewed_at',
        'completion_percentage_display',
        'discrepancy_summary_display',
        'view_document_link',
        'view_patient_link',
    ]
    
    fieldsets = [
        ('Basic Information', {
            'fields': [
                'document',
                'view_document_link',
                'patient',
                'view_patient_link',
                'parsed_data',
                'status',
            ]
        }),
        ('Comparison Metrics', {
            'fields': [
                'total_fields_compared',
                'discrepancies_found',
                'fields_resolved',
                'completion_percentage_display',
                'discrepancy_summary_display',
            ]
        }),
        ('Quality Scores', {
            'fields': [
                'overall_confidence_score',
                'data_quality_score',
            ]
        }),
        ('Review Information', {
            'fields': [
                'reviewer',
                'reviewed_at',
                'reviewer_notes',
                'auto_resolution_summary',
            ]
        }),
        ('Comparison Data', {
            'fields': [
                'comparison_data',
                'resolution_decisions',
            ],
            'classes': ['collapse'],
        }),
        ('Timestamps', {
            'fields': [
                'created_at',
                'updated_at',
            ]
        }),
    ]
    
    actions = ['mark_as_resolved', 'reset_to_pending']
    
    def completion_percentage_display(self, obj):
        """Display completion percentage with visual indicator."""
        percentage = obj.get_completion_percentage()
        if percentage == 0:
            color = 'red'
        elif percentage < 50:
            color = 'orange'
        elif percentage < 100:
            color = 'blue'
        else:
            color = 'green'
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:.1f}%</span>',
            color,
            percentage
        )
    completion_percentage_display.short_description = 'Completion'
    
    def discrepancy_summary_display(self, obj):
        """Display summary of discrepancies by category."""
        summary = obj.get_discrepancy_summary()
        total = sum(summary.values())
        
        if total == 0:
            return format_html('<span style="color: green;">No discrepancies</span>')
        
        parts = []
        for category, count in summary.items():
            if count > 0:
                parts.append(f"{category}: {count}")
        
        return format_html(
            '<span style="color: orange;">{}</span>',
            ', '.join(parts)
        )
    discrepancy_summary_display.short_description = 'Discrepancies'
    
    def view_document_link(self, obj):
        """Provide link to view the source document."""
        if obj.document:
            url = reverse('admin:documents_document_change', args=[obj.document.id])
            return format_html(
                '<a href="{}">View Document</a>',
                url
            )
        return '-'
    view_document_link.short_description = 'Source Document'
    
    def view_patient_link(self, obj):
        """Provide link to view the patient record."""
        if obj.patient:
            url = reverse('admin:patients_patient_change', args=[obj.patient.id])
            return format_html(
                '<a href="{}">View Patient</a>',
                url
            )
        return '-'
    view_patient_link.short_description = 'Patient Record'
    
    def mark_as_resolved(self, request, queryset):
        """Action to mark comparisons as resolved."""
        count = 0
        for comparison in queryset:
            if comparison.status != 'resolved':
                comparison.status = 'resolved'
                comparison.reviewed_at = timezone.now()
                comparison.reviewer = request.user
                comparison.save(update_fields=['status', 'reviewed_at', 'reviewer'])
                count += 1
        
        self.message_user(request, f'{count} comparisons marked as resolved.')
    mark_as_resolved.short_description = 'Mark selected comparisons as resolved'
    
    def reset_to_pending(self, request, queryset):
        """Action to reset comparisons to pending status."""
        count = 0
        for comparison in queryset:
            if comparison.status != 'pending':
                comparison.status = 'pending'
                comparison.reviewed_at = None
                comparison.reviewer = None
                comparison.save(update_fields=['status', 'reviewed_at', 'reviewer'])
                count += 1
        
        self.message_user(request, f'{count} comparisons reset to pending.')
    reset_to_pending.short_description = 'Reset selected comparisons to pending'


@admin.register(PatientDataAudit)
class PatientDataAuditAdmin(admin.ModelAdmin):
    """
    Admin configuration for PatientDataAudit model.
    Provides comprehensive audit trail management for patient data changes.
    """
    
    list_display = [
        'patient',
        'field_name',
        'change_type',
        'change_source',
        'reviewer',
        'is_high_impact_change',
        'created_at',
    ]
    
    list_filter = [
        'change_type',
        'change_source',
        'field_name',
        'created_at',
        'reviewer',
        'confidence_score',
    ]
    
    search_fields = [
        'patient__first_name',
        'patient__last_name',
        'patient__mrn',
        'field_name',
        'reviewer__username',
        'reviewer_reasoning',
        'original_value',
        'new_value',
    ]
    
    readonly_fields = [
        'created_at',
        'updated_at',
        'change_summary_display',
        'view_patient_link',
        'view_document_link',
        'view_comparison_link',
    ]
    
    fieldsets = [
        ('Change Information', {
            'fields': [
                'patient',
                'view_patient_link',
                'field_name',
                'change_type',
                'change_source',
                'change_summary_display',
            ]
        }),
        ('Data Changes', {
            'fields': [
                'original_value',
                'new_value',
            ]
        }),
        ('Quality Metrics', {
            'fields': [
                'confidence_score',
                'data_quality_score',
            ]
        }),
        ('Review Information', {
            'fields': [
                'reviewer',
                'reviewer_reasoning',
                'document',
                'view_document_link',
                'comparison',
                'view_comparison_link',
            ]
        }),
        ('System Metadata', {
            'fields': [
                'ip_address',
                'user_agent',
                'session_key',
                'additional_context',
            ],
            'classes': ['collapse'],
        }),
        ('Timestamps', {
            'fields': [
                'created_at',
                'updated_at',
            ]
        }),
    ]
    
    actions = ['export_audit_report', 'mark_as_reviewed']
    
    def change_summary_display(self, obj):
        """Display a summary of the change."""
        summary = obj.get_change_summary()
        if obj.is_high_impact_change():
            return format_html(
                '<span style="color: red; font-weight: bold;">⚠️ {}</span>',
                summary
            )
        return summary
    change_summary_display.short_description = 'Change Summary'
    
    def view_patient_link(self, obj):
        """Provide link to view the patient record."""
        if obj.patient:
            url = reverse('admin:patients_patient_change', args=[obj.patient.id])
            return format_html(
                '<a href="{}">View Patient</a>',
                url
            )
        return '-'
    view_patient_link.short_description = 'Patient Record'
    
    def view_document_link(self, obj):
        """Provide link to view the source document."""
        if obj.document:
            url = reverse('admin:documents_document_change', args=[obj.document.id])
            return format_html(
                '<a href="{}">View Document</a>',
                url
            )
        return '-'
    view_document_link.short_description = 'Source Document'
    
    def view_comparison_link(self, obj):
        """Provide link to view the comparison record."""
        if obj.comparison:
            url = reverse('admin:documents_patientdatacomparison_change', args=[obj.comparison.id])
            return format_html(
                '<a href="{}">View Comparison</a>',
                url
            )
        return '-'
    view_comparison_link.short_description = 'Data Comparison'
    
    def export_audit_report(self, request, queryset):
        """Export audit trail as a report."""
        # This would generate a comprehensive audit report
        count = queryset.count()
        self.message_user(request, f'Audit report functionality would export {count} records.')
    export_audit_report.short_description = 'Export audit report'
    
    def mark_as_reviewed(self, request, queryset):
        """Mark audit entries as reviewed."""
        count = 0
        for audit in queryset:
            # Add a flag or note that this has been reviewed
            if not audit.additional_context:
                audit.additional_context = {}
            audit.additional_context['admin_reviewed'] = True
            audit.additional_context['reviewed_by'] = request.user.username
            audit.additional_context['reviewed_at'] = timezone.now().isoformat()
            audit.save()
            count += 1
        
        self.message_user(request, f'{count} audit entries marked as reviewed.')
    mark_as_reviewed.short_description = 'Mark selected entries as reviewed'
