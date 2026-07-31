@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

echo.
echo Stopping Click Live desktop-tool ...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$pat = 'click-live\\desktop-tool|click-live-desktop-tool'; " ^
  "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | " ^
  "Where-Object { $_.CommandLine -match $pat -and ($_.Name -eq 'electron.exe' -or $_.Name -eq 'node.exe') } | " ^
  "ForEach-Object { Write-Host ('  stop PID ' + $_.ProcessId + ' ' + $_.Name); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

timeout /t 1 /nobreak >nul
echo Done.
echo.
pause
