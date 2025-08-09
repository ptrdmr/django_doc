"""
Core FHIR Resource Models for Medical Document Parser

This module provides custom FHIR resource models that extend the base fhir.resources
classes with additional validation and helper methods specific to our medical
document processing application.

All models follow FHIR R4 specification and include proper type hints and docstrings.
"""

from typing import Optional, List, Dict, Any, Union
from datetime import datetime, date
from uuid import uuid4

from fhir.resources.patient import Patient as FHIRPatient
from fhir.resources.documentreference import DocumentReference as FHIRDocumentReference
from fhir.resources.condition import Condition as FHIRCondition
from fhir.resources.observation import Observation as FHIRObservation
from fhir.resources.medicationstatement import MedicationStatement as FHIRMedicationStatement
from fhir.resources.practitioner import Practitioner as FHIRPractitioner
from fhir.resources.provenance import Provenance as FHIRProvenance
from fhir.resources.resource import Resource
from fhir.resources.reference import Reference
from fhir.resources.identifier import Identifier
from fhir.resources.humanname import HumanName
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.contactpoint import ContactPoint
from fhir.resources.address import Address
from fhir.resources.meta import Meta
from fhir.resources.codeablereference import CodeableReference


class PatientResource(FHIRPatient):
    """
    Extended FHIR Patient resource with custom validation and helper methods
    for medical document processing.
    
    Represents patient demographics and basic identifying information.
    """
    
    @classmethod
    def _convert_django_gender_to_fhir(cls, gender: Optional[str]) -> Optional[str]:
        """
        Convert Django Patient model gender codes to FHIR gender values.
        
        Django uses single letters (M, F, O) while FHIR uses full words.
        
        Args:
            gender: Django gender code ('M', 'F', 'O') or None
            
        Returns:
            FHIR gender value ('male', 'female', 'other', 'unknown') or None
        """
        if not gender:
            return None
            
        gender_mapping = {
            'M': 'male',
            'F': 'female', 
            'O': 'other'
        }
        
        return gender_mapping.get(gender.upper(), 'unknown')
    
    @classmethod
    def from_patient_model(cls, patient_model) -> 'PatientResource':
        """
        Create a PatientResource from a Django Patient model instance.
        
        Args:
            patient_model: Django Patient model instance
            
        Returns:
            PatientResource instance
        """
        # Convert Django gender code to FHIR gender value
        fhir_gender = cls._convert_django_gender_to_fhir(
            patient_model.gender if hasattr(patient_model, 'gender') else None
        )
        
        return cls.create_from_demographics(
            mrn=patient_model.mrn,
            first_name=patient_model.first_name,
            last_name=patient_model.last_name,
            birth_date=patient_model.date_of_birth,
            patient_id=str(patient_model.id),
            gender=fhir_gender,
            phone=None,  # Add phone field to Patient model if needed
            email=None,  # Add email field to Patient model if needed
            address=None  # Add address fields to Patient model if needed
        )
    
    @classmethod
    def create_from_demographics(
        cls,
        mrn: str,
        first_name: str,
        last_name: str,
        birth_date: Union[date, str],
        patient_id: Optional[str] = None,
        gender: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        address: Optional[Dict[str, str]] = None
    ) -> 'PatientResource':
        """
        Create a Patient resource from basic demographic information.
        
        Args:
            mrn: Medical Record Number (unique identifier)
            first_name: Patient's first name
            last_name: Patient's last name
            birth_date: Date of birth (YYYY-MM-DD format or date object)
            patient_id: Optional FHIR resource ID
            gender: Optional gender (male, female, other, unknown)
            phone: Optional phone number
            email: Optional email address
            address: Optional address dictionary with keys: line, city, state, zip
            
        Returns:
            PatientResource instance
        """
        # Generate ID if not provided
        if not patient_id:
            patient_id = str(uuid4())
            
        # Create identifier for MRN
        identifier = [Identifier(
            system="http://example.org/fhir/mrn",
            value=mrn
        )]
        
        # Create human name
        name = [HumanName(
            family=last_name,
            given=[first_name]
        )]
        
        # Convert birth date to string if needed
        if isinstance(birth_date, date):
            birth_date = birth_date.isoformat()
            
        # Create contact points if provided
        telecom = []
        if phone:
            telecom.append(ContactPoint(
                system="phone",
                value=phone
            ))
        if email:
            telecom.append(ContactPoint(
                system="email",
                value=email
            ))
            
        # Create address if provided
        address_list = []
        if address:
            address_list.append(Address(
                line=[address.get('line', '')],
                city=address.get('city', ''),
                state=address.get('state', ''),
                postalCode=address.get('zip', '')
            ))
        
        # Create meta information
        meta = Meta(
            versionId="1",
            lastUpdated=datetime.utcnow().isoformat() + "Z"
        )
        
        return cls(
            id=patient_id,
            meta=meta,
            identifier=identifier,
            name=name,
            birthDate=birth_date,
            gender=gender,
            telecom=telecom if telecom else None,
            address=address_list if address_list else None
        )
    
    def get_display_name(self) -> str:
        """
        Get a human-readable display name for the patient.
        
        Returns:
            Formatted name string (Last, First)
        """
        if self.name and len(self.name) > 0:
            name = self.name[0]
            family = name.family if name.family else "Unknown"
            given = name.given[0] if name.given and len(name.given) > 0 else "Unknown"
            return f"{family}, {given}"
        return "Unknown Patient"
    
    def get_mrn(self) -> Optional[str]:
        """
        Extract the Medical Record Number from identifiers.
        
        Returns:
            MRN string or None if not found
        """
        if self.identifier:
            for identifier in self.identifier:
                if identifier.system == "http://example.org/fhir/mrn":
                    return identifier.value
        return None


class DocumentReferenceResource(FHIRDocumentReference):
    """
    Extended FHIR DocumentReference resource for tracking medical documents
    and their processing status.
    """
    
    @classmethod
    def create_from_document(
        cls,
        patient_id: str,
        document_title: str,
        document_type: str,
        document_url: str,
        document_id: Optional[str] = None,
        creation_date: Optional[datetime] = None,
        author: Optional[str] = None
    ) -> 'DocumentReferenceResource':
        """
        Create a DocumentReference resource from document information.
        
        Args:
            patient_id: FHIR ID of the patient this document belongs to
            document_title: Title/name of the document
            document_type: Type of document (e.g., "clinical-note", "lab-report")
            document_url: URL or path to the document
            document_id: Optional FHIR resource ID
            creation_date: Optional document creation date
            author: Optional document author
            
        Returns:
            DocumentReferenceResource instance
        """
        if not document_id:
            document_id = str(uuid4())
            
        if not creation_date:
            creation_date = datetime.utcnow()
            
        # Create document type coding
        type_coding = CodeableConcept(
            coding=[Coding(
                system="http://loinc.org",
                code=document_type,
                display=document_title
            )]
        )
        
        # Create patient reference
        subject = {"reference": f"Patient/{patient_id}"}
        
        # Create content
        content = [{
            "attachment": {
                "contentType": "application/pdf",  # Default assumption
                "url": document_url,
                "title": document_title
            }
        }]
        
        # Create meta
        meta = Meta(
            versionId="1",
            lastUpdated=creation_date.isoformat() + "Z"
        )
        
        return cls(
            id=document_id,
            meta=meta,
            status="current",
            type=type_coding,
            subject=subject,
            date=creation_date.isoformat() + "Z",
            content=content
        )
    
    def get_document_url(self) -> Optional[str]:
        """
        Extract the document URL from content.
        
        Returns:
            Document URL or None if not found
        """
        if self.content and len(self.content) > 0:
            # Handle FHIR DocumentReferenceContent object
            content = self.content[0]
            if hasattr(content, 'attachment') and content.attachment:
                attachment = content.attachment
                if hasattr(attachment, 'url') and attachment.url:
                    return attachment.url
        return None


class ConditionResource(FHIRCondition):
    """
    Extended FHIR Condition resource for tracking patient diagnoses
    and medical conditions.
    """
    
    @classmethod
    def create_from_diagnosis(
        cls,
        patient_id: str,
        condition_code: str,
        condition_display: str,
        condition_id: Optional[str] = None,
        clinical_status: str = "active",
        onset_date: Optional[Union[date, str]] = None,
        practitioner_id: Optional[str] = None
    ) -> 'ConditionResource':
        """
        Create a Condition resource from diagnosis information.
        
        Args:
            patient_id: FHIR ID of the patient
            condition_code: ICD-10 or SNOMED code for the condition
            condition_display: Human-readable name of the condition
            condition_id: Optional FHIR resource ID
            clinical_status: Status of the condition (active, resolved, etc.)
            onset_date: Optional date when condition was first noted
            practitioner_id: Optional ID of diagnosing practitioner
            
        Returns:
            ConditionResource instance
        """
        if not condition_id:
            condition_id = str(uuid4())
            
        # Create condition coding
        code = CodeableConcept(
            coding=[Coding(
                system="http://hl7.org/fhir/sid/icd-10",
                code=condition_code,
                display=condition_display
            )]
        )
        
        # Create clinical status
        clinical_status_concept = CodeableConcept(
            coding=[Coding(
                system="http://terminology.hl7.org/CodeSystem/condition-clinical",
                code=clinical_status
            )]
        )
        
        # Create patient reference
        subject = {"reference": f"Patient/{patient_id}"}
        
        # Create meta
        meta = Meta(
            versionId="1",
            lastUpdated=datetime.utcnow().isoformat() + "Z"
        )
        
        # Optional onset date
        onset_datetime = None
        if onset_date:
            if isinstance(onset_date, date):
                onset_datetime = onset_date.isoformat()
            else:
                onset_datetime = onset_date
        
        return cls(
            id=condition_id,
            meta=meta,
            clinicalStatus=clinical_status_concept,
            code=code,
            subject=subject,
            onsetDateTime=onset_datetime
        )
    
    def get_condition_code(self) -> Optional[str]:
        """
        Extract the primary condition code.
        
        Returns:
            Condition code or None if not found
        """
        if self.code and self.code.coding:
            return self.code.coding[0].code
        return None
    
    def get_condition_display(self) -> Optional[str]:
        """
        Extract the human-readable condition name.
        
        Returns:
            Condition display name or None if not found
        """
        if self.code and self.code.coding:
            return self.code.coding[0].display
        return None


class ObservationResource(FHIRObservation):
    """
    Extended FHIR Observation resource for lab results, vital signs,
    and other clinical measurements.
    """
    
    @classmethod
    def create_from_lab_result(
        cls,
        patient_id: str,
        test_code: str,
        test_name: str,
        value: Union[str, float, int],
        unit: Optional[str] = None,
        observation_id: Optional[str] = None,
        reference_range: Optional[str] = None,
        observation_date: Optional[datetime] = None
    ) -> 'ObservationResource':
        """
        Create an Observation resource from lab result information.
        
        Args:
            patient_id: FHIR ID of the patient
            test_code: LOINC code for the test
            test_name: Human-readable name of the test
            value: Test result value
            unit: Optional unit of measurement
            observation_id: Optional FHIR resource ID
            reference_range: Optional reference range string
            observation_date: Optional date of observation
            
        Returns:
            ObservationResource instance
        """
        if not observation_id:
            observation_id = str(uuid4())
            
        if not observation_date:
            observation_date = datetime.utcnow()
            
        # Create observation code
        code = CodeableConcept(
            coding=[Coding(
                system="http://loinc.org",
                code=test_code,
                display=test_name
            )]
        )
        
        # Create patient reference
        subject = {"reference": f"Patient/{patient_id}"}
        
        # Create value based on type
        if isinstance(value, (int, float)):
            value_quantity = {
                "value": value,
                "unit": unit if unit else "",
                "system": "http://unitsofmeasure.org"
            }
            value_field = {"valueQuantity": value_quantity}
        else:
            value_field = {"valueString": str(value)}
        
        # Create meta
        meta = Meta(
            versionId="1",
            lastUpdated=observation_date.isoformat() + "Z"
        )
        
        return cls(
            id=observation_id,
            meta=meta,
            status="final",
            code=code,
            subject=subject,
            effectiveDateTime=observation_date.isoformat() + "Z",
            **value_field
        )
    
    def get_test_name(self) -> Optional[str]:
        """
        Extract the test name from the observation.
        
        Returns:
            Test name or None if not found
        """
        if self.code and self.code.coding:
            return self.code.coding[0].display
        return None
    
    def get_value_with_unit(self) -> str:
        """
        Get the observation value with its unit.
        
        Returns:
            Formatted value string
        """
        if hasattr(self, 'valueQuantity') and self.valueQuantity:
            value = self.valueQuantity.value
            unit = self.valueQuantity.unit or ""
            return f"{value} {unit}".strip()
        elif hasattr(self, 'valueString') and self.valueString:
            return self.valueString
        return "No value"


class MedicationStatementResource(FHIRMedicationStatement):
    """
    Extended FHIR MedicationStatement resource for tracking patient medications.
    """
    
    @classmethod
    def create_from_medication(
        cls,
        patient_id: str,
        medication_name: str,
        medication_code: Optional[str] = None,
        dosage: Optional[str] = None,
        frequency: Optional[str] = None,
        medication_id: Optional[str] = None,
        status: str = "active",
        effective_date: Optional[datetime] = None
    ) -> 'MedicationStatementResource':
        """
        Create a MedicationStatement resource from medication information.
        
        Args:
            patient_id: FHIR ID of the patient
            medication_name: Name of the medication
            medication_code: Optional RxNorm or NDC code
            dosage: Optional dosage information
            frequency: Optional frequency (e.g., "twice daily")
            medication_id: Optional FHIR resource ID
            status: Medication status (active, stopped, etc.)
            effective_date: Optional start date
            
        Returns:
            MedicationStatementResource instance
        """
        if not medication_id:
            medication_id = str(uuid4())
            
        if not effective_date:
            effective_date = datetime.utcnow()
            
        # Create medication coding
        medication_concept = CodeableConcept(
            coding=[Coding(
                system="http://www.nlm.nih.gov/research/umls/rxnorm",
                code=medication_code if medication_code else "unknown",
                display=medication_name
            )]
        )
        
        # Create medication reference using CodeableReference
        medication_ref = CodeableReference(
            concept=medication_concept
        )
        
        # Create patient reference
        subject = Reference(reference=f"Patient/{patient_id}")
        
        # Create dosage if provided
        dosage_list = []
        if dosage or frequency:
            dosage_entry = {
                "sequence": 1
            }
            if dosage:
                dosage_entry["text"] = dosage
            if frequency:
                # Parse frequency to extract numeric value
                frequency_value = 1  # default
                if "twice" in frequency.lower():
                    frequency_value = 2
                elif "three" in frequency.lower() or "thrice" in frequency.lower():
                    frequency_value = 3
                elif "four" in frequency.lower():
                    frequency_value = 4
                elif frequency.lower().startswith("once"):
                    frequency_value = 1
                else:
                    # Try to extract number from string
                    import re
                    numbers = re.findall(r'\d+', frequency)
                    if numbers:
                        frequency_value = int(numbers[0])
                
                dosage_entry["timing"] = {
                    "repeat": {
                        "frequency": frequency_value,
                        "period": 1,
                        "periodUnit": "d"  # daily
                    }
                }
            dosage_list.append(dosage_entry)
        
        # Create meta
        meta = Meta(
            versionId="1",
            lastUpdated=effective_date.isoformat() + "Z"
        )
        
        return cls(
            id=medication_id,
            meta=meta,
            status=status,
            medication=medication_ref,
            subject=subject,
            effectiveDateTime=effective_date.isoformat() + "Z",
            dosage=dosage_list if dosage_list else None
        )
    
    def get_medication_name(self) -> Optional[str]:
        """
        Extract the medication name.
        
        Returns:
            Medication name or None if not found
        """
        if self.medication and self.medication.concept:
            return self.medication.concept.coding[0].display
        return None
    
    def get_dosage_text(self) -> Optional[str]:
        """
        Extract the dosage instructions.
        
        Returns:
            Dosage text or None if not found
        """
        if self.dosage and len(self.dosage) > 0:
            # The dosage is created as a dict in create_from_medication, so we need to handle both cases
            dosage_item = self.dosage[0]
            if isinstance(dosage_item, dict):
                return dosage_item.get("text")
            else:
                # If it's a FHIR Dosage object, access the text attribute
                return getattr(dosage_item, 'text', None)
        return None


class PractitionerResource(FHIRPractitioner):
    """
    Extended FHIR Practitioner resource for healthcare providers.
    """
    
    @classmethod
    def create_from_provider(
        cls,
        first_name: str,
        last_name: str,
        npi: Optional[str] = None,
        specialty: Optional[str] = None,
        practitioner_id: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None
    ) -> 'PractitionerResource':
        """
        Create a Practitioner resource from provider information.
        
        Args:
            first_name: Provider's first name
            last_name: Provider's last name
            npi: Optional National Provider Identifier
            specialty: Optional medical specialty
            practitioner_id: Optional FHIR resource ID
            phone: Optional phone number
            email: Optional email address
            
        Returns:
            PractitionerResource instance
        """
        if not practitioner_id:
            practitioner_id = str(uuid4())
            
        # Create identifier for NPI if provided
        identifier = []
        if npi:
            identifier.append(Identifier(
                system="http://hl7.org/fhir/sid/us-npi",
                value=npi
            ))
        
        # Create human name
        name = [HumanName(
            family=last_name,
            given=[first_name]
        )]
        
        # Create contact points if provided
        telecom = []
        if phone:
            telecom.append(ContactPoint(
                system="phone",
                value=phone
            ))
        if email:
            telecom.append(ContactPoint(
                system="email",
                value=email
            ))
        
        # Create meta
        meta = Meta(
            versionId="1",
            lastUpdated=datetime.utcnow().isoformat() + "Z"
        )
        
        return cls(
            id=practitioner_id,
            meta=meta,
            identifier=identifier if identifier else None,
            name=name,
            telecom=telecom if telecom else None
        )
    
    def get_display_name(self) -> str:
        """
        Get a human-readable display name for the practitioner.
        
        Returns:
            Formatted name string (Last, First)
        """
        if self.name and len(self.name) > 0:
            name = self.name[0]
            family = name.family if name.family else "Unknown"
            given = name.given[0] if name.given and len(name.given) > 0 else "Unknown"
            return f"Dr. {family}, {given}"
        return "Unknown Practitioner"
    
    def get_npi(self) -> Optional[str]:
        """
        Extract the National Provider Identifier.
        
        Returns:
            NPI string or None if not found
        """
        if self.identifier:
            for identifier in self.identifier:
                if identifier.system == "http://hl7.org/fhir/sid/us-npi":
                    return identifier.value
        return None


class ProvenanceResource(FHIRProvenance):
    """
    Extended FHIR Provenance resource for tracking the origin and history
    of FHIR resources in medical document processing.
    
    Maintains an audit trail of who, what, when, where, and why for each
    clinical resource in the system.
    """
    
    @classmethod
    def create_for_resource(
        cls,
        target_resource: Resource,
        source_system: str,
        responsible_party: Optional[str] = None,
        activity_type: str = "create",
        provenance_id: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
        reason: Optional[str] = None,
        source_document_id: Optional[str] = None
    ) -> 'ProvenanceResource':
        """
        Create a Provenance resource for tracking a specific FHIR resource.
        
        Args:
            target_resource: The FHIR resource this provenance tracks
            source_system: Identifier for the source system (e.g., "EMR-System", "Document-Parser")
            responsible_party: Optional identifier for responsible person/system
            activity_type: Type of activity (create, update, delete, transform)
            provenance_id: Optional FHIR resource ID
            occurred_at: Optional timestamp when activity occurred
            reason: Optional reason for the activity
            source_document_id: Optional ID of source document that generated this resource
            
        Returns:
            ProvenanceResource instance
        """
        if not provenance_id:
            provenance_id = str(uuid4())
            
        if not occurred_at:
            occurred_at = datetime.utcnow()
            
        # Create target reference
        target = [Reference(
            reference=f"{target_resource.resource_type}/{target_resource.id}"
        )]
        
        # Create activity coding
        activity = CodeableConcept(
            coding=[Coding(
                system="http://terminology.hl7.org/CodeSystem/v3-DataOperation",
                code=activity_type.upper(),
                display=activity_type.title()
            )]
        )
        
        # Create agents (who was responsible)
        agent = []
        
        # Add responsible party as author if provided
        if responsible_party:
            agent.append({
                "type": CodeableConcept(
                    coding=[Coding(
                        system="http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                        code="author",
                        display="Author"
                    )]
                ),
                "who": Reference(display=responsible_party)
            })
        
        # Add source system as assembler 
        agent.append({
            "type": CodeableConcept(
                coding=[Coding(
                    system="http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                    code="assembler",
                    display="Assembler"
                )]
            ),
            "who": Reference(display=source_system)
        })
        
        # If no responsible party provided, also make source system the author
        if not responsible_party:
            agent.append({
                "type": CodeableConcept(
                    coding=[Coding(
                        system="http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                        code="author",
                        display="Author"
                    )]
                ),
                "who": Reference(display=source_system)
            })
        
        # Create meta
        meta = Meta(
            versionId="1",
            lastUpdated=occurred_at
        )
        
        # Build provenance resource
        provenance_data = {
            "id": provenance_id,
            "meta": meta,
            "target": target,
            "occurredDateTime": occurred_at,
            "recorded": occurred_at,
            "activity": activity,
            "agent": agent
        }
        
        # Add optional reason as extension (since FHIR doesn't have direct reason field)
        if reason:
            provenance_data["extension"] = [{
                "url": "http://example.org/fhir/StructureDefinition/provenance-reason",
                "valueString": reason
            }]
            
        # Add source document reference if provided
        if source_document_id:
            provenance_data["entity"] = [{
                "role": "source",
                "what": Reference(reference=f"DocumentReference/{source_document_id}")
            }]
        
        return cls(**provenance_data)
    
    @classmethod
    def create_for_update(
        cls,
        target_resource: Resource,
        previous_provenance: 'ProvenanceResource',
        responsible_party: Optional[str] = None,
        reason: Optional[str] = None,
        provenance_id: Optional[str] = None,
        occurred_at: Optional[datetime] = None
    ) -> 'ProvenanceResource':
        """
        Create a Provenance resource for tracking a resource update,
        maintaining the provenance chain from the previous version.
        
        Args:
            target_resource: The updated FHIR resource
            previous_provenance: Previous provenance resource in the chain
            responsible_party: Optional identifier for responsible person/system
            reason: Optional reason for the update
            provenance_id: Optional FHIR resource ID
            occurred_at: Optional timestamp when update occurred
            
        Returns:
            ProvenanceResource instance
        """
        if not occurred_at:
            occurred_at = datetime.utcnow()
            
        # Extract source system from previous provenance
        source_system = previous_provenance.get_source_system() or "Unknown System"
        
        # Create new provenance with update activity
        new_provenance = cls.create_for_resource(
            target_resource=target_resource,
            source_system=source_system,
            responsible_party=responsible_party,
            activity_type="update",
            provenance_id=provenance_id,
            occurred_at=occurred_at,
            reason=reason
        )
        
        # Add entity reference to previous provenance to maintain chain
        if not hasattr(new_provenance, 'entity') or not new_provenance.entity:
            new_provenance.entity = []
            
        # Add the revision entity to link to previous provenance
        revision_entity = {
            "role": "revision",
            "what": Reference(reference=f"Provenance/{previous_provenance.id}")
        }
        new_provenance.entity.append(revision_entity)
        
        return new_provenance
    
    def get_target_reference(self) -> Optional[str]:
        """
        Extract the primary target resource reference.
        
        Returns:
            Target resource reference or None if not found
        """
        if self.target and len(self.target) > 0:
            return self.target[0].reference
        return None
    
    def get_source_system(self) -> Optional[str]:
        """
        Extract the source system name from agents.
        
        Returns:
            Source system name or None if not found
        """
        if self.agent:
            # First pass: look for assembler (source system)
            for agent in self.agent:
                if agent.type and agent.type.coding:
                    for coding in agent.type.coding:
                        if coding.code == "assembler":
                            return agent.who.display
            
            # Second pass: fall back to author if no assembler found
            for agent in self.agent:
                if agent.type and agent.type.coding:
                    for coding in agent.type.coding:
                        if coding.code == "author":
                            return agent.who.display
        return None
    
    def get_responsible_party(self) -> Optional[str]:
        """
        Extract the responsible party from agents.
        
        Returns:
            Responsible party name or None if not found
        """
        if self.agent:
            for agent in self.agent:
                if agent.type and agent.type.coding:
                    for coding in agent.type.coding:
                        if coding.code == "author":
                            return agent.who.display
        return None
    
    def get_activity_type(self) -> Optional[str]:
        """
        Extract the activity type.
        
        Returns:
            Activity type or None if not found
        """
        if self.activity and self.activity.coding:
            return self.activity.coding[0].code.lower()
        return None
    
    def get_source_document_id(self) -> Optional[str]:
        """
        Extract the source document ID from entities.
        
        Returns:
            Source document ID or None if not found
        """
        if self.entity:
            for entity in self.entity:
                # Handle both dict and ProvenanceEntity objects
                if isinstance(entity, dict):
                    role = entity.get("role")
                    what = entity.get("what")
                    if role == "source" and what:
                        ref = what.reference if hasattr(what, 'reference') else what.get("reference")
                        if ref and ref.startswith("DocumentReference/"):
                            return ref.replace("DocumentReference/", "")
                else:
                    # ProvenanceEntity object
                    if entity.role == "source" and entity.what:
                        ref = entity.what.reference
                        if ref and ref.startswith("DocumentReference/"):
                            return ref.replace("DocumentReference/", "")
        return None
    
    def get_previous_provenance_id(self) -> Optional[str]:
        """
        Extract the previous provenance ID from entities to follow the chain.
        
        Returns:
            Previous provenance ID or None if not found
        """
        if self.entity:
            for entity in self.entity:
                # Handle both dict and ProvenanceEntity objects
                if isinstance(entity, dict):
                    role = entity.get("role")
                    what = entity.get("what")
                    if role == "revision" and what:
                        ref = what.reference if hasattr(what, 'reference') else what.get("reference")
                        if ref and ref.startswith("Provenance/"):
                            return ref.replace("Provenance/", "")
                else:
                    # ProvenanceEntity object
                    if entity.role == "revision" and entity.what:
                        ref = entity.what.reference
                        if ref and ref.startswith("Provenance/"):
                            return ref.replace("Provenance/", "")
        return None 