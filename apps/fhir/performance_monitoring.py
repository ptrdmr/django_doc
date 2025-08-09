"""
FHIR Performance Monitoring and Optimization Module

This module provides comprehensive performance monitoring and optimization
capabilities for FHIR merge operations, including caching, metrics collection,
batch optimization, and alerting.
"""

import time
import logging
import functools
from typing import Dict, List, Any, Optional, Callable, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict, OrderedDict
from threading import Lock
import hashlib
import json
import os

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.db import connection
from django.db.models import Avg, Count, Q, Sum

from apps.core.models import APIUsageLog


logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Container for performance metrics during FHIR operations."""
    
    operation_start: float = field(default_factory=time.time)
    operation_end: Optional[float] = None
    processing_time: Optional[float] = None
    
    # Resource metrics
    total_resources_processed: int = 0
    resources_added: int = 0
    resources_updated: int = 0
    resources_skipped: int = 0
    conflicts_detected: int = 0
    conflicts_resolved: int = 0
    
    # Memory metrics
    peak_memory_mb: float = 0.0
    memory_growth_mb: float = 0.0
    
    # Cache metrics
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_ratio: float = 0.0
    
    # Database metrics
    db_queries: int = 0
    db_query_time: float = 0.0
    
    # Error metrics
    validation_errors: int = 0
    merge_errors: int = 0
    warning_count: int = 0
    
    def finalize(self):
        """Finalize metrics calculation."""
        if self.operation_end is None:
            self.operation_end = time.time()
        
        self.processing_time = self.operation_end - self.operation_start
        
        if self.cache_hits + self.cache_misses > 0:
            self.cache_hit_ratio = self.cache_hits / (self.cache_hits + self.cache_misses)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary format."""
        self.finalize()
        return {
            'processing_time': self.processing_time,
            'total_resources_processed': self.total_resources_processed,
            'resources_added': self.resources_added,
            'resources_updated': self.resources_updated,
            'resources_skipped': self.resources_skipped,
            'conflicts_detected': self.conflicts_detected,
            'conflicts_resolved': self.conflicts_resolved,
            'peak_memory_mb': self.peak_memory_mb,
            'memory_growth_mb': self.memory_growth_mb,
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'cache_hit_ratio': self.cache_hit_ratio,
            'db_queries': self.db_queries,
            'db_query_time': self.db_query_time,
            'validation_errors': self.validation_errors,
            'merge_errors': self.merge_errors,
            'warning_count': self.warning_count,
        }


class FHIRResourceCache:
    """Intelligent caching system for FHIR resources and reference lookups."""
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache_prefix = "fhir_resource_cache"
        self._lock = Lock()
        self._memory_cache = OrderedDict()
        self._memory_cache_timestamps = {}
    
    def _generate_cache_key(self, resource_type: str, resource_id: str, version: str = None) -> str:
        """Generate a consistent cache key for resources."""
        key_parts = [self.cache_prefix, resource_type, resource_id]
        if version:
            key_parts.append(version)
        return ":".join(key_parts)
    
    def _generate_reference_key(self, reference: str) -> str:
        """Generate cache key for reference lookups."""
        return f"{self.cache_prefix}:ref:{hashlib.md5(reference.encode()).hexdigest()}"
    
    def get_resource(self, resource_type: str, resource_id: str, version: str = None) -> Optional[Dict]:
        """Get a cached FHIR resource."""
        cache_key = self._generate_cache_key(resource_type, resource_id, version)
        
        # Try Django cache first
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
        
        # Try memory cache
        with self._lock:
            if cache_key in self._memory_cache:
                timestamp = self._memory_cache_timestamps.get(cache_key, 0)
                if time.time() - timestamp < self.ttl_seconds:
                    # Move to end (LRU)
                    value = self._memory_cache.pop(cache_key)
                    self._memory_cache[cache_key] = value
                    return value
                else:
                    # Expired
                    del self._memory_cache[cache_key]
                    del self._memory_cache_timestamps[cache_key]
        
        return None
    
    def set_resource(self, resource_type: str, resource_id: str, resource_data: Dict, version: str = None):
        """Cache a FHIR resource."""
        cache_key = self._generate_cache_key(resource_type, resource_id, version)
        
        # Store in Django cache
        cache.set(cache_key, resource_data, self.ttl_seconds)
        
        # Store in memory cache (for faster access)
        with self._lock:
            # Remove oldest items if cache is full
            while len(self._memory_cache) >= self.max_size:
                oldest_key = next(iter(self._memory_cache))
                del self._memory_cache[oldest_key]
                del self._memory_cache_timestamps[oldest_key]
            
            self._memory_cache[cache_key] = resource_data
            self._memory_cache_timestamps[cache_key] = time.time()
    
    def get_reference_target(self, reference: str) -> Optional[Dict]:
        """Get cached reference target."""
        cache_key = self._generate_reference_key(reference)
        return cache.get(cache_key)
    
    def set_reference_target(self, reference: str, target_data: Dict):
        """Cache reference target."""
        cache_key = self._generate_reference_key(reference)
        cache.set(cache_key, target_data, self.ttl_seconds)
    
    def invalidate_resource(self, resource_type: str, resource_id: str):
        """Invalidate cached resource."""
        cache_key = self._generate_cache_key(resource_type, resource_id)
        cache.delete(cache_key)
        
        with self._lock:
            if cache_key in self._memory_cache:
                del self._memory_cache[cache_key]
                del self._memory_cache_timestamps[cache_key]
    
    def clear_all(self):
        """Clear all cached resources."""
        with self._lock:
            self._memory_cache.clear()
            self._memory_cache_timestamps.clear()
        
        # Clear Django cache (pattern-based)
        cache.delete_many([
            key for key in cache._cache.keys() 
            if key.startswith(self.cache_prefix)
        ])


class PerformanceMonitor:
    """Central performance monitoring system for FHIR operations."""
    
    def __init__(self):
        self.metrics_history = []
        self._lock = Lock()
        self.resource_cache = FHIRResourceCache()
        self.performance_thresholds = {
            'max_processing_time': getattr(settings, 'FHIR_MAX_PROCESSING_TIME', 30.0),
            'max_memory_growth_mb': getattr(settings, 'FHIR_MAX_MEMORY_GROWTH', 100.0),
            'min_cache_hit_ratio': getattr(settings, 'FHIR_MIN_CACHE_HIT_RATIO', 0.7),
            'max_db_queries_per_resource': getattr(settings, 'FHIR_MAX_DB_QUERIES_PER_RESOURCE', 5),
            'max_error_rate': getattr(settings, 'FHIR_MAX_ERROR_RATE', 0.05),
        }
    
    def start_monitoring(self, operation_id: str = None) -> PerformanceMetrics:
        """Start monitoring a FHIR operation."""
        metrics = PerformanceMetrics()
        if operation_id:
            metrics.operation_id = operation_id
        
        # Record initial memory state
        try:
            import psutil
            process = psutil.Process(os.getpid())
            metrics.initial_memory_mb = process.memory_info().rss / 1024 / 1024
        except ImportError:
            logger.warning("psutil not available for memory monitoring")
            metrics.initial_memory_mb = 0.0
        
        return metrics
    
    def record_metrics(self, metrics: PerformanceMetrics):
        """Record completed metrics for analysis."""
        metrics.finalize()
        
        with self._lock:
            self.metrics_history.append(metrics)
            
            # Keep only recent metrics (last 1000 operations)
            if len(self.metrics_history) > 1000:
                self.metrics_history = self.metrics_history[-1000:]
        
        # Check for performance issues
        self._check_performance_alerts(metrics)
        
        # Log performance summary
        logger.info(
            f"FHIR Operation completed - "
            f"Time: {metrics.processing_time:.2f}s, "
            f"Resources: {metrics.total_resources_processed}, "
            f"Cache Hit Ratio: {metrics.cache_hit_ratio:.2%}, "
            f"DB Queries: {metrics.db_queries}"
        )
    
    def _check_performance_alerts(self, metrics: PerformanceMetrics):
        """Check for performance issues and send alerts."""
        alerts = []
        
        if metrics.processing_time > self.performance_thresholds['max_processing_time']:
            alerts.append(f"Slow processing time: {metrics.processing_time:.2f}s")
        
        if metrics.memory_growth_mb > self.performance_thresholds['max_memory_growth_mb']:
            alerts.append(f"High memory growth: {metrics.memory_growth_mb:.1f}MB")
        
        if metrics.cache_hit_ratio < self.performance_thresholds['min_cache_hit_ratio']:
            alerts.append(f"Low cache hit ratio: {metrics.cache_hit_ratio:.2%}")
        
        if (metrics.total_resources_processed > 0 and 
            metrics.db_queries / metrics.total_resources_processed > 
            self.performance_thresholds['max_db_queries_per_resource']):
            queries_per_resource = metrics.db_queries / metrics.total_resources_processed
            alerts.append(f"High DB queries per resource: {queries_per_resource:.1f}")
        
        total_errors = metrics.validation_errors + metrics.merge_errors
        if (metrics.total_resources_processed > 0 and 
            total_errors / metrics.total_resources_processed > 
            self.performance_thresholds['max_error_rate']):
            error_rate = total_errors / metrics.total_resources_processed
            alerts.append(f"High error rate: {error_rate:.2%}")
        
        if alerts:
            logger.warning(f"Performance alerts: {'; '.join(alerts)}")
            # Here you could integrate with external alerting systems
            self._send_alerts(alerts, metrics)
    
    def _send_alerts(self, alerts: List[str], metrics: PerformanceMetrics):
        """Send performance alerts (placeholder for external integration)."""
        # This would integrate with your alerting system (Slack, email, etc.)
        logger.warning(f"FHIR Performance Alert: {alerts}")
    
    def get_performance_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get performance summary for the specified time period."""
        cutoff_time = time.time() - (hours * 3600)
        
        with self._lock:
            recent_metrics = [
                m for m in self.metrics_history 
                if m.operation_start >= cutoff_time
            ]
        
        if not recent_metrics:
            return {"message": "No recent metrics available"}
        
        total_operations = len(recent_metrics)
        
        # Calculate aggregated metrics
        summary = {
            'time_period_hours': hours,
            'total_operations': total_operations,
            'avg_processing_time': sum(m.processing_time or 0 for m in recent_metrics) / total_operations,
            'max_processing_time': max(m.processing_time or 0 for m in recent_metrics),
            'total_resources_processed': sum(m.total_resources_processed for m in recent_metrics),
            'avg_cache_hit_ratio': sum(m.cache_hit_ratio for m in recent_metrics) / total_operations,
            'total_db_queries': sum(m.db_queries for m in recent_metrics),
            'total_conflicts': sum(m.conflicts_detected for m in recent_metrics),
            'total_errors': sum(m.validation_errors + m.merge_errors for m in recent_metrics),
        }
        
        if summary['total_resources_processed'] > 0:
            summary['avg_db_queries_per_resource'] = (
                summary['total_db_queries'] / summary['total_resources_processed']
            )
            summary['error_rate'] = (
                summary['total_errors'] / summary['total_resources_processed']
            )
        
        return summary


class BatchSizeOptimizer:
    """Optimize batch sizes based on resource complexity and system performance."""
    
    def __init__(self):
        self.complexity_weights = {
            'Patient': 1.0,
            'Observation': 0.5,
            'Condition': 0.7,
            'MedicationStatement': 0.8,
            'DiagnosticReport': 1.2,
            'Procedure': 0.9,
            'AllergyIntolerance': 0.6,
            'CarePlan': 1.5,
            'Practitioner': 0.4,
            'Organization': 0.3,
            'Provenance': 0.2,
        }
        
        self.base_batch_size = getattr(settings, 'FHIR_BASE_BATCH_SIZE', 50)
        self.max_batch_size = getattr(settings, 'FHIR_MAX_BATCH_SIZE', 200)
        self.min_batch_size = getattr(settings, 'FHIR_MIN_BATCH_SIZE', 10)
    
    def calculate_resource_complexity(self, resources: List[Dict]) -> float:
        """Calculate the complexity score for a set of resources."""
        total_complexity = 0.0
        
        for resource in resources:
            resource_type = resource.get('resourceType', 'Unknown')
            weight = self.complexity_weights.get(resource_type, 1.0)
            
            # Adjust for resource size (field count)
            field_count = len(str(resource))  # Simple approximation
            size_factor = min(field_count / 1000, 2.0)  # Cap at 2x
            
            total_complexity += weight * (1 + size_factor)
        
        return total_complexity
    
    def optimize_batch_size(self, resources: List[Dict], 
                          recent_performance: Optional[PerformanceMetrics] = None) -> int:
        """Calculate optimal batch size based on resource complexity and performance."""
        
        if not resources:
            return self.base_batch_size
        
        # Calculate complexity
        avg_complexity = self.calculate_resource_complexity(resources) / len(resources)
        
        # Adjust base batch size based on complexity
        complexity_factor = 2.0 / (1 + avg_complexity)  # Higher complexity = smaller batches
        adjusted_batch_size = int(self.base_batch_size * complexity_factor)
        
        # Adjust based on recent performance
        if recent_performance:
            performance_factor = 1.0
            
            # If processing was slow, reduce batch size
            if recent_performance.processing_time and recent_performance.processing_time > 10.0:
                performance_factor *= 0.8
            
            # If cache hit ratio was low, reduce batch size
            if recent_performance.cache_hit_ratio < 0.5:
                performance_factor *= 0.9
            
            # If memory usage was high, reduce batch size
            if recent_performance.memory_growth_mb > 50.0:
                performance_factor *= 0.7
            
            adjusted_batch_size = int(adjusted_batch_size * performance_factor)
        
        # Ensure within bounds
        return max(self.min_batch_size, min(adjusted_batch_size, self.max_batch_size))
    
    def chunk_resources(self, resources: List[Dict], 
                       recent_performance: Optional[PerformanceMetrics] = None) -> List[List[Dict]]:
        """Split resources into optimally-sized chunks."""
        if not resources:
            return []
        
        optimal_size = self.optimize_batch_size(resources, recent_performance)
        
        chunks = []
        for i in range(0, len(resources), optimal_size):
            chunk = resources[i:i + optimal_size]
            chunks.append(chunk)
        
        logger.info(f"Split {len(resources)} resources into {len(chunks)} chunks of size ~{optimal_size}")
        return chunks


def performance_monitor(operation_name: str = None):
    """Decorator for monitoring FHIR operation performance."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            monitor = PerformanceMonitor()
            metrics = monitor.start_monitoring(operation_name or func.__name__)
            
            # Record initial DB query count
            initial_queries = len(connection.queries)
            
            try:
                # Execute the function
                result = func(*args, **kwargs)
                
                # Record success metrics
                if hasattr(result, 'resources_added'):
                    metrics.resources_added = getattr(result, 'resources_added', 0)
                if hasattr(result, 'resources_updated'):
                    metrics.resources_updated = getattr(result, 'resources_updated', 0)
                if hasattr(result, 'conflicts_detected'):
                    metrics.conflicts_detected = getattr(result, 'conflicts_detected', 0)
                
                return result
                
            except Exception as e:
                metrics.merge_errors += 1
                logger.error(f"Error in monitored operation {func.__name__}: {e}")
                raise
                
            finally:
                # Record final metrics
                metrics.db_queries = len(connection.queries) - initial_queries
                
                try:
                    import psutil
                    process = psutil.Process(os.getpid())
                    current_memory = process.memory_info().rss / 1024 / 1024
                    metrics.peak_memory_mb = current_memory
                    if hasattr(metrics, 'initial_memory_mb'):
                        metrics.memory_growth_mb = current_memory - metrics.initial_memory_mb
                except ImportError:
                    pass
                
                monitor.record_metrics(metrics)
        
        return wrapper
    return decorator


# Global performance monitor instance
performance_monitor_instance = PerformanceMonitor()


def get_performance_dashboard_data() -> Dict[str, Any]:
    """Get dashboard data for FHIR performance monitoring."""
    
    # Get recent API usage statistics
    recent_api_usage = APIUsageLog.objects.filter(
        created_at__gte=timezone.now() - timedelta(hours=24)
    ).aggregate(
        total_requests=Count('id'),
        avg_tokens=Avg('tokens_used'),
        total_cost=Sum('cost')
    )
    
    # Get performance summary
    performance_summary = performance_monitor_instance.get_performance_summary(24)
    
    # Combine data
    dashboard_data = {
        'performance_summary': performance_summary,
        'api_usage': recent_api_usage,
        'cache_status': {
            'hit_ratio': performance_summary.get('avg_cache_hit_ratio', 0),
            'total_hits': sum(m.cache_hits for m in performance_monitor_instance.metrics_history[-100:]),
            'total_misses': sum(m.cache_misses for m in performance_monitor_instance.metrics_history[-100:]),
        },
        'system_health': {
            'error_rate': performance_summary.get('error_rate', 0),
            'avg_processing_time': performance_summary.get('avg_processing_time', 0),
            'max_processing_time': performance_summary.get('max_processing_time', 0),
        },
        'resource_stats': {
            'total_processed': performance_summary.get('total_resources_processed', 0),
            'total_conflicts': performance_summary.get('total_conflicts', 0),
            'total_operations': performance_summary.get('total_operations', 0),
        }
    }
    
    return dashboard_data
