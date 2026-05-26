"""
URL configuration for core app - HIPAA audit trail and compliance.
"""
from django.urls import path
from . import views
from . import monitor_views

app_name = 'core'

urlpatterns = [
    # Audit trail views
    path('audit-trail/', views.AuditTrailReportView.as_view(), name='audit_trail'),
    path('audit-trail/export/', views.AuditLogExportView.as_view(), name='audit_export'),

    # Processing monitor dashboard (admin only)
    path('monitor/', monitor_views.monitor_dashboard, name='monitor-dashboard'),
    path('monitor/api/pipeline/', monitor_views.api_pipeline_metrics, name='monitor-api-pipeline'),
    path('monitor/api/live/', monitor_views.api_live_documents, name='monitor-api-live'),
    path('monitor/api/cost/', monitor_views.api_cost_summary, name='monitor-api-cost'),
    path('monitor/api/events/', monitor_views.sse_pipeline_events, name='monitor-api-events'),
]