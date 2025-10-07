"""
URL configuration for reports module.
"""

from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    # Dashboard - main reports landing page
    path('', views.ReportDashboardView.as_view(), name='dashboard'),
    
    # Generate report with parameters
    path('generate/', views.GenerateReportView.as_view(), name='generate'),
    
    # View report details
    path('<int:pk>/', views.ReportDetailView.as_view(), name='detail'),
    
    # Download generated report
    path('<int:pk>/download/', views.ReportDownloadView.as_view(), name='download'),
    
    # Delete configuration
    path('config/<int:pk>/delete/', views.ConfigurationDeleteView.as_view(), name='config-delete'),
]
