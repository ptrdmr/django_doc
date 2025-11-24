
import uuid
import sys
from apps.core.models import AuditLog

try:
    print("Testing AuditLog with UUID in details...")
    AuditLog.log_event(
        event_type='system_access',
        description='Test UUID logging',
        details={'uuid': uuid.uuid4()}
    )
    print("Success: Created AuditLog with UUID")
except Exception as e:
    print(f"Failed: {e}")

