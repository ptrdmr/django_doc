# 🧪 Testing Documentation

## Overview

Testing strategies, frameworks, and procedures for the Medical Document Parser.

## Current Testing Implementation ✅ Working Now

### Testing Packages Currently in Use
- **Django TestCase**: Primary testing framework currently implemented
- **unittest.mock**: Extensive mocking for AI services and external dependencies
- **pytest==8.3.4**: Installed but not yet configured as primary framework
- **pytest-django==4.9.0**: Installed but not yet configured
- **factory-boy==3.3.1**: Installed but not yet implemented
- **coverage==7.6.9**: Code coverage analysis (available but not yet integrated)

### Actual Test Files and Coverage
**Document Processing Tests** (`apps/documents/tests.py` - 978 lines):
- PDFTextExtractorTests: PDF text extraction validation
- DocumentAnalyzerTests: AI service integration testing with mocking
- ResponseParserTests: Multi-strategy JSON parsing from AI responses
- DocumentViewTests: Upload workflow and view testing

**FHIR Resource Tests** (`apps/fhir/tests.py` - 850+ lines):
- PatientResourceTests: FHIR Patient resource generation
- PractitionerResourceTests: Provider FHIR resource handling
- ResourceIntegrationTests: Cross-resource relationship testing
- PatientSummaryTestCase: FHIR bundle generation and management

**FHIR Accumulation Tests** (`apps/fhir/test_accumulator.py` - 93 lines):
- FHIRAccumulator service testing
- Resource conflict resolution testing
- Provenance tracking validation
- FHIR bundle integration testing

**FHIR Bundle Utilities** (`apps/fhir/test_bundle_utils.py` - 522 lines):
- Bundle creation and management
- Resource versioning and deduplication
- Clinical equivalence testing
- Resource validation workflows

**FHIR Merge System Tests** (Task 14 Complete - 280+ Comprehensive Tests):
- **FHIR Conversion Tests** (`apps/fhir/test_fhir_conversion.py`): Specialized converter testing for lab reports, clinical notes, medications, discharge summaries with FHIR validation
- **Conflict Detection Tests** (`apps/fhir/test_conflict_detection.py`): Resource conflict identification with severity assessment and medical safety validation
- **Conflict Resolution Tests** (`apps/fhir/test_conflict_resolution.py`): Strategy-based conflict resolution (newest-wins, preserve-both, confidence-based, manual review)
- **Deduplication Tests** (`apps/fhir/test_deduplication.py`): Hash-based and fuzzy matching for duplicate resource detection with provenance preservation
- **Provenance Tracking Tests** (`apps/fhir/test_provenance.py`): Complete audit trail creation and FHIR Provenance resource management
- **Historical Preservation Tests** (`apps/fhir/test_historical_preservation.py`): Append-only data preservation with version tracking and status transitions
- **Referential Integrity Tests** (`apps/fhir/test_referential_integrity.py`): FHIR resource reference validation and maintenance during merge operations
- **Resource Comparison Tests** (`apps/fhir/test_comparison.py`): Semantic equality, completeness scoring, and structured diff generation utilities
- **Transaction Management Tests** (`apps/fhir/test_transaction_manager.py`): Atomic operations, rollback capabilities, and staging area management
- **Validation Quality Tests** (`apps/fhir/test_validation_quality.py`): Post-merge validation, quality scoring, and automatic correction of minor issues
- **Batch Processing Tests** (`apps/fhir/test_batch_processing.py`): Multi-document processing with relationship detection and concurrent execution
- **Performance Monitoring Tests** (`apps/fhir/test_performance_monitoring.py`): Caching, metrics collection, and performance dashboard functionality
- **Code Systems Tests** (`apps/fhir/test_code_systems.py`): Medical code normalization across LOINC, SNOMED, ICD-10, CPT, and RxNorm systems
- **Configuration Tests** (`apps/fhir/test_configuration.py`): Merge configuration profiles and Django admin interface validation
- **API Tests** (`apps/fhir/test_merge_api.py`): REST API endpoints for FHIR merge operations with authentication and rate limiting

**Document Prompt Tests** (`apps/documents/test_prompts.py` - 206 lines):
- Medical prompt system testing
- Progressive prompt strategy validation
- Confidence scoring algorithms
- AI integration testing

### Current Testing Commands (What Actually Works)
```bash
# Run all tests (Django TestCase approach)
python manage.py test

# Run specific app tests
python manage.py test apps.documents
python manage.py test apps.fhir           # Comprehensive FHIR system testing (280+ tests)
python manage.py test apps.patients

# FHIR Merge System Testing (Task 14 Complete)
python manage.py test apps.fhir.test_fhir_conversion        # FHIR resource conversion
python manage.py test apps.fhir.test_conflict_detection     # Conflict identification  
python manage.py test apps.fhir.test_conflict_resolution    # Resolution strategies
python manage.py test apps.fhir.test_deduplication         # Duplicate detection
python manage.py test apps.fhir.test_provenance            # Audit trail creation
python manage.py test apps.fhir.test_historical_preservation # Data preservation
python manage.py test apps.fhir.test_performance_monitoring # Performance optimization
python manage.py test apps.fhir.test_batch_processing       # Batch operations
python manage.py test apps.fhir.test_merge_api             # API endpoints

# Docker environment testing
docker-compose exec web python manage.py test

# Run with verbose output
python manage.py test --verbosity=2

# Run specific test classes
python manage.py test apps.documents.tests.PDFTextExtractorTests
```

### Real Test Data Patterns Currently Used
```python
# Manual test data creation (current approach)
class DocumentTests(TestCase):
    def setUp(self):
        """Set up test data manually"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            gender='M'
        )

# AI Service Mocking (extensively used)
@patch('apps.documents.services.anthropic')
@patch('apps.documents.services.openai')
def test_ai_processing(self, mock_openai, mock_anthropic):
    # Mock AI responses for testing
    mock_response = MagicMock()
    mock_anthropic.Client.return_value.messages.create.return_value = mock_response
```

## 🚧 Planned Testing Enhancements (Future Implementation)

### Planned pytest Migration
When we migrate to pytest as the primary framework:
- **pytest configuration**: Create pytest.ini with Django settings
- **Test discovery**: Standardize test file naming and structure
- **Fixture system**: Replace setUp methods with pytest fixtures
- **Parametrized testing**: Use pytest.mark.parametrize for data-driven tests

### Planned factory-boy Implementation
Future test data generation approach:
```python
# Example factory pattern (planned, not yet implemented)
class PatientFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Patient
    
    mrn = factory.Sequence(lambda n: f"MRN{n:06d}")
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    date_of_birth = factory.Faker('date_between', start_date='-90y', end_date='-18y')
```

### Planned Coverage Integration
Future coverage workflow:
```bash
# Planned commands (not yet configured)
coverage run --source='.' manage.py test
coverage report
coverage html
```

## Testing Strategy

### Test Types Currently Implemented

**Unit Tests ✅ Working**
- Document processing service testing
- FHIR resource generation testing
- AI response parsing validation
- Database model method testing

**Integration Tests ✅ Working**
- End-to-end document processing workflows
- AI service integration with fallback testing
- FHIR data accumulation and bundle management
- Patient-document-provider relationship testing

**Mocking Strategy ✅ Working**
- Comprehensive AI service mocking (Anthropic Claude, OpenAI GPT)
- File upload and processing simulation
- Database transaction testing
- External API response simulation

### Test Types Planned for Future

**Security Tests 🚧 Planned**
- HIPAA compliance validation
- Access control testing
- Data encryption verification
- Audit logging validation

**Performance Tests 🚧 Planned**
- Database query optimization
- API response time testing
- Document processing benchmarks
- Concurrent user testing

## Test Data Management

### Current HIPAA-Compliant Approach ✅ Working
- **Synthetic Data Only**: All test data is fabricated
- **Manual Creation**: Test data created in setUp methods
- **Immediate Cleanup**: Django TestCase handles automatic cleanup
- **No PHI Exposure**: Test data uses obviously fake information

### Current Test Data Examples (From Real Tests)
```python
# Real example from apps/fhir/test_accumulator.py
self.patient = Patient.objects.create(
    mrn='TEST001',
    first_name='John',
    last_name='Doe',
    date_of_birth='1980-01-01',
    gender='M'
)

# Sample FHIR resource for testing
self.sample_condition_resource = {
    "resourceType": "Condition",
    "id": str(uuid.uuid4()),
    "subject": {"reference": f"Patient/{self.patient.id}"},
    "code": {
        "coding": [{
            "system": "http://snomed.info/sct",
            "code": "233604007",
            "display": "Pneumonia"
        }]
    }
}
```

## Medical Domain Testing ✅ Currently Implemented

### FHIR Resource Testing ✅ Working
- Resource structure validation using fhir.resources library
- FHIR R4 specification compliance testing
- Resource linking and reference validation
- Bundle creation and management testing

### Document Processing Testing ✅ Working
- PDF text extraction accuracy testing with pdfplumber
- AI medical entity recognition with mocked responses
- Multi-strategy response parsing validation
- Error handling and recovery mechanism testing

### AI Integration Testing ✅ Working
- Claude 3 Sonnet API integration with comprehensive mocking
- OpenAI GPT fallback mechanism testing
- Token counting and cost monitoring validation
- Chunking system for large documents

## Security Testing Status

### Currently Implemented ✅ Working
- Input validation testing for document uploads
- File type and size validation testing
- Basic authentication flow testing
- Database model constraint testing

### Security Testing Checklist 🚧 Planned
- [ ] Authentication mechanisms (django-allauth integration)
- [ ] Authorization controls (role-based access)
- [ ] Data encryption validation (django-cryptography)
- [ ] Audit logging verification (HIPAA compliance)
- [ ] Session management testing
- [ ] API rate limiting validation
- [ ] Input validation and sanitization

## Performance Testing 🚧 Planned

### Load Testing Scenarios
- Concurrent document uploads
- Multiple user sessions
- FHIR data retrieval at scale
- Database query optimization

### Benchmark Targets
- API response times < 200ms
- Document processing < 30 seconds
- Database queries < 100ms
- 99% uptime availability

## Quality Metrics

### Note: FHIR Module Refactor (Testing Imports)
- The FHIR services were modularized. Existing tests continue to work via re-exports in `apps/fhir/services.py`.
- For new tests, import directly from dedicated modules to improve clarity:
  - Converters → [apps/fhir/converters.py](mdc:apps/fhir/converters.py)
  - Merge Handlers → [apps/fhir/merge_handlers.py](mdc:apps/fhir/merge_handlers.py)
  - Conflict Detection → [apps/fhir/conflict_detection.py](mdc:apps/fhir/conflict_detection.py)
  - Conflict Resolution → [apps/fhir/conflict_resolution.py](mdc:apps/fhir/conflict_resolution.py)

*Updated: 2025-08-08 07:59:01 | Added testing guidance for FHIR module refactor*
### Current Test Coverage ✅ Working
Based on implemented test files:
- **Document Processing**: Comprehensive coverage with 978 lines of tests
- **FHIR Resources**: Extensive coverage with 850+ lines across multiple files
- **AI Integration**: Complete mocking and integration testing
- **Bundle Management**: Full workflow testing with 522 lines of utilities tests

### Coverage Targets 🚧 Future
- **Minimum**: 80% code coverage
- **Target**: 90% code coverage
- **Critical paths**: 100% coverage (authentication, encryption, audit)

## Test Environment Setup

### Development Testing ✅ Current Commands
```bash
# Activate virtual environment (Windows PowerShell)
venv\Scripts\activate

# Run all tests
python manage.py test

# Run with verbose output
python manage.py test --verbosity=2

# Docker environment
docker-compose exec web python manage.py test
```

### Continuous Integration 🚧 Planned
- Automated test runs on code changes
- Coverage reporting and enforcement
- Security vulnerability scanning
- HIPAA compliance validation

## Test Maintenance

### Current Practices ✅ Working
- Regular test updates with feature development
- Comprehensive mocking for external dependencies
- Clean test data patterns with proper teardown
- Integration testing for document processing workflows

### Planned Improvements 🚧 Future
- pytest migration for better test organization
- factory-boy implementation for consistent test data
- Coverage integration and reporting
- Performance benchmark automation

---

*Updated: 2025-08-08 23:54:02 | Task 14 COMPLETE - Added comprehensive FHIR testing suite with 280+ test cases for merge operations, performance monitoring, and enterprise features* 