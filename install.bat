@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   DSN Delta-MILP 调度系统 - 离线安装器
echo ============================================
echo.

:: Step 1: 检测 Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 未检测到 Python。
    echo 本应用需要 Python 3.11 或更高版本。
    echo 请先从 https://python.org/ 安装 Python，然后重新运行本脚本。
    pause
    exit /b 1
)

python --version 2>&1 | findstr /R "3\.1[1-9] 3\.[2-9]" >nul
if %ERRORLEVEL% NEQ 0 (
    echo [警告] Python 版本可能不是 3.11+。当前版本：
    python --version
    echo 继续安装...
)

echo [检测] Python 可用:
python --version
echo.

:: Step 2: 检测 packages/ 目录
if not exist "%~dp0packages" (
    echo [错误] 未找到 packages/ 目录。
    echo 离线 wheel 包必须与本安装器一同部署。
    pause
    exit /b 1
)
echo [检测] packages/ 目录存在 ✓

:: Step 3: 检测 GLPK
if not exist "%~dp0glpk\glpsol.exe" (
    echo [错误] 未找到 glpk\glpsol.exe。
    echo GLPK 求解器必须与本安装器一同部署。
    pause
    exit /b 1
)
echo [检测] glpk\glpsol.exe 存在 ✓
echo.

:: Step 4: 创建虚拟环境
echo [1/3] 创建 Python 虚拟环境...
set VENV_DIR=%~dp0.venv
if exist "%VENV_DIR%" (
    echo 检测到已有 .venv，正在移除...
    rmdir /s /q "%VENV_DIR%"
)
python -m venv "%VENV_DIR%"
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 虚拟环境创建失败。
    pause
    exit /b 1
)
echo   虚拟环境已创建: .venv/

:: Step 5: 安装包（离线）
echo.
echo [2/3] 从本地缓存安装 Python 包（离线模式）...
call "%VENV_DIR%\Scripts\activate.bat"
python -m ensurepip --upgrade 2>nul
pip install --no-index --find-links "%~dp0packages" pandas numpy matplotlib PuLP
if %ERRORLEVEL% NEQ 0 (
    echo [警告] 包安装遇到问题，尝试从 requirements.txt 安装...
    pip install --no-index --find-links "%~dp0packages" -r "%~dp0requirements.txt"
    if %ERRORLEVEL% NEQ 0 (
        echo [错误] 包安装失败。
        pause
        exit /b 1
    )
)

:: Step 6: 验证安装
echo.
echo [3/3] 验证安装...
python -c "import pulp; import pandas; import numpy; import matplotlib; print('所有 Python 包已就绪')"
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 包验证失败。
    pause
    exit /b 1
)

python -c "import os; glpk=os.path.normpath(os.path.join(os.getcwd(), 'glpk', 'glpsol.exe')); print(f'GLPK 路径: {glpk}'); print(f'GLPK 可用: {os.path.isfile(glpk)}')"

echo.
echo ============================================
echo   安装完成!
echo.
echo   生成数据:  run_data_generator.bat
echo   运行求解:  run_solver.bat
echo.
echo   输出文件位置:
echo     CSV 调度表:  dsn_schedule.csv
echo     甘特图:     dsn_gantt_chart.png
echo     优化日志:   Outputs\optimization_log.txt
echo ============================================
pause
