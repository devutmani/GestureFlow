@echo off
:: ─────────────────────────────────────────────────────────────────────────────
:: QUICK_INSTALL_WINDOWS.bat
:: Installs all GestureFlow dependencies correctly on Windows.
:: Handles the common pyaudio build failure automatically.
:: Run from the GestureFlow directory inside your activated venv.
:: ─────────────────────────────────────────────────────────────────────────────

echo.
echo   GestureFlow — Windows Dependency Installer
echo   ============================================
echo.

:: Upgrade pip first
python -m pip install --upgrade pip -q

:: Core packages (always succeed)
echo   [1/4] Installing core packages...
pip install opencv-python mediapipe numpy pyautogui Pillow screen-brightness-control colorama -q
if %errorlevel% neq 0 (
    echo   ERROR: Core package install failed.
    pause & exit /b 1
)

:: Windows audio
echo   [2/4] Installing Windows audio packages...
pip install pycaw comtypes -q

:: SpeechRecognition
echo   [3/4] Installing SpeechRecognition...
pip install SpeechRecognition -q

:: PyAudio — try normal install first, then pipwin fallback
echo   [4/4] Installing PyAudio...
pip install pyaudio -q
if %errorlevel% neq 0 (
    echo   PyAudio direct install failed. Trying pipwin...
    pip install pipwin -q
    pipwin install pyaudio
    if %errorlevel% neq 0 (
        echo.
        echo   WARNING: PyAudio could not be installed automatically.
        echo   Voice commands will be disabled.
        echo   To fix manually:
        echo     1. Go to: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio
        echo     2. Download the .whl matching your Python version
        echo     3. pip install ^<downloaded_file^>.whl
        echo.
        echo   GestureFlow will still work — just without voice.
        echo   Set VOICE_ENABLED = False in config/settings.py to hide the warning.
    )
)

echo.
echo   Installation complete!
echo   Run:  python main.py
echo.
pause
