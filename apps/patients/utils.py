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
