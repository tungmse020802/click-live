@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

echo.
echo Click Live desktop-tool — setup all-in-one
echo.

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] powershell.exe not found
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-windows-setup.ps1" %*
set ERR=%ERRORLEVEL%

if %ERR% NEQ 0 (
  echo.
  echo [ERROR] Setup/run failed with code %ERR%
)

exit /b %ERR%
