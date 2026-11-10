@echo off
REM Start the BRRI Road Accident Data System on this PC.
REM Open http://127.0.0.1:8000 in a browser. Press Ctrl+C here to stop.
cd /d "%~dp0"
".venv\Scripts\python.exe" manage.py migrate --noinput
".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
