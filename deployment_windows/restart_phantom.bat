@echo off
REM ============================================================
REM Phantom restart script (Windows).
REM
REM Calls the approved stop process, confirms shutdown completed,
REM calls the approved start process, then verifies health.
REM Contains no logic of its own beyond sequencing the other
REM approved scripts -- never bypasses stop_phantom.bat/
REM start_phantom.bat's own safety checks.
REM ============================================================
setlocal
cd /d "%~dp0"

echo ============================================================
echo Phantom restart: step 1/3 -- stop
echo ============================================================
call stop_phantom.bat
if errorlevel 1 (
    echo FAILED: stop_phantom.bat did not complete cleanly. Refusing
    echo         to start a new instance while the old one's state is
    echo         uncertain. Investigate manually.
    exit /b 1
)

if exist "state\phantom.pid" (
    echo FAILED: state\phantom.pid still exists after stop_phantom.bat
    echo         reported success. Refusing to start a new instance.
    exit /b 1
)
echo Shutdown confirmed.

echo ============================================================
echo Phantom restart: step 2/3 -- start
echo ============================================================
call start_phantom.bat
set START_EXIT=%errorlevel%

echo ============================================================
echo Phantom restart: step 3/3 -- health verification
echo ============================================================
echo start_phantom.bat's own health check already ran above; its
echo exit code is this script's exit code.
exit /b %START_EXIT%
