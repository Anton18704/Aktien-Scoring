@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Aktien-Scoring

if not exist ".venv\Scripts\python.exe" (
    echo Erster Start: Die Python-Umgebung wird eingerichtet. Das dauert einige Minuten ...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo Python wurde nicht gefunden. Bitte Python von https://www.python.org installieren
        echo und beim Installieren "Add python.exe to PATH" ankreuzen.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

echo.
echo ============================================================
echo   Aktien-Scoring laeuft. Dieses Fenster bitte offen lassen.
echo.
echo   Auf diesem Laptop:  http://localhost:8501
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    for /f "tokens=*" %%b in ("%%a") do echo   Auf dem iPad:       http://%%b:8501
)
echo.
echo   Beenden: dieses Fenster schliessen.
echo ============================================================
echo.
start "" http://localhost:8501
".venv\Scripts\python.exe" -m streamlit run app.py
pause
