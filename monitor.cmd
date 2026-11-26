@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Please run setup.cmd first.
  pause
  exit /b 1
)
echo TEST MONITOR: one student classroom; verified release messages only.
if not exist local\sc3.json (
  echo Please run configure-sc3.cmd, then test-notification.cmd first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -X utf8 rain_probe.py monitor
pause
