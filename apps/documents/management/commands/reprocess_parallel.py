"""
One-off management command to reprocess a document with parallel chunk extraction.

Fires all chunks to the AI simultaneously using ThreadPoolExecutor,
with an explicit HTTP timeout to prevent hangs.

Usage:
    docker-compose exec web python manage.py reprocess_parallel 109
"""
import time
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
import instructor
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Reprocess a document with parallel AI chunk extraction'

    def add_arguments(self, parser):
        parser.add_argument('document_id', type=int)
        parser.add_argument(
            '--max-workers', type=int, default=0,
            help='Max parallel API calls (0 = one per chunk)',
        )
        parser.add_argument(
            '--timeout', type=int, default=120,
            help='HTTP read timeout per API call in seconds (default 120)',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Chunk the document and report plan without calling the API',
        )

    def handle(self, *args, **options):
        document_id = options['document_id']
        api_timeout = options['timeout']
        dry_run = options['dry_run']

        from apps.documents.models import Document, ParsedData
        from apps.documents.performance import document_chunker
        from apps.documents.tasks import (
            _create_empty_aggregated_dict,
            _extend_aggregated_from_chunk,
            _deduplicate_aggregated,
            _build_clinical_date_defaults,
        )
        from apps.documents.services.ai_extraction import (
            StructuredMedicalExtraction,
        )

        # ── Load document ───────────────────────────────────────────
        try:
            document = Document.objects.select_related('patient').get(id=document_id)
        except Document.DoesNotExist:
            raise CommandError(f'Document {document_id} does not exist')

        text = document.original_text
        if not text:
            raise CommandError(f'Document {document_id} has no extracted text')

        self.stdout.write(f'Document {document_id}: {len(text):,} chars, '
                          f'patient {document.patient.mrn if document.patient else "none"}')

        # ── Chunk ───────────────────────────────────────────────────
        chunks = document_chunker.chunk_text(text, preserve_context=True)
        total_chunks = len(chunks)
        max_workers = options['max_workers'] or total_chunks

        self.stdout.write(f'Chunked into {total_chunks} pieces '
                          f'({settings.AI_CHUNK_SIZE} chars/chunk, '
                          f'{settings.AI_CHUNK_OVERLAP} overlap)')
        self.stdout.write(f'Plan: {max_workers} parallel API calls, '
                          f'{api_timeout}s HTTP timeout each')

        if dry_run:
            for i, c in enumerate(chunks):
                self.stdout.write(f'  chunk {i}: {len(c["text"]):,} chars')
            self.stdout.write('Dry run complete.')
            return

        # ── Build a timeout-aware AI client ─────────────────────────
        self.stdout.write(f'Initializing Anthropic client with {api_timeout}s timeout ...')
        raw_client = anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            timeout=anthropic.Timeout(
                connect=10.0,
                read=float(api_timeout),
                write=float(api_timeout),
                pool=float(api_timeout),
            ),
            max_retries=1,
        )
        patched_client = instructor.from_anthropic(raw_client)

        # Monkey-patch the module-level client so extract_medical_data_structured
        # uses our timeout-configured version for this run.
        import apps.documents.services.ai_extraction as ai_mod
        original_client = ai_mod.anthropic_client
        ai_mod.anthropic_client = patched_client

        model = getattr(settings, 'AI_MODEL_PRIMARY', 'claude-sonnet-4-5-20250929')
        context = f"Large document (parallel reprocess), patient {document.patient.mrn if document.patient else 'unknown'}"

        # ── Parallel extraction ─────────────────────────────────────
        from apps.documents.services.ai_extraction import extract_medical_data_structured

        results = {}
        errors = {}
        wall_start = time.time()

        document.status = 'processing'
        document.processing_message = 'Analyzing document with AI (parallel)...'
        document.processing_started_at = timezone.now()
        document.error_message = ''
        document.save(update_fields=[
            'status', 'processing_message', 'processing_started_at', 'error_message',
        ])

        self.stdout.write(self.style.WARNING(
            f'Firing {total_chunks} chunks in parallel (max {max_workers} workers) ...'))

        def _extract_one(chunk_idx, chunk_text):
            t0 = time.time()
            result = extract_medical_data_structured(chunk_text, context=context)
            elapsed = time.time() - t0
            return chunk_idx, result, elapsed

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_extract_one, i, c['text']): i
                for i, c in enumerate(chunks)
            }

            for future in as_completed(futures):
                idx = futures[future]
                try:
                    chunk_idx, result, elapsed = future.result()
                    items = (len(result.conditions) + len(result.medications) +
                             len(result.vital_signs) + len(result.lab_results) +
                             len(result.procedures) + len(result.providers))
                    results[chunk_idx] = result
                    self.stdout.write(self.style.SUCCESS(
                        f'  chunk {chunk_idx + 1}/{total_chunks} done — '
                        f'{items} items, {elapsed:.1f}s'))
                except Exception as exc:
                    errors[idx] = str(exc)
                    self.stdout.write(self.style.ERROR(
                        f'  chunk {idx + 1}/{total_chunks} FAILED: {exc}'))

        wall_elapsed = time.time() - wall_start

        # Restore original client
        ai_mod.anthropic_client = original_client

        self.stdout.write(f'\nExtraction complete: {len(results)}/{total_chunks} succeeded, '
                          f'{len(errors)} failed, {wall_elapsed:.1f}s wall time')

        if not results:
            document.status = 'failed'
            document.error_message = f'All {total_chunks} chunks failed in parallel extraction'
            document.processed_at = timezone.now()
            document.save(update_fields=['status', 'error_message', 'processed_at'])
            raise CommandError('All chunks failed — nothing to aggregate')

        if errors:
            self.stdout.write(self.style.WARNING(
                f'Continuing with {len(results)} successful chunks '
                f'({len(errors)} failed: {errors})'))

        # ── Aggregate ───────────────────────────────────────────────
        self.stdout.write('Aggregating chunk results ...')
        aggregated = _create_empty_aggregated_dict()
        for idx in sorted(results.keys()):
            chunk_data = results[idx].model_dump()
            _extend_aggregated_from_chunk(aggregated, chunk_data)

        _deduplicate_aggregated(aggregated)
        structured_extraction = StructuredMedicalExtraction.model_validate(aggregated)

        total_items = (len(structured_extraction.conditions) +
                       len(structured_extraction.medications) +
                       len(structured_extraction.vital_signs) +
                       len(structured_extraction.lab_results) +
                       len(structured_extraction.procedures) +
                       len(structured_extraction.providers))
        self.stdout.write(f'Aggregated: {total_items} total items, '
                          f'confidence {structured_extraction.confidence_average:.3f}')

        # ── FHIR conversion ─────────────────────────────────────────
        self.stdout.write('Converting to FHIR resources ...')
        document.processing_message = 'Converting to FHIR format...'
        document.save(update_fields=['processing_message'])

        from apps.fhir.converters import StructuredDataConverter

        converter = StructuredDataConverter()
        conversion_metadata = {
            'document_id': document.id,
            'extraction_timestamp': structured_extraction.extraction_timestamp,
            'document_type': structured_extraction.document_type,
            'confidence_average': structured_extraction.confidence_average,
        }

        parsed_data_for_dates = ParsedData.objects.filter(document=document).first()
        fhir_resources = converter.convert_structured_data(
            structured_extraction, conversion_metadata,
            document.patient,
            parsed_data=parsed_data_for_dates,
        )
        self.stdout.write(f'FHIR conversion: {len(fhir_resources)} resources')

        # ── Serialize FHIR resources ────────────────────────────────
        serialized = []
        for r in fhir_resources:
            try:
                if hasattr(r, 'model_dump'):
                    serialized.append(json.loads(json.dumps(r.model_dump(exclude_none=True), default=str)))
                elif hasattr(r, 'dict'):
                    serialized.append(json.loads(json.dumps(r.dict(exclude_none=True), default=str)))
                elif isinstance(r, dict):
                    serialized.append(json.loads(json.dumps(r, default=str)))
            except Exception as ser_exc:
                self.stdout.write(self.style.WARNING(f'Failed to serialize resource: {ser_exc}'))

        structured_data_dict = structured_extraction.model_dump()

        # ── Save ParsedData ─────────────────────────────────────────
        self.stdout.write('Saving ParsedData ...')
        clinical_date_defaults = _build_clinical_date_defaults(
            structured_data_dict, serialized
        )

        parsed_data, created = ParsedData.objects.update_or_create(
            document=document,
            defaults={
                'patient': document.patient,
                'extraction_json': [],
                'source_snippets': {},
                'fhir_delta_json': serialized if serialized else {},
                'extraction_confidence': structured_extraction.confidence_average,
                'ai_model_used': model,
                'processing_time_seconds': wall_elapsed,
                'capture_metrics': {},
                'is_approved': False,
                'is_merged': False,
                'reviewed_at': None,
                'reviewed_by': None,
                'corrections': {'structured_data': structured_data_dict},
                **clinical_date_defaults,
            }
        )
        self.stdout.write(f'{"Created" if created else "Updated"} ParsedData {parsed_data.id}')

        # ── Review status & merge ───────────────────────────────────
        review_status, flag_reason = parsed_data.determine_review_status()
        parsed_data.review_status = review_status
        parsed_data.auto_approved = (review_status == 'auto_approved')
        parsed_data.flag_reason = flag_reason
        parsed_data.save(update_fields=['review_status', 'auto_approved', 'flag_reason'])
        self.stdout.write(f'Review: {review_status} '
                          f'{"" if not flag_reason else f"({flag_reason})"}')

        from apps.documents.models import audit_extraction_decision
        audit_extraction_decision(parsed_data, request=None)

        if serialized and document.patient:
            merge_ok = document.patient.add_fhir_resources(serialized, document_id=document.id)
            if merge_ok:
                parsed_data.is_merged = True
                parsed_data.merged_at = timezone.now()
                parsed_data.save(update_fields=['is_merged', 'merged_at'])
                self.stdout.write(self.style.SUCCESS(
                    f'Merged {len(serialized)} FHIR resources into patient '
                    f'{document.patient.mrn}'))
            else:
                self.stdout.write(self.style.ERROR('Merge failed'))

        # ── Finalize document ───────────────────────────────────────
        document.status = 'completed'
        document.processing_message = ''
        document.processed_at = timezone.now()
        document.ai_extraction_time_ms = int(wall_elapsed * 1000)
        document.error_message = ''
        document.save(update_fields=[
            'status', 'processing_message', 'processed_at',
            'ai_extraction_time_ms', 'error_message',
        ])

        self.stdout.write(self.style.SUCCESS(
            f'\nDocument {document_id} completed in {wall_elapsed:.1f}s '
            f'({total_items} medical items, {len(serialized)} FHIR resources)'))
