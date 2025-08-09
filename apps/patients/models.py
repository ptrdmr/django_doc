"""
Patient models for the medical document parser.

⚠️  CRITICAL SECURITY WARNING ⚠️
===============================
This implementation stores sensitive PHI (Protected Health Information) 
in PLAIN TEXT for development purposes only. Before deploying to production 
or handling real patient data, the following fields MUST be encrypted:

- Patient.first_name
- Patient.last_name  
- Patient.ssn

HIPAA COMPLIANCE REQUIREMENT:
All PHI must be encrypted at rest. This is not optional for production use.

TODO: Implement field-level encryption using a library like:
- django-cryptography (with proper Django 5 compatibility)
- django-fernet-fields
- Custom encryption solution

DO NOT use this code with real patient data until encryption is implemented.
===============================
"""

import uuid
from django.db import models
from django.utils import timezone
from django.conf import settings

from apps.core.models import BaseModel, MedicalRecord


class Patient(MedicalRecord):
    """
    Patient model for storing demographic and medical information.
    
    Note: In production, sensitive fields like first_name, last_name, 
    and ssn should be encrypted. For now, using plain text to get 
    the basic functionality working.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Patient identification
    mrn = models.CharField(max_length=50, unique=True, help_text="Medical Record Number")
    
    # Demographics (TODO: Add encryption in future)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    date_of_birth = models.DateField()
    gender = models.CharField(
        max_length=1, 
        choices=[('M', 'Male'), ('F', 'Female'), ('O', 'Other')],
        blank=True
    )
    
    # Optional sensitive data (TODO: Add encryption)
    ssn = models.CharField(max_length=11, blank=True, null=True)
    
    # FHIR data storage
    cumulative_fhir_json = models.JSONField(default=dict, blank=True)
    
    class Meta:
        db_table = 'patients'
        indexes = [
            models.Index(fields=['mrn']),
            models.Index(fields=['date_of_birth']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = "Patient"
        verbose_name_plural = "Patients"
    
    def __str__(self):
        return f"Patient {self.mrn}"
    
    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('patients:detail', kwargs={'pk': self.pk})


class PatientHistory(BaseModel):
    """
    Audit trail for patient record changes.
    Tracks all modifications to patient data for compliance.
    """
    patient = models.ForeignKey(
        Patient, 
        on_delete=models.PROTECT,
        related_name='history_records'
    )
    
    # ============================================================================
    # DOCUMENT FIELD - TEMPORARILY COMMENTED OUT
    # ============================================================================
    # The document field is commented out because the Document model hasn't been
    # created yet (that's handled in a different task). When we implement the
    # Document model in the documents app, we'll need to:
    # 1. Uncomment this field
    # 2. Create a new migration to add the document relationship
    # 3. Update any existing PatientHistory records as needed
    #
    # TODO: Uncomment when Task 4 (Document Management) is complete
    # document = models.ForeignKey(
    #     'documents.Document',
    #     on_delete=models.PROTECT,
    #     null=True,
    #     blank=True,
    #     help_text="Source document if this change came from document processing"
    # )
    # ============================================================================
    
    action = models.CharField(
        max_length=50,
        choices=[
            ('created', 'Patient Created'),
            ('updated', 'Patient Updated'),
            ('fhir_append', 'FHIR Resources Added'),
            ('fhir_history_preserved', 'FHIR Historical Data Preserved'),
            ('document_processed', 'Document Processed'),
        ]
    )
    fhir_version = models.CharField(max_length=20, default='4.0.1')
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True
    )
    fhir_delta = models.JSONField(
        default=list,
        blank=True,
        help_text="FHIR resources added in this change"
    )
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'patient_history'
        indexes = [
            models.Index(fields=['patient', 'changed_at']),
            models.Index(fields=['action', 'changed_at']),
        ]
        verbose_name = "Patient History"
        verbose_name_plural = "Patient Histories"
    
    def __str__(self):
        return f"{self.patient.mrn} - {self.action} at {self.changed_at}"
    
    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('patients:history-detail', kwargs={'pk': self.pk})
