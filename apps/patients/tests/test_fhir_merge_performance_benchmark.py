"""
Performance benchmark tests for FHIR merge operations (Task 41.20).

Uses pytest-benchmark to provide detailed performance metrics for:
- update_fhir_resources (merge) operations
- rollback_document_merge operations
- Performance scaling with various resource counts

These tests establish performance baselines and ensure the 500ms target
is maintained as the codebase evolves.

Run with: pytest apps/patients/tests/test_fhir_merge_performance_benchmark.py --benchmark-only
"""
import pytest
from django.test import TestCase
from apps.patients.models import Patient


@pytest.mark.django_db
class TestFHIRMergePerformanceBenchmarks:
    """
    Benchmark tests for FHIR merge operations using pytest-benchmark.
    
    Benchmark metrics measured:
    - Min/Max/Mean execution time
    - Standard deviation
    - Iterations per second
    - Memory usage (if available)
    """
    
    @pytest.fixture
    def patient(self, db):
        """Create a test patient for benchmarks"""
        return Patient.objects.create(
            first_name='Benchmark',
            last_name='Patient',
            date_of_birth='1980-01-01',
            mrn='BENCH-001'
        )
    
    def test_merge_small_dataset_10_resources(self, benchmark, patient):
        """
        Benchmark merging 10 resources (small dataset).
        Expected: <50ms average, well under 500ms target.
        """
        resources = [
            {
                'resourceType': 'Condition',
                'id': f'condition-{i}',
                'code': {'text': f'Test Condition {i}'}
            }
            for i in range(10)
        ]
        
        # Benchmark the merge operation
        result = benchmark(patient.add_fhir_resources, resources, document_id=1)
        
        # Verify operation succeeded
        patient.refresh_from_db()
        bundle = patient.encrypted_fhir_bundle
        assert len(bundle['entry']) == 10
    
    def test_merge_medium_dataset_50_resources(self, benchmark, patient):
        """
        Benchmark merging 50 resources (medium dataset).
        Expected: <200ms average, well under 500ms target.
        """
        resources = []
        resource_types = ['Condition', 'Observation', 'MedicationStatement', 'Procedure', 'AllergyIntolerance']
        
        for i in range(50):
            resource_type = resource_types[i % len(resource_types)]
            resources.append({
                'resourceType': resource_type,
                'id': f'{resource_type.lower()}-{i}',
                'code': {'text': f'Test {resource_type} {i}'}
            })
        
        # Benchmark the merge operation
        result = benchmark(patient.add_fhir_resources, resources, document_id=2)
        
        # Verify operation succeeded
        patient.refresh_from_db()
        bundle = patient.encrypted_fhir_bundle
        assert len(bundle['entry']) == 50
    
    def test_merge_large_dataset_100_resources(self, benchmark, patient):
        """
        Benchmark merging 100 resources (large dataset).
        Expected: <500ms average, meeting our performance target.
        """
        resources = []
        resource_types = ['Condition', 'Observation', 'MedicationStatement', 'Procedure', 'AllergyIntolerance']
        
        for i in range(100):
            resource_type = resource_types[i % len(resource_types)]
            resources.append({
                'resourceType': resource_type,
                'id': f'{resource_type.lower()}-{i}',
                'code': {'text': f'Test {resource_type} {i}'},
                'status': 'active' if i % 2 == 0 else 'inactive'
            })
        
        # Benchmark the merge operation
        result = benchmark(patient.add_fhir_resources, resources, document_id=3)
        
        # Verify operation succeeded
        patient.refresh_from_db()
        bundle = patient.encrypted_fhir_bundle
        assert len(bundle['entry']) == 100
    
    def test_merge_idempotent_update_performance(self, benchmark, patient):
        """
        Benchmark idempotent merge (updating existing resources).
        Expected: Similar performance to initial merge, <100ms for 10 resources.
        """
        resources = [
            {
                'resourceType': 'Condition',
                'id': 'condition-diabetes',
                'code': {'text': 'Type 2 Diabetes'}
            }
        ]
        
        # Add resources initially
        patient.add_fhir_resources(resources, document_id=1)
        patient.refresh_from_db()
        
        # Benchmark the idempotent update
        resources_updated = [
            {
                'resourceType': 'Condition',
                'id': 'condition-diabetes',
                'code': {'text': 'Type 2 Diabetes'},
                'clinicalStatus': 'active'
            }
        ]
        
        result = benchmark(patient.add_fhir_resources, resources_updated, document_id=1)
        
        # Verify update succeeded (should still have 1 resource, not 2)
        patient.refresh_from_db()
        bundle = patient.encrypted_fhir_bundle
        assert len(bundle['entry']) == 1
    
    def test_rollback_small_dataset_10_resources(self, benchmark, patient):
        """
        Benchmark rollback of 10 resources (small dataset).
        Expected: <50ms average, very fast operation.
        """
        resources = [
            {'resourceType': 'Condition', 'code': {'text': f'Condition {i}'}}
            for i in range(10)
        ]
        
        def setup():
            """Setup function to add resources before each benchmark iteration"""
            patient.add_fhir_resources(resources, document_id=1)
            patient.refresh_from_db()
        
        # Benchmark the rollback operation with setup
        result = benchmark.pedantic(patient.rollback_document_merge, args=(1,), setup=setup, rounds=50)
        
        # Verify rollback succeeded in at least one iteration
        assert result == 10  # Should have removed 10 resources
    
    def test_rollback_medium_dataset_50_resources(self, benchmark, patient):
        """
        Benchmark rollback of 50 resources (medium dataset).
        Expected: <200ms average, well under 500ms target.
        """
        resources = [
            {'resourceType': 'Observation', 'code': {'text': f'Observation {i}'}}
            for i in range(50)
        ]
        
        def setup():
            """Setup function to add resources before each benchmark iteration"""
            patient.add_fhir_resources(resources, document_id=2)
            patient.refresh_from_db()
        
        # Benchmark the rollback operation with setup
        result = benchmark.pedantic(patient.rollback_document_merge, args=(2,), setup=setup, rounds=50)
        
        # Verify rollback succeeded
        assert result == 50
    
    def test_rollback_large_dataset_100_resources(self, benchmark, patient):
        """
        Benchmark rollback of 100 resources (large dataset).
        Expected: <500ms average, meeting our performance target.
        """
        resources = []
        resource_types = ['Condition', 'Observation', 'MedicationStatement', 'Procedure', 'AllergyIntolerance']
        
        for i in range(100):
            resource_type = resource_types[i % len(resource_types)]
            resources.append({
                'resourceType': resource_type,
                'code': {'text': f'{resource_type} {i}'}
            })
        
        def setup():
            """Setup function to add resources before each benchmark iteration"""
            patient.add_fhir_resources(resources, document_id=3)
            patient.refresh_from_db()
        
        # Benchmark the rollback operation with setup
        result = benchmark.pedantic(patient.rollback_document_merge, args=(3,), setup=setup, rounds=50)
        
        # Verify rollback succeeded
        assert result == 100
    
    def test_rollback_selective_from_multi_document_bundle(self, benchmark, patient):
        """
        Benchmark selective rollback from a bundle with multiple documents.
        Tests rollback performance when filtering is needed (100 resources from doc 2, 
        200 total resources in bundle).
        Expected: <500ms for selective filtering and removal.
        """
        def setup():
            """Setup function to add resources from 3 documents before each iteration"""
            for doc_id in range(1, 4):
                resources = [
                    {'resourceType': 'Observation', 'code': {'text': f'Doc {doc_id} Obs {i}'}}
                    for i in range(100)
                ]
                patient.add_fhir_resources(resources, document_id=doc_id)
            patient.refresh_from_db()
        
        # Benchmark selective rollback of middle document
        result = benchmark.pedantic(patient.rollback_document_merge, args=(2,), setup=setup, rounds=20)
        
        # Verify selective rollback succeeded
        assert result == 100
    
    def test_merge_with_complex_nested_resources(self, benchmark, patient):
        """
        Benchmark merge with complex, deeply nested FHIR resources.
        Tests performance with realistic resource complexity.
        Expected: <200ms for 20 complex resources.
        """
        resources = []
        
        for i in range(20):
            resources.append({
                'resourceType': 'Observation',
                'id': f'obs-{i}',
                'status': 'final',
                'code': {
                    'coding': [
                        {
                            'system': 'http://loinc.org',
                            'code': '15074-8',
                            'display': 'Glucose [Moles/volume] in Blood'
                        }
                    ],
                    'text': 'Blood Glucose'
                },
                'subject': {'reference': f'Patient/{patient.mrn}'},
                'effectiveDateTime': '2024-01-01T10:30:00Z',
                'valueQuantity': {
                    'value': 95 + i,
                    'unit': 'mg/dL',
                    'system': 'http://unitsofmeasure.org',
                    'code': 'mg/dL'
                },
                'referenceRange': [
                    {
                        'low': {'value': 70, 'unit': 'mg/dL'},
                        'high': {'value': 100, 'unit': 'mg/dL'},
                        'type': {
                            'coding': [{
                                'system': 'http://terminology.hl7.org/CodeSystem/referencerange-meaning',
                                'code': 'normal'
                            }]
                        }
                    }
                ]
            })
        
        # Benchmark merge with complex resources
        result = benchmark(patient.add_fhir_resources, resources, document_id=4)
        
        # Verify operation succeeded
        patient.refresh_from_db()
        bundle = patient.encrypted_fhir_bundle
        assert len(bundle['entry']) == 20


# Performance validation tests (not benchmarks, but verify benchmark results meet targets)
@pytest.mark.django_db
class TestPerformanceTargetValidation:
    """
    Tests that validate performance targets are met.
    These run with benchmark data to ensure targets are achieved.
    """
    
    @pytest.fixture
    def patient(self, db):
        """Create a test patient"""
        return Patient.objects.create(
            first_name='Target',
            last_name='Validation',
            date_of_birth='1980-01-01',
            mrn='TARGET-001'
        )
    
    def test_merge_100_resources_meets_500ms_target(self, patient, benchmark):
        """
        Critical performance test: 100 resources must merge in <500ms.
        This is our performance SLA.
        """
        resources = [
            {'resourceType': 'Condition', 'code': {'text': f'Condition {i}'}}
            for i in range(100)
        ]
        
        stats = benchmark(patient.add_fhir_resources, resources, document_id=1)
        
        # Check that mean time is under 500ms
        # pytest-benchmark stores timing in seconds
        mean_ms = benchmark.stats.stats.mean * 1000
        
        assert mean_ms < 500, f"Mean merge time {mean_ms:.2f}ms exceeds 500ms target"
        
        # Also verify max time doesn't exceed target significantly
        max_ms = benchmark.stats.stats.max * 1000
        assert max_ms < 1000, f"Max merge time {max_ms:.2f}ms too slow (should be <1000ms)"
    
    def test_rollback_100_resources_meets_500ms_target(self, patient, benchmark):
        """
        Critical performance test: Rolling back 100 resources must complete in <500ms.
        This is our performance SLA.
        """
        resources = [
            {'resourceType': 'Condition', 'code': {'text': f'Condition {i}'}}
            for i in range(100)
        ]
        
        def setup():
            """Setup function to add resources before each benchmark iteration"""
            patient.add_fhir_resources(resources, document_id=1)
            patient.refresh_from_db()
        
        stats = benchmark.pedantic(patient.rollback_document_merge, args=(1,), setup=setup, rounds=50)
        
        # Check that mean time is under 500ms
        mean_ms = benchmark.stats.stats.mean * 1000
        
        assert mean_ms < 500, f"Mean rollback time {mean_ms:.2f}ms exceeds 500ms target"
        
        # Also verify max time doesn't exceed target significantly
        max_ms = benchmark.stats.stats.max * 1000
        assert max_ms < 1000, f"Max rollback time {max_ms:.2f}ms too slow (should be <1000ms)"

