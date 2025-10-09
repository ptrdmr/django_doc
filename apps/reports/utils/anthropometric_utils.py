"""
Anthropometric data utilities for FHIR data processing.

This module provides functions to extract and calculate weight, height, BMI,
and related anthropometric measurements from FHIR bundles for medical reports.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import logging

logger = logging.getLogger(__name__)


# LOINC codes for anthropometric measurements
WEIGHT_LOINC_CODES = [
    '29463-7',  # Body weight
    '3141-9',   # Body weight (measured)
]

HEIGHT_LOINC_CODES = [
    '8302-2',   # Body height
    '8306-3',   # Body height (lying)
    '3137-7',   # Body height (measured)
]

# BMI categories based on CDC/WHO standards
BMI_CATEGORIES = {
    'underweight': (0, 18.5),
    'normal': (18.5, 25.0),
    'overweight': (25.0, 30.0),
    'obese_class_1': (30.0, 35.0),
    'obese_class_2': (35.0, 40.0),
    'obese_class_3': (40.0, float('inf')),
}


def get_bmi_category(bmi: float) -> str:
    """
    Determine BMI category based on calculated value.
    
    Args:
        bmi: Calculated BMI value
        
    Returns:
        Category name (e.g., 'normal', 'overweight')
    """
    if bmi < 0:
        return 'invalid'
    
    for category, (low, high) in BMI_CATEGORIES.items():
        if low <= bmi < high:
            return category
    
    return 'invalid'


def get_bmi_display_name(category: str) -> str:
    """
    Get human-readable display name for BMI category.
    
    Args:
        category: BMI category code
        
    Returns:
        Display name for the category
    """
    display_names = {
        'underweight': 'Underweight',
        'normal': 'Normal Weight',
        'overweight': 'Overweight',
        'obese_class_1': 'Obese (Class I)',
        'obese_class_2': 'Obese (Class II)',
        'obese_class_3': 'Obese (Class III)',
        'invalid': 'Invalid BMI',
    }
    return display_names.get(category, 'Unknown')


def calculate_bmi(weight_kg: float, height_m: float) -> Optional[float]:
    """
    Calculate BMI using the standard formula: weight(kg) / height(m)².
    
    Args:
        weight_kg: Weight in kilograms
        height_m: Height in meters
        
    Returns:
        Calculated BMI rounded to 1 decimal place, or None if invalid
    """
    if height_m <= 0 or weight_kg <= 0:
        logger.warning(f"Invalid anthropometric values: weight={weight_kg}kg, height={height_m}m")
        return None
    
    try:
        bmi = weight_kg / (height_m ** 2)
        return round(bmi, 1)
    except (ZeroDivisionError, ValueError) as e:
        logger.error(f"Error calculating BMI: {e}")
        return None


def convert_to_metric(value: float, unit: str, measurement_type: str) -> Optional[float]:
    """
    Convert measurement to metric units (kg for weight, m for height).
    
    Args:
        value: Measurement value
        unit: Unit of measurement
        measurement_type: 'weight' or 'height'
        
    Returns:
        Value converted to metric units
    """
    if measurement_type == 'weight':
        # Convert weight to kilograms
        unit_lower = unit.lower()
        if unit_lower in ['kg', 'kilograms']:
            return value
        elif unit_lower in ['lb', 'lbs', 'pounds']:
            return value * 0.453592  # Convert pounds to kg
        elif unit_lower in ['g', 'grams']:
            return value / 1000  # Convert grams to kg
    
    elif measurement_type == 'height':
        # Convert height to meters
        unit_lower = unit.lower()
        if unit_lower in ['m', 'meters']:
            return value
        elif unit_lower in ['cm', 'centimeters']:
            return value / 100  # Convert cm to m
        elif unit_lower in ['in', 'inches']:
            return value * 0.0254  # Convert inches to m
        elif unit_lower in ['ft', 'feet']:
            return value * 0.3048  # Convert feet to m
    
    logger.warning(f"Unknown unit '{unit}' for {measurement_type}")
    return None


def parse_observation_date(observation: Dict[str, Any]) -> Optional[datetime]:
    """
    Extract observation date from FHIR resource.
    
    Args:
        observation: FHIR Observation resource
        
    Returns:
        Parsed datetime object or None
    """
    # Try different date fields
    date_fields = ['effectiveDateTime', 'issued', 'date']
    
    for field in date_fields:
        if field in observation:
            date_str = observation[field]
            try:
                # Handle different date formats
                for fmt in ['%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']:
                    try:
                        return datetime.strptime(date_str.split('.')[0].replace('Z', ''), fmt.replace('%z', ''))
                    except ValueError:
                        continue
            except Exception as e:
                logger.debug(f"Error parsing date from {field}: {e}")
    
    return None


def extract_weight_observations(fhir_bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract weight observations from FHIR bundle.
    
    Args:
        fhir_bundle: Patient FHIR bundle
        
    Returns:
        List of weight observation data
    """
    weight_observations = []
    
    entries = fhir_bundle.get('entry', [])
    for entry in entries:
        resource = entry.get('resource', {})
        
        # Check if this is an Observation resource
        if resource.get('resourceType') != 'Observation':
            continue
        
        # Check if this is a weight observation
        code = resource.get('code', {})
        coding = code.get('coding', [])
        
        is_weight = False
        for code_entry in coding:
            if code_entry.get('code') in WEIGHT_LOINC_CODES:
                is_weight = True
                break
        
        if not is_weight:
            continue
        
        # Extract weight value and unit
        value_quantity = resource.get('valueQuantity', {})
        weight_value = value_quantity.get('value')
        weight_unit = value_quantity.get('unit', value_quantity.get('code', ''))
        
        if weight_value is None:
            continue
        
        # Convert to kg
        weight_kg = convert_to_metric(weight_value, weight_unit, 'weight')
        if weight_kg is None:
            continue
        
        # Extract date
        observation_date = parse_observation_date(resource)
        
        weight_observations.append({
            'date': observation_date,
            'weight_kg': round(weight_kg, 1),
            'weight_original': weight_value,
            'unit_original': weight_unit,
            'observation_id': resource.get('id'),
        })
    
    # Sort by date (oldest first for trend calculation)
    weight_observations.sort(key=lambda x: x['date'] if x['date'] else datetime.min)
    
    return weight_observations


def extract_height_observation(fhir_bundle: Dict[str, Any]) -> Optional[float]:
    """
    Extract the most recent height observation from FHIR bundle.
    
    Args:
        fhir_bundle: Patient FHIR bundle
        
    Returns:
        Height in meters or None if not found
    """
    height_observations = []
    
    entries = fhir_bundle.get('entry', [])
    for entry in entries:
        resource = entry.get('resource', {})
        
        # Check if this is an Observation resource
        if resource.get('resourceType') != 'Observation':
            continue
        
        # Check if this is a height observation
        code = resource.get('code', {})
        coding = code.get('coding', [])
        
        is_height = False
        for code_entry in coding:
            if code_entry.get('code') in HEIGHT_LOINC_CODES:
                is_height = True
                break
        
        if not is_height:
            continue
        
        # Extract height value and unit
        value_quantity = resource.get('valueQuantity', {})
        height_value = value_quantity.get('value')
        height_unit = value_quantity.get('unit', value_quantity.get('code', ''))
        
        if height_value is None:
            continue
        
        # Convert to meters
        height_m = convert_to_metric(height_value, height_unit, 'height')
        if height_m is None:
            continue
        
        # Extract date
        observation_date = parse_observation_date(resource)
        
        height_observations.append({
            'date': observation_date,
            'height_m': height_m,
        })
    
    # Return most recent height
    if height_observations:
        height_observations.sort(key=lambda x: x['date'] if x['date'] else datetime.min, reverse=True)
        return height_observations[0]['height_m']
    
    return None


def calculate_percentage_change(old_value: float, new_value: float) -> float:
    """
    Calculate percentage change between two values.
    
    Args:
        old_value: Previous value
        new_value: Current value
        
    Returns:
        Percentage change (positive for increase, negative for decrease)
    """
    if old_value == 0:
        return 0.0
    
    return round(((new_value - old_value) / old_value) * 100, 1)


def is_significant_weight_change(percentage_change: float, time_delta_days: int) -> bool:
    """
    Determine if weight change is clinically significant.
    
    Clinical significance criteria:
    - >5% change in 1 month
    - >7.5% change in 3 months
    - >10% change in 6 months
    
    Args:
        percentage_change: Percentage weight change
        time_delta_days: Days between measurements
        
    Returns:
        True if change is clinically significant
    """
    abs_change = abs(percentage_change)
    
    if time_delta_days <= 30 and abs_change >= 5.0:
        return True
    elif time_delta_days <= 90 and abs_change >= 7.5:
        return True
    elif time_delta_days <= 180 and abs_change >= 10.0:
        return True
    
    return False


def calculate_bmi_trends(fhir_bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Calculate BMI trends from weight and height observations in FHIR bundle.
    
    Args:
        fhir_bundle: Patient FHIR bundle containing observations
        
    Returns:
        List of BMI trend data points with calculated values
    """
    # Extract height (use most recent)
    height_m = extract_height_observation(fhir_bundle)
    if height_m is None:
        logger.warning("No height observation found in FHIR bundle")
        return []
    
    # Extract weight observations
    weight_observations = extract_weight_observations(fhir_bundle)
    if not weight_observations:
        logger.warning("No weight observations found in FHIR bundle")
        return []
    
    # Calculate BMI for each weight observation
    bmi_trends = []
    previous_weight = None
    previous_date = None
    
    for i, weight_obs in enumerate(weight_observations):
        weight_kg = weight_obs['weight_kg']
        observation_date = weight_obs['date']
        
        # Calculate BMI
        bmi = calculate_bmi(weight_kg, height_m)
        if bmi is None:
            continue
        
        # Determine BMI category
        bmi_category = get_bmi_category(bmi)
        bmi_display = get_bmi_display_name(bmi_category)
        
        # Calculate percentage change from previous measurement
        percentage_change = None
        time_delta_days = None
        is_significant = False
        
        if previous_weight is not None and previous_date is not None:
            percentage_change = calculate_percentage_change(previous_weight, weight_kg)
            
            if observation_date and previous_date:
                time_delta_days = (observation_date - previous_date).days
                is_significant = is_significant_weight_change(percentage_change, time_delta_days)
        
        bmi_trends.append({
            'date': observation_date,
            'weight_kg': weight_kg,
            'weight_original': weight_obs['weight_original'],
            'unit_original': weight_obs['unit_original'],
            'height_m': round(height_m, 2),
            'bmi': bmi,
            'bmi_category': bmi_category,
            'bmi_display': bmi_display,
            'percentage_change': percentage_change,
            'time_delta_days': time_delta_days,
            'is_significant_change': is_significant,
            'observation_id': weight_obs['observation_id'],
        })
        
        previous_weight = weight_kg
        previous_date = observation_date
    
    return bmi_trends


def get_weight_summary(bmi_trends: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate summary statistics for weight/BMI trends.
    
    Args:
        bmi_trends: List of BMI trend data points
        
    Returns:
        Dictionary containing summary statistics
    """
    if not bmi_trends:
        return {
            'has_data': False,
            'measurement_count': 0,
        }
    
    # Get latest and earliest measurements
    latest = bmi_trends[-1]
    earliest = bmi_trends[0]
    
    # Calculate overall change
    total_weight_change = None
    total_percentage_change = None
    
    if len(bmi_trends) >= 2:
        total_weight_change = round(latest['weight_kg'] - earliest['weight_kg'], 1)
        total_percentage_change = calculate_percentage_change(
            earliest['weight_kg'],
            latest['weight_kg']
        )
    
    # Count significant changes
    significant_changes = sum(1 for trend in bmi_trends if trend.get('is_significant_change'))
    
    return {
        'has_data': True,
        'measurement_count': len(bmi_trends),
        'latest_weight_kg': latest['weight_kg'],
        'latest_bmi': latest['bmi'],
        'latest_bmi_category': latest['bmi_display'],
        'latest_date': latest['date'],
        'earliest_weight_kg': earliest['weight_kg'],
        'earliest_bmi': earliest['bmi'],
        'earliest_date': earliest['date'],
        'total_weight_change_kg': total_weight_change,
        'total_percentage_change': total_percentage_change,
        'significant_changes_count': significant_changes,
    }

