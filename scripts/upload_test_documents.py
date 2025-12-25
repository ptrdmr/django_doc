"""
Upload test documents from test_documents/ folder for testing.

This script uploads PDF files and creates Document records for testing
the optimistic concurrency merge system.

Usage:
    python scripts/upload_test_documents.py
    
Or in Docker:
    docker-compose exec web python scripts/upload_test_documents.py
"""
import os
import sys
import django
from pathlib import Path

# Setup Django
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from django.core.files import File
from apps.documents.models import Document
from apps.patients.models import Patient


def get_or_create_test_patient():
    """Get or create a test patient for document uploads"""
    
    # Try to find existing test patient
    test_patient = Patient.objects.filter(mrn__startswith='TEST-').first()
    
    if test_patient:
        print(f"✓ Using existing test patient: {test_patient.first_name} {test_patient.last_name} (MRN: {test_patient.mrn})")
        return test_patient
    
    # Create new test patient with unique MRN
    print("Creating new test patient...")
    
    # Find highest TEST- MRN number
    existing_test_patients = Patient.objects.filter(mrn__startswith='TEST-').order_by('-mrn')
    if existing_test_patients.exists():
        last_mrn = existing_test_patients.first().mrn
        last_num = int(last_mrn.split('-')[1])
        new_num = last_num + 1
    else:
        new_num = 1
    
    test_patient = Patient.objects.create(
        first_name='Test',
        last_name='Patient',
        date_of_birth='1980-01-01',
        mrn=f'TEST-{new_num:04d}',
        gender='U'
    )
    print(f"✓ Created test patient: {test_patient.first_name} {test_patient.last_name} (MRN: {test_patient.mrn})")
    
    return test_patient


def upload_test_documents():
    """Upload all PDF files from test_documents/ folder"""
    
    test_docs_dir = project_root / 'test_documents'
    
    if not test_docs_dir.exists():
        print(f"✗ test_documents/ directory not found at {test_docs_dir}")
        return
    
    # Get test patient
    patient = get_or_create_test_patient()
    
    # Find all PDF files
    pdf_files = list(test_docs_dir.glob('*.pdf'))
    
    if not pdf_files:
        print("✗ No PDF files found in test_documents/")
        return
    
    print(f"\n📋 Found {len(pdf_files)} PDF file(s) in test_documents/")
    print("="*80)
    
    uploaded_count = 0
    skipped_count = 0
    
    for pdf_path in sorted(pdf_files):
        filename = pdf_path.name
        
        # Check if already uploaded
        existing = Document.objects.filter(
            file__icontains=filename,
            patient=patient
        ).first()
        
        if existing:
            print(f"\n⊘ Skipping {filename} (already uploaded as Document {existing.id})")
            skipped_count += 1
            continue
        
        print(f"\n📄 Uploading: {filename}")
        print(f"   Size: {pdf_path.stat().st_size / 1024:.1f} KB")
        
        try:
            with open(pdf_path, 'rb') as f:
                doc = Document.objects.create(
                    patient=patient,
                    file=File(f, name=filename),
                    status='pending',
                    uploaded_by=None  # System upload
                )
            
            print(f"   ✓ Created Document {doc.id}")
            uploaded_count += 1
            
        except Exception as e:
            print(f"   ✗ Error: {str(e)}")
    
    print("\n" + "="*80)
    print(f"✓ Upload complete: {uploaded_count} uploaded, {skipped_count} skipped")
    print("="*80)
    
    if uploaded_count > 0:
        print("\n💡 Next steps:")
        print("   1. Process a single document:")
        print(f"      python manage.py test_document_processing {doc.id}")
        print("\n   2. Process all pending documents:")
        print("      python manage.py test_document_processing --all")
        print("\n   3. Run batch test with metrics:")
        print("      python scripts/test_optimistic_merge_batch.py")
    
    print()


if __name__ == '__main__':
    print("\n" + "="*80)
    print("TEST DOCUMENT UPLOAD UTILITY")
    print("="*80 + "\n")
    
    upload_test_documents()

