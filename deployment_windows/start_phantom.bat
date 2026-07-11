@echo off
REM ============================================================
REM Phantom start script (Windows).
REM
REM Activates the local venv, validates configuration BEFORE
REM starting anything, launches run_phantom.py (which starts the
REM Bridge HTTP service, constructs the Runtime Orchestrator +
REM 5 engines, and starts Reliability monitoring, in that order --
REM see run_phantom.py's own module docstring), then reports a
REM clear HEALTHY / DEGRADED / FAILED status.
REM
REM HONESTY NOTE: current status will report DEGRADED, never
REM HEALTHY, until a market-data ingestion component is added to
REM this repository -- see KNOWN_GAPS.md. This script does not
REM claim otherwise.
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo FAILED: .venv not found. Run setup_phantom.bat first.
    exit /b 2
)

if not exist "phantom.config.ini" (
    echo FAILED: phantom.config.ini not found. Copy
    echo         config\phantom.config.template.ini to phantom.config.ini
    echo         and edit it first.
    exit /b 2
)

echo Validating configuration before startup...
".venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, '.'); from config_loader import load_settings; from pathlib import Path; load_settings(Path('phantom.config.ini'))"
if errorlevel 1 (
    echo FAILED: configuration validation failed -- see error above.
    echo         Refusing to start.
    exit /b 2
)
echo Configuration OK.

REM -- Duplicate-instance guard (run_phantom.py itself also refuses a
REM    second instance via its pid file -- this is a friendlier,
REM    earlier check for the operator).
if exist "state\phantom.pid" (
    echo A phantom.pid file already exists in state\. If Phantom is
    echo already running, this is expected -- run health_check.bat to
    echo check its status, or stop_phantom.bat if you need to restart it.
    echo start_phantom.bat will still attempt to start; run_phantom.py
    echo will refuse to run a second instance if one is truly still alive.
)

echo Starting Phantom in a new console window...
start "Phantom Runtime" ".venv\Scripts\python.exe" run_phantom.py --config phantom.config.ini

echo Waiting for startup to settle...
timeout /t 5 /nobreak >nul

echo.
echo ============================================================
echo Phantom health check
echo ============================================================
".venv\Scripts\python.exe" health_check.py --config phantom.config.ini
set HEALTH_EXIT=%errorlevel%

if %HEALTH_EXIT%==0 (
    echo STATUS: HEALTHY
) else if %HEALTH_EXIT%==1 (
    echo STATUS: DEGRADED
) else (
    echo STATUS: FAILED
    echo Check the new "Phantom Runtime" console window and
    echo logs\ for the underlying error.
)

exit /b %HEALTH_EXIT%
