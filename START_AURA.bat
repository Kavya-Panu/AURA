@echo off
setlocal
cd /d "%~dp0software"
python run_aura_brain.py
if errorlevel 1 pause
