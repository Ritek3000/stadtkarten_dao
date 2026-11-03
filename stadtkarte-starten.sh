#!/usr/bin/env bash
# Startet die Stadtkarten-Werkstatt im Browser (Linux / macOS).
# Beim ersten Start (und nach Änderungen an requirements.txt) richtet einrichten.py eine Python-Umgebung im
# Projektordner ein bzw. aktualisiert sie.
set -e
cd "$(dirname "$0")"

PY=python3
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "Python 3 wurde nicht gefunden. Bitte installieren, z.B.:"
    echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv"
    echo "  Fedora:         sudo dnf install python3"
    exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Python 3.10 oder neuer wird benötigt (gefunden: $("$PY" --version))."
    exit 1
fi

"$PY" einrichten.py

exec .venv/bin/python -m stadtkarte.ui "$@"
