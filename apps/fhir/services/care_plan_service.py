"""
CarePlan Service for FHIR Resource Processing

This service handles the conversion of extracted care plan data into proper FHIR 
CarePlan resources with goals, activities, and timeline information.
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4
from datetime import datetime
from apps.core.date_parser import ClinicalDateParser

logger = logging.getLogger(__name__)


class CarePlanService:
    """
    Service for processing care plan data into FHIR CarePlan resources.
    
    This service ensures complete capture of care plan data by properly converting
    all extracted care plan information into structured FHIR resources.
    """
    
    def __init__(self):
        self.logger = logger
        self.date_parser = ClinicalDateParser()
        
    def process_care_plans(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process all care plans from extracted data into FHIR CarePlan resources.
        
        Supports dual-format input:
        1. Structured Pydantic-derived dicts (primary path)
        2. Legacy 'fields' list (fallback path)
        
        Args:
            extracted_data: Dictionary containing either:
                - 'structured_data' dict with 'care_plans' list (Pydantic CarePlan models)
                - 'fields' list with care plan data (legacy format)
            
        Returns:
            List of FHIR CarePlan resources
        """
        care_plans = []
        patient_id = extracted_data.get('patient_id')
        
        if not patient_id:
            self.logger.warning("No patient_id provided for care plan processing")
            return care_plans
        
        # PRIMARY PATH: Handle structured Pydantic data
        if 'structured_data' in extracted_data:
            structured_data = extracted_data['structured_data']
            if isinstance(structured_data, dict) and 'care_plans' in structured_data:
                plans_list = structured_data['care_plans']
                if plans_list:
                    self.logger.info(f"Processing {len(plans_list)} care plans via structured path")
                    for plan_dict in plans_list:
                        if isinstance(plan_dict, dict):
                            plan_resource = self._create_care_plan_from_structured(plan_dict, patient_id)
                            if plan_resource:
                                care_plans.append(plan_resource)
                    self.logger.info(f"Successfully processed {len(care_plans)} care plans via structured path")
                    return care_plans
        
        # FALLBACK PATH: Handle legacy fields list format
        if 'fields' in extracted_data:
            self.logger.warning(f"Falling back to legacy fields processing for care plans")
            self.logger.info(f"Processing {len(extracted_data['fields'])} fields for care plans")
            
            for field in extracted_data['fields']:
                if isinstance(field, dict):
                    label = field.get('label', '').lower()
                    if 'care plan' in label or 'treatment plan' in label or 'protocol' in label:
                        self.logger.debug(f"Found care plan field: {label}")
                        plan_resource = self._create_care_plan_from_field(field, patient_id)
                        if plan_resource:
                            care_plans.append(plan_resource)
                            self.logger.debug(f"Created care plan resource for {label}")
        
        self.logger.info(f"Successfully processed {len(care_plans)} care plan resources via legacy path")
        return care_plans
    
    def _create_care_plan_from_structured(self, plan_dict: Dict[str, Any], patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR CarePlan resource from structured Pydantic-derived dict.
        
        Args:
            plan_dict: Dictionary from CarePlan Pydantic model with fields:
                - plan_description: str (overview)
                - goals: List[str] (objectives)
                - activities: List[str] (interventions)
                - period_start: Optional[str]
                - period_end: Optional[str]
                - status: Optional[str] (draft, active, completed, cancelled)
                - intent: Optional[str] (proposal, plan, order)
                - confidence: float (0.0-1.0)
                - source: dict
            patient_id: Patient UUID
            
        Returns:
            FHIR CarePlan resource or None
        """
        description = plan_dict.get('plan_description')
        if not description or not isinstance(description, str) or not description.strip():
            self.logger.warning(f"Invalid or empty plan_description: {plan_dict}")
            return None
        
        # Parse dates using ClinicalDateParser
        start_date = None
        end_date = None
        
        raw_start = plan_dict.get('period_start')
        if raw_start:
            extracted_dates = self.date_parser.extract_dates(raw_start)
            if extracted_dates:
                best_date = max(extracted_dates, key=lambda x: x.confidence)
                start_date = best_date.extracted_date.isoformat()
                self.logger.debug(f"Parsed care plan start date {start_date}")
        
        raw_end = plan_dict.get('period_end')
        if raw_end:
            extracted_dates = self.date_parser.extract_dates(raw_end)
            if extracted_dates:
                best_date = max(extracted_dates, key=lambda x: x.confidence)
                end_date = best_date.extracted_date.isoformat()
                self.logger.debug(f"Parsed care plan end date {end_date}")
        
        # Map status
        status = plan_dict.get('status', 'active').lower()
        status_mapping = {
            'draft': 'draft',
            'active': 'active',
            'completed': 'completed',
            'cancelled': 'cancelled',
            'on-hold': 'on-hold',
            'revoked': 'revoked'
        }
        fhir_status = status_mapping.get(status, 'active')
        
        # Map intent
        intent = plan_dict.get('intent', 'plan').lower()
        intent_mapping = {
            'proposal': 'proposal',
            'plan': 'plan',
            'order': 'order'
        }
        fhir_intent = intent_mapping.get(intent, 'plan')
        
        # Create FHIR CarePlan resource
        care_plan = {
            "resourceType": "CarePlan",
            "id": str(uuid4()),
            "status": fhir_status,
            "intent": fhir_intent,
            "description": description.strip(),
            "subject": {
                "reference": f"Patient/{patient_id}"
            },
            "meta": {
                "source": "Structured Pydantic extraction",
                "profile": ["http://hl7.org/fhir/StructureDefinition/CarePlan"],
                "versionId": "1",
                "lastUpdated": datetime.now().isoformat(),
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                    "code": "extraction-source",
                    "display": "Structured data path"
                }]
            }
        }
        
        # Add period if dates available
        if start_date or end_date:
            care_plan["period"] = {}
            if start_date:
                care_plan["period"]["start"] = start_date
            if end_date:
                care_plan["period"]["end"] = end_date
        
        # Add goals
        goals = plan_dict.get('goals', [])
        if goals and isinstance(goals, list):
            care_plan["goal"] = []
            for goal_text in goals:
                if goal_text and isinstance(goal_text, str):
                    care_plan["goal"].append({
                        "description": {
                            "text": goal_text.strip()
                        }
                    })
        
        # Add activities
        activities = plan_dict.get('activities', [])
        if activities and isinstance(activities, list):
            care_plan["activity"] = []
            for activity_text in activities:
                if activity_text and isinstance(activity_text, str):
                    care_plan["activity"].append({
                        "detail": {
                            "description": activity_text.strip()
                        }
                    })
        
        # Add confidence
        confidence = plan_dict.get('confidence')
        if confidence is not None:
            if "extension" not in care_plan:
                care_plan["extension"] = []
            care_plan["extension"].append({
                "url": "http://hl7.org/fhir/StructureDefinition/data-confidence",
                "valueDecimal": confidence
            })
        
        # Add source context
        source = plan_dict.get('source')
        if source and isinstance(source, dict):
            source_text = source.get('text', '')
            if source_text:
                care_plan["note"] = [{
                    "text": f"Source: {source_text[:200]}"
                }]
        
        self.logger.debug(f"Created CarePlan from structured data: {description[:50]}...")
        return care_plan
    
    def _create_care_plan_from_field(self, field: Dict[str, Any], patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a FHIR CarePlan resource from a legacy field.
        
        Args:
            field: Dictionary containing label, value, confidence, etc.
            patient_id: Patient UUID
            
        Returns:
            FHIR CarePlan resource or None
        """
        value = field.get('value')
        if not value or not isinstance(value, str) or not value.strip():
            self.logger.warning(f"Invalid or empty value in care plan field: {field}")
            return None
        
        # Create basic CarePlan from field
        care_plan = {
            "resourceType": "CarePlan",
            "id": str(uuid4()),
            "status": "active",
            "intent": "plan",
            "description": value.strip(),
            "subject": {
                "reference": f"Patient/{patient_id}"
            },
            "meta": {
                "source": field.get('source_context', 'Document extraction'),
                "profile": ["http://hl7.org/fhir/StructureDefinition/CarePlan"],
                "versionId": "1",
                "lastUpdated": datetime.now().isoformat(),
                "tag": []
            }
        }
        
        # Add confidence if available
        confidence = field.get('confidence')
        if confidence is not None:
            care_plan["meta"]["tag"].append({
                "system": "http://terminology.hl7.org/CodeSystem/common-tags",
                "code": "extraction-confidence",
                "display": f"Extraction confidence: {confidence}"
            })
        
        self.logger.debug(f"Created CarePlan from legacy field: {value[:50]}...")
        return care_plan

