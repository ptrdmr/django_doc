"""
URL configuration for core app - HIPAA audit trail and compliance.
"""
from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    # Audit trail views
    path('audit-trail/', views.AuditTrailReportView.as_view(), name='audit_trail'),
    path('audit-trail/export/', views.AuditLogExportView.as_view(), name='audit_export'),
    
    # TODO: Add additional core endpoints as needed
] 