@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
    py -3 main.py demo
) else (
    python main.py demo
)
if errorlevel 1 (
    echo Demo failed. Install Python 3.11+ and see README.md.
    pause
    exit /b 1
)
start "" "%~dp0results\dashboard.html"
pause

