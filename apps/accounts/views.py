"""
Views for user accounts and dashboard.
Handles user authentication, dashboard display, and account management.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView, ListView, CreateView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.utils.decorators import method_decorator
from django.db.models import Count, Q
from django.contrib import messages
from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from django.urls import reverse_lazy
from django.http import JsonResponse
from django.core.paginator import Paginator
from datetime import timedelta
import logging
import random

# Import our custom utilities
from apps.core.utils import (
    log_user_activity, 
    get_model_count, 
    ActivityTypes,
    safe_model_operation
)

# Import our RBAC components
from .models import Role, UserProfile
from .decorators import admin_required, has_role, has_permission
from .permissions import PermissionChecker, invalidate_user_permission_cache

logger = logging.getLogger(__name__)


class DashboardView(LoginRequiredMixin, TemplateView):
    """
    Main dashboard view after user login.
    Shows quick stats and navigation to main modules.
    Dynamically loads model data when available, falls back to placeholders.
    """
    template_name = 'accounts/dashboard.html'
    login_url = '/accounts/login/'
    
    def get_context_data(self, **kwargs):
        """
        Add dashboard statistics and recent activity to context.
        Uses dynamic model loading to work with or without implemented models.
        """
        context = super().get_context_data(**kwargs)
        
        # Get stats counts using utility functions
        context.update(self._get_dashboard_stats())
        
        # Get recent activities
        context['recent_activities'] = self._get_recent_activities()
        
        # Add user info for personalization
        context['user_name'] = self.request.user.get_full_name() or self.request.user.username
        
        # Log dashboard access for HIPAA compliance
        self._log_dashboard_access()
        
        return context
    
    def _get_dashboard_stats(self):
        """
        Get dashboard statistics counts using utility functions.
        
        Returns:
            dict: Dictionary with count data for dashboard
        """
        stats = {
            'patient_count': get_model_count('patients', 'Patient'),
            'provider_count': get_model_count('providers', 'Provider'),
            'document_count': get_model_count('documents', 'Document'),
            'active_users_count': self._get_active_users_count(),
        }
        
        logger.debug(f"Dashboard stats: {stats}")
        return stats
    
    def _get_active_users_count(self):
        """
        Get count of users who logged in within the last 30 days.
        
        Returns:
            int: Number of active users
        """
        try:
            from django.contrib.auth.models import User
            thirty_days_ago = timezone.now() - timedelta(days=30)
            count = User.objects.filter(last_login__gte=thirty_days_ago).count()
            logger.debug(f"Found {count} active users in last 30 days")
            return count
        except Exception as e:
            logger.error(f"Error counting active users: {e}")
            return 0
    
    def _get_recent_activities(self, limit=20):
        """
        Get recent user activities for the activity feed.
        Limited to 20 entries for performance and UX.
        
        Args:
            limit (int): Maximum number of activities to return (default: 20)
            
        Returns:
            QuerySet or list: Recent activities or placeholder data
        """
        def get_activities(Activity):
            """Operation to get activities from the model"""
            return Activity.objects.filter(
                user=self.request.user
            ).select_related('user')[:limit]
        
        activities = safe_model_operation(
            'core', 
            'Activity', 
            get_activities,
            default_return=self._get_placeholder_activities()
        )
        
        logger.debug(f"Loaded {len(activities)} activities")
        return activities
    
    def _get_placeholder_activities(self, limit=20):
        """
        Get placeholder activities for when the Activity model is not available.
        Generate enough activities to test scrolling functionality.
        
        Args:
            limit (int): Maximum number of activities to generate
            
        Returns:
            list: List of placeholder activity dictionaries
        """
        activity_types = [
            'Dashboard viewed',
            'Profile updated', 
            'Document uploaded',
            'Patient record accessed',
            'Provider information viewed',
            'Report generated',
            'Security settings changed',
            'Password updated',
            'Activity log reviewed',
            'System backup completed',
            'Data export performed',
            'FHIR validation completed',
            'Medical record processed',
            'Audit trail reviewed',
            'Compliance check performed'
        ]
        
        activities = []
        for i in range(limit):
            # Create activities with varying timestamps
            hours_ago = i * 2 + random.randint(0, 4)
            timestamp = timezone.now() - timedelta(hours=hours_ago)
            
            activities.append({
                'description': random.choice(activity_types),
                'timestamp': timestamp,
                'user': self.request.user,
            })
        
        return activities
    
    def _log_dashboard_access(self):
        """
        Log dashboard access for HIPAA compliance and activity tracking.
        """
        log_user_activity(
            user=self.request.user,
            activity_type=ActivityTypes.LOGIN,  # Using closest match
            description="Viewed dashboard",
            request=self.request
        )


class ProfileView(LoginRequiredMixin, TemplateView):
    """
    User profile view showing account information.
    """
    template_name = 'accounts/profile.html'
    login_url = '/accounts/login/'
    
    def get_context_data(self, **kwargs):
        """Add profile information to context"""
        context = super().get_context_data(**kwargs)
        
        # Log profile access
        self._log_profile_access()
        
        return context
    
    def _log_profile_access(self):
        """Log profile view for audit trail"""
        log_user_activity(
            user=self.request.user,
            activity_type=ActivityTypes.PROFILE_UPDATE,
            description="Viewed user profile",
            request=self.request
        )


class ProfileEditView(LoginRequiredMixin, TemplateView):
    """
    User profile edit view for updating account information.
    """
    template_name = 'accounts/profile_edit.html'
    login_url = '/accounts/login/'


class LockoutView(TemplateView):
    """
    Account lockout view for django-axes.
    Displayed when user has too many failed login attempts.
    """
    template_name = 'accounts/lockout.html'
    
    def get_context_data(self, **kwargs):
        """
        Add lockout information to context.
        """
        context = super().get_context_data(**kwargs)
        context['support_email'] = 'support@meddocparser.com'
        return context


# Role Management Views

@method_decorator(admin_required, name='dispatch')
class RoleListView(LoginRequiredMixin, ListView):
    """
    List view for managing healthcare roles.
    Shows all roles with permission counts and user assignments.
    """
    model = Role
    template_name = 'accounts/role_list.html'
    context_object_name = 'roles'
    paginate_by = 20
    
    def get_queryset(self):
        """Get roles with related data for efficient display."""
        return Role.objects.prefetch_related('permissions', 'user_profiles').order_by('name')
    
    def get_context_data(self, **kwargs):
        """Add additional context for role management."""
        context = super().get_context_data(**kwargs)
        
        # Add summary statistics
        context['total_roles'] = Role.objects.count()
        context['system_roles'] = Role.objects.filter(is_system_role=True).count()
        context['active_roles'] = Role.objects.filter(is_active=True).count()
        
        # Add permission statistics
        context['total_permissions'] = sum(role.get_permission_count() for role in context['roles'])
        
        # Log access for audit trail
        log_user_activity(
            user=self.request.user,
            activity_type=ActivityTypes.ADMIN,
            description="Viewed role management list",
            request=self.request
        )
        
        return context


@method_decorator(admin_required, name='dispatch')
class RoleDetailView(LoginRequiredMixin, TemplateView):
    """
    Detailed view for a specific role showing permissions and assigned users.
    """
    template_name = 'accounts/role_detail.html'
    
    def get_context_data(self, **kwargs):
        """Add role details to context."""
        context = super().get_context_data(**kwargs)
        
        role = get_object_or_404(Role, pk=kwargs['pk'])
        context['role'] = role
        
        # Get role permissions
        context['role_permissions'] = role.permissions.select_related('content_type').order_by(
            'content_type__app_label', 'codename'
        )
        
        # Get users with this role
        context['role_users'] = User.objects.filter(
            profile__roles=role
        ).select_related('profile').order_by('email')
        
        # Add statistics
        context['permission_count'] = role.get_permission_count()
        context['user_count'] = role.get_user_count()
        
        return context


@method_decorator(admin_required, name='dispatch')
class RoleCreateView(LoginRequiredMixin, CreateView):
    """
    Create view for adding new roles.
    """
    model = Role
    template_name = 'accounts/role_form.html'
    fields = ['name', 'display_name', 'description', 'is_active']
    success_url = reverse_lazy('accounts:role_list')
    
    def form_valid(self, form):
        """Handle successful form submission."""
        form.instance.created_by = self.request.user
        
        # Log role creation
        log_user_activity(
            user=self.request.user,
            activity_type=ActivityTypes.ADMIN,
            description=f"Created new role: {form.instance.name}",
            request=self.request
        )
        
        messages.success(self.request, f'Role "{form.instance.display_name}" created successfully.')
        return super().form_valid(form)


@method_decorator(admin_required, name='dispatch')
class RoleUpdateView(LoginRequiredMixin, UpdateView):
    """
    Update view for editing existing roles.
    """
    model = Role
    template_name = 'accounts/role_form.html'
    fields = ['display_name', 'description', 'is_active']
    success_url = reverse_lazy('accounts:role_list')
    
    def get_queryset(self):
        """Only allow editing of non-system roles or with proper permissions."""
        queryset = Role.objects.all()
        
        # Prevent editing system roles unless superuser
        if not self.request.user.is_superuser:
            queryset = queryset.filter(is_system_role=False)
        
        return queryset
    
    def form_valid(self, form):
        """Handle successful form submission."""
        # Log role update
        log_user_activity(
            user=self.request.user,
            activity_type=ActivityTypes.ADMIN,
            description=f"Updated role: {form.instance.name}",
            request=self.request
        )
        
        messages.success(self.request, f'Role "{form.instance.display_name}" updated successfully.')
        return super().form_valid(form)


@method_decorator(admin_required, name='dispatch')
class RoleDeleteView(LoginRequiredMixin, DeleteView):
    """
    Delete view for removing roles.
    """
    model = Role
    template_name = 'accounts/role_confirm_delete.html'
    success_url = reverse_lazy('accounts:role_list')
    
    def get_queryset(self):
        """Only allow deletion of non-system roles."""
        return Role.objects.filter(is_system_role=False)
    
    def delete(self, request, *args, **kwargs):
        """Handle role deletion with proper logging."""
        role = self.get_object()
        
        # Check if role has users assigned
        if role.get_user_count() > 0:
            messages.error(request, f'Cannot delete role "{role.display_name}" - it has users assigned.')
            return redirect('accounts:role_list')
        
        # Log role deletion
        log_user_activity(
            user=request.user,
            activity_type=ActivityTypes.ADMIN,
            description=f"Deleted role: {role.name}",
            request=request
        )
        
        messages.success(request, f'Role "{role.display_name}" deleted successfully.')
        return super().delete(request, *args, **kwargs)


# User Profile Management Views

@method_decorator(admin_required, name='dispatch')
class UserListView(LoginRequiredMixin, ListView):
    """
    List view for managing user accounts and role assignments.
    """
    model = User
    template_name = 'accounts/user_list.html'
    context_object_name = 'users'
    paginate_by = 25
    
    def get_queryset(self):
        """Get users with their profiles and roles."""
        queryset = User.objects.select_related('profile').prefetch_related(
            'profile__roles'
        ).order_by('email')
        
        # Add search functionality
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(email__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )
        
        return queryset
    
    def get_context_data(self, **kwargs):
        """Add user management statistics."""
        context = super().get_context_data(**kwargs)
        
        # Add statistics
        context['total_users'] = User.objects.count()
        context['active_users'] = User.objects.filter(is_active=True).count()
        context['users_with_profiles'] = User.objects.filter(profile__isnull=False).count()
        
        # Add role statistics
        context['role_stats'] = {}
        for role in Role.objects.all():
            context['role_stats'][role.name] = role.get_user_count()
        
        return context


@method_decorator(admin_required, name='dispatch')
class UserRoleManagementView(LoginRequiredMixin, TemplateView):
    """
    View for managing user role assignments.
    """
    template_name = 'accounts/user_role_management.html'
    
    def get_context_data(self, **kwargs):
        """Add user and role information to context."""
        context = super().get_context_data(**kwargs)
        
        user = get_object_or_404(User, pk=kwargs['user_id'])
        context['managed_user'] = user
        
        # Get or create user profile
        profile, created = UserProfile.objects.get_or_create(user=user)
        if created:
            messages.info(self.request, f'Created profile for user {user.email}')
        
        context['user_profile'] = profile
        context['user_roles'] = profile.roles.all()
        context['available_roles'] = Role.objects.filter(is_active=True)
        
        return context
    
    def post(self, request, user_id):
        """Handle role assignment/removal."""
        user = get_object_or_404(User, pk=user_id)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        
        action = request.POST.get('action')
        role_id = request.POST.get('role_id')
        
        if not role_id:
            messages.error(request, 'No role specified.')
            return redirect('accounts:user_role_management', user_id=user_id)
        
        try:
            role = Role.objects.get(pk=role_id, is_active=True)
            
            if action == 'add':
                if not profile.roles.filter(pk=role.pk).exists():
                    profile.roles.add(role)
                    messages.success(request, f'Added {role.display_name} role to {user.email}')
                    
                    # Invalidate user permission cache
                    invalidate_user_permission_cache(user, request)
                    
                    # Log role assignment
                    log_user_activity(
                        user=request.user,
                        activity_type=ActivityTypes.ADMIN,
                        description=f"Assigned {role.name} role to {user.email}",
                        request=request
                    )
                else:
                    messages.info(request, f'User already has {role.display_name} role.')
                    
            elif action == 'remove':
                if profile.roles.filter(pk=role.pk).exists():
                    profile.roles.remove(role)
                    messages.success(request, f'Removed {role.display_name} role from {user.email}')
                    
                    # Invalidate user permission cache
                    invalidate_user_permission_cache(user, request)
                    
                    # Log role removal
                    log_user_activity(
                        user=request.user,
                        activity_type=ActivityTypes.ADMIN,
                        description=f"Removed {role.name} role from {user.email}",
                        request=request
                    )
                else:
                    messages.info(request, f'User does not have {role.display_name} role.')
            
        except Role.DoesNotExist:
            messages.error(request, 'Invalid role specified.')
        except Exception as e:
            logger.error(f"Error managing user roles: {e}")
            messages.error(request, 'An error occurred while managing user roles.')
        
        return redirect('accounts:user_role_management', user_id=user_id)


# Permission Management Views

@admin_required
def role_permissions_view(request, role_id):
    """
    View for managing role permissions.
    """
    role = get_object_or_404(Role, pk=role_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        permission_id = request.POST.get('permission_id')
        
        if permission_id:
            try:
                from django.contrib.auth.models import Permission
                permission = Permission.objects.get(pk=permission_id)
                
                if action == 'add':
                    if not role.permissions.filter(pk=permission.pk).exists():
                        role.permissions.add(permission)
                        messages.success(request, f'Added permission: {permission.name}')
                        
                        # Invalidate role cache
                        PermissionChecker.invalidate_role_cache(role)
                        
                        # Log permission assignment
                        log_user_activity(
                            user=request.user,
                            activity_type=ActivityTypes.ADMIN,
                            description=f"Added permission {permission.codename} to role {role.name}",
                            request=request
                        )
                    else:
                        messages.info(request, 'Role already has this permission.')
                        
                elif action == 'remove':
                    if role.permissions.filter(pk=permission.pk).exists():
                        role.permissions.remove(permission)
                        messages.success(request, f'Removed permission: {permission.name}')
                        
                        # Invalidate role cache
                        PermissionChecker.invalidate_role_cache(role)
                        
                        # Log permission removal
                        log_user_activity(
                            user=request.user,
                            activity_type=ActivityTypes.ADMIN,
                            description=f"Removed permission {permission.codename} from role {role.name}",
                            request=request
                        )
                    else:
                        messages.info(request, 'Role does not have this permission.')
                        
            except Permission.DoesNotExist:
                messages.error(request, 'Invalid permission specified.')
            except Exception as e:
                logger.error(f"Error managing role permissions: {e}")
                messages.error(request, 'An error occurred while managing permissions.')
        
        return redirect('accounts:role_permissions', role_id=role_id)
    
    # GET request - show permission management page
    from django.contrib.auth.models import Permission
    
    context = {
        'role': role,
        'role_permissions': role.permissions.select_related('content_type').order_by(
            'content_type__app_label', 'codename'
        ),
        'available_permissions': Permission.objects.select_related('content_type').order_by(
            'content_type__app_label', 'codename'
        ),
        'permission_count': role.get_permission_count(),
    }
    
    return render(request, 'accounts/role_permissions.html', context)


@admin_required
def user_profile_detail_view(request, user_id):
    """
    Detailed view for user profile management.
    """
    user = get_object_or_404(User, pk=user_id)
    profile, created = UserProfile.objects.get_or_create(user=user)
    
    if created:
        messages.info(request, f'Created profile for user {user.email}')
    
    context = {
        'managed_user': user,
        'user_profile': profile,
        'user_roles': profile.roles.all(),
        'user_permissions': PermissionChecker.get_user_permissions_cached(user),
        'can_access_phi': profile.can_access_phi(),
        'is_account_locked': profile.is_account_locked(),
        'last_login': user.last_login,
        'date_joined': user.date_joined,
    }
    
    return render(request, 'accounts/user_profile_detail.html', context)


@admin_required
def bulk_role_assignment_view(request):
    """
    View for bulk role assignment to multiple users.
    """
    if request.method == 'POST':
        user_ids = request.POST.getlist('user_ids')
        role_id = request.POST.get('role_id')
        action = request.POST.get('action')  # 'add' or 'remove'
        
        if not user_ids or not role_id:
            messages.error(request, 'Please select users and a role.')
            return redirect('accounts:bulk_role_assignment')
        
        try:
            role = Role.objects.get(pk=role_id, is_active=True)
            users = User.objects.filter(pk__in=user_ids)
            
            success_count = 0
            
            for user in users:
                profile, _ = UserProfile.objects.get_or_create(user=user)
                
                if action == 'add':
                    if not profile.roles.filter(pk=role.pk).exists():
                        profile.roles.add(role)
                        invalidate_user_permission_cache(user, request)
                        success_count += 1
                        
                elif action == 'remove':
                    if profile.roles.filter(pk=role.pk).exists():
                        profile.roles.remove(role)
                        invalidate_user_permission_cache(user, request)
                        success_count += 1
            
            # Log bulk operation
            log_user_activity(
                user=request.user,
                activity_type=ActivityTypes.ADMIN,
                description=f"Bulk {action} {role.name} role: {success_count} users affected",
                request=request
            )
            
            if action == 'add':
                messages.success(request, f'Added {role.display_name} role to {success_count} users.')
            else:
                messages.success(request, f'Removed {role.display_name} role from {success_count} users.')
                
        except Role.DoesNotExist:
            messages.error(request, 'Invalid role specified.')
        except Exception as e:
            logger.error(f"Error in bulk role assignment: {e}")
            messages.error(request, 'An error occurred during bulk role assignment.')
        
        return redirect('accounts:bulk_role_assignment')
    
    # GET request - show bulk assignment form
    context = {
        'users': User.objects.select_related('profile').order_by('email'),
        'roles': Role.objects.filter(is_active=True).order_by('name'),
    }
    
    return render(request, 'accounts/bulk_role_assignment.html', context)


# API Views for AJAX interactions

@admin_required
def role_permissions_api(request, role_id):
    """
    API endpoint for managing role permissions via AJAX.
    """
    role = get_object_or_404(Role, pk=role_id)
    
    if request.method == 'GET':
        # Return role permissions as JSON
        permissions = []
        for perm in role.permissions.select_related('content_type'):
            permissions.append({
                'id': perm.id,
                'name': perm.name,
                'codename': perm.codename,
                'app_label': perm.content_type.app_label,
            })
        
        return JsonResponse({
            'role': {
                'id': role.id,
                'name': role.name,
                'display_name': role.display_name,
            },
            'permissions': permissions,
            'permission_count': len(permissions),
        })
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@admin_required
def user_roles_api(request, user_id):
    """
    API endpoint for getting user roles via AJAX.
    """
    user = get_object_or_404(User, pk=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=user)
    
    if request.method == 'GET':
        roles = []
        for role in profile.roles.all():
            roles.append({
                'id': role.id,
                'name': role.name,
                'display_name': role.display_name,
                'permission_count': role.get_permission_count(),
            })
        
        return JsonResponse({
            'user': {
                'id': user.id,
                'email': user.email,
                'full_name': user.get_full_name(),
            },
            'roles': roles,
            'can_access_phi': profile.can_access_phi(),
            'is_locked': profile.is_account_locked(),
        })
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)
