@echo off
echo Building Standalone Single-File Executable (Self-Contained)...

dotnet publish -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o ./dist-standalone
if %ERRORLEVEL% NEQ 0 (
    echo Standalone build failed!
    pause
    exit /b %ERRORLEVEL%
)

echo ========================================================
echo Standalone publish successful!
echo File executable: ./dist-standalone/AutomationDotNet.exe
echo ========================================================
pause
