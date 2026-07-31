@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo.
echo Click Live desktop-tool
echo.

where git >nul 2>&1
if not errorlevel 1 (
  echo git pull ...
  git -C "%~dp0..\.." pull --ff-only
  echo.
)

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js not installed. Run scripts\install-windows.bat first.
  echo.
  pause
  exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm not found. Reinstall Node.js from https://nodejs.org
  echo.
  pause
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" copy /Y ".env.example" ".env" >nul
  echo [INFO] Created .env — chi can DESKTOP_TOOL_QUEUE_URL. Login user trong app.
  echo.
)

if not exist "node_modules\electron\package.json" (
  echo node_modules not found - running npm install ...
  echo This may take a few minutes on first run.
  echo.
  call npm install
  if errorlevel 1 (
    echo.
    echo [ERROR] npm install failed.
    pause
    exit /b 1
  )
  echo.
  echo npm install OK.
  echo.
)

echo Starting desktop-tool ...
echo.
call npm start
set ERR=%ERRORLEVEL%

echo.
if %ERR% NEQ 0 (
  echo [ERROR] npm start failed with code %ERR%
) else (
  echo Desktop-tool da thoat.
)
echo.
pause
exit /b %ERR%
