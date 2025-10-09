"""
Medication data extraction and enrichment utilities for FHIR-based medical reports.

This module provides functions to extract, parse, and enrich medication data from
FHIR MedicationStatement resources for use in patient summary reports.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
import re


# Medication therapeutic class mapping (RxNorm/common names to classes)
THERAPEUTIC_CLASSES = {
    # Cardiovascular
    'lisinopril': 'ACE Inhibitors',
    'enalapril': 'ACE Inhibitors',
    'ramipril': 'ACE Inhibitors',
    'losartan': 'ARBs',
    'valsartan': 'ARBs',
    'olmesartan': 'ARBs',
    'amlodipine': 'Calcium Channel Blockers',
    'diltiazem': 'Calcium Channel Blockers',
    'nifedipine': 'Calcium Channel Blockers',
    'metoprolol': 'Beta Blockers',
    'atenolol': 'Beta Blockers',
    'carvedilol': 'Beta Blockers',
    'atorvastatin': 'Statins',
    'simvastatin': 'Statins',
    'rosuvastatin': 'Statins',
    'pravastatin': 'Statins',
    'furosemide': 'Diuretics',
    'hydrochlorothiazide': 'Diuretics',
    'spironolactone': 'Diuretics',
    'warfarin': 'Anticoagulants',
    'apixaban': 'Anticoagulants',
    'rivaroxaban': 'Anticoagulants',
    'clopidogrel': 'Antiplatelets',
    'aspirin': 'Antiplatelets',
    
    # Diabetes
    'metformin': 'Biguanides',
    'glipizide': 'Sulfonylureas',
    'glyburide': 'Sulfonylureas',
    'insulin': 'Insulin',
    'lantus': 'Insulin',
    'humalog': 'Insulin',
    'novolog': 'Insulin',
    'jardiance': 'SGLT2 Inhibitors',
    'empagliflozin': 'SGLT2 Inhibitors',
    'dapagliflozin': 'SGLT2 Inhibitors',
    'victoza': 'GLP-1 Agonists',
    'ozempic': 'GLP-1 Agonists',
    'trulicity': 'GLP-1 Agonists',
    
    # Respiratory
    'albuterol': 'Bronchodilators',
    'levalbuterol': 'Bronchodilators',
    'ipratropium': 'Bronchodilators',
    'budesonide': 'Inhaled Corticosteroids',
    'fluticasone': 'Inhaled Corticosteroids',
    'montelukast': 'Leukotriene Inhibitors',
    'prednisone': 'Oral Corticosteroids',
    
    # Gastrointestinal
    'omeprazole': 'Proton Pump Inhibitors',
    'pantoprazole': 'Proton Pump Inhibitors',
    'esomeprazole': 'Proton Pump Inhibitors',
    'lansoprazole': 'Proton Pump Inhibitors',
    'ranitidine': 'H2 Blockers',
    'famotidine': 'H2 Blockers',
    
    # Antibiotics
    'amoxicillin': 'Penicillins',
    'azithromycin': 'Macrolides',
    'ciprofloxacin': 'Fluoroquinolones',
    'levofloxacin': 'Fluoroquinolones',
    'doxycycline': 'Tetracyclines',
    'cephalexin': 'Cephalosporins',
    
    # Pain/NSAIDs
    'ibuprofen': 'NSAIDs',
    'naproxen': 'NSAIDs',
    'celecoxib': 'NSAIDs',
    'acetaminophen': 'Analgesics',
    'tramadol': 'Opioids',
    'oxycodone': 'Opioids',
    'hydrocodone': 'Opioids',
    
    # Psychiatric
    'sertraline': 'SSRIs',
    'fluoxetine': 'SSRIs',
    'escitalopram': 'SSRIs',
    'citalopram': 'SSRIs',
    'duloxetine': 'SNRIs',
    'venlafaxine': 'SNRIs',
    'bupropion': 'Antidepressants',
    'alprazolam': 'Benzodiazepines',
    'lorazepam': 'Benzodiazepines',
    'clonazepam': 'Benzodiazepines',
    
    # Thyroid
    'levothyroxine': 'Thyroid Hormones',
    'synthroid': 'Thyroid Hormones',
    
    # Other
    'gabapentin': 'Anticonvulsants',
    'pregabalin': 'Anticonvulsants',
    'methotrexate': 'Immunosuppressants',
}


# Status display names
STATUS_DISPLAY = {
    'active': 'Active',
    'completed': 'Completed',
    'entered-in-error': 'Error',
    'intended': 'Intended',
    'stopped': 'Stopped',
    'on-hold': 'On Hold',
    'unknown': 'Unknown',
}


def normalize_medication_name(name: str) -> str:
    """
    Normalize medication name for comparison and classification.
    
    Args:
        name: Raw medication name from FHIR resource
        
    Returns:
        Normalized lowercase name without common suffixes
    """
    if not name:
        return ''
    
    # Convert to lowercase
    name = name.lower().strip()
    
    # Remove common dosage forms and routes
    name = re.sub(r'\b(tablet|capsule|inhaler|injection|solution|cream|ointment|gel)\b', '', name)
    name = re.sub(r'\b(oral|topical|intravenous|subcutaneous|intramuscular)\b', '', name)
    
    # Remove dosage amounts (e.g., "10mg", "500 mg", "2 puffs")
    name = re.sub(r'\d+\s*(mg|mcg|g|ml|units?|puffs?|iu)\b', '', name)
    
    # Remove extra whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name


def get_therapeutic_class(medication_name: str) -> str:
    """
    Determine the therapeutic class of a medication.
    
    Args:
        medication_name: Medication name to classify
        
    Returns:
        Therapeutic class name, or "Other" if not found
    """
    normalized = normalize_medication_name(medication_name)
    
    # Check if any known medication is in the normalized name
    for med_key, class_name in THERAPEUTIC_CLASSES.items():
        if med_key in normalized:
            return class_name
    
    return 'Other'


def parse_dosage_text(dosage_text: str) -> Dict[str, Any]:
    """
    Parse dosage text into structured components.
    
    Args:
        dosage_text: Dosage instruction text (e.g., "10mg once daily", "2 puffs as needed")
        
    Returns:
        Dictionary with parsed dosage components:
            - amount: dosage amount (e.g., "10mg", "2 puffs")
            - frequency: how often (e.g., "once daily", "as needed")
            - route: administration route if specified
    """
    if not dosage_text:
        return {'amount': None, 'frequency': None, 'route': None}
    
    text = dosage_text.lower().strip()
    
    # Extract dosage amount
    amount_match = re.search(r'(\d+\.?\d*\s*(mg|mcg|g|ml|units?|puffs?|tablets?|capsules?|iu)\b)', text)
    amount = amount_match.group(1) if amount_match else None
    
    # Extract frequency patterns
    frequency = None
    frequency_patterns = [
        (r'\b(once|twice|three times|four times)\s+(daily|a day|per day)\b', r'\1 \2'),
        (r'\bevery\s+(\d+)\s+(hour|hours|hr|hrs)\b', r'every \1 \2'),
        (r'\b(q\d+h)\b', r'\1'),
        (r'\b(as needed|prn|when necessary)\b', 'as needed'),
        (r'\b(at bedtime|before bed|qhs)\b', 'at bedtime'),
        (r'\b(in the morning|qam)\b', 'in the morning'),
        (r'\b(with meals|with food)\b', 'with meals'),
    ]
    
    for pattern, replacement in frequency_patterns:
        match = re.search(pattern, text)
        if match:
            if callable(replacement):
                frequency = replacement(match)
            else:
                frequency = re.sub(pattern, replacement, match.group(0))
            break
    
    # Extract route
    route = None
    route_patterns = [
        'oral', 'sublingual', 'topical', 'intravenous', 'intramuscular',
        'subcutaneous', 'inhaled', 'nasal', 'ophthalmic', 'otic', 'rectal'
    ]
    for route_pattern in route_patterns:
        if route_pattern in text:
            route = route_pattern
            break
    
    return {
        'amount': amount,
        'frequency': frequency,
        'route': route,
    }


def extract_medication_from_resource(resource: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract structured medication data from a FHIR MedicationStatement resource.
    
    Args:
        resource: FHIR MedicationStatement resource dictionary
        
    Returns:
        Dictionary with extracted medication data, or None if invalid
    """
    if not isinstance(resource, dict):
        return None
    
    if resource.get('resourceType') != 'MedicationStatement':
        return None
    
    # Extract medication name
    med_name = None
    if 'medicationCodeableConcept' in resource:
        med_concept = resource['medicationCodeableConcept']
        if isinstance(med_concept, dict):
            med_name = med_concept.get('text')
            if not med_name and 'coding' in med_concept:
                codings = med_concept['coding']
                if codings and len(codings) > 0:
                    med_name = codings[0].get('display')
    
    if not med_name:
        return None
    
    # Extract dosage information
    dosage_text = None
    dosage_data = {'amount': None, 'frequency': None, 'route': None}
    
    if 'dosage' in resource and resource['dosage']:
        dosage_list = resource['dosage']
        if dosage_list and len(dosage_list) > 0:
            first_dosage = dosage_list[0]
            if isinstance(first_dosage, dict):
                dosage_text = first_dosage.get('text')
                if dosage_text:
                    dosage_data = parse_dosage_text(dosage_text)
                
                # Check for structured dosage if text not available
                if not dosage_data['route'] and 'route' in first_dosage:
                    route_concept = first_dosage['route']
                    if isinstance(route_concept, dict):
                        dosage_data['route'] = route_concept.get('text')
    
    # Extract status
    status = resource.get('status', 'unknown')
    status_display = STATUS_DISPLAY.get(status, status.title())
    
    # Extract dates
    effective_date = None
    last_updated = None
    
    if 'effectiveDateTime' in resource:
        effective_date = parse_date(resource['effectiveDateTime'])
    elif 'effectivePeriod' in resource:
        period = resource['effectivePeriod']
        if isinstance(period, dict) and 'start' in period:
            effective_date = parse_date(period['start'])
    
    if 'meta' in resource and isinstance(resource['meta'], dict):
        if 'lastUpdated' in resource['meta']:
            last_updated = parse_date(resource['meta']['lastUpdated'])
    
    # Extract confidence score if available
    confidence = None
    if 'extension' in resource:
        for ext in resource['extension']:
            if isinstance(ext, dict):
                if ext.get('url') == 'http://hl7.org/fhir/StructureDefinition/data-confidence':
                    confidence = ext.get('valueDecimal')
                    break
    
    # Determine therapeutic class
    therapeutic_class = get_therapeutic_class(med_name)
    
    return {
        'id': resource.get('id'),
        'name': med_name,
        'normalized_name': normalize_medication_name(med_name),
        'status': status,
        'status_display': status_display,
        'dosage_text': dosage_text,
        'dosage_amount': dosage_data['amount'],
        'dosage_frequency': dosage_data['frequency'],
        'route': dosage_data['route'],
        'therapeutic_class': therapeutic_class,
        'effective_date': effective_date,
        'last_updated': last_updated,
        'confidence': confidence,
    }


def parse_date(date_str: str) -> Optional[datetime]:
    """
    Parse various FHIR date formats into datetime objects.
    
    Args:
        date_str: Date string in various FHIR formats
        
    Returns:
        Parsed datetime object, or None if parsing fails
    """
    if not date_str or not isinstance(date_str, str):
        return None
    
    # List of date formats to try
    formats = [
        '%Y-%m-%dT%H:%M:%S.%fZ',     # ISO with microseconds and Z
        '%Y-%m-%dT%H:%M:%SZ',         # ISO without microseconds
        '%Y-%m-%dT%H:%M:%S',          # ISO without timezone
        '%Y-%m-%d',                   # Date only
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    
    return None


def enrich_medication_list(fhir_data: Any) -> List[Dict[str, Any]]:
    """
    Extract and enrich medication list from FHIR bundle or resource list.
    
    Args:
        fhir_data: FHIR Bundle dict, list of resources, or dict with 'entry' key
        
    Returns:
        List of enriched medication dictionaries
    """
    medications = []
    
    # Handle different FHIR data structures
    resources = []
    if isinstance(fhir_data, dict):
        if 'entry' in fhir_data:
            # FHIR Bundle format
            entries = fhir_data['entry']
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and 'resource' in entry:
                        resources.append(entry['resource'])
        elif 'resourceType' in fhir_data:
            # Single resource
            resources = [fhir_data]
    elif isinstance(fhir_data, list):
        resources = fhir_data
    
    # Extract medications from resources
    for resource in resources:
        if isinstance(resource, dict):
            med_data = extract_medication_from_resource(resource)
            if med_data:
                medications.append(med_data)
    
    # Sort by status (active first) then by name
    def sort_key(med):
        status_priority = {
            'active': 0,
            'intended': 1,
            'completed': 2,
            'on-hold': 3,
            'stopped': 4,
            'unknown': 5,
            'entered-in-error': 6,
        }
        return (status_priority.get(med['status'], 9), med['name'].lower())
    
    medications.sort(key=sort_key)
    
    return medications


def group_medications_by_class(medications: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group medications by therapeutic class.
    
    Args:
        medications: List of medication dictionaries
        
    Returns:
        Dictionary mapping therapeutic class to list of medications
    """
    grouped = {}
    
    for med in medications:
        class_name = med.get('therapeutic_class', 'Other')
        if class_name not in grouped:
            grouped[class_name] = []
        grouped[class_name].append(med)
    
    # Sort class names alphabetically
    return dict(sorted(grouped.items()))


def detect_duplicate_medications(medications: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Detect potential duplicate medications in the list.
    
    A duplicate is defined as:
    - Same normalized name
    - Both have 'active' or 'intended' status
    
    Args:
        medications: List of medication dictionaries
        
    Returns:
        List of medication pairs that are potential duplicates
    """
    duplicates = []
    active_statuses = {'active', 'intended'}
    
    # Create a map of normalized names to medications
    name_map = {}
    for med in medications:
        if med['status'] in active_statuses:
            normalized = med['normalized_name']
            if normalized not in name_map:
                name_map[normalized] = []
            name_map[normalized].append(med)
    
    # Find duplicates (2+ medications with same normalized name)
    for normalized_name, med_list in name_map.items():
        if len(med_list) > 1:
            for i, med1 in enumerate(med_list):
                for med2 in med_list[i+1:]:
                    duplicates.append({
                        'medication_1': med1,
                        'medication_2': med2,
                        'reason': 'Same medication name',
                    })
    
    return duplicates


def get_medication_summary(medications: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate summary statistics for a medication list.
    
    Args:
        medications: List of medication dictionaries
        
    Returns:
        Dictionary with summary statistics
    """
    total_count = len(medications)
    active_count = sum(1 for m in medications if m['status'] == 'active')
    
    # Count by therapeutic class
    class_counts = {}
    for med in medications:
        class_name = med.get('therapeutic_class', 'Other')
        class_counts[class_name] = class_counts.get(class_name, 0) + 1
    
    # Detect duplicates
    duplicates = detect_duplicate_medications(medications)
    
    return {
        'total_medications': total_count,
        'active_medications': active_count,
        'inactive_medications': total_count - active_count,
        'therapeutic_classes': len(class_counts),
        'class_breakdown': class_counts,
        'potential_duplicates': len(duplicates),
    }

