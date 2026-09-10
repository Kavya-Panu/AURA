@echo off
cd /d "%~dp0"
python run_aura_brain.py --voice-mode wake
if errorlevel 1 pause
