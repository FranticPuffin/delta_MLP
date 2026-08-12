@echo off
chcp 65001 >nul
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PY=%ROOT%\python\python.exe"
if not exist "%PY%" set "PY=python"
if not exist "%ROOT%\Outputs" mkdir "%ROOT%\Outputs"
"%PY%" "%ROOT%\Scripts\delta.py" --api --host 0.0.0.0 --port 8000
