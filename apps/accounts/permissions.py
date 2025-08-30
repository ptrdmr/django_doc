"""
Permission checking utilities for role-based access control.
Provides efficient permission checking with session-based caching for optimal performance.
"""

from typing import List, Set, Optional, Union
from django.contrib.auth.models import User, Permission
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.conf import settings
import logging
import hashlib

logger = logging.getLogger(__name__)


class PermissionChecker:
    """
    Centralized permission checking utility with intelligent caching.
    
    Provides fast permission checks for users and roles while maintaining
    HIPAA compliance and audit trail integration.
    """
    
    # Cache timeouts (in seconds)
    USER_PERMISSIONS_CACHE_TIMEOUT = getattr(settings, 'USER_PERMISSIONS_CACHE_TIMEOUT', 300)  # 5 minutes
    ROLE_PERMISSIONS_CACHE_TIMEOUT = getattr(settings, 'ROLE_PERMISSIONS_CACHE_TIMEOUT', 900)  # 15 minutes
    
    @classmethod
    def get_cache_key(cls, prefix: str, identifier: Union[str, int]) -> str:
        """
        Generate a consistent cache key for permissions.
        
        Args:
            prefix: Cache key prefix (e.g., 'user_perms', 'role_perms')
            identifier: User ID, role ID, or other identifier
        
        Returns:
            str: Formatted cache key
        """
        # Use hash for consistent key length
        hash_input = f"{prefix}_{identifier}".encode('utf-8')
        hash_digest = hashlib.md5(hash_input).hexdigest()[:16]
        return f"rbac_{prefix}_{hash_digest}"
    
    @classmethod
    def get_user_permissions_cached(cls, user: User) -> Set[str]:
        """
        Get all permissions for a user with caching.
        
        Combines direct user permissions and role-based permissions
        with intelligent session-based caching.
        
        Args:
            user: User instance
        
        Returns:
            Set[str]: Set of permission codenames (e.g., {'patients.view_patient'})
        """
        if not user.is_authenticated:
            return set()
        
        cache_key = cls.get_cache_key('user_perms', user.id)
        
        # Try to get from cache first
        cached_permissions = cache.get(cache_key)
        if cached_permissions is not None:
            logger.debug(f"Permission cache hit for user {user.id}")
            return cached_permissions
        
        # Cache miss - calculate permissions
        logger.debug(f"Permission cache miss for user {user.id}, calculating...")
        
        permissions = set()
        
        try:
            # Get direct user permissions
            for perm in user.get_all_permissions():
                permissions.add(perm)
            
            # Get role-based permissions
            if hasattr(user, 'profile'):
                profile = user.profile
                for role in profile.roles.filter(is_active=True):
                    role_permissions = cls.get_role_permissions_cached(role)
                    permissions.update(role_permissions)
            
            # Cache the result
            cache.set(cache_key, permissions, cls.USER_PERMISSIONS_CACHE_TIMEOUT)
            logger.debug(f"Cached {len(permissions)} permissions for user {user.id}")
            
        except Exception as e:
            logger.error(f"Error getting permissions for user {user.id}: {e}")
            # Return empty set on error to fail safe
            return set()
        
        return permissions
    
    @classmethod
    def get_role_permissions_cached(cls, role) -> Set[str]:
        """
        Get all permissions for a role with caching.
        
        Args:
            role: Role instance
        
        Returns:
            Set[str]: Set of permission codenames
        """
        cache_key = cls.get_cache_key('role_perms', role.id)
        
        # Try to get from cache first
        cached_permissions = cache.get(cache_key)
        if cached_permissions is not None:
            return cached_permissions
        
        # Cache miss - get permissions from role
        permissions = set(role.get_permissions_list())
        
        # Cache the result
        cache.set(cache_key, permissions, cls.ROLE_PERMISSIONS_CACHE_TIMEOUT)
        
        return permissions
    
    @classmethod
    def user_has_permission(cls, user: User, permission_codename: str) -> bool:
        """
        Check if a user has a specific permission.
        
        Uses cached permissions for optimal performance.
        
        Args:
            user: User instance
            permission_codename: Permission codename (e.g., 'patients.view_patient')
        
        Returns:
            bool: True if user has the permission
        """
        if not user.is_authenticated:
            return False
        
        # Superusers always have all permissions
        if user.is_superuser:
            return True
        
        # Check account lock status
        if hasattr(user, 'profile') and user.profile.is_account_locked():
            logger.warning(f"Access denied for locked user {user.id}")
            return False
        
        user_permissions = cls.get_user_permissions_cached(user)
        return permission_codename in user_permissions
    
    @classmethod
    def user_has_role(cls, user: User, role_name: str) -> bool:
        """
        Check if a user has a specific role.
        
        Args:
            user: User instance
            role_name: Role name (e.g., 'admin', 'provider')
        
        Returns:
            bool: True if user has the role
        """
        if not user.is_authenticated:
            return False
        
        try:
            if hasattr(user, 'profile'):
                return user.profile.has_role(role_name)
            return False
        except Exception as e:
            logger.error(f"Error checking role {role_name} for user {user.id}: {e}")
            return False
    
    @classmethod
    def user_has_any_role(cls, user: User, role_names: List[str]) -> bool:
        """
        Check if a user has any of the specified roles.
        
        Args:
            user: User instance
            role_names: List of role names to check
        
        Returns:
            bool: True if user has any of the roles
        """
        if not user.is_authenticated:
            return False
        
        try:
            if hasattr(user, 'profile'):
                return user.profile.has_any_role(role_names)
            return False
        except Exception as e:
            logger.error(f"Error checking roles {role_names} for user {user.id}: {e}")
            return False
    
    @classmethod
    def user_can_access_phi(cls, user: User) -> bool:
        """
        Check if a user can access Protected Health Information.
        
        PHI access is restricted to admin and provider roles only.
        
        Args:
            user: User instance
        
        Returns:
            bool: True if user can access PHI
        """
        if not user.is_authenticated:
            return False
        
        # Superusers can always access PHI
        if user.is_superuser:
            return True
        
        try:
            if hasattr(user, 'profile'):
                return user.profile.can_access_phi()
            return False
        except Exception as e:
            logger.error(f"Error checking PHI access for user {user.id}: {e}")
            return False
    
    @classmethod
    def invalidate_user_cache(cls, user: User) -> None:
        """
        Invalidate cached permissions for a user.
        
        Call this when user roles or permissions change.
        
        Args:
            user: User instance
        """
        cache_key = cls.get_cache_key('user_perms', user.id)
        cache.delete(cache_key)
        logger.debug(f"Invalidated permission cache for user {user.id}")
    
    @classmethod
    def invalidate_role_cache(cls, role) -> None:
        """
        Invalidate cached permissions for a role.
        
        Call this when role permissions change.
        
        Args:
            role: Role instance
        """
        cache_key = cls.get_cache_key('role_perms', role.id)
        cache.delete(cache_key)
        logger.debug(f"Invalidated permission cache for role {role.id}")
    
    @classmethod
    def invalidate_all_caches(cls) -> None:
        """
        Invalidate all permission-related caches.
        
        Use this for system-wide permission changes.
        """
        # This is a simple implementation - in production you might want
        # to use cache versioning or tagged caching for more efficiency
        cache.clear()
        logger.info("Invalidated all permission caches")


# Convenience functions for common permission checks
def user_has_permission(user: User, permission_codename: str) -> bool:
    """
    Convenience function to check if user has permission.
    
    Args:
        user: User instance
        permission_codename: Permission codename
    
    Returns:
        bool: True if user has permission
    """
    return PermissionChecker.user_has_permission(user, permission_codename)


def user_has_role(user: User, role_name: str) -> bool:
    """
    Convenience function to check if user has role.
    
    Args:
        user: User instance
        role_name: Role name
    
    Returns:
        bool: True if user has role
    """
    return PermissionChecker.user_has_role(user, role_name)


def user_has_any_role(user: User, role_names: List[str]) -> bool:
    """
    Convenience function to check if user has any of the specified roles.
    
    Args:
        user: User instance
        role_names: List of role names
    
    Returns:
        bool: True if user has any role
    """
    return PermissionChecker.user_has_any_role(user, role_names)


def user_can_access_phi(user: User) -> bool:
    """
    Convenience function to check PHI access.
    
    Args:
        user: User instance
    
    Returns:
        bool: True if user can access PHI
    """
    return PermissionChecker.user_can_access_phi(user)


def require_permission(user: User, permission_codename: str) -> None:
    """
    Require that a user has a specific permission or raise PermissionDenied.
    
    Args:
        user: User instance
        permission_codename: Permission codename
    
    Raises:
        PermissionDenied: If user doesn't have permission
    """
    if not user_has_permission(user, permission_codename):
        raise PermissionDenied(f"Permission required: {permission_codename}")


def require_role(user: User, role_name: str) -> None:
    """
    Require that a user has a specific role or raise PermissionDenied.
    
    Args:
        user: User instance
        role_name: Role name
    
    Raises:
        PermissionDenied: If user doesn't have role
    """
    if not user_has_role(user, role_name):
        raise PermissionDenied(f"Role required: {role_name}")


def require_any_role(user: User, role_names: List[str]) -> None:
    """
    Require that a user has any of the specified roles or raise PermissionDenied.
    
    Args:
        user: User instance
        role_names: List of role names
    
    Raises:
        PermissionDenied: If user doesn't have any role
    """
    if not user_has_any_role(user, role_names):
        roles_str = ', '.join(role_names)
        raise PermissionDenied(f"One of these roles required: {roles_str}")


def require_phi_access(user: User) -> None:
    """
    Require that a user can access PHI or raise PermissionDenied.
    
    Args:
        user: User instance
    
    Raises:
        PermissionDenied: If user cannot access PHI
    """
    if not user_can_access_phi(user):
        raise PermissionDenied("PHI access required (admin or provider role)")


# Session-based permission caching utilities
class SessionPermissionCache:
    """
    Session-based permission caching for enhanced performance.
    
    Stores user permissions in the session to reduce database queries
    during a user's active session.
    """
    
    SESSION_KEY_PREFIX = 'rbac_permissions_'
    SESSION_ROLES_KEY = 'rbac_roles'
    SESSION_CACHE_VERSION = 'rbac_cache_v1'  # Increment to invalidate all session caches
    
    @classmethod
    def get_session_cache_key(cls, user_id: int) -> str:
        """Generate session cache key for user permissions."""
        return f"{cls.SESSION_KEY_PREFIX}{user_id}"
    
    @classmethod
    def get_user_permissions_from_session(cls, request, user: User) -> Optional[Set[str]]:
        """
        Get user permissions from session cache.
        
        Args:
            request: Django request object
            user: User instance
        
        Returns:
            Set[str] or None: Cached permissions or None if not cached
        """
        if not hasattr(request, 'session'):
            return None
        
        cache_key = cls.get_session_cache_key(user.id)
        
        # Check cache version
        if request.session.get('rbac_cache_version') != cls.SESSION_CACHE_VERSION:
            cls.clear_session_cache(request)
            return None
        
        return request.session.get(cache_key)
    
    @classmethod
    def set_user_permissions_in_session(cls, request, user: User, permissions: Set[str]) -> None:
        """
        Store user permissions in session cache.
        
        Args:
            request: Django request object
            user: User instance
            permissions: Set of permission codenames
        """
        if not hasattr(request, 'session'):
            return
        
        cache_key = cls.get_session_cache_key(user.id)
        
        # Set cache version
        request.session['rbac_cache_version'] = cls.SESSION_CACHE_VERSION
        
        # Store permissions (convert set to list for JSON serialization)
        request.session[cache_key] = list(permissions)
        
        # Store user roles for quick access
        if hasattr(user, 'profile'):
            request.session[cls.SESSION_ROLES_KEY] = user.profile.get_role_names()
    
    @classmethod
    def clear_session_cache(cls, request) -> None:
        """
        Clear all RBAC-related session cache.
        
        Args:
            request: Django request object
        """
        if not hasattr(request, 'session'):
            return
        
        # Remove all RBAC session keys
        keys_to_remove = []
        for key in request.session.keys():
            if key.startswith(cls.SESSION_KEY_PREFIX) or key in [cls.SESSION_ROLES_KEY, 'rbac_cache_version']:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del request.session[key]
    
    @classmethod
    def get_user_roles_from_session(cls, request) -> Optional[List[str]]:
        """
        Get user roles from session cache.
        
        Args:
            request: Django request object
        
        Returns:
            List[str] or None: Cached role names or None if not cached
        """
        if not hasattr(request, 'session'):
            return None
        
        # Check cache version
        if request.session.get('rbac_cache_version') != cls.SESSION_CACHE_VERSION:
            return None
        
        return request.session.get(cls.SESSION_ROLES_KEY)


# Enhanced permission checking with session caching
def user_has_permission_cached(request, user: User, permission_codename: str) -> bool:
    """
    Check if user has permission with session caching.
    
    Args:
        request: Django request object
        user: User instance
        permission_codename: Permission codename
    
    Returns:
        bool: True if user has permission
    """
    if not user.is_authenticated:
        return False
    
    # Superusers always have all permissions
    if user.is_superuser:
        return True
    
    # Try session cache first
    cached_permissions = SessionPermissionCache.get_user_permissions_from_session(request, user)
    
    if cached_permissions is not None:
        # Use cached permissions
        return permission_codename in cached_permissions
    
    # Cache miss - get permissions and cache them
    permissions = PermissionChecker.get_user_permissions_cached(user)
    SessionPermissionCache.set_user_permissions_in_session(request, user, permissions)
    
    return permission_codename in permissions


def user_has_role_cached(request, user: User, role_name: str) -> bool:
    """
    Check if user has role with session caching.
    
    Args:
        request: Django request object
        user: User instance
        role_name: Role name
    
    Returns:
        bool: True if user has role
    """
    if not user.is_authenticated:
        return False
    
    # Try session cache first
    cached_roles = SessionPermissionCache.get_user_roles_from_session(request)
    
    if cached_roles is not None:
        return role_name in cached_roles
    
    # Cache miss - check role and update cache
    has_role = PermissionChecker.user_has_role(user, role_name)
    
    if hasattr(user, 'profile'):
        # Update session cache with current roles
        roles = user.profile.get_role_names()
        SessionPermissionCache.set_user_permissions_in_session(
            request, user, 
            PermissionChecker.get_user_permissions_cached(user)
        )
    
    return has_role


# Cache invalidation utilities
def invalidate_user_permission_cache(user: User, request=None) -> None:
    """
    Invalidate permission cache for a user.
    
    Call this when user roles or permissions change.
    
    Args:
        user: User instance
        request: Optional Django request object for session cache
    """
    # Invalidate server-side cache
    PermissionChecker.invalidate_user_cache(user)
    
    # Invalidate session cache if request provided
    if request:
        SessionPermissionCache.clear_session_cache(request)


def invalidate_role_permission_cache(role, affected_users: Optional[List[User]] = None) -> None:
    """
    Invalidate permission cache for a role and optionally its users.
    
    Args:
        role: Role instance
        affected_users: Optional list of users with this role
    """
    # Invalidate role cache
    PermissionChecker.invalidate_role_cache(role)
    
    # Invalidate user caches for users with this role
    if affected_users:
        for user in affected_users:
            PermissionChecker.invalidate_user_cache(user)
    else:
        # Get all users with this role and invalidate their caches
        for profile in role.user_profiles.all():
            PermissionChecker.invalidate_user_cache(profile.user)


# Healthcare-specific permission helpers
def user_is_admin(user: User) -> bool:
    """Check if user has admin role."""
    return PermissionChecker.user_has_role(user, 'admin')


def user_is_provider(user: User) -> bool:
    """Check if user has provider role."""
    return PermissionChecker.user_has_role(user, 'provider')


def user_is_staff_member(user: User) -> bool:
    """Check if user has staff role."""
    return PermissionChecker.user_has_role(user, 'staff')


def user_is_auditor(user: User) -> bool:
    """Check if user has auditor role."""
    return PermissionChecker.user_has_role(user, 'auditor')


def user_can_process_documents(user: User) -> bool:
    """Check if user can process medical documents."""
    return PermissionChecker.user_has_any_role(user, ['admin', 'provider'])


def user_can_manage_users(user: User) -> bool:
    """Check if user can manage other users."""
    return PermissionChecker.user_has_role(user, 'admin')


def user_can_view_audit_logs(user: User) -> bool:
    """Check if user can view audit logs."""
    return PermissionChecker.user_has_any_role(user, ['admin', 'auditor', 'provider'])


# Permission validation for views
def validate_patient_access(user: User, patient=None) -> None:
    """
    Validate that user can access patient data.
    
    Args:
        user: User instance
        patient: Optional patient instance for additional checks
    
    Raises:
        PermissionDenied: If access is not allowed
    """
    if not user.is_authenticated:
        raise PermissionDenied("Authentication required")
    
    if not user_has_permission(user, 'patients.view_patient'):
        raise PermissionDenied("Permission required: patients.view_patient")
    
    # Additional patient-specific checks can be added here
    # (e.g., organization-based access, provider-patient relationships)


def validate_document_processing_access(user: User) -> None:
    """
    Validate that user can process medical documents.
    
    Args:
        user: User instance
    
    Raises:
        PermissionDenied: If access is not allowed
    """
    if not user.is_authenticated:
        raise PermissionDenied("Authentication required")
    
    if not user_can_process_documents(user):
        raise PermissionDenied("Document processing requires admin or provider role")


def validate_fhir_merge_access(user: User) -> None:
    """
    Validate that user can trigger FHIR merge operations.
    
    Args:
        user: User instance
    
    Raises:
        PermissionDenied: If access is not allowed
    """
    if not user.is_authenticated:
        raise PermissionDenied("Authentication required")
    
    if not user_has_permission(user, 'fhir.add_fhirmergeoperation'):
        raise PermissionDenied("Permission required: fhir.add_fhirmergeoperation")


def validate_audit_access(user: User) -> None:
    """
    Validate that user can access audit logs.
    
    Args:
        user: User instance
    
    Raises:
        PermissionDenied: If access is not allowed
    """
    if not user.is_authenticated:
        raise PermissionDenied("Authentication required")
    
    if not user_can_view_audit_logs(user):
        raise PermissionDenied("Audit access requires admin, auditor, or provider role")
