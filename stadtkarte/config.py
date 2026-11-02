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
    "stadtform": "zufall",   # zufall (je Seed) | rund | oval | unregelmaessig | vieleck | gewachsen
    "gelaende": {
        "biotop": "gemaessigt", "kueste": "nord", "fluss": True, "flussbreite": 60, "inseln": 2,
        "wald": ["west"], "felder": ["ost", "sued"],
    },
    "mauer": {"vorhanden": True, "tore": 4},
    "viertel": [],
    "orte": [],
    "beschriftung": {},   # von Hand verschobene Beschriftungen: Schlüssel -> [dx, dy] in % der Kartenbreite
    "ausgabe": {"bildgroesse": 2000, "formate": ["svg", "png"], "raster": 0, "legende": True,
                "dachdetails": True, "nacht": False,
                "nachtkarte": True},   # nacht: die einzelne Karte als Nacht zeichnen (Kommandozeile); nachtkarte: die
                                       # Werkstatt berechnet zusätzlich zur Tagkarte die Nachtkarte zum Umschalten
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


MIN_EINWOHNER, MAX_EINWOHNER = 100, 250000


def number(sec, key, name, typ, lo, hi, default=None):
    """Zahlenfeld prüfen und umwandeln; leer (z.B. geleertes Feld in der Oberfläche) heißt Standardwert."""
    val = sec.get(key)
    if val is None or (isinstance(val, str) and not val.strip()):
        if default is None:
            raise ValueError(f"{name} fehlt (erwartet eine Zahl von {lo} bis {hi})")
        val = default
    try:
        if isinstance(val, bool):
            raise ValueError
        num = float(str(val).replace(",", ".")) if isinstance(val, str) else float(val)
        if typ is int and num != int(num):
            raise ValueError
        num = typ(num)
    except (TypeError, ValueError):
        raise ValueError(f"{name} muss eine {'ganze ' if typ is int else ''}Zahl sein, nicht '{val}'")
    if not lo <= num <= hi:
        raise ValueError(f"{name}: {num} - möglich sind {lo} bis {hi}")
    sec[key] = num
    return num


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
    if (BIOMES[g["biotop"]]["mountain"] or BIOMES[g["biotop"]]["plateau"]) and g["kueste"] == "keine":
        g["kueste"] = "nord"   # im Gebirge die Bergseite, beim Hochplateau die Seite der Kante
    # Hochplateau: Stadt oben auf dem Plateau oder unten am Fuß, direkt an der Kante oder mit Abstand
    if BIOMES[g["biotop"]]["plateau"]:
        pl = {"auf": "oben", "aufdemplateau": "oben", "drauf": "oben", "fuss": "unten", "amfuss": "unten",
              "unterhalb": "unten", "darunter": "unten"}
        g["plateau"] = pl.get(norm(g.get("plateau") or "oben"), norm(g.get("plateau") or "oben"))
        if g["plateau"] not in ("oben", "unten"):
            raise ValueError(f"gelaende.plateau: {g['plateau']} - möglich sind oben (auf dem Plateau) und unten (am Fuß)")
        ka = {"an": "direkt", "anderkante": "direkt", "kante": "direkt", "weg": "abstand", "entfernt": "abstand",
              "mitabstand": "abstand"}
        g["kante"] = ka.get(norm(g.get("kante") or "direkt"), norm(g.get("kante") or "direkt"))
        if g["kante"] not in ("direkt", "abstand"):
            raise ValueError(f"gelaende.kante: {g['kante']} - möglich sind direkt (an der Kante) und abstand")
    if g["kueste"] not in ROTATION:
        raise ValueError(f"Unbekannte Küstenlage: {g['kueste']}")
    number(cfg, "einwohner", "einwohner", int, MIN_EINWOHNER, MAX_EINWOHNER)
    if cfg.get("seed") is None or (isinstance(cfg["seed"], str) and not cfg["seed"].strip()):
        raise ValueError("seed fehlt: bitte eine ganze Zahl eintragen (oder den Würfel nutzen)")
    number(cfg, "seed", "seed", int, -2 ** 63, 2 ** 63 - 1)
    number(cfg["mauer"], "tore", "mauer.tore", int, 1, 12, DEFAULTS["mauer"]["tore"])
    number(g, "flussbreite", "gelaende.flussbreite", float, 5, 400, DEFAULTS["gelaende"]["flussbreite"])
    number(g, "inseln", "gelaende.inseln", int, 0, 20, DEFAULTS["gelaende"]["inseln"])
    aus_ = cfg["ausgabe"]
    number(aus_, "bildgroesse", "ausgabe.bildgroesse", int, 300, 8000, DEFAULTS["ausgabe"]["bildgroesse"])
    number(aus_, "raster", "ausgabe.raster", int, 0, 2000, 0)
    form = norm(cfg["stadtform"] or "zufall")
    form = {"zufaellig": "zufall", "auto": "zufall", "kreis": "rund", "elliptisch": "oval", "langgestreckt": "oval",
            "lang": "oval", "unregelmassig": "unregelmaessig", "eckig": "vieleck", "polygon": "vieleck",
            "ausgebuchtet": "gewachsen", "custom": "eigene", "gezeichnet": "eigene", "selbst": "eigene",
            "eigen": "eigene"}.get(form, form)
    if form not in ("zufall", "rund", "oval", "unregelmaessig", "vieleck", "gewachsen", "eigene"):
        raise ValueError(f"Unbekannte Stadtform: {cfg['stadtform']} "
                         "(möglich: zufall, rund, oval, unregelmaessig, vieleck, gewachsen, eigene)")
    cfg["stadtform"] = form
    if form == "eigene":   # selbst gezeichnete Mauer: Punkte in % der fertigen Karte, je Turm oder Tor
        if BIOMES[g["biotop"]]["mountain"]:
            raise ValueError("Die eigene Stadtform gibt es (noch) nicht im Gebirge.")
        pts = []
        for i, p in enumerate(cfg["mauer"].get("punkte") or []):
            try:
                x, y = float(p[0]), float(p[1])
                kind = norm(p[2]) if len(p) > 2 else "turm"
            except (TypeError, ValueError, IndexError):
                raise ValueError(f"mauer.punkte[{i}]: erwartet [x, y, turm|tor] in Prozent der Karte")
            if kind not in ("turm", "tor") or not (0 <= x <= 100 and 0 <= y <= 100):
                raise ValueError(f"mauer.punkte[{i}]: x und y von 0 bis 100, Art turm oder tor")
            pts.append([round(x, 3), round(y, 3), kind])
        cfg["mauer"]["punkte"] = pts
        cfg["ausgabe"].pop("ausschnitt", None)   # gezeichnet wird auf der ganzen Karte
    beb = norm(cfg.get("bebauung") or "dicht")   # lockere Bebauung: gleiche Einwohner auf mehr Fläche
    beb = {"normal": "dicht", "eng": "dicht", "aufgelockert": "locker", "weit": "weitlaeufig", "sehrlocker": "weitlaeufig",
           "laendlich": "weitlaeufig"}.get(beb, beb)
    if beb not in ("dicht", "locker", "weitlaeufig"):
        raise ValueError(f"Unbekannte Bebauung: {cfg.get('bebauung')} (möglich: dicht, locker, weitlaeufig)")
    if beb == "dicht":
        cfg.pop("bebauung", None)
    else:
        cfg["bebauung"] = beb
    stil = norm(cfg["ausgabe"].get("stil") or "pergament")   # Zeichenstil der fertigen Karte (Standard: Pergament)
    stil = {"normal": "standard", "modern": "standard", "papier": "pergament", "alt": "pergament",
            "historisch": "pergament"}.get(stil, stil)
    if stil not in ("standard", "pergament"):
        raise ValueError(f"Unbekannter Stil: {cfg['ausgabe'].get('stil')} (möglich: standard, pergament)")
    cfg["ausgabe"]["stil"] = stil
    aus = norm(cfg["ausgabe"].get("ausschnitt") or "weit")   # wie viel der Karte die Stadt einnimmt
    aus = {"fuellen": "fuellend", "voll": "fuellend", "ganz": "fuellend", "auto": "fuellend", "mittel": "normal",
           "eng": "nah", "gross": "nah"}.get(aus, aus)
    if aus not in ("weit", "normal", "nah", "fuellend"):
        raise ValueError(f"Unbekannter Ausschnitt: {cfg['ausgabe'].get('ausschnitt')} "
                         "(möglich: weit, normal, nah, fuellend)")
    if aus == "weit":
        cfg["ausgabe"].pop("ausschnitt", None)
    else:
        cfg["ausgabe"]["ausschnitt"] = aus
    # Staub: {Richtung | "mitte" | "ueberall": wenig | mittel | finsternis}; auch als Liste von Richtungen (= mittel)
    st = g.get("staub") or {}
    if isinstance(st, (list, tuple)):
        st = {d: "mittel" for d in st}
    if not isinstance(st, dict):
        raise ValueError("gelaende.staub: erwartet z.B. {a1: finsternis, c3: wenig} (Raster 5x5) oder {nordwest: mittel}")
    clean_st = {}
    for k, v in st.items():
        k = norm(k)
        k = {"alles": "ueberall", "ganzekarte": "ueberall", "stadt": "mitte", "zentrum": "mitte"}.get(k, k)
        v = norm(v or "")
        v = {"leicht": "wenig", "schleier": "wenig", "dicht": "mittel", "schwarz": "finsternis", "dunkel": "finsternis",
             "aus": "", "kein": "", "keiner": ""}.get(v, v)
        if not v:
            continue
        if k not in DIRS and k not in ("mitte", "ueberall") and not re.fullmatch(r"[a-e][1-5]", k):
            raise ValueError(f"gelaende.staub: unbekannte Richtung {k}")
        if v not in ("wenig", "mittel", "finsternis"):
            raise ValueError(f"gelaende.staub.{k}: {v} - möglich sind wenig, mittel, finsternis")
        clean_st[k] = v
    if clean_st:
        g["staub"] = clean_st
    else:
        g.pop("staub", None)
    for key in ("wald", "felder"):
        vals = g.get(key) or []
        g[key] = [norm(v) for v in (vals if isinstance(vals, list) else [vals])]
        for v in g[key]:
            if v not in DIRS:
                raise ValueError(f"Unbekannte Richtung bei gelaende.{key}: {v}")
    for v in cfg["viertel"]:
        v["typ"] = norm(v.get("typ", "wohn"))
        if v.get("lage") and norm(v["lage"]) in ("ausserhalb", "aussen", "draussen", "vorderstadt", "vordermauer"):
            v["ausserhalb"] = True   # Armenviertel vor der Stadtmauer
            del v["lage"]
        if v["typ"] == "hafen":   # Größe des Hafenviertels: klein | mittel | gross (Standard)
            gr = norm(v.get("groesse") or "gross")
            gr = {"gross": "gross", "groß": "gross", "klein": "klein", "mittel": "mittel", "normal": "mittel"}.get(gr, gr)
            if gr not in ("klein", "mittel", "gross"):
                raise ValueError(f"Viertel {v.get('name')}: groesse {v.get('groesse')} - möglich sind klein, mittel, gross")
            if gr == "gross":
                v.pop("groesse", None)
            else:
                v["groesse"] = gr
        else:
            v.pop("groesse", None)
        if v.get("ausserhalb"):
            v["ausserhalb"] = True
        else:
            v.pop("ausserhalb", None)
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
        if o.get("lage"):   # wie bei Vierteln: "Außerhalb", "vor der Stadt" ... einheitlich schreiben
            o["lage"] = norm(o["lage"])
    cfg["orte"] = numbered_places(cfg["orte"])
    cfg["beschriftung"] = label_offsets(cfg["beschriftung"])
    return cfg


MAX_ANZAHL = 50
SERIES_PREFIX = {"schmiede": "SM"}   # feste Buchstaben für Reihen ohne Kürzel (Schenke S, Schmiede SM)


def numbered_places(orte):
    """Orte mit anzahl werden vervielfacht und fortlaufend durchnummeriert: 5 Schenken -> S1 bis S5. Das Kürzel gibt
    den Buchstaben vor (sonst SERIES_PREFIX bzw. der erste Buchstabe des Namens); weitere Einträge mit demselben Buchstaben zählen
    weiter (z.B. 3 Schenken in einem anderen Viertel -> S6 bis S8). Einzeln vergebene Kürzel werden übersprungen."""
    if not any("anzahl" in o for o in orte):
        return orte
    taken = {str(o["kuerzel"]).strip() for o in orte if o.get("kuerzel") and "anzahl" not in o}
    counter, out = {}, []
    for o in orte:
        if "anzahl" not in o:
            out.append(o)
            continue
        n = o.pop("anzahl")
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_ANZAHL:
            raise ValueError(f"Ort {o.get('name')}: anzahl muss eine ganze Zahl von 1 bis {MAX_ANZAHL} sein")
        name = str(o.get("name") or o["typ"].capitalize())
        prefix = re.sub(r"\d+$", "", str(o.get("kuerzel") or "").strip()) or SERIES_PREFIX.get(o["typ"]) or name.strip()[:1].upper()
        for _ in range(n):
            k = counter.get(prefix, 0) + 1
            while f"{prefix}{k}" in taken:
                k += 1
            counter[prefix] = k
            out.append({**o, "name": name, "kuerzel": f"{prefix}{k}"})
    return out


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
