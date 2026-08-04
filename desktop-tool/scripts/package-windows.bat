@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo.
echo Build Click Live Desktop Tool (Windows portable + installer)
echo.

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js / npm chua cai. Cai Node LTS roi chay lai.
  pause
  exit /b 1
)

echo npm install ...
call npm install
if errorlevel 1 goto :fail

call "%~dp0build-click-helper.bat"
echo.

echo npm run dist:win ...
call npm run dist:win
if errorlevel 1 goto :fail

echo.
echo Xong. File trong desktop-tool\dist\
dir /b dist\*.exe 2>nul
echo.
echo Dat file .env cung thu muc voi .exe portable (copy tu .env.example):
echo   copy .env.example dist\ClickLiveDesktopTool-*-portable.exe
echo   (sua: dat .env cung folder khi giai nen portable, hoac cung folder setup cai)
echo.
pause
exit /b 0

:fail
echo.
echo [ERROR] Build that bai.
pause
exit /b 1
