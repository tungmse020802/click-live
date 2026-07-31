@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
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

echo Stopping old desktop-tool (neu con chay nen)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$pat='click-live\\desktop-tool|click-live-desktop-tool'; Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match $pat -and ($_.Name -eq 'electron.exe' -or $_.Name -eq 'node.exe') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 1 /nobreak >nul
echo.

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
