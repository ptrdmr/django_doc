"""
Tests for FHIR Transaction Management System

This module contains comprehensive tests for the transaction management system
including staging areas, rollback capabilities, snapshots, and concurrent access control.
"""

import json
import time
import threading
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from uuid import uuid4

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.cache import cache

from apps.patients.models import Patient
from apps.core.models import AuditLog
from .transaction_manager import (
    FHIRTransactionManager,
    TransactionSnapshot,
    StagingArea,
    TransactionResult,
    TransactionLockManager,
    SnapshotManager
)
from .services import FHIRMergeService, FHIRMergeError


class TransactionSnapshotTest(TestCase):
    """Test TransactionSnapshot class functionality."""
    
    def setUp(self):
        self.patient_mrn = "TEST123"
        self.bundle_data = {
            'resourceType': 'Bundle',
            'id': 'patient-bundle',
            'type': 'collection',
            'entry': [
                {
                    'resource': {
                        'resourceType': 'Patient',
                        'id': 'patient-1',
                        'name': [{'family': 'Test', 'given': ['John']}]
                    }
                }
            ]
        }
    
    def test_snapshot_creation(self):
        """Test creating a snapshot."""
        snapshot = TransactionSnapshot(
            snapshot_id="snap_123",
            patient_mrn=self.patient_mrn,
            bundle_data=self.bundle_data,
            created_at=timezone.now(),
            reason="test_snapshot"
        )
        
        self.assertEqual(snapshot.snapshot_id, "snap_123")
        self.assertEqual(snapshot.patient_mrn, self.patient_mrn)
        self.assertEqual(snapshot.bundle_data, self.bundle_data)
        self.assertEqual(snapshot.reason, "test_snapshot")
    
    def test_snapshot_serialization(self):
        """Test snapshot to_dict and from_dict methods."""
        snapshot = TransactionSnapshot(
            snapshot_id="snap_123",
            patient_mrn=self.patient_mrn,
            bundle_data=self.bundle_data,
            created_at=timezone.now(),
            reason="test_snapshot"
        )
        
        # Convert to dict
        snapshot_dict = snapshot.to_dict()
        self.assertIsInstance(snapshot_dict, dict)
        self.assertEqual(snapshot_dict['snapshot_id'], "snap_123")
        
        # Convert back from dict
        restored_snapshot = TransactionSnapshot.from_dict(snapshot_dict)
        self.assertEqual(restored_snapshot.snapshot_id, snapshot.snapshot_id)
        self.assertEqual(restored_snapshot.patient_mrn, snapshot.patient_mrn)
        self.assertEqual(restored_snapshot.bundle_data, snapshot.bundle_data)


class StagingAreaTest(TestCase):
    """Test StagingArea class functionality."""
    
    def setUp(self):
        self.patient_mrn = "TEST123"
        self.original_bundle = {
            'resourceType': 'Bundle',
            'type': 'collection',
            'entry': []
        }
        
        self.staging_area = StagingArea(
            staging_id="stage_123",
            patient_mrn=self.patient_mrn,
            original_bundle=self.original_bundle
        )
    
    def test_staging_area_creation(self):
        """Test creating a staging area."""
        self.assertEqual(self.staging_area.staging_id, "stage_123")
        self.assertEqual(self.staging_area.patient_mrn, self.patient_mrn)
        self.assertEqual(self.staging_area.original_bundle, self.original_bundle)
        self.assertEqual(len(self.staging_area.staged_changes), 0)
    
    def test_add_change(self):
        """Test adding changes to staging area."""
        resource_data = {
            'resourceType': 'Observation',
            'id': 'obs-1',
            'status': 'final'
        }
        
        self.staging_area.add_change('add', resource_data, {'test': 'metadata'})
        
        self.assertEqual(len(self.staging_area.staged_changes), 1)
        change = self.staging_area.staged_changes[0]
        self.assertEqual(change['operation'], 'add')
        self.assertEqual(change['resource_data'], resource_data)
        self.assertEqual(change['metadata']['test'], 'metadata')
        self.assertIn('change_id', change)
        self.assertIn('timestamp', change)
    
    def test_get_changes_summary(self):
        """Test getting summary of staged changes."""
        # Add various types of changes
        self.staging_area.add_change('add', {'resourceType': 'Observation'})
        self.staging_area.add_change('add', {'resourceType': 'Condition'})
        self.staging_area.add_change('update', {'resourceType': 'Patient'})
        self.staging_area.add_change('delete', {'resourceType': 'Medication'})
        
        summary = self.staging_area.get_changes_summary()
        self.assertEqual(summary['add'], 2)
        self.assertEqual(summary['update'], 1)
        self.assertEqual(summary['delete'], 1)
    
    def test_clear_changes(self):
        """Test clearing staged changes."""
        self.staging_area.add_change('add', {'resourceType': 'Observation'})
        self.assertEqual(len(self.staging_area.staged_changes), 1)
        
        self.staging_area.clear_changes()
        self.assertEqual(len(self.staging_area.staged_changes), 0)


class TransactionLockManagerTest(TestCase):
    """Test TransactionLockManager functionality."""
    
    def setUp(self):
        cache.clear()  # Clear cache before each test
        self.lock_manager = TransactionLockManager(lock_timeout_seconds=5)
        self.patient_mrn = "TEST123"
        self.operation_id = "op_123"
    
    def tearDown(self):
        cache.clear()  # Clean up after each test
    
    def test_acquire_lock_success(self):
        """Test successful lock acquisition."""
        result = self.lock_manager.acquire_lock(self.patient_mrn, self.operation_id)
        self.assertTrue(result)
        
        # Verify lock is held
        is_locked, lock_holder = self.lock_manager.is_locked(self.patient_mrn)
        self.assertTrue(is_locked)
        self.assertEqual(lock_holder, self.operation_id)
    
    def test_acquire_lock_already_held(self):
        """Test lock acquisition when already held by another operation."""
        # First operation acquires lock
        result1 = self.lock_manager.acquire_lock(self.patient_mrn, "op_1")
        self.assertTrue(result1)
        
        # Second operation tries to acquire same lock
        result2 = self.lock_manager.acquire_lock(self.patient_mrn, "op_2")
        self.assertFalse(result2)
    
    def test_release_lock_success(self):
        """Test successful lock release."""
        # Acquire lock first
        self.lock_manager.acquire_lock(self.patient_mrn, self.operation_id)
        
        # Release lock
        result = self.lock_manager.release_lock(self.patient_mrn, self.operation_id)
        self.assertTrue(result)
        
        # Verify lock is released
        is_locked, _ = self.lock_manager.is_locked(self.patient_mrn)
        self.assertFalse(is_locked)
    
    def test_release_lock_not_held(self):
        """Test releasing lock that isn't held by the operation."""
        result = self.lock_manager.release_lock(self.patient_mrn, self.operation_id)
        self.assertFalse(result)
    
    def test_lock_context_manager(self):
        """Test lock context manager functionality."""
        with self.lock_manager.lock_patient(self.patient_mrn, self.operation_id):
            # Inside context, lock should be held
            is_locked, lock_holder = self.lock_manager.is_locked(self.patient_mrn)
            self.assertTrue(is_locked)
            self.assertEqual(lock_holder, self.operation_id)
        
        # Outside context, lock should be released
        is_locked, _ = self.lock_manager.is_locked(self.patient_mrn)
        self.assertFalse(is_locked)
    
    def test_lock_context_manager_exception(self):
        """Test lock is released even when exception occurs."""
        try:
            with self.lock_manager.lock_patient(self.patient_mrn, self.operation_id):
                raise ValueError("Test exception")
        except ValueError:
            pass
        
        # Lock should still be released
        is_locked, _ = self.lock_manager.is_locked(self.patient_mrn)
        self.assertFalse(is_locked)
    
    def test_concurrent_lock_acquisition(self):
        """Test concurrent lock acquisition from multiple threads."""
        results = []
        
        def try_acquire_lock(op_id):
            result = self.lock_manager.acquire_lock(self.patient_mrn, f"op_{op_id}")
            results.append(result)
        
        # Start multiple threads trying to acquire the same lock
        threads = []
        for i in range(5):
            thread = threading.Thread(target=try_acquire_lock, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Only one thread should have successfully acquired the lock
        successful_acquisitions = sum(results)
        self.assertEqual(successful_acquisitions, 1)


class SnapshotManagerTest(TestCase):
    """Test SnapshotManager functionality."""
    
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='testuser', email='test@example.com')
        self.patient = Patient.objects.create(
            mrn='TEST123',
            first_name='John',
            last_name='Test',
            date_of_birth='1980-01-01',
            gender='M',
            cumulative_fhir_json={
                'resourceType': 'Bundle',
                'type': 'collection',
                'entry': []
            }
        )
        self.snapshot_manager = SnapshotManager(max_snapshots_per_patient=5)
    
    def tearDown(self):
        cache.clear()
    
    def test_create_snapshot(self):
        """Test creating a snapshot."""
        snapshot = self.snapshot_manager.create_snapshot(
            self.patient,
            reason="test_snapshot",
            created_by=self.user
        )
        
        self.assertIsInstance(snapshot, TransactionSnapshot)
        self.assertEqual(snapshot.patient_mrn, self.patient.mrn)
        self.assertEqual(snapshot.reason, "test_snapshot")
        self.assertEqual(snapshot.created_by, self.user.username)
        self.assertIsNotNone(snapshot.snapshot_id)
    
    def test_get_snapshot(self):
        """Test retrieving a snapshot."""
        # Create snapshot
        original_snapshot = self.snapshot_manager.create_snapshot(self.patient)
        
        # Retrieve snapshot
        retrieved_snapshot = self.snapshot_manager.get_snapshot(
            self.patient.mrn,
            original_snapshot.snapshot_id
        )
        
        self.assertIsNotNone(retrieved_snapshot)
        self.assertEqual(retrieved_snapshot.snapshot_id, original_snapshot.snapshot_id)
        self.assertEqual(retrieved_snapshot.patient_mrn, original_snapshot.patient_mrn)
    
    def test_get_nonexistent_snapshot(self):
        """Test retrieving a snapshot that doesn't exist."""
        snapshot = self.snapshot_manager.get_snapshot(self.patient.mrn, "nonexistent_id")
        self.assertIsNone(snapshot)
    
    def test_list_snapshots(self):
        """Test listing snapshots for a patient."""
        # Create multiple snapshots
        snapshot1 = self.snapshot_manager.create_snapshot(self.patient, reason="snapshot1")
        snapshot2 = self.snapshot_manager.create_snapshot(self.patient, reason="snapshot2")
        
        # List snapshots
        snapshots = self.snapshot_manager.list_snapshots(self.patient.mrn)
        
        self.assertEqual(len(snapshots), 2)
        snapshot_ids = [s['snapshot_id'] for s in snapshots]
        self.assertIn(snapshot1.snapshot_id, snapshot_ids)
        self.assertIn(snapshot2.snapshot_id, snapshot_ids)
    
    def test_max_snapshots_limit(self):
        """Test that old snapshots are removed when limit is exceeded."""
        # Create more snapshots than the limit
        for i in range(7):  # Limit is 5
            self.snapshot_manager.create_snapshot(self.patient, reason=f"snapshot_{i}")
        
        # Should only have 5 snapshots
        snapshots = self.snapshot_manager.list_snapshots(self.patient.mrn)
        self.assertEqual(len(snapshots), 5)
    
    def test_restore_from_snapshot(self):
        """Test restoring patient bundle from snapshot."""
        # Modify patient bundle
        original_bundle = self.patient.cumulative_fhir_json.copy()
        self.patient.cumulative_fhir_json['modified'] = True
        self.patient.save()
        
        # Create snapshot of original state
        snapshot = self.snapshot_manager.create_snapshot(self.patient)
        snapshot.bundle_data = original_bundle  # Simulate snapshot of original state
        
        # Save modified snapshot back to cache
        cache_key = f"fhir_snapshot:{self.patient.mrn}:{snapshot.snapshot_id}"
        cache.set(cache_key, snapshot.to_dict(), timeout=86400)
        
        # Restore from snapshot
        result = self.snapshot_manager.restore_from_snapshot(
            self.patient,
            snapshot.snapshot_id,
            self.user
        )
        
        self.assertTrue(result)
        
        # Refresh patient from database
        self.patient.refresh_from_db()
        self.assertNotIn('modified', self.patient.cumulative_fhir_json)


class FHIRTransactionManagerTest(TestCase):
    """Test FHIRTransactionManager functionality."""
    
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='testuser', email='test@example.com')
        self.patient = Patient.objects.create(
            mrn='TEST123',
            first_name='John',
            last_name='Test',
            date_of_birth='1980-01-01',
            gender='M',
            cumulative_fhir_json={
                'resourceType': 'Bundle',
                'type': 'collection',
                'meta': {'versionId': '1'},
                'entry': []
            }
        )
        self.transaction_manager = FHIRTransactionManager()
    
    def tearDown(self):
        cache.clear()
    
    def test_create_staging_area(self):
        """Test creating a staging area."""
        staging_area = self.transaction_manager.create_staging_area(
            self.patient,
            "test_operation"
        )
        
        self.assertIsInstance(staging_area, StagingArea)
        self.assertEqual(staging_area.patient_mrn, self.patient.mrn)
        self.assertIn("stage_", staging_area.staging_id)
        self.assertEqual(len(staging_area.staged_changes), 0)
    
    def test_get_staging_area(self):
        """Test retrieving a staging area."""
        # Create staging area
        staging_area = self.transaction_manager.create_staging_area(
            self.patient,
            "test_operation"
        )
        
        # Retrieve staging area
        retrieved_area = self.transaction_manager.get_staging_area(staging_area.staging_id)
        
        self.assertIsNotNone(retrieved_area)
        self.assertEqual(retrieved_area.staging_id, staging_area.staging_id)
    
    def test_commit_staging_area_success(self):
        """Test successful commit of staging area."""
        # Create staging area
        staging_area = self.transaction_manager.create_staging_area(
            self.patient,
            "test_operation"
        )
        
        # Add some changes
        staging_area.add_change('add', {
            'resourceType': 'Observation',
            'id': 'obs-1',
            'status': 'final'
        })
        
        # Commit changes
        result = self.transaction_manager.commit_staging_area(
            staging_area.staging_id,
            self.user
        )
        
        self.assertTrue(result.success)
        self.assertEqual(result.changes_applied, 1)
        self.assertIsNotNone(result.snapshot_id)
        
        # Verify staging area is cleaned up
        retrieved_area = self.transaction_manager.get_staging_area(staging_area.staging_id)
        self.assertIsNone(retrieved_area)
    
    def test_rollback_staging_area(self):
        """Test rolling back a staging area."""
        # Create staging area
        staging_area = self.transaction_manager.create_staging_area(
            self.patient,
            "test_operation"
        )
        
        # Add some changes
        staging_area.add_change('add', {
            'resourceType': 'Observation',
            'id': 'obs-1',
            'status': 'final'
        })
        
        # Rollback changes
        result = self.transaction_manager.rollback_staging_area(
            staging_area.staging_id,
            self.user
        )
        
        self.assertTrue(result.success)
        self.assertTrue(result.rollback_performed)
        
        # Verify staging area is cleaned up
        retrieved_area = self.transaction_manager.get_staging_area(staging_area.staging_id)
        self.assertIsNone(retrieved_area)
    
    def test_transaction_context_manager_success(self):
        """Test transaction context manager with successful operation."""
        operation_id = "test_operation"
        
        with self.transaction_manager.transaction_context(
            patient=self.patient,
            operation_id=operation_id,
            user=self.user,
            auto_commit=True
        ) as staging_area:
            staging_area.add_change('add', {
                'resourceType': 'Observation',
                'id': 'obs-1',
                'status': 'final'
            })
        
        # If we reach here, commit was successful
        # Verify staging area is cleaned up
        retrieved_area = self.transaction_manager.get_staging_area(staging_area.staging_id)
        self.assertIsNone(retrieved_area)
    
    def test_transaction_context_manager_rollback_on_exception(self):
        """Test transaction context manager rolls back on exception."""
        operation_id = "test_operation"
        
        try:
            with self.transaction_manager.transaction_context(
                patient=self.patient,
                operation_id=operation_id,
                user=self.user,
                auto_commit=True
            ) as staging_area:
                staging_area.add_change('add', {
                    'resourceType': 'Observation',
                    'id': 'obs-1',
                    'status': 'final'
                })
                raise ValueError("Test exception")
        except ValueError:
            pass
        
        # Verify staging area is cleaned up after rollback
        retrieved_area = self.transaction_manager.get_staging_area(staging_area.staging_id)
        self.assertIsNone(retrieved_area)
    
    def test_cleanup_expired_staging_areas(self):
        """Test cleanup of expired staging areas."""
        # Create staging area with short max lifetime
        short_lifetime_manager = FHIRTransactionManager(max_staging_time_minutes=0.01)  # 0.6 seconds
        
        staging_area = short_lifetime_manager.create_staging_area(
            self.patient,
            "test_operation"
        )
        
        # Wait for staging area to expire
        time.sleep(1)
        
        # Run cleanup
        expired_count = short_lifetime_manager.cleanup_expired_staging_areas()
        
        self.assertEqual(expired_count, 1)
        
        # Verify staging area is removed
        retrieved_area = short_lifetime_manager.get_staging_area(staging_area.staging_id)
        self.assertIsNone(retrieved_area)


class FHIRMergeServiceTransactionTest(TestCase):
    """Test FHIRMergeService transaction functionality."""
    
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='testuser', email='test@example.com')
        self.patient = Patient.objects.create(
            mrn='TEST123',
            first_name='John',
            last_name='Test',
            date_of_birth='1980-01-01',
            gender='M',
            cumulative_fhir_json={
                'resourceType': 'Bundle',
                'type': 'collection',
                'meta': {'versionId': '1'},
                'entry': []
            }
        )
        self.merge_service = FHIRMergeService(self.patient)
    
    def tearDown(self):
        cache.clear()
    
    def test_transactional_merge_disabled(self):
        """Test transactional merge when transactions are disabled."""
        # Disable transactions
        self.merge_service.config['use_transactions'] = False
        
        extracted_data = {
            'document_type': 'lab_report',
            'tests': [
                {
                    'name': 'Glucose',
                    'value': '95',
                    'unit': 'mg/dL',
                    'date': '2024-01-15'
                }
            ]
        }
        
        document_metadata = {
            'document_id': 'doc_123',
            'source_system': 'lab_system'
        }
        
        # Mock the regular merge method to avoid complex setup
        with patch.object(self.merge_service, 'merge_document_data') as mock_merge:
            mock_merge.return_value = MagicMock(
                success=True,
                resources_added=1,
                resources_updated=0,
                merge_errors=[],
                processing_time_seconds=0.5,
                bundle_version_before='1'
            )
            
            result = self.merge_service.merge_document_data_transactional(
                extracted_data,
                document_metadata,
                self.user
            )
            
            self.assertIsInstance(result, TransactionResult)
            self.assertTrue(result.success)
            self.assertEqual(result.changes_applied, 1)
    
    def test_transactional_merge_staging_mode(self):
        """Test transactional merge in staging mode."""
        extracted_data = {
            'document_type': 'lab_report',
            'tests': [
                {
                    'name': 'Glucose',
                    'value': '95',
                    'unit': 'mg/dL',
                    'date': '2024-01-15'
                }
            ]
        }
        
        document_metadata = {
            'document_id': 'doc_123',
            'source_system': 'lab_system'
        }
        
        # Mock the validation and conversion methods to avoid complex setup
        with patch.object(self.merge_service, 'validate_data') as mock_validate, \
             patch.object(self.merge_service, 'convert_to_fhir') as mock_convert:
            
            mock_validate.return_value = {'data': extracted_data, 'errors': [], 'warnings': []}
            mock_convert.return_value = [
                {
                    'resourceType': 'Observation',
                    'id': 'obs-1',
                    'status': 'final',
                    'code': {'text': 'Glucose'},
                    'valueQuantity': {'value': 95, 'unit': 'mg/dL'}
                }
            ]
            
            result = self.merge_service.merge_document_data_transactional(
                extracted_data,
                document_metadata,
                self.user,
                staging_mode=True
            )
            
            self.assertTrue(result.success)
            self.assertIsNotNone(result.staging_id)
            self.assertEqual(result.changes_applied, 1)
    
    def test_create_snapshot(self):
        """Test creating a snapshot via FHIRMergeService."""
        snapshot = self.merge_service.create_snapshot(
            reason="manual_test",
            user=self.user
        )
        
        self.assertIsInstance(snapshot, TransactionSnapshot)
        self.assertEqual(snapshot.patient_mrn, self.patient.mrn)
        self.assertEqual(snapshot.reason, "manual_test")
        self.assertEqual(snapshot.created_by, self.user.username)
    
    def test_list_snapshots(self):
        """Test listing snapshots via FHIRMergeService."""
        # Create a snapshot first
        self.merge_service.create_snapshot(reason="test_snapshot", user=self.user)
        
        snapshots = self.merge_service.list_snapshots()
        
        self.assertIsInstance(snapshots, list)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]['reason'], 'test_snapshot')
    
    @patch('apps.fhir.services.AuditLog.log_event')
    def test_audit_logging_integration(self, mock_audit_log):
        """Test that transaction operations create proper audit logs."""
        mock_audit_log.return_value = MagicMock(id=123)
        
        # Create and commit a staging area
        staging_area = self.merge_service.transaction_manager.create_staging_area(
            self.patient,
            "test_operation"
        )
        
        staging_area.add_change('add', {
            'resourceType': 'Observation',
            'id': 'obs-1',
            'status': 'final'
        })
        
        result = self.merge_service.commit_staged_changes(staging_area.staging_id, self.user)
        
        self.assertTrue(result.success)
        
        # Verify audit log was called
        mock_audit_log.assert_called()
        call_args = mock_audit_log.call_args
        self.assertEqual(call_args[1]['event_type'], 'fhir_transaction_commit')
        self.assertEqual(call_args[1]['user'], self.user)
        self.assertTrue(call_args[1]['phi_involved'])


class ConcurrencyTest(TestCase):
    """Test concurrent transaction scenarios."""
    
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='testuser', email='test@example.com')
        self.patient = Patient.objects.create(
            mrn='TEST123',
            first_name='John',
            last_name='Test',
            date_of_birth='1980-01-01',
            gender='M',
            cumulative_fhir_json={
                'resourceType': 'Bundle',
                'type': 'collection',
                'meta': {'versionId': '1'},
                'entry': []
            }
        )
    
    def tearDown(self):
        cache.clear()
    
    def test_concurrent_merge_operations(self):
        """Test that concurrent merge operations are properly serialized."""
        results = []
        
        def perform_merge(operation_id):
            try:
                merge_service = FHIRMergeService(self.patient)
                
                # Mock validation and conversion to avoid complex setup
                with patch.object(merge_service, 'validate_data') as mock_validate, \
                     patch.object(merge_service, 'convert_to_fhir') as mock_convert:
                    
                    mock_validate.return_value = {
                        'data': {'test': 'data'}, 
                        'errors': [], 
                        'warnings': []
                    }
                    mock_convert.return_value = [
                        {
                            'resourceType': 'Observation',
                            'id': f'obs-{operation_id}',
                            'status': 'final'
                        }
                    ]
                    
                    result = merge_service.merge_document_data_transactional(
                        {'test': 'data'},
                        {'document_id': f'doc_{operation_id}'},
                        self.user,
                        staging_mode=True
                    )
                    
                    results.append({
                        'operation_id': operation_id,
                        'success': result.success,
                        'staging_id': result.staging_id
                    })
                    
            except Exception as e:
                results.append({
                    'operation_id': operation_id,
                    'success': False,
                    'error': str(e)
                })
        
        # Start multiple threads trying to perform merge operations
        threads = []
        for i in range(3):
            thread = threading.Thread(target=perform_merge, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # All operations should succeed (they're using staging mode)
        self.assertEqual(len(results), 3)
        for result in results:
            self.assertTrue(result['success'], f"Operation {result['operation_id']} failed")


if __name__ == '__main__':
    import unittest
    unittest.main()
