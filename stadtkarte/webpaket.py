"""Web-Paket: die Karte in Einzelteilen für eine eigene Webseite.

  karte.webp        Karte ohne Beschriftung und ohne Raster, genau W x W Pixel
  beschriftung.svg  die Beschriftungsebene (viewBox 0 0 W W) ohne eingebettete Schrift; die Webseite stellt
                    EB Garamond unter diesem Namen selbst bereit
  orte.json         Orte und Viertel mit Lage im Bild und dem data-key ihrer Beschriftung (für Klicks)
  stadt.yaml        die Stadtbeschreibung mit Seed, Kennung und Beschriftungs-Verschiebungen
"""
import io
import json
import zipfile
from collections import Counter

import yaml
from PIL import Image

from . import __version__
from .config import slug
from .render import rot_xy, split_labels, strip_grid

FORMAT = 1


def kennung(cfg):
    """Feste Kennung der Stadt: Feld 'kennung' der Stadtbeschreibung, sonst aus dem Namen gebildet."""
    return cfg.get("kennung") or slug(cfg["name"])


def base_svg(svg):
    """Karte ohne Beschriftung und ohne Raster (Vorlage für karte.webp)."""
    return strip_grid(split_labels(svg)[0])


def labels_svg(svg, W):
    """Eigenständige SVG-Datei mit der Beschriftungsebene, unverändert aus der Karte übernommen."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{W}" viewBox="0 0 {W} {W}">'
            f'{split_labels(svg)[1]}</svg>\n')


def places(m):
    """Inhalt von orte.json. Braucht m["label_keys"] aus render_svg."""
    cfg = m["cfg"]
    orte, viertel = [], []
    for key, lb in m["label_keys"]:
        x, y = rot_xy(m, lb["x"], lb["y"])
        if "ort" in lb:
            o = lb["ort"]
            orte.append({"key": key, "name": o["name"], "kuerzel": o["kuerzel"], "typ": o["typ"],
                         "art": ("festung" if lb["kind"] == "festung"   # Leuchtturm: von selbst gesetzt, nicht beschrieben
                                 else "leuchtturm" if o["typ"] == "leuchtturm" else "ort"), "viertel": o["viertel"],
                         "x": round(x, 1), "y": round(y, 1)})
        elif "viertel" in lb:
            viertel.append({"key": key, "name": lb["viertel"]["name"], "typ": lb["viertel"]["typ"],
                            "x": round(x, 1), "y": round(y, 1)})
    missing = Counter(o["name"] for o in cfg["orte"]) - Counter(o["name"] for o in orte)
    nicht = []
    for o in cfg["orte"]:   # in der Reihenfolge der Stadtbeschreibung
        if missing[o["name"]] > 0:
            missing[o["name"]] -= 1
            nicht.append(o["name"])
    return {"format": FORMAT, "werkstatt": __version__, "kennung": kennung(cfg), "name": cfg["name"],
            "seed": cfg["seed"], "einwohner": cfg["einwohner"], "biotop": cfg["gelaende"]["biotop"],
            "nacht": bool(cfg["ausgabe"].get("nacht")), "breite": m["W"], "hoehe": m["W"],
            "orte": orte, "viertel": viertel, "nicht_platziert": nicht}


def description(raw, cfg):
    """stadt.yaml: die Stadtbeschreibung, wie sie eingegeben wurde, ergänzt um Seed und Kennung (damit die Stadt
    beim erneuten Veröffentlichen dieselbe bleibt, auch wenn sie umbenannt wird)."""
    out = {}
    for k, v in raw.items():
        out[k] = v
        if k == "name":
            out["kennung"] = kennung(cfg)
    out.setdefault("kennung", kennung(cfg))
    out["seed"] = cfg["seed"]
    aus = dict(out.get("ausgabe") or {})
    if cfg["ausgabe"].get("nacht"):
        aus["nacht"] = True
    elif "nacht" in aus:   # die Werkstatt liefert Tag- und Nachtkarte aus einer Beschreibung: das Paket nennt seine Version
        aus["nacht"] = False
    if aus:
        out["ausgabe"] = aus
    return yaml.safe_dump(out, allow_unicode=True, sort_keys=False)


def webp(png, quality=88):
    buf = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(buf, "WEBP", quality=quality)
    return buf.getvalue()


def files(svg, orte, raw, cfg, base_png):
    """Die vier Dateien des Pakets: {Dateiname: Bytes}. base_png: gerenderte base_svg(svg)."""
    W = orte["breite"]
    return {"karte.webp": webp(base_png),
            "beschriftung.svg": labels_svg(svg, W).encode("utf-8"),
            "orte.json": (json.dumps(orte, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            "stadt.yaml": description(raw, cfg).encode("utf-8")}


def folder_name(cfg):
    return f"{kennung(cfg)}_web"


def write_folder(target, content):
    target.mkdir(parents=True, exist_ok=True)
    for name, data in content.items():
        (target / name).write_bytes(data)


def zip_bytes(folder, content):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in content.items():
            z.writestr(f"{folder}/{name}", data)
    return buf.getvalue()
