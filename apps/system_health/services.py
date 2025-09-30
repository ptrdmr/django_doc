"""
System Health Services - Collect and analyze system metrics
"""
import logging
from datetime import timedelta
from django.utils import timezone
from django.db import connection
from django.db.models import Count, Avg, Sum
from django.contrib.auth import get_user_model

from apps.documents.models import Document, ParsedData, APIUsageLog
from apps.patients.models import Patient
from apps.providers.models import Provider
from apps.core.models import AuditLog
from .models import SystemHealthSnapshot, SystemAlert, MaintenanceTask

logger = logging.getLogger(__name__)
User = get_user_model()


class HealthCheckService:
    """
    Comprehensive system health monitoring
    """
    
    def __init__(self):
        self.now = timezone.now()
        self.last_24h = self.now - timedelta(hours=24)
    
    def create_snapshot(self):
        """
        Create a complete system health snapshot
        """
        try:
            snapshot = SystemHealthSnapshot(
                # Document Processing
                documents_pending=self._get_pending_documents(),
                documents_processing=self._get_processing_documents(),
                documents_failed_24h=self._get_failed_documents_24h(),
                documents_completed_24h=self._get_completed_documents_24h(),
                avg_processing_time_seconds=self._get_avg_processing_time(),
                
                # AI API
                ai_requests_24h=self._get_ai_requests_24h(),
                ai_errors_24h=self._get_ai_errors_24h(),
                ai_cost_24h=self._get_ai_cost_24h(),
                ai_avg_response_time=self._get_ai_avg_response_time(),
                
                # Database
                total_patients=Patient.objects.count(),
                total_providers=Provider.objects.count(),
                total_documents=Document.all_objects.count(),
                **self._get_database_size_metrics(),
                
                # Celery
                celery_active_tasks=self._get_active_celery_tasks(),
                celery_failed_tasks_24h=self._get_failed_celery_tasks_24h(),
                redis_connection_ok=self._check_redis_connection(),
                
                # Security
                failed_login_attempts_24h=self._get_failed_logins_24h(),
                suspicious_audit_events_24h=self._get_suspicious_events_24h(),
                phi_access_events_24h=self._get_phi_access_24h(),
                
                # System Resources
                **self._get_system_resources(),
            )
            
            # Determine overall status
            snapshot.overall_status = self._calculate_overall_status(snapshot)
            snapshot.save()
            
            # Generate alerts if needed
            self._generate_alerts(snapshot)
            
            logger.info(f"Health snapshot created: {snapshot.overall_status}")
            return snapshot
            
        except Exception as e:
            logger.error(f"Error creating health snapshot: {e}")
            return None
    
    def _get_pending_documents(self):
        """Count documents waiting for processing"""
        return Document.objects.filter(status='pending').count()
    
    def _get_processing_documents(self):
        """Count documents currently being processed"""
        return Document.objects.filter(status='processing').count()
    
    def _get_failed_documents_24h(self):
        """Count failed documents in last 24h"""
        return Document.objects.filter(
            status='failed',
            created_at__gte=self.last_24h
        ).count()
    
    def _get_completed_documents_24h(self):
        """Count completed documents in last 24h"""
        return Document.objects.filter(
            status='completed',
            processed_at__gte=self.last_24h
        ).count()
    
    def _get_avg_processing_time(self):
        """Calculate average processing time for completed documents"""
        try:
            recent_docs = Document.objects.filter(
                status='completed',
                processed_at__gte=self.last_24h,
                processed_at__isnull=False,
                created_at__isnull=False
            )
            
            if not recent_docs.exists():
                return None
            
            total_seconds = 0
            count = 0
            for doc in recent_docs:
                delta = doc.processed_at - doc.created_at
                total_seconds += delta.total_seconds()
                count += 1
            
            return total_seconds / count if count > 0 else None
        except Exception as e:
            logger.error(f"Error calculating avg processing time: {e}")
            return None
    
    def _get_ai_requests_24h(self):
        """Count AI API requests in last 24h"""
        try:
            return APIUsageLog.objects.filter(
                timestamp__gte=self.last_24h
            ).count()
        except Exception:
            return 0
    
    def _get_ai_errors_24h(self):
        """Count AI errors in last 24h"""
        try:
            return APIUsageLog.objects.filter(
                timestamp__gte=self.last_24h,
                error_message__isnull=False
            ).count()
        except Exception:
            return 0
    
    def _get_ai_cost_24h(self):
        """Calculate AI costs in last 24h"""
        try:
            result = APIUsageLog.objects.filter(
                timestamp__gte=self.last_24h
            ).aggregate(total_cost=Sum('cost'))
            return result['total_cost'] or 0
        except Exception:
            return 0
    
    def _get_ai_avg_response_time(self):
        """Average AI response time"""
        try:
            result = APIUsageLog.objects.filter(
                timestamp__gte=self.last_24h,
                processing_time__isnull=False
            ).aggregate(avg_time=Avg('processing_time'))
            return result['avg_time']
        except Exception:
            return None
    
    def _get_database_size_metrics(self):
        """Get database size information"""
        try:
            with connection.cursor() as cursor:
                # Total database size
                cursor.execute("""
                    SELECT pg_database_size(current_database()) / 1024.0 / 1024.0 as size_mb
                """)
                db_size = cursor.fetchone()[0]
                
                # Largest table
                cursor.execute("""
                    SELECT 
                        schemaname || '.' || tablename as table_name,
                        pg_total_relation_size(schemaname||'.'||tablename) / 1024.0 / 1024.0 as size_mb
                    FROM pg_tables
                    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                    ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
                    LIMIT 1
                """)
                largest = cursor.fetchone()
                
                return {
                    'db_size_mb': round(db_size, 2),
                    'largest_table_name': largest[0] if largest else '',
                    'largest_table_mb': round(largest[1], 2) if largest else None,
                }
        except Exception as e:
            logger.error(f"Error getting database metrics: {e}")
            return {
                'db_size_mb': None,
                'largest_table_name': '',
                'largest_table_mb': None,
            }
    
    def _get_active_celery_tasks(self):
        """Count active Celery tasks"""
        try:
            # Check for processing documents as proxy for active tasks
            return Document.objects.filter(status='processing').count()
        except Exception:
            return 0
    
    def _get_failed_celery_tasks_24h(self):
        """Count failed Celery tasks"""
        return self._get_failed_documents_24h()
    
    def _check_redis_connection(self):
        """Check if Redis is accessible"""
        try:
            from django.core.cache import cache
            cache.set('health_check', 'ok', 10)
            return cache.get('health_check') == 'ok'
        except Exception:
            return False
    
    def _get_failed_logins_24h(self):
        """Count failed login attempts"""
        try:
            return AuditLog.objects.filter(
                event_type='login_failed',
                timestamp__gte=self.last_24h
            ).count()
        except Exception:
            return 0
    
    def _get_suspicious_events_24h(self):
        """Count suspicious security events"""
        try:
            suspicious_types = [
                'unauthorized_access_attempt',
                'permission_denied',
                'invalid_token',
            ]
            return AuditLog.objects.filter(
                event_type__in=suspicious_types,
                timestamp__gte=self.last_24h
            ).count()
        except Exception:
            return 0
    
    def _get_phi_access_24h(self):
        """Count PHI access events"""
        try:
            return AuditLog.objects.filter(
                event_type__in=['patient_viewed', 'patient_fhir_exported'],
                timestamp__gte=self.last_24h
            ).count()
        except Exception:
            return 0
    
    def _get_system_resources(self):
        """Get system resource usage"""
        try:
            import psutil
            disk = psutil.disk_usage('/')
            memory = psutil.virtual_memory()
            
            return {
                'disk_usage_percent': round(disk.percent, 2),
                'memory_usage_percent': round(memory.percent, 2),
            }
        except ImportError:
            # psutil not available
            return {
                'disk_usage_percent': None,
                'memory_usage_percent': None,
            }
        except Exception as e:
            logger.error(f"Error getting system resources: {e}")
            return {
                'disk_usage_percent': None,
                'memory_usage_percent': None,
            }
    
    def _calculate_overall_status(self, snapshot):
        """
        Determine overall system health status
        """
        critical_conditions = [
            snapshot.redis_connection_ok is False,
            snapshot.documents_failed_24h > 10,
            snapshot.disk_usage_percent and snapshot.disk_usage_percent > 90,
            snapshot.memory_usage_percent and snapshot.memory_usage_percent > 90,
        ]
        
        if any(critical_conditions):
            return 'critical'
        
        warning_conditions = [
            snapshot.documents_failed_24h > 5,
            snapshot.ai_errors_24h > 10,
            snapshot.disk_usage_percent and snapshot.disk_usage_percent > 80,
            snapshot.memory_usage_percent and snapshot.memory_usage_percent > 80,
            snapshot.celery_active_tasks > 20,
        ]
        
        if any(warning_conditions):
            return 'warning'
        
        return 'healthy'
    
    def _generate_alerts(self, snapshot):
        """
        Generate system alerts based on snapshot
        """
        # Redis connection failure
        if not snapshot.redis_connection_ok:
            self._create_alert(
                severity='critical',
                category='celery',
                title='Redis Connection Failed',
                message='Unable to connect to Redis. Background task processing is unavailable.',
            )
        
        # High document failure rate
        if snapshot.documents_failed_24h > 10:
            self._create_alert(
                severity='critical' if snapshot.documents_failed_24h > 20 else 'warning',
                category='ai',
                title='High Document Failure Rate',
                message=f'{snapshot.documents_failed_24h} documents failed processing in the last 24 hours.',
                details={'failed_count': snapshot.documents_failed_24h}
            )
        
        # Disk space warning
        if snapshot.disk_usage_percent and snapshot.disk_usage_percent > 80:
            self._create_alert(
                severity='critical' if snapshot.disk_usage_percent > 90 else 'warning',
                category='storage',
                title='Low Disk Space',
                message=f'Disk usage at {snapshot.disk_usage_percent}%. Consider archiving old data.',
                details={'disk_usage': snapshot.disk_usage_percent}
            )
        
        # High AI costs
        if snapshot.ai_cost_24h > 50:  # $50/day threshold
            self._create_alert(
                severity='warning',
                category='ai',
                title='High AI API Costs',
                message=f'AI costs at ${snapshot.ai_cost_24h} in last 24 hours.',
                details={'cost_24h': float(snapshot.ai_cost_24h)}
            )
        
        # Suspicious security events
        if snapshot.suspicious_audit_events_24h > 5:
            self._create_alert(
                severity='error',
                category='security',
                title='Suspicious Security Events',
                message=f'{snapshot.suspicious_audit_events_24h} suspicious events detected.',
                details={'event_count': snapshot.suspicious_audit_events_24h}
            )
    
    def _create_alert(self, severity, category, title, message, details=None):
        """
        Create a system alert if it doesn't already exist
        """
        # Check if similar active alert exists
        existing = SystemAlert.objects.filter(
            title=title,
            is_active=True,
            created_at__gte=timezone.now() - timedelta(hours=1)
        ).first()
        
        if not existing:
            SystemAlert.objects.create(
                severity=severity,
                category=category,
                title=title,
                message=message,
                details=details,
            )
            logger.warning(f"Alert created: [{severity}] {title}")


class MaintenanceScheduler:
    """
    Schedule and track maintenance tasks
    """
    
    @staticmethod
    def create_weekly_backup_task():
        """Create weekly backup task"""
        next_week = timezone.now() + timedelta(days=7)
        return MaintenanceTask.objects.create(
            task_type='backup',
            title='Weekly Database Backup',
            description='Full PostgreSQL backup with encrypted PHI',
            priority='high',
            scheduled_for=next_week,
            due_date=next_week + timedelta(hours=6),
        )
    
    @staticmethod
    def create_monthly_audit_task():
        """Create monthly HIPAA audit task"""
        next_month = timezone.now() + timedelta(days=30)
        return MaintenanceTask.objects.create(
            task_type='audit',
            title='Monthly HIPAA Compliance Audit',
            description='Review audit logs, access patterns, and PHI protection measures',
            priority='critical',
            scheduled_for=next_month,
            due_date=next_month + timedelta(days=3),
        )
    
    @staticmethod
    def get_overdue_tasks():
        """Get all overdue maintenance tasks"""
        now = timezone.now()
        return MaintenanceTask.objects.filter(
            status__in=['pending', 'in_progress'],
            due_date__lt=now
        )
    
    @staticmethod
    def get_upcoming_tasks(days=7):
        """Get tasks scheduled within the next N days"""
        future = timezone.now() + timedelta(days=days)
        return MaintenanceTask.objects.filter(
            status='pending',
            scheduled_for__lte=future,
            scheduled_for__gte=timezone.now()
        )