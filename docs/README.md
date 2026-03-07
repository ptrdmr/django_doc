# Medical Document Parser — Documentation

**For a concise project overview, see the [root README](../README.md).**

---

## Project Overview

Django 5.0 healthcare platform that transforms medical documents into FHIR-compatible patient histories. HIPAA-compliant with enterprise-grade patient and provider management.

### Technical Stack
- **Backend**: Django 5.0, Django REST Framework
- **Frontend**: htmx, Alpine.js, Tailwind CSS
- **Database**: PostgreSQL with JSONB for FHIR
- **Async**: Redis, Celery
- **Security**: HIPAA compliance, 2FA, field encryption, audit logging

### Platform Capabilities
- Patient management with FHIR integration and audit trails
- Provider directory with NPI validation and specialty filtering
- AI-powered document extraction (95%+ FHIR capture)
- Snippet-based document review, MediExtract prompts
- FHIR R4 resources, merge/conflict resolution, provenance tracking
- Hybrid encryption, RBAC (84 permissions), sub-second medical code search

---

## Documentation Structure

| Section | Contents |
|---------|----------|
| [Architecture](./architecture/) | System design, component interactions, data flow, FHIR modeling |
| [Setup](./setup/) | Environment, database, Docker, requirements |
| [Development](./development/) | Workflow, code standards, testing, task history |
| [Security](./security/) | HIPAA, audit logging, authentication |
| [Deployment](./deployment/) | Production, AWS ([EC2 Day 1](./deployment/aws-ec2-day1.md)) |
| [Database](./database/) | Schema, JSONB, migrations, query optimization |
| [API](./api/) | REST, FHIR endpoints, auth, rate limiting |
| [Testing](./testing/) | Strategy, test data, HIPAA testing |
| [Compliance](./compliance/) | HIPAA docs for auditors, BAA template, incident response |

---

## Current Project Status

### Completed Modules (Summary)

| Module | Description |
|--------|-------------|
| Foundation | 7 Django apps, Docker, PostgreSQL, Celery, 2FA |
| Auth & Dashboard | Email auth, 25+ audit events, WCAG accessibility |
| Patient Management | 2,400+ lines templates, FHIR integration, merge/dedup |
| Provider Management | NPI validation, specialty directory, 1,661+ lines templates |
| FHIR Implementation | 4,150+ lines, 7 resource types, bundle management |
| Document Processing | 13 subtasks, AI extraction, chunking, error recovery |
| FHIR Merge | Conflict detection/resolution, 6,000+ lines |
| HIPAA Security | SSL, password validators, session security |
| Hybrid Encryption | Field encryption, sub-second search |
| RBAC | 84 permissions, role management |
| Provider Invitations | Token-based onboarding, bulk invites |
| FHIR Data Capture | 90%+ capture, metrics tracking |
| Pipeline Refactor | 95%+ capture, Pydantic, 12 subtasks |
| Clinical Dates | Extraction, manual entry, FHIR integration |
| Search-Optimized Fields | Indexed search, <50ms for 10K+ patients |
| Optimistic Concurrency | Auto-merge, quality flagging, 28 subtasks |
| Snippet Review | Text snippet validation (backend complete) |
| Patient Summary Panel | Collapsible side panel on patient detail, JSON + PDF endpoints, localStorage persistence, old Reports flow deprecated |

**Full task breakdown:** [docs/development/task-history.md](./development/task-history.md)

### Upcoming
- Task 7: Reports and Analytics
- Task 8: Advanced Search and Filtering
- Task 9: Integration APIs
- Task 10: Advanced Security Features
- Task 42: AWS Textract OCR (in progress)
- Task 44: Inline Document Upload (patient-hub)

### Platform Statistics
- 21,000+ lines of code
- 95%+ FHIR capture rate
- 25+ audit event types
- 14+ database models
- 20+ templates

---

## Quick Start

```bash
venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver

# Or: docker-compose up --build
```

---

## Support

For development questions or issues, refer to the documentation sections above or the `.taskmaster/` directory for task tracking.
