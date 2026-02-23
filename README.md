# Medical Document Parser

**HIPAA-compliant healthcare platform** that transforms medical documents into FHIR-compatible patient histories using AI-powered extraction.

## Problem & Solution

Healthcare organizations struggle to digitize legacy medical records and integrate unstructured clinical data into interoperable systems. This platform addresses that by:

- **Extracting** structured medical data from PDFs via AI (Claude/GPT) with 95%+ FHIR resource capture
- **Converting** raw text into FHIR R4 resources (conditions, medications, labs, encounters, etc.)
- **Securing** PHI with field-level encryption, audit logging, and role-based access control

Built for clinical workflows with production-ready error handling, conflict resolution, and compliance tooling.

## Tech Stack

| Layer | Technologies |
|-------|--------------|
| Backend | Django 5.0, Django REST Framework |
| Frontend | htmx, Alpine.js, Tailwind CSS |
| Database | PostgreSQL (JSONB for FHIR) |
| Async | Redis, Celery |
| AI | Anthropic Claude, OpenAI GPT (fallback) |
| Deployment | Docker, Docker Compose |

## Key Achievements

- **95%+ FHIR capture rate** — AI extraction pipeline with Pydantic validation, confidence scoring, and multi-model fallback
- **HIPAA-compliant architecture** — Field encryption (django-cryptography), 25+ audit event types, RBAC with 84 permissions
- **6,000+ lines of FHIR logic** — Merge/conflict resolution, provenance tracking, clinical equivalence engine
- **Production pipeline** — Celery task queue, circuit breaker error recovery, sub-second medical code search (SNOMED, ICD, RxNorm, LOINC)
- **21,000+ lines** of medical software across 7 Django apps

## Quick Start

```bash
# Clone and navigate
cd doc2db_2025_django

# Activate virtual environment (Windows)
venv\Scripts\activate

# Install and run
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver

# Or with Docker
docker-compose up --build
```

## Documentation

Full documentation, architecture diagrams, and task history: **[docs/README.md](docs/README.md)**

- [Architecture](docs/architecture/) — System design, data flow, FHIR modeling
- [Setup](docs/setup/) — Environment, database, Docker
- [Security](docs/security/) — HIPAA, audit logging, encryption
- [Deployment](docs/deployment/) — Production, AWS notes
