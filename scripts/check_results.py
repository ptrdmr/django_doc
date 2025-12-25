import os, sys, django
from pathlib import Path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from apps.documents.models import Document, ParsedData

print("\n" + "="*80)
print("DOCUMENT PROCESSING RESULTS")
print("="*80)

docs = Document.objects.filter(id__in=[90,91,92]).order_by('id')

for doc in docs:
    parsed = ParsedData.objects.filter(document=doc).first()
    
    print(f"\n📄 Document {doc.id}: {os.path.basename(doc.file.name)}")
    print(f"   Status: {doc.status}")
    
    if parsed:
        print(f"   Review Status: {parsed.review_status}")
        print(f"   Auto-Approved: {parsed.auto_approved}")
        print(f"   Confidence: {parsed.extraction_confidence:.1%}")
        print(f"   Resources: {parsed.get_fhir_resource_count()}")
        if parsed.flag_reason:
            print(f"   Flag Reason: {parsed.flag_reason}")
        print(f"   Is Merged: {parsed.is_merged}")
    else:
        print("   No ParsedData found")

# Get patient bundle info
from apps.patients.models import Patient
patient = Patient.objects.get(mrn='TEST-0001')
bundle = patient.encrypted_fhir_bundle
total_resources = len(bundle.get('entry', []))

print(f"\n👤 Patient Bundle (MRN: {patient.mrn}):")
print(f"   Total Resources: {total_resources}")

# Calculate metrics
parsed_all = ParsedData.objects.filter(document_id__in=[90,91,92])
total = parsed_all.count()
auto_approved = parsed_all.filter(auto_approved=True).count()
flagged = parsed_all.filter(auto_approved=False).count()

print(f"\n📊 Summary Metrics:")
print(f"   Total Processed: {total}")
print(f"   Auto-Approved: {auto_approved} ({auto_approved/total*100:.1f}%)")
print(f"   Flagged: {flagged} ({flagged/total*100:.1f}%)")

if flagged > 0:
    flag_rate = (flagged / total) * 100
    if 5 <= flag_rate <= 20:
        print(f"   ✓ Flag rate is OPTIMAL (5-20% target)")
    elif flag_rate < 5:
        print(f"   ⚠ Flag rate is LOW (< 5%) - thresholds may be too lenient")
    else:
        print(f"   ⚠ Flag rate is HIGH (> 20%) - thresholds may be too strict")

print("="*80 + "\n")

