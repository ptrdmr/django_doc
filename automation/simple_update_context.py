#!/usr/bin/env python3
"""
Simple context updater - just date and time, nothing fancy.
Updates every 5 minutes to keep current timestamp.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

def get_project_root():
    """Find the project root directory."""
    current_dir = Path(__file__).parent
    if current_dir.name == 'automation':
        project_root = current_dir.parent
    else:
        project_root = current_dir
    
    if (project_root / 'manage.py').exists():
        return project_root
    
    search_dir = current_dir
    while search_dir.parent != search_dir:
        if (search_dir / 'manage.py').exists():
            return search_dir
        search_dir = search_dir.parent
    
    raise FileNotFoundError("Could not find project root (manage.py not found)")

def update_simple_context():
    """Update context with just current date and time."""
    
    # Get current date and time
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M:%S")
    current_datetime = now.strftime("%Y-%m-%d %H:%M:%S")
    
    # Find project root and context file
    project_root = get_project_root()
    context_file = project_root / ".current-context"
    
    # Read existing context
    if context_file.exists():
        with open(context_file, 'r') as f:
            content = f.read()
    else:
        # Load template from automation folder
        template_file = Path(__file__).parent / "simple_context_template.txt"
        if template_file.exists():
            with open(template_file, 'r') as f:
                content = f.read()
        else:
            # Create default content
            content = """# Project Context - Medical Document Parser
# Auto-updated every 5 minutes with current date/time

PROJECT_NAME="Medical Document Parser"
CURRENT_DATE="PLACEHOLDER_DATE"
CURRENT_TIME="PLACEHOLDER_TIME"
LAST_UPDATED="PLACEHOLDER_DATETIME"

# Development Status (manually update as needed)
DEVELOPMENT_PHASE="Document Processing Infrastructure Complete"
ACTIVE_WORK="Database documentation and automation setup"

# Technical Context  
DJANGO_VERSION="5.0"
DATABASE="PostgreSQL with JSONB"
AI_INTEGRATION="Claude 3 Sonnet + OpenAI GPT fallback"
DEPLOYMENT="Docker containerized, Redis + Celery async processing"
"""
    
    # Update time fields
    lines = content.split('\n')
    updated_lines = []
    
    for line in lines:
        if line.startswith('CURRENT_DATE='):
            updated_lines.append(f'CURRENT_DATE="{current_date}"')
        elif line.startswith('CURRENT_TIME='):
            updated_lines.append(f'CURRENT_TIME="{current_time}"')
        elif line.startswith('LAST_UPDATED='):
            updated_lines.append(f'LAST_UPDATED="{current_datetime}"')
        else:
            # Handle placeholder replacements for new files
            line = line.replace('PLACEHOLDER_DATE', current_date)
            line = line.replace('PLACEHOLDER_TIME', current_time)
            line = line.replace('PLACEHOLDER_DATETIME', current_datetime)
            updated_lines.append(line)
    
    # Write updated content
    with open(context_file, 'w') as f:
        f.write('\n'.join(updated_lines))
    
    print(f"✅ Context updated: {current_datetime}")
    return current_datetime

def main():
    """Main function."""
    if len(sys.argv) > 1 and sys.argv[1] == '--verbose':
        print("🕐 Simple Context Update (Date & Time Only)")
        print("=" * 45)
    
    try:
        timestamp = update_simple_context()
        
        if len(sys.argv) > 1 and sys.argv[1] == '--verbose':
            print(f"📅 Current timestamp: {timestamp}")
            print("⏰ Updates every 5 minutes automatically")
            
    except Exception as e:
        print(f"❌ Error updating context: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 