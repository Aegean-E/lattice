@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "PYTHON_EXE=py -3"
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

if not defined PYTHON_EXE (
    echo [ERROR] Python 3.10+ was not found in PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

%PYTHON_EXE% start.py %*
