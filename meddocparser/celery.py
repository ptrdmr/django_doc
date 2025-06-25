"""
Celery configuration for meddocparser project.
Handles async document processing for medical document parsing.
"""

import os
from celery import Celery
from django.conf import settings

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings')

app = Celery('meddocparser')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

# Configure Celery for medical document processing
app.conf.update(
    # Task routing for document processing
    task_routes={
        'apps.documents.tasks.*': {'queue': 'document_processing'},
        'apps.fhir.tasks.*': {'queue': 'fhir_processing'},
    },
    
    # Task time limits for safety (medical documents can be large)
    task_time_limit=600,  # 10 minutes max per task
    task_soft_time_limit=540,  # 9 minute soft limit
    
    # Task retry settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # Result backend settings
    result_expires=3600,  # Results expire after 1 hour
    
    # Worker settings
    worker_prefetch_multiplier=1,  # Process one task at a time for heavy operations
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks to prevent memory leaks
)

@app.task(bind=True)
def debug_task(self):
    """Debug task for testing Celery setup"""
    print(f'Request: {self.request!r}')
    return 'Celery is working!' 