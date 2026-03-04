#!/bin/bash
echo "=== Worker logs (full) ==="
docker logs django_doc-celery_worker-1 2>&1

echo ""
echo "=== Memory ==="
docker stats --no-stream 2>/dev/null

echo ""
echo "=== System RAM ==="
free -h
