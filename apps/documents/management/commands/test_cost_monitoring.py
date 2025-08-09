"""
Management command to test the cost monitoring system.
Creates a test document and processes it to verify monitoring works.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from uuid import uuid4
from decimal import Decimal

from apps.patients.models import Patient
from apps.documents.models import Document
from apps.core.services import CostCalculator, APIUsageMonitor
from apps.core.models import APIUsageLog


class Command(BaseCommand):
    help = 'Test the cost monitoring system with sample data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--create-sample-data',
            action='store_true',
            help='Create sample API usage log entries'
        )
        parser.add_argument(
            '--test-calculator',
            action='store_true',
            help='Test the cost calculator with known model pricing'
        )
        parser.add_argument(
            '--test-analytics',
            action='store_true',
            help='Test the analytics and reporting functions'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🔧 Testing Cost Monitoring System'))
        
        if options['test_calculator']:
            self.test_cost_calculator()
            
        if options['create_sample_data']:
            self.create_sample_data()
            
        if options['test_analytics']:
            self.test_analytics()
            
        # Default action if no specific test chosen
        if not any([options['test_calculator'], options['create_sample_data'], options['test_analytics']]):
            self.test_cost_calculator()
            self.create_sample_data()
            self.test_analytics()

    def test_cost_calculator(self):
        """Test the cost calculation functionality."""
        self.stdout.write('\n📊 Testing Cost Calculator...')
        
        # Test known model pricing
        test_cases = [
            ('anthropic', 'claude-3-sonnet-20240229', 1000, 500),
            ('anthropic', 'claude-3-haiku-20240307', 10000, 2000),
            ('openai', 'gpt-3.5-turbo', 1000, 500),
            ('openai', 'gpt-4', 1000, 500),
        ]
        
        for provider, model, input_tokens, output_tokens in test_cases:
            cost = CostCalculator.calculate_cost(provider, model, input_tokens, output_tokens)
            self.stdout.write(
                f"  • {provider}/{model}: {input_tokens} in + {output_tokens} out = ${cost:.6f}"
            )
        
        # Test unknown model
        unknown_cost = CostCalculator.calculate_cost('unknown', 'unknown-model', 1000, 500)
        self.stdout.write(f"  • Unknown model cost: ${unknown_cost:.6f} (should be 0.000000)")
        
        self.stdout.write(self.style.SUCCESS('✅ Cost Calculator tests completed'))

    def create_sample_data(self):
        """Create sample API usage data for testing."""
        self.stdout.write('\n📝 Creating Sample API Usage Data...')
        
        # Create or get a test patient
        try:
            patient = Patient.objects.get(mrn='TEST-MONITOR-001')
            self.stdout.write(f"  • Using existing test patient: {patient.mrn}")
        except Patient.DoesNotExist:
            patient = Patient.objects.create(
                mrn='TEST-MONITOR-001',
                first_name='Test',
                last_name='Patient',
                date_of_birth='1990-01-01',
                gender='M'
            )
            self.stdout.write(f"  • Created test patient: {patient.mrn}")
        
        # Create a test document (without actual file since we're just testing monitoring)
        try:
            # Create document without file for cost monitoring test
            document = Document.objects.create(
                patient=patient,
                filename='test_monitoring_document.pdf',
                status='pending'
            )
            # Set file_size manually since we don't have a real file
            document.file_size = 1024
            document.save()
            
            self.stdout.write(f"  • Created test document: {document.filename}")
            
            # Create sample API usage logs
            session_id = uuid4()
            base_time = timezone.now()
            
            # Simulate multiple API calls for the same document
            api_calls = [
                ('anthropic', 'claude-3-sonnet-20240229', 2500, 800, True, None),
                ('anthropic', 'claude-3-sonnet-20240229', 3200, 1200, True, None),
                ('openai', 'gpt-3.5-turbo', 2800, 600, False, 'Rate limit exceeded'),
                ('anthropic', 'claude-3-haiku-20240307', 2800, 600, True, None),  # Fallback
            ]
            
            for i, (provider, model, input_tokens, output_tokens, success, error_msg) in enumerate(api_calls):
                start_time = base_time - timezone.timedelta(minutes=10-i*2)
                end_time = start_time + timezone.timedelta(seconds=30+i*10)
                
                try:
                    log_entry = APIUsageMonitor.log_api_usage(
                        document=document,
                        patient=patient,
                        session_id=session_id,
                        provider=provider,
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=input_tokens + output_tokens,
                        start_time=start_time,
                        end_time=end_time,
                        success=success,
                        error_message=error_msg
                    )
                    
                    status_icon = "✅" if success else "❌"
                    self.stdout.write(
                        f"    {status_icon} {provider}/{model}: {input_tokens + output_tokens} tokens, "
                        f"${log_entry.cost_usd:.6f}, {log_entry.processing_duration_ms}ms"
                    )
                    
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"    ❌ Failed to log {provider}/{model}: {e}"))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ Failed to create test document: {e}"))
        
        self.stdout.write(self.style.SUCCESS('✅ Sample data created successfully'))

    def test_analytics(self):
        """Test the analytics and reporting functions."""
        self.stdout.write('\n📈 Testing Analytics Functions...')
        
        # Test overall usage summary
        try:
            summary = APIUsageMonitor.get_usage_summary()
            self.stdout.write(f"  • Total API calls: {summary['summary']['total_api_calls']}")
            self.stdout.write(f"  • Total cost: ${summary['summary']['total_cost']:.6f}")
            self.stdout.write(f"  • Total tokens: {summary['summary']['total_tokens']:,}")
            self.stdout.write(f"  • Success rate: {summary['summary']['success_rate']:.1f}%")
            self.stdout.write(f"  • Documents processed: {summary['summary']['total_documents']}")
            
            # Show model usage breakdown
            self.stdout.write("\n  📊 Model Usage Breakdown:")
            for model_usage in summary['model_usage']:
                self.stdout.write(
                    f"    • {model_usage['provider']}/{model_usage['model']}: "
                    f"{model_usage['call_count']} calls, ${model_usage['total_cost']:.6f}"
                )
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ Analytics test failed: {e}"))
            
        # Test patient-specific analytics
        try:
            test_patient = Patient.objects.filter(mrn='TEST-MONITOR-001').first()
            if test_patient:
                patient_stats = APIUsageMonitor.get_usage_by_patient(test_patient)
                self.stdout.write(f"\n  👤 Test Patient Analytics:")
                self.stdout.write(f"    • Total cost: ${patient_stats['total_cost']:.6f}")
                self.stdout.write(f"    • Documents: {patient_stats['document_count']}")
                self.stdout.write(f"    • API calls: {patient_stats['api_calls']}")
                self.stdout.write(f"    • Avg cost per document: ${patient_stats['avg_cost_per_document']:.6f}")
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ Patient analytics test failed: {e}"))
            
        # Test cost optimization suggestions
        try:
            optimization = APIUsageMonitor.get_cost_optimization_suggestions(days=30)
            self.stdout.write(f"\n  💡 Optimization Suggestions ({optimization['total_calls_analyzed']} calls analyzed):")
            
            if optimization['suggestions']:
                for suggestion in optimization['suggestions']:
                    icon = "💰" if suggestion['type'] == 'model_optimization' else "⚠️"
                    self.stdout.write(f"    {icon} {suggestion['message']}")
            else:
                self.stdout.write("    ✨ No optimization suggestions - system is running efficiently!")
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ Optimization test failed: {e}"))
        
        self.stdout.write(self.style.SUCCESS('✅ Analytics tests completed'))
        
        # Show recent API usage
        try:
            recent_logs = APIUsageLog.objects.order_by('-created_at')[:5]
            if recent_logs:
                self.stdout.write("\n  🕐 Recent API Usage:")
                for log in recent_logs:
                    status_icon = "✅" if log.success else "❌"
                    self.stdout.write(
                        f"    {status_icon} {log.created_at.strftime('%H:%M:%S')} - "
                        f"{log.provider}/{log.model} - {log.total_tokens} tokens - ${log.cost_usd:.6f}"
                    )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ Recent logs query failed: {e}"))

        self.stdout.write(self.style.SUCCESS('\n🎉 Cost Monitoring System Test Complete!'))
        self.stdout.write('\n💡 Next steps:')
        self.stdout.write('  • Check Django admin for APIUsageLog entries')
        self.stdout.write('  • Process a real document to see live monitoring')
        self.stdout.write('  • Review cost optimization suggestions') 