@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo ========================================
echo  Click Live desktop-tool - Windows setup
echo ========================================
echo.

set "PS1=%~dp0install-windows.ps1"
if not exist "%PS1%" (
  echo [ERROR] Missing file: %PS1%
  echo.
  pause
  exit /b 1
)

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] powershell.exe not found
  echo.
  pause
  exit /b 1
)

echo Running install-windows.ps1 ...
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set ERR=%ERRORLEVEL%

echo.
if %ERR% NEQ 0 (
  echo [ERROR] Install failed with code %ERR%
) else (
  echo [OK] Done.
)
echo.
pause
exit /b %ERR%
