@echo off
REM Fill the online (Supabase) database. Double-click, paste the connection line, press Enter.
cd /d "%~dp0"
".venv\Scripts\python.exe" setup_online.py
