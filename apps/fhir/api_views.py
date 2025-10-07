"""
API views for FHIR merge configuration management.
"""

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import transaction
import json

from .models import FHIRMergeConfiguration, FHIRMergeConfigurationAudit
from .configuration import MergeConfigurationService


@login_required
@require_http_methods(["GET"])
def list_configurations(request):
    """
    API endpoint to list FHIR merge configuration profiles.
    
    Query parameters:
    - active_only: boolean (default: true) - only return active configurations
    """
    active_only = request.GET.get('active_only', 'true').lower() == 'true'
    
    try:
        configurations = MergeConfigurationService.list_configurations(active_only=active_only)
        
        config_data = []
        for config in configurations:
            config_data.append({
                'id': config.id,
                'name': config.name,
                'description': config.description,
                'is_default': config.is_default,
                'is_active': config.is_active,
                'default_conflict_strategy': config.default_conflict_strategy,
                'deduplication_tolerance_hours': config.deduplication_tolerance_hours,
                'near_duplicate_threshold': config.near_duplicate_threshold,
                'fuzzy_duplicate_threshold': config.fuzzy_duplicate_threshold,
                'max_processing_time_seconds': config.max_processing_time_seconds,
                'created_at': config.created_at.isoformat(),
                'updated_at': config.updated_at.isoformat()
            })
        
        return JsonResponse({
            'status': 'success',
            'data': config_data,
            'count': len(config_data)
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_configuration(request, config_id=None):
    """
    API endpoint to get a specific configuration or the default.
    
    URL parameters:
    - config_id: integer (optional) - ID of configuration to retrieve
    
    Query parameters:
    - name: string (optional) - name of configuration to retrieve
    - include_advanced: boolean (default: false) - include advanced config
    """
    name = request.GET.get('name')
    include_advanced = request.GET.get('include_advanced', 'false').lower() == 'true'
    
    try:
        if config_id:
            config = get_object_or_404(FHIRMergeConfiguration, id=config_id, is_active=True)
        elif name:
            config = MergeConfigurationService.get_configuration(name)
        else:
            config = MergeConfigurationService.get_configuration()
        
        # Build response data
        data = {
            'id': config.id,
            'name': config.name,
            'description': config.description,
            'is_default': config.is_default,
            'is_active': config.is_active,
            'validate_fhir': config.validate_fhir,
            'resolve_conflicts': config.resolve_conflicts,
            'deduplicate_resources': config.deduplicate_resources,
            'create_provenance': config.create_provenance,
            'default_conflict_strategy': config.default_conflict_strategy,
            'deduplication_tolerance_hours': config.deduplication_tolerance_hours,
            'near_duplicate_threshold': config.near_duplicate_threshold,
            'fuzzy_duplicate_threshold': config.fuzzy_duplicate_threshold,
            'max_processing_time_seconds': config.max_processing_time_seconds,
            'created_at': config.created_at.isoformat(),
            'updated_at': config.updated_at.isoformat()
        }
        
        if include_advanced:
            data['advanced_config'] = config.advanced_config
        
        return JsonResponse({
            'status': 'success',
            'data': data
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=404 if 'not found' in str(e).lower() else 500)


@login_required
@permission_required('fhir.add_fhirmergeconfiguration', raise_exception=True)
@csrf_exempt
@require_http_methods(["POST"])
def create_configuration(request):
    """
    API endpoint to create a new FHIR merge configuration.
    
    POST body (JSON):
    {
        "name": "string (required)",
        "description": "string (optional)",
        "base_profile": "string (optional)",
        "validate_fhir": "boolean (optional)",
        "resolve_conflicts": "boolean (optional)",
        ... other configuration options
    }
    """
    try:
        data = json.loads(request.body)
        
        # Validate required fields
        if not data.get('name'):
            return JsonResponse({
                'status': 'error',
                'message': 'Name is required'
            }, status=400)
        
        # Validate configuration data
        validation_errors = MergeConfigurationService.validate_configuration_data(data)
        if validation_errors:
            return JsonResponse({
                'status': 'error',
                'message': 'Validation failed',
                'errors': validation_errors
            }, status=400)
        
        # Create configuration
        with transaction.atomic():
            config = MergeConfigurationService.create_configuration(
                name=data['name'],
                description=data.get('description', ''),
                base_profile=data.get('base_profile'),
                user=request.user,
                **{k: v for k, v in data.items() if k not in ['name', 'description', 'base_profile']}
            )
        
        return JsonResponse({
            'status': 'success',
            'message': f"Configuration '{config.name}' created successfully",
            'data': {
                'id': config.id,
                'name': config.name,
                'is_default': config.is_default,
                'is_active': config.is_active
            }
        }, status=201)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid JSON in request body'
        }, status=400)
    except ValidationError as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@permission_required('fhir.change_fhirmergeconfiguration', raise_exception=True)
@csrf_exempt
@require_http_methods(["PUT", "PATCH"])
def update_configuration(request, config_id):
    """
    API endpoint to update an existing FHIR merge configuration.
    """
    try:
        config = get_object_or_404(FHIRMergeConfiguration, id=config_id)
        data = json.loads(request.body)
        
        # Validate configuration data
        validation_errors = MergeConfigurationService.validate_configuration_data(data)
        if validation_errors:
            return JsonResponse({
                'status': 'error',
                'message': 'Validation failed',
                'errors': validation_errors
            }, status=400)
        
        # Update configuration
        with transaction.atomic():
            updated_config = MergeConfigurationService.update_configuration(
                config,
                user=request.user,
                **data
            )
        
        return JsonResponse({
            'status': 'success',
            'message': f"Configuration '{updated_config.name}' updated successfully",
            'data': {
                'id': updated_config.id,
                'name': updated_config.name,
                'is_default': updated_config.is_default,
                'is_active': updated_config.is_active,
                'updated_at': updated_config.updated_at.isoformat()
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid JSON in request body'
        }, status=400)
    except ValidationError as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@permission_required('fhir.change_fhirmergeconfiguration', raise_exception=True)
@csrf_exempt
@require_http_methods(["POST"])
def set_default_configuration(request, config_id):
    """
    API endpoint to set a configuration as the default.
    """
    try:
        config = get_object_or_404(FHIRMergeConfiguration, id=config_id)
        
        with transaction.atomic():
            MergeConfigurationService.set_default_configuration(config, request.user)
        
        return JsonResponse({
            'status': 'success',
            'message': f"Configuration '{config.name}' is now the default"
        })
        
    except ValidationError as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@permission_required('fhir.change_fhirmergeconfiguration', raise_exception=True)
@csrf_exempt
@require_http_methods(["POST"])
def activate_configuration(request, config_id):
    """
    API endpoint to activate a configuration.
    """
    try:
        config = get_object_or_404(FHIRMergeConfiguration, id=config_id)
        MergeConfigurationService.activate_configuration(config, request.user)
        
        return JsonResponse({
            'status': 'success',
            'message': f"Configuration '{config.name}' activated"
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@permission_required('fhir.change_fhirmergeconfiguration', raise_exception=True)
@csrf_exempt
@require_http_methods(["POST"])
def deactivate_configuration(request, config_id):
    """
    API endpoint to deactivate a configuration.
    """
    try:
        config = get_object_or_404(FHIRMergeConfiguration, id=config_id)
        MergeConfigurationService.deactivate_configuration(config, request.user)
        
        return JsonResponse({
            'status': 'success',
            'message': f"Configuration '{config.name}' deactivated"
        })
        
    except ValidationError as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)
