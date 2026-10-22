@echo off
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" (".venv\Scripts\python.exe" pruefen.py AAPL KO CAT) else (".venv\Scripts\python.exe" pruefen.py %*)
pause
