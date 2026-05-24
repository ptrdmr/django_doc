"""
Django management command to check ParsedData status for documents.
"""
from django.core.management.base import BaseCommand
from apps.documents.models import Document, ParsedData


class Command(BaseCommand):
    help = 'Check ParsedData coverage for completed documents'

    def handle(self, *args, **options):
        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS('PARSEDDATA STATUS CHECK'))
        self.stdout.write("=" * 70)
        
        completed_docs = Document.objects.filter(status='completed')
        total = completed_docs.count()
        
        self.stdout.write(f"\nTotal documents in 'completed' status: {total}")
        
        if total == 0:
            self.stdout.write(self.style.WARNING("No completed documents found."))
            return
        
        with_parsed = completed_docs.filter(
            id__in=ParsedData.objects.values_list('document_id', flat=True)
        )
        without_parsed = completed_docs.exclude(
            id__in=ParsedData.objects.values_list('document_id', flat=True)
        )
        
        with_count = with_parsed.count()
        without_count = without_parsed.count()
        flagged_count = ParsedData.objects.filter(review_status='flagged').count()
        
        self.stdout.write(f"\n[OK] Completed documents WITH ParsedData: {with_count}")
        self.stdout.write(f"[X] Completed documents WITHOUT ParsedData: {without_count}")
        self.stdout.write(f"[i] ParsedData flagged for audit (internal): {flagged_count}")
        
        if with_count > 0:
            self.stdout.write(f"\n{self.style.SUCCESS('Documents WITH ParsedData:')}")
            for doc in with_parsed[:20]:
                parsed = ParsedData.objects.get(document=doc)
                field_count = len(parsed.extraction_json) if parsed.extraction_json else 0
                fhir_count = len(parsed.fhir_delta_json) if parsed.fhir_delta_json else 0
                self.stdout.write(
                    f"  [OK] Doc {doc.id}: {doc.file.name} "
                    f"({field_count} fields, {fhir_count} FHIR resources, "
                    f"confidence: {parsed.extraction_confidence:.2f}, "
                    f"review_status: {parsed.review_status})"
                )
            if with_count > 20:
                self.stdout.write(f"  ... and {with_count - 20} more")
        
        if without_count > 0:
            self.stdout.write(f"\n{self.style.ERROR('Documents WITHOUT ParsedData (BROKEN):')}")
            for doc in without_parsed:
                error_msg = f" - Error: {doc.error_message}" if doc.error_message else ""
                self.stdout.write(
                    f"  [X] Doc {doc.id}: {doc.file.name} "
                    f"(uploaded {doc.uploaded_at.strftime('%Y-%m-%d %H:%M')}){error_msg}"
                )
        
        self.stdout.write("\n" + "=" * 70)
        if without_count == 0:
            self.stdout.write(self.style.SUCCESS("[SUCCESS] All completed documents have ParsedData"))
        else:
            self.stdout.write(
                self.style.ERROR(f"[ERROR] {without_count} completed document(s) missing ParsedData")
            )
        self.stdout.write("=" * 70)
