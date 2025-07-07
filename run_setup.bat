@echo off
echo MicroVolts Server Setup
echo ============================
echo.

REM Request administrator privileges
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"
if '%errorlevel%' NEQ '0' (
    echo Requesting administrative privileges...
    powershell -Command "Start-Process cmd.exe -ArgumentList '/c %~s0' -Verb RunAs"
    exit
)

cd /d "%~dp0"

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.7 or later from https://python.org
    pause
    exit /b 1
)

REM Install requirements if needed
echo Installing required packages...
pip install -r requirements.txt

REM Run the setup script
echo Starting MicroVolts Server Setup GUI...
python microvolts_server_setup.py

pause
