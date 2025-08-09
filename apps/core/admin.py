from django.contrib import admin
from django.db import models
from .models import AuditLog, APIUsageLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Admin interface for audit logs."""
    list_display = [
        'timestamp', 'event_type', 'category', 'severity',
        'user', 'ip_address', 'description'
    ]
    list_filter = [
        'event_type', 'category', 'severity', 'timestamp'
    ]
    search_fields = [
        'user__username', 'description', 'ip_address', 'patient_mrn'
    ]
    readonly_fields = [
        'timestamp', 'content_type', 'object_id', 'content_object'
    ]
    date_hierarchy = 'timestamp'
    ordering = ['-timestamp']


@admin.register(APIUsageLog)
class APIUsageLogAdmin(admin.ModelAdmin):
    """Admin interface for API usage logs with cost monitoring."""
    list_display = [
        'created_at', 'provider', 'model', 'document',
        'total_tokens', 'cost_usd', 'processing_duration_ms',
        'success', 'chunk_info'
    ]
    list_filter = [
        'provider', 'model', 'success', 'created_at',
        'processing_started'
    ]
    search_fields = [
        'document__filename', 'patient__first_name', 'patient__last_name',
        'processing_session', 'error_message'
    ]
    readonly_fields = [
        'created_at', 'processing_session', 'processing_duration_ms',
        'cost_usd', 'duration_seconds', 'tokens_per_second', 'cost_per_token'
    ]
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    # Custom display methods
    def chunk_info(self, obj):
        """Display chunk information for chunked documents."""
        if obj.chunk_number and obj.total_chunks:
            return f"Chunk {obj.chunk_number}/{obj.total_chunks}"
        return "Single"
    chunk_info.short_description = "Chunks"
    
    # Aggregate information in the changelist
    def changelist_view(self, request, extra_context=None):
        """Add summary statistics to the changelist view."""
        from django.db.models import Sum, Count, Avg
        
        # Get summary stats for the filtered queryset
        changelist = self.get_changelist_instance(request)
        queryset = changelist.get_queryset(request)
        
        summary = queryset.aggregate(
            total_cost=Sum('cost_usd'),
            total_tokens=Sum('total_tokens'),
            total_calls=Count('id'),
            avg_duration=Avg('processing_duration_ms'),
            success_rate=Count('id', filter=models.Q(success=True)) * 100.0 / Count('id')
        )
        
        # Add summary to context
        extra_context = extra_context or {}
        extra_context['summary'] = {
            'total_cost': summary['total_cost'] or 0,
            'total_tokens': summary['total_tokens'] or 0,
            'total_calls': summary['total_calls'] or 0,
            'avg_duration': summary['avg_duration'] or 0,
            'success_rate': summary['success_rate'] or 0,
        }
        
        return super().changelist_view(request, extra_context=extra_context)


# Register your models here.
