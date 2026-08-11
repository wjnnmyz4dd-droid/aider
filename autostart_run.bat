@echo off
REM Internal runner used by the auto-start scheduled task (no pause, waits for
REM the MT5 terminal for up to 15 minutes so it survives starting at logon).
REM You normally don't run this directly - use setup_autostart.bat once.
REM
REM REQUIRED: edit INITIAL_BALANCE below to your true FTMO challenge starting
REM capital. It is pinned and never read from the live account, so a drawdown
REM can never weaken your max-loss floor.
setlocal
set INITIAL_BALANCE=50000
cd /d "%~dp0"
python -m forex_swing_orb.runtime.launcher --ftmo-verified --wait-for-terminal 900 --initial-balance %INITIAL_BALANCE% %*
endlocal
