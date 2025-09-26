"""
Data validation middleware for the document processing pipeline.

Provides structured data validation at various pipeline stages using Pydantic models
to ensure data integrity, HIPAA compliance, and proper error handling.
"""

import logging
import json
import time
from typing import Dict, Any, List, Optional, Tuple
from django.utils.deprecation import MiddlewareMixin
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth.models import AnonymousUser
from pydantic import ValidationError as PydanticValidationError

from .services.ai_extraction import StructuredMedicalExtraction
from .exceptions import (
    DataValidationError, 
    PydanticModelError,
    DocumentProcessingError
)

logger = logging.getLogger(__name__)


class StructuredDataValidationMiddleware(MiddlewareMixin):
    """
    Middleware to validate structured medical data at various pipeline stages.
    
    Features:
    - Pre-AI extraction validation (text quality)
    - Post-AI extraction validation (Pydantic model compliance)
    - Pre-FHIR conversion validation (resource completeness)
    - Post-processing validation (data integrity)
    - HIPAA-compliant audit logging
    - Graceful error handling and recovery
    """
    
    def __init__(self, get_response=None):
        """Initialize the validation middleware."""
        super().__init__(get_response)
        self.validation_start_time = None
        
        # Configuration for validation thresholds
        self.min_text_length = 50  # Minimum characters for meaningful extraction
        self.min_confidence_threshold = 0.3  # Minimum confidence for accepting data
        self.required_field_types = ['conditions', 'medications']  # Required data types
        
        # Validation rules for different data types
        self.validation_rules = {
            'text_quality': {
                'min_length': 50,
                'max_length': 100000,
                'forbidden_patterns': [r'^\s*$', r'^ERROR', r'^FAILED']
            },
            'structured_data': {
                'required_fields': ['conditions', 'medications'],
                'min_confidence': 0.3,
                'max_resources': 1000
            },
            'fhir_resources': {
                'required_resource_types': ['Condition', 'MedicationStatement'],
                'max_bundle_size': 500
            }
        }
    
    def process_request(self, request):
        """
        Pre-process requests to set up validation context.
        
        Args:
            request: HTTP request object
        """
        self.validation_start_time = time.time()
        
        # Add validation context to request for tracking
        request.validation_context = {
            'stage': 'request_start',
            'validations_performed': [],
            'validation_errors': [],
            'start_time': self.validation_start_time
        }
        
        # Check if this is a document processing request
        if self._is_document_processing_request(request):
            self._prepare_document_validation(request)
    
    def process_response(self, request, response):
        """
        Post-process responses to log validation results.
        
        Args:
            request: HTTP request object
            response: HTTP response object
            
        Returns:
            Modified response with validation headers
        """
        if hasattr(request, 'validation_context'):
            validation_time = (time.time() - self.validation_start_time) * 1000
            
            # Log validation summary
            self._log_validation_summary(request, response, validation_time)
            
            # Add validation headers for debugging (development only)
            from django.conf import settings
            if settings.DEBUG:
                response['X-Validation-Time-MS'] = f"{validation_time:.2f}"
                response['X-Validations-Count'] = str(len(request.validation_context['validations_performed']))
                if request.validation_context['validation_errors']:
                    response['X-Validation-Errors'] = str(len(request.validation_context['validation_errors']))
        
        return response
    
    def _is_document_processing_request(self, request: HttpRequest) -> bool:
        """
        Check if request involves document processing that needs validation.
        
        Args:
            request: HTTP request object
            
        Returns:
            bool: True if request needs document validation
        """
        processing_paths = [
            '/documents/upload/',
            '/documents/process/',
            '/api/documents/',
            '/api/validate/',
        ]
        
        return any(request.path_info.startswith(path) for path in processing_paths)
    
    def _prepare_document_validation(self, request: HttpRequest) -> None:
        """
        Prepare validation context for document processing requests.
        
        Args:
            request: HTTP request object
        """
        request.validation_context.update({
            'document_processing': True,
            'validation_required': True,
            'pipeline_stage': 'upload'
        })
        
        logger.info(f"Prepared document validation context for {request.path_info}")
    
    def _log_validation_summary(self, request: HttpRequest, response: HttpResponse, validation_time: float) -> None:
        """
        Log validation summary for audit purposes.
        
        Args:
            request: HTTP request object
            response: HTTP response object
            validation_time: Time spent on validation in milliseconds
        """
        if not hasattr(request, 'validation_context'):
            return
        
        context = request.validation_context
        
        try:
            # Import here to avoid circular imports
            from apps.core.models import AuditLog
            
            # Create audit log entry
            AuditLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action='DATA_VALIDATION',
                resource_type='ValidationMiddleware',
                resource_id=request.path_info,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                data_accessed=f"Validations: {len(context['validations_performed'])}, Errors: {len(context['validation_errors'])}",
                additional_info={
                    'validation_time_ms': round(validation_time, 2),
                    'validations_performed': context['validations_performed'],
                    'validation_errors': context['validation_errors'][:5],  # Limit for storage
                    'success': len(context['validation_errors']) == 0,
                    'pipeline_stage': context.get('pipeline_stage', 'unknown')
                }
            )
            
        except Exception as e:
            logger.error(f"Error logging validation summary: {e}")
    
    def _get_client_ip(self, request: HttpRequest) -> str:
        """Get client IP address for logging."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', 'unknown')


class DataValidationService:
    """
    Service class for performing structured data validation.
    
    Provides validation functions that can be used both in middleware
    and directly in processing components.
    """
    
    def __init__(self):
        """Initialize the validation service."""
        self.logger = logging.getLogger(__name__)
        
        # Validation thresholds
        self.min_text_length = 50
        self.min_confidence_threshold = 0.3
        self.max_field_count = 1000
        
        # Medical validation patterns
        self.medical_patterns = {
            'medication_name': r'^[A-Za-z][A-Za-z\s\-()0-9]*$',
            'condition_name': r'^[A-Za-z][A-Za-z\s\-()0-9]*$',
            'dosage': r'^[\d\s\.\-\/]+(mg|g|ml|units?|tablets?|capsules?|drops?|mL|mcg|IU).*$',
            'vital_value': r'^\d+[\.\d]*\s*[A-Za-z%\/]*$',
        }
    
    def validate_text_quality(self, text: str, context: Dict[str, Any] = None) -> Tuple[bool, List[str]]:
        """
        Validate extracted text quality for AI processing.
        
        Args:
            text: Extracted text to validate
            context: Optional context information
            
        Returns:
            Tuple of (is_valid: bool, issues: List[str])
        """
        issues = []
        
        if not text or not text.strip():
            issues.append("Text is empty or contains only whitespace")
            return False, issues
        
        # Check minimum length
        if len(text.strip()) < self.min_text_length:
            issues.append(f"Text too short: {len(text)} chars (minimum: {self.min_text_length})")
        
        # Check for common extraction errors
        text_lower = text.lower()
        error_indicators = [
            'pdf extraction failed',
            'unable to read',
            'corrupted file',
            'invalid format',
            'encoding error'
        ]
        
        for indicator in error_indicators:
            if indicator in text_lower:
                issues.append(f"Text contains error indicator: {indicator}")
        
        # Check for adequate medical content indicators
        medical_indicators = [
            'patient', 'diagnosis', 'medication', 'treatment', 'condition',
            'doctor', 'provider', 'clinic', 'hospital', 'prescribed'
        ]
        
        found_indicators = sum(1 for indicator in medical_indicators if indicator in text_lower)
        if found_indicators < 2:
            issues.append(f"Limited medical content detected (found {found_indicators} medical indicators)")
        
        self.logger.info(f"Text quality validation: {len(issues)} issues found, length: {len(text)} chars")
        
        return len(issues) == 0, issues
    
    def validate_structured_extraction(self, structured_data: StructuredMedicalExtraction, context: Dict[str, Any] = None) -> Tuple[bool, List[str]]:
        """
        Validate structured medical extraction using Pydantic models.
        
        Args:
            structured_data: StructuredMedicalExtraction instance to validate
            context: Optional context information
            
        Returns:
            Tuple of (is_valid: bool, issues: List[str])
        """
        issues = []
        
        try:
            # Validate using Pydantic (this will raise ValidationError if invalid)
            structured_data.dict()  # This triggers full validation
            
            # Additional business logic validation
            total_resources = (
                len(structured_data.conditions) + 
                len(structured_data.medications) + 
                len(structured_data.vital_signs) + 
                len(structured_data.lab_results) + 
                len(structured_data.procedures) + 
                len(structured_data.providers)
            )
            
            if total_resources == 0:
                issues.append("No medical data extracted - document may not contain clinical information")
            
            # Check minimum confidence
            if structured_data.confidence_average < self.min_confidence_threshold:
                issues.append(f"Low confidence score: {structured_data.confidence_average:.2f} (minimum: {self.min_confidence_threshold})")
            
            # Validate individual resource types
            self._validate_conditions(structured_data.conditions, issues)
            self._validate_medications(structured_data.medications, issues)
            self._validate_vital_signs(structured_data.vital_signs, issues)
            
            self.logger.info(f"Structured data validation: {len(issues)} issues found, {total_resources} resources extracted")
            
        except PydanticValidationError as e:
            issues.append(f"Pydantic validation failed: {str(e)}")
            self.logger.error(f"Pydantic validation error: {e}")
        
        return len(issues) == 0, issues
    
    def validate_fhir_resources(self, fhir_resources: List[Dict[str, Any]], context: Dict[str, Any] = None) -> Tuple[bool, List[str]]:
        """
        Validate FHIR resources before processing.
        
        Args:
            fhir_resources: List of FHIR resources to validate
            context: Optional context information
            
        Returns:
            Tuple of (is_valid: bool, issues: List[str])
        """
        issues = []
        
        if not fhir_resources:
            issues.append("No FHIR resources provided for validation")
            return False, issues
        
        # Validate each resource
        resource_counts = {}
        for i, resource in enumerate(fhir_resources):
            if not isinstance(resource, dict):
                issues.append(f"Resource {i} is not a dictionary")
                continue
            
            resource_type = resource.get('resourceType')
            if not resource_type:
                issues.append(f"Resource {i} missing resourceType")
                continue
            
            # Count resource types
            resource_counts[resource_type] = resource_counts.get(resource_type, 0) + 1
            
            # Validate required fields based on resource type
            resource_issues = self._validate_fhir_resource_structure(resource, resource_type)
            if resource_issues:
                issues.extend([f"Resource {i} ({resource_type}): {issue}" for issue in resource_issues])
        
        # Check for minimum required resource types
        required_types = ['Condition', 'MedicationStatement']
        for req_type in required_types:
            if req_type not in resource_counts:
                issues.append(f"Missing required resource type: {req_type}")
        
        self.logger.info(f"FHIR validation: {len(issues)} issues found, {len(fhir_resources)} resources, types: {resource_counts}")
        
        return len(issues) == 0, issues
    
    def validate_processing_completeness(self, document_data: Dict[str, Any], context: Dict[str, Any] = None) -> Tuple[bool, List[str]]:
        """
        Validate that document processing completed successfully.
        
        Args:
            document_data: Document processing results
            context: Optional context information
            
        Returns:
            Tuple of (is_valid: bool, issues: List[str])
        """
        issues = []
        
        # Check required fields in processing results
        required_fields = ['original_text', 'structured_data', 'fhir_resources']
        for field in required_fields:
            if field not in document_data:
                issues.append(f"Missing required processing field: {field}")
        
        # Validate processing status
        status = document_data.get('status')
        if status not in ['processed', 'completed']:
            issues.append(f"Invalid processing status: {status}")
        
        # Check for processing errors
        if 'error_log' in document_data and document_data['error_log']:
            error_log = document_data['error_log']
            if isinstance(error_log, list) and len(error_log) > 0:
                issues.append(f"Processing completed with {len(error_log)} errors")
        
        # Validate data consistency between structured data and FHIR resources
        structured_data = document_data.get('structured_data')
        fhir_resources = document_data.get('fhir_resources', [])
        
        if structured_data and fhir_resources:
            consistency_issues = self._validate_data_consistency(structured_data, fhir_resources)
            issues.extend(consistency_issues)
        
        self.logger.info(f"Processing completeness validation: {len(issues)} issues found")
        
        return len(issues) == 0, issues
    
    def _validate_conditions(self, conditions: List, issues: List[str]) -> None:
        """Validate medical conditions."""
        for i, condition in enumerate(conditions):
            if not condition.name or len(condition.name.strip()) < 2:
                issues.append(f"Condition {i} has invalid name")
            
            if condition.confidence < 0.1:
                issues.append(f"Condition {i} has very low confidence: {condition.confidence}")
    
    def _validate_medications(self, medications: List, issues: List[str]) -> None:
        """Validate medications."""
        for i, medication in enumerate(medications):
            if not medication.name or len(medication.name.strip()) < 2:
                issues.append(f"Medication {i} has invalid name")
            
            if medication.confidence < 0.1:
                issues.append(f"Medication {i} has very low confidence: {medication.confidence}")
            
            # Validate dosage format if present
            if medication.dosage and not any(unit in medication.dosage.lower() for unit in ['mg', 'ml', 'g', 'mcg', 'units']):
                issues.append(f"Medication {i} dosage may be incomplete: {medication.dosage}")
    
    def _validate_vital_signs(self, vital_signs: List, issues: List[str]) -> None:
        """Validate vital signs."""
        for i, vital in enumerate(vital_signs):
            if not vital.measurement or len(vital.measurement.strip()) < 2:
                issues.append(f"Vital sign {i} has invalid measurement type")
            
            if not vital.value or len(vital.value.strip()) < 1:
                issues.append(f"Vital sign {i} has no value")
    
    def _validate_fhir_resource_structure(self, resource: Dict[str, Any], resource_type: str) -> List[str]:
        """
        Validate individual FHIR resource structure.
        
        Args:
            resource: FHIR resource to validate
            resource_type: Type of FHIR resource
            
        Returns:
            List of validation issues
        """
        issues = []
        
        # Common required fields for all resources
        if 'subject' not in resource:
            issues.append("Missing required 'subject' field")
        
        # Resource-specific validation
        if resource_type == 'Condition':
            if 'code' not in resource:
                issues.append("Condition missing required 'code' field")
            if 'clinicalStatus' not in resource and 'verificationStatus' not in resource:
                issues.append("Condition missing status information")
        
        elif resource_type == 'MedicationStatement':
            if 'medicationCodeableConcept' not in resource and 'medicationReference' not in resource:
                issues.append("MedicationStatement missing medication information")
            if 'status' not in resource:
                issues.append("MedicationStatement missing status")
        
        elif resource_type == 'Observation':
            if 'code' not in resource:
                issues.append("Observation missing required 'code' field")
            if 'status' not in resource:
                issues.append("Observation missing status")
            if 'valueQuantity' not in resource and 'valueString' not in resource:
                issues.append("Observation missing value")
        
        return issues
    
    def _validate_data_consistency(self, structured_data: Dict[str, Any], fhir_resources: List[Dict[str, Any]]) -> List[str]:
        """
        Validate consistency between structured data and FHIR resources.
        
        Args:
            structured_data: Structured medical data
            fhir_resources: Generated FHIR resources
            
        Returns:
            List of consistency issues
        """
        issues = []
        
        try:
            # Count resources by type
            fhir_counts = {}
            for resource in fhir_resources:
                resource_type = resource.get('resourceType', 'Unknown')
                fhir_counts[resource_type] = fhir_counts.get(resource_type, 0) + 1
            
            # Check if structured data counts roughly match FHIR resource counts
            if isinstance(structured_data, dict):
                # Handle different structured data formats
                if 'conditions' in structured_data:
                    struct_conditions = len(structured_data.get('conditions', []))
                    fhir_conditions = fhir_counts.get('Condition', 0)
                    if abs(struct_conditions - fhir_conditions) > 2:  # Allow some variance
                        issues.append(f"Condition count mismatch: structured={struct_conditions}, FHIR={fhir_conditions}")
                
                if 'medications' in structured_data:
                    struct_medications = len(structured_data.get('medications', []))
                    fhir_medications = fhir_counts.get('MedicationStatement', 0)
                    if abs(struct_medications - fhir_medications) > 2:
                        issues.append(f"Medication count mismatch: structured={struct_medications}, FHIR={fhir_medications}")
        
        except Exception as e:
            issues.append(f"Error validating data consistency: {str(e)}")
            self.logger.error(f"Data consistency validation error: {e}")
        
        return issues


# Validation decorator for views
def validate_structured_data(validation_type: str = 'full'):
    """
    Decorator to add structured data validation to views.
    
    Args:
        validation_type: Type of validation to perform ('text', 'structured', 'fhir', 'full')
    """
    def decorator(view_func):
        def wrapper(request, *args, **kwargs):
            validator = DataValidationService()
            
            # Perform validation based on type
            if hasattr(request, 'validation_context'):
                request.validation_context['validations_performed'].append(validation_type)
            
            try:
                # Call the original view
                response = view_func(request, *args, **kwargs)
                
                # Post-process validation if needed
                if validation_type in ['structured', 'full'] and hasattr(response, 'content'):
                    # Validate response content if it contains structured data
                    try:
                        content = json.loads(response.content)
                        if 'structured_data' in content:
                            is_valid, issues = validator.validate_structured_extraction(
                                content['structured_data']
                            )
                            if not is_valid and hasattr(request, 'validation_context'):
                                request.validation_context['validation_errors'].extend(issues)
                    except (json.JSONDecodeError, KeyError):
                        pass  # Not JSON response or no structured data
                
                return response
                
            except (DataValidationError, PydanticModelError) as e:
                # Handle validation errors gracefully
                logger.error(f"Validation error in {view_func.__name__}: {e}")
                
                if hasattr(request, 'validation_context'):
                    request.validation_context['validation_errors'].append(str(e))
                
                # Return appropriate error response
                if request.headers.get('Content-Type') == 'application/json':
                    return JsonResponse({
                        'error': 'Validation failed',
                        'details': str(e),
                        'validation_type': validation_type
                    }, status=400)
                else:
                    # For HTML requests, let the view handle the error
                    raise ValidationError(f"Data validation failed: {e}")
        
        return wrapper
    return decorator


# Utility functions for manual validation
def validate_document_upload_data(document_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate document upload data manually.
    
    Args:
        document_data: Document data to validate
        
    Returns:
        Validation results dictionary
    """
    validator = DataValidationService()
    results = {
        'is_valid': True,
        'issues': [],
        'warnings': [],
        'validation_time_ms': 0
    }
    
    start_time = time.time()
    
    try:
        # Validate text quality if present
        if 'original_text' in document_data:
            text_valid, text_issues = validator.validate_text_quality(document_data['original_text'])
            if not text_valid:
                results['is_valid'] = False
                results['issues'].extend(text_issues)
        
        # Validate structured data if present
        if 'structured_data' in document_data:
            try:
                structured_data = StructuredMedicalExtraction(**document_data['structured_data'])
                struct_valid, struct_issues = validator.validate_structured_extraction(structured_data)
                if not struct_valid:
                    results['warnings'].extend(struct_issues)  # Warnings, not hard failures
            except Exception as e:
                results['issues'].append(f"Structured data validation error: {str(e)}")
                results['is_valid'] = False
        
        # Validate FHIR resources if present
        if 'fhir_resources' in document_data:
            fhir_valid, fhir_issues = validator.validate_fhir_resources(document_data['fhir_resources'])
            if not fhir_valid:
                results['warnings'].extend(fhir_issues)  # Warnings, not hard failures
    
    except Exception as e:
        results['is_valid'] = False
        results['issues'].append(f"Validation process error: {str(e)}")
        logger.error(f"Document validation error: {e}")
    
    finally:
        results['validation_time_ms'] = round((time.time() - start_time) * 1000, 2)
    
    return results


def validate_ai_extraction_input(text: str, document_id: str = None) -> bool:
    """
    Quick validation function for AI extraction input.
    
    Args:
        text: Text to validate
        document_id: Optional document ID for logging
        
    Returns:
        bool: True if text is suitable for AI extraction
    """
    validator = DataValidationService()
    is_valid, issues = validator.validate_text_quality(text)
    
    if not is_valid:
        logger.warning(f"AI extraction input validation failed for document {document_id}: {issues}")
    
    return is_valid


def validate_fhir_conversion_input(structured_data: StructuredMedicalExtraction) -> bool:
    """
    Quick validation function for FHIR conversion input.
    
    Args:
        structured_data: Structured medical data to validate
        
    Returns:
        bool: True if data is suitable for FHIR conversion
    """
    validator = DataValidationService()
    is_valid, issues = validator.validate_structured_extraction(structured_data)
    
    if not is_valid:
        logger.warning(f"FHIR conversion input validation failed: {issues}")
    
    return is_valid
