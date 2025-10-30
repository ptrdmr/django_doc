"""
Tests for CarePlan Pydantic model (Task 40.14)

Verifies that the CarePlan Pydantic model:
1. Validates correctly with valid data
2. Rejects invalid data appropriately
3. Serializes/deserializes properly
4. Integrates into StructuredMedicalExtraction
"""

import unittest
from pydantic import ValidationError
from apps.documents.services.ai_extraction import CarePlan, StructuredMedicalExtraction, SourceContext


class CarePlanPydanticModelTests(unittest.TestCase):
    """Test CarePlan Pydantic model validation and integration."""
    
    def test_care_plan_model_valid_full_data(self):
        """Test CarePlan model with all fields populated."""
        care_plan = CarePlan(
            plan_id='plan-001',
            plan_description='Diabetes management care plan',
            goals=['Maintain HbA1c < 7%', 'Achieve weight loss of 10 lbs', 'Daily exercise 30 min'],
            activities=['Check blood sugar daily', 'Take metformin 500mg BID', 'Follow diabetic diet', 'Exercise 5x/week'],
            period_start='2024-10-01',
            period_end='2025-04-01',
            status='active',
            intent='plan',
            confidence=0.93,
            source=SourceContext(
                text='Diabetes care plan: maintain HbA1c <7%, weight loss, exercise',
                start_index=400,
                end_index=465
            )
        )
        
        # Verify all fields
        self.assertEqual(care_plan.plan_id, 'plan-001')
        self.assertEqual(care_plan.plan_description, 'Diabetes management care plan')
        self.assertEqual(len(care_plan.goals), 3)
        self.assertIn('Maintain HbA1c < 7%', care_plan.goals)
        self.assertEqual(len(care_plan.activities), 4)
        self.assertIn('Check blood sugar daily', care_plan.activities)
        self.assertEqual(care_plan.period_start, '2024-10-01')
        self.assertEqual(care_plan.period_end, '2025-04-01')
        self.assertEqual(care_plan.status, 'active')
        self.assertEqual(care_plan.intent, 'plan')
        self.assertEqual(care_plan.confidence, 0.93)
    
    def test_care_plan_model_minimal_required_data(self):
        """Test CarePlan model with only required fields."""
        care_plan = CarePlan(
            plan_description='Post-surgical care',
            confidence=0.87,
            source=SourceContext(
                text='Post-op care plan',
                start_index=0,
                end_index=17
            )
        )
        
        # Verify required field
        self.assertEqual(care_plan.plan_description, 'Post-surgical care')
        
        # Verify optional fields default properly
        self.assertIsNone(care_plan.plan_id)
        self.assertEqual(care_plan.goals, [])
        self.assertEqual(care_plan.activities, [])
        self.assertIsNone(care_plan.period_start)
        self.assertIsNone(care_plan.period_end)
        self.assertIsNone(care_plan.status)
        self.assertIsNone(care_plan.intent)
    
    def test_care_plan_model_missing_required_field(self):
        """Test that missing plan_description raises ValidationError."""
        with self.assertRaises(ValidationError) as context:
            CarePlan(
                # Missing required plan_description
                goals=['Goal 1'],
                confidence=0.9,
                source=SourceContext(text='test', start_index=0, end_index=4)
            )
        
        self.assertIn('plan_description', str(context.exception))
    
    def test_care_plan_model_invalid_confidence(self):
        """Test that confidence outside 0.0-1.0 range raises ValidationError."""
        with self.assertRaises(ValidationError):
            CarePlan(
                plan_description='Test plan',
                confidence=2.0,  # Invalid
                source=SourceContext(text='test', start_index=0, end_index=4)
            )
    
    def test_care_plan_serialization(self):
        """Test that CarePlan serializes to dict correctly."""
        care_plan = CarePlan(
            plan_description='Hypertension management',
            goals=['BP < 130/80', 'Medication compliance'],
            activities=['Monitor BP daily', 'Take lisinopril'],
            status='active',
            confidence=0.91,
            source=SourceContext(text='HTN care plan', start_index=100, end_index=113)
        )
        
        plan_dict = care_plan.model_dump()
        
        # Verify dict structure
        self.assertIsInstance(plan_dict, dict)
        self.assertEqual(plan_dict['plan_description'], 'Hypertension management')
        self.assertEqual(len(plan_dict['goals']), 2)
        self.assertEqual(len(plan_dict['activities']), 2)
        self.assertEqual(plan_dict['status'], 'active')
    
    def test_care_plan_deserialization(self):
        """Test that CarePlan can be created from dict."""
        plan_dict = {
            'plan_description': 'COPD management plan',
            'goals': ['Improve lung function', 'Reduce exacerbations'],
            'activities': ['Use inhaler BID', 'Pulmonary rehab'],
            'period_start': '2024-09-01',
            'status': 'active',
            'intent': 'plan',
            'confidence': 0.89,
            'source': {
                'text': 'COPD care plan',
                'start_index': 200,
                'end_index': 214
            }
        }
        
        care_plan = CarePlan(**plan_dict)
        
        self.assertEqual(care_plan.plan_description, 'COPD management plan')
        self.assertEqual(len(care_plan.goals), 2)
    
    def test_care_plan_in_structured_extraction(self):
        """Test CarePlan integration into StructuredMedicalExtraction."""
        extraction = StructuredMedicalExtraction(
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[],
            procedures=[],
            providers=[],
            encounters=[],
            service_requests=[],
            diagnostic_reports=[],
            allergies=[],
            care_plans=[
                CarePlan(
                    plan_description='Wound care plan',
                    goals=['Healing within 2 weeks'],
                    activities=['Change dressing daily'],
                    confidence=0.90,
                    source=SourceContext(text='wound care', start_index=0, end_index=10)
                )
            ],
            extraction_timestamp='2024-10-29T12:00:00'
        )
        
        self.assertEqual(len(extraction.care_plans), 1)
        self.assertEqual(extraction.care_plans[0].plan_description, 'Wound care plan')
    
    def test_confidence_average_includes_care_plans(self):
        """Test that confidence_average calculation includes care plans."""
        extraction = StructuredMedicalExtraction(
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[],
            procedures=[],
            providers=[],
            encounters=[],
            service_requests=[],
            diagnostic_reports=[],
            allergies=[],
            care_plans=[
                CarePlan(
                    plan_description='Plan 1',
                    confidence=0.70,
                    source=SourceContext(text='test1', start_index=0, end_index=5)
                ),
                CarePlan(
                    plan_description='Plan 2',
                    confidence=0.90,
                    source=SourceContext(text='test2', start_index=6, end_index=11)
                )
            ],
            extraction_timestamp='2024-10-29T12:00:00'
        )
        
        # Confidence average should be (0.70 + 0.90) / 2 = 0.80
        self.assertEqual(extraction.confidence_average, 0.800)


if __name__ == '__main__':
    unittest.main()

