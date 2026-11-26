@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Please run setup.cmd first.
  pause
  exit /b 1
)
if not exist local\sc3.json (
  echo Please run configure-sc3.cmd first and save your own SendKey.
  pause
  exit /b 1
)
echo Sending ONE test notification. This is not a classroom question.
.venv\Scripts\python.exe -X utf8 rain_probe.py push-test
echo.
echo Server acceptance does not prove phone delivery.
echo Check the phone popup, vibration, and arrival time yourself.
pause
