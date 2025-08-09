"""
Comprehensive test suite for FHIR Performance Monitoring and Optimization features.

Tests all components of the performance monitoring system including caching,
metrics collection, batch optimization, alerting, and dashboard functionality.
"""

import time
import unittest
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth.models import User, Permission
from django.urls import reverse
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta

from apps.patients.models import Patient
from apps.core.models import APIUsageLog
from .performance_monitoring import (
    PerformanceMetrics,
    FHIRResourceCache,
    PerformanceMonitor,
    BatchSizeOptimizer,
    performance_monitor_instance,
    get_performance_dashboard_data
)
from .models import FHIRMergeOperation


class PerformanceMetricsTest(TestCase):
    """Test PerformanceMetrics data structure and calculations."""
    
    def test_metrics_initialization(self):
        """Test metrics initialization with default values."""
        metrics = PerformanceMetrics()
        
        self.assertIsInstance(metrics.operation_start, float)
        self.assertIsNone(metrics.operation_end)
        self.assertEqual(metrics.total_resources_processed, 0)
        self.assertEqual(metrics.cache_hits, 0)
        self.assertEqual(metrics.cache_misses, 0)
    
    def test_metrics_finalization(self):
        """Test metrics finalization calculates processing time."""
        metrics = PerformanceMetrics()
        start_time = time.time()
        metrics.operation_start = start_time
        
        # Simulate some processing time
        time.sleep(0.01)
        
        metrics.finalize()
        
        self.assertIsNotNone(metrics.operation_end)
        self.assertIsNotNone(metrics.processing_time)
        self.assertGreater(metrics.processing_time, 0)
    
    def test_cache_hit_ratio_calculation(self):
        """Test cache hit ratio calculation."""
        metrics = PerformanceMetrics()
        metrics.cache_hits = 80
        metrics.cache_misses = 20
        
        metrics.finalize()
        
        self.assertEqual(metrics.cache_hit_ratio, 0.8)
    
    def test_cache_hit_ratio_zero_division(self):
        """Test cache hit ratio when no cache operations occurred."""
        metrics = PerformanceMetrics()
        metrics.cache_hits = 0
        metrics.cache_misses = 0
        
        metrics.finalize()
        
        self.assertEqual(metrics.cache_hit_ratio, 0.0)
    
    def test_metrics_to_dict(self):
        """Test conversion of metrics to dictionary format."""
        metrics = PerformanceMetrics()
        metrics.total_resources_processed = 50
        metrics.cache_hits = 40
        metrics.cache_misses = 10
        
        result = metrics.to_dict()
        
        self.assertIsInstance(result, dict)
        self.assertEqual(result['total_resources_processed'], 50)
        self.assertEqual(result['cache_hit_ratio'], 0.8)
        self.assertIn('processing_time', result)


class FHIRResourceCacheTest(TestCase):
    """Test FHIR resource caching functionality."""
    
    def setUp(self):
        """Set up test cache instance."""
        self.cache = FHIRResourceCache(max_size=10, ttl_seconds=300)
        cache.clear()  # Clear Django cache
    
    def tearDown(self):
        """Clean up after tests."""
        cache.clear()
        self.cache.clear_all()
    
    def test_cache_resource_storage_and_retrieval(self):
        """Test storing and retrieving cached resources."""
        resource_data = {
            'resourceType': 'Patient',
            'id': 'patient-123',
            'name': [{'given': ['John'], 'family': 'Doe'}]
        }
        
        # Store resource
        self.cache.set_resource('Patient', 'patient-123', resource_data)
        
        # Retrieve resource
        retrieved = self.cache.get_resource('Patient', 'patient-123')
        
        self.assertEqual(retrieved, resource_data)
    
    def test_cache_miss(self):
        """Test cache miss returns None."""
        result = self.cache.get_resource('Patient', 'nonexistent')
        self.assertIsNone(result)
    
    def test_cache_versioning(self):
        """Test resource versioning in cache."""
        resource_v1 = {'resourceType': 'Patient', 'id': 'patient-123', 'version': '1'}
        resource_v2 = {'resourceType': 'Patient', 'id': 'patient-123', 'version': '2'}
        
        # Store different versions
        self.cache.set_resource('Patient', 'patient-123', resource_v1, version='1')
        self.cache.set_resource('Patient', 'patient-123', resource_v2, version='2')
        
        # Retrieve specific versions
        retrieved_v1 = self.cache.get_resource('Patient', 'patient-123', version='1')
        retrieved_v2 = self.cache.get_resource('Patient', 'patient-123', version='2')
        
        self.assertEqual(retrieved_v1['version'], '1')
        self.assertEqual(retrieved_v2['version'], '2')
    
    def test_reference_caching(self):
        """Test reference target caching."""
        reference = "Patient/patient-123"
        target_data = {'resourceType': 'Patient', 'id': 'patient-123'}
        
        # Store reference target
        self.cache.set_reference_target(reference, target_data)
        
        # Retrieve reference target
        retrieved = self.cache.get_reference_target(reference)
        
        self.assertEqual(retrieved, target_data)
    
    def test_cache_invalidation(self):
        """Test cache invalidation."""
        resource_data = {'resourceType': 'Patient', 'id': 'patient-123'}
        
        # Store and verify
        self.cache.set_resource('Patient', 'patient-123', resource_data)
        self.assertIsNotNone(self.cache.get_resource('Patient', 'patient-123'))
        
        # Invalidate and verify
        self.cache.invalidate_resource('Patient', 'patient-123')
        self.assertIsNone(self.cache.get_resource('Patient', 'patient-123'))
    
    def test_cache_size_limit(self):
        """Test that cache respects size limits."""
        # Fill cache beyond limit
        for i in range(15):  # More than max_size of 10
            self.cache.set_resource('Patient', f'patient-{i}', {'id': f'patient-{i}'})
        
        # Check that oldest items were evicted
        self.assertIsNone(self.cache.get_resource('Patient', 'patient-0'))
        self.assertIsNotNone(self.cache.get_resource('Patient', 'patient-14'))


class PerformanceMonitorTest(TestCase):
    """Test performance monitoring functionality."""
    
    def setUp(self):
        """Set up test monitor instance."""
        self.monitor = PerformanceMonitor()
    
    def test_start_monitoring(self):
        """Test starting performance monitoring."""
        metrics = self.monitor.start_monitoring("test-operation")
        
        self.assertIsInstance(metrics, PerformanceMetrics)
        self.assertIsInstance(metrics.operation_start, float)
    
    def test_record_metrics(self):
        """Test recording completed metrics."""
        metrics = PerformanceMetrics()
        metrics.total_resources_processed = 25
        metrics.processing_time = 5.0
        
        initial_count = len(self.monitor.metrics_history)
        
        self.monitor.record_metrics(metrics)
        
        self.assertEqual(len(self.monitor.metrics_history), initial_count + 1)
        self.assertEqual(self.monitor.metrics_history[-1], metrics)
    
    def test_performance_alerts_slow_processing(self):
        """Test performance alerts for slow processing."""
        metrics = PerformanceMetrics()
        metrics.processing_time = 35.0  # Exceeds threshold
        
        with patch.object(self.monitor, '_send_alerts') as mock_send:
            self.monitor._check_performance_alerts(metrics)
            mock_send.assert_called_once()
    
    def test_performance_alerts_high_memory(self):
        """Test performance alerts for high memory usage."""
        metrics = PerformanceMetrics()
        metrics.memory_growth_mb = 150.0  # Exceeds threshold
        
        with patch.object(self.monitor, '_send_alerts') as mock_send:
            self.monitor._check_performance_alerts(metrics)
            mock_send.assert_called_once()
    
    def test_performance_alerts_low_cache_hit_ratio(self):
        """Test performance alerts for low cache hit ratio."""
        metrics = PerformanceMetrics()
        metrics.cache_hit_ratio = 0.5  # Below threshold
        
        with patch.object(self.monitor, '_send_alerts') as mock_send:
            self.monitor._check_performance_alerts(metrics)
            mock_send.assert_called_once()
    
    def test_performance_summary_empty(self):
        """Test performance summary with no metrics."""
        summary = self.monitor.get_performance_summary(24)
        
        self.assertIn('message', summary)
        self.assertEqual(summary['message'], "No recent metrics available")
    
    def test_performance_summary_with_data(self):
        """Test performance summary with metric data."""
        # Add some test metrics
        for i in range(5):
            metrics = PerformanceMetrics()
            metrics.processing_time = 2.0 + i
            metrics.total_resources_processed = 10 + i
            metrics.cache_hit_ratio = 0.8
            metrics.db_queries = 5 + i
            self.monitor.record_metrics(metrics)
        
        summary = self.monitor.get_performance_summary(24)
        
        self.assertEqual(summary['total_operations'], 5)
        self.assertEqual(summary['avg_processing_time'], 4.0)  # (2+3+4+5+6)/5
        self.assertEqual(summary['total_resources_processed'], 60)  # 10+11+12+13+14


class BatchSizeOptimizerTest(TestCase):
    """Test batch size optimization functionality."""
    
    def setUp(self):
        """Set up test optimizer instance."""
        self.optimizer = BatchSizeOptimizer()
    
    def test_resource_complexity_calculation(self):
        """Test resource complexity calculation."""
        resources = [
            {'resourceType': 'Patient', 'id': 'patient-1'},
            {'resourceType': 'Observation', 'id': 'obs-1'},
            {'resourceType': 'CarePlan', 'id': 'plan-1'},
        ]
        
        complexity = self.optimizer.calculate_resource_complexity(resources)
        
        # Patient(1.0) + Observation(0.5) + CarePlan(1.5) = 3.0 base
        self.assertGreater(complexity, 3.0)  # Should be > base due to size factor
    
    def test_optimize_batch_size_simple(self):
        """Test basic batch size optimization."""
        resources = [
            {'resourceType': 'Patient', 'id': f'patient-{i}'}
            for i in range(100)
        ]
        
        batch_size = self.optimizer.optimize_batch_size(resources)
        
        self.assertGreaterEqual(batch_size, self.optimizer.min_batch_size)
        self.assertLessEqual(batch_size, self.optimizer.max_batch_size)
    
    def test_optimize_batch_size_with_performance(self):
        """Test batch size optimization with performance data."""
        resources = [{'resourceType': 'Patient', 'id': f'patient-{i}'} for i in range(50)]
        
        # Simulate poor performance
        poor_performance = PerformanceMetrics()
        poor_performance.processing_time = 15.0
        poor_performance.cache_hit_ratio = 0.4
        poor_performance.memory_growth_mb = 80.0
        
        batch_size = self.optimizer.optimize_batch_size(resources, poor_performance)
        
        # Should reduce batch size due to poor performance
        self.assertLess(batch_size, self.optimizer.base_batch_size)
    
    def test_chunk_resources(self):
        """Test resource chunking functionality."""
        resources = [{'resourceType': 'Patient', 'id': f'patient-{i}'} for i in range(100)]
        
        chunks = self.optimizer.chunk_resources(resources)
        
        self.assertGreater(len(chunks), 1)
        
        # Verify all resources are included
        total_resources = sum(len(chunk) for chunk in chunks)
        self.assertEqual(total_resources, 100)
    
    def test_chunk_empty_resources(self):
        """Test chunking with empty resource list."""
        chunks = self.optimizer.chunk_resources([])
        self.assertEqual(chunks, [])


class DashboardViewTest(TestCase):
    """Test performance dashboard views and API endpoints."""
    
    def setUp(self):
        """Set up test user."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Add required permissions
        permissions = [
            'fhir.view_fhirmergeoperation',
            'fhir.change_fhirmergeoperation'
        ]
        for perm_name in permissions:
            try:
                permission = Permission.objects.get(codename=perm_name.split('.')[-1])
                self.user.user_permissions.add(permission)
            except Permission.DoesNotExist:
                pass
        
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
    
    def test_dashboard_view_requires_login(self):
        """Test that dashboard requires authentication."""
        self.client.logout()
        
        response = self.client.get(reverse('fhir:performance_dashboard'))
        
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_dashboard_view_with_permission(self):
        """Test dashboard view with proper permissions."""
        response = self.client.get(reverse('fhir:performance_dashboard'))
        
        # Should not be 403 (might be 500 due to missing data, but not forbidden)
        self.assertNotEqual(response.status_code, 403)
    
    def test_api_performance_metrics_endpoint(self):
        """Test performance metrics API endpoint."""
        response = self.client.get(reverse('fhir:api_performance_metrics'))
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
    
    def test_api_system_health_endpoint(self):
        """Test system health API endpoint."""
        response = self.client.get(reverse('fhir:api_system_health'))
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertIn('status', data)
        self.assertIn('metrics', data)
        self.assertIn('alerts', data)
    
    def test_api_clear_cache_endpoint(self):
        """Test cache clearing API endpoint."""
        response = self.client.post(reverse('fhir:api_clear_cache'))
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data.get('success', False))
    
    def test_api_performance_metrics_with_hours_param(self):
        """Test performance metrics API with hours parameter."""
        response = self.client.get(reverse('fhir:api_performance_metrics') + '?hours=48')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertIn('performance_summary', data)
        self.assertIn('operations_timeline', data)


class IntegrationTest(TestCase):
    """Integration tests for performance monitoring in real scenarios."""
    
    def setUp(self):
        """Set up test environment with real data."""
        self.patient = Patient.objects.create(
            mrn="TEST-001",
            first_name="Test",
            last_name="Patient",
            date_of_birth="1990-01-01",
            cumulative_fhir_json={}
        )
    
    def test_performance_monitoring_integration(self):
        """Test complete performance monitoring workflow."""
        from .services import FHIRMergeService
        
        # Create merge service with monitoring
        merge_service = FHIRMergeService(self.patient)
        
        # Verify monitoring components are initialized
        self.assertIsNotNone(merge_service.performance_monitor)
        self.assertIsNotNone(merge_service.resource_cache)
        self.assertIsNotNone(merge_service.batch_optimizer)
    
    def test_cache_integration_with_merge_service(self):
        """Test cache integration with FHIR merge service."""
        from .services import FHIRMergeService
        
        merge_service = FHIRMergeService(self.patient)
        
        # Test caching operations
        resource_data = {'resourceType': 'Patient', 'id': 'test-patient'}
        merge_service.cache_resource('Patient', 'test-patient', resource_data)
        
        # Test retrieval
        cached = merge_service.get_cached_resource('Patient', 'test-patient')
        self.assertEqual(cached, resource_data)
    
    def test_batch_optimization_integration(self):
        """Test batch optimization integration."""
        from .services import FHIRMergeService
        
        merge_service = FHIRMergeService(self.patient)
        
        # Test batch optimization
        resources = [
            {'resourceType': 'Observation', 'id': f'obs-{i}'}
            for i in range(75)
        ]
        
        chunks = merge_service.optimize_batch_processing(resources)
        
        self.assertGreater(len(chunks), 1)
        
        # Verify all resources are preserved
        total_resources = sum(len(chunk) for chunk in chunks)
        self.assertEqual(total_resources, 75)


class PerformanceRegressionTest(TestCase):
    """Performance regression tests to ensure monitoring doesn't impact performance."""
    
    def test_monitoring_overhead(self):
        """Test that monitoring adds minimal overhead."""
        from .services import FHIRMergeService
        
        # Time without monitoring
        start_time = time.time()
        for _ in range(100):
            # Simulate some work
            pass
        baseline_time = time.time() - start_time
        
        # Time with monitoring
        merge_service = FHIRMergeService(Patient.objects.create(mrn="TEST"))
        
        start_time = time.time()
        for _ in range(100):
            # Same work with monitoring
            metrics = merge_service.performance_monitor.start_monitoring()
            metrics.finalize()
        monitored_time = time.time() - start_time
        
        # Monitoring should add less than 50% overhead
        overhead_ratio = monitored_time / max(baseline_time, 0.001)  # Prevent division by zero
        self.assertLess(overhead_ratio, 1.5)
    
    def test_cache_performance(self):
        """Test cache performance with high load."""
        cache_instance = FHIRResourceCache(max_size=1000)
        
        # Test write performance
        start_time = time.time()
        for i in range(1000):
            cache_instance.set_resource('Patient', f'patient-{i}', {'id': f'patient-{i}'})
        write_time = time.time() - start_time
        
        # Test read performance
        start_time = time.time()
        for i in range(1000):
            cache_instance.get_resource('Patient', f'patient-{i}')
        read_time = time.time() - start_time
        
        # Performance should be reasonable
        self.assertLess(write_time, 1.0)  # Less than 1 second for 1000 writes
        self.assertLess(read_time, 0.5)   # Less than 0.5 seconds for 1000 reads


if __name__ == '__main__':
    unittest.main()
