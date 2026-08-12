@echo off
chcp 65001 >nul
echo ============================================
echo   Delta Slim - Solver
echo ============================================
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PY=%ROOT%\python\python.exe"
if not exist "%PY%" set "PY=python"
if not exist "%ROOT%\Outputs" mkdir "%ROOT%\Outputs"
"%PY%" "%ROOT%\Scripts\delta.py"
echo.
echo 完成。输出文件:
echo   调度表 CSV : Outputs\dsn_schedule.csv
echo   甘特图 PNG : Outputs\dsn_gantt_chart.png
echo   求解日志   : Outputs\optimization_log.txt
pause
