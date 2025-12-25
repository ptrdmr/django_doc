"""
Batch testing script for optimistic concurrency merge system.

This script processes multiple documents and collects comprehensive metrics
to validate the system meets the 5-20% flag rate target and performs correctly.

Usage:
    python scripts/test_optimistic_merge_batch.py
    
Or in Docker:
    docker-compose exec web python scripts/test_optimistic_merge_batch.py
"""
import os
import sys
import django
from pathlib import Path
from collections import Counter
from datetime import datetime

# Setup Django
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
django.setup()

from django.utils import timezone
from apps.documents.models import Document, ParsedData
from apps.patients.models import Patient
from apps.documents.tasks import process_document_async


class OptimisticMergeTestRunner:
    """Test runner for optimistic concurrency merge system"""
    
    def __init__(self):
        self.results = {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'auto_approved': 0,
            'flagged': 0,
            'flag_reasons': Counter(),
            'confidence_scores': [],
            'resource_counts': [],
            'processing_times': [],
            'errors': [],
            'documents': []
        }
    
    def run_batch_test(self, document_ids=None, limit=None):
        """
        Run batch processing test on documents.
        
        Args:
            document_ids: List of specific document IDs to process
            limit: Maximum number of documents to process
        """
        print("\n" + "="*80)
        print("OPTIMISTIC CONCURRENCY MERGE SYSTEM - BATCH TEST")
        print("="*80)
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # Get documents to process
        if document_ids:
            docs = Document.objects.filter(id__in=document_ids)
            print(f"📋 Processing {len(document_ids)} specified documents...")
        else:
            docs = Document.objects.filter(status='pending')
            if limit:
                docs = docs[:limit]
            print(f"📋 Processing {docs.count()} pending documents...")
        
        if docs.count() == 0:
            print("⚠ No documents to process")
            return
        
        print("-"*80)
        
        # Process each document
        for i, doc in enumerate(docs, 1):
            self.process_document(doc, i, docs.count())
        
        # Display summary
        self.display_summary()
    
    def process_document(self, doc, index, total):
        """Process a single document and collect metrics"""
        print(f"\n[{index}/{total}] Processing Document {doc.id}")
        print(f"  File: {os.path.basename(doc.file.name)}")
        print(f"  Patient: {doc.patient.mrn}")
        
        start_time = timezone.now()
        
        try:
            # Process the document
            result = process_document_async(doc.id)
            processing_time = (timezone.now() - start_time).total_seconds()
            
            # Get parsed data
            parsed = ParsedData.objects.filter(document=doc).first()
            
            if not parsed:
                raise Exception("No ParsedData created")
            
            # Collect metrics
            self.results['total'] += 1
            self.results['successful'] += 1
            self.results['processing_times'].append(processing_time)
            self.results['confidence_scores'].append(float(parsed.extraction_confidence))
            
            resource_count = parsed.get_fhir_resource_count()
            self.results['resource_counts'].append(resource_count)
            
            # Track approval status
            if parsed.auto_approved:
                self.results['auto_approved'] += 1
                status_icon = "✓"
                status_text = "AUTO-APPROVED"
            else:
                self.results['flagged'] += 1
                self.results['flag_reasons'][parsed.flag_reason] += 1
                status_icon = "⚠"
                status_text = "FLAGGED"
            
            # Store document details
            self.results['documents'].append({
                'id': doc.id,
                'filename': os.path.basename(doc.file.name),
                'status': parsed.review_status,
                'auto_approved': parsed.auto_approved,
                'confidence': float(parsed.extraction_confidence),
                'resources': resource_count,
                'flag_reason': parsed.flag_reason,
                'processing_time': processing_time,
                'is_merged': parsed.is_merged
            })
            
            # Display result
            print(f"  {status_icon} {status_text}")
            print(f"  Confidence: {parsed.extraction_confidence:.1%}")
            print(f"  Resources: {resource_count}")
            print(f"  Processing Time: {processing_time:.2f}s")
            if parsed.flag_reason:
                print(f"  Flag Reason: {parsed.flag_reason}")
            
        except Exception as e:
            self.results['total'] += 1
            self.results['failed'] += 1
            self.results['errors'].append({
                'document_id': doc.id,
                'filename': os.path.basename(doc.file.name),
                'error': str(e)
            })
            print(f"  ✗ FAILED: {str(e)}")
    
    def display_summary(self):
        """Display comprehensive test summary"""
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        
        # Overall stats
        print(f"\n📊 Overall Statistics:")
        print(f"  Total Documents: {self.results['total']}")
        print(f"  Successful: {self.results['successful']}")
        print(f"  Failed: {self.results['failed']}")
        
        if self.results['successful'] > 0:
            # Approval rates
            print(f"\n✓ Approval Statistics:")
            auto_pct = (self.results['auto_approved'] / self.results['successful']) * 100
            flag_pct = (self.results['flagged'] / self.results['successful']) * 100
            
            print(f"  Auto-Approved: {self.results['auto_approved']} ({auto_pct:.1f}%)")
            print(f"  Flagged: {self.results['flagged']} ({flag_pct:.1f}%)")
            
            # Check if flag rate is in target range
            if 5 <= flag_pct <= 20:
                print(f"  ✓ Flag rate is within target range (5-20%)")
            elif flag_pct < 5:
                print(f"  ⚠ Flag rate is BELOW target (< 5%) - thresholds may be too lenient")
            else:
                print(f"  ⚠ Flag rate is ABOVE target (> 20%) - thresholds may be too strict")
            
            # Flag reasons breakdown
            if self.results['flag_reasons']:
                print(f"\n⚠ Flag Reasons Breakdown:")
                for reason, count in self.results['flag_reasons'].most_common():
                    pct = (count / self.results['flagged']) * 100
                    print(f"  - {reason}: {count} ({pct:.1f}%)")
            
            # Confidence statistics
            if self.results['confidence_scores']:
                avg_conf = sum(self.results['confidence_scores']) / len(self.results['confidence_scores'])
                min_conf = min(self.results['confidence_scores'])
                max_conf = max(self.results['confidence_scores'])
                
                print(f"\n📈 Confidence Scores:")
                print(f"  Average: {avg_conf:.1%}")
                print(f"  Minimum: {min_conf:.1%}")
                print(f"  Maximum: {max_conf:.1%}")
            
            # Resource extraction statistics
            if self.results['resource_counts']:
                avg_resources = sum(self.results['resource_counts']) / len(self.results['resource_counts'])
                min_resources = min(self.results['resource_counts'])
                max_resources = max(self.results['resource_counts'])
                
                print(f"\n📊 Resource Extraction:")
                print(f"  Average Resources: {avg_resources:.1f}")
                print(f"  Minimum Resources: {min_resources}")
                print(f"  Maximum Resources: {max_resources}")
            
            # Performance statistics
            if self.results['processing_times']:
                avg_time = sum(self.results['processing_times']) / len(self.results['processing_times'])
                min_time = min(self.results['processing_times'])
                max_time = max(self.results['processing_times'])
                
                print(f"\n⏱ Performance Metrics:")
                print(f"  Average Processing Time: {avg_time:.2f}s")
                print(f"  Fastest: {min_time:.2f}s")
                print(f"  Slowest: {max_time:.2f}s")
        
        # Error details
        if self.results['errors']:
            print(f"\n✗ Errors ({len(self.results['errors'])}):")
            for error in self.results['errors']:
                print(f"  - Document {error['document_id']} ({error['filename']}): {error['error']}")
        
        # Detailed document table
        if self.results['documents']:
            print(f"\n📋 Detailed Results:")
            print("-"*80)
            print(f"{'ID':<6} {'Status':<15} {'Conf':<8} {'Res':<5} {'Time':<8} {'Merged':<7}")
            print("-"*80)
            
            for doc in self.results['documents']:
                status = "✓ Auto" if doc['auto_approved'] else "⚠ Flag"
                print(f"{doc['id']:<6} {status:<15} {doc['confidence']:<7.1%} "
                      f"{doc['resources']:<5} {doc['processing_time']:<7.2f}s "
                      f"{'Yes' if doc['is_merged'] else 'No':<7}")
        
        print("="*80)
        print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80 + "\n")
        
        # Recommendations
        self.display_recommendations()
    
    def display_recommendations(self):
        """Display recommendations based on test results"""
        if self.results['successful'] == 0:
            return
        
        print("💡 RECOMMENDATIONS:")
        print("-"*80)
        
        flag_pct = (self.results['flagged'] / self.results['successful']) * 100
        
        if flag_pct < 5:
            print("⚠ Flag rate is LOW (< 5%):")
            print("  - Consider tightening quality thresholds")
            print("  - Increase confidence threshold from 0.80 to 0.85")
            print("  - Increase resource count threshold from 3 to 5")
        elif flag_pct > 20:
            print("⚠ Flag rate is HIGH (> 20%):")
            print("  - Consider loosening quality thresholds")
            print("  - Decrease confidence threshold from 0.80 to 0.75")
            print("  - Allow fallback model for high-confidence extractions")
        else:
            print("✓ Flag rate is OPTIMAL (5-20%)")
            print("  - Current thresholds are working well")
            print("  - System is ready for production deployment")
        
        # Check for common flag reasons
        if self.results['flag_reasons']:
            top_reason = self.results['flag_reasons'].most_common(1)[0]
            reason_pct = (top_reason[1] / self.results['flagged']) * 100
            
            if reason_pct > 50:
                print(f"\n⚠ Dominant flag reason: {top_reason[0]} ({reason_pct:.0f}%)")
                
                if 'confidence' in top_reason[0].lower():
                    print("  - Many documents have low confidence")
                    print("  - Consider improving AI extraction prompts")
                elif 'fallback' in top_reason[0].lower():
                    print("  - Fallback model being used frequently")
                    print("  - Check primary model availability")
                elif 'conflict' in top_reason[0].lower():
                    print("  - Patient data conflicts detected")
                    print("  - Review patient matching logic")
        
        print("="*80 + "\n")


def main():
    """Main entry point"""
    runner = OptimisticMergeTestRunner()
    
    # You can customize this:
    # - Process specific documents: runner.run_batch_test(document_ids=[1, 2, 3])
    # - Limit number of documents: runner.run_batch_test(limit=10)
    # - Process all pending: runner.run_batch_test()
    
    runner.run_batch_test(limit=20)  # Process up to 20 pending documents


if __name__ == '__main__':
    main()

