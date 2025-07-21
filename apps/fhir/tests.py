"""
Tests for FHIR Resource Models

This module contains comprehensive tests for the custom FHIR resource models
to ensure they work correctly and handle edge cases properly.
"""

from django.test import TestCase
from datetime import datetime, date
from apps.fhir.fhir_models import (
    PatientResource,
    DocumentReferenceResource,
    ConditionResource,
    ObservationResource,
    MedicationStatementResource,
    PractitionerResource
)


class PatientResourceTests(TestCase):
    """Test cases for PatientResource model"""
    
    def test_create_patient_from_demographics(self):
        """Test creating a patient resource from basic demographics"""
        patient = PatientResource.create_from_demographics(
            mrn="12345",
            first_name="John",
            last_name="Doe",
            birth_date=date(1980, 1, 15),
            gender="male",
            phone="555-1234",
            email="john.doe@example.com"
        )
        
        self.assertIsNotNone(patient.id)
        self.assertEqual(patient.get_mrn(), "12345")
        self.assertEqual(patient.get_display_name(), "Doe, John")
        self.assertEqual(patient.gender, "male")
        self.assertEqual(patient.birthDate, "1980-01-15")
        self.assertIsNotNone(patient.meta)
        self.assertEqual(patient.meta.versionId, "1")
    
    def test_create_patient_minimal_info(self):
        """Test creating a patient with minimal required information"""
        patient = PatientResource.create_from_demographics(
            mrn="67890",
            first_name="Jane",
            last_name="Smith",
            birth_date="1990-05-20"
        )
        
        self.assertIsNotNone(patient.id)
        self.assertEqual(patient.get_mrn(), "67890")
        self.assertEqual(patient.get_display_name(), "Smith, Jane")
        self.assertEqual(patient.birthDate, "1990-05-20")
        self.assertIsNone(patient.gender)
    
    def test_patient_display_name_fallback(self):
        """Test patient display name with missing name information"""
        patient = PatientResource(id="test-id")
        self.assertEqual(patient.get_display_name(), "Unknown Patient")
    
    def test_patient_mrn_not_found(self):
        """Test MRN extraction when no MRN identifier exists"""
        patient = PatientResource(id="test-id")
        self.assertIsNone(patient.get_mrn())


class DocumentReferenceResourceTests(TestCase):
    """Test cases for DocumentReferenceResource model"""
    
    def test_create_document_reference(self):
        """Test creating a document reference resource"""
        doc_ref = DocumentReferenceResource.create_from_document(
            patient_id="patient-123",
            document_title="Lab Results",
            document_type="lab-report",
            document_url="/documents/lab-results.pdf",
            author="Dr. Smith"
        )
        
        self.assertIsNotNone(doc_ref.id)
        self.assertEqual(doc_ref.status, "current")
        self.assertEqual(doc_ref.subject["reference"], "Patient/patient-123")
        self.assertEqual(doc_ref.get_document_url(), "/documents/lab-results.pdf")
        self.assertIsNotNone(doc_ref.meta)
        self.assertEqual(doc_ref.meta.versionId, "1")
    
    def test_document_reference_with_creation_date(self):
        """Test document reference with specific creation date"""
        test_date = datetime(2023, 6, 15, 10, 30, 0)
        doc_ref = DocumentReferenceResource.create_from_document(
            patient_id="patient-456",
            document_title="Clinical Note",
            document_type="clinical-note",
            document_url="/documents/note.pdf",
            creation_date=test_date
        )
        
        self.assertEqual(doc_ref.date, "2023-06-15T10:30:00Z")
        self.assertEqual(doc_ref.meta.lastUpdated, "2023-06-15T10:30:00Z")
    
    def test_document_url_extraction_no_content(self):
        """Test URL extraction when no content exists"""
        doc_ref = DocumentReferenceResource(id="test-id")
        self.assertIsNone(doc_ref.get_document_url())


class ConditionResourceTests(TestCase):
    """Test cases for ConditionResource model"""
    
    def test_create_condition_from_diagnosis(self):
        """Test creating a condition resource from diagnosis"""
        condition = ConditionResource.create_from_diagnosis(
            patient_id="patient-123",
            condition_code="E11.9",
            condition_display="Type 2 diabetes mellitus",
            clinical_status="active",
            onset_date=date(2020, 3, 10)
        )
        
        self.assertIsNotNone(condition.id)
        self.assertEqual(condition.subject["reference"], "Patient/patient-123")
        self.assertEqual(condition.get_condition_code(), "E11.9")
        self.assertEqual(condition.get_condition_display(), "Type 2 diabetes mellitus")
        self.assertEqual(condition.onsetDateTime, "2020-03-10")
        self.assertIsNotNone(condition.meta)
    
    def test_condition_with_string_onset_date(self):
        """Test condition with onset date as string"""
        condition = ConditionResource.create_from_diagnosis(
            patient_id="patient-456",
            condition_code="M79.3",
            condition_display="Panniculitis",
            onset_date="2023-01-15"
        )
        
        self.assertEqual(condition.onsetDateTime, "2023-01-15")
    
    def test_condition_code_extraction_no_code(self):
        """Test condition code extraction when no code exists"""
        condition = ConditionResource(id="test-id")
        self.assertIsNone(condition.get_condition_code())
        self.assertIsNone(condition.get_condition_display())


class ObservationResourceTests(TestCase):
    """Test cases for ObservationResource model"""
    
    def test_create_observation_from_lab_result(self):
        """Test creating an observation resource from lab result"""
        observation = ObservationResource.create_from_lab_result(
            patient_id="patient-123",
            test_code="33747-0",
            test_name="Glucose",
            value=95.0,
            unit="mg/dL",
            reference_range="70-99 mg/dL"
        )
        
        self.assertIsNotNone(observation.id)
        self.assertEqual(observation.status, "final")
        self.assertEqual(observation.subject["reference"], "Patient/patient-123")
        self.assertEqual(observation.get_test_name(), "Glucose")
        self.assertEqual(observation.get_value_with_unit(), "95.0 mg/dL")
        self.assertIsNotNone(observation.meta)
    
    def test_observation_with_string_value(self):
        """Test observation with string value"""
        observation = ObservationResource.create_from_lab_result(
            patient_id="patient-456",
            test_code="33747-0",
            test_name="Blood Type",
            value="A+",
            unit=None
        )
        
        self.assertEqual(observation.get_value_with_unit(), "A+")
    
    def test_observation_with_specific_date(self):
        """Test observation with specific observation date"""
        test_date = datetime(2023, 7, 20, 14, 30, 0)
        observation = ObservationResource.create_from_lab_result(
            patient_id="patient-789",
            test_code="2093-3",
            test_name="Cholesterol",
            value=180,
            unit="mg/dL",
            observation_date=test_date
        )
        
        self.assertEqual(observation.effectiveDateTime, "2023-07-20T14:30:00Z")
        self.assertEqual(observation.meta.lastUpdated, "2023-07-20T14:30:00Z")
    
    def test_observation_value_no_value(self):
        """Test value extraction when no value exists"""
        observation = ObservationResource(id="test-id")
        self.assertEqual(observation.get_value_with_unit(), "No value")


class MedicationStatementResourceTests(TestCase):
    """Test cases for MedicationStatementResource model"""
    
    def test_create_medication_statement(self):
        """Test creating a medication statement resource"""
        medication = MedicationStatementResource.create_from_medication(
            patient_id="patient-123",
            medication_name="Metformin",
            medication_code="6809",
            dosage="500mg",
            frequency="twice daily",
            status="active"
        )
        
        self.assertIsNotNone(medication.id)
        self.assertEqual(medication.status, "active")
        self.assertEqual(medication.subject["reference"], "Patient/patient-123")
        self.assertEqual(medication.get_medication_name(), "Metformin")
        self.assertEqual(medication.get_dosage_text(), "500mg")
        self.assertIsNotNone(medication.meta)
    
    def test_medication_minimal_info(self):
        """Test medication with minimal information"""
        medication = MedicationStatementResource.create_from_medication(
            patient_id="patient-456",
            medication_name="Aspirin"
        )
        
        self.assertEqual(medication.get_medication_name(), "Aspirin")
        self.assertEqual(medication.status, "active")
        self.assertIsNone(medication.get_dosage_text())
    
    def test_medication_name_extraction_no_concept(self):
        """Test medication name extraction when no concept exists"""
        medication = MedicationStatementResource(id="test-id")
        self.assertIsNone(medication.get_medication_name())
        self.assertIsNone(medication.get_dosage_text())


class PractitionerResourceTests(TestCase):
    """Test cases for PractitionerResource model"""
    
    def test_create_practitioner_from_provider(self):
        """Test creating a practitioner resource from provider info"""
        practitioner = PractitionerResource.create_from_provider(
            first_name="John",
            last_name="Smith",
            npi="1234567890",
            specialty="Internal Medicine",
            phone="555-1234",
            email="dr.smith@example.com"
        )
        
        self.assertIsNotNone(practitioner.id)
        self.assertEqual(practitioner.get_display_name(), "Dr. Smith, John")
        self.assertEqual(practitioner.get_npi(), "1234567890")
        self.assertIsNotNone(practitioner.meta)
    
    def test_practitioner_minimal_info(self):
        """Test practitioner with minimal information"""
        practitioner = PractitionerResource.create_from_provider(
            first_name="Jane",
            last_name="Doe"
        )
        
        self.assertEqual(practitioner.get_display_name(), "Dr. Doe, Jane")
        self.assertIsNone(practitioner.get_npi())
    
    def test_practitioner_display_name_fallback(self):
        """Test practitioner display name with missing name info"""
        practitioner = PractitionerResource(id="test-id")
        self.assertEqual(practitioner.get_display_name(), "Unknown Practitioner")
    
    def test_practitioner_npi_not_found(self):
        """Test NPI extraction when no NPI identifier exists"""
        practitioner = PractitionerResource(id="test-id")
        self.assertIsNone(practitioner.get_npi())


class ResourceIntegrationTests(TestCase):
    """Integration tests for resource interactions"""
    
    def test_create_complete_patient_record(self):
        """Test creating a complete patient record with all resource types"""
        # Create patient
        patient = PatientResource.create_from_demographics(
            mrn="12345",
            first_name="John",
            last_name="Doe",
            birth_date=date(1980, 1, 15),
            gender="male"
        )
        
        # Create practitioner
        practitioner = PractitionerResource.create_from_provider(
            first_name="Jane",
            last_name="Smith",
            npi="1234567890"
        )
        
        # Create document reference
        doc_ref = DocumentReferenceResource.create_from_document(
            patient_id=patient.id,
            document_title="Lab Results",
            document_type="lab-report",
            document_url="/documents/lab.pdf"
        )
        
        # Create condition
        condition = ConditionResource.create_from_diagnosis(
            patient_id=patient.id,
            condition_code="E11.9",
            condition_display="Type 2 diabetes mellitus"
        )
        
        # Create observation
        observation = ObservationResource.create_from_lab_result(
            patient_id=patient.id,
            test_code="33747-0",
            test_name="Glucose",
            value=95.0,
            unit="mg/dL"
        )
        
        # Create medication
        medication = MedicationStatementResource.create_from_medication(
            patient_id=patient.id,
            medication_name="Metformin",
            dosage="500mg"
        )
        
        # Verify all resources are created correctly
        self.assertIsNotNone(patient.id)
        self.assertIsNotNone(practitioner.id)
        self.assertIsNotNone(doc_ref.id)
        self.assertIsNotNone(condition.id)
        self.assertIsNotNone(observation.id)
        self.assertIsNotNone(medication.id)
        
        # Verify relationships
        self.assertEqual(doc_ref.subject["reference"], f"Patient/{patient.id}")
        self.assertEqual(condition.subject["reference"], f"Patient/{patient.id}")
        self.assertEqual(observation.subject["reference"], f"Patient/{patient.id}")
        self.assertEqual(medication.subject["reference"], f"Patient/{patient.id}")
        
        # Test helper methods
        self.assertEqual(patient.get_display_name(), "Doe, John")
        self.assertEqual(practitioner.get_display_name(), "Dr. Smith, Jane")
        self.assertEqual(condition.get_condition_display(), "Type 2 diabetes mellitus")
        self.assertEqual(observation.get_test_name(), "Glucose")
        self.assertEqual(medication.get_medication_name(), "Metformin")


class PatientSummaryTestCase(TestCase):
    """
    Test cases for patient summary generation functions.
    """
    
    def setUp(self):
        """Set up test data for patient summary tests."""
        from .fhir_models import (
            PatientResource, ConditionResource, MedicationStatementResource,
            ObservationResource, DocumentReferenceResource, PractitionerResource
        )
        from .bundle_utils import create_initial_patient_bundle, add_resource_to_bundle
        from datetime import datetime, timedelta
        
        # Create test patient
        self.patient = PatientResource.create_from_demographics(
            mrn="TEST123",
            first_name="John",
            last_name="Doe",
            birth_date="1980-01-01",
            patient_id="patient-123",
            gender="male",
            phone="555-0123",
            email="john.doe@example.com"
        )
        
        # Create initial bundle
        self.bundle = create_initial_patient_bundle(self.patient)
        
        # Add test conditions
        self.condition1 = ConditionResource.create_from_diagnosis(
            patient_id="patient-123",
            condition_code="E11.9",
            condition_display="Type 2 diabetes mellitus",
            condition_id="condition-1",
            clinical_status="active",
            onset_date="2020-01-01"
        )
        
        self.condition2 = ConditionResource.create_from_diagnosis(
            patient_id="patient-123",
            condition_code="I10",
            condition_display="Essential hypertension",
            condition_id="condition-2",
            clinical_status="active",
            onset_date="2019-06-01"
        )
        
        # Add test medications
        self.medication1 = MedicationStatementResource.create_from_medication(
            patient_id="patient-123",
            medication_name="Metformin",
            medication_code="6809",
            dosage="500mg",
            frequency="twice daily",
            medication_id="medication-1",
            status="active"
        )
        
        self.medication2 = MedicationStatementResource.create_from_medication(
            patient_id="patient-123",
            medication_name="Lisinopril",
            medication_code="29046",
            dosage="10mg",
            frequency="once daily",
            medication_id="medication-2",
            status="active"
        )
        
        # Add test observations
        self.observation1 = ObservationResource.create_from_lab_result(
            patient_id="patient-123",
            test_code="33747-0",
            test_name="Glucose",
            value=95,
            unit="mg/dL",
            observation_id="observation-1",
            observation_date=datetime.now() - timedelta(days=1)
        )
        
        self.observation2 = ObservationResource.create_from_lab_result(
            patient_id="patient-123",
            test_code="718-7",
            test_name="Hemoglobin",
            value=14.2,
            unit="g/dL",
            observation_id="observation-2",
            observation_date=datetime.now() - timedelta(days=2)
        )
        
        # Add test document
        self.document1 = DocumentReferenceResource.create_from_document(
            patient_id="patient-123",
            document_title="Annual Physical",
            document_type="clinical-note",
            document_url="/documents/annual-physical.pdf",
            document_id="document-1",
            creation_date=datetime.now() - timedelta(days=30)
        )
        
        # Add test practitioner
        self.practitioner1 = PractitionerResource.create_from_provider(
            first_name="Jane",
            last_name="Smith",
            npi="1234567890",
            specialty="Family Medicine",
            practitioner_id="practitioner-1"
        )
        
        # Add all resources to bundle
        add_resource_to_bundle(self.bundle, self.condition1)
        add_resource_to_bundle(self.bundle, self.condition2)
        add_resource_to_bundle(self.bundle, self.medication1)
        add_resource_to_bundle(self.bundle, self.medication2)
        add_resource_to_bundle(self.bundle, self.observation1)
        add_resource_to_bundle(self.bundle, self.observation2)
        add_resource_to_bundle(self.bundle, self.document1)
        add_resource_to_bundle(self.bundle, self.practitioner1)
    
    def test_generate_patient_summary_basic(self):
        """Test basic patient summary generation."""
        from .bundle_utils import generate_patient_summary
        
        summary = generate_patient_summary(
            bundle=self.bundle,
            patient_id="patient-123"
        )
        
        # Check basic structure
        self.assertIn('patient_id', summary)
        self.assertIn('generated_at', summary)
        self.assertIn('data', summary)
        self.assertEqual(summary['patient_id'], "patient-123")
        
        # Check that all default domains are included
        expected_domains = ['demographics', 'conditions', 'medications', 'observations', 'documents']
        for domain in expected_domains:
            self.assertIn(domain, summary['data'])
    
    def test_generate_patient_summary_demographics(self):
        """Test demographics extraction in patient summary."""
        from .bundle_utils import generate_patient_summary
        
        summary = generate_patient_summary(
            bundle=self.bundle,
            patient_id="patient-123",
            clinical_domains=['demographics']
        )
        
        demographics = summary['data']['demographics']
        
        # Check demographic fields
        self.assertEqual(demographics['name'], "Doe, John")
        self.assertEqual(demographics['mrn'], "TEST123")
        self.assertEqual(demographics['birth_date'], "1980-01-01")
        self.assertEqual(demographics['gender'], "male")
        self.assertEqual(demographics['contact_info']['phone'], "555-0123")
        self.assertEqual(demographics['contact_info']['email'], "john.doe@example.com")
    
    def test_generate_patient_summary_conditions(self):
        """Test conditions extraction in patient summary."""
        from .bundle_utils import generate_patient_summary
        
        summary = generate_patient_summary(
            bundle=self.bundle,
            patient_id="patient-123",
            clinical_domains=['conditions']
        )
        
        conditions = summary['data']['conditions']
        
        # Check conditions summary structure
        self.assertIn('total_count', conditions)
        self.assertIn('active_count', conditions)
        self.assertIn('items', conditions)
        
        # Should have 2 conditions
        self.assertEqual(conditions['total_count'], 2)
        self.assertEqual(conditions['active_count'], 2)
        self.assertEqual(len(conditions['items']), 2)
        
        # Check condition details
        condition_item = conditions['items'][0]  # Should be sorted by priority
        self.assertIn('id', condition_item)
        self.assertIn('code', condition_item)
        self.assertIn('display', condition_item)
        self.assertIn('clinical_status', condition_item)
    
    def test_generate_patient_summary_medications(self):
        """Test medications extraction in patient summary."""
        from .bundle_utils import generate_patient_summary
        
        summary = generate_patient_summary(
            bundle=self.bundle,
            patient_id="patient-123",
            clinical_domains=['medications']
        )
        
        medications = summary['data']['medications']
        
        # Check medications summary structure
        self.assertIn('total_count', medications)
        self.assertIn('active_count', medications)
        self.assertIn('items', medications)
        
        # Should have 2 medications
        self.assertEqual(medications['total_count'], 2)
        self.assertEqual(medications['active_count'], 2)
        self.assertEqual(len(medications['items']), 2)
        
        # Check medication details
        medication_item = medications['items'][0]
        self.assertIn('id', medication_item)
        self.assertIn('name', medication_item)
        self.assertIn('status', medication_item)
        self.assertIn('dosage', medication_item)
    
    def test_generate_patient_summary_observations(self):
        """Test observations extraction in patient summary."""
        from .bundle_utils import generate_patient_summary
        
        summary = generate_patient_summary(
            bundle=self.bundle,
            patient_id="patient-123",
            clinical_domains=['observations']
        )
        
        observations = summary['data']['observations']
        
        # Check observations summary structure
        self.assertIn('total_count', observations)
        self.assertIn('unique_tests', observations)
        self.assertIn('items', observations)
        
        # Should have 2 observations
        self.assertEqual(observations['total_count'], 2)
        self.assertEqual(observations['unique_tests'], 2)
        self.assertEqual(len(observations['items']), 2)
        
        # Check observation details
        observation_item = observations['items'][0]
        self.assertIn('id', observation_item)
        self.assertIn('test_name', observation_item)
        self.assertIn('value', observation_item)
        self.assertIn('status', observation_item)
        self.assertIn('effective_date', observation_item)
    
    def test_generate_patient_summary_documents(self):
        """Test documents extraction in patient summary."""
        from .bundle_utils import generate_patient_summary
        
        summary = generate_patient_summary(
            bundle=self.bundle,
            patient_id="patient-123",
            clinical_domains=['documents']
        )
        
        documents = summary['data']['documents']
        
        # Check documents summary structure
        self.assertIn('total_count', documents)
        self.assertIn('items', documents)
        
        # Should have 1 document
        self.assertEqual(documents['total_count'], 1)
        self.assertEqual(len(documents['items']), 1)
        
        # Check document details
        document_item = documents['items'][0]
        self.assertIn('id', document_item)
        self.assertIn('title', document_item)
        self.assertIn('type', document_item)
        self.assertIn('date', document_item)
        self.assertIn('status', document_item)
    
    def test_generate_patient_summary_with_date_range(self):
        """Test patient summary with date range filtering."""
        from .bundle_utils import generate_patient_summary
        from datetime import datetime, timedelta
        
        # Create date range for last 7 days
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=7)
        
        summary = generate_patient_summary(
            bundle=self.bundle,
            patient_id="patient-123",
            date_range=(start_date, end_date),
            clinical_domains=['observations']
        )
        
        # Check that date range is recorded
        self.assertIsNotNone(summary['date_range']['start'])
        self.assertIsNotNone(summary['date_range']['end'])
        
        # Should still have observations from last few days
        observations = summary['data']['observations']
        self.assertGreater(observations['total_count'], 0)
    
    def test_generate_patient_summary_with_max_items(self):
        """Test patient summary with item limit."""
        from .bundle_utils import generate_patient_summary
        
        summary = generate_patient_summary(
            bundle=self.bundle,
            patient_id="patient-123",
            clinical_domains=['conditions'],
            max_items_per_domain=1
        )
        
        conditions = summary['data']['conditions']
        
        # Should limit to 1 item even though we have 2 conditions
        self.assertEqual(len(conditions['items']), 1)
        self.assertEqual(conditions['total_count'], 1)  # Total after filtering
    
    def test_generate_patient_summary_invalid_patient(self):
        """Test patient summary with invalid patient ID."""
        from .bundle_utils import generate_patient_summary
        
        with self.assertRaises(ValueError) as context:
            generate_patient_summary(
                bundle=self.bundle,
                patient_id="invalid-patient"
            )
        
        self.assertIn("Patient with ID invalid-patient not found", str(context.exception))
    
    def test_generate_patient_summary_empty_bundle(self):
        """Test patient summary with empty bundle."""
        from .bundle_utils import generate_patient_summary
        from fhir.resources.bundle import Bundle
        
        empty_bundle = Bundle(type="collection", entry=[])
        
        with self.assertRaises(ValueError) as context:
            generate_patient_summary(
                bundle=empty_bundle,
                patient_id="patient-123"
            )
        
        self.assertIn("Patient with ID patient-123 not found", str(context.exception))
    
    def test_generate_clinical_summary_report_comprehensive(self):
        """Test comprehensive clinical summary report generation."""
        from .bundle_utils import generate_clinical_summary_report
        
        summary = generate_clinical_summary_report(
            bundle=self.bundle,
            patient_id="patient-123",
            report_type="comprehensive"
        )
        
        # Check report metadata
        self.assertEqual(summary['report_type'], "comprehensive")
        self.assertEqual(summary['report_title'], "Clinical Summary - Comprehensive")
        
        # Should include all domains
        expected_domains = ['demographics', 'conditions', 'medications', 'observations', 'documents', 'practitioners']
        for domain in expected_domains:
            self.assertIn(domain, summary['data'])
    
    def test_generate_clinical_summary_report_recent(self):
        """Test recent clinical summary report generation."""
        from .bundle_utils import generate_clinical_summary_report
        
        summary = generate_clinical_summary_report(
            bundle=self.bundle,
            patient_id="patient-123",
            report_type="recent"
        )
        
        # Check report metadata
        self.assertEqual(summary['report_type'], "recent")
        self.assertEqual(summary['report_title'], "Clinical Summary - Recent")
        
        # Should have date range for last 30 days
        self.assertIsNotNone(summary['date_range']['start'])
        self.assertIsNotNone(summary['date_range']['end'])
        
        # Should include limited domains
        expected_domains = ['conditions', 'medications', 'observations']
        for domain in expected_domains:
            self.assertIn(domain, summary['data'])
        
        # Should not include other domains
        self.assertNotIn('demographics', summary['data'])
        self.assertNotIn('documents', summary['data'])
    
    def test_generate_clinical_summary_report_problems_focused(self):
        """Test problems-focused clinical summary report generation."""
        from .bundle_utils import generate_clinical_summary_report
        
        summary = generate_clinical_summary_report(
            bundle=self.bundle,
            patient_id="patient-123",
            report_type="problems_focused"
        )
        
        # Check report metadata
        self.assertEqual(summary['report_type'], "problems_focused")
        self.assertEqual(summary['report_title'], "Clinical Summary - Problems Focused")
        
        # Should include problems and medications only
        self.assertIn('conditions', summary['data'])
        self.assertIn('medications', summary['data'])
        
        # Should not include other domains
        self.assertNotIn('demographics', summary['data'])
        self.assertNotIn('observations', summary['data'])
        self.assertNotIn('documents', summary['data'])
    
    def test_helper_functions_condition_priority(self):
        """Test condition priority helper functions."""
        from .bundle_utils import _get_condition_priority, _is_condition_active
        
        # Test with active condition
        priority = _get_condition_priority(self.condition1)
        is_active = _is_condition_active(self.condition1)
        
        self.assertEqual(priority, 100)  # Active conditions should have high priority
        self.assertTrue(is_active)
    
    def test_helper_functions_medication_priority(self):
        """Test medication priority helper functions."""
        from .bundle_utils import _get_medication_priority, _is_medication_active
        
        # Test with active medication
        priority = _get_medication_priority(self.medication1)
        is_active = _is_medication_active(self.medication1)
        
        self.assertEqual(priority, 100)  # Active medications should have high priority
        self.assertTrue(is_active)
    
    def test_helper_functions_observation_priority(self):
        """Test observation priority helper functions."""
        from .bundle_utils import _get_observation_priority
        
        # Test with glucose observation (should be high priority)
        priority = _get_observation_priority(self.observation1)
        self.assertEqual(priority, 90)  # Glucose is high priority
        
        # Test with hemoglobin observation (should be high priority)
        priority = _get_observation_priority(self.observation2)
        self.assertEqual(priority, 90)  # Hemoglobin is high priority
    
    def test_helper_functions_date_extraction(self):
        """Test date extraction helper functions."""
        from .bundle_utils import _get_condition_date, _get_medication_date, _get_observation_date
        
        # Test condition date
        condition_date = _get_condition_date(self.condition1)
        self.assertIsNotNone(condition_date)
        
        # Test medication date
        medication_date = _get_medication_date(self.medication1)
        self.assertIsNotNone(medication_date)
        
        # Test observation date
        observation_date = _get_observation_date(self.observation1)
        self.assertIsNotNone(observation_date)
    
    def test_edge_cases_empty_resources(self):
        """Test edge cases with empty or missing resource data."""
        from .bundle_utils import generate_patient_summary
        from .fhir_models import PatientResource
        from fhir.resources.bundle import Bundle
        
        # Create minimal patient with no additional resources
        minimal_patient = PatientResource.create_from_demographics(
            mrn="MIN123",
            first_name="Min",
            last_name="Patient",
            birth_date="1990-01-01",
            patient_id="minimal-patient"
        )
        
        minimal_bundle = Bundle(type="collection", entry=[{
            'fullUrl': f"Patient/{minimal_patient.id}",
            'resource': minimal_patient
        }])
        
        summary = generate_patient_summary(
            bundle=minimal_bundle,
            patient_id="minimal-patient"
        )
        
        # Should work with minimal data
        self.assertEqual(summary['patient_id'], "minimal-patient")
        self.assertIn('demographics', summary['data'])
        
        # Other domains should have empty results
        for domain in ['conditions', 'medications', 'observations', 'documents']:
            if domain in summary['data']:
                domain_data = summary['data'][domain]
                self.assertEqual(domain_data['total_count'], 0)
                self.assertEqual(len(domain_data['items']), 0)
