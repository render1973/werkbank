@echo off
REM KI-Werkbank starten (Hub + Sidecar in zwei getrennten Fenstern)
REM Doppelklick genuegt.

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_werkbank.ps1"

pause
