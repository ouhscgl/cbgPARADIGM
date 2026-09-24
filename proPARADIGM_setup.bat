@echo off
echo Starting paradigm setup...

echo Launching Central Control Window...
cd /d "%~dp0"
python main.py %*
timeout /t 2 /nobreak > nul
