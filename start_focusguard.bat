@echo off
rem Startet FocusGuard ohne Konsolenfenster.
cd /d %~dp0
call .venv\Scripts\activate.bat
start "" pythonw -m focusguard
