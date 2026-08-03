@echo off
chcp 65001 >nul 2>&1
title OCN Bid Monitor v2.0
echo ============================================================
echo   Oriental Cable Network - Daily Bid Opportunity Monitor v2.0
echo   Sources: ccgp.gov.cn + zfcg.sh.gov.cn
echo   Features: Lingang New Area detection, 1-10 days range
echo ============================================================
echo.

REM === Find Python (try py launcher, then python command) ===
set PYTHON=

py --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON=py
    goto :py_found
)

python --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON=python
    goto :py_found
)

echo [ERROR] Python not found on this computer!
echo.
echo Please install Python 3.8 or later from:
echo   https://www.python.org/downloads/
echo.
echo IMPORTANT: Check "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:py_found
echo [OK] Python found: %PYTHON%

REM === Script path (same folder as this bat file) ===
set SCRIPT=%~dp0bid_monitor.py

REM === Check and install dependencies ===
echo [*] Checking dependencies...
"%PYTHON%" -c "import requests, bs4" >nul 2>&1
if errorlevel 1 goto :install_deps
goto :run

:install_deps
echo [*] Installing dependencies (first run only)...
"%PYTHON%" -m pip install requests beautifulsoup4 lxml -q
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies. Check your internet connection.
    pause
    exit /b 1
)
echo [OK] Dependencies installed

:run
REM === Days range (accept command line arg, default 2) ===
set DAYS=2
if not "%~1"=="" set DAYS=%~1

REM === Run monitor ===
echo.
echo [*] Fetching latest bid opportunities (last %DAYS% days)...
echo.
"%PYTHON%" "%SCRIPT%" --days %DAYS%

echo.
echo ============================================================
echo   Report generated. Press any key to close.
echo ============================================================
pause >nul
