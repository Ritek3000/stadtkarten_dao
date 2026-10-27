"""Grafische Oberfläche: kleiner lokaler Webserver, der sich im Browser öffnet.

Start:  .venv\\Scripts\\python -m stadtkarte.ui     (oder Doppelklick auf "Stadtkarte starten.bat")
"""
import base64
import contextlib
import io
import json
import os
import pathlib
import re
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import yaml
from PIL import Image

from .. import config
from ..generator import generate
from ..interaktiv import interactive_html
from ..parallel import mode as render_mode, png_async, shutdown as shutdown_renderers
from ..render import font_face_css, move_labels, render_svg, split_labels, to_pdf
from ..styles import BIOMES, DISTRICT_TYPES

def documents_dir():
    """Dokumente-Ordner des Benutzers; unter Linux über die XDG-Einstellung (z.B. ~/Dokumente)."""
    if sys.platform.startswith("linux"):
        try:
            import subprocess
            out = subprocess.run(["xdg-user-dir", "DOCUMENTS"], capture_output=True, text=True, timeout=3).stdout.strip()
            if out and pathlib.Path(out).is_dir() and pathlib.Path(out) != pathlib.Path.home():
                return pathlib.Path(out)
        except (OSError, subprocess.SubprocessError):
            pass
        for name in ("Dokumente", "Documents"):
            if (pathlib.Path.home() / name).is_dir():
                return pathlib.Path.home() / name
        return pathlib.Path.home()
    return pathlib.Path.home() / "Documents"


if getattr(sys, "frozen", False):
    # Gebündeltes Programm (PyInstaller): Dateien liegen im Programmordner, Karten gehen nach Dokumente\Stadtkarten
    BUNDLE = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(sys.executable).parent))
    EXAMPLES = BUNDLE / "beispiele"
    HTML = BUNDLE / "stadtkarte" / "ui" / "index.html"
    OUTPUT = documents_dir() / "Stadtkarten"
else:
    ROOT = pathlib.Path(__file__).resolve().parents[2]
    EXAMPLES = ROOT / "beispiele"
    OUTPUT = ROOT / "ausgabe"
    HTML = pathlib.Path(__file__).with_name("index.html")
STATIC = HTML.with_name("static")
STATIC_TYPES = {".woff2": "font/woff2", ".png": "image/png"}

PLACE_TYPES = ["gasthaus", "laden", "schmiede", "muehle", "wassermuehle", "kontor", "werft", "adelshaus",
               "palast", "rathaus", "tempel", "kathedrale", "kaserne", "friedhof", "bauernhof", "festung"]
RESULTS = {}            # Ergebnis-ID -> erzeugte Karte (die letzten paar bleiben im Speicher)
GEN_LOCK = threading.Lock()


def slug(text):
    s = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_") or "karte"


def options():
    return {
        "district_types": list(DISTRICT_TYPES),
        "place_types": PLACE_TYPES,
        "biomes": list(BIOMES),
        "examples": sorted(p.stem for p in EXAMPLES.glob("*.yaml")),
        "output_dir": str(OUTPUT),
    }


def example(name):
    path = EXAMPLES / f"{pathlib.Path(name).name}.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def webp(png, quality):
    buf = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(buf, "WEBP", quality=quality)
    return buf.getvalue()


def build(raw):
    """Erzeugt die Karte und eine schnelle Vorschau in halber Auflösung. Die volle Auflösung (ohne
    Beschriftung) entsteht gleichzeitig in einem eigenen Render-Prozess; die Oberfläche holt sie direkt nach der
    Vorschau. Dasselbe Bild dient später auch der interaktiven Karte."""
    cfg = config.from_dict(raw)
    out = io.StringIO()
    t0 = time.time()
    with GEN_LOCK, contextlib.redirect_stdout(out):
        m = generate(cfg)
        svg = render_svg(m)
        base, labels = split_labels(svg)   # die Ansicht zeigt die Beschriftung als verschiebbare Ebene darüber
        small_job = png_async(base, zoom=0.5)
        view_job = png_async(base)
        small = small_job.result()
    rid = uuid.uuid4().hex[:12]
    while len(RESULTS) >= 4:
        RESULTS.pop(next(iter(RESULTS)))
    RESULTS[rid] = {"svg": svg, "base": base, "png": None, "view": view_job, "lock": threading.Lock(), "W": m["W"],
                    "name": cfg["name"],
                    "stem": f"{slug(cfg['name'])}_{cfg['seed']}" + ("_nacht" if cfg["ausgabe"].get("nacht") else "")}
    if (os.cpu_count() or 1) >= 4:   # genug Kerne: PNG mit Beschriftung vorsorglich schon rendern
        start_png(RESULTS[rid])
    return {
        "id": rid,
        "W": m["W"],
        "labels": labels,
        "preview": "data:image/webp;base64," + base64.b64encode(webp(small, 88)).decode(),
        "hints": [ln.replace("Hinweis: ", "") for ln in out.getvalue().splitlines() if ln.strip()],
        "stats": {"gebaeude": len(m["buildings"]) + len(m["suburbs"]), "baeume": len(m["trees"]),
                  "sekunden": round(time.time() - t0, 1), "rendern": render_mode()},
    }


def start_png(res):
    """Startet das PNG mit Beschriftung im Hintergrund (nur einmal, auch wenn mehrere gleichzeitig fragen)."""
    with res["lock"]:
        if res["png"] is None:
            res["png"] = png_async(res["svg"])
        return res["png"]


def full_png(res):
    return start_png(res).result()


def view_png(res):
    """Volle Auflösung ohne Beschriftung für die Ansicht und die interaktive Karte."""
    return res["view"].result()


def set_labels(res, moved):
    """Übernimmt von Hand verschobene Beschriftungen in die fertige Karte (ohne sie neu zu erzeugen)."""
    moved = config.label_offsets(moved)
    with res["lock"]:
        res["svg"] = move_labels(res["svg"], moved, res["W"])
        res["png"] = None


def file_bytes(res, fmt):
    if fmt == "svg":
        return res["svg"].encode("utf-8"), "image/svg+xml"
    if fmt == "png":
        return full_png(res), "image/png"
    if fmt == "webp":
        return webp(full_png(res), 92), "image/webp"
    if fmt == "pdf":
        buf = io.BytesIO()
        to_pdf(full_png(res), buf)
        return buf.getvalue(), "application/pdf"
    if fmt == "html":
        return interactive_html(res["svg"], res["name"], base_png=view_png(res)).encode("utf-8"), "text/html; charset=utf-8"
    raise ValueError(f"Unbekanntes Format: {fmt}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):   # Konsole ruhig halten
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n).decode("utf-8")

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/":
                self.send(200, HTML.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            elif url.path.startswith("/static/"):   # Schriften und Sor-Symbol des Design Systems
                path = STATIC / pathlib.Path(url.path).name
                if path.suffix not in STATIC_TYPES or not path.is_file():
                    return self.send(404, {"error": "Nicht gefunden."})
                self.send(200, path.read_bytes(), STATIC_TYPES[path.suffix], {"Cache-Control": "max-age=86400"})
            elif url.path == "/api/options":
                self.send(200, options())
            elif url.path == "/api/example":
                self.send(200, example(q.get("name", "hafenstadt")))
            elif url.path == "/api/full":   # volle Auflösung für die Ansicht (wartet, bis sie fertig ist)
                res = RESULTS.get(q.get("id", ""))
                if res is None:
                    return self.send(404, {"error": "Karte nicht mehr im Speicher."})
                self.send(200, webp(view_png(res), 88), "image/webp")
            elif url.path == "/api/font.css":
                self.send(200, font_face_css(), "text/css; charset=utf-8")
            elif url.path == "/api/download":
                res = RESULTS.get(q.get("id", ""))
                if res is None:
                    return self.send(404, {"error": "Karte nicht mehr im Speicher - bitte neu erzeugen."})
                data, ctype = file_bytes(res, q.get("format", "png"))
                name = f"{res['stem']}.{q.get('format', 'png')}"
                self.send(200, data, ctype, {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
            else:
                self.send(404, {"error": "Nicht gefunden"})
        except Exception as e:  # noqa: BLE001 - Fehler an die Oberfläche melden
            self.send(500, {"error": str(e)})

    def do_POST(self):
        url = urlparse(self.path)
        try:
            if url.path == "/api/generate":
                self.send(200, build(json.loads(self.body())))
            elif url.path == "/api/labels":
                data = json.loads(self.body())
                res = RESULTS.get(data.get("id", ""))
                if res is None:
                    return self.send(404, {"error": "Karte nicht mehr im Speicher - bitte neu erzeugen."})
                set_labels(res, data.get("beschriftung"))
                self.send(200, {"ok": True})
            elif url.path == "/api/yaml":
                raw = json.loads(self.body())
                text = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
                self.send(200, text, "text/yaml; charset=utf-8")
            elif url.path == "/api/parse":
                self.send(200, yaml.safe_load(self.body()) or {})
            elif url.path == "/api/save":
                res = RESULTS.get(json.loads(self.body()).get("id", ""))
                if res is None:
                    return self.send(404, {"error": "Karte nicht mehr im Speicher - bitte neu erzeugen."})
                OUTPUT.mkdir(parents=True, exist_ok=True)
                start_png(res)   # PNG mit Beschriftung rendert schon, während SVG geschrieben wird
                paths = []
                for fmt in ("svg", "png", "pdf", "html"):
                    path = OUTPUT / f"{res['stem']}.{fmt}"
                    path.write_bytes(file_bytes(res, fmt)[0])
                    paths.append(str(path))
                self.send(200, {"paths": paths, "folder": str(OUTPUT)})
            else:
                self.send(404, {"error": "Nicht gefunden"})
        except (ValueError, yaml.YAMLError) as e:
            self.send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.send(500, {"error": f"{type(e).__name__}: {e}"})


def main():
    import argparse
    ap = argparse.ArgumentParser(prog="stadtkarte.ui", description="Startet die Stadtkarten-Werkstatt im Browser.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--kein-browser", action="store_true", help="Browser nicht automatisch öffnen")
    args = ap.parse_args()
    server = None
    for port in range(args.port, args.port + 25):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit("Kein freier Port gefunden.")
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Stadtkarten-Werkstatt läuft auf {url}")
    print("Zum Beenden dieses Fenster schließen (oder Strg+C).")
    if not args.kein_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_renderers()


if __name__ == "__main__":
    main()
