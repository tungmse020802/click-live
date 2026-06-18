@echo off
setlocal

echo === WDA Controller - Python Setup for Windows ===
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ from https://www.python.org/downloads/
    echo         Make sure to tick "Add Python to PATH" during installation.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do echo [OK] Found %%i

REM Check pip
pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip not found. Try: python -m ensurepip
    pause
    exit /b 1
)

echo [OK] pip found
echo.
echo Installing required packages...
echo.

pip install opencv-python numpy

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install packages.
    pause
    exit /b 1
)

echo.
echo === Verifying installation ===
python -c "import cv2; import numpy; print('[OK] opencv-python', cv2.__version__); print('[OK] numpy', numpy.__version__)"

if errorlevel 1 (
    echo [ERROR] Verification failed.
    pause
    exit /b 1
)

echo.
echo === Setup complete! Python dependencies are ready. ===
pause
