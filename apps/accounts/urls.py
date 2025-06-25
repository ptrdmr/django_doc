"""
URL configuration for accounts app.
Handles user dashboard and account management.
"""
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # Dashboard (main landing page after login)
    path('', views.DashboardView.as_view(), name='dashboard'),
    
    # User profile and account management
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('profile/edit/', views.ProfileEditView.as_view(), name='profile_edit'),
    path('settings/', views.ProfileView.as_view(), name='settings'),  # Placeholder for settings (same as profile for now)
    
    # Account lockout page (for django-axes)
    path('lockout/', views.LockoutView.as_view(), name='lockout'),
] 