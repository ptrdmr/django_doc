"""
Django management command to update AI assistant context.
Integrates with the existing Taskmaster workflow.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from pathlib import Path
import os

class Command(BaseCommand):
    help = 'Update AI assistant context file with current date and project status'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output',
        )
        parser.add_argument(
            '--task-status',
            type=str,
            help='Update current task status',
        )

    def handle(self, *args, **options):
        """Update the project context file."""
        
        # Get current date
        current_date = timezone.now().strftime("%Y-%m-%d")
        
        # Find project root (go up from manage.py location)
        project_root = Path(__file__).parent.parent.parent.parent.parent
        context_file = project_root / ".current-context"
        
        if options['verbose']:
            self.stdout.write("🔄 Updating AI assistant context...")
        
        # Read existing context
        if context_file.exists():
            with open(context_file, 'r') as f:
                content = f.read()
        else:
            # Create default if doesn't exist
            content = """# Project Context - Medical Document Parser
# Auto-updated context for AI assistant sessions

PROJECT_NAME="Medical Document Parser"
CURRENT_DATE="PLACEHOLDER_DATE"
DEVELOPMENT_PHASE="Task 6 Complete - Document Processing Infrastructure"
NEXT_MILESTONE="Task 7 - Reports and Analytics Module"
LAST_UPDATED="PLACEHOLDER_DATE"

# Quick Status
ACTIVE_TASKS="Reports module planning and implementation"
RECENT_COMPLETIONS="API Usage Monitoring (6.11), Database README updates"
CURRENT_FOCUS="Setting up automated reporting infrastructure"

# Technical Context  
DJANGO_VERSION="5.0"
DATABASE="PostgreSQL with JSONB"
AI_INTEGRATION="Claude 3 Sonnet + OpenAI GPT fallback"
DEPLOYMENT="Docker containerized, Redis + Celery async processing"
"""

        # Update date fields
        lines = content.split('\n')
        updated_lines = []
        
        for line in lines:
            if line.startswith('CURRENT_DATE='):
                updated_lines.append(f'CURRENT_DATE="{current_date}"')
            elif line.startswith('LAST_UPDATED='):
                updated_lines.append(f'LAST_UPDATED="{current_date}"')
            elif options['task_status'] and line.startswith('ACTIVE_TASKS='):
                updated_lines.append(f'ACTIVE_TASKS="{options["task_status"]}"')
            else:
                # Handle placeholder replacements
                line = line.replace('PLACEHOLDER_DATE', current_date)
                updated_lines.append(line)
        
        # Write updated content
        with open(context_file, 'w') as f:
            f.write('\n'.join(updated_lines))
        
        self.stdout.write(
            self.style.SUCCESS(f'✅ Context updated with date: {current_date}')
        )
        
        if options['verbose']:
            self.stdout.write(f"📁 Context file: {context_file}")
            self.stdout.write("🎯 Ready for AI assistant session!")
            
        if options['task_status']:
            self.stdout.write(
                self.style.SUCCESS(f'📋 Task status updated: {options["task_status"]}')
            ) 