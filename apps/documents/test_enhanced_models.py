"""
Test suite for enhanced Document and ParsedData models with structured data support.
Tests the new fields added in subtask 34.6 for structured extraction data storage.
"""

import json
from datetime import datetime
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile

from apps.documents.models import Document, ParsedData
from apps.patients.models import Patient
from apps.providers.models import Provider

User = get_user_model()


class EnhancedDocumentModelTest(TestCase):
    """Test enhanced Document model with structured data fields."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            mrn='TEST123',
            created_by=self.user
        )
        
        # Create a test PDF file
        pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\nxref\n0 3\n0000000000 65535 f \ntrailer\n<<\n/Size 3\n/Root 1 0 R\n>>\nstartxref\n9\n%%EOF"
        self.test_file = ContentFile(pdf_content, name='test_document.pdf')
    
    def test_structured_data_field_creation(self):
        """Test that structured_data field can store Pydantic data."""
        document = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test_document.pdf',
            file=self.test_file
        )
        
        # Test structured data storage
        structured_data = {
            'conditions': [
                {
                    'name': 'Type 2 diabetes',
                    'status': 'active',
                    'confidence': 0.95,
                    'source': {
                        'text': 'Patient has type 2 diabetes',
                        'start_index': 10,
                        'end_index': 35
                    }
                }
            ],
            'medications': [
                {
                    'name': 'Metformin',
                    'dosage': '500mg',
                    'frequency': 'twice daily',
                    'confidence': 0.90,
                    'source': {
                        'text': 'Prescribed Metformin 500mg twice daily',
                        'start_index': 50,
                        'end_index': 88
                    }
                }
            ],
            'confidence_average': 0.925
        }
        
        document.structured_data = structured_data
        document.save()
        
        # Verify data was saved and encrypted
        document.refresh_from_db()
        self.assertTrue(document.has_structured_data())
        self.assertEqual(document.get_extraction_confidence(), 0.925)
        
        # Test resource counts
        resource_counts = document.get_extracted_resource_counts()
        self.assertEqual(resource_counts['conditions'], 1)
        self.assertEqual(resource_counts['medications'], 1)
        self.assertEqual(resource_counts['vital_signs'], 0)
    
    def test_processing_time_ms_field(self):
        """Test processing_time_ms field functionality."""
        document = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test_document.pdf',
            file=self.test_file,
            processing_time_ms=2500  # 2.5 seconds
        )
        
        # Test time conversion
        self.assertEqual(document.get_ai_processing_time_seconds(), 2.5)
        
        # Test None handling
        document.processing_time_ms = None
        document.save()
        self.assertIsNone(document.get_ai_processing_time_seconds())
    
    def test_error_log_functionality(self):
        """Test error_log field and utility methods."""
        document = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test_document.pdf',
            file=self.test_file
        )
        
        # Test adding errors to log
        document.add_error_to_log(
            error_type='ai_extraction',
            error_message='API rate limit exceeded',
            context={'model': 'claude-3-sonnet', 'retry_count': 1}
        )
        
        document.add_error_to_log(
            error_type='fhir_conversion',
            error_message='Invalid resource type',
            context={'resource': 'Condition'}
        )
        
        # Verify error log structure
        document.refresh_from_db()
        self.assertEqual(len(document.error_log), 2)
        
        # Check first error
        first_error = document.error_log[0]
        self.assertEqual(first_error['type'], 'ai_extraction')
        self.assertEqual(first_error['message'], 'API rate limit exceeded')
        self.assertEqual(first_error['context']['model'], 'claude-3-sonnet')
        self.assertIn('timestamp', first_error)
        
        # Check second error
        second_error = document.error_log[1]
        self.assertEqual(second_error['type'], 'fhir_conversion')
        self.assertEqual(second_error['message'], 'Invalid resource type')
    
    def test_document_model_backward_compatibility(self):
        """Test that existing Document functionality still works."""
        document = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test_document.pdf',
            file=self.test_file
        )
        
        # Test existing methods still work
        self.assertIsNone(document.get_processing_duration())
        self.assertTrue(document.can_retry_processing())
        
        # Test status transitions
        document.status = 'processing'
        document.save()
        
        document.status = 'completed'
        document.save()
        
        # Verify timestamps were set
        document.refresh_from_db()
        self.assertIsNotNone(document.processing_started_at)
        self.assertIsNotNone(document.processed_at)


class EnhancedParsedDataModelTest(TestCase):
    """Test enhanced ParsedData model with structured extraction metadata."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            mrn='TEST123',
            created_by=self.user
        )
        
        # Create a test PDF file
        pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\nxref\n0 3\n0000000000 65535 f \ntrailer\n<<\n/Size 3\n/Root 1 0 R\n>>\nstartxref\n9\n%%EOF"
        test_file = ContentFile(pdf_content, name='test_document.pdf')
        
        self.document = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test_document.pdf',
            file=test_file
        )
    
    def test_structured_extraction_metadata_field(self):
        """Test structured_extraction_metadata field functionality."""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            created_by=self.user
        )
        
        # Test metadata storage
        metadata = {
            'resource_counts': {
                'conditions': 2,
                'medications': 3,
                'vital_signs': 1,
                'lab_results': 4
            },
            'extraction_session_id': 'session_12345',
            'ai_model_version': 'claude-3-sonnet-20240229',
            'validation_passed': True,
            'processing_flags': ['high_confidence', 'complete_extraction']
        }
        
        parsed_data.structured_extraction_metadata = metadata
        parsed_data.extraction_confidence = 0.85
        parsed_data.save()
        
        # Test summary generation
        summary = parsed_data.get_structured_data_summary()
        self.assertTrue(summary['has_structured_data'])
        self.assertEqual(summary['resource_counts']['conditions'], 2)
        self.assertEqual(summary['resource_counts']['medications'], 3)
        self.assertEqual(summary['total_resources'], 10)
        self.assertEqual(summary['extraction_method'], 'primary')
        self.assertEqual(summary['confidence_score'], 0.85)
    
    def test_fallback_method_tracking(self):
        """Test fallback_method_used field functionality."""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            created_by=self.user,
            fallback_method_used='gpt-fallback'
        )
        
        # Test fallback detection
        self.assertTrue(parsed_data.was_fallback_extraction_used())
        
        # Test summary with fallback
        summary = parsed_data.get_structured_data_summary()
        self.assertEqual(summary['extraction_method'], 'gpt-fallback')
        
        # Test no fallback
        parsed_data.fallback_method_used = ''
        parsed_data.save()
        self.assertFalse(parsed_data.was_fallback_extraction_used())
    
    def test_extraction_quality_indicators(self):
        """Test quality indicator assessment functionality."""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            created_by=self.user,
            extraction_confidence=0.95,
            extraction_quality_score=0.88,
            fallback_method_used=''
        )
        
        # Set up FHIR data for resource count
        parsed_data.fhir_delta_json = [
            {'resourceType': 'Condition', 'id': '1'},
            {'resourceType': 'MedicationStatement', 'id': '2'}
        ]
        parsed_data.save()
        
        # Test quality indicators
        indicators = parsed_data.get_extraction_quality_indicators()
        
        self.assertEqual(indicators['confidence_level'], 'high')
        self.assertFalse(indicators['needs_review'])  # High confidence = no review needed
        self.assertFalse(indicators['fallback_used'])
        self.assertEqual(indicators['resource_count'], 2)
        self.assertEqual(indicators['quality_score'], 0.88)
    
    def test_quality_indicators_medium_confidence(self):
        """Test quality indicators with medium confidence."""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            created_by=self.user,
            extraction_confidence=0.75,  # Medium confidence
            fallback_method_used='regex'
        )
        
        indicators = parsed_data.get_extraction_quality_indicators()
        
        self.assertEqual(indicators['confidence_level'], 'medium')
        self.assertTrue(indicators['needs_review'])  # Medium confidence = needs review
        self.assertTrue(indicators['fallback_used'])
    
    def test_quality_indicators_low_confidence(self):
        """Test quality indicators with low confidence."""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            created_by=self.user,
            extraction_confidence=0.45  # Low confidence
        )
        
        indicators = parsed_data.get_extraction_quality_indicators()
        
        self.assertEqual(indicators['confidence_level'], 'low')
        self.assertTrue(indicators['needs_review'])  # Low confidence = needs review
    
    def test_enhanced_corrections_field(self):
        """Test that corrections field can store structured data."""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            created_by=self.user
        )
        
        # Test storing structured data in corrections
        structured_corrections = {
            'original_structured_data': {
                'conditions': [{'name': 'diabetes', 'confidence': 0.8}],
                'medications': [{'name': 'metformin', 'dosage': '500mg'}]
            },
            'manual_corrections': {
                'conditions': [{'name': 'Type 2 diabetes mellitus', 'confidence': 1.0}],
                'medications': [{'name': 'Metformin', 'dosage': '500mg', 'frequency': 'twice daily'}]
            },
            'correction_metadata': {
                'corrected_by': 'user123',
                'correction_timestamp': timezone.now().isoformat(),
                'correction_reason': 'Improved specificity and added missing frequency'
            }
        }
        
        parsed_data.corrections = structured_corrections
        parsed_data.save()
        
        # Verify data storage
        parsed_data.refresh_from_db()
        self.assertIn('original_structured_data', parsed_data.corrections)
        self.assertIn('manual_corrections', parsed_data.corrections)
        self.assertEqual(
            parsed_data.corrections['manual_corrections']['conditions'][0]['name'],
            'Type 2 diabetes mellitus'
        )
    
    def test_existing_parsed_data_functionality(self):
        """Test that existing ParsedData functionality still works."""
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            created_by=self.user,
            extraction_confidence=0.9
        )
        
        # Test existing methods
        self.assertTrue(parsed_data.has_high_confidence_extraction())
        
        # Test approval workflow
        parsed_data.approve_extraction(self.user, "Reviewed and approved")
        self.assertTrue(parsed_data.is_approved)
        self.assertEqual(parsed_data.reviewed_by, self.user)
        self.assertIsNotNone(parsed_data.reviewed_at)
        
        # Test merging workflow
        parsed_data.mark_as_merged(self.user)
        self.assertTrue(parsed_data.is_merged)
        self.assertIsNotNone(parsed_data.merged_at)


class DocumentModelIntegrationTest(TestCase):
    """Integration tests for Document and ParsedData models working together."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            mrn='TEST123',
            created_by=self.user
        )
    
    def test_document_to_parsed_data_workflow(self):
        """Test the complete workflow from Document to ParsedData."""
        # Create document with structured data
        pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\nxref\n0 3\n0000000000 65535 f \ntrailer\n<<\n/Size 3\n/Root 1 0 R\n>>\nstartxref\n9\n%%EOF"
        test_file = ContentFile(pdf_content, name='test_document.pdf')
        
        document = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test_document.pdf',
            file=test_file,
            processing_time_ms=3500
        )
        
        # Add structured data to document
        structured_data = {
            'conditions': [
                {'name': 'Hypertension', 'confidence': 0.92},
                {'name': 'Type 2 diabetes', 'confidence': 0.88}
            ],
            'medications': [
                {'name': 'Lisinopril', 'dosage': '10mg', 'confidence': 0.95}
            ],
            'confidence_average': 0.92
        }
        document.structured_data = structured_data
        document.save()
        
        # Create corresponding ParsedData
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            created_by=self.user,
            extraction_confidence=document.get_extraction_confidence(),
            processing_time_seconds=document.get_ai_processing_time_seconds(),
            structured_extraction_metadata={
                'resource_counts': document.get_extracted_resource_counts(),
                'processing_time_ms': document.processing_time_ms,
                'extraction_method': 'claude-structured'
            }
        )
        
        # Verify integration
        self.assertEqual(parsed_data.extraction_confidence, 0.92)
        self.assertEqual(parsed_data.processing_time_seconds, 3.5)
        
        summary = parsed_data.get_structured_data_summary()
        self.assertEqual(summary['resource_counts']['conditions'], 2)
        self.assertEqual(summary['resource_counts']['medications'], 1)
        self.assertEqual(summary['confidence_score'], 0.92)
        
        indicators = parsed_data.get_extraction_quality_indicators()
        self.assertEqual(indicators['confidence_level'], 'high')
        self.assertFalse(indicators['needs_review'])
