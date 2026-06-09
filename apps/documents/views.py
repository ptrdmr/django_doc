"""
Document upload and processing views.
"""
import logging
from django.conf import settings
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
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator

from .models import Document, ParsedData
from .forms import DocumentUploadForm
from apps.patients.models import Patient
from apps.accounts.decorators import moritrac_admin_required
from apps.core.utils import log_user_activity, ActivityTypes

logger = logging.getLogger(__name__)


class OwnedDocumentMixin:
    """Restrict queryset so non-staff users only see their own documents."""

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.request.user.is_staff:
            qs = qs.filter(uploaded_by=self.request.user)
        return qs


@method_decorator([login_required], name='dispatch')
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
    
    def post(self, request, *args, **kwargs):
        # #region agent log
        from apps.core.utils import agent_debug_log
        agent_debug_log(
            'apps/documents/views.py:DocumentUploadView.post',
            'Document upload view reached (CSRF passed)',
            {
                'path': request.path,
                'has_csrf_post': 'csrfmiddlewaretoken' in request.POST,
                'post_token_len': len(request.POST.get('csrfmiddlewaretoken', '')),
                'has_csrf_header': bool(request.META.get('HTTP_X_CSRFTOKEN')),
                'files_keys': list(request.FILES.keys()),
            },
            hypothesis_id='H1,H2,H5',
        )
        # #endregion
        return super().post(request, *args, **kwargs)

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


@method_decorator([login_required], name='dispatch')
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


@method_decorator([login_required], name='dispatch')
class DocumentListView(OwnedDocumentMixin, LoginRequiredMixin, ListView):
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


@method_decorator([login_required], name='dispatch')
class DocumentDetailView(OwnedDocumentMixin, LoginRequiredMixin, DetailView):
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


@method_decorator([login_required], name='dispatch')
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


@method_decorator([login_required], name='dispatch')
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
            large_file_threshold = getattr(
                settings, 'LARGE_DOCUMENT_FILE_SIZE_BYTES', 5 * 1024 * 1024
            )

            # Get processing documents for current user
            processing_docs = Document.objects.filter(
                created_by=request.user,
                status__in=['processing', 'pending', 'ocr_pending']
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
                elapsed_seconds = doc.get_processing_duration()
                processing_data.append({
                    'id': doc.id,
                    'filename': doc.filename,
                    'status': doc.status,
                    'status_display': doc.get_status_display(),
                    'processing_message': doc.processing_message,
                    'patient_name': f"{doc.patient.first_name} {doc.patient.last_name}",
                    'uploaded_at': doc.uploaded_at.isoformat(),
                    'elapsed_seconds': int(elapsed_seconds) if elapsed_seconds is not None else 0,
                    'processing_attempts': doc.processing_attempts,
                    'is_large_document': bool(
                        doc.file_size and doc.file_size >= large_file_threshold
                    ),
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


@method_decorator([login_required], name='dispatch')
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


@method_decorator([login_required], name='dispatch')
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


@method_decorator([login_required], name='dispatch')
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


# ============================================================================
# Development-Only Deletion Views  
# ============================================================================

@method_decorator([moritrac_admin_required], name='dispatch')
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


@method_decorator([moritrac_admin_required], name='dispatch')  
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
                
                # Merge FHIR data immediately (synchronous)
                # Note: In optimistic system, data may already be merged
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


