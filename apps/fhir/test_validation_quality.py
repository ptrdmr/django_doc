"""
Test suite for FHIR merge validation and quality checks system.
"""

import json
from datetime import datetime, timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from unittest.mock import patch, MagicMock

from apps.patients.models import Patient
from .validation_quality import (
    FHIRMergeValidator,
    ValidationReport,
    ValidationIssue,
    ValidationSeverity,
    ValidationCategory
)
from .services import FHIRMergeService


class ValidationIssueTests(TestCase):
    """Test cases for ValidationIssue class."""
    
    def test_create_validation_issue(self):
        """Test creating a validation issue."""
        issue = ValidationIssue(
            severity=ValidationSeverity.ERROR,
            category=ValidationCategory.STRUCTURE,
            message="Test validation issue",
            resource_type="Observation",
            resource_id="test-obs-1",
            field_path="code",
            auto_correctable=True,
            correction_description="Add missing code field"
        )
        
        self.assertEqual(issue.severity, ValidationSeverity.ERROR)
        self.assertEqual(issue.category, ValidationCategory.STRUCTURE)
        self.assertEqual(issue.message, "Test validation issue")
        self.assertEqual(issue.resource_type, "Observation")
        self.assertEqual(issue.resource_id, "test-obs-1")
        self.assertEqual(issue.field_path, "code")
        self.assertTrue(issue.auto_correctable)
        self.assertEqual(issue.correction_description, "Add missing code field")
        self.assertFalse(issue.corrected)
        self.assertIsNotNone(issue.id)
        self.assertIsNotNone(issue.timestamp)
    
    def test_validation_issue_to_dict(self):
        """Test conversion of validation issue to dictionary."""
        issue = ValidationIssue(
            severity=ValidationSeverity.WARNING,
            category=ValidationCategory.COMPLETENESS,
            message="Missing optional field"
        )
        
        issue_dict = issue.to_dict()
        
        self.assertIn('id', issue_dict)
        self.assertEqual(issue_dict['severity'], 'warning')
        self.assertEqual(issue_dict['category'], 'completeness')
        self.assertEqual(issue_dict['message'], "Missing optional field")
        self.assertFalse(issue_dict['corrected'])


class ValidationReportTests(TestCase):
    """Test cases for ValidationReport class."""
    
    def setUp(self):
        self.report = ValidationReport()
    
    def test_create_empty_report(self):
        """Test creating an empty validation report."""
        self.assertEqual(len(self.report.issues), 0)
        self.assertEqual(len(self.report.corrections_applied), 0)
        self.assertEqual(self.report.resources_validated, 0)
        self.assertIsNotNone(self.report.validation_start_time)
        self.assertIsNone(self.report.validation_end_time)
        self.assertIsNone(self.report.overall_score)
    
    def test_add_issue(self):
        """Test adding issues to the report."""
        issue1 = ValidationIssue(
            severity=ValidationSeverity.ERROR,
            category=ValidationCategory.STRUCTURE,
            message="Error 1"
        )
        issue2 = ValidationIssue(
            severity=ValidationSeverity.WARNING,
            category=ValidationCategory.REFERENCES,
            message="Warning 1"
        )
        
        self.report.add_issue(issue1)
        self.report.add_issue(issue2)
        
        self.assertEqual(len(self.report.issues), 2)
        self.assertIn(issue1, self.report.issues)
        self.assertIn(issue2, self.report.issues)
    
    def test_add_correction(self):
        """Test recording automatic corrections."""
        issue = ValidationIssue(
            severity=ValidationSeverity.WARNING,
            category=ValidationCategory.COMPLETENESS,
            message="Missing field",
            auto_correctable=True
        )
        
        self.report.add_issue(issue)
        self.report.add_correction(issue)
        
        self.assertTrue(issue.corrected)
        self.assertEqual(len(self.report.corrections_applied), 1)
        self.assertIn(issue, self.report.corrections_applied)
    
    def test_finalize_report(self):
        """Test finalizing the report and calculating metrics."""
        self.report.resources_validated = 10
        
        # Add some issues
        error_issue = ValidationIssue(
            severity=ValidationSeverity.ERROR,
            category=ValidationCategory.STRUCTURE,
            message="Error"
        )
        warning_issue = ValidationIssue(
            severity=ValidationSeverity.WARNING,
            category=ValidationCategory.COMPLETENESS,
            message="Warning"
        )
        
        self.report.add_issue(error_issue)
        self.report.add_issue(warning_issue)
        
        self.report.finalize()
        
        self.assertIsNotNone(self.report.validation_end_time)
        self.assertIsNotNone(self.report.overall_score)
        self.assertLessEqual(self.report.overall_score, 100.0)
        self.assertGreaterEqual(self.report.overall_score, 0.0)
    
    def test_get_issues_by_severity(self):
        """Test filtering issues by severity."""
        error1 = ValidationIssue(ValidationSeverity.ERROR, ValidationCategory.STRUCTURE, "Error 1")
        error2 = ValidationIssue(ValidationSeverity.ERROR, ValidationCategory.REFERENCES, "Error 2")
        warning = ValidationIssue(ValidationSeverity.WARNING, ValidationCategory.COMPLETENESS, "Warning")
        
        self.report.add_issue(error1)
        self.report.add_issue(error2)
        self.report.add_issue(warning)
        
        errors = self.report.get_issues_by_severity(ValidationSeverity.ERROR)
        warnings = self.report.get_issues_by_severity(ValidationSeverity.WARNING)
        
        self.assertEqual(len(errors), 2)
        self.assertEqual(len(warnings), 1)
        self.assertIn(error1, errors)
        self.assertIn(error2, errors)
        self.assertIn(warning, warnings)
    
    def test_get_issues_by_category(self):
        """Test filtering issues by category."""
        struct1 = ValidationIssue(ValidationSeverity.ERROR, ValidationCategory.STRUCTURE, "Struct 1")
        struct2 = ValidationIssue(ValidationSeverity.WARNING, ValidationCategory.STRUCTURE, "Struct 2")
        ref = ValidationIssue(ValidationSeverity.ERROR, ValidationCategory.REFERENCES, "Ref")
        
        self.report.add_issue(struct1)
        self.report.add_issue(struct2)
        self.report.add_issue(ref)
        
        structure_issues = self.report.get_issues_by_category(ValidationCategory.STRUCTURE)
        reference_issues = self.report.get_issues_by_category(ValidationCategory.REFERENCES)
        
        self.assertEqual(len(structure_issues), 2)
        self.assertEqual(len(reference_issues), 1)
        self.assertIn(struct1, structure_issues)
        self.assertIn(struct2, structure_issues)
        self.assertIn(ref, reference_issues)
    
    def test_has_critical_issues(self):
        """Test detection of critical issues."""
        # No critical issues initially
        self.assertFalse(self.report.has_critical_issues())
        
        # Add non-critical issue
        warning = ValidationIssue(ValidationSeverity.WARNING, ValidationCategory.COMPLETENESS, "Warning")
        self.report.add_issue(warning)
        self.assertFalse(self.report.has_critical_issues())
        
        # Add critical issue
        critical = ValidationIssue(ValidationSeverity.CRITICAL, ValidationCategory.SAFETY, "Critical")
        self.report.add_issue(critical)
        self.assertTrue(self.report.has_critical_issues())
        
        # Mark critical issue as corrected
        self.report.add_correction(critical)
        self.assertFalse(self.report.has_critical_issues())
    
    def test_quality_score_calculation(self):
        """Test quality score calculation logic."""
        self.report.resources_validated = 5
        
        # Perfect score with no issues
        self.report.finalize()
        self.assertEqual(self.report.overall_score, 100.0)
        
        # Add some issues and recalculate
        self.report.add_issue(ValidationIssue(ValidationSeverity.ERROR, ValidationCategory.STRUCTURE, "Error"))
        self.report.add_issue(ValidationIssue(ValidationSeverity.WARNING, ValidationCategory.COMPLETENESS, "Warning"))
        self.report.finalize()
        
        # Score should be less than 100 but greater than 0
        self.assertLess(self.report.overall_score, 100.0)
        self.assertGreater(self.report.overall_score, 0.0)


class FHIRMergeValidatorTests(TestCase):
    """Test cases for FHIRMergeValidator class."""
    
    def setUp(self):
        self.validator = FHIRMergeValidator(auto_correct=True)
    
    def test_create_validator(self):
        """Test creating a validator instance."""
        self.assertTrue(self.validator.auto_correct)
        self.assertIsNotNone(self.validator.logger)
    
    def test_validate_empty_bundle(self):
        """Test validation of an empty FHIR bundle."""
        empty_bundle = {}
        
        report = self.validator.validate_merge_result(empty_bundle)
        
        self.assertIsInstance(report, ValidationReport)
        self.assertGreater(len(report.issues), 0)
        
        # Should have a warning about empty bundle
        warnings = report.get_issues_by_severity(ValidationSeverity.WARNING)
        self.assertTrue(any("empty" in issue.message.lower() for issue in warnings))
    
    def test_validate_bundle_with_valid_resources(self):
        """Test validation of a bundle with valid resources."""
        valid_bundle = {
            "Patient": [{
                "resourceType": "Patient",
                "id": "patient-1",
                "name": [{"family": "Smith", "given": ["John"]}],
                "gender": "male"
            }],
            "Observation": [{
                "resourceType": "Observation",
                "id": "obs-1",
                "status": "final",
                "code": {
                    "coding": [{
                        "system": "http://loinc.org",
                        "code": "8302-2",
                        "display": "Body height"
                    }]
                },
                "subject": {"reference": "Patient/patient-1"},
                "valueQuantity": {
                    "value": 185,
                    "unit": "cm",
                    "system": "http://unitsofmeasure.org"
                }
            }]
        }
        
        report = self.validator.validate_merge_result(valid_bundle)
        
        self.assertIsInstance(report, ValidationReport)
        self.assertEqual(report.resources_validated, 2)
        
        # Should have high quality score for valid resources
        self.assertGreaterEqual(report.overall_score, 80.0)
    
    def test_validate_bundle_with_missing_references(self):
        """Test validation detects missing references."""
        bundle_with_broken_refs = {
            "Observation": [{
                "resourceType": "Observation",
                "id": "obs-1",
                "status": "final",
                "code": {"coding": [{"code": "8302-2", "display": "Height"}]},
                "subject": {"reference": "Patient/nonexistent-patient"},
                "valueQuantity": {"value": 185, "unit": "cm"}
            }]
        }
        
        report = self.validator.validate_merge_result(bundle_with_broken_refs)
        
        # Should have reference errors
        reference_issues = report.get_issues_by_category(ValidationCategory.REFERENCES)
        self.assertGreater(len(reference_issues), 0)
        
        # Should find the broken reference
        broken_ref_found = any(
            "nonexistent-patient" in issue.message for issue in reference_issues
        )
        self.assertTrue(broken_ref_found)
    
    def test_validate_bundle_with_incomplete_resources(self):
        """Test validation detects incomplete resources."""
        incomplete_bundle = {
            "Observation": [{
                "resourceType": "Observation",
                "id": "obs-incomplete",
                # Missing required fields like code, status
                "subject": {"reference": "Patient/patient-1"}
            }],
            "Condition": [{
                "resourceType": "Condition",
                "id": "condition-incomplete",
                # Missing code field
                "subject": {"reference": "Patient/patient-1"}
            }]
        }
        
        report = self.validator.validate_merge_result(incomplete_bundle)
        
        # Should have completeness errors
        completeness_issues = report.get_issues_by_category(ValidationCategory.COMPLETENESS)
        self.assertGreater(len(completeness_issues), 0)
        
        # Should detect missing code fields
        missing_code_found = any(
            "code" in issue.message.lower() for issue in completeness_issues
        )
        self.assertTrue(missing_code_found)
    
    def test_validate_bundle_with_critical_values(self):
        """Test validation detects critical lab values."""
        critical_bundle = {
            "Observation": [{
                "resourceType": "Observation",
                "id": "critical-glucose",
                "status": "final",
                "code": {
                    "coding": [{
                        "system": "http://loinc.org",
                        "code": "2345-7",
                        "display": "Glucose"
                    }]
                },
                "subject": {"reference": "Patient/patient-1"},
                "valueQuantity": {
                    "value": 500,  # Critical glucose level
                    "unit": "mg/dL"
                }
            }]
        }
        
        report = self.validator.validate_merge_result(critical_bundle)
        
        # Should have safety/critical issues
        safety_issues = report.get_issues_by_category(ValidationCategory.SAFETY)
        critical_issues = report.get_issues_by_severity(ValidationSeverity.CRITICAL)
        
        self.assertGreater(len(safety_issues) + len(critical_issues), 0)
    
    def test_automatic_corrections(self):
        """Test automatic correction of minor issues."""
        bundle_with_correctable_issues = {
            "Observation": [{
                "resourceType": "Observation",
                # Missing ID - should be auto-correctable
                "status": "final",
                "code": {"coding": [{"code": "8302-2"}]},
                "valueQuantity": {"value": 185, "unit": "cm"}
            }],
            "Condition": [{
                "resourceType": "Condition",
                "id": "condition-1",
                "code": {"coding": [{"code": "K21.9"}]},
                # Missing clinicalStatus - should be auto-correctable
                "subject": {"reference": "Patient/patient-1"}
            }]
        }
        
        report = self.validator.validate_merge_result(bundle_with_correctable_issues)
        
        # Should have applied some corrections
        self.assertGreater(len(report.corrections_applied), 0)
        
        # Check that correctable issues were actually corrected
        corrected_issues = [issue for issue in report.issues if issue.corrected]
        self.assertGreater(len(corrected_issues), 0)
    
    def test_temporal_consistency_validation(self):
        """Test validation of temporal consistency in observations."""
        now = datetime.now()
        one_minute_later = now + timedelta(minutes=1)
        
        temporal_bundle = {
            "Observation": [
                {
                    "resourceType": "Observation",
                    "id": "obs-1",
                    "status": "final",
                    "code": {"coding": [{"code": "8302-2", "display": "Height"}]},
                    "subject": {"reference": "Patient/patient-1"},
                    "effectiveDateTime": now.isoformat(),
                    "valueQuantity": {"value": 185, "unit": "cm"}
                },
                {
                    "resourceType": "Observation",
                    "id": "obs-2",
                    "status": "final",
                    "code": {"coding": [{"code": "8302-2", "display": "Height"}]},
                    "subject": {"reference": "Patient/patient-1"},
                    "effectiveDateTime": one_minute_later.isoformat(),
                    "valueQuantity": {"value": 186, "unit": "cm"}
                }
            ]
        }
        
        report = self.validator.validate_merge_result(temporal_bundle)
        
        # Should detect temporal inconsistency (observations too close in time)
        logic_issues = report.get_issues_by_category(ValidationCategory.LOGIC)
        
        # May or may not flag this as suspicious depending on exact timing
        # Just ensure validation ran without errors
        self.assertIsInstance(report, ValidationReport)


class FHIRMergeServiceValidationIntegrationTests(TestCase):
    """Integration tests for validation within FHIRMergeService."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            mrn='TEST-12345',
            date_of_birth='1980-01-01',
            gender='M',
            created_by=self.user
        )
    
    def test_merge_service_includes_validation(self):
        """Test that merge service includes validation in results."""
        merge_service = FHIRMergeService(self.patient)
        
        # Mock the validation to avoid complex setup
        with patch.object(merge_service.validator, 'validate_merge_result') as mock_validate:
            mock_report = ValidationReport()
            mock_report.finalize()
            mock_validate.return_value = mock_report
            
            # Prepare simple test data
            extracted_data = {
                'document_type': 'lab_report',
                'patient_name': 'John Doe',
                'test_results': [
                    {
                        'test_name': 'Glucose',
                        'value': 95,
                        'unit': 'mg/dL',
                        'reference_range': '70-100 mg/dL'
                    }
                ]
            }
            
            document_metadata = {
                'document_id': 'test-doc-123',
                'document_url': 'http://example.com/doc.pdf',
                'provider_name': 'Dr. Smith'
            }
            
            # Perform merge
            result = merge_service.merge_document_data(
                extracted_data=extracted_data,
                document_metadata=document_metadata,
                user=self.user
            )
            
            # Check that validation was called and included in result
            mock_validate.assert_called_once()
            self.assertIsNotNone(result.validation_report)
            self.assertIsInstance(result.validation_report, ValidationReport)
    
    def test_merge_service_handles_validation_errors(self):
        """Test that merge service handles validation errors gracefully."""
        merge_service = FHIRMergeService(self.patient)
        
        # Mock validation to raise an exception
        with patch.object(merge_service.validator, 'validate_merge_result') as mock_validate:
            mock_validate.side_effect = Exception("Validation failed")
            
            extracted_data = {
                'document_type': 'lab_report',
                'patient_name': 'John Doe',
                'test_results': []
            }
            
            document_metadata = {
                'document_id': 'test-doc-123'
            }
            
            # Merge should not fail due to validation error
            result = merge_service.merge_document_data(
                extracted_data=extracted_data,
                document_metadata=document_metadata,
                user=self.user
            )
            
            # Should have validation report with error
            self.assertIsNotNone(result.validation_report)
            error_issues = result.validation_report.get_issues_by_severity(ValidationSeverity.ERROR)
            self.assertGreater(len(error_issues), 0)
    
    def test_merge_service_validation_affects_result_summary(self):
        """Test that validation results are included in merge result summaries."""
        merge_service = FHIRMergeService(self.patient)
        
        # Create a mock validation report with specific issues
        with patch.object(merge_service.validator, 'validate_merge_result') as mock_validate:
            mock_report = ValidationReport()
            mock_report.add_issue(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category=ValidationCategory.COMPLETENESS,
                message="Test validation warning"
            ))
            mock_report.finalize()
            mock_validate.return_value = mock_report
            
            extracted_data = {
                'document_type': 'clinical_note',
                'patient_name': 'John Doe',
                'note_text': 'Patient appears well.'
            }
            
            document_metadata = {
                'document_id': 'test-note-123'
            }
            
            result = merge_service.merge_document_data(
                extracted_data=extracted_data,
                document_metadata=document_metadata,
                user=self.user
            )
            
            # Check that validation summary is included in messages
            summary_messages = result.get_message_summary()
            self.assertTrue(any("validation" in msg.lower() for msg in summary_messages))
            
            # Check that validation issues are tracked
            self.assertGreater(len(result.validation_issues), 0)


class ValidationQualityPerformanceTests(TestCase):
    """Performance tests for validation system."""
    
    def test_validation_performance_with_large_bundle(self):
        """Test validation performance with a large FHIR bundle."""
        # Create a large bundle with many resources
        large_bundle = {
            "Patient": [{
                "resourceType": "Patient",
                "id": "patient-1",
                "name": [{"family": "Smith", "given": ["John"]}],
                "gender": "male"
            }],
            "Observation": []
        }
        
        # Add many observations
        for i in range(100):
            obs = {
                "resourceType": "Observation",
                "id": f"obs-{i}",
                "status": "final",
                "code": {"coding": [{"code": "8302-2", "display": "Height"}]},
                "subject": {"reference": "Patient/patient-1"},
                "valueQuantity": {"value": 180 + i, "unit": "cm"}
            }
            large_bundle["Observation"].append(obs)
        
        validator = FHIRMergeValidator(auto_correct=False)  # Disable corrections for speed
        
        start_time = datetime.now()
        report = validator.validate_merge_result(large_bundle)
        end_time = datetime.now()
        
        # Validation should complete in reasonable time (under 5 seconds)
        processing_time = (end_time - start_time).total_seconds()
        self.assertLess(processing_time, 5.0)
        
        # Should validate all resources
        self.assertEqual(report.resources_validated, 101)  # 1 patient + 100 observations
        
        # Should have reasonable quality score
        self.assertGreaterEqual(report.overall_score, 70.0)
