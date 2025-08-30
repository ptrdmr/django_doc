"""
Management command to set up HIPAA audit logging permissions and groups.
Creates appropriate user groups with proper permissions for compliance officers.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from apps.core.models import AuditLog, SecurityEvent, ComplianceReport


class Command(BaseCommand):
    help = 'Set up HIPAA audit logging permissions and user groups'

    def add_arguments(self, parser):
        parser.add_argument(
            '--create-groups',
            action='store_true',
            help='Create user groups for audit access',
        )
        parser.add_argument(
            '--list-permissions',
            action='store_true',
            help='List all audit-related permissions',
        )

    def handle(self, *args, **options):
        """Main command handler."""
        
        if options['list_permissions']:
            self.list_permissions()
            return
        
        if options['create_groups']:
            self.create_audit_groups()
            return
        
        # Default: create groups
        self.create_audit_groups()

    def list_permissions(self):
        """List all audit-related permissions."""
        self.stdout.write(self.style.SUCCESS('Audit-related permissions:'))
        
        # Get content types for our models
        audit_ct = ContentType.objects.get_for_model(AuditLog)
        security_ct = ContentType.objects.get_for_model(SecurityEvent)
        compliance_ct = ContentType.objects.get_for_model(ComplianceReport)
        
        # List permissions for each model
        for ct, model_name in [(audit_ct, 'AuditLog'), (security_ct, 'SecurityEvent'), (compliance_ct, 'ComplianceReport')]:
            permissions = Permission.objects.filter(content_type=ct)
            self.stdout.write(f'\n{model_name} permissions:')
            for perm in permissions:
                self.stdout.write(f'  - {perm.codename}: {perm.name}')

    def create_audit_groups(self):
        """Create user groups with appropriate audit permissions."""
        
        # Get content types
        audit_ct = ContentType.objects.get_for_model(AuditLog)
        security_ct = ContentType.objects.get_for_model(SecurityEvent)
        compliance_ct = ContentType.objects.get_for_model(ComplianceReport)
        
        # Define groups and their permissions
        groups_config = {
            'Audit Viewers': {
                'description': 'Can view audit logs but not export',
                'permissions': [
                    ('core', 'view_audit_trail'),
                    ('core', 'view_securityevent'),
                    ('core', 'view_compliancereport'),
                ]
            },
            'Compliance Officers': {
                'description': 'Full access to audit logs and compliance reporting',
                'permissions': [
                    ('core', 'view_audit_trail'),
                    ('core', 'export_audit_logs'),
                    ('core', 'manage_audit_system'),
                    ('core', 'view_securityevent'),
                    ('core', 'change_securityevent'),
                    ('core', 'view_compliancereport'),
                    ('core', 'add_compliancereport'),
                    ('core', 'change_compliancereport'),
                ]
            },
            'Security Administrators': {
                'description': 'Can manage security events and audit system',
                'permissions': [
                    ('core', 'view_audit_trail'),
                    ('core', 'export_audit_logs'),
                    ('core', 'manage_audit_system'),
                    ('core', 'view_securityevent'),
                    ('core', 'add_securityevent'),
                    ('core', 'change_securityevent'),
                    ('core', 'delete_securityevent'),
                    ('core', 'view_compliancereport'),
                ]
            },
        }
        
        # Create groups
        for group_name, config in groups_config.items():
            group, created = Group.objects.get_or_create(name=group_name)
            
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Created group: {group_name}')
                )
            else:
                self.stdout.write(f'Group already exists: {group_name}')
            
            # Clear existing permissions
            group.permissions.clear()
            
            # Add permissions to group
            permissions_added = 0
            for app_label, codename in config['permissions']:
                try:
                    permission = Permission.objects.get(
                        content_type__app_label=app_label,
                        codename=codename
                    )
                    group.permissions.add(permission)
                    permissions_added += 1
                except Permission.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(
                            f'Permission not found: {app_label}.{codename}'
                        )
                    )
            
            self.stdout.write(f'  Added {permissions_added} permissions')
            self.stdout.write(f'  Description: {config["description"]}')
        
        self.stdout.write('\n' + self.style.SUCCESS('Audit permission groups setup complete!'))
        self.stdout.write('\nUsage instructions:')
        self.stdout.write('1. Assign users to appropriate groups based on their roles:')
        self.stdout.write('   - Audit Viewers: Basic staff who need to view audit logs')
        self.stdout.write('   - Compliance Officers: Compliance team members who generate reports')
        self.stdout.write('   - Security Administrators: IT security staff who manage incidents')
        self.stdout.write('\n2. These groups provide HIPAA-compliant access controls for audit data')
        self.stdout.write('3. All access to audit logs is itself logged for compliance')
        
        # Show group summary
        self.stdout.write('\n' + self.style.SUCCESS('Created Groups Summary:'))
        for group_name in groups_config.keys():
            group = Group.objects.get(name=group_name)
            perm_count = group.permissions.count()
            user_count = group.user_set.count()
            self.stdout.write(f'  {group_name}: {perm_count} permissions, {user_count} users')
