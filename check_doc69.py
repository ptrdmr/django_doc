import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from apps.documents.models import Document
import json

d = Document.objects.get(id=69)
print(f'Document 69 Status: {d.status}')
print(f'Processing Time: {d.processing_time_ms}ms' if d.processing_time_ms else 'Processing Time: Not recorded')
print(f'Error: {d.error_message}' if d.error_message else 'No errors')

if d.structured_data:
    sd = json.loads(d.structured_data)
    print(f'\nExtracted Data Summary:')
    print(f'  Conditions: {len(sd.get("conditions", []))}')
    print(f'  Medications: {len(sd.get("medications", []))}')
    print(f'  Vital Signs: {len(sd.get("vital_signs", []))}')
    print(f'  Lab Results: {len(sd.get("lab_results", []))}')
    print(f'  Procedures: {len(sd.get("procedures", []))}')
    print(f'  Providers: {len(sd.get("providers", []))}')
    print(f'  Encounters: {len(sd.get("encounters", []))}')
    print(f'  Service Requests: {len(sd.get("service_requests", []))}')
    print(f'  Diagnostic Reports: {len(sd.get("diagnostic_reports", []))}')
    print(f'  Allergies: {len(sd.get("allergies", []))}')
    print(f'  Care Plans: {len(sd.get("care_plans", []))}')
    print(f'  Organizations: {len(sd.get("organizations", []))}')
    
    # Show sample encounter and service request to verify field names
    if sd.get("encounters"):
        enc = sd["encounters"][0]
        print(f'\nFirst Encounter:')
        print(f'  Type: {enc.get("encounter_type", "MISSING")}')
        print(f'  Date: {enc.get("encounter_date", "N/A")}')
        print(f'  Location: {enc.get("location", "N/A")}')
    
    if sd.get("service_requests"):
        req = sd["service_requests"][0]
        print(f'\nFirst Service Request:')
        print(f'  Type: {req.get("request_type", "MISSING")}')
        print(f'  Requester: {req.get("requester", "N/A")}')
        print(f'  Priority: {req.get("priority", "N/A")}')
else:
    print('No structured data found')


