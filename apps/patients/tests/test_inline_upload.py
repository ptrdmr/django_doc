"""
Tests for Task 44: Inline Document Upload from the patient detail page.

Validates the PatientUploadDocumentView endpoint, InlineDocumentUploadForm,
htmx partial responses, permission enforcement, validation errors, and
integration with the existing floating status indicator via the
ProcessingStatusAPIView.
"""
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import Role, UserProfile
from apps.patients.models import Patient
from apps.documents.models import Document


def make_pdf(size_bytes=1024, name='test_document.pdf'):
    """Create a minimal valid-looking PDF file for testing."""
    header = b'%PDF-1.4 fake content '
    content = header + b'\x00' * max(0, size_bytes - len(header))
    return SimpleUploadedFile(name, content, content_type='application/pdf')


def create_provider_user(username, email='test@test.com', password='pass123'):
    """Create a superuser with provider role and profile.

    Uses superuser so Django model permissions (has_permission decorator) pass.
    The provider role is required by the provider_required decorator.
    """
    provider_role, _ = Role.objects.get_or_create(
        name='provider', defaults={'description': 'Healthcare provider'}
    )
    user = User.objects.create_superuser(username=username, email=email, password=password)
    profile = UserProfile.objects.create(user=user)
    profile.roles.add(provider_role)
    return user


@override_settings(
    MEDIA_ROOT='/tmp/test_inline_upload_media',
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
)
class InlineUploadPermissionTests(TestCase):
    """Verify that only authenticated providers with the correct permission can upload."""

    def setUp(self):
        self.client = Client()
        self.provider = create_provider_user('provider1', 'prov@test.com')
        self.patient = Patient.objects.create(
            first_name='Jane', last_name='Doe', mrn='UPLOAD-PERM-001',
            date_of_birth='1990-05-15', gender='F', created_by=self.provider,
        )
        self.url = reverse('patients:upload-document', args=[self.patient.pk])

    def test_unauthenticated_user_redirected(self):
        """Anonymous users must be redirected to login."""
        response = self.client.post(self.url, {'file': make_pdf()})
        self.assertIn(response.status_code, [302, 403])

    @patch('apps.documents.tasks.process_document_async.delay')
    def test_provider_can_upload(self, mock_delay):
        """Provider with correct role can upload documents."""
        self.client.force_login(self.provider)
        response = self.client.post(self.url, {'file': make_pdf()})
        self.assertIn(response.status_code, [200, 302])
        self.assertEqual(Document.objects.filter(patient=self.patient).count(), 1)

    def test_post_only_endpoint(self):
        """GET requests to the upload endpoint should return 405."""
        self.client.force_login(self.provider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)


@override_settings(
    MEDIA_ROOT='/tmp/test_inline_upload_media',
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
)
class InlineUploadValidationTests(TestCase):
    """Verify server-side file validation catches all bad inputs."""

    def setUp(self):
        self.client = Client()
        self.user = create_provider_user('validator', 'val@test.com')
        self.client.force_login(self.user)
        self.patient = Patient.objects.create(
            first_name='Test', last_name='Patient', mrn='UPLOAD-VAL-001',
            date_of_birth='1985-03-20', gender='M', created_by=self.user,
        )
        self.url = reverse('patients:upload-document', args=[self.patient.pk])

    def test_rejects_non_pdf_file(self):
        """Only PDF files should be accepted; .txt must be rejected."""
        txt_file = SimpleUploadedFile('notes.txt', b'hello', content_type='text/plain')
        self.client.post(self.url, {'file': txt_file})
        self.assertEqual(Document.objects.filter(patient=self.patient).count(), 0)

    def test_rejects_empty_file(self):
        """A zero-byte file must be rejected."""
        empty_pdf = SimpleUploadedFile('empty.pdf', b'', content_type='application/pdf')
        self.client.post(self.url, {'file': empty_pdf})
        self.assertEqual(Document.objects.filter(patient=self.patient).count(), 0)

    def test_rejects_no_file(self):
        """A POST without a file field must be rejected."""
        self.client.post(self.url, {})
        self.assertEqual(Document.objects.filter(patient=self.patient).count(), 0)

    @patch('apps.documents.tasks.process_document_async.delay')
    def test_accepts_valid_pdf(self, mock_delay):
        """A valid PDF under 50MB should be accepted and stored correctly."""
        self.client.post(self.url, {'file': make_pdf()})
        self.assertEqual(Document.objects.filter(patient=self.patient).count(), 1)
        doc = Document.objects.get(patient=self.patient)
        self.assertEqual(doc.filename, 'test_document.pdf')
        self.assertEqual(doc.status, 'pending')
        self.assertEqual(doc.created_by, self.user)


@override_settings(
    MEDIA_ROOT='/tmp/test_inline_upload_media',
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
)
class InlineUploadPatientScopingTests(TestCase):
    """Verify documents are correctly associated with the patient from the URL."""

    def setUp(self):
        self.client = Client()
        self.user = create_provider_user('scoper', 'scope@test.com')
        self.client.force_login(self.user)
        self.patient_a = Patient.objects.create(
            first_name='Alice', last_name='Smith', mrn='SCOPE-A-001',
            date_of_birth='1975-01-01', gender='F', created_by=self.user,
        )
        self.patient_b = Patient.objects.create(
            first_name='Bob', last_name='Jones', mrn='SCOPE-B-001',
            date_of_birth='1960-06-15', gender='M', created_by=self.user,
        )

    @patch('apps.documents.tasks.process_document_async.delay')
    def test_document_linked_to_url_patient(self, mock_delay):
        """Document must be associated with the patient identified in the URL, not any other."""
        url_a = reverse('patients:upload-document', args=[self.patient_a.pk])
        self.client.post(url_a, {'file': make_pdf(name='alice_doc.pdf')})

        self.assertEqual(Document.objects.filter(patient=self.patient_a).count(), 1)
        self.assertEqual(Document.objects.filter(patient=self.patient_b).count(), 0)

        doc = Document.objects.get(patient=self.patient_a)
        self.assertEqual(doc.patient_id, self.patient_a.id)

    def test_nonexistent_patient_returns_404(self):
        """Upload to a non-existent patient UUID must return 404."""
        url = reverse('patients:upload-document', args=[uuid4()])
        response = self.client.post(url, {'file': make_pdf()})
        self.assertEqual(response.status_code, 404)


@override_settings(
    MEDIA_ROOT='/tmp/test_inline_upload_media',
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
)
class InlineUploadCeleryIntegrationTests(TestCase):
    """Verify that async processing is triggered after successful upload."""

    def setUp(self):
        self.client = Client()
        self.user = create_provider_user('celerytest', 'celery@test.com')
        self.client.force_login(self.user)
        self.patient = Patient.objects.create(
            first_name='Celery', last_name='Test', mrn='CELERY-001',
            date_of_birth='1995-12-25', gender='M', created_by=self.user,
        )
        self.url = reverse('patients:upload-document', args=[self.patient.pk])

    @patch('apps.documents.tasks.process_document_async.delay')
    def test_celery_task_triggered_on_upload(self, mock_delay):
        """process_document_async.delay() must be called with the new document's ID."""
        self.client.post(self.url, {'file': make_pdf()})
        mock_delay.assert_called_once()
        doc = Document.objects.get(patient=self.patient)
        mock_delay.assert_called_with(doc.id)

    @patch('apps.documents.tasks.process_document_async.delay')
    def test_celery_not_triggered_on_validation_failure(self, mock_delay):
        """No Celery task should fire when the upload is invalid."""
        txt_file = SimpleUploadedFile('bad.txt', b'nope', content_type='text/plain')
        self.client.post(self.url, {'file': txt_file})
        mock_delay.assert_not_called()


@override_settings(
    MEDIA_ROOT='/tmp/test_inline_upload_media',
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
)
class InlineUploadHtmxResponseTests(TestCase):
    """Verify htmx vs. standard browser request handling."""

    def setUp(self):
        self.client = Client()
        self.user = create_provider_user('htmxtest', 'htmx@test.com')
        self.client.force_login(self.user)
        self.patient = Patient.objects.create(
            first_name='Htmx', last_name='User', mrn='HTMX-001',
            date_of_birth='2000-07-04', gender='F', created_by=self.user,
        )
        self.url = reverse('patients:upload-document', args=[self.patient.pk])

    @patch('apps.documents.tasks.process_document_async.delay')
    def test_htmx_request_returns_html_partial(self, mock_delay):
        """htmx POST should return 200 with HTML containing the document row."""
        response = self.client.post(
            self.url,
            {'file': make_pdf(name='htmx_doc.pdf')},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('htmx_doc.pdf', content)
        self.assertIn('<tr', content)

    @patch('apps.documents.tasks.process_document_async.delay')
    def test_non_htmx_request_redirects(self, mock_delay):
        """Standard browser POST should redirect to patient detail page."""
        response = self.client.post(self.url, {'file': make_pdf()})
        self.assertEqual(response.status_code, 302)
        self.assertIn(str(self.patient.pk), response.url)

    def test_htmx_validation_error_returns_upload_zone(self):
        """htmx POST with invalid file should return the upload zone with errors."""
        txt_file = SimpleUploadedFile('bad.txt', b'nope', content_type='text/plain')
        response = self.client.post(
            self.url,
            {'file': txt_file},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('PDF', content)


@override_settings(
    MEDIA_ROOT='/tmp/test_inline_upload_media',
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
)
class InlineUploadFloatingIndicatorCompatibilityTests(TestCase):
    """
    Verify newly uploaded documents appear in the processing status API,
    ensuring the existing floating indicator picks them up automatically.
    """

    def setUp(self):
        self.client = Client()
        self.user = create_provider_user('indicator', 'indicator@test.com')
        self.client.force_login(self.user)
        self.patient = Patient.objects.create(
            first_name='Indicator', last_name='Test', mrn='INDICATOR-001',
            date_of_birth='1988-11-11', gender='M', created_by=self.user,
        )
        self.upload_url = reverse('patients:upload-document', args=[self.patient.pk])
        self.status_url = reverse('documents:api-processing-status')

    @patch('apps.documents.tasks.process_document_async.delay')
    def test_new_upload_appears_in_processing_status(self, mock_delay):
        """
        After inline upload, the document (status=pending) should appear
        in the /documents/api/processing-status/ response so the floating
        indicator picks it up within its 3-second poll cycle.
        """
        self.client.post(self.upload_url, {'file': make_pdf(name='indicator_test.pdf')})
        doc = Document.objects.get(patient=self.patient)
        self.assertEqual(doc.status, 'pending')

        response = self.client.get(self.status_url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get('success', False))

        processing_ids = [d['id'] for d in data.get('processing_documents', [])]
        self.assertIn(doc.id, processing_ids)


@override_settings(
    MEDIA_ROOT='/tmp/test_inline_upload_media',
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
)
class InlineUploadDuplicateDetectionTests(TestCase):
    """Verify duplicate document detection works for inline uploads."""

    def setUp(self):
        self.client = Client()
        self.user = create_provider_user('dupetest', 'dupe@test.com')
        self.client.force_login(self.user)
        self.patient = Patient.objects.create(
            first_name='Dupe', last_name='Check', mrn='DUPE-001',
            date_of_birth='1970-04-01', gender='M', created_by=self.user,
        )
        self.url = reverse('patients:upload-document', args=[self.patient.pk])

    @patch('apps.documents.tasks.process_document_async.delay')
    def test_duplicate_file_rejected(self, mock_delay):
        """Uploading a file with identical size to an existing non-failed document should be rejected."""
        pdf = make_pdf(size_bytes=2048, name='first.pdf')
        self.client.post(self.url, {'file': pdf})
        self.assertEqual(Document.objects.filter(patient=self.patient).count(), 1)

        duplicate_pdf = make_pdf(size_bytes=2048, name='second.pdf')
        self.client.post(self.url, {'file': duplicate_pdf})
        self.assertEqual(
            Document.objects.filter(patient=self.patient).count(), 1,
            "Duplicate upload should not create a second document"
        )
