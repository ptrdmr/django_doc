"""Check ParsedData for document 36."""
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()
from apps.documents.models import Document, ParsedData

d = Document.objects.get(id=36)
print(f"Document {d.id}: status={d.status}, error={d.error_message or '(none)'}")

pd_list = ParsedData.objects.filter(document=d)
print(f"ParsedData records: {pd_list.count()}")

for pd in pd_list:
    print(f"\n--- ParsedData {pd.id} ---")
    print(f"  review_status: {pd.review_status}")
    print(f"  auto_approved: {pd.auto_approved}")
    print(f"  flag_reason: {pd.flag_reason}")
    print(f"  is_approved: {pd.is_approved}")
    print(f"  is_merged: {pd.is_merged}")
    print(f"  merged_at: {pd.merged_at}")
    print(f"  extraction_confidence: {pd.extraction_confidence}")
    print(f"  ai_model_used: {pd.ai_model_used}")
    print(f"  fields count: {len(pd.extraction_json) if pd.extraction_json else 0}")
    print(f"  fhir_delta_json type: {type(pd.fhir_delta_json).__name__}, len: {len(pd.fhir_delta_json) if pd.fhir_delta_json else 0}")
    
    # Show field types breakdown
    if pd.extraction_json and isinstance(pd.extraction_json, list):
        from collections import Counter
        types = Counter(f.get('type', 'unknown') for f in pd.extraction_json if isinstance(f, dict))
        print(f"  field types: {dict(types)}")
    
    # Check capture_metrics
    if pd.capture_metrics:
        print(f"  capture_metrics: {pd.capture_metrics}")
