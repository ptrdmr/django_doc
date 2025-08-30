"""
Account models for role-based access control and user management.
Provides HIPAA-compliant user roles and permission management.
"""

from django.db import models
from django.contrib.auth.models import Permission
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
import uuid


class Role(models.Model):
    """
    Role model for defining user roles in the medical document parser.
    
    Supports four primary roles for healthcare environments:
    - Admin: Full system access with all permissions
    - Provider: Healthcare provider access to patient records and documents
    - Staff: Administrative staff with limited patient information access  
    - Auditor: Read-only access to audit logs and system reports
    """
    
    # Role identification
    id = models.UUIDField(
        primary_key=True, 
        default=uuid.uuid4, 
        editable=False,
        help_text="Unique identifier for the role"
    )
    name = models.CharField(
        max_length=100, 
        unique=True,
        help_text="Role name (e.g., 'admin', 'provider', 'staff', 'auditor')"
    )
    display_name = models.CharField(
        max_length=150,
        help_text="Human-readable role name for display in UI"
    )
    description = models.TextField(
        help_text="Detailed description of role responsibilities and access level"
    )
    
    # Permission relationships
    permissions = models.ManyToManyField(
        Permission,
        blank=True,
        related_name='roles',
        help_text="Django permissions assigned to this role"
    )
    
    # Role metadata
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this role is currently active and can be assigned"
    )
    is_system_role = models.BooleanField(
        default=False,
        help_text="Whether this is a system-defined role (cannot be deleted)"
    )
    
    # Audit fields
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this role was created"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="When this role was last updated"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='roles_created',
        help_text="User who created this role"
    )
    
    class Meta:
        db_table = 'roles'
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['is_active']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = 'Role'
        verbose_name_plural = 'Roles'
    
    def __str__(self):
        """String representation of the role."""
        return self.display_name or self.name
    
    def clean(self):
        """Validate role data."""
        # Ensure name is lowercase and alphanumeric with underscores
        if self.name:
            self.name = self.name.lower().replace('-', '_').replace(' ', '_')
            if not self.name.replace('_', '').isalnum():
                raise ValidationError({
                    'name': 'Role name must contain only letters, numbers, and underscores'
                })
        
        # Set display_name if not provided
        if not self.display_name and self.name:
            self.display_name = self.name.replace('_', ' ').title()
    
    def save(self, *args, **kwargs):
        """Override save to run validation."""
        self.clean()
        super().save(*args, **kwargs)
    
    def get_permission_count(self):
        """Get the number of permissions assigned to this role."""
        return self.permissions.count()
    
    def get_user_count(self):
        """Get the number of users assigned to this role."""
        # This will work once UserProfile model is created in subtask 22.2
        try:
            return self.user_profiles.count()
        except AttributeError:
            # UserProfile model not yet created
            return 0
    
    def has_permission(self, permission_codename):
        """
        Check if this role has a specific permission.
        
        Args:
            permission_codename: Permission codename (e.g., 'patients.view_patient')
        
        Returns:
            bool: True if role has the permission
        """
        if '.' in permission_codename:
            app_label, codename = permission_codename.split('.', 1)
            return self.permissions.filter(
                content_type__app_label=app_label,
                codename=codename
            ).exists()
        else:
            return self.permissions.filter(codename=permission_codename).exists()
    
    def add_permission(self, permission_codename):
        """
        Add a permission to this role.
        
        Args:
            permission_codename: Permission codename (e.g., 'patients.view_patient')
        
        Returns:
            bool: True if permission was added, False if already exists
        """
        try:
            if '.' in permission_codename:
                app_label, codename = permission_codename.split('.', 1)
                permission = Permission.objects.get(
                    content_type__app_label=app_label,
                    codename=codename
                )
            else:
                permission = Permission.objects.get(codename=permission_codename)
            
            if not self.permissions.filter(id=permission.id).exists():
                self.permissions.add(permission)
                return True
            return False
        except Permission.DoesNotExist:
            raise ValidationError(f"Permission '{permission_codename}' does not exist")
    
    def remove_permission(self, permission_codename):
        """
        Remove a permission from this role.
        
        Args:
            permission_codename: Permission codename (e.g., 'patients.view_patient')
        
        Returns:
            bool: True if permission was removed, False if didn't exist
        """
        try:
            if '.' in permission_codename:
                app_label, codename = permission_codename.split('.', 1)
                permission = Permission.objects.get(
                    content_type__app_label=app_label,
                    codename=codename
                )
            else:
                permission = Permission.objects.get(codename=permission_codename)
            
            if self.permissions.filter(id=permission.id).exists():
                self.permissions.remove(permission)
                return True
            return False
        except Permission.DoesNotExist:
            return False
    
    def get_permissions_list(self):
        """
        Get a list of all permission codenames for this role.
        
        Returns:
            list: List of permission codenames (e.g., ['patients.view_patient'])
        """
        return [
            f"{perm.content_type.app_label}.{perm.codename}"
            for perm in self.permissions.select_related('content_type').all()
        ]
    
    @classmethod
    def get_system_roles(cls):
        """Get all system-defined roles."""
        return cls.objects.filter(is_system_role=True)
    
    @classmethod
    def get_active_roles(cls):
        """Get all active roles available for assignment."""
        return cls.objects.filter(is_active=True)


class UserProfile(models.Model):
    """
    Extended user profile for role-based access control and user management.
    
    Provides role assignments, IP restrictions, and additional user metadata
    for HIPAA-compliant access control in healthcare environments.
    """
    
    # User relationship
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        help_text="Associated user account"
    )
    
    # Role assignments
    roles = models.ManyToManyField(
        Role,
        blank=True,
        related_name='user_profiles',
        help_text="Roles assigned to this user"
    )
    
    # IP-based access control (for future Task 24)
    allowed_ip_ranges = models.JSONField(
        default=list,
        blank=True,
        help_text="List of allowed IP ranges in CIDR notation (e.g., ['192.168.1.0/24'])"
    )
    last_login_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Last IP address used for login"
    )
    
    # Security settings
    require_mfa = models.BooleanField(
        default=True,
        help_text="Whether this user requires multi-factor authentication"
    )
    is_locked = models.BooleanField(
        default=False,
        help_text="Whether this user account is temporarily locked"
    )
    lockout_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the account lockout expires (if locked)"
    )
    
    # Profile metadata
    department = models.CharField(
        max_length=100,
        blank=True,
        help_text="User's department or division"
    )
    job_title = models.CharField(
        max_length=100,
        blank=True,
        help_text="User's job title or position"
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        help_text="Contact phone number"
    )
    
    # Audit fields
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this profile was created"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="When this profile was last updated"
    )
    
    class Meta:
        db_table = 'user_profiles'
        ordering = ['user__email']
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['last_login_ip']),
            models.Index(fields=['is_locked']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'
    
    def __str__(self):
        """String representation of the user profile."""
        return f"{self.user.email}'s profile"
    
    def get_role_names(self):
        """Get a list of role names assigned to this user."""
        return list(self.roles.values_list('name', flat=True))
    
    def get_display_roles(self):
        """Get a list of display names for assigned roles."""
        return list(self.roles.values_list('display_name', flat=True))
    
    def has_role(self, role_name):
        """
        Check if user has a specific role.
        
        Args:
            role_name: Name of the role to check
        
        Returns:
            bool: True if user has the role
        """
        return self.roles.filter(name=role_name).exists()
    
    def has_any_role(self, role_names):
        """
        Check if user has any of the specified roles.
        
        Args:
            role_names: List of role names to check
        
        Returns:
            bool: True if user has any of the roles
        """
        return self.roles.filter(name__in=role_names).exists()
    
    def has_permission(self, permission_codename):
        """
        Check if user has a specific permission through their roles.
        
        Args:
            permission_codename: Permission codename (e.g., 'patients.view_patient')
        
        Returns:
            bool: True if user has the permission through any role
        """
        # Check direct user permissions first
        if self.user.has_perm(permission_codename):
            return True
        
        # Check role-based permissions
        for role in self.roles.filter(is_active=True):
            if role.has_permission(permission_codename):
                return True
        
        return False
    
    def get_all_permissions(self):
        """
        Get all permissions available to this user through their roles.
        
        Returns:
            set: Set of permission codenames
        """
        permissions = set()
        
        # Add direct user permissions
        for perm in self.user.get_all_permissions():
            permissions.add(perm)
        
        # Add role-based permissions
        for role in self.roles.filter(is_active=True):
            permissions.update(role.get_permissions_list())
        
        return permissions
    
    def add_role(self, role_name):
        """
        Add a role to this user.
        
        Args:
            role_name: Name of the role to add
        
        Returns:
            bool: True if role was added, False if already exists
        """
        try:
            role = Role.objects.get(name=role_name, is_active=True)
            if not self.roles.filter(id=role.id).exists():
                self.roles.add(role)
                return True
            return False
        except Role.DoesNotExist:
            raise ValidationError(f"Role '{role_name}' does not exist or is not active")
    
    def remove_role(self, role_name):
        """
        Remove a role from this user.
        
        Args:
            role_name: Name of the role to remove
        
        Returns:
            bool: True if role was removed, False if didn't exist
        """
        try:
            role = Role.objects.get(name=role_name)
            if self.roles.filter(id=role.id).exists():
                self.roles.remove(role)
                return True
            return False
        except Role.DoesNotExist:
            return False
    
    def is_admin(self):
        """Check if user has admin role."""
        return self.has_role('admin')
    
    def is_provider(self):
        """Check if user has provider role.""" 
        return self.has_role('provider')
    
    def is_staff_member(self):
        """Check if user has staff role."""
        return self.has_role('staff')
    
    def is_auditor(self):
        """Check if user has auditor role."""
        return self.has_role('auditor')
    
    def can_access_phi(self):
        """
        Check if user can access Protected Health Information.
        
        Returns:
            bool: True if user has roles that allow PHI access
        """
        phi_roles = ['admin', 'provider']
        return self.has_any_role(phi_roles)
    
    def is_account_locked(self):
        """
        Check if the account is currently locked.
        
        Returns:
            bool: True if account is locked and lockout hasn't expired
        """
        if not self.is_locked:
            return False
        
        if self.lockout_until and timezone.now() > self.lockout_until:
            # Lockout has expired, unlock the account
            self.is_locked = False
            self.lockout_until = None
            self.save(update_fields=['is_locked', 'lockout_until'])
            return False
        
        return True
    
    def lock_account(self, duration_minutes=60):
        """
        Lock the user account for a specified duration.
        
        Args:
            duration_minutes: How long to lock the account (default: 1 hour)
        """
        self.is_locked = True
        self.lockout_until = timezone.now() + timezone.timedelta(minutes=duration_minutes)
        self.save(update_fields=['is_locked', 'lockout_until'])
    
    def unlock_account(self):
        """Unlock the user account."""
        self.is_locked = False
        self.lockout_until = None
        self.save(update_fields=['is_locked', 'lockout_until'])
    
    @classmethod
    def get_or_create_for_user(cls, user):
        """
        Get or create a UserProfile for the given user.
        
        Args:
            user: User instance
        
        Returns:
            UserProfile: The user's profile
        """
        profile, created = cls.objects.get_or_create(user=user)
        return profile
