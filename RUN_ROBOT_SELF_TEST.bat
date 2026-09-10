@echo off
setlocal
cd /d "%~dp0software"
title AURA Robot Self-Test
echo Close AURA and Arduino Serial Monitor before continuing.
echo.
python robot_self_test.py
echo.
pause
endlocal
