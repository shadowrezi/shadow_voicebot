@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

setlocal enabledelayedexpansion

:: Find Python
set "PY_EXE="
where python >nul 2>&1
if not errorlevel 1 set "PY_EXE=python"
if not defined PY_EXE (
    where py >nul 2>&1
    if not errorlevel 1 set "PY_EXE=py"
)

if not defined PY_EXE (
    echo [error] Python not found. Install Python 3.11+ and add it to PATH.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creating virtual environment...
    "%PY_EXE%" -m venv .venv
    if errorlevel 1 (
        echo [error] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [setup] Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

".venv\Scripts\python.exe" -m jarvis %*
if errorlevel 1 pause