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

*Database documentation updated: January 2025 - Task 3.1 Patient Models Complete* 