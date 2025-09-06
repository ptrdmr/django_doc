"""
Core views for HIPAA audit trail and compliance reporting.
"""

from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.views.generic import ListView
from django.views import View
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.db.models import Q, Count
from django.core.paginator import Paginator
from django.contrib.auth.models import User
import csv
import json
from datetime import datetime, timedelta

from apps.core.models import AuditLog, SecurityEvent, ComplianceReport
from apps.accounts.decorators import audit_access_required, admin_required
from django.utils.decorators import method_decorator


@method_decorator(audit_access_required, name='dispatch')
class AuditTrailReportView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """
    HIPAA-compliant audit trail report view with comprehensive filtering.
    Provides searchable, filterable access to audit logs for compliance officers.
    """
    model = AuditLog
    template_name = 'core/audit_trail_report.html'
    context_object_name = 'audit_logs'
    paginate_by = 50
    permission_required = 'core.view_audit_trail'
    
    def get_queryset(self):
        """
        Filter audit logs based on search parameters.
        Supports filtering by date range, user, event type, resource, and PHI involvement.
        """
        queryset = AuditLog.objects.select_related('user', 'content_type').all()
        
        # Date range filtering
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        
        if start_date:
            try:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                queryset = queryset.filter(timestamp__gte=start_dt)
            except ValueError:
                pass
        
        if end_date:
            try:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                queryset = queryset.filter(timestamp__lt=end_dt)
            except ValueError:
                pass
        
        # User filtering
        user_id = self.request.GET.get('user_id')
        if user_id:
            try:
                queryset = queryset.filter(user_id=int(user_id))
            except (ValueError, TypeError):
                pass
        
        username = self.request.GET.get('username')
        if username:
            queryset = queryset.filter(username__icontains=username)
        
        # Event type filtering
        event_type = self.request.GET.get('event_type')
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        
        # Category filtering
        category = self.request.GET.get('category')
        if category:
            queryset = queryset.filter(category=category)
        
        # Severity filtering
        severity = self.request.GET.get('severity')
        if severity:
            queryset = queryset.filter(severity=severity)
        
        # PHI involvement filtering
        phi_involved = self.request.GET.get('phi_involved')
        if phi_involved == 'true':
            queryset = queryset.filter(phi_involved=True)
        elif phi_involved == 'false':
            queryset = queryset.filter(phi_involved=False)
        
        # Patient MRN filtering
        patient_mrn = self.request.GET.get('patient_mrn')
        if patient_mrn:
            queryset = queryset.filter(patient_mrn__icontains=patient_mrn)
        
        # IP address filtering
        ip_address = self.request.GET.get('ip_address')
        if ip_address:
            queryset = queryset.filter(ip_address=ip_address)
        
        # Success/failure filtering
        success = self.request.GET.get('success')
        if success == 'true':
            queryset = queryset.filter(success=True)
        elif success == 'false':
            queryset = queryset.filter(success=False)
        
        # General search across description
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(description__icontains=search) |
                Q(error_message__icontains=search)
            )
        
        return queryset.order_by('-timestamp')
    
    def get_context_data(self, **kwargs):
        """
        Add additional context for the audit trail report.
        """
        context = super().get_context_data(**kwargs)
        
        # Add filter choices for dropdowns
        context['event_types'] = AuditLog.EVENT_TYPES
        context['categories'] = AuditLog.CATEGORIES
        context['severity_levels'] = AuditLog.SEVERITY_LEVELS
        context['users'] = User.objects.filter(auditlog__isnull=False).distinct()
        
        # Add current filter values
        context['current_filters'] = {
            'start_date': self.request.GET.get('start_date', ''),
            'end_date': self.request.GET.get('end_date', ''),
            'user_id': self.request.GET.get('user_id', ''),
            'username': self.request.GET.get('username', ''),
            'event_type': self.request.GET.get('event_type', ''),
            'category': self.request.GET.get('category', ''),
            'severity': self.request.GET.get('severity', ''),
            'phi_involved': self.request.GET.get('phi_involved', ''),
            'patient_mrn': self.request.GET.get('patient_mrn', ''),
            'ip_address': self.request.GET.get('ip_address', ''),
            'success': self.request.GET.get('success', ''),
            'search': self.request.GET.get('search', ''),
        }
        
        # Add summary statistics
        total_logs = self.get_queryset().count()
        phi_logs = self.get_queryset().filter(phi_involved=True).count()
        failed_logs = self.get_queryset().filter(success=False).count()
        
        context['stats'] = {
            'total_logs': total_logs,
            'phi_logs': phi_logs,
            'failed_logs': failed_logs,
            'success_rate': ((total_logs - failed_logs) / total_logs * 100) if total_logs > 0 else 0,
        }
        
        return context


@method_decorator(audit_access_required, name='dispatch')
class AuditLogExportView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Export audit logs to CSV for compliance reporting.
    Applies same filtering as audit trail report.
    """
    permission_required = 'core.export_audit_logs'
    
    def get(self, request):
        """
        Generate CSV export of filtered audit logs.
        """
        # Create queryset using same logic as AuditTrailReportView
        view = AuditTrailReportView()
        view.request = request
        queryset = view.get_queryset()
        
        # Limit export size for performance
        max_export = 10000
        if queryset.count() > max_export:
            queryset = queryset[:max_export]
        
        # Create CSV response
        response = HttpResponse(content_type='text/csv')
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        response['Content-Disposition'] = f'attachment; filename="audit_log_export_{timestamp}.csv"'
        
        writer = csv.writer(response)
        
        # Write header row
        writer.writerow([
            'Timestamp',
            'Event Type',
            'Category', 
            'Severity',
            'User',
            'User Email',
            'IP Address',
            'User Agent',
            'Request Method',
            'Request URL',
            'Patient MRN',
            'PHI Involved',
            'Success',
            'Description',
            'Error Message',
            'Session Key',
            'Content Type',
            'Object ID',
        ])
        
        # Write data rows
        for log in queryset:
            writer.writerow([
                log.timestamp.isoformat(),
                log.event_type,
                log.category,
                log.severity,
                log.username,
                log.user_email,
                log.ip_address or '',
                log.user_agent[:100] if log.user_agent else '',  # Truncate for CSV
                log.request_method,
                log.request_url,
                log.patient_mrn,
                'Yes' if log.phi_involved else 'No',
                'Yes' if log.success else 'No',
                log.description,
                log.error_message,
                log.session_key,
                str(log.content_type) if log.content_type else '',
                log.object_id or '',
            ])
        
        # Log the export activity
        AuditLog.log_event(
            event_type='phi_export',
            user=request.user,
            request=request,
            description=f"Exported {queryset.count()} audit log entries",
            phi_involved=True,
            severity='info'
        )
        
        return response