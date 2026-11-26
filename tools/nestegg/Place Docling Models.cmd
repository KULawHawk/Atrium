@echo off
rem Double-click (Decision 167 A): fills %USERPROFILE%\.conclave\models\docling with Docling's models from the saved
rem copies only (home copy first, then the private release through your own GitHub CLI sign-in), every file
rem sha256-checked against its pin. Never overwrites a file with other bytes; deletes nothing. About 1.3 GB.
py -3.13 -I "%~dp0place_docling_models.py" %*
echo.
pause
