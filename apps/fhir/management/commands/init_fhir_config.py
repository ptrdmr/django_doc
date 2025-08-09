"""
Django management command to initialize FHIR merge configuration profiles.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from apps.fhir.configuration import MergeConfigurationService
from apps.fhir.models import FHIRMergeConfiguration


class Command(BaseCommand):
    help = 'Initialize predefined FHIR merge configuration profiles'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Reset existing profiles (delete and recreate)',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='User ID to associate with created profiles',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without actually creating it',
        )
    
    def handle(self, *args, **options):
        self.stdout.write("Initializing FHIR merge configuration profiles...")
        
        user = None
        if options['user_id']:
            try:
                user = User.objects.get(id=options['user_id'])
                self.stdout.write(f"Using user: {user.username}")
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"User with ID {options['user_id']} not found")
                )
                return
        
        if options['dry_run']:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))
            self._show_predefined_profiles()
            return
        
        if options['reset']:
            self.stdout.write("Resetting existing profiles...")
            self._reset_profiles()
        
        # Initialize predefined profiles
        try:
            MergeConfigurationService.initialize_predefined_profiles(user=user)
            self.stdout.write(
                self.style.SUCCESS("Successfully initialized FHIR merge configuration profiles")
            )
            
            # Show created profiles
            self._show_created_profiles()
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Failed to initialize profiles: {e}")
            )
    
    def _reset_profiles(self):
        """Reset existing predefined profiles."""
        predefined_names = list(MergeConfigurationService.PREDEFINED_PROFILES.keys())
        deleted_count = FHIRMergeConfiguration.objects.filter(
            name__in=predefined_names
        ).delete()[0]
        
        if deleted_count > 0:
            self.stdout.write(f"Deleted {deleted_count} existing profiles")
    
    def _show_predefined_profiles(self):
        """Show what profiles would be created."""
        self.stdout.write("\nPredefined profiles that would be created:")
        
        for name, profile in MergeConfigurationService.PREDEFINED_PROFILES.items():
            self.stdout.write(f"\n{name}:")
            self.stdout.write(f"  Description: {profile['description']}")
            self.stdout.write(f"  Conflict Strategy: {profile['default_conflict_strategy']}")
            self.stdout.write(f"  Dedup Tolerance: {profile['deduplication_tolerance_hours']} hours")
            self.stdout.write(f"  Max Processing Time: {profile['max_processing_time_seconds']} seconds")
    
    def _show_created_profiles(self):
        """Show the created profiles."""
        profiles = FHIRMergeConfiguration.objects.filter(is_active=True).order_by('name')
        
        self.stdout.write(f"\nActive configuration profiles ({profiles.count()}):")
        for profile in profiles:
            default_indicator = " (DEFAULT)" if profile.is_default else ""
            self.stdout.write(f"  • {profile.name}{default_indicator}")
            self.stdout.write(f"    {profile.description}")
