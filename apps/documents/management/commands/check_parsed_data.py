"""
Django management command to check ParsedData status for documents.
"""
from django.core.management.base import BaseCommand
from apps.documents.models import Document, ParsedData


class Command(BaseCommand):
    help = 'Check which documents in review have ParsedData'

    def handle(self, *args, **options):
        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS('PARSEDDATA STATUS CHECK'))
        self.stdout.write("=" * 70)
        
        # Get all review documents
        review_docs = Document.objects.filter(status='review')
        total = review_docs.count()
        
        self.stdout.write(f"\nTotal documents in 'review' status: {total}")
        
        if total == 0:
            self.stdout.write(self.style.WARNING("No documents in review status."))
            return
        
        # Check which have ParsedData
        with_parsed = review_docs.filter(
            id__in=ParsedData.objects.values_list('document_id', flat=True)
        )
        without_parsed = review_docs.exclude(
            id__in=ParsedData.objects.values_list('document_id', flat=True)
        )
        
        with_count = with_parsed.count()
        without_count = without_parsed.count()
        
        # Summary
        self.stdout.write(f"\n[OK] Documents WITH ParsedData: {with_count}")
        self.stdout.write(f"[X] Documents WITHOUT ParsedData: {without_count}")
        
        # Show details
        if with_count > 0:
            self.stdout.write(f"\n{self.style.SUCCESS('Documents WITH ParsedData:')}")
            for doc in with_parsed:
                parsed = ParsedData.objects.get(document=doc)
                field_count = len(parsed.extraction_json) if parsed.extraction_json else 0
                fhir_count = len(parsed.fhir_delta_json) if parsed.fhir_delta_json else 0
                self.stdout.write(
                    f"  [OK] Doc {doc.id}: {doc.file.name} "
                    f"({field_count} fields, {fhir_count} FHIR resources, "
                    f"confidence: {parsed.extraction_confidence:.2f})"
                )
        
        if without_count > 0:
            self.stdout.write(f"\n{self.style.ERROR('Documents WITHOUT ParsedData (BROKEN):')}")
            for doc in without_parsed:
                error_msg = f" - Error: {doc.error_message}" if doc.error_message else ""
                self.stdout.write(
                    f"  [X] Doc {doc.id}: {doc.file.name} "
                    f"(uploaded {doc.uploaded_at.strftime('%Y-%m-%d %H:%M')}){error_msg}"
                )
        
        # Status summary
        self.stdout.write("\n" + "=" * 70)
        if without_count == 0:
            self.stdout.write(self.style.SUCCESS("[SUCCESS] All documents have ParsedData"))
        else:
            self.stdout.write(self.style.ERROR(f"[ERROR] {without_count} document(s) still missing ParsedData"))
            self.stdout.write(self.style.WARNING("\nTo fix: python manage.py reprocess_review_documents"))
        self.stdout.write("=" * 70)

