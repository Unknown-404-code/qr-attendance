@echo off
REM ---- Gesture attendance: one-click start (Windows) ----
cd /d "%~dp0"
title Gesture attendance

if exist ".venv\installed-v2.ok" goto run

echo [1/3] Creating Python environment ...
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv >nul 2>&1 || py -3.11 -m venv .venv >nul 2>&1 || py -3.10 -m venv .venv >nul 2>&1 || py -3 -m venv .venv >nul 2>&1 || python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Python was not found. Install Python 3.12 from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH" during setup^), then run start.bat again.
  pause
  exit /b 1
)
echo [2/3] Installing packages (first run only, a few minutes) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements-app.txt
if errorlevel 1 (
  echo.
  echo Package installation failed. If the error mentions mediapipe, install Python 3.12,
  echo delete the .venv folder and run start.bat again.
  pause
  exit /b 1
)
echo ok> ".venv\installed-v2.ok"

:run
echo [3/3] Starting the attendance server ...
".venv\Scripts\python.exe" scripts\run_app.py --preload --tunnel --open %*
pause
