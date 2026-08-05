@echo off
echo ========================================================
echo Packaging Click Live Desktop Tool for Distribution...
echo ========================================================

git pull origin main

echo.
echo 1. Building Standalone Native Executable (Self-Contained)...
dotnet publish -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o ./ClickLiveDesktopTool-Package

if %ERRORLEVEL% NEQ 0 (
    echo Publish failed!
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo 2. Creating 1-Click Install & Run helper scripts inside package...

(
echo @echo off
echo Creating Desktop Shortcut...
echo set "APP_PATH=%%~dp0AutomationDotNet.exe"
echo powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $desktop = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop); $s = $ws.CreateShortcut((Join-Path $desktop 'Click Live Desktop Tool.lnk')); $s.TargetPath = '%%APP_PATH%%'; $s.Save()"
echo echo Desktop Shortcut Created Successfully!
echo pause
) > ./ClickLiveDesktopTool-Package/Install-Desktop-Shortcut.bat

(
echo @echo off
echo Launching Click Live Desktop Tool...
echo start "" "%%~dp0AutomationDotNet.exe"
) > ./ClickLiveDesktopTool-Package/Run.bat

echo.
echo 3. Compressing folder into ClickLiveDesktopTool-Windows.zip...
if exist ClickLiveDesktopTool-Windows.zip del /f /q ClickLiveDesktopTool-Windows.zip
powershell -Command "Compress-Archive -Path ./ClickLiveDesktopTool-Package/* -DestinationPath ./ClickLiveDesktopTool-Windows.zip -Force"

echo.
echo ========================================================
echo PACKAGING SUCCESSFUL!
echo Distribution zip created: ./ClickLiveDesktopTool-Windows.zip
echo Folder created: ./ClickLiveDesktopTool-Package/
echo ========================================================
pause
