"""
Admin-only processing pipeline monitor dashboard views.
"""

import json
import logging
import time

from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import moritrac_admin_required
from apps.core.monitor_service import MONITOR_EVENTS_CHANNEL, PipelineMetricsService

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 5
SNAPSHOT_INTERVAL_SECONDS = 30


def _parse_hours(request, default: int = 24) -> int:
    """Parse and clamp hours query parameter."""
    try:
        hours = int(request.GET.get('hours', default))
    except (TypeError, ValueError):
        hours = default
    return max(1, min(hours, 168))


@moritrac_admin_required
def monitor_dashboard(request):
    """Render the processing pipeline monitor dashboard."""
    hours = _parse_hours(request)
    context = {
        'hours': hours,
        'summary': PipelineMetricsService.get_dashboard_summary(hours=hours),
        'live_data': PipelineMetricsService.get_live_documents(),
        'recent_completions': PipelineMetricsService.get_recent_completions(limit=20),
        'cost_summary': PipelineMetricsService.get_cost_summary(hours=hours),
    }
    return render(request, 'core/monitor_dashboard.html', context)


@moritrac_admin_required
@require_http_methods(['GET'])
def api_pipeline_metrics(request):
    """JSON endpoint for pipeline timing, throughput, and success metrics."""
    hours = _parse_hours(request)
    try:
        data = PipelineMetricsService.get_pipeline_metrics(hours=hours)
        return JsonResponse({'success': True, 'hours': hours, **data})
    except Exception as exc:
        logger.error("Failed to load pipeline metrics: %s", exc, exc_info=True)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@moritrac_admin_required
@require_http_methods(['GET'])
def api_live_documents(request):
    """JSON endpoint for live in-progress document queue."""
    try:
        data = PipelineMetricsService.get_live_documents()
        return JsonResponse({'success': True, **data})
    except Exception as exc:
        logger.error("Failed to load live documents: %s", exc, exc_info=True)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@moritrac_admin_required
@require_http_methods(['GET'])
def api_cost_summary(request):
    """JSON endpoint for cost breakdown by provider."""
    hours = _parse_hours(request)
    try:
        data = PipelineMetricsService.get_cost_summary(hours=hours)
        return JsonResponse({'success': True, 'hours': hours, **data})
    except Exception as exc:
        logger.error("Failed to load cost summary: %s", exc, exc_info=True)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


def _monitor_event_stream(hours: int):
    """Yield SSE frames from Redis pub/sub with heartbeat and snapshot support.

    Falls back to snapshot-only polling if Redis pub/sub is unavailable so the
    connection stays alive and the browser never falls back to HTTP polling.
    """
    # Send an immediate snapshot so the client renders right away.
    try:
        snapshot = PipelineMetricsService.build_snapshot_payload(hours=hours)
        yield f"data: {json.dumps(snapshot)}\n\n"
    except Exception as exc:
        logger.error("SSE initial snapshot failed: %s", exc, exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'message': 'snapshot unavailable'})}\n\n"

    # Attempt Redis pub/sub; degrade gracefully to snapshot polling on failure.
    pubsub = None
    try:
        redis_client = PipelineMetricsService._get_redis_client()
        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(MONITOR_EVENTS_CHANNEL)
        logger.debug("SSE: subscribed to %s", MONITOR_EVENTS_CHANNEL)
    except Exception as exc:
        logger.warning("SSE: Redis pub/sub unavailable (%s), using snapshot-only mode", exc)
        pubsub = None

    last_heartbeat = time.time()
    last_snapshot = time.time()

    try:
        while True:
            now = time.time()

            # Pull messages from Redis when available.
            if pubsub is not None:
                try:
                    message = pubsub.get_message(timeout=1.0)
                    if message and message.get('type') == 'message':
                        payload = message['data']
                        if isinstance(payload, bytes):
                            payload = payload.decode('utf-8')
                        yield f"data: {payload}\n\n"
                except Exception as exc:
                    logger.warning("SSE: pub/sub read error (%s), continuing in snapshot mode", exc)
                    pubsub = None
            else:
                # No Redis — sleep briefly so we don't spin the CPU.
                time.sleep(1.0)

            now = time.time()

            if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                yield ": heartbeat\n\n"
                last_heartbeat = now

            if now - last_snapshot >= SNAPSHOT_INTERVAL_SECONDS:
                try:
                    snap = PipelineMetricsService.build_snapshot_payload(hours=hours)
                    yield f"data: {json.dumps(snap)}\n\n"
                except Exception as exc:
                    logger.warning("SSE: snapshot refresh failed: %s", exc)
                last_snapshot = now

    except GeneratorExit:
        logger.debug("SSE client disconnected")
    except Exception as exc:
        logger.error("SSE stream fatal error: %s", exc, exc_info=True)
    finally:
        if pubsub is not None:
            try:
                pubsub.unsubscribe(MONITOR_EVENTS_CHANNEL)
                pubsub.close()
            except Exception:
                pass


@require_http_methods(['GET'])
def sse_pipeline_events(request):
    """Stream pipeline stage events to the monitor dashboard via SSE.

    Uses manual auth check instead of @login_required to avoid 302 redirects
    that break EventSource connections.
    """
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'error': 'unauthorized'}, status=403)

    hours = _parse_hours(request)
    try:
        response = StreamingHttpResponse(
            streaming_content=_monitor_event_stream(hours=hours),
            content_type='text/event-stream; charset=utf-8',
        )
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['X-Accel-Buffering'] = 'no'
        return response
    except Exception as exc:
        logger.error("SSE endpoint error: %s", exc, exc_info=True)
        return JsonResponse({'error': str(exc)}, status=500)
