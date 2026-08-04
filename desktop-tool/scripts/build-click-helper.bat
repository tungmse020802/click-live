@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set OUT=resources\bin\win32\click-helper.exe
if not exist "resources\bin\win32" mkdir "resources\bin\win32"

where go >nul 2>&1
if errorlevel 1 (
  echo [WARN] Go chua cai - bo qua build click-helper.exe
  echo        App se dung PowerShell helper neu khong co exe.
  echo        Cai Go: https://go.dev/dl/ roi chay lai script nay.
  exit /b 0
)

echo Building click-helper.exe ...
pushd click-helper
go build -trimpath -ldflags="-s -w" -o "..\%OUT%" .
set ERR=%ERRORLEVEL%
popd

if %ERR% NEQ 0 (
  echo [ERROR] go build failed
  exit /b %ERR%
)

echo OK: %OUT%
exit /b 0
