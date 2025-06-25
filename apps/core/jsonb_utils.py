"""
JSONB Utilities for Medical Document Parser
Handles FHIR data storage and retrieval using PostgreSQL JSONB fields
"""

import json
from typing import Dict, List, Any, Optional
from django.db import connection
from django.conf import settings


class FHIRJSONBManager:
    """
    Manager class for handling FHIR data in PostgreSQL JSONB fields
    Provides utilities for storing, querying, and manipulating FHIR resources
    """
    
    @staticmethod
    def validate_fhir_resource(resource: Dict[str, Any]) -> bool:
        """
        Validate that a resource follows basic FHIR structure
        
        Args:
            resource: Dictionary representing a FHIR resource
            
        Returns:
            bool: True if valid FHIR resource structure
        """
        required_fields = ['resourceType', 'id']
        return all(field in resource for field in required_fields)
    
    @staticmethod
    def create_fhir_bundle(patient_id: str, resources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Create a FHIR Bundle containing multiple resources for a patient
        
        Args:
            patient_id: Unique identifier for the patient
            resources: List of FHIR resources to include in bundle
            
        Returns:
            Dict: Complete FHIR Bundle structure
        """
        bundle = {
            "resourceType": "Bundle",
            "id": f"patient-bundle-{patient_id}",
            "type": "collection",
            "timestamp": "2024-01-01T00:00:00Z",  # Should be current timestamp
            "total": len(resources),
            "entry": []
        }
        
        for resource in resources:
            if FHIRJSONBManager.validate_fhir_resource(resource):
                entry = {
                    "fullUrl": f"urn:uuid:{resource.get('id')}",
                    "resource": resource
                }
                bundle["entry"].append(entry)
        
        return bundle
    
    @staticmethod
    def add_resource_to_bundle(bundle: Dict[str, Any], resource: Dict[str, Any], 
                             document_source: str = None) -> Dict[str, Any]:
        """
        Add a new FHIR resource to an existing bundle with provenance tracking
        
        Args:
            bundle: Existing FHIR bundle
            resource: New FHIR resource to add
            document_source: Source document identifier for provenance
            
        Returns:
            Dict: Updated bundle with new resource
        """
        if not FHIRJSONBManager.validate_fhir_resource(resource):
            raise ValueError("Invalid FHIR resource structure")
        
        # Add provenance metadata
        if document_source:
            if 'meta' not in resource:
                resource['meta'] = {}
            resource['meta']['source'] = document_source
            resource['meta']['lastUpdated'] = "2024-01-01T00:00:00Z"  # Should be current timestamp
        
        # Add to bundle
        entry = {
            "fullUrl": f"urn:uuid:{resource.get('id')}",
            "resource": resource
        }
        
        if 'entry' not in bundle:
            bundle['entry'] = []
        
        bundle['entry'].append(entry)
        bundle['total'] = len(bundle['entry'])
        
        return bundle
    
    @staticmethod
    def get_resources_by_type(bundle: Dict[str, Any], resource_type: str) -> List[Dict[str, Any]]:
        """
        Extract all resources of a specific type from a FHIR bundle
        
        Args:
            bundle: FHIR bundle to search
            resource_type: Type of resource to extract (e.g., 'Patient', 'Condition')
            
        Returns:
            List: All resources of the specified type
        """
        resources = []
        
        if 'entry' in bundle:
            for entry in bundle['entry']:
                if 'resource' in entry:
                    resource = entry['resource']
                    if resource.get('resourceType') == resource_type:
                        resources.append(resource)
        
        return resources


class PostgreSQLJSONBQueries:
    """
    Utility class for PostgreSQL-specific JSONB queries
    Only works when using PostgreSQL as the database backend
    """
    
    @staticmethod
    def is_postgresql_available() -> bool:
        """Check if we're using PostgreSQL backend"""
        return 'postgresql' in settings.DATABASES['default']['ENGINE']
    
    @staticmethod
    def search_fhir_resources(table_name: str, jsonb_field: str, 
                            resource_type: str, search_criteria: Dict[str, Any]) -> List[Dict]:
        """
        Search FHIR resources using PostgreSQL JSONB operators
        
        Args:
            table_name: Database table containing JSONB field
            jsonb_field: Name of the JSONB field to search
            resource_type: Type of FHIR resource to search for
            search_criteria: Dictionary of search criteria
            
        Returns:
            List: Matching records from database
        """
        if not PostgreSQLJSONBQueries.is_postgresql_available():
            raise RuntimeError("PostgreSQL JSONB queries require PostgreSQL backend")
        
        # Example JSONB query - in real implementation, use Django ORM
        # This is just to demonstrate the concept
        sample_query = f"""
        SELECT * FROM {table_name} 
        WHERE {jsonb_field} -> 'entry' @> '[{{"resource": {{"resourceType": "{resource_type}"}}}}]'
        """
        
        # Note: In actual implementation, use parameterized queries and Django ORM
        # This is just for demonstration purposes
        return []
    
    @staticmethod
    def create_jsonb_indexes(table_name: str, jsonb_field: str):
        """
        Create PostgreSQL indexes for efficient JSONB querying
        
        Args:
            table_name: Database table name
            jsonb_field: JSONB field name
        """
        if not PostgreSQLJSONBQueries.is_postgresql_available():
            return
        
        # Example index creation - use Django migrations for actual implementation
        indexes = [
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_{jsonb_field}_gin ON {table_name} USING GIN ({jsonb_field});",
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_{jsonb_field}_resource_type ON {table_name} USING BTREE (({jsonb_field} -> 'entry' -> 0 -> 'resource' ->> 'resourceType'));"
        ]
        
        return indexes


def demonstrate_fhir_jsonb():
    """
    Demonstration function showing FHIR JSONB capabilities
    """
    print("🏥 FHIR JSONB Demonstration")
    print("=" * 50)
    
    # Sample FHIR resources
    patient_resource = {
        "resourceType": "Patient",
        "id": "patient-123",
        "name": [{"family": "Doe", "given": ["John"]}],
        "birthDate": "1980-01-01"
    }
    
    condition_resource = {
        "resourceType": "Condition",
        "id": "condition-456",
        "subject": {"reference": "Patient/patient-123"},
        "code": {
            "coding": [{
                "system": "http://snomed.info/sct",
                "code": "73211009",
                "display": "Diabetes mellitus"
            }]
        }
    }
    
    # Create FHIR bundle
    manager = FHIRJSONBManager()
    bundle = manager.create_fhir_bundle("patient-123", [patient_resource])
    
    print(f"📦 Created FHIR bundle with {bundle['total']} resources")
    
    # Add condition to bundle
    bundle = manager.add_resource_to_bundle(bundle, condition_resource, "document-789")
    print(f"📦 Updated bundle now has {bundle['total']} resources")
    
    # Extract resources by type
    patients = manager.get_resources_by_type(bundle, "Patient")
    conditions = manager.get_resources_by_type(bundle, "Condition")
    
    print(f"👤 Found {len(patients)} Patient resources")
    print(f"🩺 Found {len(conditions)} Condition resources")
    
    # Check PostgreSQL availability
    pg_utils = PostgreSQLJSONBQueries()
    if pg_utils.is_postgresql_available():
        print("✅ PostgreSQL JSONB capabilities available")
        print("🗃️  Advanced JSONB querying enabled")
    else:
        print("ℹ️  Using SQLite - basic JSONB simulation available")
        print("💡 Set DB_ENGINE=postgresql in .env for full JSONB features")
    
    return bundle


if __name__ == "__main__":
    # Run demonstration if called directly
    demonstrate_fhir_jsonb() 