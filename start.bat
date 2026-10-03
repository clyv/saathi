@echo off
REM Saathi launcher for Windows. Double-click this file (or a desktop shortcut to it).
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo First run: creating a Python environment and installing Saathi. This takes a few minutes.
  py -3 -m venv .venv 2>nul || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  echo.
  echo Now downloading the AI models. This needs internet, one time only.
  ".venv\Scripts\python.exe" scripts\setup.py
  REM A smiling-face "Saathi" shortcut on the desktop, so she never has to find this file
  ".venv\Scripts\python.exe" scripts\setup.py --shortcut
)

REM Start the server in its own minimised window (if it is already running, this copy just exits)
start "Saathi server" /min ".venv\Scripts\python.exe" server.py

REM Give it a moment, then open the call screen as an app window (no tabs or address bar)
timeout /t 3 /nobreak >nul
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if exist "%EDGE%" (
  start "" "%EDGE%" --app=http://127.0.0.1:8765/ --start-maximized
) else (
  start "" http://127.0.0.1:8765/
)
