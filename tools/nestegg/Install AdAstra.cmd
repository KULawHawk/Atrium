@echo off
rem Double-click: installs the APEX suite in one go (Nestegg phases 1 and 2). Each Windows security box is yours to answer.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-AdAstra.ps1" %*
echo.
pause
