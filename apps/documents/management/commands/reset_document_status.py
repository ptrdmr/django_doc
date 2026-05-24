"""
Management command to reset document status for reprocessing.
"""
from django.core.management.base import BaseCommand, CommandError
from apps.documents.models import Document


class Command(BaseCommand):
    help = 'Reset document status to pending for reprocessing'

    def add_arguments(self, parser):
        parser.add_argument(
            'document_id',
            type=int,
            help='ID of the document to reset to pending status'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force reset even if document is not completed',
        )

    def handle(self, *args, **options):
        document_id = options['document_id']
        force = options['force']
        
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            raise CommandError(f'Document with ID {document_id} does not exist')

        old_status = document.status
        
        if not force and old_status not in ['completed', 'failed']:
            raise CommandError(
                f'Document status is "{old_status}". Use --force to reset anyway, '
                f'or only reset completed/failed documents.'
            )

        document.status = 'pending'
        document.processing_message = ''
        document.error_message = ''
        document.save(update_fields=['status', 'processing_message', 'error_message'])
        
        try:
            parsed_data = document.parsed_data
            parsed_data.is_approved = False
            parsed_data.reviewed_by = None
            parsed_data.reviewed_at = None
            parsed_data.review_notes = ''
            parsed_data.save()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully reset document {document_id} from "{old_status}" to "pending". '
                    f'ParsedData approval status also reset.'
                )
            )
        except Exception:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully reset document {document_id} from "{old_status}" to "pending". '
                    f'No parsed data found to reset.'
                )
            )
            
        self.stdout.write(
            f'Document "{document.filename}" is ready for reprocessing.'
        )
