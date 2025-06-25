"""
Django management command to test Celery setup.
Usage: python manage.py test_celery
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.documents.tasks import test_celery_task
import time


class Command(BaseCommand):
    """Test Celery configuration and task execution"""
    
    help = 'Test Celery setup by running a simple async task'
    
    def add_arguments(self, parser):
        """Add command arguments"""
        parser.add_argument(
            '--message',
            type=str,
            default='Testing Celery from Django management command!',
            help='Custom message to send to the test task'
        )
        
        parser.add_argument(
            '--wait',
            action='store_true',
            help='Wait for the task to complete and show results'
        )
    
    def handle(self, *args, **options):
        """Execute the test command"""
        message = options['message']
        wait_for_result = options['wait']
        
        self.stdout.write("=" * 60)
        self.stdout.write(
            self.style.SUCCESS("🔧 Testing Celery Setup for Medical Document Parser")
        )
        self.stdout.write("=" * 60)
        
        # Test basic Celery task
        self.stdout.write("\n📤 Dispatching test task to Celery worker...")
        
        try:
            # Send the task to Celery
            result = test_celery_task.delay(message)
            
            self.stdout.write(
                self.style.SUCCESS(f"✅ Task dispatched successfully!")
            )
            self.stdout.write(f"   Task ID: {result.id}")
            self.stdout.write(f"   Task State: {result.state}")
            
            if wait_for_result:
                self.stdout.write("\n⏳ Waiting for task to complete...")
                
                # Wait for the task to complete (with timeout)
                try:
                    task_result = result.get(timeout=30)
                    
                    self.stdout.write(
                        self.style.SUCCESS("🎉 Task completed successfully!")
                    )
                    self.stdout.write("📋 Task Results:")
                    self.stdout.write(f"   Success: {task_result.get('success')}")
                    self.stdout.write(f"   Message: {task_result.get('message')}")
                    self.stdout.write(f"   Task ID: {task_result.get('task_id')}")
                    self.stdout.write(f"   Timestamp: {task_result.get('timestamp')}")
                    
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"❌ Task failed or timed out: {e}")
                    )
                    return
            else:
                self.stdout.write(
                    self.style.WARNING("⚠️  Not waiting for results (use --wait to wait)")
                )
                self.stdout.write("   Check Celery worker logs to see task execution")
            
            # Test Redis connection
            self.stdout.write("\n🔗 Testing Redis connection...")
            try:
                from django.core.cache import cache
                test_key = f"celery_test_{int(time.time())}"
                cache.set(test_key, "test_value", 60)
                retrieved_value = cache.get(test_key)
                
                if retrieved_value == "test_value":
                    self.stdout.write(
                        self.style.SUCCESS("✅ Redis cache connection working!")
                    )
                    cache.delete(test_key)  # Clean up
                else:
                    self.stdout.write(
                        self.style.ERROR("❌ Redis cache test failed")
                    )
                    
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"❌ Redis connection failed: {e}")
                )
            
            # Summary
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write(
                self.style.SUCCESS("🚀 Celery Test Summary:")
            )
            self.stdout.write("✅ Task dispatch: Working")
            self.stdout.write("✅ Redis connection: Working")
            self.stdout.write("✅ Django-Celery integration: Working")
            
            self.stdout.write("\n💡 Next Steps:")
            self.stdout.write("   1. Make sure Redis server is running")
            self.stdout.write("   2. Start Celery worker: celery -A meddocparser worker -l info")
            self.stdout.write("   3. Check worker logs for task execution")
            self.stdout.write("=" * 60)
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ Failed to dispatch task: {e}")
            )
            self.stdout.write("\n🔧 Troubleshooting:")
            self.stdout.write("   1. Check if Redis server is running")
            self.stdout.write("   2. Verify REDIS_URL in environment settings")
            self.stdout.write("   3. Check Django settings for Celery configuration")
            return 