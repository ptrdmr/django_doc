"""
Tests for large document OOM protection (watchdog, size gates, chunker settings).
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.documents.models import Document
from apps.documents.performance import DocumentChunker
from apps.documents.tasks import (
    cleanup_old_documents,
    _check_document_chunk_limit,
    _check_document_text_size_limit,
    _extend_aggregated_from_chunk,
    _process_chunks_streaming,
)
from apps.patients.models import Patient


def _create_user(username='oomtest'):
    return User.objects.create_superuser(
        username=username,
        email=f'{username}@test.com',
        password='pass123',
    )


def _create_patient(user, mrn='OOM-001'):
    return Patient.objects.create(
        first_name='Large',
        last_name='Doc',
        mrn=mrn,
        date_of_birth='1980-01-01',
        gender='M',
        created_by=user,
    )


def _create_document(user, patient, **kwargs):
    pdf_content = b'%PDF-1.4 test content'
    defaults = {
        'filename': 'big_summary.pdf',
        'file': SimpleUploadedFile('big_summary.pdf', pdf_content, content_type='application/pdf'),
        'file_size': 6_432_052,
        'status': 'processing',
        'processing_started_at': timezone.now() - timedelta(minutes=20),
        'processing_attempts': 0,
        'created_by': user,
        'uploaded_by': user,
        'patient': patient,
    }
    defaults.update(kwargs)
    return Document.objects.create(**defaults)


@override_settings(
    STUCK_DOCUMENT_THRESHOLD_MINUTES=15,
    MEDIA_ROOT='/tmp/test_oom_media',
)
class StuckDocumentWatchdogTests(TestCase):
    """Verify the Celery Beat watchdog recovers or fails stuck documents."""

    def setUp(self):
        self.user = _create_user()
        self.patient = _create_patient(self.user)

    @patch('apps.documents.tasks.process_document_async.delay')
    def test_watchdog_requeues_stuck_document_under_max_attempts(self, mock_delay):
        document = _create_document(self.user, self.patient, processing_attempts=1)

        result = cleanup_old_documents()

        document.refresh_from_db()
        self.assertEqual(document.status, 'pending')
        self.assertEqual(document.processing_attempts, 2)
        self.assertIn('recovered=1', result)
        mock_delay.assert_called_once_with(document.id)

    @patch('apps.documents.tasks.process_document_async.delay')
    def test_watchdog_fails_stuck_document_at_max_attempts(self, mock_delay):
        document = _create_document(
            self.user,
            self.patient,
            processing_attempts=3,
        )

        result = cleanup_old_documents()

        document.refresh_from_db()
        self.assertEqual(document.status, 'failed')
        self.assertIn('timed out', document.error_message.lower())
        self.assertIn('failed=1', result)
        mock_delay.assert_not_called()

    def test_watchdog_ignores_recent_processing_documents(self):
        document = _create_document(
            self.user,
            self.patient,
            processing_started_at=timezone.now() - timedelta(minutes=2),
        )

        result = cleanup_old_documents()

        document.refresh_from_db()
        self.assertEqual(document.status, 'processing')
        self.assertIn('recovered=0', result)


@override_settings(
    MAX_DOCUMENT_TEXT_LENGTH=1000,
    MAX_DOCUMENT_CHUNKS=2,
    MEDIA_ROOT='/tmp/test_oom_media',
)
class DocumentSizeGateTests(TestCase):
    """Verify pre-flight text and chunk limits mark documents failed."""

    def setUp(self):
        self.user = _create_user('sizegate')
        self.patient = _create_patient(self.user, mrn='SIZE-001')

    def test_text_size_limit_marks_document_failed(self):
        document = _create_document(
            self.user,
            self.patient,
            status='processing',
            processing_started_at=timezone.now(),
        )

        result = _check_document_text_size_limit(document, 5000, 'test-task')

        self.assertIsNotNone(result)
        self.assertFalse(result['success'])
        document.refresh_from_db()
        self.assertEqual(document.status, 'failed')
        self.assertIn('too large', document.error_message.lower())

    def test_chunk_limit_marks_document_failed(self):
        document = _create_document(
            self.user,
            self.patient,
            status='processing',
            processing_started_at=timezone.now(),
        )

        result = _check_document_chunk_limit(document, 5, 'test-task')

        self.assertIsNotNone(result)
        document.refresh_from_db()
        self.assertEqual(document.status, 'failed')
        self.assertIn('chunks', document.error_message.lower())


@override_settings(
    AI_CHUNK_SIZE=100,
    AI_CHUNK_OVERLAP=25,
)
class DocumentChunkerSettingsTests(TestCase):
    """Verify chunker reads AI_CHUNK_SIZE and AI_CHUNK_OVERLAP from settings."""

    def test_chunker_uses_configured_size_and_overlap(self):
        chunker = DocumentChunker()
        self.assertEqual(chunker.max_chunk_size, 100)
        self.assertEqual(chunker.overlap_size, 25)

        text = 'Sentence one. ' * 30
        chunks = chunker.chunk_text(text, preserve_context=True)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk['text']), 125)


class StreamingChunkAggregationTests(TestCase):
    """Verify streaming aggregation merges chunk output incrementally."""

    @patch('apps.documents.services.ai_extraction.extract_medical_data_structured')
    def test_process_chunks_streaming_aggregates_all_chunks(self, mock_extract):
        mock_result_one = MagicMock()
        mock_result_one.model_dump.return_value = {
            'conditions': [{'name': 'Hypertension', 'confidence': 0.9, 'source': {'text': 'chunk1'}}],
            'medications': [],
            'vital_signs': [],
            'lab_results': [],
            'procedures': [],
            'providers': [],
            'encounters': [],
            'service_requests': [],
            'diagnostic_reports': [],
            'allergies': [],
            'care_plans': [],
            'organizations': [],
            'family_history': [],
            'physical_exam_findings': [],
            'social_history': [],
        }
        mock_result_two = MagicMock()
        mock_result_two.model_dump.return_value = {
            'conditions': [{'name': 'Diabetes', 'confidence': 0.8, 'source': {'text': 'chunk2'}}],
            'medications': [{'name': 'Metformin', 'confidence': 0.85, 'source': {'text': 'chunk2'}}],
            'vital_signs': [],
            'lab_results': [],
            'procedures': [],
            'providers': [],
            'encounters': [],
            'service_requests': [],
            'diagnostic_reports': [],
            'allergies': [],
            'care_plans': [],
            'organizations': [],
            'family_history': [],
            'physical_exam_findings': [],
            'social_history': [],
        }
        mock_extract.side_effect = [mock_result_one, mock_result_two]

        chunks = [
            {'text': 'chunk one text', 'chunk_id': 0},
            {'text': 'chunk two text', 'chunk_id': 1},
        ]
        result, chunk_stats = _process_chunks_streaming(chunks, 'medical_document', 'task-1')

        self.assertEqual(len(result.conditions), 2)
        self.assertEqual(len(result.medications), 1)
        self.assertEqual(mock_extract.call_count, 2)
        self.assertEqual(chunk_stats['total'], 2)
        self.assertEqual(chunk_stats['succeeded'], 2)
        self.assertEqual(chunk_stats['failed_chunks'], [])

    def test_extend_aggregated_from_chunk_skips_invalid_payload(self):
        aggregated = {
            'conditions': [],
            'medications': [],
            'procedures': [],
        }
        _extend_aggregated_from_chunk(aggregated, None)
        _extend_aggregated_from_chunk(aggregated, {'conditions': [{'name': 'Asthma'}]})
        self.assertEqual(len(aggregated['conditions']), 1)


@override_settings(
    LARGE_DOCUMENT_FILE_SIZE_BYTES=1024,
    MEDIA_ROOT='/tmp/test_oom_media',
)
class ProcessingStatusAPITests(TestCase):
    """Verify processing status API exposes watchdog-related fields."""

    def setUp(self):
        self.client = Client()
        self.user = _create_user('statusapi')
        self.patient = _create_patient(self.user, mrn='API-001')
        self.client.force_login(self.user)
        self.url = reverse('documents:api-processing-status')

    def test_processing_status_includes_ocr_pending_and_metadata(self):
        large_pdf = b'%PDF-1.4 ' + (b'x' * 2048)
        document = Document.objects.create(
            filename='ocr_pending.pdf',
            file=SimpleUploadedFile('ocr_pending.pdf', large_pdf, content_type='application/pdf'),
            status='ocr_pending',
            processing_started_at=timezone.now() - timedelta(minutes=3),
            processing_attempts=1,
            processing_message='Running OCR...',
            created_by=self.user,
            uploaded_by=self.user,
            patient=self.patient,
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        matching = [
            item for item in data['processing_documents'] if item['id'] == document.id
        ]
        self.assertEqual(len(matching), 1)
        payload = matching[0]
        self.assertEqual(payload['status'], 'ocr_pending')
        self.assertIn('elapsed_seconds', payload)
        self.assertEqual(payload['processing_attempts'], 1)
        self.assertTrue(payload['is_large_document'])
