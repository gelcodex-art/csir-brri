@echo off
REM Bring the online (Supabase) database up to date after a new version.
REM Double-click, paste the connection line, press Enter.
cd /d "%~dp0"
".venv\Scripts\python.exe" setup_online.py update
