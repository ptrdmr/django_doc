"""
Tests for processing monitor dashboard and Textract cost tracking.
"""

from unittest.mock import MagicMock, patch

import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import APIUsageLog
from apps.core.monitor_service import PipelineMetricsService
from apps.core.services import APIUsageMonitor, CostCalculator
from apps.documents.models import Document
from apps.patients.models import Patient


class TextractCostCalculatorTests(TestCase):
    """Validate page-based Textract pricing calculations."""

    def test_detect_document_text_cost(self):
        cost = CostCalculator.calculate_textract_cost('detect_document_text', 10)
        self.assertEqual(cost, Decimal('0.015'))

    def test_analyze_document_cost(self):
        cost = CostCalculator.calculate_textract_cost('analyze', 4)
        self.assertEqual(cost, Decimal('0.06'))

    def test_zero_pages_returns_zero_cost(self):
        cost = CostCalculator.calculate_textract_cost('detect_document_text', 0)
        self.assertEqual(cost, Decimal('0.00'))


class MonitorAccessControlTests(TestCase):
    """Ensure monitor endpoints require Moritrac admin access."""

    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username='staffuser',
            email='staff@example.com',
            password='testpass123',
            is_staff=True,
        )
        self.regular_user = User.objects.create_user(
            username='regularuser',
            email='regular@example.com',
            password='testpass123',
            is_staff=False,
        )

    def test_staff_can_access_monitor_dashboard(self):
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(reverse('core:monitor-dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_non_staff_denied_monitor_dashboard(self):
        self.client.login(username='regularuser', password='testpass123')
        response = self.client.get(reverse('core:monitor-dashboard'))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_redirected_from_monitor_dashboard(self):
        response = self.client.get(reverse('core:monitor-dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_staff_can_access_monitor_sse_endpoint(self):
        self.client.login(username='staffuser', password='testpass123')
        with patch('apps.core.monitor_views._monitor_event_stream', return_value=iter([': heartbeat\n\n'])):
            response = self.client.get(reverse('core:monitor-api-events'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/event-stream')

    def test_non_staff_denied_monitor_sse_endpoint(self):
        self.client.login(username='regularuser', password='testpass123')
        response = self.client.get(reverse('core:monitor-api-events'))
        self.assertEqual(response.status_code, 403)


class PipelineMetricsServiceTests(TestCase):
    """Validate monitor aggregation service outputs."""

    def setUp(self):
        cache.clear()
        self.patient = Patient.objects.create(
            first_name='Monitor',
            last_name='Patient',
            mrn='MON-001',
            date_of_birth='1980-01-01',
        )
        self.document = Document.objects.create(
            patient=self.patient,
            filename='monitor-test.pdf',
            status='completed',
            processing_started_at=timezone.now() - timezone.timedelta(minutes=5),
            processed_at=timezone.now(),
            queue_wait_time_ms=1000,
            pdf_extraction_time_ms=2000,
            ai_extraction_time_ms=3000,
            fhir_conversion_time_ms=500,
        )
        session_id = uuid.uuid4()
        now = timezone.now()
        APIUsageMonitor.log_textract_usage(
            document=self.document,
            patient=self.patient,
            session_id=session_id,
            mode='detect_document_text',
            page_count=2,
            start_time=now - timezone.timedelta(seconds=1),
            end_time=now,
        )

    def test_live_documents_excludes_completed(self):
        live = PipelineMetricsService.get_live_documents()
        document_ids = [row['id'] for row in live['documents']]
        self.assertNotIn(self.document.id, document_ids)

    def test_cost_summary_includes_textract_provider(self):
        cost = PipelineMetricsService.get_cost_summary(hours=24)
        providers = {row['provider'] for row in cost['providers']}
        self.assertIn('aws_textract', providers)
        self.assertGreater(cost['total_cost_usd'], 0)

    def test_recent_completions_includes_stage_timings(self):
        rows = PipelineMetricsService.get_recent_completions(limit=5)
        matching = next(row for row in rows if row['id'] == self.document.id)
        self.assertEqual(matching['pdf_extraction_ms'], 2000)
        self.assertEqual(matching['ai_extraction_ms'], 3000)
        self.assertGreater(matching['cost_usd'], 0)

    def test_textract_usage_log_created(self):
        log = APIUsageLog.objects.filter(
            document=self.document,
            provider='aws_textract',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.total_tokens, 2)
        self.assertGreater(log.cost_usd, Decimal('0'))


class MonitorRealtimeTests(TestCase):
    """Validate stage key resolution and Redis event publishing."""

    def setUp(self):
        cache.clear()
        self.patient = Patient.objects.create(
            first_name='Live',
            last_name='Patient',
            mrn='LIVE-001',
            date_of_birth='1980-01-01',
        )

    def test_resolve_stage_key_for_ai_processing_message(self):
        document = Document.objects.create(
            patient=self.patient,
            filename='live.pdf',
            status='processing',
            processing_message='Analyzing document with AI...',
        )
        self.assertEqual(PipelineMetricsService.resolve_stage_key(document), 'ai_processing')

    def test_publish_stage_event_publishes_json_payload(self):
        document = Document.objects.create(
            patient=self.patient,
            filename='live.pdf',
            status='processing',
            processing_message='Extracting text from PDF...',
            processing_started_at=timezone.now(),
        )
        mock_redis = MagicMock()
        with patch.object(PipelineMetricsService, '_get_redis_client', return_value=mock_redis):
            PipelineMetricsService.publish_document_stage(document)

        mock_redis.publish.assert_called_once()
        channel, payload = mock_redis.publish.call_args[0]
        self.assertEqual(channel, 'monitor:events')
        self.assertIn('"type": "stage_change"', payload)
        self.assertIn('"stage_key": "pdf_ocr"', payload)

    def test_live_documents_include_stage_key(self):
        Document.objects.create(
            patient=self.patient,
            filename='queued.pdf',
            status='pending',
        )
        live = PipelineMetricsService.get_live_documents()
        self.assertEqual(live['documents'][0]['stage_key'], 'queued')
