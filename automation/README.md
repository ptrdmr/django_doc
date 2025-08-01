# AI Assistant Context Automation

This folder contains tools to automatically keep the AI assistant updated with current project information, including dates and development status.

## 📁 Files Overview

- **`update_context.py`** - Main Python script for updating context
- **`update_context.bat`** - Windows batch file for easy execution
- **`context_template.txt`** - Template for the context file structure
- **`setup_automation.py`** - One-time setup script for automation

## 🚀 Usage Options

### Manual Update (Recommended for Development)
```powershell
# From project root
cd automation
python update_context.py --verbose
```

### Integrated with Django
```powershell
# From project root (uses Django management command)
venv\Scripts\activate; python manage.py update_context --verbose
```

### Windows Batch File
```powershell
# From automation folder
.\update_context.bat --interactive
```

## ⚙️ Setup Instructions

1. **First Time Setup:**
   ```powershell
   cd automation
   python setup_automation.py
   ```

2. **For Daily Automation (Optional):**
   - Run `setup_automation.py --schedule` to set up Windows Task Scheduler
   - Or manually add to your development startup routine

3. **For Git Integration (Optional):**
   - Run `setup_automation.py --git-hooks` to auto-update on commits

## 📋 What Gets Updated

The automation updates the `.current-context` file in the project root with:
- Current date (YYYY-MM-DD format)
- Development phase and active tasks
- Recent completions and current focus
- Technical stack information

## 🔧 Customization

Edit `context_template.txt` to modify the context structure, then run the setup script again to apply changes.

## 💡 Integration with AI Sessions

When starting an AI assistant session, simply mention "check current context" and the assistant will look for the `.current-context` file to get up-to-date project information. 