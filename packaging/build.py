"""Baut die weitergebbare Version der Stadtkarten-Werkstatt für das System, auf dem es läuft.

Aufruf (im Projektordner):  Windows: .venv\\Scripts\\python packaging\\build.py
                             Linux:   .venv/bin/python packaging/build.py

Ergebnis im Ordner 'verteilung':
  Windows: Stadtkarten-Werkstatt-Setup.exe            Setup mit Verknüpfungen und Deinstallation (ohne Adminrechte)
           Stadtkarten-Werkstatt-portable.zip         zum Entpacken und direkt Starten
  Linux:   Stadtkarten-Werkstatt-linux-x86_64.tar.gz  zum Entpacken und direkt Starten
Benötigt: PyInstaller (pip install pyinstaller); IExpress ist in Windows enthalten.
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
    """Einfaches Programmsymbol: Turm mit Tor auf dunkelgrünem Grund."""
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, 248, 248), radius=48, fill=(37, 48, 31, 255), outline=(217, 162, 74, 255), width=10)
    d.rectangle((78, 92, 178, 214), fill=(212, 139, 58, 255), outline=(35, 30, 26, 255), width=6)
    for x in (78, 118, 158):
        d.rectangle((x, 62, x + 20, 96), fill=(212, 139, 58, 255), outline=(35, 30, 26, 255), width=6)
    d.pieslice((106, 138, 150, 182), 180, 360, fill=(35, 30, 26, 255))
    d.rectangle((106, 160, 150, 214), fill=(35, 30, 26, 255))
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
         "--add-data", f"{ROOT / 'beispiele'}{sep}beispiele",
         "--add-data", f"{ROOT / 'stadtkarte' / 'fonts'}{sep}stadtkarte/fonts",
         "--collect-binaries", "resvg_py", "--collect-all", "shapely",
         "--exclude-module", "tkinter", "--exclude-module", "PyInstaller",
         str(PKG / "werkstatt.py")], cwd=ROOT)
    return DIST / NAME


def zip_dir(src, dest):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(src))


def build_setup(app_dir):
    stage = BUILD / "setup"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    zip_dir(app_dir, stage / "app.zip")
    (stage / "install.ps1").write_text(
        (PKG / "install.ps1").read_text(encoding="utf-8").replace("__VERSION__", VERSION), encoding="utf-8-sig")
    shutil.copy(PKG / "uninstall.ps1", stage / "uninstall.ps1")
    (stage / "install.cmd").write_text(
        '@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"\r\n'
        'if errorlevel 1 pause\r\n', encoding="ascii")
    # PowerShell 5 liest Skripte ohne BOM als ANSI: Umlaute brauchen UTF-8 mit BOM
    for ps in ("uninstall.ps1",):
        (stage / ps).write_text((stage / ps).read_text(encoding="utf-8"), encoding="utf-8-sig")
    target = OUT / f"{NAME}-Setup.exe"
    files = ["app.zip", "install.cmd", "install.ps1", "uninstall.ps1"]
    sed = "\r\n".join([
        "[Version]", "Class=IEXPRESS", "SEDVersion=3",
        "[Options]", "PackagePurpose=InstallApp", "ShowInstallProgramWindow=0", "HideExtractAnimation=0",
        "UseLongFileName=1", "InsideCompressed=0", "CAB_FixedSize=0", "CAB_ResvCodeSigning=0", "RebootMode=N",
        "InstallPrompt=%InstallPrompt%", "DisplayLicense=%DisplayLicense%", "FinishMessage=%FinishMessage%",
        "TargetName=%TargetName%", "FriendlyName=%FriendlyName%", "AppLaunched=%AppLaunched%",
        "PostInstallCmd=%PostInstallCmd%", "AdminQuietInstCmd=%AdminQuietInstCmd%",
        "UserQuietInstCmd=%UserQuietInstCmd%", "SourceFiles=SourceFiles",
        "[Strings]",
        f"InstallPrompt={NAME} {VERSION} installieren?", "DisplayLicense=", "FinishMessage=",
        f"TargetName={target}", f"FriendlyName={NAME} {VERSION}",
        "AppLaunched=cmd.exe /c install.cmd", "PostInstallCmd=<None>", "AdminQuietInstCmd=", "UserQuietInstCmd=",
        *[f'FILE{i}="{fn}"' for i, fn in enumerate(files)],
        "[SourceFiles]", f"SourceFiles0={stage}\\",
        "[SourceFiles0]", *[f"%FILE{i}%=" for i in range(len(files))], ""])
    sed_path = BUILD / "setup.sed"
    sed_path.write_text(sed, encoding="mbcs")
    if target.exists():
        target.unlink()
    iexpress = pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "iexpress.exe"
    if not iexpress.exists():
        print("Hinweis: IExpress nicht gefunden - kein Setup, nur die portable ZIP.")
        return None
    run([str(iexpress), "/N", "/Q", str(sed_path)])
    if not target.exists():
        raise SystemExit("IExpress hat kein Setup erzeugt.")
    return target


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
        results = [build_setup(app), portable]
    else:
        results = [build_linux_archive(app)]
    for p in results:
        if p is not None:
            print(f"fertig: {p}  ({p.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
