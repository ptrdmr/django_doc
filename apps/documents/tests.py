"""
Tests for document processing functionality.
"""
import os
import tempfile
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.patients.models import Patient
from .models import Document
from .services import PDFTextExtractor, DocumentAnalyzer
from .tasks import process_document_async

User = get_user_model()


class PDFTextExtractorTests(TestCase):
    """
    Test the PDF text extraction service.
    """
    
    def setUp(self):
        """Set up test data"""
        self.extractor = PDFTextExtractor()
        
    def test_extractor_initialization(self):
        """Test PDF extractor initializes correctly"""
        self.assertEqual(self.extractor.supported_extensions, ['.pdf'])
        self.assertEqual(self.extractor.max_file_size_mb, 50)
    
    def test_validate_file_nonexistent(self):
        """Test validation of non-existent file"""
        result = self.extractor._validate_file('/nonexistent/file.pdf')
        self.assertFalse(result['valid'])
        self.assertIn('File not found', result['error'])
    
    def test_validate_file_wrong_extension(self):
        """Test validation of wrong file extension"""
        # Create a temporary text file
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as temp_file:
            temp_file.write(b"test content")
            temp_file_path = temp_file.name
        
        try:
            result = self.extractor._validate_file(temp_file_path)
            self.assertFalse(result['valid'])
            self.assertIn('Unsupported file type', result['error'])
        finally:
            os.unlink(temp_file_path)
    
    def test_clean_text_basic(self):
        """Test basic text cleaning functionality"""
        dirty_text = "This  is    a\n\n\n\ntest   document.\nWith multiple   spaces."
        cleaned = self.extractor._clean_text(dirty_text)
        
        # Should normalize spaces and line breaks
        self.assertNotIn('    ', cleaned)  # No multiple spaces
        self.assertNotIn('\n\n\n', cleaned)  # No triple line breaks
        self.assertIn('test document', cleaned)
    
    def test_clean_text_empty(self):
        """Test cleaning empty or None text"""
        self.assertEqual(self.extractor._clean_text(""), "")
        self.assertEqual(self.extractor._clean_text(None), "")
    
    def test_clean_text_medical_patterns(self):
        """Test cleaning of medical document patterns"""
        medical_text = "Date: 12 / 3 / 2023\nBlood pressure: 120.80mmHg\nTemperature:98.6F"
        cleaned = self.extractor._clean_text(medical_text)
        
        # Should normalize date format
        self.assertIn('12/3/2023', cleaned)
        # Should preserve decimal numbers
        self.assertIn('120.80', cleaned)
    
    @patch('pdfplumber.open')
    def test_extract_text_success(self, mock_pdfplumber):
        """Test successful text extraction"""
        # Mock PDF object
        mock_pdf = MagicMock()
        mock_pdf.metadata = {'Title': 'Test Document', 'Author': 'Test Author'}
        mock_pdf.pages = [MagicMock(), MagicMock()]
        
        # Mock page text extraction
        mock_pdf.pages[0].extract_text.return_value = "Page 1 content"
        mock_pdf.pages[1].extract_text.return_value = "Page 2 content"
        
        mock_pdfplumber.return_value.__enter__.return_value = mock_pdf
        
        # Create a temporary PDF file for testing
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
            temp_file.write(b"fake pdf content")
            temp_file_path = temp_file.name
        
        try:
            result = self.extractor.extract_text(temp_file_path)
            
            self.assertTrue(result['success'])
            self.assertIn('Page 1 content', result['text'])
            self.assertIn('Page 2 content', result['text'])
            self.assertEqual(result['page_count'], 2)
            self.assertEqual(result['metadata']['title'], 'Test Document')
            
        finally:
            os.unlink(temp_file_path)
    
    @patch('pdfplumber.open')
    def test_extract_text_pdf_error(self, mock_pdfplumber):
        """Test extraction when PDF is corrupted"""
        mock_pdfplumber.side_effect = Exception("Corrupted PDF")
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
            temp_file.write(b"fake pdf content")
            temp_file_path = temp_file.name
        
        try:
            result = self.extractor.extract_text(temp_file_path)
            
            self.assertFalse(result['success'])
            self.assertIn('Invalid or corrupted PDF', result['error_message'])
            
        finally:
            os.unlink(temp_file_path)


class DocumentProcessingTaskTests(TestCase):
    """
    Test the document processing Celery task.
    """
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            created_by=self.user
        )
        
        # Create a document with a mock file
        self.document = Document.objects.create(
            patient=self.patient,
            filename='test_document.pdf',
            status='pending',
            created_by=self.user
        )
    
    def test_process_document_nonexistent(self):
        """Test processing non-existent document"""
        result = process_document_async(999999)  # Non-existent ID
        
        self.assertFalse(result['success'])
        self.assertIn('does not exist', result['error_message'])
    
    @patch('apps.documents.services.PDFTextExtractor.extract_text')
    @patch('apps.documents.models.Document.objects.get')
    def test_process_document_success(self, mock_get_doc, mock_extract):
        """Test successful document processing"""
        # Setup mocks
        mock_document = MagicMock()
        mock_document.id = self.document.id
        mock_document.file.path = '/fake/path/test.pdf'
        mock_document.status = 'uploaded'
        mock_document.processing_started_at = None
        mock_document.original_text = ''
        
        mock_get_doc.return_value = mock_document
        mock_extract.return_value = {
            'success': True,
            'text': 'Extracted text from PDF',
            'page_count': 2,
            'file_size': 1.5,
            'metadata': {'title': 'Test Document'}
        }
        
        result = process_document_async(self.document.id)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['page_count'], 2)
        self.assertEqual(result['text_length'], len('Extracted text from PDF'))
    
    @patch('apps.documents.services.PDFTextExtractor.extract_text')
    @patch('apps.documents.models.Document.objects.get')
    def test_process_document_extraction_failure(self, mock_get_doc, mock_extract):
        """Test document processing when extraction fails"""
        # Setup mocks
        mock_document = MagicMock()
        mock_document.id = self.document.id
        mock_document.file.path = '/fake/path/test.pdf'
        mock_document.status = 'uploaded'
        mock_document.processing_started_at = None
        mock_document.original_text = ''
        
        mock_get_doc.return_value = mock_document
        mock_extract.return_value = {
            'success': False,
            'error_message': 'PDF is corrupted'
        }
        
        result = process_document_async(self.document.id)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'failed')
        self.assertIn('PDF is corrupted', result['error_message'])


class DocumentModelTests(TestCase):
    """
    Test document model functionality.
    """
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='Jane',
            last_name='Smith',
            date_of_birth='1985-05-15',
            created_by=self.user
        )
    
    def test_document_creation(self):
        """Test creating a document"""
        document = Document.objects.create(
            patient=self.patient,
            filename='test.pdf',
            status='pending',
            created_by=self.user
        )
        
        self.assertEqual(document.status, 'pending')
        self.assertEqual(document.processing_attempts, 0)
        self.assertEqual(str(document), f'test.pdf - {self.patient} (pending)')
    
    def test_can_retry_processing(self):
        """Test retry logic"""
        document = Document.objects.create(
            patient=self.patient,
            filename='test.pdf',
            status='failed',
            processing_attempts=2,
            created_by=self.user
        )
        
        # Should be able to retry (less than 3 attempts)
        self.assertTrue(document.can_retry_processing())
        
        # After 3 attempts, should not be able to retry
        document.processing_attempts = 3
        self.assertFalse(document.can_retry_processing())
    
    def test_processing_duration(self):
        """Test processing duration calculation"""
        document = Document.objects.create(
            patient=self.patient,
            filename='test.pdf',
            status='processing',
            created_by=self.user
        )
        
        # Set processing timestamps
        start_time = timezone.now()
        end_time = start_time + timezone.timedelta(seconds=30)
        
        document.processing_started_at = start_time
        document.processed_at = end_time
        
        duration = document.get_processing_duration()
        self.assertEqual(duration, 30.0)
    
    def test_increment_processing_attempts(self):
        """Test incrementing processing attempts"""
        document = Document.objects.create(
            patient=self.patient,
            filename='test.pdf',
            status='pending',
            created_by=self.user
        )
        
        original_attempts = document.processing_attempts
        document.increment_processing_attempts()
        
        # Reload from database
        document.refresh_from_db()
        self.assertEqual(document.processing_attempts, original_attempts + 1)


class DocumentViewTests(TestCase):
    """
    Test document views.
    """
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='Bob',
            last_name='Johnson',
            date_of_birth='1975-10-20',
            created_by=self.user
        )
        
        self.client.login(username='testuser', password='testpass123')
    
    def test_upload_view_get(self):
        """Test GET request to upload view"""
        response = self.client.get('/documents/upload/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Upload Document')
    
    @patch('apps.documents.tasks.process_document_async.delay')
    def test_upload_view_post_success(self, mock_delay):
        """Test successful document upload"""
        # Create a fake PDF file
        pdf_content = b'%PDF-1.4 fake pdf content'
        uploaded_file = SimpleUploadedFile(
            'test.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        
        response = self.client.post('/documents/upload/', {
            'patient': self.patient.id,
            'file': uploaded_file
        })
        
        # Should redirect to success page
        self.assertEqual(response.status_code, 302)
        
        # Check document was created
        document = Document.objects.get(filename='test.pdf')
        self.assertEqual(document.patient, self.patient)
        self.assertEqual(document.status, 'pending')
        
        # Check Celery task was called
        mock_delay.assert_called_once_with(document.id)


# ============================================================================
# DOCUMENT ANALYZER AI SERVICE TESTS
# ============================================================================

class DocumentAnalyzerTests(TestCase):
    """
    Test the DocumentAnalyzer AI service for medical document processing.
    """
    
    def setUp(self):
        """Set up test data"""
        # Mock AI clients to avoid actual API calls during testing
        self.anthropic_patcher = patch('apps.documents.services.anthropic')
        self.openai_patcher = patch('apps.documents.services.openai')
        
        self.mock_anthropic = self.anthropic_patcher.start()
        self.mock_openai = self.openai_patcher.start()
        
        # Add cleanup
        self.addCleanup(self.anthropic_patcher.stop)
        self.addCleanup(self.openai_patcher.stop)
    
    @override_settings(ANTHROPIC_API_KEY='test_anthropic_key')
    def test_analyzer_initialization_with_anthropic(self):
        """Test DocumentAnalyzer initializes correctly with Anthropic key"""
        from .services import DocumentAnalyzer
        
        # Mock successful client initialization
        mock_client = MagicMock()
        self.mock_anthropic.Client.return_value = mock_client
        
        analyzer = DocumentAnalyzer()
        
        self.assertEqual(analyzer.anthropic_key, 'test_anthropic_key')
        self.assertEqual(analyzer.primary_model, 'claude-3-sonnet-20240229')
        self.assertIsNotNone(analyzer.anthropic_client)
    
    @override_settings(ANTHROPIC_API_KEY=None, OPENAI_API_KEY='test_openai_key')
    def test_analyzer_initialization_with_openai_only(self):
        """Test DocumentAnalyzer initializes with only OpenAI key"""
        from .services import DocumentAnalyzer
        
        # Mock successful client initialization
        mock_client = MagicMock()
        self.mock_openai.OpenAI.return_value = mock_client
        
        analyzer = DocumentAnalyzer()
        
        self.assertEqual(analyzer.openai_key, 'test_openai_key')
        self.assertIsNotNone(analyzer.openai_client)
    
    @override_settings(ANTHROPIC_API_KEY=None, OPENAI_API_KEY=None)
    def test_analyzer_initialization_no_keys(self):
        """Test DocumentAnalyzer fails to initialize without API keys"""
        from .services import DocumentAnalyzer
        from django.core.exceptions import ImproperlyConfigured
        
        with self.assertRaises(ImproperlyConfigured):
            DocumentAnalyzer()
    
    @override_settings(ANTHROPIC_API_KEY='test_key')
    def test_analyze_empty_document(self):
        """Test analysis of empty document content"""
        from .services import DocumentAnalyzer
        
        # Mock successful client initialization
        mock_client = MagicMock()
        self.mock_anthropic.Client.return_value = mock_client
        
        analyzer = DocumentAnalyzer()
        result = analyzer.analyze_document("")
        
        self.assertFalse(result['success'])
        self.assertIn('empty', result['error'])
        self.assertEqual(result['fields'], [])
    
    @override_settings(ANTHROPIC_API_KEY='test_key')
    def test_analyze_small_document_success(self):
        """Test successful analysis of a small document"""
        from .services import DocumentAnalyzer
        
        # Mock successful client initialization and API response
        mock_client = MagicMock()
        self.mock_anthropic.Client.return_value = mock_client
        
        # Mock API response
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '[{"label": "Patient Name", "value": "John Smith", "confidence": 0.95}]'
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        
        mock_client.messages.create.return_value = mock_response
        
        analyzer = DocumentAnalyzer()
        
        # Test document content
        test_content = "Patient: John Smith\nDOB: 1980-01-15\nDiagnosis: Hypertension"
        
        result = analyzer.analyze_document(test_content)
        
        self.assertTrue(result['success'])
        self.assertEqual(len(result['fields']), 1)
        self.assertEqual(result['fields'][0]['label'], 'Patient Name')
        self.assertEqual(result['fields'][0]['value'], 'John Smith')
        self.assertEqual(result['fields'][0]['confidence'], 0.95)
        self.assertEqual(result['model_used'], 'claude-3-sonnet-20240229')
        self.assertEqual(result['usage']['total_tokens'], 150)
    
    @override_settings(ANTHROPIC_API_KEY='test_key')
    def test_analyze_document_with_fallback_parsing(self):
        """Test document analysis with fallback JSON parsing"""
        from .services import DocumentAnalyzer
        
        # Mock successful client initialization
        mock_client = MagicMock()
        self.mock_anthropic.Client.return_value = mock_client
        
        # Mock API response with malformed JSON requiring fallback
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = 'Some text with invalid JSON [{"incomplete": true'
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        
        mock_client.messages.create.return_value = mock_response
        
        analyzer = DocumentAnalyzer()
        
        result = analyzer.analyze_document("Test content")
        
        self.assertTrue(result['success'])
        self.assertEqual(len(result['fields']), 1)
        self.assertEqual(result['fields'][0]['label'], 'Raw AI Response')
        self.assertEqual(result['fields'][0]['confidence'], 0.3)
    
    @override_settings(ANTHROPIC_API_KEY='test_key')
    def test_analyze_large_document_chunking(self):
        """Test large document chunking and processing"""
        from .services import DocumentAnalyzer
        
        # Mock successful client initialization
        mock_client = MagicMock()
        self.mock_anthropic.Client.return_value = mock_client
        
        # Mock API responses for multiple chunks
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '[{"label": "Patient Name", "value": "John Smith", "confidence": 0.95}]'
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        
        mock_client.messages.create.return_value = mock_response
        
        analyzer = DocumentAnalyzer()
        
        # Create a large document that will trigger chunking
        large_content = "Medical Report\n" * 10000  # Large enough to trigger chunking
        
        result = analyzer.analyze_document(large_content)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['processing_method'], 'chunked_document')
        self.assertGreater(result['chunks_total'], 1)
        self.assertGreater(result['chunks_successful'], 0)
    
    @override_settings(ANTHROPIC_API_KEY='test_key', OPENAI_API_KEY='test_openai_key')
    def test_anthropic_failure_openai_fallback(self):
        """Test fallback to OpenAI when Anthropic fails"""
        from .services import DocumentAnalyzer
        
        # Mock client initialization
        mock_anthropic_client = MagicMock()
        mock_openai_client = MagicMock()
        
        self.mock_anthropic.Client.return_value = mock_anthropic_client
        self.mock_openai.OpenAI.return_value = mock_openai_client
        
        # Mock Anthropic failure
        mock_anthropic_client.messages.create.side_effect = Exception("Anthropic API error")
        
        # Mock successful OpenAI response
        mock_openai_response = MagicMock()
        mock_openai_response.choices = [MagicMock()]
        mock_openai_response.choices[0].message.content = '[{"label": "Patient Name", "value": "Jane Doe", "confidence": 0.90}]'
        mock_openai_response.usage.prompt_tokens = 120
        mock_openai_response.usage.completion_tokens = 60
        mock_openai_response.usage.total_tokens = 180
        
        mock_openai_client.chat.completions.create.return_value = mock_openai_response
        
        analyzer = DocumentAnalyzer()
        
        result = analyzer.analyze_document("Test medical document")
        
        self.assertTrue(result['success'])
        self.assertEqual(result['model_used'], 'gpt-3.5-turbo')
        self.assertEqual(result['processing_method'], 'single_document_fallback')
        self.assertEqual(result['fields'][0]['value'], 'Jane Doe')
    
    @override_settings(ANTHROPIC_API_KEY='test_key')
    def test_convert_to_fhir_basic(self):
        """Test basic FHIR conversion functionality"""
        from .services import DocumentAnalyzer
        
        # Mock successful client initialization
        mock_client = MagicMock()
        self.mock_anthropic.Client.return_value = mock_client
        
        analyzer = DocumentAnalyzer()
        
        # Test fields
        test_fields = [
            {"label": "Patient Name", "value": "John Smith", "confidence": 0.95},
            {"label": "Date of Birth", "value": "1980-01-15", "confidence": 0.98},
            {"label": "Primary Diagnosis", "value": "Hypertension", "confidence": 0.85}
        ]
        
        fhir_result = analyzer.convert_to_fhir(test_fields)
        
        self.assertEqual(fhir_result['resourceType'], 'Bundle')
        self.assertEqual(fhir_result['type'], 'collection')
        self.assertIn('timestamp', fhir_result)
        self.assertEqual(len(fhir_result['entry']), 1)
        self.assertEqual(fhir_result['entry'][0]['resource']['resourceType'], 'DocumentReference')
    
    @override_settings(ANTHROPIC_API_KEY='test_key')
    def test_chunk_document_logic(self):
        """Test document chunking logic"""
        from .services import DocumentAnalyzer
        
        # Mock successful client initialization
        mock_client = MagicMock()
        self.mock_anthropic.Client.return_value = mock_client
        
        analyzer = DocumentAnalyzer()
        
        # Test small document (no chunking)
        small_content = "Short medical report"
        chunks = analyzer._chunk_document(small_content)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], small_content)
        
        # Test large document (should chunk)
        large_content = "Medical Section\n\n\n" * 1000  # Large enough to trigger chunking
        chunks = analyzer._chunk_document(large_content)
        self.assertGreater(len(chunks), 1)
        
        # Verify all chunks are within size limits
        for chunk in chunks:
            self.assertLessEqual(len(chunk), analyzer.chunk_size)
    
    @override_settings(ANTHROPIC_API_KEY='test_key')
    def test_merge_chunk_fields_deduplication(self):
        """Test field merging and deduplication from multiple chunks"""
        from .services import DocumentAnalyzer
        
        # Mock successful client initialization
        mock_client = MagicMock()
        self.mock_anthropic.Client.return_value = mock_client
        
        analyzer = DocumentAnalyzer()
        
        # Test fields from multiple chunks with duplicates
        all_fields = [
            {"label": "Patient Name", "value": "John Smith", "confidence": 0.95, "source_chunk": 1},
            {"label": "patient name", "value": "John Smith", "confidence": 0.90, "source_chunk": 2},  # Duplicate (case-insensitive)
            {"label": "Date of Birth", "value": "1980-01-15", "confidence": 0.98, "source_chunk": 1},
            {"label": "Primary Diagnosis", "value": "Hypertension", "confidence": 0.85, "source_chunk": 3}
        ]
        
        merged_fields = analyzer._merge_chunk_fields(all_fields)
        
        # Should have 3 unique fields (patient name deduplicated)
        self.assertEqual(len(merged_fields), 3)
        
        # Find the patient name field
        patient_name_field = next(f for f in merged_fields if f['label'].lower() == 'patient name')
        
        # Should keep the higher confidence version
        self.assertEqual(patient_name_field['confidence'], 0.95)
        self.assertIn('merged_from_chunks', patient_name_field)
        self.assertEqual(patient_name_field['merged_from_chunks'], [1, 2])
    
    @override_settings(ANTHROPIC_API_KEY='test_key')
    def test_medical_extraction_prompt_generation(self):
        """Test medical extraction prompt generation"""
        from .services import DocumentAnalyzer
        
        # Mock successful client initialization
        mock_client = MagicMock()
        self.mock_anthropic.Client.return_value = mock_client
        
        analyzer = DocumentAnalyzer()
        
        # Test base prompt
        base_prompt = analyzer._get_medical_extraction_prompt()
        self.assertIn('MediExtract', base_prompt)
        self.assertIn('JSON array', base_prompt)
        self.assertIn('Patient demographics', base_prompt)
        
        # Test prompt with context
        context_prompt = analyzer._get_medical_extraction_prompt(context="Emergency Department")
        self.assertIn('Emergency Department', context_prompt)
        self.assertIn('MediExtract', context_prompt)


class ResponseParserTests(TestCase):
    """
    Test the multi-strategy response parser for AI responses.
    
    Like testing all the tools in the garage to make sure they work
    when you need them most.
    """
    
    def setUp(self):
        """Set up the response parser for testing"""
        from .services import ResponseParser
        self.parser = ResponseParser()
    
    def test_strategy_1_direct_json(self):
        """Test Strategy 1: Direct JSON parsing"""
        # Valid JSON object
        json_response = '{"patientName": "Smith, John", "dateOfBirth": "01/15/1980"}'
        
        result = self.parser.extract_structured_data(json_response)
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['label'], 'patientName')
        self.assertEqual(result[0]['value'], 'Smith, John')
        self.assertEqual(result[1]['label'], 'dateOfBirth')
        self.assertEqual(result[1]['value'], '01/15/1980')
    
    def test_strategy_2_sanitized_json(self):
        """Test Strategy 2: Sanitized JSON parsing with markdown blocks"""
        # JSON wrapped in markdown code blocks
        markdown_response = '''```json
        {
            "patientName": "Doe, Jane",
            "age": "45",
            "sex": "Female"
        }
        ```'''
        
        result = self.parser.extract_structured_data(markdown_response)
        
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['label'], 'patientName')
        self.assertEqual(result[0]['value'], 'Doe, Jane')
        self.assertEqual(result[2]['label'], 'sex')
        self.assertEqual(result[2]['value'], 'Female')
    
    def test_strategy_3_code_block_extraction(self):
        """Test Strategy 3: Extract JSON from markdown code blocks"""
        # JSON in code block with extra text
        code_block_response = '''
        Here's the extracted data:
        
        ```json
        {"medicalRecordNumber": "12345", "diagnosis": "Hypertension"}
        ```
        
        That's all I found.
        '''
        
        result = self.parser.extract_structured_data(code_block_response)
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['label'], 'medicalRecordNumber')
        self.assertEqual(result[0]['value'], '12345')
        self.assertEqual(result[1]['label'], 'diagnosis')
        self.assertEqual(result[1]['value'], 'Hypertension')
    
    def test_strategy_4_regex_patterns(self):
        """Test Strategy 4: Regex key-value extraction"""
        # Non-JSON text with key-value patterns
        text_response = '''
        Patient Name: Wilson, Robert
        Date of Birth: 03/22/1975
        Gender: Male
        Medical Record: 67890
        '''
        
        result = self.parser.extract_structured_data(text_response)
        
        self.assertGreaterEqual(len(result), 3)
        # Find patient name field
        name_field = next((f for f in result if 'Patient Name' in f['label']), None)
        self.assertIsNotNone(name_field)
        self.assertEqual(name_field['value'], 'Wilson, Robert')
        self.assertEqual(name_field['confidence'], 0.7)  # Regex confidence
    
    def test_strategy_5_medical_patterns(self):
        """Test Strategy 5: Medical pattern recognition fallback"""
        # Medical document text without clear key-value structure (forces medical patterns)
        medical_text = '''
        This medical record is for patient Johnson, Mary. The patient was born on 12/05/1990. 
        Patient gender is Female. MRN 98765 was assigned. The patient is 33 years old.
        
        Drug allergies include Penicillin and Latex per patient report.
        
        Current medications include Lisinopril 10mg daily as prescribed.
        
        PREOPERATIVE DIAGNOSIS shows Appendicitis requiring surgical intervention.
        '''
        
        result = self.parser.extract_structured_data(medical_text)
        
        self.assertGreaterEqual(len(result), 5)
        
        # Check for patient name
        name_field = next((f for f in result if f['label'] == 'patientName'), None)
        self.assertIsNotNone(name_field)
        self.assertTrue('johnson' in name_field['value'].lower() and 'mary' in name_field['value'].lower())
        
        # Check for date of birth
        dob_field = next((f for f in result if f['label'] == 'dateOfBirth'), None)
        self.assertIsNotNone(dob_field)
        self.assertEqual(dob_field['value'], '12/05/1990')
        
        # Check for sex
        sex_field = next((f for f in result if f['label'] == 'sex'), None)
        self.assertIsNotNone(sex_field)
        self.assertEqual(sex_field['value'], 'Female')
        
        # Check for allergies
        allergy_field = next((f for f in result if f['label'] == 'allergies'), None)
        self.assertIsNotNone(allergy_field)
        self.assertIn('Penicillin', str(allergy_field['value']))
    
    def test_nested_json_with_confidence(self):
        """Test parsing JSON with nested value/confidence structure"""
        nested_json = '''{
            "patientName": {"value": "Brown, David", "confidence": 0.95},
            "age": {"value": "42", "confidence": 0.88}
        }'''
        
        result = self.parser.extract_structured_data(nested_json)
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['value'], 'Brown, David')
        self.assertEqual(result[0]['confidence'], 0.95)
        self.assertEqual(result[1]['value'], '42')
        self.assertEqual(result[1]['confidence'], 0.88)
    
    def test_malformed_json_fallback(self):
        """Test that malformed JSON falls back to regex parsing"""
        malformed_json = '''{
            "patientName": "Garcia, Maria",
            "dateOfBirth": "08/10/1985"
            // Missing closing brace and has comment
        Patient Name: Garcia, Maria
        Date of Birth: 08/10/1985'''
        
        result = self.parser.extract_structured_data(malformed_json)
        
        # Should fall back to regex patterns and still find some data
        self.assertGreater(len(result), 0)
        # At least one field should have lower confidence (regex extraction)
        confidences = [f.get('confidence', 0) for f in result]
        self.assertTrue(any(conf <= 0.8 for conf in confidences))
    
    def test_empty_response_handling(self):
        """Test handling of empty or minimal responses"""
        empty_response = ""
        
        result = self.parser.extract_structured_data(empty_response)
        
        # Should return empty list for completely empty response
        self.assertEqual(len(result), 0)
    
    def test_field_validation(self):
        """Test field validation functionality"""
        # Good fields
        good_fields = [
            {"id": "1", "label": "patientName", "value": "Smith, John", "confidence": 0.9},
            {"id": "2", "label": "dateOfBirth", "value": "01/15/1980", "confidence": 0.95},
            {"id": "3", "label": "medicalRecordNumber", "value": "12345", "confidence": 0.9}
        ]
        
        validation = self.parser.validate_parsed_fields(good_fields)
        
        self.assertTrue(validation['is_valid'])
        self.assertEqual(validation['field_count'], 3)
        self.assertGreater(validation['avg_confidence'], 0.9)
        self.assertEqual(len(validation['required_fields_present']), 3)
        self.assertEqual(len(validation['issues']), 0)
    
    def test_low_quality_field_validation(self):
        """Test validation with low quality fields"""
        # Low confidence fields
        poor_fields = [
            {"id": "1", "label": "unknown", "value": "unclear", "confidence": 0.3},
            {"id": "2", "label": "maybe", "value": "possibly", "confidence": 0.2}
        ]
        
        validation = self.parser.validate_parsed_fields(poor_fields)
        
        # Should flag issues due to low confidence and missing required fields
        self.assertGreater(len(validation['issues']), 0)
        self.assertEqual(validation['field_count'], 2)
        self.assertLess(validation['avg_confidence'], 0.5)
        self.assertEqual(len(validation['required_fields_present']), 0)
        self.assertGreater(len(validation['issues']), 0)
    
    def test_extract_diagnoses(self):
        """Test diagnosis extraction from medical text"""
        diagnosis_text = '''
        PROBLEM LIST
        Problem Name: Type 2 Diabetes Mellitus
        Life Cycle Status: Active
        
        Problem Name: Hypertension
        Life Cycle Status: Active
        
        PREOPERATIVE DIAGNOSIS: Acute appendicitis
        POSTOPERATIVE DIAGNOSIS: Acute appendicitis with perforation
        '''
        
        diagnoses = self.parser._extract_diagnoses(diagnosis_text)
        
        self.assertIsNotNone(diagnoses)
        self.assertIsInstance(diagnoses, list)
        self.assertGreaterEqual(len(diagnoses), 2)
        
        # Check for problem list entries (case insensitive)
        diabetes_found = any('diabetes' in diag.lower() for diag in diagnoses)
        self.assertTrue(diabetes_found)
        
        # Check for preop/postop diagnoses
        preop_found = any('Preoperative' in diag for diag in diagnoses)
        self.assertTrue(preop_found)
    
    def test_extract_medications(self):
        """Test medication extraction from medical text"""
        medication_text = '''
        Medication Name: Metformin HCl
        Ingredients: Metformin hydrochloride 500mg
        
        Current Medications: Lisinopril 10mg daily, Atorvastatin 20mg nightly
        '''
        
        medications = self.parser._extract_medications(medication_text)
        
        self.assertIsNotNone(medications)
        self.assertIsInstance(medications, list)
        self.assertGreater(len(medications), 1)
        
        # Check for medication entries
        metformin_found = any('Metformin' in med for med in medications)
        self.assertTrue(metformin_found)
    
    def test_extract_allergies(self):
        """Test allergy extraction from medical text"""
        allergy_text = '''
        ALLERGIES: Penicillin, Sulfa drugs, Shellfish
        Known Allergies: None
        Drug Allergies: NKDA
        '''
        
        # Test with actual allergies
        allergies = self.parser._extract_allergies(allergy_text)
        
        self.assertIsNotNone(allergies)
        self.assertIsInstance(allergies, list)
        self.assertIn('Penicillin', allergies)
        self.assertIn('Sulfa drugs', allergies)
        self.assertIn('Shellfish', allergies)
    
    def test_convert_json_to_fields(self):
        """Test JSON to fields conversion"""
        test_data = {
            "patientName": "Test, Patient",
            "age": 45,
            "active": True,
            "notes": None
        }
        
        fields = self.parser._convert_json_to_fields(test_data)
        
        self.assertEqual(len(fields), 4)
        
        # Check string conversion
        name_field = fields[0]
        self.assertEqual(name_field['label'], 'patientName')
        self.assertEqual(name_field['value'], 'Test, Patient')
        
        # Check number conversion
        age_field = next(f for f in fields if f['label'] == 'age')
        self.assertEqual(age_field['value'], '45')
        
        # Check None handling
        notes_field = next(f for f in fields if f['label'] == 'notes')
        self.assertEqual(notes_field['value'], '')
    
    def test_integration_with_document_analyzer(self):
        """Test that ResponseParser integrates properly with DocumentAnalyzer"""
        from .services import DocumentAnalyzer
        
        # Mock the necessary dependencies for DocumentAnalyzer
        with patch('apps.documents.services.anthropic') as mock_anthropic:
            mock_anthropic.Client.return_value = MagicMock()
            
            # Create analyzer
            analyzer = DocumentAnalyzer(api_key="test-key")
            
            # Test response parsing integration
            test_response = '{"patientName": "Integration, Test", "confidence": 0.9}'
            
            parsed_fields = analyzer._parse_ai_response(test_response)
            
            self.assertIsInstance(parsed_fields, list)
            self.assertGreater(len(parsed_fields), 0)
            
            # Check field structure
            first_field = parsed_fields[0]
            self.assertIn('label', first_field)
            self.assertIn('value', first_field)
            self.assertIn('confidence', first_field)

# Add these test classes at the end of the file

class LargeDocumentChunkingTests(TestCase):
    """
    Test suite for enhanced medical document chunking system.
    
    Like testing a rebuilt transmission - we gotta make sure all the gears
    mesh properly and it shifts smooth under different conditions.
    """
    
    def setUp(self):
        """Set up test environment like preparing a clean workbench."""
        self.analyzer = DocumentAnalyzer()
        
        # Create test medical document content
        self.large_medical_document = self._create_large_medical_document()
        self.medium_medical_document = self._create_medium_medical_document()
        
    def _create_large_medical_document(self) -> str:
        """Create a large medical document for chunking tests."""
        # Create content that will definitely trigger chunking (200K+ characters)
        sections = []
        
        # Patient Demographics Section
        demographics = """
        PATIENT INFORMATION
        ===================
        Patient Name: Johnson, Mary Elizabeth
        Date of Birth: December 5, 1990
        Medical Record Number: MRN-98765
        Gender: Female
        Address: 123 Medical Drive, Health City, HC 12345
        Phone: (555) 123-4567
        Insurance: Blue Cross Blue Shield
        Emergency Contact: John Johnson (spouse) - (555) 987-6543
        """ * 50  # Repeat to make it large
        
        # Diagnosis Section  
        diagnoses = """
        DIAGNOSES AND ASSESSMENTS
        ========================
        Primary Diagnosis: Type 2 Diabetes Mellitus (E11.9)
        Secondary Diagnoses:
        1. Hypertension, essential (I10)
        2. Hyperlipidemia (E78.5)
        3. Obesity, BMI 32.5 (E66.9)
        
        Chief Complaint: Patient presents with increased thirst and frequent urination
        over the past 2 weeks. Reports fatigue and blurred vision episodes.
        
        Assessment: Patient shows signs of poorly controlled diabetes with possible
        diabetic complications. Blood glucose levels elevated. Requires medication
        adjustment and lifestyle counseling.
        """ * 40  # Repeat to make it large
        
        # Medications Section
        medications = """
        CURRENT MEDICATIONS
        ==================
        1. Metformin 1000mg twice daily with meals
        2. Lisinopril 10mg once daily in morning
        3. Atorvastatin 40mg once daily at bedtime
        4. Aspirin 81mg once daily for cardioprotection
        5. Multivitamin once daily
        
        Recent Changes:
        - Increased Metformin from 500mg to 1000mg due to poor glucose control
        - Started Lisinopril for blood pressure management
        - Atorvastatin dose increased from 20mg to 40mg
        
        Allergies: NKDA (No Known Drug Allergies)
        """ * 35  # Repeat to make it large
        
        # Lab Results Section
        lab_results = """
        LABORATORY RESULTS
        =================
        Date: Current Visit
        
        Glucose Panel:
        - Fasting Glucose: 185 mg/dL (High, Normal: 70-100)
        - HbA1c: 8.9% (High, Target: <7.0%)
        - Random Glucose: 245 mg/dL (High)
        
        Lipid Panel:
        - Total Cholesterol: 220 mg/dL (Borderline High)
        - LDL Cholesterol: 145 mg/dL (High, Target: <100)
        - HDL Cholesterol: 38 mg/dL (Low, Target: >40)
        - Triglycerides: 185 mg/dL (Borderline High)
        
        Complete Blood Count:
        - White Blood Cells: 7.2 K/uL (Normal: 4.0-11.0)
        - Red Blood Cells: 4.1 M/uL (Normal: 4.2-5.4)
        - Hemoglobin: 12.8 g/dL (Normal: 12.0-15.5)
        - Hematocrit: 38.5% (Normal: 36.0-46.0)
        - Platelets: 285 K/uL (Normal: 150-450)
        """ * 30  # Repeat to make it large
        
        # Procedures Section
        procedures = """
        PROCEDURES AND TREATMENTS
        ========================
        Current Visit Procedures:
        1. Blood glucose monitoring demonstration
        2. Diabetic foot examination - normal findings
        3. Ophthalmologic referral for diabetic retinopathy screening
        4. Nutritionist consultation scheduled
        
        Previous Procedures:
        - Annual physical examination (3 months ago)
        - Mammogram screening (6 months ago) - normal
        - Colonoscopy screening (2 years ago) - normal
        
        Planned Procedures:
        - Follow-up appointment in 3 months
        - Quarterly HbA1c monitoring
        - Annual comprehensive metabolic panel
        - Annual lipid panel
        """ * 25  # Repeat to make it large
        
        sections = [demographics, diagnoses, medications, lab_results, procedures]
        return '\n\n'.join(sections)
    
    def _create_medium_medical_document(self) -> str:
        """Create a medium-sized medical document (won't trigger chunking)."""
        return """
        PATIENT: Smith, John
        DOB: 01/15/1975
        MRN: 12345
        
        DIAGNOSIS: Hypertension
        MEDICATION: Lisinopril 10mg daily
        
        NOTES: Patient doing well on current regimen.
        Blood pressure well controlled at 128/82.
        Continue current medication.
        """
    
    def test_medical_aware_chunking_triggers_correctly(self):
        """Test that medical-aware chunking triggers for large documents."""
        # This should trigger chunking
        result = self.analyzer.analyze_document(self.large_medical_document)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['processing_method'], 'medical_aware_chunked_document')
        
        # Should have processing summary with chunk details
        self.assertIn('processing_summary', result)
        self.assertGreater(result['processing_summary']['total_chunks'], 1)
        
    def test_single_document_processing_for_small_docs(self):
        """Test that small documents don't trigger chunking."""
        result = self.analyzer.analyze_document(self.medium_medical_document)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['processing_method'], 'single_document')
    
    def test_document_structure_analysis(self):
        """Test medical document structure analysis."""
        structure = self.analyzer._analyze_document_structure(self.large_medical_document)
        
        # Should identify medical sections
        self.assertGreater(len(structure['patient_info_sections']), 0)
        self.assertGreater(len(structure['diagnosis_sections']), 0)
        self.assertGreater(len(structure['medication_sections']), 0)
        self.assertGreater(len(structure['lab_sections']), 0)
        
        # Should find section breaks
        self.assertGreater(len(structure['major_section_breaks']), 0)
        self.assertGreater(len(structure['paragraph_breaks']), 0)
    
    def test_optimal_break_point_selection(self):
        """Test that optimal break points respect medical sections."""
        structure = self.analyzer._analyze_document_structure(self.large_medical_document)
        
        # Test break point selection
        break_point = self.analyzer._find_optimal_break_point(
            self.large_medical_document, 0, 50000, structure
        )
        
        self.assertIsInstance(break_point, int)
        self.assertGreater(break_point, 0)
        self.assertLessEqual(break_point, len(self.large_medical_document))
    
    def test_chunk_metadata_generation(self):
        """Test that chunk metadata is properly generated."""
        test_content = "This is test medical content for chunk metadata testing."
        
        chunk_with_metadata = self.analyzer._add_chunk_metadata(
            test_content, 1, 0, len(test_content), 1000
        )
        
        self.assertIn("MEDICAL DOCUMENT CHUNK 1", chunk_with_metadata)
        self.assertIn("Document Progress:", chunk_with_metadata)
        self.assertIn("Chunk Size:", chunk_with_metadata)
        self.assertIn(test_content, chunk_with_metadata)
    
    def test_progress_tracking_in_large_document_processing(self):
        """Test comprehensive progress tracking during chunk processing."""
        result = self.analyzer.analyze_document(self.large_medical_document)
        
        self.assertTrue(result['success'])
        
        # Check processing summary
        summary = result['processing_summary']
        self.assertIn('total_chunks', summary)
        self.assertIn('successful_chunks', summary)
        self.assertIn('success_rate', summary)
        self.assertIn('total_processing_time_seconds', summary)
        
        # Check chunk details
        self.assertIn('chunk_details', result)
        self.assertGreater(len(result['chunk_details']), 0)
        
        # Each chunk detail should have required fields
        for chunk_detail in result['chunk_details']:
            self.assertIn('chunk_number', chunk_detail)
            self.assertIn('success', chunk_detail)
            self.assertIn('fields_extracted', chunk_detail)
            self.assertIn('processing_time_seconds', chunk_detail)


class MedicalDataDeduplicationTests(TestCase):
    """
    Test suite for medical data deduplication and merging.
    
    Like testing a parts sorting system - we want to make sure
    similar parts get grouped together but different ones stay separate.
    """
    
    def setUp(self):
        """Set up test data for deduplication testing."""
        self.analyzer = DocumentAnalyzer()
        
        # Create test fields with duplicates and variations
        self.test_fields = [
            # Patient demographics (should merge)
            {"label": "Patient Name", "value": "Johnson, Mary", "confidence": 0.9, "source_chunk": 1},
            {"label": "patient name", "value": "Johnson, Mary Elizabeth", "confidence": 0.95, "source_chunk": 2},
            
            # Diagnoses (should keep separate if different)
            {"label": "Primary Diagnosis", "value": "Type 2 Diabetes", "confidence": 0.9, "source_chunk": 1},
            {"label": "Secondary Diagnosis", "value": "Hypertension", "confidence": 0.85, "source_chunk": 1},
            {"label": "Diagnosis", "value": "Type 2 Diabetes Mellitus", "confidence": 0.92, "source_chunk": 2},
            
            # Medications (should merge by drug name)
            {"label": "Medication", "value": "Metformin 500mg twice daily", "confidence": 0.9, "source_chunk": 1},
            {"label": "Current Medication", "value": "Metformin 1000mg twice daily with meals", "confidence": 0.95, "source_chunk": 2},
            {"label": "Medication", "value": "Lisinopril 10mg daily", "confidence": 0.88, "source_chunk": 1},
            
            # Lab results (should keep separate tests)
            {"label": "Glucose Level", "value": "185 mg/dL", "confidence": 0.92, "source_chunk": 1},
            {"label": "Cholesterol", "value": "220 mg/dL", "confidence": 0.89, "source_chunk": 1},
            
            # Dates (should categorize properly)
            {"label": "Date of Birth", "value": "12/05/1990", "confidence": 0.95, "source_chunk": 1},
            {"label": "Visit Date", "value": "03/15/2024", "confidence": 0.90, "source_chunk": 1},
        ]
    
    def test_medical_field_categorization(self):
        """Test that medical fields are categorized correctly."""
        # Test patient demographics
        category = self.analyzer._categorize_medical_field("patient name", "johnson")
        self.assertEqual(category, 'patient_demographics')
        
        # Test diagnoses
        category = self.analyzer._categorize_medical_field("diagnosis", "diabetes")
        self.assertEqual(category, 'diagnoses')
        
        # Test medications
        category = self.analyzer._categorize_medical_field("medication", "metformin")
        self.assertEqual(category, 'medications')
        
        # Test lab results
        category = self.analyzer._categorize_medical_field("glucose level", "185")
        self.assertEqual(category, 'lab_results')
        
        # Test dates
        category = self.analyzer._categorize_medical_field("date of birth", "12/05/1990")
        self.assertEqual(category, 'dates')
    
    def test_patient_demographics_merging(self):
        """Test that patient demographics are merged correctly."""
        demo_fields = [
            {"label": "Patient Name", "value": "Johnson, Mary", "confidence": 0.9},
            {"label": "patient name", "value": "Johnson, Mary Elizabeth", "confidence": 0.95},
            {"label": "Date of Birth", "value": "12/05/1990", "confidence": 0.9},
            {"label": "DOB", "value": "December 5, 1990", "confidence": 0.85},
        ]
        
        merged = self.analyzer._merge_patient_demographics(demo_fields)
        
        # Should have 2 fields (name and DOB)
        self.assertEqual(len(merged), 2)
        
        # Should prefer higher confidence values
        name_field = next(f for f in merged if 'name' in f['label'].lower())
        self.assertIn("Elizabeth", name_field['value'])  # More complete name
    
    def test_diagnosis_merging(self):
        """Test that diagnoses are merged intelligently."""
        diagnosis_fields = [
            {"label": "Primary Diagnosis", "value": "Type 2 Diabetes", "confidence": 0.9},
            {"label": "Diagnosis", "value": "Type 2 Diabetes Mellitus", "confidence": 0.92},
            {"label": "Secondary Diagnosis", "value": "Hypertension", "confidence": 0.85},
        ]
        
        merged = self.analyzer._merge_diagnoses(diagnosis_fields)
        
        # Should have 2 distinct diagnoses
        self.assertEqual(len(merged), 2)
        
        # Should prefer more detailed description
        diabetes_field = next(f for f in merged if 'diabetes' in f['value'].lower())
        self.assertIn("Mellitus", diabetes_field['value'])  # More detailed
    
    def test_medication_merging(self):
        """Test that medications are merged by drug name."""
        med_fields = [
            {"label": "Medication", "value": "Metformin 500mg twice daily", "confidence": 0.9},
            {"label": "Current Medication", "value": "Metformin 1000mg twice daily with meals", "confidence": 0.95},
            {"label": "Medication", "value": "Lisinopril 10mg daily", "confidence": 0.88},
        ]
        
        merged = self.analyzer._merge_medications(med_fields)
        
        # Should have 2 distinct medications
        self.assertEqual(len(merged), 2)
        
        # Should prefer more complete dosage information
        metformin_field = next(f for f in merged if 'metformin' in f['value'].lower())
        self.assertIn("1000mg", metformin_field['value'])  # Updated dosage
        self.assertIn("with meals", metformin_field['value'])  # More detailed
    
    def test_medication_name_extraction(self):
        """Test medication name extraction for grouping."""
        # Test simple medication
        name = self.analyzer._extract_medication_name("Metformin 500mg twice daily")
        self.assertEqual(name, "metformin")
        
        # Test complex medication
        name = self.analyzer._extract_medication_name("Lisinopril 10mg once daily in morning")
        self.assertEqual(name, "lisinopril")
        
        # Test two-word medication
        name = self.analyzer._extract_medication_name("Birth Control pill daily")
        self.assertEqual(name, "birth control")
    
    def test_full_medical_deduplication(self):
        """Test complete medical data deduplication process."""
        deduplicated = self.analyzer._deduplicate_medical_data(self.test_fields)
        
        # Should have fewer fields than input (deduplication occurred)
        self.assertLess(len(deduplicated), len(self.test_fields))
        
        # Should have proper medical importance ordering
        # Patient identifiers should come first
        first_field = deduplicated[0]
        importance = self.analyzer._get_medical_importance(first_field['label'])
        self.assertGreaterEqual(importance, 70)  # High importance
        
        # All fields should have required properties
        for field in deduplicated:
            self.assertIn('label', field)
            self.assertIn('value', field)
            self.assertIn('confidence', field)
    
    def test_medical_importance_scoring(self):
        """Test medical importance scoring for field ordering."""
        # Test patient identifiers (highest)
        score = self.analyzer._get_medical_importance("Patient Name")
        self.assertEqual(score, 100)
        
        score = self.analyzer._get_medical_importance("Medical Record Number")
        self.assertEqual(score, 100)
        
        # Test demographics (high)
        score = self.analyzer._get_medical_importance("Date of Birth")
        self.assertEqual(score, 90)
        
        # Test diagnoses (high)
        score = self.analyzer._get_medical_importance("Primary Diagnosis")
        self.assertEqual(score, 80)
        
        # Test medications (medium-high)
        score = self.analyzer._get_medical_importance("Current Medication")
        self.assertEqual(score, 70)
        
        # Test lab results (medium)
        score = self.analyzer._get_medical_importance("Blood Glucose")
        self.assertEqual(score, 60)
        
        # Test other fields (low)
        score = self.analyzer._get_medical_importance("Random Field")
        self.assertEqual(score, 10)


class ChunkResultReassemblyTests(TestCase):
    """
    Test suite for chunk result reassembly and post-processing.
    
    Like testing the final assembly line - making sure all the parts
    come together properly and the finished product runs smooth.
    """
    
    def setUp(self):
        """Set up test environment for reassembly testing."""
        self.analyzer = DocumentAnalyzer()
        
        # Create test fields from multiple chunks
        self.multi_chunk_fields = [
            # Chunk 1 fields
            {"label": "Patient Name", "value": "Johnson, Mary", "confidence": 0.9, "source_chunk": 1},
            {"label": "Primary Diagnosis", "value": "Diabetes", "confidence": 0.85, "source_chunk": 1},
            
            # Chunk 2 fields (some overlapping)
            {"label": "Patient Name", "value": "Johnson, Mary Elizabeth", "confidence": 0.95, "source_chunk": 2},
            {"label": "Date of Birth", "value": "12/05/1990", "confidence": 0.9, "source_chunk": 2},
            {"label": "Medication", "value": "Metformin 1000mg", "confidence": 0.88, "source_chunk": 2},
            
            # Chunk 3 fields
            {"label": "Secondary Diagnosis", "value": "Hypertension", "confidence": 0.82, "source_chunk": 3},
            {"label": "Blood Pressure", "value": "140/90", "confidence": 0.91, "source_chunk": 3},
        ]
    
    def test_chunk_result_reassembly(self):
        """Test complete chunk result reassembly process."""
        reassembled = self.analyzer._reassemble_chunk_results(self.multi_chunk_fields)
        
        # Should return reassembled fields
        self.assertIsInstance(reassembled, list)
        self.assertGreater(len(reassembled), 0)
        
        # All fields should have reassembly metadata
        for field in reassembled:
            self.assertTrue(field.get('reassembled_from_chunks', False))
            self.assertIn('reassembly_timestamp', field)
            self.assertIn('field_id', field)
            self.assertIn('normalized_value', field)
            self.assertIn('medical_validation', field)
    
    def test_post_processing_adds_required_metadata(self):
        """Test that post-processing adds all required metadata."""
        test_fields = [
            {"label": "Patient Name", "value": "Johnson, Mary", "confidence": 0.9}
        ]
        
        processed = self.analyzer._post_process_medical_fields(test_fields)
        
        self.assertEqual(len(processed), 1)
        field = processed[0]
        
        # Should have all required metadata
        self.assertIn('field_id', field)
        self.assertIn('normalized_value', field)
        self.assertIn('medical_validation', field)
        
        # Field ID should be generated
        self.assertTrue(field['field_id'].startswith('med_field_'))
    
    def test_medical_value_normalization(self):
        """Test medical value normalization."""
        # Test date normalization
        normalized = self.analyzer._normalize_medical_value("DOB: 12/05/1990", "Date of Birth")
        self.assertEqual(normalized, "12/05/1990")
        
        # Test medication normalization
        normalized = self.analyzer._normalize_medical_value("Aspirin 81 mg daily", "Medication")
        self.assertIn("mg", normalized)
        
        # Test diagnosis normalization
        normalized = self.analyzer._normalize_diagnosis_value("1. Type 2 Diabetes")
        self.assertEqual(normalized, "type 2 diabetes")
    
    def test_medical_field_validation(self):
        """Test medical field validation."""
        # Test complete valid field
        validation = self.analyzer._validate_medical_field({
            "label": "Patient Name",
            "value": "Johnson, Mary",
            "confidence": 0.9
        })
        
        self.assertTrue(validation['is_complete'])
        self.assertTrue(validation['has_value'])
        self.assertTrue(validation['confidence_adequate'])
        self.assertEqual(len(validation['warnings']), 0)
        
        # Test incomplete field
        validation = self.analyzer._validate_medical_field({
            "label": "Patient Name",
            "value": "",
            "confidence": 0.3
        })
        
        self.assertFalse(validation['is_complete'])
        self.assertFalse(validation['has_value'])
        self.assertFalse(validation['confidence_adequate'])
        self.assertGreater(len(validation['warnings']), 0)
    
    def test_empty_fields_handling(self):
        """Test that empty field lists are handled gracefully."""
        result = self.analyzer._reassemble_chunk_results([])
        self.assertEqual(result, [])
        
        result = self.analyzer._deduplicate_medical_data([])
        self.assertEqual(result, [])
