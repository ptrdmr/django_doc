import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from apps.documents.models import ParsedData
import json

pd = ParsedData.objects.filter(document_id=69).first()
if pd:
    print(f'ParsedData ID: {pd.id}')
    print(f'AI Model: {pd.ai_model_used}')
    print(f'Confidence: {pd.extraction_confidence}')
    print(f'Processing Time: {pd.processing_time_seconds}s')
    
    if pd.extraction_json:
        # extraction_json might already be a dict/list
        if isinstance(pd.extraction_json, (dict, list)):
            ej = pd.extraction_json
        else:
            ej = json.loads(pd.extraction_json)
        print(f'\nExtraction JSON Summary:')
        print(f'  Conditions: {len(ej.get("conditions", []))}')
        print(f'  Medications: {len(ej.get("medications", []))}')
        print(f'  Vital Signs: {len(ej.get("vital_signs", []))}')
        print(f'  Lab Results: {len(ej.get("lab_results", []))}')
        print(f'  Procedures: {len(ej.get("procedures", []))}')
        print(f'  Providers: {len(ej.get("providers", []))}')
        print(f'  Encounters: {len(ej.get("encounters", []))}')
        print(f'  Service Requests: {len(ej.get("service_requests", []))}')
        print(f'  Diagnostic Reports: {len(ej.get("diagnostic_reports", []))}')
        print(f'  Allergies: {len(ej.get("allergies", []))}')
        print(f'  Care Plans: {len(ej.get("care_plans", []))}')
        print(f'  Organizations: {len(ej.get("organizations", []))}')
        
        # Check if encounters and service_requests have correct field names
        if ej.get("encounters"):
            enc = ej["encounters"][0]
            print(f'\n[VERIFICATION] First Encounter Fields:')
            print(f'  Has "encounter_type": {"encounter_type" in enc}')
            print(f'  Has "type": {"type" in enc}')
            if "encounter_type" in enc:
                print(f'  encounter_type value: {enc["encounter_type"]}')
            if "type" in enc:
                print(f'  type value: {enc["type"]}')
        
        if ej.get("service_requests"):
            req = ej["service_requests"][0]
            print(f'\n[VERIFICATION] First Service Request Fields:')
            print(f'  Has "request_type": {"request_type" in req}')
            print(f'  Has "service": {"service" in req}')
            if "request_type" in req:
                print(f'  request_type value: {req["request_type"]}')
            if "service" in req:
                print(f'  service value: {req["service"]}')
    else:
        print('No extraction_json')
else:
    print('No ParsedData found for document 69')

