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
REM  Choose sessions ONCE and they are remembered (persisted per machine):
REM     run_session_edge.bat --sessions ALL
REM     run_session_edge.bat --sessions LONDON,NEW_YORK
REM  After that, a plain double-click reuses your saved selection — no flags, no env
REM  edits. First run with no --sessions defaults to LONDON. Passing --sessions again
REM  changes the saved default. Add symbols the same way (default EURUSD):
REM     run_session_edge.bat --symbols EURUSD,GBPUSD
REM  Session selection stays inside Session Edge (single Python authority); the EA
REM  never chooses sessions and has no manual lot control — sizing is autonomous (PR-3J).
REM ===================================================================
setlocal
cd /d "%~dp0"
python -m forex_swing_orb.runtime.launcher --ftmo-verified %*
echo.
echo Session Edge launcher exited. Press any key to close.
pause >nul
endlocal
