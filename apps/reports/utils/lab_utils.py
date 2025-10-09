"""
Laboratory observation utilities for FHIR data processing.

This module provides functions to extract, categorize, and process laboratory
observations from FHIR bundles for use in medical reports.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


# LOINC code to clinical category mapping
# Based on common laboratory test panels and categories
LOINC_CATEGORIES = {
    # Hematology
    '718-7': 'Hematology',      # Hemoglobin
    '789-8': 'Hematology',      # Erythrocytes (RBC)
    '787-2': 'Hematology',      # MCV
    '785-6': 'Hematology',      # MCH
    '786-4': 'Hematology',      # MCHC
    '788-0': 'Hematology',      # RDW
    '6690-2': 'Hematology',     # White blood cells
    '777-3': 'Hematology',      # Platelets
    '4544-3': 'Hematology',     # Hematocrit
    '26515-7': 'Hematology',    # Platelet count
    
    # Chemistry - Basic Metabolic Panel
    '2345-7': 'Chemistry',      # Glucose
    '2160-0': 'Chemistry',      # Creatinine
    '3094-0': 'Chemistry',      # BUN
    '2951-2': 'Chemistry',      # Sodium
    '2823-3': 'Chemistry',      # Potassium
    '2075-0': 'Chemistry',      # Chloride
    '2028-9': 'Chemistry',      # CO2
    '33914-3': 'Chemistry',     # eGFR
    
    # Chemistry - Liver Function
    '1742-6': 'Liver Function', # ALT
    '1920-8': 'Liver Function', # AST
    '6768-6': 'Liver Function', # Alkaline Phosphatase
    '1975-2': 'Liver Function', # Bilirubin
    '2885-2': 'Liver Function', # Total Protein
    '1751-7': 'Liver Function', # Albumin
    
    # Lipid Panel
    '2093-3': 'Lipid Panel',    # Total Cholesterol
    '2571-8': 'Lipid Panel',    # Triglycerides
    '2085-9': 'Lipid Panel',    # HDL
    '2089-1': 'Lipid Panel',    # LDL
    '13457-7': 'Lipid Panel',   # LDL Calculated
    
    # Thyroid Function
    '3016-3': 'Thyroid',        # TSH
    '3024-7': 'Thyroid',        # Free T4
    '3053-6': 'Thyroid',        # Free T3
    
    # Hemoglobin A1c (Diabetes)
    '4548-4': 'Diabetes',       # HbA1c
    '17856-6': 'Diabetes',      # HbA1c (IFCC)
    
    # Coagulation
    '5902-2': 'Coagulation',    # PT
    '6301-6': 'Coagulation',    # INR
    '3173-2': 'Coagulation',    # aPTT
    
    # Urinalysis
    '5804-0': 'Urinalysis',     # Protein (urine)
    '5811-5': 'Urinalysis',     # Specific Gravity
    '5803-2': 'Urinalysis',     # pH
    '5794-3': 'Urinalysis',     # Hemoglobin (urine)
    
    # Cardiac Markers
    '10839-9': 'Cardiac',       # Troponin I
    '33762-6': 'Cardiac',       # NT-proBNP
    '30934-4': 'Cardiac',       # BNP
    
    # Electrolytes
    '2000-8': 'Electrolytes',   # Calcium
    '2777-1': 'Electrolytes',   # Phosphate
    '2601-3': 'Electrolytes',   # Magnesium
}


def get_lab_category(loinc_code: str) -> str:
    """
    Determine the clinical category for a LOINC code.
    
    Args:
        loinc_code: LOINC code from observation
        
    Returns:
        Category name or 'Other' if not mapped
    """
    return LOINC_CATEGORIES.get(loinc_code, 'Other')


def parse_reference_range(observation: Dict[str, Any]) -> Optional[str]:
    """
    Extract reference range from observation resource.
    
    Args:
        observation: FHIR Observation resource
        
    Returns:
        Formatted reference range string or None
    """
    try:
        ref_range = observation.get('referenceRange', [])
        if not ref_range:
            return None
            
        first_range = ref_range[0]
        low = first_range.get('low', {}).get('value')
        high = first_range.get('high', {}).get('value')
        # Get unit from either low or high (whichever is available)
        unit = first_range.get('low', {}).get('unit') or first_range.get('high', {}).get('unit', '')
        
        if low is not None and high is not None:
            return f"{low}-{high} {unit}".strip()
        elif low is not None:
            return f">{low} {unit}".strip()
        elif high is not None:
            return f"<{high} {unit}".strip()
            
        # Try text representation
        return first_range.get('text', None)
    except (KeyError, IndexError, TypeError) as e:
        logger.debug(f"Could not parse reference range: {e}")
        return None


def detect_abnormal_result(observation: Dict[str, Any]) -> str:
    """
    Detect if a lab result is abnormal based on interpretation or reference range.
    
    Args:
        observation: FHIR Observation resource
        
    Returns:
        One of: 'normal', 'low', 'high', 'critical'
    """
    try:
        # Check for explicit interpretation
        interpretation = observation.get('interpretation', [])
        if interpretation:
            code = interpretation[0].get('coding', [{}])[0].get('code', '')
            
            # FHIR interpretation codes
            if code in ['N', 'normal']:
                return 'normal'
            elif code in ['L', 'low']:
                return 'low'
            elif code in ['H', 'high']:
                return 'high'
            elif code in ['LL', 'HH', 'AA', 'critical']:
                return 'critical'
        
        # Check reference range if available
        ref_range = observation.get('referenceRange', [])
        value_qty = observation.get('valueQuantity', {})
        
        if ref_range and value_qty:
            value = value_qty.get('value')
            first_range = ref_range[0]
            low = first_range.get('low', {}).get('value')
            high = first_range.get('high', {}).get('value')
            
            if value is not None:
                if low is not None and value < low:
                    # Check if critically low (< 80% of lower limit)
                    if value < (low * 0.8):
                        return 'critical'
                    return 'low'
                elif high is not None and value > high:
                    # Check if critically high (> 120% of upper limit)
                    if value > (high * 1.2):
                        return 'critical'
                    return 'high'
                else:
                    return 'normal'
        
        # Default to normal if no interpretation available
        return 'normal'
        
    except (KeyError, TypeError, ValueError) as e:
        logger.debug(f"Could not detect abnormal result: {e}")
        return 'normal'


def extract_observation_data(observation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract relevant data from a single FHIR Observation resource.
    
    Args:
        observation: FHIR Observation resource
        
    Returns:
        Dictionary with extracted data or None if not a valid lab observation
    """
    try:
        # Check if this is a laboratory observation
        category = observation.get('category', [])
        is_lab = False
        
        for cat in category:
            coding = cat.get('coding', [])
            for code in coding:
                if code.get('code') == 'laboratory' or code.get('code') == 'LAB':
                    is_lab = True
                    break
        
        # Also check for LOINC codes (lab tests typically have LOINC codes)
        code_obj = observation.get('code', {})
        coding = code_obj.get('coding', [])
        loinc_code = None
        test_name = code_obj.get('text', 'Unknown Test')
        
        for code in coding:
            if code.get('system') == 'http://loinc.org':
                loinc_code = code.get('code')
                test_name = code.get('display', test_name)
                is_lab = True
                break
        
        # Skip non-laboratory observations
        if not is_lab:
            return None
        
        # Extract value
        value_qty = observation.get('valueQuantity', {})
        value = value_qty.get('value')
        unit = value_qty.get('unit', '')
        
        # Skip observations without values
        if value is None:
            return None
        
        # Extract date
        effective_date = observation.get('effectiveDateTime')
        if not effective_date:
            effective_date = observation.get('issued')
        
        # Parse date
        date_obj = None
        if effective_date:
            try:
                # Handle various date formats
                if 'T' in effective_date:
                    date_obj = datetime.fromisoformat(effective_date.replace('Z', '+00:00'))
                else:
                    date_obj = datetime.strptime(effective_date, '%Y-%m-%d')
            except (ValueError, AttributeError) as e:
                logger.debug(f"Could not parse date {effective_date}: {e}")
        
        # Get reference range
        ref_range = parse_reference_range(observation)
        
        # Detect abnormal results
        interpretation = detect_abnormal_result(observation)
        
        # Determine category
        lab_category = get_lab_category(loinc_code) if loinc_code else 'Other'
        
        # Extract notes
        notes = observation.get('note', [])
        note_text = notes[0].get('text') if notes else None
        
        return {
            'id': observation.get('id'),
            'test_name': test_name,
            'loinc_code': loinc_code,
            'value': value,
            'unit': unit,
            'reference_range': ref_range,
            'interpretation': interpretation,
            'category': lab_category,
            'date': date_obj,
            'date_str': effective_date,
            'notes': note_text,
            'status': observation.get('status', 'unknown')
        }
        
    except (KeyError, TypeError) as e:
        logger.error(f"Error extracting observation data: {e}")
        return None


def group_lab_results(fhir_bundle: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group laboratory observations from a FHIR bundle by clinical category.
    
    This function processes a patient's FHIR bundle, extracts laboratory
    observations, categorizes them by LOINC codes, and returns them grouped
    by clinical category (e.g., Hematology, Chemistry).
    
    Args:
        fhir_bundle: Patient's FHIR bundle (can be cumulative_fhir_json or encrypted_fhir_bundle)
        
    Returns:
        Dictionary mapping category names to lists of lab results, sorted by date (newest first)
        
    Example:
        {
            'Hematology': [
                {
                    'test_name': 'Hemoglobin',
                    'value': 14.5,
                    'unit': 'g/dL',
                    'reference_range': '12.0-16.0 g/dL',
                    'interpretation': 'normal',
                    'date': datetime(...),
                    'loinc_code': '718-7'
                },
                ...
            ],
            'Chemistry': [...],
            ...
        }
    """
    grouped_results = {}
    
    try:
        # Handle different bundle formats
        resources = []
        
        # Check if it's a Bundle resource with entry array
        if isinstance(fhir_bundle, dict):
            if 'entry' in fhir_bundle:
                # Standard FHIR Bundle format
                for entry in fhir_bundle.get('entry', []):
                    resource = entry.get('resource', {})
                    if resource.get('resourceType') == 'Observation':
                        resources.append(resource)
            elif 'fhir_resources' in fhir_bundle:
                # Our custom format from porthole
                for resource in fhir_bundle.get('fhir_resources', []):
                    if resource.get('resourceType') == 'Observation':
                        resources.append(resource)
            else:
                # Direct resource array or dictionary format
                for key, value in fhir_bundle.items():
                    if key == 'Observation' and isinstance(value, list):
                        resources.extend(value)
        
        # Process each observation
        for observation in resources:
            lab_data = extract_observation_data(observation)
            
            if lab_data:
                category = lab_data['category']
                
                if category not in grouped_results:
                    grouped_results[category] = []
                
                grouped_results[category].append(lab_data)
        
        # Sort each category by date (newest first)
        for category in grouped_results:
            grouped_results[category].sort(
                key=lambda x: x['date'] if x['date'] else datetime.min,
                reverse=True
            )
        
        logger.info(f"Grouped {sum(len(v) for v in grouped_results.values())} lab results into {len(grouped_results)} categories")
        
    except Exception as e:
        logger.error(f"Error grouping lab results: {e}")
    
    return grouped_results


def get_abnormal_results_summary(grouped_results: Dict[str, List[Dict[str, Any]]]) -> Dict[str, int]:
    """
    Get summary counts of abnormal lab results.
    
    Args:
        grouped_results: Output from group_lab_results()
        
    Returns:
        Dictionary with counts: {'critical': n, 'abnormal': n, 'normal': n}
    """
    summary = {'critical': 0, 'abnormal': 0, 'normal': 0}
    
    for category_results in grouped_results.values():
        for result in category_results:
            interpretation = result.get('interpretation', 'normal')
            if interpretation == 'critical':
                summary['critical'] += 1
            elif interpretation in ['low', 'high']:
                summary['abnormal'] += 1
            else:
                summary['normal'] += 1
    
    return summary

