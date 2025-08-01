@echo off
REM Auto-update project context for AI sessions from automation folder
REM Can be run manually or scheduled

echo 🔄 Updating project context...

REM Change to project root directory (one level up from automation)
cd /d "%~dp0.."

REM Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    echo 🔧 Activating virtual environment...
    call venv\Scripts\activate.bat
)

REM Run the simple update script from automation folder
echo 🕐 Running simple context update...
python automation\simple_update_context.py --verbose

REM Pause to see results if interactive flag is passed
if "%1"=="--interactive" (
    echo.
    echo Press any key to continue...
    pause >nul
)

echo ✅ Context update complete!

REM Return to automation directory
cd /d "%~dp0" 