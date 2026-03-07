"""
Tests for Patient Summary Side Panel endpoints and Reports deprecation.

Task 43: Patient Summary Side Panel - summary-data and summary-pdf endpoints,
plus deprecation of old Reports flow for patient summaries (subtask 43.8).
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


class PatientSummaryReportsDeprecationTests(TestCase):
    """Verify the old Reports flow is deprecated for patient summaries (Task 43.8)."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_superuser(
            username='testuser_deprecation',
            email='deprecation@example.com',
            password='testpass123'
        )
        self.client.force_login(self.user)
        self.patient = Patient.objects.create(
            first_name='Jane',
            last_name='Smith',
            mrn='TEST-DEPRECATION-001',
            date_of_birth='1985-06-15',
            gender='F',
            created_by=self.user,
        )

    def test_patient_detail_context_excludes_patient_reports(self):
        """Patient detail page no longer provides patient_reports in context."""
        url = reverse('patients:detail', args=[self.patient.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('patient_reports', response.context)

    def test_patient_detail_page_does_not_contain_reports_table(self):
        """Patient detail HTML does not render the old Reports section."""
        url = reverse('patients:detail', args=[self.patient.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn('patient_reports', content)
        self.assertNotIn('No reports generated for this patient', content)

    def test_reports_generate_patient_summary_redirects(self):
        """Requesting patient_summary generation redirects to patients list."""
        url = reverse('reports:generate') + '?type=patient_summary'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('patients:list'), response.url)

    def test_reports_generate_non_patient_summary_not_redirected(self):
        """Non-patient_summary report types are not redirected."""
        url = reverse('reports:generate') + '?type=provider_activity'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_reports_dashboard_marks_patient_summary_deprecated(self):
        """Reports dashboard shows patient_summary as deprecated, not active."""
        url = reverse('reports:dashboard')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Moved to Patient Page', content)

    def test_summary_panel_endpoints_still_work(self):
        """New patient-scoped endpoints remain functional after deprecation."""
        data_url = reverse('patients:summary-data', args=[self.patient.pk])
        data_response = self.client.get(data_url)
        self.assertEqual(data_response.status_code, 200)
        self.assertEqual(data_response['Content-Type'], 'application/json')

        pdf_url = reverse('patients:summary-pdf', args=[self.patient.pk])
        pdf_response = self.client.get(pdf_url)
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')
