"""
URL configuration for patients app.
"""
from django.urls import path
from . import views

app_name = 'patients'

urlpatterns = [
    # Patient listing and management
    path('', views.PatientListView.as_view(), name='list'),
    path('add/', views.PatientCreateView.as_view(), name='add'),
    path('<uuid:pk>/', views.PatientDetailView.as_view(), name='detail'),
    path('<uuid:pk>/edit/', views.PatientUpdateView.as_view(), name='edit'),
    path('<uuid:pk>/delete/', views.PatientDeleteView.as_view(), name='delete'),
    
    # FHIR functionality
    path('<uuid:pk>/export-fhir/', views.PatientFHIRExportView.as_view(), name='export-fhir'),
    path('<uuid:pk>/fhir-json/', views.PatientFHIRJSONView.as_view(), name='fhir-json'),
    
    # Patient history
    path('<uuid:pk>/history/', views.PatientHistoryDetailView.as_view(), name='history'),
    path('history/<int:history_pk>/', views.PatientHistoryItemView.as_view(), name='history-detail'),
    
    # Patient merge functionality
    path('merge/', views.PatientMergeListView.as_view(), name='merge-list'),
    path('merge/<uuid:source_pk>/<uuid:target_pk>/', views.PatientMergeView.as_view(), name='merge'),
    path('find-duplicates/', views.FindDuplicatePatientsView.as_view(), name='find-duplicates'),
] 