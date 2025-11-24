"""
Core utility functions for the medical document parser system.
Provides common functionality for activity logging, HIPAA compliance, and dashboard operations.
"""
from django.apps import apps
from django.utils import timezone
from django.contrib.auth.models import User
import logging

logger = logging.getLogger(__name__)


def log_user_activity(user, activity_type, description, request=None, 
                     related_object_type=None, related_object_id=None):
    """
    Log user activity for HIPAA compliance and audit trail.
    Uses the AuditLog model.
    
    Args:
        user: User who performed the activity
        activity_type: Type of activity (must match AuditLog event types ideally)
        description: Human-readable description
        request: HTTP request object (optional, for IP and user agent)
        related_object_type: Type of related object (optional)
        related_object_id: ID of related object (optional)
    
    Returns:
        AuditLog instance or None if logging failed
    """
    try:
        from apps.core.models import AuditLog
        
        # Map activity_type to AuditLog event_type if needed, or pass through
        # AuditLog.log_event handles most details
        return AuditLog.log_event(
            event_type=activity_type,
            user=user,
            request=request,
            description=description,
            # We can put related object info in details if needed, 
            # or construct content_object if we had the instance.
            # For now, basic logging is a huge step up.
            details={
                'related_object_type': related_object_type,
                'related_object_id': related_object_id
            }
        )
    except Exception as e:
        logger.error(f"Error logging activity: {e}")
        return None


def get_model_count(app_name, model_name):
    """
    Safely get count of objects from a model that may not exist yet.
    
    Args:
        app_name (str): Name of the Django app
        model_name (str): Name of the model
    
    Returns:
        int: Count of objects, 0 if model doesn't exist or has no objects
    """
    try:
        Model = apps.get_model(app_name, model_name)
        count = Model.objects.count()
        logger.debug(f"Found {count} {model_name} objects in {app_name}")
        return count
    except (LookupError, AttributeError):
        logger.debug(f"{model_name} model not found in {app_name}, returning 0")
        return 0
    except Exception as e:
        logger.error(f"Error counting {model_name} objects: {e}")
        return 0


def get_client_ip(request):
    """
    Extract client IP address from request, handling proxies.
    
    Args:
        request: Django HTTP request object
    
    Returns:
        str: Client IP address or None if not available
    """
    if not request:
        return None
    
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # Take the first IP in the list (real client)
        return x_forwarded_for.split(',')[0].strip()
    else:
        return request.META.get('REMOTE_ADDR')


def get_user_agent(request):
    """
    Extract user agent from request.
    
    Args:
        request: Django HTTP request object
    
    Returns:
        str: User agent string or None if not available
    """
    if not request:
        return None
    
    return request.META.get('HTTP_USER_AGENT')


def create_activity_context(user, activity_type, description, request=None):
    """
    Create a standardized context dict for activity logging.
    Useful for delayed logging or batch operations.
    
    Args:
        user: User who performed the activity
        activity_type: Type of activity
        description: Human-readable description
        request: HTTP request object (optional)
    
    Returns:
        dict: Context suitable for Activity.objects.create()
    """
    context = {
        'user': user,
        'activity_type': activity_type,
        'description': description,
        'timestamp': timezone.now(),
    }
    
    if request:
        context['ip_address'] = get_client_ip(request)
        context['user_agent'] = get_user_agent(request)
    
    return context


def safe_model_operation(app_name, model_name, operation, default_return=None):
    """
    Safely perform an operation on a model that may not exist.
    
    Args:
        app_name (str): Name of the Django app
        model_name (str): Name of the model
        operation (callable): Function to call with the model as argument
        default_return: Value to return if model doesn't exist or operation fails
    
    Returns:
        Result of operation or default_return
    """
    try:
        Model = apps.get_model(app_name, model_name)
        return operation(Model)
    except (LookupError, AttributeError):
        logger.debug(f"{model_name} model not found in {app_name}")
        return default_return
    except Exception as e:
        logger.error(f"Error in {app_name}.{model_name} operation: {e}")
        return default_return


class ActivityTypes:
    """
    Constants for activity types to ensure consistency across the system.
    Must match Activity.ACTIVITY_TYPES choices.
    """
    LOGIN = 'login'
    LOGOUT = 'logout'
    DOCUMENT_UPLOAD = 'document_upload'
    DOCUMENT_PROCESS = 'document_process'
    PATIENT_CREATE = 'patient_create'
    PATIENT_UPDATE = 'patient_update'
    PATIENT_VIEW = 'patient_view'
    PROVIDER_CREATE = 'provider_create'
    PROVIDER_UPDATE = 'provider_update'
    PROVIDER_VIEW = 'provider_view'
    REPORT_GENERATE = 'report_generate'
    PROFILE_UPDATE = 'profile_update'
    ADMIN = 'admin_action' 