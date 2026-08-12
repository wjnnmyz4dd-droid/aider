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
REM  This launcher runs fully automatically (no prompts). Running it
REM  attests the FTMO 2-Step Swing profile for this DEMO run (--ftmo-verified
REM  below). The DEMO-account safety check is always enforced: the launcher
REM  refuses to start on anything but a connected demo account.
REM
REM  REQUIRED: pass your true FTMO challenge starting capital, e.g.
REM     run_session_edge.bat --initial-balance 50000
REM  It is pinned and never read from the live account (so a drawdown can
REM  never weaken your max-loss floor). Add symbols if you like:
REM     run_session_edge.bat --initial-balance 50000 --symbols EURUSD,GBPUSD
REM
REM  Choose which trading sessions to run (default: LONDON). Any one, a
REM  combination, or ALL of SYDNEY,TOKYO,LONDON,NEW_YORK:
REM     run_session_edge.bat --initial-balance 50000 --sessions LONDON,NEW_YORK
REM     run_session_edge.bat --initial-balance 50000 --sessions ALL
REM  Session selection stays inside Session Edge; the EA never chooses sessions.
REM ===================================================================
setlocal
cd /d "%~dp0"
python -m forex_swing_orb.runtime.launcher --ftmo-verified %*
echo.
echo Session Edge launcher exited. Press any key to close.
pause >nul
endlocal
