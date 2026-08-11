@echo off
REM Internal runner used by the auto-start scheduled task (no pause, waits for
REM the MT5 terminal for up to 15 minutes so it survives starting at logon).
REM You normally don't run this directly - use setup_autostart.bat once.
REM
REM REQUIRED: set INITIAL_BALANCE to your true FTMO challenge starting capital
REM (e.g. 50000). There is NO default — leaving it blank fails closed and does
REM NOT start trading. It is pinned and never read from the live account, so a
REM drawdown can never weaken your max-loss floor.
setlocal
set "INITIAL_BALANCE="
REM ^-- edit the line below, e.g.  set "INITIAL_BALANCE=50000"
cd /d "%~dp0"
if "%INITIAL_BALANCE%"=="" (
  echo ERROR: edit autostart_run.bat and set INITIAL_BALANCE to your challenge
  echo starting capital before enabling auto-start. Nothing started.
  exit /b 2
)
python -m forex_swing_orb.runtime.launcher --ftmo-verified --wait-for-terminal 900 --initial-balance %INITIAL_BALANCE% %*
endlocal
