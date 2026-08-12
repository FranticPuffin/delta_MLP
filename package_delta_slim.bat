@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM =====================================================================
REM  Delta Slim - 离线安装包构建脚本
REM ---------------------------------------------------------------------
REM 构建仅包含 delta.py + delta_core.py 的精简离线部署包。
REM 复用已下载的 python/、packages/、glpk/ 资源。
REM
REM 用法：双击运行此脚本，将在 _build_slim\ 下生成部署包。
REM =====================================================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

echo ======================================================================
echo   Delta Slim - 精简离线包构建
echo ======================================================================
echo 工作目录: %ROOT%
echo.

REM ---- 验证必要资源是否存在 --------------------------------------------
if not exist "%ROOT%\python\python.exe" (
    echo [ERROR] 未找到 bundled Python: %ROOT%\python\python.exe
    echo         请先运行 package_offline.bat 生成完整资源，或确认 python\ 目录存在。
    pause
    exit /b 1
)
echo [OK] python\ ........................... 已就绪

if not exist "%ROOT%\packages" (
    echo [ERROR] 未找到 packages\ 目录，请先运行 package_offline.bat。
    pause
    exit /b 1
)
echo [OK] packages\ ......................... 已就绪

if not exist "%ROOT%\glpk\glpsol.exe" (
    echo [ERROR] 未找到 glpk\glpsol.exe，请先运行 package_offline.bat。
    pause
    exit /b 1
)
echo [OK] glpk\ ............................. 已就绪

if not exist "%ROOT%\Scripts\delta.py" (
    echo [ERROR] 未找到 Scripts\delta.py。
    pause
    exit /b 1
)
echo [OK] Scripts\delta.py .................. 已就绪

if not exist "%ROOT%\Scripts\delta_core.py" (
    echo [ERROR] 未找到 Scripts\delta_core.py。
    pause
    exit /b 1
)
echo [OK] Scripts\delta_core.py ............. 已就绪

echo.

REM ---- 创建临时目录 ----------------------------------------------------
set "BUILD=%ROOT%\_build_slim"
set "DIST_NAME=Delta_Slim_Offline"
set "DIST_DIR=%BUILD%\%DIST_NAME%"
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
mkdir "%DIST_DIR%"

echo [1/5] 复制 Python 运行时 ...
xcopy /e /y /q "%ROOT%\python" "%DIST_DIR%\python\" >nul
echo   [OK]

echo [2/5] 复制 Python 依赖包 ...
xcopy /e /y /q "%ROOT%\packages" "%DIST_DIR%\packages\" >nul
echo   [OK]

echo [3/5] 复制 GLPK 求解器 ...
xcopy /e /y /q "%ROOT%\glpk" "%DIST_DIR%\glpk\" >nul
echo   [OK]

echo [4/5] 复制核心脚本 (delta.py + delta_core.py) ...
if not exist "%DIST_DIR%\Scripts" mkdir "%DIST_DIR%\Scripts"
copy /y "%ROOT%\Scripts\delta.py" "%DIST_DIR%\Scripts\delta.py" >nul
copy /y "%ROOT%\Scripts\delta_core.py" "%DIST_DIR%\Scripts\delta_core.py" >nul
echo   [OK]

echo [5/5] 创建 Data 和 Outputs 目录 ...
if not exist "%DIST_DIR%\Data" mkdir "%DIST_DIR%\Data"
if not exist "%DIST_DIR%\Outputs" mkdir "%DIST_DIR%\Outputs"
echo   [OK]

echo.
REM ---- 复制部署脚本 ----------------------------------------------------
echo 复制部署脚本 ...
copy /y "%ROOT%\requirements.txt" "%DIST_DIR%\requirements.txt" >nul

REM 生成精简版 install.bat
(
echo @echo off
echo chcp 65001 ^>nul
echo setlocal enabledelayedexpansion
echo.
echo echo ============================================
echo echo   Delta Slim - 离线安装
echo echo ============================================
echo echo.
echo.
echo set "ROOT=%%~dp0"
echo if "%%ROOT:~-1%%"=="\" set "ROOT=%%ROOT:~0,-1%%"
echo set "PY=%%ROOT%%\python\python.exe"
echo set "PKG=%%ROOT%%\packages"
echo.
echo if not exist "%%PY%%" (
echo     echo [ERROR] 未找到 bundled Python: %%PY%%
echo     pause
echo     exit /b 1
echo )
echo echo [check] Python ................... OK
echo "%%PY%%" --version
echo.
echo if not exist "%%PKG%%" (
echo     echo [ERROR] 未找到 packages\ 目录
echo     pause
echo     exit /b 1
echo )
echo echo [check] packages\ ................ OK
echo.
echo if not exist "%%ROOT%%\glpk\glpsol.exe" (
echo     echo [ERROR] 未找到 glpk\glpsol.exe
echo     pause
echo     exit /b 1
echo )
echo echo [check] glpk\glpsol.exe .......... OK
echo.
echo echo [1/2] 安装 Python 依赖包(离线) ...
echo "%%PY%%" -m pip install --no-index --find-links "%%PKG%%" --upgrade pip 2^>nul
echo "%%PY%%" -m pip install --no-index --find-links "%%PKG%%" -r "%%ROOT%%\requirements.txt"
echo if errorlevel 1 (
echo     echo [ERROR] pip 离线安装失败
echo     pause
echo     exit /b 1
echo )
echo echo   [OK]
echo echo.
echo echo [2/2] 验证安装 ...
echo "%%PY%%" -c "import pulp, pandas, numpy, matplotlib, fastapi, uvicorn, pydantic; print('  python deps : OK')"
echo if errorlevel 1 (
echo     echo [ERROR] 依赖导入验证失败
echo     pause
echo     exit /b 1
echo )
echo "%%PY%%" -c "import sys; sys.path.insert(0, r'%%ROOT%%\Scripts'); import delta; print('  delta module: OK')"
echo if errorlevel 1 (
echo     echo [ERROR] delta 模块导入失败
echo     pause
echo     exit /b 1
echo )
echo echo.
echo echo ============================================
echo echo   安装完成！
echo echo.
echo echo   启动 HTTP API:
echo echo       run_delta_api.bat    (http://127.0.0.1:8000)
echo echo.
echo echo   运行求解器(CLI):
echo echo       run_solver.bat
echo echo.
echo echo   输出目录: Outputs\
echo echo ============================================
echo endlocal
echo pause
) > "%DIST_DIR%\install.bat"

REM 生成 run_delta_api.bat
(
echo @echo off
echo chcp 65001 ^>nul
echo set "ROOT=%%~dp0"
echo if "%%ROOT:~-1%%"=="\" set "ROOT=%%ROOT:~0,-1%%"
echo set "PY=%%ROOT%%\python\python.exe"
echo if not exist "%%PY%%" set "PY=python"
echo if not exist "%%ROOT%%\Outputs" mkdir "%%ROOT%%\Outputs"
echo "%%PY%%" "%%ROOT%%\Scripts\delta.py" --api --host 0.0.0.0 --port 8000
) > "%DIST_DIR%\run_delta_api.bat"

REM 生成 run_solver.bat
(
echo @echo off
echo chcp 65001 ^>nul
echo echo ============================================
echo echo   Delta Slim - Solver
echo echo ============================================
echo set "ROOT=%%~dp0"
echo if "%%ROOT:~-1%%"=="\" set "ROOT=%%ROOT:~0,-1%%"
echo set "PY=%%ROOT%%\python\python.exe"
echo if not exist "%%PY%%" set "PY=python"
echo if not exist "%%ROOT%%\Outputs" mkdir "%%ROOT%%\Outputs"
echo "%%PY%%" "%%ROOT%%\Scripts\delta.py"
echo echo.
echo echo 完成。输出文件:
echo echo   调度表 CSV : Outputs\dsn_schedule.csv
echo echo   甘特图 PNG : Outputs\dsn_gantt_chart.png
echo echo   求解日志   : Outputs\optimization_log.txt
echo pause
) > "%DIST_DIR%\run_solver.bat"

echo   [OK]

REM ---- 压缩打包 --------------------------------------------------------
echo.
echo 打包为 zip ...
set "ZIP_OUT=%ROOT%\%DIST_NAME%.zip"
if exist "%ZIP_OUT%" del /q "%ZIP_OUT%"
powershell -NoProfile -Command "Compress-Archive -Force -Path '%DIST_DIR%\*' -DestinationPath '%ZIP_OUT%'"
if errorlevel 1 (
    echo [ERROR] zip 压缩失败
    pause
    exit /b 1
)

echo.
echo ======================================================================
echo   构建成功！
echo ----------------------------------------------------------------------
echo   安装包 : %ZIP_OUT%
echo   大小   :
dir "%ZIP_OUT%"
echo.
echo   使用方法:
echo     1. 将 %DIST_NAME%.zip 复制到目标离线机器
echo     2. 解压后双击 install.bat
echo     3. 安装完成后双击 run_delta_api.bat 启动服务
echo ======================================================================
endlocal
pause