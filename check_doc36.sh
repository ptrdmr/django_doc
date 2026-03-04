#!/bin/bash
cd /home/ec2-user/django_doc
docker compose exec -T db psql -U django -d meddocparser -c "SELECT id, status, original_filename FROM documents_document WHERE id = 36;"
