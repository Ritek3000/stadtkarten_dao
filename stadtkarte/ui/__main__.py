"""Grafische Oberfläche: kleiner lokaler Webserver, der sich im Browser öffnet.

Start:  .venv\\Scripts\\python -m stadtkarte.ui     (oder Doppelklick auf "Stadtkarte starten.bat")
"""
import base64
import contextlib
import io
import json
import os
import pathlib
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from concurrent.futures import Future
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import yaml

from .. import __version__, config, webpaket
from ..bilder import png_to_webp
from ..generator import building_count, generate
from ..interaktiv import interactive_html
from ..parallel import mode as render_mode, png_async, shutdown as shutdown_renderers
from ..render import font_face_css, move_labels, prewarm, render_svg, split_labels, to_pdf
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
RESULTS_LOCK = threading.Lock()   # RESULTS wird von parallelen Anfragen verändert
MAX_BODY = 8 * 1024 * 1024        # Stadtbeschreibung, Einstellungen und Beschriftungen sind winzig


def options():
    return {
        "district_types": list(DISTRICT_TYPES),
        "place_types": PLACE_TYPES,
        "biomes": list(BIOMES),
        "examples": sorted(p.stem for p in EXAMPLES.glob("*.yaml")),
        "output_dir": str(OUTPUT),
        "version": __version__,
    }


def example(name):
    path = EXAMPLES / f"{pathlib.Path(name).name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(name)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class Abgebrochen(Exception):
    """Die Nachtkarte wurde nicht mehr gebraucht, weil eine neue Karte angefordert wurde."""


def new_version(svg):
    """Eine Ausgabe der Karte (Tag oder Nacht) mit ihren Bildern: Vorschau in halber Auflösung und volle Auflösung ohne
    Beschriftung (für die Ansicht und die interaktive Karte). Das PNG mit Beschriftung entsteht erst auf Anfrage."""
    base, labels = split_labels(svg)   # die Ansicht zeigt die Beschriftung als verschiebbare Ebene darüber
    return {"svg": svg, "labels": labels, "png": None, "klein": png_async(base, zoom=0.5), "view": png_async(base)}


def build(raw):
    """Erzeugt die Tagkarte und eine schnelle Vorschau in halber Auflösung. Die volle Auflösung (ohne
    Beschriftung) entsteht gleichzeitig in einem eigenen Render-Prozess; die Oberfläche holt sie direkt nach der
    Vorschau. Dasselbe Bild dient später auch der interaktiven Karte. Danach zeichnet ein Hintergrund-Thread aus
    derselben Stadt die Nachtkarte (build_night), zum Umschalten in der Ansicht."""
    cfg = config.from_dict(raw)
    out = io.StringIO()
    t0 = time.time()
    stop_night()   # eine noch nicht fertige Nachtkarte einer älteren Karte wird nicht mehr gebraucht
    with GEN_LOCK, contextlib.redirect_stdout(out):
        prewarm(cfg)   # Texturen, die nicht von der Stadt abhängen, rechnen schon während des Generators
        m = generate(cfg)
        tag = new_version(render_svg(m, nacht=False))   # die Tagkarte zuerst: nur auf sie wartet man
        small = tag["klein"].result()
    rid = uuid.uuid4().hex[:12]
    # Gelände ohne Stadt (Zwischenschritt beim Zeichnen der Mauer) braucht keine Nachtkarte
    night = bool(cfg["ausgabe"].get("nachtkarte", True)) and not m.get("gelaende_nur")
    res = {"v": {"tag": tag, "nacht": None}, "lock": threading.Lock(), "W": m["W"],
           "name": cfg["name"], "raw": raw, "cfg": cfg, "orte": webpaket.places(m),
           "raster": int(cfg["ausgabe"].get("raster") or 0) > 0,
           "stem": f"{config.slug(cfg['name'])}_{cfg['seed']}",
           "nacht": Future() if night else None,   # wird fertig, sobald die Nachtkarte gezeichnet ist
           "abbruch": threading.Event(), "verschoben": None}   # verschoben: von Hand verschobene Beschriftungen
    with RESULTS_LOCK:
        while len(RESULTS) >= 4:
            RESULTS.pop(next(iter(RESULTS)))
        RESULTS[rid] = res
    if (os.cpu_count() or 1) >= 4:   # genug Kerne: PNG mit Beschriftung vorsorglich schon rendern
        start_png(res, tag)
    if night:   # erst jetzt, damit die Aufträge der Tagkarte in der Warteschlange der Render-Prozesse vorn stehen
        threading.Thread(target=build_night, args=(res, m), daemon=True, name="nachtkarte").start()
    return {
        "id": rid,
        "W": m["W"],
        "labels": tag["labels"],
        "preview": "data:image/webp;base64," + base64.b64encode(png_to_webp(small, 88)).decode(),
        "hints": [ln.replace("Hinweis: ", "") for ln in out.getvalue().splitlines() if ln.strip()],
        "gelaende_nur": bool(m.get("gelaende_nur")),
        "nacht": night,
        "stats": {"gebaeude": building_count(m), "baeume": len(m["trees"]),
                  "sekunden": round(time.time() - t0, 1), "rendern": render_mode()},
    }


def build_night(res, m):
    """Zeichnet die Nachtkarte aus demselben Ergebnis des Generators wie die Tagkarte (nur die Darstellung ist anders;
    die Texturen liegen schon im Zwischenspeicher, das dauert nur wenige Sekunden) und reiht ihre Bilder hinter die der
    Tagkarte ein. Läuft in einem eigenen Thread; wer auf die Nachtkarte wartet, wartet auf res["nacht"]."""
    fut = res["nacht"]
    many = (os.cpu_count() or 1) >= 4
    try:
        if not many:   # wenige Kerne: die Tagkarte soll nicht auf die Nachtkarte warten, also erst ihre Ansicht abwarten
            res["v"]["tag"]["view"].result()
        with GEN_LOCK:
            if res["abbruch"].is_set():
                raise Abgebrochen("eine neue Karte wurde angefordert")
            with contextlib.redirect_stdout(io.StringIO()):
                svg = render_svg(m, nacht=True)
        with res["lock"]:
            if res["abbruch"].is_set():
                raise Abgebrochen("eine neue Karte wurde angefordert")
            if res["verschoben"] is not None:   # inzwischen verschobene Beschriftungen gelten auch hier
                svg = move_labels(svg, res["verschoben"], res["W"])
            ver = new_version(svg)
            res["v"]["nacht"] = ver
        fut.set_result(ver)
    except Abgebrochen as e:
        fut.set_exception(e)
        return
    except Exception as e:  # noqa: BLE001 - an alle weiterreichen, die auf die Nachtkarte warten
        traceback.print_exc()
        fut.set_exception(e)
        return
    if many:   # wie bei der Tagkarte das PNG mit Beschriftung vorsorglich rendern, aber erst nach den Ansichten
        try:
            ver["view"].result()
            if not res["abbruch"].is_set():
                start_png(res, ver)
        except Exception:  # noqa: BLE001 - nur ein Vorlauf, auf Anfrage rendert start_png wie sonst
            pass


def stop_night():
    """Eine neue Karte wird angefordert: die Nachtkarte älterer Karten, die noch nicht fertig ist, wird nicht mehr
    gebraucht. Ihre wartenden Render-Aufträge werden zurückgenommen, damit die neue Karte nicht dahinter wartet."""
    with RESULTS_LOCK:
        old = list(RESULTS.values())
    for res in old:
        with res["lock"]:
            res["abbruch"].set()
            ver = res["v"]["nacht"]
            for key in ("klein", "view", "png"):
                job = ver.get(key) if ver else None
                if job is not None:
                    job.cancel()


def get_version(res, name):
    """Tag- oder Nachtkarte einer Ergebnis-ID; die Nachtkarte wartet, bis sie gezeichnet ist."""
    name = name or "tag"
    if name == "tag":
        return res["v"]["tag"]
    if name != "nacht":
        raise ValueError(f"Unbekannte Ansicht: {name}")
    if res["nacht"] is None:
        raise ValueError("Die Nachtkarte wurde nicht mitberechnet (Ausgabe: „Nachtkarte mitberechnen“).")
    try:
        return res["nacht"].result()
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Die Nachtkarte ist nicht verfügbar: {e}")


def start_png(res, ver):
    """Startet das PNG mit Beschriftung im Hintergrund (nur einmal, auch wenn mehrere gleichzeitig fragen)."""
    with res["lock"]:
        if ver["png"] is None:
            ver["png"] = png_async(ver["svg"])
        return ver["png"]


def full_png(res, ver):
    return start_png(res, ver).result()


def view_png(ver):
    """Volle Auflösung ohne Beschriftung für die Ansicht und die interaktive Karte."""
    return ver["view"].result()


def set_labels(res, moved):
    """Übernimmt von Hand verschobene Beschriftungen in die fertige Karte (ohne sie neu zu erzeugen), in Tag- und
    Nachtkarte; eine Nachtkarte, die noch gezeichnet wird, bekommt sie, sobald sie fertig ist (build_night)."""
    moved = config.label_offsets(moved)
    with res["lock"]:
        res["verschoben"] = moved
        for ver in res["v"].values():
            if ver is not None:
                ver["svg"] = move_labels(ver["svg"], moved, res["W"])
                ver["png"] = None
        res["raw"] = dict(res["raw"], beschriftung=moved)   # für stadt.yaml im Web-Paket


def stem(res, name):
    """Dateiname ohne Endung; die Nachtkarte trägt wie immer den Zusatz _nacht."""
    return res["stem"] + ("_nacht" if name == "nacht" else "")


def web_files(res, ver, name):
    """Dateien des Web-Pakets. Das Bild ohne Beschriftung ist meist schon für die Ansicht gerendert; nur mit Raster
    entsteht es neu (das Paket bleibt ohne Raster). Das Paket nennt in orte.json und stadt.yaml seine Version."""
    base = png_async(webpaket.base_svg(ver["svg"])).result() if res["raster"] else view_png(ver)
    cfg = dict(res["cfg"], ausgabe=dict(res["cfg"]["ausgabe"], nacht=name == "nacht"))
    return webpaket.files(ver["svg"], dict(res["orte"], nacht=name == "nacht"), res["raw"], cfg, base)


def file_bytes(res, fmt, name="tag"):
    ver = get_version(res, name)
    if fmt == "svg":
        return ver["svg"].encode("utf-8"), "image/svg+xml"
    if fmt == "png":
        return full_png(res, ver), "image/png"
    if fmt == "webp":
        return png_to_webp(full_png(res, ver), 92), "image/webp"
    if fmt == "pdf":
        buf = io.BytesIO()
        to_pdf(full_png(res, ver), buf)
        return buf.getvalue(), "application/pdf"
    if fmt == "web":
        return webpaket.zip_bytes(webpaket.folder_name(res["cfg"]), web_files(res, ver, name)), "application/zip"
    if fmt == "html":
        return interactive_html(ver["svg"], res["name"], base_png=view_png(ver)).encode("utf-8"), "text/html; charset=utf-8"
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
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            raise ValueError("Ungültige Längenangabe der Anfrage.") from None
        if not 0 <= n <= MAX_BODY:   # negativ würde bis zum Verbindungsende lesen und den Thread blockieren
            raise ValueError(f"Die Anfrage ist zu groß (höchstens {MAX_BODY // 1024 // 1024} MB).")
        return self.rfile.read(n).decode("utf-8")

    def from_here(self):
        """Nur Anfragen der Werkstatt selbst: Host und, wenn der Browser sie mitschickt, Origin müssen die eigene
        Adresse sein. Das hält Aufrufe fremder Webseiten fern (z.B. ein Formular, das /api/generate anstößt) und
        schützt vor DNS-Rebinding, bei dem eine fremde Adresse auf 127.0.0.1 zeigt."""
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host, origin = self.headers.get("Host"), self.headers.get("Origin")
        return (host is None or host.lower() in hosts) and (origin is None or origin.lower() in {f"http://{h}" for h in hosts})

    def do_GET(self):
        if not self.from_here():
            return self.send(403, {"error": "Anfrage von fremder Herkunft abgelehnt."})
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
                self.send(200, png_to_webp(view_png(get_version(res, q.get("version"))), 88), "image/webp")
            elif url.path == "/api/nacht":   # Vorschau der Nachtkarte (wartet, bis sie gezeichnet ist)
                res = RESULTS.get(q.get("id", ""))
                if res is None:
                    return self.send(404, {"error": "Karte nicht mehr im Speicher."})
                self.send(200, png_to_webp(get_version(res, "nacht")["klein"].result(), 88), "image/webp")
            elif url.path == "/api/font.css":
                self.send(200, font_face_css(), "text/css; charset=utf-8")
            elif url.path == "/api/download":
                res = RESULTS.get(q.get("id", ""))
                if res is None:
                    return self.send(404, {"error": "Karte nicht mehr im Speicher - bitte neu erzeugen."})
                fmt, ver = q.get("format", "png"), q.get("version", "tag")
                data, ctype = file_bytes(res, fmt, ver)
                name = (f"{webpaket.folder_name(res['cfg'])}{'_nacht' if ver == 'nacht' else ''}.zip" if fmt == "web"
                        else f"{stem(res, ver)}.{fmt}")
                self.send(200, data, ctype, {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
            else:
                self.send(404, {"error": "Nicht gefunden"})
        except FileNotFoundError:
            self.send(404, {"error": "Nicht gefunden."})
        except ValueError as e:
            self.send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001 - Fehler an die Oberfläche melden
            traceback.print_exc()
            self.send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        if not self.from_here():
            return self.send(403, {"error": "Anfrage von fremder Herkunft abgelehnt."})
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
                data = json.loads(self.body())
                res = RESULTS.get(data.get("id", ""))
                if res is None:
                    return self.send(404, {"error": "Karte nicht mehr im Speicher - bitte neu erzeugen."})
                ver = data.get("version") or "tag"   # gespeichert wird die Version, die gerade zu sehen ist
                OUTPUT.mkdir(parents=True, exist_ok=True)
                start_png(res, get_version(res, ver))   # PNG mit Beschriftung rendert schon, während SVG geschrieben wird
                paths = []
                for fmt in ("svg", "png", "pdf", "html"):
                    path = OUTPUT / f"{stem(res, ver)}.{fmt}"
                    path.write_bytes(file_bytes(res, fmt, ver)[0])
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
