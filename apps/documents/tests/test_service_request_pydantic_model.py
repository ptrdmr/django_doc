"""
Tests for ServiceRequest Pydantic model (Task 40.10)

Verifies that the ServiceRequest Pydantic model:
1. Validates correctly with valid data
2. Rejects invalid data appropriately
3. Serializes/deserializes properly
4. Integrates into StructuredMedicalExtraction
"""

import unittest
from pydantic import ValidationError
from apps.documents.services.ai_extraction import ServiceRequest, StructuredMedicalExtraction, SourceContext


class ServiceRequestPydanticModelTests(unittest.TestCase):
    """Test ServiceRequest Pydantic model validation and integration."""
    
    def test_service_request_model_valid_full_data(self):
        """Test ServiceRequest model with all fields populated."""
        service_request = ServiceRequest(
            request_id='req-001',
            request_type='imaging study',
            requester='Dr. Johnson',
            reason='Suspected fracture',
            priority='urgent',
            clinical_context='Patient fell yesterday, pain in left wrist',
            request_date='2024-10-28',
            confidence=0.95,
            source=SourceContext(
                text='Order for urgent X-ray of left wrist by Dr. Johnson',
                start_index=200,
                end_index=253
            )
        )
        
        # Verify all fields set correctly
        self.assertEqual(service_request.request_id, 'req-001')
        self.assertEqual(service_request.request_type, 'imaging study')
        self.assertEqual(service_request.requester, 'Dr. Johnson')
        self.assertEqual(service_request.reason, 'Suspected fracture')
        self.assertEqual(service_request.priority, 'urgent')
        self.assertEqual(service_request.clinical_context, 'Patient fell yesterday, pain in left wrist')
        self.assertEqual(service_request.request_date, '2024-10-28')
        self.assertEqual(service_request.confidence, 0.95)
    
    def test_service_request_model_minimal_required_data(self):
        """Test ServiceRequest model with only required fields."""
        service_request = ServiceRequest(
            request_type='lab test',
            confidence=0.88,
            source=SourceContext(
                text='Order CBC',
                start_index=0,
                end_index=9
            )
        )
        
        # Verify required field
        self.assertEqual(service_request.request_type, 'lab test')
        
        # Verify optional fields default properly
        self.assertIsNone(service_request.request_id)
        self.assertIsNone(service_request.requester)
        self.assertIsNone(service_request.reason)
        self.assertIsNone(service_request.priority)
        self.assertIsNone(service_request.clinical_context)
        self.assertIsNone(service_request.request_date)
    
    def test_service_request_model_missing_required_field(self):
        """Test that missing request_type raises ValidationError."""
        with self.assertRaises(ValidationError) as context:
            ServiceRequest(
                # Missing required request_type
                requester='Dr. Smith',
                confidence=0.9,
                source=SourceContext(text='test', start_index=0, end_index=4)
            )
        
        # Verify error message mentions the missing field
        self.assertIn('request_type', str(context.exception))
    
    def test_service_request_model_invalid_confidence(self):
        """Test that confidence outside 0.0-1.0 range raises ValidationError."""
        with self.assertRaises(ValidationError):
            ServiceRequest(
                request_type='referral',
                confidence=1.2,  # Invalid: > 1.0
                source=SourceContext(text='test', start_index=0, end_index=4)
            )
    
    def test_service_request_serialization(self):
        """Test that ServiceRequest serializes to dict correctly."""
        service_request = ServiceRequest(
            request_type='referral',
            requester='Dr. Brown',
            reason='Cardiology evaluation',
            priority='routine',
            request_date='2024-10-25',
            confidence=0.91,
            source=SourceContext(text='referral to cardiology', start_index=50, end_index=72)
        )
        
        request_dict = service_request.model_dump()
        
        # Verify dict structure
        self.assertIsInstance(request_dict, dict)
        self.assertEqual(request_dict['request_type'], 'referral')
        self.assertEqual(request_dict['requester'], 'Dr. Brown')
        self.assertEqual(request_dict['reason'], 'Cardiology evaluation')
        self.assertEqual(request_dict['priority'], 'routine')
        self.assertEqual(request_dict['confidence'], 0.91)
    
    def test_service_request_deserialization(self):
        """Test that ServiceRequest can be created from dict."""
        request_dict = {
            'request_type': 'consultation',
            'requester': 'Dr. Wilson',
            'reason': 'Complex case review',
            'priority': 'urgent',
            'request_date': '2024-10-27',
            'confidence': 0.93,
            'source': {
                'text': 'Urgent consult requested',
                'start_index': 100,
                'end_index': 124
            }
        }
        
        service_request = ServiceRequest(**request_dict)
        
        # Verify deserialization worked
        self.assertEqual(service_request.request_type, 'consultation')
        self.assertEqual(service_request.priority, 'urgent')
    
    def test_service_request_in_structured_extraction(self):
        """Test ServiceRequest integration into StructuredMedicalExtraction."""
        extraction = StructuredMedicalExtraction(
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[],
            procedures=[],
            providers=[],
            encounters=[],
            service_requests=[
                ServiceRequest(
                    request_type='lab test',
                    requester='Dr. Martinez',
                    reason='Follow-up monitoring',
                    confidence=0.92,
                    source=SourceContext(text='lab order', start_index=0, end_index=9)
                )
            ],
            extraction_timestamp='2024-10-29T12:00:00',
            document_type='clinical_note'
        )
        
        # Verify service request in extraction
        self.assertEqual(len(extraction.service_requests), 1)
        self.assertEqual(extraction.service_requests[0].request_type, 'lab test')
        self.assertEqual(extraction.service_requests[0].requester, 'Dr. Martinez')
    
    def test_confidence_average_includes_service_requests(self):
        """Test that confidence_average calculation includes service requests."""
        extraction = StructuredMedicalExtraction(
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[],
            procedures=[],
            providers=[],
            encounters=[],
            service_requests=[
                ServiceRequest(
                    request_type='lab test',
                    confidence=0.85,
                    source=SourceContext(text='test1', start_index=0, end_index=5)
                ),
                ServiceRequest(
                    request_type='imaging',
                    confidence=0.95,
                    source=SourceContext(text='test2', start_index=6, end_index=11)
                )
            ],
            extraction_timestamp='2024-10-29T12:00:00'
        )
        
        # Confidence average should be (0.85 + 0.95) / 2 = 0.90
        self.assertEqual(extraction.confidence_average, 0.900)


if __name__ == '__main__':
    unittest.main()

