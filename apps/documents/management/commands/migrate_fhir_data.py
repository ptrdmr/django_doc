"""
Management command to migrate FHIR data from recent documents to patient records.
This handles the case where documents were processed before the validation workflow
was implemented and need their FHIR data committed to patient profiles.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from apps.documents.models import Document, ParsedData
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Migrate FHIR data from recent documents to patient records'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=6,
            help='Look for documents from the past N hours (default: 6)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually doing it',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force migration even if data appears to be already merged',
        )

    def handle(self, *args, **options):
        """Migrate FHIR data from recent documents"""
        
        self.stdout.write(self.style.SUCCESS('=== FHIR Data Migration ==='))
        
        # Look for recent documents
        hours_back = options['hours']
        recent_cutoff = timezone.now() - timedelta(hours=hours_back)
        
        self.stdout.write(f"Looking for documents from the past {hours_back} hours...")
        
        # Get recent documents with their related data
        recent_docs = Document.objects.filter(
            uploaded_at__gte=recent_cutoff
        ).select_related('patient').prefetch_related('parsed_data_set').order_by('-uploaded_at')
        
        if not recent_docs:
            self.stdout.write(self.style.WARNING(f"No documents found from the past {hours_back} hours"))
            return
        
        self.stdout.write(f"Found {recent_docs.count()} recent documents")
        self.stdout.write("")
        
        migration_candidates = []
        
        for doc in recent_docs:
            self.stdout.write(f"Document ID {doc.id}: {doc.filename}")
            self.stdout.write(f"  Status: {doc.status}")
            self.stdout.write(f"  Patient: {doc.patient.first_name} {doc.patient.last_name} (MRN: {doc.patient.mrn})")
            self.stdout.write(f"  Uploaded: {doc.uploaded_at}")
            
            # Check for ParsedData
            try:
                parsed_data = doc.parsed_data
                self.stdout.write(f"  ParsedData: ID {parsed_data.id}")
                self.stdout.write(f"    Review Status: {parsed_data.review_status}")
                self.stdout.write(f"    Merged: {parsed_data.is_merged}")
                
                # Count FHIR resources
                fhir_data = parsed_data.fhir_delta_json
                if fhir_data:
                    if isinstance(fhir_data, list):
                        fhir_count = len(fhir_data)
                    elif isinstance(fhir_data, dict):
                        if fhir_data.get('resourceType') == 'Bundle':
                            fhir_count = len(fhir_data.get('entry', []))
                        else:
                            fhir_count = 1
                    else:
                        fhir_count = 0
                    
                    self.stdout.write(f"    FHIR Resources: {fhir_count}")
                    
                    # Check if this needs migration
                    needs_migration = False
                    if not parsed_data.is_merged and fhir_count > 0:
                        # Needs merge (approval not required in optimistic system)
                        needs_migration = True
                        self.stdout.write(self.style.WARNING("    → Needs merge"))
                    elif parsed_data.is_merged and options['force']:
                        needs_migration = True
                        self.stdout.write(self.style.WARNING("    → Already merged but --force specified"))
                    else:
                        self.stdout.write(self.style.SUCCESS("    → Already properly processed"))
                    
                    if needs_migration:
                        migration_candidates.append((doc, parsed_data, fhir_count))
                else:
                    self.stdout.write(f"    FHIR Resources: None")
                    
            except ParsedData.DoesNotExist:
                self.stdout.write(self.style.ERROR("  No ParsedData found"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Error checking ParsedData: {e}"))
            
            # Check current patient FHIR bundle
            try:
                bundle_entries = len(doc.patient.encrypted_fhir_bundle.get('entry', []))
                self.stdout.write(f"  Patient FHIR Bundle: {bundle_entries} entries")
            except Exception as e:
                self.stdout.write(f"  Patient FHIR Bundle: Error accessing ({e})")
            
            self.stdout.write("")
        
        # Process migration candidates
        if migration_candidates:
            self.stdout.write(self.style.SUCCESS(f"=== Migration Summary ==="))
            self.stdout.write(f"Found {len(migration_candidates)} documents needing FHIR data migration")
            
            if options['dry_run']:
                self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))
                for doc, parsed_data, fhir_count in migration_candidates:
                    self.stdout.write(f"  Would migrate: Doc {doc.id} ({fhir_count} FHIR resources)")
            else:
                self.stdout.write("Proceeding with migration...")
                
                success_count = 0
                for doc, parsed_data, fhir_count in migration_candidates:
                    try:
                        self.stdout.write(f"Migrating Document {doc.id}...")
                        
                        # Get FHIR data to merge
                        fhir_data = parsed_data.fhir_delta_json
                        if not fhir_data:
                            self.stdout.write(self.style.WARNING("  ~ No FHIR data to merge"))
                            continue
                        
                        # Convert FHIR data to list format if needed
                        fhir_resources = []
                        if isinstance(fhir_data, dict):
                            if fhir_data.get('resourceType') == 'Bundle' and 'entry' in fhir_data:
                                fhir_resources = [entry['resource'] for entry in fhir_data['entry'] if 'resource' in entry]
                            else:
                                fhir_resources = [fhir_data]
                        elif isinstance(fhir_data, list):
                            fhir_resources = fhir_data
                        
                        if not fhir_resources:
                            self.stdout.write(self.style.WARNING("  ~ No FHIR resources to merge"))
                            continue
                        
                        # Merge directly to patient record (inline, no task)
                        merge_success = doc.patient.add_fhir_resources(
                            fhir_resources,
                            document_id=doc.id
                        )
                        
                        if merge_success:
                            # Mark as merged
                            parsed_data.is_merged = True
                            parsed_data.merged_at = timezone.now()
                            parsed_data.save(update_fields=['is_merged', 'merged_at'])
                            
                            self.stdout.write(self.style.SUCCESS(f"  ✓ Successfully merged {len(fhir_resources)} resources"))
                            success_count += 1
                        else:
                            self.stdout.write(self.style.ERROR("  ✗ Merge failed"))
                            
                    except Exception as migration_error:
                        self.stdout.write(self.style.ERROR(f"  ✗ Migration failed: {migration_error}"))
                
                self.stdout.write("")
                self.stdout.write(self.style.SUCCESS(f"Migration completed: {success_count}/{len(migration_candidates)} documents processed"))
        else:
            self.stdout.write(self.style.SUCCESS("No documents need FHIR data migration"))
