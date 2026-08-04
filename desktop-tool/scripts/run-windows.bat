@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo.
echo Click Live desktop-tool
echo.

set "PS1=%~dp0run-windows-setup.ps1"
set "PSEXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%PSEXE%" (
  echo [ERROR] PowerShell not found
  pause
  exit /b 1
)

if not exist "%PS1%" (
  echo [ERROR] Missing %PS1%
  pause
  exit /b 1
)

"%PSEXE%" -ExecutionPolicy Bypass -File "%PS1%" %*
set ERR=%ERRORLEVEL%

if %ERR% NEQ 0 (
  echo.
  echo [ERROR] Failed with code %ERR%
  pause
)

exit /b %ERR%
