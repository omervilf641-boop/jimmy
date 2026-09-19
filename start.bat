@echo off
rem Mini-Jarvis launcher: starts the local server (UI + PC tools) and opens the browser
cd /d "%~dp0"
start "" http://localhost:8123
python server.py
