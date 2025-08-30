"""
Tests for HIPAA audit logging system.
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User, Group, Permission
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
import json

from apps.core.models import AuditLog, SecurityEvent, ComplianceReport


class AuditLogModelTests(TestCase):
    """Test cases for AuditLog model functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_audit_log_creation(self):
        """Test basic audit log creation."""
        log = AuditLog.objects.create(
            event_type='patient_view',
            category='data_access',
            severity='info',
            user=self.user,
            username=self.user.username,
            user_email=self.user.email,
            description='Test audit log entry',
            phi_involved=True,
            success=True
        )
        
        self.assertEqual(log.event_type, 'patient_view')
        self.assertEqual(log.category, 'data_access')
        self.assertEqual(log.user, self.user)
        self.assertTrue(log.phi_involved)
        self.assertTrue(log.success)
        self.assertIsNotNone(log.timestamp)
    
    def test_audit_log_helper_method(self):
        """Test the AuditLog.log_event helper method."""
        log = AuditLog.log_event(
            event_type='patient_create',
            user=self.user,
            description='Patient created via API',
            patient_mrn='MRN123456',
            phi_involved=True
        )
        
        self.assertEqual(log.event_type, 'patient_create')
        self.assertEqual(log.category, 'data_modification')  # Auto-mapped
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.patient_mrn, 'MRN123456')
        self.assertTrue(log.phi_involved)
    
    def test_audit_log_string_representation(self):
        """Test string representation of audit log."""
        log = AuditLog.objects.create(
            event_type='login',
            user=self.user,
            username=self.user.username,
            description='User login'
        )
        
        expected = f"{log.timestamp} - login - {self.user.username}"
        self.assertEqual(str(log), expected)


class AuditLogViewTests(TestCase):
    """Test cases for audit log views."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        
        # Create users
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='adminpass123',
            is_staff=True
        )
        
        self.regular_user = User.objects.create_user(
            username='regular',
            email='regular@example.com',
            password='regularpass123'
        )
        
        # Create audit logs
        self.create_test_audit_logs()
    
    def create_test_audit_logs(self):
        """Create test audit log entries."""
        # Create various types of audit logs
        AuditLog.objects.create(
            event_type='patient_view',
            category='data_access',
            user=self.admin_user,
            username=self.admin_user.username,
            description='Patient record viewed',
            phi_involved=True,
            patient_mrn='MRN001'
        )
        
        AuditLog.objects.create(
            event_type='login_failed',
            category='authentication',
            user=None,
            username='unknown',
            description='Failed login attempt',
            phi_involved=False,
            success=False
        )
    
    def test_audit_trail_view_requires_permission(self):
        """Test that audit trail view requires proper permissions."""
        url = reverse('core:audit_trail')
        
        # Test unauthenticated access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)  # Redirect to login
        
        # Test authenticated user without permission
        self.client.login(username='regular', password='regularpass123')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)  # Permission denied


class HIPAAComplianceTests(TestCase):
    """Test HIPAA compliance requirements."""
    
    def test_audit_log_required_fields(self):
        """Test that audit logs contain all HIPAA-required fields."""
        user = User.objects.create_user(username='testuser', password='testpass123')
        
        log = AuditLog.log_event(
            event_type='patient_view',
            user=user,
            description='Patient record accessed',
            phi_involved=True
        )
        
        # HIPAA requires these fields
        self.assertIsNotNone(log.timestamp)  # Date and time
        self.assertIsNotNone(log.user)       # User identity
        self.assertIsNotNone(log.event_type) # Activity description
        self.assertIsNotNone(log.success)    # Success/failure
        
        # Additional fields for comprehensive tracking
        self.assertIsNotNone(log.username)
        self.assertIsNotNone(log.description)
        self.assertIsNotNone(log.phi_involved)
    
    def test_audit_log_retention_period(self):
        """Test audit log retention period settings."""
        from django.conf import settings
        
        # Check that retention period is set to HIPAA-compliant value
        retention_days = getattr(settings, 'AUDIT_LOG_RETENTION_DAYS', None)
        self.assertIsNotNone(retention_days)
        self.assertGreaterEqual(retention_days, 2190)  # 6 years minimum