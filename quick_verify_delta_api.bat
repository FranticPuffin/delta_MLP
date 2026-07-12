@echo off
setlocal enabledelayedexpansion

REM Quick verification script for Delta HTTP API wrapper.
REM It checks:
REM   1. Python syntax for Scripts\delta.py and Scripts\delta_core.py
REM   2. Required web dependencies
REM   3. Starts the API on port 8000
REM   4. Calls /health
REM   5. Stops the temporary API process

cd /d "%~dp0"

echo ============================================================
echo Delta API quick verification
echo ============================================================

echo.
echo [1/5] Checking Python syntax...
python -m py_compile Scripts\delta.py Scripts\delta_core.py
if errorlevel 1 (
    echo [FAILED] Python syntax check failed.
    exit /b 1
)
echo [OK] Python syntax check passed.

echo.
echo [2/5] Checking Python web dependencies...
python -c "import fastapi, uvicorn, pydantic; print('fastapi/uvicorn/pydantic installed')"
if errorlevel 1 (
    echo [FAILED] Missing dependencies.
    echo Please run:
    echo     pip install -r requirements.txt
    exit /b 1
)
echo [OK] Dependencies are installed.

echo.
echo [3/5] Starting Delta API on http://127.0.0.1:8000 ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Start-Process -FilePath python -ArgumentList 'Scripts\delta.py','--api','--host','127.0.0.1','--port','8000' -PassThru -WindowStyle Hidden; Set-Content -Path .delta_api_verify.pid -Value $p.Id"
if errorlevel 1 (
    echo [FAILED] Could not start API process.
    exit /b 1
)

echo Waiting for API to become ready...
timeout /t 5 /nobreak >nul

echo.
echo [4/5] Calling /health ...
curl -s http://127.0.0.1:8000/health
if errorlevel 1 (
    echo.
    echo [FAILED] Health check failed.
    goto cleanup_fail
)

echo.
echo [OK] Health endpoint responded.

echo.
echo [5/5] Cleaning up API process...
goto cleanup_ok

:cleanup_fail
if exist .delta_api_verify.pid (
    for /f %%p in (.delta_api_verify.pid) do powershell -NoProfile -ExecutionPolicy Bypass -Command "Stop-Process -Id %%p -Force -ErrorAction SilentlyContinue"
    del .delta_api_verify.pid >nul 2>nul
)
exit /b 1

:cleanup_ok
if exist .delta_api_verify.pid (
    for /f %%p in (.delta_api_verify.pid) do powershell -NoProfile -ExecutionPolicy Bypass -Command "Stop-Process -Id %%p -Force -ErrorAction SilentlyContinue"
    del .delta_api_verify.pid >nul 2>nul
)
echo.
echo ============================================================
echo [SUCCESS] Delta API quick verification passed.
echo ============================================================
exit /b 0