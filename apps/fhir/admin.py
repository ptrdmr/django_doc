from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.contrib import messages
from django.core.exceptions import ValidationError
import json

from .models import FHIRMergeConfiguration, FHIRMergeConfigurationAudit, FHIRMergeOperation
from .configuration import MergeConfigurationService


class FHIRMergeConfigurationAuditInline(admin.TabularInline):
    """Inline display for configuration audit trail."""
    model = FHIRMergeConfigurationAudit
    extra = 0
    readonly_fields = ('action', 'changes', 'performed_by', 'timestamp')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(FHIRMergeConfiguration)
class FHIRMergeConfigurationAdmin(admin.ModelAdmin):
    """Admin interface for FHIR merge configurations."""
    
    list_display = (
        'name',
        'description_short',
        'is_default_indicator',
        'is_active',
        'default_conflict_strategy',
        'deduplication_tolerance_hours',
        'created_at'
    )
    
    list_filter = (
        'is_default',
        'is_active',
        'default_conflict_strategy',
        'validate_fhir',
        'resolve_conflicts',
        'deduplicate_resources',
        'create_provenance',
        'created_at'
    )
    
    search_fields = ('name', 'description')
    
    readonly_fields = (
        'created_at',
        'updated_at',
        'advanced_config_display'
    )
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'name',
                'description',
                'is_default',
                'is_active',
                'created_by'
            )
        }),
        ('Core Merge Behavior', {
            'fields': (
                'validate_fhir',
                'resolve_conflicts',
                'deduplicate_resources',
                'create_provenance'
            )
        }),
        ('Conflict Resolution', {
            'fields': (
                'default_conflict_strategy',
            )
        }),
        ('Deduplication Settings', {
            'fields': (
                'deduplication_tolerance_hours',
                'near_duplicate_threshold',
                'fuzzy_duplicate_threshold'
            )
        }),
        ('Performance Settings', {
            'fields': (
                'max_processing_time_seconds',
            )
        }),
        ('Advanced Configuration', {
            'fields': (
                'advanced_config',
                'advanced_config_display'
            ),
            'classes': ('collapse',)
        }),
        ('Audit Information', {
            'fields': (
                'created_at',
                'updated_at'
            ),
            'classes': ('collapse',)
        })
    )
    
    inlines = [FHIRMergeConfigurationAuditInline]
    
    actions = [
        'make_default',
        'activate_configurations',
        'deactivate_configurations'
    ]
    
    def description_short(self, obj):
        """Return truncated description."""
        if len(obj.description) > 50:
            return obj.description[:50] + "..."
        return obj.description
    description_short.short_description = "Description"
    
    def is_default_indicator(self, obj):
        """Visual indicator for default configuration."""
        if obj.is_default:
            return format_html('<span style="color: green; font-weight: bold;">✓ DEFAULT</span>')
        return ""
    is_default_indicator.short_description = "Default"
    
    def advanced_config_display(self, obj):
        """Pretty display of advanced configuration JSON."""
        if obj.advanced_config:
            try:
                formatted_json = json.dumps(obj.advanced_config, indent=2)
                return format_html('<pre style="background: #f5f5f5; padding: 10px; border-radius: 3px;">{}</pre>', 
                                 formatted_json)
            except (TypeError, ValueError):
                return "Invalid JSON"
        return "No advanced configuration"
    advanced_config_display.short_description = "Advanced Configuration (Read-Only)"
    
    def make_default(self, request, queryset):
        """Make selected configuration the default."""
        if queryset.count() != 1:
            messages.error(request, "Please select exactly one configuration to make default")
            return
        
        config = queryset.first()
        try:
            MergeConfigurationService.set_default_configuration(config, request.user)
            messages.success(request, f"Configuration '{config.name}' is now the default")
        except ValidationError as e:
            messages.error(request, str(e))
    make_default.short_description = "Make selected configuration default"
    
    def activate_configurations(self, request, queryset):
        """Activate selected configurations."""
        count = 0
        for config in queryset:
            if not config.is_active:
                MergeConfigurationService.activate_configuration(config, request.user)
                count += 1
        
        if count:
            messages.success(request, f"Activated {count} configuration(s)")
        else:
            messages.info(request, "No configurations needed activation")
    activate_configurations.short_description = "Activate selected configurations"
    
    def deactivate_configurations(self, request, queryset):
        """Deactivate selected configurations."""
        count = 0
        errors = []
        
        for config in queryset:
            if config.is_active:
                try:
                    MergeConfigurationService.deactivate_configuration(config, request.user)
                    count += 1
                except ValidationError as e:
                    errors.append(f"{config.name}: {str(e)}")
        
        if count:
            messages.success(request, f"Deactivated {count} configuration(s)")
        
        for error in errors:
            messages.error(request, error)
    deactivate_configurations.short_description = "Deactivate selected configurations"


@admin.register(FHIRMergeConfigurationAudit)
class FHIRMergeConfigurationAuditAdmin(admin.ModelAdmin):
    """Admin interface for configuration audit trail."""
    
    list_display = (
        'configuration',
        'action',
        'performed_by',
        'timestamp',
        'changes_summary'
    )
    
    list_filter = (
        'action',
        'timestamp',
        'performed_by'
    )
    
    search_fields = (
        'configuration__name',
        'performed_by__username'
    )
    
    readonly_fields = (
        'configuration',
        'action',
        'changes',
        'performed_by',
        'timestamp'
    )
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def changes_summary(self, obj):
        """Summary of changes made."""
        if obj.changes:
            field_count = len(obj.changes)
            return f"{field_count} field(s) changed"
        return "No changes recorded"
    changes_summary.short_description = "Changes"


@admin.register(FHIRMergeOperation)
class FHIRMergeOperationAdmin(admin.ModelAdmin):
    """
    Admin interface for FHIR merge operations.
    """
    list_display = (
        'id', 'patient_short', 'operation_type', 'status', 'progress_percentage',
        'created_by', 'created_at', 'processing_time_seconds'
    )
    list_filter = (
        'status', 'operation_type', 'created_at', 'webhook_sent'
    )
    search_fields = (
        'patient__first_name', 'patient__last_name', 'patient__mrn',
        'created_by__username', 'id'
    )
    readonly_fields = (
        'id', 'created_at', 'started_at', 'completed_at',
        'processing_time_seconds', 'webhook_sent_at', 'merge_result',
        'error_details'
    )
    fieldsets = (
        ('Operation Details', {
            'fields': (
                'id', 'patient', 'configuration', 'document',
                'operation_type', 'created_by'
            )
        }),
        ('Status & Progress', {
            'fields': (
                'status', 'progress_percentage', 'current_step'
            )
        }),
        ('Timing', {
            'fields': (
                'created_at', 'started_at', 'completed_at',
                'processing_time_seconds'
            )
        }),
        ('Results', {
            'fields': (
                'resources_processed', 'conflicts_detected',
                'conflicts_resolved', 'merge_result', 'error_details'
            ),
            'classes': ('collapse',)
        }),
        ('Webhook', {
            'fields': (
                'webhook_url', 'webhook_sent', 'webhook_sent_at'
            ),
            'classes': ('collapse',)
        })
    )
    
    def get_queryset(self, request):
        """
        Optimize queryset with select_related.
        """
        return super().get_queryset(request).select_related(
            'patient', 'configuration', 'document', 'created_by'
        )
    
    def patient_short(self, obj):
        """
        Short patient display.
        """
        return f"{obj.patient.first_name} {obj.patient.last_name} ({obj.patient.mrn})"
    patient_short.short_description = "Patient"
    
    def has_add_permission(self, request):
        """
        Disable manual creation of merge operations through admin.
        """
        return False
    
    def has_delete_permission(self, request, obj=None):
        """
        Only allow superusers to delete merge operations.
        """
        return request.user.is_superuser
    
    def get_readonly_fields(self, request, obj=None):
        """
        Make most fields readonly for existing objects.
        """
        if obj:  # Editing existing object
            return self.readonly_fields + (
                'patient', 'configuration', 'document',
                'operation_type', 'created_by'
            )
        return self.readonly_fields
    
    actions = ['cancel_selected_operations']
    
    def cancel_selected_operations(self, request, queryset):
        """
        Admin action to cancel selected operations.
        """
        from django.utils import timezone
        
        cancellable_ops = queryset.filter(status__in=['pending', 'queued'])
        count = cancellable_ops.update(
            status='cancelled',
            completed_at=timezone.now()
        )
        
        self.message_user(
            request,
            f'{count} operation(s) were successfully cancelled.',
            messages.SUCCESS
        )
    
    cancel_selected_operations.short_description = "Cancel selected merge operations"
