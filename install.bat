@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM =====================================================================
REM   DSN Delta-MILP  -  Offline installer (target machine)
REM ---------------------------------------------------------------------
REM   This installer is intended to run on a machine WITHOUT internet.
REM   It uses the bundled embeddable Python in .\python\ and the wheel
REM   cache in .\packages\.  No system Python is required.
REM
REM   Bundled layout (produced by package_offline.bat):
REM     python\python.exe      embeddable Python 3.11.9
REM     packages\*.whl         all dependency wheels (cp311-win_amd64)
REM     glpk\glpsol.exe        GLPK 4.65 solver
REM     Scripts\               project sources
REM     requirements.txt       dependency manifest
REM =====================================================================

echo ============================================
echo   DSN Delta-MILP - Offline installer
echo ============================================
echo.

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PY=%ROOT%\python\python.exe"
set "PKG=%ROOT%\packages"
set "GLPK=%ROOT%\glpk\glpsol.exe"

REM ---- Step 1: verify bundled artifacts --------------------------------
if not exist "%PY%" (
    echo [ERROR] Bundled Python not found: %PY%
    echo         The package appears to be incomplete.
    pause
    exit /b 1
)
echo [check] bundled Python ............ OK
"%PY%" --version

if not exist "%PKG%" (
    echo [ERROR] packages\ folder not found: %PKG%
    pause
    exit /b 1
)
echo [check] packages\ folder .......... OK

if not exist "%GLPK%" (
    echo [ERROR] glpk\glpsol.exe not found: %GLPK%
    pause
    exit /b 1
)
echo [check] glpk\glpsol.exe ........... OK

if not exist "%ROOT%\requirements.txt" (
    echo [ERROR] requirements.txt missing.
    pause
    exit /b 1
)
echo [check] requirements.txt .......... OK
echo.

REM ---- Step 2: install all dependencies (offline) ----------------------
echo [1/2] Installing dependencies into bundled Python (offline) ...
"%PY%" -m pip install --no-index --find-links "%PKG%" --upgrade pip 2>nul
"%PY%" -m pip install --no-index --find-links "%PKG%" -r "%ROOT%\requirements.txt"
if errorlevel 1 (
    echo [ERROR] Offline pip install failed.
    echo         Check that packages\ contains a complete wheel set.
    pause
    exit /b 1
)
echo   [OK] all wheels installed.
echo.

REM ---- Step 3: verify imports + GLPK -----------------------------------
echo [2/2] Verifying installation ...
"%PY%" -c "import pulp, pandas, numpy, matplotlib, fastapi, uvicorn, pydantic; print('  python deps : OK')"
if errorlevel 1 (
    echo [ERROR] Python import verification failed.
    pause
    exit /b 1
)

"%PY%" -c "import os; p=r'%GLPK%'; print('  glpsol.exe  :', 'OK' if os.path.isfile(p) else 'MISSING', '->', p)"

REM Optional: light self-check of the API entrypoint (no port binding)
if exist "%ROOT%\Scripts\delta.py" (
    "%PY%" -c "import sys; sys.path.insert(0, r'%ROOT%\Scripts'); import delta; print('  delta module: OK')"
)

echo.
echo ============================================
echo   Installation complete.
echo.
echo   Start HTTP API for Java callers:
echo       run_delta_api.bat            (http://127.0.0.1:8000)
echo.
echo   Run solver once (CLI):
echo       run_solver.bat
echo.
echo   Generate sample data:
echo       run_data_generator.bat
echo.
echo   Outputs:
echo       Outputs\dsn_schedule.csv
echo       Outputs\dsn_gantt_chart.png
echo       Outputs\optimization_log.txt
echo ============================================
endlocal
pause