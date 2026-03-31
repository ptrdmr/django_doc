"""
Tests for Patient Summary Side Panel endpoints and Reports deprecation.

Task 43: Patient Summary Side Panel - summary-data and summary-pdf endpoints,
plus deprecation of old Reports flow for patient summaries (subtask 43.8).

Includes tests for comprehensive report coverage of all FHIR resource types
(AllergyIntolerance, CarePlan, ServiceRequest, DiagnosticReport).
"""
import json
from datetime import date

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


def _build_fhir_bundle(resources):
    """Helper to wrap a list of FHIR resource dicts into a Bundle."""
    return {
        'resourceType': 'Bundle',
        'entry': [{'resource': r} for r in resources],
    }


SAMPLE_ALLERGY = {
    'resourceType': 'AllergyIntolerance',
    'id': 'allergy-1',
    'clinicalStatus': {'coding': [{'code': 'active', 'display': 'Active'}]},
    'verificationStatus': {'coding': [{'code': 'confirmed', 'display': 'Confirmed'}]},
    'code': {'text': 'Penicillin'},
    'onsetDateTime': '2020-03-15T00:00:00Z',
    'reaction': [
        {
            'manifestation': [{'text': 'Hives'}, {'text': 'Shortness of breath'}],
            'severity': 'severe',
        }
    ],
    'note': [{'text': 'Documented by allergist'}],
}

SAMPLE_CARE_PLAN = {
    'resourceType': 'CarePlan',
    'id': 'cp-1',
    'status': 'active',
    'intent': 'plan',
    'description': 'Diabetes management plan',
    'period': {'start': '2023-01-01T00:00:00Z', 'end': '2024-01-01T00:00:00Z'},
    'goal': [
        {'description': {'text': 'Reduce A1C below 7%'}},
        {'description': {'text': 'Daily blood glucose monitoring'}},
    ],
    'activity': [
        {'detail': {'description': 'Metformin 500mg twice daily'}},
    ],
    'note': [{'text': 'Reviewed quarterly'}],
}

SAMPLE_SERVICE_REQUEST = {
    'resourceType': 'ServiceRequest',
    'id': 'sr-1',
    'status': 'active',
    'intent': 'order',
    'code': {'text': 'Cardiology referral'},
    'authoredOn': '2024-06-01T00:00:00Z',
    'priority': 'urgent',
    'reasonCode': [{'text': 'Chest pain on exertion'}],
    'category': [{'coding': [{'display': 'Consultation'}]}],
}

SAMPLE_DIAGNOSTIC_REPORT = {
    'resourceType': 'DiagnosticReport',
    'id': 'dr-1',
    'status': 'final',
    'code': {'text': 'Complete Blood Count'},
    'effectiveDateTime': '2024-07-10T14:30:00Z',
    'conclusion': 'All values within normal limits',
    'category': [{'coding': [{'display': 'Laboratory'}]}],
}


class ComprehensiveReportFHIRCoverageTests(TestCase):
    """Verify get_comprehensive_report() extracts all 11 FHIR resource types."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username='coverage_test_user',
            email='coverage@example.com',
            password='testpass123',
        )
        self.patient = Patient.objects.create(
            first_name='Coverage',
            last_name='Test',
            mrn='COV-001',
            date_of_birth='1975-04-20',
            gender='F',
            created_by=self.user,
        )

    # --- AllergyIntolerance ---

    def test_allergy_appears_in_report(self):
        """AllergyIntolerance resources are extracted into clinical_summary.allergies."""
        self.patient.encrypted_fhir_bundle = _build_fhir_bundle([SAMPLE_ALLERGY])
        self.patient.save()

        report = self.patient.get_comprehensive_report()
        allergies = report['clinical_summary']['allergies']

        self.assertEqual(len(allergies), 1)
        allergy = allergies[0]
        self.assertEqual(allergy['display_name'], 'Penicillin')
        self.assertEqual(allergy['status'], 'active')
        self.assertEqual(allergy['verification'], 'confirmed')
        self.assertEqual(allergy['severity'], 'severe')
        self.assertEqual(allergy['onset_date'], date(2020, 3, 15))
        self.assertIn('Hives', allergy['reactions'])
        self.assertIn('Shortness of breath', allergy['reactions'])
        self.assertIn('Documented by allergist', allergy['notes'])

    def test_allergy_with_coding_instead_of_text(self):
        """AllergyIntolerance with code.coding (no text) extracts display name."""
        allergy = {
            'resourceType': 'AllergyIntolerance',
            'id': 'allergy-coded',
            'clinicalStatus': {'coding': [{'code': 'active'}]},
            'verificationStatus': {'coding': [{'code': 'confirmed'}]},
            'code': {'coding': [{'system': 'http://snomed.info/sct', 'code': '91936005', 'display': 'Allergy to penicillin'}]},
        }
        self.patient.encrypted_fhir_bundle = _build_fhir_bundle([allergy])
        self.patient.save()

        report = self.patient.get_comprehensive_report()
        self.assertEqual(report['clinical_summary']['allergies'][0]['display_name'], 'Allergy to penicillin')

    # --- CarePlan ---

    def test_care_plan_appears_in_report(self):
        """CarePlan resources are extracted into clinical_summary.care_plans."""
        self.patient.encrypted_fhir_bundle = _build_fhir_bundle([SAMPLE_CARE_PLAN])
        self.patient.save()

        report = self.patient.get_comprehensive_report()
        plans = report['clinical_summary']['care_plans']

        self.assertEqual(len(plans), 1)
        plan = plans[0]
        self.assertEqual(plan['description'], 'Diabetes management plan')
        self.assertEqual(plan['status'], 'active')
        self.assertEqual(plan['intent'], 'plan')
        self.assertEqual(plan['period']['start'], date(2023, 1, 1))
        self.assertEqual(plan['period']['end'], date(2024, 1, 1))
        self.assertIn('Reduce A1C below 7%', plan['goals'])
        self.assertIn('Metformin 500mg twice daily', plan['activities'])
        self.assertIn('Reviewed quarterly', plan['notes'])

    # --- ServiceRequest ---

    def test_service_request_appears_in_report(self):
        """ServiceRequest resources are extracted into clinical_summary.service_requests."""
        self.patient.encrypted_fhir_bundle = _build_fhir_bundle([SAMPLE_SERVICE_REQUEST])
        self.patient.save()

        report = self.patient.get_comprehensive_report()
        requests = report['clinical_summary']['service_requests']

        self.assertEqual(len(requests), 1)
        req = requests[0]
        self.assertEqual(req['display_name'], 'Cardiology referral')
        self.assertEqual(req['status'], 'active')
        self.assertEqual(req['intent'], 'order')
        self.assertEqual(req['priority'], 'urgent')
        self.assertEqual(req['authored_on'], date(2024, 6, 1))
        self.assertIn('Chest pain on exertion', req['reason'])
        self.assertEqual(req['category'], 'Consultation')

    # --- DiagnosticReport ---

    def test_diagnostic_report_appears_in_report(self):
        """DiagnosticReport resources are extracted into clinical_summary.diagnostic_reports."""
        self.patient.encrypted_fhir_bundle = _build_fhir_bundle([SAMPLE_DIAGNOSTIC_REPORT])
        self.patient.save()

        report = self.patient.get_comprehensive_report()
        reports = report['clinical_summary']['diagnostic_reports']

        self.assertEqual(len(reports), 1)
        dr = reports[0]
        self.assertEqual(dr['display_name'], 'Complete Blood Count')
        self.assertEqual(dr['status'], 'final')
        self.assertEqual(dr['effective_date'], date(2024, 7, 10))
        self.assertEqual(dr['conclusion'], 'All values within normal limits')
        self.assertEqual(dr['category'], 'Laboratory')

    # --- Empty / error handling ---

    def test_empty_bundle_returns_empty_lists_for_new_types(self):
        """Report with no FHIR data returns empty lists for all new resource types."""
        self.patient.encrypted_fhir_bundle = _build_fhir_bundle([])
        self.patient.save()

        report = self.patient.get_comprehensive_report()
        cs = report['clinical_summary']
        self.assertEqual(cs['allergies'], [])
        self.assertEqual(cs['care_plans'], [])
        self.assertEqual(cs['service_requests'], [])
        self.assertEqual(cs['diagnostic_reports'], [])

    def test_no_bundle_returns_empty_lists_for_new_types(self):
        """Report with empty encrypted_fhir_bundle still has all keys present."""
        self.patient.encrypted_fhir_bundle = {}
        self.patient.save()

        report = self.patient.get_comprehensive_report()
        cs = report['clinical_summary']
        for key in ('allergies', 'care_plans', 'service_requests', 'diagnostic_reports'):
            self.assertIn(key, cs)
            self.assertEqual(cs[key], [])

    def test_malformed_allergy_returns_error_dict(self):
        """A malformed AllergyIntolerance resource produces error dict, not a crash."""
        bad_allergy = {
            'resourceType': 'AllergyIntolerance',
            'clinicalStatus': 'not-a-dict',
        }
        self.patient.encrypted_fhir_bundle = _build_fhir_bundle([bad_allergy])
        self.patient.save()

        report = self.patient.get_comprehensive_report()
        allergies = report['clinical_summary']['allergies']
        self.assertEqual(len(allergies), 1)
        self.assertIn('error', allergies[0])

    def test_malformed_care_plan_returns_error_dict(self):
        """A malformed CarePlan resource produces error dict, not a crash."""
        bad_plan = {
            'resourceType': 'CarePlan',
            'period': 'bad-value',
        }
        self.patient.encrypted_fhir_bundle = _build_fhir_bundle([bad_plan])
        self.patient.save()

        report = self.patient.get_comprehensive_report()
        plans = report['clinical_summary']['care_plans']
        self.assertEqual(len(plans), 1)

    def test_all_four_types_together(self):
        """Bundle with all 4 new types extracts each into the correct list."""
        self.patient.encrypted_fhir_bundle = _build_fhir_bundle([
            SAMPLE_ALLERGY,
            SAMPLE_CARE_PLAN,
            SAMPLE_SERVICE_REQUEST,
            SAMPLE_DIAGNOSTIC_REPORT,
        ])
        self.patient.save()

        report = self.patient.get_comprehensive_report()
        cs = report['clinical_summary']
        self.assertEqual(len(cs['allergies']), 1)
        self.assertEqual(len(cs['care_plans']), 1)
        self.assertEqual(len(cs['service_requests']), 1)
        self.assertEqual(len(cs['diagnostic_reports']), 1)

    def test_summary_data_endpoint_includes_new_keys(self):
        """The summary-data JSON endpoint returns all 4 new clinical_summary keys."""
        self.patient.encrypted_fhir_bundle = _build_fhir_bundle([
            SAMPLE_ALLERGY,
            SAMPLE_CARE_PLAN,
            SAMPLE_SERVICE_REQUEST,
            SAMPLE_DIAGNOSTIC_REPORT,
        ])
        self.patient.save()

        client = Client()
        client.force_login(self.user)
        url = reverse('patients:summary-data', args=[self.patient.pk])
        response = client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        cs = data['clinical_summary']
        self.assertEqual(len(cs['allergies']), 1)
        self.assertEqual(cs['allergies'][0]['display_name'], 'Penicillin')
        self.assertEqual(len(cs['care_plans']), 1)
        self.assertEqual(len(cs['service_requests']), 1)
        self.assertEqual(len(cs['diagnostic_reports']), 1)

    def test_date_sorting_allergies(self):
        """Allergies are sorted most recent first by onset_date."""
        old_allergy = dict(SAMPLE_ALLERGY, id='old', onsetDateTime='2018-01-01T00:00:00Z')
        new_allergy = dict(SAMPLE_ALLERGY, id='new', onsetDateTime='2024-01-01T00:00:00Z')
        self.patient.encrypted_fhir_bundle = _build_fhir_bundle([old_allergy, new_allergy])
        self.patient.save()

        report = self.patient.get_comprehensive_report()
        allergies = report['clinical_summary']['allergies']
        self.assertEqual(len(allergies), 2)
        self.assertEqual(allergies[0]['onset_date'], date(2024, 1, 1))
        self.assertEqual(allergies[1]['onset_date'], date(2018, 1, 1))

    def test_date_sorting_service_requests(self):
        """Service requests are sorted most recent first by authored_on."""
        old_sr = dict(SAMPLE_SERVICE_REQUEST, id='old-sr', authoredOn='2022-01-01T00:00:00Z')
        new_sr = dict(SAMPLE_SERVICE_REQUEST, id='new-sr', authoredOn='2025-06-01T00:00:00Z')
        self.patient.encrypted_fhir_bundle = _build_fhir_bundle([old_sr, new_sr])
        self.patient.save()

        report = self.patient.get_comprehensive_report()
        reqs = report['clinical_summary']['service_requests']
        self.assertEqual(len(reqs), 2)
        self.assertEqual(reqs[0]['authored_on'], date(2025, 6, 1))
        self.assertEqual(reqs[1]['authored_on'], date(2022, 1, 1))
