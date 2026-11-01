@echo off
setlocal EnableExtensions

REM ------------------------------------------------------------
REM Script: scripts/run.bat
REM Purpose: Run main.py with the project .venv (Windows).
REM          Run scripts\install_windows.bat once to create .venv.
REM ------------------------------------------------------------

cd /d "%~dp0.."

set "SCRIPT=main.py"

if not exist "%SCRIPT%" (
    echo [ERROR] Could not find "%SCRIPT%" in:
    echo         %cd%
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    echo [INFO] Using project virtual environment (.venv^)...
    ".venv\Scripts\python.exe" "%SCRIPT%"
    exit /b %ERRORLEVEL%
)

echo [ERROR] No virtual environment found. Create it with:
echo         scripts\install_windows.bat
exit /b 1
