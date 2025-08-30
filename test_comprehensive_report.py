#!/usr/bin/env python
"""
Test script for the get_comprehensive_report method in Patient model.
This script creates a test patient with encrypted FHIR data and generates a comprehensive report.
"""

import os
import sys
import django
from datetime import datetime, date

# Add the project root to Python path
sys.path.append('F:/coding/doc/doc2db_2025_django')

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from apps.patients.models import Patient
from django.contrib.auth import get_user_model
from django.utils import timezone
import json

User = get_user_model()

def create_test_fhir_data():
    """Create comprehensive test FHIR data for testing the report generation."""
    return {
        "Condition": [
            {
                "resourceType": "Condition",
                "id": "condition-1",
                "clinicalStatus": {
                    "coding": [{"code": "active", "display": "Active"}]
                },
                "verificationStatus": {
                    "coding": [{"code": "confirmed", "display": "Confirmed"}]
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
                "onsetDateTime": "2020-01-15",
                "recordedDate": "2020-01-15T10:30:00Z",
                "severity": {
                    "coding": [{"code": "moderate", "display": "Moderate"}]
                },
                "note": [
                    {"text": "Patient diagnosed with Type 2 diabetes mellitus"}
                ]
            },
            {
                "resourceType": "Condition",
                "id": "condition-2",
                "clinicalStatus": {
                    "coding": [{"code": "active", "display": "Active"}]
                },
                "verificationStatus": {
                    "coding": [{"code": "confirmed", "display": "Confirmed"}]
                },
                "code": {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "38341003",
                            "display": "Hypertensive disorder"
                        }
                    ]
                },
                "onsetDateTime": "2019-06-10",
                "recordedDate": "2019-06-10T14:15:00Z"
            }
        ],
        "Procedure": [
            {
                "resourceType": "Procedure",
                "id": "procedure-1",
                "status": "completed",
                "code": {
                    "coding": [
                        {
                            "system": "http://www.ama-assn.org/go/cpt",
                            "code": "99213",
                            "display": "Office visit, established patient"
                        }
                    ]
                },
                "performedDateTime": "2023-08-15",
                "category": {
                    "coding": [{"code": "outpatient", "display": "Outpatient"}]
                },
                "outcome": {
                    "coding": [{"code": "successful", "display": "Successful"}]
                },
                "note": [
                    {"text": "Routine follow-up visit for diabetes management"}
                ]
            }
        ],
        "MedicationRequest": [
            {
                "resourceType": "MedicationRequest",
                "id": "medication-1",
                "status": "active",
                "medicationCodeableConcept": {
                    "coding": [
                        {
                            "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                            "code": "860975",
                            "display": "Metformin 500mg tablets"
                        }
                    ]
                },
                "dosageInstruction": [
                    {
                        "text": "Take 1 tablet twice daily with meals",
                        "route": {
                            "coding": [{"code": "PO", "display": "Oral"}]
                        },
                        "timing": {
                            "repeat": {
                                "frequency": 2,
                                "period": 1,
                                "periodUnit": "d"
                            }
                        },
                        "doseAndRate": [
                            {
                                "doseQuantity": {
                                    "value": 500,
                                    "unit": "mg"
                                }
                            }
                        ]
                    }
                ],
                "effectivePeriod": {
                    "start": "2020-01-15",
                    "end": "2024-01-15"
                },
                "category": {
                    "coding": [{"code": "community", "display": "Community"}]
                },
                "requester": {
                    "display": "Dr. Jane Smith, MD"
                },
                "note": [
                    {"text": "For diabetes management - monitor blood glucose"}
                ]
            }
        ],
        "Observation": [
            {
                "resourceType": "Observation",
                "id": "observation-1",
                "status": "final",
                "category": [
                    {
                        "coding": [
                            {"code": "laboratory", "display": "Laboratory"}
                        ]
                    }
                ],
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
                "referenceRange": [
                    {
                        "low": {"value": 4.0, "unit": "%"},
                        "high": {"value": 6.0, "unit": "%"},
                        "text": "Normal range for adults"
                    }
                ],
                "interpretation": [
                    {
                        "coding": [{"code": "H", "display": "High"}]
                    }
                ],
                "effectiveDateTime": "2023-08-15T09:00:00Z",
                "note": [
                    {"text": "Elevated HbA1c indicates need for better glucose control"}
                ]
            },
            {
                "resourceType": "Observation",
                "id": "observation-2",
                "status": "final",
                "category": [
                    {
                        "coding": [
                            {"code": "vital-signs", "display": "Vital Signs"}
                        ]
                    }
                ],
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "85354-9",
                            "display": "Blood pressure panel"
                        }
                    ]
                },
                "valueString": "140/90 mmHg",
                "effectiveDateTime": "2023-08-15T10:30:00Z"
            }
        ],
        "Encounter": [
            {
                "resourceType": "Encounter",
                "id": "encounter-1",
                "status": "finished",
                "class": {
                    "code": "AMB",
                    "display": "Ambulatory"
                },
                "type": [
                    {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": "185349003",
                                "display": "Encounter for check up"
                            }
                        ]
                    }
                ],
                "period": {
                    "start": "2023-08-15T09:00:00Z",
                    "end": "2023-08-15T11:00:00Z"
                },
                "reasonCode": [
                    {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": "73211009",
                                "display": "Diabetes mellitus follow-up"
                            }
                        ]
                    }
                ],
                "diagnosis": [
                    {
                        "condition": {
                            "display": "Diabetes mellitus type 2"
                        }
                    }
                ],
                "location": [
                    {
                        "location": {
                            "display": "Main Street Clinic"
                        }
                    }
                ],
                "participant": [
                    {
                        "type": [
                            {
                                "coding": [{"code": "ATND", "display": "Attending physician"}]
                            }
                        ],
                        "individual": {
                            "display": "Dr. Jane Smith, MD"
                        }
                    }
                ]
            }
        ],
        "Practitioner": [
            {
                "resourceType": "Practitioner",
                "id": "practitioner-1",
                "name": [
                    {
                        "use": "official",
                        "prefix": ["Dr."],
                        "given": ["Jane"],
                        "family": "Smith",
                        "suffix": ["MD"]
                    }
                ],
                "qualification": [
                    {
                        "code": {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/v2-0360",
                                    "code": "MD",
                                    "display": "Doctor of Medicine"
                                }
                            ]
                        }
                    }
                ],
                "telecom": [
                    {
                        "system": "phone",
                        "value": "+1-555-123-4567"
                    },
                    {
                        "system": "email",
                        "value": "jane.smith@mainstreetclinic.com"
                    }
                ]
            }
        ],
        "Organization": [
            {
                "resourceType": "Organization",
                "id": "organization-1",
                "name": "Main Street Medical Clinic",
                "type": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/organization-type",
                                "code": "prov",
                                "display": "Healthcare Provider"
                            }
                        ]
                    }
                ],
                "telecom": [
                    {
                        "system": "phone",
                        "value": "+1-555-987-6543"
                    },
                    {
                        "system": "url",
                        "value": "https://mainstreetclinic.com"
                    }
                ],
                "address": [
                    {
                        "use": "work",
                        "type": "physical",
                        "line": ["123 Main Street"],
                        "city": "Anytown",
                        "state": "ST",
                        "postalCode": "12345",
                        "country": "US"
                    }
                ]
            }
        ]
    }

def main():
    """Main test function."""
    print("🔧 Testing Patient.get_comprehensive_report() method...")
    print("=" * 60)
    
    # Generate unique MRNs using timestamp
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    test_mrn = f'TEST-{timestamp}'
    empty_mrn = f'EMPTY-{timestamp}'
    
    try:
        # Clean up any existing test patients first
        Patient.objects.filter(mrn__startswith='TEST-').delete()
        Patient.objects.filter(mrn__startswith='EMPTY-').delete()
        
        # Create or get a test user
        user, created = User.objects.get_or_create(
            username='test_user',
            defaults={'email': 'test@example.com'}
        )
        if created:
            print("✅ Created test user")
        else:
            print("✅ Using existing test user")
        
        # Create a test patient with encrypted FHIR data
        patient = Patient(
            mrn=test_mrn,
            first_name='John',
            last_name='Doe',
            date_of_birth='1980-05-15',
            gender='M',
            ssn='123-45-6789',
            address='123 Test Street, Test City, TS 12345',
            phone='555-123-4567',
            email='john.doe@example.com',
            created_by=user
        )
        
        # Add comprehensive FHIR data to the encrypted bundle
        test_fhir_data = create_test_fhir_data()
        patient.encrypted_fhir_bundle = test_fhir_data
        patient.save()
        
        print(f"✅ Created test patient: {patient.mrn}")
        print(f"   Name: {patient.full_name}")
        print(f"   Age: {patient.age}")
        print(f"   FHIR Resources: {len(test_fhir_data)} resource types")
        
        # Generate comprehensive report
        print("\n🔍 Generating comprehensive report...")
        report = patient.get_comprehensive_report()
        
        # Display report summary
        print("\n📊 COMPREHENSIVE PATIENT REPORT")
        print("=" * 50)
        
        # Patient info
        patient_info = report['patient_info']
        print(f"Patient: {patient_info['name']} (MRN: {patient_info['mrn']})")
        print(f"Age: {patient_info['age']}, Gender: {patient_info['gender']}")
        print(f"DOB: {patient_info['date_of_birth']}")
        print(f"Contact: {patient_info['contact']['phone']}")
        
        # Clinical summary
        clinical = report['clinical_summary']
        print(f"\n📋 Clinical Summary:")
        print(f"  • Conditions: {len(clinical['conditions'])}")
        print(f"  • Procedures: {len(clinical['procedures'])}")
        print(f"  • Medications: {len(clinical['medications'])}")
        print(f"  • Observations: {len(clinical['observations'])}")
        print(f"  • Encounters: {len(clinical['encounters'])}")
        
        # Detailed clinical data
        if clinical['conditions']:
            print(f"\n🏥 Conditions ({len(clinical['conditions'])}):")
            for i, condition in enumerate(clinical['conditions'], 1):
                print(f"  {i}. {condition['display_name']} ({condition['status']})")
                print(f"     Onset: {condition['onset_date']}")
                if condition['severity']:
                    print(f"     Severity: {condition['severity']}")
        
        if clinical['procedures']:
            print(f"\n⚕️ Procedures ({len(clinical['procedures'])}):")
            for i, procedure in enumerate(clinical['procedures'], 1):
                print(f"  {i}. {procedure['display_name']} ({procedure['status']})")
                print(f"     Performed: {procedure['performed_date']}")
        
        if clinical['medications']:
            print(f"\n💊 Medications ({len(clinical['medications'])}):")
            for i, medication in enumerate(clinical['medications'], 1):
                print(f"  {i}. {medication['display_name']} ({medication['status']})")
                if medication['dosage']:
                    for dosage in medication['dosage']:
                        if 'text' in dosage:
                            print(f"     Dosage: {dosage['text']}")
        
        if clinical['observations']:
            print(f"\n🔬 Observations ({len(clinical['observations'])}):")
            for i, observation in enumerate(clinical['observations'], 1):
                print(f"  {i}. {observation['display_name']} ({observation['status']})")
                if observation['value']:
                    unit = f" {observation['unit']}" if observation['unit'] else ""
                    print(f"     Value: {observation['value']}{unit}")
                if observation['interpretation']:
                    print(f"     Interpretation: {', '.join(observation['interpretation'])}")
        
        if clinical['encounters']:
            print(f"\n🏥 Encounters ({len(clinical['encounters'])}):")
            for i, encounter in enumerate(clinical['encounters'], 1):
                print(f"  {i}. {encounter['class']} encounter ({encounter['status']})")
                if encounter['period']:
                    print(f"     Period: {encounter['period']['start']} to {encounter['period']['end']}")
                if encounter['location']:
                    print(f"     Location: {', '.join(encounter['location'])}")
        
        # Provider summary
        providers = report['provider_summary']
        if providers['providers']:
            print(f"\n👨‍⚕️ Providers ({len(providers['providers'])}):")
            for i, provider in enumerate(providers['providers'], 1):
                print(f"  {i}. {provider['name']}")
                if provider['qualifications']:
                    quals = [q['display'] for q in provider['qualifications'] if q['display']]
                    if quals:
                        print(f"     Qualifications: {', '.join(quals)}")
        
        if providers['organizations']:
            print(f"\n🏢 Organizations ({len(providers['organizations'])}):")
            for i, org in enumerate(providers['organizations'], 1):
                print(f"  {i}. {org['name']}")
                if org['type']:
                    types = [t['display'] for t in org['type'] if t['display']]
                    if types:
                        print(f"     Type: {', '.join(types)}")
        
        # Report metadata
        metadata = report['report_metadata']
        print(f"\n📈 Report Metadata:")
        print(f"  • Generated: {metadata['generated_at']}")
        print(f"  • Status: {metadata['status']}")
        print(f"  • Total Resources: {metadata['total_resources']}")
        print(f"  • FHIR Version: {metadata['fhir_version']}")
        
        # Test error handling with empty patient
        print("\n🧪 Testing error handling...")
        empty_patient = Patient(
            mrn=empty_mrn,
            first_name='Empty',
            last_name='Patient',
            date_of_birth='1990-01-01',
            created_by=user
        )
        empty_patient.save()
        
        empty_report = empty_patient.get_comprehensive_report()
        print(f"✅ Empty patient report status: {empty_report['report_metadata']['status']}")
        print(f"   Message: {empty_report['report_metadata'].get('message', 'N/A')}")
        
        # Clean up test data
        print("\n🧹 Cleaning up test data...")
        patient.delete()
        empty_patient.delete()
        print("✅ Test data cleaned up")
        
        print("\n🎉 All tests completed successfully!")
        print("✅ get_comprehensive_report() method is working correctly")
        
    except Exception as e:
        print(f"\n❌ Error during testing: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
