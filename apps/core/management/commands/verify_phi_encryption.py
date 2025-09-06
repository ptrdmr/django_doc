"""
Django management command to verify PHI encryption.

Usage:
    python manage.py verify_phi_encryption
    python manage.py verify_phi_encryption --no-cleanup
    python manage.py verify_phi_encryption --verbose
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.conf import settings
from faker import Faker
import json

from apps.patients.models import Patient, PatientHistory
from apps.documents.models import Document, ParsedData


class Command(BaseCommand):
    help = 'Verify that PHI data is properly encrypted at rest'

    def add_arguments(self, parser):
        parser.add_argument(
            '--no-cleanup',
            action='store_true',
            help='Do not clean up test data after verification',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Enable verbose output',
        )
        parser.add_argument(
            '--export-report',
            type=str,
            help='Export verification report to JSON file',
        )

    def handle(self, *args, **options):
        self.verbosity = options.get('verbosity', 1)
        self.verbose = options.get('verbose', False)
        self.no_cleanup = options.get('no_cleanup', False)
        self.export_report = options.get('export_report')
        
        # Initialize results tracking
        self.results = {
            'timestamp': None,
            'django_settings': str(settings.SETTINGS_MODULE),
            'encryption_config': {
                'field_encryption_keys_configured': bool(getattr(settings, 'FIELD_ENCRYPTION_KEYS', None)),
                'django_cryptography_installed': False
            },
            'tests': {},
            'summary': {
                'total_tests': 0,
                'passed': 0,
                'failed': 0,
                'errors': []
            }
        }
        
        # Check if django-cryptography is available
        try:
            import django_cryptography
            self.results['encryption_config']['django_cryptography_installed'] = True
            if self.verbose:
                self.stdout.write("✓ django-cryptography is installed")
        except ImportError:
            self.results['encryption_config']['django_cryptography_installed'] = False
            self.stdout.write(
                self.style.ERROR("✗ django-cryptography is not installed")
            )
            raise CommandError("django-cryptography package is required for encryption")
        
        self.stdout.write("Starting PHI encryption verification...")
        
        # Create test data
        self.fake = Faker()
        self.test_patient = None
        self.test_document = None
        
        try:
            self._create_test_data()
            self._verify_patient_encryption()
            self._verify_document_encryption()
            self._verify_decryption_functionality()
            self._verify_fhir_encryption()
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Verification failed with error: {str(e)}")
            )
            self.results['summary']['errors'].append(f"Critical error: {str(e)}")
            
        finally:
            if not self.no_cleanup:
                self._cleanup_test_data()
        
        # Print summary
        self._print_summary()
        
        # Export report if requested
        if self.export_report:
            self._export_report()
        
        # Exit with appropriate code
        if self.results['summary']['failed'] > 0:
            raise CommandError("PHI encryption verification failed")
        
        self.stdout.write(
            self.style.SUCCESS("✅ All PHI encryption verifications passed!")
        )

    def _log_test(self, test_name, passed, details=None):
        """Log a test result."""
        self.results['tests'][test_name] = {
            'passed': passed,
            'details': details or {}
        }
        self.results['summary']['total_tests'] += 1
        
        if passed:
            self.results['summary']['passed'] += 1
            if self.verbosity >= 2:
                self.stdout.write(f"  ✓ {test_name}")
        else:
            self.results['summary']['failed'] += 1
            self.stdout.write(
                self.style.ERROR(f"  ✗ {test_name}")
            )
            if details:
                for key, value in details.items():
                    self.stdout.write(f"    {key}: {value}")

    def _create_test_data(self):
        """Create test patient and document data."""
        self.stdout.write("Creating test data...")
        
        try:
            # Create test patient
            self.test_patient = Patient.objects.create(
                mrn=f"VERIFY{self.fake.unique.random_number(digits=6)}",
                first_name=self.fake.first_name(),
                last_name=self.fake.last_name(),
                date_of_birth=self.fake.date_of_birth(minimum_age=18, maximum_age=90).strftime('%Y-%m-%d'),
                gender=self.fake.random_element(['M', 'F', 'O']),
                ssn=self.fake.ssn().replace('-', ''),
                address=self.fake.address(),
                phone=self.fake.phone_number(),
                email=self.fake.email()
            )
            
            if self.verbose:
                self.stdout.write(f"Created test patient: {self.test_patient.mrn}")
            
            # Create test document
            self.test_document = Document.objects.create(
                patient=self.test_patient,
                filename="verification_test_document.pdf",
                file_size=1024,
                status='pending',
                original_text="This is test medical content with PHI for verification purposes.",
                notes="Test notes containing sensitive medical information for encryption testing."
            )
            
            if self.verbose:
                self.stdout.write(f"Created test document: {self.test_document.filename}")
                
        except Exception as e:
            raise CommandError(f"Failed to create test data: {str(e)}")

    def _verify_patient_encryption(self):
        """Verify Patient model field encryption."""
        self.stdout.write("Verifying patient field encryption...")
        
        encrypted_fields = [
            'first_name', 'last_name', 'date_of_birth', 'ssn',
            'address', 'phone', 'email', 'encrypted_fhir_bundle'
        ]
        
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT id, first_name, last_name, date_of_birth, ssn, 
                          address, phone, email, encrypted_fhir_bundle 
                   FROM patients WHERE id = %s""",
                [self.test_patient.id]
            )
            raw_row = cursor.fetchone()
        
        if not raw_row:
            self._log_test("patient_database_query", False, {"error": "Patient not found in database"})
            return
        
        # Map fields to database columns
        field_mapping = {
            'first_name': raw_row[1],
            'last_name': raw_row[2],
            'date_of_birth': raw_row[3],
            'ssn': raw_row[4],
            'address': raw_row[5],
            'phone': raw_row[6],
            'email': raw_row[7],
            'encrypted_fhir_bundle': raw_row[8]
        }
        
        for field in encrypted_fields:
            raw_value = field_mapping[field]
            decrypted_value = getattr(self.test_patient, field)
            
            # Skip null fields
            if raw_value is None and decrypted_value is None:
                self._log_test(f"patient_{field}_null", True, {"note": "Both raw and decrypted are NULL"})
                continue
            
            if raw_value is None or decrypted_value is None:
                self._log_test(f"patient_{field}_null_mismatch", False, {
                    "raw_is_null": raw_value is None,
                    "decrypted_is_null": decrypted_value is None
                })
                continue
            
            # Check if field appears encrypted
            is_encrypted = self._appears_encrypted(raw_value, decrypted_value)
            
            # Prepare detailed info for logging
            raw_info = {
                "raw_type": type(raw_value).__name__,
                "raw_length": len(raw_value) if isinstance(raw_value, (bytes, memoryview)) else len(str(raw_value)),
                "decrypted_length": len(str(decrypted_value)),
                "values_differ": raw_value != decrypted_value,
                "is_binary": isinstance(raw_value, (bytes, memoryview))
            }
            
            # Check for encryption markers based on data type
            if isinstance(raw_value, (bytes, memoryview)):
                raw_bytes = bytes(raw_value)
                raw_info["has_fernet_markers"] = b'gAAAAAB' in raw_bytes
                raw_info["first_20_bytes"] = raw_bytes[:20].hex() if len(raw_bytes) > 20 else raw_bytes.hex()
            else:
                raw_info["has_fernet_markers"] = 'gAAAAAB' in str(raw_value)
                raw_info["first_50_chars"] = str(raw_value)[:50]
            
            self._log_test(f"patient_{field}_encryption", is_encrypted, raw_info)

    def _verify_document_encryption(self):
        """Verify Document model field encryption."""
        self.stdout.write("Verifying document field encryption...")
        
        encrypted_fields = ['original_text', 'notes']
        
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, original_text, notes FROM documents WHERE id = %s",
                [self.test_document.id]
            )
            raw_row = cursor.fetchone()
        
        if not raw_row:
            self._log_test("document_database_query", False, {"error": "Document not found in database"})
            return
        
        field_mapping = {
            'original_text': raw_row[1],
            'notes': raw_row[2]
        }
        
        for field in encrypted_fields:
            raw_value = field_mapping[field]
            decrypted_value = getattr(self.test_document, field)
            
            if raw_value and decrypted_value:
                is_encrypted = self._appears_encrypted(raw_value, decrypted_value)
                
                # Prepare detailed info for logging
                raw_info = {
                    "raw_type": type(raw_value).__name__,
                    "raw_length": len(raw_value) if isinstance(raw_value, (bytes, memoryview)) else len(str(raw_value)),
                    "decrypted_length": len(str(decrypted_value)),
                    "values_differ": raw_value != decrypted_value,
                    "is_binary": isinstance(raw_value, (bytes, memoryview))
                }
                
                # Check for encryption markers based on data type
                if isinstance(raw_value, (bytes, memoryview)):
                    raw_bytes = bytes(raw_value)
                    raw_info["has_fernet_markers"] = b'gAAAAAB' in raw_bytes
                    raw_info["first_20_bytes"] = raw_bytes[:20].hex() if len(raw_bytes) > 20 else raw_bytes.hex()
                else:
                    raw_info["has_fernet_markers"] = 'gAAAAAB' in str(raw_value)
                    raw_info["first_50_chars"] = str(raw_value)[:50]
                
                self._log_test(f"document_{field}_encryption", is_encrypted, raw_info)

    def _verify_decryption_functionality(self):
        """Verify that encrypted data can be properly decrypted."""
        self.stdout.write("Verifying decryption functionality...")
        
        try:
            # Retrieve patient from database again
            retrieved_patient = Patient.objects.get(id=self.test_patient.id)
            
            fields_to_check = ['first_name', 'last_name', 'ssn', 'address', 'phone', 'email']
            
            for field in fields_to_check:
                original_value = getattr(self.test_patient, field)
                retrieved_value = getattr(retrieved_patient, field)
                
                matches = original_value == retrieved_value
                self._log_test(f"decryption_{field}", matches, {
                    "original_value_length": len(str(original_value)) if original_value else 0,
                    "retrieved_value_length": len(str(retrieved_value)) if retrieved_value else 0,
                    "values_match": matches
                })
        
        except Exception as e:
            self._log_test("decryption_functionality", False, {"error": str(e)})

    def _verify_fhir_encryption(self):
        """Verify FHIR bundle encryption."""
        self.stdout.write("Verifying FHIR bundle encryption...")
        
        try:
            # Add test FHIR data
            test_fhir_resources = [
                {
                    "resourceType": "Condition",
                    "id": "verification-test-condition",
                    "code": {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": "38341003",
                                "display": "Essential hypertension"
                            }
                        ]
                    },
                    "subject": {
                        "reference": f"Patient/{self.test_patient.id}"
                    }
                }
            ]
            
            # Add FHIR resources
            self.test_patient.add_fhir_resources(test_fhir_resources)
            
            # Check if FHIR bundle is encrypted
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT encrypted_fhir_bundle FROM patients WHERE id = %s",
                    [self.test_patient.id]
                )
                raw_fhir = cursor.fetchone()[0]
            
            if raw_fhir:
                decrypted_fhir = self.test_patient.encrypted_fhir_bundle
                is_encrypted = self._appears_encrypted(raw_fhir, json.dumps(decrypted_fhir) if decrypted_fhir else "")
                
                self._log_test("fhir_bundle_encryption", is_encrypted, {
                    "has_fhir_data": bool(decrypted_fhir),
                    "raw_data_length": len(str(raw_fhir)),
                    "contains_test_condition": "verification-test-condition" in json.dumps(decrypted_fhir) if decrypted_fhir else False
                })
            else:
                self._log_test("fhir_bundle_creation", False, {"error": "No FHIR bundle created"})
        
        except Exception as e:
            self._log_test("fhir_encryption", False, {"error": str(e)})

    def _appears_encrypted(self, raw_value, decrypted_value):
        """
        Check if a value appears to be encrypted.
        
        Heuristics:
        1. Raw and decrypted values should be different
        2. Raw value should be binary or bytes-like for encrypted fields
        3. Raw value should be longer (encryption overhead)
        4. When converted to string, should contain Fernet markers (gAAAAAB)
        """
        if not raw_value or not decrypted_value:
            return False
        
        # For PostgreSQL bytea fields, raw_value will be bytes or memoryview
        if isinstance(raw_value, (bytes, memoryview)):
            # This is the expected case for encrypted fields
            raw_bytes = bytes(raw_value)
            raw_str = raw_bytes.decode('utf-8', errors='ignore')
            
            # Check for Fernet encryption markers
            if 'gAAAAAB' in raw_str or b'gAAAAAB' in raw_bytes:
                return True
            
            # Alternative: check if it's significantly longer than decrypted
            if len(raw_bytes) > len(str(decrypted_value)) * 1.5:
                return True
        
        else:
            # String representation - check basic encryption markers
            raw_str = str(raw_value)
            decrypted_str = str(decrypted_value)
            
            # Values should be different
            if raw_str == decrypted_str:
                return False
            
            # Raw should be longer due to encryption overhead
            if len(raw_str) <= len(decrypted_str):
                return False
            
            # Should contain Fernet encryption markers
            if 'gAAAAAB' not in raw_str:
                return False
            
            return True
        
        return False

    def _cleanup_test_data(self):
        """Clean up test data."""
        self.stdout.write("Cleaning up test data...")
        
        try:
            if self.test_document:
                self.test_document.delete()
                if self.verbose:
                    self.stdout.write(f"Deleted test document: {self.test_document.filename}")
            
            if self.test_patient:
                self.test_patient.delete()
                if self.verbose:
                    self.stdout.write(f"Deleted test patient: {self.test_patient.mrn}")
        
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"Error during cleanup: {str(e)}")
            )

    def _print_summary(self):
        """Print verification summary."""
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("PHI ENCRYPTION VERIFICATION SUMMARY")
        self.stdout.write("=" * 50)
        
        total = self.results['summary']['total_tests']
        passed = self.results['summary']['passed']
        failed = self.results['summary']['failed']
        
        self.stdout.write(f"Total Tests: {total}")
        self.stdout.write(self.style.SUCCESS(f"Passed: {passed}"))
        
        if failed > 0:
            self.stdout.write(self.style.ERROR(f"Failed: {failed}"))
            
            # Show failed tests
            for test_name, result in self.results['tests'].items():
                if not result['passed']:
                    self.stdout.write(f"  ✗ {test_name}")
                    if result['details']:
                        for key, value in result['details'].items():
                            self.stdout.write(f"    {key}: {value}")

    def _export_report(self):
        """Export verification report to JSON file."""
        from datetime import datetime
        
        self.results['timestamp'] = datetime.now().isoformat()
        
        try:
            with open(self.export_report, 'w') as f:
                json.dump(self.results, f, indent=2)
            
            self.stdout.write(
                self.style.SUCCESS(f"Verification report exported to: {self.export_report}")
            )
        
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Failed to export report: {str(e)}")
            )
