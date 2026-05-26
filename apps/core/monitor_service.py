"""
Pipeline metrics aggregation for the processing monitor dashboard.

Provides cached aggregate queries over Document and APIUsageLog models.
No PHI is returned -- only IDs, MRNs, filenames, timing, and cost data.
"""

import json
import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from django.core.cache import cache
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncHour
from django.utils import timezone

from apps.core.models import APIUsageLog
from apps.documents.models import Document

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 10
MONITOR_EVENTS_CHANNEL = 'monitor:events'
LIVE_STATUSES = ('pending', 'processing', 'ocr_pending')
TERMINAL_STATUSES = ('completed', 'failed')
PIPELINE_FLOW_STAGES = (
    ('queued', 'Queue'),
    ('pdf_ocr', 'PDF/OCR'),
    ('ai_processing', 'AI Extract'),
    ('fhir_converting', 'FHIR'),
    ('done', 'Done'),
)


class PipelineMetricsService:
    """Aggregate document pipeline metrics for admin monitoring dashboard."""

    @classmethod
    def _cache_key(cls, method: str, **params) -> str:
        parts = [f"monitor:{method}"] + [f"{k}={v}" for k, v in sorted(params.items())]
        return ":".join(parts)

    @classmethod
    def _cached(cls, key: str, builder: Callable[[], Any]) -> Any:
        cached_value = cache.get(key)
        if cached_value is not None:
            return cached_value
        result = builder()
        cache.set(key, result, CACHE_TTL_SECONDS)
        return result

    @classmethod
    def _hours_cutoff(cls, hours: int):
        return timezone.now() - timedelta(hours=hours)

    @classmethod
    def get_stage_timing_averages(cls, hours: int = 24) -> Dict[str, Any]:
        """Return average stage timings in milliseconds for completed documents."""

        def _build():
            cutoff = cls._hours_cutoff(hours)
            aggregates = Document.objects.filter(
                status='completed',
                processed_at__gte=cutoff,
            ).aggregate(
                queue_wait_avg=Avg('queue_wait_time_ms'),
                pdf_avg=Avg('pdf_extraction_time_ms'),
                ai_avg=Avg('ai_extraction_time_ms'),
                fhir_avg=Avg('fhir_conversion_time_ms'),
                total_avg=Avg('processing_time_ms'),
            )
            return {
                'queue_wait_ms': round(aggregates['queue_wait_avg'] or 0, 1),
                'pdf_extraction_ms': round(aggregates['pdf_avg'] or 0, 1),
                'ai_extraction_ms': round(aggregates['ai_avg'] or 0, 1),
                'fhir_conversion_ms': round(aggregates['fhir_avg'] or 0, 1),
                'processing_time_ms': round(aggregates['total_avg'] or 0, 1),
            }

        return cls._cached(cls._cache_key('stage_timing', hours=hours), _build)

    @classmethod
    def get_throughput_timeline(cls, hours: int = 24) -> Dict[str, Any]:
        """Return hourly completed/failed document counts."""

        def _build():
            cutoff = cls._hours_cutoff(hours)
            hourly = (
                Document.objects.filter(processed_at__gte=cutoff)
                .annotate(hour=TruncHour('processed_at'))
                .values('hour', 'status')
                .annotate(count=Count('id'))
                .order_by('hour')
            )

            labels: List[str] = []
            completed_counts: List[int] = []
            failed_counts: List[int] = []
            bucket_map: Dict[str, Dict[str, int]] = {}

            for row in hourly:
                if not row['hour']:
                    continue
                label = row['hour'].strftime('%H:%M')
                if label not in bucket_map:
                    bucket_map[label] = {'completed': 0, 'failed': 0}
                if row['status'] == 'completed':
                    bucket_map[label]['completed'] = row['count']
                elif row['status'] == 'failed':
                    bucket_map[label]['failed'] = row['count']

            for label in sorted(bucket_map.keys()):
                labels.append(label)
                completed_counts.append(bucket_map[label]['completed'])
                failed_counts.append(bucket_map[label]['failed'])

            return {
                'labels': labels,
                'completed': completed_counts,
                'failed': failed_counts,
            }

        return cls._cached(cls._cache_key('throughput', hours=hours), _build)

    @classmethod
    def get_success_rates_by_stage(cls, hours: int = 24) -> Dict[str, Any]:
        """Return overall and inferred stage success rates."""

        def _build():
            cutoff = cls._hours_cutoff(hours)
            status_counts = Document.objects.filter(
                Q(processed_at__gte=cutoff) | Q(
                    status__in=LIVE_STATUSES,
                    uploaded_at__gte=cutoff,
                )
            ).values('status').annotate(count=Count('id'))

            counts = {row['status']: row['count'] for row in status_counts}
            completed = counts.get('completed', 0)
            failed = counts.get('failed', 0)
            in_progress = sum(counts.get(status, 0) for status in LIVE_STATUSES)
            finished = completed + failed
            overall_rate = round((completed / finished) * 100, 1) if finished else 0.0

            ocr_pending = counts.get('ocr_pending', 0)
            processing = counts.get('processing', 0)

            return {
                'overall_success_rate': overall_rate,
                'completed': completed,
                'failed': failed,
                'in_progress': in_progress,
                'stages': {
                    'queue': {
                        'label': 'Queued',
                        'active': counts.get('pending', 0),
                        'success_rate': overall_rate,
                    },
                    'pdf_ocr': {
                        'label': 'PDF / OCR',
                        'active': ocr_pending + processing,
                        'success_rate': overall_rate,
                    },
                    'ai_extraction': {
                        'label': 'AI Extraction',
                        'active': processing,
                        'success_rate': overall_rate,
                    },
                    'fhir_merge': {
                        'label': 'FHIR / Merge',
                        'active': processing,
                        'success_rate': overall_rate,
                    },
                },
            }

        return cls._cached(cls._cache_key('success_rates', hours=hours), _build)

    @classmethod
    def _get_redis_client(cls):
        """Return the underlying Redis client used by Django cache."""
        return cache.client.get_client()

    @classmethod
    def invalidate_monitor_cache(cls) -> None:
        """Clear cached monitor payloads after live pipeline changes."""
        keys_to_delete = [
            cls._cache_key('live_documents'),
            cls._cache_key('dashboard_summary', hours=24),
            cls._cache_key('success_rates', hours=24),
        ]
        cache.delete_many(keys_to_delete)

    @classmethod
    def resolve_stage_key(cls, document: Document) -> str:
        """Map a document to a stable pipeline stage key for UI steppers."""
        if document.status == 'completed':
            return 'done'
        if document.status == 'failed':
            return 'failed'
        if document.status == 'pending':
            return 'queued'
        if document.status == 'ocr_pending':
            return 'pdf_ocr'

        message = (document.processing_message or '').lower()
        if 'fhir' in message or 'converting' in message:
            return 'fhir_converting'
        if 'analyzing' in message or ' ai' in message or message.startswith('ai'):
            return 'ai_processing'
        if 'extract' in message or 'pdf' in message or 'ocr' in message:
            return 'pdf_ocr'
        if document.status == 'processing':
            return 'ai_processing'
        return 'processing'

    @classmethod
    def publish_stage_event(
        cls,
        document_id: int,
        stage: str,
        stage_key: str,
        filename: str,
        patient_mrn: Optional[str],
        elapsed_seconds: Optional[float],
        attempts: int = 0,
        status: str = '',
    ) -> None:
        """Publish a stage-change event to Redis for SSE subscribers."""
        payload = {
            'type': 'stage_change',
            'document_id': document_id,
            'stage': stage,
            'stage_key': stage_key,
            'filename': filename,
            'patient_mrn': patient_mrn,
            'elapsed_seconds': elapsed_seconds,
            'attempts': attempts,
            'status': status,
        }
        try:
            redis_client = cls._get_redis_client()
            redis_client.publish(MONITOR_EVENTS_CHANNEL, json.dumps(payload))
            cls.invalidate_monitor_cache()
        except Exception as exc:
            logger.warning("Failed to publish monitor stage event: %s", exc)

    @classmethod
    def publish_document_stage(cls, document: Document) -> None:
        """Publish the current pipeline stage for a document."""
        duration_seconds = document.get_processing_duration()
        cls.publish_stage_event(
            document_id=document.id,
            stage=cls._resolve_live_stage(document),
            stage_key=cls.resolve_stage_key(document),
            filename=document.filename,
            patient_mrn=document.patient.mrn if document.patient_id and document.patient else None,
            elapsed_seconds=round(duration_seconds, 1) if duration_seconds else None,
            attempts=document.processing_attempts or 0,
            status=document.status,
        )

    @classmethod
    def build_snapshot_payload(cls, hours: int = 24) -> Dict[str, Any]:
        """Build a full dashboard snapshot for periodic SSE refresh."""
        return {
            'type': 'snapshot',
            'live': cls.get_live_documents(),
            'summary': cls.get_dashboard_summary(hours=hours),
        }

    @classmethod
    def _resolve_live_stage(cls, document: Document) -> str:
        """Map document status/message to a human-readable pipeline stage."""
        message = (document.processing_message or '').lower()
        if document.status == 'pending':
            return 'Queued'
        if document.status == 'ocr_pending':
            return 'OCR Pending'
        if 'fhir' in message or 'converting' in message:
            return 'FHIR Converting'
        if 'analyzing' in message or 'ai' in message:
            return 'AI Processing'
        if 'extract' in message or 'pdf' in message:
            return 'PDF Extracting'
        if document.status == 'processing':
            return 'Processing'
        return document.status.replace('_', ' ').title()

    @classmethod
    def get_live_documents(cls) -> Dict[str, Any]:
        """Return in-progress documents and stage counts."""

        def _build():
            documents = (
                Document.objects.filter(status__in=LIVE_STATUSES)
                .select_related('patient')
                .order_by('-processing_started_at', '-uploaded_at')[:50]
            )

            stage_counts = {
                'queued': 0,
                'pdf_extracting': 0,
                'ocr_pending': 0,
                'ai_processing': 0,
                'fhir_converting': 0,
                'processing': 0,
            }
            rows: List[Dict[str, Any]] = []

            for document in documents:
                stage = cls._resolve_live_stage(document)
                if document.status == 'pending':
                    stage_counts['queued'] += 1
                elif document.status == 'ocr_pending':
                    stage_counts['ocr_pending'] += 1
                elif stage == 'PDF Extracting':
                    stage_counts['pdf_extracting'] += 1
                elif stage == 'AI Processing':
                    stage_counts['ai_processing'] += 1
                elif stage == 'FHIR Converting':
                    stage_counts['fhir_converting'] += 1
                else:
                    stage_counts['processing'] += 1

                duration_seconds = document.get_processing_duration()
                rows.append({
                    'id': document.id,
                    'filename': document.filename,
                    'patient_mrn': document.patient.mrn if document.patient else None,
                    'status': document.status,
                    'stage': stage,
                    'stage_key': cls.resolve_stage_key(document),
                    'processing_message': document.processing_message,
                    'attempts': document.processing_attempts,
                    'elapsed_seconds': round(duration_seconds, 1) if duration_seconds else None,
                    'uploaded_at': document.uploaded_at.isoformat() if document.uploaded_at else None,
                })

            return {
                'stage_counts': stage_counts,
                'documents': rows,
                'total_active': len(rows),
            }

        return cls._cached(cls._cache_key('live_documents'), _build)

    @classmethod
    def get_cost_summary(cls, hours: int = 24) -> Dict[str, Any]:
        """Return cost aggregates grouped by provider."""

        def _build():
            cutoff = cls._hours_cutoff(hours)
            provider_stats = (
                APIUsageLog.objects.filter(created_at__gte=cutoff)
                .values('provider')
                .annotate(
                    total_cost=Sum('cost_usd'),
                    call_count=Count('id'),
                    total_tokens=Sum('total_tokens'),
                )
                .order_by('-total_cost')
            )

            providers = []
            total_cost = Decimal('0.00')
            for row in provider_stats:
                cost = row['total_cost'] or Decimal('0.00')
                total_cost += cost
                providers.append({
                    'provider': row['provider'],
                    'total_cost': float(cost),
                    'call_count': row['call_count'],
                    'total_tokens': row['total_tokens'] or 0,
                })

            completed_docs = Document.objects.filter(
                status='completed',
                processed_at__gte=cutoff,
            ).count()
            avg_cost_per_document = (
                float(total_cost / completed_docs) if completed_docs else 0.0
            )

            return {
                'total_cost_usd': float(total_cost),
                'providers': providers,
                'completed_documents': completed_docs,
                'avg_cost_per_document_usd': round(avg_cost_per_document, 4),
            }

        return cls._cached(cls._cache_key('cost_summary', hours=hours), _build)

    @classmethod
    def get_dashboard_summary(cls, hours: int = 24) -> Dict[str, Any]:
        """Return top-level summary card metrics."""

        def _build():
            cutoff = cls._hours_cutoff(hours)
            finished = Document.objects.filter(processed_at__gte=cutoff)
            completed = finished.filter(status='completed').count()
            failed = finished.filter(status='failed').count()
            total_finished = completed + failed
            success_rate = round((completed / total_finished) * 100, 1) if total_finished else 0.0

            timing = finished.filter(status='completed').aggregate(
                avg_total_ms=Avg('processing_time_ms'),
                avg_queue_ms=Avg('queue_wait_time_ms'),
                avg_pdf_ms=Avg('pdf_extraction_time_ms'),
                avg_ai_ms=Avg('ai_extraction_time_ms'),
                avg_fhir_ms=Avg('fhir_conversion_time_ms'),
            )

            cost_data = cls.get_cost_summary(hours=hours)

            return {
                'documents_processed': completed,
                'documents_failed': failed,
                'success_rate': success_rate,
                'avg_pipeline_seconds': round((timing['avg_total_ms'] or 0) / 1000, 1),
                'avg_stage_seconds': {
                    'queue_wait': round((timing['avg_queue_ms'] or 0) / 1000, 1),
                    'pdf_extraction': round((timing['avg_pdf_ms'] or 0) / 1000, 1),
                    'ai_extraction': round((timing['avg_ai_ms'] or 0) / 1000, 1),
                    'fhir_conversion': round((timing['avg_fhir_ms'] or 0) / 1000, 1),
                },
                'cost_today_usd': cost_data['total_cost_usd'],
                'avg_cost_per_document_usd': cost_data['avg_cost_per_document_usd'],
            }

        return cls._cached(cls._cache_key('dashboard_summary', hours=hours), _build)

    @classmethod
    def get_recent_completions(cls, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recently completed documents with timing and cost."""

        def _build():
            documents = (
                Document.objects.filter(status='completed')
                .select_related('patient')
                .order_by('-processed_at')[:limit]
            )
            document_ids = [doc.id for doc in documents]
            cost_by_document = {
                row['document_id']: row['total_cost']
                for row in APIUsageLog.objects.filter(document_id__in=document_ids)
                .values('document_id')
                .annotate(total_cost=Sum('cost_usd'))
            }

            rows = []
            for document in documents:
                total_ms = (
                    (document.queue_wait_time_ms or 0)
                    + (document.pdf_extraction_time_ms or 0)
                    + (document.ai_extraction_time_ms or 0)
                    + (document.fhir_conversion_time_ms or 0)
                )
                rows.append({
                    'id': document.id,
                    'filename': document.filename,
                    'patient_mrn': document.patient.mrn if document.patient else None,
                    'processed_at': document.processed_at.isoformat() if document.processed_at else None,
                    'queue_wait_ms': document.queue_wait_time_ms,
                    'pdf_extraction_ms': document.pdf_extraction_time_ms,
                    'ai_extraction_ms': document.ai_extraction_time_ms,
                    'fhir_conversion_ms': document.fhir_conversion_time_ms,
                    'total_pipeline_ms': total_ms or document.processing_time_ms,
                    'cost_usd': float(cost_by_document.get(document.id) or 0),
                })
            return rows

        return cls._cached(cls._cache_key('recent_completions', limit=limit), _build)

    @classmethod
    def get_pipeline_metrics(cls, hours: int = 24) -> Dict[str, Any]:
        """Bundle all pipeline metric payloads for the API endpoint."""
        return {
            'summary': cls.get_dashboard_summary(hours=hours),
            'stage_timing': cls.get_stage_timing_averages(hours=hours),
            'throughput': cls.get_throughput_timeline(hours=hours),
            'success_rates': cls.get_success_rates_by_stage(hours=hours),
            'recent_completions': cls.get_recent_completions(limit=20),
        }
