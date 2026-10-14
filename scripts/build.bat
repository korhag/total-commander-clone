@echo off
setlocal EnableExtensions

REM ------------------------------------------------------------
REM Script: scripts/build.bat
REM Purpose: Build the current local sources into a standalone .exe
REM          with PyInstaller. No Git sync, push, or pull.
REM Project root: parent of this scripts\ folder (portable; no absolute paths).
REM
REM Builds to dist_build\ first so a locked dist\TotalCommanderClone does not
REM block rebuilds. On success, promotes to dist\ when the old folder is removable.
REM If dist\ is locked after build: stop the app, retry delete, then failsafe-merge
REM (robocopy staging over dist, leaving locked files in place) so the taskbar
REM shortcut path keeps working. Only prompts interactively if merge also fails.
REM
REM Pass debug for a console build (TotalCommanderClone-debug.exe).
REM ------------------------------------------------------------

cd /d "%~dp0.."

set "ICON=file-explorer.ico"
set "SCRIPT=main.py"
set "APP_EXE=TotalCommanderClone.exe"
set "DIST_FINAL=dist\TotalCommanderClone"
set "DIST_BUILD_ROOT=dist_build"
set "DIST_STAGING=%DIST_BUILD_ROOT%\TotalCommanderClone"
set "SPEC_FILE=TotalCommanderClone.spec"
set "PYTHON_EXE="
set "PYTHON_ARGS="

:parse_build_args
if "%~1"=="" goto build_args_done
if /I "%~1"=="debug" (
    set "APP_EXE=TotalCommanderClone-debug.exe"
    set "DIST_STAGING=%DIST_BUILD_ROOT%\TotalCommanderClone-debug"
    set "SPEC_FILE=TotalCommanderClone-debug.spec"
    set "BUILD_DEBUG=1"
    shift
    goto parse_build_args
)
shift
goto parse_build_args

:build_args_done
if defined BUILD_DEBUG (
    echo [INFO] Debug console build selected.
)

if not exist "%SCRIPT%" (
    echo [ERROR] Could not find "%SCRIPT%" in:
    echo         %cd%
    exit /b 1
)

if not exist "%ICON%" (
    echo [ERROR] Could not find "%ICON%". Icon is required for the build.
    exit /b 1
)

where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        set "PYTHON_EXE=python"
    ) else (
        where python3 >nul 2>&1
        if %ERRORLEVEL% EQU 0 (
            set "PYTHON_EXE=python3"
        )
    )
)

if "%PYTHON_EXE%"=="" (
    echo [ERROR] Python was not found.
    exit /b 1
)

echo [INFO] Installing dependencies (requirements.txt)...
%PYTHON_EXE% %PYTHON_ARGS% -m pip install -r requirements.txt --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Could not install requirements.
    exit /b 1
)

call :stop_running_app

call :try_clear_staging

echo [INFO] Building standalone .exe (%SPEC_FILE%)...
echo [INFO] Staging output: %DIST_STAGING%\
%PYTHON_EXE% %PYTHON_ARGS% -m PyInstaller --noconfirm --clean --distpath "%DIST_BUILD_ROOT%" %SPEC_FILE%

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Build failed.
    echo         If you see "Access is denied" on %DIST_BUILD_ROOT%\, close %APP_EXE%
    echo         and any File Explorer windows showing that folder, then retry.
    exit /b 1
)

call :promote_build_output
exit /b %ERRORLEVEL%

REM ------------------------------------------------------------
REM Subroutine: stop_running_app
REM Purpose: End TotalCommanderClone.exe with retries (best effort).
REM ------------------------------------------------------------
:stop_running_app
call :is_app_running
if errorlevel 1 exit /b 0

echo [INFO] Stopping %APP_EXE% (best effort)...
for /L %%k in (1,1,10) do (
    taskkill /IM %APP_EXE% /F >nul 2>&1
    ping 127.0.0.1 -n 2 >nul
    call :is_app_running
    if errorlevel 1 goto :stop_running_app_released
)
call :is_app_running
if not errorlevel 1 (
    echo [WARN] %APP_EXE% is still running. Build will continue to %DIST_BUILD_ROOT%\.
    echo         Close the app later to promote output into dist\.
)
:stop_running_app_released
echo [INFO] Waiting for file handles to release...
ping 127.0.0.1 -n 3 >nul
exit /b 0

REM ------------------------------------------------------------
REM Subroutine: is_app_running
REM Exit code 0 if %APP_EXE% is running, 1 if not.
REM ------------------------------------------------------------
:is_app_running
tasklist /FI "IMAGENAME eq %APP_EXE%" 2>nul | find /I "%APP_EXE%" >nul
if errorlevel 1 exit /b 1
exit /b 0

REM ------------------------------------------------------------
REM Subroutine: try_clear_staging
REM Purpose: Remove prior staging output before PyInstaller (non-fatal).
REM ------------------------------------------------------------
:try_clear_staging
if not exist "%DIST_BUILD_ROOT%" exit /b 0

echo [INFO] Clearing previous staging build at %DIST_BUILD_ROOT%\ ...
for /L %%r in (1,1,6) do (
    rmdir /s /q "%DIST_BUILD_ROOT%" 2>nul
    if not exist "%DIST_BUILD_ROOT%" exit /b 0
    ping 127.0.0.1 -n 2 >nul
)

if exist "%DIST_BUILD_ROOT%" (
    echo [WARN] Could not fully remove "%DIST_BUILD_ROOT%" - PyInstaller will try anyway.
)
exit /b 0

REM ------------------------------------------------------------
REM Subroutine: promote_build_output
REM Purpose: Move staging build into dist\ when the old folder is removable.
REM          If dist\ is locked, retry after stopping the app, then failsafe-merge.
REM ------------------------------------------------------------
:promote_build_output
if not exist "%DIST_STAGING%\%APP_EXE%" (
    echo [ERROR] Expected output not found at %DIST_STAGING%\%APP_EXE%
    exit /b 1
)

if defined BUILD_DEBUG (
    echo.
    echo [INFO] Debug build complete. Output: %DIST_STAGING%\%APP_EXE%
    echo [INFO] Console stderr is visible when run from a terminal.
    echo [INFO] Logs: %%APPDATA%%\TotalCommanderClone\startup.log and crash.log
    exit /b 0
)

if exist "%DIST_FINAL%" (
    call :remove_dist_final 6
    if errorlevel 1 goto :promote_build_output_locked
)

call :complete_promote_swap
if errorlevel 1 (
    echo [WARN] Could not move staging into dist\. Trying merge failsafe...
    call :merge_promote_into_dist
    if errorlevel 1 (
        echo [WARN] Merge failsafe failed. Output remains at %DIST_STAGING%\%APP_EXE%
        exit /b 0
    )
)
exit /b 0

REM ------------------------------------------------------------
REM Subroutine: remove_dist_final
REM Purpose: Delete %DIST_FINAL% with retries. Arg1 = max attempts (default 6).
REM Exit 0 on success, 1 if folder still exists.
REM ------------------------------------------------------------
:remove_dist_final
setlocal EnableDelayedExpansion
set "RR=6"
if not "%~1"=="" set "RR=%~1"
if exist "%DIST_FINAL%" (
    echo [INFO] Attempting to replace %DIST_FINAL%\ ...
)
for /L %%r in (1,1,!RR!) do (
    rmdir /s /q "%DIST_FINAL%" 2>nul
    if not exist "%DIST_FINAL%" (
        endlocal
        exit /b 0
    )
    ping 127.0.0.1 -n 2 >nul
)
if exist "%DIST_FINAL%" (
    endlocal
    exit /b 1
)
endlocal
exit /b 0

REM ------------------------------------------------------------
REM Subroutine: complete_promote_swap
REM Purpose: Move staging into dist\, remove dist_build, print success.
REM Exit 0 on success, 1 if move failed.
REM ------------------------------------------------------------
:complete_promote_swap
if not exist "dist" mkdir "dist"
move "%DIST_STAGING%" "%DIST_FINAL%" >nul 2>&1
if errorlevel 1 exit /b 1

rmdir "%DIST_BUILD_ROOT%" 2>nul

echo.
echo [INFO] Build complete. Output: %DIST_FINAL%\%APP_EXE%
echo [INFO] Settings are stored in %%APPDATA%%\TotalCommanderClone (persists across rebuilds).
exit /b 0

REM ------------------------------------------------------------
REM Subroutine: merge_promote_into_dist
REM Purpose: Failsafe when dist\ cannot be deleted (locked DLLs, Explorer, etc.).
REM          Copy staging over dist\ with robocopy; leave locked files in place.
REM          Succeeds if %DIST_FINAL%\%APP_EXE% exists afterward.
REM Exit 0 on success, 1 on failure.
REM ------------------------------------------------------------
:merge_promote_into_dist
echo [INFO] Failsafe: merging new build into %DIST_FINAL%\ (keeping locked files)...
if not exist "dist" mkdir "dist"
if not exist "%DIST_FINAL%" mkdir "%DIST_FINAL%"

robocopy "%DIST_STAGING%" "%DIST_FINAL%" /E /COPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS /NP >nul
set "MERGE_RC=%ERRORLEVEL%"

if not exist "%DIST_FINAL%\%APP_EXE%" (
    echo [ERROR] Failsafe merge did not produce %DIST_FINAL%\%APP_EXE%
    exit /b 1
)

REM robocopy: 0-7 = OK-ish; bit 8 (8+) = some files failed; 16+ = serious error
if %MERGE_RC% GEQ 16 (
    echo [ERROR] Failsafe merge failed (robocopy exit %MERGE_RC%).
    exit /b 1
)

if %MERGE_RC% GEQ 8 (
    echo [WARN] Some files under %DIST_FINAL% were locked and could not be overwritten.
    echo         Left existing copies in place. Verified %APP_EXE% is present for the shortcut.
)

REM Best-effort cleanup of staging (may fail if something still holds it)
rmdir /s /q "%DIST_STAGING%" 2>nul
rmdir "%DIST_BUILD_ROOT%" 2>nul

echo.
echo [INFO] Build complete. Output: %DIST_FINAL%\%APP_EXE%
echo [INFO] Settings are stored in %%APPDATA%%\TotalCommanderClone (persists across rebuilds).
exit /b 0

REM ------------------------------------------------------------
REM Subroutine: promote_build_output_locked
REM Purpose: dist\ locked after build; stop app, retry delete, then merge failsafe.
REM          Prompt only if automatic recovery fails.
REM ------------------------------------------------------------
:promote_build_output_locked
echo.
echo [INFO] Build OK at %DIST_STAGING%\%APP_EXE%
echo [WARN] Could not fully replace "%DIST_FINAL%" - some files are locked.

call :stop_running_app

call :remove_dist_final 6
if not errorlevel 1 (
    call :complete_promote_swap
    if not errorlevel 1 exit /b 0
)

echo [INFO] Delete still blocked - using merge failsafe...
call :merge_promote_into_dist
if not errorlevel 1 exit /b 0

set "CONFIRM="
set /p "CONFIRM=Automatic promote failed. Retry delete of dist\TotalCommanderClone? [Y/N] "
if /I not "%CONFIRM%"=="Y" goto :promote_build_output_locked_decline

echo [INFO] Removing locked %DIST_FINAL%\ ...
call :remove_dist_final 10
if errorlevel 1 goto :promote_build_output_locked_still_locked

call :complete_promote_swap
if errorlevel 1 (
    call :merge_promote_into_dist
    if errorlevel 1 goto :promote_build_output_locked_still_locked
)
exit /b 0

:promote_build_output_locked_still_locked
echo.
call :print_dist_lock_hints
echo [ERROR] Could not promote into "%DIST_FINAL%". New build remains at %DIST_STAGING%\%APP_EXE%
exit /b 1

:promote_build_output_locked_decline
echo.
echo [INFO] Keeping current dist\ state. Run the new build from:
echo         %DIST_STAGING%\%APP_EXE%
echo [INFO] To finish later: close apps locking files under dist\, then run
echo         scripts\build.bat again (or delete "%DIST_FINAL%" and move
echo         dist_build\TotalCommanderClone into dist\).
echo [INFO] Settings are stored in %%APPDATA%%\TotalCommanderClone (persists across rebuilds).
exit /b 0

REM ------------------------------------------------------------
REM Subroutine: print_dist_lock_hints
REM Purpose: Suggest what may be holding dist\TotalCommanderClone.
REM ------------------------------------------------------------
:print_dist_lock_hints
echo [INFO] dist\TotalCommanderClone may still be locked by:
call :is_app_running
if not errorlevel 1 (
    echo         - %APP_EXE% is still running
)
echo         - File Explorer with dist\ or TotalCommanderClone open
echo         - A terminal whose current directory is under dist\
echo         - Another app that loaded DLLs from dist\_internal (e.g. VCRUNTIME*.dll)
echo         Close those, then run scripts\build.bat again.
exit /b 0
