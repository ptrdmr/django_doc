"""Check document 36 status."""
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()
from apps.documents.models import Document
d = Document.objects.get(id=36)
print(f"Status: {d.status}")
print(f"Message: {d.processing_message}")
print(f"Error: {d.error_message}")
print(f"Processed at: {d.processed_at}")
