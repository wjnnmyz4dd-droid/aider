@echo off
REM ============================================================
REM Phantom setup script (Windows).
REM
REM Prepares a clean Windows VPS to run Phantom: verifies Python,
REM creates a local virtual environment, installs dependencies,
REM verifies folders/configuration/write access, compiles the
REM runtime, and runs an import smoke test. Never trades, never
REM touches engine logic -- installation only.
REM
REM Expected layout (this file lives in deployment_windows\, a
REM sibling of phantom\ and mt5\ -- exactly what
REM phantom_windows_deployment.zip extracts to):
REM   C:\Phantom\phantom\...
REM   C:\Phantom\mt5\...
REM   C:\Phantom\deployment_windows\setup_phantom.bat   <- you are here
REM
REM Fails closed: any failed prerequisite stops the script
REM immediately with a clear message. Nothing after a failure runs.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo Phantom Setup
echo ============================================================

REM -- 1. Verify a supported 64-bit Python is on PATH. --------------
echo [1/8] Checking for Python...
where python >nul 2>nul
if errorlevel 1 (
    echo FAILED: python was not found on PATH.
    echo         Install Python 3.9+ 64-bit from https://www.python.org/downloads/windows/
    echo         and ensure "Add python.exe to PATH" was checked during install.
    goto :FAIL
)

for /f "tokens=2 delims= " %%V in ('python --version 2^>^&1') do set PYVER=%%V
echo         Found Python %PYVER%

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)"
if errorlevel 1 (
    echo FAILED: Python %PYVER% is below the minimum supported version (3.9).
    goto :FAIL
)

python -c "import struct,sys; raise SystemExit(0 if struct.calcsize('P') * 8 == 64 else 1)"
if errorlevel 1 (
    echo FAILED: Python %PYVER% is not 64-bit. Install the 64-bit Windows installer.
    goto :FAIL
)
echo         Python %PYVER% (64-bit) OK.

REM -- 2. Create the local virtual environment. ----------------------
echo [2/8] Creating virtual environment (.venv)...
if exist ".venv\Scripts\python.exe" (
    echo         .venv already exists, skipping creation.
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo FAILED: could not create virtual environment.
        goto :FAIL
    )
)
echo         Virtual environment OK.

REM -- 3. Upgrade pip safely (inside the venv only). -----------------
echo [3/8] Upgrading pip inside .venv...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo FAILED: pip upgrade failed.
    goto :FAIL
)
echo         pip upgrade OK.

REM -- 4. Install requirements.txt (stdlib-only; expected to be a --
REM       fast, empty-set no-op -- see requirements.txt's own header).
echo [4/8] Installing requirements.txt...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo FAILED: dependency installation failed.
    goto :FAIL
)
echo         Dependencies OK (Phantom's live runtime is standard-library-only).

REM -- 5. Verify required runtime folders exist. ---------------------
echo [5/8] Verifying required runtime folders...
if not exist "..\phantom\bridge" (
    echo FAILED: ..\phantom\bridge not found. Extract the full deployment
    echo         zip so phantom\ sits alongside deployment_windows\.
    goto :FAIL
)
if not exist "..\phantom\evidence_engine" (
    echo FAILED: ..\phantom\evidence_engine not found.
    goto :FAIL
)
if not exist "..\phantom\market_intelligence" (
    echo FAILED: ..\phantom\market_intelligence not found.
    goto :FAIL
)
if not exist "..\phantom\strategy_engine" (
    echo FAILED: ..\phantom\strategy_engine not found.
    goto :FAIL
)
if not exist "..\phantom\risk_engine" (
    echo FAILED: ..\phantom\risk_engine not found.
    goto :FAIL
)
if not exist "..\phantom\compliance_engine" (
    echo FAILED: ..\phantom\compliance_engine not found.
    goto :FAIL
)
if not exist "..\phantom\runtime" (
    echo FAILED: ..\phantom\runtime not found.
    goto :FAIL
)
if not exist "..\phantom\reliability" (
    echo FAILED: ..\phantom\reliability not found.
    goto :FAIL
)
if not exist "..\mt5\PhantomBridgeEA.mq5" (
    echo FAILED: ..\mt5\PhantomBridgeEA.mq5 not found.
    goto :FAIL
)
echo         All required runtime folders present.

REM -- 6. Verify required configuration exists. ----------------------
echo [6/8] Verifying configuration...
if not exist "phantom.config.ini" (
    echo FAILED: phantom.config.ini not found in deployment_windows\.
    echo         Copy config\phantom.config.template.ini to
    echo         deployment_windows\phantom.config.ini and edit it
    echo         (API key, allowed symbols, trading profile, etc.)
    echo         before running setup again.
    goto :FAIL
)
".venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, '.'); from config_loader import load_settings; from pathlib import Path; load_settings(Path('phantom.config.ini'))"
if errorlevel 1 (
    echo FAILED: phantom.config.ini failed validation ^(see error above^).
    goto :FAIL
)
echo         Configuration OK.

REM -- 7. Verify write access for logs/state, then compile. ----------
echo [7/8] Verifying write access and compiling...
".venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, '.'); from config_loader import load_settings; from pathlib import Path; s = load_settings(Path('phantom.config.ini')); [ (p.mkdir(parents=True, exist_ok=True), (p / '.setup_write_probe').write_text('ok'), (p / '.setup_write_probe').unlink()) for p in (s.log_dir, s.state_dir) ]"
if errorlevel 1 (
    echo FAILED: log_dir/state_dir are not writable. Check the paths in
    echo         phantom.config.ini's [logging] section and folder
    echo         permissions.
    goto :FAIL
)
".venv\Scripts\python.exe" -m compileall -q "..\phantom" "."
if errorlevel 1 (
    echo FAILED: compileall reported syntax errors -- see output above.
    goto :FAIL
)
echo         Write access and compile OK.

REM -- 8. Runtime import smoke test. ---------------------------------
echo [8/8] Running import smoke test...
".venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, '..'); sys.path.insert(0, '.'); from phantom.bridge.engine import BridgeEngine; from phantom.evidence_engine.engine import EvidenceEngine; from phantom.market_intelligence.engine import MarketIntelligenceEngine; from phantom.strategy_engine.engine import StrategyEngine; from phantom.risk_engine.engine import RiskEngine; from phantom.compliance_engine.engine import ComplianceEngine; from phantom.runtime.engine import RuntimeOrchestrator; from phantom.reliability.engine import ReliabilityEngine; print('import smoke test: all 8 required packages import cleanly')"
if errorlevel 1 (
    echo FAILED: import smoke test failed -- see error above.
    goto :FAIL
)

echo ============================================================
echo Phantom setup completed successfully.
echo Next: install_mt5_files.bat, then start_phantom.bat.
echo ============================================================
exit /b 0

:FAIL
echo ============================================================
echo PHANTOM SETUP FAILED -- see the message above. Nothing further
echo was run. Fix the issue and re-run setup_phantom.bat.
echo ============================================================
exit /b 1
