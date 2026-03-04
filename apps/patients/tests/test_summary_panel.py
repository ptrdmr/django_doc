"""
Tests for Patient Summary Side Panel endpoints.

Task 43: Patient Summary Side Panel - summary-data and summary-pdf endpoints.
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.patients.models import Patient


class PatientSummaryPanelEndpointTests(TestCase):
    """Test summary-data and summary-pdf endpoints."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_superuser(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.force_login(self.user)
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            mrn='TEST-SUMMARY-001',
            date_of_birth='1980-01-01',
            gender='M',
            created_by=self.user,
        )

    def test_summary_data_returns_json(self):
        """GET /patients/<pk>/summary-data/ returns JSON with report structure."""
        url = reverse('patients:summary-data', args=[self.patient.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        data = response.json()
        self.assertIn('patient_info', data)
        self.assertIn('clinical_summary', data)
        self.assertIn('report_metadata', data)
        self.assertEqual(data['patient_info']['mrn'], 'TEST-SUMMARY-001')
        self.assertEqual(data['patient_info']['name'], 'John Doe')

    def test_summary_data_requires_auth(self):
        """Unauthenticated request to summary-data returns 302 redirect."""
        self.client.logout()
        url = reverse('patients:summary-data', args=[self.patient.pk])
        response = self.client.get(url)
        self.assertIn(response.status_code, [302, 403])

    def test_summary_data_404_for_invalid_patient(self):
        """summary-data returns 404 for non-existent patient."""
        from uuid import uuid4
        url = reverse('patients:summary-data', args=[uuid4()])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_summary_pdf_returns_pdf(self):
        """GET /patients/<pk>/summary-pdf/ returns PDF file."""
        url = reverse('patients:summary-pdf', args=[self.patient.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment', response.get('Content-Disposition', ''))
        self.assertIn('Patient_Summary', response.get('Content-Disposition', ''))

    def test_summary_pdf_requires_auth(self):
        """Unauthenticated request to summary-pdf returns redirect."""
        self.client.logout()
        url = reverse('patients:summary-pdf', args=[self.patient.pk])
        response = self.client.get(url)
        self.assertIn(response.status_code, [302, 403])
