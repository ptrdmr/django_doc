"""
Integration Tests for FHIRProcessor

Tests the main FHIR processing pipeline that integrates all resource services
to convert extracted clinical data into comprehensive FHIR resources.
"""

from django.test import TestCase
from unittest.mock import patch, MagicMock
import logging

from apps.fhir.services.fhir_processor import FHIRProcessor


class FHIRProcessorIntegrationTests(TestCase):
    """Test the FHIRProcessor integration with all resource services."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.processor = FHIRProcessor()
        
        # Disable logging during tests to reduce noise
        logging.disable(logging.CRITICAL)
    
    def tearDown(self):
        """Clean up after tests."""
        logging.disable(logging.NOTSET)
    
    def test_process_complete_extracted_data(self):
        """Test processing comprehensive extracted data with all resource types."""
        # Create a comprehensive test dataset with all supported resource types
        test_data = {
            'patient_id': '123',
            'medications': [
                {
                    'name': 'Metformin',
                    'dosage': '500mg',
                    'route': 'oral',
                    'schedule': 'twice daily'
                },
                {
                    'name': 'Lisinopril',
                    'dosage': '10mg',
                    'route': 'oral',
                    'schedule': 'once daily'
                }
            ],
            'diagnostic_reports': [
                {
                    'procedure_type': 'EKG',
                    'date': '2023-05-15',
                    'conclusion': 'Normal sinus rhythm'
                },
                {
                    'procedure_type': 'Chest X-ray',
                    'date': '2023-05-15',
                    'conclusion': 'Clear lung fields'
                }
            ],
            'service_requests': [
                {
                    'service': 'Cardiology consult',
                    'date': '2023-05-16'
                }
            ],
            'encounter': {
                'type': 'AMB',
                'type_display': 'Ambulatory visit',
                'date': '2023-05-15'
            }
        }
        
        result = self.processor.process_extracted_data(test_data)
        
        # Verify all resources were created
        self.assertGreater(len(result), 0)
        self.assertLessEqual(len(result), 6)  # 2 meds + 2 reports + 1 request + 1 encounter
        
        # Count resources by type
        resource_counts = {}
        for resource in result:
            resource_type = resource['resourceType']
            if resource_type not in resource_counts:
                resource_counts[resource_type] = 0
            resource_counts[resource_type] += 1
        
        # Verify expected resource types
        self.assertEqual(resource_counts.get('MedicationStatement', 0), 2)
        self.assertEqual(resource_counts.get('DiagnosticReport', 0), 2)
        self.assertEqual(resource_counts.get('ServiceRequest', 0), 1)
        self.assertEqual(resource_counts.get('Encounter', 0), 1)
        
        # Verify all resources have proper structure
        for resource in result:
            self.assertIn('resourceType', resource)
            self.assertIn('meta', resource)
            self.assertIn('lastUpdated', resource['meta'])
            self.assertIn('extension', resource)
    
    def test_process_partial_extracted_data(self):
        """Test processing with partial data (only medications)."""
        test_data = {
            'patient_id': '456',
            'medications': [
                {
                    'name': 'Aspirin',
                    'dosage': '81mg',
                    'schedule': 'once daily'
                    # Missing route
                }
            ]
            # No other resource types
        }
        
        result = self.processor.process_extracted_data(test_data)
        
        # Should still process the available data
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['resourceType'], 'MedicationStatement')
        self.assertEqual(result[0]['medicationCodeableConcept']['text'], 'Aspirin')
    
    def test_process_empty_data(self):
        """Test processing with empty data."""
        result = self.processor.process_extracted_data({})
        self.assertEqual(len(result), 0)
        
        result = self.processor.process_extracted_data(None)
        self.assertEqual(len(result), 0)
    
    def test_process_with_patient_id_override(self):
        """Test processing with patient_id parameter override."""
        test_data = {
            'patient_id': '123',  # Original ID
            'medications': [
                {
                    'name': 'Test Med',
                    'dosage': '100mg'
                }
            ]
        }
        
        result = self.processor.process_extracted_data(test_data, patient_id='456')
        
        # Should use the override patient_id
        self.assertEqual(len(result), 1)
        self.assertEqual(test_data['patient_id'], '456')  # Should be updated
        
        # Verify the resource references the correct patient
        medication_resource = result[0]
        self.assertEqual(medication_resource['subject']['reference'], 'Patient/456')
    
    def test_error_handling_in_individual_services(self):
        """Test error handling when individual services fail."""
        test_data = {
            'patient_id': '789',
            'medications': [{'name': 'Test Med'}],
            'diagnostic_reports': [{'procedure_type': 'Test'}]
        }
        
        # Mock one service to fail
        with patch.object(self.processor.medication_service, 'process_medications') as mock_med:
            mock_med.side_effect = Exception("Medication service failed")
            
            # Should continue processing other services despite failure
            result = self.processor.process_extracted_data(test_data)
            
            # Should still have diagnostic report (other service worked)
            diagnostic_reports = [r for r in result if r['resourceType'] == 'DiagnosticReport']
            self.assertEqual(len(diagnostic_reports), 1)
    
    def test_get_supported_resource_types(self):
        """Test getting list of supported resource types."""
        supported_types = self.processor.get_supported_resource_types()
        
        expected_types = [
            'MedicationStatement',
            'DiagnosticReport',
            'ServiceRequest',
            'Encounter'
        ]
        
        for expected_type in expected_types:
            self.assertIn(expected_type, supported_types)
    
    def test_validate_processing_capabilities(self):
        """Test validation of processing capabilities."""
        validation = self.processor.validate_processing_capabilities()
        
        self.assertTrue(validation['valid'])
        self.assertEqual(len(validation['services_initialized']), 4)
        self.assertEqual(len(validation['missing_services']), 0)
        self.assertEqual(len(validation['errors']), 0)
        
        # Verify expected services are initialized
        expected_services = [
            'MedicationService',
            'DiagnosticReportService',
            'ServiceRequestService',
            'EncounterService'
        ]
        
        for service in expected_services:
            self.assertIn(service, validation['services_initialized'])
    
    def test_processing_metadata_addition(self):
        """Test that processing metadata is properly added to resources."""
        test_data = {
            'patient_id': '999',
            'medications': [
                {
                    'name': 'Test Medication',
                    'dosage': '50mg'
                }
            ]
        }
        
        result = self.processor.process_extracted_data(test_data)
        
        self.assertEqual(len(result), 1)
        resource = result[0]
        
        # Check meta fields
        self.assertIn('meta', resource)
        self.assertIn('lastUpdated', resource['meta'])
        self.assertIn('source', resource['meta'])
        self.assertEqual(resource['meta']['source'], 'FHIRProcessor')
        self.assertIn('versionId', resource['meta'])
        self.assertIn('tag', resource['meta'])
        
        # Check processing extension
        self.assertIn('extension', resource)
        processing_extensions = [
            ext for ext in resource['extension']
            if ext.get('url') == 'http://meddocparser.local/fhir/StructureDefinition/processing-metadata'
        ]
        self.assertEqual(len(processing_extensions), 1)
        
        processing_ext = processing_extensions[0]
        self.assertIn('extension', processing_ext)
        
        # Check processing metadata fields
        ext_fields = {ext['url']: ext for ext in processing_ext['extension']}
        self.assertIn('processingTimestamp', ext_fields)
        self.assertIn('totalResourcesProcessed', ext_fields)
        self.assertIn('processingVersion', ext_fields)
        
        self.assertEqual(ext_fields['totalResourcesProcessed']['valueInteger'], 1)
        self.assertEqual(ext_fields['processingVersion']['valueString'], '1.0.0')


class FHIRProcessorServiceInitializationTests(TestCase):
    """Test FHIRProcessor service initialization and validation."""
    
    def test_initialization_with_all_services(self):
        """Test that all required services are properly initialized."""
        processor = FHIRProcessor()
        
        # Verify all required services are present
        self.assertIsNotNone(processor.medication_service)
        self.assertIsNotNone(processor.diagnostic_report_service)
        self.assertIsNotNone(processor.service_request_service)
        self.assertIsNotNone(processor.encounter_service)
        
        # Verify service types
        from apps.fhir.services import (
            MedicationService, DiagnosticReportService,
            ServiceRequestService, EncounterService
        )
        
        self.assertIsInstance(processor.medication_service, MedicationService)
        self.assertIsInstance(processor.diagnostic_report_service, DiagnosticReportService)
        self.assertIsInstance(processor.service_request_service, ServiceRequestService)
        self.assertIsInstance(processor.encounter_service, EncounterService)
    
    @patch('apps.fhir.services.fhir_processor.MedicationService')
    def test_initialization_with_service_failure(self, mock_medication_service):
        """Test initialization behavior when a service fails to initialize."""
        # Make MedicationService initialization fail
        mock_medication_service.side_effect = Exception("Service initialization failed")
        
        # Should raise the exception during initialization
        with self.assertRaises(Exception):
            FHIRProcessor()
    
    def test_processor_logging(self):
        """Test that processor logs initialization properly."""
        with patch('apps.fhir.services.fhir_processor.logger') as mock_logger:
            FHIRProcessor()
            
            # Verify initialization was logged
            mock_logger.info.assert_called_with(
                "FHIRProcessor initialized with all available resource services"
            )
