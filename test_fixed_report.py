#!/usr/bin/env python
"""
Test script to verify the fixed get_comprehensive_report method works correctly
with the proper FHIR Bundle structure.
"""

import os
import sys
import django
from datetime import datetime

# Add the project root to Python path
sys.path.append('F:/coding/doc/doc2db_2025_django')

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from apps.patients.models import Patient
from django.contrib.auth import get_user_model
import json

User = get_user_model()

def main():
    """Test the fixed comprehensive report generation."""
    print("🔧 Testing FIXED get_comprehensive_report() method...")
    print("=" * 60)
    
    try:
        # Clean up any existing test patients
        Patient.objects.filter(mrn__startswith='FIXED-TEST-').delete()
        
        # Create test user
        user, _ = User.objects.get_or_create(
            username='test_user',
            defaults={'email': 'test@example.com'}
        )
        
        # Create test patient
        patient = Patient(
            mrn='FIXED-TEST-001',
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-05-15',
            gender='M',
            created_by=user
        )
        
        # Create test FHIR resources that will be added using add_fhir_resources
        test_resources = [
            {
                "resourceType": "Condition",
                "id": "condition-1",
                "clinicalStatus": {
                    "coding": [{"code": "active", "display": "Active"}]
                },
                "code": {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "73211009",
                            "display": "Diabetes mellitus"
                        }
                    ]
                },
                "onsetDateTime": "2020-01-15"
            },
            {
                "resourceType": "Procedure",
                "id": "procedure-1",
                "status": "completed",
                "code": {
                    "coding": [
                        {
                            "system": "http://www.ama-assn.org/go/cpt",
                            "code": "99213",
                            "display": "Office visit"
                        }
                    ]
                },
                "performedDateTime": "2023-08-15"
            },
            {
                "resourceType": "MedicationRequest",
                "id": "medication-1",
                "status": "active",
                "medicationCodeableConcept": {
                    "coding": [
                        {
                            "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                            "code": "860975",
                            "display": "Metformin 500mg"
                        }
                    ]
                }
            },
            {
                "resourceType": "Observation",
                "id": "observation-1",
                "status": "final",
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "4548-4",
                            "display": "Hemoglobin A1c"
                        }
                    ]
                },
                "valueQuantity": {
                    "value": 7.2,
                    "unit": "%"
                },
                "effectiveDateTime": "2023-08-15"
            },
            {
                "resourceType": "Encounter",
                "id": "encounter-1",
                "status": "finished",
                "class": {
                    "code": "AMB",
                    "display": "Ambulatory"
                },
                "period": {
                    "start": "2023-08-15T09:00:00Z",
                    "end": "2023-08-15T11:00:00Z"
                }
            }
        ]
        
        # Add resources using the proper method (this creates the Bundle structure)
        patient.add_fhir_resources(test_resources)
        patient.save()
        
        print(f"✅ Created test patient: {patient.mrn}")
        print(f"   Bundle entries: {len(patient.encrypted_fhir_bundle.get('entry', []))}")
        
        # Generate comprehensive report
        print("\n🔍 Generating comprehensive report with FIXED method...")
        report = patient.get_comprehensive_report()
        
        # Verify report structure and content
        print("\n📊 FIXED COMPREHENSIVE PATIENT REPORT")
        print("=" * 50)
        
        # Patient info
        patient_info = report['patient_info']
        print(f"Patient: {patient_info['name']} (MRN: {patient_info['mrn']})")
        print(f"Age: {patient_info['age']}, Gender: {patient_info['gender']}")
        print(f"DOB: {patient_info['date_of_birth']}")
        
        # Clinical summary
        clinical = report['clinical_summary']
        print(f"\n📋 Clinical Summary:")
        print(f"  • Conditions: {len(clinical['conditions'])}")
        print(f"  • Procedures: {len(clinical['procedures'])}")
        print(f"  • Medications: {len(clinical['medications'])}")
        print(f"  • Observations: {len(clinical['observations'])}")
        print(f"  • Encounters: {len(clinical['encounters'])}")
        
        # Detailed verification
        if clinical['conditions']:
            print(f"\n🏥 Conditions:")
            for condition in clinical['conditions']:
                print(f"  - {condition['display_name']} ({condition['status']})")
        
        if clinical['procedures']:
            print(f"\n⚕️ Procedures:")
            for procedure in clinical['procedures']:
                print(f"  - {procedure['display_name']} ({procedure['status']})")
        
        if clinical['medications']:
            print(f"\n💊 Medications:")
            for medication in clinical['medications']:
                print(f"  - {medication['display_name']} ({medication['status']})")
        
        if clinical['observations']:
            print(f"\n🔬 Observations:")
            for observation in clinical['observations']:
                value_str = f": {observation['value']} {observation['unit']}" if observation['value'] else ""
                print(f"  - {observation['display_name']}{value_str} ({observation['status']})")
        
        if clinical['encounters']:
            print(f"\n🏥 Encounters:")
            for encounter in clinical['encounters']:
                print(f"  - {encounter['class']} encounter ({encounter['status']})")
        
        # Report metadata
        metadata = report['report_metadata']
        print(f"\n📈 Report Metadata:")
        print(f"  • Status: {metadata['status']}")
        print(f"  • Total Resources: {metadata['total_resources']}")
        print(f"  • Generated: {metadata['generated_at']}")
        
        # Validation checks
        print(f"\n✅ VALIDATION RESULTS:")
        print(f"  • Report generated successfully: {metadata['status'] == 'success'}")
        print(f"  • Expected 5 resources, got: {metadata['total_resources']}")
        print(f"  • Conditions extracted: {len(clinical['conditions']) == 1}")
        print(f"  • Procedures extracted: {len(clinical['procedures']) == 1}")
        print(f"  • Medications extracted: {len(clinical['medications']) == 1}")
        print(f"  • Observations extracted: {len(clinical['observations']) == 1}")
        print(f"  • Encounters extracted: {len(clinical['encounters']) == 1}")
        
        # Check that we got the expected data
        success = (
            metadata['status'] == 'success' and
            metadata['total_resources'] == 5 and
            len(clinical['conditions']) == 1 and
            len(clinical['procedures']) == 1 and
            len(clinical['medications']) == 1 and
            len(clinical['observations']) == 1 and
            len(clinical['encounters']) == 1
        )
        
        if success:
            print("\n🎉 ALL VALIDATION CHECKS PASSED!")
            print("✅ get_comprehensive_report() method is working correctly with Bundle structure")
        else:
            print("\n❌ VALIDATION FAILED - Some checks did not pass")
            return False
        
        # Clean up
        patient.delete()
        print("\n🧹 Test data cleaned up")
        
    except Exception as e:
        print(f"\n❌ Error during testing: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
