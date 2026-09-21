@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto :erro
)
".venv\Scripts\python.exe" -m pip install -e ".[build]"
if errorlevel 1 goto :erro
".venv\Scripts\python.exe" -m PyInstaller --noconfirm NFCeMG.spec
if errorlevel 1 goto :erro
echo Executavel criado em: %cd%\dist\NFCeMG.exe
exit /b 0
:erro
echo Nao foi possivel gerar o executavel. Confira o erro acima.
pause
exit /b 1
