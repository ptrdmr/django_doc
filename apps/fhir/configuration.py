"""
FHIR Merge Configuration Service

This module provides services for managing FHIR merge configuration profiles,
including predefined profiles for common scenarios and dynamic configuration
management.
"""

import logging
from typing import Dict, Any, Optional, List
from django.db import transaction
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import FHIRMergeConfiguration, FHIRMergeConfigurationAudit

logger = logging.getLogger(__name__)


class MergeConfigurationService:
    """
    Service for managing FHIR merge configuration profiles.
    
    Provides methods for creating, updating, and retrieving configuration
    profiles for different merge scenarios.
    """
    
    # Predefined configuration profiles
    PREDEFINED_PROFILES = {
        'initial_import': {
            'name': 'initial_import',
            'description': 'Configuration for initial import of patient data - less strict validation, more permissive merging',
            'validate_fhir': True,
            'resolve_conflicts': True,
            'deduplicate_resources': True,
            'create_provenance': True,
            'default_conflict_strategy': 'preserve_both',
            'deduplication_tolerance_hours': 48,  # More permissive for initial import
            'near_duplicate_threshold': 0.85,    # Lower threshold for initial import
            'fuzzy_duplicate_threshold': 0.65,   # Lower threshold for initial import
            'max_processing_time_seconds': 600,  # 10 minutes for complex initial imports
            'advanced_config': {
                'conflict_type_strategies': {
                    'dosage_conflict': 'preserve_both',
                    'temporal_conflict': 'preserve_both',
                    'value_mismatch': 'preserve_both'
                },
                'resource_type_strategies': {
                    'MedicationStatement': 'preserve_both',
                    'Observation': 'preserve_both',
                    'Condition': 'preserve_both'
                },
                'severity_strategies': {
                    'low': 'newest_wins',
                    'medium': 'preserve_both',
                    'high': 'manual_review'
                },
                'validation_strictness': 'lenient',
                'allow_incomplete_resources': True,
                'auto_correct_minor_errors': True
            }
        },
        'routine_update': {
            'name': 'routine_update',
            'description': 'Configuration for routine updates - balanced validation and conflict resolution',
            'validate_fhir': True,
            'resolve_conflicts': True,
            'deduplicate_resources': True,
            'create_provenance': True,
            'default_conflict_strategy': 'newest_wins',
            'deduplication_tolerance_hours': 24,
            'near_duplicate_threshold': 0.9,
            'fuzzy_duplicate_threshold': 0.7,
            'max_processing_time_seconds': 300,  # 5 minutes
            'advanced_config': {
                'conflict_type_strategies': {
                    'dosage_conflict': 'manual_review',
                    'temporal_conflict': 'newest_wins',
                    'value_mismatch': 'newest_wins'
                },
                'resource_type_strategies': {
                    'MedicationStatement': 'manual_review',
                    'Observation': 'newest_wins',
                    'Condition': 'newest_wins'
                },
                'severity_strategies': {
                    'low': 'newest_wins',
                    'medium': 'newest_wins',
                    'high': 'manual_review'
                },
                'validation_strictness': 'standard',
                'allow_incomplete_resources': False,
                'auto_correct_minor_errors': True,
                'enable_smart_deduplication': True
            }
        },
        'reconciliation': {
            'name': 'reconciliation',
            'description': 'Configuration for data reconciliation - strict validation, conservative merging',
            'validate_fhir': True,
            'resolve_conflicts': True,
            'deduplicate_resources': True,
            'create_provenance': True,
            'default_conflict_strategy': 'manual_review',
            'deduplication_tolerance_hours': 12,  # Stricter for reconciliation
            'near_duplicate_threshold': 0.95,    # Higher threshold for reconciliation
            'fuzzy_duplicate_threshold': 0.8,    # Higher threshold for reconciliation
            'max_processing_time_seconds': 900,  # 15 minutes for careful reconciliation
            'advanced_config': {
                'conflict_type_strategies': {
                    'dosage_conflict': 'manual_review',
                    'temporal_conflict': 'manual_review',
                    'value_mismatch': 'manual_review'
                },
                'resource_type_strategies': {
                    'MedicationStatement': 'manual_review',
                    'Observation': 'manual_review',
                    'Condition': 'manual_review'
                },
                'severity_strategies': {
                    'low': 'manual_review',
                    'medium': 'manual_review',
                    'high': 'manual_review'
                },
                'validation_strictness': 'strict',
                'allow_incomplete_resources': False,
                'auto_correct_minor_errors': False,
                'require_manual_approval': True,
                'enable_detailed_audit': True
            }
        },
        'fast_import': {
            'name': 'fast_import',
            'description': 'Configuration for fast import - minimal validation, performance optimized',
            'validate_fhir': False,  # Skip FHIR validation for speed
            'resolve_conflicts': True,
            'deduplicate_resources': False,  # Skip deduplication for speed
            'create_provenance': False,  # Skip provenance for speed
            'default_conflict_strategy': 'newest_wins',
            'deduplication_tolerance_hours': 24,
            'near_duplicate_threshold': 0.9,
            'fuzzy_duplicate_threshold': 0.7,
            'max_processing_time_seconds': 60,  # 1 minute max
            'advanced_config': {
                'conflict_type_strategies': {
                    'dosage_conflict': 'newest_wins',
                    'temporal_conflict': 'newest_wins',
                    'value_mismatch': 'newest_wins'
                },
                'resource_type_strategies': {
                    'MedicationStatement': 'newest_wins',
                    'Observation': 'newest_wins',
                    'Condition': 'newest_wins'
                },
                'severity_strategies': {
                    'low': 'newest_wins',
                    'medium': 'newest_wins',
                    'high': 'newest_wins'
                },
                'validation_strictness': 'none',
                'allow_incomplete_resources': True,
                'auto_correct_minor_errors': False,
                'skip_referential_integrity': True,
                'batch_processing': True
            }
        }
    }
    
    @classmethod
    def initialize_predefined_profiles(cls, user: Optional[User] = None) -> None:
        """
        Initialize predefined configuration profiles in the database.
        
        Args:
            user: User to associate with profile creation
        """
        logger.info("Initializing predefined FHIR merge configuration profiles")
        
        for profile_key, profile_data in cls.PREDEFINED_PROFILES.items():
            try:
                # Check if profile already exists
                existing_profile = FHIRMergeConfiguration.objects.filter(
                    name=profile_data['name']
                ).first()
                
                if existing_profile:
                    logger.info(f"Profile '{profile_data['name']}' already exists, skipping")
                    continue
                
                # Create new profile
                profile = FHIRMergeConfiguration(
                    name=profile_data['name'],
                    description=profile_data['description'],
                    validate_fhir=profile_data['validate_fhir'],
                    resolve_conflicts=profile_data['resolve_conflicts'],
                    deduplicate_resources=profile_data['deduplicate_resources'],
                    create_provenance=profile_data['create_provenance'],
                    default_conflict_strategy=profile_data['default_conflict_strategy'],
                    deduplication_tolerance_hours=profile_data['deduplication_tolerance_hours'],
                    near_duplicate_threshold=profile_data['near_duplicate_threshold'],
                    fuzzy_duplicate_threshold=profile_data['fuzzy_duplicate_threshold'],
                    max_processing_time_seconds=profile_data['max_processing_time_seconds'],
                    advanced_config=profile_data['advanced_config'],
                    created_by=user
                )
                
                # Set the routine_update as default if no default exists
                if profile_key == 'routine_update':
                    existing_default = FHIRMergeConfiguration.objects.filter(is_default=True).exists()
                    if not existing_default:
                        profile.is_default = True
                
                profile.save()
                
                # Create audit entry
                cls._create_audit_entry(profile, 'created', {}, user)
                
                logger.info(f"Created predefined profile: {profile_data['name']}")
                
            except Exception as e:
                logger.error(f"Failed to create profile '{profile_data['name']}': {e}")
    
    @classmethod
    def get_configuration(cls, name: Optional[str] = None) -> FHIRMergeConfiguration:
        """
        Get a configuration profile by name or return the default.
        
        Args:
            name: Name of the configuration profile to retrieve
            
        Returns:
            FHIRMergeConfiguration instance
        """
        if name:
            return FHIRMergeConfiguration.get_config_by_name(name)
        else:
            return FHIRMergeConfiguration.get_default_config()
    
    @classmethod
    def create_configuration(
        cls,
        name: str,
        description: str = "",
        base_profile: Optional[str] = None,
        user: Optional[User] = None,
        **kwargs
    ) -> FHIRMergeConfiguration:
        """
        Create a new configuration profile.
        
        Args:
            name: Unique name for the configuration
            description: Description of the configuration
            base_profile: Name of predefined profile to use as base
            user: User creating the configuration
            **kwargs: Additional configuration parameters
            
        Returns:
            Created FHIRMergeConfiguration instance
        """
        with transaction.atomic():
            # Start with default values
            config_data = {
                'name': name,
                'description': description,
                'created_by': user
            }
            
            # If base profile specified, use it as starting point
            if base_profile and base_profile in cls.PREDEFINED_PROFILES:
                base_data = cls.PREDEFINED_PROFILES[base_profile].copy()
                # Remove name and description from base data
                base_data.pop('name', None)
                base_data.pop('description', None)
                config_data.update(base_data)
            
            # Override with any provided kwargs
            config_data.update(kwargs)
            
            # Create the configuration
            configuration = FHIRMergeConfiguration(**config_data)
            configuration.save()
            
            # Create audit entry
            cls._create_audit_entry(configuration, 'created', config_data, user)
            
            logger.info(f"Created new configuration profile: {name}")
            return configuration
    
    @classmethod
    def update_configuration(
        cls,
        configuration: FHIRMergeConfiguration,
        user: Optional[User] = None,
        **kwargs
    ) -> FHIRMergeConfiguration:
        """
        Update an existing configuration profile.
        
        Args:
            configuration: Configuration to update
            user: User performing the update
            **kwargs: Fields to update
            
        Returns:
            Updated FHIRMergeConfiguration instance
        """
        with transaction.atomic():
            # Track changes for audit
            changes = {}
            
            for field, value in kwargs.items():
                if hasattr(configuration, field):
                    old_value = getattr(configuration, field)
                    if old_value != value:
                        changes[field] = {'old': old_value, 'new': value}
                        setattr(configuration, field, value)
            
            if changes:
                configuration.save()
                cls._create_audit_entry(configuration, 'updated', changes, user)
                logger.info(f"Updated configuration profile: {configuration.name}")
            
            return configuration
    
    @classmethod
    def activate_configuration(
        cls,
        configuration: FHIRMergeConfiguration,
        user: Optional[User] = None
    ) -> None:
        """
        Activate a configuration profile.
        
        Args:
            configuration: Configuration to activate
            user: User performing the activation
        """
        if not configuration.is_active:
            configuration.is_active = True
            configuration.save()
            cls._create_audit_entry(configuration, 'activated', {}, user)
            logger.info(f"Activated configuration profile: {configuration.name}")
    
    @classmethod
    def deactivate_configuration(
        cls,
        configuration: FHIRMergeConfiguration,
        user: Optional[User] = None
    ) -> None:
        """
        Deactivate a configuration profile.
        
        Args:
            configuration: Configuration to deactivate
            user: User performing the deactivation
        """
        if configuration.is_active:
            # Don't allow deactivating the default configuration
            if configuration.is_default:
                raise ValidationError("Cannot deactivate the default configuration")
            
            configuration.is_active = False
            configuration.save()
            cls._create_audit_entry(configuration, 'deactivated', {}, user)
            logger.info(f"Deactivated configuration profile: {configuration.name}")
    
    @classmethod
    def set_default_configuration(
        cls,
        configuration: FHIRMergeConfiguration,
        user: Optional[User] = None
    ) -> None:
        """
        Set a configuration as the default.
        
        Args:
            configuration: Configuration to set as default
            user: User performing the change
        """
        with transaction.atomic():
            # Remove default from other configurations
            FHIRMergeConfiguration.objects.filter(is_default=True).update(is_default=False)
            
            # Set as default and ensure it's active
            configuration.is_default = True
            configuration.is_active = True
            configuration.save()
            
            cls._create_audit_entry(configuration, 'updated', {'is_default': {'old': False, 'new': True}}, user)
            logger.info(f"Set default configuration profile: {configuration.name}")
    
    @classmethod
    def get_configuration_dict(cls, name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get configuration as dictionary for use in merge service.
        
        Args:
            name: Name of configuration profile
            
        Returns:
            Configuration dictionary
        """
        config = cls.get_configuration(name)
        return config.to_dict()
    
    @classmethod
    def list_configurations(cls, active_only: bool = True) -> List[FHIRMergeConfiguration]:
        """
        List available configuration profiles.
        
        Args:
            active_only: Whether to return only active configurations
            
        Returns:
            List of FHIRMergeConfiguration instances
        """
        queryset = FHIRMergeConfiguration.objects.all()
        if active_only:
            queryset = queryset.filter(is_active=True)
        return list(queryset.order_by('-is_default', 'name'))
    
    @classmethod
    def validate_configuration_data(cls, data: Dict[str, Any]) -> List[str]:
        """
        Validate configuration data without creating a model instance.
        
        Args:
            data: Configuration data to validate
            
        Returns:
            List of validation error messages
        """
        errors = []
        
        # Validate required fields
        if not data.get('name'):
            errors.append("Name is required")
        
        # Validate threshold values
        near_threshold = data.get('near_duplicate_threshold')
        if near_threshold is not None and not (0.0 <= near_threshold <= 1.0):
            errors.append("Near duplicate threshold must be between 0.0 and 1.0")
        
        fuzzy_threshold = data.get('fuzzy_duplicate_threshold')
        if fuzzy_threshold is not None and not (0.0 <= fuzzy_threshold <= 1.0):
            errors.append("Fuzzy duplicate threshold must be between 0.0 and 1.0")
        
        # Validate time values
        tolerance_hours = data.get('deduplication_tolerance_hours')
        if tolerance_hours is not None and tolerance_hours < 0:
            errors.append("Deduplication tolerance hours must be non-negative")
        
        processing_time = data.get('max_processing_time_seconds')
        if processing_time is not None and processing_time <= 0:
            errors.append("Max processing time must be positive")
        
        # Validate conflict strategy
        strategy = data.get('default_conflict_strategy')
        if strategy and strategy not in [choice[0] for choice in FHIRMergeConfiguration.CONFLICT_STRATEGIES]:
            errors.append(f"Invalid conflict strategy: {strategy}")
        
        return errors
    
    @classmethod
    def _create_audit_entry(
        cls,
        configuration: FHIRMergeConfiguration,
        action: str,
        changes: Dict[str, Any],
        user: Optional[User] = None
    ) -> None:
        """
        Create an audit entry for configuration changes.
        
        Args:
            configuration: Configuration that was changed
            action: Type of action performed
            changes: Dictionary of changes made
            user: User who performed the action
        """
        try:
            FHIRMergeConfigurationAudit.objects.create(
                configuration=configuration,
                action=action,
                changes=changes,
                performed_by=user
            )
        except Exception as e:
            logger.error(f"Failed to create audit entry: {e}")
