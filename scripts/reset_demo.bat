@echo off
REM Stop the backend first. Deletes the demo database and synthetic data; both are recreated on next start.
cd /d %~dp0\..\backend
if exist inspectiq.db del inspectiq.db
if exist data rmdir /s /q data
echo Demo reset. Start the backend again.
