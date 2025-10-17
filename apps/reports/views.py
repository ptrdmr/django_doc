"""
Views for the reports module.

Handles report configuration, generation, and download functionality.
"""

import os
import time
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, DetailView, FormView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import HttpResponse, FileResponse, Http404
from django.urls import reverse_lazy, reverse
from django.conf import settings
from django.utils import timezone

from .models import ReportConfiguration, GeneratedReport
from .forms import (
    PatientReportParametersForm,
    ProviderReportParametersForm,
    DocumentAuditParametersForm,
    ReportConfigurationForm
)
from .generators import (
    PatientReportTemplate,
    ProviderReportTemplate,
    DocumentAuditTemplate
)


class ReportDashboardView(LoginRequiredMixin, ListView):
    """
    Main reports dashboard showing saved configurations and recent reports.
    """
    model = ReportConfiguration
    template_name = 'reports/dashboard.html'
    context_object_name = 'report_configs'
    paginate_by = 10
    
    def get_queryset(self):
        """Get user's report configurations."""
        return ReportConfiguration.objects.filter(
            created_by=self.request.user
        ).order_by('-is_favorite', '-created_at')
    
    def get_context_data(self, **kwargs):
        """Add recent reports to context."""
        context = super().get_context_data(**kwargs)
        
        # Get recent reports
        context['recent_reports'] = GeneratedReport.objects.filter(
            created_by=self.request.user
        ).select_related('configuration').order_by('-created_at')[:10]
        
        # Get report type counts
        context['report_types'] = [
            {
                'value': 'patient_summary',
                'label': 'Patient Summary',
                'description': 'Comprehensive patient medical history report',
                'icon': 'user-circle',
            },
            {
                'value': 'provider_activity',
                'label': 'Provider Activity',
                'description': 'Provider statistics and patient list',
                'icon': 'briefcase',
                'disabled': True,  # Not yet implemented
            },
            {
                'value': 'document_audit',
                'label': 'Document Audit',
                'description': 'Document processing metrics and audit trail',
                'icon': 'document-text',
                'disabled': True,  # Not yet implemented
            },
        ]
        
        return context


class GenerateReportView(LoginRequiredMixin, FormView):
    """
    View for generating reports with parameter selection.
    """
    template_name = 'reports/generate.html'
    success_url = reverse_lazy('reports:dashboard')
    
    def get_form_class(self):
        """Return appropriate form based on report type."""
        report_type = self.request.GET.get('type', 'patient_summary')
        
        forms = {
            'patient_summary': PatientReportParametersForm,
            'provider_activity': ProviderReportParametersForm,
            'document_audit': DocumentAuditParametersForm,
        }
        
        return forms.get(report_type, PatientReportParametersForm)
    
    def get_form_kwargs(self):
        """Pass user to form for queryset filtering."""
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def get_context_data(self, **kwargs):
        """Add report type info to context."""
        context = super().get_context_data(**kwargs)
        context['report_type'] = self.request.GET.get('type', 'patient_summary')
        context['report_type_display'] = {
            'patient_summary': 'Patient Summary Report',
            'provider_activity': 'Provider Activity Report',
            'document_audit': 'Document Processing Audit',
        }.get(context['report_type'], 'Report')
        return context
    
    def form_valid(self, form):
        """Generate report when form is valid."""
        report_type = self.request.GET.get('type', 'patient_summary')
        parameters = form.cleaned_data.copy()  # Make a copy to modify
        output_format = parameters.get('format', 'pdf')
        
        # Convert model objects to IDs for serialization
        if 'patient' in parameters and parameters['patient']:
            parameters['patient_id'] = str(parameters['patient'].id)
            del parameters['patient']  # Remove the model object
        
        if 'provider' in parameters and parameters['provider']:
            parameters['provider_id'] = str(parameters['provider'].id)
            del parameters['provider']  # Remove the model object
        
        # Convert date objects to strings for serialization
        if 'date_from' in parameters and parameters['date_from']:
            parameters['date_from'] = parameters['date_from'].isoformat()
        
        if 'date_to' in parameters and parameters['date_to']:
            parameters['date_to'] = parameters['date_to'].isoformat()
        
        try:
            # Generate report
            start_time = time.time()
            report_data, file_path, file_size = self._generate_report(
                report_type, parameters, output_format
            )
            generation_time = time.time() - start_time
            
            # Create configuration if requested
            config = self._create_configuration_if_requested(report_type, parameters)
            
            # Save generated report record
            generated_report = GeneratedReport.objects.create(
                configuration=config if config else None,
                file_path=file_path,
                format=output_format,
                file_size=file_size,
                generation_time=generation_time,
                parameters_snapshot=parameters,
                status='completed',
                created_by=self.request.user
            )
            
            messages.success(
                self.request,
                f'Report generated successfully in {generation_time:.2f} seconds!'
            )
            
            # Redirect to download
            return redirect('reports:download', pk=generated_report.pk)
            
        except Exception as e:
            messages.error(
                self.request,
                f'Error generating report: {str(e)}'
            )
            return self.form_invalid(form)
    
    def _generate_report(self, report_type: str, parameters: dict, output_format: str):
        """
        Generate report file and return data, path, and size.
        
        Returns:
            Tuple of (report_data, file_path, file_size)
        """
        # Select appropriate generator
        generators = {
            'patient_summary': PatientReportTemplate,
            'provider_activity': ProviderReportTemplate,
            'document_audit': DocumentAuditTemplate,
        }
        
        generator_class = generators.get(report_type, PatientReportTemplate)
        generator = generator_class(parameters)
        
        # Create output directory
        report_dir = os.path.join(settings.MEDIA_ROOT, 'reports', str(self.request.user.id))
        os.makedirs(report_dir, exist_ok=True)
        
        # Generate filename
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{report_type}_{timestamp}.{output_format}'
        file_path = os.path.join(report_dir, filename)
        
        # Generate report in requested format
        if output_format == 'pdf':
            generator.to_pdf(file_path)
        elif output_format == 'csv':
            generator.to_csv(file_path)
        elif output_format == 'json':
            generator.to_json(file_path)
        
        # Get file size
        file_size = os.path.getsize(file_path)
        
        # Get report data
        report_data = generator.data
        
        # Return relative path from MEDIA_ROOT
        relative_path = os.path.relpath(file_path, settings.MEDIA_ROOT)
        
        return report_data, relative_path, file_size
    
    def _create_configuration_if_requested(self, report_type: str, parameters: dict):
        """Create configuration if user wants to save it."""
        save_config = self.request.POST.get('save_config')
        if not save_config:
            return None
        
        config_name = self.request.POST.get('config_name', f'{report_type}_{timezone.now().strftime("%Y-%m-%d")}')
        
        config = ReportConfiguration.objects.create(
            name=config_name,
            report_type=report_type,
            parameters=parameters,
            created_by=self.request.user
        )
        
        return config


class ReportDetailView(LoginRequiredMixin, DetailView):
    """
    View for displaying report details and preview.
    """
    model = GeneratedReport
    template_name = 'reports/detail.html'
    context_object_name = 'report'
    
    def get_queryset(self):
        """Ensure users can only view their own reports."""
        return GeneratedReport.objects.filter(created_by=self.request.user)


class ReportPreviewView(LoginRequiredMixin, View):
    """
    View for previewing reports in the browser before downloading.
    """
    
    def get(self, request, pk):
        """Render report as HTML preview."""
        # Get report (checks ownership via queryset)
        report = get_object_or_404(
            GeneratedReport.objects.filter(created_by=request.user),
            pk=pk
        )
        
        # Get the report's parameters to regenerate the data
        parameters = report.parameters_snapshot
        
        # Regenerate report data (don't generate file, just get data)
        from .generators import PatientReportTemplate
        
        if parameters.get('patient_id'):
            generator = PatientReportTemplate(parameters)
            report_data = generator.generate()
            
            # Render HTML preview template
            return render(request, 'reports/preview/patient_summary.html', {
                'report': report,
                'data': report_data,
                'title': 'Patient Summary Report',
                'generated_at': report.created_at,
            })
        
        # Fallback for unsupported report types
        messages.warning(request, 'Preview not available for this report type.')
        return redirect('reports:dashboard')


class ReportDownloadView(LoginRequiredMixin, View):
    """
    View for downloading generated reports.
    """
    
    def get(self, request, pk):
        """Serve report file for download."""
        # Get report (checks ownership via queryset)
        report = get_object_or_404(
            GeneratedReport.objects.filter(created_by=request.user),
            pk=pk
        )
        
        # Construct full file path
        file_path = os.path.join(settings.MEDIA_ROOT, report.file_path)
        
        # Check file exists
        if not os.path.exists(file_path):
            raise Http404("Report file not found")
        
        # Determine content type
        content_types = {
            'pdf': 'application/pdf',
            'csv': 'text/csv',
            'json': 'application/json',
        }
        content_type = content_types.get(report.format, 'application/octet-stream')
        
        # Serve file
        response = FileResponse(
            open(file_path, 'rb'),
            content_type=content_type
        )
        
        # Set download filename
        filename = f"{report.configuration.name if report.configuration else 'report'}_{report.created_at.strftime('%Y%m%d')}.{report.format}"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response


class ConfigurationDeleteView(LoginRequiredMixin, View):
    """
    View for deleting report configurations.
    """
    
    def post(self, request, pk):
        """Delete configuration."""
        config = get_object_or_404(
            ReportConfiguration.objects.filter(created_by=request.user),
            pk=pk
        )
        
        config_name = config.name
        config.delete()
        
        messages.success(request, f'Configuration "{config_name}" deleted successfully.')
        return redirect('reports:dashboard')
