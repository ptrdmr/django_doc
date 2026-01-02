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
    path('<int:pk>/review/', views.DocumentReviewView.as_view(), name='review'),
    path('<int:pk>/retry/', views.DocumentRetryView.as_view(), name='retry'),
    path('<int:pk>/delete/', views.DocumentDeleteView.as_view(), name='delete'),
    
    # API endpoints for enhanced UX
    path('api/processing-status/', views.ProcessingStatusAPIView.as_view(), name='api-processing-status'),
    path('api/recent-uploads/', views.RecentUploadsAPIView.as_view(), name='api-recent-uploads'),
    path('api/<int:pk>/preview/', views.DocumentPreviewAPIView.as_view(), name='api-document-preview'),
    path('api/<int:document_id>/parsed-data/', views.ParsedDataAPIView.as_view(), name='api-parsed-data'),
    
    # Admin tools
    path('migrate-fhir/', views.MigrateFHIRDataView.as_view(), name='migrate-fhir'),
    
    # Patient data comparison resolution endpoints
    path('<int:pk>/resolve/', views.PatientDataResolutionView.as_view(), name='resolve-patient-data'),
    
    # Field-level review endpoints
    path('field/<str:field_id>/approve/', views.approve_field, name='approve-field'),
    path('field/<str:field_id>/update/', views.update_field_value, name='update-field'),
    path('field/<str:field_id>/flag/', views.flag_field, name='flag-field'),
    
    # Clinical date management endpoints (Task 35.5)
    path('clinical-date/save/', views.save_clinical_date, name='save-clinical-date'),
    path('clinical-date/verify/', views.verify_clinical_date, name='verify-clinical-date'),
    
    # Flagged documents list view (Task 41.24)
    path('flagged/', views.FlaggedDocumentsListView.as_view(), name='flagged-list'),
    
    # Flagged document detail view (Task 41.25)
    path('flagged/<int:pk>/', views.FlaggedDocumentDetailView.as_view(), name='flagged-detail'),
    
    # Verification action handlers (Task 41.26)
    path('flagged/<int:pk>/mark-correct/', views.mark_as_correct, name='mark-as-correct'),
    path('flagged/<int:pk>/correct-data/', views.correct_data, name='correct-data'),
    path('flagged/<int:pk>/rollback/', views.rollback_merge, name='rollback-merge'),
] 