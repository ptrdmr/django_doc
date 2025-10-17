"""
Quick test script to generate a patient summary report with real data.
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from apps.patients.models import Patient
from apps.reports.generators import PatientReportTemplate

def test_patient_report():
    """Test patient report generation."""
    print("="*60)
    print("PATIENT SUMMARY REPORT TEST")
    print("="*60)
    
    # Get recent patients (the query is simpler this way)
    all_patients = Patient.objects.order_by('-created_at')[:10]
    
    # Filter to those with FHIR data in Python
    patients = []
    for p in all_patients:
        bundle = p.encrypted_fhir_bundle
        if bundle and bundle.get('entry'):
            patients.append(p)
        if len(patients) >= 5:
            break
    
    if not patients:
        print("\n[X] No patients with FHIR data found!")
        print("Please process some documents first.\n")
        return
    
    print(f"\n[OK] Found {len(patients)} patients with FHIR data\n")
    
    # List patients
    for i, patient in enumerate(patients, 1):
        print(f"{i}. {patient.full_name} (MRN: {patient.mrn})")
        print(f"   Age: {patient.age}, FHIR Resources: {len(patient.encrypted_fhir_bundle.get('entry', []))}")
    
    # Use first patient
    patient = patients[0]
    print(f"\n[*] Generating report for: {patient.full_name}")
    print(f"    MRN: {patient.mrn}")
    
    # Generate report
    generator = PatientReportTemplate(parameters={
        'patient_id': str(patient.id),
        'include_demographics': True,
        'include_conditions': True,
        'include_medications': True,
        'include_observations': True,
    })
    
    print("\n[*] Extracting FHIR data...")
    report_data = generator.generate()
    
    # Print summary
    print("\n[*] REPORT SUMMARY:")
    print("="*60)
    print(f"Patient: {report_data['patient_info']['name']}")
    print(f"Age: {report_data['patient_info']['age']}")
    print(f"Gender: {report_data['patient_info']['gender']}")
    print(f"\nClinical Data:")
    print(f"  - Conditions: {len(report_data['clinical_summary']['conditions'])}")
    print(f"  - Medications: {len(report_data['clinical_summary']['medications'])}")
    print(f"  - Observations: {len(report_data['clinical_summary']['observations'])}")
    print(f"  - Procedures: {len(report_data['clinical_summary']['procedures'])}")
    print(f"  - Encounters: {len(report_data['clinical_summary']['encounters'])}")
    
    # Show some sample data
    if report_data['clinical_summary']['conditions']:
        print(f"\nSample Conditions (first 3):")
        for cond in report_data['clinical_summary']['conditions'][:3]:
            print(f"  - {cond['display_name']} ({cond['status']})")
            if cond.get('onset_date'):
                print(f"    Onset: {cond['onset_date']}")
    
    if report_data['clinical_summary']['medications']:
        print(f"\nSample Medications (first 3):")
        for med in report_data['clinical_summary']['medications'][:3]:
            print(f"  - {med['display_name']} ({med['status']})")
    
    # Generate PDF
    print("\n[*] Generating PDF...")
    pdf_path = f"test_patient_report_{patient.mrn}.pdf"
    generator.to_pdf(pdf_path)
    
    file_size = os.path.getsize(pdf_path) / 1024  # KB
    print(f"\n[SUCCESS] PDF generated:")
    print(f"    File: {pdf_path}")
    print(f"    Size: {file_size:.1f} KB")
    
    # Also generate CSV and JSON
    print("\n[*] Generating CSV...")
    csv_path = f"test_patient_report_{patient.mrn}.csv"
    generator.to_csv(csv_path)
    print(f"    [OK] CSV: {csv_path}")
    
    print("\n[*] Generating JSON...")
    json_path = f"test_patient_report_{patient.mrn}.json"
    generator.to_json(json_path)
    print(f"    [OK] JSON: {json_path}")
    
    print("\n" + "="*60)
    print("[SUCCESS] PATIENT SUMMARY REPORT COMPLETE!")
    print("="*60)
    print(f"\nGenerated files:")
    print(f"  - {pdf_path}")
    print(f"  - {csv_path}")
    print(f"  - {json_path}")
    print("\n[OK] Check the files to see the complete patient medical history!\n")

if __name__ == '__main__':
    test_patient_report()

