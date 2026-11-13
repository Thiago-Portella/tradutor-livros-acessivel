@echo off
chcp 65001 >nul
C:\Python314\python.exe -X utf8 "%~dp0book_translator.py" %*
