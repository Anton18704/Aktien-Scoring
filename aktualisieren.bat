@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Aktien-Scoring aktualisieren

if not exist ".git" (
    echo.
    echo FEHLER: Dieser Ordner ist keine Git-Kopie ^(vermutlich aus einer ZIP-Datei^).
    echo Updates von GitHub sind hier nicht moeglich. Bitte Claude Bescheid geben.
    echo Ordner: %CD%
    echo.
    pause
    exit /b 1
)

echo Bisherige Version:
git log -1 --format="  %%h  %%cd  %%s" --date=format:"%%d.%%m.%%Y %%H:%%M"
echo.
echo Neueste Version von GitHub holen ...
git pull
if errorlevel 1 (
    echo.
    echo ============================================================
    echo   FEHLER beim Holen der neuen Version - siehe Meldung oben.
    echo   Bitte ein Foto von diesem Fenster an Claude schicken.
    echo ============================================================
    pause
    exit /b 1
)
echo.
echo Pakete aktualisieren ...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo.
    echo FEHLER beim Installieren der Pakete - siehe Meldung oben.
    pause
    exit /b 1
)
echo.
echo Jetzt installierte Version:
git log -1 --format="  %%h  %%cd  %%s" --date=format:"%%d.%%m.%%Y %%H:%%M"
echo.
echo Fertig. Jetzt start.bat doppelklicken.
pause
