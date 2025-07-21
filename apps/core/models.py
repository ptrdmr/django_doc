"""
Core models for the medical document parser.
Includes audit logging for HIPAA compliance.
"""

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
import json


class AuditLog(models.Model):
    """
    Comprehensive audit log for HIPAA compliance.
    Tracks all PHI access, user activities, and security events.
    """
    
    # Event types for HIPAA compliance
    EVENT_TYPES = [
        ('login', 'User Login'),
        ('logout', 'User Logout'),
        ('login_failed', 'Failed Login Attempt'),
        ('password_change', 'Password Change'),
        ('password_reset', 'Password Reset'),
        ('account_locked', 'Account Locked'),
        ('account_unlocked', 'Account Unlocked'),
        ('phi_access', 'PHI Data Access'),
        ('phi_create', 'PHI Data Creation'),
        ('phi_update', 'PHI Data Update'),
        ('phi_delete', 'PHI Data Deletion'),
        ('phi_export', 'PHI Data Export'),
        ('document_upload', 'Document Upload'),
        ('document_download', 'Document Download'),
        ('document_view', 'Document View'),
        ('document_delete', 'Document Delete'),
        ('patient_create', 'Patient Created'),
        ('patient_update', 'Patient Updated'),
        ('patient_view', 'Patient Viewed'),
        ('patient_search', 'Patient Search'),
        ('fhir_export', 'FHIR Export'),
        ('fhir_import', 'FHIR Import'),
        ('system_backup', 'System Backup'),
        ('system_restore', 'System Restore'),
        ('admin_access', 'Admin Panel Access'),
        ('config_change', 'Configuration Change'),
        ('security_violation', 'Security Violation'),
        ('data_breach', 'Data Breach Incident'),
        ('unauthorized_access', 'Unauthorized Access Attempt'),
    ]
    
    # Event categories for filtering
    CATEGORIES = [
        ('authentication', 'Authentication'),
        ('authorization', 'Authorization'),
        ('data_access', 'Data Access'),
        ('data_modification', 'Data Modification'),
        ('system_admin', 'System Administration'),
        ('security', 'Security'),
        ('compliance', 'Compliance'),
    ]
    
    # Severity levels
    SEVERITY_LEVELS = [
        ('info', 'Information'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]
    
    # Core audit fields
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES, db_index=True)
    category = models.CharField(max_length=50, choices=CATEGORIES, db_index=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_LEVELS, default='info', db_index=True)
    
    # User information
    user = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True)
    username = models.CharField(max_length=150, blank=True)  # Store username even if user is deleted
    user_email = models.EmailField(blank=True)
    
    # Session and request information
    session_key = models.CharField(max_length=40, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    request_method = models.CharField(max_length=10, blank=True)
    request_url = models.URLField(blank=True)
    
    # Generic foreign key for related objects
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Event details
    description = models.TextField()
    details = models.JSONField(default=dict, blank=True)  # Additional event data
    
    # HIPAA-specific fields
    patient_mrn = models.CharField(max_length=50, blank=True, db_index=True)  # For patient-related events
    phi_involved = models.BooleanField(default=False, db_index=True)  # Whether PHI was involved
    
    # Outcome and status
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    
    class Meta:
        db_table = 'audit_logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['timestamp', 'event_type']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['patient_mrn', 'timestamp']),
            models.Index(fields=['phi_involved', 'timestamp']),
            models.Index(fields=['severity', 'timestamp']),
            models.Index(fields=['category', 'timestamp']),
        ]
    
    def __str__(self):
        """String representation of audit log entry."""
        return f"{self.timestamp} - {self.event_type} - {self.username or 'Anonymous'}"
    
    @classmethod
    def log_event(cls, event_type, user=None, request=None, description="", 
                  details=None, patient_mrn=None, phi_involved=False, 
                  content_object=None, severity='info', success=True, error_message=""):
        """
        Create an audit log entry with comprehensive information.
        
        Args:
            event_type: The type of event (must be in EVENT_TYPES)
            user: User who performed the action
            request: HTTP request object
            description: Human-readable description
            details: Additional data as dict
            patient_mrn: Patient MRN if applicable
            phi_involved: Whether PHI was involved
            content_object: Related object
            severity: Severity level
            success: Whether the action succeeded
            error_message: Error message if failed
        """
        # Determine category based on event type
        category_mapping = {
            'login': 'authentication',
            'logout': 'authentication',
            'login_failed': 'authentication',
            'password_change': 'authentication',
            'password_reset': 'authentication',
            'account_locked': 'authentication',
            'account_unlocked': 'authentication',
            'phi_access': 'data_access',
            'phi_create': 'data_modification',
            'phi_update': 'data_modification',
            'phi_delete': 'data_modification',
            'phi_export': 'data_access',
            'document_upload': 'data_modification',
            'document_download': 'data_access',
            'document_view': 'data_access',
            'document_delete': 'data_modification',
            'patient_create': 'data_modification',
            'patient_update': 'data_modification',
            'patient_view': 'data_access',
            'patient_search': 'data_access',
            'fhir_export': 'data_access',
            'fhir_import': 'data_modification',
            'system_backup': 'system_admin',
            'system_restore': 'system_admin',
            'admin_access': 'system_admin',
            'config_change': 'system_admin',
            'security_violation': 'security',
            'data_breach': 'security',
            'unauthorized_access': 'security',
        }
        
        # Extract request information
        ip_address = None
        user_agent = ""
        request_method = ""
        request_url = ""
        session_key = ""
        
        if request:
            ip_address = cls._get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]  # Truncate to avoid issues
            request_method = request.method
            request_url = request.build_absolute_uri()
            session_key = request.session.session_key or ""
        
        # Create audit log entry
        audit_log = cls.objects.create(
            event_type=event_type,
            category=category_mapping.get(event_type, 'compliance'),
            severity=severity,
            user=user,
            username=user.username if user else "",
            user_email=user.email if user else "",
            session_key=session_key,
            ip_address=ip_address,
            user_agent=user_agent,
            request_method=request_method,
            request_url=request_url,
            content_object=content_object,
            description=description,
            details=details or {},
            patient_mrn=patient_mrn or "",
            phi_involved=phi_involved,
            success=success,
            error_message=error_message,
        )
        
        return audit_log
    
    @staticmethod
    def _get_client_ip(request):
        """Extract client IP address from request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def to_dict(self):
        """Convert audit log to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'event_type': self.event_type,
            'category': self.category,
            'severity': self.severity,
            'user': self.username,
            'user_email': self.user_email,
            'ip_address': self.ip_address,
            'description': self.description,
            'details': self.details,
            'patient_mrn': self.patient_mrn,
            'phi_involved': self.phi_involved,
            'success': self.success,
            'error_message': self.error_message,
        }


class SecurityEvent(models.Model):
    """
    High-priority security events that require immediate attention.
    These are automatically generated for critical security violations.
    """
    
    THREAT_LEVELS = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]
    
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('investigating', 'Investigating'),
        ('resolved', 'Resolved'),
        ('false_positive', 'False Positive'),
    ]
    
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    threat_level = models.CharField(max_length=20, choices=THREAT_LEVELS, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open', db_index=True)
    
    # Related audit log entry
    audit_log = models.ForeignKey(AuditLog, on_delete=models.CASCADE, related_name='security_events')
    
    # Event details
    title = models.CharField(max_length=200)
    description = models.TextField()
    mitigation_steps = models.TextField(blank=True)
    
    # Investigation details
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    investigation_notes = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_security_events')
    
    class Meta:
        db_table = 'security_events'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['threat_level', 'status']),
            models.Index(fields=['timestamp', 'threat_level']),
        ]
    
    def __str__(self):
        """String representation of security event."""
        return f"{self.timestamp} - {self.threat_level.upper()} - {self.title}"
    
    def resolve(self, resolved_by, notes=""):
        """Mark security event as resolved."""
        self.status = 'resolved'
        self.resolved_at = timezone.now()
        self.resolved_by = resolved_by
        if notes:
            self.investigation_notes = notes
        self.save()
    
    @classmethod
    def create_from_audit_log(cls, audit_log, threat_level='medium', title="", description=""):
        """Create a security event from an audit log entry."""
        security_event = cls.objects.create(
            audit_log=audit_log,
            threat_level=threat_level,
            title=title or f"Security Event: {audit_log.event_type}",
            description=description or audit_log.description,
        )
        return security_event


class ComplianceReport(models.Model):
    """
    Periodic compliance reports for HIPAA auditing.
    Generated automatically to track compliance metrics.
    """
    
    REPORT_TYPES = [
        ('daily', 'Daily Summary'),
        ('weekly', 'Weekly Summary'),
        ('monthly', 'Monthly Summary'),
        ('quarterly', 'Quarterly Summary'),
        ('annual', 'Annual Summary'),
        ('incident', 'Incident Report'),
        ('audit', 'Audit Report'),
    ]
    
    timestamp = models.DateTimeField(auto_now_add=True)
    report_type = models.CharField(max_length=20, choices=REPORT_TYPES)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    
    # Report data
    total_events = models.IntegerField(default=0)
    phi_access_events = models.IntegerField(default=0)
    failed_login_attempts = models.IntegerField(default=0)
    security_violations = models.IntegerField(default=0)
    
    # Compliance metrics
    compliance_score = models.DecimalField(max_digits=5, decimal_places=2, default=100.00)
    recommendations = models.TextField(blank=True)
    
    # Report file
    report_file = models.FileField(upload_to='compliance_reports/', null=True, blank=True)
    
    class Meta:
        db_table = 'compliance_reports'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['report_type', 'timestamp']),
            models.Index(fields=['period_start', 'period_end']),
        ]
    
    def __str__(self):
        """String representation of compliance report."""
        return f"{self.report_type} Report - {self.period_start.date()} to {self.period_end.date()}"


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
