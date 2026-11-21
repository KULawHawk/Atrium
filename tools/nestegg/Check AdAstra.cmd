@echo off
rem Double-click: runs the read-only readiness check (Nestegg phase 0). Installs nothing.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Check-AdAstra.ps1" %*
echo.
pause
