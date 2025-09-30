"""
System Health Models - Track system metrics and maintenance tasks
"""
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()


class SystemHealthSnapshot(models.Model):
    """
    Periodic snapshots of system health metrics
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # Document Processing Metrics
    documents_pending = models.IntegerField(default=0)
    documents_processing = models.IntegerField(default=0)
    documents_failed_24h = models.IntegerField(default=0)
    documents_completed_24h = models.IntegerField(default=0)
    avg_processing_time_seconds = models.FloatField(null=True, blank=True)
    
    # AI API Metrics
    ai_requests_24h = models.IntegerField(default=0)
    ai_errors_24h = models.IntegerField(default=0)
    ai_cost_24h = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    ai_avg_response_time = models.FloatField(null=True, blank=True)
    
    # Database Metrics
    total_patients = models.IntegerField(default=0)
    total_providers = models.IntegerField(default=0)
    total_documents = models.IntegerField(default=0)
    db_size_mb = models.FloatField(null=True, blank=True)
    largest_table_mb = models.FloatField(null=True, blank=True)
    largest_table_name = models.CharField(max_length=100, blank=True)
    
    # Celery Metrics
    celery_active_tasks = models.IntegerField(default=0)
    celery_failed_tasks_24h = models.IntegerField(default=0)
    redis_connection_ok = models.BooleanField(default=True)
    
    # Security Metrics
    failed_login_attempts_24h = models.IntegerField(default=0)
    suspicious_audit_events_24h = models.IntegerField(default=0)
    phi_access_events_24h = models.IntegerField(default=0)
    
    # System Resources
    disk_usage_percent = models.FloatField(null=True, blank=True)
    memory_usage_percent = models.FloatField(null=True, blank=True)
    
    # Overall Health Status
    STATUS_CHOICES = [
        ('healthy', 'Healthy'),
        ('warning', 'Warning'),
        ('critical', 'Critical'),
    ]
    overall_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='healthy')
    
    class Meta:
        db_table = 'system_health_snapshots'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp', 'overall_status']),
        ]
    
    def __str__(self):
        return f"Health Snapshot - {self.timestamp.strftime('%Y-%m-%d %H:%M')} - {self.overall_status}"


class MaintenanceTask(models.Model):
    """
    Track maintenance tasks and their execution
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    TASK_TYPES = [
        ('backup', 'Database Backup'),
        ('cleanup', 'Data Cleanup'),
        ('update', 'Software Update'),
        ('security', 'Security Patch'),
        ('optimization', 'Performance Optimization'),
        ('audit', 'HIPAA Audit'),
        ('encryption', 'Encryption Key Rotation'),
    ]
    
    task_type = models.CharField(max_length=50, choices=TASK_TYPES)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    PRIORITY_CHOICES = [
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    
    # Scheduling
    scheduled_for = models.DateTimeField(null=True, blank=True, db_index=True)
    due_date = models.DateTimeField(null=True, blank=True)
    
    # Execution tracking
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Results
    result_message = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    
    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='created_maintenance_tasks'
    )
    
    class Meta:
        db_table = 'maintenance_tasks'
        ordering = ['-priority', 'scheduled_for']
        indexes = [
            models.Index(fields=['status', 'priority']),
            models.Index(fields=['scheduled_for']),
        ]
    
    def __str__(self):
        return f"{self.get_task_type_display()} - {self.title} ({self.status})"
    
    @property
    def is_overdue(self):
        """Check if task is overdue"""
        if self.due_date and self.status not in ['completed', 'skipped']:
            return timezone.now() > self.due_date
        return False


class SystemAlert(models.Model):
    """
    Active system alerts and notifications
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    SEVERITY_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='info')
    
    CATEGORY_CHOICES = [
        ('security', 'Security'),
        ('performance', 'Performance'),
        ('compliance', 'HIPAA Compliance'),
        ('ai', 'AI Processing'),
        ('database', 'Database'),
        ('storage', 'Storage'),
        ('celery', 'Background Tasks'),
    ]
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    
    title = models.CharField(max_length=200)
    message = models.TextField()
    details = models.JSONField(null=True, blank=True)
    
    # Lifecycle
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='acknowledged_alerts'
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='resolved_alerts'
    )
    
    is_active = models.BooleanField(default=True, db_index=True)
    
    class Meta:
        db_table = 'system_alerts'
        ordering = ['-severity', '-created_at']
        indexes = [
            models.Index(fields=['is_active', '-created_at']),
            models.Index(fields=['severity', 'category']),
        ]
    
    def __str__(self):
        return f"[{self.severity.upper()}] {self.title}"
    
    def acknowledge(self, user):
        """Acknowledge an alert"""
        self.acknowledged_at = timezone.now()
        self.acknowledged_by = user
        self.save()
    
    def resolve(self, user):
        """Resolve an alert"""
        self.resolved_at = timezone.now()
        self.resolved_by = user
        self.is_active = False
        self.save()