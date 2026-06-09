"""
Immunization Service for FHIR Resource Processing (WP2 / D1).

Converts extracted immunization data into FHIR Immunization resources, preserving
vaccine-specific detail (CVX codes, lot numbers, dose-in-series, route/site) that
would otherwise be lost when vaccines are captured as generic Procedures.

Primary path : ``structured_data.immunizations`` (Immunization Pydantic model).
Fallback path: detect vaccine entries within ``structured_data.procedures`` and
convert them, so older extractions still surface immunizations correctly.
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4
from datetime import datetime

from apps.core.date_parser import ClinicalDateParser
from apps.fhir.services.extensions import append_extraction_extensions, source_snippet_from_field
from apps.fhir.services.keyword_matching import is_vaccine_name, word_match

logger = logging.getLogger(__name__)


class ImmunizationService:
    """Service for processing immunization data into FHIR Immunization resources."""

    # Minimal CVX lookup for common vaccines. Keyed by substring match against a
    # lowercased vaccine name. First match wins, so order longer/specific keys
    # before generic ones where ambiguity exists.
    CVX_LOOKUP = {
        "influenza": ("88", "Influenza, unspecified formulation"),
        "flu": ("88", "Influenza, unspecified formulation"),
        "covid-19": ("213", "SARS-COV-2 (COVID-19) vaccine, unspecified"),
        "covid": ("213", "SARS-COV-2 (COVID-19) vaccine, unspecified"),
        "sars-cov-2": ("213", "SARS-COV-2 (COVID-19) vaccine, unspecified"),
        "tdap": ("115", "Tdap"),
        "dtap": ("20", "DTaP"),
        "td": ("138", "Td (adult)"),
        "tetanus": ("112", "Tetanus toxoid, unspecified formulation"),
        "mmr": ("03", "MMR"),
        "measles": ("05", "Measles"),
        "varicella": ("21", "Varicella"),
        "zoster": ("187", "Zoster recombinant"),
        "shingrix": ("187", "Zoster recombinant"),
        "shingles": ("187", "Zoster recombinant"),
        "hepatitis a": ("52", "Hepatitis A, adult"),
        "hepatitis b": ("43", "Hepatitis B, adult"),
        "hep b": ("43", "Hepatitis B, adult"),
        "hpv": ("165", "HPV9"),
        "gardasil": ("165", "HPV9"),
        "pneumococcal conjugate": ("133", "Pneumococcal conjugate PCV 13"),
        "prevnar": ("133", "Pneumococcal conjugate PCV 13"),
        "pneumococcal polysaccharide": ("33", "Pneumococcal polysaccharide PPV23"),
        "pneumovax": ("33", "Pneumococcal polysaccharide PPV23"),
        "pneumococcal": ("109", "Pneumococcal, unspecified formulation"),
        "meningococcal": ("147", "Meningococcal MCV4, unspecified"),
        "polio": ("10", "IPV"),
        "rsv": ("305", "RSV, unspecified"),
        "rotavirus": ("122", "Rotavirus, unspecified formulation"),
        "haemophilus": ("17", "Hib, unspecified formulation"),
        "hib": ("17", "Hib, unspecified formulation"),
    }

    def __init__(self):
        self.logger = logger
        self.date_parser = ClinicalDateParser()

    def process_immunizations(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process immunizations into FHIR Immunization resources.

        Args:
            extracted_data: Processor input with 'patient_id' and 'structured_data'.

        Returns:
            List of FHIR Immunization resource dicts (may be empty).
        """
        immunizations: List[Dict[str, Any]] = []
        patient_id = extracted_data.get('patient_id')

        if not patient_id:
            self.logger.warning("No patient_id provided for immunization processing")
            return immunizations

        clinical_date = extracted_data.get('clinical_date')
        structured = extracted_data.get('structured_data')
        if not isinstance(structured, dict):
            return immunizations

        # PRIMARY PATH: explicit immunizations list.
        imm_list = structured.get('immunizations') or []
        for imm_dict in imm_list:
            if isinstance(imm_dict, dict):
                resource = self._create_immunization_from_structured(
                    imm_dict, patient_id, clinical_date=clinical_date
                )
                if resource:
                    immunizations.append(resource)
        if imm_list:
            self.logger.info(
                "Created %s immunization resource(s) via structured path", len(immunizations)
            )

        # ALWAYS sweep procedures for vaccine-like entries, even when the
        # structured path produced immunizations. ProcedureService skips every
        # vaccine-like procedure (D1 contract); if we returned early here a
        # vaccine that the model placed in ``procedures`` would be dropped by
        # both services. We dedup against vaccines already created so the same
        # shot is never emitted twice.
        claimed = {
            (imm.get('vaccineCode', {}) or {}).get('text', '').strip().lower()
            for imm in immunizations
        }
        claimed.discard('')

        procedures = structured.get('procedures') or []
        converted = 0
        for proc in procedures:
            if not isinstance(proc, dict):
                continue
            proc_name = (proc.get('name') or '').strip()
            if not proc_name or not is_vaccine_name(proc_name):
                continue
            # Skip if an equivalent vaccine was already captured structurally.
            if any(word_match(proc_name.lower(), c) or word_match(c, proc_name.lower())
                   for c in claimed):
                continue
            resource = self._create_immunization_from_procedure(
                proc, patient_id, clinical_date=clinical_date
            )
            if resource:
                immunizations.append(resource)
                claimed.add(proc_name.lower())
                converted += 1
        if converted:
            self.logger.info(
                "Converted %s vaccine procedure(s) to Immunization resources", converted
            )

        return immunizations

    def _resolve_cvx(self, vaccine_name: str,
                     provided_code: Optional[str]) -> Optional[Dict[str, str]]:
        """Resolve a CVX coding from an explicit code or name lookup."""
        if provided_code and str(provided_code).strip():
            return {
                "system": "http://hl7.org/fhir/sid/cvx",
                "code": str(provided_code).strip(),
                "display": vaccine_name.strip(),
            }
        name_lower = vaccine_name.lower()

        # Disambiguate combination vaccines before single-antigen keywords:
        # "Measles/Mumps/Rubella" must not resolve to measles-only (CVX 05)
        # just because "measles" appears on a word boundary.
        if (word_match(name_lower, "measles")
                and (word_match(name_lower, "mumps") or word_match(name_lower, "rubella"))):
            return {"system": "http://hl7.org/fhir/sid/cvx", "code": "03", "display": "MMR"}

        # Word-boundary matching so "td" no longer matches "tdap"/"std" and
        # "flu" no longer matches unrelated names.
        for keyword, (code, display) in self.CVX_LOOKUP.items():
            if word_match(name_lower, keyword):
                return {
                    "system": "http://hl7.org/fhir/sid/cvx",
                    "code": code,
                    "display": display,
                }
        return None

    def _parse_date(self, raw_date: Any, clinical_date: Any) -> Optional[str]:
        """Parse an administration date, falling back to the clinical date."""
        if raw_date:
            try:
                extracted = self.date_parser.extract_dates(str(raw_date))
                if extracted:
                    best = max(extracted, key=lambda x: x.confidence)
                    return best.extracted_date.isoformat()
            except Exception as exc:
                self.logger.debug("Could not parse immunization date: %s", exc)

        if clinical_date:
            from datetime import date as date_type, datetime as datetime_type
            if isinstance(clinical_date, datetime_type):
                return clinical_date.isoformat()
            if isinstance(clinical_date, date_type):
                return datetime_type.combine(clinical_date, datetime_type.min.time()).isoformat()
            return str(clinical_date)
        return None

    def _build_immunization(self, vaccine_name: str, patient_id: str,
                            *, cvx_code: Optional[str], occurrence: Optional[str],
                            is_forecast: bool, lot_number: Optional[str] = None,
                            manufacturer: Optional[str] = None,
                            dose_number: Optional[str] = None,
                            route: Optional[str] = None, site: Optional[str] = None,
                            status: Optional[str] = None,
                            confidence: Optional[float] = None,
                            source: Any = None,
                            source_label: str = "Structured Pydantic extraction") -> Dict[str, Any]:
        """Assemble a FHIR Immunization resource from normalized inputs."""
        vaccine_code: Dict[str, Any] = {"text": vaccine_name.strip()}
        cvx = self._resolve_cvx(vaccine_name, cvx_code)
        if cvx:
            vaccine_code["coding"] = [cvx]

        # FHIR Immunization.status: completed | entered-in-error | not-done.
        # Forecast/recommended vaccines are represented as not-done.
        fhir_status = (status or "").strip().lower()
        if is_forecast:
            fhir_status = "not-done"
        elif fhir_status not in {"completed", "entered-in-error", "not-done"}:
            fhir_status = "completed"

        immunization: Dict[str, Any] = {
            "resourceType": "Immunization",
            "id": str(uuid4()),
            "status": fhir_status,
            "vaccineCode": vaccine_code,
            "patient": {"reference": f"Patient/{patient_id}"},
            "meta": {
                "source": source_label,
                "profile": ["http://hl7.org/fhir/StructureDefinition/Immunization"],
                "versionId": "1",
                "lastUpdated": datetime.now().isoformat(),
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                    "code": "extraction-source",
                    "display": "Structured immunization path",
                }],
            },
        }

        if occurrence:
            immunization["occurrenceDateTime"] = occurrence
        else:
            # occurrence[x] is required (1..1); when unknown, use occurrenceString.
            immunization["occurrenceString"] = "unknown"

        if is_forecast:
            immunization["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "vaccine-forecast",
                "display": "Recommended/forecast vaccine (not administered)",
            })

        if lot_number and str(lot_number).strip():
            immunization["lotNumber"] = str(lot_number).strip()
        if manufacturer and str(manufacturer).strip():
            immunization["manufacturer"] = {"display": str(manufacturer).strip()}
        if route and str(route).strip():
            immunization["route"] = {"text": str(route).strip()}
        if site and str(site).strip():
            immunization["site"] = {"text": str(site).strip()}
        if dose_number and str(dose_number).strip():
            # fhir.resources R5 represents the dose-in-series as a plain string
            # field named ``doseNumber`` (R4's doseNumber[x] choice was removed).
            immunization["protocolApplied"] = [{
                "doseNumber": str(dose_number).strip()
            }]

        append_extraction_extensions(
            immunization,
            confidence=confidence,
            source_text=source_snippet_from_field(source),
        )
        return immunization

    def _create_immunization_from_structured(self, imm_dict: Dict[str, Any], patient_id: str,
                                             clinical_date=None) -> Optional[Dict[str, Any]]:
        """Create an Immunization from an Immunization Pydantic-derived dict."""
        vaccine_name = imm_dict.get('vaccine_name')
        if not vaccine_name or not isinstance(vaccine_name, str) or not vaccine_name.strip():
            self.logger.warning("Invalid or empty vaccine_name: %s", imm_dict)
            return None

        is_forecast = bool(imm_dict.get('is_forecast'))
        # A forecast/recommended vaccine was NOT administered: do not fabricate
        # an occurrence date (and never fall back to the document's clinical
        # date), or it would look like a real administration at this visit.
        occurrence = (
            None if is_forecast
            else self._parse_date(imm_dict.get('date_administered'), clinical_date)
        )
        return self._build_immunization(
            vaccine_name, patient_id,
            cvx_code=imm_dict.get('cvx_code'),
            occurrence=occurrence,
            is_forecast=is_forecast,
            lot_number=imm_dict.get('lot_number'),
            manufacturer=imm_dict.get('manufacturer'),
            dose_number=imm_dict.get('dose_number'),
            route=imm_dict.get('route'),
            site=imm_dict.get('site'),
            status=imm_dict.get('status'),
            confidence=imm_dict.get('confidence'),
            source=imm_dict.get('source'),
        )

    def _create_immunization_from_procedure(self, proc_dict: Dict[str, Any], patient_id: str,
                                            clinical_date=None) -> Optional[Dict[str, Any]]:
        """Convert a vaccine-like Procedure dict into an Immunization (fallback)."""
        vaccine_name = proc_dict.get('name')
        if not vaccine_name or not isinstance(vaccine_name, str) or not vaccine_name.strip():
            return None

        occurrence = self._parse_date(proc_dict.get('procedure_date'), clinical_date)
        return self._build_immunization(
            vaccine_name, patient_id,
            cvx_code=None,
            occurrence=occurrence,
            is_forecast=False,
            confidence=proc_dict.get('confidence'),
            source=proc_dict.get('source'),
            source_label="Converted from procedure entry",
        )
