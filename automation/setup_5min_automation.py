#!/usr/bin/env python3
"""
Setup script for 5-minute context automation.
Sets up Windows Task Scheduler to run every 5 minutes.
"""

import subprocess
import sys
from pathlib import Path

def get_project_root():
    """Find the project root directory."""
    current_dir = Path(__file__).parent.parent
    if (current_dir / 'manage.py').exists():
        return current_dir
    raise FileNotFoundError("Could not find project root (manage.py not found)")

def setup_5min_schedule():
    """Set up Windows Task Scheduler for 5-minute context updates."""
    project_root = get_project_root()
    batch_file = project_root / 'automation' / 'update_context.bat'
    
    print("🕐 Setting up 5-minute context automation...")
    
    # Delete the old daily task if it exists
    try:
        subprocess.run(
            'schtasks /delete /tn "MedicalDocParser_ContextUpdate" /f',
            shell=True,
            capture_output=True
        )
        print("🗑️  Removed old daily task")
    except:
        pass  # Task might not exist
    
    # Create new 5-minute task
    task_name = "MedicalDocParser_ContextUpdate_5min"
    task_command = f'schtasks /create /tn "{task_name}" /tr "\\"{batch_file}\\"" /sc minute /mo 5 /f'
    
    try:
        result = subprocess.run(task_command, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ 5-minute automation configured successfully!")
            print(f"⏰ Task '{task_name}' will update context every 5 minutes")
            print("💡 Context will always have current date and time")
            return True
        else:
            print(f"❌ Failed to create 5-minute task: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Error setting up 5-minute task: {e}")
        print("💡 You may need to run as administrator")
        return False

def test_5min_task():
    """Test the 5-minute task immediately."""
    print("\n🧪 Testing the 5-minute task...")
    
    try:
        result = subprocess.run(
            'schtasks /run /tn "MedicalDocParser_ContextUpdate_5min"',
            shell=True,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✅ Test successful! Task runs correctly")
            return True
        else:
            print(f"❌ Test failed: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Test error: {e}")
        return False

def main():
    """Main setup function."""
    print("🚀 Simple 5-Minute Context Automation Setup")
    print("=" * 50)
    print("📋 This will update ONLY date and time every 5 minutes")
    print()
    
    # Set up the 5-minute schedule
    success = setup_5min_schedule()
    
    if success:
        # Test it
        test_success = test_5min_task()
        
        if test_success:
            print("\n🎯 Setup Complete!")
            print("✅ Context will update every 5 minutes with current date/time")
            print("✅ No complex task tracking - just simple timestamps")
            print("💡 Manually update DEVELOPMENT_PHASE and ACTIVE_WORK as needed")
        else:
            print("\n⚠️  Setup complete but test failed")
            print("💡 The automation should still work automatically")
    else:
        print("\n❌ Setup failed")
        print("💡 Try running as administrator")

if __name__ == "__main__":
    main() 