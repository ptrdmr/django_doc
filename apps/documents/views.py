"""
Document upload and processing views.
"""
import logging
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import CreateView, ListView, DetailView, View
from django.urls import reverse_lazy
from django.contrib import messages
from django.db import IntegrityError, DatabaseError, OperationalError
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.template.loader import render_to_string

from .models import Document, ParsedData
from .forms import DocumentUploadForm
from apps.patients.models import Patient
from apps.providers.models import Provider
from apps.accounts.decorators import has_permission, provider_required, admin_required
from django.utils.decorators import method_decorator

logger = logging.getLogger(__name__)


@method_decorator([provider_required, has_permission('documents.add_document')], name='dispatch')
class DocumentUploadView(LoginRequiredMixin, CreateView):
    """
    Handle document upload with comprehensive validation and error handling.
    
    Features:
    - PDF file validation with user-friendly error messages
    - Patient and provider association
    - Duplicate detection
    - File size validation
    - Professional medical UI
    - Proper error handling and user feedback
    """
    model = Document
    form_class = DocumentUploadForm
    template_name = 'documents/upload.html'
    success_url = reverse_lazy('documents:upload-success')
    
    def get_context_data(self, **kwargs):
        """
        Add additional context for the upload template.
        
        Returns:
            dict: Enhanced context data
        """
        context = super().get_context_data(**kwargs)
        
        try:
            # Add patient and provider counts for UI display
            context.update({
                'patient_count': Patient.objects.count(),
                'provider_count': Provider.objects.count(),
                'recent_uploads': self.get_recent_uploads(),
                'upload_stats': self.get_upload_statistics(),
            })
        except (DatabaseError, OperationalError) as db_error:
            logger.error(f"Database error loading upload context: {db_error}")
            context.update({
                'patient_count': 0,
                'provider_count': 0,
                'recent_uploads': [],
                'upload_stats': {},
            })
        
        return context
    
    def get_recent_uploads(self):
        """
        Get recent uploads for display.
        
        Returns:
            QuerySet: Recent document uploads
        """
        try:
            return Document.objects.select_related('patient').order_by('-uploaded_at')[:5]
        except (DatabaseError, OperationalError) as db_error:
            logger.error(f"Error loading recent uploads: {db_error}")
            return Document.objects.none()
    
    def get_upload_statistics(self):
        """
        Get upload statistics for dashboard display.
        
        Returns:
            dict: Upload statistics
        """
        try:
            total_docs = Document.objects.count()
            pending_docs = Document.objects.filter(status='pending').count()
            completed_docs = Document.objects.filter(status='completed').count()
            failed_docs = Document.objects.filter(status='failed').count()
            
            return {
                'total': total_docs,
                'pending': pending_docs,
                'completed': completed_docs,
                'failed': failed_docs,
                'success_rate': round((completed_docs / total_docs * 100) if total_docs > 0 else 0, 1)
            }
        except (DatabaseError, OperationalError) as db_error:
            logger.error(f"Error calculating upload statistics: {db_error}")
            return {
                'total': 0,
                'pending': 0,
                'completed': 0,
                'failed': 0,
                'success_rate': 0
            }
    
    def form_valid(self, form):
        """
        Process valid form submission with proper error handling.
        
        Args:
            form: Validated DocumentUploadForm instance
            
        Returns:
            HttpResponse: Success response or error handling
        """
        try:
            # Set the created_by field to current user
            form.instance.created_by = self.request.user
            
            # Save the document
            response = super().form_valid(form)
            
            # Log successful upload
            logger.info(
                f"Document uploaded successfully: {self.object.filename} "
                f"by user {self.request.user.id} for patient {self.object.patient.id}"
            )
            
            # Show success message
            messages.success(
                self.request,
                f"Document '{self.object.filename}' uploaded successfully for "
                f"patient {self.object.patient.first_name} {self.object.patient.last_name}. "
                f"Processing will begin shortly."
            )
            
            # Trigger async PDF processing
            from .tasks import process_document_async
            process_document_async.delay(self.object.id)
            
            return response
            
        except IntegrityError as integrity_error:
            logger.error(f"Database integrity error during upload: {integrity_error}")
            messages.error(
                self.request,
                "There was a database error while uploading your document. "
                "Please try again or contact support if the problem persists."
            )
            return self.form_invalid(form)
            
        except (DatabaseError, OperationalError) as db_error:
            logger.error(f"Database error during upload: {db_error}")
            messages.error(
                self.request,
                "There was a database connection error. Please try again in a moment."
            )
            return self.form_invalid(form)
            
        except Exception as unexpected_error:
            logger.error(f"Unexpected error during upload: {unexpected_error}")
            messages.error(
                self.request,
                "An unexpected error occurred while uploading your document. "
                "Please try again or contact support."
            )
            return self.form_invalid(form)
    
    def form_invalid(self, form):
        """
        Handle invalid form submission with helpful error messages.
        
        Args:
            form: Invalid DocumentUploadForm instance
            
        Returns:
            HttpResponse: Form with error messages
        """
        logger.warning(f"Invalid form submission: {form.errors}")
        
        # Show general error message
        messages.error(
            self.request,
            "There were errors with your document upload. Please check the form and try again."
        )
        
        return super().form_invalid(form)


@method_decorator([provider_required, has_permission('documents.view_document')], name='dispatch')
class DocumentUploadSuccessView(LoginRequiredMixin, DetailView):
    """
    Display upload success page with document details.
    """
    model = Document
    template_name = 'documents/upload_success.html'
    context_object_name = 'document'
    
    def get_object(self):
        """
        Get the most recently uploaded document by this user.
        
        Returns:
            Document: Most recent document upload
        """
        try:
            return Document.objects.filter(
                created_by=self.request.user
            ).order_by('-uploaded_at').first()
        except (DatabaseError, OperationalError) as db_error:
            logger.error(f"Error loading uploaded document: {db_error}")
            return None
    
    def get_context_data(self, **kwargs):
        """
        Add additional context for success page.
        
        Returns:
            dict: Enhanced context data
        """
        context = super().get_context_data(**kwargs)
        
        if self.object:
            context.update({
                'processing_info': {
                    'expected_duration': '2-5 minutes',
                    'next_steps': 'AI processing will extract medical information',
                    'notification': 'You will be notified when processing is complete'
                }
            })
        
        return context


@method_decorator(has_permission('documents.view_document'), name='dispatch')
class DocumentListView(LoginRequiredMixin, ListView):
    """
    Display list of uploaded documents with search and filtering.
    """
    model = Document
    template_name = 'documents/document_list.html'
    context_object_name = 'documents'
    paginate_by = 20
    
    def get_queryset(self):
        """
        Get filtered and ordered document queryset.
        
        Returns:
            QuerySet: Filtered document queryset
        """
        try:
            queryset = Document.objects.select_related('patient', 'created_by').prefetch_related('providers')
            
            # Filter by status if provided
            status = self.request.GET.get('status')
            if status and status in ['pending', 'processing', 'completed', 'failed']:
                queryset = queryset.filter(status=status)
            
            # Filter by patient if provided
            patient_id = self.request.GET.get('patient')
            if patient_id:
                try:
                    queryset = queryset.filter(patient__id=patient_id)
                except (ValueError, ValidationError):
                    pass  # Invalid patient ID, ignore filter
            
            # Search by filename
            search_query = self.request.GET.get('q', '').strip()
            if search_query:
                queryset = queryset.filter(filename__icontains=search_query)
            
            return queryset.order_by('-uploaded_at')
            
        except (DatabaseError, OperationalError) as db_error:
            logger.error(f"Database error in document list view: {db_error}")
            messages.error(self.request, "There was an error loading documents. Please try again.")
            return Document.objects.none()
    
    def get_context_data(self, **kwargs):
        """
        Add search and filter context.
        
        Returns:
            dict: Enhanced context data
        """
        context = super().get_context_data(**kwargs)
        
        context.update({
            'search_query': self.request.GET.get('q', ''),
            'status_filter': self.request.GET.get('status', ''),
            'patient_filter': self.request.GET.get('patient', ''),
            'status_choices': Document.STATUS_CHOICES,
            'patients': Patient.objects.order_by('last_name', 'first_name'),
        })
        
        return context


@method_decorator(has_permission('documents.view_document'), name='dispatch')
class DocumentDetailView(LoginRequiredMixin, DetailView):
    """
    Display detailed information about a specific document.
    """
    model = Document
    template_name = 'documents/document_detail.html'
    context_object_name = 'document'
    
    def get_queryset(self):
        """
        Get document with related data.
        
        Returns:
            QuerySet: Document queryset with related data
        """
        return Document.objects.select_related('patient', 'created_by').prefetch_related('providers')
    
    def get_context_data(self, **kwargs):
        """
        Add additional context for document detail.
        
        Returns:
            dict: Enhanced context data
        """
        context = super().get_context_data(**kwargs)
        
        try:
            # Add processing information
            context.update({
                'processing_duration': self.object.get_processing_duration(),
                'can_retry': self.object.can_retry_processing(),
                'file_size_mb': round(self.object.file_size / (1024 * 1024), 1) if self.object.file_size else 0,
            })
            
            # Add parsed data if available
            if hasattr(self.object, 'parsed_data'):
                context['parsed_data'] = self.object.parsed_data
            
        except Exception as context_error:
            logger.error(f"Error building document detail context: {context_error}")
        
        return context


@method_decorator([provider_required, has_permission('documents.change_document')], name='dispatch')
class DocumentRetryView(LoginRequiredMixin, View):
    """
    Handle document processing retry with enhanced error handling.
    """
    http_method_names = ['post']
    
    def post(self, request, *args, **kwargs):
        """
        Retry document processing with comprehensive error handling.
        
        Args:
            request: HTTP request
            
        Returns:
            HttpResponse: JSON response for AJAX or redirect for regular form
        """
        document_id = kwargs.get('pk')
        document = get_object_or_404(
            Document.objects.filter(created_by=request.user),
            pk=document_id
        )
        
        try:
            if document.can_retry_processing():
                # Reset status and increment attempts
                document.status = 'pending'
                document.error_message = ''
                document.processing_started_at = None
                document.processing_completed_at = None
                document.save()
                
                # Trigger async PDF processing
                from .tasks import process_document_async
                process_document_async.delay(document.id)
                
                logger.info(f"Document {document.id} queued for retry by user {request.user.id}")
                
                success_message = f"Document '{document.filename}' has been queued for reprocessing."
                
                # Return JSON response for AJAX requests
                if request.headers.get('Content-Type') == 'application/json':
                    return JsonResponse({
                        'success': True,
                        'message': success_message,
                        'status': 'pending'
                    })
                else:
                    messages.success(request, success_message)
                    return redirect('documents:detail', pk=document.pk)
                
            else:
                error_message = "This document cannot be retried. Maximum retry attempts reached."
                
                if request.headers.get('Content-Type') == 'application/json':
                    return JsonResponse({
                        'success': False,
                        'message': error_message
                    })
                else:
                    messages.error(request, error_message)
                    return redirect('documents:detail', pk=document.pk)
            
        except Exception as retry_error:
            logger.error(f"Error retrying document processing: {retry_error}")
            error_message = "There was an error retrying the document processing. Please try again."
            
            if request.headers.get('Content-Type') == 'application/json':
                return JsonResponse({
                    'success': False,
                    'message': error_message
                })
            else:
                messages.error(request, error_message)
                return redirect('documents:detail', pk=document.pk)


@method_decorator(has_permission('documents.view_document'), name='dispatch')
class ProcessingStatusAPIView(LoginRequiredMixin, View):
    """
    API endpoint for real-time processing status monitoring.
    """
    
    def get(self, request):
        """
        Get current processing status for documents.
        
        Returns:
            JsonResponse: Processing status data
        """
        try:
            # Get processing documents for current user
            processing_docs = Document.objects.filter(
                created_by=request.user,
                status__in=['processing', 'pending']
            ).select_related('patient').order_by('-uploaded_at')[:10]
            
            # Get recently completed or failed documents (last 5 minutes)
            recent_cutoff = timezone.now() - timezone.timedelta(minutes=5)
            recent_docs = Document.objects.filter(
                created_by=request.user,
                status__in=['completed', 'failed'],
                processed_at__gte=recent_cutoff
            ).select_related('patient').order_by('-processed_at')[:5]
            
            processing_data = []
            for doc in processing_docs:
                processing_data.append({
                    'id': doc.id,
                    'filename': doc.filename,
                    'status': doc.status,
                    'status_display': doc.get_status_display(),
                    'patient_name': f"{doc.patient.first_name} {doc.patient.last_name}",
                    'uploaded_at': doc.uploaded_at.isoformat(),
                })
            
            recent_data = []
            for doc in recent_docs:
                recent_data.append({
                    'id': doc.id,
                    'filename': doc.filename,
                    'status': doc.status,
                    'status_display': doc.get_status_display(),
                    'patient_name': f"{doc.patient.first_name} {doc.patient.last_name}",
                    'completed_at': doc.processing_completed_at.isoformat() if doc.processing_completed_at else None,
                })
            
            return JsonResponse({
                'success': True,
                'processing_documents': processing_data,
                'recent_documents': recent_data,
                'timestamp': timezone.now().isoformat()
            })
            
        except Exception as status_error:
            logger.error(f"Error getting processing status: {status_error}")
            return JsonResponse({
                'success': False,
                'error': 'Unable to fetch processing status'
            }, status=500)


@method_decorator(has_permission('documents.view_document'), name='dispatch')
class RecentUploadsAPIView(LoginRequiredMixin, View):
    """
    API endpoint for refreshing recent uploads list.
    """
    
    def get(self, request):
        """
        Get updated recent uploads HTML.
        
        Returns:
            HttpResponse: Rendered HTML for recent uploads
        """
        try:
            recent_uploads = Document.objects.filter(
                created_by=request.user
            ).select_related('patient').order_by('-uploaded_at')[:5]
            
            # Render just the upload items
            html = render_to_string(
                'documents/partials/recent_uploads_list.html',
                {'recent_uploads': recent_uploads}
            )
            
            return HttpResponse(html)
            
        except Exception as uploads_error:
            logger.error(f"Error getting recent uploads: {uploads_error}")
            return HttpResponse(
                '<div class="text-center py-4 text-red-600">Error loading uploads</div>'
            )


@method_decorator(has_permission('documents.view_document'), name='dispatch')
class ParsedDataAPIView(LoginRequiredMixin, View):
    """
    API endpoint for getting parsed data with snippet context.
    """
    
    def get(self, request, document_id):
        """
        Get parsed data with snippet context for a document.
        
        Returns:
            JsonResponse: Parsed data with snippet information
        """
        try:
            document = get_object_or_404(Document, id=document_id)
            
            # Check permissions - user must have access to this document
            if not request.user.has_perm('documents.view_document'):
                return JsonResponse({
                    'success': False,
                    'error': 'Permission denied'
                }, status=403)
            
            # Get parsed data with snippet information
            try:
                parsed_data = document.parsed_data
                
                # Format response with snippet data
                response_data = {
                    'id': parsed_data.id,
                    'document_id': document.id,
                    'extraction_json': parsed_data.extraction_json,
                    'source_snippets': parsed_data.source_snippets,
                    'fhir_delta_json': parsed_data.fhir_delta_json,
                    'extraction_confidence': parsed_data.extraction_confidence,
                    'ai_model_used': parsed_data.ai_model_used,
                    'processing_time_seconds': parsed_data.processing_time_seconds,
                    'is_approved': parsed_data.is_approved,
                    'is_merged': parsed_data.is_merged,
                    'reviewed_at': parsed_data.reviewed_at.isoformat() if parsed_data.reviewed_at else None,
                    'merged_at': parsed_data.merged_at.isoformat() if parsed_data.merged_at else None
                }
                
                return JsonResponse({
                    'success': True,
                    'data': response_data,
                    'snippet_stats': self._get_snippet_stats(parsed_data.source_snippets)
                })
                
            except ParsedData.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'No parsed data available for this document'
                }, status=404)
                
        except Exception as api_error:
            logger.error(f"Error getting parsed data for document {document_id}: {api_error}")
            return JsonResponse({
                'success': False,
                'error': 'Unable to fetch parsed data'
            }, status=500)
    
    def _get_snippet_stats(self, snippets_data: dict) -> dict:
        """
        Generate statistics about snippet data quality.
        
        Args:
            snippets_data: Source snippets data
            
        Returns:
            Statistics dictionary
        """
        from .snippet_utils import SnippetHelper
        return SnippetHelper.get_snippet_stats(snippets_data)


@method_decorator(has_permission('documents.view_document'), name='dispatch')
class DocumentPreviewAPIView(LoginRequiredMixin, View):
    """
    API endpoint for document preview functionality.
    """
    
    def get(self, request, pk):
        """
        Get document preview data.
        
        Args:
            request: HTTP request
            pk: Document primary key
            
        Returns:
            JsonResponse: Document preview data
        """
        try:
            document = get_object_or_404(
                Document.objects.filter(created_by=request.user),
                pk=pk
            )
            
            preview_data = {
                'id': document.id,
                'filename': document.filename,
                'status': document.status,
                'status_display': document.get_status_display(),
                'file_size': document.file_size,
                'file_size_display': f"{document.file_size / (1024 * 1024):.1f} MB" if document.file_size else "Unknown",
                'uploaded_at': document.uploaded_at.isoformat(),
                'patient': {
                    'name': f"{document.patient.first_name} {document.patient.last_name}",
                    'mrn': document.patient.mrn,
                },
                'providers': [
                    f"{p.first_name} {p.last_name}" 
                    for p in document.providers.all()
                ],
                'notes': document.notes,
                'original_text_preview': document.original_text[:500] + '...' if document.original_text and len(document.original_text) > 500 else document.original_text,
                'error_message': document.error_message,
                'processing_attempts': getattr(document, 'processing_attempts', 0),
                'can_retry': document.can_retry_processing() if hasattr(document, 'can_retry_processing') else False,
            }
            
            return JsonResponse({
                'success': True,
                'document': preview_data
            })
            
        except Exception as preview_error:
            logger.error(f"Error getting document preview: {preview_error}")
            return JsonResponse({
                'success': False,
                'error': 'Unable to load document preview'
            }, status=500)


@method_decorator(has_permission('documents.view_document'), name='dispatch')
class DocumentReviewView(LoginRequiredMixin, DetailView):
    """
    Snippet-based document review interface for reviewing extracted data.
    
    This view displays extracted data organized by category with source context
    snippets for efficient field-by-field review and approval.
    """
    model = Document
    template_name = 'documents/review.html'
    context_object_name = 'document'
    
    def get_queryset(self):
        """
        Filter documents to only those the user has access to.
        
        Returns:
            QuerySet: Filtered documents with optimized queries
        """
        return Document.objects.filter(
            created_by=self.request.user
        ).select_related('patient').prefetch_related('providers')
    
    def get_context_data(self, **kwargs):
        """
        Add organized snippet-based context for the review template.
        
        Returns:
            dict: Enhanced context data with categorized fields
        """
        from collections import defaultdict
        
        context = super().get_context_data(**kwargs)
        
        # Initialize empty context
        context.update({
            'categorized_data': {},
            'review_progress': 0,
            'missing_fields': [],
            'parsed_data': None
        })
        
        # Add parsed data for review if available
        try:
            parsed_data = self.object.parsed_data
            context['parsed_data'] = parsed_data
            
            if parsed_data and parsed_data.extraction_json:
                # Group data by category for organized display
                categorized_data = defaultdict(list)
                extraction_data = parsed_data.extraction_json
                source_snippets = parsed_data.source_snippets or {}
                
                # Handle different extraction_json formats
                if isinstance(extraction_data, dict):
                    # Convert dict format to list of fields
                    field_list = []
                    for key, value in extraction_data.items():
                        if isinstance(value, dict) and 'value' in value:
                            # Structured format with metadata
                            field_list.append({
                                'field_name': key,
                                'field_value': value.get('value', ''),
                                'confidence': value.get('confidence', 0.5),
                                'category': value.get('category', self._categorize_field(key)),
                                'fhir_path': value.get('fhir_path', ''),
                            })
                        else:
                            # Simple key-value format
                            field_list.append({
                                'field_name': key,
                                'field_value': str(value) if value is not None else '',
                                'confidence': 0.5,  # Default confidence
                                'category': self._categorize_field(key),
                                'fhir_path': '',
                            })
                elif isinstance(extraction_data, list):
                    # Already in list format
                    field_list = extraction_data
                else:
                    field_list = []
                
                # Process each field and organize by category
                total_fields = len(field_list)
                approved_fields = 0
                
                for field_data in field_list:
                    field_name = field_data.get('field_name', 'Unknown Field')
                    category = field_data.get('category', 'Other')
                    
                    # Get snippet for this field
                    snippet_text = source_snippets.get(field_name, '')
                    if not snippet_text and source_snippets:
                        # Try to find snippet by partial match
                        for snippet_key, snippet_value in source_snippets.items():
                            if field_name.lower() in snippet_key.lower() or snippet_key.lower() in field_name.lower():
                                snippet_text = snippet_value
                                break
                    
                    # Check if field is approved (for now, assume not approved)
                    is_approved = False  # TODO: Implement field-level approval tracking
                    if is_approved:
                        approved_fields += 1
                    
                    categorized_data[category].append({
                        'field_name': field_name,
                        'field_value': field_data.get('field_value', ''),
                        'confidence': field_data.get('confidence', 0.5),
                        'snippet': snippet_text,
                        'approved': is_approved,
                        'fhir_path': field_data.get('fhir_path', ''),
                        'id': f"{field_name}_{hash(str(field_data))}"  # Generate unique ID
                    })
                
                context['categorized_data'] = dict(categorized_data)
                context['review_progress'] = round((approved_fields / total_fields * 100) if total_fields > 0 else 0)
                context['review_stats'] = {
                    'total_fields': total_fields,
                    'approved_fields': approved_fields,
                    'pending_fields': total_fields - approved_fields,
                    'total_categories': len(categorized_data),
                    'categories_with_data': len([cat for cat, items in categorized_data.items() if items])
                }
                
                # Identify potentially missing fields
                context['missing_fields'] = self._identify_missing_fields(categorized_data)
            
        except Exception as e:
            logger.error(f"Error building review context for document {self.object.id}: {e}")
            # No parsed data available or error occurred
            context['parsed_data'] = None
        
        return context
    
    def _categorize_field(self, field_name):
        """
        Categorize a field based on its name.
        
        Args:
            field_name: Name of the field to categorize
            
        Returns:
            str: Category name
        """
        field_lower = field_name.lower()
        
        # Demographics
        if any(term in field_lower for term in ['name', 'age', 'birth', 'dob', 'gender', 'sex', 'address', 'phone', 'mrn']):
            return 'Demographics'
        
        # Medical History
        elif any(term in field_lower for term in ['diagnosis', 'condition', 'history', 'medical', 'procedure', 'surgery']):
            return 'Medical History'
        
        # Medications
        elif any(term in field_lower for term in ['medication', 'drug', 'prescription', 'dosage', 'dose']):
            return 'Medications'
        
        # Vitals
        elif any(term in field_lower for term in ['vital', 'blood pressure', 'bp', 'heart rate', 'temperature', 'weight', 'height']):
            return 'Vital Signs'
        
        # Laboratory
        elif any(term in field_lower for term in ['lab', 'test', 'result', 'level', 'count']):
            return 'Laboratory Results'
        
        # Provider Information
        elif any(term in field_lower for term in ['provider', 'doctor', 'physician', 'nurse']):
            return 'Provider Information'
        
        # Default category
        else:
            return 'Other'
    
    def _identify_missing_fields(self, categorized_data):
        """
        Identify potentially missing fields based on common medical document requirements.
        
        Args:
            categorized_data: Dictionary of categorized field data
            
        Returns:
            list: List of potentially missing field specifications
        """
        # Common required fields for medical documents
        required_fields = [
            {'name': 'Patient Name', 'category': 'Demographics'},
            {'name': 'Date of Birth', 'category': 'Demographics'},
            {'name': 'Medical Record Number', 'category': 'Demographics'},
            {'name': 'Primary Diagnosis', 'category': 'Medical History'},
            {'name': 'Current Medications', 'category': 'Medications'},
        ]
        
        missing_fields = []
        all_field_names = []
        
        # Collect all extracted field names
        for category_items in categorized_data.values():
            for item in category_items:
                all_field_names.append(item['field_name'].lower())
        
        # Check for missing required fields
        for required in required_fields:
            found = False
            for extracted_name in all_field_names:
                # Simple matching - could be enhanced with fuzzy matching
                if any(word in extracted_name for word in required['name'].lower().split()):
                    found = True
                    break
            
            if not found:
                missing_fields.append(required)
        
        return missing_fields
    
    def post(self, request, *args, **kwargs):
        """
        Handle document approval/rejection workflow.
        
        Args:
            request: HTTP POST request
            
        Returns:
            HttpResponse: Redirect or error response
        """
        self.object = self.get_object()
        
        # Check if document is in reviewable state
        if self.object.status != 'review':
            messages.error(request, "This document is not available for review.")
            return redirect('documents:detail', pk=self.object.pk)
        
        try:
            action = request.POST.get('action')
            
            if action == 'approve':
                return self.handle_approval(request)
            elif action == 'reject':
                return self.handle_rejection(request)
            elif action == 'request_changes':
                return self.handle_request_changes(request)
            else:
                messages.error(request, "Invalid action specified.")
                
        except Exception as workflow_error:
            logger.error(f"Error in document review workflow: {workflow_error}")
            messages.error(request, "An error occurred processing your request.")
        
        return redirect('documents:review', pk=self.object.pk)
    
    def handle_approval(self, request):
        """
        Handle document approval and merge data into patient record.
        
        Args:
            request: HTTP request
            
        Returns:
            HttpResponse: Redirect response
        """
        try:
            parsed_data = self.object.parsed_data
            
            # Mark parsed data as approved
            parsed_data.is_approved = True
            parsed_data.reviewed_by = request.user
            parsed_data.reviewed_at = timezone.now()
            parsed_data.save()
            
            # Update document status to completed
            self.object.status = 'completed'
            self.object.save()
            
            # Merge FHIR data to patient record immediately (synchronous)
            try:
                fhir_data = parsed_data.fhir_delta_json
                if fhir_data:
                    # Convert FHIR data to list format if needed
                    fhir_resources = []
                    if isinstance(fhir_data, dict):
                        if fhir_data.get('resourceType') == 'Bundle' and 'entry' in fhir_data:
                            fhir_resources = [entry['resource'] for entry in fhir_data['entry'] if 'resource' in entry]
                        else:
                            fhir_resources = [fhir_data]
                    elif isinstance(fhir_data, list):
                        fhir_resources = fhir_data
                    
                    # Merge directly to patient record
                    if fhir_resources:
                        success = self.object.patient.add_fhir_resources(fhir_resources, document_id=self.object.id)
                        
                        if success:
                            # Mark as merged
                            parsed_data.is_merged = True
                            parsed_data.merged_at = timezone.now()
                            parsed_data.save()
                            
                            logger.info(f"Successfully merged {len(fhir_resources)} FHIR resources from document {self.object.id} to patient {self.object.patient.mrn}")
                        else:
                            logger.error(f"Failed to merge FHIR resources from document {self.object.id}")
                            
            except Exception as merge_error:
                logger.error(f"Error merging FHIR data for document {self.object.id}: {merge_error}")
                # Don't fail the approval, just log the error
            
            messages.success(
                request,
                f"Document '{self.object.filename}' approved successfully. "
                f"Data is being merged into {self.object.patient.first_name} {self.object.patient.last_name}'s record."
            )
            
            logger.info(f"Document {self.object.id} approved by user {request.user.id}")
            
        except Exception as approval_error:
            logger.error(f"Error approving document {self.object.id}: {approval_error}")
            messages.error(request, "Failed to approve document. Please try again.")
            return redirect('documents:review', pk=self.object.pk)
        
        return redirect('documents:detail', pk=self.object.pk)
    
    def handle_rejection(self, request):
        """
        Handle document rejection.
        
        Args:
            request: HTTP request
            
        Returns:
            HttpResponse: Redirect response
        """
        try:
            notes = request.POST.get('rejection_notes', '').strip()
            
            parsed_data = self.object.parsed_data
            parsed_data.is_approved = False
            parsed_data.reviewed_by = request.user
            parsed_data.reviewed_at = timezone.now()
            parsed_data.review_notes = notes
            parsed_data.save()
            
            # Update document status to failed (rejected)
            self.object.status = 'failed'
            self.object.error_message = f"Rejected by {request.user.get_full_name()}: {notes}"
            self.object.save()
            
            messages.warning(
                request,
                f"Document '{self.object.filename}' has been rejected. "
                f"The extracted data will not be added to the patient record."
            )
            
            logger.info(f"Document {self.object.id} rejected by user {request.user.id}")
            
        except Exception as rejection_error:
            logger.error(f"Error rejecting document {self.object.id}: {rejection_error}")
            messages.error(request, "Failed to reject document. Please try again.")
            return redirect('documents:review', pk=self.object.pk)
        
        return redirect('documents:detail', pk=self.object.pk)
    
    def handle_request_changes(self, request):
        """
        Handle request for changes to extracted data.
        
        Args:
            request: HTTP request
            
        Returns:
            HttpResponse: Redirect response
        """
        try:
            notes = request.POST.get('change_notes', '').strip()
            
            parsed_data = self.object.parsed_data
            parsed_data.reviewed_by = request.user
            parsed_data.reviewed_at = timezone.now()
            parsed_data.review_notes = notes
            parsed_data.save()
            
            # Keep document in review status for further editing
            # In future subtasks, this would trigger re-processing or manual editing
            
            messages.info(
                request,
                f"Change request submitted for '{self.object.filename}'. "
                f"The document remains in review status."
            )
            
            logger.info(f"Changes requested for document {self.object.id} by user {request.user.id}")
            
        except Exception as change_error:
            logger.error(f"Error requesting changes for document {self.object.id}: {change_error}")
            messages.error(request, "Failed to submit change request. Please try again.")
        
        return redirect('documents:review', pk=self.object.pk)


@method_decorator([admin_required], name='dispatch')  
class MigrateFHIRDataView(LoginRequiredMixin, View):
    """
    Simple view to migrate FHIR data from old completed documents.
    Only accessible to admins.
    """
    
    def get(self, request):
        """Show migration status and options."""
        from datetime import timedelta
        from .models import ParsedData
        
        # Get recent completed documents that might need migration
        recent_cutoff = timezone.now() - timedelta(hours=24)
        completed_docs = Document.objects.filter(
            status='completed',
            uploaded_at__gte=recent_cutoff
        ).select_related('patient')
        
        migration_candidates = []
        for doc in completed_docs:
            try:
                parsed_data = doc.parsed_data
                if not parsed_data.is_merged and parsed_data.fhir_delta_json:
                    migration_candidates.append({
                        'doc': doc,
                        'parsed_data': parsed_data,
                        'fhir_count': len(parsed_data.fhir_delta_json) if isinstance(parsed_data.fhir_delta_json, list) else 1
                    })
            except ParsedData.DoesNotExist:
                continue
        
        return render(request, 'documents/migrate_fhir.html', {
            'migration_candidates': migration_candidates,
            'total_candidates': len(migration_candidates)
        })
    
    def post(self, request):
        """Trigger FHIR data migration for selected documents."""
        from .tasks import merge_to_patient_record
        from .models import ParsedData
        
        doc_ids = request.POST.getlist('document_ids')
        if not doc_ids:
            messages.error(request, "No documents selected for migration.")
            return redirect('documents:migrate-fhir')
        
        success_count = 0
        error_count = 0
        
        for doc_id in doc_ids:
            try:
                document = Document.objects.get(id=doc_id, status='completed')
                parsed_data = document.parsed_data
                
                # Auto-approve if not already approved
                if not parsed_data.is_approved:
                    parsed_data.is_approved = True
                    parsed_data.reviewed_by = request.user
                    parsed_data.reviewed_at = timezone.now()
                    parsed_data.save()
                
                # Merge FHIR data immediately (synchronous)
                if not parsed_data.is_merged and parsed_data.fhir_delta_json:
                    try:
                        fhir_data = parsed_data.fhir_delta_json
                        
                        # Convert to list format if needed
                        fhir_resources = []
                        if isinstance(fhir_data, dict):
                            if fhir_data.get('resourceType') == 'Bundle' and 'entry' in fhir_data:
                                fhir_resources = [entry['resource'] for entry in fhir_data['entry'] if 'resource' in entry]
                            else:
                                fhir_resources = [fhir_data]
                        elif isinstance(fhir_data, list):
                            fhir_resources = fhir_data
                        
                        # Merge to patient record
                        if fhir_resources:
                            success = document.patient.add_fhir_resources(fhir_resources, document_id=document.id)
                            
                            if success:
                                parsed_data.is_merged = True
                                parsed_data.merged_at = timezone.now()
                                parsed_data.save()
                                
                                logger.info(f"Admin migration: merged {len(fhir_resources)} FHIR resources from document {doc_id} to patient {document.patient.mrn}")
                                success_count += 1
                            else:
                                logger.error(f"Failed to merge FHIR resources from document {doc_id}")
                                error_count += 1
                        else:
                            logger.warning(f"No valid FHIR resources found in document {doc_id}")
                            error_count += 1
                            
                    except Exception as merge_error:
                        logger.error(f"Error during migration for document {doc_id}: {merge_error}")
                        error_count += 1
                else:
                    logger.info(f"Document {doc_id} already merged, skipping")
                    
            except (Document.DoesNotExist, ParsedData.DoesNotExist) as e:
                logger.error(f"Error migrating document {doc_id}: {e}")
                error_count += 1
        
        if success_count > 0:
            messages.success(request, f"Successfully started migration for {success_count} documents.")
        if error_count > 0:
            messages.error(request, f"Failed to migrate {error_count} documents.")
        
        return redirect('documents:migrate-fhir')