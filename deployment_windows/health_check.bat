@echo off
REM Thin wrapper around health_check.py -- see that file for the
REM actual checks performed and the honesty notes on what "healthy"
REM can and cannot mean for this deployment (see KNOWN_GAPS.md).
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo FAILED: .venv not found. Run setup_phantom.bat first.
    exit /b 2
)

".venv\Scripts\python.exe" health_check.py --config phantom.config.ini
exit /b %errorlevel%
