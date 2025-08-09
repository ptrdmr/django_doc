"""
FHIR Batch Processing Module

Extends FHIRMergeService to handle batch processing of multiple related documents.
Provides optimized processing for document sets from the same encounter or visit.
"""

import logging
import time
from typing import List, Dict, Any, Optional, Tuple, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json

from django.db import transaction
from django.utils import timezone
from django.contrib.auth.models import User
from django.conf import settings

from apps.documents.models import Document
from apps.patients.models import Patient, PatientHistory
from apps.core.models import AuditLog
from .services import FHIRMergeService, MergeResult
from .transaction_manager import FHIRTransactionManager, StagingArea

logger = logging.getLogger(__name__)


@dataclass
class DocumentRelationship:
    """Represents relationships between documents in a batch."""
    encounter_id: Optional[str] = None
    visit_id: Optional[str] = None
    date_range: Optional[Tuple[datetime, datetime]] = None
    provider_id: Optional[str] = None
    document_type_group: Optional[str] = None
    confidence_score: float = 0.0
    
    def __str__(self):
        parts = []
        if self.encounter_id:
            parts.append(f"encounter:{self.encounter_id}")
        if self.visit_id:
            parts.append(f"visit:{self.visit_id}")
        if self.date_range:
            parts.append(f"dates:{self.date_range[0].date()}-{self.date_range[1].date()}")
        return " | ".join(parts) if parts else "unrelated"


@dataclass
class BatchDocument:
    """Wrapper for documents in batch processing."""
    document: Document
    extracted_data: Dict[str, Any]
    metadata: Dict[str, Any]
    relationship: Optional[DocumentRelationship] = None
    processing_order: int = 0
    chunk_size: Optional[int] = None
    
    @property
    def document_id(self) -> int:
        return self.document.id
    
    @property
    def document_type(self) -> str:
        return self.metadata.get('document_type', 'unknown')


@dataclass
class BatchMergeResult:
    """Comprehensive result tracking for batch merge operations."""
    batch_id: str = field(default_factory=lambda: str(uuid4()))
    total_documents: int = 0
    processed_documents: int = 0
    successful_documents: int = 0
    failed_documents: int = 0
    
    # Document processing results
    document_results: Dict[int, MergeResult] = field(default_factory=dict)
    document_errors: Dict[int, str] = field(default_factory=dict)
    
    # Batch-level metrics
    processing_start_time: Optional[datetime] = None
    processing_end_time: Optional[datetime] = None
    total_processing_time: float = 0.0
    memory_peak_usage: float = 0.0
    
    # Relationship analysis
    relationships_detected: List[DocumentRelationship] = field(default_factory=list)
    cross_document_conflicts: List[Dict[str, Any]] = field(default_factory=list)
    
    # Transaction management
    transaction_id: Optional[str] = None
    rollback_performed: bool = False
    partial_success: bool = False
    
    # Performance metrics
    average_document_processing_time: float = 0.0
    documents_per_second: float = 0.0
    
    def add_document_result(self, document_id: int, result: MergeResult):
        """Add a document processing result."""
        self.document_results[document_id] = result
        self.processed_documents += 1
        if result.success:
            self.successful_documents += 1
        else:
            self.failed_documents += 1
    
    def add_document_error(self, document_id: int, error_message: str):
        """Add a document processing error."""
        self.document_errors[document_id] = error_message
        self.processed_documents += 1
        self.failed_documents += 1
    
    def finalize(self):
        """Finalize the batch result with calculated metrics."""
        self.processing_end_time = timezone.now()
        if self.processing_start_time:
            self.total_processing_time = (
                self.processing_end_time - self.processing_start_time
            ).total_seconds()
            
            if self.total_processing_time > 0:
                self.documents_per_second = self.processed_documents / self.total_processing_time
                self.average_document_processing_time = self.total_processing_time / max(self.processed_documents, 1)
        
        self.partial_success = 0 < self.successful_documents < self.total_documents
    
    def get_success_rate(self) -> float:
        """Calculate batch success rate as percentage."""
        if self.processed_documents == 0:
            return 0.0
        return (self.successful_documents / self.processed_documents) * 100.0
    
    def get_summary(self) -> str:
        """Generate a human-readable summary of batch processing."""
        status = "completed"
        if self.rollback_performed:
            status = "rolled back"
        elif self.partial_success:
            status = "partially successful"
        elif self.failed_documents == self.total_documents:
            status = "failed"
        
        summary = (
            f"Batch {self.batch_id[:8]} {status}: "
            f"{self.successful_documents}/{self.total_documents} documents processed successfully"
        )
        
        if self.total_processing_time > 0:
            summary += f" in {self.total_processing_time:.2f}s ({self.documents_per_second:.1f} docs/sec)"
        
        if self.relationships_detected:
            summary += f", {len(self.relationships_detected)} relationships detected"
        
        if self.cross_document_conflicts:
            summary += f", {len(self.cross_document_conflicts)} cross-document conflicts"
        
        return summary


class DocumentRelationshipDetector:
    """Detects relationships between documents in a batch."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.RelationshipDetector')
    
    def detect_relationships(self, batch_documents: List[BatchDocument]) -> List[DocumentRelationship]:
        """
        Detect relationships between documents in the batch.
        
        Args:
            batch_documents: List of documents to analyze
            
        Returns:
            List of detected relationships
        """
        relationships = []
        
        # Group documents by potential relationships
        encounter_groups = self._group_by_encounter(batch_documents)
        visit_groups = self._group_by_visit(batch_documents)
        date_groups = self._group_by_date_proximity(batch_documents)
        provider_groups = self._group_by_provider(batch_documents)
        type_groups = self._group_by_document_type(batch_documents)
        
        # Analyze each grouping for relationships
        for group_type, groups in [
            ('encounter', encounter_groups),
            ('visit', visit_groups),
            ('date_proximity', date_groups),
            ('provider', provider_groups),
            ('document_type', type_groups)
        ]:
            for group_key, docs in groups.items():
                if len(docs) > 1:  # Only create relationships for multiple documents
                    relationship = self._create_relationship(group_type, group_key, docs)
                    if relationship:
                        relationships.append(relationship)
        
        return relationships
    
    def _group_by_encounter(self, batch_documents: List[BatchDocument]) -> Dict[str, List[BatchDocument]]:
        """Group documents by encounter ID."""
        groups = {}
        for doc in batch_documents:
            encounter_id = self._extract_encounter_id(doc)
            if encounter_id:
                if encounter_id not in groups:
                    groups[encounter_id] = []
                groups[encounter_id].append(doc)
        return groups
    
    def _group_by_visit(self, batch_documents: List[BatchDocument]) -> Dict[str, List[BatchDocument]]:
        """Group documents by visit ID."""
        groups = {}
        for doc in batch_documents:
            visit_id = self._extract_visit_id(doc)
            if visit_id:
                if visit_id not in groups:
                    groups[visit_id] = []
                groups[visit_id].append(doc)
        return groups
    
    def _group_by_date_proximity(self, batch_documents: List[BatchDocument]) -> Dict[str, List[BatchDocument]]:
        """Group documents by date proximity (within 24 hours)."""
        groups = {}
        proximity_hours = 24
        
        for doc in batch_documents:
            doc_date = self._extract_document_date(doc)
            if not doc_date:
                continue
                
            # Find existing group within proximity
            group_key = None
            for existing_key, existing_docs in groups.items():
                existing_date = datetime.fromisoformat(existing_key)
                if abs((doc_date - existing_date).total_seconds()) <= proximity_hours * 3600:
                    group_key = existing_key
                    break
            
            # Create new group if no existing group found
            if not group_key:
                group_key = doc_date.isoformat()
                groups[group_key] = []
            
            groups[group_key].append(doc)
        
        return groups
    
    def _group_by_provider(self, batch_documents: List[BatchDocument]) -> Dict[str, List[BatchDocument]]:
        """Group documents by provider."""
        groups = {}
        for doc in batch_documents:
            provider_id = self._extract_provider_id(doc)
            if provider_id:
                if provider_id not in groups:
                    groups[provider_id] = []
                groups[provider_id].append(doc)
        return groups
    
    def _group_by_document_type(self, batch_documents: List[BatchDocument]) -> Dict[str, List[BatchDocument]]:
        """Group documents by document type."""
        groups = {}
        for doc in batch_documents:
            doc_type = doc.document_type
            if doc_type not in groups:
                groups[doc_type] = []
            groups[doc_type].append(doc)
        return groups
    
    def _extract_encounter_id(self, doc: BatchDocument) -> Optional[str]:
        """Extract encounter ID from document data."""
        # Look for encounter ID in various possible locations
        data = doc.extracted_data
        
        # Check metadata first
        if 'encounter_id' in doc.metadata:
            return doc.metadata['encounter_id']
        
        # Check extracted data
        if 'encounter' in data:
            encounter = data['encounter']
            if isinstance(encounter, dict) and 'id' in encounter:
                return encounter['id']
            elif isinstance(encounter, str):
                return encounter
        
        # Check for encounter reference in FHIR data
        if 'encounter' in data and isinstance(data['encounter'], dict):
            if 'reference' in data['encounter']:
                return data['encounter']['reference']
        
        return None
    
    def _extract_visit_id(self, doc: BatchDocument) -> Optional[str]:
        """Extract visit ID from document data."""
        data = doc.extracted_data
        
        # Check metadata
        if 'visit_id' in doc.metadata:
            return doc.metadata['visit_id']
        
        # Check extracted data
        if 'visit' in data:
            visit = data['visit']
            if isinstance(visit, dict) and 'id' in visit:
                return visit['id']
            elif isinstance(visit, str):
                return visit
        
        return None
    
    def _extract_document_date(self, doc: BatchDocument) -> Optional[datetime]:
        """Extract document date from document data."""
        # Try document upload date first
        if hasattr(doc.document, 'uploaded_at'):
            return doc.document.uploaded_at
        
        # Try extracted date
        data = doc.extracted_data
        for date_field in ['document_date', 'service_date', 'date', 'effective_date']:
            if date_field in data:
                try:
                    if isinstance(data[date_field], datetime):
                        return data[date_field]
                    elif isinstance(data[date_field], str):
                        return datetime.fromisoformat(data[date_field].replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    continue
        
        return None
    
    def _extract_provider_id(self, doc: BatchDocument) -> Optional[str]:
        """Extract provider ID from document data."""
        data = doc.extracted_data
        
        # Check metadata
        if 'provider_id' in doc.metadata:
            return doc.metadata['provider_id']
        
        # Check extracted data
        if 'provider' in data:
            provider = data['provider']
            if isinstance(provider, dict) and 'id' in provider:
                return provider['id']
            elif isinstance(provider, str):
                return provider
        
        # Check for provider in performers
        if 'performers' in data and isinstance(data['performers'], list):
            for performer in data['performers']:
                if isinstance(performer, dict) and 'id' in performer:
                    return performer['id']
        
        return None
    
    def _create_relationship(self, group_type: str, group_key: str, documents: List[BatchDocument]) -> Optional[DocumentRelationship]:
        """Create a relationship object for a group of documents."""
        if len(documents) < 2:
            return None
        
        relationship = DocumentRelationship()
        
        # Set relationship properties based on group type
        if group_type == 'encounter':
            relationship.encounter_id = group_key
            relationship.confidence_score = 0.9
        elif group_type == 'visit':
            relationship.visit_id = group_key
            relationship.confidence_score = 0.8
        elif group_type == 'date_proximity':
            # Extract date range
            dates = []
            for doc in documents:
                doc_date = self._extract_document_date(doc)
                if doc_date:
                    dates.append(doc_date)
            if dates:
                relationship.date_range = (min(dates), max(dates))
                relationship.confidence_score = 0.6
        elif group_type == 'provider':
            relationship.provider_id = group_key
            relationship.confidence_score = 0.7
        elif group_type == 'document_type':
            relationship.document_type_group = group_key
            relationship.confidence_score = 0.5
        
        return relationship


class FHIRBatchProcessor:
    """
    Extended FHIR merge service for batch processing of multiple related documents.
    
    Provides optimized processing for document sets from the same encounter or visit,
    with memory optimization, progress tracking, and transaction management.
    """
    
    def __init__(self, patient: Patient, config_profile: Optional[str] = None):
        """
        Initialize the batch processor for a specific patient.
        
        Args:
            patient: Patient model instance to merge data into
            config_profile: Name of configuration profile to use
        """
        self.patient = patient
        self.merge_service = FHIRMergeService(patient, config_profile)
        self.relationship_detector = DocumentRelationshipDetector()
        self.transaction_manager = FHIRTransactionManager(patient)
        self.logger = logging.getLogger(__name__ + '.BatchProcessor')
        
        # Configuration
        self.max_concurrent_documents = getattr(settings, 'FHIR_BATCH_MAX_CONCURRENT', 3)
        self.memory_limit_mb = getattr(settings, 'FHIR_BATCH_MEMORY_LIMIT_MB', 512)
        self.chunk_size = getattr(settings, 'FHIR_BATCH_CHUNK_SIZE', 10)
        self.enable_progress_callbacks = True
    
    def merge_document_batch(
        self,
        documents: List[Document],
        extracted_data_list: List[Dict[str, Any]],
        metadata_list: List[Dict[str, Any]],
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        use_transactions: bool = True,
        enable_relationship_detection: bool = True,
        max_concurrent: Optional[int] = None
    ) -> BatchMergeResult:
        """
        Merge data from multiple related documents in an optimized batch operation.
        
        Args:
            documents: List of Document model instances
            extracted_data_list: List of extracted data dictionaries (one per document)
            metadata_list: List of metadata dictionaries (one per document)
            progress_callback: Optional callback for progress updates
            use_transactions: Whether to use transaction management
            enable_relationship_detection: Whether to detect document relationships
            max_concurrent: Maximum concurrent document processing (overrides default)
            
        Returns:
            BatchMergeResult with comprehensive processing results
            
        Raises:
            ValueError: If input lists have mismatched lengths
            RuntimeError: If batch processing fails critically
        """
        if not (len(documents) == len(extracted_data_list) == len(metadata_list)):
            raise ValueError("Documents, extracted_data_list, and metadata_list must have same length")
        
        # Initialize batch result
        batch_result = BatchMergeResult()
        batch_result.total_documents = len(documents)
        batch_result.processing_start_time = timezone.now()
        
        self.logger.info(f"Starting batch processing of {len(documents)} documents for patient {self.patient.id}")
        
        try:
            # Prepare batch documents
            batch_documents = self._prepare_batch_documents(documents, extracted_data_list, metadata_list)
            
            # Detect relationships if enabled
            if enable_relationship_detection:
                batch_result.relationships_detected = self.relationship_detector.detect_relationships(batch_documents)
                self.logger.info(f"Detected {len(batch_result.relationships_detected)} relationships")
            
            # Optimize processing order based on relationships
            batch_documents = self._optimize_processing_order(batch_documents, batch_result.relationships_detected)
            
            # Process documents in batches with memory management
            if use_transactions:
                batch_result = self._process_batch_transactional(
                    batch_documents, batch_result, progress_callback, max_concurrent
                )
            else:
                batch_result = self._process_batch_standard(
                    batch_documents, batch_result, progress_callback, max_concurrent
                )
            
        except Exception as e:
            self.logger.error(f"Batch processing failed: {str(e)}", exc_info=True)
            batch_result.add_document_error(-1, f"Batch processing failed: {str(e)}")
            
            if use_transactions and batch_result.transaction_id:
                self.logger.info("Rolling back batch transaction due to failure")
                # Transaction context manager handles rollback automatically
                batch_result.rollback_performed = True
        
        finally:
            batch_result.finalize()
            self._log_batch_completion(batch_result)
        
        return batch_result
    
    def _prepare_batch_documents(
        self,
        documents: List[Document],
        extracted_data_list: List[Dict[str, Any]],
        metadata_list: List[Dict[str, Any]]
    ) -> List[BatchDocument]:
        """Prepare batch documents with metadata and initial processing order."""
        batch_documents = []
        
        for i, (doc, data, metadata) in enumerate(zip(documents, extracted_data_list, metadata_list)):
            batch_doc = BatchDocument(
                document=doc,
                extracted_data=data,
                metadata=metadata,
                processing_order=i
            )
            batch_documents.append(batch_doc)
        
        return batch_documents
    
    def _optimize_processing_order(
        self,
        batch_documents: List[BatchDocument],
        relationships: List[DocumentRelationship]
    ) -> List[BatchDocument]:
        """
        Optimize processing order based on document relationships.
        
        Documents in the same encounter/visit should be processed together
        to optimize conflict resolution and memory usage.
        """
        if not relationships:
            return batch_documents
        
        # Group documents by relationship
        relationship_groups = {}
        unrelated_docs = []
        
        for doc in batch_documents:
            assigned = False
            for rel in relationships:
                if self._document_matches_relationship(doc, rel):
                    rel_key = str(rel)
                    if rel_key not in relationship_groups:
                        relationship_groups[rel_key] = []
                    relationship_groups[rel_key].append(doc)
                    assigned = True
                    break
            
            if not assigned:
                unrelated_docs.append(doc)
        
        # Rebuild processing order: related groups first, then unrelated
        optimized_docs = []
        processing_order = 0
        
        # Process relationship groups (sorted by confidence)
        for rel_key in sorted(relationship_groups.keys()):
            for doc in relationship_groups[rel_key]:
                doc.processing_order = processing_order
                optimized_docs.append(doc)
                processing_order += 1
        
        # Add unrelated documents
        for doc in unrelated_docs:
            doc.processing_order = processing_order
            optimized_docs.append(doc)
            processing_order += 1
        
        return optimized_docs
    
    def _document_matches_relationship(self, doc: BatchDocument, relationship: DocumentRelationship) -> bool:
        """Check if a document matches a given relationship."""
        # This is a simplified check - in practice, you'd want more sophisticated matching
        if relationship.encounter_id:
            return self.relationship_detector._extract_encounter_id(doc) == relationship.encounter_id
        elif relationship.visit_id:
            return self.relationship_detector._extract_visit_id(doc) == relationship.visit_id
        elif relationship.date_range:
            doc_date = self.relationship_detector._extract_document_date(doc)
            if doc_date:
                return relationship.date_range[0] <= doc_date <= relationship.date_range[1]
        elif relationship.provider_id:
            return self.relationship_detector._extract_provider_id(doc) == relationship.provider_id
        elif relationship.document_type_group:
            return doc.document_type == relationship.document_type_group
        
        return False
    
    def _process_batch_transactional(
        self,
        batch_documents: List[BatchDocument],
        batch_result: BatchMergeResult,
        progress_callback: Optional[Callable],
        max_concurrent: Optional[int]
    ) -> BatchMergeResult:
        """Process batch with transaction management."""
        # Use transaction context for the batch
        patient = batch_documents[0].document.patient
        batch_id = f"batch_{uuid4()}"
        
        with self.transaction_manager.transaction_context(
            patient=patient,
            operation_id=batch_id,
            auto_commit=False
        ) as staging_area:
            batch_result.transaction_id = batch_id
            
            try:
                # Process documents in chunks to manage memory
                chunk_size = min(self.chunk_size, len(batch_documents))
                chunks = [batch_documents[i:i + chunk_size] for i in range(0, len(batch_documents), chunk_size)]
                
                for chunk_idx, chunk in enumerate(chunks):
                    self.logger.info(f"Processing chunk {chunk_idx + 1}/{len(chunks)} ({len(chunk)} documents)")
                    
                    # Process chunk with concurrency
                    chunk_result = self._process_document_chunk(
                        chunk, batch_result, progress_callback, max_concurrent
                    )
                    
                    # Update batch result
                    for doc_id, result in chunk_result.items():
                        if isinstance(result, MergeResult):
                            batch_result.add_document_result(doc_id, result)
                        else:
                            batch_result.add_document_error(doc_id, str(result))
                
                # Commit staging area if successful
                commit_result = self.transaction_manager.commit_staging_area(staging_area.staging_id)
                if not commit_result.success:
                    raise RuntimeError(f"Failed to commit staging area: {commit_result.error_message}")
                
            except Exception as e:
                # Context manager will handle rollback automatically
                batch_result.rollback_performed = True
                raise
        
        return batch_result
    
    def _process_batch_standard(
        self,
        batch_documents: List[BatchDocument],
        batch_result: BatchMergeResult,
        progress_callback: Optional[Callable],
        max_concurrent: Optional[int]
    ) -> BatchMergeResult:
        """Process batch without transaction management."""
        # Process all documents as a single chunk
        document_results = self._process_document_chunk(
            batch_documents, batch_result, progress_callback, max_concurrent
        )
        
        # Update batch result
        for doc_id, result in document_results.items():
            if isinstance(result, MergeResult):
                batch_result.add_document_result(doc_id, result)
            else:
                batch_result.add_document_error(doc_id, str(result))
        
        return batch_result
    
    def _process_document_chunk(
        self,
        chunk: List[BatchDocument],
        batch_result: BatchMergeResult,
        progress_callback: Optional[Callable],
        max_concurrent: Optional[int]
    ) -> Dict[int, Any]:
        """Process a chunk of documents with optional concurrency."""
        max_workers = max_concurrent or self.max_concurrent_documents
        max_workers = min(max_workers, len(chunk))  # Don't create more threads than documents
        
        results = {}
        
        if max_workers > 1:
            # Concurrent processing
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all documents for processing
                future_to_doc = {
                    executor.submit(self._process_single_document, doc): doc
                    for doc in chunk
                }
                
                # Collect results
                for future in as_completed(future_to_doc):
                    doc = future_to_doc[future]
                    try:
                        result = future.result()
                        results[doc.document_id] = result
                    except Exception as e:
                        self.logger.error(f"Error processing document {doc.document_id}: {str(e)}")
                        results[doc.document_id] = str(e)
                    
                    # Progress callback
                    if progress_callback:
                        progress_callback(
                            len(results), 
                            batch_result.total_documents,
                            f"Processed document {doc.document_id}"
                        )
        else:
            # Sequential processing
            for doc in chunk:
                try:
                    result = self._process_single_document(doc)
                    results[doc.document_id] = result
                except Exception as e:
                    self.logger.error(f"Error processing document {doc.document_id}: {str(e)}")
                    results[doc.document_id] = str(e)
                
                # Progress callback
                if progress_callback:
                    progress_callback(
                        len(results), 
                        batch_result.total_documents,
                        f"Processed document {doc.document_id}"
                    )
        
        return results
    
    def _process_single_document(self, batch_doc: BatchDocument) -> MergeResult:
        """Process a single document using the merge service."""
        self.logger.debug(f"Processing document {batch_doc.document_id}")
        
        start_time = time.time()
        
        try:
            # Use the existing merge service for individual document processing
            result = self.merge_service.merge_document_data(
                batch_doc.extracted_data,
                batch_doc.metadata
            )
            
            processing_time = time.time() - start_time
            self.logger.debug(f"Document {batch_doc.document_id} processed in {processing_time:.2f}s")
            
            return result
            
        except Exception as e:
            processing_time = time.time() - start_time
            self.logger.error(f"Failed to process document {batch_doc.document_id} in {processing_time:.2f}s: {str(e)}")
            raise
    
    def _log_batch_completion(self, batch_result: BatchMergeResult):
        """Log batch completion with summary statistics."""
        success_rate = batch_result.get_success_rate()
        
        log_message = (
            f"Batch {batch_result.batch_id[:8]} completed: "
            f"{batch_result.successful_documents}/{batch_result.total_documents} successful "
            f"({success_rate:.1f}% success rate)"
        )
        
        if batch_result.total_processing_time > 0:
            log_message += f", {batch_result.total_processing_time:.2f}s total"
        
        if batch_result.rollback_performed:
            log_message += " (transaction rolled back)"
        elif batch_result.partial_success:
            log_message += " (partial success)"
        
        if success_rate >= 90:
            self.logger.info(log_message)
        elif success_rate >= 50:
            self.logger.warning(log_message)
        else:
            self.logger.error(log_message)
