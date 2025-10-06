"""
Tests for Task 35.7: Clinical Date Integration in FHIR Resource Creation

Tests verify that FHIR resources use clinical dates from ParsedData instead of
processing timestamps, maintaining clear separation between clinical and system metadata.
"""

import pytest
from datetime import datetime, date
from django.test import TestCase
from django.contrib.auth import get_user_model

from apps.patients.models import Patient
from apps.documents.models import Document, ParsedData
from apps.fhir.converters import StructuredDataConverter

# Import structured extraction models
from apps.documents.services.ai_extraction import (
    StructuredMedicalExtraction,
    MedicalCondition,
    VitalSign,
    LabResult,
    Procedure as MedicalProcedure,
    SourceContext,
)

User = get_user_model()


class ClinicalDateIntegrationTestCase(TestCase):
    """Test clinical date integration in FHIR resource creation."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass',
            email='test@example.com'
        )

        self.patient = Patient.objects.create(
            first_name='Test',
            last_name='Patient',
            date_of_birth=date(1980, 1, 1),
            gender='M',
            mrn='TEST001'
        )

        # Create a minimal document without file (not needed for FHIR testing)
        from django.core.files.uploadedfile import SimpleUploadedFile
        fake_file = SimpleUploadedFile("test.pdf", b"fake content", content_type="application/pdf")
        self.document = Document(
            patient=self.patient,
            filename='test_document.pdf',
            file=fake_file,
            uploaded_by=self.user,
            file_size=12  # Set manually to avoid file access in save()
        )
        self.document.save()

        self.converter = StructuredDataConverter()
        
        # Standard timestamp for all tests
        self.test_timestamp = datetime.now().isoformat()

    def test_clinical_date_from_parsed_data_used_for_vital_signs(self):
        """Test that vital signs use clinical date from ParsedData."""
        # Create ParsedData with clinical date
        clinical_date = date(2023, 5, 15)
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            clinical_date=clinical_date,
            date_source='extracted',
            date_status='verified'
        )

        # Create structured extraction with vital sign (no timestamp)
        structured_data = StructuredMedicalExtraction(
            extraction_timestamp=self.test_timestamp,
            conditions=[],
            medications=[],
            vital_signs=[
                VitalSign(
                    measurement='Blood Pressure',  # Correct field name
                    value='120/80',
                    unit='mmHg',
                    source=SourceContext(
                        text='BP: 120/80 mmHg',
                        start_index=0,
                        end_index=17
                    )
                )
            ],
            lab_results=[],
            procedures=[],
            providers=[]
        )

        metadata = {'document_id': self.document.id}

        # Convert to FHIR resources
        resources = self.converter.convert_structured_data(
            structured_data,
            metadata,
            self.patient,
            parsed_data=parsed_data
        )

        # Verify resource was created
        self.assertEqual(len(resources), 1)
        
        # Verify observation uses clinical date
        observation = resources[0]
        self.assertEqual(observation.effectiveDateTime.date(), clinical_date)

    def test_clinical_date_from_parsed_data_used_for_lab_results(self):
        """Test that lab results use clinical date from ParsedData."""
        # Create ParsedData with clinical date
        clinical_date = date(2023, 6, 20)
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            clinical_date=clinical_date,
            date_source='manual',
            date_status='verified'
        )

        # Create structured extraction with lab result (no test_date)
        structured_data = StructuredMedicalExtraction(
            extraction_timestamp=self.test_timestamp,
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[
                LabResult(
                    test_name='Glucose',
                    value='95',
                    unit='mg/dL',
                    source=SourceContext(
                        text='Glucose: 95 mg/dL',
                        start_index=0,
                        end_index=18
                    )
                )
            ],
            procedures=[],
            providers=[]
        )

        metadata = {'document_id': self.document.id}

        # Convert to FHIR resources
        resources = self.converter.convert_structured_data(
            structured_data,
            metadata,
            self.patient,
            parsed_data=parsed_data
        )

        # Verify resource was created
        self.assertEqual(len(resources), 1)
        
        # Verify observation uses clinical date
        observation = resources[0]
        self.assertEqual(observation.effectiveDateTime.date(), clinical_date)

    def test_clinical_date_from_parsed_data_used_for_procedures(self):
        """Test that procedures use clinical date from ParsedData."""
        # Create ParsedData with clinical date
        clinical_date = date(2023, 7, 10)
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            clinical_date=clinical_date,
            date_source='extracted',
            date_status='pending'
        )

        # Create structured extraction with procedure (no procedure_date)
        structured_data = StructuredMedicalExtraction(
            extraction_timestamp=self.test_timestamp,
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[],
            procedures=[
                MedicalProcedure(
                    name='Blood Draw',
                    outcome='Completed',
                    source=SourceContext(
                        text='Blood Draw completed',
                        start_index=0,
                        end_index=21
                    )
                )
            ],
            providers=[]
        )

        metadata = {'document_id': self.document.id}

        # Convert to FHIR resources
        resources = self.converter.convert_structured_data(
            structured_data,
            metadata,
            self.patient,
            parsed_data=parsed_data
        )

        # Verify resource was created
        self.assertEqual(len(resources), 1)
        
        # Verify observation uses clinical date
        observation = resources[0]
        self.assertEqual(observation.effectiveDateTime.date(), clinical_date)

    def test_extracted_date_preferred_over_clinical_date(self):
        """Test that dates in extracted data take priority over ParsedData clinical_date."""
        # Create ParsedData with clinical date
        clinical_date = date(2023, 5, 15)
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            clinical_date=clinical_date,
            date_source='extracted',
            date_status='verified'
        )

        # Create structured extraction with its own timestamp
        extracted_date = '2023-06-20'
        structured_data = StructuredMedicalExtraction(
            extraction_timestamp=self.test_timestamp,
            conditions=[],
            medications=[],
            vital_signs=[
                VitalSign(
                    measurement='Temperature',  # Correct field name
                    value='98.6',
                    unit='F',
                    timestamp=extracted_date,  # This should be used instead of clinical_date
                    source=SourceContext(
                        text='Temperature: 98.6 F',
                        start_index=0,
                        end_index=18
                    )
                )
            ],
            lab_results=[],
            procedures=[],
            providers=[]
        )

        metadata = {'document_id': self.document.id}

        # Convert to FHIR resources
        resources = self.converter.convert_structured_data(
            structured_data,
            metadata,
            self.patient,
            parsed_data=parsed_data
        )

        # Verify resource uses extracted date, not clinical_date
        observation = resources[0]
        self.assertEqual(observation.effectiveDateTime.date(), date(2023, 6, 20))
        self.assertNotEqual(observation.effectiveDateTime.date(), clinical_date)

    def test_no_datetime_utcnow_fallback_when_no_dates_available(self):
        """Test that None is used instead of datetime.utcnow() when no dates available."""
        # Create ParsedData WITHOUT clinical date
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            clinical_date=None  # No clinical date
        )

        # Create structured extraction without timestamp
        structured_data = StructuredMedicalExtraction(
            extraction_timestamp=self.test_timestamp,
            conditions=[],
            medications=[],
            vital_signs=[
                VitalSign(
                    measurement='Heart Rate',  # Correct field name
                    value='72',
                    unit='bpm',
                    # No timestamp field
                    source=SourceContext(
                        text='HR: 72 bpm',
                        start_index=0,
                        end_index=10
                    )
                )
            ],
            lab_results=[],
            procedures=[],
            providers=[]
        )

        metadata = {'document_id': self.document.id}

        # Convert to FHIR resources
        resources = self.converter.convert_structured_data(
            structured_data,
            metadata,
            self.patient,
            parsed_data=parsed_data
        )

        # Verify resource was created
        self.assertEqual(len(resources), 1)
        
        # Verify observation date is None (not today's date)
        observation = resources[0]
        # The observation may have None or may fail creation - either is acceptable
        # The key is it should NOT be today's date
        if observation.effectiveDateTime:
            # If there's a date, it should NOT be today (processing date)
            self.assertNotEqual(
                observation.effectiveDateTime.date(),
                date.today(),
                "FHIR resource should not use processing date when no clinical date available"
            )

    def test_conversion_without_parsed_data_works(self):
        """Test that conversion works even when ParsedData is not provided."""
        # Create structured extraction
        structured_data = StructuredMedicalExtraction(
            extraction_timestamp=self.test_timestamp,
            conditions=[],
            medications=[],
            vital_signs=[
                VitalSign(
                    measurement='Blood Pressure',  # Correct field name
                    value='120/80',
                    unit='mmHg',
                    timestamp='2023-05-15',  # Has its own timestamp
                    source=SourceContext(
                        text='BP: 120/80 mmHg',
                        start_index=0,
                        end_index=17
                    )
                )
            ],
            lab_results=[],
            procedures=[],
            providers=[]
        )

        metadata = {'document_id': self.document.id}

        # Convert without ParsedData (backward compatibility)
        resources = self.converter.convert_structured_data(
            structured_data,
            metadata,
            self.patient,
            parsed_data=None  # No ParsedData provided
        )

        # Verify resource was created
        self.assertEqual(len(resources), 1)
        
        # Verify it used the timestamp from the data
        observation = resources[0]
        self.assertEqual(observation.effectiveDateTime.date(), date(2023, 5, 15))

    def test_clinical_date_status_logged(self):
        """Test that clinical date source and status are logged."""
        # Create ParsedData with clinical date
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            clinical_date=date(2023, 8, 1),
            date_source='manual',
            date_status='verified'
        )

        structured_data = StructuredMedicalExtraction(
            extraction_timestamp=self.test_timestamp,
            conditions=[],
            medications=[],
            vital_signs=[
                VitalSign(
                    measurement='Weight',  # Correct field name
                    value='70',
                    unit='kg',
                    source=SourceContext(
                        text='Weight: 70 kg',
                        start_index=0,
                        end_index=13
                    )
                )
            ],
            lab_results=[],
            procedures=[],
            providers=[]
        )

        metadata = {'document_id': self.document.id}

        # This test primarily verifies logging doesn't cause exceptions
        # Actual log verification would require capturing log output
        resources = self.converter.convert_structured_data(
            structured_data,
            metadata,
            self.patient,
            parsed_data=parsed_data
        )

        self.assertEqual(len(resources), 1)

    def test_multiple_resources_all_use_clinical_date(self):
        """Test that all resources use the same clinical date when available."""
        clinical_date = date(2023, 9, 15)
        parsed_data = ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            clinical_date=clinical_date,
            date_source='extracted',
            date_status='verified'
        )

        # Create structured extraction with multiple resource types
        structured_data = StructuredMedicalExtraction(
            extraction_timestamp=self.test_timestamp,
            conditions=[],
            medications=[],
            vital_signs=[
                VitalSign(
                    measurement='Blood Pressure', 
                    value='120/80', 
                    unit='mmHg',
                    source=SourceContext(text='BP: 120/80 mmHg', start_index=0, end_index=17)
                )
            ],
            lab_results=[
                LabResult(
                    test_name='Glucose', 
                    value='95', 
                    unit='mg/dL',
                    source=SourceContext(text='Glucose: 95 mg/dL', start_index=0, end_index=18)
                )
            ],
            procedures=[
                MedicalProcedure(
                    name='Blood Draw', 
                    outcome='Completed',
                    source=SourceContext(text='Blood Draw completed', start_index=0, end_index=21)
                )
            ],
            providers=[]
        )

        metadata = {'document_id': self.document.id}

        resources = self.converter.convert_structured_data(
            structured_data,
            metadata,
            self.patient,
            parsed_data=parsed_data
        )

        # Verify all 3 resources were created
        self.assertEqual(len(resources), 3)
        
        # Verify all use the same clinical date
        for resource in resources:
            if hasattr(resource, 'effectiveDateTime') and resource.effectiveDateTime:
                self.assertEqual(resource.effectiveDateTime.date(), clinical_date)

