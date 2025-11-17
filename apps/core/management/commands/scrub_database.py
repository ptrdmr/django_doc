"""
Django management command to scrub all medical data from the database.

This command removes all clinical/medical data while preserving:
- User accounts and authentication
- Groups and permissions
- System configuration

Usage:
    python manage.py scrub_database --dry-run  # Preview what will be deleted
    python manage.py scrub_database --confirm  # Actually delete data
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.contrib.auth.models import User
from django.utils import timezone
import time

# Import models for deletion
from apps.patients.models import Patient, PatientHistory
from apps.documents.models import Document, ParsedData, PatientDataComparison, PatientDataAudit
from apps.providers.models import Provider, ProviderHistory
from apps.reports.models import ReportConfiguration, GeneratedReport
from apps.core.models import AuditLog, APIUsageLog, SecurityEvent, ComplianceReport
from apps.fhir.models import FHIRMergeConfiguration, FHIRMergeConfigurationAudit, FHIRMergeOperation


class Command(BaseCommand):
    help = 'Scrub all medical data from database while preserving user accounts and auth'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Required flag to confirm deletion (prevents accidental execution)'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed progress during deletion'
        )
        parser.add_argument(
            '--yes',
            action='store_true',
            help='Skip interactive confirmation prompt (use with caution)'
        )

    def handle(self, *args, **options):
        """Execute database scrubbing."""
        dry_run = options['dry_run']
        confirm = options['confirm']
        verbose = options['verbose']
        
        # Safety check: require either dry-run or confirm
        if not dry_run and not confirm:
            raise CommandError(
                "You must specify either --dry-run or --confirm flag.\n"
                "Use --dry-run to preview deletion without making changes.\n"
                "Use --confirm to actually delete data."
            )
        
        # Display warning
        self.stdout.write(self.style.WARNING("\n" + "="*70))
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No data will be deleted"))
        else:
            self.stdout.write(self.style.ERROR("DATABASE SCRUB - ALL MEDICAL DATA WILL BE DELETED"))
        self.stdout.write(self.style.WARNING("="*70 + "\n"))
        
        # Get counts before deletion
        counts = self._get_counts()
        
        # Display what will be deleted
        self.stdout.write(self.style.WARNING("\nData to be DELETED:"))
        self.stdout.write(f"  - Patients: {counts['patients']} (including {counts['patient_history']} history records)")
        self.stdout.write(f"  - Documents: {counts['documents']}")
        self.stdout.write(f"  - Parsed Data: {counts['parsed_data']}")
        self.stdout.write(f"  - Patient Comparisons: {counts['comparisons']}")
        self.stdout.write(f"  - Patient Data Audits: {counts['audits']}")
        self.stdout.write(f"  - Providers: {counts['providers']} (including {counts['provider_history']} history records)")
        self.stdout.write(f"  - Generated Reports: {counts['reports']}")
        self.stdout.write(f"  - Report Configurations: {counts['report_configs']}")
        self.stdout.write(f"  - Audit Logs: {counts['audit_logs']}")
        self.stdout.write(f"  - API Usage Logs: {counts['api_logs']}")
        self.stdout.write(f"  - Security Events: {counts['security_events']}")
        self.stdout.write(f"  - Compliance Reports: {counts['compliance_reports']}")
        self.stdout.write(f"  - FHIR Merge Operations: {counts['fhir_operations']}")
        self.stdout.write(f"  - FHIR Merge Configs: {counts['fhir_configs']}")
        self.stdout.write(f"  - FHIR Config Audits: {counts['fhir_config_audits']}")
        
        total_records = sum(counts.values())
        self.stdout.write(self.style.ERROR(f"\n  TOTAL RECORDS TO DELETE: {total_records}\n"))
        
        # Display what will be preserved
        user_count = User.objects.count()
        self.stdout.write(self.style.SUCCESS("Data to be PRESERVED:"))
        self.stdout.write(f"  - Users: {user_count}")
        self.stdout.write(f"  - Groups and Permissions")
        self.stdout.write(f"  - Django System Tables")
        self.stdout.write(f"  - Porthole folder (file system - not touched)")
        
        if dry_run:
            self.stdout.write(self.style.SUCCESS("\n✓ Dry run complete - no changes made"))
            return
        
        # Final confirmation for actual deletion
        self.stdout.write(self.style.ERROR(f"\n⚠️  WARNING: About to delete {total_records} records!"))
        self.stdout.write("This action cannot be undone.\n")
        
        # Skip interactive prompt if --yes flag is used
        if not options['yes']:
            confirm_text = input("Type 'DELETE ALL MEDICAL DATA' to confirm: ")
            
            if confirm_text != "DELETE ALL MEDICAL DATA":
                self.stdout.write(self.style.ERROR("Confirmation text did not match. Aborting."))
                return
        else:
            self.stdout.write(self.style.WARNING("--yes flag used, skipping interactive confirmation"))
        
        # Perform deletion
        self.stdout.write(self.style.WARNING("\nStarting database scrub..."))
        start_time = time.time()
        
        try:
            with transaction.atomic():
                deleted_counts = self._delete_all_medical_data(verbose)
                
            duration = time.time() - start_time
            
            # Success summary
            self.stdout.write(self.style.SUCCESS(f"\n{'='*70}"))
            self.stdout.write(self.style.SUCCESS("✓ Database scrub completed successfully"))
            self.stdout.write(self.style.SUCCESS(f"  Duration: {duration:.2f} seconds"))
            self.stdout.write(self.style.SUCCESS(f"  Total records deleted: {sum(deleted_counts.values())}"))
            self.stdout.write(self.style.SUCCESS(f"  Users preserved: {User.objects.count()}"))
            self.stdout.write(self.style.SUCCESS(f"{'='*70}\n"))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n✗ Error during database scrub: {e}"))
            raise CommandError(f"Database scrub failed: {e}")
    
    def _get_counts(self):
        """Get counts of all records that will be deleted."""
        return {
            'patients': Patient.all_objects.count(),
            'patient_history': PatientHistory.objects.count(),
            'documents': Document.objects.count(),
            'parsed_data': ParsedData.objects.count(),
            'comparisons': PatientDataComparison.objects.count(),
            'audits': PatientDataAudit.objects.count(),
            'providers': Provider.all_objects.count(),
            'provider_history': ProviderHistory.objects.count(),
            'reports': GeneratedReport.objects.count(),
            'report_configs': ReportConfiguration.objects.count(),
            'audit_logs': AuditLog.objects.count(),
            'api_logs': APIUsageLog.objects.count(),
            'security_events': SecurityEvent.objects.count(),
            'compliance_reports': ComplianceReport.objects.count(),
            'fhir_operations': FHIRMergeOperation.objects.count(),
            'fhir_configs': FHIRMergeConfiguration.objects.count(),
            'fhir_config_audits': FHIRMergeConfigurationAudit.objects.count(),
        }
    
    def _delete_all_medical_data(self, verbose):
        """Delete all medical data in proper order (respects foreign key constraints)."""
        deleted_counts = {}
        
        # Delete in order that respects foreign key constraints
        # Start with dependent records, then parent records
        
        if verbose:
            self.stdout.write("\nDeleting dependent records...")
        
        # 1. Patient History (depends on Patient)
        deleted_counts['patient_history'] = PatientHistory.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['patient_history']} patient history records")
        
        # 2. Provider History (depends on Provider)
        deleted_counts['provider_history'] = ProviderHistory.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['provider_history']} provider history records")
        
        # 3. Parsed Data (depends on Document and Patient)
        deleted_counts['parsed_data'] = ParsedData.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['parsed_data']} parsed data records")
        
        # 4. Patient Data Comparisons (depends on Patient)
        deleted_counts['comparisons'] = PatientDataComparison.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['comparisons']} comparison records")
        
        # 5. Patient Data Audits (depends on Patient)
        deleted_counts['audits'] = PatientDataAudit.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['audits']} audit records")
        
        # 6. Generated Reports (depends on ReportConfiguration)
        deleted_counts['reports'] = GeneratedReport.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['reports']} generated reports")
        
        # 7. Report Configurations (depends on User - but we keep users)
        deleted_counts['report_configs'] = ReportConfiguration.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['report_configs']} report configurations")
        
        # 8. FHIR Merge Operations
        deleted_counts['fhir_operations'] = FHIRMergeOperation.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['fhir_operations']} FHIR merge operations")
        
        # 9. FHIR Config Audits
        deleted_counts['fhir_config_audits'] = FHIRMergeConfigurationAudit.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['fhir_config_audits']} FHIR config audits")
        
        # 10. FHIR Merge Configurations
        deleted_counts['fhir_configs'] = FHIRMergeConfiguration.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['fhir_configs']} FHIR configurations")
        
        if verbose:
            self.stdout.write("\nDeleting parent records...")
        
        # 11. Documents (parent table)
        deleted_counts['documents'] = Document.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['documents']} documents")
        
        # 12. Patients (parent table, includes soft-deleted)
        deleted_counts['patients'] = Patient.all_objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['patients']} patients")
        
        # 13. Providers (parent table, includes soft-deleted)
        deleted_counts['providers'] = Provider.all_objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['providers']} providers")
        
        if verbose:
            self.stdout.write("\nDeleting audit and logging data...")
        
        # 14. Audit Logs
        deleted_counts['audit_logs'] = AuditLog.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['audit_logs']} audit logs")
        
        # 15. API Usage Logs
        deleted_counts['api_logs'] = APIUsageLog.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['api_logs']} API usage logs")
        
        # 16. Security Events
        deleted_counts['security_events'] = SecurityEvent.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['security_events']} security events")
        
        # 17. Compliance Reports
        deleted_counts['compliance_reports'] = ComplianceReport.objects.all().delete()[0]
        if verbose:
            self.stdout.write(f"  ✓ Deleted {deleted_counts['compliance_reports']} compliance reports")
        
        return deleted_counts

