"""Reset document 36 and queue for reprocessing."""
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from apps.documents.models import Document
from apps.documents.tasks import process_document_async

d = Document.objects.get(id=36)
print(f"Document {d.id}: current status = {d.status}")
d.status = 'uploaded'
d.processing_message = ''
d.error_message = ''
d.processed_at = None
d.save()
print(f"Document {d.id}: reset to status = {d.status}")

# Queue for processing
result = process_document_async.delay(d.id)
print(f"Queued task: {result.id}")
