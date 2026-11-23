@echo off
rem Double-click: fills the home copy (%USERPROFILE%\AdAstra\saved) from the private saved-copy release, every piece
rem hash-checked (Decision 30 A). Uses your own GitHub CLI sign-in (gh auth login is your step). Deletes nothing.
py -3.13 -I "%~dp0saved_copies.py" pull --to "%USERPROFILE%\AdAstra\saved" %*
echo.
pause
