import sys
sys.path.insert(0, '.')
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from apps.documents.models import Document, ParsedData

doc = Document.objects.get(id=88)
parsed = ParsedData.objects.get(document_id=88)

print("=== Document 88 Merge Status ===")
print(f"Document status: {doc.status}")
print(f"Parsed data review_status: {parsed.review_status}")
print(f"Is merged: {parsed.is_merged}")
print(f"Auto approved: {parsed.auto_approved}")
print(f"Merged at: {parsed.merged_at}")

# Check if review_recommendation field exists
if hasattr(parsed, 'review_recommendation'):
    print(f"Review recommendation: {parsed.review_recommendation}")
else:
    print("Review recommendation field: NOT FOUND in model")

# Check all fields
print("\nAll ParsedData fields:")
for field in parsed._meta.get_fields():
    if hasattr(parsed, field.name):
        print(f"  {field.name}: {getattr(parsed, field.name, 'N/A')}")


