@echo off
chcp 65001 >nul

echo ============================================
echo   DSN Delta-MILP - Solver
echo ============================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PY=%ROOT%\python\python.exe"

if not exist "%PY%" (
    echo [WARN] Bundled Python not found, falling back to system python.
    set "PY=python"
)

if not exist "%ROOT%\Outputs" mkdir "%ROOT%\Outputs"

"%PY%" "%ROOT%\Scripts\delta.py"

echo.
echo Done. Output files:
echo   Schedule CSV : %ROOT%\Outputs\dsn_schedule.csv
echo   Gantt PNG    : %ROOT%\Outputs\dsn_gantt_chart.png
echo   Solver log   : %ROOT%\Outputs\optimization_log.txt
pause