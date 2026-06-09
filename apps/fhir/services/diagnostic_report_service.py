"""
DiagnosticReport Service for FHIR Resource Processing

This service handles the conversion of extracted diagnostic report data into proper FHIR 
DiagnosticReport resources for procedures like EKG, X-rays, lab results, etc.
"""

import logging
from collections import defaultdict
from typing import List, Dict, Any, Optional
from uuid import uuid4
from datetime import datetime

from apps.fhir.services.extensions import append_extraction_extensions, source_snippet_from_field
from apps.fhir.services.encounter_linker import normalize_date_parts
from apps.fhir.services.keyword_matching import contains_any_keyword

logger = logging.getLogger(__name__)


class DiagnosticReportService:
    """
    Service for processing diagnostic report data into FHIR DiagnosticReport resources.
    
    Handles various types of diagnostic procedures including lab results, imaging studies,
    EKGs, and other diagnostic tests with their conclusions and results.
    """
    
    # Keyword signatures for fallback lab-panel detection (B1). Each entry maps a
    # canonical panel name to the keywords commonly found in its member tests,
    # a LOINC panel code, and the minimum number of member matches required to
    # confidently assert the panel.
    LAB_PANEL_SIGNATURES = {
        'Comprehensive Metabolic Panel': {
            'keywords': ['glucose', 'bun', 'creatinine', 'sodium', 'potassium',
                         'chloride', 'co2', 'carbon dioxide', 'calcium', 'albumin',
                         'bilirubin', 'alkaline phosphatase', 'ast', 'alt',
                         'total protein', 'egfr'],
            'loinc': '24323-8',
            'min_matches': 8,
        },
        'Basic Metabolic Panel': {
            'keywords': ['glucose', 'bun', 'creatinine', 'sodium', 'potassium',
                         'chloride', 'co2', 'carbon dioxide', 'calcium', 'egfr'],
            'loinc': '24321-2',
            'min_matches': 6,
        },
        'CBC with Differential': {
            'keywords': ['wbc', 'rbc', 'hemoglobin', 'hematocrit', 'platelet',
                         'neutrophil', 'lymphocyte', 'monocyte', 'eosinophil',
                         'basophil', 'mcv', 'mch', 'mchc', 'rdw'],
            'loinc': '57021-8',
            'min_matches': 6,
        },
        'Lipid Panel': {
            'keywords': ['cholesterol', 'hdl', 'ldl', 'triglyceride', 'vldl'],
            'loinc': '24331-1',
            'min_matches': 3,
        },
        'Hemoglobin A1C': {
            'keywords': ['a1c', 'hba1c', 'hemoglobin a1c', 'glycated'],
            'loinc': '4548-4',
            'min_matches': 1,
        },
        'Thyroid Panel': {
            'keywords': ['tsh', 'free t4', 'free t3', 't4', 't3', 'thyroid'],
            'loinc': '24348-5',
            'min_matches': 1,
        },
        'NMR LipoProfile': {
            'keywords': ['ldl-p', 'hdl-p', 'small ldl', 'lp-ir', 'ldl size'],
            'loinc': '63550-2',
            'min_matches': 2,
        },
        'PSA': {
            'keywords': ['psa', 'prostate specific antigen'],
            'loinc': '2857-1',
            'min_matches': 1,
        },
    }

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

        structured = extracted_data.get("structured_data")
        if isinstance(structured, dict):
            structured_reports = structured.get("diagnostic_reports")
            if isinstance(structured_reports, list) and structured_reports:
                report_data.extend(structured_reports)

        # Handle direct diagnostic_reports list (legacy unstructured batching)
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
            procedure_type = (
                report_data.get('procedure_type')
                or report_data.get('report_type')
            )
            if not procedure_type or not isinstance(procedure_type, str):
                procedure_type_stripped = ''
            else:
                procedure_type_stripped = procedure_type.strip()

            if not procedure_type_stripped:
                self.logger.warning("Diagnostic report missing procedure/report type, skipping")
                return None

            findings_blob = report_data.get('findings')
            conclusion_blob = report_data.get('conclusion')

            conclusions: List[str] = []
            if findings_blob:
                conclusions.append(str(findings_blob).strip())
            if conclusion_blob:
                conclusions.append(str(conclusion_blob).strip())
            blended_conclusion = "\n".join(part for part in conclusions if part)
                
            report_id = str(uuid4())
            
            # Create basic DiagnosticReport resource structure
            report_resource = {
                "resourceType": "DiagnosticReport",
                "id": report_id,
                "status": report_data.get('status', 'final'),
                "code": {
                    "text": procedure_type_stripped
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
                
            # Add effective datetime if available
            effective_value = (
                report_data.get('effectiveDateTime')
                or report_data.get('date')
                or report_data.get('report_date')
            )
            if effective_value:
                report_resource["effectiveDateTime"] = effective_value
                
            if blended_conclusion:
                report_resource["conclusion"] = blended_conclusion
                
            # Add category based on procedure type
            category = self._determine_category(procedure_type_stripped)
            if category:
                report_resource["category"] = [{
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                        "code": category['code'],
                        "display": category['display']
                    }]
                }]
                
            append_extraction_extensions(
                report_resource,
                confidence=report_data.get("confidence"),
                source_text=source_snippet_from_field(report_data.get("source")),
            )
                
            return report_resource
            
        except Exception as e:
            self.logger.error(f"Failed to create DiagnosticReport: {e}")
            return None
            
    def synthesize_lab_panels(self, structured_data: Dict[str, Any],
                              lab_observations: List[Dict[str, Any]],
                              patient_id: Optional[str],
                              explicit_reports: Optional[List[Dict[str, Any]]] = None
                              ) -> List[Dict[str, Any]]:
        """
        Synthesize DiagnosticReport resources by grouping lab Observations (B1).

        Many lab documents (e.g. multi-page panels) yield dozens of Observations
        but zero DiagnosticReports because the AI doesn't emit explicit report
        objects for tabular data. This groups the lab Observations into panels so
        the summary can present coherent reports with ``result`` references.

        Grouping strategy (applied independently per draw date so analytes from
        different dates are never fused into one fabricated panel):
            1. Primary: AI-provided ``panel_name`` on each LabResult.
            2. Fallback: keyword signature matching (CMP, CBC, Lipid, etc.).
            3. Remainder: a single "Miscellaneous Lab Results" report.

        Observations already referenced by an explicit DiagnosticReport are
        excluded so we never emit a duplicate panel for the same labs.

        Args:
            structured_data: The model_dump dict; reads ``lab_results``.
            lab_observations: All Observation dicts already created this run; the
                lab-category ones are matched to their source LabResult by name.
            patient_id: Patient UUID for subject reference.
            explicit_reports: DiagnosticReports already produced this run; their
                ``result`` Observation references are excluded from synthesis.

        Returns:
            List of synthesized DiagnosticReport resource dicts (may be empty).
        """
        if not patient_id:
            return []

        lab_results = structured_data.get('lab_results') or []
        if not lab_results:
            return []

        # Map normalized test name -> ordered list of Observation dicts.
        name_to_obs = self._build_lab_observation_index(lab_observations)
        if not name_to_obs:
            self.logger.debug("No lab observations available for panel synthesis")
            return []

        # Observation ids already covered by explicit reports must not be
        # re-synthesized (prevents duplicate panels for the same labs).
        covered_obs_ids = self._collect_reported_observation_ids(explicit_reports)

        # Build the pool of linkable lab entries. Each LabResult consumes a
        # distinct Observation of the same name, so repeated analytes (e.g. two
        # glucose draws) map 1:1 instead of collapsing onto the first one.
        consumed: Dict[str, int] = defaultdict(int)
        entries: List[Dict[str, Any]] = []
        for lab in lab_results:
            if not isinstance(lab, dict):
                continue
            test_name = (lab.get('test_name') or '').strip()
            if not test_name:
                continue
            obs_list = name_to_obs.get(test_name.lower())
            if not obs_list:
                continue
            idx = consumed[test_name.lower()]
            if idx >= len(obs_list):
                continue  # more lab rows than observations for this name
            obs = obs_list[idx]
            consumed[test_name.lower()] += 1
            if not obs.get('id') or obs['id'] in covered_obs_ids:
                continue
            entries.append({
                'test_name': test_name,
                'obs_id': obs['id'],
                'effective': obs.get('effectiveDateTime'),
                'ai_panel': (lab.get('panel_name') or '').strip(),
                'flagged': bool((lab.get('abnormal_flag') or '').strip()),
            })

        if not entries:
            return []

        # Partition entries by normalized draw date so each synthesized panel
        # covers a single date. Undated labs share one bucket.
        date_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for entry in entries:
            date_key = "-".join(normalize_date_parts(entry['effective'])) or "__undated__"
            date_groups[date_key].append(entry)

        reports: List[Dict[str, Any]] = []
        for group_entries in date_groups.values():
            reports.extend(self._group_entries_into_reports(group_entries, patient_id))

        self.logger.info(
            "Synthesized %s lab-panel DiagnosticReport(s) from %s lab result(s)",
            len(reports), len(lab_results),
        )
        return reports

    def _group_entries_into_reports(self, entries: List[Dict[str, Any]],
                                    patient_id: str) -> List[Dict[str, Any]]:
        """Bucket a single date's lab entries into panel DiagnosticReports."""
        panels: Dict[str, Dict[str, Any]] = {}

        def _add_to_panel(panel_name: str, entry: Dict[str, Any]) -> None:
            bucket = panels.setdefault(panel_name, {
                'observation_ids': [], 'effective_dates': [], 'flagged': 0,
            })
            bucket['observation_ids'].append(entry['obs_id'])
            if entry['effective']:
                bucket['effective_dates'].append(entry['effective'])
            if entry['flagged']:
                bucket['flagged'] += 1

        # Phase A (primary): honor AI-provided panel_name.
        remaining = []
        for entry in entries:
            if entry['ai_panel']:
                _add_to_panel(entry['ai_panel'], entry)
            else:
                remaining.append(entry)

        # Phase B (fallback): collection-based signature detection. Check larger
        # panels first (by min_matches desc) so e.g. CMP claims shared analytes
        # before BMP. A panel is asserted only when enough members are present.
        # Keyword membership uses word-boundary matching so "ast" no longer
        # matches "fasting" nor "alt" matches "cobalt".
        ordered_signatures = sorted(
            self.LAB_PANEL_SIGNATURES.items(),
            key=lambda kv: kv[1]['min_matches'], reverse=True,
        )
        for panel_name, sig in ordered_signatures:
            if not remaining:
                break
            matched = [
                e for e in remaining
                if contains_any_keyword(e['test_name'], sig['keywords'])
            ]
            if len(matched) >= sig['min_matches']:
                for entry in matched:
                    _add_to_panel(panel_name, entry)
                matched_ids = {id(e) for e in matched}
                remaining = [e for e in remaining if id(e) not in matched_ids]

        # Phase C: leftover labs become a single catch-all report.
        for entry in remaining:
            _add_to_panel('Miscellaneous Lab Results', entry)

        reports: List[Dict[str, Any]] = []
        for panel_name, bucket in panels.items():
            if not bucket['observation_ids']:
                continue
            report = self._create_panel_report(panel_name, bucket, patient_id)
            if report:
                reports.append(report)
        return reports

    def _collect_reported_observation_ids(
        self, explicit_reports: Optional[List[Dict[str, Any]]]
    ) -> set:
        """Return Observation ids already referenced by explicit DiagnosticReports."""
        covered: set = set()
        for report in explicit_reports or []:
            if not isinstance(report, dict):
                continue
            for ref in report.get('result', []) or []:
                reference = (ref or {}).get('reference', '')
                if reference.startswith('Observation/'):
                    covered.add(reference.split('/', 1)[1])
        return covered

    def _build_lab_observation_index(
        self, observations: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Index lab-category Observations by lowercased code text.

        Returns a name -> ordered list of Observations so repeated analytes
        (multiple draws of the same test) are all retained rather than collapsed
        onto the first occurrence.
        """
        index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for obs in observations or []:
            if not isinstance(obs, dict) or obs.get('resourceType') != 'Observation':
                continue
            if not self._is_lab_observation(obs):
                continue
            name = ((obs.get('code') or {}).get('text') or '').strip().lower()
            if name:
                index[name].append(obs)
        return index

    def _is_lab_observation(self, observation: Dict[str, Any]) -> bool:
        """Detect lab-category Observations via category coding or extraction tag."""
        for cat in observation.get('category', []) or []:
            for coding in (cat.get('coding') or []):
                if (coding.get('code') or '').lower() == 'laboratory':
                    return True
        # Fallback: ObservationService tags structured lab observations.
        meta_tags = (observation.get('meta') or {}).get('tag', []) or []
        for tag in meta_tags:
            display = (tag.get('display') or '').lower()
            if 'lab_result' in display or 'laboratory' in display:
                return True
        return False

    def _create_panel_report(self, panel_name: str, bucket: Dict[str, Any],
                             patient_id: str) -> Optional[Dict[str, Any]]:
        """Build a single DiagnosticReport for a resolved lab panel."""
        loinc = None
        for sig_name, sig in self.LAB_PANEL_SIGNATURES.items():
            if sig_name == panel_name:
                loinc = sig['loinc']
                break

        code_block: Dict[str, Any] = {"text": panel_name}
        if loinc:
            code_block["coding"] = [{
                "system": "http://loinc.org",
                "code": loinc,
                "display": panel_name,
            }]

        report = {
            "resourceType": "DiagnosticReport",
            "id": str(uuid4()),
            "status": "final",
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                    "code": "LAB",
                    "display": "Laboratory",
                }]
            }],
            "code": code_block,
            "subject": {"reference": f"Patient/{patient_id}"},
            "result": [
                {"reference": f"Observation/{obs_id}"}
                for obs_id in bucket['observation_ids']
            ],
            "meta": {
                "versionId": "1",
                "lastUpdated": datetime.now().isoformat(),
                "source": "DiagnosticReportService-panel-synthesis",
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                    "code": "synthesized-panel",
                    "display": "Synthesized lab panel",
                }],
            },
        }

        # Earliest effective date across members (panels share a draw date).
        effective_dates = sorted(d for d in bucket['effective_dates'] if d)
        if effective_dates:
            report["effectiveDateTime"] = effective_dates[0]

        result_count = len(bucket['observation_ids'])
        flagged = bucket['flagged']
        report["conclusion"] = (
            f"{panel_name}: {result_count} result(s)"
            + (f", {flagged} flagged" if flagged else "")
        )

        return report

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
