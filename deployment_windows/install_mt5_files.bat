@echo off
REM ============================================================
REM Phantom MT5 file installer (Windows).
REM
REM Locates (or asks for) the active MT5 data folder, copies
REM PhantomBridgeEA.mq5 into MQL5\Experts\Phantom\ and
REM PhantomBridgeEA.set into MQL5\Presets\Phantom\, taking a
REM timestamped backup of any file it would otherwise overwrite.
REM Does NOT compile the .mq5 -- that step can only happen inside
REM MetaEditor on the real Windows/MT5 installation; this script
REM prints the exact steps to do it and does not claim to have
REM done it itself.
REM
REM Usage: install_mt5_files.bat ["C:\path\to\MT5\data\folder"]
REM   If no path is given, this script tries to auto-detect a
REM   single MetaQuotes terminal data folder under
REM   %APPDATA%\MetaQuotes\Terminal\ and asks you to confirm/choose
REM   if more than one (or none) is found.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set SOURCE_DIR=%~dp0..\mt5
if not exist "%SOURCE_DIR%\PhantomBridgeEA.mq5" (
    echo FAILED: %SOURCE_DIR%\PhantomBridgeEA.mq5 not found.
    exit /b 2
)
if not exist "%SOURCE_DIR%\PhantomBridgeEA.set" (
    echo FAILED: %SOURCE_DIR%\PhantomBridgeEA.set not found.
    exit /b 2
)

set MT5_DATA_DIR=%~1
if not "%MT5_DATA_DIR%"=="" goto :GOT_DIR

echo No MT5 data folder was given on the command line.
echo Searching %APPDATA%\MetaQuotes\Terminal\ for terminal installs...

set FOUND_COUNT=0
set FOUND_DIR=
if exist "%APPDATA%\MetaQuotes\Terminal" (
    for /d %%D in ("%APPDATA%\MetaQuotes\Terminal\*") do (
        if exist "%%D\MQL5" (
            set /a FOUND_COUNT+=1
            set FOUND_DIR=%%D
            echo   Found: %%D
        )
    )
)

if %FOUND_COUNT% EQU 0 (
    echo No MT5 terminal data folder was auto-detected.
    set /p MT5_DATA_DIR=Enter the full path to your MT5 data folder ^(the one containing MQL5\^):
    if "!MT5_DATA_DIR!"=="" (
        echo FAILED: no path given.
        exit /b 2
    )
    set MT5_DATA_DIR=!MT5_DATA_DIR!
    goto :GOT_DIR
)

if %FOUND_COUNT% GTR 1 (
    echo More than one MT5 terminal data folder was found. Re-run this
    echo script with the correct one as an argument, e.g.:
    echo   install_mt5_files.bat "%FOUND_DIR%"
    exit /b 2
)

echo Exactly one MT5 terminal data folder found: %FOUND_DIR%
set /p CONFIRM=Use this folder? [Y/n]:
if /i "%CONFIRM%"=="n" (
    echo Aborted -- re-run with the correct path as an argument.
    exit /b 1
)
set MT5_DATA_DIR=%FOUND_DIR%

:GOT_DIR
if not exist "%MT5_DATA_DIR%\MQL5" (
    echo FAILED: %MT5_DATA_DIR%\MQL5 does not exist -- this does not
    echo         look like a valid MT5 data folder.
    exit /b 2
)

set EXPERTS_DIR=%MT5_DATA_DIR%\MQL5\Experts\Phantom
set PRESETS_DIR=%MT5_DATA_DIR%\MQL5\Presets\Phantom
if not exist "%EXPERTS_DIR%" mkdir "%EXPERTS_DIR%"
if not exist "%PRESETS_DIR%" mkdir "%PRESETS_DIR%"

for /f "tokens=1-4 delims=/ " %%a in ('date /t') do set DATESTAMP=%%c%%a%%b
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set TIMESTAMP=%%a%%b
set BACKUP_SUFFIX=%DATESTAMP%_%TIMESTAMP%

if exist "%EXPERTS_DIR%\PhantomBridgeEA.mq5" (
    echo Existing PhantomBridgeEA.mq5 found -- backing it up first.
    copy /Y "%EXPERTS_DIR%\PhantomBridgeEA.mq5" "%EXPERTS_DIR%\PhantomBridgeEA.mq5.bak_%BACKUP_SUFFIX%" >nul
)
copy /Y "%SOURCE_DIR%\PhantomBridgeEA.mq5" "%EXPERTS_DIR%\PhantomBridgeEA.mq5" >nul
if errorlevel 1 (
    echo FAILED: could not copy PhantomBridgeEA.mq5 to %EXPERTS_DIR%.
    exit /b 2
)
echo Copied PhantomBridgeEA.mq5 to %EXPERTS_DIR%

if exist "%PRESETS_DIR%\PhantomBridgeEA.set" (
    echo Existing PhantomBridgeEA.set found -- backing it up first.
    copy /Y "%PRESETS_DIR%\PhantomBridgeEA.set" "%PRESETS_DIR%\PhantomBridgeEA.set.bak_%BACKUP_SUFFIX%" >nul
)
copy /Y "%SOURCE_DIR%\PhantomBridgeEA.set" "%PRESETS_DIR%\PhantomBridgeEA.set" >nul
if errorlevel 1 (
    echo FAILED: could not copy PhantomBridgeEA.set to %PRESETS_DIR%.
    exit /b 2
)
echo Copied PhantomBridgeEA.set to %PRESETS_DIR%

echo.
echo ============================================================
echo Files copied. Compilation is NOT done by this script -- it can
echo only happen inside MetaEditor on this real Windows/MT5
echo installation. Do this next:
echo.
echo   1. Open MetaEditor (from MT5: Tools ^> MetaQuotes Language Editor,
echo      or press F4 inside MT5).
echo   2. In MetaEditor's Navigator panel, expand Experts ^> Phantom
echo      and double-click PhantomBridgeEA.mq5 to open it.
echo   3. Press F7 (or the Compile toolbar button) to compile.
echo   4. Confirm the status/output window shows "0 error(s)" -- a
echo      PhantomBridgeEA.ex5 file will appear next to the .mq5 file
echo      in %EXPERTS_DIR% only once compilation succeeds.
echo   5. Back in MT5, refresh the Navigator panel (right-click ^>
echo      Refresh) so the compiled EA appears under
echo      Expert Advisors ^> Phantom ^> PhantomBridgeEA.
echo.
echo This script has NOT compiled the EA and has NOT verified MT5
echo connectivity -- both require the real MetaEditor/MT5 GUI, which
echo is outside what a batch script can do.
echo ============================================================
exit /b 0
