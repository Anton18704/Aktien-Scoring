@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Neueste Version von GitHub holen und Pakete aktualisieren ...
git pull
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo Fertig.
pause
