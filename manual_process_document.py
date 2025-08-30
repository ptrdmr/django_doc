#!/usr/bin/env python
"""
Manually trigger AI processing for the uploaded document.
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from apps.documents.models import Document, ParsedData
from apps.documents.tasks import process_document_async

def process_existing_document():
    """Process the existing document."""
    print("🔄 MANUALLY PROCESSING DOCUMENT")
    print("=" * 50)
    
    # Get the first document
    doc = Document.objects.first()
    if not doc:
        print("❌ No documents found")
        return
    
    print(f"📄 Document: {doc.filename}")
    print(f"📊 Status: {doc.status}")
    print(f"📝 Text Length: {len(doc.original_text or '')} chars")
    
    # Check if already processed
    has_parsed = ParsedData.objects.filter(document=doc).exists()
    print(f"🔍 Already Parsed: {'✅' if has_parsed else '❌'}")
    
    if not doc.original_text:
        print("❌ No text to process")
        return
    
    if has_parsed:
        print("ℹ️ Document already processed")
        return
    
    # Trigger processing
    try:
        print("🚀 Starting AI processing...")
        result = process_document_async.delay(doc.id)
        print(f"✅ Celery Task ID: {result.id}")
        print("📡 Monitor progress with: docker-compose logs -f celery_worker")
        print("⏰ Check back in 1-2 minutes for results")
    except Exception as e:
        print(f"❌ Failed to start processing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    process_existing_document()
