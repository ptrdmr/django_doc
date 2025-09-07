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

from .models import Document
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
    Document review interface for reviewing extracted data before merging.
    
    This view displays the document preview alongside extracted data forms
    for user review and approval.
    """
    model = Document
    template_name = 'documents/review.html'
    context_object_name = 'document'
    
    def get_queryset(self):
        """
        Filter documents to only those the user has access to.
        
        Returns:
            QuerySet: Filtered documents
        """
        return Document.objects.filter(
            created_by=self.request.user
        ).select_related('patient').prefetch_related('providers')
    
    def get_context_data(self, **kwargs):
        """
        Add additional context for the review template.
        
        Returns:
            dict: Enhanced context data
        """
        context = super().get_context_data(**kwargs)
        
        # Add any extracted data or additional context needed for review
        # This will be expanded in later subtasks
        
        return context