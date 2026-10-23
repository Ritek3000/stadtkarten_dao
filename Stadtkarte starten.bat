@echo off
rem Startet die Stadtkarten-Werkstatt im Browser. Beim ersten Mal wird die Umgebung eingerichtet.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Einrichtung beim ersten Start, das dauert einen Moment ...
  python -m venv .venv || goto fehler
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto fehler
)
".venv\Scripts\python.exe" -m stadtkarte.ui
goto :eof
:fehler
echo.
echo Einrichtung fehlgeschlagen. Ist Python 3.10 oder neuer installiert?
pause
