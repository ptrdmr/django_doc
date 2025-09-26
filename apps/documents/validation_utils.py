"""
Validation utilities for integrating the validation middleware with document processing.

Provides helper functions and integration points for using validation throughout
the document processing pipeline.
"""

import logging
from typing import Dict, Any, List, Tuple, Optional
from django.conf import settings
from django.core.exceptions import ValidationError

from .middleware import DataValidationService
from .services.ai_extraction import StructuredMedicalExtraction
from .exceptions import DataValidationError, PydanticModelError

logger = logging.getLogger(__name__)


class DocumentProcessingValidator:
    """
    High-level validator for document processing pipeline.
    
    Provides validation at each stage of the pipeline with appropriate
    error handling and recovery mechanisms.
    """
    
    def __init__(self):
        """Initialize the document processing validator."""
        self.validator = DataValidationService()
        self.validation_enabled = getattr(settings, 'ENABLE_DOCUMENT_VALIDATION', True)
        self.strict_mode = getattr(settings, 'STRICT_VALIDATION_MODE', False)
    
    def validate_pre_ai_extraction(self, document, text: str) -> Dict[str, Any]:
        """
        Validate document and text before AI extraction.
        
        Args:
            document: Document model instance
            text: Extracted text to validate
            
        Returns:
            Dict with validation results and recommendations
        """
        validation_result = {
            'stage': 'pre_ai_extraction',
            'is_valid': True,
            'issues': [],
            'warnings': [],
            'recommendations': [],
            'can_proceed': True
        }
        
        if not self.validation_enabled:
            validation_result['skipped'] = True
            return validation_result
        
        try:
            # Validate text quality
            text_valid, text_issues = self.validator.validate_text_quality(text, {
                'document_id': str(document.id),
                'filename': document.filename
            })
            
            if not text_valid:
                validation_result['is_valid'] = False
                validation_result['issues'].extend(text_issues)
                
                if self.strict_mode:
                    validation_result['can_proceed'] = False
                else:
                    validation_result['warnings'].extend(text_issues)
                    validation_result['recommendations'].append(
                        "Consider manual review - text quality issues detected"
                    )
            
            # Additional document-specific validations
            self._validate_document_metadata(document, validation_result)
            
            logger.info(f"Pre-AI validation for document {document.id}: {len(validation_result['issues'])} issues, can_proceed={validation_result['can_proceed']}")
            
        except Exception as e:
            logger.error(f"Error in pre-AI validation for document {document.id}: {e}")
            validation_result['is_valid'] = False
            validation_result['issues'].append(f"Validation process error: {str(e)}")
            validation_result['can_proceed'] = False
        
        return validation_result
    
    def validate_post_ai_extraction(self, document, structured_data: StructuredMedicalExtraction) -> Dict[str, Any]:
        """
        Validate results after AI extraction.
        
        Args:
            document: Document model instance
            structured_data: StructuredMedicalExtraction instance
            
        Returns:
            Dict with validation results and recommendations
        """
        validation_result = {
            'stage': 'post_ai_extraction',
            'is_valid': True,
            'issues': [],
            'warnings': [],
            'recommendations': [],
            'can_proceed': True
        }
        
        if not self.validation_enabled:
            validation_result['skipped'] = True
            return validation_result
        
        try:
            # Validate structured extraction
            struct_valid, struct_issues = self.validator.validate_structured_extraction(structured_data, {
                'document_id': str(document.id)
            })
            
            if not struct_valid:
                validation_result['is_valid'] = False
                validation_result['issues'].extend(struct_issues)
                
                if self.strict_mode:
                    validation_result['can_proceed'] = False
                else:
                    validation_result['warnings'].extend(struct_issues)
                    validation_result['recommendations'].append(
                        "Consider manual review - AI extraction quality issues detected"
                    )
            
            # Add extraction quality recommendations
            self._add_extraction_quality_recommendations(structured_data, validation_result)
            
            logger.info(f"Post-AI validation for document {document.id}: {len(validation_result['issues'])} issues, confidence={structured_data.confidence_average:.2f}")
            
        except Exception as e:
            logger.error(f"Error in post-AI validation for document {document.id}: {e}")
            validation_result['is_valid'] = False
            validation_result['issues'].append(f"AI validation process error: {str(e)}")
            validation_result['can_proceed'] = False
        
        return validation_result
    
    def validate_pre_fhir_conversion(self, document, structured_data: StructuredMedicalExtraction) -> Dict[str, Any]:
        """
        Validate data before FHIR conversion.
        
        Args:
            document: Document model instance
            structured_data: StructuredMedicalExtraction instance
            
        Returns:
            Dict with validation results and recommendations
        """
        validation_result = {
            'stage': 'pre_fhir_conversion',
            'is_valid': True,
            'issues': [],
            'warnings': [],
            'recommendations': [],
            'can_proceed': True
        }
        
        if not self.validation_enabled:
            validation_result['skipped'] = True
            return validation_result
        
        try:
            # Check if data is suitable for FHIR conversion
            total_resources = (
                len(structured_data.conditions) + 
                len(structured_data.medications) + 
                len(structured_data.vital_signs) + 
                len(structured_data.lab_results) + 
                len(structured_data.procedures)
            )
            
            if total_resources == 0:
                validation_result['is_valid'] = False
                validation_result['issues'].append("No medical data available for FHIR conversion")
                validation_result['can_proceed'] = False
            
            # Check minimum data quality for FHIR
            if structured_data.confidence_average < 0.4:
                validation_result['warnings'].append(
                    f"Low confidence for FHIR conversion: {structured_data.confidence_average:.2f}"
                )
                validation_result['recommendations'].append(
                    "Consider manual review before FHIR conversion"
                )
            
            logger.info(f"Pre-FHIR validation for document {document.id}: {total_resources} resources, confidence={structured_data.confidence_average:.2f}")
            
        except Exception as e:
            logger.error(f"Error in pre-FHIR validation for document {document.id}: {e}")
            validation_result['is_valid'] = False
            validation_result['issues'].append(f"FHIR validation process error: {str(e)}")
            validation_result['can_proceed'] = False
        
        return validation_result
    
    def validate_post_fhir_conversion(self, document, fhir_resources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate FHIR resources after conversion.
        
        Args:
            document: Document model instance
            fhir_resources: List of generated FHIR resources
            
        Returns:
            Dict with validation results and recommendations
        """
        validation_result = {
            'stage': 'post_fhir_conversion',
            'is_valid': True,
            'issues': [],
            'warnings': [],
            'recommendations': [],
            'can_proceed': True
        }
        
        if not self.validation_enabled:
            validation_result['skipped'] = True
            return validation_result
        
        try:
            # Validate FHIR resources
            fhir_valid, fhir_issues = self.validator.validate_fhir_resources(fhir_resources, {
                'document_id': str(document.id)
            })
            
            if not fhir_valid:
                validation_result['is_valid'] = False
                validation_result['issues'].extend(fhir_issues)
                
                if self.strict_mode:
                    validation_result['can_proceed'] = False
                else:
                    validation_result['warnings'].extend(fhir_issues)
                    validation_result['recommendations'].append(
                        "FHIR resources have validation issues - consider manual review"
                    )
            
            # Add FHIR quality recommendations
            self._add_fhir_quality_recommendations(fhir_resources, validation_result)
            
            logger.info(f"Post-FHIR validation for document {document.id}: {len(fhir_resources)} resources, {len(validation_result['issues'])} issues")
            
        except Exception as e:
            logger.error(f"Error in post-FHIR validation for document {document.id}: {e}")
            validation_result['is_valid'] = False
            validation_result['issues'].append(f"FHIR validation process error: {str(e)}")
            validation_result['can_proceed'] = False
        
        return validation_result
    
    def validate_final_processing(self, document, processing_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate final processing results.
        
        Args:
            document: Document model instance
            processing_data: Complete processing results
            
        Returns:
            Dict with validation results and final status
        """
        validation_result = {
            'stage': 'final_processing',
            'is_valid': True,
            'issues': [],
            'warnings': [],
            'recommendations': [],
            'final_status': 'completed'
        }
        
        if not self.validation_enabled:
            validation_result['skipped'] = True
            return validation_result
        
        try:
            # Validate processing completeness
            complete_valid, complete_issues = self.validator.validate_processing_completeness(processing_data, {
                'document_id': str(document.id)
            })
            
            if not complete_valid:
                validation_result['is_valid'] = False
                validation_result['issues'].extend(complete_issues)
                validation_result['final_status'] = 'completed_with_warnings'
            
            # Determine final recommendations
            self._determine_final_recommendations(processing_data, validation_result)
            
            logger.info(f"Final validation for document {document.id}: status={validation_result['final_status']}, issues={len(validation_result['issues'])}")
            
        except Exception as e:
            logger.error(f"Error in final validation for document {document.id}: {e}")
            validation_result['is_valid'] = False
            validation_result['issues'].append(f"Final validation process error: {str(e)}")
            validation_result['final_status'] = 'failed'
        
        return validation_result
    
    def _validate_document_metadata(self, document, validation_result: Dict[str, Any]) -> None:
        """Validate document metadata."""
        if not document.filename:
            validation_result['warnings'].append("Document has no filename")
        
        if not document.patient:
            validation_result['issues'].append("Document has no associated patient")
            validation_result['is_valid'] = False
        
        if document.file_size and document.file_size > 50 * 1024 * 1024:  # 50MB
            validation_result['warnings'].append(f"Large file size: {document.file_size / (1024*1024):.1f}MB")
    
    def _add_extraction_quality_recommendations(self, structured_data: StructuredMedicalExtraction, validation_result: Dict[str, Any]) -> None:
        """Add recommendations based on extraction quality."""
        # Recommend review for low confidence items
        low_confidence_items = []
        
        for condition in structured_data.conditions:
            if condition.confidence < 0.6:
                low_confidence_items.append(f"Condition: {condition.name}")
        
        for medication in structured_data.medications:
            if medication.confidence < 0.6:
                low_confidence_items.append(f"Medication: {medication.name}")
        
        if low_confidence_items:
            validation_result['recommendations'].append(
                f"Manual review recommended for low-confidence items: {', '.join(low_confidence_items[:3])}{'...' if len(low_confidence_items) > 3 else ''}"
            )
        
        # Recommend expansion for missing data types
        if not structured_data.vital_signs and not structured_data.lab_results:
            validation_result['recommendations'].append(
                "Document may contain vital signs or lab results not extracted - consider manual review"
            )
    
    def _add_fhir_quality_recommendations(self, fhir_resources: List[Dict[str, Any]], validation_result: Dict[str, Any]) -> None:
        """Add recommendations based on FHIR resource quality."""
        resource_counts = {}
        for resource in fhir_resources:
            resource_type = resource.get('resourceType', 'Unknown')
            resource_counts[resource_type] = resource_counts.get(resource_type, 0) + 1
        
        # Recommend review for minimal data
        if len(fhir_resources) < 3:
            validation_result['recommendations'].append(
                "Limited FHIR resources generated - document may need manual enhancement"
            )
        
        # Check for balanced resource types
        if resource_counts.get('Condition', 0) == 0:
            validation_result['warnings'].append("No Condition resources generated")
        
        if resource_counts.get('MedicationStatement', 0) == 0:
            validation_result['warnings'].append("No MedicationStatement resources generated")
    
    def _determine_final_recommendations(self, processing_data: Dict[str, Any], validation_result: Dict[str, Any]) -> None:
        """Determine final processing recommendations."""
        # Check overall processing quality
        if 'error_log' in processing_data and processing_data['error_log']:
            validation_result['recommendations'].append(
                "Processing completed with errors - manual review recommended"
            )
        
        # Check data completeness
        structured_data = processing_data.get('structured_data', {})
        fhir_resources = processing_data.get('fhir_resources', [])
        
        if not structured_data and not fhir_resources:
            validation_result['recommendations'].append(
                "No medical data extracted - document may not contain clinical information"
            )
        elif len(fhir_resources) < 2:
            validation_result['recommendations'].append(
                "Limited medical data extracted - consider manual enhancement"
            )


class ValidationPipelineIntegrator:
    """
    Integrates validation into the existing document processing pipeline.
    
    Provides methods to inject validation at appropriate points in the workflow
    without disrupting existing functionality.
    """
    
    def __init__(self):
        """Initialize the pipeline integrator."""
        self.validator = DocumentProcessingValidator()
    
    def validate_and_process_document(self, document, text: str, ai_extraction_func, fhir_conversion_func) -> Dict[str, Any]:
        """
        Process document with validation at each stage.
        
        Args:
            document: Document model instance
            text: Extracted text
            ai_extraction_func: Function to perform AI extraction
            fhir_conversion_func: Function to perform FHIR conversion
            
        Returns:
            Complete processing results with validation information
        """
        processing_results = {
            'document_id': str(document.id),
            'validations': [],
            'overall_success': True,
            'processing_data': {}
        }
        
        try:
            # Stage 1: Pre-AI extraction validation
            pre_ai_validation = self.validator.validate_pre_ai_extraction(document, text)
            processing_results['validations'].append(pre_ai_validation)
            
            if not pre_ai_validation['can_proceed']:
                processing_results['overall_success'] = False
                processing_results['failure_stage'] = 'pre_ai_extraction'
                return processing_results
            
            # Stage 2: AI extraction (with validation)
            structured_data = ai_extraction_func(text)
            processing_results['processing_data']['structured_data'] = structured_data
            
            # Stage 3: Post-AI extraction validation
            post_ai_validation = self.validator.validate_post_ai_extraction(document, structured_data)
            processing_results['validations'].append(post_ai_validation)
            
            if not post_ai_validation['can_proceed']:
                processing_results['overall_success'] = False
                processing_results['failure_stage'] = 'post_ai_extraction'
                return processing_results
            
            # Stage 4: Pre-FHIR conversion validation
            pre_fhir_validation = self.validator.validate_pre_fhir_conversion(document, structured_data)
            processing_results['validations'].append(pre_fhir_validation)
            
            if not pre_fhir_validation['can_proceed']:
                processing_results['overall_success'] = False
                processing_results['failure_stage'] = 'pre_fhir_conversion'
                return processing_results
            
            # Stage 5: FHIR conversion (with validation)
            fhir_resources = fhir_conversion_func(structured_data)
            processing_results['processing_data']['fhir_resources'] = fhir_resources
            
            # Stage 6: Post-FHIR conversion validation
            post_fhir_validation = self.validator.validate_post_fhir_conversion(document, fhir_resources)
            processing_results['validations'].append(post_fhir_validation)
            
            if not post_fhir_validation['can_proceed']:
                processing_results['overall_success'] = False
                processing_results['failure_stage'] = 'post_fhir_conversion'
                return processing_results
            
            # Stage 7: Final processing validation
            final_processing_data = {
                'original_text': text,
                'structured_data': structured_data.dict(),
                'fhir_resources': fhir_resources,
                'status': 'processed'
            }
            
            final_validation = self.validator.validate_final_processing(document, final_processing_data)
            processing_results['validations'].append(final_validation)
            processing_results['processing_data'].update(final_processing_data)
            
            # Determine final status
            if final_validation['final_status'] == 'failed':
                processing_results['overall_success'] = False
                processing_results['failure_stage'] = 'final_processing'
            
            logger.info(f"Complete validation pipeline for document {document.id}: success={processing_results['overall_success']}")
            
        except Exception as e:
            logger.error(f"Error in validation pipeline for document {document.id}: {e}")
            processing_results['overall_success'] = False
            processing_results['failure_stage'] = 'pipeline_error'
            processing_results['error'] = str(e)
        
        return processing_results
    
    def get_validation_summary(self, processing_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a summary of validation results.
        
        Args:
            processing_results: Results from validate_and_process_document
            
        Returns:
            Summary of validation results
        """
        summary = {
            'document_id': processing_results.get('document_id'),
            'overall_success': processing_results.get('overall_success', False),
            'stages_completed': len(processing_results.get('validations', [])),
            'total_issues': 0,
            'total_warnings': 0,
            'total_recommendations': 0,
            'stage_results': []
        }
        
        for validation in processing_results.get('validations', []):
            stage_summary = {
                'stage': validation['stage'],
                'is_valid': validation['is_valid'],
                'issues_count': len(validation['issues']),
                'warnings_count': len(validation['warnings']),
                'recommendations_count': len(validation['recommendations'])
            }
            
            summary['total_issues'] += stage_summary['issues_count']
            summary['total_warnings'] += stage_summary['warnings_count']
            summary['total_recommendations'] += stage_summary['recommendations_count']
            summary['stage_results'].append(stage_summary)
        
        return summary


# Helper functions for integration
def validate_before_ai_extraction(document, text: str) -> bool:
    """
    Quick validation before AI extraction.
    
    Args:
        document: Document model instance
        text: Text to validate
        
    Returns:
        bool: True if processing should continue
    """
    try:
        validator = DocumentProcessingValidator()
        result = validator.validate_pre_ai_extraction(document, text)
        return result['can_proceed']
    except Exception as e:
        logger.error(f"Error in pre-AI validation check: {e}")
        return True  # Allow processing to continue on validation errors


def validate_after_ai_extraction(document, structured_data: StructuredMedicalExtraction) -> bool:
    """
    Quick validation after AI extraction.
    
    Args:
        document: Document model instance
        structured_data: StructuredMedicalExtraction instance
        
    Returns:
        bool: True if processing should continue
    """
    try:
        validator = DocumentProcessingValidator()
        result = validator.validate_post_ai_extraction(document, structured_data)
        return result['can_proceed']
    except Exception as e:
        logger.error(f"Error in post-AI validation check: {e}")
        return True  # Allow processing to continue on validation errors


def validate_before_fhir_conversion(document, structured_data: StructuredMedicalExtraction) -> bool:
    """
    Quick validation before FHIR conversion.
    
    Args:
        document: Document model instance
        structured_data: StructuredMedicalExtraction instance
        
    Returns:
        bool: True if processing should continue
    """
    try:
        validator = DocumentProcessingValidator()
        result = validator.validate_pre_fhir_conversion(document, structured_data)
        return result['can_proceed']
    except Exception as e:
        logger.error(f"Error in pre-FHIR validation check: {e}")
        return True  # Allow processing to continue on validation errors


def get_validation_recommendations(document) -> List[str]:
    """
    Get validation recommendations for a document.
    
    Args:
        document: Document model instance
        
    Returns:
        List of validation recommendations
    """
    recommendations = []
    
    try:
        # Check if document has validation issues stored
        if hasattr(document, 'error_log') and document.error_log:
            error_log = document.error_log
            if isinstance(error_log, list) and len(error_log) > 0:
                recommendations.append("Document processed with errors - manual review recommended")
        
        # Check confidence levels if structured data is available
        if hasattr(document, 'structured_data') and document.structured_data:
            confidence = document.get_extraction_confidence()
            if confidence and confidence < 0.6:
                recommendations.append(f"Low extraction confidence ({confidence:.2f}) - manual review recommended")
        
        # Check processing time
        if hasattr(document, 'processing_time_ms') and document.processing_time_ms:
            if document.processing_time_ms > 30000:  # 30 seconds
                recommendations.append("Long processing time detected - document may be complex")
    
    except Exception as e:
        logger.error(f"Error generating validation recommendations for document {document.id}: {e}")
        recommendations.append("Unable to generate recommendations - manual review suggested")
    
    return recommendations


# Configuration helper
def configure_validation_settings() -> Dict[str, Any]:
    """
    Get current validation configuration.
    
    Returns:
        Dict with current validation settings
    """
    return {
        'validation_enabled': getattr(settings, 'ENABLE_DOCUMENT_VALIDATION', True),
        'strict_mode': getattr(settings, 'STRICT_VALIDATION_MODE', False),
        'min_confidence_threshold': getattr(settings, 'MIN_CONFIDENCE_THRESHOLD', 0.3),
        'max_processing_time_ms': getattr(settings, 'MAX_PROCESSING_TIME_MS', 60000),
        'enable_audit_logging': getattr(settings, 'ENABLE_VALIDATION_AUDIT_LOGGING', True),
    }


# Context manager for validation
class ValidationContext:
    """
    Context manager for validation operations.
    
    Provides centralized validation management with proper error handling
    and cleanup.
    """
    
    def __init__(self, document, stage: str = 'unknown'):
        """
        Initialize validation context.
        
        Args:
            document: Document model instance
            stage: Current processing stage
        """
        self.document = document
        self.stage = stage
        self.validator = DocumentProcessingValidator()
        self.start_time = None
        self.validation_results = []
    
    def __enter__(self):
        """Enter validation context."""
        self.start_time = timezone.now()
        logger.info(f"Starting validation context for document {self.document.id} at stage {self.stage}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit validation context with cleanup."""
        if self.start_time:
            duration = (timezone.now() - self.start_time).total_seconds() * 1000
            logger.info(f"Validation context completed for document {self.document.id}: {duration:.2f}ms")
        
        # Log any exceptions that occurred
        if exc_type:
            logger.error(f"Exception in validation context for document {self.document.id}: {exc_val}")
    
    def validate_text(self, text: str) -> Dict[str, Any]:
        """Validate text within context."""
        result = self.validator.validate_pre_ai_extraction(self.document, text)
        self.validation_results.append(result)
        return result
    
    def validate_structured_data(self, structured_data: StructuredMedicalExtraction) -> Dict[str, Any]:
        """Validate structured data within context."""
        result = self.validator.validate_post_ai_extraction(self.document, structured_data)
        self.validation_results.append(result)
        return result
    
    def validate_fhir_resources(self, fhir_resources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate FHIR resources within context."""
        result = self.validator.validate_post_fhir_conversion(self.document, fhir_resources)
        self.validation_results.append(result)
        return result
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all validations performed in this context."""
        return {
            'document_id': str(self.document.id),
            'stage': self.stage,
            'total_validations': len(self.validation_results),
            'all_valid': all(result['is_valid'] for result in self.validation_results),
            'can_proceed': all(result['can_proceed'] for result in self.validation_results),
            'validation_results': self.validation_results
        }
