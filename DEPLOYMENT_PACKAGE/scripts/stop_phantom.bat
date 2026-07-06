@echo off
REM Phantom stop wrapper (Windows). If start_phantom.py is running as a
REM foreground console process (PAPER profile's continuous loop), Ctrl+C
REM in that console already triggers a graceful stop_all() shutdown - see
REM start_phantom.py's own signal handler. This script is for the case
REM where Phantom was registered as a Windows Service (see
REM VPS_SETUP_GUIDE.md SS3); it stops that service by name.
REM
REM Usage: stop_phantom.bat <ServiceName>

setlocal

set SERVICE_NAME=%1
if "%SERVICE_NAME%"=="" (
    echo Usage: stop_phantom.bat ^<ServiceName^>
    echo If Phantom is running in a foreground console instead of a
    echo registered Windows Service, press Ctrl+C in that console for a
    echo graceful stop_all^(^) shutdown instead.
    exit /b 2
)

nssm stop %SERVICE_NAME%
if errorlevel 1 (
    echo nssm stop failed or nssm not installed - trying sc.exe.
    sc stop %SERVICE_NAME%
)
exit /b %errorlevel%
