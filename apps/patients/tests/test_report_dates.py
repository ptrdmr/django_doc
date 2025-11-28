"""
Tests for date conversion in patient report generation.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from datetime import date

from apps.patients.models import Patient

User = get_user_model()


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

