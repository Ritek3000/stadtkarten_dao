"""Karten-Vergleichstests: feste Fingerabdrücke fertiger Karten.

Ein Umbau des Programms darf die Karten nicht verändern: derselbe Seed muss dieselbe Stadt liefern. Für eine Reihe fester
Beschreibungen (die Beispiele, dazu Sonderfälle wie eigene Mauer, Binnenland, Stadtformen) wird die Karte erzeugt und
gezeichnet und mit den Fingerabdrücken in tests/golden/karten.json verglichen. Je Karte steht dort getrennt:

  hinweise  die Hinweise des Generators ("Hinweis: Kein Platz für ...") im Wortlaut
  zahlen    Gebäude, Bäume, Straßen usw. (gut lesbar: zeigt auf einen Blick, was sich geändert hat)
  modell    Fingerabdruck des ganzen Kartenmodells nach dem Generator, Koordinaten auf 0,01 px gerundet
  karten    je Ansicht (tag, nacht): Fingerabdruck der SVG-Datei ohne eingebettete Bilder und die der Bilder einzeln

So zeigt eine Abweichung, in welcher Stufe sie entstand: ändert sich schon das Modell, liegt es am Generator, bleibt es
gleich und nur das SVG ändert sich, am Zeichnen.

Wie streng verglichen wird, hängt von der Umgebung ab, in der die Fingerabdrücke entstanden sind (Eintrag "umgebung"):
  - Betriebssystem, Shapely und GEOS gleich: alles (Hinweise, Zahlen, Modell, SVG). Eine andere GEOS-Version rechnet
    einzelne Eckpunkte anders (gleiche Häuser und Straßen, aber ein paar Punkte mehr oder weniger), Windows und Linux runden
    Sinus und Kosinus unterschiedlich.
  - zusätzlich NumPy und Pillow gleich: auch die Texturbilder (andere Versionen ändern einzelne Bytes).
  - sonst nur die Zahlen, mit 2 % Toleranz: die Karte entsteht, hat etwa gleich viele Häuser, Bäume und Straßen.
Auf GitHub laufen die Tests mit den Versionen aus requirements-lock.txt, dort wird alles verglichen.

Aufruf (im Projektordner):
  python -m tests.golden                    vergleicht alle Karten mit tests/golden/karten.json
  python -m tests.golden hafen              vergleicht nur die Karten, deren Name "hafen" enthält
  python -m tests.golden --update           schreibt die Fingerabdrücke neu (nach einer gewollten Änderung der Karten)
  python -m tests.golden --update hafen     schreibt nur die Karten mit "hafen" im Namen neu
"""
import argparse
import concurrent.futures
import concurrent.futures.process
import contextlib
import copy
import hashlib
import io
import json
import multiprocessing
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import PIL  # noqa: E402
import shapely  # noqa: E402
import yaml  # noqa: E402
from shapely.geometry.base import BaseGeometry  # noqa: E402

from stadtkarte import config  # noqa: E402
from stadtkarte.generator import building_count, generate, hint_lines  # noqa: E402
from stadtkarte.render import render_svg  # noqa: E402
from stadtkarte.styles import STILE  # noqa: E402

DATEI = ROOT / "tests" / "golden" / "karten.json"
GROESSE = 500                    # klein genug für schnelle Läufe, groß genug für alle Zeichenwege
TOLERANZ = 0.02                  # erlaubte Abweichung der Zahlen auf einem anderen Betriebssystem
BILD = re.compile(r"data:image/webp;base64,[A-Za-z0-9+/=]+")
SCHRIFT = re.compile(r"data:font/ttf;base64,[A-Za-z0-9+/=]+")


# ---------------------------------------------------------------------------------------------------------- Fälle
def beispiel(name, **ausgabe):
    """Eines der mitgelieferten Beispiele in kleiner Bildgröße, ausgabe überschreibt Angaben der Datei."""
    raw = yaml.safe_load((ROOT / "beispiele" / f"{name}.yaml").read_text(encoding="utf-8"))
    raw["ausgabe"] = {**(raw.get("ausgabe") or {}), "bildgroesse": GROESSE, **ausgabe}
    return raw


def klein(**angaben):
    """Kleine Küstenstadt mit Fluss und wenigen Orten als Grundlage für Sonderfälle; angaben überschreiben Abschnitte."""
    raw = {"name": "Kleinstadt", "seed": 5, "einwohner": 1500,
           "gelaende": {"biotop": "gemaessigt", "kueste": "nord", "fluss": True, "flussbreite": 40, "inseln": 2,
                        "wald": ["west"], "felder": ["ost", "sued"]},
           "mauer": {"vorhanden": True, "tore": 4},
           "viertel": [{"name": "Hafen", "typ": "hafen", "groesse": "klein"}, {"name": "Markt", "typ": "markt"},
                       {"name": "Handwerk", "typ": "handwerk", "lage": "west"}],
           "orte": [{"name": "Tempel", "typ": "tempel"}, {"name": "Schenke", "typ": "gasthaus", "anzahl": 2}],
           "ausgabe": {"bildgroesse": GROESSE}}
    for abschnitt, wert in angaben.items():
        raw[abschnitt] = {**raw[abschnitt], **wert} if isinstance(wert, dict) and isinstance(raw.get(abschnitt), dict) else wert
    return raw


def _abstuerze():
    from tests.test_generator import ABSTUERZE   # Karten, die früher beim Zeichnen abstürzten
    return ABSTUERZE


def faelle():
    """Name -> (Beschreibung, Ansichten). Die Beschreibungen sind fest; ändern sich Beispiele oder Fälle, ändern sich
    die Fingerabdrücke (dann: python -m tests.golden --update)."""
    eigene = [[30, 52, "tor"], [42, 40, "turm"], [60, 40, "turm"], [72, 52, "tor"], [70, 72, "turm"], [50, 80, "turm"],
              [32, 70, "turm"]]
    im_osten = beispiel("hafenstadt")
    im_osten["gelaende"] = {**im_osten["gelaende"], "kueste": "ost"}
    fuenf = beispiel("hafenstadt")
    fuenf["gelaende"] = {**fuenf["gelaende"], "bruecken": 5}
    fuenf_plateau = beispiel("plateaustadt", ausschnitt="nah")
    fuenf_plateau["gelaende"] = {**fuenf_plateau["gelaende"], "bruecken": 5}
    f = {
        "hafenstadt": (beispiel("hafenstadt"), ("tag", "nacht")),            # Küste, Fluss, Hafen, Festung, Werft, Schiffe
        "hafenstadt_standard": (beispiel("hafenstadt", stil="standard"), ("tag",)),   # Zeichenstil ohne Pergament
        "hafenstadt_nah": (beispiel("hafenstadt", ausschnitt="nah"), ("tag",)),       # vergrößerter Ausschnitt (Zuschnitt)
        "hauptstadt_fuellend": (beispiel("hauptstadt", ausschnitt="fuellend"), ("tag",)),   # Großstadt, Küste im Süden
        "zwergenstadt": (beispiel("zwergenstadt"), ("tag", "nacht")),        # Gebirge, Klamm, Terrassen, Minen
        "oasenstadt_normal": (beispiel("oasenstadt", ausschnitt="normal"), ("tag",)),   # Wüste, Oasen, Dünen
        "plateaustadt_nah": (beispiel("plateaustadt", ausschnitt="nah"), ("tag",)),     # Hochplateau, Wasserfall, Aufzug
        "nordhafen": (beispiel("nordhafen"), ("tag", "nacht")),              # Nordland, Eisschollen
        "sumpfdorf": (beispiel("sumpfdorf"), ("tag",)),                      # Sumpf, Pfahlbauten
        "heidedorf": (beispiel("heidedorf"), ("tag",)),                      # Heide: Birken, Wacholder, Findlinge
        "herbststadt": (beispiel("herbststadt"), ("tag",)),                  # Herbstwald, Stoppelfelder
        "auenstadt": (beispiel("auenstadt"), ("tag", "nacht")),              # Auwald: Altarme, Waldstreifen am Fluss
        "mittelmeerhafen": (beispiel("mittelmeerhafen"), ("tag", "nacht")),  # Zypressen, Olivenhaine, Weinberge
        "dschungelstadt": (beispiel("dschungelstadt"), ("tag",)),            # Regenwald, Baumfarne, Pfahlhäuser
        "moordorf": (beispiel("moordorf"), ("tag", "nacht")),                # Hochmoor: Moorseen, Wollgras, Torfstiche
        "kueste_ost": (im_osten, ("tag",)),                                  # Drehung der Karte um 90 Grad
        "bruecken_hafen": (fuenf, ("tag", "nacht")),                         # fünf Brücken, nur flussaufwärts vom Hafen
        "bruecken_plateau": (fuenf_plateau, ("tag",)),                       # fünf Brücken auf beiden Seiten der Mitte
        "binnenland": (klein(seed=21, einwohner=2500, stadtform="gewachsen",
                             gelaende={"biotop": "steppe", "kueste": "keine", "inseln": 0},
                             viertel=[{"name": "Markt", "typ": "markt"},
                                      {"name": "Hütten", "typ": "armen", "ausserhalb": True}],
                             orte=[{"name": "Wehrburg", "typ": "festung", "lage": "land", "kuerzel": "W"},
                                   {"name": "Friedhof", "typ": "friedhof", "lage": "ausserhalb"},
                                   {"name": "Windmühle", "typ": "muehle"}, {"name": "Hof", "typ": "bauernhof"},
                                   {"name": "Wassermühle", "typ": "wassermuehle"}, {"name": "Dom", "typ": "kathedrale"},
                                   {"name": "Schenke", "typ": "gasthaus", "anzahl": 3}]), ("tag",)),
        # Marktplatz, Badehaus, Magierturm, Arena, Färberei, Hafenkran, Kloster, Richtstätte (neu in 1.39)
        "neue_orte": (klein(seed=5, einwohner=9000, orte=[
            {"name": "Marktplatz", "typ": "marktplatz", "kuerzel": "M"}, {"name": "Badehaus", "typ": "badehaus", "kuerzel": "B"},
            {"name": "Turm des Magiers", "typ": "magierturm", "kuerzel": "T"}, {"name": "Arena", "typ": "arena", "kuerzel": "A"},
            {"name": "Färberei", "typ": "faerberei", "kuerzel": "F"}, {"name": "Hafenkran", "typ": "hafenkran", "kuerzel": "K"},
            {"name": "Kloster", "typ": "kloster", "kuerzel": "KL"}, {"name": "Galgenhügel", "typ": "richtstaette", "kuerzel": "G"}]),
            ("tag", "nacht")),
        # Ruinenviertel (neu in 1.41): Mauerreste und eingestürzte Dächer, nachts ohne Licht in den Ruinen
        "ruinenstadt": (beispiel("ruinenstadt"), ("tag", "nacht")),
        "ruinen_grossstadt": (klein(seed=12, einwohner=30000, orte=[],     # Häuserzeilen mit einzelnen Ruinen
                                    viertel=[{"name": "Altstadt", "typ": "wohn", "lage": "mitte"},
                                             {"name": "Ruinenring", "typ": "ruinen", "ruinenanteil": 50, "lage": "west"},
                                             {"name": "Handwerk", "typ": "handwerk", "lage": "ost"}]), ("tag",)),
        "eigene_mauer": (klein(stadtform="eigene", mauer={"punkte": eigene}), ("tag",)),   # selbst gezeichnete Mauer
        "eigene_gelaende": (klein(stadtform="eigene"), ("tag",)),            # nur Gelände, die Mauer fehlt noch
        # Raster, keine Legende, flache Dächer ohne Details, von Hand verschobene Beschriftung
        "ohne_details": (klein(ausgabe={"raster": 100, "legende": False, "dachdetails": False},
                               beschriftung={"viertel:Markt": [1.5, -0.8], "titel": [-2, 1]}), ("tag",)),
        "staub_weitlaeufig": (klein(bebauung="weitlaeufig",
                                    gelaende={"staub": {"a1": "finsternis", "c3": "mittel", "mitte": "wenig",
                                                         "ueberall": "wenig"}}), ("tag",)),
    }
    for form in ("oval", "vieleck", "gewachsen", "unregelmaessig"):
        f[f"form_{form}"] = (klein(seed=9, stadtform=form), ("tag",))
    for stil in STILE:   # die Zeichenstile über Standard und Pergament hinaus (Bleistift und Konturen mit Schrift in Tinte auch nachts)
        if stil not in ("standard", "pergament"):
            f[f"stil_{stil}"] = (klein(ausgabe={"stil": stil}),
                                 ("tag", "nacht") if stil in ("bleistift", "konturen") else ("tag",))
    # Konturen im Gebirge: Höhenlinien statt Schummerung
    f["stil_konturen_gebirge"] = (beispiel("zwergenstadt", stil="konturen"), ("tag",))
    for name, raw in _abstuerze().items():
        f[f"abstuerz_{name}"] = (copy.deepcopy(raw), ("tag",))
    return f


# ------------------------------------------------------------------------------------------------ Fingerabdrücke
def _ruhig(wert):
    """Rundet eine Zahl auf 0,01 und macht aus -0 eine 0 (sonst kippt ein Rundungsrest den Fingerabdruck)."""
    return f"{round(float(wert), 2) + 0.0:.2f}"


def _wkt(geom):
    return re.sub(r"(?<![\d.])-0(?![\d.])", "0", shapely.to_wkt(geom, rounding_precision=2, trim=True))


def _einspeisen(h, obj, tiefe=0):
    """Schreibt ein Stück des Kartenmodells in den Hash: Geometrien und Zahlen auf 0,01 gerundet, Wörterbücher nach
    Schlüsseln sortiert (die Reihenfolge der Schlüssel ändert die Karte nicht), Listen in ihrer Reihenfolge (sie bestimmt
    die Zeichenreihenfolge)."""
    if tiefe > 40:
        raise RecursionError("Kartenmodell zu tief verschachtelt")
    if isinstance(obj, BaseGeometry):
        h.update(_wkt(obj).encode())
    elif isinstance(obj, dict):
        for k in sorted(obj, key=str):
            if str(k).startswith("_") or callable(obj[k]):
                continue
            h.update(b"{" + str(k).encode() + b"=")
            _einspeisen(h, obj[k], tiefe + 1)
        h.update(b"}")
    elif isinstance(obj, (list, tuple)):
        h.update(b"[%d:" % len(obj))
        for v in obj:
            _einspeisen(h, v, tiefe + 1)
        h.update(b"]")
    elif isinstance(obj, (set, frozenset)):
        _einspeisen(h, sorted(obj, key=repr), tiefe + 1)
    elif isinstance(obj, np.ndarray):
        _einspeisen(h, obj.tolist(), tiefe + 1)
    elif isinstance(obj, (bool, np.bool_)):
        h.update(b"b1" if obj else b"b0")
    elif isinstance(obj, (float, np.floating)):
        h.update(b"f" + _ruhig(obj).encode())
    elif isinstance(obj, (int, np.integer)):
        h.update(b"i%d" % int(obj))
    elif obj is None or isinstance(obj, str):
        h.update(repr(obj).encode())
    else:   # unbekannter Typ: nur sein Name, damit ein neuer Typ im Modell auffällt
        h.update(b"?" + type(obj).__name__.encode())
    h.update(b";")


def fingerabdruck_modell(m):
    h = hashlib.sha256()
    _einspeisen(h, {k: v for k, v in m.items() if k not in ("cfg", "biome", "hints")})   # Hinweise: eigener Vergleich
    return h.hexdigest()[:20]


def zahlen(m):
    return {"gebaeude": building_count(m), "baeume": len(m["trees"]), "landstrassen": len(m["ext_roads"]),
            "gassen": len(m["internal_roads"]), "bruecken": len(m["bridges"]), "viertel": len(m["districts"]),
            "beschriftungen": len(m["labels"]), "tore": len(m["gates"]), "tuerme": len(m["towers"]),
            "schiffe": len(m["ships"]), "felder": len(m["fields"]), "stadtflaeche": round(m["shape"].area)}


def fingerabdruck_karte(svg):
    """SVG ohne eingebettete Bilder und Schrift (die Vektoren), dazu jedes Bild einzeln."""
    vektoren = SCHRIFT.sub("SCHRIFT", BILD.sub("BILD", svg))
    return {"svg": hashlib.sha256(vektoren.encode()).hexdigest()[:20],
            "bilder": [hashlib.sha256(b.encode()).hexdigest()[:20] for b in BILD.findall(svg)]}


def berechne(name):
    """Erzeugt und zeichnet eine Karte (läuft in einem eigenen Prozess) und liefert ihre Fingerabdrücke. Hinweise gehören
    ins Kartenmodell (m["hints"]); schreibt Erzeugen oder Zeichnen etwas auf die Konsole, scheitert der Fall."""
    raw, ansichten = faelle()[name]
    with contextlib.redirect_stdout(io.StringIO()) as ausgabe:
        m = generate(config.from_dict(copy.deepcopy(raw)))
        out = {"hinweise": hint_lines(m), "zahlen": zahlen(m), "modell": fingerabdruck_modell(m), "karten": {}}
        for ansicht in ansichten:
            out["karten"][ansicht] = fingerabdruck_karte(render_svg(m, nacht=ansicht == "nacht"))
    if ausgabe.getvalue().strip():
        raise AssertionError(f"Karte '{name}': Erzeugen oder Zeichnen schreibt auf die Konsole (Hinweise gehören nach "
                             f"m['hints']): {ausgabe.getvalue().strip()[:300]!r}")
    return out


def berechne_alle(namen=None):
    """Alle (oder die genannten) Karten, auf mehrere Prozesse verteilt: {Name: Fingerabdrücke}."""
    namen = list(namen or faelle())
    arbeiter = max(1, min(4, os.cpu_count() or 1, len(namen)))
    try:
        with concurrent.futures.ProcessPoolExecutor(arbeiter, mp_context=multiprocessing.get_context("spawn")) as pool:
            return dict(zip(namen, pool.map(berechne, namen)))
    except (OSError, concurrent.futures.process.BrokenProcessPool):   # keine Prozesse möglich: nacheinander
        return {n: berechne(n) for n in namen}


# -------------------------------------------------------------------------------------------------------- Vergleich
def umgebung():
    return {"plattform": sys.platform, "numpy": np.__version__, "shapely": shapely.__version__,
            "geos": shapely.geos_version_string, "pillow": PIL.__version__}


def laden():
    return json.loads(DATEI.read_text(encoding="utf-8"))


def speichern(daten):
    DATEI.parent.mkdir(parents=True, exist_ok=True)
    DATEI.write_text(json.dumps(daten, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _ungefaehr(a, b):
    return abs(a - b) <= max(2, TOLERANZ * max(abs(a), abs(b)))


def unterschiede(erwartet, aktuell, stand=None, jetzt=None):
    """Liste der Abweichungen einer Karte (leer = gleich). stand: Umgebung der gespeicherten Fingerabdrücke, jetzt: die
    aktuelle. Was verglichen wird, hängt davon ab, wie gut beide Umgebungen übereinstimmen (siehe Kopf der Datei)."""
    stand, jetzt = stand or umgebung(), jetzt or umgebung()
    streng = stand["plattform"] == jetzt["plattform"] and all(stand[k] == jetzt[k] for k in ("shapely", "geos"))
    gleiche_bibliotheken = streng and all(stand[k] == jetzt[k] for k in ("numpy", "pillow"))
    fehler = []
    if streng and erwartet["hinweise"] != aktuell["hinweise"]:
        fehler.append(f"hinweise: {erwartet['hinweise']} -> {aktuell['hinweise']}")
    for k in sorted(set(erwartet["zahlen"]) | set(aktuell["zahlen"])):
        a, b = erwartet["zahlen"].get(k), aktuell["zahlen"].get(k)
        if a != b and (streng or a is None or b is None or not _ungefaehr(a, b)):
            fehler.append(f"zahlen.{k}: {a} -> {b}")
    if streng and erwartet["modell"] != aktuell["modell"]:
        fehler.append(f"modell: {erwartet['modell']} -> {aktuell['modell']}  (der Generator liefert ein anderes Kartenmodell)")
    if set(erwartet["karten"]) != set(aktuell["karten"]):
        fehler.append(f"ansichten: {sorted(erwartet['karten'])} -> {sorted(aktuell['karten'])}")
    for ansicht in sorted(set(erwartet["karten"]) & set(aktuell["karten"])):
        a, b = erwartet["karten"][ansicht], aktuell["karten"][ansicht]
        if streng and a["svg"] != b["svg"]:
            fehler.append(f"{ansicht}.svg: {a['svg']} -> {b['svg']}  (die Zeichnung ohne Bilder ist anders)")
        if gleiche_bibliotheken and a["bilder"] != b["bilder"]:
            nr = [i + 1 for i, (x, y) in enumerate(zip(a["bilder"], b["bilder"])) if x != y] or ["Anzahl"]
            fehler.append(f"{ansicht}.bilder: Bild {nr} ist anders (Texturen)")
    return fehler


def vergleiche(aktuell, gespeichert):
    """{Name: [Abweichungen]} nur für Karten mit Abweichung; fehlende und überzählige Karten zählen auch."""
    stand = gespeichert.get("umgebung")
    out = {}
    for name, ist in aktuell.items():
        soll = gespeichert["faelle"].get(name)
        fehler = ["noch nicht in tests/golden/karten.json"] if soll is None else unterschiede(soll, ist, stand)
        if fehler:
            out[name] = fehler
    for name in gespeichert["faelle"]:
        if name not in aktuell and name not in faelle():
            out[name] = ["steht in tests/golden/karten.json, aber nicht mehr in tests/golden.py"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tests.golden", description="Karten-Vergleichstests.")
    ap.add_argument("text", nargs="?", default="", help="nur Karten, deren Name TEXT enthält")
    ap.add_argument("--update", action="store_true", help="Fingerabdrücke neu schreiben statt vergleichen")
    args = ap.parse_args(argv)
    alle = faelle()
    namen = [n for n in alle if args.text in n]
    if not namen:
        raise SystemExit(f"Keine Karte enthält '{args.text}' im Namen. Möglich: {', '.join(alle)}")
    try:
        alt = laden()
    except FileNotFoundError:
        alt = {"umgebung": umgebung(), "faelle": {}}
    teilweise = args.text != ""
    if args.update and teilweise and alt.get("umgebung") != umgebung():
        raise SystemExit("Die gespeicherten Fingerabdrücke stammen aus einer anderen Umgebung (Betriebssystem oder "
                         "Bibliotheksversionen). Bitte alle Karten neu schreiben: python -m tests.golden --update")
    aktuell = berechne_alle(namen)
    abweichungen = vergleiche(aktuell, alt)
    for name, fehler in abweichungen.items():
        print(f"{name}:")
        for z in fehler:
            print(f"  {z}")
    if not args.update:
        print(f"{len(abweichungen)} von {len(aktuell)} Karten weichen ab." if abweichungen
              else f"Alle {len(aktuell)} Karten wie gespeichert.")
        return 1 if abweichungen else 0
    faelle_neu = {**alt["faelle"], **aktuell}
    speichern({"umgebung": umgebung() if not teilweise else alt["umgebung"],
               "faelle": {n: faelle_neu[n] for n in alle if n in faelle_neu}})   # in der Reihenfolge von faelle()
    print(f"{len(aktuell)} Karten geschrieben nach {DATEI.relative_to(ROOT)}"
          + (f" ({len(abweichungen)} davon neu oder verändert)." if abweichungen else " (keine verändert)."))
    return 0

if __name__ == "__main__":
    sys.exit(main())
