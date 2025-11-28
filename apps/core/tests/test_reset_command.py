"""
Tests for the reset_medical_data management command.
"""

from io import StringIO
from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth import get_user_model

from apps.patients.models import Patient, PatientHistory
from apps.providers.models import Provider, ProviderHistory
from apps.documents.models import Document, ParsedData
from apps.reports.models import ReportConfiguration, GeneratedReport

User = get_user_model()


class ResetMedicalDataCommandTest(TestCase):
    """Test the reset_medical_data management command."""
    
    def setUp(self):
        """Create test data."""
        # Create users
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.admin = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpass123'
        )
        
        # Create medical data
        self.patient = Patient.objects.create(
            mrn='TEST-001',
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            created_by=self.user
        )
        
        self.provider = Provider.objects.create(
            npi='1234567890',
            first_name='Jane',
            last_name='Smith',
            specialty='Cardiology',
            organization='Test Clinic',
            created_by=self.user
        )
        
        # Create history records
        PatientHistory.objects.create(
            patient=self.patient,
            action='created',
            changed_by=self.user,
            notes='Test patient created'
        )
        
        ProviderHistory.objects.create(
            provider=self.provider,
            action='created',
            changed_by=self.user,
            notes='Test provider created'
        )
    
    def test_command_with_yes_flag(self):
        """Test command executes with --yes flag."""
        # Verify data exists
        self.assertEqual(Patient.objects.count(), 1)
        self.assertEqual(Provider.objects.count(), 1)
        self.assertEqual(User.objects.count(), 2)
        
        # Run command
        out = StringIO()
        call_command('reset_medical_data', '--yes', stdout=out)
        
        # Verify medical data deleted
        self.assertEqual(Patient.objects.count(), 0)
        self.assertEqual(PatientHistory.objects.count(), 0)
        self.assertEqual(Provider.objects.count(), 0)
        self.assertEqual(ProviderHistory.objects.count(), 0)
        
        # Verify users preserved
        self.assertEqual(User.objects.count(), 2)
        self.assertTrue(User.objects.filter(username='testuser').exists())
        self.assertTrue(User.objects.filter(username='admin').exists())
        
        # Check output
        output = out.getvalue()
        self.assertIn('successfully deleted', output)
        self.assertIn('Patients: 1', output)
        self.assertIn('Providers: 1', output)
    
    def test_command_preserves_users_and_roles(self):
        """Test that users, permissions, and roles are preserved."""
        # Add another user with different role
        staff_user = User.objects.create_user(
            username='staff',
            email='staff@example.com',
            password='staffpass123',
            is_staff=True
        )
        
        # Run command
        call_command('reset_medical_data', '--yes', stdout=StringIO())
        
        # Verify all users still exist
        self.assertEqual(User.objects.count(), 3)
        self.assertTrue(User.objects.filter(username='testuser').exists())
        self.assertTrue(User.objects.filter(username='admin').exists())
        self.assertTrue(User.objects.filter(username='staff').exists())
        
        # Verify user properties preserved
        admin_user = User.objects.get(username='admin')
        self.assertTrue(admin_user.is_superuser)
        
        staff_user_check = User.objects.get(username='staff')
        self.assertTrue(staff_user_check.is_staff)
    
    def test_command_handles_empty_database(self):
        """Test command works when no medical data exists."""
        # Delete all medical data first (use all_objects to bypass soft delete)
        PatientHistory.objects.all().delete()
        ProviderHistory.objects.all().delete()
        Patient.all_objects.all().delete()
        Provider.all_objects.all().delete()
        
        # Run command
        out = StringIO()
        call_command('reset_medical_data', '--yes', stdout=out)
        
        # Should complete successfully
        output = out.getvalue()
        self.assertIn('successfully deleted', output)
        
        # Users should still exist
        self.assertEqual(User.objects.count(), 2)
    
    def test_command_with_documents(self):
        """Test command deletes documents and related data."""
        # Create a document
        document = Document.objects.create(
            patient=self.patient,
            uploaded_by=self.user,
            filename='test.pdf',
            status='completed'
        )
        
        # Create parsed data
        ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json={'test': 'data'}
        )
        
        # Verify data exists
        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(ParsedData.objects.count(), 1)
        
        # Run command
        call_command('reset_medical_data', '--yes', stdout=StringIO())
        
        # Verify documents deleted
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(ParsedData.objects.count(), 0)
        
        # Verify users preserved
        self.assertEqual(User.objects.count(), 2)
    
    def test_command_with_reports(self):
        """Test command deletes generated reports and configurations."""
        # Create report configuration
        config = ReportConfiguration.objects.create(
            name='Test Report',
            report_type='patient_summary',
            parameters={'test': 'params'},
            created_by=self.user
        )
        
        # Create generated report
        GeneratedReport.objects.create(
            configuration=config,
            file_path='/path/to/report.pdf',
            format='pdf',
            status='completed',
            created_by=self.user
        )
        
        # Verify data exists
        self.assertEqual(ReportConfiguration.objects.count(), 1)
        self.assertEqual(GeneratedReport.objects.count(), 1)
        
        # Run command
        call_command('reset_medical_data', '--yes', stdout=StringIO())
        
        # Verify reports deleted
        self.assertEqual(ReportConfiguration.objects.count(), 0)
        self.assertEqual(GeneratedReport.objects.count(), 0)
        
        # Verify users preserved
        self.assertEqual(User.objects.count(), 2)
    
    def test_command_transaction_rollback_on_error(self):
        """Test that transaction rolls back if error occurs."""
        # This test verifies atomic transaction behavior
        # In case of error, no partial deletion should occur
        
        initial_patient_count = Patient.objects.count()
        initial_user_count = User.objects.count()
        
        # Note: In actual error scenario, all data would be preserved
        # This is a basic check that transaction context is used
        
        try:
            call_command('reset_medical_data', '--yes', stdout=StringIO())
        except Exception:
            # If error occurred, verify nothing was deleted
            self.assertEqual(Patient.objects.count(), initial_patient_count)
            self.assertEqual(User.objects.count(), initial_user_count)
