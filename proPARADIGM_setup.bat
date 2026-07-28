@echo off
echo Starting paradigm setup...

echo Launching Central Control Window...
cd /d "C:\Projects\_extensions\cbgPARADIGM"
python "main.py"
timeout /t 2 /nobreak > nul