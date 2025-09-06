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
    
    # Role Management (Admin only)
    path('roles/', views.RoleListView.as_view(), name='role_list'),
    path('roles/create/', views.RoleCreateView.as_view(), name='role_create'),
    path('roles/<uuid:pk>/', views.RoleDetailView.as_view(), name='role_detail'),
    path('roles/<uuid:pk>/edit/', views.RoleUpdateView.as_view(), name='role_update'),
    path('roles/<uuid:pk>/delete/', views.RoleDeleteView.as_view(), name='role_delete'),
    path('roles/<uuid:role_id>/permissions/', views.role_permissions_view, name='role_permissions'),
    
    # User Management (Admin only)
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/<int:user_id>/roles/', views.UserRoleManagementView.as_view(), name='user_role_management'),
    path('users/<int:user_id>/profile/', views.user_profile_detail_view, name='user_profile_detail'),
    path('users/bulk-assign/', views.bulk_role_assignment_view, name='bulk_role_assignment'),
    
    # API endpoints for AJAX interactions
    path('api/roles/<uuid:role_id>/permissions/', views.role_permissions_api, name='role_permissions_api'),
    path('api/users/<int:user_id>/roles/', views.user_roles_api, name='user_roles_api'),
    
    # Provider Invitation Management (Admin only)
    path('invitations/', views.InvitationListView.as_view(), name='invitation_list'),
    path('invitations/create/', views.CreateInvitationView.as_view(), name='create_invitation'),
    path('invitations/bulk/', views.BulkInvitationView.as_view(), name='bulk_invitation'),
    path('invitations/<uuid:invitation_id>/resend/', views.resend_invitation, name='resend_invitation'),
    path('invitations/<uuid:invitation_id>/revoke/', views.revoke_invitation, name='revoke_invitation'),
    path('invitations/cleanup/', views.cleanup_expired_invitations, name='cleanup_invitations'),
    
    # Invitation Acceptance (Public)
    path('invitations/accept/<str:token>/', views.AcceptInvitationView.as_view(), name='accept_invitation'),
    path('invitations/register/', views.InvitationRegistrationView.as_view(), name='invitation_registration'),
    
    # API endpoints for invitation management
    path('api/invitations/stats/', views.invitation_stats_api, name='invitation_stats_api'),
] 