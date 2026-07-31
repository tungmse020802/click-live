@echo off
setlocal
cd /d "%~dp0.."

where node >nul 2>&1
if errorlevel 1 (
  echo Node.js chua cai. Chay scripts\install-windows.bat truoc.
  pause
  exit /b 1
)

if not exist "node_modules\electron\package.json" (
  echo Chua npm install. Chay scripts\install-windows.bat truoc.
  pause
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" copy /Y ".env.example" ".env" >nul
  echo Da tao .env - hay sua DESKTOP_TOOL_PULL_TOKEN roi chay lai.
)

echo Starting Click Live desktop-tool ...
npm start

endlocal
