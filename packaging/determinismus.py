"""Prüft, ob derselbe Seed immer dieselbe Karte liefert, auch auf einem anderen Prozessor, und zeigt bei
Abweichungen den ersten Arbeitsschritt, an dem sich die Läufe unterscheiden.

Nach jedem Schritt des Generators (Küste, Fluss, Stadtumriss, Straßen, Viertel, Häuser ...) wird ein
Fingerabdruck festgehalten: Zustand des Zufallsgenerators sowie Ergebnis und Stadtmodell bitgenau und auf
0,01 px gerundet. Jede Karte entsteht mehrmals: im selben Prozess hintereinander und in frischen Prozessen,
die andere Prozessoren nachahmen (anderer OpenBLAS-Rechenkern, numpy ohne AVX-512). Früher rundete OpenBLAS
je nach Prozessor anders und derselbe Seed ergab andere Karten; diese Prüfung fängt solche Rückfälle ab.
Nicht abgedeckt: Windows und Linux untereinander (eigene Mathebibliotheken, auch in GEOS).

Aufruf (im Projektordner):  python packaging/determinismus.py
Exit-Code 0 = alle Läufe gleich, 1 = Abweichung gefunden (Einzelheiten in der Ausgabe).
"""
import contextlib
import hashlib
import io
import json
import os
import pathlib
import random
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import shapely  # noqa: E402
from shapely.geometry.base import BaseGeometry  # noqa: E402

from stadtkarte import city, config, generator  # noqa: E402
from stadtkarte.render import render_svg  # noqa: E402

FAELLE = [("hafenstadt", 1), ("hafenstadt", 7), ("zwergenstadt", 1), ("sumpfdorf", 1), ("auenstadt", 1),
          ("mittelmeerhafen", 1), ("moordorf", 1)]
GROESSE = 1000
GENERATOR_SCHRITTE = ["make_coast", "make_islands", "make_river", "make_pools", "make_oxbows", "make_oases", "build_fortress",
                      "outside_cemetery", "outside_windmill", "outside_farm", "make_mines", "make_fields",
                      "make_forest", "fill_forest", "scatter_trees", "suburb_houses", "make_bridges"]
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
        _record("render_svg", None, render_svg(m, nacht=False))
        _record("render_svg_nacht", None, render_svg(m, nacht=True))   # die Werkstatt zeichnet beide aus einer Stadt
    _trace.append(["Anzahl Gebäude", "-", str(len(m["buildings"]) + len(m["suburbs"])), ""])
    return [list(t) for t in _trace]


def compare(name, runs):
    """Vergleicht alle Läufe mit dem ersten; liefert True, wenn alle gleich sind. Läufe mit nachgeahmtem
    Prozessor vergleichen nur die Karte, nicht die SVG: deren Bodentextur darf in einzelnen Pixeln abweichen."""
    ok = True
    ref_label, ref_all, _ = runs[0]
    for label, tr, variant in runs[1:]:
        ref = [t for t in ref_all if not (variant and t[0].startswith("render_svg"))]
        tr = [t for t in tr if not (variant and t[0].startswith("render_svg"))]
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
        print("    Schritte (Nr. Schritt Zufall bitgenau gerundet), Referenz | Abweichung:")
        for k, (a, b) in enumerate(zip(ref, tr), 1):
            print(f"    {k:2d} {a[0]:28s} {a[1]} {a[2]} {a[3]} | {b[1]} {b[2]} {b[3]}")
    if ok:
        print(f"  gleich      {name}: {len(runs)} Läufe, {len(ref_all)} Schritte, {ref_all[-1][2]} Gebäude")
    return ok


def cpu_name():
    """Prozessormodell (unter Windows aus der Registry, unter Linux aus /proc/cpuinfo)."""
    try:
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        for line in open("/proc/cpuinfo", encoding="utf-8"):
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    import platform
    return platform.processor() or "unbekannt"


def math_fingerprints():
    """Bitgenaue Fingerabdrücke mathematischer Funktionen. Unterscheiden sie sich zwischen zwei Maschinen,
    rechnet die Plattform dort unterschiedlich (z.B. CPU-abhängige Rechenwege der Mathebibliothek)."""
    import math
    xs = [i * 0.37 - 1500.0 for i in range(8000)]
    out = {}
    for name, fn in (("sin", math.sin), ("cos", math.cos), ("atan2", lambda x: math.atan2(x, 3.1)),
                     ("exp", lambda x: math.exp(x / 900)), ("log", lambda x: math.log(abs(x) + 1)),
                     ("sqrt", lambda x: math.sqrt(abs(x))), ("pow", lambda x: abs(x) ** 0.37)):
        out[f"py.{name}"] = hashlib.sha1(repr([fn(x) for x in xs]).encode()).hexdigest()[:10]
    a = np.array(xs)
    for name, fn in (("sin", np.sin), ("cos", np.cos), ("arctan2", lambda v: np.arctan2(v, 3.1)),
                     ("exp", lambda v: np.exp(v / 900)), ("log", lambda v: np.log(np.abs(v) + 1)),
                     ("sqrt", lambda v: np.sqrt(np.abs(v))), ("power", lambda v: np.abs(v) ** 0.37)):
        out[f"np.{name}"] = hashlib.sha1(fn(a).tobytes()).hexdigest()[:10]
    return out


def numpy_cpu_features():
    try:
        from numpy._core._multiarray_umath import __cpu_features__ as feats
    except ImportError:
        return "?"
    return " ".join(k for k in ("SSE42", "AVX", "FMA3", "AVX2", "AVX512F", "AVX512_SKX", "AVX512_ICL", "AVX512_SPR")
                    if feats.get(k))


def variants():
    """Prozessor-Varianten, die auf diesem Rechner laufen können (ein Rechenkern mit Befehlen, die der Prozessor
    nicht kennt, würde abstürzen). Auf Rechnern mit AVX-512 ist auch der früher abweichende SkylakeX-Kern dabei."""
    try:
        from numpy._core._multiarray_umath import __cpu_features__ as feats
    except ImportError:
        feats = {}
    out = [("frischer Prozess", {}), ("OpenBLAS-Kern Prescott (SSE3)", {"OPENBLAS_CORETYPE": "Prescott"})]
    if feats.get("AVX2"):
        out.append(("OpenBLAS-Kern Haswell (AVX2)", {"OPENBLAS_CORETYPE": "Haswell"}))
    if feats.get("AVX512_SKX"):
        out.append(("OpenBLAS-Kern SkylakeX (AVX-512)", {"OPENBLAS_CORETYPE": "SkylakeX"}))
    if feats.get("AVX512F"):
        out.append(("numpy ohne AVX-512", {"NPY_DISABLE_CPU_FEATURES": "X86_V4 AVX512_ICL AVX512_SPR"}))
    return out


BLAS_AUFRUFE = re.compile(r"np\.(dot|linalg|matmul|inner|vdot|einsum|tensordot)\b|\w\s@\s\w")


def blas_im_code():
    """Rechnungen, die über OpenBLAS laufen, runden je nach Prozessor anders - im Generator verboten (geo.vlen und
    geo.vdot rechnen bitgleich). Die Suche fängt das auch auf Rechnern, auf denen die Läufe zufällig gleich sind."""
    funde = []
    for f in sorted((pathlib.Path(__file__).resolve().parents[1] / "stadtkarte").glob("*.py")):
        for nr, zeile in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = zeile.split("#")[0]
            if BLAS_AUFRUFE.search(code) and '"""' not in zeile:
                funde.append(f"{f.name}:{nr}: {zeile.strip()}")
    return funde


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--einzeln":   # Kindprozess: eine Karte, Ergebnis als JSON
        install()
        print(json.dumps(trace(sys.argv[2], int(sys.argv[3]))))
        return 0
    install()
    print(f"Determinismus-Prüfung (Python {sys.version.split()[0]}, Shapely {shapely.__version__}, "
          f"GEOS {shapely.geos_version_string}, numpy {np.__version__}, {sys.platform})")
    print(f"Prozessor: {cpu_name()}")
    print(f"numpy nutzt: {numpy_cpu_features()}")
    print("Rechen-Fingerabdruck: " + " ".join(f"{k}={v}" for k, v in math_fingerprints().items()))
    vs = variants()
    print("Verglichen werden: Lauf 1 und 2 im selben Prozess, " + ", ".join(v for v, _ in vs))
    all_ok = True
    funde = blas_im_code()
    for fund in funde:
        print(f"  BLAS-Aufruf {fund}  (je nach Prozessor andere Rundung: geo.vdot/geo.vlen verwenden)")
    all_ok &= not funde
    for beispiel, seed in FAELLE:
        runs = [("Lauf 1", trace(beispiel, seed), False), ("Lauf 2", trace(beispiel, seed), False)]
        for label, env in vs:
            out = subprocess.run([sys.executable, __file__, "--einzeln", beispiel, str(seed)],
                                 capture_output=True, text=True, check=True, env={**os.environ, **env}).stdout
            runs.append((label, json.loads(out.strip().splitlines()[-1]), bool(env)))
        all_ok &= compare(f"{beispiel} Seed {seed}", runs)
    print("Alle Läufe gleich." if all_ok else "FEHLER: derselbe Seed ergibt verschiedene Karten (siehe oben).")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
