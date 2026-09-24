@echo off
echo Starting paradigm manager...
cd /d "%~dp0"
python main.py %*
timeout /t 2 /nobreak > nul
