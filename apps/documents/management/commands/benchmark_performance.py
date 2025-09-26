"""
Management command to benchmark document processing performance.

Tests the performance optimizations including caching, chunking, and database queries.
"""
import time
import json
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.cache import caches
from apps.documents.models import Document
from apps.documents.services.ai_extraction import extract_medical_data_structured  
from apps.documents.cache import get_document_cache
from apps.documents.performance import PerformanceMonitor, DocumentChunker


class Command(BaseCommand):
    help = 'Benchmark document processing performance optimizations'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--iterations',
            type=int,
            default=3,
            help='Number of test iterations to run'
        )
        parser.add_argument(
            '--test-caching',
            action='store_true',
            help='Test AI extraction caching performance'
        )
        parser.add_argument(
            '--test-chunking',
            action='store_true', 
            help='Test document chunking performance'
        )
        parser.add_argument(
            '--test-db-queries',
            action='store_true',
            help='Test database query optimization'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output'
        )
    
    def handle(self, *args, **options):
        """Run performance benchmarks."""
        self.stdout.write(self.style.SUCCESS('Starting Document Processing Performance Benchmarks'))
        self.stdout.write(f"Timestamp: {timezone.now()}")
        
        results = {
            'benchmark_start': timezone.now().isoformat(),
            'iterations': options['iterations'],
            'tests': {}
        }
        
        if options['test_caching']:
            results['tests']['caching'] = self.benchmark_caching(options)
            
        if options['test_chunking']:
            results['tests']['chunking'] = self.benchmark_chunking(options)
            
        if options['test_db_queries']:
            results['tests']['database'] = self.benchmark_database_queries(options)
        
        # If no specific tests selected, run all
        if not any([options['test_caching'], options['test_chunking'], options['test_db_queries']]):
            self.stdout.write("Running all benchmark tests...")
            results['tests']['caching'] = self.benchmark_caching(options)
            results['tests']['chunking'] = self.benchmark_chunking(options)
            results['tests']['database'] = self.benchmark_database_queries(options)
        
        # Display summary
        self.display_results(results)
        
        # Save results to file
        results_file = f"performance_benchmark_{int(time.time())}.json"
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        self.stdout.write(self.style.SUCCESS(f'Benchmark results saved to {results_file}'))
    
    def benchmark_caching(self, options):
        """Test AI extraction caching performance."""
        self.stdout.write("\n" + "="*50)
        self.stdout.write(self.style.WARNING('TESTING: AI Extraction Caching'))
        self.stdout.write("="*50)
        
        cache = get_document_cache()
        test_text = "Patient has diabetes mellitus type 2. Currently taking Metformin 500mg twice daily and Lisinopril 10mg once daily for hypertension. Blood pressure is 140/90."
        
        # Clear any existing cache for this test (skip if Redis unavailable)
        try:
            ai_cache = caches['ai_extraction']
            ai_cache.clear()
        except (KeyError, Exception) as cache_error:
            self.stdout.write(self.style.WARNING(f"  Cache clear failed (likely Redis not running): {cache_error}"))
            self.stdout.write(self.style.WARNING("  Continuing without cache clearing..."))
        
        results = {
            'test_text_length': len(test_text),
            'iterations': options['iterations'],
            'cache_miss_times': [],
            'cache_hit_times': [],
            'cache_hit_rate': 0
        }
        
        # Test cache miss (first time)
        for i in range(options['iterations']):
            start_time = time.time()
            try:
                extraction = extract_medical_data_structured(test_text)
                cache_miss_time = time.time() - start_time
                results['cache_miss_times'].append(cache_miss_time)
                
                if options['verbose']:
                    self.stdout.write(f"  Cache miss {i+1}: {cache_miss_time:.3f}s")
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Cache miss test failed: {e}"))
        
        # Test cache hit (subsequent times)
        for i in range(options['iterations']):
            start_time = time.time()
            try:
                extraction = extract_medical_data_structured(test_text)
                cache_hit_time = time.time() - start_time
                results['cache_hit_times'].append(cache_hit_time)
                
                if options['verbose']:
                    self.stdout.write(f"  Cache hit {i+1}: {cache_hit_time:.3f}s")
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Cache hit test failed: {e}"))
        
        # Calculate performance improvement
        if results['cache_miss_times'] and results['cache_hit_times']:
            avg_miss = sum(results['cache_miss_times']) / len(results['cache_miss_times'])
            avg_hit = sum(results['cache_hit_times']) / len(results['cache_hit_times'])
            improvement = ((avg_miss - avg_hit) / avg_miss) * 100
            
            results['average_cache_miss_time'] = avg_miss
            results['average_cache_hit_time'] = avg_hit
            results['performance_improvement_percent'] = improvement
            
            self.stdout.write(f"  Average cache miss: {avg_miss:.3f}s")
            self.stdout.write(f"  Average cache hit: {avg_hit:.3f}s")
            self.stdout.write(self.style.SUCCESS(f"  Performance improvement: {improvement:.1f}%"))
        
        return results
    
    def benchmark_chunking(self, options):
        """Test document chunking performance."""
        self.stdout.write("\n" + "="*50)
        self.stdout.write(self.style.WARNING('TESTING: Document Chunking'))
        self.stdout.write("="*50)
        
        chunker = DocumentChunker()
        
        # Create test documents of different sizes
        test_sizes = [5000, 15000, 25000, 50000]  # Characters
        
        results = {
            'test_sizes': test_sizes,
            'chunking_results': []
        }
        
        for size in test_sizes:
            # Generate test content
            test_content = "Patient presents with symptoms of chest pain and shortness of breath. " * (size // 70)
            
            start_time = time.time()
            chunks = chunker.chunk_text(test_content, preserve_context=True)
            chunking_time = time.time() - start_time
            
            chunk_result = {
                'content_size': len(test_content),
                'chunk_count': len(chunks),
                'chunking_time': chunking_time,
                'average_chunk_size': sum(len(c['text']) for c in chunks) / len(chunks) if chunks else 0
            }
            
            results['chunking_results'].append(chunk_result)
            
            if options['verbose']:
                self.stdout.write(f"  Size {size}: {len(chunks)} chunks in {chunking_time:.3f}s")
        
        return results
    
    def benchmark_database_queries(self, options):
        """Test database query optimization."""
        self.stdout.write("\n" + "="*50)
        self.stdout.write(self.style.WARNING('TESTING: Database Query Performance'))
        self.stdout.write("="*50)
        
        results = {
            'query_tests': []
        }
        
        # Test optimized vs unoptimized queries
        test_queries = [
            {
                'name': 'Document list (optimized)',
                'query': lambda: list(Document.objects.select_related('patient', 'created_by').prefetch_related('providers')[:10])
            },
            {
                'name': 'Document list (unoptimized)', 
                'query': lambda: list(Document.objects.all()[:10])
            },
            {
                'name': 'Recent documents by status',
                'query': lambda: list(Document.objects.filter(status='completed').order_by('-processed_at')[:5])
            }
        ]
        
        for test in test_queries:
            times = []
            for i in range(options['iterations']):
                start_time = time.time()
                try:
                    test['query']()
                    query_time = time.time() - start_time
                    times.append(query_time)
                    
                    if options['verbose']:
                        self.stdout.write(f"  {test['name']} {i+1}: {query_time:.3f}s")
                        
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  {test['name']} failed: {e}"))
            
            if times:
                avg_time = sum(times) / len(times)
                results['query_tests'].append({
                    'name': test['name'],
                    'average_time': avg_time,
                    'times': times
                })
        
        return results
    
    def display_results(self, results):
        """Display benchmark results summary."""
        self.stdout.write("\n" + "="*60)
        self.stdout.write(self.style.SUCCESS('PERFORMANCE BENCHMARK SUMMARY'))
        self.stdout.write("="*60)
        
        for test_name, test_results in results['tests'].items():
            self.stdout.write(f"\n{test_name.upper()} RESULTS:")
            
            if test_name == 'caching':
                if 'performance_improvement_percent' in test_results:
                    improvement = test_results['performance_improvement_percent']
                    if improvement > 50:
                        style = self.style.SUCCESS
                    elif improvement > 20:
                        style = self.style.WARNING
                    else:
                        style = self.style.ERROR
                    
                    self.stdout.write(style(f"  Cache Performance Improvement: {improvement:.1f}%"))
            
            elif test_name == 'chunking':
                total_chunks = sum(r['chunk_count'] for r in test_results['chunking_results'])
                avg_chunking_time = sum(r['chunking_time'] for r in test_results['chunking_results']) / len(test_results['chunking_results'])
                self.stdout.write(f"  Total chunks created: {total_chunks}")
                self.stdout.write(f"  Average chunking time: {avg_chunking_time:.3f}s")
            
            elif test_name == 'database':
                for query_test in test_results['query_tests']:
                    avg_time = query_test['average_time'] * 1000  # Convert to ms
                    if avg_time < 50:
                        style = self.style.SUCCESS
                    elif avg_time < 200:
                        style = self.style.WARNING
                    else:
                        style = self.style.ERROR
                    
                    self.stdout.write(style(f"  {query_test['name']}: {avg_time:.1f}ms"))
        
        self.stdout.write(f"\nBenchmark completed at: {timezone.now()}")
        self.stdout.write("="*60)
