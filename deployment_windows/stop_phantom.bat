@echo off
REM ============================================================
REM Phantom stop script (Windows).
REM
REM Stops ONLY the single Phantom process recorded in
REM state\phantom.pid -- never a broad `taskkill /IM python.exe`,
REM which would kill every Python process on the machine,
REM including unrelated ones. Graceful shutdown first (a plain
REM `taskkill /PID` without /F), bounded wait, then forced
REM termination (`taskkill /F /PID`) only if graceful shutdown
REM did not stop it within the bound. Logs and state files are
REM never deleted by this script.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set PIDFILE=state\phantom.pid
set GRACEFUL_WAIT_SECONDS=10

if not exist "%PIDFILE%" (
    echo No %PIDFILE% found -- Phantom does not appear to be running.
    exit /b 0
)

set /p PHANTOM_PID=<"%PIDFILE%"
if "%PHANTOM_PID%"=="" (
    echo %PIDFILE% is empty -- removing stale pid file.
    del "%PIDFILE%" >nul 2>nul
    exit /b 0
)

REM -- Confirm the recorded pid is actually a python.exe process
REM    before touching it at all -- refuses to act on a pid that has
REM    been reused by an unrelated process since the pid file was
REM    written (e.g. after a reboot).
set FOUND_PYTHON=0
for /f "tokens=2 delims=," %%A in ('tasklist /FI "PID eq %PHANTOM_PID%" /FI "IMAGENAME eq python.exe" /FO CSV /NH 2^>nul') do (
    set FOUND_PYTHON=1
)
if "%FOUND_PYTHON%"=="0" (
    echo pid %PHANTOM_PID% in %PIDFILE% is not a running python.exe process
    echo ^(stale pid file, likely from a previous reboot^). Removing the
    echo stale pid file without touching any process.
    del "%PIDFILE%" >nul 2>nul
    exit /b 0
)

echo Stopping Phantom (pid %PHANTOM_PID%) -- graceful shutdown...
taskkill /PID %PHANTOM_PID% >nul 2>nul

set /a ELAPSED=0
:WAIT_LOOP
tasklist /FI "PID eq %PHANTOM_PID%" /FO CSV /NH 2>nul | findstr /I "%PHANTOM_PID%" >nul
if errorlevel 1 (
    echo Phantom stopped gracefully after %ELAPSED% second(s).
    del "%PIDFILE%" >nul 2>nul
    exit /b 0
)
if %ELAPSED% GEQ %GRACEFUL_WAIT_SECONDS% goto :FORCE_KILL
timeout /t 1 /nobreak >nul
set /a ELAPSED+=1
goto :WAIT_LOOP

:FORCE_KILL
echo Graceful shutdown did not complete within %GRACEFUL_WAIT_SECONDS%
echo second(s) -- forcing termination of pid %PHANTOM_PID% only.
taskkill /F /PID %PHANTOM_PID% >nul 2>nul
tasklist /FI "PID eq %PHANTOM_PID%" /FO CSV /NH 2>nul | findstr /I "%PHANTOM_PID%" >nul
if errorlevel 1 (
    echo Phantom force-stopped.
    del "%PIDFILE%" >nul 2>nul
    exit /b 0
) else (
    echo FAILED: pid %PHANTOM_PID% is still running after a forced
    echo         termination attempt. Investigate manually -- the
    echo         pid file was NOT removed.
    exit /b 1
)
