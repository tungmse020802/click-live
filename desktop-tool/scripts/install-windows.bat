@echo off
setlocal
cd /d "%~dp0.."

echo.
echo Click Live desktop-tool - Windows setup
echo.

where powershell >nul 2>&1
if errorlevel 1 (
  echo PowerShell khong tim thay. Can Windows PowerShell 5.1+
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-windows.ps1" %*
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" (
  echo.
  echo Cai dat that bai (ma loi %ERR%).
  pause
  exit /b %ERR%
)

endlocal
