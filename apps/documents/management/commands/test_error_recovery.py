"""
Management command to test error recovery patterns and circuit breaker functionality.
Like test driving the truck after you've installed all the new safety equipment.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.core.services import error_recovery_service, context_preservation_service
from apps.documents.services import DocumentAnalyzer
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Test error recovery patterns and circuit breaker functionality'

    def add_arguments(self, parser):
        parser.add_argument(
            '--test-circuit-breaker',
            action='store_true',
            help='Test circuit breaker pattern'
        )
        parser.add_argument(
            '--test-context-preservation',
            action='store_true',
            help='Test context preservation functionality'
        )
        parser.add_argument(
            '--test-graceful-degradation',
            action='store_true',
            help='Test graceful degradation response'
        )
        parser.add_argument(
            '--test-error-categorization',
            action='store_true',
            help='Test error categorization system'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Run all error recovery tests'
        )

    def handle(self, *args, **options):
        """Run error recovery tests based on provided options."""
        
        if options['all']:
            options.update({
                'test_circuit_breaker': True,
                'test_context_preservation': True,
                'test_graceful_degradation': True,
                'test_error_categorization': True
            })
        
        self.stdout.write(
            self.style.SUCCESS('🔧 Starting Error Recovery Pattern Tests')
        )
        
        if options['test_circuit_breaker']:
            self.test_circuit_breaker()
        
        if options['test_context_preservation']:
            self.test_context_preservation()
        
        if options['test_graceful_degradation']:
            self.test_graceful_degradation()
        
        if options['test_error_categorization']:
            self.test_error_categorization()
        
        self.stdout.write(
            self.style.SUCCESS('✅ All error recovery tests completed')
        )

    def test_circuit_breaker(self):
        """Test circuit breaker functionality."""
        self.stdout.write('\n🔌 Testing Circuit Breaker Pattern...')
        
        # Reset circuit breaker state
        error_recovery_service._circuit_breakers = {}
        
        # Test failure recording
        self.stdout.write('   Recording failures for test service...')
        for i in range(6):  # Trigger circuit breaker (threshold is 5)
            error_recovery_service.record_failure('test_service', 'connection_error')
            
        # Check if circuit is open
        is_open = error_recovery_service._is_circuit_open('test_service')
        if is_open:
            self.stdout.write(
                self.style.SUCCESS('   ✅ Circuit breaker opened after 5 failures')
            )
        else:
            self.stdout.write(
                self.style.ERROR('   ❌ Circuit breaker failed to open')
            )
        
        # Test health status
        health = error_recovery_service.get_service_health_status()
        if 'test_service' in health and health['test_service']['state'] == 'open':
            self.stdout.write(
                self.style.SUCCESS('   ✅ Health status correctly shows circuit open')
            )
        else:
            self.stdout.write(
                self.style.ERROR('   ❌ Health status incorrect')
            )
        
        # Test success recording (half-open transition)
        self.stdout.write('   Testing recovery after cool-down...')
        
        # Manually set next attempt to past to test half-open state
        test_breaker = error_recovery_service._circuit_breakers['test_service']
        test_breaker['next_attempt'] = timezone.now() - timezone.timedelta(minutes=1)
        
        # Should move to half-open on next check
        is_open_after_cooldown = error_recovery_service._is_circuit_open('test_service')
        if not is_open_after_cooldown:
            self.stdout.write(
                self.style.SUCCESS('   ✅ Circuit moved to half-open after cool-down')
            )
            
            # Record success to close circuit
            error_recovery_service.record_success('test_service')
            
            final_health = error_recovery_service.get_service_health_status()
            if final_health['test_service']['state'] == 'closed':
                self.stdout.write(
                    self.style.SUCCESS('   ✅ Circuit closed after successful recovery')
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f"   ❌ Circuit state: {final_health['test_service']['state']}")
                )
        else:
            self.stdout.write(
                self.style.ERROR('   ❌ Circuit failed to move to half-open')
            )

    def test_context_preservation(self):
        """Test context preservation functionality."""
        self.stdout.write('\n💾 Testing Context Preservation...')
        
        # Test saving context
        test_context = {
            'document_type': 'medical_record',
            'processing_attempt': 1,
            'original_error': 'rate_limit_exceeded',
            'user_id': 12345
        }
        
        context_key = context_preservation_service.save_processing_context(
            document_id=999,
            processing_session='test-session-123',
            context_data=test_context
        )
        
        if context_key:
            self.stdout.write(
                self.style.SUCCESS(f'   ✅ Context saved with key: {context_key}')
            )
        else:
            self.stdout.write(
                self.style.ERROR('   ❌ Failed to save context')
            )
            return
        
        # Test retrieving context
        retrieved_context = context_preservation_service.retrieve_processing_context(context_key)
        
        if retrieved_context:
            self.stdout.write(
                self.style.SUCCESS('   ✅ Context retrieved successfully')
            )
            
            # Verify data integrity
            if retrieved_context['context_data'] == test_context:
                self.stdout.write(
                    self.style.SUCCESS('   ✅ Context data integrity verified')
                )
            else:
                self.stdout.write(
                    self.style.ERROR('   ❌ Context data corrupted')
                )
        else:
            self.stdout.write(
                self.style.ERROR('   ❌ Failed to retrieve context')
            )
            return
        
        # Test adding attempt info
        attempt_info = {
            'service': 'anthropic',
            'error_type': 'rate_limit_exceeded',
            'retry_count': 2
        }
        
        context_preservation_service.add_attempt_to_context(context_key, attempt_info)
        
        # Retrieve and verify attempt was added
        updated_context = context_preservation_service.retrieve_processing_context(context_key)
        
        if updated_context and len(updated_context['attempt_history']) > 0:
            self.stdout.write(
                self.style.SUCCESS('   ✅ Attempt info added to context')
            )
        else:
            self.stdout.write(
                self.style.ERROR('   ❌ Failed to add attempt info')
            )

    def test_graceful_degradation(self):
        """Test graceful degradation response creation."""
        self.stdout.write('\n🛡️ Testing Graceful Degradation...')
        
        # Test with partial results
        partial_results = {
            'patient_name': 'John Doe',
            'medical_record_number': 'MRN123456'
        }
        
        degradation_response = error_recovery_service.create_graceful_degradation_response(
            document_id=789,
            partial_results=partial_results,
            error_context="All AI services failed: Anthropic rate limited, OpenAI authentication error"
        )
        
        # Verify response structure
        required_fields = [
            'success', 'degraded', 'requires_manual_review', 'document_id',
            'error_context', 'extraction_status', 'fields', 'recommendations',
            'manual_review_priority', 'timestamp'
        ]
        
        missing_fields = [field for field in required_fields if field not in degradation_response]
        
        if not missing_fields:
            self.stdout.write(
                self.style.SUCCESS('   ✅ Degradation response has all required fields')
            )
        else:
            self.stdout.write(
                self.style.ERROR(f'   ❌ Missing fields: {missing_fields}')
            )
        
        # Verify response values
        if (degradation_response['success'] == False and 
            degradation_response['degraded'] == True and
            degradation_response['requires_manual_review'] == True):
            self.stdout.write(
                self.style.SUCCESS('   ✅ Degradation response flags set correctly')
            )
        else:
            self.stdout.write(
                self.style.ERROR('   ❌ Degradation response flags incorrect')
            )
        
        # Verify partial results preserved
        if degradation_response['fields'] == partial_results:
            self.stdout.write(
                self.style.SUCCESS('   ✅ Partial results preserved in degradation response')
            )
        else:
            self.stdout.write(
                self.style.ERROR('   ❌ Partial results not preserved correctly')
            )

    def test_error_categorization(self):
        """Test error categorization system."""
        self.stdout.write('\n🏷️ Testing Error Categorization...')
        
        # Test different error types
        test_cases = [
            ('Connection timeout occurred', None, 'transient'),
            ('Rate limit exceeded - try again later', 'rate_limit_exceeded', 'rate_limit'),
            ('Invalid API key provided', 'authentication_error', 'authentication'),
            ('Model not found', 'model_not_found', 'permanent'),
            ('Malformed request data', 'invalid_request', 'malformed'),
            ('Network connection failed', None, 'transient'),
            ('Service temporarily unavailable', None, 'transient'),
            ('Unauthorized access', None, 'authentication'),
        ]
        
        all_correct = True
        
        for error_message, error_type, expected_category in test_cases:
            actual_category = error_recovery_service.categorize_error(error_message, error_type)
            
            if actual_category == expected_category:
                self.stdout.write(
                    self.style.SUCCESS(f'   ✅ "{error_message[:30]}..." → {actual_category}')
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f'   ❌ "{error_message[:30]}..." → {actual_category} (expected {expected_category})')
                )
                all_correct = False
        
        if all_correct:
            self.stdout.write(
                self.style.SUCCESS('   ✅ All error categorization tests passed')
            )
        else:
            self.stdout.write(
                self.style.ERROR('   ❌ Some error categorization tests failed')
            )
        
        # Test retry logic
        self.stdout.write('\n   Testing retry logic...')
        
        retry_tests = [
            ('transient', 1, True),   # Should retry transient errors
            ('transient', 6, False),  # Should not retry after max attempts
            ('permanent', 1, False),  # Should not retry permanent errors
            ('rate_limit', 2, True),  # Should retry rate limit errors
            ('authentication', 2, False),  # Should not retry auth errors much
        ]
        
        for error_category, attempt_number, should_retry in retry_tests:
            actual_should_retry = error_recovery_service.should_retry(error_category, attempt_number)
            
            if actual_should_retry == should_retry:
                self.stdout.write(
                    self.style.SUCCESS(f'   ✅ {error_category} attempt {attempt_number}: retry={actual_should_retry}')
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f'   ❌ {error_category} attempt {attempt_number}: retry={actual_should_retry} (expected {should_retry})')
                ) 