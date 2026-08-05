@echo off
echo Building Click Live Automation Tool (.NET Core Native WPF)...
dotnet build -c Release
if %ERRORLEVEL% NEQ 0 (
    echo Build failed!
    pause
    exit /b %ERRORLEVEL%
)

echo Publishing single-file executable for Windows x64...
dotnet publish -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -o ./dist

echo Build and Publish successful! Executable is located in ./dist/AutomationDotNet.exe
pause
