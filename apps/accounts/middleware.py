"""
Access control middleware for role-based security enforcement.
Provides global authentication, audit logging, and security monitoring.
"""

import time
import logging
from typing import Callable, Optional, List
from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import resolve, reverse
from django.contrib import messages
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.contrib.auth.models import AnonymousUser

from .permissions import PermissionChecker, SessionPermissionCache
from apps.core.models import AuditLog

logger = logging.getLogger(__name__)


class AccessControlMiddleware:
    """
    Global access control middleware for HIPAA-compliant security enforcement.
    
    Provides:
    - Global authentication enforcement
    - Audit logging integration (Task 20)
    - Performance monitoring
    - Security event logging
    - Session management
    """
    
    def __init__(self, get_response: Callable):
        """Initialize the middleware."""
        self.get_response = get_response
        
        # Configure exempt paths (paths that don't require authentication)
        self.exempt_paths = getattr(settings, 'ACCESS_CONTROL_EXEMPT_PATHS', [
            '/accounts/login/',
            '/accounts/logout/',
            '/accounts/signup/',
            '/accounts/password/',
            '/admin/login/',
            '/static/',
            '/media/',
            '/favicon.ico',
            '/health/',  # Health check endpoint
        ])
        
        # Configure paths that require specific logging
        self.audit_paths = getattr(settings, 'AUDIT_REQUIRED_PATHS', [
            '/patients/',
            '/documents/',
            '/fhir/',
            '/accounts/roles/',
        ])

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Process the request through access control."""
        start_time = time.time()
        
        try:
            # Skip middleware for exempt paths
            if self.is_exempt_path(request.path_info):
                return self.get_response(request)
            
            # Perform authentication check
            auth_result = self.check_authentication(request)
            if auth_result:
                return auth_result  # Return redirect if authentication failed
            
            # Pre-cache user permissions for performance
            self.precache_user_permissions(request)
            
            # Process the request
            response = self.get_response(request)
            
            # Log access attempt for audit trail
            self.log_access_attempt(request, response, start_time)
            
            return response
            
        except Exception as e:
            # Log middleware errors
            logger.error(f"AccessControlMiddleware error: {e}", exc_info=True)
            
            # For security, deny access on middleware errors
            if request.user.is_authenticated:
                messages.error(request, 'A security error occurred. Please try again.')
                return redirect('dashboard')
            else:
                return redirect('account_login')

    def is_exempt_path(self, path: str) -> bool:
        """
        Check if a path is exempt from access control.
        
        Args:
            path: Request path
            
        Returns:
            bool: True if path is exempt
        """
        return any(path.startswith(exempt) for exempt in self.exempt_paths)

    def check_authentication(self, request: HttpRequest) -> Optional[HttpResponse]:
        """
        Check user authentication and handle unauthenticated users.
        
        Args:
            request: Django request object
            
        Returns:
            HttpResponse or None: Redirect response if authentication failed, None if OK
        """
        if not request.user.is_authenticated:
            # Check if the view allows public access
            try:
                view_func = resolve(request.path_info).func
                if getattr(view_func, 'allow_public', False):
                    return None  # Allow public access
            except:
                pass  # Continue with authentication requirement
            
            # Log unauthorized access attempt
            self.log_unauthorized_attempt(request)
            
            # Add helpful message and redirect to login
            messages.info(request, 'Please log in to access this page.')
            
            # Store the attempted URL for post-login redirect
            login_url = reverse('account_login')
            if request.GET:
                # Preserve query parameters
                next_url = f"{request.path}?{request.GET.urlencode()}"
            else:
                next_url = request.path
            
            return HttpResponseRedirect(f"{login_url}?next={next_url}")
        
        # Check if user account is locked
        if hasattr(request.user, 'profile') and request.user.profile.is_account_locked():
            logger.warning(f"Locked user {request.user.id} attempted access to {request.path}")
            
            # Log security event
            self.log_security_event(request, 'LOCKED_ACCOUNT_ACCESS', 'Access attempt from locked account')
            
            messages.error(request, 'Your account is temporarily locked. Please contact an administrator.')
            return redirect('account_logout')
        
        return None  # Authentication OK

    def precache_user_permissions(self, request: HttpRequest) -> None:
        """
        Pre-cache user permissions for optimal performance.
        
        Args:
            request: Django request object
        """
        if request.user.is_authenticated:
            try:
                # This will cache permissions if not already cached
                PermissionChecker.get_user_permissions_cached(request.user)
                
                # Also update session cache if not present
                if not SessionPermissionCache.get_user_permissions_from_session(request, request.user):
                    permissions = PermissionChecker.get_user_permissions_cached(request.user)
                    SessionPermissionCache.set_user_permissions_in_session(request, request.user, permissions)
                    
            except Exception as e:
                logger.warning(f"Error pre-caching permissions for user {request.user.id}: {e}")

    def log_access_attempt(self, request: HttpRequest, response: HttpResponse, start_time: float) -> None:
        """
        Log access attempts for audit trail compliance.
        
        Args:
            request: Django request object
            response: Django response object
            start_time: Request start time for performance monitoring
        """
        # Calculate processing time
        processing_time = (time.time() - start_time) * 1000  # Convert to milliseconds
        
        # Determine if this path requires audit logging
        requires_audit = any(request.path_info.startswith(path) for path in self.audit_paths)
        
        # Always log for authenticated users accessing sensitive paths
        if request.user.is_authenticated and requires_audit:
            try:
                # Get client IP
                client_ip = self.get_client_ip(request)
                
                # Determine action based on method and response status
                if response.status_code >= 400:
                    action = f"ACCESS_DENIED_{request.method}"
                else:
                    action = f"ACCESS_GRANTED_{request.method}"
                
                # Create audit log entry
                AuditLog.objects.create(
                    user=request.user,
                    action=action,
                    resource_type='WebView',
                    resource_id=request.path_info,
                    ip_address=client_ip,
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                    data_accessed=f"Path: {request.path_info}, Method: {request.method}, Status: {response.status_code}",
                    additional_info={
                        'processing_time_ms': round(processing_time, 2),
                        'status_code': response.status_code,
                        'content_length': len(response.content) if hasattr(response, 'content') else 0,
                        'user_roles': self.get_user_roles(request.user),
                    }
                )
                
                # Log performance for monitoring
                if processing_time > 1000:  # Log slow requests (>1 second)
                    logger.warning(f"Slow request: {request.path} took {processing_time:.2f}ms for user {request.user.id}")
                
            except Exception as e:
                logger.error(f"Error logging access attempt: {e}")

    def log_unauthorized_attempt(self, request: HttpRequest) -> None:
        """
        Log unauthorized access attempts for security monitoring.
        
        Args:
            request: Django request object
        """
        try:
            client_ip = self.get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
            
            # Create security event log
            from apps.core.models import SecurityEvent
            
            SecurityEvent.objects.create(
                event_type='UNAUTHORIZED_ACCESS_ATTEMPT',
                severity='medium',
                description=f"Unauthorized access attempt to {request.path_info}",
                ip_address=client_ip,
                user_agent=user_agent,
                additional_data={
                    'path': request.path_info,
                    'method': request.method,
                    'referer': request.META.get('HTTP_REFERER', ''),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            logger.warning(f"Unauthorized access attempt to {request.path_info} from {client_ip}")
            
        except Exception as e:
            logger.error(f"Error logging unauthorized attempt: {e}")

    def log_security_event(self, request: HttpRequest, event_type: str, description: str) -> None:
        """
        Log security events for HIPAA compliance.
        
        Args:
            request: Django request object
            event_type: Type of security event
            description: Event description
        """
        try:
            from apps.core.models import SecurityEvent
            
            SecurityEvent.objects.create(
                user=request.user if request.user.is_authenticated else None,
                event_type=event_type,
                severity='high',
                description=description,
                ip_address=self.get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                additional_data={
                    'path': request.path_info,
                    'method': request.method,
                    'user_id': request.user.id if request.user.is_authenticated else None,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
        except Exception as e:
            logger.error(f"Error logging security event: {e}")

    def get_client_ip(self, request: HttpRequest) -> str:
        """
        Get the client IP address, handling proxies.
        
        Args:
            request: Django request object
            
        Returns:
            str: Client IP address
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            # Take the first IP in the chain (original client)
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', 'unknown')
        
        return ip

    def get_user_roles(self, user) -> List[str]:
        """
        Get user roles for logging purposes.
        
        Args:
            user: User instance
            
        Returns:
            List[str]: List of role names
        """
        try:
            if hasattr(user, 'profile'):
                return user.profile.get_role_names()
            return []
        except Exception:
            return []


class SecurityHeadersMiddleware:
    """
    Middleware to add security headers for HIPAA compliance.
    
    Adds headers that enhance security for medical data handling.
    """
    
    def __init__(self, get_response: Callable):
        """Initialize the middleware."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Add security headers to the response."""
        response = self.get_response(request)
        
        # Add security headers for HIPAA compliance
        if not settings.DEBUG:  # Only in production
            response['X-Frame-Options'] = 'DENY'
            response['X-Content-Type-Options'] = 'nosniff'
            response['X-XSS-Protection'] = '1; mode=block'
            response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
            response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
            
            # Strict Transport Security for HTTPS
            if request.is_secure():
                response['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
        
        return response


class PerformanceMonitoringMiddleware:
    """
    Middleware to monitor performance of permission checks and view access.
    
    Tracks slow requests and permission check performance for optimization.
    """
    
    def __init__(self, get_response: Callable):
        """Initialize the middleware."""
        self.get_response = get_response
        self.slow_request_threshold = getattr(settings, 'SLOW_REQUEST_THRESHOLD_MS', 1000)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Monitor request performance."""
        start_time = time.time()
        
        # Add performance tracking to request
        request.start_time = start_time
        
        response = self.get_response(request)
        
        # Calculate total processing time
        processing_time = (time.time() - start_time) * 1000
        
        # Log slow requests for optimization
        if processing_time > self.slow_request_threshold:
            logger.warning(
                f"Slow request detected: {request.path} took {processing_time:.2f}ms "
                f"for user {getattr(request.user, 'id', 'anonymous')}"
            )
            
            # Log to audit system for performance monitoring
            if request.user.is_authenticated:
                try:
                    AuditLog.objects.create(
                        user=request.user,
                        action='SLOW_REQUEST',
                        resource_type='Performance',
                        resource_id=request.path,
                        ip_address=request.META.get('REMOTE_ADDR', 'unknown'),
                        data_accessed=f"Slow request: {processing_time:.2f}ms",
                        additional_info={
                            'processing_time_ms': round(processing_time, 2),
                            'threshold_ms': self.slow_request_threshold,
                            'method': request.method,
                        }
                    )
                except Exception as e:
                    logger.error(f"Error logging slow request: {e}")
        
        # Add performance header for debugging (development only)
        if settings.DEBUG:
            response['X-Processing-Time-MS'] = f"{processing_time:.2f}"
        
        return response


class UserProfileMiddleware:
    """
    Middleware to ensure all authenticated users have a UserProfile.
    
    Automatically creates UserProfile for users who don't have one.
    """
    
    def __init__(self, get_response: Callable):
        """Initialize the middleware."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Ensure user has a profile."""
        if request.user.is_authenticated and not isinstance(request.user, AnonymousUser):
            try:
                # Check if user has a profile
                if not hasattr(request.user, 'profile'):
                    # Create profile for users without one
                    from .models import UserProfile
                    
                    profile = UserProfile.objects.create(user=request.user)
                    logger.info(f"Created UserProfile for user {request.user.id}")
                    
                    # Invalidate any cached permissions since user now has a profile
                    PermissionChecker.invalidate_user_cache(request.user)
                    
            except Exception as e:
                logger.error(f"Error ensuring UserProfile for user {request.user.id}: {e}")
        
        return self.get_response(request)


class RBACLoggingMiddleware:
    """
    Specialized middleware for RBAC-specific logging and monitoring.
    
    Tracks role-based access patterns and security events.
    """
    
    def __init__(self, get_response: Callable):
        """Initialize the middleware."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Log RBAC-specific events."""
        response = self.get_response(request)
        
        # Log role-based access for authenticated users
        if request.user.is_authenticated:
            try:
                self.log_role_access(request, response)
            except Exception as e:
                logger.error(f"Error in RBAC logging: {e}")
        
        return response

    def log_role_access(self, request: HttpRequest, response: HttpResponse) -> None:
        """
        Log role-based access patterns.
        
        Args:
            request: Django request object
            response: Django response object
        """
        # Only log for sensitive paths
        sensitive_paths = ['/patients/', '/documents/upload/', '/fhir/', '/accounts/roles/']
        
        if any(request.path_info.startswith(path) for path in sensitive_paths):
            try:
                user_roles = []
                if hasattr(request.user, 'profile'):
                    user_roles = request.user.profile.get_role_names()
                
                # Log role-based access
                AuditLog.objects.create(
                    user=request.user,
                    action='RBAC_ACCESS',
                    resource_type='RoleBasedAccess',
                    resource_id=request.path_info,
                    ip_address=request.META.get('REMOTE_ADDR', 'unknown'),
                    data_accessed=f"Roles: {', '.join(user_roles) if user_roles else 'No roles'}",
                    additional_info={
                        'user_roles': user_roles,
                        'status_code': response.status_code,
                        'method': request.method,
                        'has_phi_access': PermissionChecker.user_can_access_phi(request.user),
                    }
                )
                
            except Exception as e:
                logger.error(f"Error logging role access: {e}")


# Utility middleware for development and testing
class DebugRBACMiddleware:
    """
    Development middleware for RBAC debugging.
    
    Only active when DEBUG=True. Provides detailed RBAC information.
    """
    
    def __init__(self, get_response: Callable):
        """Initialize the middleware.""" 
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Add debug information for RBAC."""
        if not settings.DEBUG:
            return self.get_response(request)
        
        # Add debug info to request for templates
        if request.user.is_authenticated:
            try:
                request.debug_rbac = {
                    'user_id': request.user.id,
                    'user_email': request.user.email,
                    'roles': [],
                    'permissions_count': 0,
                    'has_phi_access': False,
                    'cache_status': 'unknown'
                }
                
                if hasattr(request.user, 'profile'):
                    profile = request.user.profile
                    request.debug_rbac.update({
                        'roles': profile.get_display_roles(),
                        'permissions_count': len(PermissionChecker.get_user_permissions_cached(request.user)),
                        'has_phi_access': profile.can_access_phi(),
                        'is_locked': profile.is_account_locked(),
                    })
                
                # Check cache status
                cache_key = PermissionChecker.get_cache_key('user_perms', request.user.id)
                from django.core.cache import cache
                request.debug_rbac['cache_status'] = 'hit' if cache.get(cache_key) else 'miss'
                
            except Exception as e:
                request.debug_rbac = {'error': str(e)}
                logger.error(f"Error in debug RBAC middleware: {e}")
        
        response = self.get_response(request)
        
        # Add debug headers in development
        if hasattr(request, 'debug_rbac') and isinstance(request.debug_rbac, dict):
            if 'roles' in request.debug_rbac:
                response['X-Debug-User-Roles'] = ', '.join(request.debug_rbac['roles'])
                response['X-Debug-Permissions-Count'] = str(request.debug_rbac['permissions_count'])
                response['X-Debug-PHI-Access'] = str(request.debug_rbac['has_phi_access'])
                response['X-Debug-Cache-Status'] = request.debug_rbac['cache_status']
        
        return response


# Middleware configuration helper
def get_rbac_middleware_stack():
    """
    Get the recommended RBAC middleware stack for settings.py.
    
    Returns:
        List[str]: Middleware class paths in recommended order
    """
    base_middleware = [
        'apps.accounts.middleware.SecurityHeadersMiddleware',
        'apps.accounts.middleware.UserProfileMiddleware', 
        'apps.accounts.middleware.AccessControlMiddleware',
        'apps.accounts.middleware.PerformanceMonitoringMiddleware',
        'apps.accounts.middleware.RBACLoggingMiddleware',
    ]
    
    # Add debug middleware in development
    if settings.DEBUG:
        base_middleware.append('apps.accounts.middleware.DebugRBACMiddleware')
    
    return base_middleware


# Context processor for templates
def rbac_context_processor(request):
    """
    Context processor to add RBAC information to all templates.
    
    Args:
        request: Django request object
        
    Returns:
        dict: Context variables for templates
    """
    context = {
        'user_roles': [],
        'user_permissions_count': 0,
        'user_can_access_phi': False,
        'user_is_admin': False,
        'user_is_provider': False,
        'user_is_staff_member': False,
        'user_is_auditor': False,
    }
    
    if request.user.is_authenticated:
        try:
            if hasattr(request.user, 'profile'):
                profile = request.user.profile
                context.update({
                    'user_roles': profile.get_display_roles(),
                    'user_permissions_count': len(PermissionChecker.get_user_permissions_cached(request.user)),
                    'user_can_access_phi': profile.can_access_phi(),
                    'user_is_admin': profile.is_admin(),
                    'user_is_provider': profile.is_provider(),
                    'user_is_staff_member': profile.is_staff_member(),
                    'user_is_auditor': profile.is_auditor(),
                })
        except Exception as e:
            logger.error(f"Error in RBAC context processor: {e}")
    
    return context
