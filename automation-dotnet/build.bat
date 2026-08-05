@echo off
echo Automatically pulling latest code from Git...
git pull origin main

echo.
echo Publishing Click Live Automation Tool (.NET Core Native WPF)...

dotnet publish -c Release -r win-x64 --self-contained false -o ./dist
if %ERRORLEVEL% NEQ 0 (
    echo Publish failed!
    pause
    exit /b %ERRORLEVEL%
)

echo ========================================================
echo Build & Publish successful! Files in ./dist:
echo ========================================================
dir /b ./dist
echo ========================================================
echo Running: Mở dist\AutomationDotNet.exe để chạy ứng dụng.
pause
