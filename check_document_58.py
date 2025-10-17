"""Check document 58 data in database"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from apps.documents.models import Document
import json

try:
    doc = Document.objects.get(id=9)
    print(f"Document 9: {doc.filename}")
    print(f"Status: {doc.status}")
    print(f"Uploaded at: {doc.uploaded_at}")
    print(f"Processed at: {doc.processed_at}")
    print(f"\n=== Extracted Data ===")
    
    if doc.extracted_data:
        print(f"Type: {type(doc.extracted_data)}")
        print(f"Keys: {doc.extracted_data.keys() if isinstance(doc.extracted_data, dict) else 'N/A'}")
        
        if isinstance(doc.extracted_data, dict):
            for key, value in doc.extracted_data.items():
                if isinstance(value, list):
                    print(f"  - {key}: {len(value)} items")
                else:
                    print(f"  - {key}: {value}")
        else:
            print(doc.extracted_data)
    else:
        print("extracted_data field is None or empty")
    
    print(f"\n=== Structured Extraction ===")
    if doc.structured_extraction:
        print(f"Type: {type(doc.structured_extraction)}")
        if isinstance(doc.structured_extraction, dict):
            for key, value in doc.structured_extraction.items():
                if isinstance(value, list):
                    print(f"  - {key}: {len(value)} items")
                else:
                    print(f"  - {key}: {type(value)}")
    else:
        print("structured_extraction field is None or empty")
    
    print(f"\n=== FHIR Bundle ===")
    if doc.fhir_bundle:
        print(f"Type: {type(doc.fhir_bundle)}")
        if isinstance(doc.fhir_bundle, dict):
            print(f"Keys: {doc.fhir_bundle.keys()}")
            if 'entry' in doc.fhir_bundle:
                print(f"  - Entries: {len(doc.fhir_bundle['entry'])} FHIR resources")
    else:
        print("fhir_bundle field is None or empty")
        
    print(f"\n=== Source Snippets ===")
    print(f"Source snippets count: {doc.source_snippets.count() if hasattr(doc, 'source_snippets') else 'N/A'}")
    
except Document.DoesNotExist:
    print("Document 58 not found")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

