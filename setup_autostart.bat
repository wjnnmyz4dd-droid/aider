@echo off
REM ===================================================================
REM  Session Edge - register FULLY AUTOMATIC start at Windows logon.
REM
REM  Run this ONCE. After that, Session Edge (newsfeed + producer +
REM  manager) starts by itself every time you log in - no clicking.
REM  It waits up to 15 minutes for the MT5 terminal to be running, so
REM  it is fine if MT5 opens a bit after you log in.
REM
REM  Requirements (one time):
REM    1. pip install MetaTrader5 pandas numpy
REM    2. MT5 terminal set to open on startup, logged into your DEMO
REM       account (Tools -> Options, and/or add MT5 to Windows startup).
REM
REM  To stop auto-starting later: run remove_autostart.bat
REM ===================================================================
setlocal
schtasks /Create /F /SC ONLOGON /TN "SessionEdgeAuto" /TR "\"%~dp0autostart_run.bat\""
if %ERRORLEVEL%==0 (
  echo.
  echo Registered. Session Edge will start automatically at every logon.
  echo Make sure the MT5 terminal is also set to start with Windows and is
  echo logged into your DEMO account.
) else (
  echo.
  echo Could not register the task. Try running this file as Administrator
  echo ^(right-click -^> Run as administrator^).
)
echo.
pause
endlocal
