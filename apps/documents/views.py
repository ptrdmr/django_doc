"""
Document upload and processing views.
"""
import logging
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import CreateView, ListView, DetailView, View
from django.urls import reverse_lazy
from django.contrib import messages
from django.db import IntegrityError, DatabaseError, OperationalError, transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse, Http404
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .models import Document, ParsedData
from .forms import DocumentUploadForm
from apps.patients.models import Patient
from apps.providers.models import Provider
from apps.accounts.decorators import has_permission, provider_required, admin_required
from django.utils.decorators import method_decorator
from apps.core.utils import log_user_activity, ActivityTypes

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
            
            # Log user activity for dashboard
            log_user_activity(
                user=self.request.user,
                activity_type=ActivityTypes.DOCUMENT_UPLOAD,
                description=f"Uploaded {self.object.filename} for {self.object.patient.first_name} {self.object.patient.last_name}",
                request=self.request,
                related_object_type='document',
                related_object_id=self.object.id
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
            
            # Add debug flag for development-only features
            from django.conf import settings
            context['debug'] = settings.DEBUG
            
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
                status__in=['completed', 'failed', 'review'],
                processed_at__gte=recent_cutoff
            ).select_related('patient').order_by('-processed_at')[:5]
            
            processing_data = []
            for doc in processing_docs:
                processing_data.append({
                    'id': doc.id,
                    'filename': doc.filename,
                    'status': doc.status,
                    'status_display': doc.get_status_display(),
                    'processing_message': doc.processing_message,
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
                    'processing_message': doc.processing_message,
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
    
    def post(self, request, *args, **kwargs):
        """Handle review completion actions."""
        from django.utils import timezone
        from django.contrib import messages
        from django.shortcuts import redirect
        
        document = self.get_object()
        action = request.POST.get('action')
        notes = request.POST.get('notes', '')
        
        if action == 'approve':
            # Complete the review and approve the document
            document.status = 'completed'
            document.reviewed_by = request.user
            document.reviewed_at = timezone.now()
            document.save()
            
            # Clear session approval data since review is complete
            session_keys_to_remove = [key for key in request.session.keys() 
                                    if key.startswith(f'approved_field_{document.id}_')]
            for key in session_keys_to_remove:
                del request.session[key]
            request.session.modified = True
            
            messages.success(request, 'Document review completed and approved successfully.')
            return redirect('documents:detail', pk=document.pk)
            
        elif action == 'request_changes':
            # Request changes to the document
            document.status = 'processing'  # Send back for reprocessing
            document.save()
            
            # Log the change request
            logger.info(f"Changes requested for document {document.id} by user {request.user.id}: {notes}")
            
            messages.info(request, f'Changes requested for document. Notes: {notes}')
            return redirect('documents:list')
            
        elif action == 'reject':
            # Reject the document
            document.status = 'failed'
            document.save()
            
            # Log the rejection
            logger.info(f"Document {document.id} rejected by user {request.user.id}: {notes}")
            
            messages.warning(request, f'Document rejected. Reason: {notes}')
            return redirect('documents:list')
        
        # If no valid action, fall back to GET behavior
        return self.get(request, *args, **kwargs)
    
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
        
        # Check for new structured data first, then fall back to legacy
        try:
            has_structured_data = self.object.has_structured_data()
            force_review = self.request.GET.get('force_review') == '1'
            
            if has_structured_data or force_review:
                # context['parsed_data'] will be set to the actual object below if it exists
                # If forcing review without data, we'll set a dummy object or handle gracefully
                
                if has_structured_data:
                    # Use new structured data pipeline
                    field_list = self._convert_structured_data_to_fields()
                    logger.info(f"Using structured data for document {self.object.id} review interface")
                else:
                    # Fallback to legacy data or debug mode
                    field_list = self._get_legacy_field_data(force_review)
                    logger.info(f"Using legacy data for document {self.object.id} review interface")
                
                # Process fields and organize by category
                categorized_data = defaultdict(list)
                total_fields = len(field_list)
                approved_fields = 0
                
                # Get ParsedData for clinical date information
                # Use hasattr to check if ParsedData exists before accessing it
                parsed_data_id = None
                clinical_date = None
                date_source = None
                date_status = None
                
                if hasattr(self.object, 'parsed_data'):
                    try:
                        parsed_data = self.object.parsed_data
                        context['parsed_data'] = parsed_data  # Set the actual object in context
                        parsed_data_id = parsed_data.id
                        clinical_date = parsed_data.clinical_date
                        date_source = parsed_data.date_source
                        date_status = parsed_data.date_status
                    except Exception as e:
                        logger.warning(f"Could not get ParsedData for document {self.object.id}: {e}")
                        context['parsed_data'] = True # Fallback for legacy behavior if object access fails
                elif force_review:
                     context['parsed_data'] = True # Force review mode without object

                
                for field_data in field_list:
                    # Check if field is approved in session
                    field_id = field_data.get('id', f"{field_data['field_name']}_{hash(str(field_data))}")
                    field_key = f"approved_field_{self.object.id}_{field_data['field_name']}_{field_id}"
                    is_approved = self.request.session.get(field_key, False)
                    if is_approved:
                        approved_fields += 1
                    
                    field_data['approved'] = is_approved
                    field_data['id'] = field_id
                    field_data['category_slug'] = field_data['category'].lower().replace(' ', '-').replace('_', '-')
                    
                    # Add parsed_data_id if not already set (for per-resource date management)
                    if 'parsed_data_id' not in field_data:
                        field_data['parsed_data_id'] = parsed_data_id
                    
                    # Note: clinical_date, date_source, and date_status are now set per-resource
                    # during field creation (Task 35 fix for per-resource dates)
                    
                    categorized_data[field_data['category']].append(field_data)
                
                # Group multi-property resources (like medications) by resource_index
                grouped_categorized_data = {}
                for category, items in categorized_data.items():
                    grouped_items = self._group_multi_property_items(items)
                    grouped_categorized_data[category] = grouped_items
                
                context['categorized_data'] = grouped_categorized_data
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
        
        # Add Patient Data Comparison for validation
        try:
            if context.get('parsed_data'):
                from .services import PatientDataComparisonService
                comparison_service = PatientDataComparisonService()
                comparison = comparison_service.compare_patient_data(self.object, self.object.patient)
                context['comparison'] = comparison
                
                # Add comparison helpers
                context['has_discrepancies'] = comparison.has_pending_discrepancies()
                context['comparison_summary'] = comparison.get_discrepancy_summary()
        except Exception as comparison_error:
            logger.error(f"Error creating patient data comparison: {comparison_error}")
            context['comparison'] = None
        
        # Add today's date for clinical date input max value (Task 35.5)
        from django.utils import timezone
        context['today'] = timezone.now().date()
        
        return context
    
    def _convert_structured_data_to_fields(self):
        """
        Convert new StructuredMedicalExtraction data to field format for UI display.
        
        Returns:
            list: List of field dictionaries for UI display
        """
        field_list = []
        
        try:
            from .services.ai_extraction import StructuredMedicalExtraction
            
            # Get structured data from document
            structured_data_dict = self.object.get_structured_medical_data()
            if not structured_data_dict:
                return []
            
            # Convert dict to Pydantic model for proper handling
            structured_data = StructuredMedicalExtraction.model_validate(structured_data_dict)
            
            # Process each resource type
            
            # 1. Conditions/Diagnoses
            for i, condition in enumerate(structured_data.conditions):
                # Get date metadata if it exists
                condition_dict = structured_data_dict.get('conditions', [])[i] if i < len(structured_data_dict.get('conditions', [])) else {}
                date_metadata = condition_dict.get('date_metadata', {})
                
                field_list.append({
                    'field_name': f'Condition {i+1}',
                    'field_value': condition.name,
                    'confidence': condition.confidence,
                    'category': 'Conditions',
                    'snippet': condition.source.text if condition.source else '',
                    'resource_type': 'condition',
                    'resource_index': i,
                    'field_path': f'conditions.{i}.name',
                    'clinical_date': condition.onset_date,
                    'date_source': date_metadata.get('source', 'extracted' if condition.onset_date else None),
                    'date_status': 'verified' if date_metadata.get('verified') else 'pending',
                })
                
                # Add onset date as sub-property if available
                if condition.onset_date:
                    field_list.append({
                        'field_name': f'Condition {i+1} Onset Date',
                        'field_value': condition.onset_date,
                        'confidence': condition.confidence * 0.8,
                        'category': 'Conditions',
                        'snippet': condition.source.text if condition.source else '',
                        'resource_type': 'condition',
                        'resource_index': i,
                        'field_path': f'conditions.{i}.onset_date'
                    })
                
                # Note: severity field not available in current MedicalCondition model
            
            # 2. Medications
            for i, medication in enumerate(structured_data.medications):
                # Get date metadata if it exists
                medication_dict = structured_data_dict.get('medications', [])[i] if i < len(structured_data_dict.get('medications', [])) else {}
                date_metadata = medication_dict.get('date_metadata', {})
                
                field_list.append({
                    'field_name': f'Medication {i+1}',
                    'field_value': medication.name,
                    'confidence': medication.confidence,
                    'category': 'Medications',
                    'snippet': medication.source.text if medication.source else '',
                    'resource_type': 'medication',
                    'resource_index': i,
                    'field_path': f'medications.{i}.name',
                    'clinical_date': medication.start_date,
                    'date_source': date_metadata.get('source', 'extracted' if medication.start_date else None),
                    'date_status': 'verified' if date_metadata.get('verified') else 'pending',
                })
                
                if medication.dosage:
                    field_list.append({
                        'field_name': f'Medication {i+1} Dosage',
                        'field_value': medication.dosage,
                        'confidence': medication.confidence * 0.9,
                        'category': 'Medications',
                        'snippet': medication.source.text if medication.source else '',
                        'resource_type': 'medication',
                        'resource_index': i,
                        'field_path': f'medications.{i}.dosage'
                    })
                
                if medication.frequency:
                    field_list.append({
                        'field_name': f'Medication {i+1} Frequency',
                        'field_value': medication.frequency,
                        'confidence': medication.confidence * 0.9,
                        'category': 'Medications',
                        'snippet': medication.source.text if medication.source else '',
                        'resource_type': 'medication',
                        'resource_index': i,
                        'field_path': f'medications.{i}.frequency'
                    })
            
            # 3. Vital Signs
            for i, vital in enumerate(structured_data.vital_signs):
                # Get date metadata if it exists
                vital_dict = structured_data_dict.get('vital_signs', [])[i] if i < len(structured_data_dict.get('vital_signs', [])) else {}
                date_metadata = vital_dict.get('date_metadata', {})
                
                field_list.append({
                    'field_name': f'Vital Sign: {vital.measurement}',
                    'field_value': f"{vital.value} {vital.unit}" if vital.unit else str(vital.value),
                    'confidence': vital.confidence,
                    'category': 'Vital Signs',
                    'snippet': vital.source.text if vital.source else '',
                    'resource_type': 'vital_sign',
                    'resource_index': i,
                    'field_path': f'vital_signs.{i}.value',
                    'clinical_date': vital.timestamp,
                    'date_source': date_metadata.get('source', 'extracted' if vital.timestamp else None),
                    'date_status': 'verified' if date_metadata.get('verified') else 'pending',
                })
            
            # 4. Lab Results
            for i, lab in enumerate(structured_data.lab_results):
                # Get date metadata if it exists
                lab_dict = structured_data_dict.get('lab_results', [])[i] if i < len(structured_data_dict.get('lab_results', [])) else {}
                date_metadata = lab_dict.get('date_metadata', {})
                
                field_list.append({
                    'field_name': f'Lab: {lab.test_name}',
                    'field_value': f"{lab.value} {lab.unit}" if lab.unit else str(lab.value),
                    'confidence': lab.confidence,
                    'category': 'Laboratory Results',
                    'snippet': lab.source.text if lab.source else '',
                    'resource_type': 'lab_result',
                    'resource_index': i,
                    'field_path': f'lab_results.{i}.value',
                    'clinical_date': lab.test_date,
                    'date_source': date_metadata.get('source', 'extracted' if lab.test_date else None),
                    'date_status': 'verified' if date_metadata.get('verified') else 'pending',
                })
                
                if lab.reference_range:
                    field_list.append({
                        'field_name': f'Lab: {lab.test_name} Reference Range',
                        'field_value': lab.reference_range,
                        'confidence': lab.confidence * 0.8,
                        'category': 'Laboratory Results',
                        'snippet': lab.source.text if lab.source else '',
                        'resource_type': 'lab_result',
                        'resource_index': i,
                        'field_path': f'lab_results.{i}.reference_range'
                    })
            
            # 5. Procedures
            for i, procedure in enumerate(structured_data.procedures):
                # Get date metadata if it exists
                procedure_dict = structured_data_dict.get('procedures', [])[i] if i < len(structured_data_dict.get('procedures', [])) else {}
                date_metadata = procedure_dict.get('date_metadata', {})
                
                field_list.append({
                    'field_name': f'Procedure {i+1}',
                    'field_value': procedure.name,
                    'confidence': procedure.confidence,
                    'category': 'Procedures',
                    'snippet': procedure.source.text if procedure.source else '',
                    'resource_type': 'procedure',
                    'resource_index': i,
                    'field_path': f'procedures.{i}.name',
                    'clinical_date': procedure.procedure_date,
                    'date_source': date_metadata.get('source', 'extracted' if procedure.procedure_date else None),
                    'date_status': 'verified' if date_metadata.get('verified') else 'pending',
                })
                
                # Add procedure date as sub-property if available
                if procedure.procedure_date:
                    field_list.append({
                        'field_name': f'Procedure {i+1} Date',
                        'field_value': procedure.procedure_date,
                        'confidence': procedure.confidence * 0.9,
                        'category': 'Procedures',
                        'snippet': procedure.source.text if procedure.source else '',
                        'resource_type': 'procedure',
                        'resource_index': i,
                        'field_path': f'procedures.{i}.date'
                    })
            
            # 6. Providers
            for i, provider in enumerate(structured_data.providers):
                field_list.append({
                    'field_name': f'Provider {i+1}',
                    'field_value': provider.name,
                    'confidence': provider.confidence,
                    'category': 'Provider Information',
                    'snippet': provider.source.text if provider.source else '',
                    'resource_type': 'provider',
                    'resource_index': i,
                    'field_path': f'providers.{i}.name'
                })
                
                if provider.specialty:
                    field_list.append({
                        'field_name': f'Provider {i+1} Specialty',
                        'field_value': provider.specialty,
                        'confidence': provider.confidence * 0.9,
                        'category': 'Provider Information',
                        'snippet': provider.source.text if provider.source else '',
                        'resource_type': 'provider',
                        'resource_index': i,
                        'field_path': f'providers.{i}.specialty'
                    })
            
            logger.info(f"Converted structured data to {len(field_list)} fields for document {self.object.id}")
            return field_list
            
        except Exception as e:
            logger.error(f"Error converting structured data to fields for document {self.object.id}: {e}")
            return []
    
    def _get_legacy_field_data(self, force_review=False):
        """
        Get field data from legacy ParsedData.extraction_json for backwards compatibility.
        
        Args:
            force_review: Whether to create debug data if no parsed data exists
            
        Returns:
            list: List of field dictionaries for UI display
        """
        try:
            parsed_data = self.object.parsed_data
            source_snippets = parsed_data.source_snippets if parsed_data else {}
            
            if force_review and not parsed_data:
                # Create debug data
                return [{
                    'field_name': 'Debug Message',
                    'field_value': 'Force review mode enabled - no parsed data available',
                    'confidence': 0.5,
                    'category': 'Other',
                    'snippet': 'Debug context',
                    'resource_type': 'debug',
                    'resource_index': 0,
                    'field_path': 'debug.message'
                }]
            
            if not parsed_data or not parsed_data.extraction_json:
                return []
            
            extraction_data = parsed_data.extraction_json
            field_list = []
            
            # Handle different extraction_json formats
            if isinstance(extraction_data, dict):
                # Check if this is FHIR-structured format (has resource type keys)
                fhir_resource_types = ['Patient', 'Condition', 'Observation', 'MedicationStatement', 
                                     'Procedure', 'AllergyIntolerance', 'Practitioner', 'DocumentReference']
                is_fhir_structured = any(key in fhir_resource_types for key in extraction_data.keys())
                
                if is_fhir_structured:
                    # Convert FHIR-structured data to flat fields for UI
                    field_list = self._convert_fhir_structured_to_fields(extraction_data)
                else:
                    # Legacy format conversion
                    for key, value in extraction_data.items():
                        if isinstance(value, dict) and 'value' in value:
                            # Structured format with metadata
                            field_list.append({
                                'field_name': key,
                                'field_value': value.get('value', ''),
                                'confidence': value.get('confidence', 0.5),
                                'category': value.get('category', self._categorize_field(key)),
                                'snippet': source_snippets.get(key, ''),
                                'resource_type': 'legacy',
                                'resource_index': 0,
                                'field_path': f'legacy.{key}'
                            })
                        else:
                            # Simple key-value format
                            field_list.append({
                                'field_name': key,
                                'field_value': str(value) if value is not None else '',
                                'confidence': 0.5,  # Default confidence
                                'category': self._categorize_field(key),
                                'snippet': source_snippets.get(key, ''),
                                'resource_type': 'legacy',
                                'resource_index': 0,
                                'field_path': f'legacy.{key}'
                            })
            elif isinstance(extraction_data, list):
                # Already in list format from ResponseParser
                for i, field_data in enumerate(extraction_data):
                    field_name = field_data.get('label', field_data.get('field_name', 'Unknown Field'))
                    field_value = field_data.get('value', field_data.get('field_value', ''))
                    
                    # Get snippet for this field
                    snippet_text = source_snippets.get(field_name, '')
                    if not snippet_text:
                        snippet_text = field_data.get('source_text', '')
                        if not snippet_text and self.object.original_text:
                            snippet_text = self._generate_fallback_snippet(
                                self.object.original_text,
                                field_value,
                                field_data.get('char_position', 0)
                            )
                    
                    field_list.append({
                        'field_name': field_name,
                        'field_value': field_value,
                        'confidence': field_data.get('confidence', 0.5),
                        'category': field_data.get('category', self._categorize_field(field_name)),
                        'snippet': snippet_text,
                        'resource_type': 'legacy_list',
                        'resource_index': i,
                        'field_path': f'legacy_list.{i}.{field_name}'
                    })
            
            logger.info(f"Converted legacy data to {len(field_list)} fields for document {self.object.id}")
            return field_list
            
        except Exception as e:
            logger.error(f"Error converting legacy data to fields for document {self.object.id}: {e}")
            return []
    
    def _convert_fhir_structured_to_fields(self, fhir_data):
        """
        Convert FHIR-structured data to flat field format for UI display.
        
        Args:
            fhir_data: Dictionary with FHIR resource types as keys
            
        Returns:
            list: List of field dictionaries for UI display
        """
        field_list = []
        
        # Process Patient resources
        if 'Patient' in fhir_data:
            patient_data = fhir_data['Patient']
            if isinstance(patient_data, dict):
                # Extract patient demographics
                if 'name' in patient_data:
                    name_data = patient_data['name']
                    field_list.append({
                        'field_name': 'Patient Name',
                        'field_value': name_data.get('value', ''),
                        'confidence': name_data.get('confidence', 0.5),
                        'category': 'Demographics',
                        'fhir_path': 'Patient.name',
                        'source_text': name_data.get('source_text', ''),
                    })
                
                if 'birthDate' in patient_data:
                    birth_data = patient_data['birthDate']
                    field_list.append({
                        'field_name': 'Date of Birth',
                        'field_value': birth_data.get('value', ''),
                        'confidence': birth_data.get('confidence', 0.5),
                        'category': 'Demographics',
                        'fhir_path': 'Patient.birthDate',
                        'source_text': birth_data.get('source_text', ''),
                    })
                
                if 'identifier' in patient_data:
                    id_data = patient_data['identifier']
                    field_list.append({
                        'field_name': 'Medical Record Number',
                        'field_value': id_data.get('value', ''),
                        'confidence': id_data.get('confidence', 0.5),
                        'category': 'Demographics',
                        'fhir_path': 'Patient.identifier',
                        'source_text': id_data.get('source_text', ''),
                    })
        
        # Process Condition resources
        if 'Condition' in fhir_data:
            conditions = fhir_data['Condition']
            if not isinstance(conditions, list):
                conditions = [conditions]
            
            for i, condition in enumerate(conditions):
                if isinstance(condition, dict) and 'code' in condition:
                    code_data = condition['code']
                    field_list.append({
                        'field_name': f'Diagnosis {i+1}',
                        'field_value': code_data.get('value', ''),
                        'confidence': code_data.get('confidence', 0.5),
                        'category': 'Medical History',
                        'fhir_path': f'Condition[{i}].code',
                        'source_text': code_data.get('source_text', ''),
                    })
                    
                    # Add onset date if available
                    if 'onsetDateTime' in condition:
                        onset_data = condition['onsetDateTime']
                        field_list.append({
                            'field_name': f'Diagnosis {i+1} Onset Date',
                            'field_value': onset_data.get('value', ''),
                            'confidence': onset_data.get('confidence', 0.5),
                            'category': 'Medical History',
                            'fhir_path': f'Condition[{i}].onsetDateTime',
                            'source_text': onset_data.get('source_text', ''),
                        })
        
        # Process MedicationStatement resources
        if 'MedicationStatement' in fhir_data:
            medications = fhir_data['MedicationStatement']
            if not isinstance(medications, list):
                medications = [medications]
            
            for i, medication in enumerate(medications):
                if isinstance(medication, dict) and 'medicationCodeableConcept' in medication:
                    med_data = medication['medicationCodeableConcept']
                    field_list.append({
                        'field_name': f'Medication {i+1}',
                        'field_value': med_data.get('value', ''),
                        'confidence': med_data.get('confidence', 0.5),
                        'category': 'Medications',
                        'fhir_path': f'MedicationStatement[{i}].medicationCodeableConcept',
                        'source_text': med_data.get('source_text', ''),
                    })
        
        # Process Procedure resources
        if 'Procedure' in fhir_data:
            procedures = fhir_data['Procedure']
            if not isinstance(procedures, list):
                procedures = [procedures]
            
            for i, procedure in enumerate(procedures):
                if isinstance(procedure, dict) and 'code' in procedure:
                    code_data = procedure['code']
                    field_list.append({
                        'field_name': f'Procedure {i+1}',
                        'field_value': code_data.get('value', ''),
                        'confidence': code_data.get('confidence', 0.5),
                        'category': 'Medical History',
                        'fhir_path': f'Procedure[{i}].code',
                        'source_text': code_data.get('source_text', ''),
                    })
        
        # Process AllergyIntolerance resources
        if 'AllergyIntolerance' in fhir_data:
            allergies = fhir_data['AllergyIntolerance']
            if not isinstance(allergies, list):
                allergies = [allergies]
            
            for i, allergy in enumerate(allergies):
                if isinstance(allergy, dict) and 'code' in allergy:
                    code_data = allergy['code']
                    field_list.append({
                        'field_name': f'Allergy {i+1}',
                        'field_value': code_data.get('value', ''),
                        'confidence': code_data.get('confidence', 0.5),
                        'category': 'Allergies',
                        'fhir_path': f'AllergyIntolerance[{i}].code',
                        'source_text': code_data.get('source_text', ''),
                    })
        
        return field_list
    
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
        
        # Conditions (diagnoses)
        elif any(term in field_lower for term in ['diagnosis', 'condition']):
            return 'Conditions'
        
        # Procedures
        elif any(term in field_lower for term in ['procedure', 'surgery', 'operation']):
            return 'Procedures'
        
        # Medical History (catch-all for other medical terms)
        elif any(term in field_lower for term in ['history', 'medical']):
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
    
    def _group_multi_property_items(self, items):
        """
        Group multi-property items (like medications) by resource_index.
        
        Args:
            items: List of field dictionaries
            
        Returns:
            List of items where multi-property resources are grouped into single objects
        """
        grouped = []
        medication_groups = {}
        
        for item in items:
            resource_type = item.get('resource_type')
            resource_index = item.get('resource_index')
            
            # Group multi-property resources (medications, conditions, procedures, labs)
            if resource_type in ['medication', 'condition', 'procedure', 'lab_result', 'vital_sign'] and resource_index is not None:
                if resource_index not in medication_groups:
                    # Determine base field name based on resource type
                    if resource_type == 'condition':
                        base_name = f'Condition {resource_index + 1}'
                    elif resource_type == 'procedure':
                        base_name = f'Procedure {resource_index + 1}'
                    elif resource_type == 'lab_result':
                        base_name = f'Lab {resource_index + 1}'
                    elif resource_type == 'vital_sign':
                        base_name = f'Vital Sign {resource_index + 1}'
                    else:
                        base_name = f'Medication {resource_index + 1}'
                    
                    medication_groups[resource_index] = {
                        'is_grouped': True,
                        'resource_type': resource_type,
                        'resource_index': resource_index,
                        'field_name': base_name,
                        'category': item.get('category'),
                        'properties': [],
                        'clinical_date': None,  # Will be set from main medication field
                        'date_source': None,
                        'date_status': None,
                        'snippet': item.get('snippet'),
                        'confidence': item.get('confidence', 0.8),
                        'approved': item.get('approved', False),
                        'id': item.get('id'),  # Use first property's ID as group ID
                        'parsed_data_id': item.get('parsed_data_id')
                    }
                
                # If this is the main field (not a sub-property), capture its date
                field_name = item.get('field_name', '')
                # List of all known sub-properties across all resource types
                sub_properties = ['Dosage', 'Frequency', 'Route', 'Onset Date', 'Date', 'Reference Range', 'Outcome', 'Provider']
                is_sub_property = any(prop in field_name for prop in sub_properties)
                
                if not is_sub_property:
                    # This is the main field - use its clinical_date
                    medication_groups[resource_index]['clinical_date'] = item.get('clinical_date')
                    medication_groups[resource_index]['date_source'] = item.get('date_source')
                    medication_groups[resource_index]['date_status'] = item.get('date_status')
                
                # Extract property name (everything after "Resource Type N ")
                # e.g., "Medication 3 Dosage" → "Dosage", "Procedure 2 Date" → "Date"
                # Handle multi-word resource types like "Vital Sign 5" → ["Vital", "Sign", "5", ...]
                parts = field_name.split()
                # Find where the number is, property name comes after
                property_name = field_name
                for idx, part in enumerate(parts):
                    if part.isdigit() and idx + 1 < len(parts):
                        property_name = ' '.join(parts[idx + 1:])
                        break
                
                # Add this property to the group
                medication_groups[resource_index]['properties'].append({
                    'name': property_name,
                    'value': item.get('field_value'),
                    'field_id': item.get('id'),
                    'field_path': item.get('field_path')
                })
            else:
                # Not a medication or doesn't have resource_index - add as-is
                grouped.append(item)
        
        # Add grouped medications to results
        for med_group in sorted(medication_groups.values(), key=lambda x: x['resource_index']):
            grouped.append(med_group)
        
        return grouped
    
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
    
    def _update_structured_data_field(self, field_path, new_value, document):
        """
        Update a specific field in the document's structured data.
        
        Args:
            field_path: Dot notation path to the field (e.g., 'conditions.0.name')
            new_value: New value to set
            document: Document instance to update
            
        Returns:
            bool: True if update was successful
        """
        try:
            from .services.ai_extraction import StructuredMedicalExtraction
            
            structured_data_dict = document.get_structured_medical_data()
            if not structured_data_dict:
                logger.warning(f"No structured data found for document {document.id}")
                return False
            
            # Convert to Pydantic model for validation
            structured_data = StructuredMedicalExtraction.model_validate(structured_data_dict)
            
            # Parse the field path (e.g., 'conditions.0.name' -> ['conditions', '0', 'name'])
            path_parts = field_path.split('.')
            if len(path_parts) < 3:
                logger.error(f"Invalid field path: {field_path}")
                return False
            
            resource_type = path_parts[0]  # 'conditions'
            resource_index = int(path_parts[1])  # 0
            field_name = path_parts[2]  # 'name'
            
            # Update the appropriate field
            if resource_type == 'conditions' and resource_index < len(structured_data.conditions):
                if field_name == 'name':
                    structured_data.conditions[resource_index].name = new_value
                elif field_name == 'onset_date':
                    structured_data.conditions[resource_index].onset_date = new_value
                # Note: severity field not available in current MedicalCondition model
                else:
                    logger.error(f"Unknown condition field: {field_name}")
                    return False
                    
            elif resource_type == 'medications' and resource_index < len(structured_data.medications):
                if field_name == 'name':
                    structured_data.medications[resource_index].name = new_value
                elif field_name == 'dosage':
                    structured_data.medications[resource_index].dosage = new_value
                elif field_name == 'frequency':
                    structured_data.medications[resource_index].frequency = new_value
                else:
                    logger.error(f"Unknown medication field: {field_name}")
                    return False
                    
            elif resource_type == 'vital_signs' and resource_index < len(structured_data.vital_signs):
                if field_name == 'value':
                    # Parse value and unit if combined
                    parts = new_value.split()
                    if len(parts) >= 2:
                        structured_data.vital_signs[resource_index].value = parts[0]
                        structured_data.vital_signs[resource_index].unit = ' '.join(parts[1:])
                    else:
                        structured_data.vital_signs[resource_index].value = new_value
                else:
                    logger.error(f"Unknown vital sign field: {field_name}")
                    return False
                    
            elif resource_type == 'lab_results' and resource_index < len(structured_data.lab_results):
                if field_name == 'value':
                    # Parse value and unit if combined
                    parts = new_value.split()
                    if len(parts) >= 2:
                        structured_data.lab_results[resource_index].value = parts[0]
                        structured_data.lab_results[resource_index].unit = ' '.join(parts[1:])
                    else:
                        structured_data.lab_results[resource_index].value = new_value
                elif field_name == 'reference_range':
                    structured_data.lab_results[resource_index].reference_range = new_value
                else:
                    logger.error(f"Unknown lab result field: {field_name}")
                    return False
                    
            elif resource_type == 'procedures' and resource_index < len(structured_data.procedures):
                if field_name == 'name':
                    structured_data.procedures[resource_index].name = new_value
                elif field_name == 'date':
                    structured_data.procedures[resource_index].date = new_value
                else:
                    logger.error(f"Unknown procedure field: {field_name}")
                    return False
                    
            elif resource_type == 'providers' and resource_index < len(structured_data.providers):
                if field_name == 'name':
                    structured_data.providers[resource_index].name = new_value
                elif field_name == 'specialty':
                    structured_data.providers[resource_index].specialty = new_value
                else:
                    logger.error(f"Unknown provider field: {field_name}")
                    return False
            else:
                logger.error(f"Invalid resource type or index: {resource_type}[{resource_index}]")
                return False
            
            # Save the updated structured data back to the document
            document.structured_data = structured_data.model_dump()
            document.save(update_fields=['structured_data'])
            
            logger.info(f"Updated structured data field {field_path} for document {document.id}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating structured data field {field_path} for document {document.id}: {e}")
            return False
    
    def _generate_fallback_snippet(self, original_text, field_value, char_position):
        """
        Generate a text snippet around the extracted value when AI doesn't provide source_text.
        
        Args:
            original_text: Full document text
            field_value: The extracted value to find context for
            char_position: Approximate position in the text
            
        Returns:
            str: Generated snippet with context around the value
        """
        try:
            if not original_text or not field_value:
                return ""
            
            # Try to find the exact value in the document
            value_index = original_text.lower().find(field_value.lower())
            
            if value_index != -1:
                # Found exact match - use this position
                start_pos = max(0, value_index - 150)
                end_pos = min(len(original_text), value_index + len(field_value) + 150)
            else:
                # Use char_position as fallback
                start_pos = max(0, char_position - 150)  
                end_pos = min(len(original_text), char_position + 300)
            
            # Extract the snippet
            snippet = original_text[start_pos:end_pos].strip()
            
            # Clean up the snippet
            if start_pos > 0:
                snippet = "..." + snippet
            if end_pos < len(original_text):
                snippet = snippet + "..."
                
            return snippet
            
        except Exception as e:
            logger.error(f"Error generating fallback snippet: {e}")
            return f"Context unavailable (extracted from position {char_position})"
    
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
            
            # Apply patient data comparison resolutions if they exist
            try:
                from .models import PatientDataComparison
                from .services import PatientRecordUpdateService
                
                comparison = PatientDataComparison.objects.filter(
                    document=self.object,
                    patient=self.object.patient
                ).first()
                
                if comparison and comparison.resolution_decisions:
                    # Apply resolved patient data updates
                    update_service = PatientRecordUpdateService()
                    update_results = update_service.apply_comparison_resolutions(comparison, request.user)
                    
                    if update_results['success'] and update_results['updates_applied'] > 0:
                        logger.info(f"Applied {update_results['updates_applied']} patient record updates from document {self.object.id}")
                        messages.info(
                            request,
                            f"Applied {update_results['updates_applied']} patient record updates based on your comparison decisions."
                        )
                    elif update_results.get('validation_errors'):
                        logger.warning(f"Validation errors during patient updates: {update_results['validation_errors']}")
                        
            except Exception as comparison_error:
                logger.error(f"Error applying patient data comparisons: {comparison_error}")
                # Don't fail the approval, just log the error
            
            # Mark parsed data as approved using the model method
            parsed_data.approve_extraction(request.user)
            
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
            # Template sends 'notes' parameter
            notes = request.POST.get('notes', '').strip()
            if not notes:
                # Fallback to rejection_notes if provided
                notes = request.POST.get('rejection_notes', '').strip()
            
            parsed_data = self.object.parsed_data
            # Use new rejection method that sets status and reason
            parsed_data.reject_extraction(request.user, reason=notes)
            
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


# ============================================================================
# Development-Only Deletion Views  
# ============================================================================

@method_decorator([admin_required, has_permission('documents.delete_document')], name='dispatch')
class DocumentDeleteView(LoginRequiredMixin, View):
    """
    Development-only view for deleting documents.
    
    WARNING: This view is only available in development mode.
    In production, documents should be archived or marked as deleted.
    """
    http_method_names = ['get', 'post']
    
    def dispatch(self, request, *args, **kwargs):
        """Check if we're in development mode."""
        from django.conf import settings
        
        if not settings.DEBUG:
            messages.error(request, "Document deletion is only available in development mode.")
            return redirect('documents:list')
        
        return super().dispatch(request, *args, **kwargs)
    
    def get(self, request, pk):
        """Show confirmation page for document deletion."""
        try:
            document = get_object_or_404(Document, pk=pk)
            
            # Get related data for confirmation
            related_data = {
                'has_parsed_data': hasattr(document, 'parsed_data'),
                'file_size_mb': round(document.file_size / (1024 * 1024), 1) if document.file_size else 0,
                'status': document.get_status_display(),
            }
            
            # Check if parsed data exists and is merged
            if related_data['has_parsed_data']:
                try:
                    parsed_data = document.parsed_data
                    related_data.update({
                        'is_merged': parsed_data.is_merged,
                        'fhir_resource_count': parsed_data.get_fhir_resource_count(),
                    })
                except Exception:
                    related_data['has_parsed_data'] = False
            
            return render(request, 'documents/document_confirm_delete.html', {
                'document': document,
                'related_data': related_data,
            })
            
        except Exception as delete_error:
            logger.error(f"Error loading document deletion page: {delete_error}")
            messages.error(request, "Error loading document data.")
            return redirect('documents:list')
    
    def post(self, request, pk):
        """Handle document deletion with file cleanup."""
        try:
            with transaction.atomic():
                document = get_object_or_404(Document, pk=pk)
                filename = document.filename
                patient_name = f"{document.patient.first_name} {document.patient.last_name}"
                
                # Check if document has merged FHIR data
                has_merged_data = False
                try:
                    parsed_data = document.parsed_data
                    has_merged_data = parsed_data.is_merged
                except:
                    pass
                
                logger.warning(
                    f"DEVELOPMENT DELETE: User {request.user.id} deleting document {document.id} "
                    f"({filename}) for patient {document.patient.mrn}. "
                    f"Has merged FHIR data: {has_merged_data}"
                )
                
                # Delete the physical file if it exists
                file_deleted = False
                if document.file:
                    try:
                        if default_storage.exists(document.file.name):
                            default_storage.delete(document.file.name)
                            file_deleted = True
                    except Exception as file_error:
                        logger.error(f"Error deleting file {document.file.name}: {file_error}")
                
                # Delete the document record (CASCADE will handle ParsedData)
                document.delete()
                
                success_message = f"Document '{filename}' for patient {patient_name} has been permanently deleted."
                if file_deleted:
                    success_message += " The physical file has also been removed."
                if has_merged_data:
                    success_message += " WARNING: This document had merged FHIR data in the patient record."
                
                messages.success(request, success_message)
                return redirect('documents:list')
                
        except Exception as delete_error:
            logger.error(f"Error deleting document {pk}: {delete_error}")
            messages.error(request, "Error deleting document. Please try again.")
            return redirect('documents:detail', pk=pk)


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


@method_decorator([provider_required, has_permission('documents.change_document')], name='dispatch')
class PatientDataResolutionView(LoginRequiredMixin, View):
    """
    Handle patient data comparison resolution actions via AJAX/HTMX.
    """
    http_method_names = ['post']
    
    def post(self, request, *args, **kwargs):
        """
        Handle field resolution actions.
        
        Expected POST data:
        - action: 'resolve_field', 'bulk_resolve', 'manual_edit'
        - field_name: Name of the field being resolved
        - resolution: 'keep_existing', 'use_extracted', 'manual_edit'
        - custom_value: For manual edits
        - reasoning: User's reasoning for the decision
        """
        try:
            document_id = kwargs.get('pk')
            document = get_object_or_404(Document, id=document_id, created_by=request.user)
            
            action = request.POST.get('action')
            
            if action == 'resolve_field':
                return self._handle_field_resolution(request, document)
            elif action == 'bulk_resolve':
                return self._handle_bulk_resolution(request, document)
            elif action == 'manual_edit':
                return self._handle_manual_edit(request, document)
            else:
                return JsonResponse({'error': 'Invalid action'}, status=400)
                
        except Exception as e:
            logger.error(f"Error in patient data resolution: {e}")
            return JsonResponse({'error': 'Resolution failed'}, status=500)
    
    def _handle_field_resolution(self, request, document):
        """Handle individual field resolution."""
        field_name = request.POST.get('field_name')
        resolution = request.POST.get('resolution')
        reasoning = request.POST.get('reasoning', '')
        
        if not field_name or not resolution:
            return JsonResponse({'error': 'Missing field_name or resolution'}, status=400)
        
        try:
            # Get the comparison record
            from .models import PatientDataComparison
            comparison = PatientDataComparison.objects.get(
                document=document,
                patient=document.patient
            )
            
            # Mark field as resolved
            comparison.mark_field_resolved(
                field_name=field_name,
                resolution=resolution,
                notes=reasoning
            )
            comparison.reviewer = request.user
            comparison.save()
            
            # Return updated field status
            return JsonResponse({
                'success': True,
                'field_name': field_name,
                'resolution': resolution,
                'completion_percentage': comparison.get_completion_percentage(),
                'fields_resolved': comparison.fields_resolved,
                'has_pending': comparison.has_pending_discrepancies()
            })
            
        except PatientDataComparison.DoesNotExist:
            return JsonResponse({'error': 'Comparison record not found'}, status=404)
        except Exception as e:
            logger.error(f"Error resolving field {field_name}: {e}")
            return JsonResponse({'error': 'Field resolution failed'}, status=500)
    
    def _handle_bulk_resolution(self, request, document):
        """Handle bulk resolution actions."""
        bulk_action = request.POST.get('bulk_action')
        reasoning = request.POST.get('reasoning', f'Bulk action: {bulk_action}')
        
        try:
            from .models import PatientDataComparison
            comparison = PatientDataComparison.objects.get(
                document=document,
                patient=document.patient
            )
            
            resolved_count = 0
            
            if bulk_action == 'keep_all_existing':
                # Keep all existing patient record data
                for field_name, field_data in comparison.comparison_data.items():
                    if field_data.get('has_discrepancy', False):
                        comparison.mark_field_resolved(field_name, 'keep_existing', notes=reasoning)
                        resolved_count += 1
                        
            elif bulk_action == 'use_all_high_confidence':
                # Use all high-confidence document data
                for field_name, field_data in comparison.comparison_data.items():
                    if (field_data.get('has_discrepancy', False) and 
                        field_data.get('confidence', 0.0) >= 0.8):
                        comparison.mark_field_resolved(field_name, 'use_extracted', notes=reasoning)
                        resolved_count += 1
                        
            elif bulk_action == 'apply_suggestions':
                # Apply all system suggestions
                for field_name, field_data in comparison.comparison_data.items():
                    if field_data.get('has_discrepancy', False):
                        suggested = field_data.get('suggested_resolution', 'manual_edit')
                        if suggested != 'manual_edit':
                            comparison.mark_field_resolved(field_name, suggested, notes=reasoning)
                            resolved_count += 1
            
            comparison.reviewer = request.user
            comparison.save()
            
            return JsonResponse({
                'success': True,
                'bulk_action': bulk_action,
                'resolved_count': resolved_count,
                'completion_percentage': comparison.get_completion_percentage(),
                'fields_resolved': comparison.fields_resolved,
                'has_pending': comparison.has_pending_discrepancies()
            })
            
        except PatientDataComparison.DoesNotExist:
            return JsonResponse({'error': 'Comparison record not found'}, status=404)
        except Exception as e:
            logger.error(f"Error in bulk resolution: {e}")
            return JsonResponse({'error': 'Bulk resolution failed'}, status=500)
    
    def _handle_manual_edit(self, request, document):
        """Handle manual field editing."""
        field_name = request.POST.get('field_name')
        custom_value = request.POST.get('custom_value', '')
        reasoning = request.POST.get('reasoning', '')
        
        if not field_name:
            return JsonResponse({'error': 'Missing field_name'}, status=400)
        
        try:
            from .models import PatientDataComparison
            comparison = PatientDataComparison.objects.get(
                document=document,
                patient=document.patient
            )
            
            # Mark field as resolved with custom value
            comparison.mark_field_resolved(
                field_name=field_name,
                resolution='manual_edit',
                custom_value=custom_value,
                notes=reasoning
            )
            comparison.reviewer = request.user
            comparison.save()
            
            return JsonResponse({
                'success': True,
                'field_name': field_name,
                'custom_value': custom_value,
                'completion_percentage': comparison.get_completion_percentage(),
                'fields_resolved': comparison.fields_resolved,
                'has_pending': comparison.has_pending_discrepancies()
            })
            
        except PatientDataComparison.DoesNotExist:
            return JsonResponse({'error': 'Comparison record not found'}, status=404)
        except Exception as e:
            logger.error(f"Error in manual edit for field {field_name}: {e}")
            return JsonResponse({'error': 'Manual edit failed'}, status=500)


# ============================================================================
# FIELD-LEVEL REVIEW ENDPOINTS (Subtasks 31.9-31.13)
# ============================================================================

@require_POST
def approve_field(request, field_id):
    """
    Approve a specific field in the document review interface.
    
    Args:
        request: HTTP POST request
        field_id: Unique identifier for the field to approve
        
    Returns:
        HttpResponse: Updated field card HTML for HTMX
    """
    try:
        # Get field data from request (since we're working with dynamic data)
        document_id = request.POST.get('document_id')
        if not document_id:
            return HttpResponse('<div class="text-red-600">Document ID required</div>', status=400)
        
        document = get_object_or_404(Document, id=document_id)
        
        # Verify user has permission to approve this document
        if not request.user.has_perm('documents.change_document'):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        # Create approved field data for template rendering
        # Preserve original confidence score - don't default to 0.5
        original_confidence = request.POST.get('confidence', '0.5')
        try:
            confidence_score = float(original_confidence)
        except (ValueError, TypeError):
            confidence_score = 0.5
            
        mock_item = {
            'id': field_id,
            'field_name': request.POST.get('field_name', 'Unknown Field'),
            'field_value': request.POST.get('field_value', ''),
            'confidence': confidence_score,
            'snippet': request.POST.get('snippet', ''),
            'approved': True,  # This is the key change
            'flagged': False,
            'resource_type': request.POST.get('resource_type', ''),
            'resource_index': request.POST.get('resource_index', ''),
            'field_path': request.POST.get('field_path', '')
        }
        
        # Render the updated field card
        html = render_to_string('documents/partials/field_card.html', {
            'item': mock_item
        }, request=request)
        
        # Store approval in session for progress tracking
        field_name = request.POST.get('field_name', 'Unknown Field')
        field_key = f"approved_field_{document_id}_{field_name}_{field_id}"
        request.session[field_key] = True
        request.session.modified = True
        
        logger.info(f"Field {field_id} approved by user {request.user.id}")
        
        return HttpResponse(html)
        
    except Exception as e:
        logger.error(f"Error approving field {field_id}: {e}")
        return HttpResponse('<div class="text-red-600">Error approving field</div>', status=500)


@require_POST  
def update_field_value(request, field_id):
    """
    Update the value of a specific field in the document review interface.
    Supports both structured data and legacy formats.
    
    Args:
        request: HTTP POST request with 'value' parameter
        field_id: Unique identifier for the field to update
        
    Returns:
        HttpResponse: Updated field card HTML for HTMX
    """
    try:
        # Get the new value from the request
        new_value = request.POST.get('value', '').strip()
        
        if not new_value:
            return HttpResponse('<div class="text-red-600">Value cannot be empty</div>', status=400)
        
        # Get document ID for permission checking
        document_id = request.POST.get('document_id')
        if not document_id:
            return HttpResponse('<div class="text-red-600">Document ID required</div>', status=400)
            
        document = get_object_or_404(Document, id=document_id)
        
        # Verify user has permission
        if not request.user.has_perm('documents.change_document'):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        # Get field path for structured data updates
        field_path = request.POST.get('field_path', '')
        
        # Try to update structured data if path is available
        if field_path and document.has_structured_data():
            review_view = DocumentReviewView()
            review_view.object = document
            success = review_view._update_structured_data_field(field_path, new_value, document)
            
            if success:
                logger.info(f"Updated structured data field {field_path} for document {document.id}")
            else:
                logger.warning(f"Failed to update structured data field {field_path}, using mock update")
        
        # Create updated field data for template rendering
        mock_item = {
            'id': field_id,
            'field_name': request.POST.get('field_name', 'Unknown Field'),
            'field_value': new_value,
            'confidence': float(request.POST.get('confidence', 0.5)),
            'snippet': request.POST.get('snippet', ''),
            'approved': False,  # Reset approval when value changes
            'flagged': False,
            'edited': True,  # Mark as edited
            'resource_type': request.POST.get('resource_type', 'unknown'),
            'resource_index': request.POST.get('resource_index', 0),
            'field_path': field_path
        }
        
        # Render the updated field card
        html = render_to_string('documents/partials/field_card.html', {
            'item': mock_item
        }, request=request)
        
        logger.info(f"Field {field_id} value updated by user {request.user.id}: {new_value}")
        
        return HttpResponse(html)
        
    except Exception as e:
        logger.error(f"Error updating field {field_id}: {e}")
        return HttpResponse('<div class="text-red-600">Error updating field</div>', status=500)


@require_POST
def flag_field(request, field_id):
    """
    Flag a specific field for additional review.
    
    Args:
        request: HTTP POST request with optional 'reason' parameter
        field_id: Unique identifier for the field to flag
        
    Returns:
        HttpResponse: Updated field card HTML for HTMX
    """
    try:
        # Get the flag reason from the request
        flag_reason = request.POST.get('reason', 'Needs review').strip()
        
        # Get document ID for permission checking
        document_id = request.POST.get('document_id')
        if not document_id:
            return HttpResponse('<div class="text-red-600">Document ID required</div>', status=400)
            
        document = get_object_or_404(Document, id=document_id)
        
        # Verify user has permission
        if not request.user.has_perm('documents.change_document'):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        # Create flagged field data for template rendering
        mock_item = {
            'id': field_id,
            'field_name': request.POST.get('field_name', 'Unknown Field'),
            'field_value': request.POST.get('field_value', ''),
            'confidence': float(request.POST.get('confidence', 0.5)),
            'snippet': request.POST.get('snippet', ''),
            'approved': False,  # Reset approval when flagged
            'flagged': True,
            'flag_reason': flag_reason,
            'resource_type': request.POST.get('resource_type', ''),
            'resource_index': request.POST.get('resource_index', ''),
            'field_path': request.POST.get('field_path', '')
        }
        
        # Render the updated field card
        html = render_to_string('documents/partials/field_card.html', {
            'item': mock_item
        }, request=request)
        
        logger.info(f"Field {field_id} flagged by user {request.user.id}: {flag_reason}")
        
        return HttpResponse(html)
        
    except Exception as e:
        logger.error(f"Error flagging field {field_id}: {e}")
        return HttpResponse('<div class="text-red-600">Error flagging field</div>', status=500)


@require_POST
def complete_review(request, document_id):
    """
    Complete the review process for a document.
    
    Args:
        request: HTTP POST request
        document_id: ID of the document to complete review for
        
    Returns:
        HttpResponse: Redirect to document list or error message
    """
    try:
        document = get_object_or_404(Document, id=document_id)
        
        # Verify user has permission
        if not request.user.has_perm('documents.change_document'):
            messages.error(request, 'Permission denied')
            return redirect('documents:review', document_id=document_id)
        
        # Check if document is in reviewable state
        if document.status != 'review':
            messages.error(request, 'This document is not available for review completion.')
            return redirect('documents:detail', pk=document_id)
        
        # Update document status
        document.status = 'completed'
        
        # Update parsed data
        try:
            parsed_data = document.parsed_data
            parsed_data.is_approved = True
            parsed_data.reviewed_by = request.user
            parsed_data.reviewed_at = timezone.now()
            parsed_data.save()
        except ParsedData.DoesNotExist:
            logger.warning(f"No parsed data found for document {document_id}")
        
        document.save()
        
        messages.success(request, f"Document '{document.filename}' review completed successfully.")
        logger.info(f"Document {document_id} review completed by user {request.user.id}")
        
        return redirect('documents:list')
        
    except Exception as e:
        logger.error(f"Error completing review for document {document_id}: {e}")
        messages.error(request, 'An error occurred while completing the review.')
        return redirect('documents:review', document_id=document_id)


@require_POST
def add_missing_field(request, document_id):
    """
    Add a missing field to the document review.
    
    Args:
        request: HTTP POST request with 'field_name' and 'field_value' parameters
        document_id: ID of the document to add the field to
        
    Returns:
        HttpResponse: New field card HTML for HTMX
    """
    try:
        # Get the document for permission checking
        document = get_object_or_404(Document, id=document_id)
        
        # Verify user has permission
        if not request.user.has_perm('documents.add_document'):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        # Get field information from request
        field_name = request.POST.get('field_name', '').strip()
        field_value = request.POST.get('field_value', '').strip()
        
        if not field_name:
            return HttpResponse('<div class="text-red-600">Field name is required</div>', status=400)
        
        if not field_value:
            return HttpResponse('<div class="text-red-600">Field value is required</div>', status=400)
        
        # Create new field data for template rendering
        new_field = {
            'id': f"manual_{field_name}_{timezone.now().timestamp()}",
            'field_name': field_name,
            'field_value': field_value,
            'confidence': 0.5,  # Manual entries get default confidence
            'snippet': f'Manually added by {request.user.get_full_name()}',
            'approved': False,
            'flagged': False,
            'manual_entry': True
        }
        
        # Render the new field card
        html = render_to_string('documents/partials/field_card.html', {
            'item': new_field
        }, request=request)
        
        logger.info(f"Missing field '{field_name}' added to document {document_id} by user {request.user.id}")
        
        return HttpResponse(html)
        
    except Exception as e:
        logger.error(f"Error adding missing field to document {document_id}: {e}")
        return HttpResponse('<div class="text-red-600">Error adding field</div>', status=500)


# ============================================
# Clinical Date Management API (Task 35.5)
# ============================================

@require_POST
def save_clinical_date(request):
    """
    Save or update a clinical date for a specific medical resource (condition, medication, lab, etc.).
    
    Args:
        request: HTTP POST request with:
            - parsed_data_id: ID of the ParsedData object
            - clinical_date: Date in YYYY-MM-DD format
            - document_id: ID of the source document (for permissions)
            - resource_type: Type of resource (condition, medication, lab_result, etc.)
            - resource_index: Index of the resource in the structured data array
    
    Returns:
        JsonResponse: Success status and message
    """
    try:
        # Get and validate parameters
        parsed_data_id = request.POST.get('parsed_data_id')
        clinical_date_str = request.POST.get('clinical_date')
        document_id = request.POST.get('document_id')
        resource_type = request.POST.get('resource_type')
        resource_index = request.POST.get('resource_index')
        
        if not all([parsed_data_id, clinical_date_str, document_id, resource_type, resource_index is not None]):
            return JsonResponse({
                'success': False,
                'error': 'Missing required parameters (need parsed_data_id, clinical_date, document_id, resource_type, resource_index)'
            }, status=400)
        
        # Convert resource_index to int
        try:
            resource_index = int(resource_index)
        except (ValueError, TypeError):
            return JsonResponse({
                'success': False,
                'error': 'Invalid resource_index - must be a number'
            }, status=400)
        
        # Get the document for permission checking
        document = get_object_or_404(Document, id=document_id)
        
        # Verify user has permission to review documents
        if not request.user.has_perm('documents.change_document'):
            return JsonResponse({
                'success': False,
                'error': 'Permission denied'
            }, status=403)
        
        # Get the ParsedData object
        parsed_data = get_object_or_404(ParsedData, id=parsed_data_id, document=document)
        
        # Validate and parse the date
        from apps.core.date_parser import ClinicalDateParser
        parser = ClinicalDateParser()
        
        try:
            parsed_date = parser.parse_single_date(clinical_date_str)
            if not parsed_date:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid date format. Please use YYYY-MM-DD'
                }, status=400)
        except Exception as date_error:
            logger.error(f"Error parsing clinical date '{clinical_date_str}': {date_error}")
            return JsonResponse({
                'success': False,
                'error': f'Invalid date: {str(date_error)}'
            }, status=400)
        
        # Validate date is not in the future
        if parsed_date > timezone.now().date():
            return JsonResponse({
                'success': False,
                'error': 'Clinical date cannot be in the future'
            }, status=400)
        
        # Validate date is reasonable (after 1900)
        from datetime import date as date_class
        min_date = date_class(1900, 1, 1)
        if parsed_date < min_date:
            return JsonResponse({
                'success': False,
                'error': 'Date must be after 1900'
            }, status=400)
        
        # Map resource type to date field name
        date_field_map = {
            'condition': 'onset_date',
            'medication': 'start_date',
            'lab_result': 'test_date',
            'procedure': 'procedure_date',
            'vital_sign': 'timestamp',
        }
        
        # Map resource type to plural key in structured_data
        resource_plural_map = {
            'condition': 'conditions',
            'medication': 'medications',
            'lab_result': 'lab_results',
            'procedure': 'procedures',
            'vital_sign': 'vital_signs',
        }
        
        if resource_type not in date_field_map:
            return JsonResponse({
                'success': False,
                'error': f'Invalid resource_type: {resource_type}'
            }, status=400)
        
        date_field = date_field_map[resource_type]
        resource_key = resource_plural_map[resource_type]
        
        # Save the clinical date to the specific resource
        try:
            # Get structured data from corrections
            if not parsed_data.corrections:
                parsed_data.corrections = {}
            
            if 'structured_data' not in parsed_data.corrections:
                return JsonResponse({
                    'success': False,
                    'error': 'No structured data available to update'
                }, status=400)
            
            structured_data = parsed_data.corrections['structured_data']
            
            # Validate resource exists
            if resource_key not in structured_data:
                return JsonResponse({
                    'success': False,
                    'error': f'No {resource_key} found in structured data'
                }, status=400)
            
            resources = structured_data[resource_key]
            if not isinstance(resources, list) or resource_index >= len(resources):
                return JsonResponse({
                    'success': False,
                    'error': f'Invalid resource index {resource_index} for {resource_key}'
                }, status=400)
            
            # Get the specific resource
            resource = resources[resource_index]
            old_date = resource.get(date_field)
            is_new = old_date is None
            
            # Update the date field
            resource[date_field] = parsed_date.isoformat()
            
            # Mark as manually entered by adding metadata
            if 'date_metadata' not in resource:
                resource['date_metadata'] = {}
            
            resource['date_metadata']['source'] = 'manual'
            resource['date_metadata']['entered_by'] = request.user.username
            resource['date_metadata']['entered_at'] = timezone.now().isoformat()
            resource['date_metadata']['verified'] = False
            
            # Save back to database
            parsed_data.save(update_fields=['corrections', 'updated_at'])
            
            # Log the action for HIPAA audit trail
            from apps.core.models import AuditLog
            AuditLog.log_event(
                event_type='phi_update',
                user=request.user,
                request=request,
                description=f"{'Updated' if not is_new else 'Added'} clinical date for {resource_type} in document {document.id}",
                details={
                    'parsed_data_id': str(parsed_data.id),
                    'document_id': str(document.id),
                    'resource_type': resource_type,
                    'resource_index': resource_index,
                    'resource_name': resource.get('name') or resource.get('test_name') or resource.get('measurement'),
                    'clinical_date': parsed_date.isoformat(),
                    'old_date': old_date,
                    'date_source': 'manual',
                    'action': 'update' if not is_new else 'create',
                },
                patient_mrn=document.patient.mrn if hasattr(document, 'patient') and document.patient else None,
                phi_involved=True,
                content_object=parsed_data,
                severity='info'
            )
            
            logger.info(f"Clinical date {'updated' if not is_new else 'saved'} for {resource_type}[{resource_index}] in ParsedData {parsed_data.id} by user {request.user.id}: {parsed_date}")
            
            return JsonResponse({
                'success': True,
                'message': 'Clinical date saved successfully',
                'clinical_date': parsed_date.isoformat(),
                'date_source': 'manual',
                'date_status': 'pending',
                'resource_type': resource_type,
                'resource_index': resource_index
            })
            
        except Exception as save_error:
            logger.error(f"Error saving clinical date for {resource_type}[{resource_index}] in ParsedData {parsed_data.id}: {save_error}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'error': f'Failed to save clinical date: {str(save_error)}'
            }, status=500)
    
    except Http404:
        # Return JSON 404 for API consistency
        return JsonResponse({
            'success': False,
            'error': 'Document or parsed data not found'
        }, status=404)
    
    except Exception as e:
        logger.error(f"Unexpected error saving clinical date: {e}")
        return JsonResponse({
            'success': False,
            'error': 'An unexpected error occurred'
        }, status=500)


@require_POST
def verify_clinical_date(request):
    """
    Verify a clinical date for parsed data.
    
    Args:
        request: HTTP POST request with:
            - parsed_data_id: ID of the ParsedData object
            - document_id: ID of the source document (for permissions)
    
    Returns:
        JsonResponse: Success status and message
    """
    try:
        # Get and validate parameters
        parsed_data_id = request.POST.get('parsed_data_id')
        document_id = request.POST.get('document_id')
        
        if not all([parsed_data_id, document_id]):
            return JsonResponse({
                'success': False,
                'error': 'Missing required parameters'
            }, status=400)
        
        # Get the document for permission checking
        document = get_object_or_404(Document, id=document_id)
        
        # Verify user has permission to review documents
        if not request.user.has_perm('documents.change_document'):
            return JsonResponse({
                'success': False,
                'error': 'Permission denied'
            }, status=403)
        
        # Get the ParsedData object
        parsed_data = get_object_or_404(ParsedData, id=parsed_data_id, document=document)
        
        # Check if there's a clinical date to verify
        if not parsed_data.has_clinical_date():
            return JsonResponse({
                'success': False,
                'error': 'No clinical date to verify'
            }, status=400)
        
        # Verify the clinical date
        try:
            parsed_data.verify_clinical_date()
            
            # Log the action for HIPAA audit trail using proper event types
            from apps.core.models import AuditLog
            AuditLog.log_event(
                event_type='phi_update',
                user=request.user,
                request=request,
                description=f"Verified clinical date for document {document.id}",
                details={
                    'parsed_data_id': str(parsed_data.id),
                    'document_id': str(document.id),
                    'clinical_date': parsed_data.clinical_date.isoformat(),
                    'action': 'verify',
                    'previous_status': 'pending',
                    'new_status': 'verified',
                },
                patient_mrn=document.patient.mrn if hasattr(document, 'patient') and document.patient else None,
                phi_involved=True,
                content_object=parsed_data,
                severity='info'
            )
            
            logger.info(f"Clinical date verified for ParsedData {parsed_data.id} by user {request.user.id}")
            
            return JsonResponse({
                'success': True,
                'message': 'Clinical date verified successfully',
                'date_status': 'verified'
            })
            
        except Exception as verify_error:
            logger.error(f"Error verifying clinical date for ParsedData {parsed_data.id}: {verify_error}")
            return JsonResponse({
                'success': False,
                'error': f'Failed to verify clinical date: {str(verify_error)}'
            }, status=500)
    
    except Http404:
        # Return JSON 404 for API consistency
        return JsonResponse({
            'success': False,
            'error': 'Document or parsed data not found'
        }, status=404)
    
    except Exception as e:
        logger.error(f"Unexpected error verifying clinical date: {e}")
        return JsonResponse({
            'success': False,
            'error': 'An unexpected error occurred'
        }, status=500)