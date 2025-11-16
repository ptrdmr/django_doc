import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from apps.documents.models import ParsedData

pd = ParsedData.objects.filter(document_id=69).first()
if pd and pd.structured_extraction_metadata:
    sem = pd.structured_extraction_metadata
    print(f'Structured Extraction Metadata Type: {type(sem)}')
    print(f'\nResource Counts:')
    print(f'  Conditions: {len(sem.get("conditions", []))}')
    print(f'  Medications: {len(sem.get("medications", []))}')
    print(f'  Vital Signs: {len(sem.get("vital_signs", []))}')
    print(f'  Lab Results: {len(sem.get("lab_results", []))}')
    print(f'  Procedures: {len(sem.get("procedures", []))}')
    print(f'  Providers: {len(sem.get("providers", []))}')
    print(f'  Encounters: {len(sem.get("encounters", []))}')
    print(f'  Service Requests: {len(sem.get("service_requests", []))}')
    print(f'  Diagnostic Reports: {len(sem.get("diagnostic_reports", []))}')
    print(f'  Allergies: {len(sem.get("allergies", []))}')
    print(f'  Care Plans: {len(sem.get("care_plans", []))}')
    print(f'  Organizations: {len(sem.get("organizations", []))}')
    
    # Check field names in encounters
    encs = sem.get("encounters", [])
    if encs:
        print(f'\n[CRITICAL CHECK] First Encounter:')
        enc = encs[0]
        print(f'  All fields: {list(enc.keys())}')
        print(f'  Has "encounter_type": {"encounter_type" in enc}')
        print(f'  Has "type": {"type" in enc}')
        if "encounter_type" in enc:
            print(f'  [SUCCESS] encounter_type = {enc["encounter_type"]}')
        if "type" in enc:
            print(f'  [PROBLEM] type = {enc["type"]}')
    
    # Check field names in service_requests
    reqs = sem.get("service_requests", [])
    if reqs:
        print(f'\n[CRITICAL CHECK] First Service Request:')
        req = reqs[0]
        print(f'  All fields: {list(req.keys())}')
        print(f'  Has "request_type": {"request_type" in req}')
        print(f'  Has "service": {"service" in req}')
        if "request_type" in req:
            print(f'  [SUCCESS] request_type = {req["request_type"]}')
        if "service" in req:
            print(f'  [PROBLEM] service = {req["service"]}')
else:
    print('No structured_extraction_metadata found')


