"""Baut die weitergebbare Version der Stadtkarten-Werkstatt für das System, auf dem es läuft.

Aufruf (im Projektordner):  Windows: .venv\\Scripts\\python packaging\\build.py
                             Linux:   .venv/bin/python packaging/build.py

Ergebnis im Ordner 'verteilung':
  Windows: Stadtkarten-Werkstatt-portable.zip         zum Entpacken und direkt Starten
           (kein Setup: eine selbstentpackende Setup.exe mit PowerShell-Skript löst bei Browsern und Virenscannern
           Fehlalarme aus)
  Linux:   Stadtkarten-Werkstatt-linux-x86_64.tar.gz  zum Entpacken und direkt Starten
Benötigt: PyInstaller (pip install pyinstaller).
PyInstaller baut nur für das eigene System - die Linux-Version entsteht unter Linux (z.B. per GitHub Actions).
"""
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

from PIL import Image, ImageDraw

NAME = "Stadtkarten-Werkstatt"
ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSION = re.search(r'__version__ = "([^"]+)"',
                    (ROOT / "stadtkarte" / "__init__.py").read_text(encoding="utf-8")).group(1)
PKG = ROOT / "packaging"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
OUT = ROOT / "verteilung"
IS_WIN = sys.platform == "win32"


def make_icon(path):
    """Programmsymbol nach dem Design System: Symbol des Sor auf Staubschwarz mit goldener Haarlinie."""
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((6, 6, 250, 250), fill=(18, 16, 14, 255), outline=(204, 180, 84, 255), width=4)
    sor = Image.open(ROOT / "stadtkarte" / "ui" / "static" / "sor-symbol.png").convert("RGBA")
    h = 206
    sor = sor.resize((round(sor.width * h / sor.height), h), Image.LANCZOS)
    img.alpha_composite(sor, ((256 - sor.width) // 2, (256 - h) // 2))
    img.save(path, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])


def run(cmd, **kw):
    print(">", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def build_app():
    BUILD.mkdir(exist_ok=True)
    icon = BUILD / ("icon.ico" if IS_WIN else "icon.png")
    make_icon(icon)
    sep = os.pathsep                      # Trennzeichen für --add-data: ';' unter Windows, ':' unter Linux
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
         "--name", NAME, *(["--icon", str(icon)] if IS_WIN else []),
         "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"), "--specpath", str(BUILD),
         "--add-data", f"{ROOT / 'stadtkarte' / 'ui' / 'index.html'}{sep}stadtkarte/ui",
         "--add-data", f"{ROOT / 'stadtkarte' / 'ui' / 'static'}{sep}stadtkarte/ui/static",
         "--add-data", f"{ROOT / 'beispiele'}{sep}beispiele",
         "--add-data", f"{ROOT / 'stadtkarte' / 'fonts'}{sep}stadtkarte/fonts",
         "--collect-binaries", "resvg_py", "--collect-all", "shapely",
         "--exclude-module", "tkinter", "--exclude-module", "PyInstaller",
         str(PKG / "werkstatt.py")], cwd=ROOT)
    return DIST / NAME


LINUX_README = """Stadtkarten-Werkstatt {version} für Linux
=========================================

Starten:   ./Stadtkarten-Werkstatt
           (öffnet die Werkstatt im Browser; zum Beenden das Terminal schließen oder Strg+C)

Optional ins Anwendungsmenü aufnehmen:
           ./installiere-menueeintrag.sh

Gespeicherte Karten landen im Dokumente-Ordner unter "Stadtkarten".
"""

LINUX_MENU = """#!/usr/bin/env bash
# Legt einen Eintrag im Anwendungsmenü an, der auf diesen Ordner zeigt.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/stadtkarten-werkstatt.desktop" <<EOD
[Desktop Entry]
Type=Application
Name=Stadtkarten-Werkstatt
Comment=Stadtkarten für Die Alte Ordnung erzeugen
Exec="$DIR/Stadtkarten-Werkstatt"
Icon=$DIR/icon.png
Terminal=true
Categories=Graphics;Game;
EOD
echo "Menüeintrag angelegt."
"""


def build_linux_archive(app):
    """tar.gz mit Programmordner, Symbol, Kurzanleitung und Skript für einen Menüeintrag (Rechte bleiben erhalten)."""
    shutil.copy(BUILD / "icon.png", app / "icon.png")
    (app / "LIESMICH.txt").write_text(LINUX_README.format(version=VERSION), encoding="utf-8")
    menu = app / "installiere-menueeintrag.sh"
    menu.write_text(LINUX_MENU, encoding="utf-8", newline="\n")
    menu.chmod(0o755)
    arch = platform.machine().lower().replace("amd64", "x86_64")
    target = OUT / f"{NAME}-linux-{arch}.tar.gz"
    with tarfile.open(target, "w:gz") as tar:
        tar.add(app, arcname=NAME)
    return target


def main():
    OUT.mkdir(exist_ok=True)
    app = build_app()
    if IS_WIN:
        portable = OUT / f"{NAME}-portable.zip"
        with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for f in sorted(app.rglob("*")):
                if f.is_file():
                    z.write(f, pathlib.Path(NAME) / f.relative_to(app))
        results = [portable]
    else:
        results = [build_linux_archive(app)]
    for p in results:
        if p is not None:
            print(f"fertig: {p}  ({p.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
