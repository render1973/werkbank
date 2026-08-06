@echo off
REM Besprechung-Protokoll-Pipeline starten
REM Doppelklick genügt — venv wird aktiviert, CUDA-Pfade gesetzt, App gestartet.

cd /d "%~dp0"

call venv\Scripts\activate.bat

set PATH=%~dp0venv\Lib\site-packages\nvidia\cublas\bin;%PATH%
set PATH=%~dp0venv\Lib\site-packages\nvidia\cudnn\bin;%PATH%

echo.
echo ============================================================
echo Starte Besprechung-Protokoll-Pipeline...
echo Browser oeffnen: http://127.0.0.1:5000
echo Zum Beenden: Strg+C, dann eine Taste druecken
echo ============================================================
echo.

python app.py

pause
