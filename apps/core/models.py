from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Activity(models.Model):
    """
    Model to track user activities throughout the system for audit trail and dashboard.
    Follows HIPAA compliance requirements for activity logging.
    """
    ACTIVITY_TYPES = [
        ('login', 'User Login'),
        ('logout', 'User Logout'),
        ('document_upload', 'Document Upload'),
        ('document_process', 'Document Processing'),
        ('patient_create', 'Patient Created'),
        ('patient_update', 'Patient Updated'),
        ('patient_view', 'Patient Viewed'),
        ('provider_create', 'Provider Created'),
        ('provider_update', 'Provider Updated'),
        ('provider_view', 'Provider Viewed'),
        ('report_generate', 'Report Generated'),
        ('profile_update', 'Profile Updated'),
    ]
    
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        help_text="User who performed the activity"
    )
    activity_type = models.CharField(
        max_length=50, 
        choices=ACTIVITY_TYPES,
        help_text="Type of activity performed"
    )
    description = models.CharField(
        max_length=255,
        help_text="Human-readable description of the activity"
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        help_text="When the activity occurred"
    )
    ip_address = models.GenericIPAddressField(
        null=True, 
        blank=True,
        help_text="IP address where activity originated (for HIPAA compliance)"
    )
    user_agent = models.TextField(
        null=True, 
        blank=True,
        help_text="Browser/client information (for HIPAA compliance)"
    )
    
    # Optional reference to related objects
    related_object_type = models.CharField(
        max_length=50, 
        null=True, 
        blank=True,
        help_text="Type of object this activity relates to (e.g., 'patient', 'document')"
    )
    related_object_id = models.CharField(
        max_length=50, 
        null=True, 
        blank=True,
        help_text="ID of the related object"
    )
    
    class Meta:
        db_table = 'core_activities'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['activity_type', '-timestamp']),
            models.Index(fields=['-timestamp']),
        ]
        verbose_name = 'Activity'
        verbose_name_plural = 'Activities'
    
    def __str__(self):
        """String representation of the activity"""
        return f"{self.user.username} - {self.get_activity_type_display()} at {self.timestamp}"
    
    @classmethod
    def log_activity(cls, user, activity_type, description, request=None, 
                    related_object_type=None, related_object_id=None):
        """
        Convenience method to log an activity.
        
        Args:
            user: User who performed the activity
            activity_type: Type of activity (must be in ACTIVITY_TYPES)
            description: Human-readable description
            request: HTTP request object (optional, for IP and user agent)
            related_object_type: Type of related object (optional)
            related_object_id: ID of related object (optional)
        
        Returns:
            Activity instance
        """
        ip_address = None
        user_agent = None
        
        if request:
            # Extract IP address
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0]
            else:
                ip_address = request.META.get('REMOTE_ADDR')
            
            # Extract user agent
            user_agent = request.META.get('HTTP_USER_AGENT')
        
        return cls.objects.create(
            user=user,
            activity_type=activity_type,
            description=description,
            ip_address=ip_address,
            user_agent=user_agent,
            related_object_type=related_object_type,
            related_object_id=related_object_id
        )


class BaseModel(models.Model):
    """
    Abstract base model with common audit fields.
    All app models should inherit from this for consistency.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.PROTECT, 
        null=True, 
        blank=True,
        related_name='%(class)s_created'
    )
    updated_by = models.ForeignKey(
        User, 
        on_delete=models.PROTECT, 
        null=True, 
        blank=True,
        related_name='%(class)s_updated'
    )
    
    class Meta:
        abstract = True
