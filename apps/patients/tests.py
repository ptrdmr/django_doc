"""
Tests for patient models and views, including search-optimized fields.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from datetime import date

from apps.patients.models import Patient, PatientHistory

User = get_user_model()


class PatientModelSearchFieldsTest(TestCase):
    """
    Test suite for search-optimized fields in Patient model.
    
    Tests the automatic population of first_name_search and last_name_search
    fields with lowercase versions of encrypted name fields.
    """
    
    def setUp(self):
        """Set up test user for patient creation."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_patient_save_populates_search_fields(self):
        """Test that save method populates search fields with lowercase names."""
        patient = Patient.objects.create(
            mrn='TEST-001',
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            created_by=self.user
        )
        
        # Verify search fields are populated with lowercase values
        self.assertEqual(patient.first_name_search, 'john')
        self.assertEqual(patient.last_name_search, 'doe')
    
    def test_patient_save_handles_mixed_case(self):
        """Test that search fields handle mixed case input correctly."""
        patient = Patient.objects.create(
            mrn='TEST-002',
            first_name='JoHn',
            last_name='DoE',
            date_of_birth='1985-03-15',
            created_by=self.user
        )
        
        # Verify all lowercase regardless of input case
        self.assertEqual(patient.first_name_search, 'john')
        self.assertEqual(patient.last_name_search, 'doe')
    
    def test_patient_save_handles_uppercase(self):
        """Test that search fields handle uppercase input correctly."""
        patient = Patient.objects.create(
            mrn='TEST-003',
            first_name='JOHN',
            last_name='DOE',
            date_of_birth='1990-06-20',
            created_by=self.user
        )
        
        # Verify lowercase conversion
        self.assertEqual(patient.first_name_search, 'john')
        self.assertEqual(patient.last_name_search, 'doe')
    
    def test_patient_update_refreshes_search_fields(self):
        """Test that updating patient name updates search fields."""
        patient = Patient.objects.create(
            mrn='TEST-004',
            first_name='Jane',
            last_name='Smith',
            date_of_birth='1992-11-10',
            created_by=self.user
        )
        
        # Initial verification
        self.assertEqual(patient.first_name_search, 'jane')
        self.assertEqual(patient.last_name_search, 'smith')
        
        # Update patient name
        patient.first_name = 'Janet'
        patient.last_name = 'Johnson'
        patient.save()
        
        # Verify search fields updated
        self.assertEqual(patient.first_name_search, 'janet')
        self.assertEqual(patient.last_name_search, 'johnson')
    
    def test_patient_with_special_characters(self):
        """Test that search fields handle names with special characters."""
        patient = Patient.objects.create(
            mrn='TEST-005',
            first_name="O'Brien",
            last_name='Smith-Jones',
            date_of_birth='1988-08-25',
            created_by=self.user
        )
        
        # Verify special characters preserved but lowercase
        self.assertEqual(patient.first_name_search, "o'brien")
        self.assertEqual(patient.last_name_search, 'smith-jones')
    
    def test_patient_with_accented_characters(self):
        """Test that search fields handle names with accented characters."""
        patient = Patient.objects.create(
            mrn='TEST-006',
            first_name='José',
            last_name='García',
            date_of_birth='1975-04-18',
            created_by=self.user
        )
        
        # Verify accented characters preserved but lowercase
        self.assertEqual(patient.first_name_search, 'josé')
        self.assertEqual(patient.last_name_search, 'garcía')
    
    def test_patient_with_empty_names(self):
        """Test that search fields handle empty name fields gracefully."""
        patient = Patient.objects.create(
            mrn='TEST-007',
            first_name='',
            last_name='',
            date_of_birth='2000-01-01',
            created_by=self.user
        )
        
        # Verify search fields are empty strings (not None)
        self.assertEqual(patient.first_name_search, '')
        self.assertEqual(patient.last_name_search, '')


class PatientSearchFunctionalityTest(TestCase):
    """
    Test suite for patient search functionality using search-optimized fields.
    
    Tests that views correctly use the new search fields for efficient
    case-insensitive searching.
    """
    
    def setUp(self):
        """Set up test data with multiple patients."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.user.set_password('testpass123')
        self.user.save()
        
        # Create test patients with various names
        self.patient1 = Patient.objects.create(
            mrn='TEST-101',
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-15',
            created_by=self.user
        )
        
        self.patient2 = Patient.objects.create(
            mrn='TEST-102',
            first_name='Jane',
            last_name='Smith',
            date_of_birth='1985-06-20',
            created_by=self.user
        )
        
        self.patient3 = Patient.objects.create(
            mrn='TEST-103',
            first_name='Jonathan',
            last_name='Johnson',
            date_of_birth='1990-11-30',
            created_by=self.user
        )
        
        self.patient4 = Patient.objects.create(
            mrn='TEST-104',
            first_name='Mary',
            last_name='O\'Connor',
            date_of_birth='1975-03-10',
            created_by=self.user
        )
        
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
    
    def test_search_by_first_name_lowercase(self):
        """Test searching by first name with lowercase query."""
        response = self.client.get(reverse('patients:list') + '?q=john')
        
        # Should find both 'John' and 'Jonathan'
        patients = response.context['patients']
        patient_mrns = [p.mrn for p in patients]
        
        self.assertIn('TEST-101', patient_mrns)
        self.assertIn('TEST-103', patient_mrns)
        self.assertNotIn('TEST-102', patient_mrns)
    
    def test_search_by_first_name_uppercase(self):
        """Test searching by first name with uppercase query."""
        response = self.client.get(reverse('patients:list') + '?q=JOHN')
        
        # Should find both 'John' and 'Jonathan' (case-insensitive)
        patients = response.context['patients']
        patient_mrns = [p.mrn for p in patients]
        
        self.assertIn('TEST-101', patient_mrns)
        self.assertIn('TEST-103', patient_mrns)
    
    def test_search_by_last_name(self):
        """Test searching by last name."""
        response = self.client.get(reverse('patients:list') + '?q=smith')
        
        # Should find only Jane Smith
        patients = response.context['patients']
        self.assertEqual(len(patients), 1)
        self.assertEqual(patients[0].mrn, 'TEST-102')
    
    def test_search_by_partial_name(self):
        """Test searching with partial name match."""
        response = self.client.get(reverse('patients:list') + '?q=jon')
        
        # Should find John, Jonathan, Johnson
        patients = response.context['patients']
        patient_mrns = [p.mrn for p in patients]
        
        self.assertIn('TEST-101', patient_mrns)  # John
        self.assertIn('TEST-103', patient_mrns)  # Jonathan/Johnson
    
    def test_search_by_mrn(self):
        """Test searching by MRN."""
        response = self.client.get(reverse('patients:list') + '?q=TEST-102')
        
        # Should find only Jane Smith
        patients = response.context['patients']
        self.assertEqual(len(patients), 1)
        self.assertEqual(patients[0].mrn, 'TEST-102')
    
    def test_search_with_special_characters(self):
        """Test searching for name with special characters."""
        response = self.client.get(reverse('patients:list') + "?q=o'connor")
        
        # Should find Mary O'Connor
        patients = response.context['patients']
        self.assertEqual(len(patients), 1)
        self.assertEqual(patients[0].mrn, 'TEST-104')
    
    def test_empty_search_returns_all_patients(self):
        """Test that empty search query returns all patients."""
        response = self.client.get(reverse('patients:list'))
        
        patients = response.context['patients']
        self.assertEqual(len(patients), 4)
    
    def test_search_no_results(self):
        """Test search query that matches no patients."""
        response = self.client.get(reverse('patients:list') + '?q=nonexistent')
        
        patients = response.context['patients']
        self.assertEqual(len(patients), 0)
    
    def test_search_pagination_preserves_query(self):
        """Test that pagination preserves search query parameters."""
        # Create more patients to trigger pagination (need > 20)
        for i in range(25):
            Patient.objects.create(
                mrn=f'PAGI-{i:03d}',
                first_name='Test',
                last_name=f'Patient{i}',
                date_of_birth='1990-01-01',
                created_by=self.user
            )
        
        response = self.client.get(reverse('patients:list') + '?q=test')
        
        # Verify search query in context
        self.assertEqual(response.context['search_query'], 'test')
        
        # Verify pagination exists
        self.assertTrue(response.context['is_paginated'])
    
    def test_search_case_insensitive_mixed_case(self):
        """Test case-insensitive search with mixed case input."""
        # Search with various case combinations
        test_queries = ['JoHn', 'SMITH', 'DoE', 'jOnAtHaN']
        
        for query in test_queries:
            response = self.client.get(reverse('patients:list') + f'?q={query}')
            patients = response.context['patients']
            # Each query should find at least one patient
            self.assertGreater(len(patients), 0, 
                             f"Query '{query}' should find at least one patient")


class PatientSearchPerformanceTest(TestCase):
    """
    Test suite for search performance validation.
    
    Ensures that search operations use database indexes and don't
    perform operations on encrypted fields.
    """
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_search_fields_indexed(self):
        """Verify that search fields have database indexes."""
        from django.db import connection
        
        # Get index information from database
        with connection.cursor() as cursor:
            # Check for indexes on search fields
            cursor.execute("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'patients' 
                AND (indexname LIKE '%first_name_search%' 
                     OR indexname LIKE '%last_name_search%')
            """)
            indexes = cursor.fetchall()
        
        # Should have indexes on both search fields
        self.assertGreater(len(indexes), 0, 
                          "Search fields should have database indexes")
    
    def test_queryset_uses_search_fields(self):
        """Verify that search queries use the search_optimized fields."""
        # Create a test patient
        patient = Patient.objects.create(
            mrn='TEST-200',
            first_name='SearchTest',
            last_name='User',
            date_of_birth='1990-01-01',
            created_by=self.user
        )
        
        # Query using search fields
        from django.db.models import Q
        results = Patient.objects.filter(
            Q(first_name_search__icontains='searchtest')
        )
        
        # Should find the patient
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first().mrn, 'TEST-200')


class PatientSearchEdgeCasesTest(TestCase):
    """
    Test suite for edge cases in patient search functionality.
    
    Tests boundary conditions, special inputs, and error handling.
    """
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
        
        # Create test patient
        self.patient = Patient.objects.create(
            mrn='EDGE-001',
            first_name='Edge',
            last_name='Case',
            date_of_birth='1990-01-01',
            created_by=self.user
        )
    
    def test_search_with_very_long_query(self):
        """Test search with maximum length query string."""
        long_query = 'a' * 100  # Max length from PatientSearchForm
        response = self.client.get(reverse('patients:list') + f'?q={long_query}')
        
        # Should handle gracefully without error
        self.assertEqual(response.status_code, 200)
    
    def test_search_with_special_sql_characters(self):
        """Test search query with SQL special characters."""
        # These should be safely escaped by Django ORM
        special_queries = [
            "%",     # SQL wildcard
            "_",     # SQL wildcard
            "'",     # SQL quote
            ";",     # SQL statement terminator
            "--",    # SQL comment
        ]
        
        for query in special_queries:
            response = self.client.get(reverse('patients:list') + f'?q={query}')
            # Should handle safely without SQL injection
            self.assertEqual(response.status_code, 200)
    
    def test_search_with_unicode_characters(self):
        """Test search with various Unicode characters."""
        # Create patient with Unicode name
        Patient.objects.create(
            mrn='UNICODE-001',
            first_name='François',
            last_name='Müller',
            date_of_birth='1985-05-15',
            created_by=self.user
        )
        
        response = self.client.get(reverse('patients:list') + '?q=françois')
        patients = response.context['patients']
        
        # Should find the patient
        patient_mrns = [p.mrn for p in patients]
        self.assertIn('UNICODE-001', patient_mrns)
    
    def test_search_with_whitespace(self):
        """Test search query with leading/trailing whitespace."""
        # Whitespace should be stripped by form validation
        response = self.client.get(reverse('patients:list') + '?q=%20edge%20')
        patients = response.context['patients']
        
        # Should still find the patient
        self.assertGreater(len(patients), 0)
    
    def test_bulk_patient_creation_populates_search_fields(self):
        """Test that bulk_create doesn't populate search fields (expected behavior)."""
        # Note: bulk_create bypasses save() method
        # This is documented Django behavior
        bulk_patients = [
            Patient(
                mrn=f'BULK-{i:03d}',
                first_name='Bulk',
                last_name=f'Patient{i}',
                date_of_birth='1990-01-01',
                created_by=self.user
            )
            for i in range(5)
        ]
        
        Patient.objects.bulk_create(bulk_patients)
        
        # Verify: bulk_create doesn't call save(), so search fields won't be populated
        # This is expected and documented behavior
        bulk_created = Patient.objects.filter(mrn__startswith='BULK-')
        
        # All should exist
        self.assertEqual(bulk_created.count(), 5)
        
        # But search fields will be empty (this is Django's expected behavior)
        # If we need search fields populated, we'd need to iterate and save individually
        empty_search_fields = bulk_created.filter(first_name_search='')
        self.assertEqual(empty_search_fields.count(), 5)


class PatientSearchIntegrationTest(TestCase):
    """
    Integration tests for patient search across the entire workflow.
    
    Tests end-to-end scenarios combining model creation, updates,
    and search functionality.
    """
    
    def setUp(self):
        """Set up complete test environment."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
    
    def test_create_patient_and_search_workflow(self):
        """Test complete workflow: create patient, then search for them."""
        # Create patient via view (if we had a create view that we could test)
        patient = Patient.objects.create(
            mrn='WORKFLOW-001',
            first_name='Workflow',
            last_name='Test',
            date_of_birth='1990-01-01',
            created_by=self.user
        )
        
        # Verify search fields populated
        self.assertEqual(patient.first_name_search, 'workflow')
        self.assertEqual(patient.last_name_search, 'test')
        
        # Search for the patient
        response = self.client.get(reverse('patients:list') + '?q=workflow')
        patients = response.context['patients']
        
        # Should find the patient
        self.assertEqual(len(patients), 1)
        self.assertEqual(patients[0].mrn, 'WORKFLOW-001')
    
    def test_update_patient_and_search_workflow(self):
        """Test workflow: update patient name, then search with new name."""
        # Create patient
        patient = Patient.objects.create(
            mrn='UPDATE-001',
            first_name='Original',
            last_name='Name',
            date_of_birth='1990-01-01',
            created_by=self.user
        )
        
        # Update patient name
        patient.first_name = 'Updated'
        patient.last_name = 'Patient'
        patient.save()
        
        # Search with old name - should not find
        response = self.client.get(reverse('patients:list') + '?q=original')
        patients = response.context['patients']
        self.assertEqual(len(patients), 0)
        
        # Search with new name - should find
        response = self.client.get(reverse('patients:list') + '?q=updated')
        patients = response.context['patients']
        self.assertEqual(len(patients), 1)
        self.assertEqual(patients[0].mrn, 'UPDATE-001')
    
    def test_search_history_preservation(self):
        """Test that patient history is maintained during updates."""
        # Create patient
        patient = Patient.objects.create(
            mrn='HISTORY-001',
            first_name='History',
            last_name='Patient',
            date_of_birth='1990-01-01',
            created_by=self.user
        )
        
        # Create history record
        PatientHistory.objects.create(
            patient=patient,
            action='created',
            changed_by=self.user,
            notes='Initial creation'
        )
        
        # Update patient name
        patient.first_name = 'Updated'
        patient.save()
        
        # Verify history still accessible
        history = PatientHistory.objects.filter(patient=patient)
        self.assertEqual(history.count(), 1)
        
        # Verify search still works
        response = self.client.get(reverse('patients:list') + '?q=updated')
        patients = response.context['patients']
        self.assertEqual(len(patients), 1)


class PatientReportDateConversionTest(TestCase):
    """
    Test suite for date conversion in patient report generation.
    
    Ensures that dates extracted from FHIR resources are converted to
    Python date objects for proper template rendering.
    """
    
    def setUp(self):
        """Set up test patient with FHIR data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create patient with FHIR bundle containing date strings
        self.patient = Patient.objects.create(
            mrn='DATE-TEST-001',
            first_name='Date',
            last_name='Test',
            date_of_birth='1980-01-01',
            created_by=self.user
        )
        
        # Add FHIR bundle with observations, medications, procedures, conditions
        self.patient.encrypted_fhir_bundle = {
            'resourceType': 'Bundle',
            'type': 'collection',
            'entry': [
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'id': 'obs-1',
                        'status': 'final',
                        'code': {
                            'text': 'Test Lab Result'
                        },
                        'valueString': '100',
                        'effectiveDateTime': '2018-09-05T00:00:00+00:00'
                    }
                },
                {
                    'resource': {
                        'resourceType': 'MedicationStatement',
                        'id': 'med-1',
                        'status': 'active',
                        'medication': {
                            'concept': {
                                'text': 'Test Medication'
                            }
                        },
                        'dosage': [{'text': '10mg daily'}],
                        'effectiveDateTime': '2020-01-15T00:00:00+00:00'
                    }
                },
                {
                    'resource': {
                        'resourceType': 'Procedure',
                        'id': 'proc-1',
                        'status': 'completed',
                        'code': {
                            'text': 'Test Procedure'
                        },
                        'occurrenceDateTime': '2019-06-20T00:00:00+00:00'
                    }
                },
                {
                    'resource': {
                        'resourceType': 'Condition',
                        'id': 'cond-1',
                        'code': {
                            'text': 'Test Condition'
                        },
                        'onsetDateTime': '2017-03-10T00:00:00+00:00',
                        'recordedDate': '2017-03-12T00:00:00+00:00'
                    }
                }
            ]
        }
        self.patient.save()
    
    def test_observation_date_is_date_object(self):
        """Test that observation effective_date is a Python date object."""
        report = self.patient.get_comprehensive_report()
        
        # Get first observation
        observations = report['clinical_summary']['observations']
        self.assertGreater(len(observations), 0, "Should have at least one observation")
        
        obs = observations[0]
        self.assertIsNotNone(obs['effective_date'], "Observation should have effective_date")
        self.assertIsInstance(obs['effective_date'], date, 
                            "effective_date should be a Python date object, not a string")
        self.assertEqual(obs['effective_date'], date(2018, 9, 5))
    
    def test_medication_date_is_date_object(self):
        """Test that medication effective_period dates are Python date objects."""
        report = self.patient.get_comprehensive_report()
        
        # Get first medication
        medications = report['clinical_summary']['medications']
        self.assertGreater(len(medications), 0, "Should have at least one medication")
        
        med = medications[0]
        self.assertIsNotNone(med['effective_period'], "Medication should have effective_period")
        self.assertIsNotNone(med['effective_period']['start'], "Should have start date")
        self.assertIsInstance(med['effective_period']['start'], date,
                            "Start date should be a Python date object, not a string")
        self.assertEqual(med['effective_period']['start'], date(2020, 1, 15))
    
    def test_procedure_date_is_date_object(self):
        """Test that procedure performed_date is a Python date object."""
        report = self.patient.get_comprehensive_report()
        
        # Get first procedure
        procedures = report['clinical_summary']['procedures']
        self.assertGreater(len(procedures), 0, "Should have at least one procedure")
        
        proc = procedures[0]
        self.assertIsNotNone(proc['performed_date'], "Procedure should have performed_date")
        self.assertIsInstance(proc['performed_date'], date,
                            "performed_date should be a Python date object, not a string")
        self.assertEqual(proc['performed_date'], date(2019, 6, 20))
    
    def test_condition_dates_are_date_objects(self):
        """Test that condition onset_date and recorded_date are Python date objects."""
        report = self.patient.get_comprehensive_report()
        
        # Get first condition
        conditions = report['clinical_summary']['conditions']
        self.assertGreater(len(conditions), 0, "Should have at least one condition")
        
        cond = conditions[0]
        self.assertIsNotNone(cond['onset_date'], "Condition should have onset_date")
        self.assertIsInstance(cond['onset_date'], date,
                            "onset_date should be a Python date object, not a string")
        self.assertEqual(cond['onset_date'], date(2017, 3, 10))
        
        self.assertIsNotNone(cond['recorded_date'], "Condition should have recorded_date")
        self.assertIsInstance(cond['recorded_date'], date,
                            "recorded_date should be a Python date object, not a string")
        self.assertEqual(cond['recorded_date'], date(2017, 3, 12))
    
    def test_malformed_date_returns_none(self):
        """Test that malformed date strings are handled gracefully."""
        # Create patient with malformed date
        patient = Patient.objects.create(
            mrn='MALFORMED-001',
            first_name='Malformed',
            last_name='Date',
            date_of_birth='1990-01-01',
            created_by=self.user
        )
        
        patient.encrypted_fhir_bundle = {
            'resourceType': 'Bundle',
            'type': 'collection',
            'entry': [
                {
                    'resource': {
                        'resourceType': 'Observation',
                        'id': 'obs-bad',
                        'status': 'final',
                        'code': {'text': 'Test'},
                        'valueString': '100',
                        'effectiveDateTime': 'invalid-date-string'
                    }
                }
            ]
        }
        patient.save()
        
        report = patient.get_comprehensive_report()
        observations = report['clinical_summary']['observations']
        
        # Should handle gracefully without crashing
        self.assertGreater(len(observations), 0)
        # Malformed date should result in None
        self.assertIsNone(observations[0]['effective_date'])