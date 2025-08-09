"""
Django management command to test FHIR batch processing functionality.

This command creates test data and runs batch processing scenarios to validate
the implementation and performance characteristics.
"""

import time
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from apps.patients.models import Patient
from apps.documents.models import Document
from apps.fhir.services import FHIRMergeService
from apps.fhir.batch_processing import FHIRBatchProcessor, BatchMergeResult


class Command(BaseCommand):
    help = 'Test FHIR batch processing functionality with various scenarios'

    def add_arguments(self, parser):
        parser.add_argument(
            '--scenario',
            type=str,
            choices=['basic', 'relationships', 'performance', 'concurrent', 'all'],
            default='basic',
            help='Test scenario to run'
        )
        parser.add_argument(
            '--documents',
            type=int,
            default=5,
            help='Number of documents to process in batch'
        )
        parser.add_argument(
            '--concurrent',
            type=int,
            default=2,
            help='Maximum concurrent processing for performance tests'
        )
        parser.add_argument(
            '--cleanup',
            action='store_true',
            help='Clean up test data after running tests'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Enable verbose output'
        )

    def handle(self, *args, **options):
        """Main command handler."""
        self.verbosity = 2 if options['verbose'] else 1
        self.scenario = options['scenario']
        self.num_documents = options['documents']
        self.max_concurrent = options['concurrent']
        self.cleanup = options['cleanup']
        
        self.stdout.write(
            self.style.SUCCESS(f"Starting FHIR batch processing tests - Scenario: {self.scenario}")
        )
        
        try:
            # Setup test data
            self.setup_test_data()
            
            # Run selected scenarios
            if self.scenario == 'all':
                self.run_all_scenarios()
            else:
                self.run_scenario(self.scenario)
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Test failed: {str(e)}")
            )
            raise CommandError(f"Batch processing test failed: {str(e)}")
        finally:
            if self.cleanup:
                self.cleanup_test_data()
        
        self.stdout.write(
            self.style.SUCCESS("FHIR batch processing tests completed successfully")
        )

    def setup_test_data(self):
        """Create test data for batch processing tests."""
        self.stdout.write("Setting up test data...")
        
        # Create test user
        self.test_user, created = User.objects.get_or_create(
            username='batch_test_user',
            defaults={
                'email': 'batch_test@example.com',
                'first_name': 'Batch',
                'last_name': 'Tester'
            }
        )
        
        # Create test patient
        self.test_patient, created = Patient.objects.get_or_create(
            mrn='BATCH_TEST_001',
            defaults={
                'first_name': 'Batch',
                'last_name': 'TestPatient',
                'date_of_birth': '1990-01-01',
                'gender': 'M',
                'cumulative_fhir_json': {}
            }
        )
        
        # Create test documents
        self.test_documents = []
        self.extracted_data_list = []
        self.metadata_list = []
        
        base_date = timezone.now() - timedelta(days=1)
        
        for i in range(self.num_documents):
            # Create document
            document = Document.objects.create(
                patient=self.test_patient,
                filename=f'batch_test_doc_{i}.pdf',
                created_by=self.test_user,
                status='completed',
                uploaded_at=base_date + timedelta(hours=i),
                original_text=f'Test medical document {i+1} content for batch processing'
            )
            self.test_documents.append(document)
            
            # Create extracted data
            extracted_data = self._generate_test_extracted_data(i, document)
            self.extracted_data_list.append(extracted_data)
            
            # Create metadata
            metadata = self._generate_test_metadata(i, document)
            self.metadata_list.append(metadata)
        
        if self.verbosity >= 2:
            self.stdout.write(f"Created {len(self.test_documents)} test documents")

    def _generate_test_extracted_data(self, index: int, document: Document) -> Dict[str, Any]:
        """Generate test extracted data for a document."""
        document_types = ['lab_report', 'clinical_note', 'medication_list', 'discharge_summary']
        doc_type = document_types[index % len(document_types)]
        
        base_data = {
            'document_date': (timezone.now() - timedelta(days=1) + timedelta(hours=index)).isoformat(),
            'patient_name': f"{self.test_patient.first_name} {self.test_patient.last_name}",
            'provider': {'name': f'Dr. Provider{index % 3}', 'id': f'PROV{index % 3}'}
        }
        
        # Add type-specific data
        if doc_type == 'lab_report':
            base_data.update({
                'test_date': base_data['document_date'],  # Add required field
                'tests': [
                    {
                        'name': f'Test_{index}',
                        'value': 100 + index,
                        'unit': 'mg/dL',
                        'reference_range': '70-100'
                    }
                ]
            })
        elif doc_type == 'clinical_note':
            base_data.update({
                'note_date': base_data['document_date'],  # Add required field
                'diagnoses': [f'Diagnosis_{index}'],
                'assessment': f'Assessment for document {index}',
                'plan': f'Treatment plan for document {index}'
            })
        elif doc_type == 'medication_list':
            base_data.update({
                'list_date': base_data['document_date'],  # Add required field
                'medications': [
                    {
                        'name': f'Medication_{index}',
                        'dosage': f'{10 + index}mg',
                        'frequency': 'daily'
                    }
                ]
            })
        elif doc_type == 'discharge_summary':
            base_data.update({
                'discharge_date': base_data['document_date'],  # Add required field
                'discharge_diagnosis': [f'Discharge_Diagnosis_{index}'],
                'discharge_medications': [f'Discharge_Med_{index}'],
                'discharge_instructions': f'Instructions for document {index}'
            })
        
        # Add relationship data for some documents
        if index < 3:  # First 3 documents are related
            base_data['encounter'] = {'id': 'ENC_BATCH_TEST_123'}
        if index % 2 == 0:  # Even numbered documents share a visit
            base_data['visit'] = {'id': 'VIS_BATCH_TEST_456'}
        
        return base_data

    def _generate_test_metadata(self, index: int, document: Document) -> Dict[str, Any]:
        """Generate test metadata for a document."""
        document_types = ['lab_report', 'clinical_note', 'medication_list', 'discharge_summary']
        
        return {
            'document_id': document.id,
            'document_type': document_types[index % len(document_types)],
            'source': 'batch_test',
            'version': '1.0',
            'processed_at': timezone.now().isoformat(),
            'file_size': 1024 * (index + 1),  # Simulate different file sizes
            'provider_id': f'PROV{index % 3}'
        }

    def run_all_scenarios(self):
        """Run all test scenarios."""
        scenarios = ['basic', 'relationships', 'performance', 'concurrent']
        
        for scenario in scenarios:
            self.stdout.write(f"\n{'-' * 50}")
            self.stdout.write(f"Running scenario: {scenario}")
            self.stdout.write(f"{'-' * 50}")
            self.run_scenario(scenario)

    def run_scenario(self, scenario: str):
        """Run a specific test scenario."""
        if scenario == 'basic':
            self.test_basic_batch_processing()
        elif scenario == 'relationships':
            self.test_relationship_detection()
        elif scenario == 'performance':
            self.test_performance_characteristics()
        elif scenario == 'concurrent':
            self.test_concurrent_processing()

    def test_basic_batch_processing(self):
        """Test basic batch processing functionality."""
        self.stdout.write("Testing basic batch processing...")
        
        merge_service = FHIRMergeService(self.test_patient)
        
        # Test batch processing capabilities
        capabilities = merge_service.get_batch_processing_capabilities()
        self.stdout.write(f"Batch processing capabilities: {json.dumps(capabilities, indent=2)}")
        
        # Progress tracking
        progress_updates = []
        
        def progress_callback(processed, total, message):
            progress_updates.append(f"Progress: {processed}/{total} - {message}")
            if self.verbosity >= 2:
                self.stdout.write(f"  {progress_updates[-1]}")
        
        # Process batch
        start_time = time.time()
        
        result = merge_service.merge_document_batch(
            documents=self.test_documents,
            extracted_data_list=self.extracted_data_list,
            metadata_list=self.metadata_list,
            progress_callback=progress_callback,
            use_transactions=True,
            enable_relationship_detection=True,
            user=self.test_user
        )
        
        processing_time = time.time() - start_time
        
        # Report results
        self.stdout.write(f"\nBatch Processing Results:")
        self.stdout.write(f"  Total documents: {result.total_documents}")
        self.stdout.write(f"  Processed: {result.processed_documents}")
        self.stdout.write(f"  Successful: {result.successful_documents}")
        self.stdout.write(f"  Failed: {result.failed_documents}")
        self.stdout.write(f"  Success rate: {result.get_success_rate():.1f}%")
        self.stdout.write(f"  Processing time: {processing_time:.2f}s")
        self.stdout.write(f"  Documents per second: {result.documents_per_second:.2f}")
        self.stdout.write(f"  Progress updates: {len(progress_updates)}")
        
        if result.relationships_detected:
            self.stdout.write(f"  Relationships detected: {len(result.relationships_detected)}")
        
        # Validate results
        if result.failed_documents > 0:
            self.stdout.write(self.style.WARNING(f"Some documents failed processing"))
            for doc_id, error in result.document_errors.items():
                self.stdout.write(f"    Document {doc_id}: {error}")
        
        if result.get_success_rate() >= 80:
            self.stdout.write(self.style.SUCCESS("✓ Basic batch processing test passed"))
        else:
            raise CommandError(f"Basic batch processing failed with {result.get_success_rate():.1f}% success rate")

    def test_relationship_detection(self):
        """Test document relationship detection."""
        self.stdout.write("Testing relationship detection...")
        
        batch_processor = FHIRBatchProcessor(self.test_patient)
        
        # Prepare batch documents
        batch_documents = batch_processor._prepare_batch_documents(
            self.test_documents,
            self.extracted_data_list,
            self.metadata_list
        )
        
        # Detect relationships
        relationships = batch_processor.relationship_detector.detect_relationships(batch_documents)
        
        self.stdout.write(f"Detected {len(relationships)} relationships:")
        
        for i, relationship in enumerate(relationships):
            self.stdout.write(f"  Relationship {i + 1}: {relationship} (confidence: {relationship.confidence_score:.2f})")
        
        # Validate relationship detection
        if len(relationships) > 0:
            self.stdout.write(self.style.SUCCESS("✓ Relationship detection test passed"))
        else:
            self.stdout.write(self.style.WARNING("⚠ No relationships detected - this may be expected"))

    def test_performance_characteristics(self):
        """Test performance characteristics of batch processing."""
        self.stdout.write("Testing performance characteristics...")
        
        batch_processor = FHIRBatchProcessor(self.test_patient)
        
        # Test different concurrency levels
        concurrency_levels = [1, 2, 3]
        results = {}
        
        for max_concurrent in concurrency_levels:
            self.stdout.write(f"  Testing with max_concurrent={max_concurrent}")
            
            start_time = time.time()
            
            result = batch_processor.merge_document_batch(
                documents=self.test_documents,
                extracted_data_list=self.extracted_data_list,
                metadata_list=self.metadata_list,
                use_transactions=False,  # Disable for performance testing
                enable_relationship_detection=False,  # Disable for pure processing speed
                max_concurrent=max_concurrent
            )
            
            processing_time = time.time() - start_time
            
            results[max_concurrent] = {
                'processing_time': processing_time,
                'documents_per_second': len(self.test_documents) / processing_time,
                'success_rate': result.get_success_rate()
            }
            
            self.stdout.write(f"    Time: {processing_time:.2f}s, Rate: {results[max_concurrent]['documents_per_second']:.2f} docs/sec")
        
        # Performance analysis
        self.stdout.write(f"\nPerformance Analysis:")
        best_performance = max(results.values(), key=lambda x: x['documents_per_second'])
        worst_performance = min(results.values(), key=lambda x: x['documents_per_second'])
        
        self.stdout.write(f"  Best rate: {best_performance['documents_per_second']:.2f} docs/sec")
        self.stdout.write(f"  Worst rate: {worst_performance['documents_per_second']:.2f} docs/sec")
        
        # Check for reasonable performance
        if best_performance['documents_per_second'] > 0.5:  # At least 0.5 docs/sec
            self.stdout.write(self.style.SUCCESS("✓ Performance test passed"))
        else:
            self.stdout.write(self.style.WARNING("⚠ Performance may be suboptimal"))

    def test_concurrent_processing(self):
        """Test concurrent processing behavior."""
        self.stdout.write("Testing concurrent processing...")
        
        batch_processor = FHIRBatchProcessor(self.test_patient)
        batch_processor.max_concurrent_documents = self.max_concurrent
        
        # Test with progress tracking to verify concurrent behavior
        progress_updates = []
        start_times = []
        
        def progress_callback(processed, total, message):
            current_time = time.time()
            start_times.append(current_time)
            progress_updates.append({
                'processed': processed,
                'total': total,
                'message': message,
                'timestamp': current_time
            })
            if self.verbosity >= 2:
                self.stdout.write(f"  {message}")
        
        start_time = time.time()
        
        result = batch_processor.merge_document_batch(
            documents=self.test_documents,
            extracted_data_list=self.extracted_data_list,
            metadata_list=self.metadata_list,
            progress_callback=progress_callback,
            use_transactions=False,
            max_concurrent=self.max_concurrent
        )
        
        total_time = time.time() - start_time
        
        # Analyze timing patterns
        if len(start_times) >= 2:
            time_diffs = [start_times[i] - start_times[i-1] for i in range(1, len(start_times))]
            avg_interval = sum(time_diffs) / len(time_diffs)
            
            self.stdout.write(f"  Total processing time: {total_time:.2f}s")
            self.stdout.write(f"  Average progress interval: {avg_interval:.2f}s")
            self.stdout.write(f"  Success rate: {result.get_success_rate():.1f}%")
            
            # Concurrent processing should show some parallelism
            if avg_interval < total_time / len(self.test_documents):
                self.stdout.write(self.style.SUCCESS("✓ Concurrent processing appears to be working"))
            else:
                self.stdout.write(self.style.WARNING("⚠ Concurrent processing may not be effective"))
        else:
            self.stdout.write(self.style.WARNING("⚠ Insufficient progress data to analyze concurrency"))

    def cleanup_test_data(self):
        """Clean up test data created during tests."""
        self.stdout.write("Cleaning up test data...")
        
        # Delete test documents
        for document in self.test_documents:
            document.delete()
        
        # Reset patient FHIR data
        self.test_patient.cumulative_fhir_json = {}
        self.test_patient.save()
        
        # Optionally delete test patient and user
        # (commented out to preserve for multiple test runs)
        # self.test_patient.delete()
        # self.test_user.delete()
        
        self.stdout.write("Test data cleanup completed")
