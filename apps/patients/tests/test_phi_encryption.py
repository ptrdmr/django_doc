"""
Comprehensive PHI encryption tests for HIPAA compliance.

These tests verify that all Protected Health Information (PHI) is properly
encrypted at rest and can be correctly decrypted when accessed.
"""

from django.test import TestCase, TransactionTestCase
from django.db import connection
from django.conf import settings
from faker import Faker
import json
import uuid

from apps.patients.models import Patient, PatientHistory
from apps.documents.models import Document, ParsedData


class PHIEncryptionTestCase(TestCase):
    """
    Test PHI encryption functionality for HIPAA compliance.
    """
    
    def setUp(self):
        """Set up test data."""
        self.fake = Faker()
        
        # Create test patient with PHI
        self.patient = Patient.objects.create(
            mrn=f"TEST{self.fake.unique.random_number(digits=6)}",
            first_name=self.fake.first_name(),
            last_name=self.fake.last_name(),
            date_of_birth=self.fake.date_of_birth(minimum_age=18, maximum_age=90).strftime('%Y-%m-%d'),
            gender=self.fake.random_element(['M', 'F', 'O']),
            ssn=self.fake.ssn().replace('-', ''),
            address=self.fake.address(),
            phone=self.fake.phone_number(),
            email=self.fake.email()
        )
    
    def test_patient_phi_fields_encryption(self):
        """Test that all Patient PHI fields are encrypted at rest."""
        encrypted_fields = [
            'first_name', 'last_name', 'date_of_birth', 'ssn',
            'address', 'phone', 'email', 'encrypted_fhir_bundle'
        ]
        
        # Get raw database values
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT first_name, last_name, date_of_birth, ssn, 
                          address, phone, email, encrypted_fhir_bundle 
                   FROM patients WHERE id = %s""",
                [self.patient.id]
            )
            raw_row = cursor.fetchone()
        
        self.assertIsNotNone(raw_row, "Patient should exist in database")
        
        # Map fields to database columns
        field_mapping = {
            'first_name': raw_row[0],
            'last_name': raw_row[1],
            'date_of_birth': raw_row[2],
            'ssn': raw_row[3],
            'address': raw_row[4],
            'phone': raw_row[5],
            'email': raw_row[6],
            'encrypted_fhir_bundle': raw_row[7]
        }
        
        # Check each encrypted field
        for field in encrypted_fields:
            with self.subTest(field=field):
                raw_value = field_mapping[field]
                decrypted_value = getattr(self.patient, field)
                
                # Skip null fields
                if raw_value is None and decrypted_value is None:
                    continue
                
                # Both should have values for non-null fields
                if field in ['first_name', 'last_name', 'ssn']:  # Required fields
                    self.assertIsNotNone(raw_value, f"{field} raw value should not be null")
                    self.assertIsNotNone(decrypted_value, f"{field} decrypted value should not be null")
                
                # If both have values, check encryption
                if raw_value is not None and decrypted_value is not None:
                    # Raw should be binary data for encrypted fields
                    self.assertIsInstance(raw_value, (bytes, memoryview), 
                                        f"{field} should be stored as binary data")
                    
                    # Raw and decrypted should be different
                    self.assertNotEqual(raw_value, decrypted_value,
                                      f"{field} raw and decrypted values should differ")
                    
                    # Raw should be longer due to encryption overhead
                    self.assertGreater(len(raw_value), len(str(decrypted_value)),
                                     f"{field} encrypted value should be longer")
    
    def test_patient_decryption_functionality(self):
        """Test that encrypted Patient data can be correctly decrypted."""
        # Retrieve patient from database again
        retrieved_patient = Patient.objects.get(id=self.patient.id)
        
        # Compare original with retrieved values
        test_fields = [
            'first_name', 'last_name', 'date_of_birth', 
            'ssn', 'address', 'phone', 'email'
        ]
        
        for field in test_fields:
            with self.subTest(field=field):
                original_value = getattr(self.patient, field)
                retrieved_value = getattr(retrieved_patient, field)
                
                self.assertEqual(original_value, retrieved_value,
                               f"{field} should decrypt to the same value")
    
    def test_document_phi_fields_encryption(self):
        """Test that Document PHI fields are encrypted at rest."""
        # Create test document with PHI content
        document = Document.objects.create(
            patient=self.patient,
            filename="test_medical_record.pdf",
            file_size=1024,
            status='pending',
            original_text="This is test medical content with patient PHI for verification purposes.",
            notes="Test notes containing sensitive medical information and patient details."
        )
        
        encrypted_fields = ['original_text', 'notes']
        
        # Get raw database values
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT original_text, notes FROM documents WHERE id = %s",
                [document.id]
            )
            raw_row = cursor.fetchone()
        
        self.assertIsNotNone(raw_row, "Document should exist in database")
        
        # Check each encrypted field
        for i, field in enumerate(encrypted_fields):
            with self.subTest(field=field):
                raw_value = raw_row[i]
                decrypted_value = getattr(document, field)
                
                if raw_value and decrypted_value:
                    # Raw should be binary data
                    self.assertIsInstance(raw_value, (bytes, memoryview),
                                        f"Document.{field} should be stored as binary data")
                    
                    # Values should be different
                    self.assertNotEqual(raw_value, decrypted_value,
                                      f"Document.{field} raw and decrypted should differ")
                    
                    # Raw should be longer
                    self.assertGreater(len(raw_value), len(str(decrypted_value)),
                                     f"Document.{field} encrypted should be longer")
    
    def test_fhir_bundle_encryption(self):
        """Test that FHIR bundles are encrypted when stored."""
        # Add test FHIR data
        test_fhir_resources = [
            {
                "resourceType": "Condition",
                "id": "test-condition-encryption",
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
                    "reference": f"Patient/{self.patient.id}"
                }
            }
        ]
        
        # Add FHIR resources to patient
        self.patient.add_fhir_resources(test_fhir_resources)
        
        # Check that FHIR bundle contains the test data
        fhir_bundle = self.patient.encrypted_fhir_bundle
        self.assertIsInstance(fhir_bundle, dict, "FHIR bundle should be a dict")
        self.assertIn("entry", fhir_bundle, "FHIR bundle should have entries")
        
        # Verify test condition is in the bundle
        found_test_condition = False
        for entry in fhir_bundle.get("entry", []):
            resource = entry.get("resource", {})
            if resource.get("id") == "test-condition-encryption":
                found_test_condition = True
                break
        
        self.assertTrue(found_test_condition, "Test condition should be in FHIR bundle")
        
        # Check raw database storage
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT encrypted_fhir_bundle FROM patients WHERE id = %s",
                [self.patient.id]
            )
            raw_fhir = cursor.fetchone()[0]
        
        if raw_fhir:
            # Should be binary data
            self.assertIsInstance(raw_fhir, (bytes, memoryview),
                                "FHIR bundle should be stored as binary data")
            
            # Should be different from decrypted JSON
            fhir_json_str = json.dumps(fhir_bundle)
            self.assertNotEqual(raw_fhir, fhir_json_str,
                              "Raw FHIR data should differ from decrypted JSON")
    
    def test_searchable_metadata_phi_safety(self):
        """Test that searchable metadata doesn't contain PHI."""
        # Add FHIR data to generate searchable metadata
        test_fhir_resources = [
            {
                "resourceType": "Condition",
                "id": "metadata-test-condition",
                "code": {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "E11.9",
                            "display": "Type 2 diabetes mellitus without complications"
                        }
                    ]
                },
                "subject": {
                    "reference": f"Patient/{self.patient.id}"
                }
            }
        ]
        
        self.patient.add_fhir_resources(test_fhir_resources)
        
        # Check searchable fields don't contain PHI
        phi_values = [
            self.patient.first_name,
            self.patient.last_name,
            self.patient.ssn,
            self.patient.phone,
            self.patient.email
        ]
        
        searchable_fields = [
            self.patient.searchable_medical_codes,
            self.patient.encounter_dates,
            self.patient.provider_references
        ]
        
        for searchable_data in searchable_fields:
            if searchable_data:
                searchable_str = json.dumps(searchable_data)
                for phi_value in phi_values:
                    if phi_value:
                        self.assertNotIn(str(phi_value), searchable_str,
                                       f"Searchable metadata should not contain PHI: {phi_value}")
    
    def test_field_types_are_encrypted_fields(self):
        """Test that PHI fields use proper encrypted field types."""
        from django_cryptography.fields import EncryptedCharField, EncryptedTextField, EncryptedJSONField
        
        # Check Patient model encrypted fields
        patient_encrypted_fields = {
            'first_name': EncryptedCharField,
            'last_name': EncryptedCharField,
            'date_of_birth': EncryptedCharField,
            'ssn': EncryptedCharField,
            'address': EncryptedTextField,
            'phone': EncryptedCharField,
            'email': EncryptedCharField,
            'encrypted_fhir_bundle': EncryptedJSONField
        }
        
        for field_name, expected_type in patient_encrypted_fields.items():
            field = Patient._meta.get_field(field_name)
            self.assertIsInstance(field, expected_type,
                                f"Patient.{field_name} should be {expected_type.__name__}")
        
        # Check Document model encrypted fields
        document_encrypted_fields = {
            'original_text': EncryptedTextField,
            'notes': EncryptedTextField
        }
        
        for field_name, expected_type in document_encrypted_fields.items():
            field = Document._meta.get_field(field_name)
            self.assertIsInstance(field, expected_type,
                                f"Document.{field_name} should be {expected_type.__name__}")
    
    def test_encryption_configuration(self):
        """Test that encryption is properly configured."""
        # Check that encryption keys are configured
        self.assertTrue(hasattr(settings, 'FIELD_ENCRYPTION_KEYS'),
                       "FIELD_ENCRYPTION_KEYS should be configured")
        
        keys = getattr(settings, 'FIELD_ENCRYPTION_KEYS', [])
        self.assertTrue(keys, "At least one encryption key should be configured")
        self.assertIsInstance(keys[0], str, "Encryption key should be a string")
        self.assertGreater(len(keys[0]), 40, "Encryption key should be sufficiently long")
    
    def test_audit_logging_no_phi_exposure(self):
        """Test that audit logs don't expose PHI."""
        # Create FHIR resources that will generate audit logs
        test_fhir_resources = [
            {
                "resourceType": "Condition",
                "id": "audit-test-condition",
                "code": {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "I10",
                            "display": "Essential hypertension"
                        }
                    ]
                }
            }
        ]
        
        self.patient.add_fhir_resources(test_fhir_resources)
        
        # Check that audit logs exist
        audit_logs = PatientHistory.objects.filter(patient=self.patient)
        self.assertTrue(audit_logs.exists(), "Audit logs should be created")
        
        # Check that audit logs don't contain PHI
        phi_values = [
            self.patient.first_name,
            self.patient.last_name,
            self.patient.ssn,
            self.patient.phone,
            self.patient.email
        ]
        
        for log in audit_logs:
            log_data = {
                'action': log.action,
                'notes': log.notes,
                'fhir_delta': json.dumps(log.fhir_delta) if log.fhir_delta else ''
            }
            
            for field, value in log_data.items():
                if value:
                    for phi_value in phi_values:
                        if phi_value:
                            self.assertNotIn(str(phi_value), str(value),
                                           f"Audit log {field} should not contain PHI: {phi_value}")


class PHIEncryptionIntegrationTestCase(TransactionTestCase):
    """
    Integration tests for PHI encryption across multiple operations.
    """
    
    def setUp(self):
        """Set up test data."""
        self.fake = Faker()
    
    def test_patient_lifecycle_encryption(self):
        """Test PHI encryption throughout patient data lifecycle."""
        # Create patient
        patient = Patient.objects.create(
            mrn=f"LIFECYCLE{self.fake.unique.random_number(digits=6)}",
            first_name=self.fake.first_name(),
            last_name=self.fake.last_name(),
            date_of_birth=self.fake.date_of_birth(minimum_age=18, maximum_age=90).strftime('%Y-%m-%d'),
            ssn=self.fake.ssn().replace('-', ''),
            email=self.fake.email()
        )
        
        original_data = {
            'first_name': patient.first_name,
            'last_name': patient.last_name,
            'ssn': patient.ssn,
            'email': patient.email
        }
        
        # Update patient
        patient.address = self.fake.address()
        patient.phone = self.fake.phone_number()
        patient.save()
        
        # Retrieve patient
        retrieved_patient = Patient.objects.get(id=patient.id)
        
        # Verify original data is still correct
        for field, original_value in original_data.items():
            self.assertEqual(getattr(retrieved_patient, field), original_value,
                           f"{field} should remain unchanged after updates")
        
        # Verify new data is correct
        self.assertEqual(retrieved_patient.address, patient.address)
        self.assertEqual(retrieved_patient.phone, patient.phone)
        
        # Add FHIR data
        fhir_resources = [
            {
                "resourceType": "Condition",
                "id": "lifecycle-test-condition",
                "code": {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "Z87.891",
                            "display": "Personal history of nicotine dependence"
                        }
                    ]
                }
            }
        ]
        
        patient.add_fhir_resources(fhir_resources)
        
        # Retrieve again and verify FHIR data
        final_patient = Patient.objects.get(id=patient.id)
        self.assertIn("entry", final_patient.encrypted_fhir_bundle)
        
        # Verify all original PHI is still intact
        for field, original_value in original_data.items():
            self.assertEqual(getattr(final_patient, field), original_value,
                           f"{field} should remain intact after FHIR operations")
    
    def test_cross_model_phi_consistency(self):
        """Test PHI encryption consistency across related models."""
        # Create patient
        patient = Patient.objects.create(
            mrn=f"CROSS{self.fake.unique.random_number(digits=6)}",
            first_name=self.fake.first_name(),
            last_name=self.fake.last_name(),
            ssn=self.fake.ssn().replace('-', ''),
        )
        
        # Create document
        document = Document.objects.create(
            patient=patient,
            filename="cross_model_test.pdf",
            file_size=2048,
            original_text=f"Medical record for {patient.first_name} {patient.last_name}",
            notes=f"Patient SSN: {patient.ssn}"
        )
        
        # Verify that document's encrypted content doesn't leak patient PHI
        # when both are retrieved from database
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT original_text, notes FROM documents WHERE id = %s",
                [document.id]
            )
            doc_raw = cursor.fetchone()
            
            cursor.execute(
                "SELECT first_name, last_name, ssn FROM patients WHERE id = %s",
                [patient.id]
            )
            patient_raw = cursor.fetchone()
        
        # Raw document data should not contain raw patient data
        if doc_raw[0] and patient_raw[0]:  # original_text and first_name
            self.assertNotEqual(doc_raw[0], patient_raw[0],
                              "Document and patient raw data should be independently encrypted")
        
        # But decrypted document should contain patient info
        self.assertIn(patient.first_name, document.original_text,
                     "Decrypted document should contain patient PHI")
        self.assertIn(patient.ssn, document.notes,
                     "Decrypted document notes should contain patient PHI")
