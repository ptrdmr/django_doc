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
] 