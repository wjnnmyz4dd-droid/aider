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
REM  On first launch you will be asked to type VERIFIED to attest the
REM  FTMO 2-Step Swing profile. To skip the prompt, run:
REM     run_session_edge.bat --ftmo-verified
REM ===================================================================
setlocal
cd /d "%~dp0"
python -m forex_swing_orb.runtime.launcher %*
echo.
echo Session Edge launcher exited. Press any key to close.
pause >nul
endlocal
