"""
Report generator classes for creating various report types.

Base classes and concrete implementations for generating reports
in multiple formats (PDF, CSV, JSON) from patient and system data.
"""

import os
import csv
import json
from datetime import datetime
from io import BytesIO, StringIO
from typing import Dict, Any, Optional

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

# Try WeasyPrint first, fall back to ReportLab
try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    WEASYPRINT_AVAILABLE = False
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib import colors

from apps.patients.models import Patient


class ReportGenerator:
    """
    Base class for all report generators.
    
    Implements template method pattern where subclasses override
    generate() to provide report-specific data extraction.
    """
    
    def __init__(self, parameters: Optional[Dict[str, Any]] = None):
        """
        Initialize report generator with parameters.
        
        Args:
            parameters: Dict of report parameters (filters, options, etc.)
        """
        self.parameters = parameters or {}
        self.title = "Base Report"
        self.description = "Base report description"
        self.data = None
    
    def generate(self) -> Dict[str, Any]:
        """
        Generate report data.
        
        Must be implemented by subclasses to return structured data.
        
        Returns:
            Dict containing report data
            
        Raises:
            NotImplementedError: If subclass doesn't implement
        """
        raise NotImplementedError("Subclasses must implement generate()")
    
    def to_pdf(self, output_path: str) -> str:
        """
        Convert report data to PDF format.
        
        Args:
            output_path: Where to save the PDF file
            
        Returns:
            Path to generated PDF file
        """
        if not self.data:
            self.data = self.generate()
        
        generator = PDFGenerator()
        return generator.generate(self.data, output_path, self.title)
    
    def to_csv(self, output_path: str) -> str:
        """
        Convert report data to CSV format.
        
        Args:
            output_path: Where to save the CSV file
            
        Returns:
            Path to generated CSV file
        """
        if not self.data:
            self.data = self.generate()
        
        generator = CSVGenerator()
        return generator.generate(self.data, output_path)
    
    def to_json(self, output_path: str) -> str:
        """
        Convert report data to JSON format.
        
        Args:
            output_path: Where to save the JSON file
            
        Returns:
            Path to generated JSON file
        """
        if not self.data:
            self.data = self.generate()
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, default=str)
        
        return output_path


class PDFGenerator:
    """
    Utility class for generating PDF reports using WeasyPrint.
    
    Converts HTML templates with medical data into professional
    HIPAA-compliant PDF documents.
    """
    
    def __init__(self, template: Optional[str] = None):
        """
        Initialize PDF generator.
        
        Args:
            template: Optional template name (defaults to report type template)
        """
        self.template = template
    
    def generate(self, data: Dict[str, Any], output_path: str, title: str = "Report") -> str:
        """
        Generate PDF from report data.
        
        Args:
            data: Report data dict
            output_path: Where to save the PDF
            title: Report title for the document
            
        Returns:
            Path to generated PDF file
        """
        if WEASYPRINT_AVAILABLE:
            return self._generate_with_weasyprint(data, output_path, title)
        else:
            return self._generate_with_reportlab(data, output_path, title)
    
    def _generate_with_weasyprint(self, data: Dict[str, Any], output_path: str, title: str) -> str:
        """Generate PDF using WeasyPrint (HTML to PDF)."""
        # Determine template based on report type
        if not self.template:
            report_type = data.get('report_metadata', {}).get('report_type', 'patient_summary')
            self.template = f'reports/pdf/{report_type}.html'
        
        # Render HTML from template
        html_content = render_to_string(self.template, {
            'data': data,
            'title': title,
            'generated_at': timezone.now(),
        })
        
        # Convert HTML to PDF using WeasyPrint
        html = HTML(string=html_content, base_url=settings.STATIC_URL)
        
        # Apply medical report styling
        css = CSS(string=self._get_pdf_styles())
        
        # Generate PDF
        html.write_pdf(output_path, stylesheets=[css])
        
        return output_path
    
    def _generate_with_reportlab(self, data: Dict[str, Any], output_path: str, title: str) -> str:
        """Generate PDF using ReportLab with all 7 clinical summary sections."""
        doc = SimpleDocTemplate(output_path, pagesize=letter,
                               topMargin=0.75*inch, bottomMargin=0.75*inch)

        story = []
        styles = getSampleStyleSheet()

        styles.add(ParagraphStyle(
            name='CustomTitle', parent=styles['Heading1'],
            fontSize=20, textColor=colors.HexColor('#2563eb'), spaceAfter=12
        ))
        styles.add(ParagraphStyle(
            name='SectionHeader', parent=styles['Heading2'],
            fontSize=14, textColor=colors.HexColor('#1e40af'),
            spaceBefore=12, spaceAfter=6
        ))
        styles.add(ParagraphStyle(
            name='EmptyState', parent=styles['Normal'],
            fontSize=10, textColor=colors.HexColor('#888888'),
            fontName='Helvetica-Oblique', spaceBefore=4, spaceAfter=4
        ))

        header_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ])

        def _fmt_date(val):
            if not val:
                return 'N/A'
            if hasattr(val, 'strftime'):
                return val.strftime('%m/%d/%Y')
            return str(val)[:10]

        # Title
        story.append(Paragraph(title, styles['CustomTitle']))
        story.append(Spacer(1, 0.2*inch))

        patient_info = data.get('patient_info', {})
        clinical = data.get('clinical_summary', {})

        # --- Section 1: Demographics & Context ---
        story.append(Paragraph("1. Demographics &amp; Context", styles['SectionHeader']))
        primary_dx = patient_info.get('primary_diagnosis')
        dx_name = primary_dx.get('display_name', 'N/A') if primary_dx else 'Not specified'
        dx_code = ''
        if primary_dx and primary_dx.get('codes'):
            dx_code = primary_dx['codes'][0].get('code', 'N/A')

        info_data = [
            ['MRN:', str(patient_info.get('mrn', 'N/A'))],
            ['Name:', str(patient_info.get('name', 'N/A'))],
            ['Age:', str(patient_info.get('age', 'N/A'))],
            ['Gender:', str(patient_info.get('gender', 'N/A'))],
            ['DOB:', _fmt_date(patient_info.get('date_of_birth'))],
            ['Living Setting:', str(patient_info.get('living_setting', 'N/A'))],
            ['Primary Diagnosis:', str(dx_name)],
            ['ICD-10:', str(dx_code or 'N/A')],
            ['Initial Diagnosis Date:', _fmt_date(patient_info.get('initial_diagnosis_date'))],
        ]
        info_table = Table(info_data, colWidths=[1.8*inch, 4.2*inch])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f1f5f9')),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#475569')),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(info_table)

        comorbidities = patient_info.get('comorbidities', [])
        if comorbidities:
            names = '; '.join(c.get('display_name', '') for c in comorbidities if c.get('display_name'))
            story.append(Spacer(1, 0.05*inch))
            story.append(Paragraph(f"<b>Comorbidities:</b> {names}", styles['Normal']))
        story.append(Spacer(1, 0.15*inch))

        # --- Section 2: Diagnoses with Onset Dates ---
        story.append(Paragraph("2. Diagnoses with Clinical Onset Dates", styles['SectionHeader']))
        conditions = clinical.get('conditions', [])
        if conditions:
            cond_data = [['Condition', 'ICD-10', 'Onset Date']]
            for c in conditions:
                cond_data.append([
                    str(c.get('display_name', 'Unknown'))[:50],
                    str(c.get('codes', [{}])[0].get('code', 'N/A') if c.get('codes') else 'N/A'),
                    _fmt_date(c.get('onset_date')),
                ])
            cond_table = Table(cond_data, colWidths=[3*inch, 1.2*inch, 1.8*inch])
            cond_table.setStyle(header_style)
            story.append(cond_table)
        else:
            story.append(Paragraph("No diagnoses recorded", styles['EmptyState']))
        story.append(Spacer(1, 0.15*inch))

        # --- Section 3: Weight Tracking ---
        story.append(Paragraph("3. Weight Tracking", styles['SectionHeader']))
        weight = clinical.get('weight_timeline', {})
        if weight.get('has_data') and weight.get('data_points'):
            unit = weight.get('unit', '')
            wt_data = [['Date', f'Weight ({unit})']]
            for pt in weight['data_points']:
                wt_data.append([_fmt_date(pt.get('date')), str(pt.get('weight', '—'))])
            wt_table = Table(wt_data, colWidths=[3*inch, 3*inch])
            wt_table.setStyle(header_style)
            story.append(wt_table)
        else:
            story.append(Paragraph("No weight data recorded", styles['EmptyState']))
        story.append(Spacer(1, 0.15*inch))

        # --- Section 4: Hospitalizations ---
        story.append(Paragraph("4. Hospitalizations", styles['SectionHeader']))
        encounters = clinical.get('encounters', [])
        if encounters:
            enc_data = [['Dates', 'Reason', 'Type']]
            for e in encounters:
                period = e.get('period', {})
                start = _fmt_date(period.get('start'))
                end = _fmt_date(period.get('end')) if period.get('end') else 'Ongoing'
                reasons = e.get('reason', [])
                reason_text = reasons[0].get('display', reasons[0].get('code', 'N/A')) if reasons else 'Not specified'
                enc_data.append([
                    f"{start} - {end}",
                    str(reason_text)[:40],
                    str(e.get('class', 'Visit')),
                ])
            enc_table = Table(enc_data, colWidths=[2.2*inch, 2.5*inch, 1.3*inch])
            enc_table.setStyle(header_style)
            story.append(enc_table)
        else:
            story.append(Paragraph("No hospitalizations recorded", styles['EmptyState']))
        story.append(Spacer(1, 0.15*inch))

        # --- Section 5: Labs ---
        story.append(Paragraph("5. Labs", styles['SectionHeader']))
        observations = clinical.get('observations', [])
        if observations:
            obs_data = [['Test', 'Result', 'Date']]
            for o in observations:
                val = o.get('value', '—')
                unit_str = f" {o['unit']}" if o.get('unit') else ''
                obs_data.append([
                    str(o.get('display_name', 'Unknown'))[:40],
                    f"{val}{unit_str}",
                    _fmt_date(o.get('effective_date')),
                ])
            obs_table = Table(obs_data, colWidths=[2.5*inch, 2*inch, 1.5*inch])
            obs_table.setStyle(header_style)
            story.append(obs_table)
        else:
            story.append(Paragraph("No lab results recorded", styles['EmptyState']))
        story.append(Spacer(1, 0.15*inch))

        # --- Section 6: Medications ---
        story.append(Paragraph("6. Medications", styles['SectionHeader']))
        medications = clinical.get('medications', [])
        if medications:
            med_data = [['Medication', 'Dosage', 'Started', 'Status']]
            for m in medications:
                dosage_list = m.get('dosage', [])
                dose_text = 'N/A'
                if dosage_list:
                    dose_text = dosage_list[0].get('text', dosage_list[0].get('dose', 'N/A'))
                period = m.get('effective_period') or {}
                med_data.append([
                    str(m.get('display_name', 'Unknown'))[:35],
                    str(dose_text)[:25],
                    _fmt_date(period.get('start')),
                    str(m.get('status', 'N/A')),
                ])
            med_table = Table(med_data, colWidths=[2*inch, 1.6*inch, 1.2*inch, 1.2*inch])
            med_table.setStyle(header_style)
            story.append(med_table)
        else:
            story.append(Paragraph("No medications recorded", styles['EmptyState']))
        story.append(Spacer(1, 0.15*inch))

        # --- Section 7: Procedures ---
        story.append(Paragraph("7. Procedures", styles['SectionHeader']))
        procedures = clinical.get('procedures', [])
        if procedures:
            proc_data = [['Procedure', 'Date', 'Outcome']]
            for p in procedures:
                proc_data.append([
                    str(p.get('display_name', 'Unknown'))[:40],
                    _fmt_date(p.get('performed_date')),
                    str(p.get('outcome', 'Completed'))[:25],
                ])
            proc_table = Table(proc_data, colWidths=[3*inch, 1.5*inch, 1.5*inch])
            proc_table.setStyle(header_style)
            story.append(proc_table)
        else:
            story.append(Paragraph("No procedures recorded", styles['EmptyState']))

        # Footer
        story.append(Spacer(1, 0.3*inch))
        story.append(Paragraph(
            "<i>This report contains Protected Health Information (PHI). "
            "Handle in accordance with HIPAA regulations. "
            "CONFIDENTIAL — For authorized personnel only.</i>",
            styles['Normal']
        ))
        generated_at = data.get('report_metadata', {}).get('generated_at', '')
        story.append(Paragraph(f"<i>Generated: {generated_at}</i>", styles['Normal']))

        doc.build(story)
        return output_path
    
    def generate_weight_chart_image(self, weight_data: Dict[str, Any]) -> Optional[str]:
        """
        Generate weight chart as base64-encoded PNG for PDF inclusion.
        
        Args:
            weight_data: Dict with dates, weights, unit, and has_data keys
            
        Returns:
            str: Base64 encoded PNG image data URI, or None if no data
        """
        if not weight_data.get('has_data'):
            return None
        
        try:
            import matplotlib
            matplotlib.use('Agg')  # Use non-GUI backend
            import matplotlib.pyplot as plt
            import io
            import base64
            
            dates = weight_data['dates']
            weights = weight_data['weights']
            unit = weight_data['unit']
            
            # Create figure
            fig, ax = plt.subplots(figsize=(6, 3))
            ax.plot(dates, weights, marker='o', color='#4a90e2', linewidth=2, markersize=6)
            ax.set_xlabel('Date', fontsize=10)
            ax.set_ylabel(f"Weight ({unit})", fontsize=10)
            ax.set_title('Weight Trend', fontsize=12, fontweight='bold', pad=10)
            ax.grid(True, alpha=0.3, linestyle='--')
            
            # Format x-axis labels
            plt.xticks(rotation=45, ha='right', fontsize=9)
            plt.yticks(fontsize=9)
            plt.tight_layout()
            
            # Convert to base64
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100, bbox_inches='tight', facecolor='white')
            buf.seek(0)
            image_base64 = base64.b64encode(buf.read()).decode('utf-8')
            plt.close(fig)
            
            return f"data:image/png;base64,{image_base64}"
            
        except ImportError:
            # matplotlib not installed, return None
            return None
        except Exception as e:
            # Log error but don't break report generation
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Error generating weight chart: {e}")
            return None
    
    def _get_pdf_styles(self) -> str:
        """
        Get CSS styles for medical PDF reports.
        
        Returns:
            CSS string with medical report styling
        """
        return """
        @page {
            size: letter;
            margin: 1in 0.75in;
            
            @top-right {
                content: "Page " counter(page) " of " counter(pages);
                font-size: 9pt;
                color: #666;
            }
            
            @bottom-center {
                content: "CONFIDENTIAL - HIPAA Protected Health Information";
                font-size: 8pt;
                color: #999;
                border-top: 1px solid #ddd;
                padding-top: 0.25in;
            }
        }
        
        body {
            font-family: 'Helvetica', 'Arial', sans-serif;
            font-size: 10pt;
            line-height: 1.4;
            color: #333;
        }
        
        h1 {
            color: #2563eb;
            font-size: 20pt;
            margin-bottom: 0.25in;
            border-bottom: 2px solid #2563eb;
            padding-bottom: 0.1in;
        }
        
        h2 {
            color: #1e40af;
            font-size: 14pt;
            margin-top: 0.2in;
            margin-bottom: 0.1in;
            border-bottom: 1px solid #ddd;
            padding-bottom: 5pt;
        }
        
        h3 {
            color: #1e3a8a;
            font-size: 12pt;
            margin-top: 0.15in;
            margin-bottom: 0.05in;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 0.1in 0;
            font-size: 9pt;
        }
        
        th {
            background-color: #f1f5f9;
            color: #1e40af;
            padding: 8pt;
            text-align: left;
            border-bottom: 2px solid #cbd5e1;
            font-weight: bold;
        }
        
        td {
            padding: 6pt 8pt;
            border-bottom: 1px solid #e2e8f0;
        }
        
        tr:nth-child(even) {
            background-color: #f8fafc;
        }
        
        .section {
            margin-bottom: 0.15in;
        }
        
        .label {
            font-weight: bold;
            color: #475569;
            margin-right: 0.1in;
        }
        
        .value {
            color: #333;
        }
        
        .header-info {
            background-color: #f1f5f9;
            padding: 0.15in;
            margin-bottom: 0.2in;
            border-radius: 4pt;
        }
        
        .clinical-section {
            page-break-inside: avoid;
            margin-bottom: 0.15in;
        }
        
        .empty-state {
            color: #94a3b8;
            font-style: italic;
            padding: 0.1in;
        }
        """


class CSVGenerator:
    """
    Utility class for generating CSV reports.
    
    Converts structured report data into tabular CSV format
    for import into spreadsheet applications.
    """
    
    def generate(self, data: Dict[str, Any], output_path: str) -> str:
        """
        Generate CSV from report data.
        
        Args:
            data: Report data dict
            output_path: Where to save the CSV
            
        Returns:
            Path to generated CSV file
        """
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            
            # Determine format based on report type
            report_type = data.get('report_metadata', {}).get('report_type', 'patient_summary')
            
            if report_type == 'patient_summary':
                self._write_patient_summary_csv(data, writer)
            elif report_type == 'provider_activity':
                self._write_provider_activity_csv(data, writer)
            elif report_type == 'document_audit':
                self._write_document_audit_csv(data, writer)
        
        return output_path
    
    def _write_patient_summary_csv(self, data: Dict[str, Any], writer):
        """Write patient summary data as CSV."""
        # Patient info section
        writer.writerow(['Patient Information'])
        writer.writerow(['MRN', data['patient_info'].get('mrn', '')])
        writer.writerow(['Name', data['patient_info'].get('name', '')])
        writer.writerow(['Age', data['patient_info'].get('age', '')])
        writer.writerow(['Gender', data['patient_info'].get('gender', '')])
        writer.writerow([])
        
        # Conditions
        writer.writerow(['Conditions'])
        writer.writerow(['Display Name', 'Status', 'Onset Date', 'Severity'])
        for condition in data['clinical_summary'].get('conditions', []):
            writer.writerow([
                condition.get('display_name', ''),
                condition.get('status', ''),
                condition.get('onset_date', ''),
                condition.get('severity', '')
            ])
        writer.writerow([])
        
        # Medications
        writer.writerow(['Medications'])
        writer.writerow(['Medication Name', 'Status', 'Dosage'])
        for med in data['clinical_summary'].get('medications', []):
            dosage_text = ', '.join([d.get('text', '') for d in med.get('dosage', [])])
            writer.writerow([
                med.get('display_name', ''),
                med.get('status', ''),
                dosage_text
            ])
        writer.writerow([])
        
        # Observations
        writer.writerow(['Observations'])
        writer.writerow(['Test Name', 'Value', 'Unit', 'Date', 'Interpretation'])
        for obs in data['clinical_summary'].get('observations', []):
            interp = ', '.join(obs.get('interpretation', [])) if obs.get('interpretation') else ''
            writer.writerow([
                obs.get('display_name', ''),
                obs.get('value', ''),
                obs.get('unit', ''),
                obs.get('effective_date', ''),
                interp
            ])
    
    def _write_provider_activity_csv(self, data: Dict[str, Any], writer):
        """Write provider activity data as CSV."""
        writer.writerow(['Provider Activity Report'])
        writer.writerow(['Generated:', data.get('report_metadata', {}).get('generated_at', '')])
        writer.writerow([])
        # Implementation for provider activity
        pass
    
    def _write_document_audit_csv(self, data: Dict[str, Any], writer):
        """Write document audit data as CSV."""
        writer.writerow(['Document Processing Audit'])
        writer.writerow(['Generated:', data.get('report_metadata', {}).get('generated_at', '')])
        writer.writerow([])
        # Implementation for document audit
        pass


class PatientReportTemplate(ReportGenerator):
    """
    Generate comprehensive patient summary reports.
    
    Pulls complete patient medical history from encrypted FHIR
    bundle and formats it for PDF/CSV export.
    """
    
    def __init__(self, parameters: Optional[Dict[str, Any]] = None):
        """
        Initialize patient report generator.
        
        Args:
            parameters: Dict with 'patient_id' (required) and optional filters
        """
        super().__init__(parameters)
        self.title = "Patient Summary Report"
        self.description = "Comprehensive medical history for patient"
    
    def generate(self) -> Dict[str, Any]:
        """
        Generate patient summary report data.
        
        Returns:
            Dict with patient demographics, conditions, medications,
            observations, procedures, encounters, and providers
            
        Raises:
            ValueError: If patient_id not provided or patient not found
        """
        patient_id = self.parameters.get('patient_id')
        if not patient_id:
            raise ValueError("patient_id is required in parameters")
        
        try:
            patient = Patient.objects.get(pk=patient_id)
        except Patient.DoesNotExist:
            raise ValueError(f"Patient with ID {patient_id} not found")
        
        # Use existing get_comprehensive_report method
        report_data = patient.get_comprehensive_report()
        
        # Add report metadata
        report_data['report_metadata']['report_type'] = 'patient_summary'
        report_data['report_metadata']['parameters'] = self.parameters
        report_data['report_metadata']['title'] = self.title
        
        # Apply any filters from parameters
        report_data = self._apply_filters(report_data)
        
        return report_data
    
    def _apply_filters(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply filtering based on parameters.
        
        Args:
            data: Unfiltered report data
            
        Returns:
            Filtered report data
        """
        # Date range filtering
        date_from = self.parameters.get('date_from')
        date_to = self.parameters.get('date_to')
        
        if date_from or date_to:
            data = self._filter_by_date_range(data, date_from, date_to)
        
        # Include/exclude sections
        include_demographics = self.parameters.get('include_demographics', True)
        if not include_demographics:
            data['patient_info']['contact'] = {}  # Redact contact info
        
        return data
    
    def _filter_by_date_range(self, data: Dict[str, Any], date_from: Optional[str], date_to: Optional[str]) -> Dict[str, Any]:
        """
        Filter clinical data by date range.
        
        Args:
            data: Report data to filter
            date_from: Start date (YYYY-MM-DD) or None
            date_to: End date (YYYY-MM-DD) or None
            
        Returns:
            Filtered report data
        """
        # Filter conditions
        if date_from or date_to:
            data['clinical_summary']['conditions'] = [
                c for c in data['clinical_summary']['conditions']
                if self._date_in_range(c.get('onset_date') or c.get('recorded_date'), date_from, date_to)
            ]
            
            # Filter observations
            data['clinical_summary']['observations'] = [
                o for o in data['clinical_summary']['observations']
                if self._date_in_range(o.get('effective_date'), date_from, date_to)
            ]
            
            # Filter procedures
            data['clinical_summary']['procedures'] = [
                p for p in data['clinical_summary']['procedures']
                if self._date_in_range(p.get('performed_date'), date_from, date_to)
            ]
            
            # Filter encounters
            data['clinical_summary']['encounters'] = [
                e for e in data['clinical_summary']['encounters']
                if self._date_in_range(
                    (e.get('period', {}).get('start') if e.get('period') else None),
                    date_from,
                    date_to
                )
            ]
        
        return data
    
    def _date_in_range(self, date_str: Optional[str], date_from: Optional[str], date_to: Optional[str]) -> bool:
        """
        Check if date falls within range.
        
        Args:
            date_str: Date to check (YYYY-MM-DD format)
            date_from: Start of range or None
            date_to: End of range or None
            
        Returns:
            True if date is in range, False otherwise
        """
        if not date_str:
            return True  # Include items without dates
        
        if date_from and date_str < date_from:
            return False
        
        if date_to and date_str > date_to:
            return False
        
        return True


class ProviderReportTemplate(ReportGenerator):
    """
    Generate provider activity reports.
    
    Shows provider statistics, patient list, and document processing metrics.
    """
    
    def __init__(self, parameters: Optional[Dict[str, Any]] = None):
        super().__init__(parameters)
        self.title = "Provider Activity Report"
        self.description = "Provider statistics and patient activity"
    
    def generate(self) -> Dict[str, Any]:
        """Generate provider activity report data."""
        # TODO: Implement in next phase
        return {
            'report_metadata': {
                'report_type': 'provider_activity',
                'status': 'not_implemented',
                'message': 'Provider reports coming soon'
            }
        }


class DocumentAuditTemplate(ReportGenerator):
    """
    Generate document processing audit reports.
    
    Shows document processing stats, errors, and performance metrics.
    """
    
    def __init__(self, parameters: Optional[Dict[str, Any]] = None):
        super().__init__(parameters)
        self.title = "Document Processing Audit"
        self.description = "Document processing metrics and audit trail"
    
    def generate(self) -> Dict[str, Any]:
        """Generate document audit report data."""
        # TODO: Implement in next phase
        return {
            'report_metadata': {
                'report_type': 'document_audit',
                'status': 'not_implemented',
                'message': 'Document audit reports coming soon'
            }
        }

