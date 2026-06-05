@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "PYTHON_CMD="
where py >nul 2>&1 && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
    where python >nul 2>&1 && set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo Python 3 wurde nicht gefunden.
    echo Bitte installiere Python 3 und fuege es zum PATH hinzu.
    pause
    exit /b 1
)

%PYTHON_CMD% "%SCRIPT_DIR%xml-sorter.py"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Das Tool wurde mit Fehlercode %EXIT_CODE% beendet.
)

pause
exit /b %EXIT_CODE%
