#!/usr/bin/env python
"""
Comprehensive Project Health Check
==================================

This script performs a thorough validation of the entire Django project,
focusing on critical components like PHI encryption, FHIR processing,
database integrity, and system configuration.
"""

import os
import sys
import django
import json
from datetime import datetime, date
from django.core.management import execute_from_command_line
from django.core.exceptions import ValidationError
from django.db import connection, transaction
import traceback

# Add the project root to Python path
sys.path.append('F:/coding/doc/doc2db_2025_django')

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from django.contrib.auth import get_user_model
from apps.patients.models import Patient, PatientHistory
from apps.core.models import AuditLog
from django.conf import settings
from django.core.management.color import make_style

User = get_user_model()
style = make_style()

class HealthChecker:
    def __init__(self):
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'checks': {},
            'overall_status': 'UNKNOWN',
            'critical_issues': [],
            'warnings': [],
            'recommendations': []
        }
    
    def log_result(self, check_name, status, message, details=None):
        """Log a check result."""
        self.results['checks'][check_name] = {
            'status': status,
            'message': message,
            'details': details or {}
        }
        
        if status == 'CRITICAL':
            self.results['critical_issues'].append(f"{check_name}: {message}")
        elif status == 'WARNING':
            self.results['warnings'].append(f"{check_name}: {message}")
    
    def print_header(self, title):
        """Print a formatted header."""
        print(f"\n{'='*60}")
        print(f" {title}")
        print(f"{'='*60}")
    
    def print_check(self, check_name, status, message):
        """Print a formatted check result."""
        if status == 'PASS':
            icon = '✅'
            color = style.SUCCESS
        elif status == 'WARNING':
            icon = '⚠️'
            color = style.WARNING
        elif status == 'CRITICAL':
            icon = '❌'
            color = style.ERROR
        else:
            icon = '❓'
            color = style.NOTICE
        
        print(f"{icon} {color(check_name)}: {message}")
    
    def check_django_system(self):
        """Check Django system configuration and health."""
        self.print_header("DJANGO SYSTEM CHECKS")
        
        try:
            # Run Django system checks
            from django.core.management.commands.check import Command
            from io import StringIO
            from django.core.management.base import CommandError
            
            # Capture system check output
            old_stdout = sys.stdout
            sys.stdout = captured_output = StringIO()
            
            try:
                command = Command()
                command.handle(verbosity=1, deploy=False, fail_level='ERROR')
                system_check_output = captured_output.getvalue()
                
                if "System check identified no issues" in system_check_output or not system_check_output.strip():
                    self.log_result('django_system_check', 'PASS', 'All Django system checks passed')
                    self.print_check('Django System Check', 'PASS', 'All system checks passed')
                else:
                    self.log_result('django_system_check', 'WARNING', 'Some Django system issues found', 
                                  {'output': system_check_output})
                    self.print_check('Django System Check', 'WARNING', 'Some issues found - check details')
                    
            except CommandError as e:
                self.log_result('django_system_check', 'CRITICAL', f'Django system check failed: {str(e)}')
                self.print_check('Django System Check', 'CRITICAL', f'System check failed: {str(e)}')
                
            finally:
                sys.stdout = old_stdout
                
        except Exception as e:
            self.log_result('django_system_check', 'CRITICAL', f'Error running system checks: {str(e)}')
            self.print_check('Django System Check', 'CRITICAL', f'Error: {str(e)}')
    
    def check_database_integrity(self):
        """Check database schema and migration integrity."""
        self.print_header("DATABASE INTEGRITY CHECKS")
        
        try:
            # Check database connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                if result and result[0] == 1:
                    self.log_result('db_connection', 'PASS', 'Database connection successful')
                    self.print_check('Database Connection', 'PASS', 'Connection established')
                else:
                    self.log_result('db_connection', 'CRITICAL', 'Database connection test failed')
                    self.print_check('Database Connection', 'CRITICAL', 'Connection test failed')
        except Exception as e:
            self.log_result('db_connection', 'CRITICAL', f'Database connection error: {str(e)}')
            self.print_check('Database Connection', 'CRITICAL', f'Error: {str(e)}')
        
        try:
            # Check migration status
            from django.core.management.commands.showmigrations import Command
            from io import StringIO
            
            old_stdout = sys.stdout
            sys.stdout = captured_output = StringIO()
            
            try:
                command = Command()
                command.handle(verbosity=0)
                migration_output = captured_output.getvalue()
                
                if "[X]" in migration_output and "[ ]" not in migration_output:
                    self.log_result('migrations', 'PASS', 'All migrations applied')
                    self.print_check('Database Migrations', 'PASS', 'All migrations applied')
                elif "[ ]" in migration_output:
                    unapplied_count = migration_output.count("[ ]")
                    self.log_result('migrations', 'WARNING', f'{unapplied_count} unapplied migrations found')
                    self.print_check('Database Migrations', 'WARNING', f'{unapplied_count} unapplied migrations')
                else:
                    self.log_result('migrations', 'PASS', 'Migration status checked')
                    self.print_check('Database Migrations', 'PASS', 'Status verified')
                    
            finally:
                sys.stdout = old_stdout
                
        except Exception as e:
            self.log_result('migrations', 'WARNING', f'Error checking migrations: {str(e)}')
            self.print_check('Database Migrations', 'WARNING', f'Check error: {str(e)}')
        
        try:
            # Check critical table existence
            critical_tables = ['patients', 'patient_history', 'auth_user', 'audit_logs']
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT table_name FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                """)
                existing_tables = [row[0] for row in cursor.fetchall()]
                
                missing_tables = [table for table in critical_tables if table not in existing_tables]
                if missing_tables:
                    self.log_result('critical_tables', 'CRITICAL', f'Missing tables: {missing_tables}')
                    self.print_check('Critical Tables', 'CRITICAL', f'Missing: {", ".join(missing_tables)}')
                else:
                    self.log_result('critical_tables', 'PASS', 'All critical tables exist')
                    self.print_check('Critical Tables', 'PASS', 'All critical tables present')
                    
        except Exception as e:
            self.log_result('critical_tables', 'WARNING', f'Error checking tables: {str(e)}')
            self.print_check('Critical Tables', 'WARNING', f'Check error: {str(e)}')
    
    def check_phi_encryption(self):
        """Test PHI encryption/decryption functionality."""
        self.print_header("PHI ENCRYPTION VALIDATION")
        
        try:
            # Create test user
            test_user, _ = User.objects.get_or_create(
                username='health_check_user',
                defaults={'email': 'healthcheck@example.com'}
            )
            
            # Test PHI field encryption
            test_patient = Patient(
                mrn='HEALTH-CHECK-001',
                first_name='Test',
                last_name='Patient',
                date_of_birth='1990-01-01',
                gender='M',
                ssn='123-45-6789',
                address='123 Test St, Test City, TS 12345',
                phone='555-123-4567',
                email='test@example.com',
                created_by=test_user
            )
            test_patient.save()
            
            # Verify encryption by checking raw database values
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT first_name, last_name, date_of_birth, ssn, address, phone, email
                    FROM patients WHERE mrn = %s
                """, ['HEALTH-CHECK-001'])
                raw_data = cursor.fetchone()
                
                # Check that raw data is encrypted (not plaintext)
                encrypted_fields_ok = True
                field_names = ['first_name', 'last_name', 'date_of_birth', 'ssn', 'address', 'phone', 'email']
                plaintext_values = ['Test', 'Patient', '1990-01-01', '123-45-6789', '123 Test St', '555-123-4567', 'test@example.com']
                
                for i, (field_name, plaintext_value) in enumerate(zip(field_names, plaintext_values)):
                    if raw_data[i] and plaintext_value.lower() in str(raw_data[i]).lower():
                        encrypted_fields_ok = False
                        break
                
                if encrypted_fields_ok:
                    self.log_result('phi_encryption', 'PASS', 'PHI fields properly encrypted at rest')
                    self.print_check('PHI Encryption', 'PASS', 'All PHI fields encrypted in database')
                else:
                    self.log_result('phi_encryption', 'CRITICAL', 'PHI data found in plaintext in database')
                    self.print_check('PHI Encryption', 'CRITICAL', 'PLAINTEXT PHI DETECTED IN DATABASE!')
            
            # Verify decryption works
            retrieved_patient = Patient.objects.get(mrn='HEALTH-CHECK-001')
            if (retrieved_patient.first_name == 'Test' and 
                retrieved_patient.last_name == 'Patient' and
                retrieved_patient.date_of_birth == '1990-01-01'):
                
                self.log_result('phi_decryption', 'PASS', 'PHI decryption working correctly')
                self.print_check('PHI Decryption', 'PASS', 'Transparent decryption working')
            else:
                self.log_result('phi_decryption', 'CRITICAL', 'PHI decryption not working properly')
                self.print_check('PHI Decryption', 'CRITICAL', 'Decryption failure detected')
            
            # Test helper methods
            if retrieved_patient.age and retrieved_patient.full_name == 'Test Patient':
                self.log_result('phi_helpers', 'PASS', 'PHI helper methods working')
                self.print_check('PHI Helper Methods', 'PASS', 'Age and name methods working')
            else:
                self.log_result('phi_helpers', 'WARNING', 'PHI helper methods may have issues')
                self.print_check('PHI Helper Methods', 'WARNING', 'Helper methods need verification')
            
            # Cleanup
            test_patient.delete()
            
        except Exception as e:
            self.log_result('phi_encryption', 'CRITICAL', f'PHI encryption test failed: {str(e)}')
            self.print_check('PHI Encryption', 'CRITICAL', f'Test failed: {str(e)}')
    
    def check_fhir_processing(self):
        """Validate FHIR data processing pipeline."""
        self.print_header("FHIR PROCESSING VALIDATION")
        
        try:
            # Create test user and patient
            test_user, _ = User.objects.get_or_create(
                username='fhir_test_user',
                defaults={'email': 'fhirtest@example.com'}
            )
            
            test_patient = Patient(
                mrn='FHIR-TEST-001',
                first_name='FHIR',
                last_name='Test',
                date_of_birth='1985-06-15',
                created_by=test_user
            )
            test_patient.save()
            
            # Test FHIR resource addition
            test_condition = {
                "resourceType": "Condition",
                "id": "test-condition-health-check",
                "clinicalStatus": {
                    "coding": [{"code": "active", "display": "Active"}]
                },
                "code": {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "73211009",
                            "display": "Diabetes mellitus"
                        }
                    ]
                },
                "onsetDateTime": "2020-01-15"
            }
            
            # Test add_fhir_resources method
            result = test_patient.add_fhir_resources(test_condition)
            if result:
                self.log_result('fhir_add_resources', 'PASS', 'FHIR resource addition successful')
                self.print_check('FHIR Resource Addition', 'PASS', 'Resources added successfully')
            else:
                self.log_result('fhir_add_resources', 'CRITICAL', 'FHIR resource addition failed')
                self.print_check('FHIR Resource Addition', 'CRITICAL', 'Resource addition failed')
            
            # Test encrypted bundle structure
            if (test_patient.encrypted_fhir_bundle and 
                'entry' in test_patient.encrypted_fhir_bundle and
                len(test_patient.encrypted_fhir_bundle['entry']) > 0):
                
                self.log_result('fhir_bundle_structure', 'PASS', 'FHIR Bundle structure correct')
                self.print_check('FHIR Bundle Structure', 'PASS', 'Proper Bundle format maintained')
            else:
                self.log_result('fhir_bundle_structure', 'CRITICAL', 'FHIR Bundle structure invalid')
                self.print_check('FHIR Bundle Structure', 'CRITICAL', 'Invalid Bundle format')
            
            # Test searchable metadata extraction
            if (test_patient.searchable_medical_codes and 
                'conditions' in test_patient.searchable_medical_codes and
                len(test_patient.searchable_medical_codes['conditions']) > 0):
                
                condition_code = test_patient.searchable_medical_codes['conditions'][0]
                if condition_code.get('code') == '73211009':
                    self.log_result('fhir_metadata_extraction', 'PASS', 'Metadata extraction working')
                    self.print_check('FHIR Metadata Extraction', 'PASS', 'Searchable codes extracted')
                else:
                    self.log_result('fhir_metadata_extraction', 'WARNING', 'Metadata extraction incomplete')
                    self.print_check('FHIR Metadata Extraction', 'WARNING', 'Extraction may be incomplete')
            else:
                self.log_result('fhir_metadata_extraction', 'CRITICAL', 'Metadata extraction failed')
                self.print_check('FHIR Metadata Extraction', 'CRITICAL', 'No searchable metadata created')
            
            # Test comprehensive report generation
            report = test_patient.get_comprehensive_report()
            if (report and 
                report.get('report_metadata', {}).get('status') == 'success' and
                len(report.get('clinical_summary', {}).get('conditions', [])) > 0):
                
                self.log_result('fhir_report_generation', 'PASS', 'Comprehensive report generation working')
                self.print_check('FHIR Report Generation', 'PASS', 'Reports generated successfully')
            else:
                self.log_result('fhir_report_generation', 'CRITICAL', 'Report generation failed')
                self.print_check('FHIR Report Generation', 'CRITICAL', 'Report generation not working')
            
            # Cleanup
            test_patient.delete()
            
        except Exception as e:
            self.log_result('fhir_processing', 'CRITICAL', f'FHIR processing test failed: {str(e)}')
            self.print_check('FHIR Processing', 'CRITICAL', f'Test failed: {str(e)}')
    
    def check_model_relationships(self):
        """Check model relationships and constraints."""
        self.print_header("MODEL RELATIONSHIP VALIDATION")
        
        try:
            # Test Patient -> PatientHistory relationship
            test_user, _ = User.objects.get_or_create(
                username='model_test_user',
                defaults={'email': 'modeltest@example.com'}
            )
            
            test_patient = Patient(
                mrn='MODEL-TEST-001',
                first_name='Model',
                last_name='Test',
                date_of_birth='1980-12-25',
                created_by=test_user
            )
            test_patient.save()
            
            # Check if PatientHistory was created (should happen automatically)
            history_count = PatientHistory.objects.filter(patient=test_patient).count()
            if history_count > 0:
                self.log_result('patient_history_relation', 'PASS', 'Patient-PatientHistory relationship working')
                self.print_check('Patient-History Relationship', 'PASS', 'Automatic history creation working')
            else:
                self.log_result('patient_history_relation', 'WARNING', 'PatientHistory not auto-created')
                self.print_check('Patient-History Relationship', 'WARNING', 'History creation may be manual')
            
            # Test model validation
            try:
                invalid_patient = Patient(
                    mrn='',  # Invalid - required field
                    first_name='Invalid',
                    last_name='Test',
                    date_of_birth='1990-01-01',
                    created_by=test_user
                )
                invalid_patient.full_clean()  # This should raise ValidationError
                self.log_result('model_validation', 'WARNING', 'Model validation may be too lenient')
                self.print_check('Model Validation', 'WARNING', 'Validation rules may need tightening')
            except ValidationError:
                self.log_result('model_validation', 'PASS', 'Model validation working correctly')
                self.print_check('Model Validation', 'PASS', 'Validation rules enforced')
            
            # Cleanup
            test_patient.delete()
            
        except Exception as e:
            self.log_result('model_relationships', 'WARNING', f'Model relationship test error: {str(e)}')
            self.print_check('Model Relationships', 'WARNING', f'Test error: {str(e)}')
    
    def check_code_quality(self):
        """Run code quality and linting checks."""
        self.print_header("CODE QUALITY CHECKS")
        
        # Check critical files exist
        critical_files = [
            'apps/patients/models.py',
            'apps/core/models.py',
            'meddocparser/settings/base.py',
            'requirements.txt'
        ]
        
        missing_files = []
        for file_path in critical_files:
            if not os.path.exists(file_path):
                missing_files.append(file_path)
        
        if missing_files:
            self.log_result('critical_files', 'CRITICAL', f'Missing critical files: {missing_files}')
            self.print_check('Critical Files', 'CRITICAL', f'Missing: {", ".join(missing_files)}')
        else:
            self.log_result('critical_files', 'PASS', 'All critical files present')
            self.print_check('Critical Files', 'PASS', 'All critical files found')
        
        # Check settings configuration
        try:
            encryption_keys = getattr(settings, 'FIELD_ENCRYPTION_KEYS', None)
            if encryption_keys and len(encryption_keys) > 0:
                self.log_result('encryption_config', 'PASS', 'Encryption keys configured')
                self.print_check('Encryption Configuration', 'PASS', 'Keys properly configured')
            else:
                self.log_result('encryption_config', 'CRITICAL', 'Encryption keys not configured')
                self.print_check('Encryption Configuration', 'CRITICAL', 'Missing encryption keys')
        except Exception as e:
            self.log_result('encryption_config', 'WARNING', f'Error checking encryption config: {str(e)}')
            self.print_check('Encryption Configuration', 'WARNING', f'Config check error: {str(e)}')
    
    def generate_summary(self):
        """Generate overall health summary."""
        self.print_header("PROJECT HEALTH SUMMARY")
        
        # Count results by status
        critical_count = sum(1 for check in self.results['checks'].values() if check['status'] == 'CRITICAL')
        warning_count = sum(1 for check in self.results['checks'].values() if check['status'] == 'WARNING')
        pass_count = sum(1 for check in self.results['checks'].values() if check['status'] == 'PASS')
        
        # Determine overall status
        if critical_count > 0:
            self.results['overall_status'] = 'CRITICAL'
            overall_color = style.ERROR
            overall_icon = '❌'
        elif warning_count > 0:
            self.results['overall_status'] = 'WARNING'
            overall_color = style.WARNING
            overall_icon = '⚠️'
        else:
            self.results['overall_status'] = 'HEALTHY'
            overall_color = style.SUCCESS
            overall_icon = '✅'
        
        print(f"\n{overall_icon} {overall_color('OVERALL PROJECT STATUS: ' + self.results['overall_status'])}")
        print(f"\n📊 Check Results:")
        print(f"   ✅ Passed: {pass_count}")
        print(f"   ⚠️  Warnings: {warning_count}")
        print(f"   ❌ Critical: {critical_count}")
        
        if self.results['critical_issues']:
            print(f"\n🚨 CRITICAL ISSUES REQUIRING IMMEDIATE ATTENTION:")
            for issue in self.results['critical_issues']:
                print(f"   • {issue}")
        
        if self.results['warnings']:
            print(f"\n⚠️  WARNINGS TO ADDRESS:")
            for warning in self.results['warnings']:
                print(f"   • {warning}")
        
        # Generate recommendations
        if critical_count == 0 and warning_count == 0:
            self.results['recommendations'].append("Project is in excellent health! Continue with regular monitoring.")
        elif critical_count == 0:
            self.results['recommendations'].append("Project is generally healthy. Address warnings when convenient.")
        else:
            self.results['recommendations'].append("URGENT: Address all critical issues before deploying to production.")
        
        if self.results['recommendations']:
            print(f"\n💡 RECOMMENDATIONS:")
            for rec in self.results['recommendations']:
                print(f"   • {rec}")
    
    def save_report(self):
        """Save detailed report to file."""
        report_file = f"project_health_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        print(f"\n📄 Detailed report saved to: {report_file}")
    
    def run_all_checks(self):
        """Run all health checks."""
        print(style.SUCCESS("🏥 COMPREHENSIVE PROJECT HEALTH CHECK"))
        print(style.SUCCESS("=" * 60))
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            self.check_django_system()
            self.check_database_integrity()
            self.check_phi_encryption()
            self.check_fhir_processing()
            self.check_model_relationships()
            self.check_code_quality()
            
            self.generate_summary()
            self.save_report()
            
            print(f"\n🏁 Health check completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Return status code
            if self.results['overall_status'] == 'CRITICAL':
                return 2
            elif self.results['overall_status'] == 'WARNING':
                return 1
            else:
                return 0
                
        except Exception as e:
            print(f"\n💥 HEALTH CHECK FAILED: {str(e)}")
            traceback.print_exc()
            return 3

def main():
    """Main function."""
    checker = HealthChecker()
    return checker.run_all_checks()

if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
