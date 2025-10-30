"""
Tests for DiagnosticReport Pydantic model (Task 40.11)

Verifies that the DiagnosticReport Pydantic model:
1. Validates correctly with valid data
2. Rejects invalid data appropriately
3. Serializes/deserializes properly
4. Integrates into StructuredMedicalExtraction
"""

import unittest
from pydantic import ValidationError
from apps.documents.services.ai_extraction import DiagnosticReport, StructuredMedicalExtraction, SourceContext


class DiagnosticReportPydanticModelTests(unittest.TestCase):
    """Test DiagnosticReport Pydantic model validation and integration."""
    
    def test_diagnostic_report_model_valid_full_data(self):
        """Test DiagnosticReport model with all fields populated."""
        diagnostic_report = DiagnosticReport(
            report_id='rpt-001',
            report_type='radiology',
            findings='Chest X-ray shows clear lung fields, no infiltrates or effusions',
            conclusion='No acute cardiopulmonary disease',
            recommendations='Routine follow-up in 1 year',
            status='final',
            report_date='2024-10-25',
            ordering_provider='Dr. Martinez',
            confidence=0.97,
            source=SourceContext(
                text='Radiology Report: Chest X-ray clear, no acute disease',
                start_index=300,
                end_index=353
            )
        )
        
        # Verify all fields set correctly
        self.assertEqual(diagnostic_report.report_id, 'rpt-001')
        self.assertEqual(diagnostic_report.report_type, 'radiology')
        self.assertEqual(diagnostic_report.findings, 'Chest X-ray shows clear lung fields, no infiltrates or effusions')
        self.assertEqual(diagnostic_report.conclusion, 'No acute cardiopulmonary disease')
        self.assertEqual(diagnostic_report.recommendations, 'Routine follow-up in 1 year')
        self.assertEqual(diagnostic_report.status, 'final')
        self.assertEqual(diagnostic_report.report_date, '2024-10-25')
        self.assertEqual(diagnostic_report.ordering_provider, 'Dr. Martinez')
        self.assertEqual(diagnostic_report.confidence, 0.97)
    
    def test_diagnostic_report_model_minimal_required_data(self):
        """Test DiagnosticReport model with only required fields."""
        diagnostic_report = DiagnosticReport(
            report_type='lab',
            findings='Hemoglobin A1c: 6.5%',
            confidence=0.89,
            source=SourceContext(
                text='HbA1c result',
                start_index=0,
                end_index=12
            )
        )
        
        # Verify required fields
        self.assertEqual(diagnostic_report.report_type, 'lab')
        self.assertEqual(diagnostic_report.findings, 'Hemoglobin A1c: 6.5%')
        
        # Verify optional fields default properly
        self.assertIsNone(diagnostic_report.report_id)
        self.assertIsNone(diagnostic_report.conclusion)
        self.assertIsNone(diagnostic_report.recommendations)
        self.assertIsNone(diagnostic_report.status)
        self.assertIsNone(diagnostic_report.report_date)
        self.assertIsNone(diagnostic_report.ordering_provider)
    
    def test_diagnostic_report_model_missing_required_fields(self):
        """Test that missing required fields raise ValidationError."""
        # Missing report_type
        with self.assertRaises(ValidationError) as context:
            DiagnosticReport(
                findings='Test findings',
                confidence=0.9,
                source=SourceContext(text='test', start_index=0, end_index=4)
            )
        self.assertIn('report_type', str(context.exception))
        
        # Missing findings
        with self.assertRaises(ValidationError) as context:
            DiagnosticReport(
                report_type='lab',
                confidence=0.9,
                source=SourceContext(text='test', start_index=0, end_index=4)
            )
        self.assertIn('findings', str(context.exception))
    
    def test_diagnostic_report_model_invalid_confidence(self):
        """Test that confidence outside 0.0-1.0 range raises ValidationError."""
        with self.assertRaises(ValidationError):
            DiagnosticReport(
                report_type='pathology',
                findings='Biopsy results',
                confidence=1.3,  # Invalid: > 1.0
                source=SourceContext(text='test', start_index=0, end_index=4)
            )
    
    def test_diagnostic_report_serialization(self):
        """Test that DiagnosticReport serializes to dict correctly."""
        diagnostic_report = DiagnosticReport(
            report_type='cardiology',
            findings='EKG shows normal sinus rhythm',
            conclusion='Normal EKG',
            status='final',
            report_date='2024-10-26',
            confidence=0.94,
            source=SourceContext(text='EKG report', start_index=100, end_index=110)
        )
        
        report_dict = diagnostic_report.model_dump()
        
        # Verify dict structure
        self.assertIsInstance(report_dict, dict)
        self.assertEqual(report_dict['report_type'], 'cardiology')
        self.assertEqual(report_dict['findings'], 'EKG shows normal sinus rhythm')
        self.assertEqual(report_dict['conclusion'], 'Normal EKG')
        self.assertEqual(report_dict['status'], 'final')
        self.assertEqual(report_dict['confidence'], 0.94)
    
    def test_diagnostic_report_deserialization(self):
        """Test that DiagnosticReport can be created from dict."""
        report_dict = {
            'report_type': 'lab',
            'findings': 'CBC: WBC 7.5, Hgb 14.2, Plt 250',
            'conclusion': 'Normal complete blood count',
            'status': 'final',
            'report_date': '2024-10-24',
            'ordering_provider': 'Dr. Lee',
            'confidence': 0.96,
            'source': {
                'text': 'Lab results',
                'start_index': 200,
                'end_index': 211
            }
        }
        
        diagnostic_report = DiagnosticReport(**report_dict)
        
        # Verify deserialization worked
        self.assertEqual(diagnostic_report.report_type, 'lab')
        self.assertEqual(diagnostic_report.findings, 'CBC: WBC 7.5, Hgb 14.2, Plt 250')
        self.assertEqual(diagnostic_report.ordering_provider, 'Dr. Lee')
    
    def test_diagnostic_report_in_structured_extraction(self):
        """Test DiagnosticReport integration into StructuredMedicalExtraction."""
        extraction = StructuredMedicalExtraction(
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[],
            procedures=[],
            providers=[],
            encounters=[],
            service_requests=[],
            diagnostic_reports=[
                DiagnosticReport(
                    report_type='radiology',
                    findings='CT scan shows no abnormalities',
                    conclusion='Normal study',
                    confidence=0.95,
                    source=SourceContext(text='CT report', start_index=0, end_index=9)
                )
            ],
            extraction_timestamp='2024-10-29T12:00:00',
            document_type='radiology_report'
        )
        
        # Verify diagnostic report in extraction
        self.assertEqual(len(extraction.diagnostic_reports), 1)
        self.assertEqual(extraction.diagnostic_reports[0].report_type, 'radiology')
        self.assertEqual(extraction.diagnostic_reports[0].findings, 'CT scan shows no abnormalities')
    
    def test_confidence_average_includes_diagnostic_reports(self):
        """Test that confidence_average calculation includes diagnostic reports."""
        extraction = StructuredMedicalExtraction(
            conditions=[],
            medications=[],
            vital_signs=[],
            lab_results=[],
            procedures=[],
            providers=[],
            encounters=[],
            service_requests=[],
            diagnostic_reports=[
                DiagnosticReport(
                    report_type='lab',
                    findings='Test 1',
                    confidence=0.80,
                    source=SourceContext(text='test1', start_index=0, end_index=5)
                ),
                DiagnosticReport(
                    report_type='radiology',
                    findings='Test 2',
                    confidence=0.90,
                    source=SourceContext(text='test2', start_index=6, end_index=11)
                )
            ],
            extraction_timestamp='2024-10-29T12:00:00'
        )
        
        # Confidence average should be (0.80 + 0.90) / 2 = 0.85
        self.assertEqual(extraction.confidence_average, 0.850)


if __name__ == '__main__':
    unittest.main()

