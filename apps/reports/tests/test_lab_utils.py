"""
Unit tests for laboratory observation utilities.
"""

from datetime import datetime
from django.test import TestCase
from apps.reports.utils.lab_utils import (
    get_lab_category,
    parse_reference_range,
    detect_abnormal_result,
    extract_observation_data,
    group_lab_results,
    get_abnormal_results_summary,
    LOINC_CATEGORIES
)


class LabCategoryTests(TestCase):
    """Test LOINC category mapping."""
    
    def test_known_loinc_code(self):
        """Test category lookup for known LOINC codes."""
        self.assertEqual(get_lab_category('718-7'), 'Hematology')
        self.assertEqual(get_lab_category('2345-7'), 'Chemistry')
        self.assertEqual(get_lab_category('2093-3'), 'Lipid Panel')
    
    def test_unknown_loinc_code(self):
        """Test category lookup for unknown LOINC codes."""
        self.assertEqual(get_lab_category('99999-9'), 'Other')
        self.assertEqual(get_lab_category(''), 'Other')
    
    def test_loinc_categories_completeness(self):
        """Verify LOINC_CATEGORIES dictionary is populated."""
        self.assertGreater(len(LOINC_CATEGORIES), 0)
        self.assertIn('718-7', LOINC_CATEGORIES)  # Hemoglobin


class ReferenceRangeParsingTests(TestCase):
    """Test reference range extraction."""
    
    def test_parse_range_with_low_and_high(self):
        """Test parsing reference range with both low and high values."""
        observation = {
            'referenceRange': [{
                'low': {'value': 12.0, 'unit': 'g/dL'},
                'high': {'value': 16.0, 'unit': 'g/dL'}
            }]
        }
        result = parse_reference_range(observation)
        self.assertEqual(result, '12.0-16.0 g/dL')
    
    def test_parse_range_with_only_low(self):
        """Test parsing reference range with only low value."""
        observation = {
            'referenceRange': [{
                'low': {'value': 5.0, 'unit': 'mmol/L'}
            }]
        }
        result = parse_reference_range(observation)
        self.assertEqual(result, '>5.0 mmol/L')
    
    def test_parse_range_with_only_high(self):
        """Test parsing reference range with only high value."""
        observation = {
            'referenceRange': [{
                'high': {'value': 100.0, 'unit': 'mg/dL'}
            }]
        }
        result = parse_reference_range(observation)
        self.assertEqual(result, '<100.0 mg/dL')
    
    def test_parse_range_with_text(self):
        """Test parsing reference range from text."""
        observation = {
            'referenceRange': [{
                'text': 'Negative'
            }]
        }
        result = parse_reference_range(observation)
        self.assertEqual(result, 'Negative')
    
    def test_parse_range_missing(self):
        """Test parsing observation with no reference range."""
        observation = {}
        result = parse_reference_range(observation)
        self.assertIsNone(result)
    
    def test_parse_range_empty_array(self):
        """Test parsing observation with empty reference range array."""
        observation = {'referenceRange': []}
        result = parse_reference_range(observation)
        self.assertIsNone(result)


class AbnormalResultDetectionTests(TestCase):
    """Test abnormal result detection logic."""
    
    def test_detect_normal_from_interpretation(self):
        """Test detection of normal result from interpretation code."""
        observation = {
            'interpretation': [{
                'coding': [{
                    'code': 'N'
                }]
            }]
        }
        result = detect_abnormal_result(observation)
        self.assertEqual(result, 'normal')
    
    def test_detect_low_from_interpretation(self):
        """Test detection of low result from interpretation code."""
        observation = {
            'interpretation': [{
                'coding': [{
                    'code': 'L'
                }]
            }]
        }
        result = detect_abnormal_result(observation)
        self.assertEqual(result, 'low')
    
    def test_detect_high_from_interpretation(self):
        """Test detection of high result from interpretation code."""
        observation = {
            'interpretation': [{
                'coding': [{
                    'code': 'H'
                }]
            }]
        }
        result = detect_abnormal_result(observation)
        self.assertEqual(result, 'high')
    
    def test_detect_critical_from_interpretation(self):
        """Test detection of critical result from interpretation code."""
        observation = {
            'interpretation': [{
                'coding': [{
                    'code': 'HH'
                }]
            }]
        }
        result = detect_abnormal_result(observation)
        self.assertEqual(result, 'critical')
    
    def test_detect_low_from_reference_range(self):
        """Test detection of low result from reference range comparison."""
        observation = {
            'valueQuantity': {'value': 10.0},
            'referenceRange': [{
                'low': {'value': 12.0}
            }]
        }
        result = detect_abnormal_result(observation)
        self.assertEqual(result, 'low')
    
    def test_detect_high_from_reference_range(self):
        """Test detection of high result from reference range comparison."""
        observation = {
            'valueQuantity': {'value': 18.0},
            'referenceRange': [{
                'high': {'value': 16.0}
            }]
        }
        result = detect_abnormal_result(observation)
        self.assertEqual(result, 'high')
    
    def test_detect_critical_low(self):
        """Test detection of critically low result (< 80% of lower limit)."""
        observation = {
            'valueQuantity': {'value': 9.0},  # < 12.0 * 0.8
            'referenceRange': [{
                'low': {'value': 12.0}
            }]
        }
        result = detect_abnormal_result(observation)
        self.assertEqual(result, 'critical')
    
    def test_detect_critical_high(self):
        """Test detection of critically high result (> 120% of upper limit)."""
        observation = {
            'valueQuantity': {'value': 20.0},  # > 16.0 * 1.2
            'referenceRange': [{
                'high': {'value': 16.0}
            }]
        }
        result = detect_abnormal_result(observation)
        self.assertEqual(result, 'critical')
    
    def test_detect_normal_within_range(self):
        """Test detection of normal result within reference range."""
        observation = {
            'valueQuantity': {'value': 14.0},
            'referenceRange': [{
                'low': {'value': 12.0},
                'high': {'value': 16.0}
            }]
        }
        result = detect_abnormal_result(observation)
        self.assertEqual(result, 'normal')
    
    def test_detect_default_normal(self):
        """Test default to normal when no interpretation available."""
        observation = {}
        result = detect_abnormal_result(observation)
        self.assertEqual(result, 'normal')


class ObservationDataExtractionTests(TestCase):
    """Test extraction of data from FHIR Observation resources."""
    
    def test_extract_complete_lab_observation(self):
        """Test extraction from complete lab observation with all fields."""
        observation = {
            'id': 'obs-123',
            'resourceType': 'Observation',
            'status': 'final',
            'category': [{
                'coding': [{
                    'system': 'http://terminology.hl7.org/CodeSystem/v2-0074',
                    'code': 'LAB'
                }]
            }],
            'code': {
                'coding': [{
                    'system': 'http://loinc.org',
                    'code': '718-7',
                    'display': 'Hemoglobin'
                }],
                'text': 'Hemoglobin'
            },
            'valueQuantity': {
                'value': 14.5,
                'unit': 'g/dL'
            },
            'effectiveDateTime': '2025-01-15T10:30:00Z',
            'referenceRange': [{
                'low': {'value': 12.0, 'unit': 'g/dL'},
                'high': {'value': 16.0, 'unit': 'g/dL'}
            }],
            'interpretation': [{
                'coding': [{'code': 'N'}]
            }],
            'note': [{
                'text': 'Sample note'
            }]
        }
        
        result = extract_observation_data(observation)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['id'], 'obs-123')
        self.assertEqual(result['test_name'], 'Hemoglobin')
        self.assertEqual(result['loinc_code'], '718-7')
        self.assertEqual(result['value'], 14.5)
        self.assertEqual(result['unit'], 'g/dL')
        self.assertEqual(result['reference_range'], '12.0-16.0 g/dL')
        self.assertEqual(result['interpretation'], 'normal')
        self.assertEqual(result['category'], 'Hematology')
        self.assertIsNotNone(result['date'])
        self.assertEqual(result['notes'], 'Sample note')
        self.assertEqual(result['status'], 'final')
    
    def test_extract_observation_without_loinc(self):
        """Test extraction from observation without LOINC code but with LAB category."""
        observation = {
            'id': 'obs-456',
            'category': [{
                'coding': [{
                    'code': 'laboratory'
                }]
            }],
            'code': {
                'text': 'Custom Lab Test'
            },
            'valueQuantity': {
                'value': 50.0,
                'unit': 'mg/dL'
            },
            'effectiveDateTime': '2025-01-15'
        }
        
        result = extract_observation_data(observation)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['test_name'], 'Custom Lab Test')
        self.assertIsNone(result['loinc_code'])
        self.assertEqual(result['category'], 'Other')
        self.assertEqual(result['value'], 50.0)
    
    def test_skip_non_lab_observation(self):
        """Test that non-laboratory observations are skipped."""
        observation = {
            'id': 'obs-vital',
            'category': [{
                'coding': [{
                    'code': 'vital-signs'
                }]
            }],
            'code': {
                'text': 'Blood Pressure'
            },
            'valueQuantity': {
                'value': 120
            }
        }
        
        result = extract_observation_data(observation)
        self.assertIsNone(result)
    
    def test_skip_observation_without_value(self):
        """Test that observations without values are skipped."""
        observation = {
            'id': 'obs-no-value',
            'category': [{
                'coding': [{'code': 'LAB'}]
            }],
            'code': {
                'text': 'Pending Test'
            }
        }
        
        result = extract_observation_data(observation)
        self.assertIsNone(result)
    
    def test_extract_with_various_date_formats(self):
        """Test date parsing with different formats."""
        # ISO format with Z
        obs1 = {
            'category': [{'coding': [{'code': 'LAB'}]}],
            'code': {'text': 'Test'},
            'valueQuantity': {'value': 10},
            'effectiveDateTime': '2025-01-15T10:30:00Z'
        }
        result1 = extract_observation_data(obs1)
        self.assertIsNotNone(result1['date'])
        
        # Date only format
        obs2 = {
            'category': [{'coding': [{'code': 'LAB'}]}],
            'code': {'text': 'Test'},
            'valueQuantity': {'value': 10},
            'effectiveDateTime': '2025-01-15'
        }
        result2 = extract_observation_data(obs2)
        self.assertIsNotNone(result2['date'])


class GroupLabResultsTests(TestCase):
    """Test grouping of lab results by category."""
    
    def test_group_empty_bundle(self):
        """Test grouping with empty FHIR bundle."""
        bundle = {'entry': []}
        result = group_lab_results(bundle)
        self.assertEqual(result, {})
    
    def test_group_standard_bundle_format(self):
        """Test grouping with standard FHIR Bundle format."""
        bundle = {
            'resourceType': 'Bundle',
            'entry': [
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'category': [{'coding': [{'code': 'LAB'}]}],
                        'code': {
                            'coding': [{
                                'system': 'http://loinc.org',
                                'code': '718-7',
                                'display': 'Hemoglobin'
                            }]
                        },
                        'valueQuantity': {'value': 14.5, 'unit': 'g/dL'},
                        'effectiveDateTime': '2025-01-15'
                    }
                },
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'category': [{'coding': [{'code': 'LAB'}]}],
                        'code': {
                            'coding': [{
                                'system': 'http://loinc.org',
                                'code': '2345-7',
                                'display': 'Glucose'
                            }]
                        },
                        'valueQuantity': {'value': 95.0, 'unit': 'mg/dL'},
                        'effectiveDateTime': '2025-01-15'
                    }
                }
            ]
        }
        
        result = group_lab_results(bundle)
        
        self.assertIn('Hematology', result)
        self.assertIn('Chemistry', result)
        self.assertEqual(len(result['Hematology']), 1)
        self.assertEqual(len(result['Chemistry']), 1)
        self.assertEqual(result['Hematology'][0]['test_name'], 'Hemoglobin')
        self.assertEqual(result['Chemistry'][0]['test_name'], 'Glucose')
    
    def test_group_custom_fhir_resources_format(self):
        """Test grouping with custom fhir_resources array format."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Observation',
                    'category': [{'coding': [{'code': 'LAB'}]}],
                    'code': {
                        'coding': [{
                            'system': 'http://loinc.org',
                            'code': '2093-3'
                        }]
                    },
                    'valueQuantity': {'value': 200.0, 'unit': 'mg/dL'},
                    'effectiveDateTime': '2025-01-15'
                }
            ]
        }
        
        result = group_lab_results(bundle)
        
        self.assertIn('Lipid Panel', result)
        self.assertEqual(len(result['Lipid Panel']), 1)
    
    def test_group_sorts_by_date(self):
        """Test that results within categories are sorted by date (newest first)."""
        bundle = {
            'entry': [
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'category': [{'coding': [{'code': 'LAB'}]}],
                        'code': {'coding': [{'system': 'http://loinc.org', 'code': '718-7'}]},
                        'valueQuantity': {'value': 14.0},
                        'effectiveDateTime': '2025-01-10'
                    }
                },
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'category': [{'coding': [{'code': 'LAB'}]}],
                        'code': {'coding': [{'system': 'http://loinc.org', 'code': '718-7'}]},
                        'valueQuantity': {'value': 15.0},
                        'effectiveDateTime': '2025-01-20'
                    }
                },
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'category': [{'coding': [{'code': 'LAB'}]}],
                        'code': {'coding': [{'system': 'http://loinc.org', 'code': '718-7'}]},
                        'valueQuantity': {'value': 14.5},
                        'effectiveDateTime': '2025-01-15'
                    }
                }
            ]
        }
        
        result = group_lab_results(bundle)
        hematology = result['Hematology']
        
        self.assertEqual(len(hematology), 3)
        # Should be sorted newest first
        self.assertEqual(hematology[0]['value'], 15.0)  # 2025-01-20
        self.assertEqual(hematology[1]['value'], 14.5)  # 2025-01-15
        self.assertEqual(hematology[2]['value'], 14.0)  # 2025-01-10
    
    def test_group_filters_non_lab_observations(self):
        """Test that non-laboratory observations are filtered out."""
        bundle = {
            'entry': [
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'category': [{'coding': [{'code': 'vital-signs'}]}],
                        'code': {'text': 'Blood Pressure'},
                        'valueQuantity': {'value': 120}
                    }
                },
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'category': [{'coding': [{'code': 'LAB'}]}],
                        'code': {'coding': [{'system': 'http://loinc.org', 'code': '718-7'}]},
                        'valueQuantity': {'value': 14.5}
                    }
                }
            ]
        }
        
        result = group_lab_results(bundle)
        
        # Only lab observation should be included
        self.assertEqual(len(result), 1)
        self.assertIn('Hematology', result)


class AbnormalResultsSummaryTests(TestCase):
    """Test abnormal results summary generation."""
    
    def test_summary_with_mixed_results(self):
        """Test summary counts with mix of normal, abnormal, and critical results."""
        grouped_results = {
            'Hematology': [
                {'interpretation': 'normal'},
                {'interpretation': 'low'},
                {'interpretation': 'critical'}
            ],
            'Chemistry': [
                {'interpretation': 'high'},
                {'interpretation': 'normal'}
            ]
        }
        
        summary = get_abnormal_results_summary(grouped_results)
        
        self.assertEqual(summary['normal'], 2)
        self.assertEqual(summary['abnormal'], 2)
        self.assertEqual(summary['critical'], 1)
    
    def test_summary_with_all_normal(self):
        """Test summary with all normal results."""
        grouped_results = {
            'Hematology': [
                {'interpretation': 'normal'},
                {'interpretation': 'normal'}
            ]
        }
        
        summary = get_abnormal_results_summary(grouped_results)
        
        self.assertEqual(summary['normal'], 2)
        self.assertEqual(summary['abnormal'], 0)
        self.assertEqual(summary['critical'], 0)
    
    def test_summary_with_empty_results(self):
        """Test summary with empty results."""
        grouped_results = {}
        
        summary = get_abnormal_results_summary(grouped_results)
        
        self.assertEqual(summary['normal'], 0)
        self.assertEqual(summary['abnormal'], 0)
        self.assertEqual(summary['critical'], 0)

