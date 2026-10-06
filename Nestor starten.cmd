@echo off
rem Nestor starten: Coach im Hintergrund, Dashboard im Vollbild. Fenster zu = Coach aus.
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\nestor_starten.ps1"
