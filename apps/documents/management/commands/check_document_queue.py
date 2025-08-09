"""
Management command to check document processing queue status and manually trigger processing.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.documents.models import Document
from apps.documents.tasks import process_document_async


class Command(BaseCommand):
    help = 'Check document processing queue and optionally trigger processing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--process',
            action='store_true',
            help='Actually trigger processing for pending documents',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=10,
            help='Limit number of documents to show/process',
        )

    def handle(self, *args, **options):
        """Check document queue status"""
        
        self.stdout.write(self.style.SUCCESS('=== Document Queue Status ==='))
        
        # Get document counts by status
        for status, display in Document.STATUS_CHOICES:
            count = Document.objects.filter(status=status).count()
            if count > 0:
                self.stdout.write(f"{display}: {count} documents")
        
        # Show pending documents
        pending_docs = Document.objects.filter(status='pending').order_by('-created_at')[:options['limit']]
        
        if pending_docs:
            self.stdout.write(f'\n=== Pending Documents (showing first {options["limit"]}) ===')
            for doc in pending_docs:
                self.stdout.write(
                    f"ID: {doc.id}, Filename: {doc.filename}, "
                    f"Patient: {doc.patient}, Created: {doc.created_at}"
                )
        
        # Show processing documents (might be stuck)
        processing_docs = Document.objects.filter(status='processing').order_by('-created_at')[:options['limit']]
        
        if processing_docs:
            self.stdout.write(f'\n=== Processing Documents (might be stuck) ===')
            for doc in processing_docs:
                time_processing = timezone.now() - doc.processing_started_at if doc.processing_started_at else "Unknown"
                self.stdout.write(
                    f"ID: {doc.id}, Filename: {doc.filename}, "
                    f"Started: {doc.processing_started_at}, Duration: {time_processing}"
                )
        
        # Trigger processing if requested
        if options['process']:
            pending_count = pending_docs.count()
            if pending_count > 0:
                self.stdout.write(f'\n=== Triggering Processing for {pending_count} Pending Documents ===')
                for doc in pending_docs:
                    try:
                        task_result = process_document_async.delay(doc.id)
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Triggered processing for document {doc.id} (task: {task_result.id})"
                            )
                        )
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(
                                f"Failed to trigger processing for document {doc.id}: {e}"
                            )
                        )
            else:
                self.stdout.write("No pending documents to process")
        else:
            if pending_docs:
                self.stdout.write(
                    f'\nTo trigger processing, run: python manage.py check_document_queue --process'
                ) 