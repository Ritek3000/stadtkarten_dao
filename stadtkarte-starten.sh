#!/usr/bin/env bash
# Startet die Stadtkarten-Werkstatt im Browser (Linux / macOS).
# Beim ersten Start wird eine Python-Umgebung im Projektordner eingerichtet.
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

if [ ! -x ".venv/bin/python" ]; then
    echo "Einrichtung beim ersten Start, das dauert einen Moment ..."
    if ! "$PY" -m venv .venv; then
        echo "Die Python-Umgebung konnte nicht angelegt werden."
        echo "Unter Debian/Ubuntu fehlt meist das Paket python3-venv:  sudo apt install python3-venv"
        exit 1
    fi
    .venv/bin/python -m pip install -q --upgrade pip
    .venv/bin/python -m pip install -q -r requirements.txt
fi

exec .venv/bin/python -m stadtkarte.ui "$@"
