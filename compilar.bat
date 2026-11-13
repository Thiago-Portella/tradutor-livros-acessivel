@echo off
chcp 65001 >nul
cd /d "T:\codigos\tradutor_livros"
taskkill /F /IM TradutorLivros.exe >nul 2>&1
echo Iniciando compilacao com PyInstaller... > build.log
C:\Python314\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed --name "TradutorLivros" --exclude-module pymupdf_layout --exclude-module pymupdf4llm --exclude-module onnxruntime --exclude-module scipy --exclude-module numpy "T:\codigos\tradutor_livros\book_translator.py" >> build.log 2>&1
echo EXIT_CODE=%ERRORLEVEL% >> build.log
