@echo off
REM Run on a machine WITH internet, same OS + Python version as the event machine.
cd /d %~dp0\..
pip download -r backend\requirements.txt -d offline\wheels
cd frontend && call npm install && cd ..
echo Done. Copy the whole ai_friday_starter folder to the common folder.
