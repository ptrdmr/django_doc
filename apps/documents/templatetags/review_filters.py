"""
Template filters for document review interface.
"""

from django import template

register = template.Library()


@register.filter
def confidence_level(score):
    """
    Convert a numeric confidence score to a text level.
    
    Args:
        score: Confidence score (0.0-1.0)
        
    Returns:
        str: Text level (high, medium, low)
    """
    if score is None:
        return "unknown"
    
    try:
        score = float(score)
        if score >= 0.8:
            return "high"
        elif score >= 0.5:
            return "medium"
        else:
            return "low"
    except (ValueError, TypeError):
        return "unknown"


@register.filter
def clean_field_name(field_name):
    """
    Convert field names to human-readable format.
    
    Args:
        field_name: Raw field name from extraction
        
    Returns:
        str: Cleaned, human-readable field name
    """
    if not field_name:
        return "Unknown Field"
    
    # Handle common field name patterns
    name_mapping = {
        'patient_name': 'Patient Name',
        'date_of_birth': 'Date of Birth',
        'medical_record_number': 'Medical Record Number',
        'mrn': 'MRN',
        'dob': 'Date of Birth',
        'diagnoses': 'Diagnoses',
        'medications': 'Current Medications',
        'allergies': 'Allergies',
        'vital_signs': 'Vital Signs',
        'blood_pressure': 'Blood Pressure',
        'heart_rate': 'Heart Rate',
        'temperature': 'Temperature',
        'weight': 'Weight',
        'height': 'Height',
        'lab_results': 'Laboratory Results',
        'provider_name': 'Provider Name',
        'provider_info': 'Provider Information',
    }
    
    # Direct mapping first
    if field_name.lower() in name_mapping:
        return name_mapping[field_name.lower()]
    
    # Clean up common patterns
    cleaned = field_name.replace('_', ' ').replace('-', ' ')
    
    # Title case the result
    cleaned = ' '.join(word.capitalize() for word in cleaned.split())
    
    return cleaned
