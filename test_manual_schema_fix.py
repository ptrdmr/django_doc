"""
Test to verify the manual fallback schema produces valid Pydantic models.
This simulates what Claude returns when using the manual JSON schema.
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from apps.documents.services.ai_extraction import StructuredMedicalExtraction
import json

def test_complete_manual_schema():
    """Test that Claude's response with all 12 resource types validates"""
    
    # Simulate Claude returning data matching the manual schema
    claude_response = {
        "conditions": [
            {
                "name": "Hypertension",
                "status": "active",
                "confidence": 0.9,
                "onset_date": "2020-01-15",
                "icd_code": "I10",
                "source": {"text": "Patient has hypertension", "start_index": 0, "end_index": 25}
            }
        ],
        "medications": [
            {
                "name": "Lisinopril 10mg",
                "dosage": "10mg",
                "route": "oral",
                "frequency": "daily",
                "status": "active",
                "confidence": 0.9,
                "start_date": "2020-02-01",
                "stop_date": None,
                "source": {"text": "Lisinopril 10mg daily", "start_index": 50, "end_index": 71}
            }
        ],
        "vital_signs": [
            {
                "measurement": "Blood Pressure",
                "value": "120/80",
                "unit": "mmHg",
                "timestamp": "2024-11-10T10:00:00",
                "confidence": 0.95,
                "source": {"text": "BP 120/80", "start_index": 100, "end_index": 109}
            }
        ],
        "lab_results": [
            {
                "test_name": "Glucose",
                "value": "95",
                "unit": "mg/dL",
                "reference_range": "70-100",
                "status": "final",
                "test_date": "2024-11-09",
                "confidence": 0.9,
                "source": {"text": "Glucose 95 mg/dL", "start_index": 150, "end_index": 166}
            }
        ],
        "procedures": [
            {
                "name": "Annual Physical Exam",
                "procedure_date": "2024-11-10",
                "provider": "Dr. Smith",
                "outcome": "Normal findings",
                "confidence": 0.9,
                "source": {"text": "Annual physical completed", "start_index": 200, "end_index": 225}
            }
        ],
        "providers": [
            {
                "name": "Dr. Jane Smith",
                "specialty": "Family Medicine",
                "role": "Primary Care Physician",
                "contact_info": None,
                "confidence": 0.95,
                "source": {"text": "Dr. Jane Smith, Family Medicine", "start_index": 250, "end_index": 282}
            }
        ],
        "encounters": [
            {
                "encounter_id": None,
                "encounter_type": "office visit",  # CRITICAL: Must be "encounter_type" not "type"
                "encounter_date": "2024-11-10",
                "encounter_end_date": None,
                "location": "Main Clinic",
                "reason": "Annual checkup",
                "participants": ["Dr. Smith"],
                "status": "finished",
                "confidence": 0.9,
                "source": {"text": "Office visit for annual checkup", "start_index": 300, "end_index": 331}
            }
        ],
        "service_requests": [
            {
                "request_id": None,
                "request_type": "lab test",  # CRITICAL: Must be "request_type" not "service"
                "requester": "Dr. Smith",
                "reason": "Routine screening",
                "priority": "routine",
                "clinical_context": "Annual physical",
                "request_date": "2024-11-10",
                "confidence": 0.9,
                "source": {"text": "Order routine labs", "start_index": 350, "end_index": 368}
            }
        ],
        "diagnostic_reports": [
            {
                "report_id": None,
                "report_type": "lab",
                "findings": "All values within normal limits",
                "conclusion": "Normal lab results",
                "recommendations": "Continue current medications",
                "status": "final",
                "report_date": "2024-11-09",
                "ordering_provider": "Dr. Smith",
                "confidence": 0.9,
                "source": {"text": "Lab report shows normal values", "start_index": 400, "end_index": 430}
            }
        ],
        "allergies": [
            {
                "allergy_id": None,
                "allergen": "Penicillin",
                "reaction": "Rash",
                "severity": "moderate",
                "onset_date": "2015-03-20",
                "status": "active",
                "verification_status": "confirmed",
                "confidence": 0.95,
                "source": {"text": "Allergic to Penicillin - rash", "start_index": 450, "end_index": 480}
            }
        ],
        "care_plans": [
            {
                "plan_id": None,
                "plan_description": "Hypertension management plan",
                "goals": ["Maintain BP below 130/80", "Continue medication compliance"],
                "activities": ["Monthly BP checks", "Annual labs"],
                "period_start": "2024-11-10",
                "period_end": "2025-11-10",
                "status": "active",
                "intent": "plan",
                "confidence": 0.9,
                "source": {"text": "Continue HTN management", "start_index": 500, "end_index": 524}
            }
        ],
        "organizations": [
            {
                "organization_id": None,
                "name": "Main Street Clinic",
                "identifier": None,
                "organization_type": "clinic",
                "address": "123 Main St",
                "city": "Springfield",
                "state": "IL",
                "postal_code": "62701",
                "phone": "555-0100",
                "confidence": 0.9,
                "source": {"text": "Main Street Clinic, Springfield IL", "start_index": 550, "end_index": 585}
            }
        ],
        "extraction_timestamp": "2024-11-10T15:30:00",
        "document_type": "clinical_note",
        "confidence_average": None
    }
    
    # This should NOT raise ValidationError
    try:
        extraction = StructuredMedicalExtraction(**claude_response)
        print("[PASS] Complete schema validation successful!")
        print(f"  - Conditions: {len(extraction.conditions)}")
        print(f"  - Medications: {len(extraction.medications)}")
        print(f"  - Vital Signs: {len(extraction.vital_signs)}")
        print(f"  - Lab Results: {len(extraction.lab_results)}")
        print(f"  - Procedures: {len(extraction.procedures)}")
        print(f"  - Providers: {len(extraction.providers)}")
        print(f"  - Encounters: {len(extraction.encounters)}")
        print(f"  - Service Requests: {len(extraction.service_requests)}")
        print(f"  - Diagnostic Reports: {len(extraction.diagnostic_reports)}")
        print(f"  - Allergies: {len(extraction.allergies)}")
        print(f"  - Care Plans: {len(extraction.care_plans)}")
        print(f"  - Organizations: {len(extraction.organizations)}")
        print(f"  - Average Confidence: {extraction.confidence_average}")
        
        # Verify critical field names
        assert extraction.encounters[0].encounter_type == "office visit"
        print(f"\n[PASS] Encounter has correct field: encounter_type = '{extraction.encounters[0].encounter_type}'")
        
        assert extraction.service_requests[0].request_type == "lab test"
        print(f"[PASS] ServiceRequest has correct field: request_type = '{extraction.service_requests[0].request_type}'")
        
        return True
        
    except Exception as e:
        print(f"[FAIL] Validation error: {e}")
        return False


def test_problematic_document_scenario():
    """Test the exact scenario that was failing - encounters and service_requests"""
    
    # Simulate what was causing the original error
    problematic_response = {
        "conditions": [],
        "medications": [],
        "vital_signs": [],
        "lab_results": [],
        "procedures": [],
        "providers": [],
        "encounters": [
            {
                "encounter_type": "Emergency Department",  # Correct field name
                "encounter_date": "2024-10-20",
                "location": "General Hospital ER",
                "reason": "Chest pain",
                "participants": ["Dr. Jones"],
                "confidence": 0.9,
                "source": {"text": "Patient seen in ER", "start_index": 0, "end_index": 18}
            }
        ],
        "service_requests": [
            {
                "request_type": "STAT Cardiology Consult",  # Correct field name
                "requester": "Dr. Jones",
                "reason": "Elevated troponin",
                "priority": "stat",
                "confidence": 0.9,
                "source": {"text": "Cardiology consult ordered", "start_index": 50, "end_index": 76}
            }
        ],
        "diagnostic_reports": [],
        "allergies": [],
        "care_plans": [],
        "organizations": [],
        "extraction_timestamp": "2024-11-10T15:30:00",
        "document_type": "emergency_note",
        "confidence_average": None
    }
    
    try:
        extraction = StructuredMedicalExtraction(**problematic_response)
        print("\n[PASS] Problematic document scenario now validates!")
        print(f"  - Encounter type: {extraction.encounters[0].encounter_type}")
        print(f"  - Service request type: {extraction.service_requests[0].request_type}")
        return True
    except Exception as e:
        print(f"\n[FAIL] Still failing: {e}")
        return False


if __name__ == '__main__':
    print("=" * 70)
    print("Testing Manual Fallback Schema Fix")
    print("=" * 70)
    
    test1 = test_complete_manual_schema()
    test2 = test_problematic_document_scenario()
    
    print("\n" + "=" * 70)
    if test1 and test2:
        print("[SUCCESS] All tests passed! Manual schema fix is working.")
    else:
        print("[FAILURE] Some tests failed. Check output above.")
    print("=" * 70)


