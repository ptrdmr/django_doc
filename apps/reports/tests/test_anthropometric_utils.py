"""
Unit tests for anthropometric data utilities.
"""

from datetime import datetime, timedelta
from django.test import TestCase
from apps.reports.utils.anthropometric_utils import (
    get_bmi_category,
    get_bmi_display_name,
    calculate_bmi,
    convert_to_metric,
    parse_observation_date,
    extract_weight_observations,
    extract_height_observation,
    calculate_percentage_change,
    is_significant_weight_change,
    calculate_bmi_trends,
    get_weight_summary,
    WEIGHT_LOINC_CODES,
    HEIGHT_LOINC_CODES,
    BMI_CATEGORIES,
)


class BMICategoryTests(TestCase):
    """Test BMI category determination."""
    
    def test_underweight_category(self):
        """Test BMI categorization for underweight."""
        self.assertEqual(get_bmi_category(17.5), 'underweight')
        self.assertEqual(get_bmi_category(18.4), 'underweight')
    
    def test_normal_category(self):
        """Test BMI categorization for normal weight."""
        self.assertEqual(get_bmi_category(18.5), 'normal')
        self.assertEqual(get_bmi_category(22.0), 'normal')
        self.assertEqual(get_bmi_category(24.9), 'normal')
    
    def test_overweight_category(self):
        """Test BMI categorization for overweight."""
        self.assertEqual(get_bmi_category(25.0), 'overweight')
        self.assertEqual(get_bmi_category(27.5), 'overweight')
        self.assertEqual(get_bmi_category(29.9), 'overweight')
    
    def test_obese_categories(self):
        """Test BMI categorization for obesity classes."""
        self.assertEqual(get_bmi_category(30.0), 'obese_class_1')
        self.assertEqual(get_bmi_category(32.5), 'obese_class_1')
        self.assertEqual(get_bmi_category(35.0), 'obese_class_2')
        self.assertEqual(get_bmi_category(37.5), 'obese_class_2')
        self.assertEqual(get_bmi_category(40.0), 'obese_class_3')
        self.assertEqual(get_bmi_category(45.0), 'obese_class_3')
    
    def test_invalid_bmi(self):
        """Test handling of invalid BMI values."""
        self.assertEqual(get_bmi_category(-5.0), 'invalid')
        self.assertEqual(get_bmi_category(-1.0), 'invalid')
    
    def test_bmi_display_names(self):
        """Test display names for BMI categories."""
        self.assertEqual(get_bmi_display_name('normal'), 'Normal Weight')
        self.assertEqual(get_bmi_display_name('overweight'), 'Overweight')
        self.assertEqual(get_bmi_display_name('obese_class_1'), 'Obese (Class I)')
        self.assertEqual(get_bmi_display_name('invalid'), 'Invalid BMI')
        self.assertEqual(get_bmi_display_name('unknown_code'), 'Unknown')


class BMICalculationTests(TestCase):
    """Test BMI calculation logic."""
    
    def test_standard_bmi_calculation(self):
        """Test BMI calculation with standard values."""
        # 70 kg, 1.75 m = BMI 22.9
        bmi = calculate_bmi(70.0, 1.75)
        self.assertAlmostEqual(bmi, 22.9, places=1)
    
    def test_bmi_rounding(self):
        """Test that BMI is rounded to 1 decimal place."""
        bmi = calculate_bmi(80.5, 1.80)
        self.assertEqual(bmi, 24.8)
    
    def test_bmi_with_zero_height(self):
        """Test BMI calculation with zero height."""
        bmi = calculate_bmi(70.0, 0.0)
        self.assertIsNone(bmi)
    
    def test_bmi_with_zero_weight(self):
        """Test BMI calculation with zero weight."""
        bmi = calculate_bmi(0.0, 1.75)
        self.assertIsNone(bmi)
    
    def test_bmi_with_negative_values(self):
        """Test BMI calculation with negative values."""
        bmi1 = calculate_bmi(-70.0, 1.75)
        bmi2 = calculate_bmi(70.0, -1.75)
        self.assertIsNone(bmi1)
        self.assertIsNone(bmi2)


class MetricConversionTests(TestCase):
    """Test unit conversion to metric."""
    
    def test_weight_conversion_kg(self):
        """Test weight conversion from kg (no conversion)."""
        self.assertEqual(convert_to_metric(70.0, 'kg', 'weight'), 70.0)
        self.assertEqual(convert_to_metric(70.0, 'kilograms', 'weight'), 70.0)
    
    def test_weight_conversion_lbs(self):
        """Test weight conversion from pounds to kg."""
        result = convert_to_metric(154.0, 'lb', 'weight')
        self.assertAlmostEqual(result, 69.85, places=1)
        
        result = convert_to_metric(154.0, 'pounds', 'weight')
        self.assertAlmostEqual(result, 69.85, places=1)
    
    def test_weight_conversion_grams(self):
        """Test weight conversion from grams to kg."""
        result = convert_to_metric(70000.0, 'g', 'weight')
        self.assertEqual(result, 70.0)
    
    def test_height_conversion_meters(self):
        """Test height conversion from meters (no conversion)."""
        self.assertEqual(convert_to_metric(1.75, 'm', 'height'), 1.75)
        self.assertEqual(convert_to_metric(1.75, 'meters', 'height'), 1.75)
    
    def test_height_conversion_cm(self):
        """Test height conversion from cm to meters."""
        result = convert_to_metric(175.0, 'cm', 'height')
        self.assertEqual(result, 1.75)
    
    def test_height_conversion_inches(self):
        """Test height conversion from inches to meters."""
        result = convert_to_metric(68.9, 'in', 'height')
        self.assertAlmostEqual(result, 1.75, places=2)
    
    def test_height_conversion_feet(self):
        """Test height conversion from feet to meters."""
        result = convert_to_metric(5.74, 'ft', 'height')
        self.assertAlmostEqual(result, 1.75, places=2)
    
    def test_unknown_unit(self):
        """Test handling of unknown units."""
        result = convert_to_metric(100.0, 'unknown', 'weight')
        self.assertIsNone(result)


class DateParsingTests(TestCase):
    """Test observation date parsing."""
    
    def test_parse_effective_datetime(self):
        """Test parsing effectiveDateTime field."""
        observation = {
            'effectiveDateTime': '2024-01-15T10:30:00'
        }
        result = parse_observation_date(observation)
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2024)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 15)
    
    def test_parse_issued_field(self):
        """Test parsing issued field."""
        observation = {
            'issued': '2024-02-20T14:45:00'
        }
        result = parse_observation_date(observation)
        self.assertIsNotNone(result)
    
    def test_parse_date_only(self):
        """Test parsing date without time."""
        observation = {
            'effectiveDateTime': '2024-03-10'
        }
        result = parse_observation_date(observation)
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2024)
        self.assertEqual(result.month, 3)
        self.assertEqual(result.day, 10)
    
    def test_parse_missing_date(self):
        """Test handling observation with no date."""
        observation = {}
        result = parse_observation_date(observation)
        self.assertIsNone(result)


class WeightExtractionTests(TestCase):
    """Test weight observation extraction."""
    
    def test_extract_single_weight(self):
        """Test extraction of single weight observation."""
        fhir_bundle = {
            'entry': [{
                'resource': {
                    'resourceType': 'Observation',
                    'id': 'weight-1',
                    'code': {
                        'coding': [{'code': '29463-7', 'display': 'Body weight'}]
                    },
                    'valueQuantity': {
                        'value': 70.0,
                        'unit': 'kg'
                    },
                    'effectiveDateTime': '2024-01-15T10:00:00'
                }
            }]
        }
        
        results = extract_weight_observations(fhir_bundle)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['weight_kg'], 70.0)
        self.assertEqual(results[0]['observation_id'], 'weight-1')
    
    def test_extract_multiple_weights(self):
        """Test extraction of multiple weight observations."""
        fhir_bundle = {
            'entry': [
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'id': 'weight-1',
                        'code': {
                            'coding': [{'code': '29463-7'}]
                        },
                        'valueQuantity': {
                            'value': 70.0,
                            'unit': 'kg'
                        },
                        'effectiveDateTime': '2024-01-15'
                    }
                },
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'id': 'weight-2',
                        'code': {
                            'coding': [{'code': '29463-7'}]
                        },
                        'valueQuantity': {
                            'value': 68.5,
                            'unit': 'kg'
                        },
                        'effectiveDateTime': '2024-02-15'
                    }
                }
            ]
        }
        
        results = extract_weight_observations(fhir_bundle)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['weight_kg'], 70.0)
        self.assertEqual(results[1]['weight_kg'], 68.5)
    
    def test_extract_weight_in_pounds(self):
        """Test extraction and conversion of weight in pounds."""
        fhir_bundle = {
            'entry': [{
                'resource': {
                    'resourceType': 'Observation',
                    'code': {
                        'coding': [{'code': '29463-7'}]
                    },
                    'valueQuantity': {
                        'value': 154.0,
                        'unit': 'lb'
                    },
                    'effectiveDateTime': '2024-01-15'
                }
            }]
        }
        
        results = extract_weight_observations(fhir_bundle)
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0]['weight_kg'], 69.9, places=0)
    
    def test_skip_non_observation_resources(self):
        """Test that non-Observation resources are skipped."""
        fhir_bundle = {
            'entry': [
                {
                    'resource': {
                        'resourceType': 'Patient',
                        'id': 'patient-1'
                    }
                },
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'code': {
                            'coding': [{'code': '29463-7'}]
                        },
                        'valueQuantity': {
                            'value': 70.0,
                            'unit': 'kg'
                        }
                    }
                }
            ]
        }
        
        results = extract_weight_observations(fhir_bundle)
        self.assertEqual(len(results), 1)
    
    def test_skip_non_weight_observations(self):
        """Test that non-weight observations are skipped."""
        fhir_bundle = {
            'entry': [
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'code': {
                            'coding': [{'code': '8310-5', 'display': 'Temperature'}]
                        },
                        'valueQuantity': {
                            'value': 98.6,
                            'unit': 'degF'
                        }
                    }
                }
            ]
        }
        
        results = extract_weight_observations(fhir_bundle)
        self.assertEqual(len(results), 0)


class HeightExtractionTests(TestCase):
    """Test height observation extraction."""
    
    def test_extract_height_in_meters(self):
        """Test extraction of height in meters."""
        fhir_bundle = {
            'entry': [{
                'resource': {
                    'resourceType': 'Observation',
                    'code': {
                        'coding': [{'code': '8302-2', 'display': 'Body height'}]
                    },
                    'valueQuantity': {
                        'value': 1.75,
                        'unit': 'm'
                    },
                    'effectiveDateTime': '2024-01-15'
                }
            }]
        }
        
        result = extract_height_observation(fhir_bundle)
        self.assertAlmostEqual(result, 1.75, places=2)
    
    def test_extract_height_in_cm(self):
        """Test extraction and conversion of height in cm."""
        fhir_bundle = {
            'entry': [{
                'resource': {
                    'resourceType': 'Observation',
                    'code': {
                        'coding': [{'code': '8302-2'}]
                    },
                    'valueQuantity': {
                        'value': 175.0,
                        'unit': 'cm'
                    },
                    'effectiveDateTime': '2024-01-15'
                }
            }]
        }
        
        result = extract_height_observation(fhir_bundle)
        self.assertAlmostEqual(result, 1.75, places=2)
    
    def test_extract_most_recent_height(self):
        """Test that most recent height is returned when multiple exist."""
        fhir_bundle = {
            'entry': [
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'code': {
                            'coding': [{'code': '8302-2'}]
                        },
                        'valueQuantity': {
                            'value': 175.0,
                            'unit': 'cm'
                        },
                        'effectiveDateTime': '2023-01-15'
                    }
                },
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'code': {
                            'coding': [{'code': '8302-2'}]
                        },
                        'valueQuantity': {
                            'value': 176.0,
                            'unit': 'cm'
                        },
                        'effectiveDateTime': '2024-01-15'
                    }
                }
            ]
        }
        
        result = extract_height_observation(fhir_bundle)
        self.assertAlmostEqual(result, 1.76, places=2)
    
    def test_no_height_found(self):
        """Test handling when no height observation exists."""
        fhir_bundle = {'entry': []}
        result = extract_height_observation(fhir_bundle)
        self.assertIsNone(result)


class PercentageChangeTests(TestCase):
    """Test percentage change calculation."""
    
    def test_positive_percentage_change(self):
        """Test calculation of positive percentage change."""
        result = calculate_percentage_change(70.0, 75.0)
        self.assertAlmostEqual(result, 7.1, places=1)
    
    def test_negative_percentage_change(self):
        """Test calculation of negative percentage change."""
        result = calculate_percentage_change(75.0, 70.0)
        self.assertAlmostEqual(result, -6.7, places=1)
    
    def test_zero_change(self):
        """Test zero percentage change."""
        result = calculate_percentage_change(70.0, 70.0)
        self.assertEqual(result, 0.0)
    
    def test_zero_old_value(self):
        """Test handling of zero old value."""
        result = calculate_percentage_change(0.0, 70.0)
        self.assertEqual(result, 0.0)


class SignificantWeightChangeTests(TestCase):
    """Test significant weight change detection."""
    
    def test_significant_1month_change(self):
        """Test significant weight change in 1 month."""
        # 5% change in 30 days is significant
        self.assertTrue(is_significant_weight_change(5.0, 30))
        self.assertTrue(is_significant_weight_change(6.0, 30))
        self.assertFalse(is_significant_weight_change(4.0, 30))
    
    def test_significant_3month_change(self):
        """Test significant weight change in 3 months."""
        # 7.5% change in 90 days is significant
        self.assertTrue(is_significant_weight_change(7.5, 90))
        self.assertTrue(is_significant_weight_change(8.0, 90))
        self.assertFalse(is_significant_weight_change(7.0, 90))
    
    def test_significant_6month_change(self):
        """Test significant weight change in 6 months."""
        # 10% change in 180 days is significant
        self.assertTrue(is_significant_weight_change(10.0, 180))
        self.assertTrue(is_significant_weight_change(11.0, 180))
        self.assertFalse(is_significant_weight_change(9.0, 180))
    
    def test_negative_percentage_significance(self):
        """Test that negative changes are also evaluated."""
        # Weight loss is also significant
        self.assertTrue(is_significant_weight_change(-5.5, 30))
        self.assertTrue(is_significant_weight_change(-8.0, 90))


class BMITrendsTests(TestCase):
    """Test BMI trends calculation."""
    
    def test_calculate_single_bmi_trend(self):
        """Test BMI trend calculation with single weight."""
        fhir_bundle = {
            'entry': [
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'code': {
                            'coding': [{'code': '8302-2'}]
                        },
                        'valueQuantity': {
                            'value': 175.0,
                            'unit': 'cm'
                        },
                        'effectiveDateTime': '2024-01-01'
                    }
                },
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'id': 'weight-1',
                        'code': {
                            'coding': [{'code': '29463-7'}]
                        },
                        'valueQuantity': {
                            'value': 70.0,
                            'unit': 'kg'
                        },
                        'effectiveDateTime': '2024-01-15'
                    }
                }
            ]
        }
        
        trends = calculate_bmi_trends(fhir_bundle)
        self.assertEqual(len(trends), 1)
        self.assertEqual(trends[0]['weight_kg'], 70.0)
        self.assertAlmostEqual(trends[0]['height_m'], 1.75, places=2)
        self.assertAlmostEqual(trends[0]['bmi'], 22.9, places=1)
        self.assertEqual(trends[0]['bmi_category'], 'normal')
        self.assertIsNone(trends[0]['percentage_change'])
    
    def test_calculate_multiple_bmi_trends(self):
        """Test BMI trend calculation with multiple weights."""
        fhir_bundle = {
            'entry': [
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'code': {
                            'coding': [{'code': '8302-2'}]
                        },
                        'valueQuantity': {
                            'value': 175.0,
                            'unit': 'cm'
                        },
                        'effectiveDateTime': '2024-01-01'
                    }
                },
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'code': {
                            'coding': [{'code': '29463-7'}]
                        },
                        'valueQuantity': {
                            'value': 70.0,
                            'unit': 'kg'
                        },
                        'effectiveDateTime': '2024-01-15'
                    }
                },
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'code': {
                            'coding': [{'code': '29463-7'}]
                        },
                        'valueQuantity': {
                            'value': 68.0,
                            'unit': 'kg'
                        },
                        'effectiveDateTime': '2024-02-15'
                    }
                }
            ]
        }
        
        trends = calculate_bmi_trends(fhir_bundle)
        self.assertEqual(len(trends), 2)
        
        # First measurement
        self.assertEqual(trends[0]['weight_kg'], 70.0)
        self.assertIsNone(trends[0]['percentage_change'])
        
        # Second measurement
        self.assertEqual(trends[1]['weight_kg'], 68.0)
        self.assertAlmostEqual(trends[1]['percentage_change'], -2.9, places=1)
        self.assertEqual(trends[1]['time_delta_days'], 31)
    
    def test_no_height_returns_empty(self):
        """Test that missing height returns empty list."""
        fhir_bundle = {
            'entry': [{
                'resource': {
                    'resourceType': 'Observation',
                    'code': {
                        'coding': [{'code': '29463-7'}]
                    },
                    'valueQuantity': {
                        'value': 70.0,
                        'unit': 'kg'
                    }
                }
            }]
        }
        
        trends = calculate_bmi_trends(fhir_bundle)
        self.assertEqual(len(trends), 0)
    
    def test_no_weight_returns_empty(self):
        """Test that missing weight returns empty list."""
        fhir_bundle = {
            'entry': [{
                'resource': {
                    'resourceType': 'Observation',
                    'code': {
                        'coding': [{'code': '8302-2'}]
                    },
                    'valueQuantity': {
                        'value': 175.0,
                        'unit': 'cm'
                    }
                }
            }]
        }
        
        trends = calculate_bmi_trends(fhir_bundle)
        self.assertEqual(len(trends), 0)


class WeightSummaryTests(TestCase):
    """Test weight summary generation."""
    
    def test_summary_with_no_data(self):
        """Test summary with empty trends."""
        summary = get_weight_summary([])
        self.assertFalse(summary['has_data'])
        self.assertEqual(summary['measurement_count'], 0)
    
    def test_summary_with_single_measurement(self):
        """Test summary with single measurement."""
        trends = [{
            'date': datetime(2024, 1, 15),
            'weight_kg': 70.0,
            'bmi': 22.9,
            'bmi_display': 'Normal Weight',
            'is_significant_change': False,
        }]
        
        summary = get_weight_summary(trends)
        self.assertTrue(summary['has_data'])
        self.assertEqual(summary['measurement_count'], 1)
        self.assertEqual(summary['latest_weight_kg'], 70.0)
        self.assertEqual(summary['latest_bmi'], 22.9)
        self.assertIsNone(summary['total_weight_change_kg'])
    
    def test_summary_with_multiple_measurements(self):
        """Test summary with multiple measurements."""
        trends = [
            {
                'date': datetime(2024, 1, 15),
                'weight_kg': 70.0,
                'bmi': 22.9,
                'bmi_display': 'Normal Weight',
                'is_significant_change': False,
            },
            {
                'date': datetime(2024, 2, 15),
                'weight_kg': 68.0,
                'bmi': 22.2,
                'bmi_display': 'Normal Weight',
                'is_significant_change': False,
            },
            {
                'date': datetime(2024, 3, 15),
                'weight_kg': 66.0,
                'bmi': 21.6,
                'bmi_display': 'Normal Weight',
                'is_significant_change': True,
            },
        ]
        
        summary = get_weight_summary(trends)
        self.assertTrue(summary['has_data'])
        self.assertEqual(summary['measurement_count'], 3)
        self.assertEqual(summary['latest_weight_kg'], 66.0)
        self.assertEqual(summary['earliest_weight_kg'], 70.0)
        self.assertEqual(summary['total_weight_change_kg'], -4.0)
        self.assertAlmostEqual(summary['total_percentage_change'], -5.7, places=1)
        self.assertEqual(summary['significant_changes_count'], 1)

