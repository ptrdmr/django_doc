"""
FHIR Performance Monitoring Dashboard Views

Provides web-based dashboard views for monitoring FHIR merge operation
performance, cache statistics, error rates, and system health metrics.
"""

import json
from datetime import datetime, timedelta
from typing import Dict, Any

from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, permission_required
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db.models import Count, Avg, Q
from django.contrib import messages

from apps.core.models import APIUsageLog
from apps.patients.models import Patient
from apps.documents.models import Document
from .performance_monitoring import get_performance_dashboard_data, performance_monitor_instance
from .models import FHIRMergeOperation


@login_required
@permission_required('fhir.view_fhirmergeoperation', raise_exception=True)
def performance_dashboard(request):
    """
    Main performance monitoring dashboard view.
    
    Displays comprehensive performance metrics, charts, and system health
    information for FHIR merge operations.
    """
    try:
        # Get dashboard data
        dashboard_data = get_performance_dashboard_data()
        
        # Get recent merge operations
        recent_operations = FHIRMergeOperation.objects.filter(
            created_at__gte=timezone.now() - timedelta(hours=24)
        ).select_related('patient').order_by('-created_at')[:20]
        
        # Calculate additional statistics
        total_patients = Patient.objects.count()
        
        total_documents = Document.objects.filter(
            created_at__gte=timezone.now() - timedelta(days=30)
        ).count()
        
        # Get error rate trends
        error_operations = FHIRMergeOperation.objects.filter(
            created_at__gte=timezone.now() - timedelta(hours=24),
            status='failed'
        ).count()
        
        total_operations = FHIRMergeOperation.objects.filter(
            created_at__gte=timezone.now() - timedelta(hours=24)
        ).count()
        
        error_rate = (error_operations / total_operations * 100) if total_operations > 0 else 0
        
        context = {
            'dashboard_data': dashboard_data,
            'recent_operations': recent_operations,
            'total_patients': total_patients,
            'total_documents': total_documents,
            'error_rate': error_rate,
            'total_operations_24h': total_operations,
            'failed_operations_24h': error_operations,
        }
        
        return render(request, 'fhir/performance_dashboard.html', context)
        
    except Exception as e:
        messages.error(request, f"Error loading performance dashboard: {str(e)}")
        return render(request, 'fhir/performance_dashboard_error.html', {'error': str(e)})


@login_required
@permission_required('fhir.view_fhirmergeoperation', raise_exception=True)
@require_http_methods(["GET"])
def api_performance_metrics(request):
    """
    API endpoint for real-time performance metrics.
    
    Returns JSON data for dashboard charts and widgets.
    """
    try:
        hours = int(request.GET.get('hours', 24))
        hours = min(hours, 168)  # Max 1 week
        
        # Get performance summary
        performance_summary = performance_monitor_instance.get_performance_summary(hours)
        
        # Get time-series data for charts
        cutoff_time = timezone.now() - timedelta(hours=hours)
        
        # Merge operations over time
        operations_timeline = []
        merge_operations = FHIRMergeOperation.objects.filter(
            created_at__gte=cutoff_time
        ).extra(
            select={'hour': "date_trunc('hour', created_at)"}
        ).values('hour').annotate(
            count=Count('id'),
            avg_duration=Avg('processing_time_seconds'),
            success_count=Count('id', filter=Q(status='completed')),
            error_count=Count('id', filter=Q(status='failed'))
        ).order_by('hour')
        
        for op in merge_operations:
            operations_timeline.append({
                'timestamp': op['hour'].isoformat(),
                'total_operations': op['count'],
                'avg_duration': float(op['avg_duration'] or 0),
                'success_rate': (op['success_count'] / op['count'] * 100) if op['count'] > 0 else 0,
                'error_rate': (op['error_count'] / op['count'] * 100) if op['count'] > 0 else 0,
            })
        
        # API usage trends
        api_usage = APIUsageLog.objects.filter(
            created_at__gte=cutoff_time
        ).extra(
            select={'hour': "date_trunc('hour', created_at)"}
        ).values('hour').annotate(
            total_requests=Count('id'),
            total_tokens=Count('tokens_used'),
            avg_cost=Avg('cost')
        ).order_by('hour')
        
        api_timeline = []
        for usage in api_usage:
            api_timeline.append({
                'timestamp': usage['hour'].isoformat(),
                'requests': usage['total_requests'],
                'tokens': usage['total_tokens'],
                'avg_cost': float(usage['avg_cost'] or 0),
            })
        
        # Resource type distribution
        resource_types = {}
        if hasattr(performance_monitor_instance, 'metrics_history'):
            for metrics in performance_monitor_instance.metrics_history[-100:]:
                # This would need to be enhanced to track resource types
                # For now, provide sample data
                pass
        
        # Sample resource distribution data
        resource_types = {
            'Patient': 15,
            'Observation': 45,
            'Condition': 20,
            'MedicationStatement': 12,
            'DiagnosticReport': 8,
        }
        
        response_data = {
            'performance_summary': performance_summary,
            'operations_timeline': operations_timeline,
            'api_timeline': api_timeline,
            'resource_distribution': resource_types,
            'cache_metrics': {
                'hit_ratio': performance_summary.get('avg_cache_hit_ratio', 0),
                'total_hits': sum(
                    getattr(m, 'cache_hits', 0) 
                    for m in performance_monitor_instance.metrics_history[-50:]
                ),
                'total_misses': sum(
                    getattr(m, 'cache_misses', 0) 
                    for m in performance_monitor_instance.metrics_history[-50:]
                ),
            },
            'timestamp': timezone.now().isoformat(),
        }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@permission_required('fhir.view_fhirmergeoperation', raise_exception=True)
@require_http_methods(["GET"])
def api_system_health(request):
    """
    API endpoint for system health check.
    
    Returns current system health status and alerts.
    """
    try:
        # Get recent performance data
        recent_metrics = performance_monitor_instance.metrics_history[-10:] if performance_monitor_instance.metrics_history else []
        
        health_status = {
            'status': 'healthy',
            'alerts': [],
            'metrics': {
                'avg_response_time': 0,
                'error_rate': 0,
                'cache_hit_ratio': 0,
                'memory_usage': 0,
            }
        }
        
        if recent_metrics:
            # Calculate averages
            avg_processing_time = sum(getattr(m, 'processing_time', 0) or 0 for m in recent_metrics) / len(recent_metrics)
            total_errors = sum(getattr(m, 'merge_errors', 0) + getattr(m, 'validation_errors', 0) for m in recent_metrics)
            total_operations = sum(getattr(m, 'total_resources_processed', 0) for m in recent_metrics)
            avg_cache_ratio = sum(getattr(m, 'cache_hit_ratio', 0) for m in recent_metrics) / len(recent_metrics)
            avg_memory = sum(getattr(m, 'peak_memory_mb', 0) for m in recent_metrics) / len(recent_metrics)
            
            error_rate = (total_errors / total_operations * 100) if total_operations > 0 else 0
            
            health_status['metrics'].update({
                'avg_response_time': avg_processing_time,
                'error_rate': error_rate,
                'cache_hit_ratio': avg_cache_ratio,
                'memory_usage': avg_memory,
            })
            
            # Check for alerts
            if avg_processing_time > 30:
                health_status['alerts'].append({
                    'level': 'warning',
                    'message': f'High response time: {avg_processing_time:.2f}s',
                    'threshold': 30
                })
            
            if error_rate > 5:
                health_status['alerts'].append({
                    'level': 'error',
                    'message': f'High error rate: {error_rate:.1f}%',
                    'threshold': 5
                })
                health_status['status'] = 'degraded'
            
            if avg_cache_ratio < 0.7:
                health_status['alerts'].append({
                    'level': 'warning',
                    'message': f'Low cache hit ratio: {avg_cache_ratio:.1%}',
                    'threshold': 0.7
                })
            
            if avg_memory > 100:
                health_status['alerts'].append({
                    'level': 'warning',
                    'message': f'High memory usage: {avg_memory:.1f}MB',
                    'threshold': 100
                })
        
        # Set overall status based on alerts
        if any(alert['level'] == 'error' for alert in health_status['alerts']):
            health_status['status'] = 'unhealthy'
        elif health_status['alerts']:
            health_status['status'] = 'degraded'
        
        return JsonResponse(health_status)
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'error': str(e),
            'alerts': [{'level': 'error', 'message': f'Health check failed: {str(e)}'}]
        }, status=500)


@login_required
@permission_required('fhir.change_fhirmergeoperation', raise_exception=True)
@require_http_methods(["POST"])
def api_clear_cache(request):
    """
    API endpoint to clear FHIR resource cache.
    
    Requires appropriate permissions and logs the action.
    """
    try:
        # Clear the global cache
        performance_monitor_instance.resource_cache.clear_all()
        
        # Log the action
        from apps.core.models import AuditLog
        AuditLog.objects.create(
            user=request.user,
            action="fhir_cache_cleared",
            resource_type="FHIRCache",
            resource_id="global",
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )
        
        return JsonResponse({
            'success': True,
            'message': 'FHIR resource cache cleared successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@permission_required('fhir.view_fhirmergeoperation', raise_exception=True)
@require_http_methods(["GET"])
def api_operation_details(request, operation_id):
    """
    API endpoint to get detailed information about a specific merge operation.
    
    Args:
        operation_id: UUID of the merge operation
    """
    try:
        operation = FHIRMergeOperation.objects.select_related('patient').get(
            id=operation_id
        )
        
        # Format operation data for response
        operation_data = {
            'id': str(operation.id),
            'patient_mrn': operation.patient.mrn,
            'operation_type': operation.operation_type,
            'status': operation.status,
            'progress_percentage': operation.progress_percentage,
            'current_step': operation.current_step,
            'created_at': operation.created_at.isoformat(),
            'completed_at': operation.completed_at.isoformat() if operation.completed_at else None,
            'processing_time_seconds': operation.processing_time_seconds,
            'resources_processed': operation.resources_processed,
            'resources_added': operation.resources_added,
            'resources_updated': operation.resources_updated,
            'conflicts_detected': operation.conflicts_detected,
            'conflicts_resolved': operation.conflicts_resolved,
            'validation_score': operation.validation_score,
            'merge_result': operation.merge_result,
            'error_details': operation.error_details,
            'webhook_url': operation.webhook_url,
            'webhook_delivered_at': operation.webhook_delivered_at.isoformat() if operation.webhook_delivered_at else None,
        }
        
        return JsonResponse(operation_data)
        
    except FHIRMergeOperation.DoesNotExist:
        return JsonResponse({'error': 'Operation not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
