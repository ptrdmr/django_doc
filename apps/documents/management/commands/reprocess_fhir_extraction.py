"""
Management command to reprocess documents with FHIR-focused extraction.

This command reprocesses existing documents using the new FHIR-focused extraction
to generate individual FHIR resources with proper temporal data instead of 
concatenated strings. Useful for migrating from legacy extraction format.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db import transaction
from datetime import timedelta
from apps.documents.models import Document, ParsedData
from apps.documents.services import DocumentAnalyzer, PDFTextExtractor
from apps.patients.models import Patient
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Reprocess documents with FHIR-focused extraction for improved data structure'

    def add_arguments(self, parser):
        parser.add_argument(
            '--document-ids',
            nargs='+',
            type=int,
            help='Specific document IDs to reprocess (space-separated)',
        )
        parser.add_argument(
            '--patient-mrn',
            type=str,
            help='Reprocess all documents for a specific patient MRN',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Reprocess documents from the past N days (default: 30)',
        )
        parser.add_argument(
            '--status',
            choices=['pending', 'processing', 'completed', 'failed', 'review'],
            help='Only reprocess documents with specific status',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be reprocessed without actually doing it',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force reprocessing even if documents already have FHIR data',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=10,
            help='Number of documents to process in each batch (default: 10)',
        )

    def handle(self, *args, **options):
        """Reprocess documents with FHIR-focused extraction"""
        
        self.stdout.write(self.style.SUCCESS('=== FHIR-Focused Extraction Reprocessing ==='))
        
        # Build queryset based on options
        queryset = self._build_queryset(options)
        
        if not queryset.exists():
            self.stdout.write(self.style.WARNING("No documents found matching criteria"))
            return
        
        total_docs = queryset.count()
        self.stdout.write(f"Found {total_docs} documents to reprocess")
        
        if options['dry_run']:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))
            self._show_dry_run_summary(queryset)
            return
        
        # Process documents in batches
        batch_size = options['batch_size']
        success_count = 0
        error_count = 0
        
        for i in range(0, total_docs, batch_size):
            batch = queryset[i:i + batch_size]
            self.stdout.write(f"\nProcessing batch {i//batch_size + 1} ({len(batch)} documents)...")
            
            for doc in batch:
                try:
                    success = self._reprocess_document(doc, options)
                    if success:
                        success_count += 1
                        self.stdout.write(self.style.SUCCESS(f"  ✓ Document {doc.id}: {doc.filename}"))
                    else:
                        error_count += 1
                        self.stdout.write(self.style.ERROR(f"  ✗ Document {doc.id}: Failed to reprocess"))
                        
                except Exception as e:
                    error_count += 1
                    self.stdout.write(self.style.ERROR(f"  ✗ Document {doc.id}: {str(e)}"))
                    logger.error(f"Error reprocessing document {doc.id}: {e}")
        
        # Final summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Reprocessing Summary ==="))
        self.stdout.write(f"Total documents: {total_docs}")
        self.stdout.write(f"Successfully reprocessed: {success_count}")
        self.stdout.write(f"Errors: {error_count}")
        
        if error_count > 0:
            self.stdout.write(self.style.WARNING(f"Check logs for error details"))

    def _build_queryset(self, options):
        """Build document queryset based on command options"""
        queryset = Document.objects.select_related('patient')
        
        # Filter by specific document IDs
        if options['document_ids']:
            queryset = queryset.filter(id__in=options['document_ids'])
        
        # Filter by patient MRN
        elif options['patient_mrn']:
            try:
                patient = Patient.objects.get(mrn=options['patient_mrn'])
                queryset = queryset.filter(patient=patient)
            except Patient.DoesNotExist:
                raise CommandError(f"Patient with MRN '{options['patient_mrn']}' not found")
        
        # Filter by date range (only if not filtering by specific IDs or patient)
        elif not options['document_ids'] and not options['patient_mrn']:
            days_back = options['days']
            date_cutoff = timezone.now() - timedelta(days=days_back)
            queryset = queryset.filter(uploaded_at__gte=date_cutoff)
        
        # Filter by status
        if options['status']:
            queryset = queryset.filter(status=options['status'])
        
        return queryset.order_by('-uploaded_at')

    def _show_dry_run_summary(self, queryset):
        """Show what would be reprocessed in dry run mode"""
        for doc in queryset[:20]:  # Show first 20 documents
            self.stdout.write(f"Would reprocess: Document {doc.id} - {doc.filename}")
            self.stdout.write(f"  Patient: {doc.patient.mrn}")
            self.stdout.write(f"  Status: {doc.status}")
            
            # Check current ParsedData
            try:
                parsed_data = doc.parsed_data
                fhir_count = parsed_data.get_fhir_resource_count()
                self.stdout.write(f"  Current FHIR resources: {fhir_count}")
            except ParsedData.DoesNotExist:
                self.stdout.write(f"  Current FHIR resources: None")
            
            self.stdout.write("")
        
        if queryset.count() > 20:
            self.stdout.write(f"... and {queryset.count() - 20} more documents")

    def _reprocess_document(self, document, options):
        """
        Reprocess a single document with FHIR-focused extraction.
        
        Args:
            document: Document instance to reprocess
            options: Command options
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check if document has text content
            if not document.original_text:
                self.stdout.write(f"    Skipping Document {document.id}: No extracted text")
                return False
            
            # Check if we should skip already processed documents
            if not options['force']:
                try:
                    parsed_data = document.parsed_data
                    if parsed_data.is_merged and parsed_data.get_fhir_resource_count() > 0:
                        self.stdout.write(f"    Skipping Document {document.id}: Already has FHIR data (use --force to override)")
                        return False
                except ParsedData.DoesNotExist:
                    pass  # No parsed data, proceed with reprocessing
            
            # Initialize document analyzer with FHIR-focused extraction
            analyzer = DocumentAnalyzer(document=document)
            
            # Reprocess the document text
            self.stdout.write(f"    Reprocessing with FHIR-focused extraction...")
            
            # Extract using FHIR-focused mode (this will now use the new format)
            ai_result = analyzer.analyze_document(
                document_content=document.original_text,
                context=f"Reprocessing for FHIR compliance - {document.filename}"
            )
            
            if not ai_result.get('success'):
                self.stdout.write(f"    AI extraction failed: {ai_result.get('error', 'Unknown error')}")
                return False
            
            # Convert to FHIR resources (will use new structured format)
            patient_id = str(document.patient.id)
            fhir_resources = analyzer.convert_to_fhir(ai_result['fields'], patient_id)
            
            if not fhir_resources:
                self.stdout.write(f"    No FHIR resources generated")
                return False
            
            # Calculate metrics if available
            try:
                from apps.fhir.services import FHIRMetricsService
                metrics_service = FHIRMetricsService()
                capture_metrics = metrics_service.calculate_data_capture_metrics(
                    ai_result['fields'], fhir_resources
                )
                ai_result['capture_metrics'] = capture_metrics
            except Exception as metrics_error:
                self.stdout.write(f"    Warning: Metrics calculation failed: {metrics_error}")
            
            # Create or update ParsedData record
            with transaction.atomic():
                # Extract snippet data from fields
                fields_data = ai_result.get('fields', [])
                snippets_data = {}
                
                # Handle both legacy and new FHIR formats for snippet extraction
                if isinstance(fields_data, dict):
                    # New FHIR-structured format
                    for resource_type, resource_data in fields_data.items():
                        if isinstance(resource_data, list):
                            for i, resource in enumerate(resource_data):
                                for field_name, field_data in resource.items():
                                    if isinstance(field_data, dict) and 'source_text' in field_data:
                                        snippet_key = f"{resource_type}_{i}_{field_name}"
                                        snippets_data[snippet_key] = {
                                            'source_text': field_data.get('source_text', ''),
                                            'char_position': field_data.get('char_position', 0)
                                        }
                        elif isinstance(resource_data, dict):
                            for field_name, field_data in resource_data.items():
                                if isinstance(field_data, dict) and 'source_text' in field_data:
                                    snippet_key = f"{resource_type}_{field_name}"
                                    snippets_data[snippet_key] = {
                                        'source_text': field_data.get('source_text', ''),
                                        'char_position': field_data.get('char_position', 0)
                                    }
                elif isinstance(fields_data, list):
                    # Legacy format
                    for field in fields_data:
                        field_label = field.get('label', '')
                        if field_label and ('source_text' in field or 'char_position' in field):
                            snippets_data[field_label] = {
                                'source_text': field.get('source_text', ''),
                                'char_position': field.get('char_position', 0)
                            }
                
                # Calculate average confidence
                avg_confidence = 0.0
                if isinstance(fields_data, list) and fields_data:
                    confidences = [field.get('confidence', 0.0) for field in fields_data if isinstance(field, dict)]
                    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
                elif isinstance(fields_data, dict):
                    # For FHIR-structured format, extract confidence from nested data
                    all_confidences = []
                    for resource_type, resource_data in fields_data.items():
                        if isinstance(resource_data, list):
                            for resource in resource_data:
                                for field_name, field_data in resource.items():
                                    if isinstance(field_data, dict) and 'confidence' in field_data:
                                        all_confidences.append(field_data['confidence'])
                        elif isinstance(resource_data, dict):
                            for field_name, field_data in resource_data.items():
                                if isinstance(field_data, dict) and 'confidence' in field_data:
                                    all_confidences.append(field_data['confidence'])
                    avg_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0.0
                
                # Update or create ParsedData
                parsed_data, created = ParsedData.objects.update_or_create(
                    document=document,
                    defaults={
                        'patient': document.patient,
                        'extraction_json': fields_data,
                        'source_snippets': snippets_data,
                        'fhir_delta_json': fhir_resources,
                        'extraction_confidence': avg_confidence,
                        'ai_model_used': ai_result.get('model_used', 'reprocessing'),
                        'processing_time_seconds': ai_result.get('processing_duration_ms', 0) / 1000.0,
                        'capture_metrics': ai_result.get('capture_metrics', {}),
                        'is_approved': False,  # Reset approval for reprocessed data
                        'is_merged': False,    # Reset merge status
                        'reviewed_at': None,   # Clear review timestamp
                        'reviewed_by': None,   # Clear reviewer
                    }
                )
                
                action = "Created" if created else "Updated"
                self.stdout.write(f"    ✓ {action} ParsedData with {len(fhir_resources)} FHIR resources")
                
                # Update document status
                document.status = 'review'  # Mark for review since we reset approval
                document.processed_at = timezone.now()
                document.error_message = ''
                document.save()
                
                self.stdout.write(f"    ✓ Document marked for review")
                
            return True
            
        except Exception as e:
            self.stdout.write(f"    Error reprocessing document: {e}")
            logger.error(f"Error reprocessing document {document.id}: {e}")
            return False

    def _get_reprocessing_summary(self, document):
        """Get summary of what will be reprocessed for a document"""
        summary = {
            'id': document.id,
            'filename': document.filename,
            'patient_mrn': document.patient.mrn,
            'status': document.status,
            'has_text': bool(document.original_text),
            'text_length': len(document.original_text) if document.original_text else 0,
        }
        
        # Check current ParsedData
        try:
            parsed_data = document.parsed_data
            summary.update({
                'has_parsed_data': True,
                'current_fhir_count': parsed_data.get_fhir_resource_count(),
                'is_approved': parsed_data.is_approved,
                'is_merged': parsed_data.is_merged,
                'extraction_confidence': parsed_data.extraction_confidence,
            })
        except ParsedData.DoesNotExist:
            summary.update({
                'has_parsed_data': False,
                'current_fhir_count': 0,
                'is_approved': False,
                'is_merged': False,
                'extraction_confidence': None,
            })
        
        return summary
