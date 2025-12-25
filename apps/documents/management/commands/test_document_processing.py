"""
Management command to test document processing with optimistic merge system.

Usage:
    python manage.py test_document_processing <document_id>
    python manage.py test_document_processing --all
    python manage.py test_document_processing --upload <pdf_path>
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from apps.documents.models import Document, ParsedData
from apps.patients.models import Patient
from apps.documents.tasks import process_document_async
import os


class Command(BaseCommand):
    help = 'Test document processing with optimistic merge system'

    def add_arguments(self, parser):
        parser.add_argument(
            'document_id',
            nargs='?',
            type=int,
            help='Document ID to process'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Process all pending documents'
        )
        parser.add_argument(
            '--upload',
            type=str,
            help='Upload and process a PDF file (provide path)'
        )
        parser.add_argument(
            '--patient-id',
            type=int,
            help='Patient ID for uploaded document (required with --upload)'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output including FHIR resources'
        )

    def handle(self, *args, **options):
        if options['upload']:
            self.handle_upload(options)
        elif options['all']:
            self.handle_all()
        elif options['document_id']:
            self.handle_single(options['document_id'], options['verbose'])
        else:
            raise CommandError('Provide document_id, --all, or --upload')

    def handle_upload(self, options):
        """Upload a new document and process it"""
        pdf_path = options['upload']
        patient_id = options.get('patient_id')
        
        if not patient_id:
            raise CommandError('--patient-id required when using --upload')
        
        if not os.path.exists(pdf_path):
            raise CommandError(f'File not found: {pdf_path}')
        
        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            raise CommandError(f'Patient {patient_id} not found')
        
        self.stdout.write(f"\n📄 Uploading document: {os.path.basename(pdf_path)}")
        self.stdout.write(f"   Patient: {patient.first_name} {patient.last_name} (MRN: {patient.mrn})")
        
        # Create document record
        with open(pdf_path, 'rb') as f:
            from django.core.files import File
            doc = Document.objects.create(
                patient=patient,
                file=File(f, name=os.path.basename(pdf_path)),
                status='pending',
                uploaded_by=None  # System upload
            )
        
        self.stdout.write(self.style.SUCCESS(f"✓ Document created with ID: {doc.id}"))
        
        # Process it
        self.stdout.write(f"\n🔄 Processing document...")
        self.handle_single(doc.id, options.get('verbose', False))

    def handle_all(self):
        """Process all pending documents"""
        docs = Document.objects.filter(status='pending')
        count = docs.count()
        
        if count == 0:
            self.stdout.write(self.style.WARNING('No pending documents found'))
            return
        
        self.stdout.write(f"\n📋 Found {count} pending document(s)")
        self.stdout.write("="*70)
        
        for i, doc in enumerate(docs, 1):
            self.stdout.write(f"\n[{i}/{count}] Processing document {doc.id}...")
            try:
                self.handle_single(doc.id, verbose=False)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ✗ Error: {str(e)}"))
        
        self.stdout.write("\n" + "="*70)
        self.stdout.write(self.style.SUCCESS(f"✓ Batch processing complete: {count} documents"))

    def handle_single(self, doc_id, verbose=False):
        """Process a single document and display results"""
        try:
            doc = Document.objects.get(id=doc_id)
        except Document.DoesNotExist:
            raise CommandError(f'Document {doc_id} not found')
        
        # Check if already processed
        existing_parsed = ParsedData.objects.filter(document=doc).first()
        if existing_parsed and existing_parsed.is_merged:
            self.stdout.write(self.style.WARNING(
                f"⚠ Document {doc_id} already processed (is_merged=True)"
            ))
            self.display_results(doc, existing_parsed, verbose)
            return
        
        # Process the document
        start_time = timezone.now()
        
        try:
            self.stdout.write(f"🔄 Processing document {doc_id}...")
            result = process_document_async(doc_id)
            
            processing_time = (timezone.now() - start_time).total_seconds()
            
            # Get the parsed data
            parsed = ParsedData.objects.filter(document=doc).first()
            
            if not parsed:
                raise CommandError('No ParsedData created - processing may have failed')
            
            # Display results
            self.stdout.write(self.style.SUCCESS(f"\n✓ Processing complete! ({processing_time:.2f}s)"))
            self.display_results(doc, parsed, verbose)
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n✗ Processing failed: {str(e)}"))
            raise

    def display_results(self, doc, parsed, verbose=False):
        """Display processing results in a formatted way"""
        
        # Header
        self.stdout.write("\n" + "="*70)
        self.stdout.write(f"DOCUMENT {doc.id} - PROCESSING RESULTS")
        self.stdout.write("="*70)
        
        # Document info
        self.stdout.write(f"\n📄 Document Info:")
        self.stdout.write(f"   File: {os.path.basename(doc.file.name)}")
        self.stdout.write(f"   Patient: {doc.patient.first_name} {doc.patient.last_name} (MRN: {doc.patient.mrn})")
        self.stdout.write(f"   Status: {doc.status}")
        
        # Quality check results
        self.stdout.write(f"\n🔍 Quality Check Results:")
        
        if parsed.auto_approved:
            self.stdout.write(self.style.SUCCESS(f"   ✓ AUTO-APPROVED"))
        else:
            self.stdout.write(self.style.WARNING(f"   ⚠ FLAGGED FOR REVIEW"))
        
        self.stdout.write(f"   Review Status: {parsed.review_status}")
        self.stdout.write(f"   Confidence: {parsed.extraction_confidence:.2%}")
        self.stdout.write(f"   AI Model: {parsed.ai_model_used or 'N/A'}")
        
        if parsed.flag_reason:
            self.stdout.write(self.style.WARNING(f"   Flag Reason: {parsed.flag_reason}"))
        
        # FHIR extraction results
        resource_count = parsed.get_fhir_resource_count()
        self.stdout.write(f"\n📊 FHIR Extraction:")
        self.stdout.write(f"   Resources Extracted: {resource_count}")
        
        if verbose and resource_count > 0:
            # Show resource breakdown
            fhir_data = parsed.fhir_delta_json
            if isinstance(fhir_data, list):
                resource_types = {}
                for resource in fhir_data:
                    rtype = resource.get('resourceType', 'Unknown')
                    resource_types[rtype] = resource_types.get(rtype, 0) + 1
                
                self.stdout.write(f"   Resource Breakdown:")
                for rtype, count in sorted(resource_types.items()):
                    self.stdout.write(f"     - {rtype}: {count}")
        
        # Merge status
        self.stdout.write(f"\n🔄 Merge Status:")
        if parsed.is_merged:
            self.stdout.write(self.style.SUCCESS(f"   ✓ MERGED to patient record"))
            self.stdout.write(f"   Merged At: {parsed.merged_at.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            self.stdout.write(self.style.ERROR(f"   ✗ NOT MERGED"))
        
        # Patient bundle info
        patient = doc.patient
        patient.refresh_from_db()
        bundle = patient.encrypted_fhir_bundle
        bundle_count = len(bundle.get('entry', []))
        
        self.stdout.write(f"\n👤 Patient FHIR Bundle:")
        self.stdout.write(f"   Total Resources: {bundle_count}")
        
        if verbose and bundle_count > 0:
            # Show bundle resource breakdown
            resource_types = {}
            for entry in bundle.get('entry', []):
                resource = entry.get('resource', {})
                rtype = resource.get('resourceType', 'Unknown')
                resource_types[rtype] = resource_types.get(rtype, 0) + 1
            
            self.stdout.write(f"   Bundle Breakdown:")
            for rtype, count in sorted(resource_types.items()):
                self.stdout.write(f"     - {rtype}: {count}")
        
        # Processing metadata
        if verbose:
            self.stdout.write(f"\n⏱ Processing Metadata:")
            if parsed.processing_time_seconds:
                self.stdout.write(f"   Processing Time: {parsed.processing_time_seconds:.2f}s")
            self.stdout.write(f"   Created: {parsed.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            if parsed.updated_at != parsed.created_at:
                self.stdout.write(f"   Updated: {parsed.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        
        self.stdout.write("="*70 + "\n")

