"""Baut die Browserversion der Stadtkarten-Werkstatt: ein Ordner mit rein statischen Dateien.

Aufruf (im Projektordner):  Windows: .venv\\Scripts\\python packaging\\web.py
                             Linux:   .venv/bin/python packaging/web.py

Ergebnis im Ordner 'build/web'. Er lässt sich auf jeden Webspace hochladen (auch in einen Unterordner) oder per
GitHub Pages veröffentlichen (.github/workflows/web.yml). Der Python-Kern läuft dort mit Pyodide im Browser; Pyodide,
numpy, Shapely, Pillow, PyYAML und resvg-wasm lädt der Browser beim ersten Besuch vom CDN jsDelivr.

  index.html      die Oberfläche (stadtkarte/ui/index.html, Pfade relativ, dazu werkstatt.js und die Kopfzeile von dao-rpg.de)
  werkstatt.js    leitet die /api-Aufrufe der Oberfläche an den Web Worker um
  worker.js       Web Worker: Pyodide, resvg-wasm und stadtkarte/ui/browser.py
  werkstatt.zip   der Python-Kern (stadtkarte), die Beispiele und der Ersatz für resvg-py
  font.css        EB Garamond für die Beschriftung in der Ansicht
  static/         Schriften und Symbole des Design Systems

Zum Ausprobieren am Rechner:  python -m http.server -d build/web 8000   (dann http://localhost:8000/)
"""
import pathlib
import shutil
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "build" / "web"
UI = ROOT / "stadtkarte" / "ui"
WEB = ROOT / "web"


def kopfzeile(html):
    """Setzt in der Browserversion die Kopfzeile der Webseite dao-rpg.de ein (web/kopfzeile.*): Sor-Symbol, Hauptnavigation,
    Hell/Dunkel-Schalter und Bürger-Menü wie bei Heldenmaschine und Daten-Editor. Die lokale Oberfläche behält ihre schlichte
    Kopfzeile; sie braucht weder Webseite noch Menü."""
    css, kopf, js = ((WEB / n).read_text(encoding="utf-8") for n in ("kopfzeile.css", "kopfzeile.html", "kopfzeile.js"))

    def ersetzen(von, bis, neu, was, bis_mit=False):
        i = html.find(von)
        j = html.find(bis, i + 1) if i >= 0 else -1
        if i < 0 or j < 0:
            raise SystemExit(f"index.html: {was} nicht gefunden - passt packaging/web.py noch zur Oberfläche?")
        return html[:i] + neu + html[j + (len(bis) if bis_mit else 0):]

    html = ersetzen("<title>Stadtkarten-Werkstatt</title>", "</title>", "<title>Stadtkartenwerkstatt – Die Alte Ordnung", "Titel")
    html = ersetzen("/* Kopfzeile */", "[hidden] { display: none !important; }", css, "Kopfzeilen-Stile")
    html = ersetzen('<header class="bar">', "</header>", kopf.rstrip("\n"), "Kopfzeile", bis_mit=True)
    return ersetzen('$("#btnTheme").onclick', "\n// Stadtbeschreibung (.yaml)", js, "Hell/Dunkel-Schalter")


def index_html():
    html = kopfzeile((UI / "index.html").read_text(encoding="utf-8"))
    for alt, neu in (('href="/api/font.css"', 'href="font.css"'), ('"/static/', '"static/'), ("url(/static/", "url(static/")):
        if alt not in html:
            raise SystemExit(f"index.html: {alt!r} nicht gefunden - passt packaging/web.py noch zur Oberfläche?")
        html = html.replace(alt, neu)
    i = html.index("<script>")   # vor dem ersten Skript, damit die Umleitung steht, bevor die Seite /api aufruft
    return html[:i] + '<script src="werkstatt.js"></script>\n' + html[i:]


def werkstatt_zip(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted((ROOT / "stadtkarte").rglob("*")):
            rel = f.relative_to(ROOT)
            if f.is_dir() or "__pycache__" in rel.parts or rel.parts[:3] == ("stadtkarte", "ui", "static") \
                    or f.suffix not in {".py", ".ttf", ".txt"}:
                continue
            z.write(f, rel.as_posix())
        for f in sorted((ROOT / "beispiele").glob("*.yaml")):
            z.write(f, f.relative_to(ROOT).as_posix())
        z.write(ROOT / "web" / "resvg_py.py", "resvg_py.py")


def main():
    from stadtkarte.render import font_face_css
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "static").mkdir(parents=True)
    (OUT / "index.html").write_text(index_html(), encoding="utf-8")
    (OUT / "font.css").write_text(font_face_css(), encoding="utf-8")
    for name in ("werkstatt.js", "worker.js"):
        shutil.copy2(ROOT / "web" / name, OUT / name)
    for f in (UI / "static").iterdir():
        shutil.copy2(f, OUT / "static" / f.name)
    werkstatt_zip(OUT / "werkstatt.zip")
    (OUT / ".nojekyll").write_text("")   # GitHub Pages: Dateien unverändert ausliefern
    größe = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"Browserversion in {OUT} ({größe / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
