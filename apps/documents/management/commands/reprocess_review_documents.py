"""
Django management command to reprocess all documents in review status.
Used to fix documents that were processed with the ParsedData bug.
"""
from django.core.management.base import BaseCommand
from apps.documents.models import Document, ParsedData
from apps.documents.tasks import process_document_async


class Command(BaseCommand):
    help = 'Reprocess all documents in review status (especially those missing ParsedData)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Reprocess ALL documents in review, even if they have ParsedData',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be reprocessed without actually doing it',
        )

    def handle(self, *args, **options):
        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS('REPROCESSING DOCUMENTS IN REVIEW STATUS'))
        self.stdout.write("=" * 70)
        
        # Find documents to reprocess
        if options['all']:
            # Reprocess all documents in review
            docs_to_process = Document.objects.filter(status='review')
            self.stdout.write(f"\nMode: Reprocess ALL documents in review status")
        else:
            # Only reprocess documents WITHOUT ParsedData (the broken ones)
            docs_to_process = Document.objects.filter(
                status='review'
            ).exclude(
                id__in=ParsedData.objects.values_list('document_id', flat=True)
            )
            self.stdout.write(f"\nMode: Reprocess only documents WITHOUT ParsedData")
        
        count = docs_to_process.count()
        
        if count == 0:
            self.stdout.write(self.style.WARNING("\n[OK] No documents need reprocessing!"))
            return
        
        self.stdout.write(f"\nFound {count} document(s) to reprocess:")
        
        for doc in docs_to_process:
            has_parsed = ParsedData.objects.filter(document=doc).exists()
            status_icon = "X" if not has_parsed else "OK"
            self.stdout.write(
                f"  [{status_icon}] Document {doc.id}: {doc.file.name} "
                f"(uploaded {doc.uploaded_at.strftime('%Y-%m-%d %H:%M')})"
            )
        
        if options['dry_run']:
            self.stdout.write(self.style.WARNING("\n[DRY RUN] No tasks triggered."))
            return
        
        # Trigger reprocessing
        self.stdout.write(f"\n[START] Triggering reprocessing tasks...")
        
        task_ids = []
        for doc in docs_to_process:
            task = process_document_async.delay(doc.id)
            task_ids.append(task.id)
            self.stdout.write(f"   [OK] Document {doc.id}: Task {task.id}")
        
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS(f"[DONE] {len(task_ids)} task(s) submitted to Celery"))
        self.stdout.write("=" * 70)
        
        self.stdout.write("\nMonitor Celery worker logs for progress.")
        self.stdout.write("Processing typically takes 30-60 seconds per document.")
        self.stdout.write("\nTo check results after processing completes:")
        self.stdout.write(self.style.WARNING("  python manage.py check_parsed_data"))

