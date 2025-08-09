"""
Tests for FHIR Code System Mapping and Normalization

This module contains comprehensive tests for the code system mapping functionality
including detection, normalization, fuzzy matching, and confidence scoring.
"""

import unittest
from unittest.mock import patch, MagicMock
from django.test import TestCase

from .code_systems import (
    CodeSystemMapper,
    CodeSystemDetector,
    FuzzyCodeMatcher,
    CodeSystemRegistry,
    CodeMapping,
    NormalizedCode,
    CodeSystemInfo,
    default_code_mapper
)


class CodeSystemRegistryTest(TestCase):
    """Test the CodeSystemRegistry functionality."""
    
    def test_get_system_info(self):
        """Test retrieving system information."""
        loinc_info = CodeSystemRegistry.get_system_info('LOINC')
        self.assertIsNotNone(loinc_info)
        self.assertEqual(loinc_info.name, 'LOINC')
        self.assertEqual(loinc_info.uri, 'http://loinc.org')
        
        # Test case insensitivity
        snomed_info = CodeSystemRegistry.get_system_info('snomed')
        self.assertIsNotNone(snomed_info)
        self.assertEqual(snomed_info.name, 'SNOMED CT')
    
    def test_get_unknown_system(self):
        """Test retrieving unknown system returns None."""
        unknown = CodeSystemRegistry.get_system_info('UNKNOWN_SYSTEM')
        self.assertIsNone(unknown)
    
    def test_get_all_systems(self):
        """Test getting all supported systems."""
        systems = CodeSystemRegistry.get_all_systems()
        self.assertIn('LOINC', systems)
        self.assertIn('SNOMED', systems)
        self.assertIn('ICD-10-CM', systems)
        self.assertIn('CPT', systems)
    
    def test_validate_code_format(self):
        """Test code format validation."""
        # LOINC codes
        self.assertTrue(CodeSystemRegistry.validate_code_format('8480-6', 'LOINC'))
        self.assertTrue(CodeSystemRegistry.validate_code_format('2093-3', 'LOINC'))
        self.assertFalse(CodeSystemRegistry.validate_code_format('invalid', 'LOINC'))
        
        # ICD-10-CM codes
        self.assertTrue(CodeSystemRegistry.validate_code_format('E11.9', 'ICD-10-CM'))
        self.assertTrue(CodeSystemRegistry.validate_code_format('Z51.11', 'ICD-10-CM'))
        self.assertFalse(CodeSystemRegistry.validate_code_format('999.99', 'ICD-10-CM'))
        
        # SNOMED codes
        self.assertTrue(CodeSystemRegistry.validate_code_format('386661006', 'SNOMED'))
        self.assertTrue(CodeSystemRegistry.validate_code_format('44054006', 'SNOMED'))
        self.assertFalse(CodeSystemRegistry.validate_code_format('123', 'SNOMED'))  # Too short


class CodeSystemDetectorTest(TestCase):
    """Test the CodeSystemDetector functionality."""
    
    def test_detect_loinc_codes(self):
        """Test LOINC code detection."""
        system, confidence = CodeSystemDetector.detect_system('8480-6')
        self.assertEqual(system, 'LOINC')
        self.assertGreater(confidence, 0.7)
        
        system, confidence = CodeSystemDetector.detect_system('2093-3', context='lab')
        self.assertEqual(system, 'LOINC')
        self.assertGreater(confidence, 0.8)  # Higher confidence with context
    
    def test_detect_icd10_codes(self):
        """Test ICD-10 code detection."""
        system, confidence = CodeSystemDetector.detect_system('E11.9')
        self.assertEqual(system, 'ICD-10-CM')
        self.assertGreater(confidence, 0.7)
        
        system, confidence = CodeSystemDetector.detect_system('I10', context='diagnosis')
        self.assertEqual(system, 'ICD-10-CM')  # I10 matches ICD-10-CM pattern
        self.assertGreater(confidence, 0.8)
    
    def test_detect_snomed_codes(self):
        """Test SNOMED code detection."""
        system, confidence = CodeSystemDetector.detect_system('386661006')
        self.assertEqual(system, 'SNOMED')
        self.assertGreater(confidence, 0.7)
        
        # Longer codes get higher confidence
        system, confidence = CodeSystemDetector.detect_system('12345678901')
        self.assertEqual(system, 'SNOMED')
        self.assertGreater(confidence, 0.8)
    
    def test_detect_cpt_codes(self):
        """Test CPT code detection."""
        system, confidence = CodeSystemDetector.detect_system('99213')
        self.assertEqual(system, 'CPT')
        self.assertGreater(confidence, 0.7)
        
        system, confidence = CodeSystemDetector.detect_system('80053', context='procedure')
        self.assertEqual(system, 'CPT')
        self.assertGreater(confidence, 0.8)
    
    def test_detect_unknown_codes(self):
        """Test unknown code detection."""
        system, confidence = CodeSystemDetector.detect_system('!!!@#$%^&*()')
        self.assertEqual(system, 'UNKNOWN')
        self.assertEqual(confidence, 0.0)
        
        system, confidence = CodeSystemDetector.detect_system('')
        self.assertEqual(system, 'UNKNOWN')
        self.assertEqual(confidence, 0.0)
    
    def test_context_boost(self):
        """Test context-based confidence boost."""
        # Lab context should boost LOINC
        _, conf_no_context = CodeSystemDetector.detect_system('8480-6')
        _, conf_with_context = CodeSystemDetector.detect_system('8480-6', context='laboratory')
        self.assertGreater(conf_with_context, conf_no_context)
        
        # Diagnosis context should boost ICD
        _, conf_no_context = CodeSystemDetector.detect_system('E11.9')
        _, conf_with_context = CodeSystemDetector.detect_system('E11.9', context='diagnosis')
        self.assertGreater(conf_with_context, conf_no_context)


class FuzzyCodeMatcherTest(TestCase):
    """Test the FuzzyCodeMatcher functionality."""
    
    def setUp(self):
        self.matcher = FuzzyCodeMatcher(similarity_threshold=0.8)
    
    def test_find_similar_codes(self):
        """Test finding similar codes."""
        target = '8480-6'
        candidates = ['8480-6', '8481-6', '8462-4', 'completely-different']
        
        results = self.matcher.find_similar_codes(target, candidates)
        
        # Should find exact match first
        self.assertEqual(results[0][0], '8480-6')
        self.assertEqual(results[0][1], 1.0)
        
        # Should find similar codes
        self.assertGreater(len(results), 1)
        for code, similarity in results:
            self.assertGreaterEqual(similarity, 0.8)
    
    def test_structural_similarity(self):
        """Test structural similarity calculation."""
        # Codes with same structure should be similar
        similarity = self.matcher._calculate_structure_similarity('8480-6', '8481-6')
        self.assertGreater(similarity, 0.8)
        
        # Codes with different structure should be less similar
        similarity = self.matcher._calculate_structure_similarity('8480-6', 'E11.9')
        self.assertLess(similarity, 0.8)
    
    def test_normalization(self):
        """Test code normalization for comparison."""
        normalized = self.matcher._normalize_for_comparison('E11.9')
        self.assertEqual(normalized, 'e119')
        
        normalized = self.matcher._normalize_for_comparison('8480-6')
        self.assertEqual(normalized, '84806')
    
    def test_empty_inputs(self):
        """Test handling of empty inputs."""
        results = self.matcher.find_similar_codes('', ['code1', 'code2'])
        self.assertEqual(len(results), 0)
        
        results = self.matcher.find_similar_codes('code', [])
        self.assertEqual(len(results), 0)


class CodeSystemMapperTest(TestCase):
    """Test the CodeSystemMapper functionality."""
    
    def setUp(self):
        self.mapper = CodeSystemMapper(enable_caching=False)  # Disable caching for tests
    
    def test_normalize_code(self):
        """Test code normalization."""
        # Test LOINC code
        normalized = self.mapper.normalize_code('8480-6', context='lab')
        self.assertEqual(normalized.code, '8480-6')
        self.assertEqual(normalized.system, 'LOINC')
        self.assertEqual(normalized.system_uri, 'http://loinc.org')
        self.assertGreater(normalized.confidence, 0.8)
        
        # Test ICD-10 code
        normalized = self.mapper.normalize_code('E11.9', context='diagnosis')
        self.assertEqual(normalized.code, 'E11.9')
        self.assertEqual(normalized.system, 'ICD-10-CM')
        self.assertGreater(normalized.confidence, 0.8)
    
    def test_normalize_code_with_known_system(self):
        """Test normalization with pre-specified system."""
        normalized = self.mapper.normalize_code('8480-6', system='LOINC')
        self.assertEqual(normalized.system, 'LOINC')
        self.assertEqual(normalized.confidence, 1.0)
    
    def test_normalize_invalid_code(self):
        """Test normalization of invalid codes."""
        normalized = self.mapper.normalize_code('INVALID_CODE')
        self.assertEqual(normalized.system, 'UNKNOWN')
        self.assertEqual(normalized.confidence, 0.0)
    
    def test_clean_code(self):
        """Test code cleaning functionality."""
        cleaned = self.mapper._clean_code('  E11.9  ')
        self.assertEqual(cleaned, 'E11.9')
        
        cleaned = self.mapper._clean_code('e11.9')
        self.assertEqual(cleaned, 'E11.9')  # Should be uppercase for ICD
    
    def test_find_equivalent_codes(self):
        """Test finding equivalent codes."""
        # This test depends on predefined mappings
        mappings = self.mapper.find_equivalent_codes('E11.9', 'ICD-10-CM')
        
        # Should be able to find mappings (may be empty in test environment)
        self.assertIsInstance(mappings, list)
        
        for mapping in mappings:
            self.assertIsInstance(mapping, CodeMapping)
            self.assertEqual(mapping.source_code, 'E11.9')
            self.assertEqual(mapping.source_system, 'ICD-10-CM')
    
    def test_get_system_uri(self):
        """Test getting system URIs."""
        uri = self.mapper.get_system_uri('LOINC')
        self.assertEqual(uri, 'http://loinc.org')
        
        uri = self.mapper.get_system_uri('UNKNOWN')
        self.assertEqual(uri, 'http://unknown.org')
    
    def test_mapping_statistics(self):
        """Test getting mapping statistics."""
        stats = self.mapper.get_mapping_statistics()
        
        self.assertIn('total_cached_mappings', stats)
        self.assertIn('supported_systems', stats)
        self.assertIn('predefined_mappings', stats)
        self.assertIn('cache_enabled', stats)
        
        self.assertEqual(stats['cache_enabled'], False)
        self.assertGreater(stats['supported_systems'], 0)
    
    def test_error_handling(self):
        """Test error handling in normalization."""
        # Empty code should raise ValueError
        with self.assertRaises(ValueError):
            self.mapper.normalize_code('')
        
        with self.assertRaises(ValueError):
            self.mapper.normalize_code(None)


class CodeMappingTest(TestCase):
    """Test the CodeMapping data structure."""
    
    def test_code_mapping_creation(self):
        """Test creating code mappings."""
        mapping = CodeMapping(
            source_code='E11.9',
            source_system='ICD-10-CM',
            target_code='44054006',
            target_system='SNOMED',
            confidence=0.95,
            mapping_type='equivalent',
            description='Type 2 diabetes mellitus'
        )
        
        self.assertEqual(mapping.source_code, 'E11.9')
        self.assertEqual(mapping.target_code, '44054006')
        self.assertEqual(mapping.confidence, 0.95)
        self.assertEqual(mapping.mapping_type, 'equivalent')


class NormalizedCodeTest(TestCase):
    """Test the NormalizedCode data structure."""
    
    def test_normalized_code_creation(self):
        """Test creating normalized codes."""
        code = NormalizedCode(
            code='8480-6',
            system='LOINC',
            system_uri='http://loinc.org',
            display='Systolic blood pressure',
            original_code='8480-6',
            original_system='LOINC',
            confidence=1.0,
            normalization_notes=['No changes needed']
        )
        
        self.assertEqual(code.code, '8480-6')
        self.assertEqual(code.system, 'LOINC')
        self.assertEqual(code.confidence, 1.0)
        self.assertEqual(len(code.normalization_notes), 1)


class IntegrationTest(TestCase):
    """Integration tests for code system mapping."""
    
    def test_default_mapper_instance(self):
        """Test the default mapper instance."""
        self.assertIsInstance(default_code_mapper, CodeSystemMapper)
        
        # Test basic functionality
        normalized = default_code_mapper.normalize_code('8480-6')
        self.assertEqual(normalized.system, 'LOINC')
    
    def test_end_to_end_normalization(self):
        """Test complete normalization workflow."""
        # Start with a raw code
        raw_code = '  8480-6  '
        
        # Normalize it
        normalized = default_code_mapper.normalize_code(raw_code, context='laboratory')
        
        # Verify results
        self.assertEqual(normalized.code, '8480-6')
        self.assertEqual(normalized.system, 'LOINC')
        self.assertEqual(normalized.original_code, raw_code)
        self.assertGreater(normalized.confidence, 0.8)
        self.assertGreater(len(normalized.normalization_notes), 0)
    
    def test_mapping_workflow(self):
        """Test code mapping workflow."""
        # Find equivalent codes
        mappings = default_code_mapper.find_equivalent_codes('E11.9', 'ICD-10-CM')
        
        # Verify structure (even if no mappings found)
        self.assertIsInstance(mappings, list)
        
        for mapping in mappings:
            self.assertIsInstance(mapping, CodeMapping)
            self.assertGreaterEqual(mapping.confidence, 0.0)
            self.assertLessEqual(mapping.confidence, 1.0)
    
    def test_performance(self):
        """Test basic performance characteristics."""
        import time
        
        # Test detection performance
        start = time.time()
        for _ in range(100):
            CodeSystemDetector.detect_system('8480-6')
        detection_time = time.time() - start
        
        # Should be fast (less than 1 second for 100 detections)
        self.assertLess(detection_time, 1.0)
        
        # Test normalization performance
        start = time.time()
        for _ in range(100):
            default_code_mapper.normalize_code('8480-6')
        normalization_time = time.time() - start
        
        # Should be reasonably fast
        self.assertLess(normalization_time, 5.0)


class ErrorHandlingTest(TestCase):
    """Test error handling in code system mapping."""
    
    def test_invalid_inputs(self):
        """Test handling of invalid inputs."""
        mapper = CodeSystemMapper()
        
        # Invalid code should raise ValueError
        with self.assertRaises(ValueError):
            mapper.normalize_code('')
        
        with self.assertRaises(ValueError):
            mapper.normalize_code(None)
    
    def test_malformed_codes(self):
        """Test handling of malformed codes."""
        mapper = CodeSystemMapper()
        
        # Malformed but non-empty codes should not crash
        normalized = mapper.normalize_code('!!!@@@###')
        self.assertEqual(normalized.system, 'UNKNOWN')
        self.assertEqual(normalized.confidence, 0.0)
    
    def test_unknown_systems(self):
        """Test handling of unknown systems."""
        mapper = CodeSystemMapper()
        
        # Unknown system should be handled gracefully
        normalized = mapper.normalize_code('TEST123', system='UNKNOWN_SYSTEM')
        self.assertEqual(normalized.system, 'UNKNOWN')
        self.assertEqual(normalized.confidence, 0.0)


if __name__ == '__main__':
    unittest.main()
