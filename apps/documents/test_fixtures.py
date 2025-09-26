"""
Test fixtures and utilities for document processing tests.

This module provides reusable test data, mock objects, and utility functions
for testing the document processing pipeline.
"""

import json
import tempfile
from unittest.mock import Mock
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.patients.models import Patient
from apps.providers.models import Provider
from .models import Document, ParsedData
from .services.ai_extraction import (
    StructuredMedicalExtraction,
    MedicalCondition,
    Medication,
    VitalSign,
    LabResult,
    Procedure,
    ProviderInfo,
    SourceContext
)

User = get_user_model()


class MockAIResponses:
    """Mock AI service responses for consistent testing."""
    
    @staticmethod
    def get_claude_structured_response():
        """Mock Claude response for structured extraction."""
        return {
            "conditions": [
                {
                    "condition_name": "Type 2 Diabetes Mellitus",
                    "icd_code": "E11.9",
                    "status": "active",
                    "onset_date": "2020-01-15",
                    "confidence": 0.9,
                    "source_context": {
                        "text": "Type 2 Diabetes Mellitus - Continue Metformin, HbA1c 7.2%",
                        "start_index": 150,
                        "end_index": 200
                    }
                },
                {
                    "condition_name": "Essential Hypertension", 
                    "icd_code": "I10",
                    "status": "active",
                    "confidence": 0.85,
                    "source_context": {
                        "text": "Essential Hypertension - Continue Lisinopril",
                        "start_index": 201,
                        "end_index": 240
                    }
                }
            ],
            "medications": [
                {
                    "medication_name": "Metformin",
                    "dosage": "500mg",
                    "frequency": "twice daily",
                    "route": "oral",
                    "confidence": 0.95,
                    "source_context": {
                        "text": "Metformin 500mg twice daily",
                        "start_index": 75,
                        "end_index": 100
                    }
                },
                {
                    "medication_name": "Lisinopril",
                    "dosage": "10mg",
                    "frequency": "once daily", 
                    "route": "oral",
                    "confidence": 0.9,
                    "source_context": {
                        "text": "Lisinopril 10mg once daily",
                        "start_index": 101,
                        "end_index": 125
                    }
                }
            ],
            "vital_signs": [
                {
                    "vital_type": "blood_pressure",
                    "value": "135/85",
                    "unit": "mmHg",
                    "confidence": 0.95,
                    "source_context": {
                        "text": "Blood Pressure: 135/85 mmHg",
                        "start_index": 126,
                        "end_index": 150
                    }
                },
                {
                    "vital_type": "heart_rate",
                    "value": "78",
                    "unit": "bpm",
                    "confidence": 0.9,
                    "source_context": {
                        "text": "Heart Rate: 78 bpm",
                        "start_index": 151,
                        "end_index": 170
                    }
                }
            ],
            "lab_results": [
                {
                    "test_name": "Glucose",
                    "value": "145",
                    "unit": "mg/dL",
                    "reference_range": "70-100",
                    "status": "High",
                    "confidence": 0.95,
                    "source_context": {
                        "text": "Glucose: 145 mg/dL (High)",
                        "start_index": 300,
                        "end_index": 325
                    }
                },
                {
                    "test_name": "HbA1c",
                    "value": "7.2",
                    "unit": "%",
                    "reference_range": "<7.0",
                    "status": "Elevated",
                    "confidence": 0.9,
                    "source_context": {
                        "text": "HbA1c: 7.2% (Elevated)",
                        "start_index": 326,
                        "end_index": 350
                    }
                }
            ],
            "procedures": [],
            "providers": [
                {
                    "provider_name": "Dr. Jane Smith",
                    "specialty": "Internal Medicine",
                    "confidence": 0.8,
                    "source_context": {
                        "text": "Dr. Jane Smith, Internal Medicine",
                        "start_index": 0,
                        "end_index": 30
                    }
                }
            ]
        }
    
    @staticmethod
    def get_legacy_ai_response():
        """Mock legacy AI response format."""
        return {
            "diagnoses": [
                "Type 2 Diabetes Mellitus",
                "Essential Hypertension"
            ],
            "medications": [
                "Metformin 500mg twice daily",
                "Lisinopril 10mg once daily"
            ],
            "procedures": [],
            "lab_results": [
                {
                    "test": "Glucose",
                    "value": "145 mg/dL",
                    "unit": "mg/dL"
                },
                {
                    "test": "HbA1c", 
                    "value": "7.2%",
                    "unit": "%"
                }
            ]
        }


class TestDocumentContent:
    """Sample medical document content for testing."""
    
    BASIC_MEDICAL_RECORD = b"""
    MEDICAL RECORD
    
    Patient: John Doe
    DOB: 01/15/1980
    MRN: TEST001
    
    CHIEF COMPLAINT:
    Follow-up for diabetes and hypertension
    
    CURRENT MEDICATIONS:
    - Metformin 500mg twice daily
    - Lisinopril 10mg once daily
    - Aspirin 81mg daily
    
    VITAL SIGNS:
    Blood Pressure: 135/85 mmHg
    Heart Rate: 78 bpm
    Temperature: 98.6°F
    Weight: 180 lbs
    
    ASSESSMENT AND PLAN:
    1. Type 2 Diabetes Mellitus - Continue Metformin, HbA1c 7.2%
    2. Essential Hypertension - Continue Lisinopril
    3. Cardiovascular prophylaxis - Continue aspirin
    
    LABORATORY RESULTS:
    Glucose: 145 mg/dL (High)
    HbA1c: 7.2% (Elevated)
    Creatinine: 1.0 mg/dL (Normal)
    """
    
    COMPLEX_MEDICAL_RECORD = b"""
    COMPREHENSIVE MEDICAL EVALUATION
    
    Patient: Sarah Johnson
    DOB: 03/22/1975
    MRN: TEST002
    Date: 2024-09-26
    
    CHIEF COMPLAINT:
    Annual physical examination with multiple chronic conditions management
    
    HISTORY OF PRESENT ILLNESS:
    45-year-old female with history of hypertension, hyperlipidemia, and obesity
    presenting for routine follow-up. Reports good medication compliance.
    
    CURRENT MEDICATIONS:
    - Amlodipine 5mg once daily
    - Atorvastatin 20mg at bedtime
    - Metformin 1000mg twice daily
    - Hydrochlorothiazide 25mg once daily
    
    ALLERGIES:
    Penicillin (rash)
    
    VITAL SIGNS:
    Temperature: 98.4°F
    Blood Pressure: 142/88 mmHg
    Heart Rate: 82 bpm
    Respiratory Rate: 16/min
    Weight: 195 lbs
    Height: 5'6"
    BMI: 31.5 kg/m²
    
    PHYSICAL EXAMINATION:
    General: Alert, oriented, in no acute distress
    HEENT: Normocephalic, atraumatic
    Cardiovascular: Regular rate and rhythm, no murmurs
    Pulmonary: Clear to auscultation bilaterally
    Abdomen: Soft, non-tender, obese
    Extremities: No edema
    
    LABORATORY RESULTS:
    Complete Metabolic Panel:
    - Glucose: 158 mg/dL (High)
    - Creatinine: 0.9 mg/dL (Normal)
    - eGFR: >60 mL/min/1.73m²
    - Sodium: 140 mEq/L (Normal)
    - Potassium: 4.2 mEq/L (Normal)
    
    Lipid Panel:
    - Total Cholesterol: 195 mg/dL
    - LDL: 110 mg/dL (Borderline High)
    - HDL: 42 mg/dL (Low)
    - Triglycerides: 215 mg/dL (High)
    
    Diabetes Monitoring:
    - HbA1c: 8.1% (Poor Control)
    
    ASSESSMENT AND PLAN:
    1. Type 2 Diabetes Mellitus (E11.9) - Poor control
       - Increase Metformin to 1000mg three times daily
       - Consider adding SGLT2 inhibitor
       - Diabetes education referral
       - Follow-up in 3 months
    
    2. Essential Hypertension (I10) - Suboptimal control
       - Continue Amlodipine 5mg daily
       - Continue HCTZ 25mg daily
       - Lifestyle modifications
       - Recheck in 4 weeks
    
    3. Hyperlipidemia (E78.5)
       - Continue Atorvastatin 20mg at bedtime
       - Dietary counseling
       - Recheck lipids in 6 months
    
    4. Obesity (E66.9)
       - Nutrition consultation
       - Exercise program
       - Weight management discussion
    
    PROCEDURES PERFORMED:
    - Routine physical examination
    - Blood pressure measurement
    - Point-of-care glucose testing
    
    FOLLOW-UP:
    - Return in 3 months for diabetes management
    - Blood work in 6 weeks
    - Mammography due
    - Colonoscopy due (age 45)
    """
    
    CORRUPTED_CONTENT = b'\x00\x01\x02\x03CORRUPTED\xFF\xFE\x00INVALID\x00'
    
    MINIMAL_CONTENT = b"Patient name: Test Patient. No other information available."
    
    LARGE_CONTENT_TEMPLATE = """
    EXTENDED MEDICAL RECORD - PAGE {page}
    
    Patient continues to show {condition} with {medication} treatment.
    Vital signs remain stable. Additional notes: {notes}
    
    """


class TestDataFactory:
    """Factory class for creating test data objects."""
    
    @staticmethod
    def create_user(**kwargs):
        """Create a test user with default values."""
        defaults = {
            'username': 'testuser',
            'email': 'test@example.com',
            'password': 'testpass123',
            'first_name': 'Test',
            'last_name': 'User'
        }
        defaults.update(kwargs)
        return User.objects.create_user(**defaults)
    
    @staticmethod
    def create_patient(**kwargs):
        """Create a test patient with default values."""
        defaults = {
            'first_name': 'John',
            'last_name': 'Doe',
            'date_of_birth': '1980-01-15',
            'mrn': 'TEST001',
            'gender': 'M'
        }
        defaults.update(kwargs)
        return Patient.objects.create(**defaults)
    
    @staticmethod
    def create_provider(**kwargs):
        """Create a test provider with default values."""
        defaults = {
            'first_name': 'Dr. Jane',
            'last_name': 'Smith',
            'npi': '1234567890',
            'specialty': 'Internal Medicine'
        }
        defaults.update(kwargs)
        return Provider.objects.create(**defaults)
    
    @staticmethod
    def create_document(patient=None, user=None, content=None, **kwargs):
        """Create a test document with default values."""
        if not patient:
            patient = TestDataFactory.create_patient()
        if not user:
            user = TestDataFactory.create_user()
        if not content:
            content = TestDocumentContent.BASIC_MEDICAL_RECORD
        
        defaults = {
            'filename': 'test_medical_record.pdf',
            'status': 'uploaded',
            'file_size': len(content)
        }
        defaults.update(kwargs)
        
        file_obj = SimpleUploadedFile(
            defaults['filename'],
            content,
            content_type="application/pdf"
        )
        
        return Document.objects.create(
            file=file_obj,
            patient=patient,
            uploaded_by=user,
            **defaults
        )
    
    @staticmethod
    def create_parsed_data(document, structured_data=None, **kwargs):
        """Create test parsed data for a document."""
        if not structured_data:
            structured_data = MockAIResponses.get_claude_structured_response()
        
        defaults = {
            'ai_model_used': 'claude-3-sonnet',
            'processing_time_seconds': 5.2,
            'extraction_confidence': 0.9,
            'structured_data': structured_data
        }
        defaults.update(kwargs)
        
        return ParsedData.objects.create(
            document=document,
            **defaults
        )
    
    @staticmethod
    def create_structured_medical_extraction():
        """Create a StructuredMedicalExtraction object for testing."""
        return StructuredMedicalExtraction(
            conditions=[
                MedicalCondition(
                    condition_name="Type 2 Diabetes Mellitus",
                    icd_code="E11.9",
                    status="active",
                    onset_date="2020-01-15",
                    confidence=0.9,
                    source_context=SourceContext(
                        text="Type 2 Diabetes Mellitus - Continue Metformin",
                        start_index=150,
                        end_index=200
                    )
                ),
                MedicalCondition(
                    condition_name="Essential Hypertension",
                    icd_code="I10", 
                    status="active",
                    confidence=0.85,
                    source_context=SourceContext(
                        text="Essential Hypertension - Continue Lisinopril",
                        start_index=201,
                        end_index=240
                    )
                )
            ],
            medications=[
                Medication(
                    medication_name="Metformin",
                    dosage="500mg",
                    frequency="twice daily",
                    route="oral",
                    confidence=0.95,
                    source_context=SourceContext(
                        text="Metformin 500mg twice daily",
                        start_index=75,
                        end_index=100
                    )
                ),
                Medication(
                    medication_name="Lisinopril",
                    dosage="10mg",
                    frequency="once daily",
                    route="oral",
                    confidence=0.9,
                    source_context=SourceContext(
                        text="Lisinopril 10mg once daily",
                        start_index=101,
                        end_index=125
                    )
                )
            ],
            vital_signs=[
                VitalSign(
                    vital_type="blood_pressure",
                    value="135/85",
                    unit="mmHg",
                    confidence=0.95,
                    source_context=SourceContext(
                        text="Blood Pressure: 135/85 mmHg",
                        start_index=126,
                        end_index=150
                    )
                ),
                VitalSign(
                    vital_type="heart_rate",
                    value="78",
                    unit="bpm",
                    confidence=0.9,
                    source_context=SourceContext(
                        text="Heart Rate: 78 bpm",
                        start_index=151,
                        end_index=170
                    )
                )
            ],
            lab_results=[
                LabResult(
                    test_name="Glucose",
                    value="145",
                    unit="mg/dL",
                    reference_range="70-100",
                    status="High",
                    confidence=0.95,
                    source_context=SourceContext(
                        text="Glucose: 145 mg/dL (High)",
                        start_index=300,
                        end_index=325
                    )
                ),
                LabResult(
                    test_name="HbA1c",
                    value="7.2",
                    unit="%",
                    reference_range="<7.0",
                    status="Elevated",
                    confidence=0.9,
                    source_context=SourceContext(
                        text="HbA1c: 7.2% (Elevated)",
                        start_index=326,
                        end_index=350
                    )
                )
            ],
            procedures=[
                Procedure(
                    procedure_name="Routine Physical Examination",
                    cpt_code="99213",
                    date_performed="2024-09-26",
                    confidence=0.8,
                    source_context=SourceContext(
                        text="Routine physical examination performed",
                        start_index=400,
                        end_index=440
                    )
                )
            ],
            providers=[
                ProviderInfo(
                    provider_name="Dr. Jane Smith",
                    specialty="Internal Medicine",
                    confidence=0.8,
                    source_context=SourceContext(
                        text="Dr. Jane Smith, Internal Medicine",
                        start_index=0,
                        end_index=30
                    )
                )
            ]
        )


class TestAssertions:
    """Custom assertion helpers for testing."""
    
    @staticmethod
    def assert_fhir_resource_valid(resource, resource_type):
        """Assert that a FHIR resource is valid."""
        assert resource.get('resourceType') == resource_type
        assert 'id' in resource
        assert 'subject' in resource
        assert 'reference' in resource['subject']
    
    @staticmethod
    def assert_structured_data_complete(structured_data):
        """Assert that structured medical data is complete."""
        assert isinstance(structured_data, StructuredMedicalExtraction)
        assert len(structured_data.conditions) > 0
        assert len(structured_data.medications) > 0
        assert structured_data.confidence_average > 0
    
    @staticmethod
    def assert_document_processing_success(document):
        """Assert that document processing completed successfully."""
        assert document.status in ['review', 'completed']
        assert hasattr(document, 'parsed_data')
        assert document.parsed_data is not None
        assert document.processed_at is not None
    
    @staticmethod
    def assert_audit_log_exists(action, resource_type, timestamp_after=None):
        """Assert that an audit log entry exists."""
        from apps.core.models import AuditLog
        
        filters = {
            'action': action,
            'resource_type': resource_type
        }
        
        if timestamp_after:
            filters['timestamp__gt'] = timestamp_after
        
        assert AuditLog.objects.filter(**filters).exists()


def create_large_document_content(size_mb):
    """Create document content of approximately specified size in MB."""
    base_content = TestDocumentContent.LARGE_CONTENT_TEMPLATE
    target_size = size_mb * 1024 * 1024  # Convert MB to bytes
    
    content_parts = []
    current_size = 0
    page = 1
    
    while current_size < target_size:
        page_content = base_content.format(
            page=page,
            condition="stable diabetes",
            medication="Metformin",
            notes="Patient continues to respond well to treatment"
        )
        content_parts.append(page_content)
        current_size += len(page_content.encode('utf-8'))
        page += 1
    
    return ''.join(content_parts).encode('utf-8')


def create_mock_fhir_resources(patient_id):
    """Create mock FHIR resources for testing."""
    return [
        {
            'resourceType': 'Condition',
            'id': 'condition-1',
            'code': {'text': 'Type 2 Diabetes Mellitus'},
            'subject': {'reference': f'Patient/{patient_id}'},
            'verificationStatus': {
                'coding': [{
                    'system': 'http://terminology.hl7.org/CodeSystem/condition-ver-status',
                    'code': 'confirmed'
                }]
            }
        },
        {
            'resourceType': 'MedicationStatement',
            'id': 'medication-1',
            'medicationCodeableConcept': {'text': 'Metformin 500mg'},
            'subject': {'reference': f'Patient/{patient_id}'},
            'status': 'active'
        },
        {
            'resourceType': 'Observation',
            'id': 'observation-1',
            'code': {'text': 'Blood Pressure'},
            'subject': {'reference': f'Patient/{patient_id}'},
            'valueQuantity': {'value': 135, 'unit': 'mmHg'}
        }
    ]
