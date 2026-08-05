@echo off
echo ========================================================
echo Installing Click Live Desktop Tool (.NET Core Native)...
echo ========================================================

git pull origin main

echo.
echo Building latest standalone application...
dotnet publish -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o ./dist-standalone

if %ERRORLEVEL% NEQ 0 (
    echo Build failed! Cannot proceed with installation.
    pause
    exit /b %ERRORLEVEL%
)

set "INSTALL_DIR=%LOCALAPPDATA%\ClickLiveDesktopTool"
echo.
echo Installing to: %INSTALL_DIR%
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

copy /Y ".\dist-standalone\AutomationDotNet.exe" "%INSTALL_DIR%\ClickLiveDesktopTool.exe"

echo.
echo Creating Desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $desktop = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop); $s = $ws.CreateShortcut((Join-Path $desktop 'Click Live Desktop Tool.lnk')); $s.TargetPath = '%INSTALL_DIR%\ClickLiveDesktopTool.exe'; $s.Save()"

echo.
echo ========================================================
echo INSTALLATION COMPLETED SUCCESSFULLY!
echo Desktop Shortcut 'Click Live Desktop Tool' created.
echo ========================================================
pause
