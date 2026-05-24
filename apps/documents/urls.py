"""
URL configuration for documents app.
"""
from django.urls import path
from . import views

app_name = 'documents'

urlpatterns = [
    # Document upload
    path('upload/', views.DocumentUploadView.as_view(), name='upload'),
    path('upload/success/', views.DocumentUploadSuccessView.as_view(), name='upload-success'),
    
    # Document management
    path('', views.DocumentListView.as_view(), name='list'),
    path('<int:pk>/', views.DocumentDetailView.as_view(), name='detail'),
    path('<int:pk>/retry/', views.DocumentRetryView.as_view(), name='retry'),
    path('<int:pk>/delete/', views.DocumentDeleteView.as_view(), name='delete'),
    
    # API endpoints for enhanced UX
    path('api/processing-status/', views.ProcessingStatusAPIView.as_view(), name='api-processing-status'),
    path('api/recent-uploads/', views.RecentUploadsAPIView.as_view(), name='api-recent-uploads'),
    path('api/<int:pk>/preview/', views.DocumentPreviewAPIView.as_view(), name='api-document-preview'),
    path('api/<int:document_id>/parsed-data/', views.ParsedDataAPIView.as_view(), name='api-parsed-data'),
    
    # Admin tools
    path('migrate-fhir/', views.MigrateFHIRDataView.as_view(), name='migrate-fhir'),
    
    # Clinical date management endpoints (Task 35.5)
    path('clinical-date/save/', views.save_clinical_date, name='save-clinical-date'),
    path('clinical-date/verify/', views.verify_clinical_date, name='verify-clinical-date'),
] 