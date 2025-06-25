import uuid
from django.db import models
from django.utils import timezone
from django.conf import settings
from django_crypto_fields.fields import EncryptedCharField

from apps.core.models import BaseModel


class SoftDeleteManager(models.Manager):
    """
    Custom manager to exclude soft-deleted records from default queries.
    """
    def get_queryset(self):
        """
        Return a queryset that excludes records with a `deleted_at` timestamp.
        """
        return super().get_queryset().filter(deleted_at__isnull=True)


class MedicalRecord(BaseModel):
    """
    Abstract base model for all medical data models.
    
    Includes soft-delete functionality and uses the SoftDeleteManager
    to ensure deleted records are not retrieved by default.
    """
    deleted_at = models.DateTimeField(null=True, blank=True)
    
    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        """
        Override the default delete method to perform a soft delete.
        """
        self.deleted_at = timezone.now()
        self.save()

    def undelete(self):
        """
        Restore a soft-deleted record.
        """
        self.deleted_at = None
        self.save()


class Patient(MedicalRecord):
    """
    Stores patient demographic and medical information.

    This model handles sensitive PHI by encrypting identifying fields
    and stores cumulative medical data in a JSONB field as a FHIR bundle.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Encrypted PHI fields for HIPAA compliance
    first_name = EncryptedCharField(max_length=255)
    last_name = EncryptedCharField(max_length=255)
    ssn = EncryptedCharField(max_length=11, blank=True, null=True)
    
    # Non-encrypted fields for searching and identification
    mrn = models.CharField(max_length=50, unique=True, help_text="Medical Record Number")
    date_of_birth = models.DateField()
    
    # Cumulative FHIR bundle for storing all patient-related FHIR resources
    cumulative_fhir_json = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'patients'
        verbose_name = "Patient"
        verbose_name_plural = "Patients"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['mrn']),
            models.Index(fields=['date_of_birth']),
        ]

    def __str__(self):
        return f"Patient (MRN: {self.mrn})"

    def add_fhir_resources(self, new_resources: list, document_id: int):
        """
        Appends new FHIR resources to the cumulative JSON bundle.

        This method ensures that medical history is never overwritten,
        only appended. It adds provenance information to each new resource.

        Args:
            new_resources (list): A list of FHIR resource dictionaries.
            document_id (int): The ID of the source document for these resources.
        """
        bundle = self.cumulative_fhir_json or {}
        
        for resource in new_resources:
            resource['meta'] = {
                'source': f'document_{document_id}',
                'lastUpdated': timezone.now().isoformat(),
                'versionId': str(uuid.uuid4())
            }
            
            resource_type = resource.get('resourceType')
            if resource_type:
                if resource_type not in bundle:
                    bundle[resource_type] = []
                bundle[resource_type].append(resource)
        
        self.cumulative_fhir_json = bundle
        self.save(update_fields=['cumulative_fhir_json', 'updated_at'])

        # Log this change to the patient's history
        PatientHistory.objects.create(
            patient=self,
            document_id=document_id,
            action='fhir_append',
            fhir_delta=new_resources,
            created_by=self.updated_by  # Assuming the updater is the creator of the history
        )


class PatientHistory(BaseModel):
    """
    Logs all significant changes to a patient's record for audit purposes.
    
    This provides a detailed timeline of when data was added or modified,
    which is crucial for data integrity and HIPAA compliance.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='history')
    document = models.ForeignKey(
        'documents.Document', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='patient_history_entries'
    )
    action = models.CharField(max_length=100, help_text="The action performed, e.g., 'fhir_append'")
    fhir_delta = models.JSONField(default=dict, help_text="The FHIR resources that were added or changed")

    class Meta:
        db_table = 'patient_history'
        verbose_name = "Patient History"
        verbose_name_plural = "Patient Histories"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['patient', '-created_at']),
        ]

    def __str__(self):
        return f"History for {self.patient} at {self.created_at}"
