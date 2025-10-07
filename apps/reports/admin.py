"""
Admin configuration for reports module.
"""

from django.contrib import admin
from .models import ReportConfiguration, GeneratedReport


@admin.register(ReportConfiguration)
class ReportConfigurationAdmin(admin.ModelAdmin):
    """Admin interface for report configurations."""
    
    list_display = ['name', 'report_type', 'created_by', 'is_favorite', 'created_at']
    list_filter = ['report_type', 'is_favorite', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at', 'created_by', 'updated_by']
    
    fieldsets = (
        ('Report Information', {
            'fields': ('name', 'report_type', 'description', 'is_favorite')
        }),
        ('Parameters', {
            'fields': ('parameters',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_by', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        """Set created_by/updated_by on save."""
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(GeneratedReport)
class GeneratedReportAdmin(admin.ModelAdmin):
    """Admin interface for generated reports."""
    
    list_display = ['id', 'configuration', 'format', 'status', 'file_size_mb', 'generation_time', 'created_at']
    list_filter = ['format', 'status', 'created_at']
    search_fields = ['configuration__name', 'error_message']
    readonly_fields = ['created_at', 'updated_at', 'created_by', 'updated_by', 'file_size_mb']
    
    fieldsets = (
        ('Report Information', {
            'fields': ('configuration', 'format', 'status')
        }),
        ('File Details', {
            'fields': ('file_path', 'file_size', 'file_size_mb')
        }),
        ('Generation Details', {
            'fields': ('generation_time', 'parameters_snapshot', 'error_message')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_by', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        """Set created_by/updated_by on save."""
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
