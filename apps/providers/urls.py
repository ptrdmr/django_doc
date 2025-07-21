"""
URL configuration for providers app.
"""
from django.urls import path
from . import views

app_name = 'providers'

urlpatterns = [
    # Provider listing and management
    path('', views.ProviderListView.as_view(), name='list'),
    path('add/', views.ProviderCreateView.as_view(), name='add'),
    path('directory/', views.ProviderDirectoryView.as_view(), name='directory'),
    path('<uuid:pk>/', views.ProviderDetailView.as_view(), name='detail'),
    path('<uuid:pk>/edit/', views.ProviderUpdateView.as_view(), name='edit'),
] 