"""
Role-based access control decorators for Django views.
Provides secure, cached permission checking with HIPAA compliance.
"""

from functools import wraps
from typing import List, Union, Callable, Any
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.http import HttpRequest, HttpResponse
from django.contrib import messages
from django.urls import reverse
import logging

from .permissions import (
    user_has_permission_cached, 
    user_has_role_cached, 
    PermissionChecker,
    user_can_access_phi,
    invalidate_user_permission_cache
)

logger = logging.getLogger(__name__)


def has_permission(permission_codename: str):
    """
    Decorator to check if user has a specific permission.
    
    Uses cached permission checking for optimal performance.
    Automatically handles authentication and provides helpful error messages.
    
    Args:
        permission_codename: Permission codename (e.g., 'patients.view_patient')
    
    Usage:
        @has_permission('patients.view_patient')
        def patient_detail(request, patient_id):
            return render(request, 'patients/detail.html')
    
    Returns:
        Decorator function that enforces permission checking
    """
    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapped_view(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            # Ensure user is authenticated
            if not request.user.is_authenticated:
                messages.error(request, 'Please log in to access this page.')
                return redirect('account_login')
            
            # Check if user has the required permission
            if user_has_permission_cached(request, request.user, permission_codename):
                # Log successful access for audit trail
                logger.info(f"User {request.user.id} accessed {view_func.__name__} with permission {permission_codename}")
                return view_func(request, *args, **kwargs)
            
            # Permission denied - log the attempt
            logger.warning(f"User {request.user.id} denied access to {view_func.__name__} - missing permission: {permission_codename}")
            
            # Add user-friendly error message
            messages.error(
                request, 
                f'Access denied. You do not have permission to access this resource. '
                f'Required permission: {permission_codename}'
            )
            
            # Redirect to dashboard or previous page
            return redirect('accounts:dashboard')
        
        # Mark the view as requiring authentication for middleware
        wrapped_view.require_auth = True
        wrapped_view.required_permission = permission_codename
        
        return wrapped_view
    return decorator


def has_role(role_name: str):
    """
    Decorator to check if user has a specific role.
    
    Uses cached role checking for optimal performance.
    
    Args:
        role_name: Role name (e.g., 'admin', 'provider', 'staff', 'auditor')
    
    Usage:
        @has_role('provider')
        def upload_document(request):
            return render(request, 'documents/upload.html')
    
    Returns:
        Decorator function that enforces role checking
    """
    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapped_view(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            # Ensure user is authenticated
            if not request.user.is_authenticated:
                messages.error(request, 'Please log in to access this page.')
                return redirect('account_login')
            
            # Check if user has the required role
            if user_has_role_cached(request, request.user, role_name):
                # Log successful access
                logger.info(f"User {request.user.id} accessed {view_func.__name__} with role {role_name}")
                return view_func(request, *args, **kwargs)
            
            # Role denied - log the attempt
            logger.warning(f"User {request.user.id} denied access to {view_func.__name__} - missing role: {role_name}")
            
            # Add user-friendly error message
            messages.error(
                request,
                f'Access denied. You do not have the required role to access this resource. '
                f'Required role: {role_name.title()}'
            )
            
            return redirect('accounts:dashboard')
        
        # Mark the view for middleware
        wrapped_view.require_auth = True
        wrapped_view.required_role = role_name
        
        return wrapped_view
    return decorator


def has_any_role(role_names: List[str]):
    """
    Decorator to check if user has any of the specified roles.
    
    Args:
        role_names: List of role names (e.g., ['admin', 'provider'])
    
    Usage:
        @has_any_role(['admin', 'provider'])
        def process_document(request):
            return render(request, 'documents/process.html')
    
    Returns:
        Decorator function that enforces role checking
    """
    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapped_view(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if not request.user.is_authenticated:
                messages.error(request, 'Please log in to access this page.')
                return redirect('account_login')
            
            # Check if user has any of the required roles
            if PermissionChecker.user_has_any_role(request.user, role_names):
                logger.info(f"User {request.user.id} accessed {view_func.__name__} with one of roles: {role_names}")
                return view_func(request, *args, **kwargs)
            
            logger.warning(f"User {request.user.id} denied access to {view_func.__name__} - missing any role from: {role_names}")
            
            roles_str = ', '.join([role.title() for role in role_names])
            messages.error(
                request,
                f'Access denied. You need one of these roles: {roles_str}'
            )
            
            return redirect('accounts:dashboard')
        
        wrapped_view.require_auth = True
        wrapped_view.required_roles = role_names
        
        return wrapped_view
    return decorator


def requires_phi_access(view_func: Callable = None):
    """
    Decorator to check if user can access Protected Health Information.
    
    Restricts access to admin and provider roles only (HIPAA compliance).
    
    Usage:
        @requires_phi_access
        def patient_detail(request, patient_id):
            return render(request, 'patients/detail.html')
    
    Returns:
        Decorator function that enforces PHI access checking
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapped_view(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if not request.user.is_authenticated:
                messages.error(request, 'Please log in to access this page.')
                return redirect('account_login')
            
            if user_can_access_phi(request.user):
                logger.info(f"User {request.user.id} accessed PHI in {func.__name__}")
                return func(request, *args, **kwargs)
            
            logger.warning(f"User {request.user.id} denied PHI access in {func.__name__}")
            
            messages.error(
                request,
                'Access denied. Protected Health Information access requires '
                'Administrator or Healthcare Provider role.'
            )
            
            return redirect('accounts:dashboard')
        
        wrapped_view.require_auth = True
        wrapped_view.require_phi_access = True
        
        return wrapped_view
    
    # Support both @requires_phi_access and @requires_phi_access()
    if view_func is None:
        return decorator
    else:
        return decorator(view_func)


def admin_required(view_func: Callable):
    """
    Decorator to require admin role.
    
    Convenience decorator for admin-only views.
    
    Usage:
        @admin_required
        def manage_users(request):
            return render(request, 'accounts/manage_users.html')
    """
    return has_role('admin')(view_func)


def provider_required(view_func: Callable):
    """
    Decorator to require provider role.
    
    Convenience decorator for provider-only views.
    
    Usage:
        @provider_required
        def upload_medical_document(request):
            return render(request, 'documents/upload.html')
    """
    return has_role('provider')(view_func)


def staff_or_above(view_func: Callable):
    """
    Decorator to require staff role or higher (staff, provider, admin).
    
    Usage:
        @staff_or_above
        def view_patient_list(request):
            return render(request, 'patients/list.html')
    """
    return has_any_role(['staff', 'provider', 'admin'])(view_func)


def provider_or_admin(view_func: Callable):
    """
    Decorator to require provider or admin role.
    
    Common pattern for medical data access.
    
    Usage:
        @provider_or_admin
        def edit_patient(request, patient_id):
            return render(request, 'patients/edit.html')
    """
    return has_any_role(['provider', 'admin'])(view_func)


def audit_access_required(view_func: Callable):
    """
    Decorator to require audit access (admin or auditor).
    
    Usage:
        @audit_access_required
        def view_audit_logs(request):
            return render(request, 'core/audit_logs.html')
    """
    return has_any_role(['admin', 'auditor'])(view_func)


# Advanced decorators with custom logic
def permission_required_with_fallback(
    permission_codename: str, 
    fallback_roles: List[str] = None,
    fallback_url: str = 'dashboard'
):
    """
    Advanced decorator that checks permission with role fallback.
    
    If user doesn't have the specific permission, check if they have
    any of the fallback roles.
    
    Args:
        permission_codename: Primary permission to check
        fallback_roles: List of roles that can access without the permission
        fallback_url: URL to redirect to on access denial
    
    Usage:
        @permission_required_with_fallback(
            'patients.delete_patient', 
            fallback_roles=['admin'],
            fallback_url='patients:list'
        )
        def delete_patient(request, patient_id):
            return render(request, 'patients/delete_confirm.html')
    """
    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapped_view(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if not request.user.is_authenticated:
                messages.error(request, 'Please log in to access this page.')
                return redirect('account_login')
            
            # Check primary permission
            if user_has_permission_cached(request, request.user, permission_codename):
                return view_func(request, *args, **kwargs)
            
            # Check fallback roles if specified
            if fallback_roles and PermissionChecker.user_has_any_role(request.user, fallback_roles):
                logger.info(f"User {request.user.id} accessed {view_func.__name__} via fallback role")
                return view_func(request, *args, **kwargs)
            
            # Access denied
            logger.warning(f"User {request.user.id} denied access to {view_func.__name__}")
            messages.error(request, f'Access denied. Required permission: {permission_codename}')
            
            return redirect(fallback_url)
        
        wrapped_view.require_auth = True
        wrapped_view.required_permission = permission_codename
        wrapped_view.fallback_roles = fallback_roles
        
        return wrapped_view
    return decorator


def cache_user_permissions(view_func: Callable):
    """
    Decorator to ensure user permissions are cached before view execution.
    
    Useful for views that will make multiple permission checks.
    
    Usage:
        @cache_user_permissions
        @has_role('provider')
        def complex_medical_view(request):
            # This view will benefit from pre-cached permissions
            return render(request, 'medical/complex.html')
    """
    @wraps(view_func)
    def wrapped_view(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if request.user.is_authenticated:
            # Pre-cache user permissions
            PermissionChecker.get_user_permissions_cached(request.user)
        
        return view_func(request, *args, **kwargs)
    
    return wrapped_view


# Method decorators for class-based views
class PermissionRequiredMixin:
    """
    Mixin for class-based views to check permissions.
    
    Usage:
        class PatientDetailView(PermissionRequiredMixin, DetailView):
            permission_required = 'patients.view_patient'
            model = Patient
    """
    permission_required = None
    role_required = None
    roles_required = None  # List of roles (any one required)
    require_phi_access = False
    login_url = 'account_login'
    permission_denied_message = None
    
    def dispatch(self, request, *args, **kwargs):
        """Check permissions before dispatching to view method."""
        if not request.user.is_authenticated:
            messages.error(request, 'Please log in to access this page.')
            return redirect(self.login_url)
        
        # Check PHI access if required
        if self.require_phi_access and not user_can_access_phi(request.user):
            logger.warning(f"User {request.user.id} denied PHI access to {self.__class__.__name__}")
            messages.error(request, 'Access denied. PHI access requires Administrator or Provider role.')
            return redirect('accounts:dashboard')
        
        # Check specific permission
        if self.permission_required:
            if not user_has_permission_cached(request, request.user, self.permission_required):
                logger.warning(f"User {request.user.id} denied access to {self.__class__.__name__} - missing permission: {self.permission_required}")
                error_msg = self.permission_denied_message or f'Permission required: {self.permission_required}'
                messages.error(request, error_msg)
                return redirect('accounts:dashboard')
        
        # Check specific role
        if self.role_required:
            if not user_has_role_cached(request, request.user, self.role_required):
                logger.warning(f"User {request.user.id} denied access to {self.__class__.__name__} - missing role: {self.role_required}")
                messages.error(request, f'Role required: {self.role_required.title()}')
                return redirect('accounts:dashboard')
        
        # Check any of multiple roles
        if self.roles_required:
            if not PermissionChecker.user_has_any_role(request.user, self.roles_required):
                logger.warning(f"User {request.user.id} denied access to {self.__class__.__name__} - missing any role from: {self.roles_required}")
                roles_str = ', '.join([role.title() for role in self.roles_required])
                messages.error(request, f'One of these roles required: {roles_str}')
                return redirect('accounts:dashboard')
        
        # All checks passed
        return super().dispatch(request, *args, **kwargs)


# Healthcare-specific decorators
def medical_staff_only(view_func: Callable):
    """
    Decorator for medical staff only (admin, provider).
    
    Usage:
        @medical_staff_only
        def process_medical_document(request):
            return render(request, 'documents/process.html')
    """
    return has_any_role(['admin', 'provider'])(view_func)


def administrative_access(view_func: Callable):
    """
    Decorator for administrative access (admin, staff).
    
    Usage:
        @administrative_access
        def manage_providers(request):
            return render(request, 'providers/manage.html')
    """
    return has_any_role(['admin', 'staff'])(view_func)


def compliance_access(view_func: Callable):
    """
    Decorator for compliance access (admin, auditor).
    
    Usage:
        @compliance_access
        def compliance_report(request):
            return render(request, 'reports/compliance.html')
    """
    return has_any_role(['admin', 'auditor'])(view_func)


# Security enforcement decorators
def enforce_account_active(view_func: Callable):
    """
    Decorator to ensure user account is not locked.
    
    Usage:
        @enforce_account_active
        @has_role('provider')
        def sensitive_operation(request):
            return render(request, 'sensitive.html')
    """
    @wraps(view_func)
    def wrapped_view(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if request.user.is_authenticated and hasattr(request.user, 'profile'):
            if request.user.profile.is_account_locked():
                logger.warning(f"Locked user {request.user.id} attempted access to {view_func.__name__}")
                messages.error(request, 'Your account is temporarily locked. Please contact an administrator.')
                return redirect('account_logout')
        
        return view_func(request, *args, **kwargs)
    
    return wrapped_view


def log_access_attempt(view_func: Callable):
    """
    Decorator to log all access attempts to a view.
    
    Useful for sensitive views that need comprehensive audit trails.
    
    Usage:
        @log_access_attempt
        @requires_phi_access
        def view_patient_phi(request, patient_id):
            return render(request, 'patients/phi_detail.html')
    """
    @wraps(view_func)
    def wrapped_view(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        # Log access attempt
        user_id = request.user.id if request.user.is_authenticated else 'anonymous'
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        
        logger.info(f"Access attempt to {view_func.__name__}: user={user_id}, ip={client_ip}, agent={user_agent[:100]}")
        
        # Execute view
        response = view_func(request, *args, **kwargs)
        
        # Log successful completion
        logger.info(f"Access completed for {view_func.__name__}: user={user_id}, status={response.status_code}")
        
        return response
    
    return wrapped_view


# Utility decorators for development and testing
def bypass_in_debug(view_func: Callable):
    """
    Decorator to bypass permission checks in DEBUG mode.
    
    WARNING: Only use for development/testing!
    
    Usage:
        @bypass_in_debug
        @has_role('admin')
        def debug_view(request):
            return render(request, 'debug.html')
    """
    @wraps(view_func)
    def wrapped_view(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        from django.conf import settings
        
        if settings.DEBUG:
            logger.debug(f"DEBUG MODE: Bypassing permission check for {view_func.__name__}")
            
        return view_func(request, *args, **kwargs)
    
    return wrapped_view


# Combined decorators for common patterns
def admin_or_provider_required(view_func: Callable):
    """
    Combined decorator for admin or provider access.
    
    Most common pattern for medical data access.
    """
    return has_any_role(['admin', 'provider'])(view_func)


def secure_medical_view(permission_codename: str):
    """
    Comprehensive security decorator for medical views.
    
    Combines authentication, permission checking, PHI access, account status,
    and access logging.
    
    Args:
        permission_codename: Required permission
    
    Usage:
        @secure_medical_view('patients.view_patient')
        def secure_patient_view(request, patient_id):
            return render(request, 'patients/secure_detail.html')
    """
    def decorator(view_func: Callable) -> Callable:
        # Apply multiple decorators in order
        decorated_func = view_func
        decorated_func = log_access_attempt(decorated_func)
        decorated_func = enforce_account_active(decorated_func)
        decorated_func = requires_phi_access(decorated_func)
        decorated_func = has_permission(permission_codename)(decorated_func)
        decorated_func = cache_user_permissions(decorated_func)
        
        return decorated_func
    
    return decorator


# Error handling utilities for decorators
def handle_permission_denied(request: HttpRequest, exception: PermissionDenied, view_name: str = None) -> HttpResponse:
    """
    Centralized permission denied handler.
    
    Args:
        request: Django request object
        exception: PermissionDenied exception
        view_name: Optional view name for logging
    
    Returns:
        HttpResponse: Appropriate response for permission denial
    """
    user_id = request.user.id if request.user.is_authenticated else 'anonymous'
    logger.warning(f"Permission denied for user {user_id} in {view_name}: {str(exception)}")
    
    # Add message if not already added
    if not any(msg.level_tag == 'error' for msg in messages.get_messages(request)):
        messages.error(request, str(exception))
    
    # Redirect based on authentication status
    if not request.user.is_authenticated:
        return redirect('account_login')
    else:
        return redirect('accounts:dashboard')


# Decorator composition utilities
def compose_decorators(*decorators):
    """
    Utility to compose multiple decorators cleanly.
    
    Args:
        *decorators: Decorator functions to compose
    
    Usage:
        secure_admin_view = compose_decorators(
            log_access_attempt,
            enforce_account_active,
            admin_required,
            cache_user_permissions
        )
        
        @secure_admin_view
        def admin_dashboard(request):
            return render(request, 'admin/dashboard.html')
    """
    def decorator(view_func: Callable) -> Callable:
        for dec in reversed(decorators):
            view_func = dec(view_func)
        return view_func
    return decorator
