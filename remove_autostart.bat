@echo off
REM Unregister the automatic start-at-logon task created by setup_autostart.bat.
setlocal
schtasks /Delete /F /TN "SessionEdgeAuto"
if %ERRORLEVEL%==0 (
  echo Session Edge auto-start removed. It will no longer start at logon.
) else (
  echo No auto-start task found (nothing to remove), or run as Administrator.
)
echo.
pause
endlocal
