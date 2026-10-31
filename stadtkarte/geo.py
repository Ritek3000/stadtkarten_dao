"""Geometrie-Hilfsfunktionen und Rauschen."""
import math

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPoint, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import split, unary_union

from .simplex import Simplex1


class Noise1D(Simplex1):
    """Glattes 1D-Simplex-Rauschen (Gradientenrauschen); bei period=n ist fbm(x) periodisch mit Periode n."""

    def fbm(self, x, octaves=4):
        total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
        for o in range(octaves):
            total += amp * self.value(x * freq + o * 31)
            norm += amp
            amp *= 0.5
            freq *= 2
        return total / norm


def polys(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    if hasattr(g, "geoms"):
        return [p for sub in g.geoms for p in polys(sub)]
    return []


def lines(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type in ("LineString", "LinearRing"):
        return [LineString(g.coords)]
    if hasattr(g, "geoms"):
        return [ln for sub in g.geoms for ln in lines(sub)]
    return []


def points(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Point":
        return [g]
    if hasattr(g, "geoms"):
        return [p for sub in g.geoms for p in points(sub)]
    return []


def clean(g, min_area=1.0):
    return [p for p in polys(g) if p.area >= min_area]


def blob(rng, cx, cy, r, rough=0.25, n=72, stretch=(1.0, 1.0)):
    """Unregelmäßige rundliche Fläche."""
    noise = Noise1D(rng, period=8)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        rad = r * (1 + rough * noise.fbm(8 * i / n, 3) * 1.6)
        pts.append((cx + math.cos(a) * rad * stretch[0], cy + math.sin(a) * rad * stretch[1]))
    return Polygon(pts).buffer(0)


def axes(poly):
    """Ecke, lange Achse, kurze Achse des kleinsten umschließenden Rechtecks."""
    rect = poly.minimum_rotated_rectangle
    if rect.geom_type != "Polygon":
        return None
    c = np.array(rect.exterior.coords)[:4]
    e1, e2 = c[1] - c[0], c[3] - c[0]
    if vlen(e1) < vlen(e2):
        e1, e2 = e2, e1
    return c[0], e1, e2


def min_width(poly):
    ax = axes(poly)
    return 0.0 if ax is None else vlen(ax[2])


def cut(poly, frac, gap, jitter=0.0):
    """Teilt ein Polygon quer zur langen Achse; gap>0 lässt eine Gasse frei."""
    ax = axes(poly)
    if ax is None:
        return [poly]
    o, e1, e2 = ax
    l2 = vlen(e2)
    if l2 < 1e-6:
        return [poly]
    d = e2 / l2
    if jitter:
        ca, sa = math.cos(jitter), math.sin(jitter)
        d = np.array([d[0] * ca - d[1] * sa, d[0] * sa + d[1] * ca])
    q = o + e1 * frac
    ext = l2 * 2 + vlen(e1)
    line = LineString([q - d * ext, q + d * ext])
    try:
        res = poly.difference(line.buffer(gap / 2, cap_style="flat")) if gap > 0 else split(poly, line)
    except Exception:
        return [poly]
    return [p for p in polys(res) if p.area > 1]


def subdivide(poly, max_area, gap, rng, min_area, var=0.3, jitter=0.06):
    out, stack, guard = [], [poly], 0
    while stack and guard < 50000:
        guard += 1
        p = stack.pop()
        if p.area < min_area:
            continue
        if p.area <= max_area * rng.uniform(1 - var, 1 + var):
            out.append(p)
            continue
        pieces = cut(p, rng.uniform(0.38, 0.62), gap, rng.uniform(-jitter, jitter))
        if len(pieces) == 1 and abs(pieces[0].area - p.area) < 1:
            out.append(p)
            continue
        stack.extend(pieces)
    return out


def is_rect(poly):
    return len(poly.exterior.coords) == 5 and poly.area >= 0.98 * poly.minimum_rotated_rectangle.area


def hip_planes(poly):
    """Walmdach für beliebige Grundrisse: jede Dachfläche gehört zur nächstgelegenen Außenwand
    (Voronoi-Zerlegung entlang der Wände, entspricht einem Walmdach mit gleicher Neigung).
    Liefert (Flächen, Grate); Fläche = (Polygon, Normale nach außen, Wandrichtung, Traufpunkt, Tiefe)."""
    poly = orient(poly, 1.0)                          # gegen den Uhrzeigersinn: Normale (dy, -dx) zeigt nach außen
    cs = np.array(poly.exterior.coords)[:-1]
    edges = []
    pts, labels = [], []
    for i in range(len(cs)):
        a, b = cs[i], cs[(i + 1) % len(cs)]
        d = b - a
        L = float(np.hypot(*d))
        if L < 1e-6:
            continue
        k = max(4, int(L / 1.0))
        for t in np.linspace(0.03, 0.97, k):
            pts.append(a + d * t)
            labels.append(len(edges))
        edges.append((a, d / L, np.array([d[1], -d[0]]) / L))
    cells = shapely.voronoi_polygons(MultiPoint(pts), ordered=True, extend_to=poly.buffer(poly.length))
    groups = {}
    for lab, cell in zip(labels, cells.geoms):
        groups.setdefault(lab, []).append(cell)
    planes = []
    for lab, cl in groups.items():
        try:
            region = unary_union(cl).intersection(poly)
        except shapely.errors.GEOSException:   # seltene Rundungsfehler der Voronoi-Zellen: bereinigt erneut versuchen
            region = unary_union([c.buffer(0) for c in cl]).intersection(poly.buffer(0))
        if region.is_empty or region.area < 0.5:
            continue
        a, rd, n = edges[lab]
        rc = np.array([c for g in polys(region) for c in g.exterior.coords])
        depth = float(np.max((rc[:, 0] - a[0]) * -n[0] + (rc[:, 1] - a[1]) * -n[1])) if len(rc) else 0.0
        planes.append((region, n, rd, a, max(depth, 0.5)))
    inner = unary_union([pl[0].boundary for pl in planes]).difference(poly.exterior.buffer(0.25))
    ridges = [ln for ln in lines(inner) if ln.length > 0.4]
    return planes, ridges


def roof(poly):
    """First, Gratlinien und verschattete Dachhälfte eines Gebäudes."""
    if not is_rect(poly):
        planes, ridges = hip_planes(poly)
        shade = unary_union([g for g, n, *_ in planes if n[0] * 0.6 + n[1] * 0.8 > 0])
        return ridges, (shade if not shade.is_empty else None)
    ax = axes(poly)
    if ax is None:
        return [], None
    o, e1, e2 = ax
    l1, l2 = vlen(e1), vlen(e2)
    u = e1 / l1
    h = min(l2 / 2, l1 / 2)
    a = o + e2 / 2 + u * h
    b = o + e1 + e2 / 2 - u * h
    ridge_lines = []
    if vlen(b - a) > 0.5:
        ridge_lines.append(LineString([a, b]))
    for p, q in ((a, o), (a, o + e2), (b, o + e1), (b, o + e1 + e2)):
        ridge_lines.append(LineString([p, q]))
    clipped = [ln for r in ridge_lines for ln in lines(r.intersection(poly))]
    half = Polygon([o, o + e1, o + e1 + e2 / 2, o + e2 / 2]).intersection(poly)
    return clipped, (half if not half.is_empty else None)


def vlen(v):
    """Länge eines 2D-Vektors. Bewusst nicht np.linalg.norm/np.dot: die laufen über OpenBLAS, das je nach
    Prozessor einen anderen Rechenkern wählt und dann in der letzten Stelle anders rundet. Knappe Entscheidungen
    (passt ein Haus noch?) kippten dadurch, und derselbe Seed ergab auf verschiedenen Rechnern andere Karten.
    Die schlichte Formel liefert dieselben Werte wie bisher die verbreiteten Rechenkerne (Haswell/Zen)."""
    x, y = float(v[0]), float(v[1])
    return math.sqrt(x * x + y * y)


def vdot(a, b):
    """Skalarprodukt zweier 2D-Vektoren, auf jedem Prozessor bitgleich (siehe vlen)."""
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1])


def unit(v):
    n = math.hypot(v[0], v[1])
    return (v[0] / n, v[1] / n) if n > 1e-9 else (0.0, 0.0)


def fit_rect(poly, min_short=0.0, max_ratio=None, iters=60):
    """Größtes (näherungsweise) Rechteck in poly, ausgerichtet am kleinsten umschließenden Rechteck.

    Startet mit dem umschließenden Rechteck und schiebt jeweils die Seite nach innen, an der am meisten
    Fläche über das Polygon hinausragt. Liefert None, wenn die kurze Seite kleiner als min_short wird.
    max_ratio kürzt zu lange, schmale Rechtecke mittig auf langes/kurzes Verhältnis <= max_ratio."""
    ax = axes(poly)
    if ax is None:
        return None
    o, e1, e2 = ax
    l1, l2 = vlen(e1), vlen(e2)
    if l2 < 1e-6:
        return None
    u, v = e1 / l1, e2 / l2

    def make(a0, a1, b0, b1):
        return Polygon([o + u * a0 + v * b0, o + u * a1 + v * b0, o + u * a1 + v * b1, o + u * a0 + v * b1])

    a0, a1, b0, b1 = 0.0, l1, 0.0, l2
    fit = poly.buffer(0.05)
    for _ in range(iters):
        rect = make(a0, a1, b0, b1)
        out = rect.difference(fit)
        if out.area <= 0.003 * rect.area:
            break
        da, db = (a1 - a0) * 0.12, (b1 - b0) * 0.12
        sides = [make(a0, a0 + da, b0, b1), make(a1 - da, a1, b0, b1),
                 make(a0, a1, b0, b0 + db), make(a0, a1, b1 - db, b1)]
        # Überstand je Seite, bezogen auf die Seitenlänge (sonst würde immer die lange Seite gekürzt)
        score = [out.intersection(sd).area / L for sd, L in zip(sides, (b1 - b0, b1 - b0, a1 - a0, a1 - a0))]
        k = int(np.argmax(score))
        step_a, step_b = max(0.3, (a1 - a0) * 0.04), max(0.3, (b1 - b0) * 0.04)
        if k == 0:
            a0 += step_a
        elif k == 1:
            a1 -= step_a
        elif k == 2:
            b0 += step_b
        else:
            b1 -= step_b
        if a1 - a0 < min_short or b1 - b0 < min_short:
            return None
    else:
        return None
    # Ergebnis normieren: kurze Seite prüfen, zu langgestreckte Häuser mittig kürzen
    w, h = a1 - a0, b1 - b0
    short, long_ = min(w, h), max(w, h)
    if short < min_short:
        return None
    if max_ratio and long_ > short * max_ratio:
        cut = (long_ - short * max_ratio) / 2
        if w >= h:
            a0, a1 = a0 + cut, a1 - cut
        else:
            b0, b1 = b0 + cut, b1 - cut
    # Rest-Überstand beseitigen: gleichmäßig verkleinern, bis das Rechteck sicher im Grundstück liegt
    strict = poly.buffer(0.15)
    for _ in range(12):
        rect = make(a0, a1, b0, b1)
        if strict.contains(rect):
            return rect if min(a1 - a0, b1 - b0) >= min_short else None
        da, db = (a1 - a0) * 0.02, (b1 - b0) * 0.02
        a0, a1, b0, b1 = a0 + da, a1 - da, b0 + db, b1 - db
    return None
