@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM =====================================================================
REM  DSN Delta-MILP  -  Offline package builder
REM ---------------------------------------------------------------------
REM  Run this on a machine WITH internet access.
REM  It will produce a fully-self-contained folder/zip that can be copied
REM  to an offline target machine (Windows 10/11 x64) and installed via
REM  install.bat with NO further downloads required.
REM
REM  Bundled artifacts:
REM    - Python 3.11.9 embeddable (python\)
REM    - All wheel dependencies for cp311-win_amd64 (packages\)
REM    - GLPK 4.65 Windows solver (glpk\)
REM    - Project source, scripts, docs, sample data
REM =====================================================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

echo ======================================================================
echo   DSN Delta-MILP  -  Offline package builder
echo ======================================================================
echo Working directory: %ROOT%
echo.

REM ---- Configurable versions -------------------------------------------
set "PY_VER=3.11.9"
set "PY_MAJMIN=311"
set "PY_EMBED_URL=https://www.python.org/ftp/python/%PY_VER%/python-%PY_VER%-embed-amd64.zip"
set "GETPIP_URL=https://bootstrap.pypa.io/get-pip.py"
set "GLPK_URL=https://sourceforge.net/projects/winglpk/files/winglpk/GLPK-4.65/winglpk-4.65.zip/download"
REM ----------------------------------------------------------------------

REM Detect a host Python (only needed on THIS build machine, not on target)
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No host Python found on this build machine.
    echo         Install Python 3.x and re-run this script.
    pause
    exit /b 1
)
echo [HOST] Python:
python --version
echo.

REM Detect curl (Windows 10+ ships with curl.exe)
where curl >nul 2>&1
if errorlevel 1 (
    echo [ERROR] curl.exe not found. Windows 10 1803+ ships curl by default.
    pause
    exit /b 1
)

set "BUILD=%ROOT%\_build_offline"
set "DOWNLOADS=%BUILD%\downloads"
if not exist "%BUILD%" mkdir "%BUILD%"
if not exist "%DOWNLOADS%" mkdir "%DOWNLOADS%"

REM =====================================================================
REM  Step 1.  Embeddable Python
REM =====================================================================
echo [1/5] Preparing embeddable Python %PY_VER% ...
set "PY_DIR=%ROOT%\python"
set "PY_ZIP=%DOWNLOADS%\python-embed.zip"

if exist "%PY_DIR%\python.exe" (
    echo   - python\ already exists, skipping download.
) else (
    if not exist "%PY_ZIP%" (
        echo   - downloading %PY_EMBED_URL%
        curl -L -o "%PY_ZIP%" "%PY_EMBED_URL%"
        if errorlevel 1 ( echo [ERROR] failed to download Python embeddable. & pause & exit /b 1 )
    )
    if not exist "%PY_DIR%" mkdir "%PY_DIR%"
    echo   - extracting to python\
    powershell -NoProfile -Command "Expand-Archive -Force -LiteralPath '%PY_ZIP%' -DestinationPath '%PY_DIR%'"
    if errorlevel 1 ( echo [ERROR] failed to extract Python embeddable. & pause & exit /b 1 )
)

REM Patch python311._pth so site / pip / project imports work
set "PTH_FILE=%PY_DIR%\python%PY_MAJMIN%._pth"
if exist "%PTH_FILE%" (
    echo   - patching %PTH_FILE%
    > "%PTH_FILE%"  echo python%PY_MAJMIN%.zip
    >>"%PTH_FILE%" echo .
    >>"%PTH_FILE%" echo Lib\site-packages
    >>"%PTH_FILE%" echo import site
)

REM Bootstrap pip into the embeddable interpreter
if not exist "%PY_DIR%\Scripts\pip.exe" (
    echo   - bootstrapping pip via get-pip.py
    if not exist "%DOWNLOADS%\get-pip.py" (
        curl -L -o "%DOWNLOADS%\get-pip.py" "%GETPIP_URL%"
        if errorlevel 1 ( echo [ERROR] failed to download get-pip.py. & pause & exit /b 1 )
    )
    "%PY_DIR%\python.exe" "%DOWNLOADS%\get-pip.py" --no-warn-script-location
    if errorlevel 1 ( echo [ERROR] get-pip.py failed. & pause & exit /b 1 )

)

echo   [OK] embeddable Python ready at: %PY_DIR%
echo.

REM =====================================================================
REM  Step 2.  Download all wheel dependencies for cp311-win_amd64
REM =====================================================================
echo [2/5] Downloading Python wheel dependencies (cp311-win_amd64) ...
set "PKG_DIR=%ROOT%\packages"
if not exist "%PKG_DIR%" mkdir "%PKG_DIR%"

python -m pip download ^
    --dest "%PKG_DIR%" ^
    --only-binary=:all: ^
    --python-version 3.11 ^
    --platform win_amd64 ^
    --implementation cp ^
    --abi cp311 ^
    -r "%ROOT%\requirements.txt"
if errorlevel 1 (
    echo [ERROR] pip download failed. Check requirements.txt and network.
    pause
    exit /b 1
)
echo   [OK] wheels saved to: %PKG_DIR%
dir /b "%PKG_DIR%" | find /c /v "" > "%BUILD%\pkg_count.txt"
set /p PKG_COUNT=<"%BUILD%\pkg_count.txt"
echo   total wheel files: %PKG_COUNT%
echo.

REM =====================================================================
REM  Step 3.  GLPK 4.65 Windows binary
REM =====================================================================
echo [3/5] Preparing GLPK 4.65 Windows solver ...
set "GLPK_DIR=%ROOT%\glpk"
set "GLPK_ZIP=%DOWNLOADS%\winglpk-4.65.zip"
set "GLPK_TMP=%BUILD%\glpk_extract"

if exist "%GLPK_DIR%\glpsol.exe" (
    echo   - glpk\glpsol.exe already exists, skipping download.
    goto :glpk_done
)

if not exist "%GLPK_ZIP%" (
    echo   - downloading GLPK from SourceForge
    curl -L -o "%GLPK_ZIP%" "%GLPK_URL%"
    if errorlevel 1 ( echo [ERROR] failed to download GLPK. & pause & exit /b 1 )
)

if not exist "%GLPK_DIR%" mkdir "%GLPK_DIR%"
if exist "%GLPK_TMP%" rmdir /s /q "%GLPK_TMP%"
mkdir "%GLPK_TMP%"

echo   - extracting GLPK to %GLPK_TMP%
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force -LiteralPath '%GLPK_ZIP%' -DestinationPath '%GLPK_TMP%'"
if errorlevel 1 ( echo [ERROR] failed to extract GLPK. & pause & exit /b 1 )

set "GLPK_W64=%GLPK_TMP%\glpk-4.65\w64"
if not exist "%GLPK_W64%\glpsol.exe" (
    echo [ERROR] %GLPK_W64%\glpsol.exe not found after extraction.
    echo         Inspect %GLPK_TMP% manually.
    pause
    exit /b 1
)
echo   - copying binaries from %GLPK_W64%
xcopy /e /y /q "%GLPK_W64%\*" "%GLPK_DIR%\" >nul
if errorlevel 1 ( echo [ERROR] xcopy GLPK failed. & pause & exit /b 1 )

if not exist "%GLPK_DIR%\glpsol.exe" (
    echo [ERROR] glpsol.exe not found at %GLPK_DIR%.
    pause
    exit /b 1
)

:glpk_done
echo   [OK] GLPK ready at: %GLPK_DIR%
echo.

REM =====================================================================
REM  Step 4.  Smoke test the bundled stack
REM =====================================================================
echo [4/5] Smoke-testing bundled Python + wheels ...
set "TEST_DIR=%BUILD%\test_install"
if exist "%TEST_DIR%" rmdir /s /q "%TEST_DIR%"
mkdir "%TEST_DIR%"

"%PY_DIR%\python.exe" -m pip install ^
    --no-index ^
    --find-links "%PKG_DIR%" ^
    --target "%TEST_DIR%" ^
    -r "%ROOT%\requirements.txt"
if errorlevel 1 (
    echo [ERROR] offline pip install smoke test failed.
    echo         The wheel set in packages\ is incomplete.
    pause
    exit /b 1
)

"%PY_DIR%\python.exe" -c "import sys; sys.path.insert(0, r'%TEST_DIR%'); import pulp, pandas, numpy, matplotlib, fastapi, uvicorn, pydantic; print('[smoke] imports OK')"
if errorlevel 1 (
    echo [ERROR] smoke import failed.
    pause
    exit /b 1
)
echo   [OK] smoke test passed.
echo.

REM =====================================================================
REM  Step 5.  Build distributable zip
REM =====================================================================
echo [5/5] Building distributable zip ...
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmm"') do set "STAMP=%%T"
set "DIST_NAME=DSN_Delta_Offline_%STAMP%"
set "DIST_DIR=%BUILD%\%DIST_NAME%"
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
mkdir "%DIST_DIR%"

echo   - staging files into %DIST_DIR%
xcopy /e /y /q "%ROOT%\python"   "%DIST_DIR%\python\"   >nul
xcopy /e /y /q "%ROOT%\packages" "%DIST_DIR%\packages\" >nul
xcopy /e /y /q "%ROOT%\glpk"     "%DIST_DIR%\glpk\"     >nul
xcopy /e /y /q "%ROOT%\Scripts"  "%DIST_DIR%\Scripts\"  >nul
if exist "%ROOT%\Data" xcopy /e /y /q "%ROOT%\Data" "%DIST_DIR%\Data\" >nul
if exist "%ROOT%\Docs" xcopy /e /y /q "%ROOT%\Docs" "%DIST_DIR%\Docs\" >nul
if not exist "%DIST_DIR%\Outputs" mkdir "%DIST_DIR%\Outputs"

copy /y "%ROOT%\install.bat"            "%DIST_DIR%\" >nul
copy /y "%ROOT%\requirements.txt"       "%DIST_DIR%\" >nul
copy /y "%ROOT%\run_delta_api.bat"      "%DIST_DIR%\" >nul
copy /y "%ROOT%\run_solver.bat"         "%DIST_DIR%\" >nul
copy /y "%ROOT%\run_data_generator.bat" "%DIST_DIR%\" >nul
if exist "%ROOT%\quick_verify_delta_api.bat" copy /y "%ROOT%\quick_verify_delta_api.bat" "%DIST_DIR%\" >nul
if exist "%ROOT%\README_DEPLOY.md"      copy /y "%ROOT%\README_DEPLOY.md" "%DIST_DIR%\" >nul

set "ZIP_OUT=%ROOT%\%DIST_NAME%.zip"
if exist "%ZIP_OUT%" del /q "%ZIP_OUT%"
echo   - compressing to %ZIP_OUT%
powershell -NoProfile -Command "Compress-Archive -Force -Path '%DIST_DIR%\*' -DestinationPath '%ZIP_OUT%'"
if errorlevel 1 (
    echo [ERROR] zip compression failed.
    pause
    exit /b 1
)

echo.
echo ======================================================================
echo   SUCCESS
echo ----------------------------------------------------------------------
echo   Offline package : %ZIP_OUT%
echo   Staging folder  : %DIST_DIR%
echo.
echo   Copy the .zip to the offline target machine, unzip, then double-click
echo   install.bat.  No internet required on the target.
echo ======================================================================
endlocal
pause
