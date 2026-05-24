"""
Views for user accounts and admin panel.
Two-tier model: Moritrac Admin (is_staff) and User.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordResetForm
from django.utils.decorators import method_decorator
from django.db import DatabaseError, OperationalError
from django.db.models import Count, Q
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from datetime import timedelta
import logging

from apps.core.utils import log_user_activity, get_model_count, ActivityTypes
from apps.patients.models import Patient
from apps.patients.views import PatientSearchForm
from .models import UserProfile
from .decorators import moritrac_admin_required

logger = logging.getLogger(__name__)


class DashboardView(LoginRequiredMixin, TemplateView):
    """Unified home page after login: metrics plus searchable patient list."""

    template_name = 'accounts/dashboard.html'
    login_url = '/accounts/login/'
    patients_per_page = 10

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self._get_dashboard_stats())
        context['user_name'] = self.request.user.get_full_name() or self.request.user.username
        context.update(self._get_patient_list_context())
        return context

    def _validate_search_input(self):
        search_form = PatientSearchForm(self.request.GET)
        if search_form.is_valid():
            return True, search_form.cleaned_data.get('q', ''), search_form
        logger.warning(f"Invalid dashboard search form data: {search_form.errors}")
        messages.warning(self.request, "Invalid search criteria. Please try again.")
        return False, '', search_form

    def _filter_patients_by_search(self, queryset, search_query):
        if not search_query:
            return queryset
        search_lower = search_query.lower()
        return queryset.filter(
            Q(first_name_search__icontains=search_lower)
            | Q(last_name_search__icontains=search_lower)
            | Q(mrn__icontains=search_query)
        )

    def _get_patient_queryset(self):
        queryset = Patient.objects.annotate(document_count=Count('documents'))
        # Users only see their own patients; admins see all
        if not self.request.user.is_staff:
            queryset = queryset.filter(created_by=self.request.user)
        is_valid, search_query, search_form = self._validate_search_input()
        if is_valid:
            queryset = self._filter_patients_by_search(queryset, search_query)
        return queryset.order_by('last_name', 'first_name'), search_form, search_query

    def _get_patient_list_context(self):
        try:
            queryset, search_form, search_query = self._get_patient_queryset()
            paginator = Paginator(queryset, self.patients_per_page)
            page_number = self.request.GET.get('page', 1)
            page_obj = paginator.get_page(page_number)
            return {
                'patients': page_obj.object_list,
                'page_obj': page_obj,
                'is_paginated': page_obj.has_other_pages(),
                'search_form': search_form,
                'search_query': search_query,
                'total_patients': queryset.count(),
            }
        except (DatabaseError, OperationalError) as db_error:
            logger.error(f"Database error loading dashboard patients: {db_error}")
            messages.error(self.request, "There was an error loading patients. Please try again.")
            return self._get_empty_patient_list_context()

    def _get_empty_patient_list_context(self):
        search_form = PatientSearchForm(self.request.GET)
        search_query = search_form.data.get('q', '') if search_form.data else ''
        return {
            'patients': [],
            'page_obj': None,
            'is_paginated': False,
            'search_form': search_form,
            'search_query': search_query,
            'total_patients': 0,
        }

    def _get_dashboard_stats(self):
        stats = {
            'patient_count': get_model_count('patients', 'Patient'),
            'document_count': get_model_count('documents', 'Document'),
            'active_users_count': self._get_active_users_count(),
        }
        return stats

    def _get_active_users_count(self):
        try:
            thirty_days_ago = timezone.now() - timedelta(days=30)
            return User.objects.filter(last_login__gte=thirty_days_ago).count()
        except Exception as e:
            logger.error(f"Error counting active users: {e}")
            return 0


class ProfileView(LoginRequiredMixin, TemplateView):
    """User profile view showing account information."""

    template_name = 'accounts/profile.html'
    login_url = '/accounts/login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        log_user_activity(
            user=self.request.user,
            activity_type=ActivityTypes.PROFILE_UPDATE,
            description="Viewed user profile",
            request=self.request,
        )
        return context


class ProfileEditView(LoginRequiredMixin, TemplateView):
    """User profile edit view."""

    template_name = 'accounts/profile_edit.html'
    login_url = '/accounts/login/'


class LockoutView(TemplateView):
    """Account lockout view for django-axes."""

    template_name = 'accounts/lockout.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['support_email'] = 'support@meddocparser.com'
        return context


# ---------------------------------------------------------------------------
# Admin Panel (Moritrac Admin only)
# ---------------------------------------------------------------------------

@method_decorator(moritrac_admin_required, name='dispatch')
class AdminUserListView(LoginRequiredMixin, ListView):
    """
    Admin panel: list all users with stats and actions.
    Replaces the old User Management + Role Management pages.
    """

    model = User
    template_name = 'accounts/admin_user_list.html'
    context_object_name = 'users'
    paginate_by = 25

    def get_queryset(self):
        qs = User.objects.annotate(
            patient_count=Count('patient_created', distinct=True),
            document_count=Count('uploaded_documents', distinct=True),
        ).order_by('-last_login')

        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(email__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('q', '')
        context['total_users'] = User.objects.count()
        context['active_users'] = User.objects.filter(is_active=True).count()
        context['admin_users'] = User.objects.filter(is_staff=True).count()
        return context


@method_decorator(moritrac_admin_required, name='dispatch')
class AdminUserDetailView(LoginRequiredMixin, DetailView):
    """
    Admin panel: detailed view of a single user.
    Shows their patients, documents, and provides admin actions.
    """

    model = User
    template_name = 'accounts/admin_user_detail.html'
    context_object_name = 'target_user'
    pk_url_kwarg = 'user_id'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        target = self.object

        context['user_patients'] = Patient.objects.filter(
            created_by=target
        ).order_by('-created_at')[:20]

        Document = None
        try:
            from apps.documents.models import Document as DocModel
            Document = DocModel
        except ImportError:
            pass

        if Document:
            context['user_documents'] = Document.objects.filter(
                uploaded_by=target
            ).order_by('-created_at')[:30]
            context['failed_documents'] = Document.objects.filter(
                uploaded_by=target, status='failed'
            ).order_by('-created_at')[:10]
        else:
            context['user_documents'] = []
            context['failed_documents'] = []

        return context


@require_POST
@moritrac_admin_required
def admin_user_action(request, user_id):
    """Handle admin actions on a user: toggle active, toggle admin, send password reset."""
    target_user = get_object_or_404(User, pk=user_id)
    action = request.POST.get('action')

    if target_user == request.user and action in ('deactivate', 'demote'):
        messages.error(request, "You cannot deactivate or demote yourself.")
        return redirect('accounts:admin_user_detail', user_id=user_id)

    if action == 'activate':
        target_user.is_active = True
        target_user.save(update_fields=['is_active'])
        messages.success(request, f"Activated {target_user.email}.")

    elif action == 'deactivate':
        target_user.is_active = False
        target_user.save(update_fields=['is_active'])
        messages.success(request, f"Deactivated {target_user.email}.")

    elif action == 'promote':
        target_user.is_staff = True
        target_user.save(update_fields=['is_staff'])
        messages.success(request, f"Promoted {target_user.email} to Admin.")

    elif action == 'demote':
        target_user.is_staff = False
        target_user.save(update_fields=['is_staff'])
        messages.success(request, f"Removed admin access from {target_user.email}.")

    elif action == 'reset_password':
        form = PasswordResetForm(data={'email': target_user.email})
        if form.is_valid():
            form.save(request=request)
            messages.success(request, f"Password reset email sent to {target_user.email}.")
        else:
            messages.error(request, "Could not send password reset email.")

    else:
        messages.error(request, f"Unknown action: {action}")

    return redirect('accounts:admin_user_detail', user_id=user_id)
