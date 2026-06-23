@echo off
setlocal

tasklist /FI "IMAGENAME eq ios.exe" 2>NUL | find /I "ios.exe" >NUL
if errorlevel 1 (
  echo No ios.exe process is running.
  exit /B 0
)

echo Stopping all ios.exe tunnel and port-forward processes...
taskkill /F /T /IM ios.exe >NUL
if errorlevel 1 (
  echo Failed to stop ios.exe. Run this script as Administrator.
  exit /B 1
)

echo All ios.exe processes stopped.
exit /B 0
