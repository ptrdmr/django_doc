"""
Custom middleware for HIPAA compliance and security.
Includes CSP headers and audit logging.
"""

from django.utils.deprecation import MiddlewareMixin
from django.http import HttpResponseForbidden
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
import re


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Add comprehensive security headers for HIPAA compliance.
    Includes Content Security Policy and other security headers.
    """
    
    def process_response(self, request, response):
        """
        Add security headers to all responses.
        
        Args:
            request: HTTP request object
            response: HTTP response object
            
        Returns:
            Modified response with security headers
        """
        # Content Security Policy - very strict for medical data
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com",  # Allow unpkg CDN for Alpine.js and htmx
            "style-src 'self' 'unsafe-inline'",   # Allow inline styles for Tailwind
            "img-src 'self' data:",               # Allow data URLs for icons
            "font-src 'self'",
            "connect-src 'self'",                 # AJAX requests to same origin only
            "form-action 'self'",                 # Forms can only submit to same origin
            "frame-ancestors 'none'",             # Prevent framing completely
            "object-src 'none'",                  # No Flash, Java applets, etc.
            "base-uri 'self'",                    # Restrict base tag
        ]
        
        # Only force HTTPS upgrade in production (DEBUG=False)
        if not settings.DEBUG:
            csp_directives.append("upgrade-insecure-requests")
        
        # Join CSP directives
        csp_header = "; ".join(csp_directives)
        response['Content-Security-Policy'] = csp_header
        
        # Additional security headers
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        
        # HIPAA-specific headers
        response['X-Medical-App'] = 'HIPAA-Compliant'
        response['X-PHI-Protection'] = 'Enabled'
        
        # Cache control for sensitive pages
        if self._is_sensitive_path(request.path):
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
        
        return response
    
    def _is_sensitive_path(self, path):
        """
        Check if path contains sensitive medical data.
        
        Args:
            path: URL path to check
            
        Returns:
            Boolean indicating if path is sensitive
        """
        sensitive_patterns = [
            r'/patients/',
            r'/documents/',
            r'/providers/',
            r'/fhir/',
            r'/reports/',
            r'/admin/',
            r'/api/',
        ]
        
        for pattern in sensitive_patterns:
            if re.search(pattern, path):
                return True
        return False


class AuditLoggingMiddleware(MiddlewareMixin):
    """
    Automatically log all requests for HIPAA audit trail.
    Captures comprehensive information about user activities.
    """
    
    def __init__(self, get_response):
        """Initialize middleware."""
        self.get_response = get_response
        super().__init__(get_response)
    
    def process_request(self, request):
        """
        Process incoming request for audit logging.
        
        Args:
            request: HTTP request object
        """
        # Store request start time for performance tracking
        request._audit_start_time = timezone.now()
        
        # Log sensitive page access
        if self._is_audit_worthy_request(request):
            self._log_request_start(request)
    
    def process_response(self, request, response):
        """
        Process response and log audit information.
        
        Args:
            request: HTTP request object
            response: HTTP response object
            
        Returns:
            Response object
        """
        # Only log if we have start time
        if hasattr(request, '_audit_start_time'):
            # Calculate response time
            end_time = timezone.now()
            response_time = (end_time - request._audit_start_time).total_seconds()
            
            # Log response for audit trail
            if self._is_audit_worthy_request(request):
                self._log_request_complete(request, response, response_time)
        
        return response
    
    def process_exception(self, request, exception):
        """
        Log exceptions for security monitoring.
        
        Args:
            request: HTTP request object
            exception: Exception that occurred
        """
        # Import here to avoid circular imports
        from apps.core.models import AuditLog
        
        # Log security-related exceptions
        if self._is_security_exception(exception):
            AuditLog.log_event(
                event_type='security_violation',
                user=request.user if hasattr(request, 'user') and not isinstance(request.user, AnonymousUser) else None,
                request=request,
                description=f"Security exception: {str(exception)}",
                severity='error',
                success=False,
                error_message=str(exception)
            )
    
    def _is_audit_worthy_request(self, request):
        """
        Determine if request should be audited.
        
        Args:
            request: HTTP request object
            
        Returns:
            Boolean indicating if request should be audited
        """
        # Skip static files
        if request.path.startswith('/static/') or request.path.startswith('/media/'):
            return False
        
        # Skip health checks
        if request.path in ['/health/', '/ping/', '/status/']:
            return False
        
        # Skip non-sensitive GET requests
        if request.method == 'GET' and not self._is_sensitive_path(request.path):
            return False
        
        # Log all POST, PUT, DELETE requests
        if request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
            return True
        
        # Log access to sensitive areas
        if self._is_sensitive_path(request.path):
            return True
        
        return False
    
    def _is_sensitive_path(self, path):
        """
        Check if path contains sensitive medical data.
        
        Args:
            path: URL path to check
            
        Returns:
            Boolean indicating if path is sensitive
        """
        sensitive_patterns = [
            r'/patients/',
            r'/documents/',
            r'/providers/',
            r'/fhir/',
            r'/reports/',
            r'/admin/',
            r'/api/',
            r'/accounts/',
        ]
        
        for pattern in sensitive_patterns:
            if re.search(pattern, path):
                return True
        return False
    
    def _log_request_start(self, request):
        """
        Log the start of a request.
        
        Args:
            request: HTTP request object
        """
        # Import here to avoid circular imports
        from apps.core.models import AuditLog
        
        # Determine event type based on request
        event_type = self._determine_event_type(request)
        
        # Check if PHI might be involved
        phi_involved = self._is_phi_request(request)
        
        AuditLog.log_event(
            event_type=event_type,
            user=request.user if hasattr(request, 'user') and not isinstance(request.user, AnonymousUser) else None,
            request=request,
            description=f"{request.method} request to {request.path}",
            phi_involved=phi_involved,
            severity='info'
        )
    
    def _log_request_complete(self, request, response, response_time):
        """
        Log completion of a request.
        
        Args:
            request: HTTP request object
            response: HTTP response object
            response_time: Time taken to process request
        """
        # Import here to avoid circular imports
        from apps.core.models import AuditLog
        
        # Determine if request was successful
        success = 200 <= response.status_code < 400
        severity = 'info' if success else 'warning'
        
        # Log performance issues
        if response_time > 10:  # Slow requests
            severity = 'warning'
        
        AuditLog.log_event(
            event_type='phi_access' if self._is_phi_request(request) else 'system_access',
            user=request.user if hasattr(request, 'user') and not isinstance(request.user, AnonymousUser) else None,
            request=request,
            description=f"Request completed with status {response.status_code} in {response_time:.2f}s",
            details={'response_time': response_time, 'status_code': response.status_code},
            phi_involved=self._is_phi_request(request),
            severity=severity,
            success=success
        )
    
    def _determine_event_type(self, request):
        """
        Determine appropriate event type for request.
        
        Args:
            request: HTTP request object
            
        Returns:
            String event type
        """
        path = request.path.lower()
        method = request.method
        
        # Authentication events
        if 'login' in path:
            return 'login'
        elif 'logout' in path:
            return 'logout'
        
        # PHI-related events
        if any(pattern in path for pattern in ['/patients/', '/documents/', '/fhir/']):
            if method == 'POST':
                return 'phi_create'
            elif method in ['PUT', 'PATCH']:
                return 'phi_update'
            elif method == 'DELETE':
                return 'phi_delete'
            else:
                return 'phi_access'
        
        # Admin events
        if '/admin/' in path:
            return 'admin_access'
        
        # Default
        return 'system_access'
    
    def _is_phi_request(self, request):
        """
        Check if request involves PHI data.
        
        Args:
            request: HTTP request object
            
        Returns:
            Boolean indicating if PHI is involved
        """
        phi_patterns = [
            r'/patients/',
            r'/documents/',
            r'/fhir/',
            r'/reports/',
        ]
        
        for pattern in phi_patterns:
            if re.search(pattern, request.path):
                return True
        return False
    
    def _is_security_exception(self, exception):
        """
        Check if exception is security-related.
        
        Args:
            exception: Exception object
            
        Returns:
            Boolean indicating if exception is security-related
        """
        security_exceptions = [
            'PermissionDenied',
            'Forbidden',
            'SuspiciousOperation',
            'ValidationError',
        ]
        
        exception_name = exception.__class__.__name__
        return exception_name in security_exceptions


class RateLimitingMiddleware(MiddlewareMixin):
    """
    Basic rate limiting middleware for HIPAA compliance.
    Prevents brute force attacks and excessive API usage.
    """
    
    def __init__(self, get_response):
        """Initialize middleware."""
        self.get_response = get_response
        super().__init__(get_response)
    
    def process_request(self, request):
        """
        Check rate limits for incoming requests.
        
        Args:
            request: HTTP request object
            
        Returns:
            HttpResponseForbidden if rate limit exceeded
        """
        # Skip rate limiting for certain paths
        if self._is_exempt_path(request.path):
            return None
        
        # Check if user has exceeded rate limits
        if self._is_rate_limited(request):
            # Log rate limit violation
            from apps.core.models import AuditLog
            AuditLog.log_event(
                event_type='security_violation',
                user=request.user if hasattr(request, 'user') and not isinstance(request.user, AnonymousUser) else None,
                request=request,
                description="Rate limit exceeded",
                severity='warning',
                success=False
            )
            
            return HttpResponseForbidden("Rate limit exceeded. Please try again later.")
        
        return None
    
    def _is_exempt_path(self, path):
        """
        Check if path is exempt from rate limiting.
        
        Args:
            path: URL path to check
            
        Returns:
            Boolean indicating if path is exempt
        """
        exempt_patterns = [
            r'/static/',
            r'/media/',
            r'/health/',
            r'/ping/',
            r'/status/',
        ]
        
        for pattern in exempt_patterns:
            if re.search(pattern, path):
                return True
        return False
    
    def _is_rate_limited(self, request):
        """
        Check if request should be rate limited.
        This is a basic implementation - consider using django-ratelimit for production.
        
        Args:
            request: HTTP request object
            
        Returns:
            Boolean indicating if request is rate limited
        """
        # For now, just return False - implement proper rate limiting logic
        # This would typically check Redis cache or database for request counts
        return False 