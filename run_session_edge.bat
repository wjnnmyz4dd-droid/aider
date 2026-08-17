@echo off
REM ===================================================================
REM  Session Edge - automatic DEMO launcher (double-click friendly)
REM
REM  Prerequisites (one time):
REM    1. MetaTrader 5 terminal open and logged into a DEMO account
REM    2. pip install MetaTrader5 pandas numpy
REM
REM  This starts newsfeed + producer + manager together and wires them
REM  to the terminal's MQL5\Files\session_edge_bridge folder that the
REM  SessionEdgeExecutionEA reads. DEMO only. Ctrl+C stops everything.
REM
REM  NORMAL USE: just double-click this file. No arguments needed.
REM  The launcher connects to your running MT5 DEMO terminal, identifies the
REM  account, and (on the FIRST run for that account) captures + PINS your
REM  starting capital automatically. Every later start reuses that pinned value,
REM  so a drawdown can never weaken your max-loss floor. Running it also attests
REM  the FTMO 2-Step Swing profile (--ftmo-verified). The DEMO-account safety
REM  check is always enforced: it refuses anything but a connected demo account.
REM
REM  FIRST-RUN OVERRIDE (optional): if your true FTMO starting capital differs
REM  from the current demo balance, pin it explicitly the first time:
REM     run_session_edge.bat --initial-balance 50000
REM  To correct an already-pinned value later, reset it deliberately:
REM     run_session_edge.bat --reinitialize 50000
REM
REM  Add symbols / sessions if you like (defaults: EURUSD, LONDON):
REM     run_session_edge.bat --symbols EURUSD,GBPUSD --sessions LONDON,NEW_YORK
REM     run_session_edge.bat --sessions ALL
REM  Session selection stays inside Session Edge; the EA never chooses sessions.
REM ===================================================================
setlocal
cd /d "%~dp0"
python -m forex_swing_orb.runtime.launcher --ftmo-verified %*
echo.
echo Session Edge launcher exited. Press any key to close.
pause >nul
endlocal
