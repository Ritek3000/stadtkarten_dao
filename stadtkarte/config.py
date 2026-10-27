"""Einlesen und Vervollständigen der Stadtbeschreibung (YAML)."""
import copy
import math
import re

import yaml

from .styles import BIOME_ALIASES, BIOMES

# Himmelsrichtungen als Bildschirm-Vektoren (y zeigt nach unten)
_D = math.sqrt(0.5)
DIRS = {
    "nord": (0, -1), "nordost": (_D, -_D), "ost": (1, 0), "suedost": (_D, _D),
    "sued": (0, 1), "suedwest": (-_D, _D), "west": (-1, 0), "nordwest": (-_D, -_D),
    "mitte": (0, 0),
}
# Die Karte wird intern immer mit Küste im Norden erzeugt und am Ende gedreht.
ROTATION = {"nord": 0, "ost": 90, "sued": 180, "west": 270, "keine": 0}

# andere Schreibweisen für besondere Orte
PLACE_ALIASES = {"windmuehle": "muehle", "wasserrad": "wassermuehle", "halle": "rathaus", "dorfhalle": "rathaus",
                 "stadthalle": "rathaus", "schloss": "palast", "hof": "bauernhof", "bauernhaus": "bauernhof",
                 "gehoeft": "bauernhof", "dom": "kathedrale", "muenster": "kathedrale"}

DEFAULTS = {
    "name": "Namenlose Stadt",
    "seed": 1,
    "einwohner": 5000,
    "gelaende": {
        "biotop": "gemaessigt", "kueste": "nord", "fluss": True, "flussbreite": 60, "inseln": 2,
        "wald": ["west"], "felder": ["ost", "sued"],
    },
    "mauer": {"vorhanden": True, "tore": 4},
    "viertel": [],
    "orte": [],
    "beschriftung": {},   # von Hand verschobene Beschriftungen: Schlüssel -> [dx, dy] in % der Kartenbreite
    "ausgabe": {"bildgroesse": 2000, "formate": ["svg", "png"], "raster": 0, "legende": True,
                "dachdetails": True, "nacht": False},
}


def norm(word):
    """'Südost' -> 'suedost' usw."""
    w = str(word).strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("-", ""), (" ", "")):
        w = w.replace(a, b)
    return w


def _merge(base, extra):
    out = dict(base)
    for k, v in (extra or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load(path):
    with open(path, encoding="utf-8") as f:
        return from_dict(yaml.safe_load(f) or {})


def from_dict(raw):
    """Vervollständigt und prüft eine Stadtbeschreibung (z.B. aus der Oberfläche)."""
    cfg = _merge(copy.deepcopy(DEFAULTS), copy.deepcopy(raw))
    g = cfg["gelaende"]
    g["kueste"] = norm(g["kueste"]) if g["kueste"] else "keine"
    g["biotop"] = BIOME_ALIASES.get(norm(g["biotop"]), norm(g["biotop"]))
    if g["biotop"] not in BIOMES:
        raise ValueError(f"Unbekanntes Biotop: {g['biotop']} (möglich: {', '.join(BIOMES)})")
    if BIOMES[g["biotop"]]["mountain"] and g["kueste"] == "keine":
        g["kueste"] = "nord"   # im Gebirge gibt "kueste" die Bergseite an
    if g["kueste"] not in ROTATION:
        raise ValueError(f"Unbekannte Küstenlage: {g['kueste']}")
    try:
        cfg["einwohner"] = int(cfg["einwohner"])
    except (TypeError, ValueError):
        raise ValueError(f"einwohner muss eine Zahl sein, nicht '{cfg['einwohner']}'")
    if not 100 <= cfg["einwohner"] <= 250000:
        raise ValueError(f"einwohner: {cfg['einwohner']} - möglich sind 100 bis 250000")
    for key in ("wald", "felder"):
        vals = g.get(key) or []
        g[key] = [norm(v) for v in (vals if isinstance(vals, list) else [vals])]
        for v in g[key]:
            if v not in DIRS:
                raise ValueError(f"Unbekannte Richtung bei gelaende.{key}: {v}")
    for v in cfg["viertel"]:
        v["typ"] = norm(v.get("typ", "wohn"))
        if v.get("lage"):
            v["lage"] = norm(v["lage"])
            if v["lage"] not in DIRS:
                raise ValueError(f"Unbekannte Lage bei Viertel {v.get('name')}: {v['lage']}")
    if cfg.get("kennung") is not None:   # feste Kennung für das Web-Paket (Ordner- und Dateiname)
        cfg["kennung"] = str(cfg["kennung"]).strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", cfg["kennung"]):
            raise ValueError(f"Kennung '{cfg['kennung']}': nur Kleinbuchstaben a-z, Ziffern, '-' und '_' "
                             "(keine Umlaute oder Leerzeichen)")
    for o in cfg["orte"]:
        o["typ"] = norm(o.get("typ", "laden"))
        o["typ"] = PLACE_ALIASES.get(o["typ"], o["typ"])
    cfg["beschriftung"] = label_offsets(cfg["beschriftung"])
    return cfg


def slug(text):
    """Dateiname aus einem Stadtnamen: 'Tir'as'laan' -> 'tir_as_laan'."""
    s = str(text).lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_") or "karte"


def place_info(spec, district=None):
    """Angaben zu einem Ort für die Ortsliste des Web-Pakets (an der Beschriftung gespeichert). typ wie in der
    Stadtbeschreibung, auch wenn z.B. aus der Wassermühle mangels Fluss eine Windmühle wurde."""
    return {"name": spec["name"], "kuerzel": spec.get("kuerzel") or None, "typ": spec.get("typ_yaml", spec["typ"]),
            "viertel": district}


def label_offsets(moved):
    """Prüft die von Hand verschobenen Beschriftungen: {"viertel:Hafen": [dx, dy], ...} in % der Kartenbreite."""
    moved = moved or {}
    if not isinstance(moved, dict):
        raise ValueError('beschriftung muss eine Zuordnung sein, z.B.  "viertel:Hafen": [1.5, -0.8]')
    for key, val in moved.items():
        if not (isinstance(val, (list, tuple)) and len(val) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in val)):
            raise ValueError(f"beschriftung.{key}: erwartet [dx, dy] in Prozent der Kartenbreite")
    return moved


def to_canonical(direction, rot_deg):
    """Richtung auf der fertigen Karte -> Richtung im internen Koordinatensystem."""
    x, y = DIRS[direction]
    a = math.radians(-rot_deg)
    return (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a))
