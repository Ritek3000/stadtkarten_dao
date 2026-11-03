"""Richtet die Python-Umgebung (.venv) der Stadtkarten-Werkstatt ein oder bringt sie auf den Stand von requirements.txt.

Wird von "Stadtkarte starten.bat" und stadtkarte-starten.sh vor jedem Start aufgerufen (nur Standardbibliothek):
  - fehlt die Umgebung, wird sie angelegt und eingerichtet;
  - hat sich requirements.txt seit der letzten erfolgreichen Installation geändert (z.B. nach einem Update des
    Programms), werden die Pakete nachinstalliert;
  - brach eine Einrichtung ab (z.B. kein Netz), wird sie beim nächsten Start wiederholt, statt mit einer halben
    Umgebung zu starten;
  - lassen sich die Pakete nicht aktualisieren, die vorhandene Umgebung funktioniert aber, startet das Programm damit
    (Rechner ohne Netz).
Exit-Code 0 = Umgebung ist startklar, sonst 1 mit einer Meldung.
"""
import hashlib
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
MIN_PYTHON = (3, 10)
CHECK_IMPORTS = "import numpy, PIL, resvg_py, shapely, yaml"   # die Pakete aus requirements.txt


def venv_python(venv):
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def setup(root=ROOT, run=subprocess.run):
    """Bringt root/.venv auf den Stand von root/requirements.txt. Liefert den Exit-Code (0 = startklar)."""
    if sys.version_info < MIN_PYTHON:
        print("Python %d.%d oder neuer wird benötigt (gefunden: %s)." % (MIN_PYTHON + (sys.version.split()[0],)))
        return 1
    venv, requirements = root / ".venv", root / "requirements.txt"
    py, stamp = venv_python(venv), venv / ".requirements.sha256"
    want = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if py.exists() and stamp.exists() and stamp.read_text(encoding="utf-8").strip() == want:
        return 0   # eingerichtet, requirements.txt unverändert
    first = not py.exists()
    if first:
        print("Einrichtung beim ersten Start, das dauert einen Moment ...")
        if run([sys.executable, "-m", "venv", str(venv)]).returncode != 0:
            print("Die Python-Umgebung konnte nicht angelegt werden.")
            print("Unter Debian/Ubuntu fehlt meist das Paket python3-venv:  sudo apt install python3-venv")
            shutil.rmtree(venv, ignore_errors=True)   # keine halbe Umgebung zurücklassen
            return 1
        run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"])   # nur ein Komfort: scheitert er, geht es weiter
    else:
        print("Die Python-Umgebung wird auf den Stand von requirements.txt gebracht ...")
    if run([str(py), "-m", "pip", "install", "-q", "-r", str(requirements)]).returncode == 0:
        stamp.write_text(want, encoding="utf-8")
        return 0
    if not first and run([str(py), "-c", CHECK_IMPORTS], capture_output=True).returncode == 0:
        print("Warnung: Die Pakete konnten nicht aktualisiert werden (keine Verbindung?). "
              "Das Programm startet mit den vorhandenen Paketen.")
        return 0   # den Stempel nicht schreiben: der nächste Start versucht es erneut
    print("Die Einrichtung ist fehlgeschlagen. Besteht eine Internetverbindung und ist Python %d.%d oder neuer "
          "installiert?" % MIN_PYTHON)
    print("Beim nächsten Start wird sie wiederholt.")
    return 1


if __name__ == "__main__":
    sys.exit(setup())
