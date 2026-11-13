@echo off
chcp 65001 >nul
cd /d "%~dp0"
taskkill /F /IM TradutorLivros.exe >nul 2>&1
echo Iniciando compilacao com PyInstaller... > build.log
if exist "C:\Python314\python.exe" (
    set "PY_BIN=C:\Python314\python.exe"
) else (
    set "PY_BIN=python"
)
"%PY_BIN%" -m PyInstaller --noconfirm --clean "%~dp0TradutorLivros.spec" >> build.log 2>&1
echo EXIT_CODE=%ERRORLEVEL% >> build.log
