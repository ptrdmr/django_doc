"""
Management command to set up admin users.
Creates admin users with is_staff=True (Moritrac Admin).
"""

import os
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.db import transaction
from apps.accounts.models import UserProfile
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Set up admin users (Moritrac Admin = is_staff=True)'

    def add_arguments(self, parser):
        parser.add_argument('--email', type=str, help='Email address for the admin user')
        parser.add_argument('--password', type=str, help='Password for the admin user')
        parser.add_argument('--from-env', action='store_true', help='Create from environment variables')

    def handle(self, *args, **options):
        if options.get('from_env'):
            self._setup_from_env()
        else:
            email = options.get('email')
            password = options.get('password')
            if not email or not password:
                raise CommandError('Email and password are required when not using --from-env')
            self._create_admin(email, password)

    def _setup_from_env(self):
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '')
        if not email or not password:
            self.stdout.write(self.style.WARNING(
                'DJANGO_SUPERUSER_EMAIL and DJANGO_SUPERUSER_PASSWORD not set. Skipping.'
            ))
            return
        self._create_admin(email, password)

    @transaction.atomic
    def _create_admin(self, email, password):
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                'username': email,
                'is_staff': True,
                'is_superuser': True,
                'is_active': True,
            }
        )
        if created:
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f'Created admin user: {email}'))
        else:
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            user.save(update_fields=['is_staff', 'is_superuser', 'is_active'])
            self.stdout.write(self.style.SUCCESS(f'Updated existing user to admin: {email}'))

        UserProfile.get_or_create_for_user(user)
        logger.info(f"Admin user setup complete: {email}")
