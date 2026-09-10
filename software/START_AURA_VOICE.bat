@echo off
cd /d "%~dp0"
python run_aura_brain.py
if errorlevel 1 pause
