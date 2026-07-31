@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

echo.
echo Stopping Click Live desktop-tool ...
echo.

REM Free local API port 8795
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8795" ^| findstr "LISTENING"') do (
  echo   taskkill PID %%a ^(port 8795^)
  taskkill /F /PID %%a >nul 2>&1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$names = @('electron.exe','node.exe'); " ^
  "$pat = 'desktop-tool|click-live-desktop-tool'; " ^
  "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | " ^
  "Where-Object { $names -contains $_.Name -and $_.CommandLine -match $pat } | " ^
  "ForEach-Object { Write-Host ('  stop PID ' + $_.ProcessId + ' ' + $_.Name); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

timeout /t 2 /nobreak >nul
echo Done.
echo.
