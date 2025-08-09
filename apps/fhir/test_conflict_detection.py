"""
Comprehensive Test Suite for FHIR Conflict Detection

This test suite validates the conflict detection functionality for different
FHIR resource types, ensuring conflicts are properly identified and categorized.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from django.test import TestCase
from django.utils import timezone

from apps.patients.models import Patient
from .services import (
    ConflictDetector,
    ConflictDetail,
    ConflictResult,
    FHIRMergeService,
    ObservationMergeHandler,
    ConditionMergeHandler,
    MergeResult
)
from .fhir_models import (
    ObservationResource,
    ConditionResource,
    MedicationStatementResource
)


class TestConflictDetector(TestCase):
    """Test the ConflictDetector class functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.conflict_detector = ConflictDetector()
    
    def test_observation_value_conflict_detection(self):
        """Test detection of value conflicts in Observation resources."""
        # Create two observations with different values
        obs1 = Mock()
        obs1.resource_type = 'Observation'
        obs1.code = {'coding': [{'code': 'blood-glucose'}]}
        obs1.valueQuantity = Mock()
        obs1.valueQuantity.value = 120.0
        obs1.valueQuantity.unit = 'mg/dL'
        obs1.effectiveDateTime = '2023-12-01T10:00:00Z'
        obs1.id = 'obs-1'
        
        obs2 = Mock()
        obs2.resource_type = 'Observation'
        obs2.code = {'coding': [{'code': 'blood-glucose'}]}
        obs2.valueQuantity = Mock()
        obs2.valueQuantity.value = 95.0
        obs2.valueQuantity.unit = 'mg/dL'
        obs2.effectiveDateTime = '2023-12-01T10:00:00Z'
        obs2.id = 'obs-2'
        
        conflicts = self.conflict_detector.detect_conflicts(obs1, obs2, 'Observation')
        
        # Should detect a value conflict
        self.assertGreater(len(conflicts), 0)
        value_conflicts = [c for c in conflicts if c.conflict_type == 'value_mismatch']
        self.assertEqual(len(value_conflicts), 1)
        self.assertEqual(value_conflicts[0].field_name, 'value')
        self.assertEqual(value_conflicts[0].existing_value, 95.0)
        self.assertEqual(value_conflicts[0].new_value, 120.0)
    
    def test_observation_unit_conflict_detection(self):
        """Test detection of unit conflicts in Observation resources."""
        obs1 = Mock()
        obs1.resource_type = 'Observation'
        obs1.code = {'coding': [{'code': 'blood-glucose'}]}
        obs1.valueQuantity = Mock()
        obs1.valueQuantity.value = 120.0
        obs1.valueQuantity.unit = 'mg/dL'
        obs1.effectiveDateTime = '2023-12-01T10:00:00Z'
        obs1.id = 'obs-1'
        
        obs2 = Mock()
        obs2.resource_type = 'Observation'
        obs2.code = {'coding': [{'code': 'blood-glucose'}]}
        obs2.valueQuantity = Mock()
        obs2.valueQuantity.value = 120.0
        obs2.valueQuantity.unit = 'mmol/L'  # Different unit!
        obs2.effectiveDateTime = '2023-12-01T10:00:00Z'
        obs2.id = 'obs-2'
        
        conflicts = self.conflict_detector.detect_conflicts(obs1, obs2, 'Observation')
        
        # Should detect a unit conflict
        unit_conflicts = [c for c in conflicts if c.conflict_type == 'unit_mismatch']
        self.assertEqual(len(unit_conflicts), 1)
        self.assertEqual(unit_conflicts[0].severity, 'high')  # Unit conflicts are serious
        self.assertEqual(unit_conflicts[0].existing_value, 'mmol/L')
        self.assertEqual(unit_conflicts[0].new_value, 'mg/dL')
    
    def test_observation_temporal_conflict_detection(self):
        """Test detection of temporal conflicts in Observation resources."""
        base_time = datetime(2023, 12, 1, 10, 0, 0)
        later_time = base_time + timedelta(hours=3)  # 3 hours later
        
        obs1 = Mock()
        obs1.resource_type = 'Observation'
        obs1.code = {'coding': [{'code': 'blood-glucose'}]}
        obs1.valueQuantity = Mock()
        obs1.valueQuantity.value = 120.0
        obs1.valueQuantity.unit = 'mg/dL'
        obs1.effectiveDateTime = base_time.isoformat() + 'Z'
        obs1.id = 'obs-1'
        
        obs2 = Mock()
        obs2.resource_type = 'Observation'
        obs2.code = {'coding': [{'code': 'blood-glucose'}]}
        obs2.valueQuantity = Mock()
        obs2.valueQuantity.value = 120.0
        obs2.valueQuantity.unit = 'mg/dL'
        obs2.effectiveDateTime = later_time.isoformat() + 'Z'
        obs2.id = 'obs-2'
        
        conflicts = self.conflict_detector.detect_conflicts(obs1, obs2, 'Observation')
        
        # Should detect a temporal conflict
        temporal_conflicts = [c for c in conflicts if c.conflict_type == 'temporal_conflict']
        self.assertEqual(len(temporal_conflicts), 1)
        self.assertEqual(temporal_conflicts[0].field_name, 'effectiveDateTime')
        self.assertEqual(temporal_conflicts[0].severity, 'medium')
    
    def test_condition_status_conflict_detection(self):
        """Test detection of status conflicts in Condition resources."""
        condition1 = Mock()
        condition1.resource_type = 'Condition'
        condition1.code = {'coding': [{'code': 'diabetes'}]}
        condition1.clinicalStatus = 'active'
        condition1.onsetDateTime = '2023-01-01T00:00:00Z'
        condition1.severity = 'moderate'
        condition1.id = 'cond-1'
        
        condition2 = Mock()
        condition2.resource_type = 'Condition'
        condition2.code = {'coding': [{'code': 'diabetes'}]}
        condition2.clinicalStatus = 'resolved'  # Different status!
        condition2.onsetDateTime = '2023-01-01T00:00:00Z'
        condition2.severity = 'moderate'
        condition2.id = 'cond-2'
        
        conflicts = self.conflict_detector.detect_conflicts(condition1, condition2, 'Condition')
        
        # Should detect a status conflict
        status_conflicts = [c for c in conflicts if c.conflict_type == 'status_conflict']
        self.assertEqual(len(status_conflicts), 1)
        self.assertEqual(status_conflicts[0].field_name, 'clinicalStatus')
        self.assertEqual(status_conflicts[0].severity, 'high')  # Active vs Resolved is critical
        self.assertEqual(status_conflicts[0].existing_value, 'resolved')
        self.assertEqual(status_conflicts[0].new_value, 'active')
    
    def test_medication_dosage_conflict_detection(self):
        """Test detection of dosage conflicts in MedicationStatement resources."""
        med1 = Mock()
        med1.resource_type = 'MedicationStatement'
        med1.medicationCodeableConcept = {'coding': [{'code': 'aspirin'}]}
        med1.dosage = '81mg daily'
        med1.status = 'active'
        med1.effectivePeriod = {'start': '2023-01-01'}
        med1.id = 'med-1'
        
        med2 = Mock()
        med2.resource_type = 'MedicationStatement'
        med2.medicationCodeableConcept = {'coding': [{'code': 'aspirin'}]}
        med2.dosage = '325mg daily'  # Different dosage!
        med2.status = 'active'
        med2.effectivePeriod = {'start': '2023-01-01'}
        med2.id = 'med-2'
        
        conflicts = self.conflict_detector.detect_conflicts(med1, med2, 'MedicationStatement')
        
        # Should detect a dosage conflict
        dosage_conflicts = [c for c in conflicts if c.conflict_type == 'dosage_conflict']
        self.assertEqual(len(dosage_conflicts), 1)
        self.assertEqual(dosage_conflicts[0].field_name, 'dosage')
        self.assertEqual(dosage_conflicts[0].severity, 'high')  # Dosage conflicts are critical
        self.assertEqual(dosage_conflicts[0].existing_value, '325mg daily')
        self.assertEqual(dosage_conflicts[0].new_value, '81mg daily')
    
    def test_duplicate_detection_observations(self):
        """Test duplicate detection for identical observations."""
        # Create two identical observations
        obs1 = Mock()
        obs1.resource_type = 'Observation'
        obs1.code = {'coding': [{'code': 'blood-glucose'}]}
        obs1.valueQuantity = Mock()
        obs1.valueQuantity.value = 120.0
        obs1.valueQuantity.unit = 'mg/dL'
        obs1.effectiveDateTime = '2023-12-01T10:00:00Z'
        obs1.valueString = None
        obs1.valueCodeableConcept = None
        obs1.valueBoolean = None
        
        obs2 = Mock()
        obs2.resource_type = 'Observation'
        obs2.code = {'coding': [{'code': 'blood-glucose'}]}
        obs2.valueQuantity = Mock()
        obs2.valueQuantity.value = 120.0
        obs2.valueQuantity.unit = 'mg/dL'
        obs2.effectiveDateTime = '2023-12-01T10:00:00Z'
        obs2.valueString = None
        obs2.valueCodeableConcept = None
        obs2.valueBoolean = None
        
        is_duplicate = self.conflict_detector.check_for_duplicates(obs1, obs2, 'Observation')
        self.assertTrue(is_duplicate)
    
    def test_duplicate_detection_conditions(self):
        """Test duplicate detection for identical conditions."""
        condition1 = Mock()
        condition1.resource_type = 'Condition'
        condition1.code = {'coding': [{'code': 'diabetes'}]}
        condition1.clinicalStatus = 'active'
        condition1.onsetDateTime = '2023-01-01T00:00:00Z'
        
        condition2 = Mock()
        condition2.resource_type = 'Condition'
        condition2.code = {'coding': [{'code': 'diabetes'}]}
        condition2.clinicalStatus = 'active'
        condition2.onsetDateTime = '2023-01-01T00:00:00Z'
        
        is_duplicate = self.conflict_detector.check_for_duplicates(condition1, condition2, 'Condition')
        self.assertTrue(is_duplicate)
    
    def test_severity_assessment_numeric_values(self):
        """Test severity assessment for numeric value conflicts."""
        # Test high severity (>50% difference)
        severity = self.conflict_detector._assess_value_conflict_severity(100.0, 40.0)
        self.assertEqual(severity, 'high')
        
        # Test medium severity (20-50% difference)
        severity = self.conflict_detector._assess_value_conflict_severity(100.0, 80.0)
        self.assertEqual(severity, 'medium')
        
        # Test low severity (<20% difference)
        severity = self.conflict_detector._assess_value_conflict_severity(100.0, 95.0)
        self.assertEqual(severity, 'low')
        
        # Test with zero values
        severity = self.conflict_detector._assess_value_conflict_severity(0.0, 100.0)
        self.assertEqual(severity, 'high')
    
    def test_condition_status_conflict_severity(self):
        """Test severity assessment for condition status conflicts."""
        # Test critical transitions
        severity = self.conflict_detector._assess_condition_status_conflict('active', 'resolved')
        self.assertEqual(severity, 'high')
        
        severity = self.conflict_detector._assess_condition_status_conflict('resolved', 'active')
        self.assertEqual(severity, 'high')
        
        # Test other transitions
        severity = self.conflict_detector._assess_condition_status_conflict('active', 'provisional')
        self.assertEqual(severity, 'medium')


class TestConflictResult(TestCase):
    """Test the ConflictResult class functionality."""
    
    def test_conflict_result_tracking(self):
        """Test that ConflictResult properly tracks conflicts."""
        result = ConflictResult()
        
        # Add some conflicts
        conflict1 = ConflictDetail(
            conflict_type='value_mismatch',
            resource_type='Observation',
            field_name='value',
            existing_value=100.0,
            new_value=120.0,
            severity='medium'
        )
        
        conflict2 = ConflictDetail(
            conflict_type='unit_mismatch',
            resource_type='Observation',
            field_name='unit',
            existing_value='mg/dL',
            new_value='mmol/L',
            severity='high'
        )
        
        conflict3 = ConflictDetail(
            conflict_type='status_conflict',
            resource_type='Condition',
            field_name='clinicalStatus',
            existing_value='active',
            new_value='resolved',
            severity='critical'
        )
        
        result.add_conflict(conflict1)
        result.add_conflict(conflict2)
        result.add_conflict(conflict3)
        
        # Check totals
        self.assertEqual(result.total_conflicts, 3)
        
        # Check conflict type counts
        self.assertEqual(result.conflict_types['value_mismatch'], 1)
        self.assertEqual(result.conflict_types['unit_mismatch'], 1)
        self.assertEqual(result.conflict_types['status_conflict'], 1)
        
        # Check resource type counts
        self.assertEqual(result.resource_conflicts['Observation'], 2)
        self.assertEqual(result.resource_conflicts['Condition'], 1)
        
        # Check severity counts
        self.assertEqual(result.severity_counts['medium'], 1)
        self.assertEqual(result.severity_counts['high'], 1)
        self.assertEqual(result.severity_counts['critical'], 1)
        
        # Check critical conflicts
        self.assertTrue(result.has_critical_conflicts())
    
    def test_conflict_filtering(self):
        """Test filtering conflicts by type and resource type."""
        result = ConflictResult()
        
        conflict1 = ConflictDetail(
            conflict_type='value_mismatch',
            resource_type='Observation',
            field_name='value',
            existing_value=100.0,
            new_value=120.0
        )
        
        conflict2 = ConflictDetail(
            conflict_type='status_conflict',
            resource_type='Condition',
            field_name='clinicalStatus',
            existing_value='active',
            new_value='resolved'
        )
        
        result.add_conflict(conflict1)
        result.add_conflict(conflict2)
        
        # Test filtering by conflict type
        value_conflicts = result.get_conflicts_by_type('value_mismatch')
        self.assertEqual(len(value_conflicts), 1)
        self.assertEqual(value_conflicts[0].conflict_type, 'value_mismatch')
        
        # Test filtering by resource type
        obs_conflicts = result.get_conflicts_by_resource_type('Observation')
        self.assertEqual(len(obs_conflicts), 1)
        self.assertEqual(obs_conflicts[0].resource_type, 'Observation')


class TestMergeHandlerConflictIntegration(TestCase):
    """Test integration of conflict detection with merge handlers."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.observation_handler = ObservationMergeHandler()
        self.condition_handler = ConditionMergeHandler()
        
        # Mock bundle
        self.mock_bundle = Mock()
        self.mock_bundle.entry = []
        
        # Mock context
        self.context = {
            'current_bundle': self.mock_bundle,
            'document_metadata': {'source': 'test'},
            'user': None,
            'merge_timestamp': timezone.now()
        }
        
        # Mock config with conflict detection enabled
        self.config = {
            'conflict_detection_enabled': True,
            'duplicate_detection_enabled': True
        }
    
    def test_observation_handler_conflict_detection(self):
        """Test that ObservationMergeHandler properly uses conflict detection."""
        # Create a new observation
        new_obs = Mock()
        new_obs.resource_type = 'Observation'
        new_obs.code = {'coding': [{'code': 'blood-glucose'}]}
        new_obs.valueQuantity = Mock()
        new_obs.valueQuantity.value = 120.0
        new_obs.valueQuantity.unit = 'mg/dL'
        new_obs.effectiveDateTime = '2023-12-01T10:00:00Z'
        new_obs.subject = 'Patient/123'
        new_obs.id = 'obs-new'
        new_obs.valueString = None
        new_obs.valueCodeableConcept = None
        new_obs.valueBoolean = None
        
        # Create an existing observation with conflict
        existing_obs = Mock()
        existing_obs.resource_type = 'Observation'
        existing_obs.code = {'coding': [{'code': 'blood-glucose'}]}
        existing_obs.valueQuantity = Mock()
        existing_obs.valueQuantity.value = 95.0  # Different value
        existing_obs.valueQuantity.unit = 'mg/dL'
        existing_obs.effectiveDateTime = '2023-12-01T10:00:00Z'
        existing_obs.subject = 'Patient/123'
        existing_obs.id = 'obs-existing'
        existing_obs.valueString = None
        existing_obs.valueCodeableConcept = None
        existing_obs.valueBoolean = None
        
        # Mock the bundle entry
        mock_entry = Mock()
        mock_entry.resource = existing_obs
        self.mock_bundle.entry = [mock_entry]
        
        # Mock the _add_resource_to_bundle method
        self.observation_handler._add_resource_to_bundle = Mock(return_value={
            'action': 'added',
            'resource_type': 'Observation',
            'resource_id': 'obs-new'
        })
        
        # Test merge
        result = self.observation_handler.merge_resource(
            new_obs, self.mock_bundle, self.context, self.config
        )
        
        # Should detect conflicts and add as sequence
        self.assertEqual(result['action'], 'added_as_sequence')
        self.assertGreater(result['conflicts_detected'], 0)
        self.assertEqual(result['conflicts_resolved'], result['conflicts_detected'])
        self.assertIn('conflict_details', result)
        self.assertGreater(len(result['conflict_details']), 0)
    
    def test_condition_handler_conflict_detection(self):
        """Test that ConditionMergeHandler properly uses conflict detection."""
        # Create a new condition
        new_condition = Mock()
        new_condition.resource_type = 'Condition'
        new_condition.code = {'coding': [{'code': 'diabetes'}]}
        new_condition.clinicalStatus = 'active'
        new_condition.onsetDateTime = '2023-01-01T00:00:00Z'
        new_condition.subject = 'Patient/123'
        new_condition.recordedDate = '2023-12-01T00:00:00Z'
        new_condition.id = 'cond-new'
        new_condition.severity = None
        
        # Create an existing condition with conflict
        existing_condition = Mock()
        existing_condition.resource_type = 'Condition'
        existing_condition.code = {'coding': [{'code': 'diabetes'}]}
        existing_condition.clinicalStatus = 'resolved'  # Different status
        existing_condition.onsetDateTime = '2023-01-01T00:00:00Z'
        existing_condition.subject = 'Patient/123'
        existing_condition.recordedDate = '2023-11-01T00:00:00Z'
        existing_condition.id = 'cond-existing'
        existing_condition.severity = None
        
        # Mock the bundle entry
        mock_entry = Mock()
        mock_entry.resource = existing_condition
        self.mock_bundle.entry = [mock_entry]
        
        # Mock the update method
        self.condition_handler._update_existing_condition = Mock(return_value={
            'action': 'updated',
            'resource_type': 'Condition',
            'resource_id': 'cond-existing',
            'warnings': []
        })
        
        # Test merge
        result = self.condition_handler.merge_resource(
            new_condition, self.mock_bundle, self.context, self.config
        )
        
        # Should detect conflicts and update
        self.assertEqual(result['action'], 'updated')
        self.assertGreater(result['conflicts_detected'], 0)
        self.assertEqual(result['conflicts_resolved'], result['conflicts_detected'])


if __name__ == '__main__':
    unittest.main() 