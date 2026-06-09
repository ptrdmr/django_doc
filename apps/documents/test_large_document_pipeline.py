"""
Verification tests for the Large Document Pipeline Overhaul.

Covers the plan's verification checklist:
- Redis/locmem cache write/read round-trip (Phase 0.1 dead-cache fix)
- Immunizations aggregation across chunks (Phase 0.2)
- Exact-match dedupe of labs/vitals/immunizations (Phase 0.5)
- Ledger skip-on-retry — succeeded chunks never re-billed (Phase 3.2)
- Partial completion threshold + failed-chunk continuation (Phase 3.3)
- Soft time limit resume re-enqueue (Phase 3.3)
- Per-document and daily cost circuit breakers (Phase 3.4)
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.models import APIUsageLog
from apps.documents.cache import DocumentProcessingCache
from apps.documents.models import Document, DocumentChunkResult
from apps.documents.services.ai_extraction import AIExtractionError
from apps.documents.tasks import (
    _check_cost_circuit_breaker,
    _chunk_content_hash,
    _create_empty_aggregated_dict,
    _deduplicate_aggregated,
    _extend_aggregated_from_chunk,
    _handle_soft_time_limit,
    _process_chunks_streaming,
)
from apps.patients.models import Patient


def _create_user(username='pipelinetest'):
    return User.objects.create_superuser(
        username=username,
        email=f'{username}@test.com',
        password='pass123',
    )


def _create_patient(user, mrn='PIPE-001'):
    return Patient.objects.create(
        first_name='Pipeline',
        last_name='Test',
        mrn=mrn,
        date_of_birth='1980-01-01',
        gender='M',
        created_by=user,
    )


def _create_document(user, patient, **kwargs):
    defaults = {
        'filename': 'pipeline_test.pdf',
        'file': SimpleUploadedFile(
            'pipeline_test.pdf', b'%PDF-1.4 test', content_type='application/pdf'
        ),
        'file_size': 1024,
        'status': 'processing',
        'created_by': user,
        'uploaded_by': user,
        'patient': patient,
    }
    defaults.update(kwargs)
    return Document.objects.create(**defaults)


def _empty_chunk_dump(**overrides):
    """Minimal valid StructuredMedicalExtraction dump for a chunk."""
    dump = {
        'conditions': [],
        'medications': [],
        'vital_signs': [],
        'lab_results': [],
        'procedures': [],
        'immunizations': [],
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
    dump.update(overrides)
    return dump


class CacheRoundTripTests(TestCase):
    """Phase 0.1: the cache must actually persist (timezone import fix)."""

    def test_ai_extraction_cache_write_then_read_round_trip(self):
        """A cache write must succeed and be readable — before the fix every
        write raised NameError on timezone.now() and was swallowed."""
        doc_cache = DocumentProcessingCache()
        cache_key = doc_cache.get_ai_extraction_cache_key(
            'Patient has hypertension.', 'claude-sonnet-4-5-20250929'
        )

        write_ok = doc_cache.cache_ai_extraction(cache_key, {
            'structured_data': {'conditions': [{'name': 'Hypertension'}]},
            'confidence_average': 0.9,
            'model_used': 'claude-sonnet-4-5-20250929',
            'processing_duration_ms': 1200,
            'field_count': 1,
        })
        self.assertTrue(write_ok, "Cache write failed — timezone regression?")

        cached = doc_cache.get_cached_ai_extraction(cache_key)
        self.assertIsNotNone(cached, "Cache read returned None after successful write")
        self.assertEqual(
            cached['structured_data']['conditions'][0]['name'], 'Hypertension'
        )
        self.assertIn('cache_timestamp', cached)

    def test_cache_key_changes_with_model(self):
        """Different models must produce different cache keys (no cross-model hits)."""
        doc_cache = DocumentProcessingCache()
        key_sonnet = doc_cache.get_ai_extraction_cache_key('same text', 'claude-sonnet-4-5')
        key_haiku = doc_cache.get_ai_extraction_cache_key('same text', 'claude-haiku-4')
        self.assertNotEqual(key_sonnet, key_haiku)


class ImmunizationAggregationTests(TestCase):
    """Phase 0.2: immunizations must survive chunked aggregation."""

    def test_immunizations_key_present_in_empty_aggregate(self):
        aggregated = _create_empty_aggregated_dict()
        self.assertIn('immunizations', aggregated)
        self.assertEqual(aggregated['immunizations'], [])

    def test_immunizations_merged_across_chunks(self):
        """Vaccines from multiple chunks must all land in the aggregate —
        previously they were silently dropped on every chunked document."""
        aggregated = _create_empty_aggregated_dict()
        _extend_aggregated_from_chunk(aggregated, _empty_chunk_dump(
            immunizations=[{
                'vaccine_name': 'Influenza', 'date_administered': '2025-10-01',
                'confidence': 0.9, 'source': {'text': 'chunk1'},
            }],
        ))
        _extend_aggregated_from_chunk(aggregated, _empty_chunk_dump(
            immunizations=[{
                'vaccine_name': 'Tdap', 'date_administered': '2024-03-15',
                'confidence': 0.85, 'source': {'text': 'chunk2'},
            }],
        ))

        self.assertEqual(len(aggregated['immunizations']), 2)
        names = {item['vaccine_name'] for item in aggregated['immunizations']}
        self.assertEqual(names, {'Influenza', 'Tdap'})


class ExactDedupTests(TestCase):
    """Phase 0.5: overlap-zone duplicates removed; distinct measurements kept."""

    def test_duplicate_labs_from_overlap_removed(self):
        aggregated = _create_empty_aggregated_dict()
        duplicate_lab = {
            'test_name': 'Glucose', 'value': '105', 'test_date': '2025-06-01',
            'confidence': 0.9, 'source': {'text': 'overlap zone'},
        }
        aggregated['lab_results'] = [duplicate_lab, dict(duplicate_lab)]

        _deduplicate_aggregated(aggregated)

        self.assertEqual(len(aggregated['lab_results']), 1)

    def test_distinct_lab_draws_not_merged(self):
        """Two glucose draws with different values/dates are NOT duplicates —
        fuzzy matching would wrongly merge them; exact matching must not."""
        aggregated = _create_empty_aggregated_dict()
        aggregated['lab_results'] = [
            {'test_name': 'Glucose', 'value': '105', 'test_date': '2025-06-01',
             'confidence': 0.9, 'source': {'text': 'am draw'}},
            {'test_name': 'Glucose', 'value': '142', 'test_date': '2025-06-01',
             'confidence': 0.9, 'source': {'text': 'pm draw'}},
            {'test_name': 'Glucose', 'value': '105', 'test_date': '2025-06-02',
             'confidence': 0.9, 'source': {'text': 'next day'}},
        ]

        _deduplicate_aggregated(aggregated)

        self.assertEqual(len(aggregated['lab_results']), 3)

    def test_duplicate_vitals_and_immunizations_removed(self):
        aggregated = _create_empty_aggregated_dict()
        vital = {
            'measurement': 'Blood Pressure', 'value': '120/80', 'timestamp': '2025-06-01',
            'confidence': 0.9, 'source': {'text': 'overlap'},
        }
        shot = {
            'vaccine_name': 'Influenza', 'date_administered': '2025-10-01',
            'confidence': 0.9, 'source': {'text': 'overlap'},
        }
        aggregated['vital_signs'] = [vital, dict(vital)]
        aggregated['immunizations'] = [shot, dict(shot)]

        _deduplicate_aggregated(aggregated)

        self.assertEqual(len(aggregated['vital_signs']), 1)
        self.assertEqual(len(aggregated['immunizations']), 1)


@override_settings(MEDIA_ROOT='/tmp/test_pipeline_media')
class LedgerSkipOnRetryTests(TestCase):
    """Phase 3.2: succeeded ledger rows must skip the API entirely."""

    def setUp(self):
        self.user = _create_user('ledgertest')
        self.patient = _create_patient(self.user, mrn='LEDGER-001')
        self.document = _create_document(self.user, self.patient)

    @patch('apps.documents.services.ai_extraction.extract_medical_data_structured')
    def test_succeeded_chunk_skips_api_call(self, mock_extract):
        """Retry of a document with one checkpointed chunk must only call the
        API for the remaining chunk — this is the no-re-billing guarantee."""
        from django.conf import settings
        model = getattr(settings, 'AI_MODEL_PRIMARY', 'claude-sonnet-4-5-20250929')

        chunk_one_text = 'chunk one already done'
        DocumentChunkResult.objects.create(
            document=self.document,
            chunk_index=0,
            content_hash=_chunk_content_hash(chunk_one_text, model),
            status='succeeded',
            structured_json=_empty_chunk_dump(conditions=[{
                'name': 'Hypertension', 'confidence': 0.9,
                'source': {'text': 'from ledger'},
            }]),
            attempts=1,
        )

        fresh_result = MagicMock()
        fresh_result.model_dump.return_value = _empty_chunk_dump(conditions=[{
            'name': 'Diabetes', 'confidence': 0.85, 'source': {'text': 'fresh'},
        }])
        mock_extract.return_value = fresh_result

        chunks = [
            {'text': chunk_one_text, 'chunk_id': 0},
            {'text': 'chunk two needs processing', 'chunk_id': 1},
        ]
        result, chunk_stats = _process_chunks_streaming(
            chunks, 'medical_document', 'task-ledger', document=self.document
        )

        # Only chunk two hit the API
        self.assertEqual(mock_extract.call_count, 1)
        self.assertEqual(chunk_stats['ledger_hits'], 1)
        self.assertEqual(chunk_stats['succeeded'], 2)
        # Both chunks' data made it into the aggregate
        names = {c.name for c in result.conditions}
        self.assertEqual(names, {'Hypertension', 'Diabetes'})

    @patch('apps.documents.services.ai_extraction.extract_medical_data_structured')
    def test_stale_hash_invalidates_checkpoint(self, mock_extract):
        """A ledger row whose hash doesn't match the current text/model must
        NOT be used — config/prompt changes correctly force re-extraction."""
        DocumentChunkResult.objects.create(
            document=self.document,
            chunk_index=0,
            content_hash='0' * 64,  # stale hash from an old prompt version
            status='succeeded',
            structured_json=_empty_chunk_dump(),
            attempts=1,
        )

        fresh_result = MagicMock()
        fresh_result.model_dump.return_value = _empty_chunk_dump(conditions=[{
            'name': 'Asthma', 'confidence': 0.9, 'source': {'text': 'fresh'},
        }])
        mock_extract.return_value = fresh_result

        chunks = [{'text': 'text that does not match stale hash', 'chunk_id': 0}]
        result, chunk_stats = _process_chunks_streaming(
            chunks, 'medical_document', 'task-stale', document=self.document
        )

        self.assertEqual(mock_extract.call_count, 1)
        self.assertEqual(chunk_stats['ledger_hits'], 0)
        self.assertEqual(result.conditions[0].name, 'Asthma')

    @patch('apps.documents.services.ai_extraction.extract_medical_data_structured')
    def test_each_chunk_persisted_immediately(self, mock_extract):
        """Every processed chunk must leave a succeeded ledger row with
        attempts incremented — a mid-run kill loses nothing."""
        fresh_result = MagicMock()
        fresh_result.model_dump.return_value = _empty_chunk_dump()
        mock_extract.return_value = fresh_result

        chunks = [
            {'text': 'chunk a', 'chunk_id': 0},
            {'text': 'chunk b', 'chunk_id': 1},
        ]
        _process_chunks_streaming(
            chunks, 'medical_document', 'task-persist', document=self.document
        )

        rows = DocumentChunkResult.objects.filter(document=self.document)
        self.assertEqual(rows.count(), 2)
        for row in rows:
            self.assertEqual(row.status, 'succeeded')
            self.assertEqual(row.attempts, 1)


@override_settings(MEDIA_ROOT='/tmp/test_pipeline_media')
class PartialCompletionTests(TestCase):
    """Phase 3.3: failed chunks recorded, processing continues, threshold enforced."""

    def setUp(self):
        self.user = _create_user('partialtest')
        self.patient = _create_patient(self.user, mrn='PART-001')
        self.document = _create_document(self.user, self.patient)

    @override_settings(AI_CHUNK_PARTIAL_THRESHOLD=0.5)
    @patch('apps.documents.services.ai_extraction.extract_medical_data_structured')
    def test_failed_chunk_recorded_and_processing_continues(self, mock_extract):
        """One failed chunk of two (50% >= threshold 0.5) yields a partial
        result with the failure tracked in chunk_stats and the ledger."""
        good_result = MagicMock()
        good_result.model_dump.return_value = _empty_chunk_dump(conditions=[{
            'name': 'Hypertension', 'confidence': 0.9, 'source': {'text': 'good'},
        }])
        mock_extract.side_effect = [RuntimeError('API exploded'), good_result]

        chunks = [
            {'text': 'failing chunk', 'chunk_id': 0},
            {'text': 'good chunk', 'chunk_id': 1},
        ]
        result, chunk_stats = _process_chunks_streaming(
            chunks, 'medical_document', 'task-partial', document=self.document
        )

        self.assertEqual(chunk_stats['failed_chunks'], [0])
        self.assertEqual(chunk_stats['succeeded'], 1)
        self.assertEqual(len(result.conditions), 1)

        failed_row = DocumentChunkResult.objects.get(
            document=self.document, chunk_index=0
        )
        self.assertEqual(failed_row.status, 'failed')
        self.assertIn('API exploded', failed_row.error_message)
        self.assertEqual(failed_row.attempts, 1)

    @override_settings(AI_CHUNK_PARTIAL_THRESHOLD=0.85)
    @patch('apps.documents.services.ai_extraction.extract_medical_data_structured')
    def test_below_threshold_raises(self, mock_extract):
        """1/2 chunks (50%) below the 85% threshold must fail loudly, with
        the succeeded chunk still checkpointed for a cheap retry."""
        good_result = MagicMock()
        good_result.model_dump.return_value = _empty_chunk_dump()
        mock_extract.side_effect = [good_result, RuntimeError('API exploded')]

        chunks = [
            {'text': 'good chunk', 'chunk_id': 0},
            {'text': 'failing chunk', 'chunk_id': 1},
        ]
        with self.assertRaises(AIExtractionError) as ctx:
            _process_chunks_streaming(
                chunks, 'medical_document', 'task-threshold', document=self.document
            )
        self.assertIn('1/2', str(ctx.exception))

        # Succeeded chunk is checkpointed — retry will only pay for chunk 1
        self.assertTrue(
            DocumentChunkResult.objects.filter(
                document=self.document, chunk_index=0, status='succeeded'
            ).exists()
        )


@override_settings(MEDIA_ROOT='/tmp/test_pipeline_media')
class SoftTimeLimitResumeTests(TestCase):
    """Phase 3.3: soft time limit re-enqueues a resume run, then fails after max."""

    def setUp(self):
        self.user = _create_user('resumetest')
        self.patient = _create_patient(self.user, mrn='RESUME-001')
        self.document = _create_document(
            self.user, self.patient, original_text='saved text for resume'
        )

    @override_settings(LARGE_DOCUMENT_MAX_RESUMES=2)
    @patch('apps.documents.tasks.continue_document_processing.apply_async')
    def test_first_soft_limit_enqueues_resume(self, mock_apply_async):
        result = _handle_soft_time_limit(
            self.document.id, 'task-stl', total_time=600.0, resume_attempt=0
        )

        self.assertEqual(result['status'], 'resuming')
        self.assertEqual(result['resume_attempt'], 1)
        mock_apply_async.assert_called_once()
        call_kwargs = mock_apply_async.call_args.kwargs
        self.assertEqual(call_kwargs['args'], [self.document.id, ''])
        self.assertEqual(call_kwargs['kwargs'], {'resume_attempt': 1})

        self.document.refresh_from_db()
        self.assertNotEqual(self.document.status, 'failed')

    @override_settings(LARGE_DOCUMENT_MAX_RESUMES=2)
    @patch('apps.documents.tasks.continue_document_processing.apply_async')
    def test_exhausted_resumes_marks_failed(self, mock_apply_async):
        result = _handle_soft_time_limit(
            self.document.id, 'task-stl', total_time=600.0, resume_attempt=2
        )

        self.assertEqual(result['status'], 'failed')
        mock_apply_async.assert_not_called()

        self.document.refresh_from_db()
        self.assertEqual(self.document.status, 'failed')
        self.assertIn('timed out', self.document.error_message.lower())


@override_settings(MEDIA_ROOT='/tmp/test_pipeline_media')
class CostCircuitBreakerTests(TestCase):
    """Phase 3.4: spend limits halt processing before the next API call."""

    def setUp(self):
        self.user = _create_user('costtest')
        self.patient = _create_patient(self.user, mrn='COST-001')
        self.document = _create_document(self.user, self.patient)

    @override_settings(AI_PER_DOCUMENT_COST_LIMIT=1.00, AI_DAILY_COST_LIMIT=100.00)
    def test_per_document_limit_halts_processing(self):
        DocumentChunkResult.objects.create(
            document=self.document,
            chunk_index=0,
            content_hash='a' * 64,
            status='succeeded',
            structured_json={},
            cost_usd=Decimal('1.25'),
        )

        with self.assertRaises(AIExtractionError) as ctx:
            _check_cost_circuit_breaker(self.document, 'task-cost')
        self.assertIn('Per-document AI cost limit', str(ctx.exception))

    @override_settings(AI_PER_DOCUMENT_COST_LIMIT=5.00, AI_DAILY_COST_LIMIT=0.50)
    def test_daily_limit_halts_processing(self):
        APIUsageLog.objects.create(
            document=self.document,
            patient=self.patient,
            processing_session='11111111-1111-1111-1111-111111111111',
            provider='anthropic',
            model='claude-sonnet-4-5-20250929',
            input_tokens=100000,
            output_tokens=20000,
            total_tokens=120000,
            cost_usd=Decimal('0.60'),
            processing_started=timezone.now(),
            processing_completed=timezone.now(),
            processing_duration_ms=5000,
            success=True,
        )

        with self.assertRaises(AIExtractionError) as ctx:
            _check_cost_circuit_breaker(self.document, 'task-cost')
        self.assertIn('Daily AI cost limit', str(ctx.exception))

    @override_settings(AI_PER_DOCUMENT_COST_LIMIT=5.00, AI_DAILY_COST_LIMIT=100.00)
    def test_under_limits_passes(self):
        DocumentChunkResult.objects.create(
            document=self.document,
            chunk_index=0,
            content_hash='b' * 64,
            status='succeeded',
            structured_json={},
            cost_usd=Decimal('0.10'),
        )
        # Must not raise
        _check_cost_circuit_breaker(self.document, 'task-cost')

    @override_settings(AI_PER_DOCUMENT_COST_LIMIT=0.01)
    @patch('apps.documents.services.ai_extraction.extract_medical_data_structured')
    def test_breaker_checked_before_api_call(self, mock_extract):
        """The breaker must trip BEFORE the chunk API call, not after."""
        DocumentChunkResult.objects.create(
            document=self.document,
            chunk_index=5,
            content_hash='c' * 64,
            status='succeeded',
            structured_json={},
            cost_usd=Decimal('2.00'),
        )

        chunks = [{'text': 'would cost money', 'chunk_id': 0}]
        with self.assertRaises(AIExtractionError):
            _process_chunks_streaming(
                chunks, 'medical_document', 'task-preflight', document=self.document
            )
        mock_extract.assert_not_called()
