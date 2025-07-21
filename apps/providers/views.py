from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView
from django.db.models import Q, Count
from django.urls import reverse_lazy
from django.contrib import messages
from django import forms
from django.core.exceptions import ValidationError
from django.db import IntegrityError, DatabaseError, OperationalError
from django.http import JsonResponse, HttpResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
import logging
import json
import uuid
import re
from collections import defaultdict

from .models import Provider, ProviderHistory

logger = logging.getLogger(__name__)


def handle_provider_error(request, error, operation, provider_info=""):
    """
    Centralized error handling for provider operations.
    
    Args:
        request: HTTP request object
        error: Exception that occurred
        operation: String describing the operation (create, update, delete, etc.)
        provider_info: Additional provider context for logging
        
    Returns:
        None (adds message to request)
    """
    error_context = f"Provider {operation}"
    if provider_info:
        error_context += f" - {provider_info}"
    
    logger.error(f"{error_context}: {str(error)}")
    
    if isinstance(error, IntegrityError):
        if "npi" in str(error).lower():
            messages.error(request, "This NPI number is already registered to another provider.")
        else:
            messages.error(request, "A provider with this information already exists.")
    elif isinstance(error, (DatabaseError, OperationalError)):
        messages.error(request, "There was a database error. Please try again or contact support.")
    elif isinstance(error, ValidationError):
        messages.error(request, f"Validation error: {str(error)}")
    else:
        messages.error(request, f"An unexpected error occurred during {operation}. Please try again.")


class ProviderSearchForm(forms.Form):
    """
    Form for validating provider search input.
    
    Validates search query length and content to prevent
    malicious input and improve search performance.
    """
    q = forms.CharField(
        max_length=100,
        required=False,
        strip=True,
        widget=forms.TextInput(attrs={
            'placeholder': 'Search by name, NPI, specialty, or organization...',
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 pl-10'
        })
    )
    
    def clean_q(self):
        """
        Validate search query input.
        
        Returns:
            str: Cleaned search query
            
        Raises:
            ValidationError: If query contains invalid characters
        """
        query = self.cleaned_data.get('q', '').strip()
        
        if len(query) > 100:
            raise ValidationError("Search query too long. Maximum 100 characters.")
        
        # Basic input sanitization - only allow letters, numbers, spaces, and common punctuation
        allowed_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-_@&')
        if query and not set(query).issubset(allowed_chars):
            raise ValidationError("Search query contains invalid characters.")
        
        return query


class ProviderDirectoryForm(forms.Form):
    """
    Form for filtering providers in the directory view.
    
    Provides filtering by specialty, organization, and search functionality.
    """
    search = forms.CharField(
        max_length=100,
        required=False,
        strip=True,
        widget=forms.TextInput(attrs={
            'placeholder': 'Search providers by name or NPI...',
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
        })
    )
    
    specialty = forms.CharField(
        max_length=100,
        required=False,
        strip=True,
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
        })
    )
    
    organization = forms.CharField(
        max_length=200,
        required=False,
        strip=True,
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
        })
    )
    
    sort_by = forms.ChoiceField(
        choices=[
            ('name', 'Name (A-Z)'),
            ('specialty', 'Specialty'),
            ('organization', 'Organization'),
            ('recent', 'Recently Added'),
        ],
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
        })
    )
    
    def __init__(self, *args, **kwargs):
        """
        Initialize form with dynamic choices for specialty and organization.
        """
        super().__init__(*args, **kwargs)
        
        try:
            # Get specialty choices
            specialties = Provider.objects.values_list('specialty', flat=True).distinct().order_by('specialty')
            specialty_choices = [('', 'All Specialties')] + [(s, s) for s in specialties if s]
            self.fields['specialty'].widget.choices = specialty_choices
            
            # Get organization choices
            organizations = Provider.objects.values_list('organization', flat=True).distinct().order_by('organization')
            org_choices = [('', 'All Organizations')] + [(o, o) for o in organizations if o]
            self.fields['organization'].widget.choices = org_choices
            
        except (DatabaseError, OperationalError) as db_error:
            logger.error(f"Error loading directory form choices: {db_error}")
            # Fallback to empty choices
            self.fields['specialty'].widget.choices = [('', 'All Specialties')]
            self.fields['organization'].widget.choices = [('', 'All Organizations')]


class ProviderListView(LoginRequiredMixin, ListView):
    """
    Display a list of providers with search and pagination functionality.
    
    Features:
    - Search by first name, last name, NPI, specialty, or organization
    - Pagination with 20 providers per page
    - Sorting by last name
    - Professional medical UI design
    """
    model = Provider
    template_name = 'providers/provider_list.html'
    context_object_name = 'providers'
    paginate_by = 20
    
    def validate_search_input(self):
        """
        Validate search form input from request.
        
        Returns:
            tuple: (is_valid, search_query)
        """
        search_form = ProviderSearchForm(self.request.GET)
        
        if search_form.is_valid():
            search_query = search_form.cleaned_data.get('q', '')
            return True, search_query
        else:
            logger.warning(f"Invalid search form data: {search_form.errors}")
            messages.warning(self.request, "Invalid search criteria. Please try again.")
            return False, ''
    
    def filter_providers_by_search(self, queryset, search_query):
        """
        Filter provider queryset by search criteria.
        
        Args:
            queryset: Base provider queryset
            search_query: Validated search string
            
        Returns:
            QuerySet: Filtered queryset
        """
        if search_query:
            return queryset.filter(
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query) |
                Q(npi__icontains=search_query) |
                Q(specialty__icontains=search_query) |
                Q(organization__icontains=search_query)
            )
        return queryset
    
    def order_providers(self, queryset):
        """
        Apply consistent ordering to provider queryset.
        
        Args:
            queryset: Provider queryset to order
            
        Returns:
            QuerySet: Ordered queryset
        """
        return queryset.order_by('last_name', 'first_name')
    
    def get_queryset(self):
        """
        Get filtered and ordered provider queryset.
        
        Returns:
            QuerySet: Filtered provider queryset
        """
        try:
            queryset = super().get_queryset()
            is_valid, search_query = self.validate_search_input()
            
            if is_valid:
                queryset = self.filter_providers_by_search(queryset, search_query)
            
            return self.order_providers(queryset)
            
        except (DatabaseError, OperationalError) as database_error:
            logger.error(f"Database error in provider list view: {database_error}")
            messages.error(self.request, "There was an error loading providers. Please try again.")
            return Provider.objects.none()
    
    def build_search_context(self):
        """
        Build search-related context data.
        
        Returns:
            dict: Search context data
        """
        search_form = ProviderSearchForm(self.request.GET)
        search_query = search_form.data.get('q', '') if search_form.data else ''
        
        return {
            'search_form': search_form,
            'search_query': search_query
        }
    
    def get_provider_count(self):
        """
        Get total provider count safely.
        
        Returns:
            int: Total provider count
        """
        try:
            return Provider.objects.count()
        except (DatabaseError, OperationalError) as count_error:
            logger.error(f"Error getting provider count: {count_error}")
            return 0
    
    def get_specialty_summary(self):
        """
        Get summary of providers by specialty.
        
        Returns:
            dict: Specialty counts
        """
        try:
            specialty_counts = Provider.objects.values('specialty').annotate(
                count=Count('specialty')
            ).order_by('-count')[:5]  # Top 5 specialties
            
            return {item['specialty']: item['count'] for item in specialty_counts}
        except (DatabaseError, OperationalError) as specialty_error:
            logger.error(f"Error getting specialty summary: {specialty_error}")
            return {}
    
    def get_context_data(self, **kwargs):
        """
        Add extra context data for the template.
        
        Returns:
            dict: Context data with search query, form, and statistics
        """
        try:
            context = super().get_context_data(**kwargs)
            search_context = self.build_search_context()
            context.update(search_context)
            context['total_providers'] = self.get_provider_count()
            context['specialty_summary'] = self.get_specialty_summary()
            return context
            
        except (DatabaseError, OperationalError) as context_error:
            logger.error(f"Error building context for provider list: {context_error}")
            return super().get_context_data(**kwargs)


class ProviderDirectoryView(LoginRequiredMixin, TemplateView):
    """
    Provider directory view that organizes providers by specialty and provides filtering.
    
    Features:
    - Groups providers by specialty
    - Filtering by specialty, organization, search terms
    - Sorting options (name, specialty, organization, recent)
    - Pagination within each specialty group
    - Statistics and summary information
    """
    template_name = 'providers/provider_directory.html'
    
    def get_filter_form(self):
        """
        Get and validate the directory filter form.
        
        Returns:
            ProviderDirectoryForm: Validated form instance
        """
        return ProviderDirectoryForm(self.request.GET)
    
    def apply_filters(self, queryset, form):
        """
        Apply filters from the form to the provider queryset.
        
        Args:
            queryset: Base provider queryset
            form: Validated directory form
            
        Returns:
            QuerySet: Filtered queryset
        """
        if not form.is_valid():
            return queryset
        
        cleaned_data = form.cleaned_data
        
        # Apply search filter
        search_term = cleaned_data.get('search', '').strip()
        if search_term:
            queryset = queryset.filter(
                Q(first_name__icontains=search_term) |
                Q(last_name__icontains=search_term) |
                Q(npi__icontains=search_term)
            )
        
        # Apply specialty filter
        specialty_filter = cleaned_data.get('specialty', '').strip()
        if specialty_filter:
            queryset = queryset.filter(specialty=specialty_filter)
        
        # Apply organization filter
        org_filter = cleaned_data.get('organization', '').strip()
        if org_filter:
            queryset = queryset.filter(organization=org_filter)
        
        return queryset
    
    def apply_sorting(self, queryset, form):
        """
        Apply sorting to the provider queryset.
        
        Args:
            queryset: Filtered provider queryset
            form: Validated directory form
            
        Returns:
            QuerySet: Sorted queryset
        """
        if not form.is_valid():
            return queryset.order_by('last_name', 'first_name')
        
        sort_by = form.cleaned_data.get('sort_by', 'name')
        
        if sort_by == 'name':
            return queryset.order_by('last_name', 'first_name')
        elif sort_by == 'specialty':
            return queryset.order_by('specialty', 'last_name', 'first_name')
        elif sort_by == 'organization':
            return queryset.order_by('organization', 'last_name', 'first_name')
        elif sort_by == 'recent':
            return queryset.order_by('-created_at', 'last_name', 'first_name')
        else:
            return queryset.order_by('last_name', 'first_name')
    
    def group_providers_by_specialty(self, providers):
        """
        Group providers by specialty for directory display.
        
        Args:
            providers: QuerySet of providers
            
        Returns:
            dict: Specialty groups with provider lists
        """
        specialty_groups = defaultdict(list)
        
        for provider in providers:
            specialty = provider.specialty or 'Other'
            specialty_groups[specialty].append(provider)
        
        # Sort specialties alphabetically and convert to regular dict
        sorted_groups = {}
        for specialty in sorted(specialty_groups.keys()):
            sorted_groups[specialty] = specialty_groups[specialty]
        
        return sorted_groups
    
    def get_directory_statistics(self, providers, specialty_groups):
        """
        Calculate statistics for the directory.
        
        Args:
            providers: QuerySet of all providers
            specialty_groups: Grouped providers by specialty
            
        Returns:
            dict: Directory statistics
        """
        try:
            total_providers = providers.count()
            total_specialties = len(specialty_groups)
            
            # Get organizations count
            organizations = providers.values_list('organization', flat=True).distinct()
            total_organizations = len([org for org in organizations if org])
            
            # Get largest specialty group
            largest_specialty = max(
                specialty_groups.items(), 
                key=lambda x: len(x[1]),
                default=('', [])
            )
            
            return {
                'total_providers': total_providers,
                'total_specialties': total_specialties,
                'total_organizations': total_organizations,
                'largest_specialty': largest_specialty[0],
                'largest_specialty_count': len(largest_specialty[1])
            }
        except (DatabaseError, OperationalError, ValueError) as stats_error:
            logger.error(f"Error calculating directory statistics: {stats_error}")
            return {
                'total_providers': 0,
                'total_specialties': 0,
                'total_organizations': 0,
                'largest_specialty': '',
                'largest_specialty_count': 0
            }
    
    def get_context_data(self, **kwargs):
        """
        Build context data for the provider directory.
        
        Returns:
            dict: Context data with grouped providers and directory information
        """
        try:
            context = super().get_context_data(**kwargs)
            
            # Get and validate filter form
            filter_form = self.get_filter_form()
            context['filter_form'] = filter_form
            
            # Get base queryset
            providers = Provider.objects.all()
            
            # Apply filters and sorting
            filtered_providers = self.apply_filters(providers, filter_form)
            sorted_providers = self.apply_sorting(filtered_providers, filter_form)
            
            # Group providers by specialty
            specialty_groups = self.group_providers_by_specialty(sorted_providers)
            context['specialty_groups'] = specialty_groups
            
            # Calculate statistics
            stats = self.get_directory_statistics(sorted_providers, specialty_groups)
            context['directory_stats'] = stats
            
            # Add active filters for display
            if filter_form.is_valid():
                active_filters = {}
                for field, value in filter_form.cleaned_data.items():
                    if value:
                        active_filters[field] = value
                context['active_filters'] = active_filters
            
            # Add breadcrumb data
            context['breadcrumbs'] = [
                {'name': 'Home', 'url': '/'},
                {'name': 'Providers', 'url': '/providers/'},
                {'name': 'Directory', 'url': None}
            ]
            
            return context
            
        except (DatabaseError, OperationalError) as context_error:
            logger.error(f"Error building context for provider directory: {context_error}")
            return super().get_context_data(**kwargs)


class ProviderDetailView(LoginRequiredMixin, DetailView):
    """
    Display detailed information for a specific provider.
    
    Shows provider demographics, linked patients, and complete history timeline.
    Once Document management is implemented, will also show associated documents.
    """
    model = Provider
    template_name = 'providers/provider_detail.html'
    context_object_name = 'provider'
    
    def get_provider_history(self):
        """
        Get provider history records with related data for efficient display.
        
        Returns:
            QuerySet: Provider history records with related user data
        """
        try:
            return ProviderHistory.objects.filter(
                provider=self.object
            ).select_related('changed_by').order_by('-changed_at')
        except (DatabaseError, OperationalError) as history_error:
            logger.error(f"Error loading provider history for {self.object.id}: {history_error}")
            messages.warning(self.request, "Some provider history may not be available.")
            return ProviderHistory.objects.none()
    
    def get_linked_patients(self):
        """
        Get patients linked to this provider.
        
        TODO: This will work once Document and DocumentProvider models are implemented.
        For now, returns empty queryset with appropriate logging.
        
        Returns:
            QuerySet: Linked patients (empty for now)
        """
        try:
            # TODO: Uncomment when Document and DocumentProvider models exist
            # return self.object.get_patients()
            logger.info(f"Provider {self.object.npi} - patient linking not yet available")
            return []
        except (DatabaseError, OperationalError) as patients_error:
            logger.error(f"Error loading linked patients for provider {self.object.id}: {patients_error}")
            messages.warning(self.request, "Some patient information may not be available.")
            return []
    
    def get_document_count(self):
        """
        Get count of documents associated with this provider.
        
        TODO: This will work once DocumentProvider model is implemented.
        For now, returns 0.
        
        Returns:
            int: Document count (0 for now)
        """
        try:
            return self.object.get_document_count()
        except (DatabaseError, OperationalError) as doc_error:
            logger.error(f"Error getting document count for provider {self.object.id}: {doc_error}")
            return 0
    
    def get_history_statistics(self):
        """
        Get statistics about provider history for display.
        
        Returns:
            dict: History statistics
        """
        try:
            history_queryset = self.get_provider_history()
            
            total_count = history_queryset.count()
            action_counts = {}
            
            for history in history_queryset:
                action = history.action
                action_counts[action] = action_counts.get(action, 0) + 1
            
            return {
                'total_records': total_count,
                'action_breakdown': action_counts,
                'document_count': self.get_document_count()
            }
        except (DatabaseError, OperationalError) as stats_error:
            logger.error(f"Error calculating history statistics for {self.object.id}: {stats_error}")
            return {
                'total_records': 0,
                'action_breakdown': {},
                'document_count': 0
            }
    
    def get_context_data(self, **kwargs):
        """
        Add comprehensive provider context data.
        
        Returns:
            dict: Enhanced context data with provider history, linked patients, and statistics
        """
        try:
            context = super().get_context_data(**kwargs)
            
            # Add provider history
            context['provider_history'] = self.get_provider_history()
            
            # Add linked patients (empty for now)
            context['linked_patients'] = self.get_linked_patients()
            
            # Add history statistics
            context['history_stats'] = self.get_history_statistics()
            
            # Add breadcrumb data
            context['breadcrumbs'] = [
                {'name': 'Home', 'url': '/'},
                {'name': 'Providers', 'url': '/providers/'},
                {'name': f'Dr. {self.object.first_name} {self.object.last_name}', 'url': None}
            ]
            
            return context
            
        except (DatabaseError, OperationalError) as context_error:
            logger.error(f"Error building context for provider detail {self.object.id}: {context_error}")
            return super().get_context_data(**kwargs)


class ProviderForm(forms.ModelForm):
    """
    Enhanced form for provider creation and editing with comprehensive validation.
    
    Includes NPI validation, specialty suggestions, and user-friendly error messages.
    """
    
    class Meta:
        model = Provider
        fields = ['npi', 'first_name', 'last_name', 'specialty', 'organization']
        widgets = {
            'npi': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500',
                'placeholder': 'Enter 10-digit NPI number',
                'maxlength': '10',
                'pattern': '[0-9]{10}',
                'autocomplete': 'off'
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500',
                'placeholder': "Provider's first name",
                'autocomplete': 'given-name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500',
                'placeholder': "Provider's last name",
                'autocomplete': 'family-name'
            }),
            'specialty': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500',
                'placeholder': 'e.g., Cardiology, Internal Medicine',
                'list': 'specialty-suggestions',
                'autocomplete': 'off'
            }),
            'organization': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500',
                'placeholder': 'Healthcare organization or hospital',
                'autocomplete': 'organization'
            }),
        }
    
    def clean_npi(self):
        """
        Validate NPI number with comprehensive checks.
        
        Returns:
            str: Validated NPI number
            
        Raises:
            ValidationError: If NPI is invalid
        """
        npi = self.cleaned_data.get('npi', '').strip()
        
        if not npi:
            raise ValidationError("NPI number is required.")
        
        # Remove any non-digit characters
        npi_digits = re.sub(r'\D', '', npi)
        
        if len(npi_digits) != 10:
            raise ValidationError("NPI must be exactly 10 digits.")
        
        # Basic NPI validation - first digit cannot be 0
        if npi_digits[0] == '0':
            raise ValidationError("NPI cannot start with 0.")
        
        # Check for obvious patterns that indicate invalid NPI
        if npi_digits == '1234567890' or npi_digits == '0123456789':
            raise ValidationError("Please enter a valid NPI number.")
        
        # Check if NPI already exists (excluding current instance for updates)
        existing_provider = Provider.objects.filter(npi=npi_digits)
        if self.instance and self.instance.pk:
            existing_provider = existing_provider.exclude(pk=self.instance.pk)
        
        if existing_provider.exists():
            existing = existing_provider.first()
            raise ValidationError(
                f"This NPI is already registered to Dr. {existing.first_name} {existing.last_name}."
            )
        
        return npi_digits
    
    def clean_first_name(self):
        """
        Validate and format first name.
        
        Returns:
            str: Cleaned first name
        """
        first_name = self.cleaned_data.get('first_name', '').strip()
        
        if not first_name:
            raise ValidationError("First name is required.")
        
        if len(first_name) < 2:
            raise ValidationError("First name must be at least 2 characters.")
        
        # Capitalize first letter of each word
        return first_name.title()
    
    def clean_last_name(self):
        """
        Validate and format last name.
        
        Returns:
            str: Cleaned last name
        """
        last_name = self.cleaned_data.get('last_name', '').strip()
        
        if not last_name:
            raise ValidationError("Last name is required.")
        
        if len(last_name) < 2:
            raise ValidationError("Last name must be at least 2 characters.")
        
        # Capitalize first letter of each word
        return last_name.title()
    
    def clean_specialty(self):
        """
        Validate and format specialty.
        
        Returns:
            str: Cleaned specialty
        """
        specialty = self.cleaned_data.get('specialty', '').strip()
        
        if specialty:
            # Capitalize first letter of each word
            specialty = specialty.title()
            
            # Validate length
            if len(specialty) > 100:
                raise ValidationError("Specialty must be less than 100 characters.")
        
        return specialty
    
    def clean_organization(self):
        """
        Validate and format organization.
        
        Returns:
            str: Cleaned organization
        """
        organization = self.cleaned_data.get('organization', '').strip()
        
        if organization:
            # Validate length
            if len(organization) > 200:
                raise ValidationError("Organization name must be less than 200 characters.")
        
        return organization


class ProviderCreateView(LoginRequiredMixin, CreateView):
    """
    Create a new provider record with enhanced validation and error handling.
    """
    model = Provider
    form_class = ProviderForm
    template_name = 'providers/provider_form.html'
    success_url = reverse_lazy('providers:list')
    
    def create_provider_history(self):
        """
        Create history record for new provider.
        
        Returns:
            ProviderHistory: Created history record
        """
        return ProviderHistory.objects.create(
            provider=self.object,
            action='created',
            changed_by=self.request.user,
            notes=f'Provider record created by {self.request.user.get_full_name()}'
        )
    
    def show_success_message(self):
        """
        Display success message to user.
        """
        messages.success(
            self.request, 
            f'Provider Dr. {self.object.first_name} {self.object.last_name} created successfully.'
        )
    
    def form_valid(self, form):
        """
        Save the provider and create a history record with enhanced error handling.
        
        Returns:
            HttpResponse: Redirect to success URL or form with errors
        """
        try:
            response = super().form_valid(form)
            self.create_provider_history()
            self.show_success_message()
            return response
            
        except Exception as error:
            provider_info = f"NPI: {form.cleaned_data.get('npi', 'Unknown')}"
            handle_provider_error(self.request, error, "creation", provider_info)
            return self.form_invalid(form)


class ProviderUpdateView(LoginRequiredMixin, UpdateView):
    """
    Update an existing provider record with enhanced validation and error handling.
    """
    model = Provider
    form_class = ProviderForm
    template_name = 'providers/provider_form.html'
    success_url = reverse_lazy('providers:list')
    
    def create_update_history(self):
        """
        Create history record for provider update.
        
        Returns:
            ProviderHistory: Created history record
        """
        return ProviderHistory.objects.create(
            provider=self.object,
            action='updated',
            changed_by=self.request.user,
            notes=f'Provider record updated by {self.request.user.get_full_name()}'
        )
    
    def show_update_message(self):
        """
        Display update success message to user.
        """
        messages.success(
            self.request, 
            f'Provider Dr. {self.object.first_name} {self.object.last_name} updated successfully.'
        )
    
    def form_valid(self, form):
        """
        Save the provider and create a history record with enhanced error handling.
        
        Returns:
            HttpResponse: Redirect to success URL or form with errors
        """
        try:
            response = super().form_valid(form)
            self.create_update_history()
            self.show_update_message()
            return response
            
        except Exception as error:
            provider_info = f"ID: {self.object.id}, NPI: {form.cleaned_data.get('npi', 'Unknown')}"
            handle_provider_error(self.request, error, "update", provider_info)
            return self.form_invalid(form)
