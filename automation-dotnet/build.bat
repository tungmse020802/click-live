@echo off
echo Building Click Live Automation Tool (.NET Core Native WPF)...
dotnet build -c Release -o ./dist
if %ERRORLEVEL% NEQ 0 (
    echo Build failed!
    pause
    exit /b %ERRORLEVEL%
)

echo Build successful! Executable is located in ./dist/AutomationDotNet.exe
pause
