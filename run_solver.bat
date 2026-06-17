@echo off
chcp 65001 >nul

echo ============================================
echo   DSN Delta-MILP - 调度求解器
echo ============================================

set SCRIPT_DIR=%~dp0

:: 激活虚拟环境
if exist "%SCRIPT_DIR%.venv\Scripts\activate.bat" (
    call "%SCRIPT_DIR%.venv\Scripts\activate.bat"
) else (
    echo [警告] 未找到 .venv，请先运行 install.bat。
    echo 尝试使用系统 Python 运行...
)

:: 确保 Outputs 目录存在
if not exist "%SCRIPT_DIR%Outputs" mkdir "%SCRIPT_DIR%Outputs"

:: 运行求解器
python "%SCRIPT_DIR%Scripts\delta.py"

echo.
echo 完成。输出文件:
echo   调度表 CSV:  %SCRIPT_DIR%dsn_schedule.csv
echo   甘特图 PNG:  %SCRIPT_DIR%dsn_gantt_chart.png
echo   优化日志:    %SCRIPT_DIR%Outputs\optimization_log.txt
pause
