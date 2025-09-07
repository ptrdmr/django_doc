"""
Management command to reset document status for testing review workflow.
"""
from django.core.management.base import BaseCommand, CommandError
from apps.documents.models import Document


class Command(BaseCommand):
    help = 'Reset document status to review for testing the review workflow'

    def add_arguments(self, parser):
        parser.add_argument(
            'document_id',
            type=int,
            help='ID of the document to reset to review status'
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

        # Reset document to review status
        document.status = 'review'
        document.save()
        
        # Reset parsed data approval if it exists
        try:
            parsed_data = document.parsed_data
            parsed_data.is_approved = False
            parsed_data.reviewed_by = None
            parsed_data.reviewed_at = None
            parsed_data.review_notes = ''
            parsed_data.save()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully reset document {document_id} from "{old_status}" to "review" status. '
                    f'ParsedData approval status also reset.'
                )
            )
        except Exception:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully reset document {document_id} from "{old_status}" to "review" status. '
                    f'No parsed data found to reset.'
                )
            )
            
        self.stdout.write(
            f'Document "{document.filename}" is now ready for review testing.'
        )
