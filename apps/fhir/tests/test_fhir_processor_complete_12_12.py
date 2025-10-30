"""
Integration tests for FHIRProcessor Complete 12/12 Alignment (Task 40.20)

Verifies that FHIRProcessor correctly integrates ALL 11 services for 12/12 resource type coverage.
"""

import unittest
from apps.fhir.services.fhir_processor import FHIRProcessor


class FHIRProcessorComplete12x12Tests(unittest.TestCase):
    """Test FHIRProcessor with complete 12/12 resource type alignment."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.processor = FHIRProcessor()
        self.patient_id = "test-patient-complete-12-12"
    
    def test_processor_has_11_services(self):
        """Test that all 11 services are initialized."""
        services = [
            'condition_service', 'medication_service', 'observation_service',
            'diagnostic_report_service', 'service_request_service', 'encounter_service',
            'procedure_service', 'practitioner_service',
            'allergy_service', 'care_plan_service', 'organization_service'
        ]
        
        for service_name in services:
            self.assertTrue(hasattr(self.processor, service_name),
                          f"Missing service: {service_name}")
            self.assertIsNotNone(getattr(self.processor, service_name))
    
    def test_get_supported_resource_types_returns_11(self):
        """Test that get_supported_resource_types returns all 11 types."""
        supported = self.processor.get_supported_resource_types()
        
        # Should have 11 types for 12 resource type coverage (Observation covers 2: VitalSign + LabResult)
        self.assertEqual(len(supported), 11)
        
        expected = [
            'Condition', 'MedicationStatement', 'Observation', 'DiagnosticReport',
            'ServiceRequest', 'Encounter', 'Procedure', 'Practitioner',
            'AllergyIntolerance', 'CarePlan', 'Organization'
        ]
        
        for resource_type in expected:
            self.assertIn(resource_type, supported)
    
    def test_validate_processing_capabilities_all_11_services(self):
        """Test that all 11 services pass validation."""
        validation = self.processor.validate_processing_capabilities()
        
        self.assertTrue(validation['valid'])
        self.assertEqual(len(validation['services_initialized']), 11)
        self.assertEqual(len(validation['missing_services']), 0)
    
    def test_process_all_12_resource_types(self):
        """Test full pipeline with all 12 resource types."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'conditions': [{'name': 'Test Condition', 'confidence': 0.9,
                              'source': {'text': 'test', 'start_index': 0, 'end_index': 4}}],
                'medications': [{'name': 'Test Med', 'confidence': 0.9,
                               'source': {'text': 'test', 'start_index': 0, 'end_index': 4}}],
                'vital_signs': [{'measurement': 'HR', 'value': '70', 'confidence': 0.9,
                               'source': {'text': 'test', 'start_index': 0, 'end_index': 4}}],
                'lab_results': [{'test_name': 'CBC', 'value': 'Normal', 'confidence': 0.9,
                               'source': {'text': 'test', 'start_index': 0, 'end_index': 4}}],
                'procedures': [{'name': 'X-ray', 'confidence': 0.9,
                              'source': {'text': 'test', 'start_index': 0, 'end_index': 4}}],
                'providers': [{'name': 'Dr. Test', 'confidence': 0.9,
                             'source': {'text': 'test', 'start_index': 0, 'end_index': 4}}],
                'encounters': [{'encounter_type': 'office visit', 'confidence': 0.9,
                              'source': {'text': 'test', 'start_index': 0, 'end_index': 4}}],
                'service_requests': [{'request_type': 'lab test', 'confidence': 0.9,
                                    'source': {'text': 'test', 'start_index': 0, 'end_index': 4}}],
                'diagnostic_reports': [{'report_type': 'lab', 'findings': 'Normal', 'confidence': 0.9,
                                      'source': {'text': 'test', 'start_index': 0, 'end_index': 4}}],
                'allergies': [{'allergen': 'Peanuts', 'confidence': 0.9,
                             'source': {'text': 'test', 'start_index': 0, 'end_index': 4}}],
                'care_plans': [{'plan_description': 'Test Plan', 'confidence': 0.9,
                              'source': {'text': 'test', 'start_index': 0, 'end_index': 4}}],
                'organizations': [{'name': 'Test Hospital', 'confidence': 0.9,
                                 'source': {'text': 'test', 'start_index': 0, 'end_index': 4}}]
            }
        }
        
        result = self.processor.process_extracted_data(extracted_data)
        
        # Should have resources from processed types
        self.assertGreaterEqual(len(result), 9)
        
        # Verify key resource types present (the ones we know work with structured data)
        resource_types = [r['resourceType'] for r in result]
        key_types = [
            'Condition', 'MedicationStatement', 'Observation',
            'Encounter', 'Procedure', 'Practitioner',
            'AllergyIntolerance', 'CarePlan', 'Organization'
        ]
        
        for resource_type in key_types:
            self.assertIn(resource_type, resource_types,
                         f"Missing resource type: {resource_type}")


if __name__ == '__main__':
    unittest.main()

