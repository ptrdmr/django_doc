"""
Patient utility functions for searching and data operations.
Provides fast search capabilities using the hybrid encryption strategy's 
unencrypted searchable fields while maintaining HIPAA compliance.
"""

from typing import List, Optional, Union, Dict, Any
from datetime import datetime, date
from django.db.models import QuerySet, Q
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.core.exceptions import ValidationError
import logging

from .models import Patient

logger = logging.getLogger(__name__)


def search_patients_by_medical_code(
    code_system: str, 
    code: str, 
    resource_types: Optional[List[str]] = None
) -> QuerySet[Patient]:
    """
    Search for patients with a specific medical code across all FHIR resource types.
    
    Uses the unencrypted searchable_medical_codes field for fast searching
    without compromising PHI encryption.
    
    Args:
        code_system: The coding system (e.g., "http://snomed.info/sct", "http://hl7.org/fhir/sid/icd-10-cm")
        code: The specific medical code (e.g., "73211009", "E11.9")
        resource_types: Optional list of resource types to search in 
                       (e.g., ["conditions", "procedures"]). If None, searches all types.
    
    Returns:
        QuerySet of Patient objects matching the medical code
        
    Example:
        # Search for patients with diabetes (SNOMED CT code)
        patients = search_patients_by_medical_code("http://snomed.info/sct", "73211009")
        
        # Search only in conditions
        patients = search_patients_by_medical_code(
            "http://snomed.info/sct", 
            "73211009", 
            resource_types=["conditions"]
        )
    """
    if not code_system or not code:
        return Patient.objects.none()
    
    # Define searchable resource types
    all_resource_types = ["conditions", "procedures", "medications", "observations"]
    search_types = resource_types if resource_types else all_resource_types
    
    # Build query for each resource type
    queries = []
    
    for resource_type in search_types:
        if resource_type in all_resource_types:
            # Create JSONB containment query for this resource type
            query_filter = {
                f"searchable_medical_codes__{resource_type}__contains": [
                    {"system": code_system, "code": code}
                ]
            }
            queries.append(Q(**query_filter))
    
    # Combine queries with OR logic
    if queries:
        combined_query = queries[0]
        for query in queries[1:]:
            combined_query |= query
        
        return Patient.objects.filter(combined_query).distinct()
    
    return Patient.objects.none()


def search_patients_by_date_range(
    start_date: Union[str, date], 
    end_date: Union[str, date]
) -> QuerySet[Patient]:
    """
    Search for patients with encounters in a specific date range.
    
    Uses the unencrypted encounter_dates field for fast date-based searching
    without compromising PHI encryption.
    
    Args:
        start_date: Start date (YYYY-MM-DD string or date object)
        end_date: End date (YYYY-MM-DD string or date object)
    
    Returns:
        QuerySet of Patient objects with encounters in the date range
        
    Example:
        # Search for patients with encounters in January 2023
        patients = search_patients_by_date_range("2023-01-01", "2023-01-31")
        
        # Using date objects
        from datetime import date
        patients = search_patients_by_date_range(
            date(2023, 1, 1), 
            date(2023, 1, 31)
        )
    """
    # Convert dates to strings if needed
    if isinstance(start_date, date):
        start_date = start_date.isoformat()
    if isinstance(end_date, date):
        end_date = end_date.isoformat()
    
    # Validate date format
    try:
        start_parsed = parse_date(start_date)
        end_parsed = parse_date(end_date)
        if not start_parsed or not end_parsed:
            raise ValidationError("Invalid date format")
        if start_parsed > end_parsed:
            raise ValidationError("Start date must be before end date")
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid date range provided: {start_date} to {end_date}")
        return Patient.objects.none()
    
    # PostgreSQL JSONB query to find patients with encounters in date range
    # This searches the encounter_dates array for dates within the range
    return Patient.objects.extra(
        where=[
            "EXISTS (SELECT 1 FROM jsonb_array_elements_text(encounter_dates) AS encounter_date "
            "WHERE encounter_date::date BETWEEN %s::date AND %s::date)"
        ],
        params=[start_date, end_date]
    ).distinct()


def search_patients_by_provider(provider_reference: str) -> QuerySet[Patient]:
    """
    Search for patients seen by a specific provider.
    
    Uses the unencrypted provider_references field for fast provider-based searching
    without compromising PHI encryption.
    
    Args:
        provider_reference: Provider reference (e.g., "Practitioner/123", "Organization/456")
    
    Returns:
        QuerySet of Patient objects seen by the specified provider
        
    Example:
        # Search for patients seen by a specific practitioner
        patients = search_patients_by_provider("Practitioner/123")
        
        # Search for patients seen at a specific organization
        patients = search_patients_by_provider("Organization/456")
    """
    if not provider_reference:
        return Patient.objects.none()
    
    # Use JSONB containment to find patients with this provider reference
    return Patient.objects.filter(
        provider_references__contains=[provider_reference]
    ).distinct()


def search_patients_by_condition(condition_code: str, code_system: Optional[str] = None) -> QuerySet[Patient]:
    """
    Specialized search for patients with specific medical conditions.
    
    Args:
        condition_code: The condition code (e.g., "73211009", "E11.9")
        code_system: Optional code system. If None, searches across all systems.
    
    Returns:
        QuerySet of Patient objects with the specified condition
        
    Example:
        # Search for diabetes patients (SNOMED CT)
        patients = search_patients_by_condition("73211009", "http://snomed.info/sct")
        
        # Search across all code systems
        patients = search_patients_by_condition("E11.9")
    """
    if code_system:
        return search_patients_by_medical_code(code_system, condition_code, ["conditions"])
    else:
        # Search across all code systems in conditions
        return Patient.objects.filter(
            searchable_medical_codes__conditions__contains=[{"code": condition_code}]
        ).distinct()


def search_patients_by_medication(medication_code: str, code_system: Optional[str] = None) -> QuerySet[Patient]:
    """
    Specialized search for patients with specific medications.
    
    Args:
        medication_code: The medication code (e.g., RxNorm code)
        code_system: Optional code system. If None, searches across all systems.
    
    Returns:
        QuerySet of Patient objects with the specified medication
        
    Example:
        # Search for patients on insulin (RxNorm)
        patients = search_patients_by_medication("5856", "http://www.nlm.nih.gov/research/umls/rxnorm")
        
        # Search across all code systems
        patients = search_patients_by_medication("5856")
    """
    if code_system:
        return search_patients_by_medical_code(code_system, medication_code, ["medications"])
    else:
        # Search across all code systems in medications
        return Patient.objects.filter(
            searchable_medical_codes__medications__contains=[{"code": medication_code}]
        ).distinct()


def search_patients_by_procedure(procedure_code: str, code_system: Optional[str] = None) -> QuerySet[Patient]:
    """
    Specialized search for patients who had specific procedures.
    
    Args:
        procedure_code: The procedure code (e.g., CPT code)
        code_system: Optional code system. If None, searches across all systems.
    
    Returns:
        QuerySet of Patient objects who had the specified procedure
        
    Example:
        # Search for patients who had a specific procedure (CPT)
        patients = search_patients_by_procedure("99213", "http://www.ama-assn.org/go/cpt")
        
        # Search across all code systems
        patients = search_patients_by_procedure("99213")
    """
    if code_system:
        return search_patients_by_medical_code(code_system, procedure_code, ["procedures"])
    else:
        # Search across all code systems in procedures
        return Patient.objects.filter(
            searchable_medical_codes__procedures__contains=[{"code": procedure_code}]
        ).distinct()


def search_patients_by_observation_code(observation_code: str, code_system: Optional[str] = None) -> QuerySet[Patient]:
    """
    Specialized search for patients with specific lab results or observations.
    
    Args:
        observation_code: The observation code (e.g., LOINC code)
        code_system: Optional code system. If None, searches across all systems.
    
    Returns:
        QuerySet of Patient objects with the specified observation
        
    Example:
        # Search for patients with glucose lab results (LOINC)
        patients = search_patients_by_observation_code("33747-0", "http://loinc.org")
        
        # Search across all code systems
        patients = search_patients_by_observation_code("33747-0")
    """
    if code_system:
        return search_patients_by_medical_code(code_system, observation_code, ["observations"])
    else:
        # Search across all code systems in observations
        return Patient.objects.filter(
            searchable_medical_codes__observations__contains=[{"code": observation_code}]
        ).distinct()


def advanced_patient_search(
    medical_codes: Optional[List[Dict[str, str]]] = None,
    date_range: Optional[Dict[str, str]] = None,
    providers: Optional[List[str]] = None,
    combine_with_and: bool = True
) -> QuerySet[Patient]:
    """
    Advanced patient search combining multiple criteria.
    
    Args:
        medical_codes: List of medical codes to search for
                      [{"system": "http://snomed.info/sct", "code": "73211009"}]
        date_range: Date range for encounters 
                   {"start": "2023-01-01", "end": "2023-12-31"}
        providers: List of provider references to search for
                  ["Practitioner/123", "Organization/456"]
        combine_with_and: If True, combines criteria with AND logic.
                         If False, uses OR logic.
    
    Returns:
        QuerySet of Patient objects matching the combined criteria
        
    Example:
        # Find diabetic patients seen by specific provider in 2023
        patients = advanced_patient_search(
            medical_codes=[{"system": "http://snomed.info/sct", "code": "73211009"}],
            date_range={"start": "2023-01-01", "end": "2023-12-31"},
            providers=["Practitioner/123"],
            combine_with_and=True
        )
    """
    queries = []
    
    # Build medical code queries
    if medical_codes:
        for code_info in medical_codes:
            code_system = code_info.get("system")
            code = code_info.get("code")
            if code_system and code:
                code_query = search_patients_by_medical_code(code_system, code)
                if code_query.exists():
                    queries.append(Q(id__in=code_query.values_list('id', flat=True)))
    
    # Build date range query
    if date_range and date_range.get("start") and date_range.get("end"):
        date_query = search_patients_by_date_range(
            date_range["start"], 
            date_range["end"]
        )
        if date_query.exists():
            queries.append(Q(id__in=date_query.values_list('id', flat=True)))
    
    # Build provider queries
    if providers:
        provider_queries = []
        for provider_ref in providers:
            provider_query = search_patients_by_provider(provider_ref)
            if provider_query.exists():
                provider_queries.append(Q(id__in=provider_query.values_list('id', flat=True)))
        
        if provider_queries:
            # Combine provider queries with OR logic
            combined_provider_query = provider_queries[0]
            for query in provider_queries[1:]:
                combined_provider_query |= query
            queries.append(combined_provider_query)
    
    # Combine all queries
    if not queries:
        return Patient.objects.none()
    
    if len(queries) == 1:
        return Patient.objects.filter(queries[0]).distinct()
    
    # Combine with AND or OR logic
    if combine_with_and:
        combined_query = queries[0]
        for query in queries[1:]:
            combined_query &= query
    else:
        combined_query = queries[0]
        for query in queries[1:]:
            combined_query |= query
    
    return Patient.objects.filter(combined_query).distinct()


def get_patient_medical_summary(patient: Patient) -> Dict[str, Any]:
    """
    Get a summary of a patient's medical information from searchable metadata.
    
    This provides a quick overview without decrypting the full FHIR bundle,
    useful for search results and patient lists.
    
    Args:
        patient: Patient object to summarize
    
    Returns:
        Dictionary containing medical summary information
        
    Example:
        patient = Patient.objects.get(mrn="12345")
        summary = get_patient_medical_summary(patient)
        print(f"Conditions: {len(summary['conditions'])}")
    """
    if not patient.searchable_medical_codes:
        return {
            "conditions": [],
            "procedures": [],
            "medications": [],
            "observations": [],
            "encounter_count": 0,
            "provider_count": 0,
            "last_encounter": None
        }
    
    codes = patient.searchable_medical_codes
    
    # Get encounter information
    encounter_dates = patient.encounter_dates or []
    last_encounter = max(encounter_dates) if encounter_dates else None
    
    # Get provider information
    provider_refs = patient.provider_references or []
    
    return {
        "conditions": codes.get("conditions", []),
        "procedures": codes.get("procedures", []),
        "medications": codes.get("medications", []),
        "observations": codes.get("observations", []),
        "encounter_count": len(encounter_dates),
        "provider_count": len(provider_refs),
        "last_encounter": last_encounter,
        "providers": provider_refs
    }


def search_patients_by_text_query(query: str, limit: int = 50) -> QuerySet[Patient]:
    """
    Full-text search across searchable medical metadata.
    
    Searches through medical code displays and descriptions without
    accessing encrypted PHI fields.
    
    Args:
        query: Search query string
        limit: Maximum number of results to return
    
    Returns:
        QuerySet of Patient objects matching the text query
        
    Example:
        # Search for patients with diabetes-related conditions
        patients = search_patients_by_text_query("diabetes")
        
        # Search for specific medication names
        patients = search_patients_by_text_query("insulin")
    """
    if not query or len(query.strip()) < 2:
        return Patient.objects.none()
    
    query = query.strip().lower()
    
    # Use PostgreSQL's JSONB text search capabilities
    # Search in the display text of all medical codes
    return Patient.objects.extra(
        where=[
            """
            (
                searchable_medical_codes->'conditions' @> '[{"display": ""}]'::jsonb OR
                searchable_medical_codes->'procedures' @> '[{"display": ""}]'::jsonb OR
                searchable_medical_codes->'medications' @> '[{"display": ""}]'::jsonb OR
                searchable_medical_codes->'observations' @> '[{"display": ""}]'::jsonb
            ) AND (
                LOWER(searchable_medical_codes::text) LIKE %s
            )
            """
        ],
        params=[f'%{query}%']
    ).distinct()[:limit]


def get_patients_with_multiple_conditions(
    condition_codes: List[Dict[str, str]], 
    require_all: bool = True
) -> QuerySet[Patient]:
    """
    Find patients with multiple specific conditions.
    
    Args:
        condition_codes: List of condition codes to search for
                        [{"system": "...", "code": "..."}, ...]
        require_all: If True, patient must have ALL conditions.
                    If False, patient must have ANY condition.
    
    Returns:
        QuerySet of Patient objects with the specified conditions
        
    Example:
        # Find patients with both diabetes AND hypertension
        patients = get_patients_with_multiple_conditions([
            {"system": "http://snomed.info/sct", "code": "73211009"},  # Diabetes
            {"system": "http://snomed.info/sct", "code": "38341003"}   # Hypertension
        ], require_all=True)
    """
    if not condition_codes:
        return Patient.objects.none()
    
    queries = []
    for condition in condition_codes:
        code_system = condition.get("system")
        code = condition.get("code")
        if code_system and code:
            query = search_patients_by_medical_code(code_system, code, ["conditions"])
            if query.exists():
                queries.append(Q(id__in=query.values_list('id', flat=True)))
    
    if not queries:
        return Patient.objects.none()
    
    if len(queries) == 1:
        return Patient.objects.filter(queries[0]).distinct()
    
    # Combine queries based on require_all flag
    if require_all:
        # AND logic - patient must have all conditions
        combined_query = queries[0]
        for query in queries[1:]:
            combined_query &= query
    else:
        # OR logic - patient must have any condition
        combined_query = queries[0]
        for query in queries[1:]:
            combined_query |= query
    
    return Patient.objects.filter(combined_query).distinct()


def get_recent_patients_by_activity(days: int = 30, limit: int = 100) -> QuerySet[Patient]:
    """
    Get patients with recent medical activity based on encounter dates.
    
    Args:
        days: Number of days to look back for activity
        limit: Maximum number of patients to return
    
    Returns:
        QuerySet of Patient objects with recent activity, ordered by most recent
        
    Example:
        # Get patients with activity in the last 30 days
        recent_patients = get_recent_patients_by_activity(30)
        
        # Get patients with activity in the last 7 days
        recent_patients = get_recent_patients_by_activity(7, limit=20)
    """
    from datetime import timedelta
    from django.utils import timezone
    
    cutoff_date = (timezone.now().date() - timedelta(days=days)).isoformat()
    
    # Find patients with encounter dates after the cutoff
    return Patient.objects.extra(
        where=[
            "EXISTS (SELECT 1 FROM jsonb_array_elements_text(encounter_dates) AS encounter_date "
            "WHERE encounter_date::date >= %s::date)"
        ],
        params=[cutoff_date]
    ).distinct()[:limit]


def validate_search_parameters(params: Dict[str, Any]) -> Dict[str, str]:
    """
    Validate search parameters for security and format compliance.
    
    Args:
        params: Dictionary of search parameters
    
    Returns:
        Dictionary of validation errors (empty if all valid)
        
    Example:
        errors = validate_search_parameters({
            "code_system": "http://snomed.info/sct",
            "code": "73211009",
            "start_date": "2023-01-01"
        })
    """
    errors = {}
    
    # Validate code system URLs
    if "code_system" in params:
        code_system = params["code_system"]
        if code_system and not code_system.startswith(("http://", "https://", "urn:")):
            errors["code_system"] = "Code system must be a valid URI"
    
    # Validate medical codes (basic format check)
    if "code" in params:
        code = params["code"]
        if code and (len(code) < 1 or len(code) > 50):
            errors["code"] = "Medical code must be 1-50 characters"
    
    # Validate dates
    for date_field in ["start_date", "end_date"]:
        if date_field in params:
            date_value = params[date_field]
            if date_value:
                try:
                    parsed_date = parse_date(date_value)
                    if not parsed_date:
                        errors[date_field] = "Invalid date format (use YYYY-MM-DD)"
                    elif parsed_date > timezone.now().date():
                        errors[date_field] = "Date cannot be in the future"
                except (ValueError, TypeError):
                    errors[date_field] = "Invalid date format (use YYYY-MM-DD)"
    
    # Validate provider references
    if "provider_reference" in params:
        provider_ref = params["provider_reference"]
        if provider_ref and not provider_ref.startswith(("Practitioner/", "Organization/")):
            errors["provider_reference"] = "Provider reference must start with 'Practitioner/' or 'Organization/'"
    
    return errors


def get_searchable_medical_codes_stats() -> Dict[str, int]:
    """
    Get statistics about searchable medical codes across all patients.
    
    Useful for understanding the medical data landscape and search optimization.
    
    Returns:
        Dictionary with counts of different types of medical codes
        
    Example:
        stats = get_searchable_medical_codes_stats()
        print(f"Total conditions: {stats['total_conditions']}")
    """
    from django.db import connection
    
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                SUM(jsonb_array_length(COALESCE(searchable_medical_codes->'conditions', '[]'::jsonb))) as total_conditions,
                SUM(jsonb_array_length(COALESCE(searchable_medical_codes->'procedures', '[]'::jsonb))) as total_procedures,
                SUM(jsonb_array_length(COALESCE(searchable_medical_codes->'medications', '[]'::jsonb))) as total_medications,
                SUM(jsonb_array_length(COALESCE(searchable_medical_codes->'observations', '[]'::jsonb))) as total_observations,
                SUM(jsonb_array_length(COALESCE(encounter_dates, '[]'::jsonb))) as total_encounters,
                SUM(jsonb_array_length(COALESCE(provider_references, '[]'::jsonb))) as total_provider_refs,
                COUNT(*) as total_patients
            FROM patients
            WHERE deleted_at IS NULL
        """)
        
        result = cursor.fetchone()
        
        return {
            "total_conditions": int(result[0] or 0),
            "total_procedures": int(result[1] or 0),
            "total_medications": int(result[2] or 0),
            "total_observations": int(result[3] or 0),
            "total_encounters": int(result[4] or 0),
            "total_provider_references": int(result[5] or 0),
            "total_patients": int(result[6] or 0)
        }


# Convenience functions for common searches
def find_diabetic_patients() -> QuerySet[Patient]:
    """Find patients with diabetes using common diabetes codes."""
    diabetes_codes = [
        {"system": "http://snomed.info/sct", "code": "73211009"},  # Diabetes mellitus
        {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "E11"},  # Type 2 diabetes
        {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "E10"},  # Type 1 diabetes
    ]
    
    return get_patients_with_multiple_conditions(diabetes_codes, require_all=False)


def find_hypertensive_patients() -> QuerySet[Patient]:
    """Find patients with hypertension using common hypertension codes."""
    hypertension_codes = [
        {"system": "http://snomed.info/sct", "code": "38341003"},  # Hypertension
        {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I10"},  # Essential hypertension
    ]
    
    return get_patients_with_multiple_conditions(hypertension_codes, require_all=False)


def find_patients_on_insulin() -> QuerySet[Patient]:
    """Find patients on insulin therapy using common insulin codes."""
    insulin_codes = [
        {"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "5856"},  # Insulin
        {"system": "http://snomed.info/sct", "code": "412210009"},  # Insulin preparation
    ]
    
    return get_patients_with_multiple_conditions(insulin_codes, require_all=False)


# ============================================================================
# WP3 — Patient Summary & Data Presentation helpers
# ----------------------------------------------------------------------------
# Pure functions operating on the report dicts produced by
# ``Patient.get_comprehensive_report()``. They classify and regroup already
# extracted resources for presentation. No DB access, no PHI logging, and they
# degrade gracefully when WP1/WP2 enrichment (FHIR category codes, encounter
# references, synthesized DiagnosticReports) is absent.
# ============================================================================

# Canonical observation presentation categories (align with FHIR
# observation-category codes so the same keys work in templates).
OBS_CATEGORY_LABORATORY = 'laboratory'
OBS_CATEGORY_VITAL_SIGNS = 'vital-signs'
OBS_CATEGORY_EXAM = 'exam'
OBS_CATEGORY_SOCIAL_HISTORY = 'social-history'

# Ordered keys for stable iteration / template rendering.
OBSERVATION_CATEGORY_ORDER = [
    OBS_CATEGORY_LABORATORY,
    OBS_CATEGORY_VITAL_SIGNS,
    OBS_CATEGORY_EXAM,
    OBS_CATEGORY_SOCIAL_HISTORY,
]

OBSERVATION_CATEGORY_LABELS = {
    OBS_CATEGORY_LABORATORY: 'Labs',
    OBS_CATEGORY_VITAL_SIGNS: 'Vital Signs',
    OBS_CATEGORY_EXAM: 'Physical Exam',
    OBS_CATEGORY_SOCIAL_HISTORY: 'Social History',
}

# Map raw FHIR category codes / displays to our presentation categories.
_FHIR_CATEGORY_CODE_MAP = {
    'laboratory': OBS_CATEGORY_LABORATORY,
    'lab': OBS_CATEGORY_LABORATORY,
    'vital-signs': OBS_CATEGORY_VITAL_SIGNS,
    'vital signs': OBS_CATEGORY_VITAL_SIGNS,
    'vitals': OBS_CATEGORY_VITAL_SIGNS,
    'exam': OBS_CATEGORY_EXAM,
    'social-history': OBS_CATEGORY_SOCIAL_HISTORY,
    'social history': OBS_CATEGORY_SOCIAL_HISTORY,
}

# Keyword sets for the Priority-2 heuristic (used only when no usable FHIR
# category code is present). Matched on word boundaries via WP2's
# ``contains_any_keyword`` so short tokens don't false-match unrelated text.
SOCIAL_HISTORY_KEYWORDS = (
    'smoking', 'smoker', 'tobacco', 'cigarette', 'nicotine', 'vaping',
    'alcohol', 'etoh', 'substance use', 'illicit', 'drug use',
    'occupation', 'employment', 'marital status', 'sexual history',
    'pack year', 'pack-year', 'recreational', 'caffeine',
)

PHYSICAL_EXAM_KEYWORDS = (
    'bmi', 'body mass index', 'body fat', 'waist circumference',
    'physical exam', 'inspection', 'palpation', 'auscultation', 'gait',
    'general appearance', 'edema', 'murmur', 'range of motion',
)

VITAL_SIGN_KEYWORDS = (
    'blood pressure', 'systolic', 'diastolic', 'heart rate', 'pulse',
    'respiratory rate', 'respiration', 'temperature', 'body temperature',
    'oxygen saturation', 'spo2', 'o2 sat', 'body weight', 'weight',
    'height', 'body height', 'head circumference',
)


def categorize_observation(observation: Dict[str, Any]) -> str:
    """
    Classify a report-extracted Observation into a presentation category.

    Resolution order:
        1. Explicit FHIR ``category_code`` (or ``category`` display) emitted by
           WP1/WP2 extraction.
        2. Keyword heuristic over the observation's display name / code displays
           (social history, then vital signs, then physical exam).
        3. Default to ``laboratory``.

    Args:
        observation: Observation dict from ``get_comprehensive_report``.

    Returns:
        One of: 'laboratory', 'vital-signs', 'exam', 'social-history'.
    """
    from apps.fhir.services.keyword_matching import contains_any_keyword

    # Priority 1: explicit FHIR category code (fall back to display string).
    raw = (observation.get('category_code') or observation.get('category') or '')
    raw = raw.strip().lower() if isinstance(raw, str) else ''
    if raw in _FHIR_CATEGORY_CODE_MAP:
        return _FHIR_CATEGORY_CODE_MAP[raw]

    # Priority 2: keyword heuristic on display name + code displays.
    haystack_parts = [observation.get('display_name') or '']
    for code in observation.get('codes', []) or []:
        if isinstance(code, dict) and code.get('display'):
            haystack_parts.append(code['display'])
    haystack = ' '.join(haystack_parts)

    if contains_any_keyword(haystack, SOCIAL_HISTORY_KEYWORDS):
        return OBS_CATEGORY_SOCIAL_HISTORY
    if contains_any_keyword(haystack, VITAL_SIGN_KEYWORDS):
        return OBS_CATEGORY_VITAL_SIGNS
    if contains_any_keyword(haystack, PHYSICAL_EXAM_KEYWORDS):
        return OBS_CATEGORY_EXAM

    # Default
    return OBS_CATEGORY_LABORATORY


def build_observations_by_category(
    observations: List[Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Split a flat observation list into category buckets for presentation.

    Args:
        observations: Flat list of Observation dicts (kept intact by caller for
            backward compatibility).

    Returns:
        Dict with keys 'laboratory', 'vital-signs', 'exam', 'social-history',
        each mapping to a list of observation dicts. Order is preserved within
        each bucket (caller pre-sorts by date).
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {
        key: [] for key in OBSERVATION_CATEGORY_ORDER
    }
    for obs in observations or []:
        if not isinstance(obs, dict):
            continue
        category = categorize_observation(obs)
        buckets.setdefault(category, []).append(obs)
    return buckets


def observation_category_sections(
    buckets: Dict[str, List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    """
    Build an ordered, template-friendly list of observation category sections.

    Django templates cannot resolve hyphenated dict keys (e.g. ``vital-signs``)
    via dot notation, so this exposes the same buckets as an ordered list of
    ``{'key', 'label', 'observations'}`` dicts for iteration in PDF templates.

    Args:
        buckets: Output of :func:`build_observations_by_category`.

    Returns:
        Ordered list of section dicts (laboratory, vital-signs, exam,
        social-history).
    """
    sections: List[Dict[str, Any]] = []
    for key in OBSERVATION_CATEGORY_ORDER:
        sections.append({
            'key': key,
            'label': OBSERVATION_CATEGORY_LABELS.get(key, key),
            'observations': buckets.get(key, []),
        })
    return sections


# Encounter type presentation labels keyed by canonical type code.
ENCOUNTER_TYPE_LABELS = {
    'inpatient': 'Inpatient Stay',
    'ambulatory': 'Ambulatory Visit',
    'emergency': 'Emergency Visit',
}

# FHIR v3-ActCode encounter class codes -> canonical type code.
_ENCOUNTER_CLASS_CODE_MAP = {
    'IMP': 'inpatient',
    'ACUTE': 'inpatient',
    'NONAC': 'inpatient',
    'SS': 'inpatient',      # short stay
    'EMER': 'emergency',
    'AMB': 'ambulatory',
    'OBSENC': 'ambulatory',
    'VR': 'ambulatory',     # virtual
    'HH': 'ambulatory',     # home health
}

_EMERGENCY_KEYWORDS = ('emergency', 'emergency room', 'emergency department',
                       'trauma')
_INPATIENT_KEYWORDS = ('inpatient', 'admitted', 'admission', 'hospitalization',
                       'hospitalisation', 'hospital stay', 'discharge')
_AMBULATORY_KEYWORDS = ('outpatient', 'office visit', 'clinic', 'ambulatory',
                        'office', 'consult', 'follow-up', 'follow up')


def classify_encounter_type(encounter: Dict[str, Any]) -> Dict[str, str]:
    """
    Determine an encounter's presentation type from FHIR class + keywords.

    Resolution order:
        1. FHIR ``class_code`` (IMP/AMB/EMER/...) from WP2's encounter service.
        2. Keyword fallback over class display, type displays, reason, location.
        3. Default to ``ambulatory`` (most visits are outpatient).

    Args:
        encounter: Encounter dict from ``get_comprehensive_report``.

    Returns:
        Dict with 'code' (inpatient|ambulatory|emergency) and human 'label'.
    """
    from apps.fhir.services.keyword_matching import contains_any_keyword

    # Priority 1: explicit FHIR class code.
    class_code = (encounter.get('class_code') or '')
    class_code = class_code.strip().upper() if isinstance(class_code, str) else ''
    if class_code in _ENCOUNTER_CLASS_CODE_MAP:
        code = _ENCOUNTER_CLASS_CODE_MAP[class_code]
        return {'code': code, 'label': ENCOUNTER_TYPE_LABELS[code]}

    # Priority 2: keyword fallback over human-readable fields.
    haystack_parts = [encounter.get('class') or '']
    for enc_type in encounter.get('type', []) or []:
        if isinstance(enc_type, dict) and enc_type.get('display'):
            haystack_parts.append(enc_type['display'])
    for reason in encounter.get('reason', []) or []:
        if isinstance(reason, dict):
            haystack_parts.append(reason.get('display') or reason.get('code') or '')
    locations = encounter.get('location') or []
    if isinstance(locations, list):
        haystack_parts.extend(str(loc) for loc in locations)
    haystack = ' '.join(part for part in haystack_parts if part)

    if contains_any_keyword(haystack, _EMERGENCY_KEYWORDS):
        return {'code': 'emergency', 'label': ENCOUNTER_TYPE_LABELS['emergency']}
    if contains_any_keyword(haystack, _INPATIENT_KEYWORDS):
        return {'code': 'inpatient', 'label': ENCOUNTER_TYPE_LABELS['inpatient']}
    if contains_any_keyword(haystack, _AMBULATORY_KEYWORDS):
        return {'code': 'ambulatory', 'label': ENCOUNTER_TYPE_LABELS['ambulatory']}

    # Default: ambulatory visit.
    return {'code': 'ambulatory', 'label': ENCOUNTER_TYPE_LABELS['ambulatory']}


def _resource_primary_date(resource: Dict[str, Any], resource_type: str) -> Any:
    """Return the most relevant date value for a report-extracted resource."""
    if resource_type == 'observation':
        return resource.get('effective_date')
    if resource_type == 'condition':
        return resource.get('onset_date') or resource.get('recorded_date')
    if resource_type == 'procedure':
        if resource.get('performed_date'):
            return resource['performed_date']
        period = resource.get('performed_period') or {}
        return period.get('start')
    if resource_type == 'medication':
        period = resource.get('effective_period') or {}
        return period.get('start')
    if resource_type == 'diagnostic_report':
        return resource.get('effective_date')
    return None


# Clinical resource collections that participate in encounter grouping.
_GROUPABLE_RESOURCE_TYPES = [
    'observations', 'conditions', 'procedures', 'medications',
    'diagnostic_reports',
]


def group_resources_by_encounter(
    clinical_summary: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Group clinical resources under the encounter/visit they belong to (E1).

    Three-tier matching per resource (graceful degradation):
        Tier 1: explicit FHIR encounter reference (WP2 ``encounter_reference``).
        Tier 2: normalized date match at the coarsest shared precision against
                an encounter's period start (WP2 ``dates_match_at_precision``).
        Tier 3: an "Unlinked" bucket for resources with no encounter and no
                usable date (or whose date matches no encounter).

    Args:
        clinical_summary: The ``clinical_summary`` dict from the report.

    Returns:
        Ordered list of group dicts. Each group has::

            {
                'encounter': <encounter dict or None>,
                'encounter_id': <id or 'unlinked'>,
                'label': <type label or 'Encounters / Visits'>,
                'type': <{'code','label'} or None>,
                'date': <date or None>,
                'resources': {'observations': [...], 'conditions': [...], ...},
                'resource_count': <int>,
            }

        Encounter groups come first (sorted most-recent first), then the
        unlinked bucket (only when non-empty).
    """
    from apps.fhir.services.encounter_linker import dates_match_at_precision

    encounters = clinical_summary.get('encounters', []) or []

    # Build one group per real encounter, indexed by id.
    groups_by_id: Dict[str, Dict[str, Any]] = {}
    ordered_ids: List[str] = []
    for enc in encounters:
        if not isinstance(enc, dict):
            continue
        enc_id = str(enc.get('id', 'unknown'))
        enc_type = classify_encounter_type(enc)
        period = enc.get('period') or {}
        groups_by_id[enc_id] = {
            'encounter': enc,
            'encounter_id': enc_id,
            'label': enc_type['label'],
            'type': enc_type,
            'date': period.get('start'),
            'resources': {rtype: [] for rtype in _GROUPABLE_RESOURCE_TYPES},
            'resource_count': 0,
        }
        ordered_ids.append(enc_id)

    unlinked = {
        'encounter': None,
        'encounter_id': 'unlinked',
        'label': 'Unlinked / Undated',
        'type': None,
        'date': None,
        'resources': {rtype: [] for rtype in _GROUPABLE_RESOURCE_TYPES},
        'resource_count': 0,
    }

    def _place_resource(resource: Dict[str, Any], rtype_key: str,
                        rtype_singular: str) -> None:
        # Tier 1: explicit encounter reference.
        ref_id = resource.get('encounter_reference')
        if ref_id and str(ref_id) in groups_by_id:
            target = groups_by_id[str(ref_id)]
            target['resources'][rtype_key].append(resource)
            target['resource_count'] += 1
            return

        # Tier 2: date match at coarsest shared precision.
        resource_date = _resource_primary_date(resource, rtype_singular)
        if resource_date:
            for enc_id in ordered_ids:
                enc_start = groups_by_id[enc_id]['date']
                if enc_start and dates_match_at_precision(resource_date, enc_start):
                    target = groups_by_id[enc_id]
                    target['resources'][rtype_key].append(resource)
                    target['resource_count'] += 1
                    return

        # Tier 3: unlinked bucket.
        unlinked['resources'][rtype_key].append(resource)
        unlinked['resource_count'] += 1

    rtype_singular_map = {
        'observations': 'observation',
        'conditions': 'condition',
        'procedures': 'procedure',
        'medications': 'medication',
        'diagnostic_reports': 'diagnostic_report',
    }
    for rtype_key in _GROUPABLE_RESOURCE_TYPES:
        for resource in clinical_summary.get(rtype_key, []) or []:
            if isinstance(resource, dict):
                _place_resource(resource, rtype_key, rtype_singular_map[rtype_key])

    # Encounter groups most-recent first; unlinked appended only when non-empty.
    encounter_groups = [groups_by_id[enc_id] for enc_id in ordered_ids]
    encounter_groups.sort(
        key=lambda g: _date_sort_key(g['date']), reverse=True
    )

    result = encounter_groups
    if unlinked['resource_count'] > 0:
        result = result + [unlinked]
    return result


def _date_sort_key(value: Any) -> str:
    """Normalize a date-ish value to a sortable 'YYYY-MM-DD' string."""
    sentinel = '0000-00-00'
    if value is None:
        return sentinel
    if hasattr(value, 'isoformat'):
        try:
            return value.isoformat()[:10]
        except (ValueError, TypeError):
            return sentinel
    text = str(value).strip()
    return text[:10] if text else sentinel


def group_observations_by_panel(
    observations: List[Dict[str, Any]],
    diagnostic_reports: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Group lab Observations under their DiagnosticReport panels (E/Phase 4).

    Matches Observations to DiagnosticReports via the report's ``result_refs``
    (Observation ids, populated by WP2's ``synthesize_lab_panels``). Observations
    not claimed by any panel are returned as a flat ``unclaimed`` list so the
    template stays backward compatible when no panels exist.

    Args:
        observations: Observation dicts (typically the laboratory bucket).
        diagnostic_reports: DiagnosticReport dicts from the report.

    Returns:
        Dict::

            {
                'panels': [
                    {'display_name', 'status', 'effective_date', 'conclusion',
                     'category', 'observations': [...], 'observation_count',
                     'flagged_count'},
                    ...
                ],
                'unclaimed': [...observations not in any panel...],
                'has_panels': <bool>,
            }
    """
    obs_by_id: Dict[str, Dict[str, Any]] = {}
    for obs in observations or []:
        if isinstance(obs, dict) and obs.get('id'):
            obs_by_id[str(obs['id'])] = obs

    claimed_ids = set()
    panels: List[Dict[str, Any]] = []

    for report in diagnostic_reports or []:
        if not isinstance(report, dict):
            continue
        result_refs = report.get('result_refs') or []
        if not result_refs:
            continue
        panel_observations: List[Dict[str, Any]] = []
        for obs_id in result_refs:
            obs = obs_by_id.get(str(obs_id))
            if obs is not None:
                panel_observations.append(obs)
                claimed_ids.add(str(obs_id))
        if not panel_observations:
            continue
        flagged = sum(
            1 for o in panel_observations
            if interpretation_to_flag(o.get('interpretation'))
        )
        panels.append({
            'display_name': report.get('display_name') or 'Lab Panel',
            'status': report.get('status'),
            'effective_date': report.get('effective_date'),
            'conclusion': report.get('conclusion'),
            'category': report.get('category'),
            'observations': panel_observations,
            'observation_count': len(panel_observations),
            'flagged_count': flagged,
        })

    # Panels most-recent first for consistent presentation.
    panels.sort(key=lambda p: _date_sort_key(p['effective_date']), reverse=True)

    unclaimed = [
        obs for obs in (observations or [])
        if isinstance(obs, dict) and str(obs.get('id')) not in claimed_ids
    ]

    return {
        'panels': panels,
        'unclaimed': unclaimed,
        'has_panels': bool(panels),
    }


# ---------------------------------------------------------------------------
# Medication deduplication (Phase 1b)
# ---------------------------------------------------------------------------

# Statuses that represent a currently-relevant (active) medication.
_ACTIVE_MED_STATUSES = {'active', 'intended', 'on-hold'}


def _normalize_drug_name(name: str) -> str:
    """
    Normalize a medication display name for dedup matching.

    Lowercases, collapses internal whitespace, and strips surrounding
    punctuation/whitespace so "Tamsulosin " and "tamsulosin" collapse together.

    Args:
        name: Raw medication display name.

    Returns:
        Normalized key string (empty string when name is falsy).
    """
    if not name:
        return ''
    return ' '.join(str(name).strip().lower().split())


def _med_primary_dose(medication: Dict[str, Any]) -> str:
    """Return the first dosage's normalized dose string, or '' when absent."""
    dosage = medication.get('dosage') or []
    if dosage and isinstance(dosage[0], dict):
        dose = dosage[0].get('dose')
        if dose:
            return ' '.join(str(dose).strip().lower().split())
    return ''


def _med_start_value(medication: Dict[str, Any]) -> Any:
    """Return a medication's effective-period start for recency comparison."""
    period = medication.get('effective_period') or {}
    return period.get('start')


def _merge_medication_sigs(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    """
    Merge dosage/SIG instructions from ``source`` into ``target`` in place.

    Appends any dosage entries from source whose full SIG text is not already
    present on the target, preserving the complete instruction text.
    """
    target_dosage = target.setdefault('dosage', [])
    existing_texts = {
        (d.get('text') or '').strip().lower()
        for d in target_dosage if isinstance(d, dict)
    }
    for dosage in source.get('dosage') or []:
        if not isinstance(dosage, dict):
            continue
        text_key = (dosage.get('text') or '').strip().lower()
        if text_key and text_key not in existing_texts:
            target_dosage.append(dosage)
            existing_texts.add(text_key)


def deduplicate_medications(medications: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Deduplicate medications by normalized (drug name + dose).

    The same drug is frequently extracted from multiple documents, producing
    duplicate entries (e.g. tamsulosin 3x). This collapses them by keeping the
    record with the most recent start date and merging the full SIG text from
    every source so no dosing instruction is lost.

    Args:
        medications: List of medication summary dicts from the report.

    Returns:
        Dict::

            {
                'active': [<active/intended meds>],
                'historical': [<everything else>],
                'all': [<deduped meds, recency-sorted>],
            }
    """
    seen: Dict[tuple, Dict[str, Any]] = {}

    for med in medications or []:
        if not isinstance(med, dict):
            continue
        key = (_normalize_drug_name(med.get('display_name', '')), _med_primary_dose(med))

        if key not in seen:
            # Shallow copy so merging SIGs never mutates the caller's source dict.
            seen[key] = dict(med, dosage=list(med.get('dosage') or []))
            continue

        existing = seen[key]
        existing_start = _date_sort_key(_med_start_value(existing))
        incoming_start = _date_sort_key(_med_start_value(med))

        if incoming_start > existing_start:
            # Incoming is more recent: promote it, then merge older SIGs in.
            promoted = dict(med, dosage=list(med.get('dosage') or []))
            _merge_medication_sigs(promoted, existing)
            # Prefer an active status if either record was active.
            if existing.get('status') in _ACTIVE_MED_STATUSES:
                promoted['status'] = promoted.get('status') or existing.get('status')
            seen[key] = promoted
        else:
            _merge_medication_sigs(existing, med)
            # Keep an active status if the incoming duplicate was active.
            if (existing.get('status') not in _ACTIVE_MED_STATUSES
                    and med.get('status') in _ACTIVE_MED_STATUSES):
                existing['status'] = med['status']

    all_meds = list(seen.values())
    all_meds.sort(key=lambda m: _date_sort_key(_med_start_value(m)), reverse=True)

    active = [m for m in all_meds if m.get('status') in _ACTIVE_MED_STATUSES]
    historical = [m for m in all_meds if m.get('status') not in _ACTIVE_MED_STATUSES]

    return {
        'active': active,
        'historical': historical,
        'all': all_meds,
    }


# ---------------------------------------------------------------------------
# Labs-by-visit grouping (Phase 2)
# ---------------------------------------------------------------------------

def interpretation_to_flag(interpretation: Any) -> str:
    """
    Map a FHIR interpretation value to a short, print-friendly flag.

    Handles both human display strings ("High", "Low", "Critical low") and
    HL7 v3 ObservationInterpretation codes ("H", "L", "HH", "LL", "A", "N").

    Args:
        interpretation: An interpretation list (from the report) or string.

    Returns:
        'H' (high), 'L' (low), 'A' (abnormal), or '' when normal/absent.
    """
    if not interpretation:
        return ''
    if isinstance(interpretation, (list, tuple)):
        text = ' '.join(str(i) for i in interpretation if i)
    else:
        text = str(interpretation)
    text = text.strip().lower()
    if not text:
        return ''
    # Normalize standalone codes by checking the first token too.
    first = text.split()[0] if text.split() else ''
    if 'high' in text or first in ('h', 'hh', 'hu'):
        return 'H'
    if 'low' in text or first in ('l', 'll', 'lu'):
        return 'L'
    if 'normal' in text or first in ('n', 'norm'):
        return ''
    if 'abnormal' in text or first in ('a', 'aa', 'ab'):
        return 'A'
    return ''


def _observation_is_flagged(observation: Dict[str, Any]) -> bool:
    """True when an observation carries an abnormal (H/L/A) interpretation flag.

    Uses the derived flag rather than raw interpretation presence so that
    explicitly-normal results ("N") are not counted as flagged.
    """
    return bool(
        observation.get('flag')
        or interpretation_to_flag(observation.get('interpretation'))
    )


def build_labs_by_visit(
    encounter_groups: List[Dict[str, Any]],
    lab_panels: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build a visit-grouped lab structure for the hybrid (visit > panel) display.

    ``encounter_groups`` knows which observations belong to which visit, and
    ``lab_panels`` knows which observations belong to which DiagnosticReport
    panel. This combines them so each visit lists its lab panels, plus any
    visit labs not claimed by a panel ("Other Results").

    Observations whose visit cannot be determined fall into a synthetic
    "Undated / Unlinked Labs" group so nothing is silently dropped.

    Args:
        encounter_groups: Output of ``group_resources_by_encounter``.
        lab_panels: Output of ``group_observations_by_panel``.

    Returns:
        Dict::

            {
                'visits': [
                    {
                        'encounter': <encounter dict or None>,
                        'encounter_id': <id or 'unlinked'>,
                        'type_label': <str>,
                        'location': <str or None>,
                        'date': <date or None>,
                        'panels': [<panel dict>, ...],
                        'other_results': [<observation>, ...],
                        'total_results': <int>,
                        'flagged_count': <int>,
                    },
                    ...
                ],
                'has_labs': <bool>,
            }
    """
    panels = (lab_panels or {}).get('panels', []) or []
    unclaimed = (lab_panels or {}).get('unclaimed', []) or []

    # Map each observation id -> the panel it belongs to (an obs is in <=1 panel).
    panel_by_obs_id: Dict[str, Dict[str, Any]] = {}
    for panel in panels:
        for obs in panel.get('observations', []) or []:
            if isinstance(obs, dict) and obs.get('id') is not None:
                panel_by_obs_id[str(obs['id'])] = panel

    # Unclaimed (lab but panel-less) observations, indexed by id.
    unclaimed_by_id: Dict[str, Dict[str, Any]] = {
        str(obs['id']): obs
        for obs in unclaimed
        if isinstance(obs, dict) and obs.get('id') is not None
    }
    # The authoritative set of laboratory observation ids comes from lab_panels,
    # since observation category is computed there (not stored on the obs dict).
    lab_obs_ids = set(panel_by_obs_id.keys()) | set(unclaimed_by_id.keys())

    visits: List[Dict[str, Any]] = []
    claimed_panel_keys = set()
    claimed_unclaimed_ids = set()

    for group in encounter_groups or []:
        if not isinstance(group, dict):
            continue
        group_obs = group.get('resources', {}).get('observations', []) or []
        lab_obs = [
            o for o in group_obs
            if isinstance(o, dict) and str(o.get('id')) in lab_obs_ids
        ]
        if not lab_obs:
            continue

        visit_panels: List[Dict[str, Any]] = []
        seen_panel_keys = set()
        other_results: List[Dict[str, Any]] = []

        for obs in lab_obs:
            obs_id = str(obs.get('id'))
            panel = panel_by_obs_id.get(obs_id)
            if panel is not None:
                panel_key = id(panel)
                if panel_key not in seen_panel_keys:
                    seen_panel_keys.add(panel_key)
                    claimed_panel_keys.add(panel_key)
                    visit_panels.append(panel)
            else:
                other_results.append(obs)
                claimed_unclaimed_ids.add(obs_id)

        total_results = sum(p.get('observation_count', 0) for p in visit_panels) + len(other_results)
        flagged_count = (
            sum(p.get('flagged_count', 0) for p in visit_panels)
            + sum(1 for o in other_results if _observation_is_flagged(o))
        )

        encounter = group.get('encounter') or {}
        type_info = group.get('type') or {}
        enc_id = group.get('encounter_id', 'unlinked')
        visits.append({
            'encounter': encounter,
            'encounter_id': enc_id,
            'type_label': type_info.get('label') or group.get('label') or 'Visit',
            'location': (encounter or {}).get('location'),
            'date': group.get('date'),
            'panels': visit_panels,
            'other_results': other_results,
            'total_results': total_results,
            'flagged_count': flagged_count,
            'is_unlinked': enc_id in (None, 'unlinked') or group.get('date') is None,
        })

    # Any panels or unclaimed labs never attached to a visit collect into an
    # "Undated / Unlinked Labs" group so nothing is silently dropped.
    orphan_panels = [p for p in panels if id(p) not in claimed_panel_keys]
    orphan_unclaimed = [
        obs for obs_id, obs in unclaimed_by_id.items()
        if obs_id not in claimed_unclaimed_ids
    ]
    if orphan_panels or orphan_unclaimed:
        total_results = (
            sum(p.get('observation_count', 0) for p in orphan_panels) + len(orphan_unclaimed)
        )
        flagged_count = (
            sum(p.get('flagged_count', 0) for p in orphan_panels)
            + sum(1 for o in orphan_unclaimed if _observation_is_flagged(o))
        )
        visits.append({
            'encounter': None,
            'encounter_id': 'unlinked',
            'type_label': 'Undated / Unlinked Labs',
            'location': None,
            'date': None,
            'panels': orphan_panels,
            'other_results': orphan_unclaimed,
            'total_results': total_results,
            'flagged_count': flagged_count,
            'is_unlinked': True,
        })

    return {
        'visits': visits,
        'has_labs': bool(visits),
        'has_linked_labs': any(not v['is_unlinked'] for v in visits),
    }


def _encounter_location_token(encounter):
    """Return a normalized primary-location token for dedup matching.

    Takes the first location string and trims to the part before the first
    comma so minor suffix differences ("...Center" vs "...Center, 55 EER")
    still collapse to the same visit.

    Args:
        encounter: An encounter dict with an optional ``location`` list.

    Returns:
        Lower-cased location token, or '' when no location is present.
    """
    locations = encounter.get('location') or []
    if isinstance(locations, (list, tuple)) and locations:
        first = str(locations[0]).strip().lower()
        return first.split(',')[0].strip()
    return ''


def _encounter_date_token(encounter):
    """Return the ISO date (YYYY-MM-DD) of an encounter's start, or ''."""
    period = encounter.get('period') or {}
    start = period.get('start')
    if start is None:
        return ''
    if hasattr(start, 'isoformat'):
        return start.isoformat()[:10]
    return str(start)[:10]


def _encounter_richness(encounter):
    """Score how much clinical detail an encounter carries (higher = keep)."""
    score = 0
    for key in ('location', 'reason', 'diagnosis', 'type', 'participants'):
        value = encounter.get(key)
        if value:
            score += len(value) if isinstance(value, (list, tuple)) else 1
    period = encounter.get('period') or {}
    if period.get('end'):
        score += 1
    return score


def deduplicate_encounters(encounters):
    """Collapse duplicate encounters extracted from different documents.

    Two encounters are treated as the same visit when they share the same
    start date, classified ``type_code``, and normalized primary-location
    token. The survivor is the entry with the richest data, so location /
    reason / diagnosis detail is preserved. Encounters that lack both a date
    and a location are never merged (keyed by id) to avoid collapsing
    genuinely distinct visits.

    Args:
        encounters: List of encounter dicts, already annotated with
            ``type_code`` by ``classify_encounter_type``.

    Returns:
        A deduplicated list preserving first-occurrence order.
    """
    if not encounters:
        return encounters

    chosen = {}
    order = []
    for encounter in encounters:
        if not isinstance(encounter, dict):
            continue
        date_token = _encounter_date_token(encounter)
        loc_token = _encounter_location_token(encounter)
        if not date_token and not loc_token:
            # Not enough signal to merge safely; keep distinct by id.
            key = ('id', str(encounter.get('id')))
        else:
            key = (date_token, encounter.get('type_code') or '', loc_token)

        if key not in chosen:
            chosen[key] = encounter
            order.append(key)
        elif _encounter_richness(encounter) > _encounter_richness(chosen[key]):
            chosen[key] = encounter

    return [chosen[key] for key in order]


def build_vitals_by_visit(encounter_groups, vital_observations):
    """Group vital-signs and exam observations under their encounter/visit.

    Mirrors ``build_labs_by_visit``: walks the already-ordered encounter
    groups (most-recent-first) and, for each visit, collects the observations
    that belong to the vital-signs / exam categories. The authoritative set of
    vital/exam ids comes from ``vital_observations`` (the pre-categorized
    buckets), since observation category is computed -- not stored on the obs
    dict.

    Args:
        encounter_groups: Output of ``group_resources_by_encounter`` -- a
            list of visit dicts each carrying a ``resources`` map.
        vital_observations: Flat list of observation dicts already classified
            as ``vital-signs`` or ``exam`` (e.g. obs_by_category buckets
            concatenated).

    Returns:
        Dict with ``visits`` (list of per-visit vitals blocks) and the
        ``has_vitals`` convenience boolean.
    """
    vital_obs_ids = {
        str(obs['id'])
        for obs in (vital_observations or [])
        if isinstance(obs, dict) and obs.get('id') is not None
    }

    visits = []
    for group in encounter_groups or []:
        if not isinstance(group, dict):
            continue
        group_obs = group.get('resources', {}).get('observations', []) or []
        vitals = [
            obs for obs in group_obs
            if isinstance(obs, dict) and str(obs.get('id')) in vital_obs_ids
        ]
        if not vitals:
            continue
        enc_id = group.get('encounter_id')
        visits.append({
            'encounter_id': enc_id,
            'type_label': group.get('label') or group.get('type'),
            'location': group.get('location'),
            'date': group.get('date'),
            'vitals': vitals,
            'total': len(vitals),
            'is_unlinked': enc_id in (None, 'unlinked') or group.get('date') is None,
        })

    return {
        'visits': visits,
        'has_vitals': bool(visits),
        'has_linked_vitals': any(not v['is_unlinked'] for v in visits),
    }
