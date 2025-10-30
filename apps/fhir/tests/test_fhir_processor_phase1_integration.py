"""
Integration tests for FHIRProcessor Phase 1 wiring (Task 40.7)

Verifies that FHIRProcessor correctly integrates all 8 services:
1. ConditionService
2. MedicationService
3. ObservationService
4. EncounterService
5. DiagnosticReportService
6. ServiceRequestService
7. ProcedureService (NEW)
8. PractitionerService (NEW)
"""

import unittest
from apps.fhir.services.fhir_processor import FHIRProcessor


class FHIRProcessorPhase1IntegrationTests(unittest.TestCase):
    """Test FHIRProcessor with newly wired services."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.processor = FHIRProcessor()
        self.patient_id = "test-patient-integration-001"
    
    def test_processor_initialization(self):
        """Test that all 8 services are properly initialized."""
        # Verify all service attributes exist
        self.assertIsNotNone(self.processor.condition_service)
        self.assertIsNotNone(self.processor.medication_service)
        self.assertIsNotNone(self.processor.observation_service)
        self.assertIsNotNone(self.processor.encounter_service)
        self.assertIsNotNone(self.processor.diagnostic_report_service)
        self.assertIsNotNone(self.processor.service_request_service)
        self.assertIsNotNone(self.processor.procedure_service)
        self.assertIsNotNone(self.processor.practitioner_service)
    
    def test_get_supported_resource_types(self):
        """Test that get_supported_resource_types returns 8 types."""
        supported = self.processor.get_supported_resource_types()
        
        # Should have 8 types now (up from 4)
        self.assertEqual(len(supported), 8)
        
        # Verify all expected types present
        expected_types = [
            'Condition',
            'MedicationStatement',
            'Observation',
            'DiagnosticReport',
            'ServiceRequest',
            'Encounter',
            'Procedure',
            'Practitioner'
        ]
        
        for resource_type in expected_types:
            self.assertIn(resource_type, supported, f"{resource_type} should be in supported types")
    
    def test_validate_processing_capabilities(self):
        """Test that all 8 services pass validation."""
        validation = self.processor.validate_processing_capabilities()
        
        # Should be valid
        self.assertTrue(validation['valid'])
        
        # Should have 8 services initialized
        self.assertEqual(len(validation['services_initialized']), 8)
        
        # Should have no missing services
        self.assertEqual(len(validation['missing_services']), 0)
        
        # Should have no errors
        self.assertEqual(len(validation['errors']), 0)
        
        # Verify all services in the list
        expected_services = [
            'ConditionService',
            'MedicationService',
            'ObservationService',
            'DiagnosticReportService',
            'ServiceRequestService',
            'EncounterService',
            'ProcedureService',
            'PractitionerService'
        ]
        
        for service_name in expected_services:
            self.assertIn(service_name, validation['services_initialized'])
    
    def test_process_with_procedures_and_practitioners(self):
        """Test full pipeline with procedures and practitioners data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'conditions': [{
                    'name': 'Hypertension',
                    'status': 'active',
                    'confidence': 0.95,
                    'source': {'text': 'HTN', 'start_index': 0, 'end_index': 3}
                }],
                'medications': [{
                    'name': 'Lisinopril',
                    'dosage': '10mg',
                    'status': 'active',
                    'confidence': 0.94,
                    'source': {'text': 'lisinopril', 'start_index': 10, 'end_index': 20}
                }],
                'vital_signs': [{
                    'measurement': 'Blood Pressure',
                    'value': '140/90',
                    'unit': 'mmHg',
                    'confidence': 0.96,
                    'source': {'text': 'BP 140/90', 'start_index': 30, 'end_index': 39}
                }],
                'procedures': [{
                    'name': 'EKG',
                    'procedure_date': '2024-10-20',
                    'confidence': 0.93,
                    'source': {'text': 'EKG performed', 'start_index': 50, 'end_index': 63}
                }],
                'providers': [{
                    'name': 'Dr. Smith',
                    'specialty': 'Cardiology',
                    'confidence': 0.97,
                    'source': {'text': 'Dr. Smith', 'start_index': 70, 'end_index': 79}
                }]
            }
        }
        
        result = self.processor.process_extracted_data(extracted_data)
        
        # Should have resources from all types
        self.assertGreater(len(result), 0)
        
        # Count resource types
        resource_types = [r['resourceType'] for r in result]
        self.assertIn('Condition', resource_types)
        self.assertIn('MedicationStatement', resource_types)
        self.assertIn('Observation', resource_types)
        self.assertIn('Procedure', resource_types)
        self.assertIn('Practitioner', resource_types)
        
        # Verify we have at least 5 resources (1 of each type)
        self.assertGreaterEqual(len(result), 5)
    
    def test_process_procedures_only(self):
        """Test processing with only procedure data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'procedures': [
                    {
                        'name': 'Colonoscopy',
                        'procedure_date': '2024-09-15',
                        'provider': 'Dr. Johnson',
                        'confidence': 0.96,
                        'source': {'text': 'colonoscopy', 'start_index': 0, 'end_index': 11}
                    }
                ]
            }
        }
        
        result = self.processor.process_extracted_data(extracted_data)
        
        # Should have procedure resource (plus encounter created by default)
        self.assertGreaterEqual(len(result), 1)
        
        # Find procedure resource
        procedures = [r for r in result if r['resourceType'] == 'Procedure']
        self.assertEqual(len(procedures), 1)
        self.assertEqual(procedures[0]['code']['text'], 'Colonoscopy')
    
    def test_process_practitioners_only(self):
        """Test processing with only practitioner data."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'providers': [
                    {
                        'name': 'Dr. Emily Chen',
                        'specialty': 'Neurology',
                        'role': 'Consultant',
                        'confidence': 0.97,
                        'source': {'text': 'Dr. Chen', 'start_index': 0, 'end_index': 8}
                    }
                ]
            }
        }
        
        result = self.processor.process_extracted_data(extracted_data)
        
        # Should have practitioner resource (plus encounter created by default)
        self.assertGreaterEqual(len(result), 1)
        
        # Find practitioner resource
        practitioners = [r for r in result if r['resourceType'] == 'Practitioner']
        self.assertEqual(len(practitioners), 1)
        self.assertEqual(practitioners[0]['name'][0]['family'], 'Chen')
    
    def test_empty_structured_data(self):
        """Test that empty structured data doesn't break processing."""
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'conditions': [],
                'medications': [],
                'vital_signs': [],
                'lab_results': [],
                'procedures': [],
                'providers': []
            }
        }
        
        result = self.processor.process_extracted_data(extracted_data)
        
        # May create default encounter, but shouldn't error
        # Just verify it doesn't crash and returns a list
        self.assertIsInstance(result, list)
    
    def test_service_error_handling(self):
        """Test that errors in one service don't crash the pipeline."""
        # Malformed data that will cause some services to fail
        extracted_data = {
            'patient_id': self.patient_id,
            'structured_data': {
                'procedures': [
                    {
                        # Invalid: missing name
                        'procedure_date': '2024-10-10',
                        'confidence': 0.9,
                        'source': {'text': 'test', 'start_index': 0, 'end_index': 4}
                    }
                ],
                'providers': [
                    {
                        'name': 'Valid Provider',
                        'confidence': 0.95,
                        'source': {'text': 'provider', 'start_index': 10, 'end_index': 18}
                    }
                ]
            }
        }
        
        # Should not crash, should process valid data
        result = self.processor.process_extracted_data(extracted_data)
        
        # Should have practitioner (valid), but not procedure (invalid)
        # Plus default encounter
        self.assertGreaterEqual(len(result), 1)
        
        # Find practitioner resource
        practitioners = [r for r in result if r['resourceType'] == 'Practitioner']
        self.assertEqual(len(practitioners), 1)
        
        # Should NOT have procedure (was invalid)
        procedures = [r for r in result if r['resourceType'] == 'Procedure']
        self.assertEqual(len(procedures), 0)


if __name__ == '__main__':
    unittest.main()

