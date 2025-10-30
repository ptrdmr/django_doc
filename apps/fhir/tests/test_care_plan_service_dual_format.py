"""
Tests for CarePlanService dual-format support (Task 40.18)
"""

import unittest
from apps.fhir.services.care_plan_service import CarePlanService


class CarePlanServiceDualFormatTests(unittest.TestCase):
    """Test CarePlanService with both structured and legacy input formats."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = CarePlanService()
        self.patient_id = "test-patient-plan-888"
    
    def test_structured_input_happy_path(self):
        """Test processing structured CarePlan data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'care_plans': [{
                    'plan_description': 'Diabetes management',
                    'goals': ['HbA1c < 7%', 'Weight loss 10 lbs'],
                    'activities': ['Check glucose daily', 'Exercise 30min'],
                    'period_start': '2024-10-01',
                    'period_end': '2025-04-01',
                    'status': 'active',
                    'intent': 'plan',
                    'confidence': 0.93,
                    'source': {'text': 'DM care plan', 'start_index': 0, 'end_index': 12}
                }]
            }
        }
        
        result = self.service.process_care_plans(extracted_data)
        
        self.assertEqual(len(result), 1)
        plan = result[0]
        self.assertEqual(plan['resourceType'], 'CarePlan')
        self.assertEqual(plan['description'], 'Diabetes management')
        self.assertEqual(plan['status'], 'active')
        self.assertEqual(plan['intent'], 'plan')
        self.assertEqual(len(plan['goal']), 2)
        self.assertEqual(len(plan['activity']), 2)
        self.assertIn('period', plan)
    
    def test_structured_minimal_data(self):
        """Test with only required fields."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'care_plans': [{
                    'plan_description': 'Post-op care',
                    'confidence': 0.85,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = self.service.process_care_plans(extracted_data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['description'], 'Post-op care')
    
    def test_status_mapping(self):
        """Test status mapping."""
        for status in ['draft', 'active', 'completed', 'cancelled']:
            extracted_data = {
                'patient_id': self.patient_id,
                'structured_data': {
                    'care_plans': [{
                        'plan_description': 'Test',
                        'status': status,
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }]
                }
            }
            
            result = self.service.process_care_plans(extracted_data)
            self.assertEqual(result[0]['status'], status)
    
    def test_legacy_fields_regression(self):
        """Test backward compatibility."""
        extracted_data = {
            'patient_id': self.patient_id,
            'fields': [{
                'label': 'Care Plan',
                'value': 'HTN management plan',
                'confidence': 0.88
            }]
        }
        
        result = self.service.process_care_plans(extracted_data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['description'], 'HTN management plan')
    
    def test_empty_list(self):
        """Test empty list handling."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {'care_plans': []}
        }
        
        result = self.service.process_care_plans(extracted_data)
        self.assertEqual(len(result), 0)
    
    def test_missing_patient_id(self):
        """Test missing patient_id."""
        extracted_data = {
            'structured_data': {
                'care_plans': [{
                    'plan_description': 'Test',
                    'confidence': 0.9,
                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                }]
            }
        }
        
        result = self.service.process_care_plans(extracted_data)
        self.assertEqual(len(result), 0)


if __name__ == '__main__':
    unittest.main()

