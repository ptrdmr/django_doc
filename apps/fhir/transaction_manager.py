"""
FHIR Transaction Management System

This module provides comprehensive transaction management for FHIR bundle operations,
including staging areas, rollback capabilities, snapshots, and concurrent access control.
Ensures atomic operations and data integrity for medical records.
"""

import json
import logging
import threading
import time
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import uuid4
import copy

from django.db import transaction, connection
from django.utils import timezone
from django.core.cache import cache
from django.conf import settings
from django.contrib.auth.models import User

from apps.patients.models import Patient, PatientHistory
from apps.core.models import AuditLog
from apps.core.jsonb_utils import serialize_fhir_data
from .bundle_utils import validate_bundle_integrity


logger = logging.getLogger(__name__)


@dataclass
class TransactionSnapshot:
    """Represents a point-in-time snapshot of a patient's FHIR bundle."""
    snapshot_id: str
    patient_mrn: str
    bundle_data: Dict[str, Any]
    created_at: datetime
    created_by: Optional[str] = None
    reason: str = "periodic_backup"
    bundle_version: str = "1"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary for storage."""
        return {
            'snapshot_id': self.snapshot_id,
            'patient_mrn': self.patient_mrn,
            'bundle_data': self.bundle_data,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'created_by': self.created_by,
            'reason': self.reason,
            'bundle_version': self.bundle_version
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TransactionSnapshot':
        """Create snapshot from dictionary."""
        created_at = datetime.fromisoformat(data['created_at']) if data.get('created_at') else None
        return cls(
            snapshot_id=data['snapshot_id'],
            patient_mrn=data['patient_mrn'],
            bundle_data=data['bundle_data'],
            created_at=created_at,
            created_by=data.get('created_by'),
            reason=data.get('reason', 'periodic_backup'),
            bundle_version=data.get('bundle_version', '1')
        )


@dataclass
class StagingArea:
    """Represents a staging area for pending FHIR bundle changes."""
    staging_id: str
    patient_mrn: str
    original_bundle: Dict[str, Any]
    staged_changes: List[Dict[str, Any]] = field(default_factory=list)
    merge_metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=timezone.now)
    locked_by: Optional[str] = None
    lock_acquired_at: Optional[datetime] = None
    
    def add_change(self, operation: str, resource_data: Dict[str, Any], metadata: Dict[str, Any] = None):
        """Add a staged change to the staging area."""
        change = {
            'operation': operation,  # 'add', 'update', 'delete'
            'resource_data': resource_data,
            'metadata': metadata or {},
            'timestamp': timezone.now().isoformat(),
            'change_id': str(uuid4())
        }
        self.staged_changes.append(change)
        logger.debug(f"Added {operation} change to staging area {self.staging_id}")
    
    def get_changes_summary(self) -> Dict[str, int]:
        """Get summary of staged changes by operation type."""
        summary = {'add': 0, 'update': 0, 'delete': 0}
        for change in self.staged_changes:
            operation = change.get('operation', 'unknown')
            if operation in summary:
                summary[operation] += 1
        return summary
    
    def clear_changes(self):
        """Clear all staged changes."""
        self.staged_changes = []
        logger.debug(f"Cleared all changes from staging area {self.staging_id}")


@dataclass
class TransactionResult:
    """Result of a transaction operation."""
    success: bool = False
    transaction_id: str = ""
    staging_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    changes_applied: int = 0
    rollback_performed: bool = False
    error_message: Optional[str] = None
    processing_time_seconds: float = 0.0
    bundle_version_before: str = "1"
    bundle_version_after: str = "1"
    audit_log_ids: List[int] = field(default_factory=list)


class TransactionLockManager:
    """Manages concurrent access locks for patient FHIR bundles."""
    
    def __init__(self, lock_timeout_seconds: int = 300):  # 5 minutes default
        self.lock_timeout_seconds = lock_timeout_seconds
        self.local_locks = {}  # In-memory locks for same-process concurrency
        self.lock = threading.RLock()  # Thread-safe access to local_locks
    
    def acquire_lock(self, patient_mrn: str, operation_id: str, timeout_seconds: int = None) -> bool:
        """
        Acquire an exclusive lock for a patient's FHIR bundle.
        
        Args:
            patient_mrn: Patient MRN to lock
            operation_id: Unique identifier for the operation
            timeout_seconds: Lock timeout (defaults to class setting)
            
        Returns:
            True if lock acquired, False otherwise
        """
        timeout = timeout_seconds or self.lock_timeout_seconds
        cache_key = f"fhir_lock:{patient_mrn}"
        lock_data = {
            'operation_id': operation_id,
            'acquired_at': timezone.now().isoformat(),
            'timeout_seconds': timeout
        }
        
        with self.lock:
            # Check local locks first (same process)
            if patient_mrn in self.local_locks:
                existing_lock = self.local_locks[patient_mrn]
                if existing_lock['operation_id'] != operation_id:
                    # Check if lock has expired
                    acquired_time = datetime.fromisoformat(existing_lock['acquired_at'])
                    if timezone.now() - acquired_time < timedelta(seconds=existing_lock['timeout_seconds']):
                        logger.warning(f"Local lock already held for patient {patient_mrn} by {existing_lock['operation_id']}")
                        return False
                    else:
                        # Lock expired, remove it
                        del self.local_locks[patient_mrn]
            
            # Try to acquire distributed lock via cache
            if cache.add(cache_key, lock_data, timeout=timeout):
                # Successfully acquired distributed lock, add local lock
                self.local_locks[patient_mrn] = lock_data
                logger.info(f"Acquired lock for patient {patient_mrn} by operation {operation_id}")
                return True
            else:
                logger.warning(f"Failed to acquire distributed lock for patient {patient_mrn}")
                return False
    
    def release_lock(self, patient_mrn: str, operation_id: str) -> bool:
        """
        Release a lock for a patient's FHIR bundle.
        
        Args:
            patient_mrn: Patient MRN to unlock
            operation_id: Operation ID that acquired the lock
            
        Returns:
            True if lock released, False if not held by this operation
        """
        cache_key = f"fhir_lock:{patient_mrn}"
        
        with self.lock:
            # Check local lock
            if patient_mrn in self.local_locks:
                local_lock = self.local_locks[patient_mrn]
                if local_lock['operation_id'] != operation_id:
                    logger.error(f"Cannot release lock for {patient_mrn}: not held by {operation_id}")
                    return False
                
                # Remove local lock
                del self.local_locks[patient_mrn]
            
            # Release distributed lock
            cached_lock = cache.get(cache_key)
            if cached_lock and cached_lock.get('operation_id') == operation_id:
                cache.delete(cache_key)
                logger.info(f"Released lock for patient {patient_mrn} by operation {operation_id}")
                return True
            else:
                logger.warning(f"Distributed lock for {patient_mrn} not held by {operation_id}")
                return False
    
    def is_locked(self, patient_mrn: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a patient's FHIR bundle is currently locked.
        
        Args:
            patient_mrn: Patient MRN to check
            
        Returns:
            Tuple of (is_locked, operation_id)
        """
        cache_key = f"fhir_lock:{patient_mrn}"
        
        with self.lock:
            # Check local lock first
            if patient_mrn in self.local_locks:
                local_lock = self.local_locks[patient_mrn]
                acquired_time = datetime.fromisoformat(local_lock['acquired_at'])
                if timezone.now() - acquired_time < timedelta(seconds=local_lock['timeout_seconds']):
                    return True, local_lock['operation_id']
                else:
                    # Local lock expired
                    del self.local_locks[patient_mrn]
            
            # Check distributed lock
            cached_lock = cache.get(cache_key)
            if cached_lock:
                return True, cached_lock.get('operation_id')
            
            return False, None
    
    @contextmanager
    def lock_patient(self, patient_mrn: str, operation_id: str, timeout_seconds: int = None):
        """
        Context manager for acquiring and automatically releasing patient locks.
        
        Args:
            patient_mrn: Patient MRN to lock
            operation_id: Unique identifier for the operation
            timeout_seconds: Lock timeout
            
        Raises:
            RuntimeError: If lock cannot be acquired
        """
        if not self.acquire_lock(patient_mrn, operation_id, timeout_seconds):
            raise RuntimeError(f"Could not acquire lock for patient {patient_mrn}")
        
        try:
            yield
        finally:
            self.release_lock(patient_mrn, operation_id)


class SnapshotManager:
    """Manages periodic snapshots of patient FHIR bundles for recovery purposes."""
    
    def __init__(self, max_snapshots_per_patient: int = 10):
        self.max_snapshots_per_patient = max_snapshots_per_patient
    
    def create_snapshot(
        self,
        patient: Patient,
        reason: str = "periodic_backup",
        created_by: User = None
    ) -> TransactionSnapshot:
        """
        Create a snapshot of the patient's current FHIR bundle.
        
        Args:
            patient: Patient to snapshot
            reason: Reason for creating snapshot
            created_by: User creating the snapshot
            
        Returns:
            TransactionSnapshot object
        """
        snapshot_id = f"snap_{patient.mrn}_{int(time.time())}_{str(uuid4())[:8]}"
        
        # Deep copy the bundle data to ensure immutability
        bundle_data = copy.deepcopy(patient.cumulative_fhir_json)
        
        snapshot = TransactionSnapshot(
            snapshot_id=snapshot_id,
            patient_mrn=patient.mrn,
            bundle_data=bundle_data,
            created_at=timezone.now(),
            created_by=created_by.username if created_by else None,
            reason=reason,
            bundle_version=bundle_data.get('meta', {}).get('versionId', '1')
        )
        
        # Store snapshot in cache with patient-specific key
        cache_key = f"fhir_snapshot:{patient.mrn}:{snapshot_id}"
        cache.set(cache_key, snapshot.to_dict(), timeout=86400 * 30)  # 30 days
        
        # Also maintain a list of snapshots for this patient
        snapshots_list_key = f"fhir_snapshots_list:{patient.mrn}"
        snapshots_list = cache.get(snapshots_list_key, [])
        snapshots_list.append({
            'snapshot_id': snapshot_id,
            'created_at': snapshot.created_at.isoformat(),
            'reason': reason
        })
        
        # Keep only the most recent snapshots
        snapshots_list = sorted(snapshots_list, key=lambda x: x['created_at'], reverse=True)
        if len(snapshots_list) > self.max_snapshots_per_patient:
            # Remove old snapshots
            for old_snapshot in snapshots_list[self.max_snapshots_per_patient:]:
                old_cache_key = f"fhir_snapshot:{patient.mrn}:{old_snapshot['snapshot_id']}"
                cache.delete(old_cache_key)
            snapshots_list = snapshots_list[:self.max_snapshots_per_patient]
        
        cache.set(snapshots_list_key, snapshots_list, timeout=86400 * 30)
        
        logger.info(f"Created snapshot {snapshot_id} for patient {patient.mrn} (reason: {reason})")
        return snapshot
    
    def get_snapshot(self, patient_mrn: str, snapshot_id: str) -> Optional[TransactionSnapshot]:
        """
        Retrieve a specific snapshot.
        
        Args:
            patient_mrn: Patient MRN
            snapshot_id: Snapshot identifier
            
        Returns:
            TransactionSnapshot or None if not found
        """
        cache_key = f"fhir_snapshot:{patient_mrn}:{snapshot_id}"
        snapshot_data = cache.get(cache_key)
        
        if snapshot_data:
            return TransactionSnapshot.from_dict(snapshot_data)
        return None
    
    def list_snapshots(self, patient_mrn: str) -> List[Dict[str, Any]]:
        """
        List all snapshots for a patient.
        
        Args:
            patient_mrn: Patient MRN
            
        Returns:
            List of snapshot metadata
        """
        snapshots_list_key = f"fhir_snapshots_list:{patient_mrn}"
        return cache.get(snapshots_list_key, [])
    
    def restore_from_snapshot(
        self,
        patient: Patient,
        snapshot_id: str,
        user: User = None
    ) -> bool:
        """
        Restore a patient's FHIR bundle from a snapshot.
        
        Args:
            patient: Patient to restore
            snapshot_id: Snapshot to restore from
            user: User performing the restoration
            
        Returns:
            True if restoration successful, False otherwise
        """
        snapshot = self.get_snapshot(patient.mrn, snapshot_id)
        if not snapshot:
            logger.error(f"Snapshot {snapshot_id} not found for patient {patient.mrn}")
            return False
        
        try:
            with transaction.atomic():
                # Create a backup snapshot before restoration
                backup_snapshot = self.create_snapshot(
                    patient,
                    reason=f"pre_restore_backup_{snapshot_id}",
                    created_by=user
                )
                
                # Restore the bundle data
                patient.cumulative_fhir_json = snapshot.bundle_data
                patient.save()
                
                # Log the restoration
                AuditLog.log_event(
                    event_type='fhir_restore',
                    user=user,
                    description=f"Restored FHIR bundle from snapshot {snapshot_id}",
                    details={
                        'snapshot_id': snapshot_id,
                        'snapshot_created_at': snapshot.created_at.isoformat(),
                        'backup_snapshot_id': backup_snapshot.snapshot_id,
                        'patient_mrn': patient.mrn
                    },
                    patient_mrn=patient.mrn,
                    phi_involved=True,
                    content_object=patient
                )
                
                logger.info(f"Restored patient {patient.mrn} from snapshot {snapshot_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to restore patient {patient.mrn} from snapshot {snapshot_id}: {str(e)}")
            return False


class FHIRTransactionManager:
    """
    Comprehensive transaction management system for FHIR bundle operations.
    
    Provides staging areas, rollback capabilities, snapshots, and concurrent access control
    to ensure atomic operations and data integrity for medical records.
    """
    
    def __init__(self, 
                 auto_snapshot: bool = True,
                 snapshot_frequency_hours: int = 24,
                 max_staging_time_minutes: int = 30):
        """
        Initialize the transaction manager.
        
        Args:
            auto_snapshot: Whether to automatically create snapshots
            snapshot_frequency_hours: How often to create automatic snapshots
            max_staging_time_minutes: Maximum time to keep staging areas active
        """
        self.auto_snapshot = auto_snapshot
        self.snapshot_frequency_hours = snapshot_frequency_hours
        self.max_staging_time_minutes = max_staging_time_minutes
        
        self.lock_manager = TransactionLockManager()
        self.snapshot_manager = SnapshotManager()
        self.staging_areas: Dict[str, StagingArea] = {}
    
    def create_staging_area(self, patient: Patient, operation_id: str) -> StagingArea:
        """
        Create a new staging area for pending FHIR bundle changes.
        
        Args:
            patient: Patient for whom to create staging area
            operation_id: Unique identifier for the operation
            
        Returns:
            StagingArea object
        """
        staging_id = f"stage_{patient.mrn}_{int(time.time())}_{operation_id[:8]}"
        
        # Create deep copy of current bundle for staging
        original_bundle = copy.deepcopy(patient.cumulative_fhir_json)
        
        staging_area = StagingArea(
            staging_id=staging_id,
            patient_mrn=patient.mrn,
            original_bundle=original_bundle,
            created_at=timezone.now()
        )
        
        self.staging_areas[staging_id] = staging_area
        logger.info(f"Created staging area {staging_id} for patient {patient.mrn}")
        
        return staging_area
    
    def get_staging_area(self, staging_id: str) -> Optional[StagingArea]:
        """Get a staging area by ID."""
        return self.staging_areas.get(staging_id)
    
    def commit_staging_area(
        self,
        staging_id: str,
        user: User = None,
        validation_callback: callable = None
    ) -> TransactionResult:
        """
        Commit changes from a staging area to the patient's FHIR bundle.
        
        Args:
            staging_id: Staging area to commit
            user: User performing the commit
            validation_callback: Optional validation function
            
        Returns:
            TransactionResult with operation details
        """
        result = TransactionResult(transaction_id=str(uuid4()))
        start_time = time.time()
        
        staging_area = self.staging_areas.get(staging_id)
        if not staging_area:
            result.error_message = f"Staging area {staging_id} not found"
            return result
        
        try:
            patient = Patient.objects.get(mrn=staging_area.patient_mrn)
        except Patient.DoesNotExist:
            result.error_message = f"Patient {staging_area.patient_mrn} not found"
            return result
        
        operation_id = f"commit_{staging_id}"
        
        try:
            # Acquire lock for the patient
            with self.lock_manager.lock_patient(patient.mrn, operation_id):
                with transaction.atomic():
                    # Create snapshot if auto-snapshot is enabled
                    snapshot_id = None
                    if self.auto_snapshot:
                        snapshot = self.snapshot_manager.create_snapshot(
                            patient,
                            reason=f"pre_commit_{staging_id}",
                            created_by=user
                        )
                        snapshot_id = snapshot.snapshot_id
                        result.snapshot_id = snapshot_id
                    
                    # Get current bundle version
                    result.bundle_version_before = patient.cumulative_fhir_json.get('meta', {}).get('versionId', '1')
                    
                    # Apply validation if provided
                    if validation_callback:
                        validation_result = validation_callback(staging_area)
                        if not validation_result.get('valid', True):
                            result.error_message = f"Validation failed: {validation_result.get('errors')}"
                            return result
                    
                    # Apply staged changes to patient bundle
                    updated_bundle = copy.deepcopy(staging_area.original_bundle)
                    changes_applied = 0
                    
                    for change in staging_area.staged_changes:
                        try:
                            self._apply_change(updated_bundle, change)
                            changes_applied += 1
                        except Exception as e:
                            logger.error(f"Failed to apply change {change.get('change_id')}: {str(e)}")
                            # In a real implementation, you might choose to fail the entire commit
                            # or continue with partial application based on business rules
                            continue
                    
                    # Update bundle metadata
                    if 'meta' not in updated_bundle:
                        updated_bundle['meta'] = {}
                    updated_bundle['meta']['lastUpdated'] = timezone.now().isoformat()
                    new_version = str(int(result.bundle_version_before) + 1)
                    updated_bundle['meta']['versionId'] = new_version
                    result.bundle_version_after = new_version
                    
                    # Validate final bundle integrity (basic validation for dict bundles)
                    try:
                        if not self._validate_bundle_dict(updated_bundle):
                            result.error_message = "Final bundle failed integrity validation"
                            return result
                    except Exception as e:
                        logger.warning(f"Bundle validation failed: {e}, proceeding with commit")
                    
                    # Save the updated bundle
                    patient.cumulative_fhir_json = serialize_fhir_data(updated_bundle)
                    patient.save()
                    
                    # Create audit log
                    audit_log = AuditLog.log_event(
                        event_type='fhir_transaction_commit',
                        user=user,
                        description=f"Committed staging area {staging_id}",
                        details={
                            'staging_id': staging_id,
                            'changes_applied': changes_applied,
                            'snapshot_id': snapshot_id,
                            'bundle_version_before': result.bundle_version_before,
                            'bundle_version_after': result.bundle_version_after,
                            'patient_mrn': patient.mrn
                        },
                        patient_mrn=patient.mrn,
                        phi_involved=True,
                        content_object=patient
                    )
                    result.audit_log_ids.append(audit_log.id)
                    
                    # Update result
                    result.success = True
                    result.staging_id = staging_id
                    result.changes_applied = changes_applied
                    
                    # Clean up staging area
                    del self.staging_areas[staging_id]
                    
                    logger.info(f"Successfully committed staging area {staging_id} with {changes_applied} changes")
                    
        except RuntimeError as e:
            result.error_message = f"Lock acquisition failed: {str(e)}"
        except Exception as e:
            result.error_message = f"Commit failed: {str(e)}"
            logger.error(f"Failed to commit staging area {staging_id}: {str(e)}", exc_info=True)
        
        finally:
            result.processing_time_seconds = time.time() - start_time
        
        return result
    
    def rollback_staging_area(self, staging_id: str, user: User = None) -> TransactionResult:
        """
        Rollback/discard changes in a staging area.
        
        Args:
            staging_id: Staging area to rollback
            user: User performing the rollback
            
        Returns:
            TransactionResult with operation details
        """
        result = TransactionResult(transaction_id=str(uuid4()))
        
        staging_area = self.staging_areas.get(staging_id)
        if not staging_area:
            result.error_message = f"Staging area {staging_id} not found"
            return result
        
        try:
            # Log the rollback
            if user:
                AuditLog.log_event(
                    event_type='fhir_transaction_rollback',
                    user=user,
                    description=f"Rolled back staging area {staging_id}",
                    details={
                        'staging_id': staging_id,
                        'changes_discarded': len(staging_area.staged_changes),
                        'patient_mrn': staging_area.patient_mrn
                    },
                    patient_mrn=staging_area.patient_mrn,
                    phi_involved=False
                )
            
            # Remove staging area
            del self.staging_areas[staging_id]
            
            result.success = True
            result.rollback_performed = True
            result.staging_id = staging_id
            
            logger.info(f"Rolled back staging area {staging_id}")
            
        except Exception as e:
            result.error_message = f"Rollback failed: {str(e)}"
            logger.error(f"Failed to rollback staging area {staging_id}: {str(e)}", exc_info=True)
        
        return result
    
    def _apply_change(self, bundle: Dict[str, Any], change: Dict[str, Any]):
        """
        Apply a single staged change to the bundle.
        
        Args:
            bundle: Bundle to modify
            change: Change to apply
        """
        operation = change['operation']
        resource_data = change['resource_data']
        
        if operation == 'add':
            # Add new resource to bundle
            if 'entry' not in bundle:
                bundle['entry'] = []
            
            bundle['entry'].append({
                'resource': resource_data,
                'fullUrl': f"{resource_data.get('resourceType', 'Resource')}/{resource_data.get('id', str(uuid4()))}"
            })
            
        elif operation == 'update':
            # Update existing resource
            resource_id = resource_data.get('id')
            resource_type = resource_data.get('resourceType')
            
            if not resource_id or not resource_type:
                raise ValueError("Resource ID and type required for update operation")
            
            # Find and update the resource
            for entry in bundle.get('entry', []):
                resource = entry.get('resource', {})
                if (resource.get('id') == resource_id and 
                    resource.get('resourceType') == resource_type):
                    entry['resource'] = resource_data
                    break
            else:
                # Resource not found, add it as new
                if 'entry' not in bundle:
                    bundle['entry'] = []
                bundle['entry'].append({
                    'resource': resource_data,
                    'fullUrl': f"{resource_type}/{resource_id}"
                })
        
        elif operation == 'delete':
            # Remove resource from bundle
            resource_id = resource_data.get('id')
            resource_type = resource_data.get('resourceType')
            
            if not resource_id or not resource_type:
                raise ValueError("Resource ID and type required for delete operation")
            
            # Find and remove the resource
            bundle_entries = bundle.get('entry', [])
            bundle['entry'] = [
                entry for entry in bundle_entries
                if not (entry.get('resource', {}).get('id') == resource_id and
                       entry.get('resource', {}).get('resourceType') == resource_type)
            ]
        
        else:
            raise ValueError(f"Unknown operation: {operation}")
    
    @contextmanager
    def transaction_context(
        self,
        patient: Patient,
        operation_id: str,
        user: User = None,
        auto_commit: bool = False,
        validation_callback: callable = None
    ):
        """
        Context manager for FHIR transaction operations.
        
        Args:
            patient: Patient for the transaction
            operation_id: Unique operation identifier
            user: User performing the operation
            auto_commit: Whether to automatically commit on success
            validation_callback: Optional validation function
            
        Yields:
            StagingArea for adding changes
            
        Raises:
            RuntimeError: If transaction fails
        """
        staging_area = self.create_staging_area(patient, operation_id)
        staging_id = staging_area.staging_id
        
        try:
            yield staging_area
            
            if auto_commit:
                result = self.commit_staging_area(staging_id, user, validation_callback)
                if not result.success:
                    raise RuntimeError(f"Transaction commit failed: {result.error_message}")
                
        except Exception as e:
            # Rollback on any exception
            rollback_result = self.rollback_staging_area(staging_id, user)
            if not rollback_result.success:
                logger.error(f"Rollback also failed: {rollback_result.error_message}")
            raise
    
    def cleanup_expired_staging_areas(self):
        """Clean up staging areas that have exceeded their maximum lifetime."""
        current_time = timezone.now()
        max_age = timedelta(minutes=self.max_staging_time_minutes)
        
        expired_staging_ids = []
        for staging_id, staging_area in self.staging_areas.items():
            if current_time - staging_area.created_at > max_age:
                expired_staging_ids.append(staging_id)
        
        for staging_id in expired_staging_ids:
            logger.warning(f"Cleaning up expired staging area {staging_id}")
            del self.staging_areas[staging_id]
        
        return len(expired_staging_ids)
    
    def _validate_bundle_dict(self, bundle: Dict[str, Any]) -> bool:
        """
        Basic validation for dictionary-based FHIR bundles.
        
        Args:
            bundle: Bundle dictionary to validate
            
        Returns:
            True if bundle is valid, False otherwise
        """
        try:
            # Check that it's a dictionary
            if not isinstance(bundle, dict):
                logger.warning("Bundle is not a dictionary")
                return False
            
            # Check resource type
            if bundle.get('resourceType') != 'Bundle':
                logger.warning("Bundle missing or incorrect resourceType")
                return False
            
            # Check bundle type
            if not bundle.get('type'):
                logger.warning("Bundle missing type")
                return False
            
            # Check that entries are valid
            entries = bundle.get('entry', [])
            if not isinstance(entries, list):
                logger.warning("Bundle entries is not a list")
                return False
            
            # Basic validation of entries
            for i, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    logger.warning(f"Bundle entry {i} is not a dictionary")
                    return False
                
                resource = entry.get('resource', {})
                if not isinstance(resource, dict):
                    logger.warning(f"Bundle entry {i} resource is not a dictionary")
                    return False
                
                if not resource.get('resourceType'):
                    logger.warning(f"Bundle entry {i} resource missing resourceType")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Bundle validation failed with exception: {e}")
            return False
