"""Einlesen und Vervollständigen der Stadtbeschreibung (YAML)."""
import copy
import math

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
    for o in cfg["orte"]:
        o["typ"] = norm(o.get("typ", "laden"))
    return cfg


def to_canonical(direction, rot_deg):
    """Richtung auf der fertigen Karte -> Richtung im internen Koordinatensystem."""
    x, y = DIRS[direction]
    a = math.radians(-rot_deg)
    return (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a))
