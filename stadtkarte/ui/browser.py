"""Die Werkstatt im Browser: dieselben /api-Aufrufe wie der lokale Server (ui/__main__.py), aber für Pyodide.

Im Browser gibt es weder Prozesse noch Threads. Der Python-Kern läuft dort in einem Web Worker (web/worker.js), der
die Anfragen der Oberfläche nacheinander an handle() gibt. Die Bilder entstehen deshalb erst, wenn die Oberfläche sie
abholt (Vorschau sofort, volle Ansicht und Nachtkarte danach), statt wie am Rechner gleichzeitig in eigenen Prozessen.
Alles Übrige (Optionen, Downloads, Beschriftungen) kommt unverändert aus ui/__main__.py.
"""
import base64
import importlib
import io
import json
import time
import uuid
import zipfile
from urllib.parse import parse_qs

import yaml

from .. import config, webpaket
from ..bilder import png_to_webp
from ..generator import building_count, generate
from ..render import move_labels, render_svg, split_labels, to_png

desk = importlib.import_module("stadtkarte.ui.__main__")   # der lokale Server; hier nur seine Hilfsfunktionen

RESULTS = {}   # Ergebnis-ID -> erzeugte Karte; im Browser ist der Speicher knapper, daher nur die letzten zwei


class Spaeter:
    """Wie ein Future (result(), cancel()), rechnet aber erst beim ersten result() und merkt sich das Ergebnis."""

    def __init__(self, fn):
        self._fn, self._fertig, self._wert = fn, False, None

    def result(self):
        if not self._fertig:
            self._wert, self._fertig = self._fn(), True
        return self._wert

    def cancel(self):
        return False


def new_version(svg):
    """Wie ui/__main__.new_version, nur entstehen Vorschau und volle Ansicht erst auf Anfrage."""
    base, labels = split_labels(svg)
    return {"svg": svg, "labels": labels, "png": None,
            "klein": Spaeter(lambda: to_png(base, zoom=0.5)), "view": Spaeter(lambda: to_png(base))}


def build(raw):
    """Tagkarte erzeugen und ihre Vorschau zeichnen; die Nachtkarte entsteht erst, wenn die Oberfläche sie abholt."""
    cfg = config.from_dict(raw)
    zeiten = {}
    t0 = t = time.perf_counter()
    m = generate(cfg)
    zeiten["generator"], t = time.perf_counter() - t, time.perf_counter()
    tag = new_version(render_svg(m, nacht=False))
    zeiten["svg"], t = time.perf_counter() - t, time.perf_counter()
    small = tag["klein"].result()
    zeiten["vorschau"] = time.perf_counter() - t
    gesamt = time.perf_counter() - t0
    rid = uuid.uuid4().hex[:12]
    night = bool(cfg["ausgabe"].get("nachtkarte", True)) and not m.get("gelaende_nur")
    res = {"v": {"tag": tag, "nacht": None}, "W": m["W"], "name": cfg["name"], "raw": raw, "cfg": cfg,
           "orte": webpaket.places(m), "raster": int(cfg["ausgabe"].get("raster") or 0) > 0,
           "stem": f"{config.slug(cfg['name'])}_{cfg['seed']}", "verschoben": None, "lock": _KeinLock()}

    def nacht():
        svg = render_svg(m, nacht=True)
        if res["verschoben"] is not None:   # inzwischen verschobene Beschriftungen gelten auch hier
            svg = move_labels(svg, res["verschoben"], res["W"])
        ver = res["v"]["nacht"] = new_version(svg)
        return ver
    res["nacht"] = Spaeter(nacht) if night else None
    while len(RESULTS) >= 2:
        RESULTS.pop(next(iter(RESULTS)))
    RESULTS[rid] = res
    print("Stadtkarte im Browser: " + ", ".join(f"{k} {v:.1f} s" for k, v in zeiten.items()) + f", gesamt {gesamt:.1f} s")
    return {
        "id": rid,
        "W": m["W"],
        "labels": tag["labels"],
        "preview": "data:image/webp;base64," + base64.b64encode(png_to_webp(small, 88)).decode(),
        "hints": m["hints"],
        "gelaende_nur": bool(m.get("gelaende_nur")),
        "nacht": night,
        "stats": {"gebaeude": building_count(m), "baeume": len(m["trees"]), "sekunden": round(gesamt, 1),
                  "rendern": "browser", "zeiten": {k: round(v, 2) for k, v in zeiten.items()}},
    }


class _KeinLock:
    """ui/__main__ sperrt res["lock"]; ohne Threads gibt es nichts zu sperren."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def options():
    return dict(desk.options(), output_dir="den Download-Ordner des Browsers")


class Fehlt(Exception):
    """Die Karte ist nicht mehr im Speicher."""


def _result(q):
    res = RESULTS.get(q.get("id", ""))
    if res is None:
        raise Fehlt("Karte nicht mehr im Speicher - bitte neu erzeugen.")
    return res


def save_zip(res, ver):
    """„Alles speichern“: im Browser gibt es keinen Ordner ausgabe, daher SVG, PNG, PDF und HTML als ein ZIP."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for fmt in ("svg", "png", "pdf", "html"):
            z.writestr(f"{desk.stem(res, ver)}.{fmt}", desk.file_bytes(res, fmt, ver)[0])
    return buf.getvalue()


def _antwort(status, body, ctype="application/json; charset=utf-8", filename=None):
    if isinstance(body, (dict, list)):
        body = json.dumps(body, ensure_ascii=False).encode("utf-8")
    elif isinstance(body, str):
        body = body.encode("utf-8")
    return {"status": status, "ctype": ctype, "body": body, "filename": filename}


def handle(method, path, query="", body=""):
    """Eine Anfrage der Oberfläche wie beim lokalen Server. Liefert status, ctype, body (bytes) und filename (für
    Downloads, sonst None)."""
    q = {k: v[0] for k, v in parse_qs(query.lstrip("?")).items()}
    try:
        if method == "GET":
            if path == "/api/options":
                return _antwort(200, options())
            if path == "/api/example":
                return _antwort(200, desk.example(q.get("name", "hafenstadt")))
            if path == "/api/full":
                res = _result(q)
                return _antwort(200, png_to_webp(desk.view_png(desk.get_version(res, q.get("version"))), 88), "image/webp")
            if path == "/api/nacht":
                res = _result(q)
                return _antwort(200, png_to_webp(desk.get_version(res, "nacht")["klein"].result(), 88), "image/webp")
            if path == "/api/download":
                res = _result(q)
                fmt, ver = q.get("format", "png"), q.get("version", "tag")
                data, ctype = desk.file_bytes(res, fmt, ver)
                name = (f"{webpaket.folder_name(res['cfg'])}{'_nacht' if ver == 'nacht' else ''}.zip" if fmt == "web"
                        else f"{desk.stem(res, ver)}.{fmt}")
                return _antwort(200, data, ctype, name)
        elif method == "POST":
            if path == "/api/generate":
                return _antwort(200, build(json.loads(body)))
            if path == "/api/labels":
                data = json.loads(body)
                desk.set_labels(_result(data), data.get("beschriftung"))
                return _antwort(200, {"ok": True})
            if path == "/api/yaml":
                return _antwort(200, yaml.safe_dump(json.loads(body), allow_unicode=True, sort_keys=False),
                                "text/yaml; charset=utf-8")
            if path == "/api/parse":
                return _antwort(200, yaml.safe_load(body) or {})
            if path == "/api/save":
                data = json.loads(body)
                res, ver = _result(data), data.get("version") or "tag"
                return _antwort(200, save_zip(res, ver), "application/zip", f"{desk.stem(res, ver)}.zip")
        return _antwort(404, {"error": "Nicht gefunden"})
    except Fehlt as e:
        return _antwort(404, {"error": str(e)})
    except FileNotFoundError:
        return _antwort(404, {"error": "Nicht gefunden."})
    except (ValueError, yaml.YAMLError) as e:
        return _antwort(400, {"error": str(e)})
    except Exception as e:  # noqa: BLE001 - Fehler an die Oberfläche melden
        import traceback
        traceback.print_exc()
        return _antwort(500, {"error": f"{type(e).__name__}: {e}"})
