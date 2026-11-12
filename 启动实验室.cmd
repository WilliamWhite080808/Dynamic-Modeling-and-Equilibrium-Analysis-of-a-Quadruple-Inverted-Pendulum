@echo off
cd /d "%~dp0"
echo Pendulum Lab: http://127.0.0.1:8765
python launch.py
if errorlevel 1 pause
