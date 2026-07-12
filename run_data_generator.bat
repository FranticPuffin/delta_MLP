@echo off
chcp 65001 >nul

echo ============================================
echo   DSN Delta-MILP - Data generator
echo ============================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PY=%ROOT%\python\python.exe"

if not exist "%PY%" (
    echo [WARN] Bundled Python not found, falling back to system python.
    set "PY=python"
)

if not exist "%ROOT%\Data"    mkdir "%ROOT%\Data"
if not exist "%ROOT%\Outputs" mkdir "%ROOT%\Outputs"

"%PY%" "%ROOT%\Scripts\datapreprocess.py"

echo.
echo Done. Data written to: %ROOT%\Data\dsn_data.jsonl
pause