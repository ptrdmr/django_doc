"""
Unit tests for FHIRMetricsService.

Tests the calculation of data capture metrics and improvements.
"""

from django.test import TestCase
from apps.fhir.services.metrics_service import FHIRMetricsService


class FHIRMetricsServiceTests(TestCase):
    """Test cases for FHIRMetricsService."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.metrics_service = FHIRMetricsService()
    
    def test_calculate_data_capture_metrics_perfect_capture(self):
        """Test with perfect capture (100%)."""
        extracted_data = {
            'medications': [
                {'name': 'Med1', 'dosage': '10mg'},
                {'name': 'Med2', 'dosage': '20mg'}
            ],
            'diagnostic_reports': [
                {'procedure_type': 'EKG', 'conclusion': 'Normal'}
            ],
            'service_requests': [
                {'service': 'Consult'}
            ]
        }
        
        processed_resources = [
            {'resourceType': 'MedicationStatement', 'medicationCodeableConcept': {'text': 'Med1'}},
            {'resourceType': 'MedicationStatement', 'medicationCodeableConcept': {'text': 'Med2'}},
            {'resourceType': 'DiagnosticReport', 'code': {'text': 'EKG'}},
            {'resourceType': 'ServiceRequest', 'code': {'text': 'Consult'}}
        ]
        
        metrics = self.metrics_service.calculate_data_capture_metrics(
            extracted_data, processed_resources
        )
        
        self.assertEqual(metrics['overall']['total_data_points'], 4)
        self.assertEqual(metrics['overall']['captured_data_points'], 4)
        self.assertEqual(metrics['overall']['capture_rate'], 100.0)
        
        # Check category metrics
        self.assertEqual(metrics['by_category']['medications']['extracted_count'], 2)
        self.assertEqual(metrics['by_category']['medications']['captured_count'], 2)
        self.assertEqual(metrics['by_category']['medications']['capture_rate'], 100.0)
        
        self.assertEqual(metrics['by_category']['diagnostic_reports']['extracted_count'], 1)
        self.assertEqual(metrics['by_category']['diagnostic_reports']['captured_count'], 1)
        self.assertEqual(metrics['by_category']['diagnostic_reports']['capture_rate'], 100.0)
    
    def test_calculate_data_capture_metrics_partial_capture(self):
        """Test with partial capture."""
        extracted_data = {
            'medications': [
                {'name': 'Med1'},
                {'name': 'Med2'},
                {'name': 'Med3'}
            ],
            'diagnostic_reports': [
                {'procedure_type': 'EKG'},
                {'procedure_type': 'X-ray'}
            ]
        }
        
        processed_resources = [
            {'resourceType': 'MedicationStatement', 'medicationCodeableConcept': {'text': 'Med1'}},
            {'resourceType': 'DiagnosticReport', 'code': {'text': 'EKG'}}
            # Missing Med2, Med3, and X-ray
        ]
        
        metrics = self.metrics_service.calculate_data_capture_metrics(
            extracted_data, processed_resources
        )
        
        self.assertEqual(metrics['overall']['total_data_points'], 5)
        self.assertEqual(metrics['overall']['captured_data_points'], 2)
        self.assertEqual(metrics['overall']['capture_rate'], 40.0)
        
        # Check category metrics
        self.assertEqual(metrics['by_category']['medications']['capture_rate'], 33.3)  # 1/3
        self.assertEqual(metrics['by_category']['diagnostic_reports']['capture_rate'], 50.0)  # 1/2
    
    def test_calculate_data_capture_metrics_empty_data(self):
        """Test with empty data."""
        extracted_data = {}
        processed_resources = []
        
        metrics = self.metrics_service.calculate_data_capture_metrics(
            extracted_data, processed_resources
        )
        
        self.assertEqual(metrics['overall']['total_data_points'], 0)
        self.assertEqual(metrics['overall']['captured_data_points'], 0)
        self.assertEqual(metrics['overall']['capture_rate'], 0.0)
        self.assertEqual(metrics['by_category'], {})
    
    def test_calculate_data_capture_metrics_encounter_single_item(self):
        """Test with encounter as single item (not list)."""
        extracted_data = {
            'encounter': {
                'type': 'AMB',
                'date': '2023-05-15'
            }
        }
        
        processed_resources = [
            {'resourceType': 'Encounter', 'class': {'code': 'AMB'}}
        ]
        
        metrics = self.metrics_service.calculate_data_capture_metrics(
            extracted_data, processed_resources
        )
        
        self.assertEqual(metrics['overall']['total_data_points'], 1)
        self.assertEqual(metrics['overall']['captured_data_points'], 1)
        self.assertEqual(metrics['overall']['capture_rate'], 100.0)
        
        # Check encounter category
        self.assertEqual(metrics['by_category']['encounter']['extracted_count'], 1)
        self.assertEqual(metrics['by_category']['encounter']['captured_count'], 1)
    
    def test_generate_metrics_report(self):
        """Test metrics report generation."""
        metrics = {
            'overall': {
                'total_data_points': 5,
                'captured_data_points': 4,
                'capture_rate': 80.0
            },
            'by_category': {
                'medications': {
                    'extracted_count': 3,
                    'captured_count': 3,
                    'capture_rate': 100.0
                },
                'diagnostic_reports': {
                    'extracted_count': 2,
                    'captured_count': 1,
                    'capture_rate': 50.0
                }
            },
            'resource_counts': {
                'MedicationStatement': 3,
                'DiagnosticReport': 1
            },
            'processing_metadata': {
                'timestamp': '2023-05-15T10:00:00',
                'ai_data_categories': ['medications', 'diagnostic_reports'],
                'fhir_resource_types': ['MedicationStatement', 'DiagnosticReport']
            },
            'quality_indicators': {
                'high_capture_categories': [
                    {'category': 'medications', 'rate': 100.0}
                ],
                'low_capture_categories': [
                    {'category': 'diagnostic_reports', 'rate': 50.0}
                ],
                'missing_categories': [],
                'resource_diversity': 2,
                'completeness_score': 75.0
            }
        }
        
        report = self.metrics_service.generate_metrics_report(metrics)
        
        self.assertIn('FHIR Data Capture Metrics Report', report)
        self.assertIn('Overall Capture Rate: 80.0%', report)
        self.assertIn('✅ Medications: 3/3 (100.0%)', report)
        self.assertIn('❌ Diagnostic Reports: 1/2 (50.0%)', report)
        self.assertIn('MedicationStatement: 3', report)
        self.assertIn('DiagnosticReport: 1', report)
        self.assertIn('Resource Diversity: 2 different types', report)
        self.assertIn('Completeness Score: 75.0%', report)
    
    def test_calculate_improvement_metrics(self):
        """Test improvement metrics calculation."""
        before_metrics = {
            'overall': {'capture_rate': 60.0},
            'by_category': {
                'medications': {'capture_rate': 50.0},
                'diagnostic_reports': {'capture_rate': 70.0}
            }
        }
        
        after_metrics = {
            'overall': {'capture_rate': 85.0},
            'by_category': {
                'medications': {'capture_rate': 90.0},
                'diagnostic_reports': {'capture_rate': 80.0},
                'service_requests': {'capture_rate': 100.0}  # New category
            }
        }
        
        improvement = self.metrics_service.calculate_improvement_metrics(
            before_metrics, after_metrics
        )
        
        # Check overall improvement
        self.assertEqual(improvement['overall_improvement']['before_rate'], 60.0)
        self.assertEqual(improvement['overall_improvement']['after_rate'], 85.0)
        self.assertEqual(improvement['overall_improvement']['improvement'], 25.0)
        
        # Check category improvements
        self.assertEqual(
            improvement['category_improvements']['medications']['improvement'], 40.0
        )
        self.assertEqual(
            improvement['category_improvements']['diagnostic_reports']['improvement'], 10.0
        )
        
        # Check new categories
        self.assertIn('service_requests', improvement['new_categories'])
        
        # Check improved categories (> 5% improvement)
        improved_meds = next(
            (cat for cat in improvement['improved_categories'] 
             if cat['category'] == 'medications'), None
        )
        self.assertIsNotNone(improved_meds)
        self.assertEqual(improved_meds['improvement'], 40.0)
    
    def test_quality_indicators_calculation(self):
        """Test quality indicators calculation."""
        category_metrics = {
            'medications': {'capture_rate': 95.0},
            'diagnostic_reports': {'capture_rate': 45.0},
            'service_requests': {'capture_rate': 75.0}
        }
        
        resource_counts = {
            'MedicationStatement': 2,
            'DiagnosticReport': 1,
            'ServiceRequest': 1
        }
        
        indicators = self.metrics_service._calculate_quality_indicators(
            category_metrics, resource_counts
        )
        
        # Check high capture categories (>= 90%)
        self.assertEqual(len(indicators['high_capture_categories']), 1)
        self.assertEqual(indicators['high_capture_categories'][0]['category'], 'medications')
        
        # Check low capture categories (< 50%)
        self.assertEqual(len(indicators['low_capture_categories']), 1)
        self.assertEqual(indicators['low_capture_categories'][0]['category'], 'diagnostic_reports')
        
        # Check resource diversity
        self.assertEqual(indicators['resource_diversity'], 3)
        
        # Check completeness score (weighted average of important categories)
        # medications (95.0) + diagnostic_reports (45.0) = 140.0 / 2 = 70.0
        self.assertEqual(indicators['completeness_score'], 70.0)
    
    def test_count_extracted_items_various_types(self):
        """Test counting extracted items with various data types."""
        # Test with list
        self.assertEqual(self.metrics_service._count_extracted_items([1, 2, 3]), 3)
        self.assertEqual(self.metrics_service._count_extracted_items([]), 0)
        
        # Test with dict (single item)
        self.assertEqual(self.metrics_service._count_extracted_items({'key': 'value'}), 1)
        self.assertEqual(self.metrics_service._count_extracted_items({}), 0)
        
        # Test with string
        self.assertEqual(self.metrics_service._count_extracted_items('some text'), 1)
        self.assertEqual(self.metrics_service._count_extracted_items(''), 0)
        self.assertEqual(self.metrics_service._count_extracted_items('   '), 0)
        
        # Test with other types
        self.assertEqual(self.metrics_service._count_extracted_items(None), 0)
        self.assertEqual(self.metrics_service._count_extracted_items(123), 0)
    
    def test_count_fhir_resources(self):
        """Test counting FHIR resources by type."""
        fhir_resources = [
            {'resourceType': 'MedicationStatement'},
            {'resourceType': 'MedicationStatement'},
            {'resourceType': 'DiagnosticReport'},
            {'resourceType': 'ServiceRequest'},
            {'resourceType': 'Unknown'},
            {}  # Missing resourceType
        ]
        
        counts = self.metrics_service._count_fhir_resources(fhir_resources)
        
        self.assertEqual(counts['MedicationStatement'], 2)
        self.assertEqual(counts['DiagnosticReport'], 1)
        self.assertEqual(counts['ServiceRequest'], 1)
        self.assertEqual(counts['Unknown'], 2)  # Unknown + missing resourceType
