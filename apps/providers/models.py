"""
Provider models for the medical document parser.

⚠️  CRITICAL SECURITY WARNING ⚠️
===============================
This implementation stores sensitive provider information that may be
considered Protected Health Information (PHI) under HIPAA when it
relates to patient care. While provider information is generally less
sensitive than patient data, certain fields should be secured:

- Provider.first_name
- Provider.last_name  
- Provider.organization

HIPAA COMPLIANCE REQUIREMENT:
Consider encryption for provider data when it contains sensitive
information or when linked to patient records.

TODO: Implement field-level encryption using a library like:
- django-cryptography (with proper Django 5 compatibility)
- django-fernet-fields
- Custom encryption solution

Handle with care when processing provider data linked to patient records.
===============================
"""

import uuid
from django.db import models
from django.utils import timezone
from django.urls import reverse
from django.conf import settings

from apps.core.models import BaseModel, MedicalRecord


class Provider(MedicalRecord):
    """
    Provider model for storing healthcare provider information.
    
    Note: In production, sensitive fields like first_name, last_name, 
    and organization should be encrypted when linked to patient records.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Provider identification
    npi = models.CharField(
        max_length=10, 
        unique=True, 
        verbose_name="NPI Number",
        help_text="National Provider Identifier"
    )
    
    # Provider demographics
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    specialty = models.CharField(max_length=100)
    organization = models.CharField(max_length=200)
    
    class Meta:
        db_table = 'providers'
        indexes = [
            models.Index(fields=['npi']),
            models.Index(fields=['specialty']),
            models.Index(fields=['organization']),
            models.Index(fields=['last_name', 'first_name']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = "Provider"
        verbose_name_plural = "Providers"
    
    @property
    def name(self):
        """
        Full name of the provider.
        """
        return f"{self.first_name} {self.last_name}".strip()
    
    def __str__(self):
        """
        String representation of provider.
        """
        return f"Dr. {self.first_name} {self.last_name} ({self.specialty})"
    
    def get_absolute_url(self):
        """
        Get the absolute URL for provider detail view.
        """
        return reverse('providers:detail', kwargs={'pk': self.pk})
    
    def get_patients(self):
        """
        Return all patients linked to this provider through documents.
        
        TODO: This method will work once the Document and DocumentProvider 
        models are implemented in Task 6. For now, returns empty queryset.
        """
        from apps.patients.models import Patient
        # TODO: Uncomment when Document and DocumentProvider models exist
        # return Patient.objects.filter(
        #     documents__document_providers__provider=self
        # ).distinct()
        return Patient.objects.none()
    
    def get_full_name(self):
        """
        Get the provider's full name.
        """
        return f"{self.first_name} {self.last_name}"
    
    def get_document_count(self):
        """
        Get the count of documents associated with this provider.
        
        TODO: This method will work once the DocumentProvider model is implemented.
        For now, returns 0.
        """
        # TODO: Uncomment when DocumentProvider model exists
        # return self.document_providers.count()
        return 0


# ============================================================================
# DOCUMENT PROVIDER MODEL - TEMPORARILY COMMENTED OUT
# ============================================================================
# The DocumentProvider model is commented out because the Document model hasn't been
# created yet (that's handled in Task 6 - Document Upload and Processing).
# When we implement the Document model in the documents app, we'll need to:
# 1. Uncomment this model
# 2. Create a new migration to add the DocumentProvider relationship
# 3. Update the Provider.get_patients() method to work with the new relationship
#
# TODO: Uncomment when Task 6 (Document Management) is complete
# 
# class DocumentProvider(BaseModel):
#     """
#     Junction model for linking providers to documents.
#     
#     Tracks the relationship between providers and medical documents,
#     including the type of relationship (attending, consulting, etc.).
#     """
#     RELATIONSHIP_CHOICES = [
#         ('attending', 'Attending'),
#         ('consulting', 'Consulting'),
#         ('referring', 'Referring'),
#         ('other', 'Other'),
#     ]
#     
#     # Note: Using string reference to avoid circular import
#     document = models.ForeignKey(
#         'documents.Document', 
#         on_delete=models.CASCADE,
#         related_name='document_providers'
#     )
#     provider = models.ForeignKey(
#         Provider, 
#         on_delete=models.CASCADE,
#         related_name='document_providers'
#     )
#     relationship_type = models.CharField(
#         max_length=20, 
#         choices=RELATIONSHIP_CHOICES,
#         default='other'
#     )
#     
#     class Meta:
#         db_table = 'document_providers'
#         unique_together = ['document', 'provider']
#         indexes = [
#             models.Index(fields=['document', 'provider']),
#             models.Index(fields=['provider', 'relationship_type']),
#             models.Index(fields=['created_at']),
#         ]
#         verbose_name = "Document Provider"
#         verbose_name_plural = "Document Providers"
#     
#     def __str__(self):
#         """
#         String representation of document-provider relationship.
#         """
#         return f"{self.provider.get_full_name()} - {self.get_relationship_type_display()}"
# ============================================================================


class ProviderHistory(BaseModel):
    """
    Audit trail for provider record changes.
    Tracks all modifications to provider data for compliance.
    """
    provider = models.ForeignKey(
        Provider, 
        on_delete=models.PROTECT,
        related_name='history_records'
    )
    
    action = models.CharField(
        max_length=50,
        choices=[
            ('created', 'Provider Created'),
            ('updated', 'Provider Updated'),
            ('linked_to_document', 'Linked to Document'),
            ('unlinked_from_document', 'Unlinked from Document'),
        ]
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True
    )
    changes = models.JSONField(
        default=dict,
        blank=True,
        help_text="Details of what changed"
    )
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'provider_history'
        indexes = [
            models.Index(fields=['provider', 'changed_at']),
            models.Index(fields=['action', 'changed_at']),
        ]
        verbose_name = "Provider History"
        verbose_name_plural = "Provider Histories"
    
    def __str__(self):
        """
        String representation of provider history entry.
        """
        return f"{self.provider.npi} - {self.action} at {self.changed_at}"
