@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1] Python 3.13
py -3.13 --version
echo.
echo [2] Local Python environment and Playwright
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -X utf8 -c "import sys,importlib.metadata,tkinter; print(sys.version.split()[0]); print('Playwright',importlib.metadata.version('playwright')); print('Local settings UI: available')"
) else (
  echo Not installed. Run setup.cmd.
)
echo.
echo [3] Edge executable
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" goto edge_found
if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" goto edge_found
if exist "%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe" goto edge_found
echo Edge not found in standard locations. Install Microsoft Edge from its official site.
goto config_check
:edge_found
echo Edge found in a standard location.
:config_check
echo.
echo [4] Mobile configuration file
if exist local\sc3.json (
  echo Present. Key validity and phone delivery still require a notification test.
) else (
  echo Not configured. Run configure-sc3.cmd.
)
echo.
echo This check does not log in, send messages, or display your SendKey.
pause
