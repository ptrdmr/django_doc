"""
Tests for dashboard views.
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from apps.patients.models import Patient


class DashboardViewTests(TestCase):
    """Test cases for the unified dashboard home page."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            is_superuser=True,
        )
        self.client.force_login(self.user)
        self.dashboard_url = reverse('accounts:dashboard')

        self.patient = Patient.objects.create(
            first_name='Test',
            last_name='Patient',
            mrn='TEST-001',
            date_of_birth='1980-01-01',
            gender='M',
        )

    def test_dashboard_loads_successfully(self):
        """Test that dashboard page loads without errors."""
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/dashboard.html')

    def test_dashboard_shows_patient_count(self):
        """Test that dashboard displays correct patient count."""
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('patient_count', response.context)
        self.assertEqual(response.context['patient_count'], 1)

    def test_dashboard_includes_patient_list_for_authorized_users(self):
        """Test that authorized users see patients on the dashboard."""
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['has_patient_permission'])
        self.assertEqual(len(response.context['patients']), 1)
        self.assertEqual(response.context['patients'][0].mrn, 'TEST-001')

    def test_dashboard_search_filters_patients(self):
        """Test that dashboard patient search filters results."""
        Patient.objects.create(
            first_name='Other',
            last_name='Person',
            mrn='TEST-002',
            date_of_birth='1990-01-01',
            gender='F',
        )
        response = self.client.get(self.dashboard_url + '?q=Other')
        self.assertEqual(response.status_code, 200)
        patients = list(response.context['patients'])
        self.assertEqual(len(patients), 1)
        self.assertEqual(patients[0].mrn, 'TEST-002')

    def test_dashboard_hides_patient_list_without_permission(self):
        """Test graceful degradation when user lacks patient view permission."""
        limited_user = User.objects.create_user(
            username='limited',
            email='limited@example.com',
            password='testpass123',
            is_superuser=False,
        )
        self.client.force_login(limited_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['has_patient_permission'])
        self.assertEqual(len(response.context['patients']), 0)

    def test_dashboard_requires_authentication(self):
        """Test that dashboard requires user to be logged in."""
        self.client.logout()
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_legacy_patients_list_redirects_to_dashboard(self):
        """Test that legacy /patients/ URL redirects to unified dashboard."""
        response = self.client.get(reverse('patients:list'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/dashboard/')

    def test_dashboard_paginates_patients(self):
        """Test that dashboard paginates patient results at 10 per page."""
        for i in range(12):
            Patient.objects.create(
                first_name=f'Page{i}',
                last_name='Patient',
                mrn=f'PAGE-{i:03d}',
                date_of_birth='1990-01-01',
                gender='M',
            )

        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_paginated'])
        self.assertEqual(len(response.context['patients']), 10)
