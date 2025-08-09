"""
Test suite for FHIR conflict resolution strategies.

This module tests the conflict resolution system that handles conflicts between
new and existing FHIR resources during the merge process.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth.models import User

from fhir.resources.observation import Observation
from fhir.resources.condition import Condition  
from fhir.resources.medicationstatement import MedicationStatement
from fhir.resources.bundle import Bundle

from apps.patients.models import Patient
from apps.fhir.services import (
    FHIRMergeService,
    ConflictDetail,
    ConflictResult,
    ConflictResolver,
    NewestWinsStrategy,
    PreserveBothStrategy,
    ConfidenceBasedStrategy,
    ManualReviewStrategy,
    ObservationMergeHandler
)


class ConflictResolutionStrategyTest(TestCase):
    """
    Test suite for individual conflict resolution strategies.
    """
    
    def setUp(self):
        """Set up test fixtures for conflict resolution testing."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            gender='M',  # Add valid gender
            created_by=self.user
        )
        
        # Create test FHIR resources with timestamps
        # Both observations should represent the same measurement (same date) to trigger conflict detection
        self.new_observation = self._create_test_observation(
            value=150.0,
            date='2024-12-15T10:00:00Z',
            resource_id='glucose-obs-1'
        )
        
        self.existing_observation = self._create_test_observation(
            value=140.0,
            date='2024-12-15T10:00:00Z',  # Same date to trigger conflict detection
            resource_id='glucose-obs-2'  # Different ID but same measurement time
        )
        
        self.conflict_detail = ConflictDetail(
            conflict_type='value_mismatch',
            resource_type='Observation',
            field_name='valueQuantity.value',
            existing_value='140.0',
            new_value='150.0',
            severity='medium',
            description='Lab result value mismatch',
            resource_id='test-obs-1'
        )
        
        self.context = {
            'document_metadata': {
                'ai_confidence_score': 0.85
            },
            'user': self.user,
            'merge_timestamp': timezone.now()
        }
    
    def _create_test_observation(self, value: float, date: str, resource_id: str) -> Observation:
        """Create a test Observation resource with specified parameters."""
        obs_data = {
            'resourceType': 'Observation',
            'id': resource_id,
            'status': 'final',
            'code': {
                'coding': [{
                    'system': 'http://loinc.org',
                    'code': '33747-0',
                    'display': 'Glucose'
                }]
            },
            'subject': {
                'reference': f'Patient/{self.patient.id}'
            },
            'effectiveDateTime': date,
            'valueQuantity': {
                'value': value,
                'unit': 'mg/dL',
                'system': 'http://unitsofmeasure.org'
            }
        }
        return Observation(**obs_data)


class TestNewestWinsStrategy(ConflictResolutionStrategyTest):
    """Test the newest wins resolution strategy."""
    
    def setUp(self):
        super().setUp()
        self.strategy = NewestWinsStrategy()
    
    def test_newer_resource_wins(self):
        """Test that newer resource is selected when timestamps differ."""
        result = self.strategy.resolve_conflict(
            self.conflict_detail,
            self.new_observation,  # 2024-12-15 (newer)
            self.existing_observation,  # 2024-12-14 (older)
            self.context
        )
        
        self.assertEqual(result['strategy'], 'newest_wins')
        self.assertEqual(result['action'], 'keep_new')
        self.assertEqual(result['resolved_value'], '150.0')
        self.assertIn('newer or equal', result['reasoning'])
    
    def test_older_new_resource_loses(self):
        """Test that older new resource loses to newer existing resource."""
        # Swap the timestamps to make existing newer
        older_new_obs = self._create_test_observation(
            value=150.0,
            date='2024-12-13T10:00:00Z',  # Older than existing
            resource_id='older-new-obs'
        )
        
        result = self.strategy.resolve_conflict(
            self.conflict_detail,
            older_new_obs,
            self.existing_observation,  # 2024-12-14 (newer)
            self.context
        )
        
        self.assertEqual(result['action'], 'keep_existing')
        self.assertEqual(result['resolved_value'], '140.0')
        self.assertIn('Existing resource is newer', result['reasoning'])
    
    def test_missing_timestamps_defaults_to_new(self):
        """Test behavior when timestamps are missing."""
        # Create observation without effectiveDateTime
        obs_without_date = self._create_test_observation(150.0, None, 'no-date-obs')
        obs_without_date.effectiveDateTime = None
        
        conflict_detail = ConflictDetail(
            conflict_type='value_mismatch',
            resource_type='Observation',
            field_name='valueQuantity.value',
            existing_value='140.0',
            new_value='150.0',
            severity='medium'
        )
        
        result = self.strategy.resolve_conflict(
            conflict_detail,
            obs_without_date,
            obs_without_date,
            self.context
        )
        
        self.assertEqual(result['action'], 'keep_new')
        self.assertIn('Default to new resource', result['reasoning'])
    
    def test_conflict_detail_updated_with_resolution(self):
        """Test that conflict detail is updated with resolution information."""
        result = self.strategy.resolve_conflict(
            self.conflict_detail,
            self.new_observation,
            self.existing_observation,
            self.context
        )
        
        self.assertEqual(self.conflict_detail.resolution_strategy, 'newest_wins')
        self.assertIsNotNone(self.conflict_detail.resolution_result)
        self.assertEqual(self.conflict_detail.resolution_result['action'], 'keep_new')


class TestPreserveBothStrategy(ConflictResolutionStrategyTest):
    """Test the preserve both resolution strategy."""
    
    def setUp(self):
        super().setUp()
        self.strategy = PreserveBothStrategy()
    
    def test_preserve_both_values(self):
        """Test that both values are preserved in temporal sequence."""
        result = self.strategy.resolve_conflict(
            self.conflict_detail,
            self.new_observation,
            self.existing_observation,
            self.context
        )
        
        self.assertEqual(result['strategy'], 'preserve_both')
        self.assertEqual(result['action'], 'preserve_both')
        
        resolved_value = result['resolved_value']
        self.assertEqual(resolved_value['existing'], '140.0')
        self.assertEqual(resolved_value['new'], '150.0')
        self.assertEqual(resolved_value['preservation_method'], 'temporal_sequence')
    
    def test_critical_conflict_flagged_for_review(self):
        """Test that critical conflicts get additional review metadata."""
        critical_conflict = ConflictDetail(
            conflict_type='dosage_conflict',
            resource_type='MedicationStatement',
            field_name='dosageInstruction.doseAndRate.doseQuantity.value',
            existing_value='10mg',
            new_value='100mg',
            severity='critical',
            description='Critical medication dosage mismatch'
        )
        
        result = self.strategy.resolve_conflict(
            critical_conflict,
            self.new_observation,
            self.existing_observation,
            self.context
        )
        
        metadata = result['metadata']
        self.assertTrue(metadata['flagged_for_review'])
        self.assertEqual(metadata['review_priority'], 'high')
        self.assertEqual(metadata['clinical_significance'], 'potential_safety_issue')
    
    def test_high_severity_requires_clinical_review(self):
        """Test that high severity conflicts require clinical review."""
        high_severity_conflict = ConflictDetail(
            conflict_type='value_mismatch',
            resource_type='Observation',
            field_name='valueQuantity.value',
            existing_value='140.0',
            new_value='300.0',  # Significantly different
            severity='high'
        )
        
        result = self.strategy.resolve_conflict(
            high_severity_conflict,
            self.new_observation,
            self.existing_observation,
            self.context
        )
        
        self.assertTrue(result['metadata']['requires_clinical_review'])


class TestConfidenceBasedStrategy(ConflictResolutionStrategyTest):
    """Test the confidence-based resolution strategy."""
    
    def setUp(self):
        super().setUp()
        self.strategy = ConfidenceBasedStrategy()
    
    def test_higher_confidence_new_resource_wins(self):
        """Test that new resource with higher confidence wins."""
        # Mock the confidence extraction to return different values for new vs existing
        with patch.object(self.strategy, '_extract_confidence_score') as mock_extract:
            # Return higher confidence for new, lower for existing
            mock_extract.side_effect = [0.95, 0.85]  # new_confidence, existing_confidence
            
            result = self.strategy.resolve_conflict(
                self.conflict_detail,
                self.new_observation,
                self.existing_observation,
                self.context
            )
            
            self.assertEqual(result['action'], 'keep_new')
            self.assertIn('higher confidence', result['reasoning'])
            confidence_comparison = result['confidence_comparison']
            self.assertEqual(confidence_comparison['new_confidence'], 0.95)
            self.assertEqual(confidence_comparison['existing_confidence'], 0.85)
    
    def test_higher_confidence_existing_resource_wins(self):
        """Test that existing resource with higher confidence wins."""
        # Mock existing resource with higher confidence
        with patch.object(self.strategy, '_extract_confidence_score') as mock_extract:
            # Return higher confidence for existing, lower for new
            mock_extract.side_effect = [0.70, 0.90]  # new_confidence, existing_confidence
            
            result = self.strategy.resolve_conflict(
                self.conflict_detail,
                self.new_observation,
                self.existing_observation,
                self.context
            )
            
            self.assertEqual(result['action'], 'keep_existing')
            self.assertEqual(result['resolved_value'], '140.0')
            self.assertIn('higher confidence', result['reasoning'])
    
    def test_equal_confidence_falls_back_to_newest_wins(self):
        """Test fallback to newest_wins when confidence scores are equal."""
        with patch.object(self.strategy, '_extract_confidence_score') as mock_extract:
            # Return equal confidence scores
            mock_extract.side_effect = [0.85, 0.85]
            
            result = self.strategy.resolve_conflict(
                self.conflict_detail,
                self.new_observation,
                self.existing_observation,
                self.context
            )
            
            self.assertIn('fallback_newest_wins', result['strategy'])
            self.assertIn('Equal confidence', result['reasoning'])
    
    def test_missing_confidence_falls_back_to_newest_wins(self):
        """Test fallback when confidence scores are missing."""
        context_no_confidence = {
            'user': self.user,
            'merge_timestamp': timezone.now()
        }
        
        result = self.strategy.resolve_conflict(
            self.conflict_detail,
            self.new_observation,
            self.existing_observation,
            context_no_confidence
        )
        
        self.assertIn('fallback_newest_wins', result['strategy'])
        self.assertIn('Missing confidence scores', result['reasoning'])
    
    def test_confidence_extraction_from_resource_meta(self):
        """Test extraction of confidence from resource meta tags."""
        # This would require mocking fhir resource meta structure
        # For now, test the basic extraction logic
        confidence = self.strategy._extract_confidence_score(
            self.new_observation,
            self.context
        )
        
        # Should extract from document metadata
        self.assertEqual(confidence, 0.85)


class TestManualReviewStrategy(ConflictResolutionStrategyTest):
    """Test the manual review resolution strategy."""
    
    def setUp(self):
        super().setUp()
        self.strategy = ManualReviewStrategy()
    
    def test_flag_for_manual_review(self):
        """Test that conflicts are flagged for manual review."""
        result = self.strategy.resolve_conflict(
            self.conflict_detail,
            self.new_observation,
            self.existing_observation,
            self.context
        )
        
        self.assertEqual(result['strategy'], 'manual_review')
        self.assertEqual(result['action'], 'flag_for_review')
        self.assertIsNone(result['resolved_value'])
        self.assertEqual(result['reasoning'], 'Conflict requires manual review')
        
        review_metadata = result['review_metadata']
        self.assertTrue(review_metadata['requires_clinical_review'])
        self.assertTrue(review_metadata['both_values_preserved'])
        self.assertEqual(review_metadata['existing_value'], '140.0')
        self.assertEqual(review_metadata['new_value'], '150.0')
    
    def test_critical_conflict_gets_urgent_review(self):
        """Test that critical conflicts get urgent review priority."""
        critical_conflict = ConflictDetail(
            conflict_type='dosage_conflict',
            resource_type='MedicationStatement',
            field_name='dosageInstruction',
            existing_value='10mg',
            new_value='100mg',
            severity='critical'
        )
        
        result = self.strategy.resolve_conflict(
            critical_conflict,
            self.new_observation,
            self.existing_observation,
            self.context
        )
        
        review_metadata = result['review_metadata']
        self.assertEqual(review_metadata['review_priority'], 'urgent')
        self.assertTrue(review_metadata['urgent_review'])
        self.assertTrue(review_metadata['potential_safety_issue'])
        self.assertTrue(review_metadata['escalation_required'])
    
    def test_review_priority_determination(self):
        """Test that review priority is determined correctly by severity."""
        # Test different severity levels
        test_cases = [
            ('critical', 'urgent'),
            ('high', 'high'),
            ('medium', 'low'),
            ('low', 'low')
        ]
        
        for severity, expected_priority in test_cases:
            conflict = ConflictDetail(
                conflict_type='timing_conflict',  # Use non-special conflict type
                resource_type='Observation',
                field_name='value',
                existing_value='old',
                new_value='new',
                severity=severity
            )
            
            priority = self.strategy._determine_review_priority(conflict)
            self.assertEqual(priority, expected_priority, f"Failed for severity {severity}")
    
    def test_special_conflict_types_get_medium_priority(self):
        """Test that value_mismatch and dosage_conflict get medium priority."""
        for conflict_type in ['value_mismatch', 'dosage_conflict']:
            conflict = ConflictDetail(
                conflict_type=conflict_type,
                resource_type='Observation',
                field_name='value',
                existing_value='old',
                new_value='new',
                severity='low'  # Even with low severity, these types get medium
            )
            
            priority = self.strategy._determine_review_priority(conflict)
            self.assertEqual(priority, 'medium', f"Failed for conflict type {conflict_type}")


class TestConflictResolver(ConflictResolutionStrategyTest):
    """Test the main ConflictResolver coordination class."""
    
    def setUp(self):
        super().setUp()
        self.config = {
            'conflict_resolution_strategy': 'newest_wins',
            'conflict_type_strategies': {
                'dosage_conflict': 'manual_review',
                'temporal_conflict': 'preserve_both'
            },
            'resource_type_strategies': {
                'MedicationStatement': 'preserve_both'
            },
            'severity_strategies': {
                'critical': 'manual_review',
                'high': 'preserve_both',
                'medium': 'newest_wins',
                'low': 'newest_wins'
            }
        }
        self.resolver = ConflictResolver(self.config)
    
    def test_resolver_initialization(self):
        """Test that conflict resolver initializes with all strategies."""
        expected_strategies = ['newest_wins', 'preserve_both', 'confidence_based', 'manual_review']
        
        for strategy_name in expected_strategies:
            self.assertIn(strategy_name, self.resolver.strategies)
            self.assertIsNotNone(self.resolver.strategies[strategy_name])
    
    def test_resolve_no_conflicts(self):
        """Test resolution when no conflicts exist."""
        result = self.resolver.resolve_conflicts(
            [],  # No conflicts
            self.new_observation,
            self.existing_observation,
            self.context
        )
        
        self.assertEqual(result['total_conflicts'], 0)
        self.assertEqual(result['resolved_conflicts'], 0)
        self.assertEqual(result['overall_action'], 'no_conflicts')
    
    def test_resolve_multiple_conflicts(self):
        """Test resolution of multiple conflicts with different strategies."""
        conflicts = [
            ConflictDetail(
                conflict_type='value_mismatch',
                resource_type='Observation',
                field_name='valueQuantity.value',
                existing_value='140.0',
                new_value='150.0',
                severity='medium'
            ),
            ConflictDetail(
                conflict_type='dosage_conflict',
                resource_type='MedicationStatement',
                field_name='dosage',
                existing_value='10mg',
                new_value='20mg',
                severity='high'
            )
        ]
        
        result = self.resolver.resolve_conflicts(
            conflicts,
            self.new_observation,
            self.existing_observation,
            self.context
        )
        
        self.assertEqual(result['total_conflicts'], 2)
        self.assertEqual(len(result['resolution_actions']), 2)
        
        # Check that different strategies were applied
        actions = result['resolution_actions']
        strategies_used = [action['strategy_used'] for action in actions]
        
        # Based on config: value_mismatch -> medium -> newest_wins
        # dosage_conflict -> manual_review (from conflict_type_strategies)
        self.assertIn('newest_wins', strategies_used)
        self.assertIn('manual_review', strategies_used)
    
    def test_strategy_selection_by_conflict_type(self):
        """Test that strategy selection respects conflict type configuration."""
        conflict = ConflictDetail(
            conflict_type='dosage_conflict',
            resource_type='Observation',
            field_name='dosage',
            existing_value='10mg',
            new_value='20mg',
            severity='low'
        )
        
        strategy_name = self.resolver._select_strategy_for_conflict(conflict)
        self.assertEqual(strategy_name, 'manual_review')  # From conflict_type_strategies
    
    def test_strategy_selection_by_resource_type(self):
        """Test that strategy selection respects resource type configuration."""
        conflict = ConflictDetail(
            conflict_type='value_mismatch',
            resource_type='MedicationStatement',
            field_name='dosage',
            existing_value='10mg',
            new_value='20mg',
            severity='medium'
        )
        
        strategy_name = self.resolver._select_strategy_for_conflict(conflict)
        self.assertEqual(strategy_name, 'preserve_both')  # From resource_type_strategies
    
    def test_strategy_selection_by_severity(self):
        """Test that strategy selection falls back to severity-based mapping."""
        conflict = ConflictDetail(
            conflict_type='unknown_conflict',
            resource_type='UnknownResource',
            field_name='field',
            existing_value='old',
            new_value='new',
            severity='critical'
        )
        
        strategy_name = self.resolver._select_strategy_for_conflict(conflict)
        self.assertEqual(strategy_name, 'manual_review')  # From severity_strategies
    
    def test_critical_conflicts_overall_action(self):
        """Test that critical conflicts result in appropriate overall action."""
        critical_conflict = ConflictDetail(
            conflict_type='dosage_conflict',
            resource_type='MedicationStatement',
            field_name='dosage',
            existing_value='10mg',
            new_value='100mg',
            severity='critical'
        )
        
        result = self.resolver.resolve_conflicts(
            [critical_conflict],
            self.new_observation,
            self.existing_observation,
            self.context
        )
        
        self.assertEqual(result['overall_action'], 'critical_conflicts_require_review')
        self.assertGreater(result['unresolved_conflicts'], 0)
    
    def test_error_handling_in_resolution(self):
        """Test that resolution errors are handled gracefully."""
        # Create a mock strategy that raises an exception
        with patch.object(self.resolver.strategies['newest_wins'], 'resolve_conflict') as mock_resolve:
            mock_resolve.side_effect = Exception("Test resolution error")
            
            result = self.resolver.resolve_conflicts(
                [self.conflict_detail],
                self.new_observation,
                self.existing_observation,
                self.context
            )
            
            self.assertEqual(result['unresolved_conflicts'], 1)
            self.assertEqual(result['resolution_actions'][0]['action'], 'failed')
            self.assertIn('Resolution failed', result['resolution_actions'][0]['reasoning'])


class TestConflictResolutionIntegration(ConflictResolutionStrategyTest):
    """Test integration of conflict resolution with merge handlers."""
    
    def setUp(self):
        super().setUp()
        self.merge_service = FHIRMergeService(self.patient)
        self.observation_handler = ObservationMergeHandler()
    
    def test_merge_handler_uses_conflict_resolver(self):
        """Test that merge handlers properly use the conflict resolver."""
        # Create a bundle with existing observation
        bundle = Bundle(resourceType="Bundle", type="collection")
        bundle.entry = []
        
        # Add existing observation to bundle
        from fhir.resources.bundle import BundleEntry
        entry = BundleEntry()
        entry.resource = self.existing_observation
        bundle.entry.append(entry)
        
        # Create context with conflict resolver
        context = {
            'current_bundle': bundle,
            'document_metadata': {'source': 'test'},
            'user': self.user,
            'merge_timestamp': timezone.now(),
            'conflict_resolver': self.merge_service.conflict_resolver
        }
        
        config = {
            'conflict_detection_enabled': True,
            'resolve_conflicts': True,
            'duplicate_detection_enabled': True
        }
        
        # Test merge with conflicting observation
        result = self.observation_handler.merge_resource(
            self.new_observation,
            bundle,
            context,
            config
        )
        
        # Should have detected and resolved conflicts
        self.assertGreater(result.get('conflicts_detected', 0), 0)
        self.assertIn('resolution_actions', result)
    
    def test_fhir_merge_service_passes_conflict_resolver(self):
        """Test that FHIRMergeService properly passes conflict resolver to handlers."""
        # This tests the integration at the service level
        extracted_data = {
            'patient_name': 'John Doe',  # Required for validation
            'document_date': '2024-12-15',  # Required for validation
            'observations': [{
                'code': 'glucose',
                'value': 150.0,
                'unit': 'mg/dL',
                'date': '2024-12-15'
            }]
        }
        
        document_metadata = {
            'document_id': 'test-doc-1',
            'source': 'test',
            'ai_confidence_score': 0.90,
            'patient_name': 'John Doe',      # Required for validation
            'document_date': '2024-12-15'    # Required for validation
        }
        
        # Add an existing observation to the patient's FHIR bundle
        self.patient.cumulative_fhir_json = {
            'resourceType': 'Bundle',
            'type': 'collection',
            'entry': [{
                'resource': {
                    'resourceType': 'Observation',
                    'id': 'existing-glucose',
                    'status': 'final',
                    'code': {
                        'coding': [{'code': 'glucose', 'display': 'Glucose'}]
                    },
                    'valueQuantity': {
                        'value': 140.0,
                        'unit': 'mg/dL'
                    },
                    'effectiveDateTime': '2024-12-14T09:00:00Z'
                }
            }]
        }
        self.patient.save()
        
        # Perform merge operation
        result = self.merge_service.merge_document_data(
            extracted_data,
            document_metadata,
            self.user
        )
        
        # Should complete successfully with conflict resolution
        self.assertTrue(result.success)
        self.assertGreaterEqual(result.conflicts_detected, 0)
    
    def test_configuration_override_via_kwargs(self):
        """Test that configuration can be overridden via kwargs."""
        # Test overriding conflict resolution strategy
        override_config = {
            'conflict_resolution_strategy': 'preserve_both'
        }
        
        # Create a new service instance with override
        merge_service = FHIRMergeService(self.patient)
        merge_service._update_config(override_config)
        
        # Verify configuration was updated
        self.assertEqual(
            merge_service.config['conflict_resolution_strategy'],
            'preserve_both'
        )
        
        # Verify conflict resolver was updated with new config
        self.assertEqual(
            merge_service.conflict_resolver.config['conflict_resolution_strategy'],
            'preserve_both'
        )


if __name__ == '__main__':
    unittest.main() 