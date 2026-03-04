"""Check document 36 text length vs chunk threshold."""
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()
from django.conf import settings
from apps.documents.models import Document

d = Document.objects.get(id=36)
text = d.original_text or ''
threshold = getattr(settings, 'AI_TOKEN_THRESHOLD_FOR_CHUNKING', 20000)
print(f"Document {d.id}: {d.filename}")
print(f"  original_text length: {len(text)} chars")
print(f"  chunk threshold:      {threshold} chars")
print(f"  would be chunked:     {len(text) > threshold}")
print(f"  ratio:                {len(text) / threshold:.1f}x threshold")
