"""
Management command to artificially flag a document for UI testing purposes.

This is a development/testing tool to verify the flagged document review interface
works correctly when no naturally-flagged documents exist.

Usage:
    python manage.py flag_document_for_testing <document_id>
    python manage.py flag_document_for_testing <document_id> --reason "Custom flag reason"
    python manage.py flag_document_for_testing <document_id> --confidence 0.65
"""
from django.core.management.base import BaseCommand, CommandError
from apps.documents.models import Document, ParsedData


class Command(BaseCommand):
    help = 'Artificially flag a document for testing the flagged document review UI'

    def add_arguments(self, parser):
        parser.add_argument(
            'document_id',
            type=int,
            help='ID of the document to flag'
        )
        parser.add_argument(
            '--reason',
            type=str,
            default='Low extraction confidence (manually flagged for testing)',
            help='Custom flag reason text'
        )
        parser.add_argument(
            '--confidence',
            type=float,
            default=0.75,
            help='Set extraction confidence (0.0-1.0) to simulate low confidence'
        )
        parser.add_argument(
            '--unflag',
            action='store_true',
            help='Remove flag and restore to previous state'
        )

    def handle(self, *args, **options):
        document_id = options['document_id']
        flag_reason = options['reason']
        confidence = options['confidence']
        unflag = options['unflag']
        
        # Validate confidence range
        if not 0.0 <= confidence <= 1.0:
            raise CommandError('Confidence must be between 0.0 and 1.0')
        
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            raise CommandError(f'Document with ID {document_id} does not exist')
        
        # Check if ParsedData exists
        try:
            parsed_data = document.parsed_data
        except ParsedData.DoesNotExist:
            raise CommandError(
                f'Document {document_id} has no ParsedData. '
                'Process the document first before flagging it.'
            )
        
        if unflag:
            # Restore to reviewed state
            old_status = parsed_data.review_status
            parsed_data.review_status = 'reviewed'
            parsed_data.flag_reason = ''
            parsed_data.save()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'✓ Unflagged ParsedData {parsed_data.id} '
                    f'(was: {old_status}, now: {parsed_data.review_status})'
                )
            )
            self.stdout.write(
                f'  Document: {document.filename}'
            )
            self.stdout.write(
                f'  Patient: {document.patient.first_name} {document.patient.last_name}'
            )
            return
        
        # Store original state
        original_status = parsed_data.review_status
        original_confidence = parsed_data.extraction_confidence
        
        # Flag the document
        parsed_data.review_status = 'flagged'
        parsed_data.flag_reason = flag_reason
        parsed_data.extraction_confidence = confidence
        parsed_data.save()
        
        self.stdout.write(
            self.style.SUCCESS(
                f'✓ Flagged ParsedData {parsed_data.id} for testing'
            )
        )
        self.stdout.write(f'  Document: {document.filename}')
        self.stdout.write(f'  Patient: {document.patient.first_name} {document.patient.last_name}')
        self.stdout.write(f'  Original status: {original_status}')
        self.stdout.write(f'  New status: flagged')
        self.stdout.write(f'  Original confidence: {original_confidence}')
        self.stdout.write(f'  New confidence: {confidence}')
        self.stdout.write(f'  Flag reason: {flag_reason}')
        self.stdout.write('')
        self.stdout.write(
            self.style.WARNING(
                'To view flagged documents, visit: http://localhost:8000/documents/flagged/'
            )
        )
        self.stdout.write(
            self.style.WARNING(
                f'To unflag this document later: python manage.py flag_document_for_testing {document_id} --unflag'
            )
        )

