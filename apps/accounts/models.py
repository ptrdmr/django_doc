"""
Account models for user management.
Provides a simplified two-tier access model: Moritrac Admin (is_staff) and User.
"""

from django.db import models
from django.conf import settings
from django.utils import timezone


class UserProfile(models.Model):
    """
    Extended user profile with metadata and security features.

    Access control is handled by Django's built-in is_staff field:
    - is_staff=True -> Moritrac Admin (full access, all patients)
    - is_staff=False -> User (own patients only)
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )

    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    # Security
    is_locked = models.BooleanField(default=False)
    lockout_until = models.DateTimeField(null=True, blank=True)

    # Profile metadata
    department = models.CharField(max_length=100, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_profiles'
        ordering = ['user__email']
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['is_locked']),
        ]
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    def __str__(self):
        return f"{self.user.email}'s profile"

    @property
    def is_moritrac_admin(self):
        """Whether this user is a Moritrac Admin (has full access)."""
        return self.user.is_staff

    def is_account_locked(self):
        """Check if the account is currently locked."""
        if not self.is_locked:
            return False
        if self.lockout_until and timezone.now() > self.lockout_until:
            self.is_locked = False
            self.lockout_until = None
            self.save(update_fields=['is_locked', 'lockout_until'])
            return False
        return True

    def lock_account(self, duration_minutes=60):
        """Lock the user account for a specified duration."""
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
        """Get or create a UserProfile for the given user."""
        profile, _ = cls.objects.get_or_create(user=user)
        return profile
