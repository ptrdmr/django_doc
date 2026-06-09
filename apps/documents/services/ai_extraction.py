"""
AI Extraction Service with Instructor-based Structured Data Extraction

This service uses the instructor library with Anthropic Claude (primary) and OpenAI (fallback)
to provide structured medical data extraction from clinical documents with Pydantic validation.
Follows the project's established AI service patterns and configuration.

Enhanced with comprehensive error handling and logging for Task 34.5.
Memory optimizations added for large document processing (OOM fix).
"""

import logging
import json
import instructor
import time
import re
import gc
from typing import List, Optional, Dict, Any, Union, Literal
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationError
from django.conf import settings
import anthropic
from openai import OpenAI


def _force_gc(context: str = ""):
    """
    Force garbage collection after freeing large variables.
    Caller is responsible for `del`-ing variables before calling this.
    """
    gc.collect()
    if context:
        logger.debug(f"GC forced: {context}")

# Import custom exceptions for enhanced error handling
from apps.documents.exceptions import (
    AIExtractionError,
    AIServiceTimeoutError,
    AIServiceRateLimitError,
    AIResponseParsingError,
    PydanticModelError,
    ConfigurationError,
    ExternalServiceError
)

logger = logging.getLogger(__name__)

# FHIR-aligned date granularity when only partial dates appear in source text (no invented day/month).
DateGranularityLiteral = Literal['year', 'month', 'day']

# Import enhanced prompting service for comprehensive data capture
# Note: This import is now handled locally in each function to avoid scope issues

# Initialize AI clients following project patterns with enhanced error handling
def _initialize_ai_clients():
    """
    Initialize AI clients with comprehensive error handling and validation.

    Returns (anthropic_client, openai_client, anthropic_raw_client). The raw
    client is kept un-patched because instructor's wrapper replaces
    messages.create with a signature requiring response_model — the manual
    JSON fallback path needs the original SDK call.
    """
    anthropic_client = None
    openai_client = None
    anthropic_raw_client = None
    
    try:
        # Validate configuration
        anthropic_key = getattr(settings, 'ANTHROPIC_API_KEY', None)
        openai_key = getattr(settings, 'OPENAI_API_KEY', None)
        
        if not anthropic_key and not openai_key:
            raise ConfigurationError(
                "No AI service API keys configured",
                config_key="ANTHROPIC_API_KEY, OPENAI_API_KEY",
                details={
                    'available_settings': dir(settings),
                    'has_anthropic_key': bool(anthropic_key),
                    'has_openai_key': bool(openai_key)
                }
            )
        
        # Initialize Anthropic Claude (primary) with explicit HTTP timeouts.
        # Without a timeout the SDK default (~10 min read) lets hung connections
        # burn the entire Celery task budget. max_retries=1 stops the SDK from
        # silently multiplying API cost on transient failures.
        if anthropic_key:
            try:
                request_timeout = float(getattr(settings, 'AI_REQUEST_TIMEOUT', 120))
                anthropic_client = anthropic.Anthropic(
                    api_key=anthropic_key,
                    timeout=anthropic.Timeout(
                        connect=10.0,
                        read=request_timeout,
                        write=request_timeout,
                        pool=30.0,
                    ),
                    max_retries=1,
                )
                logger.info(
                    f"Anthropic Claude client initialized successfully (primary, "
                    f"timeout={request_timeout}s, max_retries=1)"
                )
            except Exception as e:
                logger.error(f"Failed to initialize Anthropic client: {e}")
                anthropic_client = None
        
        # Initialize OpenAI (fallback)
        if openai_key:
            try:
                openai_client = instructor.patch(OpenAI(api_key=openai_key))
                logger.info("OpenAI client initialized successfully (fallback)")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                openai_client = None
        
        # Try to patch Anthropic client with instructor for Pydantic support,
        # keeping the raw client for the manual JSON fallback path
        if anthropic_client:
            anthropic_raw_client = anthropic_client
            try:
                from instructor import from_anthropic
                anthropic_client = from_anthropic(anthropic_client)
                logger.info("Anthropic Claude client patched with instructor for Pydantic support")
            except Exception as e:
                logger.warning(f"Could not patch Anthropic client with instructor: {e}, using manual JSON parsing")
                # anthropic_client remains unpatched - will use manual JSON parsing
        
        if not anthropic_client and not openai_client:
            raise ConfigurationError(
                "Failed to initialize any AI clients",
                details={'anthropic_available': bool(anthropic_key), 'openai_available': bool(openai_key)}
            )
        
        logger.info(f"AI clients initialized - Claude: {bool(anthropic_client)}, OpenAI: {bool(openai_client)}")
        return anthropic_client, openai_client, anthropic_raw_client
        
    except ConfigurationError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error initializing AI clients: {e}")
        raise ConfigurationError(
            f"Failed to initialize AI clients: {str(e)}",
            details={'exception_type': type(e).__name__}
        )

# Initialize clients
try:
    anthropic_client, openai_client, anthropic_raw_client = _initialize_ai_clients()
except ConfigurationError as e:
    logger.warning(f"AI client initialization failed: {e}")
    anthropic_client = None
    openai_client = None
    anthropic_raw_client = None


class SourceContext(BaseModel):
    """Context information about where data was extracted from in the source text."""
    text: str = Field(description="The exact text snippet from the document")
    start_index: int = Field(description="Approximate start position in source text", ge=0, default=0)
    end_index: int = Field(description="Approximate end position in source text", ge=0, default=0)
    
    @field_validator('end_index')
    @classmethod
    def end_after_start(cls, v, info):
        start = info.data.get('start_index', 0)
        if v < start and v != 0:
            v = start + len(info.data.get('text', ''))
        return v


class MedicalCondition(BaseModel):
    """A medical condition, diagnosis, or clinical finding."""
    name: str = Field(description="The medical condition or diagnosis name")
    status: str = Field(
        description="Status of the condition",
        default="active"
    )
    evidence_type: Optional[Literal[
        "explicit_diagnosis",   # Provider wrote "Diagnosis: ..."
        "problem_list",         # Listed in a problem list
        "assessment",           # Stated in assessment/impression section
        "history",              # Documented in past medical history
        "inferred",             # VIOLATION MARKER: AI derived this -- should not happen
    ]] = Field(
        default=None,
        description=(
            "How this condition was identified in the document. You should NEVER need to "
            "use 'inferred' -- only extract conditions a provider explicitly states. "
            "If this is set to 'inferred', the system will flag it as a data quality issue."
        )
    )
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    onset_date: Optional[str] = Field(default=None, description="When condition was diagnosed")
    date_precision: Optional[DateGranularityLiteral] = Field(
        default=None,
        description="Granularity of onset_date only: year (YYYY), month (YYYY-MM), or full day (YYYY-MM-DD)."
    )
    icd_code: Optional[str] = Field(default=None, description="ICD-10 code if present in the document")
    snomed_code: Optional[str] = Field(default=None, description="SNOMED CT code if present in the document")
    source: SourceContext = Field(description="Source context in the document")


class Medication(BaseModel):
    """A medication, drug, or therapeutic substance."""
    name: str = Field(description="The medication name (as written; prefer the primary label)")
    generic_name: Optional[str] = Field(default=None, description="Generic drug name if stated")
    brand_name: Optional[str] = Field(default=None, description="Brand/trade name if stated")
    dosage: Optional[str] = Field(default=None, description="Strength only (e.g., '0.4 mg', '10 mg')")
    dosage_form: Optional[str] = Field(default=None, description="Form (capsule, tablet, solution, etc.)")
    quantity: Optional[str] = Field(default=None, description="Amount per dose (e.g., '1 capsule', '2 tablets')")
    route: Optional[str] = Field(default=None, description="Route of administration (oral, IV, topical, etc.)")
    frequency: Optional[str] = Field(default=None, description="Dosing frequency (daily, BID, every 6 hours, etc.)")
    sig: Optional[str] = Field(
        default=None,
        description="Complete SIG/instruction text verbatim (e.g., 'Take 1 capsule twice a day by oral route'). Do NOT truncate."
    )
    refills: Optional[str] = Field(default=None, description="Refills authorized if stated (e.g., '3', '0', 'PRN')")
    prescriber: Optional[str] = Field(default=None, description="Prescribing provider if stated")
    status: str = Field(description="Medication status", default="active")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    start_date: Optional[str] = Field(default=None, description="When medication was started")
    stop_date: Optional[str] = Field(default=None, description="When medication was stopped")
    date_precision: Optional[DateGranularityLiteral] = Field(
        default=None,
        description="Granularity of start_date/stop_date strings when present."
    )
    source: SourceContext = Field(description="Source context in the document")


class VitalSignComponent(BaseModel):
    """A single component of a multi-part vital sign (e.g., systolic/diastolic of a BP)."""
    measurement: str = Field(description="Component name (e.g., 'systolic', 'diastolic')")
    value: str = Field(description="The measured value for this component")
    unit: Optional[str] = Field(default=None, description="Unit of measurement")


class VitalSign(BaseModel):
    """A vital sign measurement."""
    measurement: str = Field(description="Type of vital sign")
    value: str = Field(description="The measured value")
    unit: Optional[str] = Field(default=None, description="Unit of measurement")
    category: Optional[str] = Field(
        default="vital-signs",
        description="Observation category: 'vital-signs' (default), 'exam', or 'social-history'."
    )
    components: List[VitalSignComponent] = Field(
        default_factory=list,
        description="Sub-measurements for composite vitals (e.g., systolic + diastolic for blood pressure)."
    )
    timestamp: Optional[str] = Field(default=None, description="When measurement was taken")
    date_precision: Optional[DateGranularityLiteral] = Field(
        default=None,
        description="Granularity of timestamp when present."
    )
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class LabResult(BaseModel):
    """A laboratory test result."""
    test_name: str = Field(description="Name of the laboratory test")
    value: str = Field(description="Test result value")
    unit: Optional[str] = Field(default=None, description="Unit of measurement")
    reference_range: Optional[str] = Field(default=None, description="Normal reference range exactly as shown in the lab table row")
    abnormal_flag: Optional[str] = Field(
        default=None,
        description="Abnormal flag if shown (e.g., 'H', 'L', 'HH', 'LL', 'A', 'critical')."
    )
    category: Optional[str] = Field(
        default="laboratory",
        description="Observation category: 'laboratory' (default), 'vital-signs', 'exam', or 'social-history'."
    )
    panel_name: Optional[str] = Field(
        default=None,
        description=(
            "Lab panel this test belongs to if identifiable (e.g., 'Comprehensive Metabolic Panel', "
            "'CBC with Differential', 'Lipid Panel'). Used to group results into diagnostic reports."
        )
    )
    status: Optional[str] = Field(default=None, description="Result status")
    test_date: Optional[str] = Field(default=None, description="Date test was performed")
    date_precision: Optional[DateGranularityLiteral] = Field(
        default=None,
        description="Granularity of test_date when present."
    )
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class Procedure(BaseModel):
    """A medical procedure or intervention."""
    name: str = Field(description="Name of the procedure")
    cpt_code: Optional[str] = Field(default=None, description="CPT code if present in the document")
    procedure_date: Optional[str] = Field(default=None, description="Date procedure was performed")
    provider: Optional[str] = Field(default=None, description="Provider who performed procedure")
    outcome: Optional[str] = Field(default=None, description="Outcome or result")
    date_precision: Optional[DateGranularityLiteral] = Field(
        default=None,
        description="Granularity of procedure_date when present."
    )
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class Immunization(BaseModel):
    """A vaccine administration or immunization record."""
    vaccine_name: str = Field(description="Name of the vaccine (e.g., 'Influenza', 'Tdap', 'COVID-19')")
    cvx_code: Optional[str] = Field(default=None, description="CVX vaccine code if present in the document")
    date_administered: Optional[str] = Field(default=None, description="Date the vaccine was administered")
    date_precision: Optional[DateGranularityLiteral] = Field(
        default=None,
        description="Granularity of date_administered when present."
    )
    lot_number: Optional[str] = Field(default=None, description="Vaccine lot number if stated")
    manufacturer: Optional[str] = Field(default=None, description="Vaccine manufacturer if stated")
    dose_number: Optional[str] = Field(default=None, description="Dose number in series (e.g., '1', '2', 'booster')")
    route: Optional[str] = Field(default=None, description="Route of administration (e.g., intramuscular, subcutaneous)")
    site: Optional[str] = Field(default=None, description="Body site of administration (e.g., left deltoid)")
    status: Optional[str] = Field(
        default="completed",
        description="Status: completed, entered-in-error, not-done. Default completed for documented administrations."
    )
    is_forecast: bool = Field(
        default=False,
        description="True if this is a recommended/forecast/due vaccine rather than an administered one."
    )
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class Provider(BaseModel):
    """A healthcare provider."""
    name: str = Field(description="Provider's name")
    specialty: Optional[str] = Field(default=None, description="Medical specialty")
    role: Optional[str] = Field(default=None, description="Role in patient care")
    contact_info: Optional[str] = Field(default=None, description="Contact information")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class Encounter(BaseModel):
    """A clinical encounter or visit."""
    encounter_id: Optional[str] = Field(default=None, description="Unique identifier for this encounter")
    encounter_type: str = Field(description="Type: office visit, emergency, telehealth, inpatient, outpatient, etc.")
    encounter_date: Optional[str] = Field(default=None, description="Start date/time of encounter (ISO format preferred)")
    encounter_end_date: Optional[str] = Field(default=None, description="End date/time if applicable")
    location: Optional[str] = Field(default=None, description="Facility or location name")
    reason: Optional[str] = Field(default=None, description="Chief complaint or reason for visit")
    participants: List[str] = Field(default_factory=list, description="Provider names involved in encounter")
    status: Optional[str] = Field(default=None, description="Status: planned, arrived, in-progress, finished, cancelled")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class ServiceRequest(BaseModel):
    """A service request, order, or referral."""
    request_id: Optional[str] = Field(default=None, description="Unique identifier")
    request_type: str = Field(description="Type: lab test, imaging study, referral, consultation, procedure order")
    requester: Optional[str] = Field(default=None, description="Ordering provider name")
    reason: Optional[str] = Field(default=None, description="Clinical indication or reason for request")
    priority: Optional[str] = Field(default=None, description="Priority: routine, urgent, stat, asap")
    clinical_context: Optional[str] = Field(default=None, description="Additional clinical context")
    request_date: Optional[str] = Field(default=None, description="Date order was placed")
    forecast_due_date: Optional[str] = Field(
        default=None,
        description="For vaccine forecasts or scheduled orders, the due/overdue date if stated."
    )
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class DiagnosticReport(BaseModel):
    """A diagnostic report or study result."""
    report_id: Optional[str] = Field(default=None, description="Unique identifier")
    report_type: str = Field(description="Type: lab, radiology, pathology, cardiology, etc.")
    findings: str = Field(description="Key findings or results from report")
    conclusion: Optional[str] = Field(default=None, description="Diagnostic conclusion or impression")
    recommendations: Optional[str] = Field(default=None, description="Recommended follow-up or actions")
    status: Optional[str] = Field(default=None, description="Status: preliminary, final, amended, corrected")
    report_date: Optional[str] = Field(default=None, description="Date report was generated")
    ordering_provider: Optional[str] = Field(default=None, description="Provider who ordered the test")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class AllergyIntolerance(BaseModel):
    """An allergy or intolerance to a substance."""
    allergy_id: Optional[str] = Field(default=None, description="Unique identifier")
    allergen: str = Field(description="Substance causing allergy (medication, food, environmental)")
    reaction: Optional[str] = Field(default=None, description="Type of reaction observed")
    severity: Optional[str] = Field(default=None, description="Severity: mild, moderate, severe, life-threatening")
    onset_date: Optional[str] = Field(default=None, description="Date allergy was first observed")
    status: Optional[str] = Field(default=None, description="Status: active, inactive, resolved")
    verification_status: Optional[str] = Field(default=None, description="Verification: confirmed, unconfirmed, refuted")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class CarePlan(BaseModel):
    """A care plan or treatment plan."""
    plan_id: Optional[str] = Field(default=None, description="Unique identifier")
    plan_description: str = Field(description="Overview of care plan or treatment plan")
    goals: List[str] = Field(default_factory=list, description="Care goals or treatment objectives")
    activities: List[str] = Field(default_factory=list, description="Planned activities or interventions")
    period_start: Optional[str] = Field(default=None, description="Care plan start date")
    period_end: Optional[str] = Field(default=None, description="Care plan end date")
    status: Optional[str] = Field(default=None, description="Status: draft, active, completed, cancelled")
    intent: Optional[str] = Field(default=None, description="Intent: proposal, plan, order")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class Organization(BaseModel):
    """A healthcare organization or facility."""
    organization_id: Optional[str] = Field(default=None, description="Unique identifier")
    name: str = Field(description="Organization or facility name")
    role_in_document: Optional[Literal[
        "care_site",        # Treating facility / clinic / hospital
        "performing_lab",   # Lab that ran the tests
        "ordering_org",     # Organization that ordered the service
        "pharmacy",         # Dispensing pharmacy
        "payer",            # Insurance / payer
        "fax_header",       # Fax routing header (administrative noise)
        "admin",            # Other administrative/routing org (noise)
    ]] = Field(
        default=None,
        description=(
            "Role this organization plays in the document. Used to filter administrative "
            "noise (fax headers, release-form boilerplate, CC lists) from clinically relevant orgs."
        )
    )
    identifier: Optional[str] = Field(default=None, description="NPI, tax ID, or other identifier")
    organization_type: Optional[str] = Field(default=None, description="Type: hospital, clinic, lab, pharmacy, payer, etc.")
    address: Optional[str] = Field(default=None, description="Physical address")
    city: Optional[str] = Field(default=None, description="City")
    state: Optional[str] = Field(default=None, description="State or province")
    postal_code: Optional[str] = Field(default=None, description="ZIP or postal code")
    phone: Optional[str] = Field(default=None, description="Contact phone number")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class FamilyMemberHistory(BaseModel):
    """Family history row for FHIR FamilyMemberHistory conversion."""

    relationship: str = Field(description="Relationship to patient (e.g. mother, father, sibling)")
    condition: str = Field(description="Reported condition or cause of death in relative")
    onset_age: Optional[str] = Field(default=None, description="Age at onset if stated")
    deceased: Optional[bool] = Field(default=None, description="Whether relative is deceased if stated")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class PhysicalExamFinding(BaseModel):
    """Physical exam bullet mapped to Observation (category exam)."""

    body_site: Optional[str] = Field(default=None, description="Body area if mentioned")
    finding: str = Field(description="Exam finding narrative")
    status: Optional[str] = Field(default=None, description="normal, abnormal, or similar if discernible")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class SocialHistoryItem(BaseModel):
    """Social history row mapped to Observation (category social-history)."""

    category: Optional[str] = Field(
        default=None,
        description="living_arrangement, employment, substance_use, tobacco, alcohol, support_system, etc.",
    )
    description: str = Field(description="Social history narrative")
    confidence: float = Field(description="Confidence score (0.0-1.0)", ge=0.0, le=1.0, default=0.8)
    source: SourceContext = Field(description="Source context in the document")


class StructuredMedicalExtraction(BaseModel):
    """Complete structured medical data extraction from a clinical document."""
    
    # Core medical data
    conditions: List[MedicalCondition] = Field(
        default_factory=list,
        description="All medical conditions, diagnoses, and clinical findings"
    )
    medications: List[Medication] = Field(
        default_factory=list,
        description="All medications, drugs, and therapeutic substances"
    )
    vital_signs: List[VitalSign] = Field(
        default_factory=list,
        description="All vital sign measurements"
    )
    lab_results: List[LabResult] = Field(
        default_factory=list,
        description="All laboratory test results"
    )
    procedures: List[Procedure] = Field(
        default_factory=list,
        description="All medical procedures and interventions"
    )
    immunizations: List[Immunization] = Field(
        default_factory=list,
        description="All vaccine administrations and immunization records"
    )
    providers: List[Provider] = Field(
        default_factory=list,
        description="All healthcare providers mentioned"
    )
    encounters: List[Encounter] = Field(
        default_factory=list,
        description="All clinical encounters and visits documented"
    )
    service_requests: List[ServiceRequest] = Field(
        default_factory=list,
        description="All service requests, orders, and referrals"
    )
    diagnostic_reports: List[DiagnosticReport] = Field(
        default_factory=list,
        description="All diagnostic reports and study results"
    )
    allergies: List[AllergyIntolerance] = Field(
        default_factory=list,
        description="All documented allergies and intolerances"
    )
    care_plans: List[CarePlan] = Field(
        default_factory=list,
        description="All documented care plans and treatment plans"
    )
    organizations: List[Organization] = Field(
        default_factory=list,
        description="All healthcare organizations and facilities mentioned"
    )
    family_history: List[FamilyMemberHistory] = Field(
        default_factory=list,
        description="Family history entries for pedigree-relevant conditions"
    )
    physical_exam_findings: List[PhysicalExamFinding] = Field(
        default_factory=list,
        description="Structured physical exam bullets from exam section"
    )
    social_history: List[SocialHistoryItem] = Field(
        default_factory=list,
        description="Social determinants / living situation / tobacco alcohol employment when documented"
    )
    
    # Metadata
    clinical_date: Optional[str] = Field(
        default=None,
        description=(
            "Primary clinical date of this document (visit date, lab collection date, "
            "service date). Use the date the care described actually occurred, not the "
            "print/fax date. Partial dates allowed (YYYY or YYYY-MM)."
        )
    )
    clinical_date_source: Optional[str] = Field(
        default=None,
        description="Where the clinical date was found (e.g., 'encounter header', 'lab collection date')."
    )
    extraction_timestamp: str = Field(description="When this extraction was performed")
    document_type: Optional[str] = Field(default=None, description="Type of clinical document")
    confidence_average: Optional[float] = Field(default=None, description="Average confidence")
    
    @model_validator(mode='after')
    def calculate_average_confidence(self):
        """Calculate average confidence across all extracted items."""
        all_items = []
        for field_name in [
            'conditions', 'medications', 'vital_signs', 'lab_results', 'procedures',
            'providers', 'encounters', 'service_requests', 'diagnostic_reports',
            'allergies', 'care_plans', 'organizations',
            'family_history', 'physical_exam_findings', 'social_history',
        ]:
            items = getattr(self, field_name, [])
            all_items.extend(item.confidence for item in items)
        
        if all_items:
            self.confidence_average = round(sum(all_items) / len(all_items), 3)
        else:
            self.confidence_average = 0.0
        return self


def extract_medical_data_structured(text: str, context: Optional[str] = None) -> StructuredMedicalExtraction:
    """
    Extract structured medical data using Claude (primary) or OpenAI (fallback) with instructor.
    
    Enhanced with comprehensive error handling, retry logic, graceful degradation, and intelligent caching.
    
    Args:
        text: The medical document text to analyze
        context: Optional context about the document type or source
        
    Returns:
        StructuredMedicalExtraction object with all extracted data
        
    Raises:
        AIExtractionError: If extraction fails completely
        AIServiceTimeoutError: If AI service requests timeout
        AIServiceRateLimitError: If rate limits are exceeded
        AIResponseParsingError: If response cannot be parsed
        PydanticModelError: If data validation fails
        ConfigurationError: If AI services are not configured
    """
    from django.utils import timezone
    from apps.documents.cache import get_document_cache
    
    document_cache = get_document_cache()
    extraction_id = str(time.time())[:10]  # Short unique ID for this extraction
    logger.info(f"[{extraction_id}] Starting structured medical data extraction with caching")
    
    # Validate inputs
    if not text or not text.strip():
        raise AIExtractionError(
            "Cannot extract from empty text",
            details={'text_length': len(text), 'extraction_id': extraction_id}
        )
    
    if len(text) > 100000:  # Safety guard; chunking keeps normal chunks well below this
        logger.warning(f"[{extraction_id}] Text is very long ({len(text)} chars), truncating to 100000")
        text = text[:100000]
    
    # Check if any AI clients are available
    if not anthropic_client and not openai_client:
        raise ConfigurationError(
            "No AI services available for extraction",
            details={'anthropic_available': False, 'openai_available': False}
        )
    
    # Performance Optimization: Check cache for existing extraction results
    primary_model = getattr(settings, 'AI_MODEL_PRIMARY', 'claude-sonnet-4-5-20250929')
    cache_context = {
        'ai_model': primary_model,
        'context': context or '',
        # WP1: bumped from 2.0 to invalidate cached extractions after prompt/schema changes
        # (strict assertion rules, expanded medication SIG, codes, clinical_date, etc.)
        # WP2: bumped to 4.0 for new immunizations list + schema_prompt sync.
        'extraction_version': '4.0'
    }
    cache_key = document_cache.get_ai_extraction_cache_key(text, primary_model, cache_context)
    
    # Try to get cached result first
    cached_result = document_cache.get_cached_ai_extraction(cache_key)
    if cached_result:
        logger.info(f"[{extraction_id}] Using cached AI extraction result (cache hit)")
        try:
            # Reconstruct StructuredMedicalExtraction from cached data
            cached_structured_data = cached_result.get('structured_data')
            if cached_structured_data:
                return StructuredMedicalExtraction.model_validate(cached_structured_data)
        except Exception as cache_error:
            logger.warning(f"[{extraction_id}] Cache result invalid, proceeding with fresh extraction: {cache_error}")
            # Continue with fresh extraction if cache is corrupted
    # Canonical static system prompt — single source of truth shared with the
    # cached extraction path (see apps/documents/services/extraction_prompts.py).
    # Context-specific guidance is variable content and lives in the user
    # message so the static system prefix stays byte-identical across calls
    # (required for Anthropic prompt-cache prefix matching).
    from apps.documents.services.extraction_prompts import (
        get_canonical_system_prompt,
        get_context_instructions,
    )

    system_prompt = get_canonical_system_prompt()
    context_instructions = get_context_instructions(context)
    logger.info(f"[{extraction_id}] Using canonical extraction prompt")

    user_prompt = f"""Extract all medical information from this clinical document:

{text}

Document context: {context or 'General clinical document'}{context_instructions}

Return structured data with complete source context for each item."""

    # Prompt-cached extraction path (primary when enabled): static system
    # prefix with cache_control cuts input cost ~50-65% on chunks 2..N.
    # Bypasses Instructor entirely. Falls back to the legacy paths below on
    # unexpected failure; rate-limit/timeout errors propagate for task retry.
    if getattr(settings, 'AI_USE_CACHED_EXTRACTION', True) and anthropic_client:
        try:
            from apps.documents.services.cached_extraction import get_cached_extractor

            extractor = get_cached_extractor()
            extraction = extractor.extract(text, context=context, extraction_id=extraction_id)

            total_items = (len(extraction.conditions) + len(extraction.medications) +
                           len(extraction.vital_signs) + len(extraction.lab_results) +
                           len(extraction.procedures) + len(extraction.providers))
            logger.info(
                f"[{extraction_id}] Cached-path extraction successful: {total_items} items, "
                f"confidence {extraction.confidence_average:.3f}"
            )

            try:
                cache_data = {
                    'structured_data': extraction.model_dump(),
                    'extraction_metadata': {
                        'total_items': total_items,
                        'confidence_average': extraction.confidence_average,
                        'extraction_timestamp': extraction.extraction_timestamp,
                        'ai_service': 'claude_cached',
                        'usage': extractor.last_usage,
                    }
                }
                document_cache.cache_ai_extraction(cache_key, cache_data)
                del cache_data
            except Exception as cache_error:
                logger.warning(f"[{extraction_id}] Failed to cache extraction result: {cache_error}")

            return extraction

        except (AIServiceRateLimitError, AIServiceTimeoutError) as retryable_error:
            # Propagate so the Celery layer can back off and retry properly
            logger.warning(f"[{extraction_id}] Cached-path extraction hit retryable error: {retryable_error}")
            raise
        except Exception as cached_path_error:
            logger.warning(
                f"[{extraction_id}] Cached-path extraction failed: {cached_path_error}, "
                f"falling back to legacy extraction path"
            )

    # Try Claude first (primary AI service)
    claude_errors = []
    if anthropic_client:
        try:
            logger.info(f"[{extraction_id}] Attempting structured extraction with Claude (primary)")
            
            start_time = time.time()
            
            # Try instructor-based approach first (if Claude client was successfully patched)
            try:
                # Check if Claude client has instructor capabilities
                if hasattr(anthropic_client, 'chat') and hasattr(anthropic_client.chat, 'completions'):
                    logger.info(f"[{extraction_id}] Using instructor-patched Claude for Pydantic extraction")
                    
                    extraction = anthropic_client.chat.completions.create(
                        model=getattr(settings, 'AI_MODEL_PRIMARY', 'claude-sonnet-4-5-20250929'),
                        response_model=StructuredMedicalExtraction,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.1,
                        max_tokens=getattr(settings, 'AI_MAX_TOKENS_PER_REQUEST', 4096),
                        # Cap instructor's validation-retry loop: each silent retry
                        # re-sends the full prompt + failed response at full price.
                        max_retries=1
                    )
                    
                    api_duration = time.time() - start_time
                    
                    # Set extraction timestamp and document type
                    extraction.extraction_timestamp = datetime.now().isoformat()
                    extraction.document_type = context
                    
                    total_items = (len(extraction.conditions) + len(extraction.medications) + 
                                 len(extraction.vital_signs) + len(extraction.lab_results) + 
                                 len(extraction.procedures) + len(extraction.providers))
                    
                    logger.info(f"[{extraction_id}] Claude instructor extraction successful: {total_items} items, "
                               f"confidence {extraction.confidence_average:.3f} in {api_duration:.2f}s")
                    
                    # Performance Optimization: Cache successful extraction result
                    try:
                        cache_data = {
                            'structured_data': extraction.model_dump(),
                            'extraction_metadata': {
                                'total_items': total_items,
                                'confidence_average': extraction.confidence_average,
                                'extraction_timestamp': extraction.extraction_timestamp,
                                'ai_service': 'claude_instructor',
                                'processing_time': api_duration
                            }
                        }
                        document_cache.cache_ai_extraction(cache_key, cache_data)
                        logger.info(f"[{extraction_id}] Cached successful extraction result")
                    except Exception as cache_error:
                        logger.warning(f"[{extraction_id}] Failed to cache extraction result: {cache_error}")
                        # Don't fail the extraction if caching fails
                    
                    return extraction
                
                else:
                    # Fall back to manual JSON parsing approach
                    raise Exception("Claude client not instructor-patched, using manual JSON parsing")
                    
            except Exception as instructor_error:
                logger.info(f"[{extraction_id}] Instructor approach failed: {instructor_error}, falling back to manual JSON parsing")
                
                # Fallback: Manual JSON parsing approach using the canonical
                # schema prompt (single source of truth in extraction_prompts.py)
                from apps.documents.services.extraction_prompts import SCHEMA_PROMPT
                schema_prompt = SCHEMA_PROMPT
                
                # Reset start time for manual approach
                start_time = time.time()
                
                try:
                    # Use the raw SDK client: the instructor wrapper's
                    # messages.create requires response_model and would
                    # TypeError here instead of making the API call
                    manual_client = anthropic_raw_client or anthropic_client
                    response = manual_client.messages.create(
                        model=getattr(settings, 'AI_MODEL_PRIMARY', 'claude-sonnet-4-5-20250929'),
                        max_tokens=getattr(settings, 'AI_MAX_TOKENS_PER_REQUEST', 4096),
                        temperature=0.1,
                        system=system_prompt,
                        messages=[
                            {"role": "user", "content": user_prompt + "\n\n" + schema_prompt}
                        ]
                    )
                    api_duration = time.time() - start_time
                    
                    logger.info(f"[{extraction_id}] Claude manual JSON API call completed in {api_duration:.2f}s")
                    
                except anthropic.RateLimitError as e:
                    raise AIServiceRateLimitError(
                        f"Claude rate limit exceeded: {str(e)}",
                        ai_service="anthropic_claude",
                        details={'extraction_id': extraction_id, 'api_duration': time.time() - start_time}
                    )
                except anthropic.APITimeoutError as e:
                    raise AIServiceTimeoutError(
                        f"Claude API timeout: {str(e)}",
                        ai_service="anthropic_claude",
                        timeout_seconds=time.time() - start_time,
                        details={'extraction_id': extraction_id}
                    )
                except anthropic.APIError as e:
                    raise ExternalServiceError(
                        f"Claude API error: {str(e)}",
                        service_name="anthropic_claude",
                        details={'extraction_id': extraction_id, 'error_type': type(e).__name__}
                    )
                
                # Parse Claude's manual JSON response
                # MEMORY FIX: Extract response and clear the full response object
                try:
                    response_text = response.content[0].text
                    del response  # Clear the full Anthropic response object
                    logger.debug(f"[{extraction_id}] Claude manual response length: {len(response_text)} chars")
                    
                    # PORTHOLE: Capture raw Claude response for debugging
                    try:
                        from apps.core.porthole import capture_raw_llm_response
                        # Extract document ID from extraction_id if possible
                        doc_id = extraction_id.split('_')[-1] if '_' in extraction_id else extraction_id
                        capture_raw_llm_response(
                            document_id=doc_id,
                            raw_response=response_text,
                            llm_type="claude_manual_json",
                            parsing_successful=False  # Will update if parsing succeeds
                        )
                    except Exception as porthole_error:
                        logger.warning(f"[{extraction_id}] Porthole capture failed: {porthole_error}")
                    
                    # Try to extract JSON from the response
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if not json_match:
                        raise AIResponseParsingError(
                            "No valid JSON found in Claude response",
                            ai_service="anthropic_claude",
                            raw_response=response_text,
                            expected_format="JSON object",
                            details={'extraction_id': extraction_id}
                        )
                    
                    json_data = json.loads(json_match.group())
                    
                    # MEMORY FIX: Clear the matched string immediately after parsing
                    del json_match
                    
                    # Set extraction timestamp and document type
                    json_data['extraction_timestamp'] = datetime.now().isoformat()
                    json_data['document_type'] = context
                    
                    # Parse into Pydantic model with detailed error handling
                    try:
                        extraction = StructuredMedicalExtraction(**json_data)
                        # MEMORY FIX: Clear the raw dict after creating model
                        del json_data
                    except ValidationError as ve:
                        raise PydanticModelError(
                            f"Claude response failed Pydantic validation: {str(ve)}",
                            model_name="StructuredMedicalExtraction",
                            validation_errors=ve.errors(),
                            details={'extraction_id': extraction_id, 'raw_data_keys': list(json_data.keys())}
                        )
                    
                    total_items = (len(extraction.conditions) + len(extraction.medications) + 
                                 len(extraction.vital_signs) + len(extraction.lab_results) + 
                                 len(extraction.procedures) + len(extraction.providers))
                    
                    logger.info(f"[{extraction_id}] Claude manual extraction successful: {total_items} items, "
                               f"confidence {extraction.confidence_average:.3f}")
                    
                    # Performance Optimization: Cache successful extraction result
                    try:
                        cache_data = {
                            'structured_data': extraction.model_dump(),
                            'extraction_metadata': {
                                'total_items': total_items,
                                'confidence_average': extraction.confidence_average,
                                'extraction_timestamp': extraction.extraction_timestamp,
                                'ai_service': 'claude'
                            }
                        }
                        document_cache.cache_ai_extraction(cache_key, cache_data)
                        del cache_data  # MEMORY FIX: Free cache dict copy
                        logger.info(f"[{extraction_id}] Cached successful extraction result")
                    except Exception as cache_error:
                        logger.warning(f"[{extraction_id}] Failed to cache extraction result: {cache_error}")
                        # Don't fail the extraction if caching fails
                    
                    # MEMORY FIX: Free response_text before returning (extraction holds parsed data)
                    del response_text
                    _force_gc("after Claude extraction complete")
                    
                    return extraction
                    
                except json.JSONDecodeError as je:
                    raise AIResponseParsingError(
                        f"Claude response is not valid JSON: {str(je)}",
                        ai_service="anthropic_claude",
                        raw_response=response_text[:500],  # Truncated for logging
                        expected_format="JSON object",
                        details={'extraction_id': extraction_id}
                    )
                
        except (AIServiceRateLimitError, AIServiceTimeoutError, ExternalServiceError, 
                AIResponseParsingError, PydanticModelError) as specific_error:
            # Re-raise specific errors
            claude_errors.append(str(specific_error))
            logger.warning(f"[{extraction_id}] Claude extraction failed with specific error: {specific_error}")
            raise
        except Exception as e:
            claude_errors.append(str(e))
            logger.warning(f"[{extraction_id}] Claude extraction failed with unexpected error: {e}, trying OpenAI fallback")
    
    # Try OpenAI as fallback
    openai_errors = []
    if openai_client:
        try:
            logger.info(f"[{extraction_id}] Attempting structured extraction with OpenAI (fallback)")
            
            start_time = time.time()
            try:
                extraction = openai_client.chat.completions.create(
                    model=getattr(settings, 'AI_MODEL_FALLBACK', 'gpt-4o-mini'),
                    response_model=StructuredMedicalExtraction,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.1,
                    max_tokens=getattr(settings, 'AI_MAX_TOKENS_PER_REQUEST', 4096)
                )
                api_duration = time.time() - start_time
                
                logger.info(f"[{extraction_id}] OpenAI API call completed in {api_duration:.2f}s")
                
            except Exception as openai_exc:
                # Handle various OpenAI-specific errors
                error_str = str(openai_exc).lower()
                
                if 'rate limit' in error_str or 'quota' in error_str:
                    raise AIServiceRateLimitError(
                        f"OpenAI rate limit exceeded: {str(openai_exc)}",
                        ai_service="openai_gpt",
                        details={'extraction_id': extraction_id, 'api_duration': time.time() - start_time}
                    )
                elif 'timeout' in error_str:
                    raise AIServiceTimeoutError(
                        f"OpenAI API timeout: {str(openai_exc)}",
                        ai_service="openai_gpt",
                        timeout_seconds=time.time() - start_time,
                        details={'extraction_id': extraction_id}
                    )
                else:
                    raise ExternalServiceError(
                        f"OpenAI API error: {str(openai_exc)}",
                        service_name="openai_gpt",
                        details={'extraction_id': extraction_id, 'error_type': type(openai_exc).__name__}
                    )
            
            # Validate the extraction result
            if not extraction:
                raise AIResponseParsingError(
                    "OpenAI returned empty extraction result",
                    ai_service="openai_gpt",
                    expected_format="StructuredMedicalExtraction",
                    details={'extraction_id': extraction_id}
                )
            
            # Set extraction timestamp and document type
            extraction.extraction_timestamp = datetime.now().isoformat()
            extraction.document_type = context
            
            total_items = (len(extraction.conditions) + len(extraction.medications) + 
                         len(extraction.vital_signs) + len(extraction.lab_results) + 
                         len(extraction.procedures) + len(extraction.providers))
            
            logger.info(f"[{extraction_id}] OpenAI extraction successful: {total_items} items, "
                       f"confidence {extraction.confidence_average:.3f}")
            
            # Performance Optimization: Cache successful extraction result
            try:
                cache_data = {
                    'structured_data': extraction.model_dump(),
                    'extraction_metadata': {
                        'total_items': total_items,
                        'confidence_average': extraction.confidence_average,
                        'extraction_timestamp': extraction.extraction_timestamp,
                        'ai_service': 'openai'
                    }
                }
                document_cache.cache_ai_extraction(cache_key, cache_data)
                logger.info(f"[{extraction_id}] Cached successful OpenAI extraction result")
            except Exception as cache_error:
                logger.warning(f"[{extraction_id}] Failed to cache extraction result: {cache_error}")
                # Don't fail the extraction if caching fails
            
            return extraction
            
        except (AIServiceRateLimitError, AIServiceTimeoutError, ExternalServiceError, 
                AIResponseParsingError) as specific_error:
            # Re-raise specific errors
            openai_errors.append(str(specific_error))
            logger.error(f"[{extraction_id}] OpenAI extraction failed with specific error: {specific_error}")
            raise
        except Exception as e:
            openai_errors.append(str(e))
            logger.error(f"[{extraction_id}] OpenAI extraction failed with unexpected error: {e}")
    
    # If both services fail, provide comprehensive error information
    all_errors = claude_errors + openai_errors
    error_summary = {
        'claude_available': bool(anthropic_client),
        'openai_available': bool(openai_client),
        'claude_errors': claude_errors,
        'openai_errors': openai_errors,
        'extraction_id': extraction_id,
        'text_length': len(text),
        'context': context
    }
    
    raise AIExtractionError(
        f"All AI extraction services failed. Errors: {'; '.join(all_errors[:3])}",  # Limit to first 3 errors
        details=error_summary
    )


def extract_medical_data(text: str, context: Optional[str] = None) -> Dict[str, Any]:
    """
    Legacy-compatible extraction function that returns a dictionary format.
    
    This function provides backward compatibility while using the new structured extraction.
    
    Args:
        text: The medical document text to analyze
        context: Optional context about the document type or source
        
    Returns:
        Dictionary with extracted medical data in legacy format
    """
    try:
        # Use the new structured extraction with enhanced error tracking
        structured_data = extract_medical_data_structured(text, context)
        
        # Convert to legacy format for backward compatibility
        legacy_format = {
            "diagnoses": [condition.name for condition in structured_data.conditions],
            "medications": [
                f"{med.name} {med.dosage or ''} {med.frequency or ''}".strip()
                for med in structured_data.medications
            ],
            "procedures": [proc.name for proc in structured_data.procedures],
            "lab_results": [
                {
                    "test": lab.test_name,
                    "value": lab.value,
                    "unit": lab.unit or "",
                    "reference_range": lab.reference_range or ""
                }
                for lab in structured_data.lab_results
            ],
            "vital_signs": [
                {
                    "type": vital.measurement,
                    "value": vital.value,
                    "unit": vital.unit or ""
                }
                for vital in structured_data.vital_signs
            ],
            "providers": [
                {
                    "name": provider.name,
                    "specialty": provider.specialty or "",
                    "role": provider.role or ""
                }
                for provider in structured_data.providers
            ],
            # Metadata
            "extraction_confidence": structured_data.confidence_average,
            "extraction_timestamp": structured_data.extraction_timestamp,
            "total_items_extracted": (
                len(structured_data.conditions) + 
                len(structured_data.medications) + 
                len(structured_data.vital_signs) + 
                len(structured_data.lab_results) + 
                len(structured_data.procedures) + 
                len(structured_data.providers)
            ),
            "extraction_method": "structured_ai",
            "error_recovery_used": False
        }
        
        logger.info(f"Converted structured data to legacy format: {legacy_format['total_items_extracted']} total items")
        return legacy_format
        
    except (AIServiceRateLimitError, AIServiceTimeoutError) as rate_error:
        # For rate limiting, don't fallback immediately - let caller handle retry
        logger.warning(f"Rate limiting in legacy extraction: {rate_error}")
        raise
    except (AIExtractionError, AIResponseParsingError, PydanticModelError) as ai_error:
        logger.warning(f"AI extraction failed in legacy method: {ai_error}, falling back to regex extraction")
        # Fallback to basic extraction for AI-specific errors
        fallback_result = legacy_extract_medical_data(text, context)
        fallback_result["error_recovery_used"] = True
        fallback_result["original_error"] = str(ai_error)
        return fallback_result
    except Exception as e:
        logger.error(f"Unexpected error in legacy extraction: {e}")
        # Fallback to basic extraction for any other errors
        fallback_result = legacy_extract_medical_data(text, context)
        fallback_result["error_recovery_used"] = True
        fallback_result["original_error"] = str(e)
        return fallback_result


def legacy_extract_medical_data(text: str, context: Optional[str] = None) -> Dict[str, Any]:
    """
    Fallback extraction method that uses simpler text analysis.
    
    Args:
        text: The medical document text to analyze
        context: Optional context about the document type or source
        
    Returns:
        Basic dictionary with extracted medical data
    """
    logger.warning("Using fallback legacy extraction method")
    
    # Simple keyword-based extraction as fallback
    import re
    
    # Basic medication pattern matching
    medication_patterns = [
        r'\b\w+\s+\d+\s*mg\b',  # Drug name + dosage
        r'\b\w+\s+\d+\s*mcg\b',
        r'\b\w+\s+\d+\s*units?\b'
    ]
    
    medications = []
    for pattern in medication_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        medications.extend(matches)
    
    # Basic diagnosis pattern matching
    diagnosis_patterns = [
        r'(?:diagnosis|dx|impression):\s*([^.\n]+)',
        r'(?:condition|disease):\s*([^.\n]+)'
    ]
    
    diagnoses = []
    for pattern in diagnosis_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        diagnoses.extend([match.strip() for match in matches])
    
    return {
        "diagnoses": list(set(diagnoses)) if diagnoses else ["No diagnoses extracted"],
        "medications": list(set(medications)) if medications else ["No medications extracted"],
        "procedures": [],
        "lab_results": [],
        "vital_signs": [],
        "providers": [],
        "extraction_confidence": 0.3,  # Low confidence for fallback method
        "extraction_timestamp": datetime.now().isoformat(),
        "total_items_extracted": len(set(diagnoses)) + len(set(medications)),
        "fallback_method": True
    }


# Export the main functions for external use
__all__ = [
    'extract_medical_data',
    'extract_medical_data_structured',
    'StructuredMedicalExtraction',
    'MedicalCondition',
    'Medication',
    'VitalSign', 
    'LabResult',
    'Procedure',
    'Provider',
    'Immunization',
    'SourceContext',
]
