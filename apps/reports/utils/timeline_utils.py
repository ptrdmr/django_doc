"""
Timeline Utilities for Medical Report Generation.

This module provides functions to extract and process clinical timeline events
from FHIR data, including encounters and procedures.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any


# Encounter class codes and their display names
ENCOUNTER_CLASSES = {
    'AMB': 'Ambulatory',
    'EMER': 'Emergency',
    'IMP': 'Inpatient',
    'ACUTE': 'Inpatient acute',
    'NONAC': 'Inpatient non-acute',
    'OBSENC': 'Observation',
    'PRENC': 'Pre-admission',
    'SS': 'Short stay',
    'VR': 'Virtual',
}

# Encounter type mappings for timeline categorization
ENCOUNTER_TYPE_CATEGORIES = {
    'admission': ['IMP', 'ACUTE', 'NONAC', 'PRENC'],
    'emergency': ['EMER'],
    'consultation': ['AMB', 'VR'],
    'observation': ['OBSENC', 'SS'],
}


def parse_fhir_datetime(date_string: Optional[str]) -> Optional[datetime]:
    """
    Parse a FHIR datetime string into a Python datetime object.
    
    Supports multiple FHIR date/datetime formats:
    - YYYY
    - YYYY-MM
    - YYYY-MM-DD
    - YYYY-MM-DDThh:mm:ss
    - YYYY-MM-DDThh:mm:ss+zz:zz
    
    Args:
        date_string: FHIR date/datetime string
    
    Returns:
        datetime object or None if parsing fails
    """
    if not date_string:
        return None
    
    # Remove timezone suffix for simplicity
    if '+' in date_string:
        date_string = date_string.split('+')[0]
    if 'Z' in date_string:
        date_string = date_string.replace('Z', '')
    
    # Try different datetime formats
    formats = [
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d',
        '%Y-%m',
        '%Y',
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_string, fmt)
        except ValueError:
            continue
    
    return None


def categorize_encounter_class(encounter_class: str) -> str:
    """
    Categorize an encounter class code into a timeline event type.
    
    Args:
        encounter_class: FHIR encounter class code (e.g., 'AMB', 'IMP')
    
    Returns:
        Timeline event category: 'admission', 'emergency', 'consultation', 'observation', or 'encounter'
    """
    for category, class_codes in ENCOUNTER_TYPE_CATEGORIES.items():
        if encounter_class in class_codes:
            return category
    return 'encounter'  # Default category


def get_encounter_display_name(encounter_class: str) -> str:
    """
    Get a user-friendly display name for an encounter class.
    
    Args:
        encounter_class: FHIR encounter class code
    
    Returns:
        Display name for the encounter class
    """
    return ENCOUNTER_CLASSES.get(encounter_class, 'Encounter')


def extract_encounter_events(fhir_bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract encounter events from a FHIR bundle.
    
    Args:
        fhir_bundle: FHIR bundle dictionary containing Encounter resources
    
    Returns:
        List of encounter event dictionaries with structured data
    """
    encounters = []
    
    # Handle different bundle formats
    if 'fhir_resources' in fhir_bundle:
        resources = fhir_bundle.get('fhir_resources', [])
    elif 'entry' in fhir_bundle:
        resources = [entry.get('resource', {}) for entry in fhir_bundle.get('entry', [])]
    else:
        resources = []
    
    for resource in resources:
        if resource.get('resourceType') != 'Encounter':
            continue
        
        # Extract encounter class
        encounter_class = resource.get('class', {})
        if isinstance(encounter_class, dict):
            class_code = encounter_class.get('code', 'AMB')
        else:
            class_code = 'AMB'
        
        # Extract dates from period
        period = resource.get('period', {})
        start_date = parse_fhir_datetime(period.get('start'))
        end_date = parse_fhir_datetime(period.get('end'))
        
        # Extract service type or type
        service_type = None
        if 'serviceType' in resource:
            service_type_obj = resource.get('serviceType', {})
            if 'coding' in service_type_obj:
                coding = service_type_obj['coding'][0] if service_type_obj['coding'] else {}
                service_type = coding.get('display') or coding.get('code')
        
        if not service_type and 'type' in resource:
            type_list = resource.get('type', [])
            if type_list:
                type_obj = type_list[0]
                if 'text' in type_obj:
                    service_type = type_obj['text']
                elif 'coding' in type_obj:
                    coding = type_obj['coding'][0] if type_obj['coding'] else {}
                    service_type = coding.get('display') or coding.get('code')
        
        # Extract location
        location = None
        if 'location' in resource:
            locations = resource.get('location', [])
            if locations:
                loc_obj = locations[0].get('location', {})
                location = loc_obj.get('display') or loc_obj.get('reference')
        
        # Extract participant (provider)
        provider = None
        if 'participant' in resource:
            participants = resource.get('participant', [])
            for participant in participants:
                individual = participant.get('individual', {})
                provider = individual.get('display') or individual.get('reference')
                if provider:
                    break
        
        # Extract reason
        reason = None
        if 'reasonCode' in resource:
            reason_codes = resource.get('reasonCode', [])
            if reason_codes:
                reason_obj = reason_codes[0]
                if 'text' in reason_obj:
                    reason = reason_obj['text']
                elif 'coding' in reason_obj:
                    coding = reason_obj['coding'][0] if reason_obj['coding'] else {}
                    reason = coding.get('display') or coding.get('code')
        
        # Build encounter event
        encounter_event = {
            'id': resource.get('id'),
            'type': categorize_encounter_class(class_code),
            'title': service_type or get_encounter_display_name(class_code),
            'start_date': start_date,
            'end_date': end_date,
            'status': resource.get('status', 'unknown'),
            'location': location,
            'provider': provider,
            'reason': reason,
            'class_code': class_code,
            'resource_type': 'Encounter',
        }
        
        encounters.append(encounter_event)
    
    return encounters


def extract_procedure_events(fhir_bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract procedure events from a FHIR bundle.
    
    Args:
        fhir_bundle: FHIR bundle dictionary containing Procedure resources
    
    Returns:
        List of procedure event dictionaries with structured data
    """
    procedures = []
    
    # Handle different bundle formats
    if 'fhir_resources' in fhir_bundle:
        resources = fhir_bundle.get('fhir_resources', [])
    elif 'entry' in fhir_bundle:
        resources = [entry.get('resource', {}) for entry in fhir_bundle.get('entry', [])]
    else:
        resources = []
    
    for resource in resources:
        if resource.get('resourceType') != 'Procedure':
            continue
        
        # Extract procedure code/name
        procedure_name = None
        code_obj = resource.get('code', {})
        if 'text' in code_obj:
            procedure_name = code_obj['text']
        elif 'coding' in code_obj:
            coding = code_obj['coding'][0] if code_obj['coding'] else {}
            procedure_name = coding.get('display') or coding.get('code')
        
        # Extract date (performed can be dateTime or Period)
        performed = resource.get('performedDateTime') or resource.get('performedPeriod', {})
        if isinstance(performed, str):
            start_date = parse_fhir_datetime(performed)
            end_date = None
        elif isinstance(performed, dict):
            start_date = parse_fhir_datetime(performed.get('start'))
            end_date = parse_fhir_datetime(performed.get('end'))
        else:
            start_date = None
            end_date = None
        
        # Extract location
        location = None
        if 'location' in resource:
            loc_obj = resource.get('location', {})
            location = loc_obj.get('display') or loc_obj.get('reference')
        
        # Extract performer (provider)
        provider = None
        if 'performer' in resource:
            performers = resource.get('performer', [])
            for performer in performers:
                actor = performer.get('actor', {})
                provider = actor.get('display') or actor.get('reference')
                if provider:
                    break
        
        # Extract reason
        reason = None
        if 'reasonCode' in resource:
            reason_codes = resource.get('reasonCode', [])
            if reason_codes:
                reason_obj = reason_codes[0]
                if 'text' in reason_obj:
                    reason = reason_obj['text']
                elif 'coding' in reason_obj:
                    coding = reason_obj['coding'][0] if reason_obj['coding'] else {}
                    reason = coding.get('display') or coding.get('code')
        
        # Build procedure event
        procedure_event = {
            'id': resource.get('id'),
            'type': 'procedure',
            'title': procedure_name or 'Procedure',
            'start_date': start_date,
            'end_date': end_date,
            'status': resource.get('status', 'unknown'),
            'location': location,
            'provider': provider,
            'reason': reason,
            'resource_type': 'Procedure',
        }
        
        procedures.append(procedure_event)
    
    return procedures


def calculate_event_duration_days(event: Dict[str, Any]) -> Optional[int]:
    """
    Calculate the duration of an event in days.
    
    Args:
        event: Event dictionary with start_date and end_date
    
    Returns:
        Number of days or None if dates are missing
    """
    start_date = event.get('start_date')
    end_date = event.get('end_date')
    
    if not start_date:
        return None
    
    if not end_date:
        return 1  # Single-day event
    
    duration = (end_date - start_date).days
    return max(1, duration)  # Minimum 1 day


def sort_events_by_date(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sort events by start date (newest first).
    
    Args:
        events: List of event dictionaries
    
    Returns:
        Sorted list of events
    """
    def get_sort_key(event):
        start_date = event.get('start_date')
        if start_date:
            return start_date
        return datetime.min
    
    return sorted(events, key=get_sort_key, reverse=True)


def calculate_timeline_positions(events: List[Dict[str, Any]], 
                                 total_columns: int = 365) -> List[Dict[str, Any]]:
    """
    Calculate grid column positions for timeline events.
    
    This assigns start_column and end_column values to each event
    for CSS Grid-based timeline display.
    
    Args:
        events: List of event dictionaries with dates
        total_columns: Total number of columns in the timeline grid (default: 365 days)
    
    Returns:
        List of events with added start_column and end_column fields
    """
    if not events:
        return []
    
    # Find date range
    dates = []
    for event in events:
        if event.get('start_date'):
            dates.append(event['start_date'])
        if event.get('end_date'):
            dates.append(event['end_date'])
    
    if not dates:
        # No dates available, assign default positions
        for i, event in enumerate(events):
            event['start_column'] = 1
            event['end_column'] = 2
        return events
    
    min_date = min(dates)
    max_date = max(dates)
    date_range_days = (max_date - min_date).days
    
    if date_range_days == 0:
        # All events on same day
        for event in events:
            event['start_column'] = 1
            event['end_column'] = 2
        return events
    
    # Calculate column positions
    days_per_column = date_range_days / total_columns
    
    for event in events:
        start_date = event.get('start_date')
        end_date = event.get('end_date')
        
        if not start_date:
            event['start_column'] = 1
            event['end_column'] = 2
            continue
        
        # Calculate start column
        days_from_min = (start_date - min_date).days
        start_column = int(days_from_min / days_per_column) + 1
        
        # Calculate end column
        if end_date:
            days_from_min_end = (end_date - min_date).days
            end_column = int(days_from_min_end / days_per_column) + 1
        else:
            end_column = start_column + 1  # Single column span
        
        # Ensure minimum span of 1 column
        if end_column <= start_column:
            end_column = start_column + 1
        
        event['start_column'] = start_column
        event['end_column'] = end_column
    
    return events


def extract_timeline_events(fhir_bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract all timeline events (encounters and procedures) from a FHIR bundle.
    
    This is the main function to use for report generation.
    
    Args:
        fhir_bundle: FHIR bundle dictionary
    
    Returns:
        List of all timeline events, sorted by date (newest first)
    """
    # Extract encounters and procedures
    encounters = extract_encounter_events(fhir_bundle)
    procedures = extract_procedure_events(fhir_bundle)
    
    # Combine all events
    all_events = encounters + procedures
    
    # Calculate durations
    for event in all_events:
        event['duration_days'] = calculate_event_duration_days(event)
    
    # Sort by date
    all_events = sort_events_by_date(all_events)
    
    # Calculate timeline positions for grid display
    all_events = calculate_timeline_positions(all_events)
    
    return all_events


def get_timeline_summary(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate summary statistics for timeline events.
    
    Args:
        events: List of timeline event dictionaries
    
    Returns:
        Dictionary with summary statistics
    """
    total_events = len(events)
    
    # Count by type
    type_counts = {}
    for event in events:
        event_type = event.get('type', 'unknown')
        type_counts[event_type] = type_counts.get(event_type, 0) + 1
    
    # Count by status
    status_counts = {}
    for event in events:
        status = event.get('status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1
    
    # Find date range
    dates = []
    for event in events:
        if event.get('start_date'):
            dates.append(event['start_date'])
        if event.get('end_date'):
            dates.append(event['end_date'])
    
    earliest_date = min(dates) if dates else None
    latest_date = max(dates) if dates else None
    
    # Calculate total inpatient days (for admissions)
    total_inpatient_days = 0
    for event in events:
        if event.get('type') == 'admission' and event.get('duration_days'):
            total_inpatient_days += event['duration_days']
    
    return {
        'total_events': total_events,
        'type_counts': type_counts,
        'status_counts': status_counts,
        'earliest_date': earliest_date,
        'latest_date': latest_date,
        'date_range_days': (latest_date - earliest_date).days if earliest_date and latest_date else 0,
        'total_inpatient_days': total_inpatient_days,
    }

