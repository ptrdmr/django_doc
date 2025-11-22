"""
Patient management views.
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView, View
from django.db.models import Q, Count
from django.urls import reverse_lazy
from django.contrib import messages
from django import forms
from django.core.exceptions import ValidationError
from django.db import IntegrityError, DatabaseError, OperationalError, transaction
from django.http import JsonResponse, HttpResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
import logging
import json
import uuid
from difflib import SequenceMatcher

from .models import Patient, PatientHistory
from .forms import PatientForm
from apps.accounts.decorators import has_permission, requires_phi_access, provider_required, admin_required
from django.utils.decorators import method_decorator

logger = logging.getLogger(__name__)


class PatientSearchForm(forms.Form):
    """
    Form for validating patient search input.
    
    Validates search query length and content to prevent
    malicious input and improve search performance.
    """
    q = forms.CharField(
        max_length=100,
        required=False,
        strip=True,
        widget=forms.TextInput(attrs={
            'placeholder': 'Search by name, MRN, or date of birth...',
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
        allowed_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-_@')
        if query and not set(query).issubset(allowed_chars):
            raise ValidationError("Search query contains invalid characters.")
        
        return query


@method_decorator(has_permission('patients.view_patient'), name='dispatch')
class PatientListView(LoginRequiredMixin, ListView):
    """
    Display a list of patients with search and pagination functionality.
    
    Features:
    - Search by first name, last name, or MRN
    - Pagination with 20 patients per page
    - Sorting by last name
    - Professional medical UI design
    """
    model = Patient
    template_name = 'patients/patient_list.html'
    context_object_name = 'patients'
    paginate_by = 20
    
    def validate_search_input(self):
        """
        Validate search form input from request.
        
        Returns:
            tuple: (is_valid, search_query)
        """
        search_form = PatientSearchForm(self.request.GET)
        
        if search_form.is_valid():
            search_query = search_form.cleaned_data.get('q', '')
            return True, search_query
        else:
            logger.warning(f"Invalid search form data: {search_form.errors}")
            messages.warning(self.request, "Invalid search criteria. Please try again.")
            return False, ''
    
    def filter_patients_by_search(self, queryset, search_query):
        """
        Filter patient queryset by search criteria using search-optimized fields.
        
        Uses unencrypted, indexed search fields for efficient case-insensitive searching
        while maintaining encryption of sensitive PHI data.
        
        Args:
            queryset: Base patient queryset
            search_query: Validated search string
            
        Returns:
            QuerySet: Filtered queryset
        """
        if search_query:
            # Use search-optimized fields for efficient database lookups
            search_lower = search_query.lower()
            return queryset.filter(
                Q(first_name_search__icontains=search_lower) |
                Q(last_name_search__icontains=search_lower) |
                Q(mrn__icontains=search_query)
            )
        return queryset
    
    def order_patients(self, queryset):
        """
        Apply consistent ordering to patient queryset.
        
        Args:
            queryset: Patient queryset to order
            
        Returns:
            QuerySet: Ordered queryset
        """
        return queryset.order_by('last_name', 'first_name')
    
    def get_queryset(self):
        """
        Get filtered and ordered patient queryset.
        
        Returns:
            QuerySet: Filtered patient queryset
        """
        try:
            queryset = super().get_queryset()
            is_valid, search_query = self.validate_search_input()
            
            if is_valid:
                queryset = self.filter_patients_by_search(queryset, search_query)
            
            return self.order_patients(queryset)
            
        except (DatabaseError, OperationalError) as database_error:
            logger.error(f"Database error in patient list view: {database_error}")
            messages.error(self.request, "There was an error loading patients. Please try again.")
            return Patient.objects.none()
    
    def build_search_context(self):
        """
        Build search-related context data.
        
        Returns:
            dict: Search context data
        """
        search_form = PatientSearchForm(self.request.GET)
        search_query = search_form.data.get('q', '') if search_form.data else ''
        
        return {
            'search_form': search_form,
            'search_query': search_query
        }
    
    def get_patient_count(self):
        """
        Get total patient count safely.
        
        Returns:
            int: Total patient count
        """
        try:
            return Patient.objects.count()
        except (DatabaseError, OperationalError) as count_error:
            logger.error(f"Error getting patient count: {count_error}")
            return 0
    
    def get_context_data(self, **kwargs):
        """
        Add extra context data for the template.
        
        Returns:
            dict: Context data with search query and form
        """
        try:
            context = super().get_context_data(**kwargs)
            search_context = self.build_search_context()
            context.update(search_context)
            context['total_patients'] = self.get_patient_count()
            return context
            
        except (DatabaseError, OperationalError) as context_error:
            logger.error(f"Error building context for patient list: {context_error}")
            return super().get_context_data(**kwargs)


@method_decorator([requires_phi_access, has_permission('patients.view_patient')], name='dispatch')
class PatientDetailView(LoginRequiredMixin, DetailView):
    """
    Display detailed information for a specific patient.
    
    Shows patient demographics, FHIR data summary, and complete history timeline.
    Includes functionality to view specific versions of FHIR data.
    """
    model = Patient
    template_name = 'patients/patient_detail.html'
    context_object_name = 'patient'
    
    def get_patient_history(self):
        """
        Get patient history records with related data for efficient display.
        
        Returns:
            QuerySet: Patient history records with related user data
        """
        try:
            return PatientHistory.objects.filter(
                patient=self.object
            ).select_related('changed_by').order_by('-changed_at')
        except (DatabaseError, OperationalError) as history_error:
            logger.error(f"Error loading patient history for {self.object.id}: {history_error}")
            messages.warning(self.request, "Some patient history may not be available.")
            return PatientHistory.objects.none()
    
    def get_fhir_summary(self):
        """
        Get FHIR data summary with resource counts.
        
        Returns:
            dict: FHIR resource summary with counts and last updated info
        """
        try:
            # Access the encrypted FHIR bundle (current field, not legacy cumulative_fhir_json)
            fhir_bundle = self.object.encrypted_fhir_bundle
            if not fhir_bundle or not fhir_bundle.get('entry'):
                return {}
            
            # Count resources by type from the FHIR Bundle entries
            summary = {}
            # Initialize specific counters for Labs and Vitals
            lab_count = 0
            vital_count = 0
            
            for entry in fhir_bundle.get('entry', []):
                resource = entry.get('resource', {})
                resource_type = resource.get('resourceType')
                
                if resource_type:
                    if resource_type not in summary:
                        summary[resource_type] = {
                            'count': 0,
                            'resources': []
                        }
                    summary[resource_type]['count'] += 1
                    summary[resource_type]['resources'].append(resource)
                    
                    # Check if it's a Lab or Vital (for separate counts)
                    if resource_type == 'Observation':
                        is_vital = False
                        code_text = ""
                        
                        # Try to determine from code
                        if 'code' in resource:
                            code_obj = resource['code']
                            if 'text' in code_obj:
                                code_text = code_obj['text'].lower()
                            elif 'coding' in code_obj and code_obj['coding']:
                                code_text = (code_obj['coding'][0].get('display') or '').lower()
                        
                        # Vital keywords
                        vital_keywords = [
                            'blood pressure', 'systolic', 'diastolic', 
                            'heart rate', 'pulse', 
                            'temperature', 
                            'respiratory', 'breathing rate',
                            'oxygen saturation', 'o2 sat',
                            'height', 'weight', 'bmi', 'body mass'
                        ]
                        
                        if any(k in code_text for k in vital_keywords):
                            vital_count += 1
                        else:
                            # If it's an Observation but not a Vital, count as Lab
                            lab_count += 1

            # Add last updated info for each resource type
            for resource_type, data in summary.items():
                data['last_updated'] = self.get_latest_resource_date(data['resources'])
                # Remove resources list from summary to keep it clean
                del data['resources']
            
            # Add the separate counts to the summary dictionary
            summary['LabResult'] = {'count': lab_count}
            summary['VitalSign'] = {'count': vital_count}
            
            return summary
        except (TypeError, KeyError) as fhir_error:
            logger.error(f"Error processing FHIR data for patient {self.object.id}: {fhir_error}")
            return {}
    
    def get_latest_resource_date(self, resources):
        """
        Get the latest update date from FHIR resources.
        
        Args:
            resources (list): List of FHIR resources
            
        Returns:
            str: Latest update date or None
        """
        try:
            dates = []
            for resource in resources:
                if isinstance(resource, dict) and 'meta' in resource:
                    if 'lastUpdated' in resource['meta']:
                        dates.append(resource['meta']['lastUpdated'])
            
            if dates:
                return max(dates)
            return None
        except (TypeError, KeyError):
            return None
    
    def get_history_statistics(self):
        """
        Get statistics about patient history for display.
        
        Returns:
            dict: History statistics
        """
        try:
            history_queryset = self.get_patient_history()
            
            total_count = history_queryset.count()
            action_counts = {}
            
            for history in history_queryset:
                action = history.action
                action_counts[action] = action_counts.get(action, 0) + 1
            
            return {
                'total_records': total_count,
                'action_breakdown': action_counts,
                'has_fhir_data': bool(self.object.cumulative_fhir_json)
            }
        except (DatabaseError, OperationalError) as stats_error:
            logger.error(f"Error calculating history statistics for {self.object.id}: {stats_error}")
            return {
                'total_records': 0,
                'action_breakdown': {},
                'has_fhir_data': False
            }
    
    def get_patient_reports(self):
        """
        Get reports generated for this patient.
        
        Returns:
            QuerySet: GeneratedReport objects
        """
        try:
            # Import here to avoid circular dependency
            from apps.reports.models import GeneratedReport
            
            return GeneratedReport.objects.filter(
                parameters_snapshot__patient_id=str(self.object.id)
            ).order_by('-created_at')
        except (ImportError, DatabaseError, OperationalError) as e:
            logger.error(f"Error loading reports for patient {self.object.id}: {e}")
            return []

    def get_context_data(self, **kwargs):
        """
        Add comprehensive patient context data.
        
        Returns:
            dict: Enhanced context data with patient history, FHIR summary, and statistics
        """
        try:
            context = super().get_context_data(**kwargs)
            
            # Add patient history
            context['patient_history'] = self.get_patient_history()
            
            # Add FHIR data summary
            context['fhir_summary'] = self.get_fhir_summary()
            
            # Add history statistics
            context['history_stats'] = self.get_history_statistics()
            
            # Add patient's documents
            context['patient_documents'] = self.object.documents.select_related('created_by').order_by('-uploaded_at')
            
            # Add patient's generated reports
            context['patient_reports'] = self.get_patient_reports()
            
            # Add breadcrumb data
            context['breadcrumbs'] = [
                {'name': 'Home', 'url': '/'},
                {'name': 'Patients', 'url': '/patients/'},
                {'name': f'{self.object.first_name} {self.object.last_name}', 'url': None}
            ]
            
            # Add debug flag for development-only features
            from django.conf import settings
            context['debug'] = settings.DEBUG
            
            return context
            
        except (DatabaseError, OperationalError) as context_error:
            logger.error(f"Error building context for patient detail {self.object.id}: {context_error}")
            return super().get_context_data(**kwargs)


@method_decorator([provider_required, has_permission('patients.add_patient')], name='dispatch')
class PatientCreateView(LoginRequiredMixin, CreateView):
    """
    Create a new patient record.
    """
    model = Patient
    form_class = PatientForm
    template_name = 'patients/patient_form.html'
    success_url = reverse_lazy('patients:list')
    
    def create_patient_history(self):
        """
        Create history record for new patient.
        
        Returns:
            PatientHistory: Created history record
        """
        return PatientHistory.objects.create(
            patient=self.object,
            action='created',
            changed_by=self.request.user,
            notes=f'Patient record created by {self.request.user.get_full_name()}'
        )
    
    def show_success_message(self):
        """
        Display success message to user.
        """
        messages.success(
            self.request, 
            f'Patient {self.object.first_name} {self.object.last_name} created successfully.'
        )
    
    def form_valid(self, form):
        """
        Save the patient and create a history record.
        
        Returns:
            HttpResponse: Redirect to success URL
        """
        try:
            response = super().form_valid(form)
            self.create_patient_history()
            self.show_success_message()
            return response
            
        except IntegrityError as integrity_error:
            logger.error(f"Database integrity error creating patient: {integrity_error}")
            messages.error(self.request, "A patient with this MRN already exists.")
            return self.form_invalid(form)
            
        except (DatabaseError, OperationalError) as create_error:
            logger.error(f"Error creating patient: {create_error}")
            messages.error(self.request, "There was an error creating the patient record.")
            return self.form_invalid(form)


@method_decorator([provider_required, has_permission('patients.change_patient')], name='dispatch')
class PatientUpdateView(LoginRequiredMixin, UpdateView):
    """
    Update an existing patient record.
    """
    model = Patient
    form_class = PatientForm
    template_name = 'patients/patient_form.html'
    success_url = reverse_lazy('patients:list')
    
    def create_update_history(self):
        """
        Create history record for patient update.
        
        Returns:
            PatientHistory: Created history record
        """
        return PatientHistory.objects.create(
            patient=self.object,
            action='updated',
            changed_by=self.request.user,
            notes=f'Patient record updated by {self.request.user.get_full_name()}'
        )
    
    def show_update_message(self):
        """
        Display update success message to user.
        """
        messages.success(
            self.request, 
            f'Patient {self.object.first_name} {self.object.last_name} updated successfully.'
        )
    
    def form_valid(self, form):
        """
        Save the patient and create a history record.
        
        Returns:
            HttpResponse: Redirect to success URL
        """
        try:
            response = super().form_valid(form)
            self.create_update_history()
            self.show_update_message()
            return response
            
        except IntegrityError as integrity_error:
            logger.error(f"Database integrity error updating patient: {integrity_error}")
            messages.error(self.request, "A patient with this MRN already exists.")
            return self.form_invalid(form)
            
        except (DatabaseError, OperationalError) as update_error:
            logger.error(f"Error updating patient {self.object.id}: {update_error}")
            messages.error(self.request, "There was an error updating the patient record.")
            return self.form_invalid(form)


# ============================================================================
# FHIR Export Views
# ============================================================================

@method_decorator([provider_required, has_permission('patients.change_patient')], name='dispatch')
class SetPrimaryDiagnosisView(LoginRequiredMixin, View):
    """
    AJAX endpoint to set primary diagnosis for a patient.
    """
    
    def post(self, request, pk):
        """
        Set primary diagnosis for patient.
        
        Args:
            request: HTTP request with condition_id in POST data
            pk: Patient UUID
            
        Returns:
            JsonResponse: Success or error message
        """
        try:
            patient = get_object_or_404(Patient, pk=pk)
            condition_id = request.POST.get('condition_id')
            
            if not condition_id:
                return JsonResponse({
                    'success': False, 
                    'error': 'No condition ID provided'
                }, status=400)
            
            # Validate that condition exists in patient's FHIR data
            condition_found = False
            for entry in patient.encrypted_fhir_bundle.get('entry', []):
                resource = entry.get('resource', {})
                if (resource.get('resourceType') == 'Condition' and 
                    resource.get('id') == condition_id):
                    condition_found = True
                    break
            
            if not condition_found:
                return JsonResponse({
                    'success': False,
                    'error': 'Condition not found in patient records'
                }, status=404)
            
            # Update primary condition
            patient.primary_condition_id = condition_id
            patient.save()
            
            # Create audit record
            PatientHistory.objects.create(
                patient=patient,
                action='updated',
                changed_by=request.user,
                notes=f'Primary diagnosis set to condition {condition_id} by {request.user.get_full_name()}'
            )
            
            logger.info(f"Primary diagnosis set for patient {patient.mrn} by user {request.user.id}")
            
            return JsonResponse({
                'success': True,
                'message': 'Primary diagnosis updated successfully'
            })
            
        except Exception as e:
            logger.error(f"Error setting primary diagnosis for patient {pk}: {e}")
            return JsonResponse({
                'success': False,
                'error': 'An error occurred while updating the primary diagnosis'
            }, status=500)


@method_decorator([requires_phi_access, has_permission('patients.export_patient_data')], name='dispatch')
class PatientFHIRExportView(LoginRequiredMixin, View):
    """
    Export patient data as FHIR JSON file download.
    """
    
    def get(self, request, pk):
        """
        Generate and download FHIR data for a patient.
        
        Args:
            request: HTTP request
            pk: Patient UUID
            
        Returns:
            HttpResponse: JSON file download
        """
        try:
            patient = get_object_or_404(Patient, pk=pk)
            
            # Create FHIR bundle
            fhir_bundle = self.create_fhir_bundle(patient)
            
            # Create response with JSON file
            response = HttpResponse(
                json.dumps(fhir_bundle, indent=2),
                content_type='application/json'
            )
            response['Content-Disposition'] = f'attachment; filename="patient_{patient.mrn}_fhir_export.json"'
            
            # Log the export
            PatientHistory.objects.create(
                patient=patient,
                action='fhir_export',
                changed_by=request.user,
                notes=f'FHIR data exported by {request.user.get_full_name()}'
            )
            
            return response
            
        except Exception as export_error:
            logger.error(f"Error exporting FHIR data for patient {pk}: {export_error}")
            messages.error(request, "There was an error exporting the patient data.")
            return redirect('patients:detail', pk=pk)
    
    def create_fhir_bundle(self, patient):
        """
        Create a complete FHIR bundle for the patient.
        
        Args:
            patient: Patient instance
            
        Returns:
            dict: FHIR bundle structure
        """
        bundle = {
            "resourceType": "Bundle",
            "id": str(uuid.uuid4()),
            "type": "document",
            "timestamp": timezone.now().isoformat(),
            "entry": []
        }
        
        # Add patient resource
        patient_resource = {
            "resource": {
                "resourceType": "Patient",
                "id": str(patient.id),
                "identifier": [
                    {
                        "use": "usual",
                        "type": {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                                    "code": "MR",
                                    "display": "Medical record number"
                                }
                            ]
                        },
                        "value": patient.mrn
                    }
                ],
                "name": [
                    {
                        "use": "official",
                        "family": patient.last_name,
                        "given": [patient.first_name]
                    }
                ],
                "birthDate": patient.get_date_of_birth().isoformat() if patient.get_date_of_birth() else None,
                "gender": self.map_gender_to_fhir(patient.gender)
            }
        }
        bundle["entry"].append(patient_resource)
        
        # Add existing FHIR data from encrypted bundle
        if patient.encrypted_fhir_bundle and patient.encrypted_fhir_bundle.get('entry'):
            for entry in patient.encrypted_fhir_bundle.get('entry', []):
                if 'resource' in entry:
                    bundle["entry"].append({"resource": entry["resource"]})
        
        return bundle
    
    def map_gender_to_fhir(self, gender):
        """
        Map internal gender codes to FHIR gender values.
        
        Args:
            gender: Internal gender code
            
        Returns:
            str: FHIR gender value
        """
        gender_map = {
            'M': 'male',
            'F': 'female',
            'O': 'other'
        }
        return gender_map.get(gender, 'unknown')


@method_decorator([requires_phi_access, has_permission('patients.view_patient')], name='dispatch')
class PatientFHIRJSONView(LoginRequiredMixin, View):
    """
    Return patient FHIR data as JSON (for API access).
    """
    
    def get(self, request, pk):
        """
        Return FHIR data as JSON response.
        
        Args:
            request: HTTP request
            pk: Patient UUID
            
        Returns:
            JsonResponse: FHIR data
        """
        try:
            patient = get_object_or_404(Patient, pk=pk)
            
            return JsonResponse({
                'patient_id': str(patient.id),
                'mrn': patient.mrn,
                'fhir_data': patient.encrypted_fhir_bundle,
                'last_updated': patient.updated_at.isoformat()
            })
            
        except Exception as json_error:
            logger.error(f"Error returning FHIR JSON for patient {pk}: {json_error}")
            return JsonResponse({'error': 'Unable to retrieve patient FHIR data'}, status=500)


# ============================================================================
# Patient History Views
# ============================================================================

@method_decorator([requires_phi_access, has_permission('patients.view_patient')], name='dispatch')
class PatientHistoryDetailView(LoginRequiredMixin, DetailView):
    """
    Detailed view of patient history timeline.
    """
    model = Patient
    template_name = 'patients/patient_history.html'
    context_object_name = 'patient'
    
    def get_context_data(self, **kwargs):
        """
        Add detailed history data to context.
        
        Returns:
            dict: Context with detailed history
        """
        context = super().get_context_data(**kwargs)
        
        try:
            # Get all history with related data
            history = PatientHistory.objects.filter(
                patient=self.object
            ).select_related('changed_by').order_by('-changed_at')
            
            context['patient_history'] = history
            context['history_count'] = history.count()
            
            # Group history by action type
            action_summary = {}
            for record in history:
                action = record.action
                if action not in action_summary:
                    action_summary[action] = 0
                action_summary[action] += 1
            
            context['action_summary'] = action_summary
            
        except (DatabaseError, OperationalError) as history_error:
            logger.error(f"Error loading detailed history for patient {self.object.id}: {history_error}")
            context['patient_history'] = PatientHistory.objects.none()
            context['history_count'] = 0
            context['action_summary'] = {}
        
        return context


@method_decorator([requires_phi_access, has_permission('patients.view_patient')], name='dispatch')
class PatientHistoryItemView(LoginRequiredMixin, DetailView):
    """
    View individual history record details.
    """
    model = PatientHistory
    template_name = 'patients/history_item.html'
    context_object_name = 'history_item'
    pk_url_kwarg = 'history_pk'
    
    def get_context_data(self, **kwargs):
        """
        Add patient context to history item.
        
        Returns:
            dict: Context with patient data
        """
        context = super().get_context_data(**kwargs)
        context['patient'] = self.object.patient
        return context


# ============================================================================
# Development-Only Deletion Views
# ============================================================================

@method_decorator([admin_required, has_permission('patients.delete_patient')], name='dispatch')
class PatientDeleteView(LoginRequiredMixin, View):
    """
    Development-only view for deleting patients.
    
    WARNING: This view is only available in development mode.
    In production, patients should be soft-deleted or archived.
    """
    http_method_names = ['get', 'post']
    
    def dispatch(self, request, *args, **kwargs):
        """Check if we're in development mode."""
        from django.conf import settings
        
        if not settings.DEBUG:
            messages.error(request, "Patient deletion is only available in development mode.")
            return redirect('patients:list')
        
        return super().dispatch(request, *args, **kwargs)
    
    def get(self, request, pk):
        """Show confirmation page for patient deletion."""
        try:
            patient = get_object_or_404(Patient, pk=pk)
            
            # Get related data counts for confirmation
            related_data = {
                'documents': patient.documents.count(),
                'history_records': patient.history_records.count(),
                'parsed_data': patient.parsed_data.count() if hasattr(patient, 'parsed_data') else 0,
            }
            
            return render(request, 'patients/patient_confirm_delete.html', {
                'patient': patient,
                'related_data': related_data,
                'total_related_items': sum(related_data.values())
            })
            
        except Exception as delete_error:
            logger.error(f"Error loading patient deletion page: {delete_error}")
            messages.error(request, "Error loading patient data.")
            return redirect('patients:list')
    
    def post(self, request, pk):
        """Handle patient deletion with cascade cleanup."""
        try:
            with transaction.atomic():
                patient = get_object_or_404(Patient, pk=pk)
                patient_name = f"{patient.first_name} {patient.last_name}"
                patient_mrn = patient.mrn
                
                # Count related items before deletion
                doc_count = patient.documents.count()
                history_count = patient.history_records.count()
                
                logger.warning(
                    f"DEVELOPMENT DELETE: User {request.user.id} hard deleting patient {patient.mrn} "
                    f"with {doc_count} documents and {history_count} history records"
                )
                
                # HARD DELETE: First delete related records, then the patient
                # Delete patient history first (due to PROTECT constraint)
                PatientHistory.objects.filter(patient=patient).delete()
                
                # Delete any parsed data records
                if hasattr(patient, 'parsed_data'):
                    patient.parsed_data.all().delete()
                
                # Now we can safely hard delete the patient
                super(Patient, patient).delete()
                
                # Also clean up any other soft-deleted patients with the same MRN
                # (in case there were previous soft deletes)
                self.cleanup_soft_deleted_with_mrn(patient_mrn)
                
                messages.success(
                    request,
                    f"Patient {patient_name} (MRN: {patient_mrn}) and all related data "
                    f"({doc_count} documents, {history_count} history records) have been permanently deleted."
                )
                
                return redirect('patients:list')
                
        except Exception as delete_error:
            logger.error(f"Error deleting patient {pk}: {delete_error}")
            messages.error(request, "Error deleting patient. Please try again.")
            return redirect('patients:detail', pk=pk)
    
    def cleanup_soft_deleted_with_mrn(self, mrn):
        """Clean up any soft-deleted patients with the same MRN."""
        try:
            soft_deleted = Patient.all_objects.filter(mrn=mrn, deleted_at__isnull=False)
            for soft_patient in soft_deleted:
                try:
                    # Delete related history first
                    PatientHistory.objects.filter(patient=soft_patient).delete()
                    # Hard delete the soft-deleted patient
                    super(Patient, soft_patient).delete()
                except Exception as cleanup_error:
                    logger.error(f"Error cleaning up soft-deleted patient {soft_patient.id}: {cleanup_error}")
        except Exception as e:
            logger.error(f"Error during MRN cleanup for {mrn}: {e}")


@method_decorator([admin_required], name='dispatch')
class CleanupSoftDeletedView(LoginRequiredMixin, View):
    """
    Development utility to permanently remove soft-deleted patients.
    
    This helps clean up patients that were soft-deleted and might be
    blocking MRN reuse in development.
    """
    http_method_names = ['get', 'post']
    
    def dispatch(self, request, *args, **kwargs):
        """Check if we're in development mode."""
        from django.conf import settings
        
        if not settings.DEBUG:
            messages.error(request, "Cleanup functionality is only available in development mode.")
            return redirect('patients:list')
        
        return super().dispatch(request, *args, **kwargs)
    
    def get(self, request):
        """Show soft-deleted patients that can be cleaned up."""
        try:
            # Get soft-deleted patients
            soft_deleted = Patient.all_objects.filter(deleted_at__isnull=False)
            
            return render(request, 'patients/cleanup_soft_deleted.html', {
                'soft_deleted_patients': soft_deleted,
                'count': soft_deleted.count()
            })
            
        except Exception as cleanup_error:
            logger.error(f"Error loading cleanup page: {cleanup_error}")
            messages.error(request, "Error loading soft-deleted patients.")
            return redirect('patients:list')
    
    def post(self, request):
        """Permanently delete all soft-deleted patients."""
        try:
            with transaction.atomic():
                # Get soft-deleted patients
                soft_deleted = Patient.all_objects.filter(deleted_at__isnull=False)
                count = soft_deleted.count()
                
                if count == 0:
                    messages.info(request, "No soft-deleted patients found to clean up.")
                    return redirect('patients:list')
                
                # Get MRNs for logging
                mrns = list(soft_deleted.values_list('mrn', flat=True))
                
                logger.warning(
                    f"DEVELOPMENT CLEANUP: User {request.user.id} permanently deleting "
                    f"{count} soft-deleted patients: {mrns}"
                )
                
                # Hard delete all soft-deleted patients
                for patient in soft_deleted:
                    try:
                        # Delete patient history first (due to PROTECT constraint)
                        PatientHistory.objects.filter(patient=patient).delete()
                        
                        # Delete any parsed data records
                        if hasattr(patient, 'parsed_data'):
                            patient.parsed_data.all().delete()
                        
                        # Now hard delete the patient
                        super(Patient, patient).delete()
                    except Exception as patient_delete_error:
                        logger.error(f"Error deleting soft-deleted patient {patient.mrn}: {patient_delete_error}")
                        # Continue with other patients
                
                messages.success(
                    request,
                    f"Successfully cleaned up {count} soft-deleted patient record(s). "
                    f"MRNs are now available for reuse."
                )
                
                return redirect('patients:list')
                
        except Exception as cleanup_error:
            logger.error(f"Error during soft-delete cleanup: {cleanup_error}")
            messages.error(request, "Error cleaning up soft-deleted patients. Please try again.")
            return redirect('patients:list')


# ============================================================================
# Patient Merge Views
# ============================================================================

@method_decorator([admin_required, has_permission('patients.view_patient')], name='dispatch')
class FindDuplicatePatientsView(LoginRequiredMixin, TemplateView):
    """
    Find and display potential duplicate patient records.
    """
    template_name = 'patients/find_duplicates.html'
    
    def get_context_data(self, **kwargs):
        """
        Find potential duplicate patients.
        
        Returns:
            dict: Context with duplicate candidates
        """
        context = super().get_context_data(**kwargs)
        
        try:
            duplicates = self.find_potential_duplicates()
            context['duplicate_groups'] = duplicates
            context['total_duplicates'] = sum(len(group) for group in duplicates)
            
        except (DatabaseError, OperationalError) as dup_error:
            logger.error(f"Error finding duplicate patients: {dup_error}")
            context['duplicate_groups'] = []
            context['total_duplicates'] = 0
        
        return context
    
    def find_potential_duplicates(self):
        """
        Find potential duplicate patients based on name and DOB similarity.
        
        Returns:
            list: Groups of potential duplicates
        """
        patients = Patient.objects.all().order_by('last_name', 'first_name')
        duplicate_groups = []
        processed_ids = set()
        
        for patient in patients:
            if patient.id in processed_ids:
                continue
            
            similar_patients = self.find_similar_patients(patient, patients, processed_ids)
            
            if similar_patients:
                duplicate_groups.append(similar_patients)
                for similar_patient in similar_patients:
                    processed_ids.add(similar_patient.id)
        
        return duplicate_groups
    
    def find_similar_patients(self, target_patient, all_patients, processed_ids):
        """
        Find patients similar to the target patient.
        
        Args:
            target_patient: Patient to find duplicates for
            all_patients: All patients to search through
            processed_ids: IDs already processed
            
        Returns:
            list: Similar patients (including target if matches found)
        """
        similar_patients = [target_patient]
        
        for patient in all_patients:
            if patient.id == target_patient.id or patient.id in processed_ids:
                continue
            
            # Check name similarity
            name_similarity = self.calculate_name_similarity(target_patient, patient)
            
            # Check if same DOB (using helper method for encrypted date field)
            same_dob = target_patient.get_date_of_birth() == patient.get_date_of_birth()
            
            # Consider as duplicate if high name similarity and same DOB
            if name_similarity > 0.8 and same_dob:
                similar_patients.append(patient)
        
        # Only return if we found actual duplicates
        return similar_patients if len(similar_patients) > 1 else []
    
    def calculate_name_similarity(self, patient1, patient2):
        """
        Calculate similarity score between two patients' names.
        
        Args:
            patient1: First patient
            patient2: Second patient
            
        Returns:
            float: Similarity score (0.0 to 1.0)
        """
        name1 = f"{patient1.first_name.lower()} {patient1.last_name.lower()}"
        name2 = f"{patient2.first_name.lower()} {patient2.last_name.lower()}"
        
        return SequenceMatcher(None, name1, name2).ratio()


@method_decorator([admin_required, has_permission('patients.merge_patients')], name='dispatch')
class PatientMergeListView(LoginRequiredMixin, TemplateView):
    """
    List view for selecting patients to merge.
    """
    template_name = 'patients/merge_list.html'
    
    def get_context_data(self, **kwargs):
        """
        Add patients list for merge selection.
        
        Returns:
            dict: Context with patients
        """
        context = super().get_context_data(**kwargs)
        
        try:
            # Get search parameters
            search_query = self.request.GET.get('q', '')
            
            patients = Patient.objects.all()
            
            if search_query:
                # Use search-optimized fields for efficient searching
                search_lower = search_query.lower()
                patients = patients.filter(
                    Q(first_name_search__icontains=search_lower) |
                    Q(last_name_search__icontains=search_lower) |
                    Q(mrn__icontains=search_query)
                )
            
            context['patients'] = patients.order_by('last_name', 'first_name')[:50]  # Limit results
            context['search_query'] = search_query
            
        except (DatabaseError, OperationalError) as merge_error:
            logger.error(f"Error loading patients for merge: {merge_error}")
            context['patients'] = Patient.objects.none()
            context['search_query'] = ''
        
        return context


@method_decorator([admin_required, has_permission('patients.merge_patients')], name='dispatch')
class PatientMergeView(LoginRequiredMixin, TemplateView):
    """
    Merge two patient records.
    """
    template_name = 'patients/merge_confirm.html'
    
    def get_context_data(self, **kwargs):
        """
        Add source and target patients to context.
        
        Returns:
            dict: Context with patients to merge
        """
        context = super().get_context_data(**kwargs)
        
        try:
            source_patient = get_object_or_404(Patient, pk=kwargs['source_pk'])
            target_patient = get_object_or_404(Patient, pk=kwargs['target_pk'])
            
            context['source_patient'] = source_patient
            context['target_patient'] = target_patient
            
            # Compare patients
            context['comparison'] = self.compare_patients(source_patient, target_patient)
            
        except (DatabaseError, OperationalError) as merge_context_error:
            logger.error(f"Error loading merge context: {merge_context_error}")
            raise Http404("Unable to load patient data for merge")
        
        return context
    
    def post(self, request, source_pk, target_pk):
        """
        Perform the patient merge operation.
        
        Args:
            request: HTTP request
            source_pk: Source patient UUID (will be merged into target)
            target_pk: Target patient UUID (will receive merged data)
            
        Returns:
            HttpResponse: Redirect to target patient
        """
        try:
            with transaction.atomic():
                source_patient = get_object_or_404(Patient, pk=source_pk)
                target_patient = get_object_or_404(Patient, pk=target_pk)
                
                # Merge FHIR data
                self.merge_fhir_data(source_patient, target_patient)
                
                # Move patient history
                self.move_patient_history(source_patient, target_patient)
                
                # Create merge history record
                PatientHistory.objects.create(
                    patient=target_patient,
                    action='patient_merged',
                    changed_by=request.user,
                    notes=f'Patient {source_patient.mrn} merged into {target_patient.mrn} by {request.user.get_full_name()}'
                )
                
                # Soft delete source patient
                source_patient.delete()
                
                messages.success(
                    request,
                    f'Patient {source_patient.first_name} {source_patient.last_name} '
                    f'(MRN: {source_patient.mrn}) has been successfully merged into '
                    f'{target_patient.first_name} {target_patient.last_name} '
                    f'(MRN: {target_patient.mrn}).'
                )
                
                return redirect('patients:detail', pk=target_patient.pk)
                
        except Exception as merge_error:
            logger.error(f"Error merging patients {source_pk} -> {target_pk}: {merge_error}")
            messages.error(request, "There was an error merging the patient records.")
            return redirect('patients:merge-list')
    
    def compare_patients(self, source, target):
        """
        Compare two patients for merge review.
        
        Args:
            source: Source patient
            target: Target patient
            
        Returns:
            dict: Comparison data
        """
        return {
            'names_match': (source.first_name.lower() == target.first_name.lower() and 
                          source.last_name.lower() == target.last_name.lower()),
            'dob_match': source.get_date_of_birth() == target.get_date_of_birth(),
            'gender_match': source.gender == target.gender,
            'source_fhir_count': len(source.cumulative_fhir_json) if source.cumulative_fhir_json else 0,
            'target_fhir_count': len(target.cumulative_fhir_json) if target.cumulative_fhir_json else 0,
            'source_history_count': source.history_records.count(),
            'target_history_count': target.history_records.count()
        }
    
    def merge_fhir_data(self, source_patient, target_patient):
        """
        Merge FHIR data from source into target patient.
        
        Args:
            source_patient: Patient to merge from
            target_patient: Patient to merge into
        """
        if not source_patient.cumulative_fhir_json:
            return
        
        target_fhir = target_patient.cumulative_fhir_json or {}
        
        for resource_type, resources in source_patient.cumulative_fhir_json.items():
            if resource_type not in target_fhir:
                target_fhir[resource_type] = []
            
            if isinstance(resources, list):
                target_fhir[resource_type].extend(resources)
            else:
                target_fhir[resource_type].append(resources)
        
        target_patient.cumulative_fhir_json = target_fhir
        target_patient.save()
    
    def move_patient_history(self, source_patient, target_patient):
        """
        Move patient history from source to target patient.
        
        Args:
            source_patient: Patient to move history from
            target_patient: Patient to move history to
        """
        PatientHistory.objects.filter(
            patient=source_patient
        ).update(patient=target_patient)
