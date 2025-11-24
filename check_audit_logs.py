
import os
import django
import sys

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings')
django.setup()

from apps.core.models import AuditLog
from django.contrib.auth.models import User

def check_audit_logs():
    print("Checking last 10 AuditLog entries:")
    logs = AuditLog.objects.all().order_by('-timestamp')[:10]
    
    if not logs:
        print("No AuditLog entries found.")
        return

    for log in logs:
        print(f"ID: {log.id}")
        print(f"Time: {log.timestamp}")
        print(f"Event: {log.event_type}")
        print(f"User: {log.username} (ID: {log.user_id})")
        print(f"Description: {log.description}")
        print(f"Details: {log.details}")
        print("-" * 30)

if __name__ == "__main__":
    check_audit_logs()

