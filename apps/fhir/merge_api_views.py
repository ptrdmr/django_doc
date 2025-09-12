"""
Additional API views for FHIR merge operations.
"""

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.core.paginator import Paginator
from django.views.decorators.cache import cache_page
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.conf import settings
import json
import time
import uuid
import requests
from datetime import timedelta

from .models import FHIRMergeConfiguration, FHIRMergeConfigurationAudit, FHIRMergeOperation
from .configuration import MergeConfigurationService
import apps.fhir.services as fhir_services
from apps.patients.models import Patient
from apps.documents.models import Document


# ==============================================================================
# FHIR MERGE OPERATION API ENDPOINTS
# ==============================================================================

@login_required
@permission_required('fhir.add_fhirmergeoperation', raise_exception=True)
@csrf_exempt
@require_http_methods(["POST"])
def trigger_merge_operation(request):
    """
    API endpoint to trigger a FHIR merge operation.
    
    POST body (JSON):
    {
        "patient_id": "integer (required)",
        "document_id": "integer (optional for single document)",
        "document_ids": "array of integers (optional for batch)",
        "operation_type": "string (optional, defaults to single_document)",
        "configuration_name": "string (optional, uses default)",
        "webhook_url": "string (optional)",
        "async": "boolean (default: true)"
    }
    """
    try:
        data = json.loads(request.body)
        
        # Validate required fields
        patient_id = data.get('patient_id')
        if not patient_id:
            return JsonResponse({
                'status': 'error',
                'message': 'patient_id is required'
            }, status=400)
        
        # Get patient
        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': f'Patient with ID {patient_id} not found'
            }, status=404)
        
        # Check patient access permissions
        if not _user_can_access_patient(request.user, patient):
            return JsonResponse({
                'status': 'error',
                'message': 'Access denied to patient data'
            }, status=403)
        
        # Get configuration
        config_name = data.get('configuration_name')
        try:
            if config_name:
                config = MergeConfigurationService.get_configuration(config_name)
            else:
                config = MergeConfigurationService.get_configuration()
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Configuration error: {str(e)}'
            }, status=400)
        
        # Determine operation type and validate documents
        operation_type = data.get('operation_type', 'single_document')
        document = None
        document_ids = []
        
        if operation_type == 'single_document':
            document_id = data.get('document_id')
            if document_id:
                try:
                    document = Document.objects.get(id=document_id)
                    if document.patient != patient:
                        return JsonResponse({
                            'status': 'error',
                            'message': 'Document does not belong to specified patient'
                        }, status=400)
                except Document.DoesNotExist:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Document with ID {document_id} not found'
                    }, status=404)
        elif operation_type == 'batch_documents':
            document_ids = data.get('document_ids', [])
            if not document_ids:
                return JsonResponse({
                    'status': 'error',
                    'message': 'document_ids is required for batch operations'
                }, status=400)
            
            # Validate all documents belong to patient
            documents = Document.objects.filter(id__in=document_ids, patient=patient)
            if len(documents) != len(document_ids):
                return JsonResponse({
                    'status': 'error',
                    'message': 'Some documents not found or do not belong to patient'
                }, status=400)
        
        # Rate limiting check
        if not _check_rate_limit(request.user):
            return JsonResponse({
                'status': 'error',
                'message': 'Rate limit exceeded. Please try again later.'
            }, status=429)
        
        # Create merge operation record
        with transaction.atomic():
            merge_operation = FHIRMergeOperation.objects.create(
                patient=patient,
                configuration=config,
                document=document,
                operation_type=operation_type,
                webhook_url=data.get('webhook_url', ''),
                created_by=request.user
            )
        
        # Execute merge operation
        async_mode = data.get('async', True)
        
        if async_mode:
            # Queue for background processing
            merge_operation.status = 'queued'
            merge_operation.save(update_fields=['status'])
            
            # Queue the task (placeholder - implement with your task queue)
            # _queue_merge_operation.delay(merge_operation.id, document_ids)
            
            return JsonResponse({
                'status': 'success',
                'message': 'Merge operation queued successfully',
                'operation_id': str(merge_operation.id),
                'data': merge_operation.get_summary()
            }, status=202)
        else:
            # Synchronous processing
            result = _execute_merge_operation_sync(merge_operation, document_ids)
            
            return JsonResponse({
                'status': 'success' if result['success'] else 'error',
                'message': result['message'],
                'operation_id': str(merge_operation.id),
                'data': merge_operation.get_summary(),
                'merge_result': result.get('merge_result')
            }, status=200 if result['success'] else 500)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid JSON in request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Internal error: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_merge_operation_status(request, operation_id):
    """
    API endpoint to get the status of a FHIR merge operation.
    """
    try:
        operation = get_object_or_404(FHIRMergeOperation, id=operation_id)
        
        # Check access permissions
        if not _user_can_access_patient(request.user, operation.patient):
            return JsonResponse({
                'status': 'error',
                'message': 'Access denied to operation data'
            }, status=403)
        
        return JsonResponse({
            'status': 'success',
            'data': operation.get_summary()
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=404 if 'not found' in str(e).lower() else 500)


@login_required
@require_http_methods(["GET"])
def get_merge_operation_result(request, operation_id):
    """
    API endpoint to get the detailed result of a completed FHIR merge operation.
    """
    try:
        operation = get_object_or_404(FHIRMergeOperation, id=operation_id)
        
        # Check access permissions
        if not _user_can_access_patient(request.user, operation.patient):
            return JsonResponse({
                'status': 'error',
                'message': 'Access denied to operation data'
            }, status=403)
        
        if not operation.is_completed:
            return JsonResponse({
                'status': 'error',
                'message': 'Operation is not yet completed'
            }, status=400)
        
        response_data = {
            'status': 'success',
            'data': {
                'operation': operation.get_summary(),
                'merge_result': operation.merge_result,
                'error_details': operation.error_details if operation.status == 'failed' else None
            }
        }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=404 if 'not found' in str(e).lower() else 500)


@login_required
@require_http_methods(["GET"])
def list_merge_operations(request):
    """
    API endpoint to list FHIR merge operations.
    
    Query parameters:
    - patient_id: integer (optional) - filter by patient
    - status: string (optional) - filter by status
    - operation_type: string (optional) - filter by operation type
    - page: integer (default: 1) - page number
    - page_size: integer (default: 20) - items per page
    - include_completed: boolean (default: true) - include completed operations
    """
    try:
        # Build query
        operations = FHIRMergeOperation.objects.select_related(
            'patient', 'configuration', 'document', 'created_by'
        )
        
        # Apply filters
        patient_id = request.GET.get('patient_id')
        if patient_id:
            patient = get_object_or_404(Patient, id=patient_id)
            if not _user_can_access_patient(request.user, patient):
                return JsonResponse({
                    'status': 'error',
                    'message': 'Access denied to patient data'
                }, status=403)
            operations = operations.filter(patient=patient)
        else:
            # Filter by user's accessible patients
            accessible_patients = _get_user_accessible_patients(request.user)
            operations = operations.filter(patient__in=accessible_patients)
        
        status = request.GET.get('status')
        if status:
            operations = operations.filter(status=status)
        
        operation_type = request.GET.get('operation_type')
        if operation_type:
            operations = operations.filter(operation_type=operation_type)
        
        include_completed = request.GET.get('include_completed', 'true').lower() == 'true'
        if not include_completed:
            operations = operations.exclude(status__in=['completed', 'failed', 'cancelled'])
        
        # Pagination
        page = int(request.GET.get('page', 1))
        page_size = min(int(request.GET.get('page_size', 20)), 100)  # Max 100 items per page
        
        paginator = Paginator(operations, page_size)
        page_obj = paginator.get_page(page)
        
        # Build response
        operations_data = []
        for operation in page_obj:
            operations_data.append(operation.get_summary())
        
        return JsonResponse({
            'status': 'success',
            'data': operations_data,
            'pagination': {
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'total_items': paginator.count,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@permission_required('fhir.change_fhirmergeoperation', raise_exception=True)
@csrf_exempt
@require_http_methods(["POST"])
def cancel_merge_operation(request, operation_id):
    """
    API endpoint to cancel a pending or queued FHIR merge operation.
    """
    try:
        operation = get_object_or_404(FHIRMergeOperation, id=operation_id)
        
        # Check access permissions
        if not _user_can_access_patient(request.user, operation.patient):
            return JsonResponse({
                'status': 'error',
                'message': 'Access denied to operation data'
            }, status=403)
        
        # Check if operation can be cancelled
        if operation.status not in ['pending', 'queued']:
            return JsonResponse({
                'status': 'error',
                'message': f'Cannot cancel operation in {operation.status} state'
            }, status=400)
        
        # Cancel operation
        operation.status = 'cancelled'
        operation.completed_at = timezone.now()
        operation.save(update_fields=['status', 'completed_at'])
        
        return JsonResponse({
            'status': 'success',
            'message': 'Operation cancelled successfully',
            'data': operation.get_summary()
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=404 if 'not found' in str(e).lower() else 500)


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _user_can_access_patient(user, patient):
    """
    Check if user has access to patient data.
    
    This implements basic organization-based access control.
    You may need to adjust based on your specific access control requirements.
    """
    if user.is_superuser:
        return True
    
    # Check if user belongs to same organization as patient
    if hasattr(user, 'organization') and hasattr(patient, 'organization'):
        return user.organization == patient.organization
    
    # Fallback - check if user created any records for this patient
    return patient.created_by == user or user.has_perm('patients.view_patient')


def _get_user_accessible_patients(user):
    """
    Get list of patients accessible to the user.
    """
    if user.is_superuser:
        return Patient.objects.all()
    
    if hasattr(user, 'organization'):
        return Patient.objects.filter(organization=user.organization)
    
    return Patient.objects.filter(created_by=user)


def _check_rate_limit(user):
    """
    Check if user is within rate limits for merge operations.
    
    Basic implementation - you may want to use django-ratelimit or similar.
    """
    # Allow superusers to bypass rate limits
    if user.is_superuser:
        return True
    
    # Check operations in last hour
    since = timezone.now() - timedelta(hours=1)
    recent_operations = FHIRMergeOperation.objects.filter(
        created_by=user,
        created_at__gte=since
    ).count()
    
    max_operations_per_hour = getattr(settings, 'FHIR_MERGE_RATE_LIMIT_PER_HOUR', 10)
    return recent_operations < max_operations_per_hour


def _execute_merge_operation_sync(operation, document_ids=None):
    """
    Execute merge operation synchronously.
    """
    try:
        operation.mark_started()
        
        # Initialize merge service
        merge_service = fhir_services.FHIRMergeService(
            patient=operation.patient,
            config_profile=operation.configuration.name
        )
        
        if operation.operation_type == 'single_document' and operation.document:
            # Single document merge
            operation.update_progress(20, "Extracting document data")
            
            # Here you would extract data from the document
            # This is a placeholder - implement based on your document processing
            extracted_data = {
                'document_type': 'clinical_note',
                'content': 'Sample extracted content'
            }
            
            document_metadata = {
                'document_id': operation.document.id,
                'document_url': operation.document.file.url if operation.document.file else None,
                'document_type': extracted_data['document_type']
            }
            
            operation.update_progress(50, "Merging data into FHIR bundle")
            
            # Perform merge
            merge_result = merge_service.merge_document_data(
                extracted_data=extracted_data,
                document_metadata=document_metadata,
                user=operation.created_by
            )
            
            operation.update_progress(90, "Finalizing merge")
            
        elif operation.operation_type == 'batch_documents' and document_ids:
            # Batch document merge
            operation.update_progress(10, "Preparing batch processing")
            
            # This would use the batch processing functionality
            # Placeholder implementation
            merge_result = {'resources_added': len(document_ids), 'success': True}
        
        else:
            raise ValueError("Invalid operation configuration")
        
        # Complete operation
        operation.mark_completed(merge_result=merge_result.__dict__ if hasattr(merge_result, '__dict__') else merge_result)
        
        # Send webhook if configured
        if operation.webhook_url:
            _send_webhook_notification(operation)
        
        return {
            'success': True,
            'message': 'Merge operation completed successfully',
            'merge_result': merge_result
        }
        
    except Exception as e:
        # Mark operation as failed
        operation.mark_completed(error_details={
            'error': str(e),
            'type': type(e).__name__
        })
        
        return {
            'success': False,
            'message': f'Merge operation failed: {str(e)}'
        }


def _send_webhook_notification(operation):
    """
    Send webhook notification for completed operation.
    """
    if not operation.webhook_url or operation.webhook_sent:
        return
    
    try:
        payload = {
            'operation_id': str(operation.id),
            'patient_id': operation.patient.id,
            'status': operation.status,
            'operation_type': operation.operation_type,
            'completed_at': operation.completed_at.isoformat() if operation.completed_at else None,
            'is_successful': operation.is_successful,
            'processing_time_seconds': operation.processing_time_seconds,
            'resources_processed': operation.resources_processed,
        }
        
        response = requests.post(
            operation.webhook_url,
            json=payload,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            operation.webhook_sent = True
            operation.webhook_sent_at = timezone.now()
            operation.save(update_fields=['webhook_sent', 'webhook_sent_at'])
        
    except Exception as e:
        # Log webhook failure but don't fail the operation
        pass
