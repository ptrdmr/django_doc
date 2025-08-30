"""
Management command to set up permissions for healthcare roles.
Implements hybrid permission system with Django built-in + custom medical permissions.
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import Permission, ContentType
from django.contrib.contenttypes.models import ContentType as DjangoContentType
from django.db import transaction
from apps.accounts.models import Role
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Set up permissions for healthcare roles (Admin, Provider, Staff, Auditor)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--role',
            type=str,
            help='Specific role to update (admin, provider, staff, auditor). If not specified, updates all roles.'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )

    def handle(self, *args, **options):
        """Set up permissions for all healthcare roles."""
        self.dry_run = options.get('dry_run', False)
        specific_role = options.get('role')
        
        if self.dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        self.stdout.write('Setting up healthcare role permissions...')
        
        # Define role permission mappings
        role_permissions = self.get_role_permission_mappings()
        
        if specific_role:
            if specific_role not in role_permissions:
                raise CommandError(f"Unknown role: {specific_role}. Available roles: {list(role_permissions.keys())}")
            roles_to_process = {specific_role: role_permissions[specific_role]}
        else:
            roles_to_process = role_permissions
        
        total_assigned = 0
        
        with transaction.atomic():
            for role_name, permissions in roles_to_process.items():
                assigned = self.setup_role_permissions(role_name, permissions)
                total_assigned += assigned
        
        if self.dry_run:
            self.stdout.write(self.style.SUCCESS(f'DRY RUN: Would assign {total_assigned} permissions'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Successfully assigned {total_assigned} permissions to healthcare roles'))

    def get_role_permission_mappings(self):
        """
        Define permission mappings for each healthcare role.
        
        Returns comprehensive permission sets based on healthcare workflow needs.
        """
        return {
            'admin': {
                'description': 'Full system access - can manage all aspects of the medical document parser',
                'permissions': [
                    # User and role management
                    'accounts.add_role', 'accounts.change_role', 'accounts.delete_role', 'accounts.view_role',
                    'accounts.add_userprofile', 'accounts.change_userprofile', 'accounts.delete_userprofile', 'accounts.view_userprofile',
                    
                    # Patient management (full access including PHI)
                    'patients.add_patient', 'patients.change_patient', 'patients.delete_patient', 'patients.view_patient',
                    'patients.add_patienthistory', 'patients.change_patienthistory', 'patients.view_patienthistory',
                    
                    # Provider management
                    'providers.add_provider', 'providers.change_provider', 'providers.delete_provider', 'providers.view_provider',
                    'providers.add_providerhistory', 'providers.change_providerhistory', 'providers.view_providerhistory',
                    
                    # Document processing (full access)
                    'documents.add_document', 'documents.change_document', 'documents.delete_document', 'documents.view_document',
                    'documents.add_parseddata', 'documents.change_parseddata', 'documents.delete_parseddata', 'documents.view_parseddata',
                    
                    # FHIR operations (full access)
                    'fhir.add_fhirmergeoperation', 'fhir.change_fhirmergeoperation', 'fhir.delete_fhirmergeoperation', 'fhir.view_fhirmergeoperation',
                    'fhir.add_fhirmergeconfiguration', 'fhir.change_fhirmergeconfiguration', 'fhir.delete_fhirmergeconfiguration', 'fhir.view_fhirmergeconfiguration',
                    
                    # Audit and security (full access)
                    'core.add_auditlog', 'core.change_auditlog', 'core.view_auditlog',
                    'core.add_securityevent', 'core.change_securityevent', 'core.view_securityevent',
                    'core.add_apiusagelog', 'core.change_apiusagelog', 'core.view_apiusagelog',
                    'core.add_compliancereport', 'core.change_compliancereport', 'core.view_compliancereport',
                ]
            },
            
            'provider': {
                'description': 'Healthcare provider access - can view/edit patients and process documents',
                'permissions': [
                    # Patient access (view and edit, including PHI for medical purposes)
                    'patients.view_patient', 'patients.change_patient',
                    'patients.view_patienthistory',
                    
                    # Provider management (can update own profile)
                    'providers.view_provider', 'providers.change_provider',
                    'providers.view_providerhistory',
                    
                    # Document processing (can upload and process documents)
                    'documents.add_document', 'documents.view_document', 'documents.change_document',
                    'documents.add_parseddata', 'documents.view_parseddata', 'documents.change_parseddata',
                    
                    # FHIR operations (can trigger merges and view results)
                    'fhir.add_fhirmergeoperation', 'fhir.view_fhirmergeoperation',
                    'fhir.view_fhirmergeconfiguration',
                    
                    # Limited audit access (can view logs related to their actions)
                    'core.view_auditlog',
                    'core.view_apiusagelog',
                ]
            },
            
            'staff': {
                'description': 'Administrative staff access - limited patient info, no sensitive PHI',
                'permissions': [
                    # Limited patient access (view only, no PHI editing)
                    'patients.view_patient',
                    
                    # Provider directory access
                    'providers.view_provider',
                    
                    # Document management (can upload but not process)
                    'documents.add_document', 'documents.view_document',
                    'documents.view_parseddata',
                    
                    # No FHIR operations (cannot trigger merges)
                    # No audit access (cannot view sensitive logs)
                ]
            },
            
            'auditor': {
                'description': 'Audit and compliance access - read-only across all systems',
                'permissions': [
                    # Read-only patient access (for audit purposes)
                    'patients.view_patient', 'patients.view_patienthistory',
                    
                    # Read-only provider access
                    'providers.view_provider', 'providers.view_providerhistory',
                    
                    # Read-only document access
                    'documents.view_document', 'documents.view_parseddata',
                    
                    # Read-only FHIR operations (can view but not trigger)
                    'fhir.view_fhirmergeoperation', 'fhir.view_fhirmergeconfiguration',
                    
                    # Full audit access (primary responsibility)
                    'core.view_auditlog', 'core.view_securityevent',
                    'core.view_apiusagelog', 'core.view_compliancereport',
                ]
            }
        }

    def setup_role_permissions(self, role_name, permission_config):
        """
        Set up permissions for a specific role.
        
        Args:
            role_name: Name of the role to configure
            permission_config: Dictionary with description and permissions list
        
        Returns:
            int: Number of permissions assigned
        """
        try:
            role = Role.objects.get(name=role_name)
        except Role.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Role "{role_name}" not found'))
            return 0
        
        self.stdout.write(f'\\nConfiguring role: {role.display_name}')
        self.stdout.write(f'Description: {permission_config["description"]}')
        
        permissions_list = permission_config['permissions']
        permissions_assigned = 0
        permissions_not_found = 0
        
        # Clear existing permissions if not dry run
        if not self.dry_run:
            role.permissions.clear()
        
        for permission_codename in permissions_list:
            try:
                if '.' in permission_codename:
                    app_label, codename = permission_codename.split('.', 1)
                    
                    # Get the permission
                    permission = Permission.objects.get(
                        content_type__app_label=app_label,
                        codename=codename
                    )
                    
                    if self.dry_run:
                        self.stdout.write(f'  Would add: {permission_codename}')
                    else:
                        role.permissions.add(permission)
                        self.stdout.write(f'  ✅ Added: {permission_codename}')
                    
                    permissions_assigned += 1
                
            except Permission.DoesNotExist:
                self.stdout.write(f'  ⚠️  Permission not found: {permission_codename}')
                permissions_not_found += 1
                continue
            except Exception as e:
                self.stdout.write(f'  ❌ Error adding {permission_codename}: {e}')
                continue
        
        self.stdout.write(f'  Summary: {permissions_assigned} permissions assigned, {permissions_not_found} not found')
        
        return permissions_assigned

    def create_custom_medical_permissions(self):
        """
        Create custom medical permissions beyond Django's built-in permissions.
        
        These are healthcare-specific permissions for fine-grained access control.
        """
        custom_permissions = [
            {
                'app_label': 'patients',
                'model': 'patient',
                'codename': 'view_phi',
                'name': 'Can view Protected Health Information'
            },
            {
                'app_label': 'patients', 
                'model': 'patient',
                'codename': 'edit_phi',
                'name': 'Can edit Protected Health Information'
            },
            {
                'app_label': 'documents',
                'model': 'document',
                'codename': 'process_medical_documents',
                'name': 'Can process medical documents with AI'
            },
            {
                'app_label': 'fhir',
                'model': 'fhirmergeoperation',
                'codename': 'trigger_fhir_merge',
                'name': 'Can trigger FHIR data merge operations'
            },
            {
                'app_label': 'core',
                'model': 'auditlog',
                'codename': 'view_phi_audit',
                'name': 'Can view PHI access audit logs'
            },
        ]
        
        created_count = 0
        
        for perm_data in custom_permissions:
            try:
                # Get or create content type
                content_type = DjangoContentType.objects.get(
                    app_label=perm_data['app_label'],
                    model=perm_data['model']
                )
                
                # Create custom permission
                permission, created = Permission.objects.get_or_create(
                    codename=perm_data['codename'],
                    content_type=content_type,
                    defaults={'name': perm_data['name']}
                )
                
                if created:
                    created_count += 1
                    if self.dry_run:
                        self.stdout.write(f'  Would create: {perm_data["app_label"]}.{perm_data["codename"]}')
                    else:
                        self.stdout.write(f'  ✅ Created: {perm_data["app_label"]}.{perm_data["codename"]}')
                else:
                    if self.dry_run:
                        self.stdout.write(f'  Would update: {perm_data["app_label"]}.{perm_data["codename"]}')
                    else:
                        self.stdout.write(f'  ℹ️  Exists: {perm_data["app_label"]}.{perm_data["codename"]}')
                        
            except DjangoContentType.DoesNotExist:
                self.stdout.write(f'  ⚠️  Content type not found: {perm_data["app_label"]}.{perm_data["model"]}')
                continue
            except Exception as e:
                self.stdout.write(f'  ❌ Error creating permission {perm_data["codename"]}: {e}')
                continue
        
        return created_count
