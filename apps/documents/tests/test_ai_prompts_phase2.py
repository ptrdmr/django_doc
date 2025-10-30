"""
Tests for AI Extraction Prompt Updates (Task 40.12)

Verifies that AI extraction prompts include instructions for Phase 2 models:
- Encounter
- ServiceRequest  
- DiagnosticReport
"""

import unittest
from apps.documents.services import ai_extraction


class AIPromptsPhase2Tests(unittest.TestCase):
    """Test that AI extraction prompts include Phase 2 resource types."""
    
    def test_prompt_includes_encounter_instructions(self):
        """Test that prompts include Encounter extraction instructions."""
        # Read the ai_extraction module source
        import inspect
        source = inspect.getsource(ai_extraction.extract_medical_data_structured)
        
        # Verify Encounter-related keywords in prompts
        self.assertIn('ENCOUNTER', source.upper())
        self.assertIn('encounter_type', source)
        self.assertIn('encounter_date', source)
        self.assertIn('participants', source)
        
        # Verify example phrases
        self.assertIn('office visit', source.lower())
        self.assertIn('emergency', source.lower())
    
    def test_prompt_includes_service_request_instructions(self):
        """Test that prompts include ServiceRequest extraction instructions."""
        import inspect
        source = inspect.getsource(ai_extraction.extract_medical_data_structured)
        
        # Verify ServiceRequest-related keywords
        self.assertIn('SERVICE REQUEST', source.upper())
        self.assertIn('request_type', source)
        self.assertIn('requester', source)
        self.assertIn('priority', source)
        
        # Verify example phrases
        self.assertIn('referral', source.lower())
        self.assertIn('order', source.lower())
    
    def test_prompt_includes_diagnostic_report_instructions(self):
        """Test that prompts include DiagnosticReport extraction instructions."""
        import inspect
        source = inspect.getsource(ai_extraction.extract_medical_data_structured)
        
        # Verify DiagnosticReport-related keywords
        self.assertIn('DIAGNOSTIC REPORT', source.upper())
        self.assertIn('report_type', source)
        self.assertIn('findings', source)
        self.assertIn('conclusion', source)
        
        # Verify example phrases
        self.assertIn('lab', source.lower())
        self.assertIn('radiology', source.lower())
    
    def test_structured_extraction_has_new_fields(self):
        """Test that StructuredMedicalExtraction has the new fields."""
        from apps.documents.services.ai_extraction import StructuredMedicalExtraction
        
        # Create minimal extraction
        extraction = StructuredMedicalExtraction(
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[],
            procedures=[],
            providers=[],
            encounters=[],  # NEW
            service_requests=[],  # NEW
            diagnostic_reports=[],  # NEW
            extraction_timestamp='2024-10-29T12:00:00'
        )
        
        # Verify new fields exist and are lists
        self.assertIsInstance(extraction.encounters, list)
        self.assertIsInstance(extraction.service_requests, list)
        self.assertIsInstance(extraction.diagnostic_reports, list)
    
    def test_new_model_classes_exist(self):
        """Test that new Pydantic model classes are defined."""
        # Verify models are importable
        from apps.documents.services.ai_extraction import Encounter, ServiceRequest, DiagnosticReport
        
        # Verify they are classes
        self.assertTrue(callable(Encounter))
        self.assertTrue(callable(ServiceRequest))
        self.assertTrue(callable(DiagnosticReport))
    
    def test_prompt_keywords_for_all_new_types(self):
        """Test that critical extraction keywords are present for all 3 new types."""
        import inspect
        source = inspect.getsource(ai_extraction.extract_medical_data_structured)
        
        # Encounter keywords
        encounter_keywords = ['encounter_type', 'encounter_date', 'location', 'participants']
        for keyword in encounter_keywords:
            self.assertIn(keyword, source, f"Missing encounter keyword: {keyword}")
        
        # ServiceRequest keywords
        request_keywords = ['request_type', 'requester', 'priority', 'request_date']
        for keyword in request_keywords:
            self.assertIn(keyword, source, f"Missing service request keyword: {keyword}")
        
        # DiagnosticReport keywords
        report_keywords = ['report_type', 'findings', 'conclusion', 'report_date']
        for keyword in report_keywords:
            self.assertIn(keyword, source, f"Missing diagnostic report keyword: {keyword}")


if __name__ == '__main__':
    unittest.main()

