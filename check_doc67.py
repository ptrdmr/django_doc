import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from apps.documents.models import Document

d = Document.objects.get(id=67)
print(f'Document 67:')
print(f'  Status: {d.status}')
print(f'  Filename: {d.filename}')
print(f'  Uploaded: {d.uploaded_at}')
print(f'  Error: {d.error_message[:300] if d.error_message else "None"}')


