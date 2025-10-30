I'll create a complete artifact with the fully integrated PRD, including all technical architecture and site flow details:I'll create a complete artifact with the fully integrated PRD:

<artifact identifier="medical-doc-parser-prd-v3-complete" type="text/markdown" title="Medical Document Parser PRD v3.0 - Complete"> # Medical Document Parsing Platform - Product Requirements Document

**Version:** 3.0  
**Date:** June 2025  
**Status:** Final - Solo Developer Edition with Patient/Provider Management  
**Project Type:** Healthcare SaaS Platform  
**Compliance:** HIPAA-compliant  
**Development Model:** Solo Developer with AI Assistance

## Executive Summary

A secure, browser-based solution that transforms unstructured medical documents into FHIR-compliant, actionable data while building comprehensive patient medical histories. The platform creates and maintains patient profiles with cumulative FHIR records and provider profiles, helping small hospices and clinics build a complete view of their patients' medical journey. Each parsed document enriches the patient's history and links to relevant providers.

## 1. Problem Statement

### Current State

- Healthcare facilities have fragmented patient histories across multiple documents
- No unified view of a patient's complete medical journey
- Manual tracking of which providers treated which patients
- 30-60 minutes per document for manual abstraction
- No ability to build comprehensive patient profiles from historical documents

### Target State

- Automated document processing that builds cumulative patient histories
- Single source of truth for each patient's complete medical data
- Provider profiles linked to their patients and documents
- 5-minute processing that adds to existing patient records
- Comprehensive FHIR-compliant patient profiles that grow over time

## 2. Success Metrics

|Metric|Target|Measurement|
|---|---|---|
|Processing Speed|≤5 min/document|Celery task timing|
|Patient Profile Completeness|100% documents linked|Database queries|
|Provider Linkage|100% documents linked to providers|Audit reports|
|FHIR History Accuracy|98%+ cumulative accuracy|Validation testing|
|Data Consolidation|90% reduction in duplicate data|Before/after comparison|
|User Workflow Efficiency|<10 clicks per document|UX metrics|

## 3. User Personas

### Primary: Sarah - Medical Records Coordinator

- **Role:** Manages patient records for 200+ patients at a hospice
- **Goals:** Build complete patient histories, track provider relationships
- **Pain Points:** Scattered records, no unified patient view, manual provider tracking
- **Success:** Can see any patient's complete history in one place

### Secondary Users

- **Dr. James - Medical Director:** Reviews comprehensive patient histories
- **IT Manager:** Manages provider accounts and access
- **Compliance Officer:** Audits patient-provider relationships

## 4. Core User Flows (Based on Site Map)

### 4.1 Login Flow

1. User accesses login page
2. Enters credentials
3. System validates and creates session
4. Redirects to User Home Page (dashboard)

### 4.2 User Home Page (Central Hub)

Dashboard displays:

- Quick stats (patients, providers, documents processed)
- Recent activity feed
- Navigation cards to four main modules:
    - Document Parser
    - Patients & Providers
    - Reports
    - User Account Info

### 4.3 Document Parser Flow

1. User clicks "Document Parser" from home
2. Selects or creates patient profile
3. Uploads PDF document
4. System extracts and displays data
5. User reviews/edits extracted data
6. User links document to provider(s)
7. System adds data to patient's cumulative FHIR record
8. Confirmation of successful addition to patient history

### 4.4 Patients & Providers Flow

1. **Patient Management:**
    
    - View all patients with search/filter
    - Click patient to see complete FHIR history
    - View all documents for a patient
    - Edit patient demographics
    - Export patient's complete FHIR record
2. **Provider Management:**
    
    - View all providers
    - See patients linked to each provider
    - View documents by provider
    - Add/edit provider information

### 4.5 Reports Flow

1. Select report type:
    - Patient summary report
    - Provider activity report
    - Document processing report
2. Configure parameters (date range, filters)
3. Generate and download report

### 4.6 User Account Info Flow

1. View/edit user profile
2. Change password
3. View activity history
4. Manage preferences

## 5. Functional Requirements

### 5.1 Patient Profile Management

- **FR-PAT-001:** Create patient profile with demographics
- **FR-PAT-002:** Maintain cumulative FHIR JSON for each patient
- **FR-PAT-003:** Append new data to existing FHIR record (never overwrite)
- **FR-PAT-004:** Track document history per patient
- **FR-PAT-005:** Merge duplicate patient records
- **FR-PAT-006:** Patient search by name, DOB, MRN
- **FR-PAT-007:** Export complete patient FHIR bundle
- **FR-PAT-008:** View patient timeline/history

### 5.2 Provider Profile Management

- **FR-PROV-001:** Create provider profiles
- **FR-PROV-002:** Link providers to documents
- **FR-PROV-003:** Track patient-provider relationships
- **FR-PROV-004:** Provider search and filtering
- **FR-PROV-005:** View all patients for a provider
- **FR-PROV-006:** Provider directory with specialties

### 5.3 Document Processing (Enhanced)

- **FR-DOC-001:** Accept PDF format (text-based)
- **FR-DOC-002:** Maximum 80 pages per document
- **FR-DOC-003:** Link document to patient (required)
- **FR-DOC-004:** Link document to provider(s) (required)
- **FR-DOC-005:** Extract and append to patient history
- **FR-DOC-006:** Maintain document-patient-provider relationships
- **FR-DOC-007:** Prevent duplicate document uploads

### 5.4 FHIR Data Management

- **FR-FHIR-001:** Cumulative patient FHIR record structure
- **FR-FHIR-002:** Add new resources without overwriting
- **FR-FHIR-003:** Handle resource updates (versioning)
- **FR-FHIR-004:** Deduplicate identical resources
- **FR-FHIR-005:** Maintain resource provenance (which doc it came from)
- **FR-FHIR-006:** Generate patient summary from cumulative data

### 5.5 Core FHIR Resources (Phase 1)

- **FR-FHIR-010:** Patient (master demographics)
- **FR-FHIR-011:** DocumentReference (all documents)
- **FR-FHIR-012:** Condition (cumulative diagnosis list)
- **FR-FHIR-013:** Observation (all labs/vitals over time)
- **FR-FHIR-014:** MedicationStatement (current med list)
- **FR-FHIR-015:** Practitioner (linked providers)

### 5.6 Navigation & UI Structure

- **FR-NAV-001:** User Home Page with four module cards
- **FR-NAV-002:** Consistent breadcrumb navigation
- **FR-NAV-003:** Quick patient search from any page
- **FR-NAV-004:** Return to home from any module
- **FR-NAV-005:** Module-specific navigation within each section

### 5.7 Reports Module

- **FR-REP-001:** Patient history summary report
- **FR-REP-002:** Provider patient list report
- **FR-REP-003:** Document processing audit report
- **FR-REP-004:** Export reports as PDF
- **FR-REP-005:** Date range filtering for all reports

## 6. Database Schema (Updated)

```sql
-- Core tables with relationships
patients (
  id, mrn, first_name, last_name, dob, 
  cumulative_fhir_json, -- Complete FHIR history
  created_at, updated_at
)

providers (
  id, npi, first_name, last_name, 
  specialty, organization,
  created_at, updated_at  
)

documents (
  id, patient_id, filename, status,
  uploaded_at, uploaded_by,
  processed_at, original_text
)

document_providers (
  document_id, provider_id,
  relationship_type -- attending, consulting, etc
)

parsed_data (
  id, document_id, patient_id,
  extraction_json, fhir_delta_json, -- What this doc added
  merged_at -- When added to patient record
)

patient_history (
  id, patient_id, document_id,
  action, fhir_version,
  changed_at, changed_by
)
```

## 7. Technical Architecture

### 7.1 Technology Stack

|Component|Technology|Justification|
|---|---|---|
|Backend Framework|Django 5.0 + DRF|Mature, batteries included, excellent ORM|
|Frontend|htmx + Alpine.js|Simple, no build process, server-side rendering|
|Styling|Tailwind CSS|Rapid UI development, utility-first|
|Database|PostgreSQL 15 + JSONB|Native JSON support for FHIR storage|
|Cache/Queue|Redis + Celery|Async document processing|
|AI/ML Primary|Claude 4 Sonnet|Superior medical text understanding|
|AI/ML Fallback|GPT-3.5-Turbo|Cost-effective backup|
|PDF Processing|pdfplumber|Reliable text extraction|
|Container|Docker Compose|Consistent development environment|
|Development IDE|VS Code + Cursor|AI-assisted coding|
|Version Control|Git + GitHub|Code management|
|Testing|pytest + Django tests|Comprehensive testing|
|Monitoring|Django Debug Toolbar|Development profiling|

### 7.2 Architecture Diagram

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Browser   │────▶│  Django/htmx │────▶│ PostgreSQL  │
│  (Tailwind) │     │   (Gunicorn) │     │   (JSONB)   │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
                    ┌──────▼───────┐
                    │    Celery    │
                    │   (1 worker)  │
                    └──────┬───────┘
                           │
                ┌──────────┼──────────┐
                │                     │
          ┌─────▼─────┐         ┌────▼────┐
          │ Claude 4  │         │ GPT-3.5 │
          │    API    │         │   API   │
          └───────────┘         └─────────┘
```

### 7.3 Site Flow Architecture (Visual Representation)

```
                        ┌─────────────────┐
                        │   Login Page    │
                        │                 │
                        └────────┬────────┘
                                │
                                ▼
                        ┌─────────────────┐
                        │ User Home Page  │
                        │  (Dashboard)    │
                        └────────┬────────┘
                                │
        ┌───────────────┬───────┴───────┬──────────────┐
        │               │               │              │
        ▼               ▼               ▼              ▼
┌───────────────┐ ┌──────────────┐ ┌────────────────┐ ┌──────────────┐
│Document Parser│ │   Reports    │ │Patients &      │ │User Account  │
│               │ │              │ │Providers       │ │Info          │
├───────────────┤ ├──────────────┤ ├────────────────┤ ├──────────────┤
│- Upload PDF   │ │- Patient     │ │- Patient List  │ │- Profile     │
│- Link Patient │ │  Summary     │ │- Provider Dir  │ │- Password    │
│- Link Provider│ │- Provider    │ │- View History  │ │- Preferences │
│- Extract Data │ │  Activity    │ │- Manage Links  │ │- Activity    │
│- Update FHIR  │ │- Audit Logs  │ │- Export FHIR   │ │  Log         │
└───────────────┘ └──────────────┘ └────────────────┘ └──────────────┘
```

### 7.4 Django App Structure

```
meddocparser/
├── manage.py
├── requirements.txt
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── meddocparser/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   └── wsgi.py
├── apps/
│   ├── accounts/          # User auth & profiles
│   ├── core/              # Shared utilities
│   ├── documents/         # Document upload/processing
│   ├── patients/          # Patient management
│   ├── providers/         # Provider management
│   ├── fhir/             # FHIR processing
│   └── reports/          # Reporting module
├── static/
│   ├── css/
│   └── js/
├── templates/
│   ├── base.html
│   ├── home.html
│   └── modules/
└── tests/
```

### 7.5 Key Python Dependencies

```python
# requirements.txt
Django==5.0.6
djangorestframework==3.15.1
django-allauth==0.54.0
django-htmx==1.17.0
django-tailwind==3.6.0
psycopg2-binary==2.9.9
redis==5.0.0
celery==5.3.1
pdfplumber==0.10.0
anthropic==0.25.0  # Claude API
openai==1.30.0     # GPT fallback
fhir.resources==7.1.0  # FHIR validation
python-decouple==3.8  # Environment vars
sentry-sdk==1.45.0  # Error tracking
pytest==8.1.0
pytest-django==4.8.0
black==24.3.0  # Code formatting
```

### 7.6 Frontend Stack Details

```javascript
// Alpine.js for interactivity
Alpine.data('documentUpload', () => ({
    uploading: false,
    progress: 0,
    selectedPatient: null,
    selectedProviders: [],
    
    async uploadDocument() {
        this.uploading = true;
        // Handle file upload with progress
    }
}))

// htmx for server interactions
<div hx-post="/api/documents/upload/"
     hx-encoding="multipart/form-data"
     hx-target="#upload-result">
    <!-- Upload form -->
</div>
```

### 7.7 Development Environment

```yaml
# docker-compose.yml
version: '3.8'

services:
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: meddocparser
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine

  web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    volumes:
      - .:/code
    ports:
      - "8000:8000"
    depends_on:
      - db
      - redis
    environment:
      - DEBUG=True
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/meddocparser
      - REDIS_URL=redis://redis:6379

  celery:
    build: .
    command: celery -A meddocparser worker -l info
    volumes:
      - .:/code
    depends_on:
      - db
      - redis
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/meddocparser
      - REDIS_URL=redis://redis:6379

volumes:
  postgres_data:
```

### 7.8 Navigation Implementation

Each module in the site flow is implemented as a Django app with its own URL patterns:

```python
# meddocparser/urls.py
urlpatterns = [
    path('', include('apps.core.urls')),  # Login and home
    path('documents/', include('apps.documents.urls')),  # Document parser
    path('patients-providers/', include('apps.patients.urls')),  # Combined module
    path('reports/', include('apps.reports.urls')),
    path('account/', include('apps.accounts.urls')),
]
```

### 7.9 htmx Navigation Pattern

```html
<!-- base.html navigation -->
<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
    <nav class="bg-blue-600 text-white p-4">
        <div class="container mx-auto flex justify-between">
            <a href="/" class="font-bold">MedDocParser</a>
            {% if user.is_authenticated %}
                <a href="/account/" hx-boost="true">{{ user.email }}</a>
            {% endif %}
        </div>
    </nav>
    
    <main class="container mx-auto my-8">
        {% block content %}{% endblock %}
    </main>
</body>
```

### 7.10 Patient History Architecture

```python
# Cumulative FHIR Pattern
class PatientFHIRManager:
    def add_document_data(self, patient_id, new_fhir_data):
        """Merge new FHIR data into patient's cumulative record"""
        # 1. Get existing patient FHIR bundle
        # 2. Extract new resources from document
        # 3. Merge/append (never overwrite)
        # 4. Update timestamps and provenance
        # 5. Save new cumulative version
        # 6. Log the update in patient_history
```

### 7.11 UI Components for Site Flow

```html
<!-- User Home Page -->
<div class="grid grid-cols-2 gap-6 max-w-4xl mx-auto">
  <!-- Document Parser Card -->
  <div hx-get="/document-parser/" 
       class="card hover:shadow-lg cursor-pointer">
    <h3>Document Parser</h3>
    <p>Upload and process new documents</p>
  </div>
  
  <!-- Patients & Providers Card -->
  <div hx-get="/patients-providers/"
       class="card hover:shadow-lg cursor-pointer">
    <h3>Patients & Providers</h3>
    <p>Manage profiles and relationships</p>
  </div>
  
  <!-- Reports Card -->
  <div hx-get="/reports/"
       class="card hover:shadow-lg cursor-pointer">
    <h3>Reports</h3>
    <p>Generate summaries and exports</p>
  </div>
  
  <!-- Account Card -->
  <div hx-get="/account/"
       class="card hover:shadow-lg cursor-pointer">
    <h3>User Account Info</h3>
    <p>Manage your profile</p>
  </div>
</div>
```

## 8. Updated Implementation Plan

### Week 1-2: Foundation + Navigation

```yaml
Goals: Core structure matching site flow
Tasks:
- Django project with proper app structure
- User authentication (login page)
- User home page with four module cards
- Basic navigation between modules
- Patient and Provider models

Deliverable: Site navigation working per flow diagram
```

### Week 3-4: Patient & Provider Module

```yaml
Goals: Profile management before documents
Tasks:
- Patient CRUD interface
- Provider CRUD interface  
- Patient search/filter
- Provider directory
- Cumulative FHIR JSON structure

Deliverable: Can create/manage patients and providers
```

### Week 5-6: Document Parser Core

```yaml
Goals: Upload with patient/provider linking
Tasks:
- Document upload interface
- Patient selection/creation during upload
- Provider selection/linking
- Claude 4 integration
- Basic extraction

Deliverable: Documents linked to patients/providers
```

### Week 7-8: FHIR Integration

```yaml
Goals: Cumulative patient histories
Tasks:
- FHIR resource extraction
- Merge logic for patient records
- Append without overwriting
- History tracking
- View cumulative patient FHIR

Deliverable: Patient profiles grow with each document
```

### Week 9-10: Reports Module

```yaml
Goals: Basic reporting functionality
Tasks:
- Patient summary reports
- Provider activity reports
- Document audit trail
- PDF generation
- Export functionality

Deliverable: Core reports working
```

### Week 11-12: Polish & Testing

```yaml
Goals: Complete user workflows
Tasks:
- UI/UX improvements
- Patient history timeline view
- Bulk operations
- Performance optimization
- Security hardening

Deliverable: MVP matching site flow
```

## 9. Key Business Rules

### 9.1 Patient History Rules

- **BR-PAT-001:** Never delete or overwrite patient FHIR data
- **BR-PAT-002:** Each document adds to history, never replaces
- **BR-PAT-003:** Patient records are permanent (soft delete only)
- **BR-PAT-004:** Duplicate resources are merged, not duplicated
- **BR-PAT-005:** All changes tracked in audit log

### 9.2 Document Processing Rules

- **BR-DOC-001:** Every document MUST be linked to a patient
- **BR-DOC-002:** Every document MUST have at least one provider
- **BR-DOC-003:** Documents cannot be deleted after processing
- **BR-DOC-004:** Reprocessing appends new data, preserves old

### 9.3 Provider Rules

- **BR-PROV-001:** Providers can be linked to multiple patients
- **BR-PROV-002:** Provider-patient relationships are permanent
- **BR-PROV-003:** Track relationship type (attending, consulting)

## 10. User Interface Updates

### 10.1 Module-Based Navigation

Each module has its own navigation structure:

```
Home
├── Document Parser
│   ├── Upload New
│   ├── Processing Queue
│   └── Recent Uploads
├── Patients & Providers
│   ├── Patient List
│   ├── Provider Directory
│   └── Relationships
├── Reports
│   ├── Patient Summaries
│   ├── Provider Reports
│   └── Audit Logs
└── User Account
    ├── Profile
    ├── Security
    └── Preferences
```

### 10.2 Patient History View

```html
<!-- Patient Timeline -->
<div class="patient-history-timeline">
  <h2>Sarah Johnson - Complete Medical History</h2>
  
  <!-- Cumulative FHIR Summary -->
  <div class="fhir-summary">
    <h3>Current Status</h3>
    <!-- Active conditions, medications, allergies -->
  </div>
  
  <!-- Document Timeline -->
  <div class="timeline">
    <!-- Each document that contributed to history -->
  </div>
  
  <!-- Export Options -->
  <div class="export-actions">
    <button>Export Complete FHIR Bundle</button>
    <button>Generate Summary Report</button>
  </div>
</div>
```

## 11. AI-Assisted Development Strategy

### 11.1 Task Master Configuration

```yaml
# Optimal settings for solo development
project_type: "medical-saas"
complexity: "medium-high"
solo_developer: true
ai_assistance: "maximum"

# Claude 4 for development assistance
primary_model: "claude-opus-4-20250514"
research_model: "perplexity-sonar"
fallback_model: "gpt-3.5-turbo"

# Task breakdown
subtasks_per_task: 3-5
task_size: "2-4 hours"
include_tests: true
```

### 11.2 Daily Workflow

```yaml
Morning (2 hours):
- Review Task Master's next task
- Use Cursor AI for implementation
- Focus on single feature

Afternoon (2 hours):
- Test morning's work
- Fix issues with AI help
- Update documentation

Evening (1 hour):
- Plan next day
- Update task status
- Quick code review
```

### 11.3 AI Prompt Templates

```python
# For new features
"Implement {feature} using Django + htmx. 
Follow patterns in existing code. 
Include error handling and user feedback."

# For debugging
"Debug this error: {error}
Context: {what_user_did}
Expected: {expected_behavior}"

# For FHIR mapping
"Map this medical data to FHIR {resource_type}:
{sample_data}
Follow FHIR R4 specification exactly."
```

## 12. Cost Management

### 12.1 API Usage Estimates

```yaml
Per Document (80 pages):
- Claude 4: ~40k tokens = $0.60-$1.00
- GPT-3.5 Fallback: ~40k tokens = $0.02-$0.04
- Target: <$1.00 per document average

Monthly Estimates (50 docs/day):
- Claude 4: $900-1500
- GPT-3.5: $30-60
- Total API: ~$1000-1500/month
```

### 12.2 Cost Optimization

- Cache all LLM responses
- Use GPT-3.5 for simple extractions
- Implement token counting before API calls
- Daily cost monitoring alerts
- Batch similar extractions

## 13. Risks and Mitigation

|Risk|Probability|Impact|Mitigation|
|---|---|---|---|
|API costs exceed budget|High|High|Strict token limits, aggressive caching|
|Complex medical documents|High|Medium|Focus on common formats first|
|Solo developer burnout|Medium|High|AI assistance, realistic timeline|
|FHIR complexity|Medium|Medium|Phased approach, use libraries|
|PDF parsing failures|Medium|Medium|Multiple extraction methods|

## 14. Definition of Done

### Feature Complete:

- Core functionality implemented
- Basic error handling in place
- Manual testing passed
- Code committed with clear message
- Basic documentation written

### Sprint Complete:

- All planned features working
- No critical bugs
- Updated task status in Task Master
- Quick self-demo recorded

### MVP Complete:

- All core features functional
- Security basics implemented
- Deployment documentation ready
- Test data and demo prepared
- Pilot customer identified

## 15. Development Constraints

### Technical Constraints

- Single developer bandwidth
- Local development only (no cloud initially)
- English documents only
- Text-based PDFs only (no OCR)
- Single organization support

### Simplifications for MVP

- No real-time collaboration
- Basic UI (functional, not beautiful)
- Manual processes acceptable
- No mobile app
- Limited to 10 concurrent users

## 16. Success Criteria (Updated)

### MVP Must Have

- ✓ Site navigation matching flow diagram
- ✓ Patient profiles with cumulative FHIR
- ✓ Provider profiles and linking
- ✓ Document processing adds to patient history
- ✓ Basic reports for patients and providers
- ✓ User account management

### Pilot Success Metrics

- 50 patients with complete histories
- 20 providers properly linked
- 500 documents processed and linked
- Zero data loss or overwrites
- Positive feedback on patient history feature

## 17. Non-Functional Requirements

### 17.1 Performance

- **NFR-PERF-001:** 95% of documents processed in <5 minutes
- **NFR-PERF-002:** Support 10 concurrent users
- **NFR-PERF-003:** Handle 50 documents/day
- **NFR-PERF-004:** Page load time <3 seconds
- **NFR-PERF-005:** Upload feedback within 1 second

### 17.2 Security & Compliance

- **NFR-SEC-001:** HTTPS only (self-signed cert for development)
- **NFR-SEC-002:** Encrypted database fields for PHI
- **NFR-SEC-003:** Basic audit logging
- **NFR-SEC-004:** Secure file storage with access controls
- **NFR-SEC-005:** HIPAA security checklist compliance (not certified)
- **NFR-SEC-006:** No data retention after 30 days (configurable)

### 17.3 Reliability

- **NFR-REL-001:** Graceful error handling with user feedback
- **NFR-REL-002:** Automatic retry for failed LLM calls
- **NFR-REL-003:** Database backups (manual for MVP)
- **NFR-REL-004:** Clear error messages for users

### 17.4 Usability

- **NFR-USE-001:** Mobile-responsive design with Tailwind
- **NFR-USE-002:** Works on Chrome, Firefox, Safari, Edge
- **NFR-USE-003:** Intuitive UI requiring no training
- **NFR-USE-004:** Inline help text and tooltips
- **NFR-USE-005:** Keyboard navigation support

---

## Appendices

### A. Quick Reference

#### Docker Commands

```bash
docker-compose up -d  # Start services
docker-compose logs -f web  # View logs
docker-compose exec web python manage.py shell  # Django shell
```

#### Task Master Commands

```bash
task-master next  # Get next task
task-master list  # View all tasks
task-master complete <id>  # Mark done
```

### B. AI Development Tips

1. Always test AI-generated code immediately
2. Keep prompts specific and contextual
3. Use existing code as examples
4. Don't trust, verify
5. Document why, not just what

### C. FHIR Resource Priority

1. **Must Have:** Patient, DocumentReference, Condition
2. **Should Have:** Observation, MedicationStatement
3. **Nice to Have:** Procedure, AllergyIntolerance, Practitioner
4. **Future:** Encounter, Coverage, Organization

### D. Glossary

- **FHIR:** Fast Healthcare Interoperability Resources
- **PHI:** Protected Health Information
- **MRN:** Medical Record Number
- **EHR:** Electronic Health Record
- **ICD-10:** International Classification of Diseases v10
- **HL7:** Health Level Seven International
- **htmx:** HTML extensions for AJAX functionality
- **Alpine.js:** Lightweight JavaScript framework
- **JSONB:** Binary JSON storage in PostgreSQL

---

**Document Control**

- Version: 3.0 (Complete Solo Developer Edition)
- Last Updated: June 2025
- Development Start: Immediate
- MVP Target: 12 weeks
- Owner: Solo Developer
- AI Assistant: Claude 4 + Cursor
- Document Status: Ready for Task Master ingestion

---

**Key Changes in Version 3.0:**

1. Added comprehensive patient profile management with cumulative FHIR
2. Added provider profile management
3. Restructured UI to match site flow diagram
4. Documents now enhance patient histories rather than standalone processing
5. Added relationship tracking between patients, providers, and documents
6. Implemented proper navigation structure with four main modules
7. Added reports module for patient and provider summaries
8. Included complete technical architecture and implementation details
9. Added detailed technology stack and development environment setup
10. Integrated site flow visual representation with technical implementation

**Ready to Start?**

1. Save this PRD as `.taskmaster/docs/prd.txt`
2. Run `task-master init`
3. Run `task-master parse-prd prd.txt`
4. Begin your journey!

This PRD is optimized for Task Master parsing and solo development with AI assistance. Each section maps to concrete tasks that can be broken down further. The technical architecture fully supports the site flow implementation. Good luck with your project! </artifact>

I've created the complete, integrated PRD v3.0 in the artifact above. This document now includes:

1. **All original content** from the patient/provider management version
2. **Complete technical architecture** (sections 7.1-7.11)
3. **Technology stack details** with specific versions and justifications
4. **Site flow architecture** with visual representation
5. **Django app structure** showing how modules map to the site flow
6. **Development environment setup** with Docker configuration
7. **Frontend implementation details** with htmx and Alpine.js examples
8. **Navigation patterns** matching your site flow diagram

The document is now ready to be saved as `.taskmaster/docs/prd.txt` and ingested by Task Master. Nothing has been removed - only the technical details have been properly integrated into the comprehensive PRD.