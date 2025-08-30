"""
Management command to set up admin users for Docker deployment.
Creates admin users with proper RBAC roles and permissions.
"""

import os
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.db import transaction
from apps.accounts.models import Role, UserProfile
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Set up admin users with RBAC roles for Docker deployment'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            help='Email address for the admin user'
        )
        parser.add_argument(
            '--password',
            type=str,
            help='Password for the admin user'
        )
        parser.add_argument(
            '--from-env',
            action='store_true',
            help='Create admin user from environment variables'
        )

    def handle(self, *args, **options):
        """Set up admin users with proper RBAC roles."""
        self.stdout.write('🔐 Setting up admin users with RBAC roles...')
        
        if options.get('from_env'):
            self.setup_admin_from_env()
        else:
            email = options.get('email')
            password = options.get('password')
            
            if not email or not password:
                raise CommandError('Email and password are required when not using --from-env')
            
            self.setup_admin_user(email, password)
        
        self.stdout.write(self.style.SUCCESS('✅ Admin user setup completed!'))

    def setup_admin_from_env(self):
        """Set up admin user from environment variables."""
        # Get admin credentials from environment
        admin_email = os.getenv('DJANGO_ADMIN_EMAIL')
        admin_password = os.getenv('DJANGO_ADMIN_PASSWORD')
        
        if not admin_email or not admin_password:
            self.stdout.write(
                self.style.WARNING(
                    'No DJANGO_ADMIN_EMAIL or DJANGO_ADMIN_PASSWORD found in environment. '
                    'Skipping admin user creation.'
                )
            )
            return
        
        self.setup_admin_user(admin_email, admin_password)

    def setup_admin_user(self, email, password):
        """
        Set up an admin user with proper RBAC role.
        
        Args:
            email: Admin user email
            password: Admin user password
        """
        try:
            with transaction.atomic():
                # Get or create admin role
                try:
                    admin_role = Role.objects.get(name='admin')
                    self.stdout.write(f'✅ Found admin role with {admin_role.get_permission_count()} permissions')
                except Role.DoesNotExist:
                    self.stdout.write(self.style.ERROR('❌ Admin role not found. Run migrations first.'))
                    return
                
                # Create or update user
                user, user_created = User.objects.get_or_create(
                    email=email,
                    defaults={
                        'username': email,
                        'is_staff': True,
                        'is_active': True,
                    }
                )
                
                if user_created:
                    user.set_password(password)
                    user.save()
                    self.stdout.write(f'✅ Created admin user: {email}')
                else:
                    # Update password for existing user
                    user.set_password(password)
                    user.is_staff = True
                    user.is_active = True
                    user.save()
                    self.stdout.write(f'✅ Updated admin user: {email}')
                
                # Create or get user profile
                profile, profile_created = UserProfile.objects.get_or_create(user=user)
                
                if profile_created:
                    self.stdout.write(f'✅ Created UserProfile for {email}')
                
                # Assign admin role
                if not profile.roles.filter(name='admin').exists():
                    profile.roles.add(admin_role)
                    self.stdout.write(f'✅ Assigned admin role to {email}')
                else:
                    self.stdout.write(f'ℹ️  User {email} already has admin role')
                
                # Verify admin setup
                self.verify_admin_setup(user, profile)
                
        except Exception as e:
            logger.error(f"Error setting up admin user: {e}")
            self.stdout.write(self.style.ERROR(f'❌ Error: {e}'))

    def verify_admin_setup(self, user, profile):
        """
        Verify that the admin user is properly set up.
        
        Args:
            user: User instance
            profile: UserProfile instance
        """
        self.stdout.write('\n🔍 Verifying admin setup...')
        
        # Check user status
        self.stdout.write(f'  User active: {user.is_active}')
        self.stdout.write(f'  User staff: {user.is_staff}')
        
        # Check profile and roles
        self.stdout.write(f'  Has profile: {hasattr(user, "profile")}')
        self.stdout.write(f'  Role count: {profile.roles.count()}')
        self.stdout.write(f'  Is admin: {profile.is_admin()}')
        self.stdout.write(f'  Can access PHI: {profile.can_access_phi()}')
        
        # Check permissions
        from apps.accounts.permissions import PermissionChecker
        permissions = PermissionChecker.get_user_permissions_cached(user)
        self.stdout.write(f'  Permission count: {len(permissions)}')
        
        # Test key permissions
        key_permissions = [
            'accounts.add_role',
            'patients.view_patient', 
            'documents.add_document',
            'fhir.add_fhirmergeoperation',
            'core.view_auditlog'
        ]
        
        self.stdout.write('  Key permissions:')
        for perm in key_permissions:
            has_perm = perm in permissions
            status = '✅' if has_perm else '❌'
            self.stdout.write(f'    {status} {perm}')
        
        self.stdout.write('\n✅ Admin verification completed!')

    def setup_docker_environment(self):
        """
        Additional Docker-specific setup for RBAC system.
        """
        self.stdout.write('🐳 Configuring RBAC for Docker environment...')
        
        # Ensure all required roles exist
        required_roles = ['admin', 'provider', 'staff', 'auditor']
        missing_roles = []
        
        for role_name in required_roles:
            try:
                role = Role.objects.get(name=role_name)
                self.stdout.write(f'  ✅ {role.display_name} role exists')
            except Role.DoesNotExist:
                missing_roles.append(role_name)
        
        if missing_roles:
            self.stdout.write(
                self.style.ERROR(
                    f'❌ Missing roles: {", ".join(missing_roles)}. '
                    'Run migrations and role setup first.'
                )
            )
        else:
            self.stdout.write('✅ All required healthcare roles exist')
        
        # Check permission assignments
        try:
            admin_role = Role.objects.get(name='admin')
            if admin_role.get_permission_count() == 0:
                self.stdout.write(
                    self.style.WARNING(
                        '⚠️  Admin role has no permissions. Run: python manage.py setup_role_permissions'
                    )
                )
            else:
                self.stdout.write(f'✅ Admin role has {admin_role.get_permission_count()} permissions')
        except Role.DoesNotExist:
            pass
