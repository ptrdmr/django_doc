"""
System Health Dashboard Views
"""
from datetime import timedelta
from django.utils import timezone
from django.views.generic import ListView, DetailView, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages

from apps.core.decorators import has_permission
from django.utils.decorators import method_decorator

from .models import SystemHealthSnapshot, SystemAlert, MaintenanceTask
from .services import HealthCheckService, MaintenanceScheduler
from apps.documents.models import Document, APIUsageLog
from apps.core.models import AuditLog


@method_decorator(has_permission('view_system_health'), name='dispatch')
class SystemHealthDashboardView(LoginRequiredMixin, TemplateView):
    """
    Main system health dashboard showing real-time metrics
    """
    template_name = 'system_health/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get latest snapshot or create one
        latest_snapshot = SystemHealthSnapshot.objects.first()
        if not latest_snapshot or (timezone.now() - latest_snapshot.timestamp) > timedelta(minutes=15):
            service = HealthCheckService()
            latest_snapshot = service.create_snapshot()
        
        # Active alerts
        active_alerts = SystemAlert.objects.filter(is_active=True)
        critical_alerts = active_alerts.filter(severity='critical')
        
        # Maintenance tasks
        overdue_tasks = MaintenanceScheduler.get_overdue_tasks()
        upcoming_tasks = MaintenanceScheduler.get_upcoming_tasks(days=7)
        
        # Recent trends (last 7 days)
        week_ago = timezone.now() - timedelta(days=7)
        snapshots_week = SystemHealthSnapshot.objects.filter(
            timestamp__gte=week_ago
        ).order_by('timestamp')
        
        context.update({
            'snapshot': latest_snapshot,
            'active_alerts': active_alerts,
            'critical_alerts': critical_alerts,
            'overdue_tasks': overdue_tasks,
            'upcoming_tasks': upcoming_tasks,
            'snapshots_week': snapshots_week,
            'alert_counts': self._get_alert_counts(active_alerts),
            'task_counts': self._get_task_counts(),
        })
        
        return context
    
    def _get_alert_counts(self, alerts):
        """Count alerts by severity"""
        return {
            'critical': alerts.filter(severity='critical').count(),
            'error': alerts.filter(severity='error').count(),
            'warning': alerts.filter(severity='warning').count(),
            'info': alerts.filter(severity='info').count(),
        }
    
    def _get_task_counts(self):
        """Count tasks by status"""
        return {
            'overdue': MaintenanceScheduler.get_overdue_tasks().count(),
            'pending': MaintenanceTask.objects.filter(status='pending').count(),
            'in_progress': MaintenanceTask.objects.filter(status='in_progress').count(),
            'completed_week': MaintenanceTask.objects.filter(
                status='completed',
                completed_at__gte=timezone.now() - timedelta(days=7)
            ).count(),
        }


@method_decorator(has_permission('view_system_health'), name='dispatch')
class AlertListView(LoginRequiredMixin, ListView):
    """
    List all system alerts
    """
    model = SystemAlert
    template_name = 'system_health/alert_list.html'
    context_object_name = 'alerts'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = SystemAlert.objects.all()
        
        # Filter by severity
        severity = self.request.GET.get('severity')
        if severity:
            queryset = queryset.filter(severity=severity)
        
        # Filter by category
        category = self.request.GET.get('category')
        if category:
            queryset = queryset.filter(category=category)
        
        # Filter by active status
        show_resolved = self.request.GET.get('show_resolved', 'false') == 'true'
        if not show_resolved:
            queryset = queryset.filter(is_active=True)
        
        return queryset


@method_decorator(has_permission('manage_system_health'), name='dispatch')
class AcknowledgeAlertView(LoginRequiredMixin, DetailView):
    """
    Acknowledge an alert
    """
    model = SystemAlert
    
    def post(self, request, *args, **kwargs):
        alert = self.get_object()
        alert.acknowledge(request.user)
        messages.success(request, f"Alert '{alert.title}' acknowledged.")
        return redirect('system_health:alerts')


@method_decorator(has_permission('manage_system_health'), name='dispatch')
class ResolveAlertView(LoginRequiredMixin, DetailView):
    """
    Resolve an alert
    """
    model = SystemAlert
    
    def post(self, request, *args, **kwargs):
        alert = self.get_object()
        alert.resolve(request.user)
        messages.success(request, f"Alert '{alert.title}' resolved.")
        return redirect('system_health:alerts')


@method_decorator(has_permission('view_system_health'), name='dispatch')
class MaintenanceTaskListView(LoginRequiredMixin, ListView):
    """
    List maintenance tasks
    """
    model = MaintenanceTask
    template_name = 'system_health/task_list.html'
    context_object_name = 'tasks'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = MaintenanceTask.objects.all()
        
        # Filter by status
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        # Filter by priority
        priority = self.request.GET.get('priority')
        if priority:
            queryset = queryset.filter(priority=priority)
        
        return queryset


@method_decorator(has_permission('view_system_health'), name='dispatch')
class MetricsAPIView(LoginRequiredMixin, TemplateView):
    """
    API endpoint for real-time metrics (for AJAX updates)
    """
    
    def get(self, request, *args, **kwargs):
        latest_snapshot = SystemHealthSnapshot.objects.first()
        
        if not latest_snapshot:
            return JsonResponse({'error': 'No health data available'}, status=404)
        
        data = {
            'timestamp': latest_snapshot.timestamp.isoformat(),
            'overall_status': latest_snapshot.overall_status,
            'documents': {
                'pending': latest_snapshot.documents_pending,
                'processing': latest_snapshot.documents_processing,
                'failed_24h': latest_snapshot.documents_failed_24h,
                'completed_24h': latest_snapshot.documents_completed_24h,
                'avg_processing_time': latest_snapshot.avg_processing_time_seconds,
            },
            'ai': {
                'requests_24h': latest_snapshot.ai_requests_24h,
                'errors_24h': latest_snapshot.ai_errors_24h,
                'cost_24h': float(latest_snapshot.ai_cost_24h),
                'avg_response_time': latest_snapshot.ai_avg_response_time,
            },
            'database': {
                'patients': latest_snapshot.total_patients,
                'providers': latest_snapshot.total_providers,
                'documents': latest_snapshot.total_documents,
                'size_mb': latest_snapshot.db_size_mb,
            },
            'security': {
                'failed_logins_24h': latest_snapshot.failed_login_attempts_24h,
                'suspicious_events_24h': latest_snapshot.suspicious_audit_events_24h,
                'phi_access_24h': latest_snapshot.phi_access_events_24h,
            },
            'system': {
                'disk_usage_percent': latest_snapshot.disk_usage_percent,
                'memory_usage_percent': latest_snapshot.memory_usage_percent,
                'redis_ok': latest_snapshot.redis_connection_ok,
            },
            'alerts': {
                'active': SystemAlert.objects.filter(is_active=True).count(),
                'critical': SystemAlert.objects.filter(is_active=True, severity='critical').count(),
            }
        }
        
        return JsonResponse(data)


@method_decorator(has_permission('manage_system_health'), name='dispatch')
class RefreshHealthDataView(LoginRequiredMixin, TemplateView):
    """
    Force refresh of health data
    """
    
    def post(self, request, *args, **kwargs):
        service = HealthCheckService()
        snapshot = service.create_snapshot()
        
        if snapshot:
            messages.success(request, f"Health data refreshed. Status: {snapshot.overall_status}")
        else:
            messages.error(request, "Failed to refresh health data.")
        
        return redirect('system_health:dashboard')