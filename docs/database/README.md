# 💾 Database Documentation

## Overview

Database schema, models, and query patterns for the Medical Document Parser.

## Current Database Setup

### PostgreSQL Configuration
- PostgreSQL 15+ with JSONB support
- FHIR-specific extensions: uuid-ossp, pg_trgm, btree_gin
- Encrypted field support via django-cryptography

### Development vs Production
- **Development**: SQLite (default) or PostgreSQL (optional)
- **Production**: PostgreSQL with SSL and enhanced security

## Planned Models

### Core Medical Entities
- **Patient**: Demographics, MRN, encrypted PHI data, FHIR bundle
- **Provider**: Healthcare providers, specialties, organizations
- **Document**: Uploaded medical documents, processing status
- **Organization**: Healthcare organizations, HIPAA entities

### FHIR Resources
- **FHIR Bundle**: Cumulative patient FHIR data in JSONB
- **Document Reference**: FHIR references to source documents
- **Provenance**: Data lineage and audit trails

### Audit & Security
- **Audit Log**: HIPAA-compliant access logging
- **User Profile**: Extended user information, organization membership

## JSONB Patterns

### FHIR Data Storage
```json
{
  "resourceType": "Bundle",
  "entry": [
    {
      "resource": {
        "resourceType": "Patient",
        "id": "patient-123",
        "name": [{"given": ["John"], "family": "Doe"}]
      }
    }
  ]
}
```

### Query Optimization
- GIN indexes on JSONB fields for FHIR queries
- Partial indexes for status and organization filtering
- Proper foreign key relationships with appropriate ON DELETE behavior

---

*Database documentation will be updated as models are implemented* 