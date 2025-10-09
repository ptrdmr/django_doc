"""
Tests for medication data extraction and enrichment utilities.
"""

from django.test import TestCase
from datetime import datetime

from apps.reports.utils.medication_utils import (
    normalize_medication_name,
    get_therapeutic_class,
    parse_dosage_text,
    extract_medication_from_resource,
    parse_date,
    enrich_medication_list,
    group_medications_by_class,
    detect_duplicate_medications,
    get_medication_summary,
    THERAPEUTIC_CLASSES,
    STATUS_DISPLAY,
)


class NormalizeMedicationNameTests(TestCase):
    """Tests for normalize_medication_name function."""
    
    def test_normalize_simple_name(self):
        """Test normalization of simple medication names."""
        self.assertEqual(normalize_medication_name('Lisinopril'), 'lisinopril')
        self.assertEqual(normalize_medication_name('METFORMIN'), 'metformin')
    
    def test_normalize_with_dosage_form(self):
        """Test removal of dosage forms."""
        self.assertEqual(normalize_medication_name('Albuterol inhaler'), 'albuterol')
        self.assertEqual(normalize_medication_name('Aspirin tablet'), 'aspirin')
        self.assertEqual(normalize_medication_name('Insulin injection'), 'insulin')
    
    def test_normalize_with_dosage_amount(self):
        """Test removal of dosage amounts."""
        self.assertEqual(normalize_medication_name('Lisinopril 10mg'), 'lisinopril')
        self.assertEqual(normalize_medication_name('Metformin 500 mg'), 'metformin')
        self.assertEqual(normalize_medication_name('Albuterol 2 puffs'), 'albuterol')
    
    def test_normalize_complex_name(self):
        """Test normalization of complex medication names."""
        result = normalize_medication_name('Albuterol inhaler 2 puffs')
        self.assertEqual(result, 'albuterol')
        
        result = normalize_medication_name('Insulin injection 10 units')
        self.assertEqual(result, 'insulin')
    
    def test_normalize_empty_or_none(self):
        """Test normalization of empty or None values."""
        self.assertEqual(normalize_medication_name(''), '')
        self.assertEqual(normalize_medication_name(None), '')
    
    def test_normalize_preserves_base_name(self):
        """Test that base medication name is preserved."""
        result = normalize_medication_name('Omeprazole capsule 20mg oral')
        self.assertEqual(result, 'omeprazole')


class GetTherapeuticClassTests(TestCase):
    """Tests for get_therapeutic_class function."""
    
    def test_cardiovascular_medications(self):
        """Test classification of cardiovascular medications."""
        self.assertEqual(get_therapeutic_class('Lisinopril'), 'ACE Inhibitors')
        self.assertEqual(get_therapeutic_class('Atorvastatin'), 'Statins')
        self.assertEqual(get_therapeutic_class('Metoprolol'), 'Beta Blockers')
    
    def test_diabetes_medications(self):
        """Test classification of diabetes medications."""
        self.assertEqual(get_therapeutic_class('Metformin'), 'Biguanides')
        self.assertEqual(get_therapeutic_class('Insulin'), 'Insulin')
    
    def test_respiratory_medications(self):
        """Test classification of respiratory medications."""
        self.assertEqual(get_therapeutic_class('Albuterol'), 'Bronchodilators')
        self.assertEqual(get_therapeutic_class('Prednisone'), 'Oral Corticosteroids')
    
    def test_gi_medications(self):
        """Test classification of GI medications."""
        self.assertEqual(get_therapeutic_class('Omeprazole'), 'Proton Pump Inhibitors')
        self.assertEqual(get_therapeutic_class('Famotidine'), 'H2 Blockers')
    
    def test_unknown_medication(self):
        """Test classification of unknown medications."""
        self.assertEqual(get_therapeutic_class('UnknownDrug123'), 'Other')
    
    def test_classification_with_dosage_forms(self):
        """Test classification works with dosage forms included."""
        self.assertEqual(get_therapeutic_class('Albuterol inhaler'), 'Bronchodilators')
        self.assertEqual(get_therapeutic_class('Omeprazole 20mg'), 'Proton Pump Inhibitors')


class ParseDosageTextTests(TestCase):
    """Tests for parse_dosage_text function."""
    
    def test_parse_simple_dosage(self):
        """Test parsing simple dosage amounts."""
        result = parse_dosage_text('10mg')
        self.assertEqual(result['amount'], '10mg')
        
        result = parse_dosage_text('500 mg')
        self.assertEqual(result['amount'], '500 mg')
    
    def test_parse_dosage_with_frequency(self):
        """Test parsing dosage with frequency."""
        result = parse_dosage_text('10mg once daily')
        self.assertEqual(result['amount'], '10mg')
        self.assertEqual(result['frequency'], 'once daily')
        
        result = parse_dosage_text('500mg twice a day')
        self.assertEqual(result['amount'], '500mg')
        self.assertEqual(result['frequency'], 'twice a day')
    
    def test_parse_as_needed_dosage(self):
        """Test parsing as-needed dosages."""
        result = parse_dosage_text('2 puffs as needed')
        self.assertEqual(result['amount'], '2 puffs')
        self.assertEqual(result['frequency'], 'as needed')
        
        result = parse_dosage_text('1 tablet prn')
        self.assertEqual(result['amount'], '1 tablet')
        self.assertEqual(result['frequency'], 'as needed')
    
    def test_parse_with_route(self):
        """Test parsing dosage with route."""
        result = parse_dosage_text('10mg oral once daily')
        self.assertEqual(result['amount'], '10mg')
        self.assertEqual(result['frequency'], 'once daily')
        self.assertEqual(result['route'], 'oral')
        
        result = parse_dosage_text('100mg subcutaneous')
        self.assertEqual(result['route'], 'subcutaneous')
    
    def test_parse_bedtime_dosage(self):
        """Test parsing bedtime dosages."""
        result = parse_dosage_text('10mg at bedtime')
        self.assertEqual(result['frequency'], 'at bedtime')
        
        result = parse_dosage_text('5mg qhs')
        self.assertEqual(result['frequency'], 'at bedtime')
    
    def test_parse_with_meals(self):
        """Test parsing dosages taken with meals."""
        result = parse_dosage_text('500mg with meals')
        self.assertEqual(result['frequency'], 'with meals')
    
    def test_parse_empty_or_none(self):
        """Test parsing empty or None dosage text."""
        result = parse_dosage_text('')
        self.assertIsNone(result['amount'])
        self.assertIsNone(result['frequency'])
        
        result = parse_dosage_text(None)
        self.assertIsNone(result['amount'])


class ExtractMedicationFromResourceTests(TestCase):
    """Tests for extract_medication_from_resource function."""
    
    def test_extract_basic_medication(self):
        """Test extraction of basic medication data."""
        resource = {
            'resourceType': 'MedicationStatement',
            'id': 'med-123',
            'status': 'active',
            'medicationCodeableConcept': {
                'text': 'Lisinopril'
            },
            'dosage': [{
                'text': '10mg once daily'
            }]
        }
        
        result = extract_medication_from_resource(resource)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['id'], 'med-123')
        self.assertEqual(result['name'], 'Lisinopril')
        self.assertEqual(result['status'], 'active')
        self.assertEqual(result['status_display'], 'Active')
        self.assertEqual(result['dosage_text'], '10mg once daily')
        self.assertEqual(result['dosage_amount'], '10mg')
        self.assertEqual(result['therapeutic_class'], 'ACE Inhibitors')
    
    def test_extract_with_coding(self):
        """Test extraction when medication uses coding instead of text."""
        resource = {
            'resourceType': 'MedicationStatement',
            'id': 'med-456',
            'status': 'active',
            'medicationCodeableConcept': {
                'coding': [{
                    'system': 'http://www.nlm.nih.gov/research/umls/rxnorm',
                    'code': '314076',
                    'display': 'Metformin'
                }]
            }
        }
        
        result = extract_medication_from_resource(resource)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'Metformin')
        self.assertEqual(result['therapeutic_class'], 'Biguanides')
    
    def test_extract_with_dates(self):
        """Test extraction of medication with dates."""
        resource = {
            'resourceType': 'MedicationStatement',
            'id': 'med-789',
            'status': 'active',
            'medicationCodeableConcept': {
                'text': 'Atorvastatin'
            },
            'effectiveDateTime': '2024-01-15T10:30:00Z',
            'meta': {
                'lastUpdated': '2024-01-15T10:30:00Z'
            }
        }
        
        result = extract_medication_from_resource(resource)
        
        self.assertIsNotNone(result)
        self.assertIsInstance(result['effective_date'], datetime)
        self.assertIsInstance(result['last_updated'], datetime)
    
    def test_extract_with_confidence(self):
        """Test extraction of medication with confidence score."""
        resource = {
            'resourceType': 'MedicationStatement',
            'id': 'med-999',
            'status': 'active',
            'medicationCodeableConcept': {
                'text': 'Omeprazole'
            },
            'extension': [{
                'url': 'http://hl7.org/fhir/StructureDefinition/data-confidence',
                'valueDecimal': 0.95
            }]
        }
        
        result = extract_medication_from_resource(resource)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['confidence'], 0.95)
    
    def test_extract_invalid_resource(self):
        """Test extraction returns None for invalid resources."""
        # Wrong resource type
        result = extract_medication_from_resource({
            'resourceType': 'Observation',
            'id': 'obs-123'
        })
        self.assertIsNone(result)
        
        # Missing medication name
        result = extract_medication_from_resource({
            'resourceType': 'MedicationStatement',
            'id': 'med-123',
            'status': 'active'
        })
        self.assertIsNone(result)
        
        # Not a dict
        result = extract_medication_from_resource("invalid")
        self.assertIsNone(result)
    
    def test_extract_different_statuses(self):
        """Test extraction of medications with different statuses."""
        statuses = ['active', 'completed', 'stopped', 'on-hold', 'unknown']
        
        for status in statuses:
            resource = {
                'resourceType': 'MedicationStatement',
                'id': f'med-{status}',
                'status': status,
                'medicationCodeableConcept': {
                    'text': 'Test Med'
                }
            }
            
            result = extract_medication_from_resource(resource)
            self.assertIsNotNone(result)
            self.assertEqual(result['status'], status)
            self.assertIn(result['status_display'], STATUS_DISPLAY.values())


class ParseDateTests(TestCase):
    """Tests for parse_date function."""
    
    def test_parse_iso_with_microseconds(self):
        """Test parsing ISO format with microseconds."""
        date_str = '2024-01-15T10:30:45.123456Z'
        result = parse_date(date_str)
        
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.year, 2024)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 15)
    
    def test_parse_iso_without_microseconds(self):
        """Test parsing ISO format without microseconds."""
        date_str = '2024-01-15T10:30:45Z'
        result = parse_date(date_str)
        
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.hour, 10)
        self.assertEqual(result.minute, 30)
    
    def test_parse_date_only(self):
        """Test parsing date-only format."""
        date_str = '2024-01-15'
        result = parse_date(date_str)
        
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.year, 2024)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 15)
    
    def test_parse_invalid_date(self):
        """Test parsing invalid date strings."""
        self.assertIsNone(parse_date('invalid-date'))
        self.assertIsNone(parse_date(''))
        self.assertIsNone(parse_date(None))
        self.assertIsNone(parse_date(123))  # Not a string


class EnrichMedicationListTests(TestCase):
    """Tests for enrich_medication_list function."""
    
    def test_enrich_from_bundle(self):
        """Test enriching medication list from FHIR bundle."""
        bundle = {
            'resourceType': 'Bundle',
            'entry': [
                {
                    'resource': {
                        'resourceType': 'MedicationStatement',
                        'id': 'med-1',
                        'status': 'active',
                        'medicationCodeableConcept': {
                            'text': 'Lisinopril'
                        },
                        'dosage': [{'text': '10mg'}]
                    }
                },
                {
                    'resource': {
                        'resourceType': 'MedicationStatement',
                        'id': 'med-2',
                        'status': 'active',
                        'medicationCodeableConcept': {
                            'text': 'Metformin'
                        },
                        'dosage': [{'text': '500mg'}]
                    }
                }
            ]
        }
        
        result = enrich_medication_list(bundle)
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['name'], 'Lisinopril')
        self.assertEqual(result[1]['name'], 'Metformin')
    
    def test_enrich_from_resource_list(self):
        """Test enriching medication list from list of resources."""
        resources = [
            {
                'resourceType': 'MedicationStatement',
                'id': 'med-1',
                'status': 'active',
                'medicationCodeableConcept': {
                    'text': 'Atorvastatin'
                }
            },
            {
                'resourceType': 'Observation',
                'id': 'obs-1'
            },  # Should be filtered out
            {
                'resourceType': 'MedicationStatement',
                'id': 'med-2',
                'status': 'stopped',
                'medicationCodeableConcept': {
                    'text': 'Aspirin'
                }
            }
        ]
        
        result = enrich_medication_list(resources)
        
        self.assertEqual(len(result), 2)
        # Active should come before stopped
        self.assertEqual(result[0]['status'], 'active')
        self.assertEqual(result[1]['status'], 'stopped')
    
    def test_enrich_sorts_by_status(self):
        """Test that medications are sorted by status priority."""
        resources = [
            {
                'resourceType': 'MedicationStatement',
                'id': 'med-1',
                'status': 'stopped',
                'medicationCodeableConcept': {'text': 'Med A'}
            },
            {
                'resourceType': 'MedicationStatement',
                'id': 'med-2',
                'status': 'active',
                'medicationCodeableConcept': {'text': 'Med B'}
            },
            {
                'resourceType': 'MedicationStatement',
                'id': 'med-3',
                'status': 'completed',
                'medicationCodeableConcept': {'text': 'Med C'}
            }
        ]
        
        result = enrich_medication_list(resources)
        
        # Should be sorted: active, completed, stopped
        self.assertEqual(result[0]['status'], 'active')
        self.assertEqual(result[1]['status'], 'completed')
        self.assertEqual(result[2]['status'], 'stopped')
    
    def test_enrich_empty_data(self):
        """Test enriching with empty data."""
        self.assertEqual(enrich_medication_list([]), [])
        self.assertEqual(enrich_medication_list({}), [])
        self.assertEqual(enrich_medication_list({'entry': []}), [])


class GroupMedicationsByClassTests(TestCase):
    """Tests for group_medications_by_class function."""
    
    def test_group_by_therapeutic_class(self):
        """Test grouping medications by therapeutic class."""
        medications = [
            {'name': 'Lisinopril', 'therapeutic_class': 'ACE Inhibitors'},
            {'name': 'Enalapril', 'therapeutic_class': 'ACE Inhibitors'},
            {'name': 'Metformin', 'therapeutic_class': 'Biguanides'},
            {'name': 'Atorvastatin', 'therapeutic_class': 'Statins'},
        ]
        
        result = group_medications_by_class(medications)
        
        self.assertEqual(len(result), 3)
        self.assertEqual(len(result['ACE Inhibitors']), 2)
        self.assertEqual(len(result['Biguanides']), 1)
        self.assertEqual(len(result['Statins']), 1)
    
    def test_group_preserves_medication_data(self):
        """Test that grouping preserves all medication data."""
        medications = [
            {
                'name': 'Lisinopril',
                'therapeutic_class': 'ACE Inhibitors',
                'dosage_text': '10mg',
                'status': 'active'
            }
        ]
        
        result = group_medications_by_class(medications)
        
        grouped_med = result['ACE Inhibitors'][0]
        self.assertEqual(grouped_med['name'], 'Lisinopril')
        self.assertEqual(grouped_med['dosage_text'], '10mg')
        self.assertEqual(grouped_med['status'], 'active')
    
    def test_group_empty_list(self):
        """Test grouping empty medication list."""
        result = group_medications_by_class([])
        self.assertEqual(result, {})
    
    def test_group_handles_other_class(self):
        """Test grouping handles "Other" therapeutic class."""
        medications = [
            {'name': 'Unknown Med', 'therapeutic_class': 'Other'}
        ]
        
        result = group_medications_by_class(medications)
        
        self.assertIn('Other', result)
        self.assertEqual(len(result['Other']), 1)


class DetectDuplicateMedicationsTests(TestCase):
    """Tests for detect_duplicate_medications function."""
    
    def test_detect_exact_duplicates(self):
        """Test detection of exact duplicate medications."""
        medications = [
            {
                'name': 'Lisinopril 10mg',
                'normalized_name': 'lisinopril',
                'status': 'active'
            },
            {
                'name': 'Lisinopril 10mg tablet',
                'normalized_name': 'lisinopril',
                'status': 'active'
            }
        ]
        
        result = detect_duplicate_medications(medications)
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['reason'], 'Same medication name')
    
    def test_no_duplicates_different_names(self):
        """Test no duplicates detected for different medications."""
        medications = [
            {
                'name': 'Lisinopril',
                'normalized_name': 'lisinopril',
                'status': 'active'
            },
            {
                'name': 'Metformin',
                'normalized_name': 'metformin',
                'status': 'active'
            }
        ]
        
        result = detect_duplicate_medications(medications)
        
        self.assertEqual(len(result), 0)
    
    def test_no_duplicates_inactive_meds(self):
        """Test no duplicates detected when one is inactive."""
        medications = [
            {
                'name': 'Lisinopril',
                'normalized_name': 'lisinopril',
                'status': 'active'
            },
            {
                'name': 'Lisinopril',
                'normalized_name': 'lisinopril',
                'status': 'stopped'
            }
        ]
        
        result = detect_duplicate_medications(medications)
        
        # Should be 0 because one is stopped (not active/intended)
        self.assertEqual(len(result), 0)
    
    def test_detect_multiple_duplicates(self):
        """Test detection of multiple duplicate medications."""
        medications = [
            {
                'name': 'Lisinopril 10mg',
                'normalized_name': 'lisinopril',
                'status': 'active'
            },
            {
                'name': 'Lisinopril 20mg',
                'normalized_name': 'lisinopril',
                'status': 'active'
            },
            {
                'name': 'Metformin 500mg',
                'normalized_name': 'metformin',
                'status': 'active'
            },
            {
                'name': 'Metformin 1000mg',
                'normalized_name': 'metformin',
                'status': 'intended'
            }
        ]
        
        result = detect_duplicate_medications(medications)
        
        # Should detect 2 duplicate pairs
        self.assertEqual(len(result), 2)


class GetMedicationSummaryTests(TestCase):
    """Tests for get_medication_summary function."""
    
    def test_summary_basic_counts(self):
        """Test summary includes basic medication counts."""
        medications = [
            {'status': 'active', 'therapeutic_class': 'ACE Inhibitors', 'normalized_name': 'lisinopril'},
            {'status': 'active', 'therapeutic_class': 'Statins', 'normalized_name': 'atorvastatin'},
            {'status': 'stopped', 'therapeutic_class': 'NSAIDs', 'normalized_name': 'ibuprofen'},
        ]
        
        result = get_medication_summary(medications)
        
        self.assertEqual(result['total_medications'], 3)
        self.assertEqual(result['active_medications'], 2)
        self.assertEqual(result['inactive_medications'], 1)
    
    def test_summary_class_breakdown(self):
        """Test summary includes therapeutic class breakdown."""
        medications = [
            {'status': 'active', 'therapeutic_class': 'ACE Inhibitors', 'normalized_name': 'lisinopril'},
            {'status': 'active', 'therapeutic_class': 'ACE Inhibitors', 'normalized_name': 'enalapril'},
            {'status': 'active', 'therapeutic_class': 'Statins', 'normalized_name': 'atorvastatin'},
        ]
        
        result = get_medication_summary(medications)
        
        self.assertEqual(result['therapeutic_classes'], 2)
        self.assertEqual(result['class_breakdown']['ACE Inhibitors'], 2)
        self.assertEqual(result['class_breakdown']['Statins'], 1)
    
    def test_summary_includes_duplicates(self):
        """Test summary includes duplicate count."""
        medications = [
            {
                'name': 'Lisinopril',
                'normalized_name': 'lisinopril',
                'status': 'active',
                'therapeutic_class': 'ACE Inhibitors'
            },
            {
                'name': 'Lisinopril',
                'normalized_name': 'lisinopril',
                'status': 'active',
                'therapeutic_class': 'ACE Inhibitors'
            }
        ]
        
        result = get_medication_summary(medications)
        
        self.assertEqual(result['potential_duplicates'], 1)
    
    def test_summary_empty_list(self):
        """Test summary for empty medication list."""
        result = get_medication_summary([])
        
        self.assertEqual(result['total_medications'], 0)
        self.assertEqual(result['active_medications'], 0)
        self.assertEqual(result['therapeutic_classes'], 0)
        self.assertEqual(result['potential_duplicates'], 0)

