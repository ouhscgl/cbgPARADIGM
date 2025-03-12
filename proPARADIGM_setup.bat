@echo off
echo Starting paradigm setup...

echo Launching Central Control Window...
cd /d "C:\Projects\_extensions\cbgPARADIGM"
python "control_panel.py"
timeout /t 2 /nobreak > nul