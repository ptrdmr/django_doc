from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe

from .models import Document, ParsedData


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
        'is_approved',
        'is_merged',
        'fhir_resource_count',
        'created_at',
    ]
    
    list_filter = [
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
                'is_approved',
                'reviewed_by',
                'reviewed_at',
                'review_notes',
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
        """Action to approve extracted data."""
        count = 0
        for parsed_data in queryset:
            if not parsed_data.is_approved:
                parsed_data.approve_extraction(request.user, "Approved via admin action")
                count += 1
        
        self.message_user(request, f'{count} extractions approved.')
    approve_extraction.short_description = 'Approve selected extractions'
    
    def mark_as_merged(self, request, queryset):
        """Action to mark data as merged."""
        count = 0
        for parsed_data in queryset:
            if not parsed_data.is_merged:
                parsed_data.mark_as_merged(request.user)
                count += 1
        
        self.message_user(request, f'{count} parsed data marked as merged.')
    mark_as_merged.short_description = 'Mark selected data as merged'
