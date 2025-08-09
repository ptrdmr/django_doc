"""
Test suite for FHIR merge configuration system.
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User, Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse
import json

from .models import FHIRMergeConfiguration, FHIRMergeConfigurationAudit
from .configuration import MergeConfigurationService
from .services import FHIRMergeService
from apps.patients.models import Patient


class FHIRMergeConfigurationModelTests(TestCase):
    """Test cases for FHIRMergeConfiguration model."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_create_basic_configuration(self):
        """Test creating a basic configuration."""
        config = FHIRMergeConfiguration.objects.create(
            name='test_config',
            description='Test configuration',
            created_by=self.user
        )
        
        self.assertEqual(config.name, 'test_config')
        self.assertEqual(config.description, 'Test configuration')
        self.assertTrue(config.is_active)
        self.assertFalse(config.is_default)
        self.assertEqual(config.created_by, self.user)
    
    def test_unique_name_constraint(self):
        """Test that configuration names must be unique."""
        FHIRMergeConfiguration.objects.create(
            name='duplicate_name',
            created_by=self.user
        )
        
        with self.assertRaises(IntegrityError):
            FHIRMergeConfiguration.objects.create(
                name='duplicate_name',
                created_by=self.user
            )
    
    def test_default_configuration_constraint(self):
        """Test that only one configuration can be default."""
        config1 = FHIRMergeConfiguration.objects.create(
            name='config1',
            is_default=True,
            created_by=self.user
        )
        
        config2 = FHIRMergeConfiguration.objects.create(
            name='config2',
            is_default=True,
            created_by=self.user
        )
        
        # Refresh from database
        config1.refresh_from_db()
        config2.refresh_from_db()
        
        # Only config2 should be default now
        self.assertFalse(config1.is_default)
        self.assertTrue(config2.is_default)
    
    def test_threshold_validation(self):
        """Test validation of threshold values."""
        config = FHIRMergeConfiguration(
            name='invalid_config',
            near_duplicate_threshold=1.5,  # Invalid: > 1.0
            created_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            config.full_clean()
        
        config.near_duplicate_threshold = -0.1  # Invalid: < 0.0
        with self.assertRaises(ValidationError):
            config.full_clean()
    
    def test_time_validation(self):
        """Test validation of time-related fields."""
        config = FHIRMergeConfiguration(
            name='invalid_config',
            deduplication_tolerance_hours=-1,  # Invalid: negative
            created_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            config.full_clean()
        
        config.deduplication_tolerance_hours = 24
        config.max_processing_time_seconds = 0  # Invalid: zero
        with self.assertRaises(ValidationError):
            config.full_clean()
    
    def test_to_dict_method(self):
        """Test the to_dict method."""
        config = FHIRMergeConfiguration.objects.create(
            name='test_config',
            description='Test configuration',
            validate_fhir=True,
            resolve_conflicts=False,
            default_conflict_strategy='preserve_both',
            advanced_config={'test_key': 'test_value'},
            created_by=self.user
        )
        
        config_dict = config.to_dict()
        
        self.assertEqual(config_dict['profile_name'], 'test_config')
        self.assertTrue(config_dict['validate_fhir'])
        self.assertFalse(config_dict['resolve_conflicts'])
        self.assertEqual(config_dict['conflict_resolution_strategy'], 'preserve_both')
        self.assertEqual(config_dict['test_key'], 'test_value')  # From advanced_config
    
    def test_get_default_config(self):
        """Test getting the default configuration."""
        # No configurations exist
        default_config = FHIRMergeConfiguration.get_default_config()
        self.assertEqual(default_config.name, 'default')
        self.assertTrue(default_config.is_default)
        
        # Create a default configuration
        saved_config = FHIRMergeConfiguration.objects.create(
            name='saved_default',
            is_default=True,
            is_active=True,
            created_by=self.user
        )
        
        default_config = FHIRMergeConfiguration.get_default_config()
        self.assertEqual(default_config.id, saved_config.id)
    
    def test_get_config_by_name(self):
        """Test getting configuration by name."""
        config = FHIRMergeConfiguration.objects.create(
            name='named_config',
            is_active=True,
            created_by=self.user
        )
        
        retrieved_config = FHIRMergeConfiguration.get_config_by_name('named_config')
        self.assertEqual(retrieved_config.id, config.id)
        
        # Test with non-existent name - should return default
        default_config = FHIRMergeConfiguration.get_config_by_name('non_existent')
        self.assertEqual(default_config.name, 'default')


class MergeConfigurationServiceTests(TestCase):
    """Test cases for MergeConfigurationService."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_initialize_predefined_profiles(self):
        """Test initialization of predefined profiles."""
        MergeConfigurationService.initialize_predefined_profiles(self.user)
        
        # Check that all predefined profiles were created
        profiles = list(MergeConfigurationService.PREDEFINED_PROFILES.keys())
        for profile_name in profiles:
            config = FHIRMergeConfiguration.objects.get(name=profile_name)
            self.assertEqual(config.created_by, self.user)
            self.assertTrue(config.is_active)
        
        # Check that routine_update is set as default
        routine_config = FHIRMergeConfiguration.objects.get(name='routine_update')
        self.assertTrue(routine_config.is_default)
        
        # Test idempotency - running again shouldn't create duplicates
        initial_count = FHIRMergeConfiguration.objects.count()
        MergeConfigurationService.initialize_predefined_profiles(self.user)
        final_count = FHIRMergeConfiguration.objects.count()
        self.assertEqual(initial_count, final_count)
    
    def test_create_configuration(self):
        """Test creating a new configuration."""
        config = MergeConfigurationService.create_configuration(
            name='new_config',
            description='New test configuration',
            user=self.user,
            validate_fhir=False,
            resolve_conflicts=True
        )
        
        self.assertEqual(config.name, 'new_config')
        self.assertEqual(config.description, 'New test configuration')
        self.assertFalse(config.validate_fhir)
        self.assertTrue(config.resolve_conflicts)
        self.assertEqual(config.created_by, self.user)
        
        # Check audit entry was created
        audit_entry = FHIRMergeConfigurationAudit.objects.get(
            configuration=config,
            action='created'
        )
        self.assertEqual(audit_entry.performed_by, self.user)
    
    def test_create_configuration_with_base_profile(self):
        """Test creating configuration with base profile."""
        config = MergeConfigurationService.create_configuration(
            name='based_config',
            description='Configuration based on fast_import',
            base_profile='fast_import',
            user=self.user,
            validate_fhir=True  # Override the base profile setting
        )
        
        # Should inherit from fast_import but override validate_fhir
        self.assertEqual(config.name, 'based_config')
        self.assertTrue(config.validate_fhir)  # Overridden
        self.assertFalse(config.deduplicate_resources)  # From fast_import
        self.assertFalse(config.create_provenance)  # From fast_import
    
    def test_update_configuration(self):
        """Test updating an existing configuration."""
        config = FHIRMergeConfiguration.objects.create(
            name='update_test',
            validate_fhir=True,
            resolve_conflicts=False,
            created_by=self.user
        )
        
        updated_config = MergeConfigurationService.update_configuration(
            config,
            user=self.user,
            resolve_conflicts=True,
            default_conflict_strategy='preserve_both'
        )
        
        self.assertTrue(updated_config.resolve_conflicts)
        self.assertEqual(updated_config.default_conflict_strategy, 'preserve_both')
        
        # Check audit entry was created
        audit_entry = FHIRMergeConfigurationAudit.objects.get(
            configuration=config,
            action='updated'
        )
        self.assertEqual(audit_entry.performed_by, self.user)
        self.assertIn('resolve_conflicts', audit_entry.changes)
    
    def test_set_default_configuration(self):
        """Test setting a configuration as default."""
        config1 = FHIRMergeConfiguration.objects.create(
            name='config1',
            is_default=True,
            created_by=self.user
        )
        
        config2 = FHIRMergeConfiguration.objects.create(
            name='config2',
            is_default=False,
            created_by=self.user
        )
        
        MergeConfigurationService.set_default_configuration(config2, self.user)
        
        # Refresh from database
        config1.refresh_from_db()
        config2.refresh_from_db()
        
        self.assertFalse(config1.is_default)
        self.assertTrue(config2.is_default)
        self.assertTrue(config2.is_active)  # Should be activated
    
    def test_activate_deactivate_configuration(self):
        """Test activating and deactivating configurations."""
        config = FHIRMergeConfiguration.objects.create(
            name='toggle_test',
            is_active=False,
            created_by=self.user
        )
        
        # Test activation
        MergeConfigurationService.activate_configuration(config, self.user)
        config.refresh_from_db()
        self.assertTrue(config.is_active)
        
        # Test deactivation
        MergeConfigurationService.deactivate_configuration(config, self.user)
        config.refresh_from_db()
        self.assertFalse(config.is_active)
        
        # Test deactivating default configuration should raise error
        config.is_default = True
        config.is_active = True
        config.save()
        
        with self.assertRaises(ValidationError):
            MergeConfigurationService.deactivate_configuration(config, self.user)
    
    def test_list_configurations(self):
        """Test listing configurations."""
        # Create test configurations
        active_config = FHIRMergeConfiguration.objects.create(
            name='active_config',
            is_active=True,
            created_by=self.user
        )
        
        inactive_config = FHIRMergeConfiguration.objects.create(
            name='inactive_config',
            is_active=False,
            created_by=self.user
        )
        
        # Test active only
        active_configs = MergeConfigurationService.list_configurations(active_only=True)
        config_names = [config.name for config in active_configs]
        self.assertIn('active_config', config_names)
        self.assertNotIn('inactive_config', config_names)
        
        # Test all configurations
        all_configs = MergeConfigurationService.list_configurations(active_only=False)
        config_names = [config.name for config in all_configs]
        self.assertIn('active_config', config_names)
        self.assertIn('inactive_config', config_names)
    
    def test_validate_configuration_data(self):
        """Test configuration data validation."""
        # Valid data
        valid_data = {
            'name': 'valid_config',
            'near_duplicate_threshold': 0.85,
            'fuzzy_duplicate_threshold': 0.7,
            'deduplication_tolerance_hours': 24,
            'max_processing_time_seconds': 300,
            'default_conflict_strategy': 'newest_wins'
        }
        
        errors = MergeConfigurationService.validate_configuration_data(valid_data)
        self.assertEqual(len(errors), 0)
        
        # Invalid data
        invalid_data = {
            'name': '',  # Missing name
            'near_duplicate_threshold': 1.5,  # Invalid threshold
            'deduplication_tolerance_hours': -1,  # Invalid time
            'max_processing_time_seconds': 0,  # Invalid time
            'default_conflict_strategy': 'invalid_strategy'  # Invalid strategy
        }
        
        errors = MergeConfigurationService.validate_configuration_data(invalid_data)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any('Name is required' in error for error in errors))
        self.assertTrue(any('threshold' in error for error in errors))


class FHIRMergeServiceConfigurationTests(TestCase):
    """Test cases for FHIRMergeService configuration integration."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-01-01',
            gender='M',
            mrn='TEST001'
        )
        
        # Initialize predefined profiles
        MergeConfigurationService.initialize_predefined_profiles(self.user)
    
    def test_merge_service_initialization_with_default_config(self):
        """Test merge service initialization with default configuration."""
        merge_service = FHIRMergeService(self.patient)
        
        # Should use the default routine_update configuration
        self.assertEqual(merge_service.get_current_configuration_profile(), 'routine_update')
        self.assertTrue(merge_service.config['validate_fhir'])
        self.assertTrue(merge_service.config['resolve_conflicts'])
    
    def test_merge_service_initialization_with_specific_config(self):
        """Test merge service initialization with specific configuration."""
        merge_service = FHIRMergeService(self.patient, config_profile='fast_import')
        
        self.assertEqual(merge_service.get_current_configuration_profile(), 'fast_import')
        self.assertFalse(merge_service.config['validate_fhir'])
        self.assertFalse(merge_service.config['deduplicate_resources'])
    
    def test_set_configuration_profile(self):
        """Test switching configuration profiles."""
        merge_service = FHIRMergeService(self.patient, config_profile='routine_update')
        
        # Switch to reconciliation profile
        merge_service.set_configuration_profile('reconciliation')
        
        self.assertEqual(merge_service.get_current_configuration_profile(), 'reconciliation')
        self.assertEqual(merge_service.config['default_conflict_strategy'], 'manual_review')
        self.assertEqual(merge_service.config['deduplication_tolerance_hours'], 12)
    
    def test_configure_merge_settings_override(self):
        """Test overriding configuration settings."""
        merge_service = FHIRMergeService(self.patient, config_profile='routine_update')
        
        # Override specific settings
        merge_service.configure_merge_settings(
            validate_fhir=False,
            deduplicate_resources=False
        )
        
        self.assertFalse(merge_service.config['validate_fhir'])
        self.assertFalse(merge_service.config['deduplicate_resources'])
        # Other settings should remain unchanged
        self.assertTrue(merge_service.config['resolve_conflicts'])


class ConfigurationAPITests(TestCase):
    """Test cases for configuration API views."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Add permissions
        permissions = Permission.objects.filter(
            content_type__app_label='fhir',
            content_type__model='fhirmergeconfiguration'
        )
        self.user.user_permissions.set(permissions)
        
        self.client.login(username='testuser', password='testpass123')
        
        # Create test configuration
        self.test_config = FHIRMergeConfiguration.objects.create(
            name='api_test_config',
            description='Configuration for API testing',
            validate_fhir=True,
            resolve_conflicts=False,
            created_by=self.user
        )
    
    def test_list_configurations_api(self):
        """Test the list configurations API endpoint."""
        response = self.client.get('/fhir/api/configurations/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(data['status'], 'success')
        self.assertGreater(data['count'], 0)
        
        # Check that our test config is in the response
        config_names = [config['name'] for config in data['data']]
        self.assertIn('api_test_config', config_names)
    
    def test_get_configuration_api(self):
        """Test the get configuration API endpoint."""
        response = self.client.get(f'/fhir/api/configurations/{self.test_config.id}/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['data']['name'], 'api_test_config')
        self.assertEqual(data['data']['description'], 'Configuration for API testing')
        self.assertTrue(data['data']['validate_fhir'])
        self.assertFalse(data['data']['resolve_conflicts'])
    
    def test_get_default_configuration_api(self):
        """Test getting the default configuration via API."""
        response = self.client.get('/fhir/api/configurations/default/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(data['status'], 'success')
        # Should have some configuration data
        self.assertIn('name', data['data'])
    
    def test_create_configuration_api(self):
        """Test creating a configuration via API."""
        config_data = {
            'name': 'api_created_config',
            'description': 'Created via API',
            'validate_fhir': False,
            'resolve_conflicts': True,
            'default_conflict_strategy': 'preserve_both'
        }
        
        response = self.client.post(
            '/fhir/api/configurations/create/',
            data=json.dumps(config_data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 201)
        data = response.json()
        
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['data']['name'], 'api_created_config')
        
        # Verify the configuration was actually created
        created_config = FHIRMergeConfiguration.objects.get(name='api_created_config')
        self.assertEqual(created_config.description, 'Created via API')
        self.assertFalse(created_config.validate_fhir)
        self.assertTrue(created_config.resolve_conflicts)
    
    def test_update_configuration_api(self):
        """Test updating a configuration via API."""
        update_data = {
            'description': 'Updated description',
            'validate_fhir': False,
            'max_processing_time_seconds': 600
        }
        
        response = self.client.put(
            f'/fhir/api/configurations/{self.test_config.id}/update/',
            data=json.dumps(update_data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(data['status'], 'success')
        
        # Verify the configuration was updated
        self.test_config.refresh_from_db()
        self.assertEqual(self.test_config.description, 'Updated description')
        self.assertFalse(self.test_config.validate_fhir)
        self.assertEqual(self.test_config.max_processing_time_seconds, 600)
    
    def test_set_default_configuration_api(self):
        """Test setting a configuration as default via API."""
        response = self.client.post(f'/fhir/api/configurations/{self.test_config.id}/set-default/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(data['status'], 'success')
        
        # Verify the configuration is now default
        self.test_config.refresh_from_db()
        self.assertTrue(self.test_config.is_default)
    
    def test_activate_deactivate_configuration_api(self):
        """Test activating and deactivating configurations via API."""
        # First deactivate
        self.test_config.is_active = False
        self.test_config.save()
        
        # Test activation
        response = self.client.post(f'/fhir/api/configurations/{self.test_config.id}/activate/')
        self.assertEqual(response.status_code, 200)
        
        self.test_config.refresh_from_db()
        self.assertTrue(self.test_config.is_active)
        
        # Test deactivation
        response = self.client.post(f'/fhir/api/configurations/{self.test_config.id}/deactivate/')
        self.assertEqual(response.status_code, 200)
        
        self.test_config.refresh_from_db()
        self.assertFalse(self.test_config.is_active)
    
    def test_api_authentication_required(self):
        """Test that API endpoints require authentication."""
        # Logout
        self.client.logout()
        
        response = self.client.get('/fhir/api/configurations/')
        # Should redirect to login or return 401/403
        self.assertIn(response.status_code, [302, 401, 403])
    
    def test_api_validation_errors(self):
        """Test API validation error handling."""
        # Try to create configuration with invalid data
        invalid_data = {
            'name': '',  # Missing name
            'near_duplicate_threshold': 1.5  # Invalid threshold
        }
        
        response = self.client.post(
            '/fhir/api/configurations/create/',
            data=json.dumps(invalid_data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        
        self.assertEqual(data['status'], 'error')
        self.assertIn('errors', data)


class ConfigurationAuditTests(TestCase):
    """Test cases for configuration audit functionality."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_audit_trail_creation(self):
        """Test that audit entries are created for configuration changes."""
        # Create configuration
        config = MergeConfigurationService.create_configuration(
            name='audit_test',
            description='Test audit trail',
            user=self.user
        )
        
        # Check creation audit entry
        create_audit = FHIRMergeConfigurationAudit.objects.get(
            configuration=config,
            action='created'
        )
        self.assertEqual(create_audit.performed_by, self.user)
        
        # Update configuration
        MergeConfigurationService.update_configuration(
            config,
            user=self.user,
            description='Updated description'
        )
        
        # Check update audit entry
        update_audit = FHIRMergeConfigurationAudit.objects.get(
            configuration=config,
            action='updated'
        )
        self.assertEqual(update_audit.performed_by, self.user)
        self.assertIn('description', update_audit.changes)
    
    def test_audit_entry_structure(self):
        """Test the structure of audit entries."""
        config = MergeConfigurationService.create_configuration(
            name='audit_structure_test',
            user=self.user,
            validate_fhir=True,
            resolve_conflicts=False
        )
        
        # Update to create audit entry with changes
        MergeConfigurationService.update_configuration(
            config,
            user=self.user,
            resolve_conflicts=True,
            default_conflict_strategy='preserve_both'
        )
        
        audit_entry = FHIRMergeConfigurationAudit.objects.get(
            configuration=config,
            action='updated'
        )
        
        # Check changes structure
        changes = audit_entry.changes
        self.assertIn('resolve_conflicts', changes)
        self.assertIn('default_conflict_strategy', changes)
        
        resolve_conflict_change = changes['resolve_conflicts']
        self.assertEqual(resolve_conflict_change['old'], False)
        self.assertEqual(resolve_conflict_change['new'], True)
