@echo off
echo ========================================================
echo Checking .NET Environment...
echo ========================================================

dotnet --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo .NET Environment is already installed!
) else (
    echo .NET Environment NOT found. Automatically downloading and installing .NET 8 Desktop Runtime from Microsoft...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://download.visualstudio.microsoft.com/download/pr/49520448-b4b6-4444-a55d-2226871a2a4b/0d6df6cf2a304e25a228fa48682fa057/windowsdesktop-runtime-8.0.12-win-x64.exe' -OutFile '$env:TEMP\dotnet-installer.exe'"
    echo Installing .NET 8 Runtime silently...
    start /wait %TEMP%\dotnet-installer.exe /quiet /norestart
    echo .NET 8 Runtime installed successfully!
)

echo.
echo Launching application installer...
call install-windows.bat
