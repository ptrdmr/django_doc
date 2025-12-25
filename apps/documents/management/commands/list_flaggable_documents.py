"""
Management command to list documents that can be flagged for testing.

Shows documents with ParsedData that are currently auto_approved or reviewed,
making them good candidates for temporary flagging to test the flagged UI.

Usage:
    python manage.py list_flaggable_documents
    python manage.py list_flaggable_documents --limit 10
"""
from django.core.management.base import BaseCommand
from apps.documents.models import Document, ParsedData
from django.db.models import Q


class Command(BaseCommand):
    help = 'List documents that can be flagged for testing the flagged document review UI'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=20,
            help='Maximum number of documents to display (default: 20)'
        )
        parser.add_argument(
            '--show-flagged',
            action='store_true',
            help='Also show currently flagged documents'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        show_flagged = options['show_flagged']
        
        self.stdout.write(
            self.style.SUCCESS('Documents Available for Flagging (Testing)\n')
        )
        
        # Build queryset
        # Use defer to skip fields that may not exist in database yet
        defer_fields = ['auto_approved', 'corrections', 'review_notes']
        
        if show_flagged:
            # Show all documents with ParsedData
            queryset = ParsedData.objects.select_related(
                'document',
                'patient'
            ).defer(*defer_fields).order_by('-created_at')
        else:
            # Only show non-flagged documents
            queryset = ParsedData.objects.exclude(
                review_status='flagged'
            ).select_related(
                'document',
                'patient'
            ).defer(*defer_fields).order_by('-created_at')
        
        total_count = queryset.count()
        items = queryset[:limit]
        
        if not items:
            self.stdout.write(
                self.style.WARNING('No documents found with ParsedData.')
            )
            self.stdout.write(
                'Upload and process some documents first, then run this command.'
            )
            return
        
        # Display table header
        self.stdout.write(
            f'{"ID":<6} {"Status":<15} {"Conf":<6} {"Patient":<30} {"Filename":<40}'
        )
        self.stdout.write('-' * 100)
        
        for item in items:
            doc_id = item.document.id
            status = item.review_status
            confidence = f'{item.extraction_confidence:.2f}' if item.extraction_confidence else 'N/A'
            patient_name = f'{item.patient.first_name} {item.patient.last_name}'
            filename = item.document.filename
            
            # Truncate long names/filenames
            if len(patient_name) > 28:
                patient_name = patient_name[:25] + '...'
            if len(filename) > 38:
                filename = filename[:35] + '...'
            
            # Color code by status
            if status == 'flagged':
                status_display = self.style.WARNING(f'{status:<15}')
            elif status == 'reviewed':
                status_display = self.style.SUCCESS(f'{status:<15}')
            else:
                status_display = f'{status:<15}'
            
            self.stdout.write(
                f'{doc_id:<6} {status_display} {confidence:<6} {patient_name:<30} {filename:<40}'
            )
        
        # Summary
        self.stdout.write('-' * 100)
        self.stdout.write(f'Showing {len(items)} of {total_count} documents\n')
        
        if not show_flagged:
            flagged_count = ParsedData.objects.filter(review_status='flagged').count()
            if flagged_count > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f'Note: {flagged_count} document(s) are currently flagged. '
                        'Use --show-flagged to see them.'
                    )
                )
        
        # Usage instructions
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('To flag a document for testing:'))
        if items:
            example_id = items[0].document.id
            self.stdout.write(
                f'  python manage.py flag_document_for_testing {example_id}'
            )
            self.stdout.write(
                f'  python manage.py flag_document_for_testing {example_id} '
                '--reason "Critical error: Test flag"'
            )
            self.stdout.write(
                f'  python manage.py flag_document_for_testing {example_id} --confidence 0.65'
            )
        
        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS('To view flagged documents:')
        )
        self.stdout.write('  Visit: http://localhost:8000/documents/flagged/')

