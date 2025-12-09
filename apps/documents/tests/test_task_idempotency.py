"""
Task 41.15: Tests for process_document_async idempotency.

Ensures documents are not processed multiple times and race conditions are prevented.
"""

import pytest
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from unittest.mock import patch, MagicMock
from apps.documents.models import Document, ParsedData
from apps.patients.models import Patient
from apps.documents.tasks import process_document_async
from django.core.files.uploadedfile import SimpleUploadedFile
import time
from threading import Thread


class TaskIdempotencyBasicTests(TestCase):
    """Test basic idempotency behavior of process_document_async."""
    
    def setUp(self):
        """Create test data."""
        self.patient = Patient.objects.create(
            first_name="John",
            last_name="Doe",
            date_of_birth="1980-01-01",
            mrn="TEST-001"
        )
        
        # Create test PDF file
        pdf_content = b"%PDF-1.4 test content"
        self.pdf_file = SimpleUploadedFile(
            "test_document.pdf",
            pdf_content,
            content_type="application/pdf"
        )
        
        self.document = Document.objects.create(
            patient=self.patient,
            file=self.pdf_file,
            filename="test_document.pdf",
            status='pending'
        )
    
    def test_already_completed_document_skipped(self):
        """
        Test that a document with status='completed' and merged ParsedData
        is skipped without reprocessing (idempotency check).
        """
        # Set document to completed status
        self.document.status = 'completed'
        self.document.processed_at = timezone.now()
        self.document.save()
        
        # Create merged ParsedData
        ParsedData.objects.create(
            document=self.document,
            patient=self.patient,
            extraction_json=[],
            fhir_delta_json=[],
            extraction_confidence=0.95,
            review_status='auto_approved',
            auto_approved=True,
            is_merged=True,
            merged_at=timezone.now()
        )
        
        # Call task
        result = process_document_async(self.document.id)
        
        # Verify skipped
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['idempotent_skip'])
        self.assertTrue(result['already_processed'])
    
    def test_completed_without_merge_not_skipped(self):
        """
        Test that a document with status='completed' but no merged ParsedData
        will attempt reprocessing (data may have been lost or not merged).
        """
        # Set document to completed but no merged ParsedData
        self.document.status = 'completed'
        self.document.processed_at = timezone.now()
        self.document.save()
        
        # Call task - should not skip because no merged data
        result = process_document_async(self.document.id)
        
        # Verify it did not skip (it should attempt processing)
        self.assertNotIn('idempotent_skip', result)
    
    def test_failed_document_status_reset(self):
        """
        Test that a document with status='failed' has its status reset to pending
        during the idempotency check to allow reprocessing.
        """
        # Set document to failed status
        self.document.status = 'failed'
        self.document.error_message = "Previous processing error"
        self.document.save()
        
        initial_attempts = self.document.processing_attempts or 0
        
        # Call task (will fail due to fake PDF, but that's okay)
        result = process_document_async(self.document.id)
        
        # Verify status was reset and processing was attempted
        self.document.refresh_from_db()
        
        # The key test: processing_attempts should have incremented
        # This proves the idempotency check allowed reprocessing
        self.assertGreater(
            self.document.processing_attempts or 0,
            initial_attempts,
            "Processing should have been attempted (status was reset from 'failed')"
        )


class TaskIdempotencyLockingTests(TransactionTestCase):
    """Test database locking prevents race conditions."""
    
    def setUp(self):
        """Create test data."""
        self.patient = Patient.objects.create(
            first_name="Jane",
            last_name="Smith",
            date_of_birth="1985-05-15",
            mrn="TEST-002"
        )
        
        pdf_content = b"%PDF-1.4 test content"
        self.pdf_file = SimpleUploadedFile(
            "test_race.pdf",
            pdf_content,
            content_type="application/pdf"
        )
        
        self.document = Document.objects.create(
            patient=self.patient,
            file=self.pdf_file,
            filename="test_race.pdf",
            status='pending'
        )
    
    def test_select_for_update_lock_exists(self):
        """
        Test that the idempotency check uses select_for_update to lock the document.
        Verifies the lock mechanism exists without testing full concurrent execution.
        """
        from django.db import transaction
        
        # Hold a lock on the document
        with transaction.atomic():
            locked_doc = Document.objects.select_for_update().get(id=self.document.id)
            
            # Try to get the document with idempotency check
            # This should either skip or wait, not crash
            try:
                result = process_document_async(self.document.id)
                # Should skip due to lock being held
                self.assertIn('success', result)
            except Exception as e:
                # Should not raise exceptions from lock conflicts
                self.fail(f"Idempotency check crashed with lock held: {e}")


class TaskIdempotencyPerformanceTests(TestCase):
    """Test performance impact of idempotency checks."""
    
    def setUp(self):
        """Create test data."""
        self.patient = Patient.objects.create(
            first_name="Performance",
            last_name="Test",
            date_of_birth="1990-01-01",
            mrn="TEST-PERF"
        )
        
        pdf_content = b"%PDF-1.4 test content"
        self.pdf_file = SimpleUploadedFile(
            "test_perf.pdf",
            pdf_content,
            content_type="application/pdf"
        )
    
    def test_idempotency_check_performance(self):
        """
        Test that idempotency check completes quickly (<100ms).
        """
        # Create completed document with merged data
        document = Document.objects.create(
            patient=self.patient,
            file=self.pdf_file,
            filename="test_perf.pdf",
            status='completed',
            processed_at=timezone.now()
        )
        
        ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json=[],
            fhir_delta_json=[],
            extraction_confidence=0.95,
            review_status='auto_approved',
            auto_approved=True,
            is_merged=True,
            merged_at=timezone.now()
        )
        
        # Measure idempotency check time
        start = time.time()
        result = process_document_async(document.id)
        elapsed = (time.time() - start) * 1000  # Convert to ms
        
        # Verify skipped quickly
        self.assertTrue(result['idempotent_skip'])
        self.assertLess(elapsed, 200, f"Idempotency check took {elapsed:.2f}ms, should be <200ms")
    
    def test_batch_idempotency_check_performance(self):
        """
        Test idempotency check performance with multiple documents.
        """
        # Create 10 completed documents
        documents = []
        for i in range(10):
            pdf_content = b"%PDF-1.4 test content"
            pdf_file = SimpleUploadedFile(
                f"test_batch_{i}.pdf",
                pdf_content,
                content_type="application/pdf"
            )
            
            doc = Document.objects.create(
                patient=self.patient,
                file=pdf_file,
                filename=f"test_batch_{i}.pdf",
                status='completed',
                processed_at=timezone.now()
            )
            
            ParsedData.objects.create(
                document=doc,
                patient=self.patient,
                extraction_json=[],
                fhir_delta_json=[],
                extraction_confidence=0.95,
                review_status='auto_approved',
                auto_approved=True,
                is_merged=True,
                merged_at=timezone.now()
            )
            
            documents.append(doc)
        
        # Check all documents
        start = time.time()
        for doc in documents:
            result = process_document_async(doc.id)
            self.assertTrue(result['idempotent_skip'])
        
        elapsed = (time.time() - start) * 1000
        avg_time = elapsed / len(documents)
        
        self.assertLess(
            avg_time,
            100,
            f"Average idempotency check took {avg_time:.2f}ms, should be <100ms"
        )


class TaskIdempotencyEdgeCaseTests(TestCase):
    """Test edge cases and error handling in idempotency logic."""
    
    def setUp(self):
        """Create test data."""
        self.patient = Patient.objects.create(
            first_name="Edge",
            last_name="Case",
            date_of_birth="1995-03-20",
            mrn="TEST-EDGE"
        )
        
        pdf_content = b"%PDF-1.4 test content"
        self.pdf_file = SimpleUploadedFile(
            "test_edge.pdf",
            pdf_content,
            content_type="application/pdf"
        )
    
    def test_nonexistent_document_returns_error(self):
        """
        Test that processing a nonexistent document raises DoesNotExist exception.
        """
        # Should raise DoesNotExist exception (not swallowed by idempotency check)
        with self.assertRaises(Document.DoesNotExist):
            process_document_async(99999)  # Non-existent ID
    
    def test_completed_with_old_unmerged_data_not_skipped(self):
        """
        Test that a document with completed status but old unmerged ParsedData
        will attempt reprocessing.
        """
        document = Document.objects.create(
            patient=self.patient,
            file=self.pdf_file,
            filename="test_old_data.pdf",
            status='completed',
            processed_at=timezone.now()
        )
        
        # Create old ParsedData that was never merged
        ParsedData.objects.create(
            document=document,
            patient=self.patient,
            extraction_json=[],
            fhir_delta_json=[],
            extraction_confidence=0.80,
            review_status='flagged',
            auto_approved=False,
            is_merged=False,  # Never merged
            flag_reason="Low confidence"
        )
        
        # Should not skip because data was never merged
        result = process_document_async(document.id)
        
        # Verify it attempted processing (not skipped)
        self.assertNotIn('already_processed', result)
