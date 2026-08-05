@echo off
echo Building Click Live Desktop Tool Installer...
git pull origin main

dotnet publish -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o ./dist-standalone

if %ERRORLEVEL% NEQ 0 (
    echo Publish failed!
    pause
    exit /b %ERRORLEVEL%
)

if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" setup.iss
    echo.
    echo Inno Setup Installer created: .\installer\ClickLiveDesktopTool-Setup.exe
    pause
    exit /b 0
)

echo.
echo Executing 1-Click Automated Installer script...
call install-windows.bat
