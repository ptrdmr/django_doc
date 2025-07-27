from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Simple test command'

    def handle(self, *args, **options):
        self.stdout.write("✅ Basic Django command works!")
        
        # Test basic imports step by step
        try:
            self.stdout.write("Testing basic imports...")
            
            import anthropic
            self.stdout.write("✅ anthropic imports fine")
        except ImportError:
            self.stdout.write("❌ anthropic not available")
        
        try:
            import openai
            self.stdout.write("✅ openai imports fine")
        except ImportError:
            self.stdout.write("❌ openai not available")
            
        self.stdout.write("✅ Simple test completed!") 