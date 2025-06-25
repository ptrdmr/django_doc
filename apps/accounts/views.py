"""
Views for user accounts and dashboard.
Handles user authentication, dashboard display, and account management.
"""
from django.shortcuts import render
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.db.models import Count
from django.contrib import messages
from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from datetime import timedelta
import logging
import random

# Import our custom utilities
from apps.core.utils import (
    log_user_activity, 
    get_model_count, 
    ActivityTypes,
    safe_model_operation
)

logger = logging.getLogger(__name__)


class DashboardView(LoginRequiredMixin, TemplateView):
    """
    Main dashboard view after user login.
    Shows quick stats and navigation to main modules.
    Dynamically loads model data when available, falls back to placeholders.
    """
    template_name = 'accounts/dashboard.html'
    login_url = '/accounts/login/'
    
    def get_context_data(self, **kwargs):
        """
        Add dashboard statistics and recent activity to context.
        Uses dynamic model loading to work with or without implemented models.
        """
        context = super().get_context_data(**kwargs)
        
        # Get stats counts using utility functions
        context.update(self._get_dashboard_stats())
        
        # Get recent activities
        context['recent_activities'] = self._get_recent_activities()
        
        # Add user info for personalization
        context['user_name'] = self.request.user.get_full_name() or self.request.user.username
        
        # Log dashboard access for HIPAA compliance
        self._log_dashboard_access()
        
        return context
    
    def _get_dashboard_stats(self):
        """
        Get dashboard statistics counts using utility functions.
        
        Returns:
            dict: Dictionary with count data for dashboard
        """
        stats = {
            'patient_count': get_model_count('patients', 'Patient'),
            'provider_count': get_model_count('providers', 'Provider'),
            'document_count': get_model_count('documents', 'Document'),
            'active_users_count': self._get_active_users_count(),
        }
        
        logger.debug(f"Dashboard stats: {stats}")
        return stats
    
    def _get_active_users_count(self):
        """
        Get count of users who logged in within the last 30 days.
        
        Returns:
            int: Number of active users
        """
        try:
            from django.contrib.auth.models import User
            thirty_days_ago = timezone.now() - timedelta(days=30)
            count = User.objects.filter(last_login__gte=thirty_days_ago).count()
            logger.debug(f"Found {count} active users in last 30 days")
            return count
        except Exception as e:
            logger.error(f"Error counting active users: {e}")
            return 0
    
    def _get_recent_activities(self, limit=20):
        """
        Get recent user activities for the activity feed.
        Limited to 20 entries for performance and UX.
        
        Args:
            limit (int): Maximum number of activities to return (default: 20)
            
        Returns:
            QuerySet or list: Recent activities or placeholder data
        """
        def get_activities(Activity):
            """Operation to get activities from the model"""
            return Activity.objects.filter(
                user=self.request.user
            ).select_related('user')[:limit]
        
        activities = safe_model_operation(
            'core', 
            'Activity', 
            get_activities,
            default_return=self._get_placeholder_activities()
        )
        
        logger.debug(f"Loaded {len(activities)} activities")
        return activities
    
    def _get_placeholder_activities(self, limit=20):
        """
        Get placeholder activities for when the Activity model is not available.
        Generate enough activities to test scrolling functionality.
        
        Args:
            limit (int): Maximum number of activities to generate
            
        Returns:
            list: List of placeholder activity dictionaries
        """
        activity_types = [
            'Dashboard viewed',
            'Profile updated', 
            'Document uploaded',
            'Patient record accessed',
            'Provider information viewed',
            'Report generated',
            'Security settings changed',
            'Password updated',
            'Activity log reviewed',
            'System backup completed',
            'Data export performed',
            'FHIR validation completed',
            'Medical record processed',
            'Audit trail reviewed',
            'Compliance check performed'
        ]
        
        activities = []
        for i in range(limit):
            # Create activities with varying timestamps
            hours_ago = i * 2 + random.randint(0, 4)
            timestamp = timezone.now() - timedelta(hours=hours_ago)
            
            activities.append({
                'description': random.choice(activity_types),
                'timestamp': timestamp,
                'user': self.request.user,
            })
        
        return activities
    
    def _log_dashboard_access(self):
        """
        Log dashboard access for HIPAA compliance and activity tracking.
        """
        log_user_activity(
            user=self.request.user,
            activity_type=ActivityTypes.LOGIN,  # Using closest match
            description="Viewed dashboard",
            request=self.request
        )


class ProfileView(LoginRequiredMixin, TemplateView):
    """
    User profile view showing account information.
    """
    template_name = 'accounts/profile.html'
    login_url = '/accounts/login/'
    
    def get_context_data(self, **kwargs):
        """Add profile information to context"""
        context = super().get_context_data(**kwargs)
        
        # Log profile access
        self._log_profile_access()
        
        return context
    
    def _log_profile_access(self):
        """Log profile view for audit trail"""
        log_user_activity(
            user=self.request.user,
            activity_type=ActivityTypes.PROFILE_UPDATE,
            description="Viewed user profile",
            request=self.request
        )


class ProfileEditView(LoginRequiredMixin, TemplateView):
    """
    User profile edit view for updating account information.
    """
    template_name = 'accounts/profile_edit.html'
    login_url = '/accounts/login/'


class LockoutView(TemplateView):
    """
    Account lockout view for django-axes.
    Displayed when user has too many failed login attempts.
    """
    template_name = 'accounts/lockout.html'
    
    def get_context_data(self, **kwargs):
        """
        Add lockout information to context.
        """
        context = super().get_context_data(**kwargs)
        context['support_email'] = 'support@meddocparser.com'
        return context
