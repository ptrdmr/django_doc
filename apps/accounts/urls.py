"""
URL configuration for accounts app.
Handles dashboard, profile, and admin panel.
"""

from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # Dashboard (main landing page after login)
    path('', views.DashboardView.as_view(), name='dashboard'),

    # User profile
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('profile/edit/', views.ProfileEditView.as_view(), name='profile_edit'),
    path('settings/', views.ProfileView.as_view(), name='settings'),

    # Account lockout (django-axes)
    path('lockout/', views.LockoutView.as_view(), name='lockout'),

    # Admin Panel (Moritrac Admin only)
    path('users/', views.AdminUserListView.as_view(), name='user_list'),
    path('users/<int:user_id>/', views.AdminUserDetailView.as_view(), name='admin_user_detail'),
    path('users/<int:user_id>/action/', views.admin_user_action, name='admin_user_action'),
]
