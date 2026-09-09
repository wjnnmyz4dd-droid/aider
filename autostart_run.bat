@echo off
REM Internal runner used by the auto-start scheduled task (no pause, waits for
REM the MT5 terminal for up to 15 minutes so it survives starting at logon).
REM You normally don't run this directly - use setup_autostart.bat once.
REM
REM OPTIONAL: set INITIAL_BALANCE to your true FTMO challenge starting capital
REM (e.g. 50000) ONLY if it differs from the current demo balance. If left blank,
REM the launcher captures + PINS the current DEMO balance on the first run for the
REM account and reuses that pinned value on every restart (a drawdown never weakens
REM your max-loss floor). It is never re-read from the live account after pinning.
setlocal
set "INITIAL_BALANCE="
REM ^-- optional: e.g.  set "INITIAL_BALANCE=50000"
cd /d "%~dp0"
if "%INITIAL_BALANCE%"=="" (
  python -m forex_swing_orb.runtime.launcher --ftmo-verified --wait-for-terminal 900 %*
) else (
  python -m forex_swing_orb.runtime.launcher --ftmo-verified --wait-for-terminal 900 --initial-balance %INITIAL_BALANCE% %*
)
endlocal
