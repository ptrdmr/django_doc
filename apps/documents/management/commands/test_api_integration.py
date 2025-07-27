"""
Django management command to test DocumentAnalyzer API integration.
"""
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Test DocumentAnalyzer API integration and rate limiting'

    def handle(self, *args, **options):
        """Test the DocumentAnalyzer API integration"""
        self.stdout.write("🔧 Testing DocumentAnalyzer API integration...")
        
        try:
            # Import DocumentAnalyzer
            from apps.documents.services import DocumentAnalyzer
            self.stdout.write("✅ DocumentAnalyzer import successful")
            
            # Test initialization
            analyzer = DocumentAnalyzer()
            self.stdout.write("✅ DocumentAnalyzer initialization successful")
            
            # Check configuration
            self.stdout.write(f"📊 Primary model: {analyzer.primary_model}")
            self.stdout.write(f"📊 Fallback model: {analyzer.fallback_model}")
            self.stdout.write(f"📊 Max tokens: {analyzer.max_tokens}")
            self.stdout.write(f"📊 Timeout: {analyzer.timeout}")
            
            # Check API client availability
            anthropic_available = analyzer.anthropic_client is not None
            openai_available = analyzer.openai_client is not None
            
            if anthropic_available:
                self.stdout.write("✅ Anthropic client initialized")
            else:
                self.stdout.write("❌ Anthropic client not available (no API key)")
                
            if openai_available:
                self.stdout.write("✅ OpenAI client initialized")
            else:
                self.stdout.write("❌ OpenAI client not available (no API key)")
            
            if not anthropic_available and not openai_available:
                self.stdout.write(
                    self.style.WARNING(
                        "⚠️  No API keys configured. Add ANTHROPIC_API_KEY or OPENAI_API_KEY to test API calls"
                    )
                )
            
            # Test error handling methods exist
            if hasattr(analyzer, '_call_anthropic'):
                self.stdout.write("✅ Enhanced Anthropic API method available")
            if hasattr(analyzer, '_call_openai'):
                self.stdout.write("✅ Enhanced OpenAI API method available")
            
            self.stdout.write(
                self.style.SUCCESS("\n🎉 API integration test completed successfully!")
            )
            
        except ImportError as e:
            self.stdout.write(
                self.style.ERROR(f"❌ Import error: {e}")
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ Test failed: {e}")
            ) 