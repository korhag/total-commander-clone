@echo off
setlocal EnableExtensions

REM ------------------------------------------------------------
REM Script: scripts/update-and-rebuild.bat
REM Purpose: Called from the app when the user accepts an update.
REM          Waits for TotalCommanderClone.exe to exit, gets the
REM          latest public code (git pull OR GitHub zip if Git is
REM          missing), rebuilds with build.bat, then relaunches.
REM
REM No GitHub username/PAT required for the public repo.
REM ------------------------------------------------------------

cd /d "%~dp0.."

set "APP_EXE=TotalCommanderClone.exe"
set "DIST_EXE=dist\TotalCommanderClone\TotalCommanderClone.exe"
set "BRANCH=main"
set "REMOTE=origin"
set "PUBLIC_URL=https://github.com/derya-kromeka/total-commander-clone.git"
set "HAVE_GIT="

echo.
echo ============================================================
echo  Total Commander Clone - Update and rebuild
echo ============================================================
echo  Project: %cd%
echo.

echo [INFO] Waiting for %APP_EXE% to exit...
set /a "_wait=0"
:wait_app
call :is_app_running
if errorlevel 1 goto app_stopped
set /a "_wait+=1"
if %_wait% GEQ 60 (
    echo [WARN] App still running after ~2 minutes. Trying to stop it...
    taskkill /IM %APP_EXE% /F >nul 2>&1
    ping 127.0.0.1 -n 3 >nul
    goto app_stopped
)
ping 127.0.0.1 -n 3 >nul
goto wait_app

:app_stopped
echo [INFO] App is not running. Continuing...
echo.

where git >nul 2>&1
if not errorlevel 1 set "HAVE_GIT=1"

if defined HAVE_GIT (
    for /f "delims=" %%b in ('git branch --show-current 2^>nul') do set "BRANCH=%%b"
)
if "%BRANCH%"=="" set "BRANCH=main"

if defined HAVE_GIT (
    echo [INFO] Git found - updating via git fetch/merge ^(public HTTPS, no login^)...
    call :update_via_git
    if errorlevel 1 goto fail
) else (
    echo [INFO] Git is not installed - updating via public GitHub zip download...
    call :update_via_zip
    if errorlevel 1 goto fail
)

echo.
echo [INFO] Building new executable ^(scripts\build.bat^)...
call "%~dp0build.bat"
if errorlevel 1 (
    echo [ERROR] Build failed. See messages above.
    goto fail
)

if not exist "%DIST_EXE%" (
    echo [ERROR] Build finished but exe not found:
    echo         %DIST_EXE%
    goto fail
)

echo.
echo [INFO] Starting updated app...
start "" "%DIST_EXE%"
echo [OK] Update complete.
exit /b 0

:fail
echo.
echo Update did not finish successfully.
pause
exit /b 1

REM ------------------------------------------------------------
:update_via_git
if not exist ".git" (
    echo [WARN] No .git folder - falling back to zip download.
    call :update_via_zip
    exit /b %ERRORLEVEL%
)

git remote get-url %REMOTE% >nul 2>&1
if errorlevel 1 (
    echo [INFO] Adding public remote %REMOTE% -^> %PUBLIC_URL%
    git remote add %REMOTE% "%PUBLIC_URL%"
    if errorlevel 1 (
        echo [ERROR] Could not add remote %REMOTE%.
        exit /b 1
    )
)

echo [INFO] Fetching %REMOTE%/%BRANCH%...
git fetch "%REMOTE%" "%BRANCH%"
if errorlevel 1 (
    echo [ERROR] git fetch failed.
    echo         Public clone URL: %PUBLIC_URL%
    exit /b 1
)

echo [INFO] Merging %REMOTE%/%BRANCH% into local branch...
git merge --no-edit "%REMOTE%/%BRANCH%"
if errorlevel 1 (
    echo [ERROR] git merge failed ^(conflicts or local changes?^).
    echo         Resolve conflicts, then run: scripts\build.bat
    exit /b 1
)
exit /b 0

REM ------------------------------------------------------------
:update_via_zip
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0download-public-update.ps1" -ProjectRoot "%cd%" -Branch "%BRANCH%"
exit /b %ERRORLEVEL%

REM ------------------------------------------------------------
:is_app_running
tasklist /FI "IMAGENAME eq %APP_EXE%" 2>nul | find /I "%APP_EXE%" >nul
if errorlevel 1 exit /b 1
exit /b 0
