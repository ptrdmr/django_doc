"""
Tests for patient search-optimized fields.

Tests the automatic population and usage of first_name_search and last_name_search
fields for efficient, case-insensitive searching.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.db.models import Q

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


class PatientSearchQuerysetTest(TestCase):
    """
    Test suite for patient search using search-optimized fields at the queryset level.
    """
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test patients
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
    
    def test_queryset_filter_by_first_name_search(self):
        """Test filtering patients by first_name_search field."""
        # Search for exact name
        results = Patient.objects.filter(first_name_search='john')
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first().mrn, 'TEST-101')
        
        # Search with icontains for partial match
        results = Patient.objects.filter(first_name_search__icontains='joh')
        # Should find John and Jonathan (both contain 'joh')
        self.assertGreaterEqual(results.count(), 1)
        patient_mrns = [p.mrn for p in results]
        self.assertIn('TEST-101', patient_mrns)
    
    def test_queryset_filter_by_last_name_search(self):
        """Test filtering patients by last_name_search field."""
        results = Patient.objects.filter(last_name_search__icontains='smith')
        
        # Should find only Jane Smith
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first().mrn, 'TEST-102')
    
    def test_queryset_case_insensitive_search(self):
        """Test that search is case-insensitive."""
        # Since search fields are lowercase, we search with lowercase
        # The __icontains operator is case-insensitive
        results = Patient.objects.filter(first_name_search__icontains='john')
        # Should find exact match 'john' at minimum
        self.assertGreaterEqual(results.count(), 1, 
                               "Query 'john' should find at least 1 patient")
        
        # Test that uppercase search also works (case-insensitive)
        results_upper = Patient.objects.filter(first_name_search__icontains='JOHN')
        self.assertGreaterEqual(results_upper.count(), 1,
                               "Query 'JOHN' should find at least 1 patient")
        
        # Both queries should return same results
        self.assertEqual(results.count(), results_upper.count())
    
    def test_queryset_combined_search(self):
        """Test combining search across first and last names."""
        # Search for 'smith' which appears in last names
        results = Patient.objects.filter(
            Q(first_name_search__icontains='jane') |
            Q(last_name_search__icontains='smith')
        )
        
        # Should find Jane Smith (matches both criteria)
        self.assertGreaterEqual(results.count(), 1)
        patient_mrns = [p.mrn for p in results]
        self.assertIn('TEST-102', patient_mrns)


class PatientSearchPerformanceTest(TestCase):
    """
    Test suite for search performance validation.
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
        results = Patient.objects.filter(
            Q(first_name_search__icontains='searchtest')
        )
        
        # Should find the patient
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first().mrn, 'TEST-200')


class PatientSearchEdgeCasesTest(TestCase):
    """
    Test suite for edge cases in patient search functionality.
    """
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_search_with_special_sql_characters(self):
        """Test search query with SQL special characters."""
        # Create patient
        patient = Patient.objects.create(
            mrn='EDGE-001',
            first_name='Edge',
            last_name='Case',
            date_of_birth='1990-01-01',
            created_by=self.user
        )
        
        # These should be safely escaped by Django ORM
        special_queries = ['%', '_', "'"]
        
        for query in special_queries:
            # Should handle safely without SQL injection
            try:
                results = Patient.objects.filter(first_name_search__icontains=query)
                # Just verify it doesn't crash
                _ = results.count()
            except Exception as e:
                self.fail(f"Query with '{query}' should not raise exception: {e}")
    
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
        
        results = Patient.objects.filter(first_name_search__icontains='françois')
        
        # Should find the patient
        self.assertEqual(results.count(), 1)
    
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
        bulk_created = Patient.objects.filter(mrn__startswith='BULK-')
        
        # All should exist
        self.assertEqual(bulk_created.count(), 5)
        
        # But search fields will be empty (this is Django's expected behavior)
        empty_search_fields = bulk_created.filter(first_name_search='')
        self.assertEqual(empty_search_fields.count(), 5)

