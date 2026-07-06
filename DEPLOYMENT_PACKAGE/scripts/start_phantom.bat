@echo off
REM Phantom startup wrapper (Windows). Loads the profile's env file (if
REM present next to this script's ..\config\ directory) as real process
REM environment variables, then runs start_phantom.py.
REM
REM Usage: start_phantom.bat [DEV|PAPER|LIVE]
REM Default profile: DEV

setlocal enabledelayedexpansion

set PROFILE=%1
if "%PROFILE%"=="" set PROFILE=DEV

set ENVFILE=%~dp0..\config\%PROFILE%.env
if not exist "%ENVFILE%" (
    echo No env file found at %ENVFILE% - copy config\%PROFILE%.env.template to config\%PROFILE%.env and fill it in first.
    exit /b 2
)

for /f "usebackq tokens=1,* delims==" %%A in ("%ENVFILE%") do (
    set line=%%A
    if not "!line:~0,1!"=="#" if not "!line!"=="" (
        set "%%A=%%B"
    )
)

set PHANTOM_PROFILE=%PROFILE%
python "%~dp0start_phantom.py"
exit /b %errorlevel%
