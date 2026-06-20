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

pip install opencv-python numpy pillow pytesseract

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install packages.
    pause
    exit /b 1
)

echo.
echo === Installing Tesseract OCR engine ===
echo.
echo Checking if Tesseract is installed...
tesseract --version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Tesseract not found in PATH.
    echo.
    echo Please install Tesseract manually:
    echo   1. Download: https://github.com/UB-Mannheim/tesseract/wiki
    echo      ^(choose tesseract-ocr-w64-setup-*.exe^)
    echo   2. During install, tick "Add to PATH"
    echo   3. Re-run this script after installation
    echo.
    echo OCR treasure detection will fall back to color/pixel heuristic without Tesseract.
    echo.
) else (
    for /f "tokens=*" %%i in ('tesseract --version 2^>^&1 ^| findstr /i "tesseract"') do echo [OK] %%i
)

echo.
echo === Verifying Python packages ===
python -c "import cv2; import numpy; from PIL import Image; import pytesseract; print('[OK] opencv-python', cv2.__version__); print('[OK] numpy', numpy.__version__); print('[OK] Pillow', Image.__version__); print('[OK] pytesseract', pytesseract.__version__)"

if errorlevel 1 (
    echo [ERROR] Verification failed.
    pause
    exit /b 1
)

echo.
echo === Setup complete! Python dependencies are ready. ===
pause
