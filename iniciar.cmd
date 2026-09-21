@echo off
cd /d "%~dp0"
if exist "dist\NFCeMG.exe" (
    start "" "dist\NFCeMG.exe"
    exit /b 0
)
if not exist ".venv\Scripts\python.exe" (
    echo Execute primeiro os passos de instalacao descritos no README.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m nfce_mg gui
if errorlevel 1 pause
