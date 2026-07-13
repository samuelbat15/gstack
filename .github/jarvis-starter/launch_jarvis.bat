@echo off
cd /d "%~dp0"
python jarvis.py --gui
if errorlevel 1 (
    echo.
    echo Jarvis a rencontre une erreur au demarrage.
    pause
)
