@echo off
chcp 65001 >nul
REM Start Delta HTTP API for Java / Web callers.
REM Default URL: http://0.0.0.0:8000  (reachable as http://<host>:8000)

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PY=%ROOT%\python\python.exe"

if not exist "%PY%" (
    echo [WARN] Bundled Python not found, falling back to system python.
    set "PY=python"
)

if not exist "%ROOT%\Outputs" mkdir "%ROOT%\Outputs"

"%PY%" "%ROOT%\Scripts\delta.py" --api --host 0.0.0.0 --port 8000