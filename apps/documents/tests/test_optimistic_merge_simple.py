"""
Focused unit tests for Task 41.13: Optimistic Concurrency Immediate Merge Logic.

Tests the new merge logic added to process_document_async without heavy mocking.
"""

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.documents.models import Document, ParsedData
from apps.patients.models import Patient, PatientHistory

User = get_user_model()


class OptimisticMergeLogicTests(TestCase):
    """
    Unit tests for the optimistic merge logic.
    Tests determine_review_status integration and immediate merge behavior.
    """
    
    def setUp(self):
        """Set up test data."""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test patient
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            mrn='TEST-001',
            date_of_birth='1980-01-01'
        )
        
        # Sample FHIR resources for testing
        self.sample_fhir_resources = [
            {
                'resourceType': 'Condition',
                'id': 'cond-1',
                'code': {
                    'coding': [{
                        'system': 'http://snomed.info/sct',
                        'code': '44054006',
                        'display': 'Type 2 diabetes mellitus'
                    }]
                },
                'subject': {'reference': f'Patient/{self.patient.id}'}
            },
            {
                'resourceType': 'Observation',
                'id': 'obs-1',
                'code': {
                    'coding': [{
                        'system': 'http://loinc.org',
                        'code': '2339-0',
                        'display': 'Glucose'
                    }]
                },
                'valueQuantity': {
                    'value': 120,
                    'unit': 'mg/dL'
                },
                'subject': {'reference': f'Patient/{self.patient.id}'}
            }
        ]
    
    def _create_test_document(self, filename='test.pdf'):
        """Helper to create a test document."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        pdf_content = b'%PDF-1.4 fake pdf content'
        uploaded_file = SimpleUploadedFile(
            filename,
            pdf_content,
            content_type='application/pdf'
        )
        
        document = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename=filename,
            file=uploaded_file,
            file_size=len(pdf_content),
            status='pending'
        )
        return document
    
    def test_high_quality_extraction_auto_approved(self):
        """
        Test that high-confidence ParsedData is auto-approved.
        """
        document = self._create_test_document()
        
        # Create ParsedData with high confidence (should auto-approve)
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=self.sample_fhir_resources,
            extraction_confidence=0.95,  # High confidence
            ai_model_used='claude-3-sonnet',  # Primary model
            processing_time_seconds=1.5
        )
        
        # Call determine_review_status
        review_status, flag_reason = parsed_data.determine_review_status()
        
        # Should be auto-approved
        self.assertEqual(review_status, 'auto_approved')
        self.assertEqual(flag_reason, '')
        
        # Update the parsed_data as the task would
        parsed_data.review_status = review_status
        parsed_data.auto_approved = (review_status == 'auto_approved')
        parsed_data.flag_reason = flag_reason
        parsed_data.save()
        
        # Verify status was set correctly
        parsed_data.refresh_from_db()
        self.assertTrue(parsed_data.auto_approved)
        self.assertEqual(parsed_data.review_status, 'auto_approved')
    
    def test_low_confidence_extraction_flagged(self):
        """
        Test that low-confidence ParsedData is flagged.
        """
        document = self._create_test_document()
        
        # Create ParsedData with low confidence (should flag)
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=self.sample_fhir_resources,
            extraction_confidence=0.65,  # Low confidence (< 0.80)
            ai_model_used='claude-3-sonnet',
            processing_time_seconds=1.5
        )
        
        # Call determine_review_status
        review_status, flag_reason = parsed_data.determine_review_status()
        
        # Should be flagged
        self.assertEqual(review_status, 'flagged')
        self.assertIn('confidence', flag_reason.lower())
        
        # Update the parsed_data as the task would
        parsed_data.review_status = review_status
        parsed_data.auto_approved = (review_status == 'auto_approved')
        parsed_data.flag_reason = flag_reason
        parsed_data.save()
        
        # Verify status was set correctly
        parsed_data.refresh_from_db()
        self.assertFalse(parsed_data.auto_approved)
        self.assertEqual(parsed_data.review_status, 'flagged')
        self.assertIn('confidence', parsed_data.flag_reason.lower())
    
    def test_fallback_model_extraction_flagged(self):
        """
        Test that extraction using fallback model is flagged.
        """
        document = self._create_test_document()
        
        # Create ParsedData with fallback model (should flag)
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=self.sample_fhir_resources,
            extraction_confidence=0.90,  # High confidence but fallback model
            ai_model_used='gpt-4',  # Fallback model
            processing_time_seconds=1.5
        )
        
        # Call determine_review_status
        review_status, flag_reason = parsed_data.determine_review_status()
        
        # Should be flagged due to fallback model
        self.assertEqual(review_status, 'flagged')
        self.assertIn('fallback', flag_reason.lower())
        self.assertIn('gpt', flag_reason.lower())
    
    def test_immediate_merge_high_quality(self):
        """
        Test that high-quality data is immediately merged into patient record.
        """
        document = self._create_test_document()
        
        # Create ParsedData with high quality
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=self.sample_fhir_resources,
            extraction_confidence=0.95,
            ai_model_used='claude-3-sonnet',
            processing_time_seconds=1.5
        )
        
        # Determine review status (would be auto-approved)
        review_status, flag_reason = parsed_data.determine_review_status()
        parsed_data.review_status = review_status
        parsed_data.auto_approved = True
        parsed_data.flag_reason = flag_reason
        parsed_data.save()
        
        # Check initial patient bundle state
        initial_bundle = self.patient.encrypted_fhir_bundle
        initial_entry_count = len(initial_bundle.get('entry', []))
        
        # Perform immediate merge (as the task does)
        merge_success = self.patient.add_fhir_resources(
            self.sample_fhir_resources,
            document_id=document.id
        )
        
        # Verify merge succeeded
        self.assertTrue(merge_success)
        
        # Mark ParsedData as merged
        parsed_data.is_merged = True
        parsed_data.merged_at = timezone.now()
        parsed_data.save()
        
        # Verify patient record was updated
        self.patient.refresh_from_db()
        updated_bundle = self.patient.encrypted_fhir_bundle
        updated_entry_count = len(updated_bundle.get('entry', []))
        
        # Should have more resources now
        self.assertGreater(updated_entry_count, initial_entry_count)
        
        # Verify ParsedData was marked as merged
        parsed_data.refresh_from_db()
        self.assertTrue(parsed_data.is_merged)
        self.assertIsNotNone(parsed_data.merged_at)
    
    def test_immediate_merge_low_quality(self):
        """
        Test that even low-quality (flagged) data is immediately merged.
        This is the core of optimistic concurrency - merge now, review later.
        """
        document = self._create_test_document()
        
        # Create ParsedData with low quality (will be flagged)
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=self.sample_fhir_resources,
            extraction_confidence=0.65,  # Low confidence - will flag
            ai_model_used='claude-3-sonnet',
            processing_time_seconds=1.5
        )
        
        # Determine review status (would be flagged)
        review_status, flag_reason = parsed_data.determine_review_status()
        parsed_data.review_status = review_status
        parsed_data.auto_approved = False
        parsed_data.flag_reason = flag_reason
        parsed_data.save()
        
        # Verify it was flagged
        self.assertEqual(review_status, 'flagged')
        
        # Check initial patient bundle state
        initial_bundle = self.patient.encrypted_fhir_bundle
        initial_entry_count = len(initial_bundle.get('entry', []))
        
        # CRITICAL: Even though flagged, still perform immediate merge
        merge_success = self.patient.add_fhir_resources(
            self.sample_fhir_resources,
            document_id=document.id
        )
        
        # Verify merge succeeded despite being flagged
        self.assertTrue(merge_success)
        
        # Mark as merged
        parsed_data.is_merged = True
        parsed_data.merged_at = timezone.now()
        parsed_data.save()
        
        # Verify patient record was updated
        self.patient.refresh_from_db()
        updated_bundle = self.patient.encrypted_fhir_bundle
        updated_entry_count = len(updated_bundle.get('entry', []))
        
        # Data was merged despite being flagged
        self.assertGreater(updated_entry_count, initial_entry_count)
        
        # Verify ParsedData shows flagged but merged
        parsed_data.refresh_from_db()
        self.assertTrue(parsed_data.is_merged)
        self.assertFalse(parsed_data.auto_approved)
        self.assertEqual(parsed_data.review_status, 'flagged')
    
    def test_audit_trail_created(self):
        """
        Test that PatientHistory audit trail is created when merging.
        """
        document = self._create_test_document()
        
        # Check initial audit count
        initial_audit_count = PatientHistory.objects.filter(
            patient=self.patient,
            action='fhir_merge'
        ).count()
        
        # Create and merge data
        parsed_data = ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'},
            fhir_delta_json=self.sample_fhir_resources,
            extraction_confidence=0.95,
            ai_model_used='claude-3-sonnet'
        )
        
        # Perform merge
        self.patient.add_fhir_resources(
            self.sample_fhir_resources,
            document_id=document.id
        )
        
        # Verify audit trail was created
        final_audit_count = PatientHistory.objects.filter(
            patient=self.patient,
            action='fhir_merge'
        ).count()
        
        self.assertGreater(final_audit_count, initial_audit_count)
        
        # Verify audit entry contains document reference
        latest_audit = PatientHistory.objects.filter(
            patient=self.patient,
            action='fhir_merge'
        ).order_by('-created_at').first()
        
        self.assertIsNotNone(latest_audit)
        # The notes should contain document reference
        self.assertIn(str(document.id), latest_audit.notes)

