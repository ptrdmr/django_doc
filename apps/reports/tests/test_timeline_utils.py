"""
Tests for Timeline Utilities.

Comprehensive test suite for FHIR timeline event extraction and processing.
"""

import unittest
from datetime import datetime, timedelta
from apps.reports.utils.timeline_utils import (
    parse_fhir_datetime,
    categorize_encounter_class,
    get_encounter_display_name,
    extract_encounter_events,
    extract_procedure_events,
    calculate_event_duration_days,
    sort_events_by_date,
    calculate_timeline_positions,
    extract_timeline_events,
    get_timeline_summary,
)


class TestParseFhirDatetime(unittest.TestCase):
    """Test FHIR datetime parsing."""
    
    def test_parse_full_datetime_with_microseconds(self):
        """Test parsing full datetime with microseconds."""
        result = parse_fhir_datetime("2024-01-15T10:30:45.123456")
        expected = datetime(2024, 1, 15, 10, 30, 45, 123456)
        self.assertEqual(result, expected)
    
    def test_parse_full_datetime(self):
        """Test parsing full datetime without microseconds."""
        result = parse_fhir_datetime("2024-01-15T10:30:45")
        expected = datetime(2024, 1, 15, 10, 30, 45)
        self.assertEqual(result, expected)
    
    def test_parse_date_only(self):
        """Test parsing date without time."""
        result = parse_fhir_datetime("2024-01-15")
        expected = datetime(2024, 1, 15)
        self.assertEqual(result, expected)
    
    def test_parse_year_month(self):
        """Test parsing year and month only."""
        result = parse_fhir_datetime("2024-01")
        expected = datetime(2024, 1, 1)
        self.assertEqual(result, expected)
    
    def test_parse_year_only(self):
        """Test parsing year only."""
        result = parse_fhir_datetime("2024")
        expected = datetime(2024, 1, 1)
        self.assertEqual(result, expected)
    
    def test_parse_datetime_with_timezone(self):
        """Test parsing datetime with timezone suffix."""
        result = parse_fhir_datetime("2024-01-15T10:30:45+05:30")
        expected = datetime(2024, 1, 15, 10, 30, 45)
        self.assertEqual(result, expected)
    
    def test_parse_datetime_with_z(self):
        """Test parsing datetime with Z suffix."""
        result = parse_fhir_datetime("2024-01-15T10:30:45Z")
        expected = datetime(2024, 1, 15, 10, 30, 45)
        self.assertEqual(result, expected)
    
    def test_parse_none(self):
        """Test parsing None."""
        result = parse_fhir_datetime(None)
        self.assertIsNone(result)
    
    def test_parse_empty_string(self):
        """Test parsing empty string."""
        result = parse_fhir_datetime("")
        self.assertIsNone(result)
    
    def test_parse_invalid_format(self):
        """Test parsing invalid date format."""
        result = parse_fhir_datetime("not-a-date")
        self.assertIsNone(result)


class TestCategorizeEncounterClass(unittest.TestCase):
    """Test encounter class categorization."""
    
    def test_categorize_ambulatory(self):
        """Test categorizing ambulatory encounter."""
        result = categorize_encounter_class('AMB')
        self.assertEqual(result, 'consultation')
    
    def test_categorize_inpatient(self):
        """Test categorizing inpatient encounter."""
        result = categorize_encounter_class('IMP')
        self.assertEqual(result, 'admission')
    
    def test_categorize_emergency(self):
        """Test categorizing emergency encounter."""
        result = categorize_encounter_class('EMER')
        self.assertEqual(result, 'emergency')
    
    def test_categorize_observation(self):
        """Test categorizing observation encounter."""
        result = categorize_encounter_class('OBSENC')
        self.assertEqual(result, 'observation')
    
    def test_categorize_unknown(self):
        """Test categorizing unknown encounter class."""
        result = categorize_encounter_class('UNKNOWN')
        self.assertEqual(result, 'encounter')


class TestGetEncounterDisplayName(unittest.TestCase):
    """Test encounter display name retrieval."""
    
    def test_get_display_name_ambulatory(self):
        """Test getting display name for ambulatory."""
        result = get_encounter_display_name('AMB')
        self.assertEqual(result, 'Ambulatory')
    
    def test_get_display_name_emergency(self):
        """Test getting display name for emergency."""
        result = get_encounter_display_name('EMER')
        self.assertEqual(result, 'Emergency')
    
    def test_get_display_name_unknown(self):
        """Test getting display name for unknown code."""
        result = get_encounter_display_name('UNKNOWN')
        self.assertEqual(result, 'Encounter')


class TestExtractEncounterEvents(unittest.TestCase):
    """Test encounter event extraction from FHIR bundles."""
    
    def test_extract_basic_encounter(self):
        """Test extracting basic encounter with minimal data."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Encounter',
                    'id': 'enc-123',
                    'status': 'finished',
                    'class': {
                        'code': 'AMB',
                        'display': 'Ambulatory'
                    }
                }
            ]
        }
        
        events = extract_encounter_events(bundle)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['id'], 'enc-123')
        self.assertEqual(events[0]['type'], 'consultation')
        self.assertEqual(events[0]['status'], 'finished')
    
    def test_extract_encounter_with_dates(self):
        """Test extracting encounter with period dates."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Encounter',
                    'id': 'enc-123',
                    'status': 'finished',
                    'class': {'code': 'IMP'},
                    'period': {
                        'start': '2024-01-15T10:00:00',
                        'end': '2024-01-20T14:00:00'
                    }
                }
            ]
        }
        
        events = extract_encounter_events(bundle)
        self.assertEqual(len(events), 1)
        self.assertIsNotNone(events[0]['start_date'])
        self.assertIsNotNone(events[0]['end_date'])
        self.assertEqual(events[0]['start_date'], datetime(2024, 1, 15, 10, 0, 0))
        self.assertEqual(events[0]['end_date'], datetime(2024, 1, 20, 14, 0, 0))
    
    def test_extract_encounter_with_service_type(self):
        """Test extracting encounter with service type."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Encounter',
                    'id': 'enc-123',
                    'status': 'finished',
                    'class': {'code': 'AMB'},
                    'serviceType': {
                        'coding': [
                            {
                                'code': '124',
                                'display': 'General Practice'
                            }
                        ]
                    }
                }
            ]
        }
        
        events = extract_encounter_events(bundle)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['title'], 'General Practice')
    
    def test_extract_encounter_with_location(self):
        """Test extracting encounter with location."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Encounter',
                    'id': 'enc-123',
                    'status': 'finished',
                    'class': {'code': 'AMB'},
                    'location': [
                        {
                            'location': {
                                'display': 'Clinic A'
                            }
                        }
                    ]
                }
            ]
        }
        
        events = extract_encounter_events(bundle)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['location'], 'Clinic A')
    
    def test_extract_encounter_with_provider(self):
        """Test extracting encounter with provider."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Encounter',
                    'id': 'enc-123',
                    'status': 'finished',
                    'class': {'code': 'AMB'},
                    'participant': [
                        {
                            'individual': {
                                'display': 'Dr. Smith'
                            }
                        }
                    ]
                }
            ]
        }
        
        events = extract_encounter_events(bundle)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['provider'], 'Dr. Smith')
    
    def test_extract_encounter_with_reason(self):
        """Test extracting encounter with reason."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Encounter',
                    'id': 'enc-123',
                    'status': 'finished',
                    'class': {'code': 'AMB'},
                    'reasonCode': [
                        {
                            'text': 'Annual checkup'
                        }
                    ]
                }
            ]
        }
        
        events = extract_encounter_events(bundle)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['reason'], 'Annual checkup')
    
    def test_extract_no_encounters(self):
        """Test extracting from bundle with no encounters."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Observation',
                    'id': 'obs-123'
                }
            ]
        }
        
        events = extract_encounter_events(bundle)
        self.assertEqual(len(events), 0)
    
    def test_extract_multiple_encounters(self):
        """Test extracting multiple encounters."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Encounter',
                    'id': 'enc-1',
                    'status': 'finished',
                    'class': {'code': 'AMB'}
                },
                {
                    'resourceType': 'Encounter',
                    'id': 'enc-2',
                    'status': 'finished',
                    'class': {'code': 'IMP'}
                }
            ]
        }
        
        events = extract_encounter_events(bundle)
        self.assertEqual(len(events), 2)
    
    def test_extract_from_entry_format(self):
        """Test extracting from FHIR bundle with entry format."""
        bundle = {
            'entry': [
                {
                    'resource': {
                        'resourceType': 'Encounter',
                        'id': 'enc-123',
                        'status': 'finished',
                        'class': {'code': 'AMB'}
                    }
                }
            ]
        }
        
        events = extract_encounter_events(bundle)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['id'], 'enc-123')


class TestExtractProcedureEvents(unittest.TestCase):
    """Test procedure event extraction from FHIR bundles."""
    
    def test_extract_basic_procedure(self):
        """Test extracting basic procedure."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Procedure',
                    'id': 'proc-123',
                    'status': 'completed',
                    'code': {
                        'text': 'Blood draw'
                    }
                }
            ]
        }
        
        events = extract_procedure_events(bundle)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['id'], 'proc-123')
        self.assertEqual(events[0]['type'], 'procedure')
        self.assertEqual(events[0]['title'], 'Blood draw')
        self.assertEqual(events[0]['status'], 'completed')
    
    def test_extract_procedure_with_datetime(self):
        """Test extracting procedure with performed datetime."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Procedure',
                    'id': 'proc-123',
                    'status': 'completed',
                    'code': {'text': 'Blood draw'},
                    'performedDateTime': '2024-01-15T10:00:00'
                }
            ]
        }
        
        events = extract_procedure_events(bundle)
        self.assertEqual(len(events), 1)
        self.assertIsNotNone(events[0]['start_date'])
        self.assertEqual(events[0]['start_date'], datetime(2024, 1, 15, 10, 0, 0))
    
    def test_extract_procedure_with_period(self):
        """Test extracting procedure with performed period."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Procedure',
                    'id': 'proc-123',
                    'status': 'completed',
                    'code': {'text': 'Surgery'},
                    'performedPeriod': {
                        'start': '2024-01-15T10:00:00',
                        'end': '2024-01-15T14:00:00'
                    }
                }
            ]
        }
        
        events = extract_procedure_events(bundle)
        self.assertEqual(len(events), 1)
        self.assertIsNotNone(events[0]['start_date'])
        self.assertIsNotNone(events[0]['end_date'])
    
    def test_extract_procedure_with_location(self):
        """Test extracting procedure with location."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Procedure',
                    'id': 'proc-123',
                    'status': 'completed',
                    'code': {'text': 'Surgery'},
                    'location': {
                        'display': 'OR 3'
                    }
                }
            ]
        }
        
        events = extract_procedure_events(bundle)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['location'], 'OR 3')
    
    def test_extract_procedure_with_performer(self):
        """Test extracting procedure with performer."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Procedure',
                    'id': 'proc-123',
                    'status': 'completed',
                    'code': {'text': 'Surgery'},
                    'performer': [
                        {
                            'actor': {
                                'display': 'Dr. Johnson'
                            }
                        }
                    ]
                }
            ]
        }
        
        events = extract_procedure_events(bundle)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['provider'], 'Dr. Johnson')
    
    def test_extract_no_procedures(self):
        """Test extracting from bundle with no procedures."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Encounter',
                    'id': 'enc-123'
                }
            ]
        }
        
        events = extract_procedure_events(bundle)
        self.assertEqual(len(events), 0)


class TestCalculateEventDuration(unittest.TestCase):
    """Test event duration calculation."""
    
    def test_calculate_duration_with_dates(self):
        """Test calculating duration with start and end dates."""
        event = {
            'start_date': datetime(2024, 1, 15),
            'end_date': datetime(2024, 1, 20)
        }
        
        duration = calculate_event_duration_days(event)
        self.assertEqual(duration, 5)
    
    def test_calculate_duration_single_day(self):
        """Test calculating duration for single-day event."""
        event = {
            'start_date': datetime(2024, 1, 15),
            'end_date': None
        }
        
        duration = calculate_event_duration_days(event)
        self.assertEqual(duration, 1)
    
    def test_calculate_duration_no_start(self):
        """Test calculating duration with no start date."""
        event = {
            'start_date': None,
            'end_date': datetime(2024, 1, 20)
        }
        
        duration = calculate_event_duration_days(event)
        self.assertIsNone(duration)
    
    def test_calculate_duration_same_day(self):
        """Test calculating duration for same-day event."""
        event = {
            'start_date': datetime(2024, 1, 15, 10, 0),
            'end_date': datetime(2024, 1, 15, 14, 0)
        }
        
        duration = calculate_event_duration_days(event)
        self.assertEqual(duration, 1)  # Minimum 1 day


class TestSortEventsByDate(unittest.TestCase):
    """Test event sorting by date."""
    
    def test_sort_events_newest_first(self):
        """Test sorting events with newest first."""
        events = [
            {'id': '1', 'start_date': datetime(2024, 1, 15)},
            {'id': '2', 'start_date': datetime(2024, 1, 20)},
            {'id': '3', 'start_date': datetime(2024, 1, 10)}
        ]
        
        sorted_events = sort_events_by_date(events)
        self.assertEqual(sorted_events[0]['id'], '2')
        self.assertEqual(sorted_events[1]['id'], '1')
        self.assertEqual(sorted_events[2]['id'], '3')
    
    def test_sort_events_with_none_dates(self):
        """Test sorting events with some None dates."""
        events = [
            {'id': '1', 'start_date': datetime(2024, 1, 15)},
            {'id': '2', 'start_date': None},
            {'id': '3', 'start_date': datetime(2024, 1, 20)}
        ]
        
        sorted_events = sort_events_by_date(events)
        self.assertEqual(sorted_events[0]['id'], '3')
        self.assertEqual(sorted_events[1]['id'], '1')
        self.assertEqual(sorted_events[2]['id'], '2')


class TestCalculateTimelinePositions(unittest.TestCase):
    """Test timeline grid position calculations."""
    
    def test_calculate_positions_basic(self):
        """Test calculating positions for basic events."""
        events = [
            {
                'id': '1',
                'start_date': datetime(2024, 1, 1),
                'end_date': datetime(2024, 1, 10)
            },
            {
                'id': '2',
                'start_date': datetime(2024, 1, 15),
                'end_date': datetime(2024, 1, 20)
            }
        ]
        
        positioned = calculate_timeline_positions(events, total_columns=100)
        
        self.assertIn('start_column', positioned[0])
        self.assertIn('end_column', positioned[0])
        self.assertGreater(positioned[1]['start_column'], positioned[0]['start_column'])
    
    def test_calculate_positions_no_dates(self):
        """Test calculating positions for events with no dates."""
        events = [
            {'id': '1', 'start_date': None, 'end_date': None}
        ]
        
        positioned = calculate_timeline_positions(events)
        
        self.assertEqual(positioned[0]['start_column'], 1)
        self.assertEqual(positioned[0]['end_column'], 2)
    
    def test_calculate_positions_same_day(self):
        """Test calculating positions for same-day events."""
        events = [
            {
                'id': '1',
                'start_date': datetime(2024, 1, 15),
                'end_date': datetime(2024, 1, 15)
            }
        ]
        
        positioned = calculate_timeline_positions(events)
        
        self.assertEqual(positioned[0]['start_column'], 1)
        self.assertEqual(positioned[0]['end_column'], 2)
    
    def test_calculate_positions_empty_list(self):
        """Test calculating positions for empty event list."""
        events = []
        
        positioned = calculate_timeline_positions(events)
        
        self.assertEqual(len(positioned), 0)
    
    def test_calculate_positions_minimum_span(self):
        """Test that end column is always greater than start column."""
        events = [
            {
                'id': '1',
                'start_date': datetime(2024, 1, 15, 10, 0),
                'end_date': datetime(2024, 1, 15, 10, 30)  # Same day, close times
            }
        ]
        
        positioned = calculate_timeline_positions(events)
        
        self.assertGreater(positioned[0]['end_column'], positioned[0]['start_column'])


class TestExtractTimelineEvents(unittest.TestCase):
    """Test complete timeline event extraction."""
    
    def test_extract_combined_events(self):
        """Test extracting both encounters and procedures."""
        bundle = {
            'fhir_resources': [
                {
                    'resourceType': 'Encounter',
                    'id': 'enc-123',
                    'status': 'finished',
                    'class': {'code': 'AMB'},
                    'period': {
                        'start': '2024-01-15T10:00:00'
                    }
                },
                {
                    'resourceType': 'Procedure',
                    'id': 'proc-123',
                    'status': 'completed',
                    'code': {'text': 'Blood draw'},
                    'performedDateTime': '2024-01-16T10:00:00'
                }
            ]
        }
        
        events = extract_timeline_events(bundle)
        
        self.assertEqual(len(events), 2)
        # Should be sorted newest first
        self.assertEqual(events[0]['id'], 'proc-123')
        self.assertEqual(events[1]['id'], 'enc-123')
        # Should have durations
        self.assertIn('duration_days', events[0])
        self.assertIn('duration_days', events[1])
        # Should have timeline positions
        self.assertIn('start_column', events[0])
        self.assertIn('end_column', events[0])


class TestGetTimelineSummary(unittest.TestCase):
    """Test timeline summary generation."""
    
    def test_get_summary_basic(self):
        """Test getting basic summary."""
        events = [
            {
                'id': '1',
                'type': 'consultation',
                'status': 'finished',
                'start_date': datetime(2024, 1, 15),
                'duration_days': 1
            },
            {
                'id': '2',
                'type': 'admission',
                'status': 'finished',
                'start_date': datetime(2024, 1, 20),
                'end_date': datetime(2024, 1, 25),
                'duration_days': 5
            }
        ]
        
        summary = get_timeline_summary(events)
        
        self.assertEqual(summary['total_events'], 2)
        self.assertEqual(summary['type_counts']['consultation'], 1)
        self.assertEqual(summary['type_counts']['admission'], 1)
        self.assertEqual(summary['status_counts']['finished'], 2)
        self.assertEqual(summary['total_inpatient_days'], 5)
    
    def test_get_summary_date_range(self):
        """Test summary date range calculation."""
        events = [
            {
                'id': '1',
                'type': 'consultation',
                'status': 'finished',
                'start_date': datetime(2024, 1, 1),
            },
            {
                'id': '2',
                'type': 'consultation',
                'status': 'finished',
                'start_date': datetime(2024, 1, 31),
            }
        ]
        
        summary = get_timeline_summary(events)
        
        self.assertEqual(summary['date_range_days'], 30)
        self.assertEqual(summary['earliest_date'], datetime(2024, 1, 1))
        self.assertEqual(summary['latest_date'], datetime(2024, 1, 31))
    
    def test_get_summary_empty_list(self):
        """Test summary for empty event list."""
        events = []
        
        summary = get_timeline_summary(events)
        
        self.assertEqual(summary['total_events'], 0)
        self.assertEqual(summary['type_counts'], {})
        self.assertEqual(summary['total_inpatient_days'], 0)


if __name__ == '__main__':
    unittest.main()

