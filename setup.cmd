@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3.13 -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Setup complete.
echo Next: configure-sc3.cmd, then test-notification.cmd, then monitor.cmd.
pause
exit /b 0
:failed
echo Setup failed. Keep this window open and report the last error.
pause
exit /b 1
