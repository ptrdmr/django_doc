"""
Custom Exception Classes for Document Processing Pipeline

This module defines custom exceptions for better error categorization and handling
throughout the document processing pipeline, supporting Task 34.5 error handling enhancement.

The exception hierarchy provides specific error types for:
- Document processing failures
- AI extraction issues
- FHIR conversion problems  
- Data validation errors
- External service failures

Author: Task 34.5 - Enhance error handling and logging
Date: 2025-09-17 15:46:02
"""

from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class DocumentProcessingError(Exception):
    """Base exception for all document processing errors."""
    
    def __init__(self, message: str, error_code: str = None, details: Dict[str, Any] = None):
        """
        Initialize a document processing error.
        
        Args:
            message: Human-readable error message
            error_code: Machine-readable error code for categorization
            details: Additional error context and metadata
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code or 'DOCUMENT_PROCESSING_ERROR'
        self.details = details or {}
        
        # Log the exception when created
        logger.error(f"DocumentProcessingError [{self.error_code}]: {message}", extra=self.details)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        return {
            'error_type': self.__class__.__name__,
            'message': self.message,
            'error_code': self.error_code,
            'details': self.details
        }


class PDFExtractionError(DocumentProcessingError):
    """Exception raised when PDF text extraction fails."""
    
    def __init__(self, message: str, file_path: str = None, page_number: int = None, **kwargs):
        details = kwargs.get('details', {})
        if file_path:
            details['file_path'] = file_path
        if page_number:
            details['page_number'] = page_number
            
        super().__init__(
            message=message,
            error_code='PDF_EXTRACTION_ERROR',
            details=details
        )


class AIExtractionError(DocumentProcessingError):
    """Exception raised when AI-powered data extraction fails."""
    
    def __init__(self, message: str, ai_service: str = None, model_used: str = None, **kwargs):
        details = kwargs.get('details', {})
        if ai_service:
            details['ai_service'] = ai_service
        if model_used:
            details['model_used'] = model_used
            
        super().__init__(
            message=message,
            error_code='AI_EXTRACTION_ERROR',
            details=details
        )


class AIServiceTimeoutError(AIExtractionError):
    """Exception raised when AI service requests timeout."""
    
    def __init__(self, message: str, timeout_seconds: float = None, **kwargs):
        details = kwargs.get('details', {})
        if timeout_seconds:
            details['timeout_seconds'] = timeout_seconds
            
        super().__init__(
            message=message,
            error_code='AI_SERVICE_TIMEOUT',
            details=details
        )


class AIServiceRateLimitError(AIExtractionError):
    """Exception raised when AI service rate limits are exceeded."""
    
    def __init__(self, message: str, retry_after: int = None, **kwargs):
        details = kwargs.get('details', {})
        if retry_after:
            details['retry_after_seconds'] = retry_after
            
        super().__init__(
            message=message,
            error_code='AI_SERVICE_RATE_LIMIT',
            details=details
        )


class AIResponseParsingError(AIExtractionError):
    """Exception raised when AI response cannot be parsed into expected format."""
    
    def __init__(self, message: str, raw_response: str = None, expected_format: str = None, **kwargs):
        details = kwargs.get('details', {})
        if raw_response:
            details['raw_response'] = raw_response[:500]  # Truncate for logging
        if expected_format:
            details['expected_format'] = expected_format
            
        super().__init__(
            message=message,
            error_code='AI_RESPONSE_PARSING_ERROR',
            details=details
        )


class FHIRConversionError(DocumentProcessingError):
    """Exception raised when FHIR resource conversion fails."""
    
    def __init__(self, message: str, resource_type: str = None, data_source: str = None, **kwargs):
        details = kwargs.get('details', {})
        if resource_type:
            details['resource_type'] = resource_type
        if data_source:
            details['data_source'] = data_source
            
        super().__init__(
            message=message,
            error_code='FHIR_CONVERSION_ERROR',
            details=details
        )


class FHIRValidationError(FHIRConversionError):
    """Exception raised when FHIR resource validation fails."""
    
    def __init__(self, message: str, validation_errors: list = None, **kwargs):
        details = kwargs.get('details', {})
        if validation_errors:
            details['validation_errors'] = validation_errors
            
        super().__init__(
            message=message,
            error_code='FHIR_VALIDATION_ERROR',
            details=details
        )


class DataValidationError(DocumentProcessingError):
    """Exception raised when extracted data validation fails."""
    
    def __init__(self, message: str, field_name: str = None, validation_rule: str = None, **kwargs):
        details = kwargs.get('details', {})
        if field_name:
            details['field_name'] = field_name
        if validation_rule:
            details['validation_rule'] = validation_rule
            
        super().__init__(
            message=message,
            error_code='DATA_VALIDATION_ERROR',
            details=details
        )


class PydanticModelError(DataValidationError):
    """Exception raised when Pydantic model validation fails."""
    
    def __init__(self, message: str, model_name: str = None, validation_errors: list = None, **kwargs):
        details = kwargs.get('details', {})
        if model_name:
            details['model_name'] = model_name
        if validation_errors:
            details['validation_errors'] = validation_errors
            
        super().__init__(
            message=message,
            error_code='PYDANTIC_MODEL_ERROR',
            details=details
        )


class ExternalServiceError(DocumentProcessingError):
    """Exception raised when external service calls fail."""
    
    def __init__(self, message: str, service_name: str = None, http_status: int = None, **kwargs):
        details = kwargs.get('details', {})
        if service_name:
            details['service_name'] = service_name
        if http_status:
            details['http_status'] = http_status
            
        super().__init__(
            message=message,
            error_code='EXTERNAL_SERVICE_ERROR',
            details=details
        )


class ConfigurationError(DocumentProcessingError):
    """Exception raised when system configuration is invalid."""
    
    def __init__(self, message: str, config_key: str = None, **kwargs):
        details = kwargs.get('details', {})
        if config_key:
            details['config_key'] = config_key
            
        super().__init__(
            message=message,
            error_code='CONFIGURATION_ERROR',
            details=details
        )


class CeleryTaskError(DocumentProcessingError):
    """Exception raised during Celery task execution."""
    
    def __init__(self, message: str, task_id: str = None, task_name: str = None, **kwargs):
        details = kwargs.get('details', {})
        if task_id:
            details['task_id'] = task_id
        if task_name:
            details['task_name'] = task_name
            
        super().__init__(
            message=message,
            error_code='CELERY_TASK_ERROR',
            details=details
        )


# Exception mapping for error recovery
ERROR_RECOVERY_STRATEGIES = {
    'AI_SERVICE_TIMEOUT': 'retry_with_backoff',
    'AI_SERVICE_RATE_LIMIT': 'wait_and_retry',
    'AI_RESPONSE_PARSING_ERROR': 'fallback_extraction',
    'PDF_EXTRACTION_ERROR': 'manual_review_required',
    'FHIR_VALIDATION_ERROR': 'relaxed_validation',
    'PYDANTIC_MODEL_ERROR': 'basic_extraction',
    'EXTERNAL_SERVICE_ERROR': 'retry_or_skip',
}


def get_recovery_strategy(error_code: str) -> str:
    """
    Get the recommended recovery strategy for an error code.
    
    Args:
        error_code: The error code to look up
        
    Returns:
        Recovery strategy name
    """
    return ERROR_RECOVERY_STRATEGIES.get(error_code, 'manual_intervention')


def categorize_exception(exception: Exception) -> Dict[str, Any]:
    """
    Categorize an exception for error reporting and recovery.
    
    Args:
        exception: The exception to categorize
        
    Returns:
        Dictionary with error category information
    """
    if isinstance(exception, DocumentProcessingError):
        return exception.to_dict()
    
    # Handle standard Python exceptions
    category_map = {
        'ConnectionError': 'EXTERNAL_SERVICE_ERROR',
        'TimeoutError': 'AI_SERVICE_TIMEOUT', 
        'ValueError': 'DATA_VALIDATION_ERROR',
        'KeyError': 'CONFIGURATION_ERROR',
        'FileNotFoundError': 'PDF_EXTRACTION_ERROR',
        'PermissionError': 'PDF_EXTRACTION_ERROR',
    }
    
    error_code = category_map.get(exception.__class__.__name__, 'UNKNOWN_ERROR')
    
    return {
        'error_type': exception.__class__.__name__,
        'message': str(exception),
        'error_code': error_code,
        'details': {'original_exception': True}
    }


# Export all exception classes
__all__ = [
    'DocumentProcessingError',
    'PDFExtractionError', 
    'AIExtractionError',
    'AIServiceTimeoutError',
    'AIServiceRateLimitError',
    'AIResponseParsingError',
    'FHIRConversionError',
    'FHIRValidationError',
    'DataValidationError',
    'PydanticModelError',
    'ExternalServiceError',
    'ConfigurationError',
    'CeleryTaskError',
    'get_recovery_strategy',
    'categorize_exception',
]
