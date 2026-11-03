@echo off
rem Startet die Stadtkarten-Werkstatt im Browser. Beim ersten Start (und nach Aenderungen an requirements.txt)
rem richtet einrichten.py die Python-Umgebung ein bzw. aktualisiert sie.
cd /d "%~dp0"
python einrichten.py || goto fehler
".venv\Scripts\python.exe" -m stadtkarte.ui
goto :eof
:fehler
echo.
echo Einrichtung fehlgeschlagen. Ist Python 3.10 oder neuer installiert?
pause
