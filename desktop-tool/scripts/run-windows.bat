@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo.
echo Click Live desktop-tool
echo.

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js not installed. Run scripts\install-windows.bat first.
  echo.
  pause
  exit /b 1
)

if not exist "node_modules\electron\package.json" (
  echo [ERROR] Run npm install first - scripts\install-windows.bat
  echo.
  pause
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" copy /Y ".env.example" ".env" >nul
  echo [WARN] Created .env - set DESKTOP_TOOL_PULL_TOKEN then rerun.
  echo.
)

echo Starting desktop-tool ...
echo.
call npm start
set ERR=%ERRORLEVEL%

echo.
if %ERR% NEQ 0 (
  echo [ERROR] npm start failed with code %ERR%
  pause
  exit /b %ERR%
)

endlocal
