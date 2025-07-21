# 💾 Database Schema Documentation

## Overview

The Medical Document Parser uses PostgreSQL with JSONB extensions for flexible FHIR data storage while maintaining relational integrity for core medical data.

## Database Design Principles

- **HIPAA Compliance**: All patient data models include audit trails and soft delete
- **FHIR Integration**: JSONB fields store cumulative FHIR bundles with provenance
- **Performance Optimization**: Strategic indexes on frequently queried fields
- **Data Integrity**: Foreign key constraints with PROTECT to prevent data loss
- **Security Ready**: Models designed for future field-level encryption

---

## Core Models

### BaseModel Abstract Class

**Purpose**: Provides consistent audit fields across all medical data models.

```python
class BaseModel(models.Model):
    """Base model with audit fields for all medical data"""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True)
    
    class Meta:
        abstract = True
```

**Usage**: All medical data models inherit from BaseModel to ensure consistent audit tracking.

### MedicalRecord Abstract Class

**Purpose**: Extends BaseModel with soft delete functionality for medical records.

```python
class MedicalRecord(BaseModel):
    """Base for all medical data models with soft delete"""
    deleted_at = models.DateTimeField(null=True, blank=True)
    
    objects = SoftDeleteManager()
    all_objects = models.Manager()
    
    class Meta:
        abstract = True
```

**Key Features**:
- Soft delete prevents accidental loss of medical records
- Dual managers: `objects` (active records) and `all_objects` (including deleted)
- HIPAA compliance through audit trail preservation

---

## Patient Management Models - Task 3.1 ✅

### Patient Model

**Table**: `patients_patient`  
**Purpose**: Core patient demographics and FHIR data storage

```sql
-- Database Schema
CREATE TABLE patients_patient (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mrn VARCHAR(50) UNIQUE NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    date_of_birth DATE NOT NULL,
    gender VARCHAR(20) NOT NULL,
    ssn VARCHAR(11),
    cumulative_fhir_json JSONB DEFAULT '{}',
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by_id INTEGER REFERENCES auth_user(id) ON DELETE PROTECT
);
```

**Indexes**:
```sql
-- Optimized query performance
CREATE UNIQUE INDEX patients_patient_mrn_unique ON patients_patient (mrn);
CREATE INDEX patients_patient_dob_idx ON patients_patient (date_of_birth);
CREATE INDEX patients_patient_name_idx ON patients_patient (last_name, first_name);
CREATE INDEX patients_patient_fhir_gin_idx ON patients_patient USING GIN (cumulative_fhir_json);
CREATE INDEX patients_patient_active_idx ON patients_patient (deleted_at) WHERE deleted_at IS NULL;
```

**Field Details**:
- `id`: UUID primary key for enhanced security and FHIR compatibility
- `mrn`: Medical Record Number - unique identifier for patient
- `first_name`, `last_name`: Patient demographics (ready for encryption)
- `date_of_birth`: Patient DOB for age calculations and filtering
- `gender`: Patient gender with predefined choices
- `ssn`: Social Security Number (optional, ready for encryption)
- `cumulative_fhir_json`: JSONB field storing complete FHIR patient bundle
- `deleted_at`: Soft delete timestamp (NULL = active record)

**Django Model Methods**:
```python
def __str__(self):
    return f"{self.last_name}, {self.first_name} (MRN: {self.mrn})"

def get_absolute_url(self):
    return reverse('patients:detail', kwargs={'pk': self.pk})

def add_fhir_resources(self, new_resources, document_id):
    """Append new FHIR resources without overwriting existing data"""
    # Implementation for cumulative FHIR bundle management
```

### PatientHistory Model

**Table**: `patients_patienthistory`  
**Purpose**: HIPAA-compliant audit trail for all patient data changes

```sql
-- Database Schema
CREATE TABLE patients_patienthistory (
    id SERIAL PRIMARY KEY,
    patient_id UUID NOT NULL REFERENCES patients_patient(id) ON DELETE PROTECT,
    action VARCHAR(50) NOT NULL,
    fhir_version VARCHAR(20) DEFAULT 'R4',
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    changed_by_id INTEGER NOT NULL REFERENCES auth_user(id) ON DELETE PROTECT,
    fhir_delta JSONB DEFAULT '{}',
    notes TEXT
);
```

**Indexes**:
```sql
-- Audit trail query optimization
CREATE INDEX patients_patienthistory_patient_idx ON patients_patienthistory (patient_id, changed_at);
CREATE INDEX patients_patienthistory_user_idx ON patients_patienthistory (changed_by_id, changed_at);
CREATE INDEX patients_patienthistory_action_idx ON patients_patienthistory (action);
```

**Field Details**:
- `patient_id`: Foreign key to Patient (PROTECT prevents deletion)
- `action`: Type of change (created, updated, fhir_append, etc.)
- `fhir_version`: FHIR specification version used
- `changed_at`: Timestamp of the change
- `changed_by_id`: User who made the change
- `fhir_delta`: JSONB field storing the specific changes made
- `notes`: Optional text notes about the change

**Action Choices**:
```python
ACTION_CHOICES = [
    ('created', 'Patient Created'),
    ('updated', 'Patient Updated'),
    ('fhir_append', 'FHIR Data Added'),
    ('document_processed', 'Document Processed'),
    ('manual_edit', 'Manual Edit'),
    ('system_update', 'System Update'),
]
```

---

## JSONB Field Structures

### cumulative_fhir_json Format

The `cumulative_fhir_json` field stores a complete FHIR bundle organized by resource type:

```json
{
    "Patient": [{
        "resourceType": "Patient",
        "id": "patient-uuid",
        "identifier": [{"value": "MRN-12345"}],
        "name": [{"family": "Doe", "given": ["John"]}],
        "meta": {
            "source": "document_123",
            "lastUpdated": "2025-01-20T15:30:00Z",
            "versionId": "uuid-version"
        }
    }],
    "Condition": [{
        "resourceType": "Condition",
        "subject": {"reference": "Patient/patient-uuid"},
        "code": {"coding": [{"code": "E11.9", "display": "Type 2 diabetes"}]},
        "meta": {
            "source": "document_123",
            "lastUpdated": "2025-01-20T15:30:00Z"
        }
    }],
    "Observation": [],
    "MedicationStatement": []
}
```

### fhir_delta Format

The `fhir_delta` field in PatientHistory stores the specific changes:

```json
{
    "added_resources": [{
        "resourceType": "Condition",
        "code": {"coding": [{"code": "I10", "display": "Hypertension"}]}
    }],
    "modified_fields": {
        "first_name": {"old": "Jon", "new": "John"},
        "date_of_birth": {"old": "1980-01-01", "new": "1980-01-02"}
    },
    "source_document": "document_456"
}
```

---

## Query Patterns

### Common Patient Queries

```python
# Active patients only (soft delete aware)
active_patients = Patient.objects.all()  # Uses SoftDeleteManager

# All patients including deleted
all_patients = Patient.all_objects.all()

# Search by MRN
patient = Patient.objects.get(mrn='12345')

# Search by name (ready for encrypted fields)
patients = Patient.objects.filter(
    last_name__icontains='smith',
    first_name__icontains='john'
)

# Patients with specific FHIR condition
diabetic_patients = Patient.objects.filter(
    cumulative_fhir_json__Condition__contains=[{
        'code': {'coding': [{'code': 'E11.9'}]}
    }]
)
```

### Audit Trail Queries

```python
# Patient history for audit
history = PatientHistory.objects.filter(
    patient=patient
).select_related('changed_by').order_by('-changed_at')

# Recent FHIR additions
recent_fhir = PatientHistory.objects.filter(
    action='fhir_append',
    changed_at__gte=timezone.now() - timedelta(days=7)
)
```

---

## Security Considerations

### Current Implementation
- **Soft Delete**: Medical records are never permanently deleted
- **Audit Trails**: Complete change history for HIPAA compliance
- **Foreign Key Protection**: PROTECT prevents accidental cascade deletion
- **UUID Primary Keys**: Enhanced security over sequential integers

### Future Encryption Implementation
The models are designed for easy addition of field-level encryption:

```python
# Future implementation with django-cryptography or similar
first_name = encrypt(models.CharField(max_length=100))
last_name = encrypt(models.CharField(max_length=100))
ssn = encrypt(models.CharField(max_length=11, blank=True))
```

### HIPAA Compliance Features
- Complete audit trails for all patient data access and changes
- Soft delete prevents accidental data loss
- Provenance tracking in FHIR data with source document references
- User attribution for all changes

---

## Migration History

### 0001_initial.py - Patient Models (Task 3.1)
**Applied**: January 2025  
**Description**: Initial Patient and PatientHistory models with FHIR integration

**Tables Created**:
- `patients_patient` with UUID primary key and FHIR JSONB field
- `patients_patienthistory` for audit trail
- Optimized indexes for performance

**Key Features**:
- Soft delete functionality
- FHIR-ready JSONB storage
- Complete audit trail system
- Performance-optimized indexes

---

## Performance Optimization

### Index Strategy
- **GIN Index**: On JSONB fields for fast FHIR queries
- **Composite Indexes**: On frequently queried field combinations
- **Partial Indexes**: On active records (WHERE deleted_at IS NULL)

### Query Optimization Tips
```python
# ✅ DO: Use select_related for foreign keys
patients = Patient.objects.select_related('created_by')

# ✅ DO: Use prefetch_related for reverse relationships
patients = Patient.objects.prefetch_related('history')

# ✅ DO: Filter on indexed fields
patients = Patient.objects.filter(mrn='12345')  # Uses unique index

# ❌ DON'T: Query on non-indexed JSONB paths without GIN index
# This would be slow without proper indexing
```

---

## Provider Management Models - Task 4.1 ✅

### Provider Model

**Table**: `providers_provider`  
**Purpose**: Healthcare provider information with NPI validation and specialty tracking

```sql
-- Database Schema
CREATE TABLE providers_provider (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    npi VARCHAR(10) UNIQUE NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    specialty VARCHAR(100) NOT NULL,
    organization VARCHAR(200) NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by_id INTEGER REFERENCES auth_user(id) ON DELETE PROTECT
);
```

**Indexes**:
```sql
-- Optimized query performance for provider operations
CREATE UNIQUE INDEX providers_provider_npi_unique ON providers_provider (npi);
CREATE INDEX providers_provider_specialty_idx ON providers_provider (specialty);
CREATE INDEX providers_provider_organization_idx ON providers_provider (organization);
CREATE INDEX providers_provider_name_idx ON providers_provider (last_name, first_name);
CREATE INDEX providers_provider_active_idx ON providers_provider (deleted_at) WHERE deleted_at IS NULL;
```

**Field Details**:
- `id`: UUID primary key for enhanced security and FHIR compatibility
- `npi`: National Provider Identifier - 10-digit unique identifier (validated)
- `first_name`, `last_name`: Provider demographics
- `specialty`: Medical specialty (e.g., "Cardiology", "Internal Medicine")
- `organization`: Healthcare organization/practice name
- `deleted_at`: Soft delete timestamp (NULL = active record)

**Django Model Methods**:
```python
def __str__(self):
    return f"Dr. {self.first_name} {self.last_name} ({self.specialty})"

def get_absolute_url(self):
    return reverse('providers:detail', kwargs={'pk': self.pk})

def get_patients(self):
    """Return all patients linked to this provider through documents"""
    # Future implementation when Document model is created
    pass
```

**NPI Validation**:
- Exactly 10 digits required
- Cannot start with 0
- Must be unique across all providers
- Real-time validation in forms

### ProviderHistory Model

**Table**: `providers_providerhistory`  
**Purpose**: HIPAA-compliant audit trail for all provider data changes

```sql
-- Database Schema
CREATE TABLE providers_providerhistory (
    id SERIAL PRIMARY KEY,
    provider_id UUID NOT NULL REFERENCES providers_provider(id) ON DELETE PROTECT,
    action VARCHAR(50) NOT NULL,
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    changed_by_id INTEGER NOT NULL REFERENCES auth_user(id) ON DELETE PROTECT,
    changes JSONB DEFAULT '{}',
    notes TEXT
);
```

**Indexes**:
```sql
-- Audit trail query optimization
CREATE INDEX providers_providerhistory_provider_idx ON providers_providerhistory (provider_id, changed_at);
CREATE INDEX providers_providerhistory_user_idx ON providers_providerhistory (changed_by_id, changed_at);
CREATE INDEX providers_providerhistory_action_idx ON providers_providerhistory (action);
```

**Field Details**:
- `provider_id`: Foreign key to Provider (PROTECT prevents deletion)
- `action`: Type of change (created, updated, npi_changed, etc.)
- `changed_at`: Timestamp of the change
- `changed_by_id`: User who made the change
- `changes`: JSONB field storing the specific field changes
- `notes`: Optional text notes about the change

**Action Choices**:
```python
ACTION_CHOICES = [
    ('created', 'Provider Created'),
    ('updated', 'Provider Updated'),
    ('npi_changed', 'NPI Number Changed'),
    ('specialty_changed', 'Specialty Updated'),
    ('organization_changed', 'Organization Updated'),
    ('manual_edit', 'Manual Edit'),
    ('system_update', 'System Update'),
]
```

---

## FHIR Data Storage Architecture - Task 5 ✅

### FHIR Bundle Management in PostgreSQL

The FHIR data architecture leverages PostgreSQL's advanced JSONB capabilities to store complete FHIR bundles while maintaining relational integrity and query performance.

### JSONB Storage Strategy

**Cumulative Bundle Approach**:
- Each patient has ONE cumulative FHIR bundle in `cumulative_fhir_json`
- New resources are APPENDED, never overwritten
- Complete medical history preserved with provenance tracking
- Optimized for temporal queries and clinical summaries

### FHIR Resource Organization

```json
{
    "bundle_metadata": {
        "id": "bundle-uuid-12345",
        "type": "collection", 
        "timestamp": "2025-01-20T15:30:00Z",
        "total_resources": 25,
        "last_updated": "2025-01-20T15:30:00Z"
    },
    "Patient": [{
        "resourceType": "Patient",
        "id": "patient-uuid",
        "identifier": [{"system": "http://example.org/fhir/mrn", "value": "MRN-12345"}],
        "name": [{"family": "Doe", "given": ["John"]}],
        "birthDate": "1980-01-15",
        "gender": "male",
        "meta": {
            "source": "document_123",
            "lastUpdated": "2025-01-20T15:30:00Z",
            "versionId": "1"
        }
    }],
    "Condition": [{
        "resourceType": "Condition",
        "id": "condition-uuid-1",
        "subject": {"reference": "Patient/patient-uuid"},
        "clinicalStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]
        },
        "code": {
            "coding": [{
                "system": "http://snomed.info/sct",
                "code": "E11.9",
                "display": "Type 2 diabetes mellitus without complications"
            }]
        },
        "onsetDateTime": "2020-03-15T00:00:00Z",
        "meta": {
            "source": "document_123",
            "lastUpdated": "2025-01-20T15:30:00Z",
            "versionId": "1"
        }
    }],
    "MedicationStatement": [{
        "resourceType": "MedicationStatement",
        "id": "medication-uuid-1",
        "subject": {"reference": "Patient/patient-uuid"},
        "status": "active",
        "medicationCodeableConcept": {
            "coding": [{
                "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                "code": "860975",
                "display": "Metformin 500 MG Oral Tablet"
            }]
        },
        "effectiveDateTime": "2020-03-15T00:00:00Z",
        "dosage": [{
            "text": "500 mg twice daily with meals",
            "timing": {"repeat": {"frequency": 2, "period": 1, "periodUnit": "d"}}
        }],
        "meta": {
            "source": "document_123",
            "lastUpdated": "2025-01-20T15:30:00Z",
            "versionId": "1"
        }
    }],
    "Observation": [{
        "resourceType": "Observation",
        "id": "observation-uuid-1",
        "subject": {"reference": "Patient/patient-uuid"},
        "status": "final",
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "laboratory"
            }]
        }],
        "code": {
            "coding": [{
                "system": "http://loinc.org",
                "code": "4548-4", 
                "display": "Hemoglobin A1c"
            }]
        },
        "valueQuantity": {
            "value": 7.2,
            "unit": "%",
            "system": "http://unitsofmeasure.org",
            "code": "%"
        },
        "effectiveDateTime": "2025-01-15T10:30:00Z",
        "meta": {
            "source": "document_456",
            "lastUpdated": "2025-01-20T15:30:00Z",
            "versionId": "1"
        }
    }],
    "DocumentReference": [{
        "resourceType": "DocumentReference",
        "id": "document-uuid-1",
        "subject": {"reference": "Patient/patient-uuid"},
        "status": "current",
        "type": {
            "coding": [{
                "system": "http://loinc.org",
                "code": "34133-9",
                "display": "Summary of episode note"
            }]
        },
        "content": [{
            "attachment": {
                "contentType": "application/pdf",
                "url": "/media/documents/patient_report_123.pdf",
                "title": "Patient Medical Summary - Jan 2025"
            }
        }],
        "date": "2025-01-20T15:30:00Z",
        "meta": {
            "source": "document_123",
            "lastUpdated": "2025-01-20T15:30:00Z",
            "versionId": "1"
        }
    }],
    "Practitioner": [{
        "resourceType": "Practitioner",
        "id": "practitioner-uuid-1",
        "identifier": [{"system": "http://hl7.org/fhir/sid/us-npi", "value": "1234567890"}],
        "name": [{"family": "Smith", "given": ["John"], "prefix": ["Dr."]}],
        "qualification": [{
            "code": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v2-0360",
                    "code": "MD",
                    "display": "Doctor of Medicine"
                }]
            }
        }],
        "meta": {
            "source": "document_123",
            "lastUpdated": "2025-01-20T15:30:00Z",
            "versionId": "1"
        }
    }],
    "Provenance": [{
        "resourceType": "Provenance",
        "id": "provenance-uuid-1",
        "target": [{"reference": "Condition/condition-uuid-1"}],
        "occurredDateTime": "2025-01-20T15:30:00Z",
        "recorded": "2025-01-20T15:30:00Z",
        "agent": [{
            "type": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                    "code": "author"
                }]
            },
            "who": {
                "reference": "Practitioner/practitioner-uuid-1",
                "display": "Dr. John Smith"
            }
        }],
        "entity": [{
            "role": "source",
            "what": {
                "reference": "DocumentReference/document-uuid-1",
                "display": "Source Document: Patient Medical Summary"
            }
        }]
    }]
}
```

### FHIR Query Optimization

**GIN Indexes for JSONB**:
```sql
-- Optimized JSONB queries for FHIR data
CREATE INDEX patients_patient_fhir_gin_idx ON patients_patient USING GIN (cumulative_fhir_json);

-- Resource-specific indexes for common queries
CREATE INDEX patients_fhir_conditions_idx ON patients_patient USING GIN ((cumulative_fhir_json->'Condition'));
CREATE INDEX patients_fhir_medications_idx ON patients_patient USING GIN ((cumulative_fhir_json->'MedicationStatement'));
CREATE INDEX patients_fhir_observations_idx ON patients_patient USING GIN ((cumulative_fhir_json->'Observation'));
```

**Common FHIR Queries**:
```python
# Find patients with specific condition (Type 2 Diabetes)
diabetic_patients = Patient.objects.filter(
    cumulative_fhir_json__Condition__contains=[{
        'code': {'coding': [{'code': 'E11.9'}]}
    }]
)

# Find patients on specific medication (Metformin)
metformin_patients = Patient.objects.filter(
    cumulative_fhir_json__MedicationStatement__contains=[{
        'medicationCodeableConcept': {'coding': [{'code': '860975'}]}
    }]
)

# Find patients with recent lab results
recent_labs = Patient.objects.filter(
    cumulative_fhir_json__Observation__contains=[{
        'category': [{'coding': [{'code': 'laboratory'}]}],
        'effectiveDateTime__gte': '2025-01-01T00:00:00Z'
    }]
)

# Count total FHIR resources for a patient
patient_resource_count = Patient.objects.annotate(
    total_conditions=Cast(
        KeyTextTransform('Condition', 'cumulative_fhir_json'), 
        IntegerField()
    )
).filter(total_conditions__gt=0)
```

### Resource Versioning Schema

**Version Management**:
Each FHIR resource includes metadata for version tracking:

```json
{
    "meta": {
        "source": "document_123",           // Source document ID
        "lastUpdated": "2025-01-20T15:30:00Z",  // Timestamp of last update
        "versionId": "2",                   // Resource version number
        "profile": ["http://hl7.org/fhir/StructureDefinition/Patient"],
        "security": [{
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
            "code": "HTEST"
        }]
    }
}
```

**Deduplication Strategy**:
- Clinical equivalence detection prevents true duplicates
- Similar observations within 1-hour timeframe are updated, not duplicated
- Identical conditions (same SNOMED code) are versioned, not duplicated
- Same medications are updated with status changes

### Provenance Tracking Schema

**Complete Audit Trail**:
Every clinical resource has corresponding Provenance resource:

```json
{
    "resourceType": "Provenance", 
    "target": [{"reference": "Condition/condition-uuid"}],    // What was created/modified
    "occurredDateTime": "2025-01-20T15:30:00Z",              // When it happened
    "recorded": "2025-01-20T15:30:00Z",                      // When it was recorded
    "agent": [{                                               // Who was responsible
        "who": {"reference": "Practitioner/dr-smith-uuid"}
    }],
    "entity": [{                                              // What was the source
        "role": "source",
        "what": {"reference": "DocumentReference/doc-uuid"}
    }]
}
```

---

## Migration History

### 0001_initial.py - Patient Models (Task 3.1)
**Applied**: January 2025  
**Description**: Initial Patient and PatientHistory models with FHIR integration

### 0001_initial.py - Provider Models (Task 4.1) 
**Applied**: January 2025  
**Description**: Provider and ProviderHistory models with NPI validation

**Tables Created**:
- `providers_provider` with UUID primary key and NPI validation
- `providers_providerhistory` for audit trail
- Optimized indexes for provider searches

**Key Features**:
- 10-digit NPI validation and uniqueness
- Specialty and organization tracking
- Soft delete functionality
- Complete audit trail system

### FHIR Bundle Storage Optimization (Task 5)
**Applied**: January 2025  
**Description**: Advanced JSONB indexing for FHIR data

**Indexes Created**:
- GIN indexes on FHIR resource types
- Performance optimization for clinical queries
- Resource-specific query paths

---

## Performance Optimization

### JSONB Query Performance

**Best Practices**:
```python
# ✅ DO: Use GIN indexes for JSONB containment queries
patients = Patient.objects.filter(
    cumulative_fhir_json__Condition__contains=[condition_criteria]
)

# ✅ DO: Use resource-specific paths for targeted queries  
conditions = Patient.objects.filter(
    cumulative_fhir_json__Condition__0__code__coding__0__code='E11.9'
)

# ❌ DON'T: Use deep nested queries without indexes
# This would be slow without proper GIN indexing
```

### Provider Search Optimization

**Efficient Provider Queries**:
```python
# ✅ DO: Use indexed fields for provider searches
providers = Provider.objects.filter(
    specialty__icontains='cardio',  # Uses specialty index
    organization__icontains='mayo'   # Uses organization index
)

# ✅ DO: Combine with name searches on indexed fields
providers = Provider.objects.filter(
    Q(first_name__icontains=query) |
    Q(last_name__icontains=query) |  # Uses name composite index
    Q(npi__icontains=query)          # Uses unique NPI index
)
```

### Audit Trail Query Optimization

**Efficient History Queries**:
```python
# ✅ DO: Use composite indexes for time-based queries
recent_changes = PatientHistory.objects.filter(
    patient=patient,                    # Uses patient+time composite index
    changed_at__gte=last_week
).select_related('changed_by')         # Avoid N+1 queries

# ✅ DO: Use action-based filtering with indexes
fhir_updates = PatientHistory.objects.filter(
    action='fhir_append'               # Uses action index
).order_by('-changed_at')
```

---

*Database documentation updated: January 2025 - Tasks 3.1 (Patient), 4.1 (Provider), 5 (FHIR) Complete* 