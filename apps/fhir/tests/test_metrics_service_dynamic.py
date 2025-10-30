"""
Tests for FHIRMetricsService dynamic resource detection (Task 40.8)

Verifies that FHIRMetricsService can:
1. Dynamically detect resource types from FHIRProcessor
2. Validate alignment between metrics and processor
3. Fall back to defaults when processor not provided
"""

import unittest
from unittest.mock import Mock
from apps.fhir.services.metrics_service import FHIRMetricsService
from apps.fhir.services.fhir_processor import FHIRProcessor


class FHIRMetricsServiceDynamicTests(unittest.TestCase):
    """Test FHIRMetricsService with dynamic resource detection."""
    
    def test_initialization_with_processor(self):
        """Test that metrics service gets types from processor."""
        processor = FHIRProcessor()
        metrics_service = FHIRMetricsService(fhir_processor=processor)
        
        # Should have resource types from processor
        self.assertIsNotNone(metrics_service.supported_resource_types)
        self.assertEqual(len(metrics_service.supported_resource_types), 8)
        
        # Verify it matches processor
        processor_types = processor.get_supported_resource_types()
        self.assertEqual(metrics_service.supported_resource_types, processor_types)
    
    def test_initialization_without_processor(self):
        """Test backward compatibility when no processor provided."""
        metrics_service = FHIRMetricsService()
        
        # Should use default list
        self.assertIsNotNone(metrics_service.supported_resource_types)
        self.assertGreater(len(metrics_service.supported_resource_types), 0)
        
        # Should include expected types
        expected_types = ['Condition', 'MedicationStatement', 'Observation']
        for resource_type in expected_types:
            self.assertIn(resource_type, metrics_service.supported_resource_types)
    
    def test_validate_against_processor_perfect_match(self):
        """Test validation when metrics and processor are perfectly aligned."""
        processor = FHIRProcessor()
        metrics_service = FHIRMetricsService(fhir_processor=processor)
        
        validation = metrics_service.validate_against_processor(processor)
        
        # Should be valid
        self.assertTrue(validation['valid'])
        self.assertEqual(len(validation['missing_in_processor']), 0)
        self.assertEqual(len(validation['missing_in_metrics']), 0)
        self.assertEqual(len(validation['warnings']), 0)
        
        # Lists should match
        self.assertEqual(validation['metrics_types'], validation['processor_types'])
    
    def test_validate_against_processor_with_mismatch(self):
        """Test validation when metrics has types not in processor."""
        # Create processor
        processor = FHIRProcessor()
        
        # Create metrics with extra types
        metrics_service = FHIRMetricsService()  # Uses defaults which include AllergyIntolerance, CarePlan, Organization
        
        validation = metrics_service.validate_against_processor(processor)
        
        # Should detect mismatch
        self.assertFalse(validation['valid'])
        
        # Should have types in metrics but not in processor
        self.assertGreater(len(validation['missing_in_processor']), 0)
        self.assertIn('AllergyIntolerance', validation['missing_in_processor'])
        self.assertIn('CarePlan', validation['missing_in_processor'])
        self.assertIn('Organization', validation['missing_in_processor'])
        
        # Should have warnings
        self.assertGreater(len(validation['warnings']), 0)
    
    def test_validate_processor_types_subset_of_defaults(self):
        """Test that current processor types are a subset of default types."""
        processor = FHIRProcessor()
        metrics_service = FHIRMetricsService()
        
        processor_types = set(processor.get_supported_resource_types())
        default_types = set(metrics_service.supported_resource_types)
        
        # All processor types should be in defaults
        self.assertTrue(processor_types.issubset(default_types))
    
    def test_dynamic_initialization_matches_processor(self):
        """Test that dynamic initialization exactly matches processor capabilities."""
        processor = FHIRProcessor()
        metrics_service = FHIRMetricsService(fhir_processor=processor)
        
        # Get types from both
        metrics_types = set(metrics_service.supported_resource_types)
        processor_types = set(processor.get_supported_resource_types())
        
        # Should be identical
        self.assertEqual(metrics_types, processor_types)
        
        # Should have exactly 8 types (Phase 1 count)
        self.assertEqual(len(metrics_types), 8)
    
    def test_error_handling_in_dynamic_detection(self):
        """Test that errors in processor don't crash metrics service."""
        # Create mock processor that raises error
        mock_processor = Mock()
        mock_processor.get_supported_resource_types.side_effect = Exception("Test error")
        
        # Should not crash, should fall back to defaults
        metrics_service = FHIRMetricsService(fhir_processor=mock_processor)
        
        # Should have default types
        self.assertIsNotNone(metrics_service.supported_resource_types)
        self.assertGreater(len(metrics_service.supported_resource_types), 0)


if __name__ == '__main__':
    unittest.main()

