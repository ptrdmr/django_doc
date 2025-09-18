"""
Error Monitoring and Alerting System for Document Processing Pipeline

This module provides comprehensive error monitoring, alerting, and recovery strategies
for the medical document processing pipeline, supporting Task 34.5 error handling enhancement.

Features:
- Real-time error tracking and categorization
- Error rate monitoring and threshold alerting
- Performance metrics collection
- Recovery strategy automation
- Admin dashboard integration
- Health check endpoints

Author: Task 34.5 - Enhance error handling and logging
Date: 2025-09-17 15:46:02
"""

import logging
import time
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.db.models import Q
from collections import defaultdict, deque
import threading
import json

from .exceptions import (
    DocumentProcessingError,
    PDFExtractionError,
    AIExtractionError,
    AIServiceTimeoutError,
    AIServiceRateLimitError,
    FHIRConversionError,
    CeleryTaskError,
    categorize_exception,
    get_recovery_strategy
)

logger = logging.getLogger(__name__)


class ErrorMetrics:
    """
    Thread-safe error metrics collector for real-time monitoring.
    """
    
    def __init__(self, max_history: int = 1000):
        """
        Initialize error metrics collector.
        
        Args:
            max_history: Maximum number of error events to keep in memory
        """
        self.max_history = max_history
        self._lock = threading.Lock()
        self._reset_metrics()
    
    def _reset_metrics(self):
        """Reset all metrics (called during initialization and periodic resets)."""
        self.error_counts = defaultdict(int)
        self.error_history = deque(maxlen=self.max_history)
        self.performance_metrics = {
            'total_errors': 0,
            'errors_by_type': defaultdict(int),
            'errors_by_component': defaultdict(int),
            'error_rate_per_minute': 0.0,
            'last_error_time': None,
            'recovery_success_rate': 0.0,
            'critical_error_count': 0
        }
        self.component_health = defaultdict(lambda: {'status': 'healthy', 'last_check': timezone.now()})
    
    def record_error(self, error: Exception, component: str, details: Dict[str, Any] = None) -> None:
        """
        Record an error event with comprehensive metadata.
        
        Args:
            error: The exception that occurred
            component: Component where error occurred (e.g., 'pdf_extraction', 'ai_service')
            details: Additional error details and context
        """
        with self._lock:
            error_event = {
                'timestamp': timezone.now(),
                'error_type': type(error).__name__,
                'error_message': str(error),
                'component': component,
                'severity': self._determine_severity(error),
                'recovery_strategy': self._get_recovery_strategy(error),
                'details': details or {}
            }
            
            # Add error code if available
            if hasattr(error, 'error_code'):
                error_event['error_code'] = error.error_code
            
            # Store error event
            self.error_history.append(error_event)
            
            # Update counters
            self.error_counts[type(error).__name__] += 1
            self.performance_metrics['total_errors'] += 1
            self.performance_metrics['errors_by_type'][type(error).__name__] += 1
            self.performance_metrics['errors_by_component'][component] += 1
            self.performance_metrics['last_error_time'] = timezone.now()
            
            # Track critical errors
            if error_event['severity'] == 'critical':
                self.performance_metrics['critical_error_count'] += 1
            
            # Update component health status
            self._update_component_health(component, error_event['severity'])
            
            logger.info(f"Recorded {error_event['severity']} error: {type(error).__name__} in {component}")
    
    def _determine_severity(self, error: Exception) -> str:
        """Determine error severity level."""
        if isinstance(error, (AIServiceTimeoutError, AIServiceRateLimitError)):
            return 'warning'
        elif isinstance(error, (PDFExtractionError, FHIRConversionError)):
            return 'error'
        elif isinstance(error, (AIExtractionError, CeleryTaskError)):
            return 'error'
        elif isinstance(error, DocumentProcessingError):
            return 'critical'
        else:
            return 'error'
    
    def _get_recovery_strategy(self, error: Exception) -> str:
        """Get appropriate recovery strategy for error."""
        if hasattr(error, 'error_code'):
            return get_recovery_strategy(error.error_code)
        return get_recovery_strategy(type(error).__name__)
    
    def _update_component_health(self, component: str, severity: str) -> None:
        """Update component health status based on error severity."""
        if severity == 'critical':
            self.component_health[component]['status'] = 'critical'
        elif severity == 'error' and self.component_health[component]['status'] == 'healthy':
            self.component_health[component]['status'] = 'degraded'
        
        self.component_health[component]['last_check'] = timezone.now()
    
    def get_error_rate(self, window_minutes: int = 5) -> float:
        """
        Calculate error rate per minute over the specified time window.
        
        Args:
            window_minutes: Time window in minutes
            
        Returns:
            Error rate per minute
        """
        with self._lock:
            cutoff_time = timezone.now() - timedelta(minutes=window_minutes)
            recent_errors = [
                error for error in self.error_history 
                if error['timestamp'] >= cutoff_time
            ]
            
            error_rate = len(recent_errors) / max(window_minutes, 1)
            self.performance_metrics['error_rate_per_minute'] = error_rate
            return error_rate
    
    def get_component_status(self) -> Dict[str, Dict[str, Any]]:
        """Get health status for all components."""
        with self._lock:
            return dict(self.component_health)
    
    def get_error_summary(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get comprehensive error summary for the specified time period.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            Comprehensive error summary
        """
        with self._lock:
            cutoff_time = timezone.now() - timedelta(hours=hours)
            recent_errors = [
                error for error in self.error_history 
                if error['timestamp'] >= cutoff_time
            ]
            
            summary = {
                'time_period_hours': hours,
                'total_errors': len(recent_errors),
                'error_rate_per_hour': len(recent_errors) / max(hours, 1),
                'errors_by_type': defaultdict(int),
                'errors_by_component': defaultdict(int),
                'errors_by_severity': defaultdict(int),
                'recovery_strategies': defaultdict(int),
                'component_health': self.get_component_status(),
                'recent_critical_errors': []
            }
            
            for error in recent_errors:
                summary['errors_by_type'][error['error_type']] += 1
                summary['errors_by_component'][error['component']] += 1
                summary['errors_by_severity'][error['severity']] += 1
                summary['recovery_strategies'][error['recovery_strategy']] += 1
                
                if error['severity'] == 'critical':
                    summary['recent_critical_errors'].append({
                        'timestamp': error['timestamp'].isoformat(),
                        'error_type': error['error_type'],
                        'error_message': error['error_message'],
                        'component': error['component']
                    })
            
            return summary


# Global error metrics instance
error_metrics = ErrorMetrics()


class ErrorMonitor:
    """
    Main error monitoring and alerting coordinator.
    """
    
    def __init__(self):
        """Initialize error monitor with configuration."""
        self.metrics = error_metrics
        self.alert_thresholds = {
            'error_rate_per_minute': getattr(settings, 'ERROR_RATE_THRESHOLD', 5.0),
            'critical_errors_per_hour': getattr(settings, 'CRITICAL_ERROR_THRESHOLD', 3),
            'component_failure_threshold': getattr(settings, 'COMPONENT_FAILURE_THRESHOLD', 10)
        }
        self.logger = logging.getLogger(__name__)
    
    def record_processing_error(self, error: Exception, document_id: int = None, 
                              component: str = 'unknown', **kwargs) -> None:
        """
        Record a processing error with full context.
        
        Args:
            error: The exception that occurred
            document_id: ID of document being processed
            component: Component where error occurred
            **kwargs: Additional context information
        """
        details = {
            'document_id': document_id,
            **kwargs
        }
        
        self.metrics.record_error(error, component, details)
        
        # Check for alert conditions
        self._check_alert_conditions()
        
        # Log to Django logging system
        self.logger.error(
            f"Processing error in {component}: {type(error).__name__}: {str(error)}",
            extra={
                'document_id': document_id,
                'component': component,
                'error_type': type(error).__name__,
                'error_details': details
            }
        )
    
    def _check_alert_conditions(self) -> None:
        """Check if any alert conditions are met and trigger alerts."""
        # Check error rate threshold
        current_error_rate = self.metrics.get_error_rate(window_minutes=5)
        if current_error_rate > self.alert_thresholds['error_rate_per_minute']:
            self._send_alert(
                'high_error_rate',
                f"High error rate detected: {current_error_rate:.2f} errors/minute",
                severity='warning'
            )
        
        # Check critical error threshold
        summary = self.metrics.get_error_summary(hours=1)
        critical_errors = summary['errors_by_severity']['critical']
        if critical_errors > self.alert_thresholds['critical_errors_per_hour']:
            self._send_alert(
                'critical_errors',
                f"High critical error count: {critical_errors} in the last hour",
                severity='critical'
            )
    
    def _send_alert(self, alert_type: str, message: str, severity: str = 'warning') -> None:
        """
        Send alert notification (placeholder for future implementation).
        
        Args:
            alert_type: Type of alert
            message: Alert message
            severity: Alert severity level
        """
        # Cache alert to prevent spam
        cache_key = f"alert_{alert_type}_{severity}"
        if cache.get(cache_key):
            return  # Alert recently sent
        
        # Set cache for 5 minutes to prevent alert spam
        cache.set(cache_key, True, 300)
        
        self.logger.warning(f"ALERT [{severity.upper()}] {alert_type}: {message}")
        
        # TODO: Implement actual alerting (email, Slack, etc.)
        # This could integrate with Django admin notifications, external services, etc.
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get overall system health status.
        
        Returns:
            Comprehensive health status report
        """
        summary = self.metrics.get_error_summary(hours=1)
        current_error_rate = self.metrics.get_error_rate(window_minutes=5)
        
        # Determine overall health
        overall_status = 'healthy'
        if summary['errors_by_severity']['critical'] > 0:
            overall_status = 'critical'
        elif current_error_rate > self.alert_thresholds['error_rate_per_minute']:
            overall_status = 'degraded'
        elif summary['total_errors'] > 0:
            overall_status = 'warning'
        
        return {
            'overall_status': overall_status,
            'current_error_rate': current_error_rate,
            'last_hour_summary': summary,
            'component_health': self.metrics.get_component_status(),
            'alert_thresholds': self.alert_thresholds,
            'timestamp': timezone.now().isoformat()
        }
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """
        Get data for admin dashboard display.
        
        Returns:
            Dashboard-ready error monitoring data
        """
        health_status = self.get_health_status()
        summary_24h = self.metrics.get_error_summary(hours=24)
        
        return {
            'health_status': health_status,
            'error_trends': {
                'last_24_hours': summary_24h,
                'current_error_rate': health_status['current_error_rate']
            },
            'top_error_types': dict(
                sorted(summary_24h['errors_by_type'].items(), 
                      key=lambda x: x[1], reverse=True)[:10]
            ),
            'component_status': health_status['component_health'],
            'recovery_recommendations': self._get_recovery_recommendations()
        }
    
    def _get_recovery_recommendations(self) -> List[Dict[str, str]]:
        """Generate recovery recommendations based on current error patterns."""
        recommendations = []
        summary = self.metrics.get_error_summary(hours=1)
        
        # Check for specific error patterns and provide recommendations
        if summary['errors_by_type'].get('AIServiceRateLimitError', 0) > 2:
            recommendations.append({
                'type': 'rate_limiting',
                'message': 'High rate limit errors detected. Consider implementing exponential backoff.',
                'action': 'Review AI service usage patterns and implement rate limiting.'
            })
        
        if summary['errors_by_type'].get('PDFExtractionError', 0) > 3:
            recommendations.append({
                'type': 'pdf_extraction',
                'message': 'Multiple PDF extraction failures detected.',
                'action': 'Check PDF file formats and consider adding file validation.'
            })
        
        if summary['errors_by_component'].get('ai_service', 0) > 5:
            recommendations.append({
                'type': 'ai_service',
                'message': 'High AI service error rate detected.',
                'action': 'Check API key validity and service status. Consider fallback strategies.'
            })
        
        return recommendations


# Global error monitor instance
error_monitor = ErrorMonitor()


# Convenience functions for easy integration
def record_error(error: Exception, component: str, document_id: int = None, **kwargs) -> None:
    """
    Convenience function to record an error.
    
    Args:
        error: The exception that occurred
        component: Component where error occurred
        document_id: Optional document ID
        **kwargs: Additional context
    """
    error_monitor.record_processing_error(error, document_id, component, **kwargs)


def get_health_status() -> Dict[str, Any]:
    """Get current system health status."""
    return error_monitor.get_health_status()


def get_dashboard_data() -> Dict[str, Any]:
    """Get data for admin dashboard."""
    return error_monitor.get_dashboard_data()


def reset_metrics() -> None:
    """Reset all error metrics (useful for testing or periodic cleanup)."""
    global error_metrics
    error_metrics._reset_metrics()
    logger.info("Error metrics reset")
