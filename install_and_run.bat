@echo off
:: ─────────────────────────────────────────────────────────────────────────────
:: install_and_run.bat
:: One-shot: create venv → install deps → launch GestureFlow  (Windows)
:: ─────────────────────────────────────────────────────────────────────────────

echo.
echo   ╔══════════════════════════════════════╗
echo   ║        GestureFlow  Installer        ║
echo   ╚══════════════════════════════════════╝
echo.

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: python not found. Install Python 3.9+ from python.org
    pause
    exit /b 1
)

python --version

:: Create venv
if not exist ".venv" (
    echo   Creating virtual environment ...
    python -m venv .venv
)

:: Activate
call .venv\Scripts\activate.bat

:: Upgrade pip
pip install --upgrade pip -q

:: Install dependencies
echo   Installing dependencies (may take 2-3 minutes) ...
pip install -r requirements.txt -q

echo.
echo   Installation complete! Launching GestureFlow ...
echo.

python main.py

pause
