@echo off
cd /d "%~dp0"
".venv-train\Scripts\python.exe" -m scripts.start_active_evolution_workbench
if errorlevel 1 (
  pause
  exit /b 1
)
start "" "http://127.0.0.1:8080/evolution"
