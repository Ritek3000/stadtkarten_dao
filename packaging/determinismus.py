"""Prüft, ob derselbe Seed immer dieselbe Karte liefert, und zeigt bei Abweichungen den ersten Arbeitsschritt,
an dem sich die Läufe unterscheiden.

Nach jedem Schritt des Generators (Küste, Fluss, Stadtumriss, Straßen, Viertel, Häuser ...) wird ein
Fingerabdruck festgehalten: Zustand des Zufallsgenerators sowie Ergebnis und Stadtmodell bitgenau und auf
0,01 px gerundet. Jede Karte entsteht mehrmals, im selben Prozess hintereinander und in frischen Prozessen.

Aufruf (im Projektordner):  python packaging/determinismus.py
Exit-Code 0 = alle Läufe gleich, 1 = Abweichung gefunden (Einzelheiten in der Ausgabe).
"""
import contextlib
import hashlib
import io
import json
import pathlib
import random
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import shapely  # noqa: E402
from shapely.geometry.base import BaseGeometry  # noqa: E402

from stadtkarte import city, config, generator  # noqa: E402
from stadtkarte.render import render_svg  # noqa: E402

FAELLE = [("hafenstadt", 1), ("hafenstadt", 7), ("zwergenstadt", 1), ("sumpfdorf", 1)]
GROESSE = 1000
GENERATOR_SCHRITTE = ["make_coast", "make_islands", "make_river", "make_pools", "make_oases", "build_fortress",
                      "outside_cemetery", "outside_windmill", "outside_farm", "make_mines", "make_fields",
                      "make_forest", "scatter_trees", "suburb_houses", "make_bridges"]
STADT_SCHRITTE = ["outline", "walls_and_gates", "external_roads", "internal_roads", "districts", "buildings",
                  "landmarks", "connect_to_streets", "squares_and_wells", "district_labels", "harbor",
                  "fill_empty_with_trees"]

_trace = []


def _feed(h, obj, rounded, seen):
    if id(obj) in seen:
        return
    if isinstance(obj, BaseGeometry):
        h.update(shapely.to_wkt(obj, rounding_precision=2).encode() if rounded else shapely.to_wkb(obj))
    elif isinstance(obj, dict):
        seen.add(id(obj))
        for k in sorted(obj, key=str):
            if str(k).startswith("_") or callable(obj[k]):
                continue
            h.update(str(k).encode())
            _feed(h, obj[k], rounded, seen)
    elif isinstance(obj, (list, tuple)):
        seen.add(id(obj))
        h.update(b"[%d" % len(obj))
        for v in obj:
            _feed(h, v, rounded, seen)
    elif isinstance(obj, np.ndarray):
        h.update(np.round(obj, 2).tobytes() if rounded else obj.tobytes())
    elif isinstance(obj, (float, np.floating)):
        h.update((f"{float(obj):.2f}" if rounded else repr(float(obj))).encode())
    elif isinstance(obj, (int, str, bool, type(None), np.integer)):
        h.update(repr(obj).encode())


def _fp(obj, rounded):
    h = hashlib.sha1()
    _feed(h, obj, rounded, set())
    return h.hexdigest()[:12]


def _rng_fp(rng):
    return hashlib.sha1(repr(rng.getstate()).encode()).hexdigest()[:12] if rng is not None else "-"


def _record(name, rng, *objs):
    _trace.append([name, _rng_fp(rng), _fp(objs, False), _fp(objs, True)])


def _wrap_function(module, name):
    fn = getattr(module, name, None)
    if fn is None or getattr(fn, "_traced", False):
        return

    def traced(*args, **kw):
        res = fn(*args, **kw)
        rng = next((a for a in args if isinstance(a, random.Random)), None)
        _record(name, rng, res)
        return res
    traced._traced = True
    setattr(module, name, traced)


def _wrap_method(cls, name):
    fn = getattr(cls, name, None)
    if fn is None or getattr(fn, "_traced", False):
        return

    def traced(self, *args, **kw):
        res = fn(self, *args, **kw)
        _record(f"Stadt.{name}", self.rng, res, self.out)
        return res
    traced._traced = True
    setattr(cls, name, traced)


def install():
    for name in GENERATOR_SCHRITTE:
        _wrap_function(generator, name)
    for name in STADT_SCHRITTE:
        _wrap_method(city.CityBuilder, name)


def trace(beispiel, seed):
    """Fingerabdrücke aller Schritte für eine Karte."""
    _trace.clear()
    cfg = config.load(ROOT / "beispiele" / f"{beispiel}.yaml")
    cfg["seed"] = seed
    cfg["ausgabe"]["bildgroesse"] = GROESSE
    with contextlib.redirect_stdout(io.StringIO()):
        m = generator.generate(cfg)
        _record("Ergebnis generate", None, {k: v for k, v in m.items() if k != "cfg"})
        _record("render_svg", None, render_svg(m))
    _trace.append(["Anzahl Gebäude", "-", str(len(m["buildings"]) + len(m["suburbs"])), ""])
    return [list(t) for t in _trace]


def compare(name, runs):
    """Vergleicht alle Läufe mit dem ersten; liefert True, wenn alle gleich sind."""
    ok = True
    ref_label, ref = runs[0]
    for label, tr in runs[1:]:
        if tr == ref:
            continue
        ok = False
        n = min(len(tr), len(ref))
        i = next((k for k in range(n) if tr[k] != ref[k]), n)
        print(f"  ABWEICHUNG {name}: {label} gegen {ref_label}")
        if i == n:
            print(f"    unterschiedlich viele Schritte: {len(ref)} gegen {len(tr)}")
            continue
        a, b = ref[i], tr[i]
        what = [w for w, x, y in (("Zufallszustand", a[1], b[1]), ("Ergebnis bitgenau", a[2], b[2]),
                                  ("Ergebnis auf 0,01 px", a[3], b[3])) if x != y]
        if a[0] != b[0]:
            what = [f"anderer Schritt: {a[0]} gegen {b[0]}"]
        print(f"    erster abweichender Schritt Nr. {i + 1}: {a[0]}  ({', '.join(what)})")
        print(f"    davor gleich: {', '.join(t[0] for t in ref[max(0, i - 3):i]) or '-'}")
        if ref[-1][0] == "Anzahl Gebäude":
            print(f"    Gebäude: {ref[-1][2]} gegen {tr[-1][2]}")
    if ok:
        print(f"  gleich      {name}: {len(runs)} Läufe, {len(ref)} Schritte, {ref[-1][2]} Gebäude")
    return ok


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--einzeln":   # Kindprozess: eine Karte, Ergebnis als JSON
        install()
        print(json.dumps(trace(sys.argv[2], int(sys.argv[3]))))
        return 0
    install()
    print(f"Determinismus-Prüfung (Python {sys.version.split()[0]}, Shapely {shapely.__version__}, "
          f"GEOS {shapely.geos_version_string}, numpy {np.__version__}, {sys.platform})")
    all_ok = True
    for beispiel, seed in FAELLE:
        runs = [("Prozess A, Lauf 1", trace(beispiel, seed)), ("Prozess A, Lauf 2", trace(beispiel, seed))]
        for k in (1, 2):
            out = subprocess.run([sys.executable, __file__, "--einzeln", beispiel, str(seed)],
                                 capture_output=True, text=True, check=True).stdout
            runs.append((f"frischer Prozess {k}", json.loads(out.strip().splitlines()[-1])))
        all_ok &= compare(f"{beispiel} Seed {seed}", runs)
    print("Alle Läufe gleich." if all_ok else "Es gibt Abweichungen (siehe oben).")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
