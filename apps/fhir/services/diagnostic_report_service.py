"""
DiagnosticReport Service for FHIR Resource Processing

This service handles the conversion of extracted diagnostic report data into proper FHIR 
DiagnosticReport resources for procedures like EKG, X-rays, lab results, etc.
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4
from datetime import datetime

logger = logging.getLogger(__name__)


class DiagnosticReportService:
    """
    Service for processing diagnostic report data into FHIR DiagnosticReport resources.
    
    Handles various types of diagnostic procedures including lab results, imaging studies,
    EKGs, and other diagnostic tests with their conclusions and results.
    """
    
    def __init__(self):
        self.logger = logger
        
    def process_diagnostic_reports(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process diagnostic reports with complete procedure and result information.
        
        Args:
            extracted_data: Dictionary containing extracted medical data with diagnostic reports
            
        Returns:
            List of FHIR DiagnosticReport resources
        """
        reports = []
        patient_id = extracted_data.get('patient_id')
        
        # Handle different diagnostic report data structures
        report_data = self._extract_diagnostic_report_data(extracted_data)
        
        for report in report_data:
            try:
                report_resource = self._create_diagnostic_report(report, patient_id)
                if report_resource:
                    reports.append(report_resource)
                    self.logger.info(f"Created DiagnosticReport for: {report.get('procedure_type', 'Unknown procedure')}")
            except Exception as e:
                self.logger.error(f"Failed to create DiagnosticReport for {report}: {e}")
                continue
                
        self.logger.info(f"Processed {len(reports)} diagnostic reports from {len(report_data)} extracted entries")
        return reports
        
    def _extract_diagnostic_report_data(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract diagnostic report data from various possible structures in extracted data.
        
        Args:
            extracted_data: Raw extracted data that may contain diagnostic reports in different formats
            
        Returns:
            List of normalized diagnostic report dictionaries
        """
        report_data = []
        
        # Handle direct diagnostic_reports list
        if 'diagnostic_reports' in extracted_data and isinstance(extracted_data['diagnostic_reports'], list):
            report_data.extend(extracted_data['diagnostic_reports'])
            
        # Handle procedures that are actually diagnostic reports
        if 'procedures' in extracted_data and isinstance(extracted_data['procedures'], list):
            for proc in extracted_data['procedures']:
                if self._is_diagnostic_procedure(proc):
                    report_data.append(self._convert_procedure_to_report(proc))
                    
        # Handle fields from document analyzer
        if 'fields' in extracted_data:
            for field in extracted_data['fields']:
                if isinstance(field, dict):
                    label = field.get('label', '').lower()
                    if any(term in label for term in ['lab', 'test', 'result', 'report', 'ekg', 'ecg', 'x-ray', 'imaging', 'ultrasound', 'ct', 'mri']):
                        # Convert field to diagnostic report format
                        report = self._convert_field_to_report(field)
                        if report:
                            report_data.append(report)
                            
        # Handle string-based lab results or test results
        if 'lab_results' in extracted_data:
            if isinstance(extracted_data['lab_results'], str):
                string_reports = self._parse_lab_results_string(extracted_data['lab_results'])
                report_data.extend(string_reports)
            elif isinstance(extracted_data['lab_results'], list):
                report_data.extend(extracted_data['lab_results'])
                
        return report_data
        
    def _is_diagnostic_procedure(self, procedure: Dict[str, Any]) -> bool:
        """
        Determine if a procedure is actually a diagnostic report.
        
        Args:
            procedure: Procedure data dictionary
            
        Returns:
            True if this should be treated as a diagnostic report
        """
        proc_name = procedure.get('name', '').lower()
        proc_type = procedure.get('type', '').lower()
        
        diagnostic_indicators = [
            'lab', 'test', 'result', 'ekg', 'ecg', 'x-ray', 'xray', 
            'imaging', 'ultrasound', 'ct scan', 'mri', 'blood test',
            'urine test', 'culture', 'biopsy', 'pathology'
        ]
        
        return any(indicator in proc_name or indicator in proc_type for indicator in diagnostic_indicators)
        
    def _convert_procedure_to_report(self, procedure: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a procedure dictionary to a diagnostic report format.
        
        Args:
            procedure: Procedure data dictionary
            
        Returns:
            Diagnostic report data dictionary
        """
        return {
            'procedure_type': procedure.get('name', procedure.get('type')),
            'date': procedure.get('date'),
            'conclusion': procedure.get('result', procedure.get('outcome')),
            'status': procedure.get('status', 'final'),
            'source': 'procedure_conversion'
        }
        
    def _convert_field_to_report(self, field: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert a document analyzer field into a diagnostic report dictionary.
        
        Args:
            field: Field dictionary from document analyzer
            
        Returns:
            Normalized diagnostic report dictionary or None
        """
        value = field.get('value', '')
        label = field.get('label', '')
        
        if not value:
            return None
            
        # Parse diagnostic report information from the field
        report_info = self._parse_diagnostic_text(value, label)
        if report_info['procedure_type']:
            return {
                'procedure_type': report_info['procedure_type'],
                'date': report_info.get('date'),
                'conclusion': report_info.get('conclusion'),
                'status': 'final',
                'confidence': field.get('confidence', 0.8),
                'source': 'document_field'
            }
        return None
        
    def _parse_lab_results_string(self, lab_string: str) -> List[Dict[str, Any]]:
        """
        Parse a string containing multiple lab results or test results.
        
        Args:
            lab_string: String containing lab results
            
        Returns:
            List of diagnostic report dictionaries
        """
        reports = []
        
        # Split by common separators
        separators = [';', '\n', '|']
        items = [lab_string]
        
        for sep in separators:
            new_items = []
            for item in items:
                new_items.extend([i.strip() for i in item.split(sep) if i.strip()])
            items = new_items
            
        for item in items:
            report_info = self._parse_diagnostic_text(item, 'lab_result')
            if report_info['procedure_type']:
                reports.append({
                    'procedure_type': report_info['procedure_type'],
                    'date': report_info.get('date'),
                    'conclusion': report_info.get('conclusion'),
                    'status': 'final',
                    'source': 'string_parsing'
                })
                
        return reports
        
    def _parse_diagnostic_text(self, text: str, context: str = '') -> Dict[str, Any]:
        """
        Parse diagnostic information from a text string.
        
        Args:
            text: Text containing diagnostic information
            context: Context about the type of diagnostic (e.g., 'lab_result', 'ekg')
            
        Returns:
            Dictionary with parsed diagnostic components
        """
        import re
        
        text = text.strip()
        if not text:
            return {'procedure_type': None}
            
        # Initialize result
        result = {
            'procedure_type': None,
            'date': None,
            'conclusion': None
        }
        
        # Common diagnostic procedure patterns
        procedure_patterns = [
            r'(EKG|ECG|electrocardiogram)',
            r'(chest x-ray|chest xray|CXR)',
            r'(CT scan|computed tomography)',
            r'(MRI|magnetic resonance)',
            r'(ultrasound|US|echo)',
            r'(blood test|lab work|laboratory)',
            r'(urine test|urinalysis|UA)',
            r'(culture|blood culture)',
            r'(biopsy|pathology)',
            r'([A-Z][a-z]+ test)',  # Generic test pattern
        ]
        
        # Date patterns
        date_patterns = [
            r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            r'(\d{4}-\d{2}-\d{2})',
            r'(on \d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            r'(dated \d{1,2}[-/]\d{1,2}[-/]\d{2,4})'
        ]
        
        text_lower = text.lower()
        
        # Extract procedure type
        procedure_type = None
        for pattern in procedure_patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                procedure_type = match.group(1)
                break
                
        # If no specific procedure found, try to infer from context
        if not procedure_type:
            if 'lab' in context.lower() or 'test' in text_lower:
                # Try to extract the test name
                test_match = re.search(r'([A-Za-z\s]+)\s*(?:test|level|count)', text, re.IGNORECASE)
                if test_match:
                    procedure_type = f"{test_match.group(1).strip()} test"
                else:
                    procedure_type = "Laboratory test"
            elif 'ekg' in context.lower() or 'ecg' in text_lower:
                procedure_type = "EKG"
            elif 'imaging' in context.lower():
                procedure_type = "Imaging study"
            else:
                # Use the first few words as procedure type
                words = text.split()[:3]
                procedure_type = ' '.join(words)
                
        result['procedure_type'] = procedure_type
        
        # Extract date
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                result['date'] = match.group(1).replace('on ', '').replace('dated ', '')
                break
                
        # Extract conclusion/result (everything after common result indicators)
        conclusion_indicators = [
            r'result[s]?[:\s]+(.+)',
            r'conclusion[:\s]+(.+)',
            r'finding[s]?[:\s]+(.+)',
            r'impression[:\s]+(.+)',
            r'shows?[:\s]+(.+)',
            r'reveals?[:\s]+(.+)'
        ]
        
        for pattern in conclusion_indicators:
            match = re.search(pattern, text_lower)
            if match:
                result['conclusion'] = match.group(1).strip()
                break
                
        # If no specific conclusion found, use the whole text as conclusion
        if not result['conclusion'] and procedure_type:
            # Remove the procedure type from the text to get the conclusion
            conclusion_text = re.sub(re.escape(procedure_type.lower()), '', text_lower).strip()
            conclusion_text = re.sub(r'^[:\-\s]+', '', conclusion_text)  # Remove leading punctuation
            if conclusion_text:
                result['conclusion'] = conclusion_text
                
        return result
        
    def _create_diagnostic_report(self, report_data: Dict[str, Any], patient_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        Create a DiagnosticReport resource from diagnostic information.
        
        Args:
            report_data: Diagnostic report data dictionary
            patient_id: Patient ID for the resource
            
        Returns:
            FHIR DiagnosticReport resource or None if creation fails
        """
        try:
            procedure_type = report_data.get('procedure_type')
            if not procedure_type:
                self.logger.warning("Diagnostic report missing procedure type, skipping")
                return None
                
            report_id = str(uuid4())
            
            # Create basic DiagnosticReport resource structure
            report_resource = {
                "resourceType": "DiagnosticReport",
                "id": report_id,
                "status": report_data.get('status', 'final'),
                "code": {
                    "text": procedure_type
                },
                "meta": {
                    "versionId": "1",
                    "lastUpdated": datetime.now().isoformat(),
                    "source": f"DiagnosticReportService-{report_data.get('source', 'unknown')}"
                }
            }
            
            # Add patient reference if available
            if patient_id:
                report_resource["subject"] = {
                    "reference": f"Patient/{patient_id}"
                }
                
            # Add effective date if available
            if report_data.get('date'):
                report_resource["effectiveDateTime"] = report_data['date']
                
            # Add conclusion if available
            if report_data.get('conclusion'):
                report_resource["conclusion"] = report_data['conclusion']
                
            # Add category based on procedure type
            category = self._determine_category(procedure_type)
            if category:
                report_resource["category"] = [{
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                        "code": category['code'],
                        "display": category['display']
                    }]
                }]
                
            # Add confidence as extension if available
            if report_data.get('confidence'):
                report_resource["extension"] = [{
                    "url": "http://hl7.org/fhir/StructureDefinition/data-confidence",
                    "valueDecimal": report_data['confidence']
                }]
                
            return report_resource
            
        except Exception as e:
            self.logger.error(f"Failed to create DiagnosticReport: {e}")
            return None
            
    def _determine_category(self, procedure_type: str) -> Optional[Dict[str, str]]:
        """
        Determine the appropriate category for a diagnostic report.
        
        Args:
            procedure_type: Type of diagnostic procedure
            
        Returns:
            Dictionary with category code and display, or None
        """
        procedure_lower = procedure_type.lower()
        
        if any(term in procedure_lower for term in ['lab', 'blood', 'urine', 'culture']):
            return {'code': 'LAB', 'display': 'Laboratory'}
        elif any(term in procedure_lower for term in ['x-ray', 'xray', 'ct', 'mri', 'ultrasound', 'imaging']):
            return {'code': 'RAD', 'display': 'Radiology'}
        elif any(term in procedure_lower for term in ['ekg', 'ecg', 'cardio']):
            return {'code': 'CG', 'display': 'Cardiodiagnostics'}
        elif any(term in procedure_lower for term in ['path', 'biopsy']):
            return {'code': 'PAT', 'display': 'Pathology'}
        else:
            return {'code': 'OTH', 'display': 'Other'}
