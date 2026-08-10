@echo off
REM Internal runner used by the auto-start scheduled task (no pause, waits for
REM the MT5 terminal for up to 15 minutes so it survives starting at logon).
REM You normally don't run this directly - use setup_autostart.bat once.
setlocal
cd /d "%~dp0"
python -m forex_swing_orb.runtime.launcher --ftmo-verified --wait-for-terminal 900 %*
endlocal
