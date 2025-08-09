"""
Tests for FHIR Merge Result Summary Generation

This module contains comprehensive tests for the MergeResult class
and its summary generation capabilities, including serialization,
human-readable formatting, and UI display methods.
"""

import json
from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import patch, MagicMock
from django.utils import timezone
from django.contrib.auth.models import User

from .services import MergeResult


class MergeResultTest(TestCase):
    """Test the enhanced MergeResult class functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.result = MergeResult()
        # Create unique username for each test
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        self.test_user = User.objects.create_user(
            username=f'testuser_{unique_id}',
            email=f'test_{unique_id}@example.com'
        )
    
    def test_initialization(self):
        """Test MergeResult initialization."""
        result = MergeResult()
        
        # Check default values
        self.assertFalse(result.success)
        self.assertEqual(result.operation_type, "fhir_merge")
        self.assertEqual(result.resources_added, 0)
        self.assertEqual(result.resources_updated, 0)
        self.assertEqual(result.resources_skipped, 0)
        self.assertEqual(result.conflicts_detected, 0)
        self.assertEqual(result.conflicts_resolved, 0)
        self.assertEqual(result.duplicates_removed, 0)
        self.assertEqual(result.validation_score, 100.0)
        self.assertEqual(result.processing_time_seconds, 0.0)
        self.assertIsNone(result.patient_mrn)
        self.assertEqual(result.document_ids, [])
        self.assertEqual(result.resources_by_type, {})
        self.assertEqual(result.duplicates_by_type, {})
        self.assertEqual(result.validation_errors, [])
        self.assertEqual(result.validation_warnings, [])
        self.assertEqual(result.merge_errors, [])
        self.assertEqual(result.warning_messages, [])
        self.assertEqual(result.info_messages, [])
        self.assertIsNotNone(result.timestamp)
    
    def test_add_resource(self):
        """Test adding resource tracking."""
        result = MergeResult()
        
        # Add various resource types and actions
        result.add_resource("Observation", "added")
        result.add_resource("Observation", "added")
        result.add_resource("Observation", "updated")
        result.add_resource("Condition", "added")
        result.add_resource("MedicationStatement", "skipped")
        
        # Check totals
        self.assertEqual(result.resources_added, 3)
        self.assertEqual(result.resources_updated, 1)
        self.assertEqual(result.resources_skipped, 1)
        self.assertEqual(result.get_total_resources_processed(), 5)
        
        # Check resource type tracking
        self.assertEqual(result.resources_by_type["Observation"]["added"], 2)
        self.assertEqual(result.resources_by_type["Observation"]["updated"], 1)
        self.assertEqual(result.resources_by_type["Observation"]["skipped"], 0)
        self.assertEqual(result.resources_by_type["Condition"]["added"], 1)
        self.assertEqual(result.resources_by_type["MedicationStatement"]["skipped"], 1)
    
    def test_add_duplicate_removed(self):
        """Test duplicate tracking."""
        result = MergeResult()
        
        result.add_duplicate_removed("Observation")
        result.add_duplicate_removed("Observation")
        result.add_duplicate_removed("Condition")
        
        self.assertEqual(result.duplicates_removed, 3)
        self.assertEqual(result.duplicates_by_type["Observation"], 2)
        self.assertEqual(result.duplicates_by_type["Condition"], 1)
    
    def test_add_validation_issue(self):
        """Test validation issue tracking."""
        result = MergeResult()
        
        # Add errors (should reduce validation score)
        result.add_validation_issue("missing_field", "Patient name is required", "patient.name", "error")
        result.add_validation_issue("invalid_date", "Invalid birth date", "patient.birthDate", "error")
        
        # Add warnings (should reduce validation score less)
        result.add_validation_issue("format_warning", "Date format could be improved", "date", "warning")
        
        self.assertEqual(len(result.validation_errors), 2)
        self.assertEqual(len(result.validation_warnings), 1)
        self.assertEqual(result.validation_score, 78.0)  # 100 - 10 - 10 - 2
        
        # Check issue structure
        error = result.validation_errors[0]
        self.assertEqual(error["type"], "missing_field")
        self.assertEqual(error["message"], "Patient name is required")
        self.assertEqual(error["field"], "patient.name")
        self.assertEqual(error["severity"], "error")
        self.assertIn("timestamp", error)
    
    def test_add_merge_error(self):
        """Test merge error tracking."""
        result = MergeResult()
        
        exception = ValueError("Test exception")
        result.add_merge_error("validation_error", "Validation failed", exception)
        
        self.assertEqual(len(result.merge_errors), 1)
        error = result.merge_errors[0]
        self.assertEqual(error["type"], "validation_error")
        self.assertEqual(error["message"], "Validation failed")
        self.assertEqual(error["exception"], "Test exception")
        self.assertIn("timestamp", error)
    
    def test_add_message(self):
        """Test message tracking."""
        result = MergeResult()
        
        result.add_message("Processing started")
        result.add_message("Warning about data quality", "warning")
        
        self.assertEqual(len(result.info_messages), 1)
        self.assertEqual(len(result.warning_messages), 1)
        self.assertEqual(result.info_messages[0]["message"], "Processing started")
        self.assertEqual(result.warning_messages[0]["message"], "Warning about data quality")
    
    def test_set_performance_metrics(self):
        """Test performance metrics setting."""
        result = MergeResult()
        
        result.set_performance_metrics(2.5, 150.0, 3)
        
        self.assertEqual(result.processing_time_seconds, 2.5)
        self.assertEqual(result.memory_usage_mb, 150.0)
        self.assertEqual(result.api_calls_made, 3)
    
    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        result = MergeResult()
        
        # Test with no resources (should be 100%)
        self.assertEqual(result.get_success_rate(), 100.0)
        
        # Test with resources
        result.add_resource("Observation", "added")
        result.add_resource("Observation", "updated")
        result.add_resource("Condition", "skipped")
        
        # Success rate = (added + updated) / total = 2/3 = 66.67%
        self.assertAlmostEqual(result.get_success_rate(), 66.67, places=1)
    
    def test_conflict_resolution_rate(self):
        """Test conflict resolution rate calculation."""
        result = MergeResult()
        
        # Test with no conflicts (should be 100%)
        self.assertEqual(result.get_conflict_resolution_rate(), 100.0)
        
        # Test with conflicts
        result.conflicts_detected = 5
        result.conflicts_resolved = 3
        
        # Resolution rate = resolved / detected = 3/5 = 60%
        self.assertEqual(result.get_conflict_resolution_rate(), 60.0)
    
    def test_operation_summary(self):
        """Test operation summary generation."""
        result = MergeResult()
        result.success = True
        result.add_resource("Observation", "added")
        result.add_resource("Condition", "updated")
        result.processing_time_seconds = 1.23
        
        summary = result.get_operation_summary()
        
        self.assertIn("✅ Successful", summary)
        self.assertIn("2 resources", summary)
        self.assertIn("100.0% success rate", summary)
        self.assertIn("1.23s", summary)
    
    def test_operation_summary_failed(self):
        """Test operation summary for failed operation."""
        result = MergeResult()
        result.success = False
        result.add_merge_error("test_error", "Test error message")
        
        summary = result.get_operation_summary()
        self.assertIn("❌ Failed", summary)
    
    def test_operation_summary_with_issues(self):
        """Test operation summary for operation with issues."""
        result = MergeResult()
        result.success = False  # But no merge errors
        
        summary = result.get_operation_summary()
        self.assertIn("⚠️ Completed with issues", summary)
    
    def test_detailed_summary_generation(self):
        """Test detailed summary generation."""
        result = MergeResult()
        result.operation_type = "fhir_merge"
        result.patient_mrn = "TEST123"
        result.performed_by_username = "testuser"
        result.success = True
        
        # Add some data
        result.add_resource("Observation", "added")
        result.add_resource("Condition", "updated")
        result.conflicts_detected = 2
        result.conflicts_resolved = 2
        result.add_duplicate_removed("Observation")
        result.add_validation_issue("test", "Test validation issue", severity="warning")
        result.provenance_resources_created = 1
        result.processing_time_seconds = 2.5
        result.bundle_version_before = "1"
        result.bundle_version_after = "2"
        result.bundle_size_before = 5
        result.bundle_size_after = 7
        
        summary = result.get_detailed_summary()
        
        # Check key sections are present
        self.assertIn("FHIR MERGE OPERATION SUMMARY", summary)
        self.assertIn("Operation: fhir_merge", summary)
        self.assertIn("Patient MRN: TEST123", summary)
        self.assertIn("Performed by: testuser", summary)
        self.assertIn("RESOURCE PROCESSING:", summary)
        self.assertIn("Resources Added: 1", summary)
        self.assertIn("Resources Updated: 1", summary)
        self.assertIn("CONFLICT RESOLUTION:", summary)
        self.assertIn("Conflicts Detected: 2", summary)
        self.assertIn("DEDUPLICATION:", summary)
        self.assertIn("Duplicates Removed: 1", summary)
        self.assertIn("VALIDATION:", summary)
        self.assertIn("PERFORMANCE:", summary)
        self.assertIn("Processing Time: 2.50 seconds", summary)
        self.assertIn("BUNDLE VERSIONING:", summary)
        self.assertIn("Version Before: 1", summary)
        self.assertIn("Version After: 2", summary)
        self.assertIn("PROVENANCE:", summary)
        self.assertIn("Provenance Resources Created: 1", summary)
    
    def test_ui_summary_generation(self):
        """Test UI summary generation."""
        result = MergeResult()
        result.success = True
        result.add_resource("Observation", "added")
        result.add_resource("Condition", "updated")
        result.conflicts_detected = 3
        result.conflicts_resolved = 2
        result.add_duplicate_removed("Observation")
        result.processing_time_seconds = 1.5
        result.validation_score = 85.0
        
        ui_summary = result.get_ui_summary()
        
        # Check structure
        self.assertIn("status", ui_summary)
        self.assertIn("metrics", ui_summary)
        self.assertIn("details", ui_summary)
        self.assertIn("issues", ui_summary)
        
        # Check status
        self.assertTrue(ui_summary["status"]["success"])
        self.assertIn("summary", ui_summary["status"])
        self.assertIn("timestamp", ui_summary["status"])
        
        # Check metrics
        metrics = ui_summary["metrics"]
        self.assertEqual(metrics["resources_processed"], 2)
        self.assertEqual(metrics["success_rate"], 100.0)
        self.assertEqual(metrics["processing_time"], 1.5)
        self.assertEqual(metrics["validation_score"], 85.0)
        
        # Check details
        details = ui_summary["details"]
        self.assertEqual(details["resources"]["added"], 1)
        self.assertEqual(details["resources"]["updated"], 1)
        self.assertEqual(details["conflicts"]["detected"], 3)
        self.assertEqual(details["conflicts"]["resolved"], 2)
        self.assertEqual(details["deduplication"]["removed"], 1)
        
        # Check issues
        issues = ui_summary["issues"]
        self.assertEqual(issues["errors"], 0)
        self.assertEqual(issues["warnings"], 0)
    
    def test_to_dict_serialization(self):
        """Test dictionary serialization."""
        result = MergeResult()
        result.success = True
        result.operation_type = "fhir_merge"
        result.patient_mrn = "TEST123"
        result.document_ids = ["doc1", "doc2"]
        result.performed_by_user_id = self.test_user.id
        result.performed_by_username = self.test_user.username
        result.add_resource("Observation", "added")
        result.conflicts_detected = 1
        result.conflicts_resolved = 1  # Set to 1 to make resolution rate 100%
        result.processing_time_seconds = 2.0
        
        data = result.to_dict()
        
        # Check all expected fields are present
        expected_fields = [
            'success', 'operation_type', 'patient_mrn', 'document_ids',
            'resources_added', 'resources_updated', 'resources_skipped',
            'conflicts_detected', 'conflicts_resolved', 'duplicates_removed',
            'validation_score', 'processing_time_seconds', 'timestamp',
            'performed_by_user_id', 'performed_by_username',
            'total_resources_processed', 'success_rate', 'conflict_resolution_rate'
        ]
        
        for field in expected_fields:
            self.assertIn(field, data)
        
        # Check specific values
        self.assertEqual(data['success'], True)
        self.assertEqual(data['operation_type'], "fhir_merge")
        self.assertEqual(data['patient_mrn'], "TEST123")
        self.assertEqual(data['document_ids'], ["doc1", "doc2"])
        self.assertEqual(data['resources_added'], 1)
        self.assertEqual(data['processing_time_seconds'], 2.0)
        self.assertEqual(data['performed_by_user_id'], self.test_user.id)
        self.assertEqual(data['performed_by_username'], self.test_user.username)
        
        # Check calculated fields
        self.assertEqual(data['total_resources_processed'], 1)
        self.assertEqual(data['success_rate'], 100.0)
        self.assertEqual(data['conflict_resolution_rate'], 100.0)
    
    def test_from_dict_deserialization(self):
        """Test creation from dictionary."""
        data = {
            'success': True,
            'operation_type': 'fhir_merge',
            'patient_mrn': 'TEST123',
            'document_ids': ['doc1'],
            'resources_added': 2,
            'resources_updated': 1,
            'conflicts_detected': 3,
            'conflicts_resolved': 2,
            'processing_time_seconds': 1.5,
            'validation_score': 90.0,
            'performed_by_user_id': 1,
            'performed_by_username': 'testuser',
            'timestamp': '2023-01-01T12:00:00+00:00',
            'resources_by_type': {'Observation': {'added': 1, 'updated': 0, 'skipped': 0}},
            'duplicates_by_type': {'Observation': 1},
            'validation_errors': [{'type': 'test', 'message': 'Test error'}],
            'merge_errors': [{'type': 'test', 'message': 'Test error'}]
        }
        
        result = MergeResult.from_dict(data)
        
        # Check basic fields
        self.assertEqual(result.success, True)
        self.assertEqual(result.operation_type, 'fhir_merge')
        self.assertEqual(result.patient_mrn, 'TEST123')
        self.assertEqual(result.document_ids, ['doc1'])
        self.assertEqual(result.resources_added, 2)
        self.assertEqual(result.resources_updated, 1)
        self.assertEqual(result.conflicts_detected, 3)
        self.assertEqual(result.conflicts_resolved, 2)
        self.assertEqual(result.processing_time_seconds, 1.5)
        self.assertEqual(result.validation_score, 90.0)
        self.assertEqual(result.performed_by_user_id, 1)
        self.assertEqual(result.performed_by_username, 'testuser')
        
        # Check complex fields
        self.assertEqual(result.resources_by_type, {'Observation': {'added': 1, 'updated': 0, 'skipped': 0}})
        self.assertEqual(result.duplicates_by_type, {'Observation': 1})
        self.assertEqual(len(result.validation_errors), 1)
        self.assertEqual(len(result.merge_errors), 1)
        
        # Check timestamp parsing
        expected_timestamp = datetime.fromisoformat('2023-01-01T12:00:00+00:00')
        self.assertEqual(result.timestamp, expected_timestamp)
    
    def test_json_serialization(self):
        """Test JSON serialization/deserialization."""
        result = MergeResult()
        result.success = True
        result.patient_mrn = "TEST123"
        result.add_resource("Observation", "added")
        result.processing_time_seconds = 1.5
        
        # Convert to dict and then JSON
        data = result.to_dict()
        json_str = json.dumps(data)
        
        # Parse back from JSON
        parsed_data = json.loads(json_str)
        
        # Create new result from parsed data
        new_result = MergeResult.from_dict(parsed_data)
        
        # Check they match
        self.assertEqual(new_result.success, result.success)
        self.assertEqual(new_result.patient_mrn, result.patient_mrn)
        self.assertEqual(new_result.resources_added, result.resources_added)
        self.assertEqual(new_result.processing_time_seconds, result.processing_time_seconds)


class MergeResultIntegrationTest(TestCase):
    """Test MergeResult integration scenarios."""
    
    def test_complex_merge_scenario(self):
        """Test a complex merge scenario with all features."""
        result = MergeResult()
        result.operation_type = "fhir_merge"
        result.patient_mrn = "COMPLEX123"
        result.document_ids = ["doc1", "doc2", "doc3"]
        
        # Simulate processing multiple documents
        # Document 1: Lab results
        result.add_resource("Observation", "added")
        result.add_resource("Observation", "added")
        result.add_resource("DiagnosticReport", "added")
        
        # Document 2: Clinical notes with conflicts
        result.add_resource("Condition", "added")
        result.add_resource("Condition", "updated")  # Conflict resolved
        result.conflicts_detected = 2
        result.conflicts_resolved = 2
        
        # Document 3: Medication list with duplicates
        result.add_resource("MedicationStatement", "added")
        result.add_duplicate_removed("MedicationStatement")
        result.add_resource("MedicationStatement", "skipped")  # Another duplicate
        
        # Add some validation issues
        result.add_validation_issue("date_format", "Date format inconsistent", "effectiveDate", "warning")
        result.add_validation_issue("missing_code", "Missing medication code", "medication.code", "error")
        
        # Add processing info
        result.set_performance_metrics(5.2, 200.0, 15)
        result.provenance_resources_created = 3
        result.bundle_version_before = "v1.2"
        result.bundle_version_after = "v1.3"
        result.bundle_size_before = 12
        result.bundle_size_after = 17
        result.success = True
        
        # Test calculations
        self.assertEqual(result.get_total_resources_processed(), 7)
        self.assertAlmostEqual(result.get_success_rate(), 85.71, places=1)  # 6 successful out of 7
        self.assertEqual(result.get_conflict_resolution_rate(), 100.0)
        self.assertEqual(result.validation_score, 88.0)  # 100 - 10 (error) - 2 (warning)
        
        # Test summary generation
        summary = result.get_operation_summary()
        self.assertIn("✅ Successful", summary)
        self.assertIn("7 resources", summary)
        self.assertIn("85.7% success rate", summary)
        self.assertIn("5.20s", summary)
        
        # Test detailed summary
        detailed = result.get_detailed_summary()
        self.assertIn("COMPLEX123", detailed)
        self.assertIn("Observation: 2 total", detailed)
        self.assertIn("Condition: 2 total", detailed)
        self.assertIn("MedicationStatement: 2 total", detailed)
        self.assertIn("Conflicts Resolved: 2", detailed)
        self.assertIn("Duplicates Removed: 1", detailed)
        self.assertIn("Validation Score: 88.0/100", detailed)
        self.assertIn("Processing Time: 5.20 seconds", detailed)
        self.assertIn("Memory Usage: 200.0 MB", detailed)
        self.assertIn("API Calls Made: 15", detailed)
        
        # Test UI summary
        ui_summary = result.get_ui_summary()
        self.assertEqual(ui_summary["metrics"]["resources_processed"], 7)
        self.assertEqual(ui_summary["details"]["resources"]["by_type"]["Observation"]["added"], 2)
        self.assertEqual(ui_summary["details"]["conflicts"]["resolution_rate"], 100.0)
        self.assertEqual(ui_summary["issues"]["validation_errors"], 1)
        self.assertEqual(ui_summary["issues"]["validation_warnings"], 1)
        
        # Test serialization round-trip
        data = result.to_dict()
        restored_result = MergeResult.from_dict(data)
        
        self.assertEqual(restored_result.patient_mrn, result.patient_mrn)
        self.assertEqual(restored_result.get_total_resources_processed(), result.get_total_resources_processed())
        self.assertEqual(restored_result.get_success_rate(), result.get_success_rate())
        self.assertEqual(restored_result.validation_score, result.validation_score)
