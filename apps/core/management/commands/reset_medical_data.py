"""
Management command to safely clear medical data while preserving users and roles.

This command removes all patient, provider, and document data from the database
while keeping user accounts, permissions, and role assignments intact.

Usage:
    python manage.py reset_medical_data [--yes]
    
Options:
    --yes    Skip confirmation prompt and proceed with deletion
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = 'Clear all medical data (patients, providers, documents) while preserving users and roles'

    def add_arguments(self, parser):
        parser.add_argument(
            '--yes',
            action='store_true',
            help='Skip confirmation prompt',
        )

    def handle(self, *args, **options):
        """Execute the medical data reset."""
        skip_confirm = options.get('yes', False)
        
        # Display warning
        self.stdout.write(self.style.WARNING('\n' + '='*70))
        self.stdout.write(self.style.WARNING('WARNING: Medical Data Reset'))
        self.stdout.write(self.style.WARNING('='*70))
        self.stdout.write('\nThis command will DELETE the following data:')
        self.stdout.write('  • All patients and patient history')
        self.stdout.write('  • All providers and provider history')
        self.stdout.write('  • All documents and parsed data')
        self.stdout.write('  • All FHIR merge operations')
        self.stdout.write('  • All patient data comparisons and audits')
        self.stdout.write('  • All generated reports and configurations')
        self.stdout.write('\nThis command will PRESERVE:')
        self.stdout.write(self.style.SUCCESS('  ✓ All user accounts'))
        self.stdout.write(self.style.SUCCESS('  ✓ All roles and permissions'))
        self.stdout.write(self.style.SUCCESS('  ✓ All organizations'))
        self.stdout.write(self.style.SUCCESS('  ✓ System configuration'))
        
        # Get counts before deletion
        counts = self._get_data_counts()
        
        self.stdout.write('\n' + '-'*70)
        self.stdout.write('Current data counts:')
        for model_name, count in counts.items():
            self.stdout.write(f'  {model_name}: {count}')
        self.stdout.write('-'*70 + '\n')
        
        # Confirmation prompt
        if not skip_confirm:
            confirm = input('Are you sure you want to proceed? Type "DELETE" to confirm: ')
            if confirm != 'DELETE':
                self.stdout.write(self.style.ERROR('Operation cancelled.'))
                return
        
        # Execute deletion
        self.stdout.write('\nStarting medical data deletion...')
        
        try:
            with transaction.atomic():
                deleted_counts = self._delete_medical_data()
                
            # Display results
            self.stdout.write('\n' + '='*70)
            self.stdout.write(self.style.SUCCESS('Medical data successfully deleted!'))
            self.stdout.write('='*70)
            self.stdout.write('\nDeleted records:')
            for model_name, count in deleted_counts.items():
                self.stdout.write(f'  {model_name}: {count}')
            
            self.stdout.write('\n' + self.style.SUCCESS('✓ Database is now clean and ready for testing'))
            self.stdout.write(self.style.SUCCESS('✓ All user accounts and roles preserved'))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\nError during deletion: {str(e)}'))
            raise

    def _get_data_counts(self):
        """Get counts of data to be deleted."""
        from apps.patients.models import Patient, PatientHistory
        from apps.providers.models import Provider, ProviderHistory
        from apps.documents.models import (
            Document, ParsedData, PatientDataComparison, PatientDataAudit
        )
        from apps.fhir.models import FHIRMergeOperation
        from apps.reports.models import ReportConfiguration, GeneratedReport
        
        return {
            'Patients': Patient.objects.count(),
            'Patient History': PatientHistory.objects.count(),
            'Providers': Provider.objects.count(),
            'Provider History': ProviderHistory.objects.count(),
            'Documents': Document.objects.count(),
            'Parsed Data': ParsedData.objects.count(),
            'Data Comparisons': PatientDataComparison.objects.count(),
            'Data Audits': PatientDataAudit.objects.count(),
            'FHIR Merge Operations': FHIRMergeOperation.objects.count(),
            'Generated Reports': GeneratedReport.objects.count(),
            'Report Configurations': ReportConfiguration.objects.count(),
        }

    def _delete_medical_data(self):
        """Delete all medical data in correct order to handle foreign keys."""
        from apps.patients.models import Patient, PatientHistory
        from apps.providers.models import Provider, ProviderHistory
        from apps.documents.models import (
            Document, ParsedData, PatientDataComparison, PatientDataAudit
        )
        from apps.fhir.models import FHIRMergeOperation
        from apps.reports.models import ReportConfiguration, GeneratedReport
        
        deleted_counts = {}
        
        # Delete in order to respect foreign key constraints
        
        # 1. Generated reports (no dependencies)
        self.stdout.write('  Deleting generated reports...')
        count, _ = GeneratedReport.objects.all().delete()
        deleted_counts['Generated Reports'] = count
        
        # 2. Report configurations (no dependencies)
        self.stdout.write('  Deleting report configurations...')
        count, _ = ReportConfiguration.objects.all().delete()
        deleted_counts['Report Configurations'] = count
        
        # 3. FHIR merge operations (references patients and documents)
        self.stdout.write('  Deleting FHIR merge operations...')
        count, _ = FHIRMergeOperation.objects.all().delete()
        deleted_counts['FHIR Merge Operations'] = count
        
        # 4. Patient data audits (references documents and patients)
        self.stdout.write('  Deleting patient data audits...')
        count, _ = PatientDataAudit.objects.all().delete()
        deleted_counts['Data Audits'] = count
        
        # 5. Patient data comparisons (references documents, patients, parsed data)
        self.stdout.write('  Deleting patient data comparisons...')
        count, _ = PatientDataComparison.objects.all().delete()
        deleted_counts['Data Comparisons'] = count
        
        # 6. Parsed data (references documents and patients)
        self.stdout.write('  Deleting parsed data...')
        count, _ = ParsedData.objects.all().delete()
        deleted_counts['Parsed Data'] = count
        
        # 7. Documents (references patients and providers via M2M)
        self.stdout.write('  Deleting documents...')
        count, _ = Document.objects.all().delete()
        deleted_counts['Documents'] = count
        
        # 8. Provider history (references providers)
        self.stdout.write('  Deleting provider history...')
        count, _ = ProviderHistory.objects.all().delete()
        deleted_counts['Provider History'] = count
        
        # 9. Providers
        self.stdout.write('  Deleting providers...')
        count, _ = Provider.objects.all().delete()
        deleted_counts['Providers'] = count
        
        # 10. Patient history (references patients)
        self.stdout.write('  Deleting patient history...')
        count, _ = PatientHistory.objects.all().delete()
        deleted_counts['Patient History'] = count
        
        # 11. Patients (base records)
        self.stdout.write('  Deleting patients...')
        count, _ = Patient.objects.all().delete()
        deleted_counts['Patients'] = count
        
        return deleted_counts
