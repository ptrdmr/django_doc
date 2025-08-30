#!/usr/bin/env python
"""
Test script to verify the FHIR bundle structure created by add_fhir_resources
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
    """Test the actual bundle structure."""
    print("🔍 Testing FHIR bundle structure...")
    
    # Create test user
    user, _ = User.objects.get_or_create(
        username='test_user',
        defaults={'email': 'test@example.com'}
    )
    
    # Create test patient
    patient = Patient(
        mrn='TEST-BUNDLE-001',
        first_name='Test',
        last_name='Patient',
        date_of_birth='1980-01-01',
        created_by=user
    )
    
    # Create test FHIR resource
    test_condition = {
        "resourceType": "Condition",
        "id": "test-condition",
        "code": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "73211009",
                    "display": "Diabetes mellitus"
                }
            ]
        }
    }
    
    # Add resource using the method
    patient.add_fhir_resources(test_condition)
    patient.save()
    
    # Check the actual structure
    print("📊 Encrypted FHIR Bundle Structure:")
    print(json.dumps(patient.encrypted_fhir_bundle, indent=2))
    
    # Clean up
    patient.delete()
    
    print("✅ Test completed")

if __name__ == '__main__':
    main()
