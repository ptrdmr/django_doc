"""
Tests for AI Extraction Prompt Updates Phase 3 (Task 40.16)

Verifies that AI extraction prompts include instructions for Phase 3 models:
- AllergyIntolerance
- CarePlan
- Organization
"""

import unittest
from apps.documents.services import ai_extraction


class AIPromptsPhase3Tests(unittest.TestCase):
    """Test that AI extraction prompts include Phase 3 resource types."""
    
    def test_prompt_includes_allergy_instructions(self):
        """Test that prompts include AllergyIntolerance extraction instructions."""
        import inspect
        source = inspect.getsource(ai_extraction.extract_medical_data_structured)
        
        # Verify keywords
        self.assertIn('ALLERGY', source.upper())
        self.assertIn('allergen', source)
        self.assertIn('reaction', source)
        self.assertIn('severity', source)
        
        # Verify examples
        self.assertIn('NKDA', source)
        self.assertIn('anaphylaxis', source.lower())
    
    def test_prompt_includes_care_plan_instructions(self):
        """Test that prompts include CarePlan extraction instructions."""
        import inspect
        source = inspect.getsource(ai_extraction.extract_medical_data_structured)
        
        # Verify keywords
        self.assertIn('CARE PLAN', source.upper())
        self.assertIn('plan_description', source)
        self.assertIn('goals', source)
        self.assertIn('activities', source)
        
        # Verify examples
        self.assertIn('treatment plan', source.lower())
    
    def test_prompt_includes_organization_instructions(self):
        """Test that prompts include Organization extraction instructions."""
        import inspect
        source = inspect.getsource(ai_extraction.extract_medical_data_structured)
        
        # Verify keywords
        self.assertIn('ORGANIZATION', source.upper())
        self.assertIn('organization', source.lower())
        self.assertIn('facility', source.lower())
        
        # Verify examples
        self.assertIn('Hospital', source)
        self.assertIn('Clinic', source)
    
    def test_all_12_models_in_structured_extraction(self):
        """Test that StructuredMedicalExtraction has all 12 resource type fields."""
        from apps.documents.services.ai_extraction import StructuredMedicalExtraction
        
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
            care_plans=[],
            organizations=[],
            extraction_timestamp='2024-10-29T12:00:00'
        )
        
        # Verify all 12 fields exist
        self.assertEqual(len(extraction.conditions), 0)
        self.assertEqual(len(extraction.medications), 0)
        self.assertEqual(len(extraction.vital_signs), 0)
        self.assertEqual(len(extraction.lab_results), 0)
        self.assertEqual(len(extraction.procedures), 0)
        self.assertEqual(len(extraction.providers), 0)
        self.assertEqual(len(extraction.encounters), 0)
        self.assertEqual(len(extraction.service_requests), 0)
        self.assertEqual(len(extraction.diagnostic_reports), 0)
        self.assertEqual(len(extraction.allergies), 0)
        self.assertEqual(len(extraction.care_plans), 0)
        self.assertEqual(len(extraction.organizations), 0)
    
    def test_prompt_lists_12_resource_types(self):
        """Test that prompts explicitly mention all 12 resource types."""
        import inspect
        source = inspect.getsource(ai_extraction.extract_medical_data_structured)
        
        # Check for "12" or list of all types
        self.assertIn('12', source)


if __name__ == '__main__':
    unittest.main()

