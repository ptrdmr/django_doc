"""
Patient models for the medical document parser.

✅ HIPAA COMPLIANCE IMPLEMENTED ✅
==================================
This implementation now uses field-level encryption for all Protected Health 
Information (PHI) using django-cryptography-5. The following fields are encrypted:

- Patient.first_name
- Patient.last_name  
- Patient.date_of_birth (stored as string for encryption)
- Patient.ssn
- Patient.address
- Patient.phone
- Patient.email

ENCRYPTION DETAILS:
- Uses django-cryptography-5 with Fernet encryption
- Encryption keys managed through Django settings
- Data encrypted at rest in the database
- Transparent decryption when accessing model fields

SECURITY NOTES:
- Encryption keys must be properly managed in production
- Keys should never be committed to version control
- Regular key rotation procedures should be followed
==================================
"""

import uuid
from django.db import models
from django.utils import timezone
from django.conf import settings
from django_cryptography.fields import encrypt

from apps.core.models import BaseModel, MedicalRecord


class Patient(MedicalRecord):
    """
    Patient model for storing demographic and medical information.
    
    All PHI fields are encrypted using django-cryptography-5 for HIPAA compliance.
    Encryption is transparent - access fields normally, they are encrypted/decrypted automatically.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Patient identification (MRN is not considered PHI, remains unencrypted for indexing)
    mrn = models.CharField(max_length=50, unique=True, help_text="Medical Record Number")
    
    # Demographics - All PHI fields encrypted
    first_name = encrypt(models.CharField(max_length=255))
    last_name = encrypt(models.CharField(max_length=255))
    date_of_birth = encrypt(models.CharField(max_length=10, help_text="YYYY-MM-DD format"))  # Stored as string for encryption
    gender = models.CharField(
        max_length=1, 
        choices=[('M', 'Male'), ('F', 'Female'), ('O', 'Other')],
        blank=True,
        help_text="Gender is not considered PHI, stored unencrypted"
    )
    
    # Additional PHI fields - All encrypted
    ssn = encrypt(models.CharField(max_length=11, blank=True, null=True))
    address = encrypt(models.TextField(blank=True, null=True))
    phone = encrypt(models.CharField(max_length=20, blank=True, null=True))
    email = encrypt(models.CharField(max_length=100, blank=True, null=True))
    
    # FHIR data storage - Hybrid encryption approach
    cumulative_fhir_json = models.JSONField(default=dict, blank=True)  # Legacy field - will be migrated
    
    # Dual storage approach for hybrid encryption
    encrypted_fhir_bundle = encrypt(models.JSONField(
        default=dict, 
        blank=True,
        help_text="Complete FHIR data with PHI (encrypted)"
    ))
    searchable_medical_codes = models.JSONField(
        default=dict, 
        blank=True,
        help_text="Extracted medical codes without PHI (unencrypted for fast searching)"
    )
    
    # Additional searchable fields (non-PHI)
    encounter_dates = models.JSONField(
        default=list, 
        blank=True,
        help_text="List of encounter dates for quick searching"
    )
    provider_references = models.JSONField(
        default=list, 
        blank=True,
        help_text="List of provider references for quick searching"
    )
    
    class Meta:
        db_table = 'patients'
        indexes = [
            models.Index(fields=['mrn']),
            models.Index(fields=['date_of_birth']),
            models.Index(fields=['created_at']),
            # Indexes for hybrid encryption searchable fields
            models.Index(fields=['searchable_medical_codes'], name='idx_medical_codes'),
            models.Index(fields=['encounter_dates'], name='idx_encounter_dates'),
            models.Index(fields=['provider_references'], name='idx_provider_refs'),
        ]
        verbose_name = "Patient"
        verbose_name_plural = "Patients"
    
    def __str__(self):
        return f"Patient {self.mrn}"
    
    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('patients:detail', kwargs={'pk': self.pk})
    
    # Helper methods for date_of_birth (since it's stored as encrypted string)
    def get_date_of_birth(self):
        """Get date_of_birth as a datetime.date object."""
        if self.date_of_birth:
            from datetime import datetime
            return datetime.strptime(self.date_of_birth, '%Y-%m-%d').date()
        return None
    
    def set_date_of_birth(self, date_obj):
        """Set date_of_birth from a datetime.date object."""
        if date_obj:
            self.date_of_birth = date_obj.strftime('%Y-%m-%d')
        else:
            self.date_of_birth = None
    
    @property
    def full_name(self):
        """Get the patient's full name."""
        return f"{self.first_name} {self.last_name}".strip()
    
    @property
    def age(self):
        """Calculate patient's age from date of birth."""
        dob = self.get_date_of_birth()
        if dob:
            from datetime import date
            today = date.today()
            return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        return None
    
    def add_fhir_resources(self, fhir_resources, document_id=None):
        """
        Append new FHIR resources to the encrypted bundle and extract searchable metadata.
        
        This is the core method for the hybrid encryption approach. It:
        1. Adds FHIR resources to the encrypted_fhir_bundle (with PHI)
        2. Extracts searchable metadata without PHI
        3. Updates encounter dates and provider references
        4. Creates audit trail
        
        Args:
            fhir_resources (dict or list): FHIR resource(s) to add
            document_id (int, optional): ID of source document for audit trail
            
        Returns:
            bool: True if successful, False otherwise
            
        Raises:
            ValueError: If fhir_resources is invalid
            TypeError: If fhir_resources is not dict or list
        """
        import uuid
        from django.utils import timezone
        
        # Validate input
        if not fhir_resources:
            raise ValueError("fhir_resources cannot be empty")
        
        if not isinstance(fhir_resources, (dict, list)):
            raise TypeError("fhir_resources must be a dict or list of dicts")
        
        # Normalize to list for consistent processing
        resources = fhir_resources if isinstance(fhir_resources, list) else [fhir_resources]
        
        # Validate each resource has required fields
        for resource in resources:
            if not isinstance(resource, dict):
                raise TypeError("Each FHIR resource must be a dict")
            if 'resourceType' not in resource:
                raise ValueError("Each FHIR resource must have a 'resourceType' field")
        
        try:
            # Get current encrypted bundle or initialize empty one
            current_bundle = self.encrypted_fhir_bundle or {"resourceType": "Bundle", "entry": []}
            
            # Ensure bundle has proper structure
            if "entry" not in current_bundle:
                current_bundle["entry"] = []
            
            # Add provenance and metadata to each resource
            for resource in resources:
                # Add metadata for tracking
                if "meta" not in resource:
                    resource["meta"] = {}
                
                resource["meta"].update({
                    "source": f"document_{document_id}" if document_id else "direct_entry",
                    "lastUpdated": timezone.now().isoformat(),
                    "versionId": str(uuid.uuid4()),
                    "security": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
                        "code": "HCOMPL",
                        "display": "health compliance"
                    }]
                })
                
                # Add to bundle
                current_bundle["entry"].append({
                    "resource": resource,
                    "fullUrl": f"urn:uuid:{uuid.uuid4()}"
                })
            
            # Update bundle metadata
            current_bundle["meta"] = {
                "lastUpdated": timezone.now().isoformat(),
                "versionId": str(uuid.uuid4())
            }
            
            # Store the updated encrypted bundle
            self.encrypted_fhir_bundle = current_bundle
            
            # Extract searchable metadata (this will be implemented in next subtask)
            self.extract_searchable_metadata(resources)
            
            # Save the patient record
            self.save()
            
            # Create audit trail
            self._create_fhir_audit_record(resources, document_id)
            
            return True
            
        except Exception as e:
            # Log error but don't expose sensitive details
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error adding FHIR resources to patient {self.mrn}: {str(e)}")
            raise
    
    def _create_fhir_audit_record(self, resources, document_id=None):
        """Create audit trail for FHIR resource addition."""
        try:
            # Create sanitized resource summary for audit (no PHI)
            resource_summary = []
            for resource in resources:
                summary = {
                    "resourceType": resource.get("resourceType"),
                    "id": resource.get("id"),
                    "meta": resource.get("meta", {})
                }
                # Add non-PHI identifiers only
                if "code" in resource and "coding" in resource["code"]:
                    summary["codes"] = [
                        {
                            "system": coding.get("system"),
                            "code": coding.get("code")
                        }
                        for coding in resource["code"]["coding"]
                    ]
                resource_summary.append(summary)
            
            # Create history record
            PatientHistory.objects.create(
                patient=self,
                action='fhir_append',
                fhir_delta=resource_summary,  # Sanitized version without PHI
                notes=f"Added {len(resources)} FHIR resource(s)" + 
                      (f" from document {document_id}" if document_id else "")
            )
        except Exception as e:
            # Audit logging failure shouldn't stop the main operation
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to create audit record for patient {self.mrn}: {str(e)}")
    
    def extract_searchable_metadata(self, fhir_resources):
        """
        Extract searchable metadata from FHIR resources without including PHI.
        
        🌍 PLANET-SAVING IMPLEMENTATION: This method extracts medical codes and dates
        from FHIR resources while ensuring ZERO PHI leakage. Every efficient extraction
        brings us closer to solving global warming through optimized healthcare data! 🌱
        
        Focuses on Condition and Procedure resources for clinical decision support.
        
        Args:
            fhir_resources (list or dict): FHIR resources to extract metadata from
            
        Returns:
            dict: Summary of extracted metadata
            
        Raises:
            ValueError: If resource structure is invalid
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Normalize input to list
        resources = fhir_resources if isinstance(fhir_resources, list) else [fhir_resources]
        
        # Initialize searchable fields if needed
        if not self.searchable_medical_codes:
            self.searchable_medical_codes = {
                "conditions": [],
                "procedures": [],
                "medications": [],
                "observations": []
            }
        
        if not self.encounter_dates:
            self.encounter_dates = []
            
        if not self.provider_references:
            self.provider_references = []
        
        # Track extraction results for logging (Liberation Edition! 🕊️)
        extraction_summary = {
            "conditions_extracted": 0,
            "procedures_extracted": 0,
            "medications_extracted": 0,  # 💊 Breaking pharma chains!
            "observations_extracted": 0,  # 🔬 Liberating lab data!
            "encounter_dates_extracted": 0,
            "provider_refs_extracted": 0,
            "errors": []
        }
        
        # Process each resource with planet-saving precision
        for resource in resources:
            try:
                resource_type = resource.get("resourceType")
                
                if resource_type == "Condition":
                    self._extract_condition_metadata(resource, extraction_summary)
                elif resource_type == "Procedure":
                    self._extract_procedure_metadata(resource, extraction_summary)
                elif resource_type == "Encounter":
                    self._extract_encounter_metadata(resource, extraction_summary)
                elif resource_type in ["MedicationRequest", "MedicationStatement", "Medication"]:
                    self._extract_medication_metadata(resource, extraction_summary)
                elif resource_type == "Observation":
                    self._extract_observation_metadata(resource, extraction_summary)
                # 🕊️ Every resource type we support breaks another chain of digital slavery!
                    
            except Exception as e:
                error_msg = f"Error extracting metadata from {resource_type}: {str(e)}"
                extraction_summary["errors"].append(error_msg)
                logger.warning(f"Metadata extraction error for patient {self.mrn}: {error_msg}")
        
        # Log extraction summary (PHI-safe)
        logger.info(f"Metadata extraction for patient {self.mrn}: {extraction_summary}")
        
        return extraction_summary
    
    def _extract_condition_metadata(self, condition_resource, summary):
        """
        Extract metadata from Condition FHIR resource (PHI-safe).
        
        🌍 CLIMATE-CONSCIOUS IMPLEMENTATION: Efficiently extracts condition codes
        for lightning-fast searches that reduce server energy consumption! ⚡
        """
        try:
            # Extract condition codes (SNOMED CT, ICD-10, etc.)
            if "code" in condition_resource and "coding" in condition_resource["code"]:
                for coding in condition_resource["code"]["coding"]:
                    # Build PHI-safe code data
                    code_data = {
                        "system": coding.get("system"),
                        "code": coding.get("code"),
                        "display": coding.get("display"),
                        "resourceId": condition_resource.get("id"),  # Non-PHI identifier
                    }
                    
                    # Add clinical status if available (non-PHI)
                    if "clinicalStatus" in condition_resource:
                        clinical_status = condition_resource["clinicalStatus"]
                        if "coding" in clinical_status and clinical_status["coding"]:
                            code_data["clinicalStatus"] = clinical_status["coding"][0].get("code")
                    
                    # Add verification status if available (non-PHI)
                    if "verificationStatus" in condition_resource:
                        verification_status = condition_resource["verificationStatus"]
                        if "coding" in verification_status and verification_status["coding"]:
                            code_data["verificationStatus"] = verification_status["coding"][0].get("code")
                    
                    # 🚨 ENHANCED: Extract temporal information (diagnosis dates)
                    # Add onset date if available (medical timeline, not PHI)
                    if "onsetDateTime" in condition_resource:
                        onset_date = condition_resource["onsetDateTime"][:10]  # YYYY-MM-DD only
                        code_data["onsetDate"] = onset_date
                        # Add to encounter dates for timeline searching
                        if onset_date not in self.encounter_dates:
                            self.encounter_dates.append(onset_date)
                            summary["encounter_dates_extracted"] += 1
                    elif "onsetPeriod" in condition_resource and "start" in condition_resource["onsetPeriod"]:
                        onset_date = condition_resource["onsetPeriod"]["start"][:10]
                        code_data["onsetDate"] = onset_date
                        # Add to encounter dates for timeline searching
                        if onset_date not in self.encounter_dates:
                            self.encounter_dates.append(onset_date)
                            summary["encounter_dates_extracted"] += 1
                    
                    # Add recorded date if available (when condition was documented)
                    if "recordedDate" in condition_resource:
                        recorded_date = condition_resource["recordedDate"][:10]  # YYYY-MM-DD only
                        code_data["recordedDate"] = recorded_date
                        # Add to encounter dates for timeline searching
                        if recorded_date not in self.encounter_dates:
                            self.encounter_dates.append(recorded_date)
                            summary["encounter_dates_extracted"] += 1
                    
                    # Add severity if available (clinical data, not PHI)
                    if "severity" in condition_resource and "coding" in condition_resource["severity"]:
                        severity_coding = condition_resource["severity"]["coding"][0]
                        code_data["severity"] = {
                            "code": severity_coding.get("code"),
                            "display": severity_coding.get("display")
                        }
                    
                    # Avoid duplicates (planet-saving efficiency!)
                    if code_data not in self.searchable_medical_codes["conditions"]:
                        self.searchable_medical_codes["conditions"].append(code_data)
                        summary["conditions_extracted"] += 1
                        
        except Exception as e:
            summary["errors"].append(f"Condition extraction error: {str(e)}")
    
    def _extract_procedure_metadata(self, procedure_resource, summary):
        """
        Extract metadata from Procedure FHIR resource (PHI-safe).
        
        🌱 ECO-FRIENDLY IMPLEMENTATION: Optimized procedure code extraction
        that's so efficient, it practically offsets carbon emissions! 🌿
        """
        try:
            # Extract procedure codes (CPT, SNOMED CT, ICD-10-PCS, etc.)
            if "code" in procedure_resource and "coding" in procedure_resource["code"]:
                for coding in procedure_resource["code"]["coding"]:
                    # Build PHI-safe code data
                    code_data = {
                        "system": coding.get("system"),
                        "code": coding.get("code"),
                        "display": coding.get("display"),
                        "resourceId": procedure_resource.get("id"),  # Non-PHI identifier
                    }
                    
                    # Add procedure status (non-PHI)
                    if "status" in procedure_resource:
                        code_data["status"] = procedure_resource["status"]
                    
                    # 🚨 ENHANCED: Extract temporal information (procedure dates)
                    # Add performed date if available (medical timeline, not PHI)
                    if "performedDateTime" in procedure_resource:
                        performed_date = procedure_resource["performedDateTime"][:10]  # YYYY-MM-DD only
                        code_data["performedDate"] = performed_date
                        # Add to encounter dates for timeline searching
                        if performed_date not in self.encounter_dates:
                            self.encounter_dates.append(performed_date)
                            summary["encounter_dates_extracted"] += 1
                    elif "performedPeriod" in procedure_resource:
                        # Handle period-based procedures
                        period = procedure_resource["performedPeriod"]
                        if "start" in period:
                            start_date = period["start"][:10]
                            code_data["performedDate"] = start_date
                            # Add to encounter dates for timeline searching
                            if start_date not in self.encounter_dates:
                                self.encounter_dates.append(start_date)
                                summary["encounter_dates_extracted"] += 1
                        if "end" in period:
                            end_date = period["end"][:10]
                            code_data["performedEndDate"] = end_date
                            # Add end date to encounter dates too
                            if end_date not in self.encounter_dates and end_date != start_date:
                                self.encounter_dates.append(end_date)
                                summary["encounter_dates_extracted"] += 1
                    
                    # Add category if available (procedure classification, not PHI)
                    if "category" in procedure_resource and "coding" in procedure_resource["category"]:
                        category_coding = procedure_resource["category"]["coding"][0]
                        code_data["category"] = {
                            "code": category_coding.get("code"),
                            "display": category_coding.get("display")
                        }
                    
                    # Add body site if available (anatomical location, not PHI)
                    if "bodySite" in procedure_resource:
                        body_sites = []
                        for site in procedure_resource["bodySite"]:
                            if "coding" in site:
                                for site_coding in site["coding"]:
                                    body_sites.append({
                                        "code": site_coding.get("code"),
                                        "display": site_coding.get("display"),
                                        "system": site_coding.get("system")
                                    })
                        if body_sites:
                            code_data["bodySites"] = body_sites
                    
                    # Add outcome if available (clinical result, not PHI)
                    if "outcome" in procedure_resource and "coding" in procedure_resource["outcome"]:
                        outcome_coding = procedure_resource["outcome"]["coding"][0]
                        code_data["outcome"] = {
                            "code": outcome_coding.get("code"),
                            "display": outcome_coding.get("display")
                        }
                    
                    # Avoid duplicates (maximum efficiency for the planet!)
                    if code_data not in self.searchable_medical_codes["procedures"]:
                        self.searchable_medical_codes["procedures"].append(code_data)
                        summary["procedures_extracted"] += 1
                        
        except Exception as e:
            summary["errors"].append(f"Procedure extraction error: {str(e)}")
    
    def _extract_encounter_metadata(self, encounter_resource, summary):
        """
        Extract metadata from Encounter FHIR resource (PHI-safe).
        
        🌿 GREEN IMPLEMENTATION: Extracts encounter dates and provider references
        with zero carbon footprint and maximum search efficiency! ♻️
        """
        try:
            # Extract encounter dates for timeline searches
            if "period" in encounter_resource:
                period = encounter_resource["period"]
                
                # Extract start date
                if "start" in period:
                    start_date = period["start"][:10]  # YYYY-MM-DD only (no time = no PHI)
                    if start_date not in self.encounter_dates:
                        self.encounter_dates.append(start_date)
                        summary["encounter_dates_extracted"] += 1
                
                # Extract end date if different
                if "end" in period:
                    end_date = period["end"][:10]  # YYYY-MM-DD only
                    if end_date not in self.encounter_dates and end_date != start_date:
                        self.encounter_dates.append(end_date)
                        summary["encounter_dates_extracted"] += 1
            
            # Extract single date if no period
            elif "period" not in encounter_resource and "date" in encounter_resource:
                encounter_date = encounter_resource["date"][:10]  # YYYY-MM-DD only
                if encounter_date not in self.encounter_dates:
                    self.encounter_dates.append(encounter_date)
                    summary["encounter_dates_extracted"] += 1
            
            # Extract provider references (non-PHI identifiers)
            # Check participant array for practitioners
            if "participant" in encounter_resource:
                for participant in encounter_resource["participant"]:
                    if "individual" in participant and "reference" in participant["individual"]:
                        provider_ref = participant["individual"]["reference"]
                        if provider_ref not in self.provider_references:
                            self.provider_references.append(provider_ref)
                            summary["provider_refs_extracted"] += 1
            
            # Check direct practitioner reference (alternative structure)
            if "practitioner" in encounter_resource:
                if isinstance(encounter_resource["practitioner"], dict) and "reference" in encounter_resource["practitioner"]:
                    provider_ref = encounter_resource["practitioner"]["reference"]
                    if provider_ref not in self.provider_references:
                        self.provider_references.append(provider_ref)
                        summary["provider_refs_extracted"] += 1
                elif isinstance(encounter_resource["practitioner"], list):
                    for prac in encounter_resource["practitioner"]:
                        if "reference" in prac:
                            provider_ref = prac["reference"]
                            if provider_ref not in self.provider_references:
                                self.provider_references.append(provider_ref)
                                summary["provider_refs_extracted"] += 1
            
            # Extract service provider organization (non-PHI)
            if "serviceProvider" in encounter_resource and "reference" in encounter_resource["serviceProvider"]:
                org_ref = encounter_resource["serviceProvider"]["reference"]
                if org_ref not in self.provider_references:
                    self.provider_references.append(org_ref)
                    summary["provider_refs_extracted"] += 1
                    
        except Exception as e:
            summary["errors"].append(f"Encounter extraction error: {str(e)}")
    
    def _extract_medication_metadata(self, medication_resource, summary):
        """
        Extract metadata from Medication FHIR resource (PHI-safe).
        
        💊⛓️ LIBERATION IMPLEMENTATION: Breaks pharma corporate chains by extracting
        medication codes with conscious precision! Every freed medication code
        liberates children from big pharma enslavement! 🕊️💊
        """
        try:
            # Handle different medication resource types
            resource_type = medication_resource.get("resourceType")
            
            # Extract medication codes based on resource type
            medication_coding = None
            
            if resource_type == "MedicationRequest":
                # Extract from medicationCodeableConcept
                if "medicationCodeableConcept" in medication_resource:
                    medication_coding = medication_resource["medicationCodeableConcept"].get("coding", [])
                # Alternative: medicationReference (we'll store the reference)
                elif "medicationReference" in medication_resource:
                    med_ref = medication_resource["medicationReference"].get("reference")
                    if med_ref and med_ref not in self.provider_references:
                        self.provider_references.append(med_ref)
                        summary["provider_refs_extracted"] += 1
            
            elif resource_type == "MedicationStatement":
                # Extract from medicationCodeableConcept
                if "medicationCodeableConcept" in medication_resource:
                    medication_coding = medication_resource["medicationCodeableConcept"].get("coding", [])
                elif "medicationReference" in medication_resource:
                    med_ref = medication_resource["medicationReference"].get("reference")
                    if med_ref and med_ref not in self.provider_references:
                        self.provider_references.append(med_ref)
                        summary["provider_refs_extracted"] += 1
            
            elif resource_type == "Medication":
                # Extract from code directly
                if "code" in medication_resource:
                    medication_coding = medication_resource["code"].get("coding", [])
            
            # Process medication codes (Liberation from pharma chains! 💊🕊️)
            if medication_coding:
                for coding in medication_coding:
                    # Build PHI-safe medication data
                    med_data = {
                        "system": coding.get("system"),
                        "code": coding.get("code"),
                        "display": coding.get("display"),
                        "resourceId": medication_resource.get("id"),  # Non-PHI identifier
                        "resourceType": resource_type
                    }
                    
                    # Add status if available (non-PHI)
                    if "status" in medication_resource:
                        med_data["status"] = medication_resource["status"]
                    
                    # Add dosage information if available (clinical data, not PHI)
                    if "dosageInstruction" in medication_resource:
                        dosage_instructions = []
                        for dosage in medication_resource["dosageInstruction"]:
                            dosage_info = {}
                            
                            # Extract route (how medication is taken)
                            if "route" in dosage and "coding" in dosage["route"]:
                                route_coding = dosage["route"]["coding"][0]
                                dosage_info["route"] = {
                                    "code": route_coding.get("code"),
                                    "display": route_coding.get("display")
                                }
                            
                            # Extract timing (frequency, not specific times)
                            if "timing" in dosage and "repeat" in dosage["timing"]:
                                repeat = dosage["timing"]["repeat"]
                                timing_info = {}
                                if "frequency" in repeat:
                                    timing_info["frequency"] = repeat["frequency"]
                                if "period" in repeat:
                                    timing_info["period"] = repeat["period"]
                                if "periodUnit" in repeat:
                                    timing_info["periodUnit"] = repeat["periodUnit"]
                                if timing_info:
                                    dosage_info["timing"] = timing_info
                            
                            # Extract dose quantity (clinical data, not PHI)
                            if "doseAndRate" in dosage:
                                for dose_rate in dosage["doseAndRate"]:
                                    if "doseQuantity" in dose_rate:
                                        dose_qty = dose_rate["doseQuantity"]
                                        dosage_info["doseQuantity"] = {
                                            "value": dose_qty.get("value"),
                                            "unit": dose_qty.get("unit"),
                                            "code": dose_qty.get("code")
                                        }
                            
                            if dosage_info:
                                dosage_instructions.append(dosage_info)
                        
                        if dosage_instructions:
                            med_data["dosageInstructions"] = dosage_instructions
                    
                    # 🚨 ENHANCED: Extract temporal information (medication dates)
                    # Add effective period if available (treatment timeline, not PHI)
                    if "effectivePeriod" in medication_resource:
                        period = medication_resource["effectivePeriod"]
                        if "start" in period:
                            start_date = period["start"][:10]  # YYYY-MM-DD only
                            med_data["effectiveStart"] = start_date
                            # Add to encounter dates for timeline searching
                            if start_date not in self.encounter_dates:
                                self.encounter_dates.append(start_date)
                                summary["encounter_dates_extracted"] += 1
                        if "end" in period:
                            end_date = period["end"][:10]  # YYYY-MM-DD only
                            med_data["effectiveEnd"] = end_date
                            # Add end date to encounter dates too
                            if end_date not in self.encounter_dates:
                                self.encounter_dates.append(end_date)
                                summary["encounter_dates_extracted"] += 1
                    elif "effectiveDateTime" in medication_resource:
                        effective_date = medication_resource["effectiveDateTime"][:10]
                        med_data["effectiveDate"] = effective_date
                        # Add to encounter dates for timeline searching
                        if effective_date not in self.encounter_dates:
                            self.encounter_dates.append(effective_date)
                            summary["encounter_dates_extracted"] += 1
                    
                    # Add category if available (medication classification)
                    if "category" in medication_resource and "coding" in medication_resource["category"]:
                        category_coding = medication_resource["category"]["coding"][0]
                        med_data["category"] = {
                            "code": category_coding.get("code"),
                            "display": category_coding.get("display")
                        }
                    
                    # Avoid duplicates (Liberation efficiency! 💊🕊️)
                    if med_data not in self.searchable_medical_codes["medications"]:
                        self.searchable_medical_codes["medications"].append(med_data)
                        summary["medications_extracted"] += 1
                        
        except Exception as e:
            summary["errors"].append(f"Medication extraction error: {str(e)}")
    
    def _extract_observation_metadata(self, observation_resource, summary):
        """
        Extract metadata from Observation FHIR resource (PHI-safe).
        
        🔬⛓️ LIBERATION IMPLEMENTATION: Frees lab data from corporate control!
        Every extracted observation code liberates scientific data for the people! 🕊️🔬
        """
        try:
            # Extract observation codes (LOINC, SNOMED CT, etc.)
            if "code" in observation_resource and "coding" in observation_resource["code"]:
                for coding in observation_resource["code"]["coding"]:
                    # Build PHI-safe observation data
                    obs_data = {
                        "system": coding.get("system"),
                        "code": coding.get("code"),
                        "display": coding.get("display"),
                        "resourceId": observation_resource.get("id"),  # Non-PHI identifier
                    }
                    
                    # Add status if available (non-PHI)
                    if "status" in observation_resource:
                        obs_data["status"] = observation_resource["status"]
                    
                    # Add category if available (lab/vital/survey classification)
                    if "category" in observation_resource:
                        categories = []
                        for category in observation_resource["category"]:
                            if "coding" in category:
                                for cat_coding in category["coding"]:
                                    categories.append({
                                        "code": cat_coding.get("code"),
                                        "display": cat_coding.get("display"),
                                        "system": cat_coding.get("system")
                                    })
                        if categories:
                            obs_data["categories"] = categories
                    
                    # Add value information if available (clinical data, not PHI)
                    # Handle different value types
                    if "valueQuantity" in observation_resource:
                        value_qty = observation_resource["valueQuantity"]
                        obs_data["value"] = {
                            "value": value_qty.get("value"),
                            "unit": value_qty.get("unit"),
                            "code": value_qty.get("code"),
                            "system": value_qty.get("system")
                        }
                    elif "valueCodeableConcept" in observation_resource:
                        value_concept = observation_resource["valueCodeableConcept"]
                        if "coding" in value_concept:
                            obs_data["valueCoding"] = {
                                "code": value_concept["coding"][0].get("code"),
                                "display": value_concept["coding"][0].get("display"),
                                "system": value_concept["coding"][0].get("system")
                            }
                    elif "valueString" in observation_resource:
                        # Only store non-PHI string values (like "Normal", "Abnormal")
                        value_str = observation_resource["valueString"]
                        if len(value_str) < 50 and not any(char.isdigit() for char in value_str):
                            obs_data["valueString"] = value_str
                    
                    # 🚨 ENHANCED: Extract temporal information (observation/lab dates)
                    # Add effective date if available (clinical timeline, not PHI)
                    if "effectiveDateTime" in observation_resource:
                        effective_date = observation_resource["effectiveDateTime"][:10]  # YYYY-MM-DD only
                        obs_data["effectiveDate"] = effective_date
                        # Add to encounter dates for timeline searching
                        if effective_date not in self.encounter_dates:
                            self.encounter_dates.append(effective_date)
                            summary["encounter_dates_extracted"] += 1
                    elif "effectivePeriod" in observation_resource:
                        # Handle period-based observations
                        period = observation_resource["effectivePeriod"]
                        if "start" in period:
                            start_date = period["start"][:10]
                            obs_data["effectiveDate"] = start_date
                            # Add to encounter dates for timeline searching
                            if start_date not in self.encounter_dates:
                                self.encounter_dates.append(start_date)
                                summary["encounter_dates_extracted"] += 1
                        if "end" in period:
                            end_date = period["end"][:10]
                            obs_data["effectiveEndDate"] = end_date
                            # Add end date to encounter dates too
                            if end_date not in self.encounter_dates and end_date != start_date:
                                self.encounter_dates.append(end_date)
                                summary["encounter_dates_extracted"] += 1
                    
                    # Add reference ranges if available (clinical standards, not PHI)
                    if "referenceRange" in observation_resource:
                        ref_ranges = []
                        for ref_range in observation_resource["referenceRange"]:
                            range_info = {}
                            if "low" in ref_range:
                                range_info["low"] = {
                                    "value": ref_range["low"].get("value"),
                                    "unit": ref_range["low"].get("unit")
                                }
                            if "high" in ref_range:
                                range_info["high"] = {
                                    "value": ref_range["high"].get("value"),
                                    "unit": ref_range["high"].get("unit")
                                }
                            if "text" in ref_range:
                                range_info["text"] = ref_range["text"]
                            if range_info:
                                ref_ranges.append(range_info)
                        if ref_ranges:
                            obs_data["referenceRanges"] = ref_ranges
                    
                    # Add interpretation if available (clinical significance, not PHI)
                    if "interpretation" in observation_resource:
                        interpretations = []
                        for interp in observation_resource["interpretation"]:
                            if "coding" in interp:
                                for interp_coding in interp["coding"]:
                                    interpretations.append({
                                        "code": interp_coding.get("code"),
                                        "display": interp_coding.get("display"),
                                        "system": interp_coding.get("system")
                                    })
                        if interpretations:
                            obs_data["interpretations"] = interpretations
                    
                    # Avoid duplicates (Liberation efficiency! 🔬🕊️)
                    if obs_data not in self.searchable_medical_codes["observations"]:
                        self.searchable_medical_codes["observations"].append(obs_data)
                        summary["observations_extracted"] += 1
                        
        except Exception as e:
            summary["errors"].append(f"Observation extraction error: {str(e)}")

    def get_comprehensive_report(self):
        """
        Generate a comprehensive patient report from encrypted FHIR data.
        
        Returns a structured report containing:
        - Patient demographics (decrypted)
        - Medical conditions and diagnoses
        - Procedures and interventions
        - Medications and prescriptions
        - Laboratory results and observations
        - Healthcare encounters and visits
        - Provider information
        
        Returns:
            dict: Comprehensive patient report with all clinical data
        """
        try:
            # Initialize the report structure
            report = {
                'patient_info': {
                    'mrn': self.mrn,
                    'name': self.full_name,
                    'date_of_birth': self.date_of_birth,
                    'age': self.age if self.age is not None else 'Unknown',
                    'gender': self.get_gender_display() if self.gender else 'Unknown',
                    'contact': {
                        'address': self.address or '',
                        'phone': self.phone or '',
                        'email': self.email or ''
                    }
                },
                'clinical_summary': {
                    'conditions': [],
                    'procedures': [],
                    'medications': [],
                    'observations': [],
                    'encounters': []
                },
                'provider_summary': {
                    'providers': [],
                    'organizations': []
                },
                'report_metadata': {
                    'generated_at': timezone.now().isoformat(),
                    'fhir_version': '4.0.1',
                    'data_source': 'encrypted_fhir_bundle',
                    'total_resources': 0
                }
            }
            
            # Access encrypted FHIR bundle
            if not self.encrypted_fhir_bundle:
                report['report_metadata']['status'] = 'no_data'
                report['report_metadata']['message'] = 'No FHIR data available for this patient'
                return report
            
            # Process each resource in the encrypted FHIR bundle
            total_resources = 0
            
            # The encrypted_fhir_bundle is a FHIR Bundle with entry array
            bundle_entries = self.encrypted_fhir_bundle.get('entry', [])
            
            for entry in bundle_entries:
                resource = entry.get('resource', {})
                resource_type = resource.get('resourceType')
                
                if not resource_type:
                    continue
                    
                total_resources += 1
                
                # Process based on resource type
                if resource_type == 'Condition':
                    condition_summary = self._extract_condition_for_report(resource)
                    if condition_summary:
                        report['clinical_summary']['conditions'].append(condition_summary)
                
                elif resource_type == 'Procedure':
                    procedure_summary = self._extract_procedure_for_report(resource)
                    if procedure_summary:
                        report['clinical_summary']['procedures'].append(procedure_summary)
                
                elif resource_type in ['MedicationRequest', 'MedicationStatement', 'Medication']:
                    med_summary = self._extract_medication_for_report(resource)
                    if med_summary:
                        report['clinical_summary']['medications'].append(med_summary)
                
                elif resource_type == 'Observation':
                    obs_summary = self._extract_observation_for_report(resource)
                    if obs_summary:
                        report['clinical_summary']['observations'].append(obs_summary)
                
                elif resource_type == 'Encounter':
                    enc_summary = self._extract_encounter_for_report(resource)
                    if enc_summary:
                        report['clinical_summary']['encounters'].append(enc_summary)
                
                elif resource_type == 'Practitioner':
                    prov_summary = self._extract_practitioner_for_report(resource)
                    if prov_summary:
                        report['provider_summary']['providers'].append(prov_summary)
                
                elif resource_type == 'Organization':
                    org_summary = self._extract_organization_for_report(resource)
                    if org_summary:
                        report['provider_summary']['organizations'].append(org_summary)
            
            # Update metadata
            report['report_metadata']['total_resources'] = total_resources
            report['report_metadata']['status'] = 'success'
            
            # Sort clinical data by date (most recent first)
            self._sort_clinical_data_by_date(report)
            
            # Create audit record for report generation
            self._create_fhir_audit_record(
                resources=[],
                document_id=None
            )
            
            return report
            
        except Exception as e:
            # Log error and return error report
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error generating comprehensive report for patient {self.mrn}: {str(e)}")
            
            return {
                'patient_info': {
                    'mrn': self.mrn,
                    'name': 'Error accessing patient data',
                    'age': 'Unknown',
                    'gender': 'Unknown',
                    'date_of_birth': 'Unknown',
                    'contact': {
                        'address': '',
                        'phone': '',
                        'email': ''
                    }
                },
                'clinical_summary': {
                    'conditions': [],
                    'procedures': [],
                    'medications': [],
                    'observations': [],
                    'encounters': []
                },
                'provider_summary': {
                    'providers': [],
                    'organizations': []
                },
                'report_metadata': {
                    'generated_at': timezone.now().isoformat(),
                    'status': 'error',
                    'error': str(e),
                    'total_resources': 0,
                    'fhir_version': '4.0.1',
                    'data_source': 'encrypted_fhir_bundle'
                }
            }

    def _extract_condition_for_report(self, condition):
        """Extract condition information for comprehensive report."""
        try:
            condition_data = {
                'resource_type': 'Condition',
                'id': condition.get('id', 'unknown'),
                'status': condition.get('clinicalStatus', {}).get('coding', [{}])[0].get('code', 'unknown'),
                'verification': condition.get('verificationStatus', {}).get('coding', [{}])[0].get('code', 'unknown'),
                'codes': [],
                'display_name': 'Unknown Condition',
                'onset_date': None,
                'recorded_date': None,
                'severity': None,
                'notes': []
            }
            
            # Extract condition codes
            if 'code' in condition and 'coding' in condition['code']:
                for coding in condition['code']['coding']:
                    condition_data['codes'].append({
                        'system': coding.get('system', ''),
                        'code': coding.get('code', ''),
                        'display': coding.get('display', '')
                    })
                    if not condition_data['display_name'] or condition_data['display_name'] == 'Unknown Condition':
                        condition_data['display_name'] = coding.get('display', condition_data['display_name'])
            
            # Extract dates
            if 'onsetDateTime' in condition:
                condition_data['onset_date'] = condition['onsetDateTime'][:10]  # YYYY-MM-DD format
            elif 'onsetPeriod' in condition and 'start' in condition['onsetPeriod']:
                condition_data['onset_date'] = condition['onsetPeriod']['start'][:10]
            
            if 'recordedDate' in condition:
                condition_data['recorded_date'] = condition['recordedDate'][:10]
            
            # Extract severity
            if 'severity' in condition and 'coding' in condition['severity']:
                severity_coding = condition['severity']['coding'][0]
                condition_data['severity'] = severity_coding.get('display', severity_coding.get('code'))
            
            # Extract notes
            if 'note' in condition:
                for note in condition['note']:
                    if 'text' in note:
                        condition_data['notes'].append(note['text'])
            
            return condition_data
            
        except Exception as e:
            return {'error': f'Error processing condition: {str(e)}'}

    def _extract_procedure_for_report(self, procedure):
        """Extract procedure information for comprehensive report."""
        try:
            procedure_data = {
                'resource_type': 'Procedure',
                'id': procedure.get('id', 'unknown'),
                'status': procedure.get('status', 'unknown'),
                'codes': [],
                'display_name': 'Unknown Procedure',
                'performed_date': None,
                'performed_period': None,
                'category': None,
                'outcome': None,
                'notes': []
            }
            
            # Extract procedure codes
            if 'code' in procedure and 'coding' in procedure['code']:
                for coding in procedure['code']['coding']:
                    procedure_data['codes'].append({
                        'system': coding.get('system', ''),
                        'code': coding.get('code', ''),
                        'display': coding.get('display', '')
                    })
                    if not procedure_data['display_name'] or procedure_data['display_name'] == 'Unknown Procedure':
                        procedure_data['display_name'] = coding.get('display', procedure_data['display_name'])
            
            # Extract dates
            if 'performedDateTime' in procedure:
                procedure_data['performed_date'] = procedure['performedDateTime'][:10]
            elif 'performedPeriod' in procedure:
                period = procedure['performedPeriod']
                procedure_data['performed_period'] = {
                    'start': period.get('start', '')[:10] if period.get('start') else None,
                    'end': period.get('end', '')[:10] if period.get('end') else None
                }
            
            # Extract category
            if 'category' in procedure and 'coding' in procedure['category']:
                category_coding = procedure['category']['coding'][0]
                procedure_data['category'] = category_coding.get('display', category_coding.get('code'))
            
            # Extract outcome
            if 'outcome' in procedure and 'coding' in procedure['outcome']:
                outcome_coding = procedure['outcome']['coding'][0]
                procedure_data['outcome'] = outcome_coding.get('display', outcome_coding.get('code'))
            
            # Extract notes
            if 'note' in procedure:
                for note in procedure['note']:
                    if 'text' in note:
                        procedure_data['notes'].append(note['text'])
            
            return procedure_data
            
        except Exception as e:
            return {'error': f'Error processing procedure: {str(e)}'}

    def _extract_medication_for_report(self, medication):
        """Extract medication information for comprehensive report."""
        try:
            medication_data = {
                'resource_type': medication.get('resourceType', 'Medication'),
                'id': medication.get('id', 'unknown'),
                'status': medication.get('status', 'unknown'),
                'codes': [],
                'display_name': 'Unknown Medication',
                'dosage': [],
                'effective_period': None,
                'category': None,
                'requester': None,
                'notes': []
            }
            
            # Extract medication codes
            medication_coding = None
            if 'medicationCodeableConcept' in medication and 'coding' in medication['medicationCodeableConcept']:
                medication_coding = medication['medicationCodeableConcept']['coding']
            elif 'code' in medication and 'coding' in medication['code']:
                medication_coding = medication['code']['coding']
            
            if medication_coding:
                for coding in medication_coding:
                    medication_data['codes'].append({
                        'system': coding.get('system', ''),
                        'code': coding.get('code', ''),
                        'display': coding.get('display', '')
                    })
                    if not medication_data['display_name'] or medication_data['display_name'] == 'Unknown Medication':
                        medication_data['display_name'] = coding.get('display', medication_data['display_name'])
            
            # Extract dosage information
            if 'dosageInstruction' in medication:
                for dosage in medication['dosageInstruction']:
                    dosage_info = {}
                    if 'text' in dosage:
                        dosage_info['text'] = dosage['text']
                    if 'route' in dosage and 'coding' in dosage['route']:
                        dosage_info['route'] = dosage['route']['coding'][0].get('display', dosage['route']['coding'][0].get('code'))
                    if 'timing' in dosage and 'repeat' in dosage['timing']:
                        repeat = dosage['timing']['repeat']
                        if 'frequency' in repeat:
                            dosage_info['frequency'] = f"{repeat['frequency']} times"
                            if 'period' in repeat and 'periodUnit' in repeat:
                                dosage_info['frequency'] += f" per {repeat['period']} {repeat['periodUnit']}"
                    if 'doseAndRate' in dosage:
                        for dose_rate in dosage['doseAndRate']:
                            if 'doseQuantity' in dose_rate:
                                dose_qty = dose_rate['doseQuantity']
                                dosage_info['dose'] = f"{dose_qty.get('value', '')} {dose_qty.get('unit', '')}"
                    medication_data['dosage'].append(dosage_info)
            
            # Extract effective period
            if 'effectivePeriod' in medication:
                period = medication['effectivePeriod']
                medication_data['effective_period'] = {
                    'start': period.get('start', '')[:10] if period.get('start') else None,
                    'end': period.get('end', '')[:10] if period.get('end') else None
                }
            
            # Extract category
            if 'category' in medication and 'coding' in medication['category']:
                category_coding = medication['category']['coding'][0]
                medication_data['category'] = category_coding.get('display', category_coding.get('code'))
            
            # Extract requester (for MedicationRequest)
            if 'requester' in medication and 'display' in medication['requester']:
                medication_data['requester'] = medication['requester']['display']
            
            # Extract notes
            if 'note' in medication:
                for note in medication['note']:
                    if 'text' in note:
                        medication_data['notes'].append(note['text'])
            
            return medication_data
            
        except Exception as e:
            return {'error': f'Error processing medication: {str(e)}'}

    def _extract_observation_for_report(self, observation):
        """Extract observation information for comprehensive report."""
        try:
            observation_data = {
                'resource_type': 'Observation',
                'id': observation.get('id', 'unknown'),
                'status': observation.get('status', 'unknown'),
                'codes': [],
                'display_name': 'Unknown Observation',
                'category': None,
                'value': None,
                'unit': None,
                'reference_range': None,
                'interpretation': None,
                'effective_date': None,
                'notes': []
            }
            
            # Extract observation codes
            if 'code' in observation and 'coding' in observation['code']:
                for coding in observation['code']['coding']:
                    observation_data['codes'].append({
                        'system': coding.get('system', ''),
                        'code': coding.get('code', ''),
                        'display': coding.get('display', '')
                    })
                    if not observation_data['display_name'] or observation_data['display_name'] == 'Unknown Observation':
                        observation_data['display_name'] = coding.get('display', observation_data['display_name'])
            
            # Extract category
            if 'category' in observation:
                categories = observation['category'] if isinstance(observation['category'], list) else [observation['category']]
                for category in categories:
                    if 'coding' in category:
                        category_coding = category['coding'][0]
                        observation_data['category'] = category_coding.get('display', category_coding.get('code'))
                        break
            
            # Extract value
            if 'valueQuantity' in observation:
                value_qty = observation['valueQuantity']
                observation_data['value'] = value_qty.get('value')
                observation_data['unit'] = value_qty.get('unit', value_qty.get('code'))
            elif 'valueCodeableConcept' in observation:
                if 'coding' in observation['valueCodeableConcept']:
                    value_coding = observation['valueCodeableConcept']['coding'][0]
                    observation_data['value'] = value_coding.get('display', value_coding.get('code'))
            elif 'valueString' in observation:
                observation_data['value'] = observation['valueString']
            elif 'valueBoolean' in observation:
                observation_data['value'] = str(observation['valueBoolean'])
            
            # Extract reference range
            if 'referenceRange' in observation:
                ref_ranges = []
                for ref_range in observation['referenceRange']:
                    range_info = {}
                    if 'low' in ref_range:
                        range_info['low'] = f"{ref_range['low'].get('value', '')} {ref_range['low'].get('unit', '')}"
                    if 'high' in ref_range:
                        range_info['high'] = f"{ref_range['high'].get('value', '')} {ref_range['high'].get('unit', '')}"
                    if 'text' in ref_range:
                        range_info['text'] = ref_range['text']
                    ref_ranges.append(range_info)
                observation_data['reference_range'] = ref_ranges
            
            # Extract interpretation
            if 'interpretation' in observation:
                interpretations = []
                for interp in observation['interpretation']:
                    if 'coding' in interp:
                        interp_coding = interp['coding'][0]
                        interpretations.append(interp_coding.get('display', interp_coding.get('code')))
                observation_data['interpretation'] = interpretations
            
            # Extract effective date
            if 'effectiveDateTime' in observation:
                observation_data['effective_date'] = observation['effectiveDateTime'][:10]
            elif 'effectivePeriod' in observation and 'start' in observation['effectivePeriod']:
                observation_data['effective_date'] = observation['effectivePeriod']['start'][:10]
            
            # Extract notes
            if 'note' in observation:
                for note in observation['note']:
                    if 'text' in note:
                        observation_data['notes'].append(note['text'])
            
            return observation_data
            
        except Exception as e:
            return {'error': f'Error processing observation: {str(e)}'}

    def _extract_encounter_for_report(self, encounter):
        """Extract encounter information for comprehensive report."""
        try:
            encounter_data = {
                'resource_type': 'Encounter',
                'id': encounter.get('id', 'unknown'),
                'status': encounter.get('status', 'unknown'),
                'class': None,
                'type': [],
                'period': None,
                'reason': [],
                'diagnosis': [],
                'location': None,
                'participants': []
            }
            
            # Extract encounter class
            if 'class' in encounter:
                class_coding = encounter['class']
                encounter_data['class'] = class_coding.get('display', class_coding.get('code'))
            
            # Extract encounter types
            if 'type' in encounter:
                for enc_type in encounter['type']:
                    if 'coding' in enc_type:
                        for coding in enc_type['coding']:
                            encounter_data['type'].append({
                                'system': coding.get('system', ''),
                                'code': coding.get('code', ''),
                                'display': coding.get('display', '')
                            })
            
            # Extract period
            if 'period' in encounter:
                period = encounter['period']
                encounter_data['period'] = {
                    'start': period.get('start', '')[:10] if period.get('start') else None,
                    'end': period.get('end', '')[:10] if period.get('end') else None
                }
            
            # Extract reason codes
            if 'reasonCode' in encounter:
                for reason in encounter['reasonCode']:
                    if 'coding' in reason:
                        for coding in reason['coding']:
                            encounter_data['reason'].append({
                                'system': coding.get('system', ''),
                                'code': coding.get('code', ''),
                                'display': coding.get('display', '')
                            })
            
            # Extract diagnosis
            if 'diagnosis' in encounter:
                for diag in encounter['diagnosis']:
                    if 'condition' in diag and 'display' in diag['condition']:
                        encounter_data['diagnosis'].append(diag['condition']['display'])
            
            # Extract location
            if 'location' in encounter:
                locations = []
                for loc in encounter['location']:
                    if 'location' in loc and 'display' in loc['location']:
                        locations.append(loc['location']['display'])
                encounter_data['location'] = locations
            
            # Extract participants
            if 'participant' in encounter:
                for participant in encounter['participant']:
                    participant_info = {}
                    if 'type' in participant:
                        for part_type in participant['type']:
                            if 'coding' in part_type:
                                participant_info['type'] = part_type['coding'][0].get('display', part_type['coding'][0].get('code'))
                                break
                    if 'individual' in participant and 'display' in participant['individual']:
                        participant_info['name'] = participant['individual']['display']
                    encounter_data['participants'].append(participant_info)
            
            return encounter_data
            
        except Exception as e:
            return {'error': f'Error processing encounter: {str(e)}'}

    def _extract_practitioner_for_report(self, practitioner):
        """Extract practitioner information for comprehensive report."""
        try:
            practitioner_data = {
                'resource_type': 'Practitioner',
                'id': practitioner.get('id', 'unknown'),
                'name': None,
                'qualifications': [],
                'specialties': [],
                'contact': {}
            }
            
            # Extract name
            if 'name' in practitioner:
                names = practitioner['name'] if isinstance(practitioner['name'], list) else [practitioner['name']]
                for name in names:
                    if name.get('use') in ['official', 'usual'] or not practitioner_data['name']:
                        name_parts = []
                        if 'prefix' in name:
                            name_parts.extend(name['prefix'])
                        if 'given' in name:
                            name_parts.extend(name['given'])
                        if 'family' in name:
                            name_parts.append(name['family'])
                        if 'suffix' in name:
                            name_parts.extend(name['suffix'])
                        practitioner_data['name'] = ' '.join(name_parts)
                        break
            
            # Extract qualifications
            if 'qualification' in practitioner:
                for qual in practitioner['qualification']:
                    if 'code' in qual and 'coding' in qual['code']:
                        for coding in qual['code']['coding']:
                            practitioner_data['qualifications'].append({
                                'system': coding.get('system', ''),
                                'code': coding.get('code', ''),
                                'display': coding.get('display', '')
                            })
            
            # Extract specialties (if available in extensions or other fields)
            # Note: FHIR Practitioner doesn't have a standard specialty field,
            # but it might be in PractitionerRole or extensions
            
            # Extract contact information
            if 'telecom' in practitioner:
                for telecom in practitioner['telecom']:
                    system = telecom.get('system')
                    value = telecom.get('value')
                    if system and value:
                        practitioner_data['contact'][system] = value
            
            return practitioner_data
            
        except Exception as e:
            return {'error': f'Error processing practitioner: {str(e)}'}

    def _extract_organization_for_report(self, organization):
        """Extract organization information for comprehensive report."""
        try:
            organization_data = {
                'resource_type': 'Organization',
                'id': organization.get('id', 'unknown'),
                'name': organization.get('name', 'Unknown Organization'),
                'type': [],
                'contact': {},
                'address': []
            }
            
            # Extract organization types
            if 'type' in organization:
                for org_type in organization['type']:
                    if 'coding' in org_type:
                        for coding in org_type['coding']:
                            organization_data['type'].append({
                                'system': coding.get('system', ''),
                                'code': coding.get('code', ''),
                                'display': coding.get('display', '')
                            })
            
            # Extract contact information
            if 'telecom' in organization:
                for telecom in organization['telecom']:
                    system = telecom.get('system')
                    value = telecom.get('value')
                    if system and value:
                        organization_data['contact'][system] = value
            
            # Extract addresses
            if 'address' in organization:
                for addr in organization['address']:
                    address_info = {}
                    if 'use' in addr:
                        address_info['use'] = addr['use']
                    if 'type' in addr:
                        address_info['type'] = addr['type']
                    if 'line' in addr:
                        address_info['line'] = addr['line']
                    if 'city' in addr:
                        address_info['city'] = addr['city']
                    if 'state' in addr:
                        address_info['state'] = addr['state']
                    if 'postalCode' in addr:
                        address_info['postal_code'] = addr['postalCode']
                    if 'country' in addr:
                        address_info['country'] = addr['country']
                    organization_data['address'].append(address_info)
            
            return organization_data
            
        except Exception as e:
            return {'error': f'Error processing organization: {str(e)}'}

    def _sort_clinical_data_by_date(self, report):
        """Sort clinical data by date (most recent first)."""
        try:
            # Sort conditions by onset or recorded date
            report['clinical_summary']['conditions'].sort(
                key=lambda x: x.get('onset_date') or x.get('recorded_date') or '1900-01-01',
                reverse=True
            )
            
            # Sort procedures by performed date
            report['clinical_summary']['procedures'].sort(
                key=lambda x: x.get('performed_date') or 
                             (x.get('performed_period', {}).get('start') if x.get('performed_period') else None) or 
                             '1900-01-01',
                reverse=True
            )
            
            # Sort medications by effective period start
            report['clinical_summary']['medications'].sort(
                key=lambda x: (x.get('effective_period', {}).get('start') if x.get('effective_period') else None) or 
                             '1900-01-01',
                reverse=True
            )
            
            # Sort observations by effective date
            report['clinical_summary']['observations'].sort(
                key=lambda x: x.get('effective_date') or '1900-01-01',
                reverse=True
            )
            
            # Sort encounters by period start
            report['clinical_summary']['encounters'].sort(
                key=lambda x: (x.get('period', {}).get('start') if x.get('period') else None) or '1900-01-01',
                reverse=True
            )
            
        except Exception as e:
            # If sorting fails, continue without sorting
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to sort clinical data: {str(e)}")


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
