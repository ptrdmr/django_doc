"""
Tests for FHIR Batch Processing Module

Comprehensive test suite for batch processing of multiple related documents
with relationship detection, transaction management, and performance validation.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import time
from typing import List, Dict, Any

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from apps.patients.models import Patient
from apps.documents.models import Document
from apps.fhir.batch_processing import (
    DocumentRelationship,
    BatchDocument,
    BatchMergeResult,
    DocumentRelationshipDetector,
    FHIRBatchProcessor
)
from apps.fhir.services import FHIRMergeService, MergeResult


class DocumentRelationshipTest(TestCase):
    """Test DocumentRelationship data structure."""
    
    def test_document_relationship_creation(self):
        """Test creating document relationships with different attributes."""
        # Test encounter-based relationship
        rel1 = DocumentRelationship(
            encounter_id="ENC123",
            confidence_score=0.9
        )
        self.assertEqual(rel1.encounter_id, "ENC123")
        self.assertEqual(rel1.confidence_score, 0.9)
        self.assertIn("encounter:ENC123", str(rel1))
        
        # Test visit-based relationship
        rel2 = DocumentRelationship(
            visit_id="VIS456",
            confidence_score=0.8
        )
        self.assertEqual(rel2.visit_id, "VIS456")
        self.assertIn("visit:VIS456", str(rel2))
        
        # Test date range relationship
        start_date = datetime(2023, 1, 1, 10, 0)
        end_date = datetime(2023, 1, 1, 14, 0)
        rel3 = DocumentRelationship(
            date_range=(start_date, end_date),
            confidence_score=0.6
        )
        self.assertEqual(rel3.date_range, (start_date, end_date))
        self.assertIn("dates:2023-01-01-2023-01-01", str(rel3))
    
    def test_empty_relationship_string(self):
        """Test string representation of empty relationship."""
        empty_rel = DocumentRelationship()
        self.assertEqual(str(empty_rel), "unrelated")


class BatchDocumentTest(TestCase):
    """Test BatchDocument wrapper class."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='Test',
            last_name='Patient',
            date_of_birth='1990-01-01',
            gender='M'
        )
        self.document = Document.objects.create(
            patient=self.patient,
            file='test_doc.pdf',
            uploaded_by=self.user,
            status='completed'
        )
    
    def test_batch_document_creation(self):
        """Test creating BatchDocument with all fields."""
        extracted_data = {'test_data': 'value'}
        metadata = {'document_type': 'lab_report', 'provider': 'Dr. Smith'}
        relationship = DocumentRelationship(encounter_id="ENC123")
        
        batch_doc = BatchDocument(
            document=self.document,
            extracted_data=extracted_data,
            metadata=metadata,
            relationship=relationship,
            processing_order=1,
            chunk_size=100
        )
        
        self.assertEqual(batch_doc.document, self.document)
        self.assertEqual(batch_doc.extracted_data, extracted_data)
        self.assertEqual(batch_doc.metadata, metadata)
        self.assertEqual(batch_doc.relationship, relationship)
        self.assertEqual(batch_doc.processing_order, 1)
        self.assertEqual(batch_doc.chunk_size, 100)
        self.assertEqual(batch_doc.document_id, self.document.id)
        self.assertEqual(batch_doc.document_type, 'lab_report')
    
    def test_batch_document_defaults(self):
        """Test BatchDocument with default values."""
        batch_doc = BatchDocument(
            document=self.document,
            extracted_data={'data': 'test'},
            metadata={'document_type': 'unknown'}
        )
        
        self.assertIsNone(batch_doc.relationship)
        self.assertEqual(batch_doc.processing_order, 0)
        self.assertIsNone(batch_doc.chunk_size)
        self.assertEqual(batch_doc.document_type, 'unknown')


class BatchMergeResultTest(TestCase):
    """Test BatchMergeResult tracking class."""
    
    def test_batch_merge_result_initialization(self):
        """Test initial state of BatchMergeResult."""
        result = BatchMergeResult()
        
        # Check initial values
        self.assertIsNotNone(result.batch_id)
        self.assertEqual(result.total_documents, 0)
        self.assertEqual(result.processed_documents, 0)
        self.assertEqual(result.successful_documents, 0)
        self.assertEqual(result.failed_documents, 0)
        self.assertEqual(len(result.document_results), 0)
        self.assertEqual(len(result.document_errors), 0)
        self.assertEqual(len(result.relationships_detected), 0)
        self.assertEqual(len(result.cross_document_conflicts), 0)
        self.assertFalse(result.rollback_performed)
        self.assertFalse(result.partial_success)
    
    def test_add_document_result_success(self):
        """Test adding successful document result."""
        result = BatchMergeResult()
        merge_result = MergeResult()
        merge_result.success = True
        
        result.add_document_result(123, merge_result)
        
        self.assertEqual(result.processed_documents, 1)
        self.assertEqual(result.successful_documents, 1)
        self.assertEqual(result.failed_documents, 0)
        self.assertIn(123, result.document_results)
        self.assertEqual(result.document_results[123], merge_result)
    
    def test_add_document_result_failure(self):
        """Test adding failed document result."""
        result = BatchMergeResult()
        merge_result = MergeResult()
        merge_result.success = False
        
        result.add_document_result(456, merge_result)
        
        self.assertEqual(result.processed_documents, 1)
        self.assertEqual(result.successful_documents, 0)
        self.assertEqual(result.failed_documents, 1)
    
    def test_add_document_error(self):
        """Test adding document error."""
        result = BatchMergeResult()
        
        result.add_document_error(789, "Processing failed")
        
        self.assertEqual(result.processed_documents, 1)
        self.assertEqual(result.successful_documents, 0)
        self.assertEqual(result.failed_documents, 1)
        self.assertIn(789, result.document_errors)
        self.assertEqual(result.document_errors[789], "Processing failed")
    
    def test_finalize_metrics_calculation(self):
        """Test finalize method calculates metrics correctly."""
        result = BatchMergeResult()
        result.total_documents = 10
        result.processing_start_time = timezone.now() - timedelta(seconds=30)
        
        # Add some results
        success_result = MergeResult()
        success_result.success = True
        result.add_document_result(1, success_result)
        result.add_document_result(2, success_result)
        
        fail_result = MergeResult()
        fail_result.success = False
        result.add_document_result(3, fail_result)
        
        result.finalize()
        
        # Check calculated metrics
        self.assertIsNotNone(result.processing_end_time)
        self.assertGreater(result.total_processing_time, 0)
        self.assertGreater(result.documents_per_second, 0)
        self.assertGreater(result.average_document_processing_time, 0)
        self.assertTrue(result.partial_success)  # 2 success, 1 failure out of 10 total
    
    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        result = BatchMergeResult()
        
        # Test 0% success rate
        self.assertEqual(result.get_success_rate(), 0.0)
        
        # Add results for 80% success rate
        success_result = MergeResult()
        success_result.success = True
        for i in range(4):
            result.add_document_result(i, success_result)
        
        fail_result = MergeResult()
        fail_result.success = False
        result.add_document_result(4, fail_result)
        
        self.assertEqual(result.get_success_rate(), 80.0)
    
    def test_summary_generation(self):
        """Test human-readable summary generation."""
        result = BatchMergeResult()
        result.total_documents = 5
        result.successful_documents = 4
        result.failed_documents = 1
        result.total_processing_time = 10.5
        result.documents_per_second = 0.48
        
        # Test different scenarios
        summary = result.get_summary()
        self.assertIn("partially successful", summary)
        self.assertIn("4/5", summary)
        self.assertIn("10.50s", summary)
        
        # Test rollback scenario
        result.rollback_performed = True
        rollback_summary = result.get_summary()
        self.assertIn("rolled back", rollback_summary)
        
        # Test complete failure
        result.rollback_performed = False
        result.successful_documents = 0
        result.failed_documents = 5
        failure_summary = result.get_summary()
        self.assertIn("failed", failure_summary)


class DocumentRelationshipDetectorTest(TestCase):
    """Test DocumentRelationshipDetector functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.detector = DocumentRelationshipDetector()
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='Test',
            last_name='Patient',
            date_of_birth='1990-01-01',
            gender='M'
        )
    
    def _create_test_document(self, doc_id: int, extracted_data: Dict[str, Any], metadata: Dict[str, Any]) -> BatchDocument:
        """Helper to create test BatchDocument."""
        document = Mock()
        document.id = doc_id
        document.uploaded_at = datetime.now()
        
        return BatchDocument(
            document=document,
            extracted_data=extracted_data,
            metadata=metadata
        )
    
    def test_encounter_grouping(self):
        """Test grouping documents by encounter ID."""
        # Create documents with same encounter
        doc1 = self._create_test_document(1, {'encounter': {'id': 'ENC123'}}, {})
        doc2 = self._create_test_document(2, {'encounter': {'id': 'ENC123'}}, {})
        doc3 = self._create_test_document(3, {'encounter': {'id': 'ENC456'}}, {})
        
        groups = self.detector._group_by_encounter([doc1, doc2, doc3])
        
        self.assertEqual(len(groups), 2)
        self.assertIn('ENC123', groups)
        self.assertIn('ENC456', groups)
        self.assertEqual(len(groups['ENC123']), 2)
        self.assertEqual(len(groups['ENC456']), 1)
    
    def test_visit_grouping(self):
        """Test grouping documents by visit ID."""
        # Create documents with visit IDs in metadata
        doc1 = self._create_test_document(1, {}, {'visit_id': 'VIS789'})
        doc2 = self._create_test_document(2, {}, {'visit_id': 'VIS789'})
        doc3 = self._create_test_document(3, {}, {'visit_id': 'VIS101'})
        
        groups = self.detector._group_by_visit([doc1, doc2, doc3])
        
        self.assertEqual(len(groups), 2)
        self.assertIn('VIS789', groups)
        self.assertIn('VIS101', groups)
        self.assertEqual(len(groups['VIS789']), 2)
    
    def test_date_proximity_grouping(self):
        """Test grouping documents by date proximity."""
        base_time = datetime.now()
        
        # Create documents with dates within 24 hours
        doc1 = self._create_test_document(1, {'document_date': base_time.isoformat()}, {})
        doc2 = self._create_test_document(2, {'document_date': (base_time + timedelta(hours=12)).isoformat()}, {})
        doc3 = self._create_test_document(3, {'document_date': (base_time + timedelta(days=2)).isoformat()}, {})
        
        groups = self.detector._group_by_date_proximity([doc1, doc2, doc3])
        
        # Should have 2 groups - one for doc1&doc2 (within 24h), one for doc3
        self.assertEqual(len(groups), 2)
        
        # Find group with 2 documents
        two_doc_group = None
        one_doc_group = None
        for group_docs in groups.values():
            if len(group_docs) == 2:
                two_doc_group = group_docs
            elif len(group_docs) == 1:
                one_doc_group = group_docs
        
        self.assertIsNotNone(two_doc_group)
        self.assertIsNotNone(one_doc_group)
    
    def test_provider_grouping(self):
        """Test grouping documents by provider."""
        doc1 = self._create_test_document(1, {'provider': {'id': 'PROV123'}}, {})
        doc2 = self._create_test_document(2, {'provider': {'id': 'PROV123'}}, {})
        doc3 = self._create_test_document(3, {'provider': {'id': 'PROV456'}}, {})
        
        groups = self.detector._group_by_provider([doc1, doc2, doc3])
        
        self.assertEqual(len(groups), 2)
        self.assertIn('PROV123', groups)
        self.assertIn('PROV456', groups)
        self.assertEqual(len(groups['PROV123']), 2)
    
    def test_document_type_grouping(self):
        """Test grouping documents by document type."""
        doc1 = self._create_test_document(1, {}, {'document_type': 'lab_report'})
        doc2 = self._create_test_document(2, {}, {'document_type': 'lab_report'})
        doc3 = self._create_test_document(3, {}, {'document_type': 'clinical_note'})
        
        groups = self.detector._group_by_document_type([doc1, doc2, doc3])
        
        self.assertEqual(len(groups), 2)
        self.assertIn('lab_report', groups)
        self.assertIn('clinical_note', groups)
        self.assertEqual(len(groups['lab_report']), 2)
    
    def test_relationship_detection_integration(self):
        """Test full relationship detection workflow."""
        # Create documents with multiple relationship types
        doc1 = self._create_test_document(
            1, 
            {'encounter': {'id': 'ENC123'}, 'provider': {'id': 'PROV123'}},
            {'document_type': 'lab_report'}
        )
        doc2 = self._create_test_document(
            2,
            {'encounter': {'id': 'ENC123'}, 'provider': {'id': 'PROV123'}}, 
            {'document_type': 'lab_report'}
        )
        doc3 = self._create_test_document(
            3,
            {'encounter': {'id': 'ENC456'}},
            {'document_type': 'clinical_note'}
        )
        
        relationships = self.detector.detect_relationships([doc1, doc2, doc3])
        
        # Should detect multiple relationships
        self.assertGreater(len(relationships), 0)
        
        # Check for encounter relationship
        encounter_rels = [r for r in relationships if r.encounter_id == 'ENC123']
        self.assertGreater(len(encounter_rels), 0)
        
        # Check for document type relationships
        lab_type_rels = [r for r in relationships if r.document_type_group == 'lab_report']
        self.assertGreater(len(lab_type_rels), 0)


class FHIRBatchProcessorTest(TestCase):
    """Test FHIRBatchProcessor functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='Test',
            last_name='Patient', 
            date_of_birth='1990-01-01',
            gender='M',
            cumulative_fhir_json={}
        )
        
        # Create test documents
        self.documents = []
        for i in range(3):
            doc = Document.objects.create(
                patient=self.patient,
                file=f'test_doc_{i}.pdf',
                uploaded_by=self.user,
                status='completed'
            )
            self.documents.append(doc)
        
        # Create test data
        self.extracted_data_list = [
            {'test_data': f'document_{i}', 'encounter': {'id': 'ENC123'}}
            for i in range(3)
        ]
        self.metadata_list = [
            {'document_type': 'lab_report', 'document_id': doc.id}
            for doc in self.documents
        ]
    
    def test_batch_processor_initialization(self):
        """Test FHIRBatchProcessor initialization."""
        processor = FHIRBatchProcessor(self.patient, 'test_profile')
        
        self.assertEqual(processor.patient, self.patient)
        self.assertIsNotNone(processor.merge_service)
        self.assertIsNotNone(processor.relationship_detector)
        self.assertIsNotNone(processor.transaction_manager)
        self.assertIsInstance(processor.max_concurrent_documents, int)
        self.assertIsInstance(processor.memory_limit_mb, int)
        self.assertIsInstance(processor.chunk_size, int)
    
    @patch('apps.fhir.batch_processing.FHIRBatchProcessor._process_single_document')
    def test_batch_processing_validation(self, mock_process):
        """Test input validation for batch processing."""
        processor = FHIRBatchProcessor(self.patient)
        
        # Test mismatched input lengths
        with self.assertRaises(ValueError):
            processor.merge_document_batch(
                documents=self.documents[:2],  # 2 documents
                extracted_data_list=self.extracted_data_list,  # 3 data items
                metadata_list=self.metadata_list  # 3 metadata items
            )
    
    @patch('apps.fhir.batch_processing.FHIRBatchProcessor._process_single_document')
    def test_batch_processing_success(self, mock_process):
        """Test successful batch processing."""
        processor = FHIRBatchProcessor(self.patient)
        
        # Mock successful processing
        mock_result = MergeResult()
        mock_result.success = True
        mock_process.return_value = mock_result
        
        # Process batch
        result = processor.merge_document_batch(
            documents=self.documents,
            extracted_data_list=self.extracted_data_list,
            metadata_list=self.metadata_list,
            use_transactions=False  # Disable transactions for simpler testing
        )
        
        # Verify results
        self.assertEqual(result.total_documents, 3)
        self.assertEqual(result.processed_documents, 3)
        self.assertEqual(result.successful_documents, 3)
        self.assertEqual(result.failed_documents, 0)
        self.assertEqual(result.get_success_rate(), 100.0)
        self.assertFalse(result.partial_success)
    
    @patch('apps.fhir.batch_processing.FHIRBatchProcessor._process_single_document')
    def test_batch_processing_partial_failure(self, mock_process):
        """Test batch processing with partial failures."""
        processor = FHIRBatchProcessor(self.patient)
        
        # Mock mixed results
        def side_effect(batch_doc):
            result = MergeResult()
            # Fail on second document
            if batch_doc.document_id == self.documents[1].id:
                result.success = False
            else:
                result.success = True
            return result
        
        mock_process.side_effect = side_effect
        
        # Process batch
        result = processor.merge_document_batch(
            documents=self.documents,
            extracted_data_list=self.extracted_data_list,
            metadata_list=self.metadata_list,
            use_transactions=False
        )
        
        # Verify results
        self.assertEqual(result.total_documents, 3)
        self.assertEqual(result.processed_documents, 3)
        self.assertEqual(result.successful_documents, 2)
        self.assertEqual(result.failed_documents, 1)
        self.assertEqual(result.get_success_rate(), 66.7)  # 2/3 = 66.7%
        self.assertTrue(result.partial_success)
    
    @patch('apps.fhir.batch_processing.FHIRBatchProcessor._process_single_document')
    def test_progress_callback(self, mock_process):
        """Test progress callback functionality."""
        processor = FHIRBatchProcessor(self.patient)
        
        # Mock successful processing
        mock_result = MergeResult()
        mock_result.success = True
        mock_process.return_value = mock_result
        
        # Track progress calls
        progress_calls = []
        
        def progress_callback(processed, total, message):
            progress_calls.append((processed, total, message))
        
        # Process batch with progress callback
        result = processor.merge_document_batch(
            documents=self.documents,
            extracted_data_list=self.extracted_data_list,
            metadata_list=self.metadata_list,
            progress_callback=progress_callback,
            use_transactions=False
        )
        
        # Verify progress was tracked
        self.assertEqual(len(progress_calls), 3)  # One call per document
        
        # Check progress values
        for i, (processed, total, message) in enumerate(progress_calls):
            self.assertEqual(processed, i + 1)
            self.assertEqual(total, 3)
            self.assertIn("Processed document", message)
    
    def test_processing_order_optimization(self):
        """Test document processing order optimization."""
        processor = FHIRBatchProcessor(self.patient)
        
        # Create batch documents with different relationships
        batch_docs = []
        for i, doc in enumerate(self.documents):
            batch_doc = BatchDocument(
                document=doc,
                extracted_data=self.extracted_data_list[i],
                metadata=self.metadata_list[i],
                processing_order=i
            )
            batch_docs.append(batch_doc)
        
        # Create relationships (documents 0 and 1 related by encounter)
        relationships = [
            DocumentRelationship(encounter_id='ENC123', confidence_score=0.9)
        ]
        
        # Optimize processing order
        optimized_docs = processor._optimize_processing_order(batch_docs, relationships)
        
        self.assertEqual(len(optimized_docs), 3)
        # Processing order should be updated
        for i, doc in enumerate(optimized_docs):
            self.assertEqual(doc.processing_order, i)
    
    def test_memory_management_chunking(self):
        """Test memory management with document chunking."""
        processor = FHIRBatchProcessor(self.patient)
        processor.chunk_size = 2  # Force chunking with small chunk size
        
        # Create larger batch
        large_documents = self.documents * 3  # 9 documents total
        large_extracted_data = self.extracted_data_list * 3
        large_metadata = self.metadata_list * 3
        
        # Prepare batch documents
        batch_documents = processor._prepare_batch_documents(
            large_documents,
            large_extracted_data,
            large_metadata
        )
        
        self.assertEqual(len(batch_documents), 9)
        
        # Test chunk creation
        chunk_size = processor.chunk_size
        chunks = [batch_documents[i:i + chunk_size] for i in range(0, len(batch_documents), chunk_size)]
        
        # Should have 5 chunks (2+2+2+2+1)
        self.assertEqual(len(chunks), 5)
        self.assertEqual(len(chunks[0]), 2)
        self.assertEqual(len(chunks[-1]), 1)  # Last chunk has remainder


class BatchProcessingIntegrationTest(TestCase):
    """Integration tests for batch processing with FHIRMergeService."""
    
    def setUp(self):
        """Set up integration test data."""
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.patient = Patient.objects.create(
            mrn='TEST001',
            first_name='Test',
            last_name='Patient',
            date_of_birth='1990-01-01',
            gender='M',
            cumulative_fhir_json={}
        )
        
        self.document = Document.objects.create(
            patient=self.patient,
            file='test_doc.pdf',
            uploaded_by=self.user,
            status='completed'
        )
    
    @patch('apps.fhir.services.FHIRMergeService.merge_document_data')
    def test_merge_service_batch_integration(self, mock_merge):
        """Test integration between FHIRMergeService and batch processing."""
        # Mock successful merge
        mock_result = MergeResult()
        mock_result.success = True
        mock_merge.return_value = mock_result
        
        # Create merge service and test batch processing
        merge_service = FHIRMergeService(self.patient)
        
        # Test batch processing capabilities
        capabilities = merge_service.get_batch_processing_capabilities()
        self.assertTrue(capabilities['supports_batch_processing'])
        self.assertTrue(capabilities['supports_relationship_detection'])
        self.assertTrue(capabilities['supports_transaction_management'])
        
        # Test batch merge
        result = merge_service.merge_document_batch(
            documents=[self.document],
            extracted_data_list=[{'test': 'data'}],
            metadata_list=[{'document_type': 'test'}],
            use_transactions=False
        )
        
        # Verify batch processing worked
        self.assertEqual(result.total_documents, 1)
        self.assertEqual(result.successful_documents, 1)


if __name__ == '__main__':
    unittest.main()
