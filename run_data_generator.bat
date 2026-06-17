@echo off
chcp 65001 >nul

echo ============================================
echo   DSN Delta-MILP - 数据生成器
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

:: 运行数据生成器
python "%SCRIPT_DIR%Scripts\datapreprocess.py"

echo.
echo 完成。数据已保存至: %SCRIPT_DIR%Data\dsn_data.jsonl
pause
