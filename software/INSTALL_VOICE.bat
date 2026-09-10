@echo off
cd /d "%~dp0"
echo Installing AURA voice dependencies...
python -m pip install -r requirements_brain.txt --upgrade
if errorlevel 1 (
    echo.
    echo Installation failed. Copy the error and send it to ChatGPT.
    pause
    exit /b 1
)
echo.
echo Voice dependencies installed successfully.
echo The Whisper model downloads automatically on first startup.
pause
