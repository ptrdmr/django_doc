"""
FHIR Data Validation Framework

This module provides comprehensive validation and normalization utilities
for FHIR data processing in medical document parsing workflows.
"""

import json
import logging
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from django.utils import timezone


class ValidationResult:
    """
    Comprehensive validation result object that tracks all validation outcomes.
    """
    
    def __init__(self):
        self.is_valid = True
        self.data = {}
        self.errors = []
        self.warnings = []
        self.critical_errors = []
        self.field_errors = {}  # Field-specific errors
        self.normalized_fields = []  # Fields that were normalized
        self.validation_metadata = {
            'validation_timestamp': timezone.now(),
            'validator_version': '1.0.0',
            'schema_version': '1.0.0'
        }
    
    def add_error(self, message: str, field: str = None, is_critical: bool = False):
        """Add a validation error."""
        if is_critical:
            self.critical_errors.append(message)
        self.errors.append(message)
        
        if field:
            if field not in self.field_errors:
                self.field_errors[field] = []
            self.field_errors[field].append(message)
        
        self.is_valid = False
    
    def add_warning(self, message: str, field: str = None):
        """Add a validation warning."""
        self.warnings.append(message)
        
        if field:
            if field not in self.field_errors:
                self.field_errors[field] = []
            self.field_errors[field].append(f"WARNING: {message}")
    
    def add_normalized_field(self, field: str, original_value: Any, normalized_value: Any):
        """Track field normalization."""
        self.normalized_fields.append({
            'field': field,
            'original_value': str(original_value),
            'normalized_value': str(normalized_value)
        })
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert validation result to dictionary."""
        return {
            'is_valid': self.is_valid,
            'data': self.data,
            'errors': self.errors,
            'warnings': self.warnings,
            'critical_errors': self.critical_errors,
            'field_errors': self.field_errors,
            'normalized_fields': self.normalized_fields,
            'validation_metadata': self.validation_metadata
        }


class DataNormalizer:
    """
    Utility class for normalizing various types of medical data.
    """
    
    @staticmethod
    def normalize_date(date_value: Any) -> Optional[str]:
        """
        Normalize date values to ISO format.
        
        Args:
            date_value: Date in various formats
            
        Returns:
            ISO formatted date string or None if invalid
        """
        if not date_value:
            return None
        
        # If already a date object
        if isinstance(date_value, datetime):
            return date_value.date().isoformat()
        elif isinstance(date_value, date):
            return date_value.isoformat()
        
        # If string, try to parse various formats
        if isinstance(date_value, str):
            date_value = date_value.strip()
            
            # Common date formats
            date_formats = [
                '%Y-%m-%d',           # 2023-12-25
                '%m/%d/%Y',           # 12/25/2023
                '%m-%d-%Y',           # 12-25-2023
                '%d/%m/%Y',           # 25/12/2023
                '%d-%m-%Y',           # 25-12-2023
                '%B %d, %Y',          # December 25, 2023
                '%b %d, %Y',          # Dec 25, 2023
                '%Y/%m/%d',           # 2023/12/25
                '%m/%d/%y',           # 12/25/23
                '%d/%m/%y',           # 25/12/23
            ]
            
            for fmt in date_formats:
                try:
                    parsed_date = datetime.strptime(date_value, fmt).date()
                    return parsed_date.isoformat()
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def normalize_name(name_value: Any) -> Optional[str]:
        """
        Normalize person names.
        
        Args:
            name_value: Name in various formats
            
        Returns:
            Normalized name string or None if invalid
        """
        if not name_value:
            return None
        
        if not isinstance(name_value, str):
            name_value = str(name_value)
        
        # Basic name normalization
        name_value = name_value.strip()
        
        # Remove multiple spaces
        name_value = re.sub(r'\s+', ' ', name_value)
        
        # Title case for proper names
        name_value = name_value.title()
        
        # Handle common prefixes and suffixes
        name_parts = name_value.split()
        normalized_parts = []
        
        for part in name_parts:
            # Keep common prefixes lowercase
            if part.lower() in ['dr', 'dr.', 'mr', 'mr.', 'mrs', 'mrs.', 'ms', 'ms.']:
                normalized_parts.append(part.capitalize() + ('.' if not part.endswith('.') else ''))
            # Keep common suffixes as-is
            elif part.lower() in ['jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv']:
                normalized_parts.append(part.upper() + ('.' if part.lower() in ['jr', 'sr'] and not part.endswith('.') else ''))
            else:
                normalized_parts.append(part)
        
        return ' '.join(normalized_parts)
    
    @staticmethod
    def normalize_medical_code(code_value: Any, code_system: str = None) -> Optional[Dict[str, str]]:
        """
        Normalize medical codes.
        
        Args:
            code_value: Medical code in various formats
            code_system: Code system (LOINC, SNOMED, ICD-10, etc.)
            
        Returns:
            Normalized code dictionary or None if invalid
        """
        if not code_value:
            return None
        
        if not isinstance(code_value, str):
            code_value = str(code_value)
        
        code_value = code_value.strip().upper()
        
        # Remove common separators and normalize format
        code_value = re.sub(r'[^\w\.-]', '', code_value)
        
        # Detect code system if not provided
        if not code_system:
            if re.match(r'^\d{1,5}-\d$', code_value):  # LOINC pattern
                code_system = 'LOINC'
            elif re.match(r'^[A-Z]\d{2}(\.\d{1,2})?$', code_value):  # ICD-10 pattern
                code_system = 'ICD-10'
            elif len(code_value) >= 6 and code_value.isdigit():  # SNOMED pattern
                code_system = 'SNOMED'
            else:
                code_system = 'UNKNOWN'
        
        return {
            'code': code_value,
            'system': code_system,
            'display': None  # Will be populated later if available
        }
    
    @staticmethod
    def normalize_numeric_value(value: Any, data_type: str = 'decimal') -> Optional[float]:
        """
        Normalize numeric values.
        
        Args:
            value: Numeric value in various formats
            data_type: Expected data type (integer, decimal, percentage)
            
        Returns:
            Normalized numeric value or None if invalid
        """
        if value is None:
            return None
        
        # If already a number
        if isinstance(value, (int, float)):
            return float(value)
        
        # If string, clean and convert
        if isinstance(value, str):
            value = value.strip()
            
            # Check if string contains any letters - if so, it's not a pure number
            if re.search(r'[a-zA-Z]', value):
                return None
            
            # Remove common non-numeric characters (currency symbols, spaces, etc.)
            value = re.sub(r'[^\d\.-]', '', value)
            
            if not value:
                return None
            
            try:
                if data_type == 'integer':
                    return float(int(value))
                else:
                    return float(Decimal(value))
            except (ValueError, InvalidOperation):
                return None
        
        return None


class DocumentSchemaValidator:
    """
    Schema-based validator for different document types.
    """
    
    def __init__(self):
        self.schemas = self._load_schemas()
    
    def _load_schemas(self) -> Dict[str, Dict]:
        """
        Load validation schemas for different document types.
        
        Returns:
            Dictionary of document type schemas
        """
        return {
            'lab_report': {
                'required_fields': ['patient_name', 'test_date', 'tests'],
                'optional_fields': ['ordering_provider', 'lab_facility', 'collection_date'],
                'field_types': {
                    'patient_name': 'string',
                    'test_date': 'date',
                    'collection_date': 'date',
                    'tests': 'array',
                    'ordering_provider': 'string',
                    'lab_facility': 'string'
                },
                'field_constraints': {
                    'patient_name': {'min_length': 2, 'max_length': 100},
                    'test_date': {'min_date': '1900-01-01', 'max_date': 'today+1'},
                    'collection_date': {'min_date': '1900-01-01', 'max_date': 'today+1'}
                }
            },
            'clinical_note': {
                'required_fields': ['patient_name', 'note_date', 'provider'],
                'optional_fields': ['chief_complaint', 'assessment', 'plan', 'diagnosis_codes'],
                'field_types': {
                    'patient_name': 'string',
                    'note_date': 'date',
                    'provider': 'string',
                    'chief_complaint': 'string',
                    'assessment': 'string',
                    'plan': 'string',
                    'diagnosis_codes': 'array'
                },
                'field_constraints': {
                    'patient_name': {'min_length': 2, 'max_length': 100},
                    'note_date': {'min_date': '1900-01-01', 'max_date': 'today+1'},
                    'provider': {'min_length': 2, 'max_length': 100}
                }
            },
            'medication_list': {
                'required_fields': ['patient_name', 'list_date', 'medications'],
                'optional_fields': ['prescribing_provider', 'pharmacy'],
                'field_types': {
                    'patient_name': 'string',
                    'list_date': 'date',
                    'medications': 'array',
                    'prescribing_provider': 'string',
                    'pharmacy': 'string'
                },
                'field_constraints': {
                    'patient_name': {'min_length': 2, 'max_length': 100},
                    'list_date': {'min_date': '1900-01-01', 'max_date': 'today+1'}
                }
            },
            'discharge_summary': {
                'required_fields': ['patient_name', 'admission_date', 'discharge_date'],
                'optional_fields': ['attending_physician', 'diagnosis', 'procedures', 'medications'],
                'field_types': {
                    'patient_name': 'string',
                    'admission_date': 'date',
                    'discharge_date': 'date',
                    'attending_physician': 'string',
                    'diagnosis': 'array',
                    'procedures': 'array',
                    'medications': 'array'
                },
                'field_constraints': {
                    'patient_name': {'min_length': 2, 'max_length': 100},
                    'admission_date': {'min_date': '1900-01-01', 'max_date': 'today+1'},
                    'discharge_date': {'min_date': '1900-01-01', 'max_date': 'today+1'}
                }
            },
            'generic': {
                'required_fields': ['patient_name', 'document_date'],
                'optional_fields': [],
                'field_types': {
                    'patient_name': 'string',
                    'document_date': 'date'
                },
                'field_constraints': {
                    'patient_name': {'min_length': 2, 'max_length': 100},
                    'document_date': {'min_date': '1900-01-01', 'max_date': 'today+1'}
                }
            }
        }
    
    def validate_schema(self, data: Dict[str, Any], document_type: str = 'generic') -> ValidationResult:
        """
        Validate data against document type schema.
        
        Args:
            data: Data to validate
            document_type: Type of document to validate against
            
        Returns:
            ValidationResult with validation outcomes
        """
        result = ValidationResult()
        schema = self.schemas.get(document_type, self.schemas['generic'])
        
        # Check required fields
        for field in schema['required_fields']:
            if field not in data or data[field] is None:
                result.add_error(f"Required field '{field}' is missing", field, is_critical=True)
            elif isinstance(data[field], str) and not data[field].strip():
                result.add_error(f"Required field '{field}' is empty", field, is_critical=True)
        
        # Validate field types and constraints
        for field, value in data.items():
            if value is None:
                continue
            
            expected_type = schema['field_types'].get(field)
            constraints = schema['field_constraints'].get(field, {})
            
            if expected_type:
                validation_error = self._validate_field_type(field, value, expected_type, constraints)
                if validation_error:
                    result.add_error(validation_error, field)
        
        result.data = data
        return result
    
    def _validate_field_type(self, field: str, value: Any, expected_type: str, constraints: Dict) -> Optional[str]:
        """
        Validate a single field's type and constraints.
        
        Args:
            field: Field name
            value: Field value
            expected_type: Expected data type
            constraints: Field constraints
            
        Returns:
            Error message if validation fails, None otherwise
        """
        if expected_type == 'string':
            if not isinstance(value, str):
                return f"Field '{field}' must be a string"
            
            if 'min_length' in constraints and len(value) < constraints['min_length']:
                return f"Field '{field}' must be at least {constraints['min_length']} characters"
            
            if 'max_length' in constraints and len(value) > constraints['max_length']:
                return f"Field '{field}' must be no more than {constraints['max_length']} characters"
        
        elif expected_type == 'date':
            # Date validation will be handled by normalization
            pass
        
        elif expected_type == 'array':
            if not isinstance(value, list):
                return f"Field '{field}' must be an array"
        
        elif expected_type == 'number':
            try:
                float(value)
            except (ValueError, TypeError):
                return f"Field '{field}' must be a number"
        
        return None


def serialize_fhir_data(data: Any) -> Any:
    """
    Recursively serialize FHIR data to ensure datetime and Decimal objects are converted properly.
    
    Like makin' sure all the parts in your engine work together - sometimes you need
    to adjust different types of components to work with the same fuel system.
    
    Args:
        data: Data structure that may contain datetime or Decimal objects
        
    Returns:
        Serialized data with datetime objects converted to ISO strings and Decimals to floats
    """
    if isinstance(data, (datetime, date)):
        return data.isoformat()
    elif isinstance(data, Decimal):
        return float(data)
    elif isinstance(data, dict):
        return {key: serialize_fhir_data(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [serialize_fhir_data(item) for item in data]
    else:
        return data
