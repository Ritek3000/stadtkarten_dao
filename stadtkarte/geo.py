"""Geometrie-Hilfsfunktionen und Rauschen."""
import math

import numpy as np
import shapely
from shapely.errors import ShapelyError
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


def rings(g):
    """Flächen als (Außenring, [Löcher]) in Koordinatenlisten (Eingabe der Bildmasken, z.B. umgebung._mask)."""
    return [(list(p.exterior.coords), [list(h.coords) for h in p.interiors]) for p in polys(g)]


def oriented_rect(cx, cy, tx, ty, L, B):
    """Rechteck L x B um (cx, cy), dessen lange Seite in Richtung (tx, ty) zeigt."""
    return Polygon([(cx + tx * a * L / 2 - ty * b * B / 2, cy + ty * a * L / 2 + tx * b * B / 2)
                    for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))])


def ship_footprint(cx, cy, length, width, angle_deg):
    """Grundfläche eines Schiffs als gedrehtes Rechteck."""
    a = math.radians(angle_deg)
    u, v = np.array([math.cos(a), math.sin(a)]), np.array([-math.sin(a), math.cos(a)])
    c = np.array([cx, cy])
    return Polygon([c - u * length / 2 - v * width / 2, c + u * length / 2 - v * width / 2,
                    c + u * length / 2 + v * width / 2, c - u * length / 2 + v * width / 2])


def clean(g, min_area=1.0):
    return [p for p in polys(g) if p.area >= min_area]


def merge_polys(a, b, tol=0.01):
    """Vereinigt zwei Flächen zu einem einzelnen Polygon; Haarspalte unter 2*tol werden dabei geschlossen.
    None, wenn daraus kein einzelnes Polygon wird (die Flächen berühren sich nicht oder nur an einem Punkt).
    Aufweiten und wieder Schrumpfen liefert in GEOS bei manchen Formen 'leer', etwa wenn die Vereinigung neben dem
    Polygon noch Linienreste enthält. Ein leeres Polygon gilt aber als 'Polygon' und fiele erst viel später auf
    (min_width/axes), deshalb wird dann ohne die Linienreste neu gerechnet und im Zweifel die Vereinigung selbst
    genommen, sofern sie schon ein einzelnes Polygon ist."""
    union = a.union(b)
    joined = union.buffer(tol).buffer(-tol)
    if joined.is_empty:
        parts = polys(union)
        if parts:
            joined = unary_union(parts).buffer(tol).buffer(-tol)
            if joined.is_empty and len(parts) == 1:
                joined = parts[0]
    return joined if joined.geom_type == "Polygon" and not joined.is_empty else None


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
    except (ShapelyError, ValueError):   # GEOS kann den Schnitt nicht berechnen: Fläche bleibt ungeteilt
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


_HIP_CACHE = {}


def hip_planes(poly):
    """Walmdach für beliebige Grundrisse: jede Dachfläche gehört zur nächstgelegenen Außenwand (entspricht einem
    Walmdach mit gleicher Neigung). Liefert (Flächen, Grate); Fläche = (Polygon, Normale nach außen, Wandrichtung,
    Traufpunkt, Tiefe). Konvexe Grundrisse rechnet _convex_hip_planes exakt, die übrigen _voronoi_hip_planes.
    Generator (Grate, Schatten) und Zeichnen (Dachflächen) fragen dasselbe Haus ab: das Ergebnis wird gemerkt."""
    key = poly.wkb
    hit = _HIP_CACHE.get(key)
    if hit is None:
        hit = _convex_hip_planes(poly) or _voronoi_hip_planes(poly)
        if len(_HIP_CACHE) >= 4096:   # Speicher begrenzen (eine Großstadt hat einige hundert solcher Häuser)
            _HIP_CACHE.clear()
        _HIP_CACHE[key] = hit
    return list(hit[0]), list(hit[1])


def _convex_hip_planes(poly):
    """Walmdach eines konvexen Grundrisses, exakt. Die Dachfläche einer Wand ist der Teil des Grundrisses, der näher an
    der Traufe (als Gerade) liegt als an jeder anderen; bei konvexen Grundrissen ist das genau das Walmdach mit gleicher
    Neigung. Jede Fläche ist damit ein Schnitt von Halbebenen: einfaches Abschneiden statt Voronoi und Vereinigung.
    Die Dachhöhe über einem Punkt ist sein Abstand zur Traufe seiner Fläche, also zur nächsten Wand; Grate werden wie
    bei _voronoi_hip_planes erst ab 0,25 px Abstand zur Wand gezeichnet. None, wenn poly nicht konvex ist oder Löcher hat."""
    if poly.interiors:
        return None
    raw = [(float(x), float(y)) for x, y in list(orient(poly, 1.0).exterior.coords)[:-1]]
    pts = []
    for p in raw:                                      # doppelte Punkte weglassen
        if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 1e-6:
            pts.append(p)
    while len(pts) > 2 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= 1e-6:
        pts.pop()
    i = 0
    while len(pts) >= 3 and i < len(pts):              # Ecken auf einer Geraden weglassen, einspringende: nicht konvex
        (ax, ay), (bx, by), (cx, cy) = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cross) <= 1e-9 * math.hypot(bx - ax, by - ay) * math.hypot(cx - bx, cy - by):
            del pts[i]
            i = max(i - 1, 0)
        elif cross < 0:
            return None
        else:
            i += 1
    if len(pts) < 3:
        return None
    edges = []                                         # (Traufpunkt, Richtung, Normale nach innen)
    for i, (ax, ay) in enumerate(pts):
        bx, by = pts[(i + 1) % len(pts)]
        L = math.hypot(bx - ax, by - ay)
        dx, dy = (bx - ax) / L, (by - ay) / L
        edges.append((ax, ay, dx, dy, -dy, dx))

    def height(e, x, y):
        return (x - e[0]) * e[4] + (y - e[1]) * e[5]

    planes, ridges = [], []
    for i, e in enumerate(edges):
        ax, ay, dx, dy, mx, my = e
        face = pts
        for j, f in enumerate(edges):                  # näher an Wand i als an Wand j
            if j != i:
                nx, ny = mx - f[4], my - f[5]
                if abs(nx) + abs(ny) > 1e-12:
                    face = _clip_halfplane(face, nx, ny, ax * mx + ay * my - (f[0] * f[4] + f[1] * f[5]))
        if abs(signed_area(face)) < 0.5:
            continue
        hs = [height(e, x, y) for x, y in face]
        planes.append((Polygon(face), np.array([dy, -dx]), np.array([dx, dy]), np.array([ax, ay]), max(max(hs), 0.5)))
        for k in range(len(face)):                     # Grate: Kanten der Fläche, die nicht auf der Traufe liegen
            (px, py), (qx, qy), hp, hq = face[k - 1], face[k], hs[k - 1], hs[k]
            if max(hp, hq) <= 0.25:                    # (auch die Traufe selbst)
                continue
            mid = ((px + qx) / 2, (py + qy) / 2)
            hm = height(e, *mid)
            nb = [j for j, f in enumerate(edges) if j != i and abs(height(f, *mid) - hm) <= 1e-6 * (1 + hm)]
            if nb and min(nb) < i:                     # gemeinsamer Grat zweier Flächen: nur einmal
                continue
            if hp < 0.25:
                t = (0.25 - hp) / (hq - hp)
                px, py = px + t * (qx - px), py + t * (qy - py)
            elif hq < 0.25:
                t = (0.25 - hq) / (hp - hq)
                qx, qy = qx + t * (px - qx), qy + t * (py - qy)
            if math.hypot(qx - px, qy - py) > 0.4:
                ridges.append(LineString([(px, py), (qx, qy)]))
    return (planes, ridges) if planes else None


def _voronoi_hip_planes(poly):
    """Walmdach für beliebige Grundrisse (auch mit einspringenden Ecken): Voronoi-Zerlegung entlang der Wände."""
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


def vlen3(v):
    """Länge eines 3D-Vektors, auf jedem Prozessor bitgleich (siehe vlen; z.B. für die Lichtrichtung)."""
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    return math.sqrt(x * x + y * y + z * z)


def vdot(a, b):
    """Skalarprodukt zweier 2D-Vektoren, auf jedem Prozessor bitgleich (siehe vlen)."""
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1])


def unit(v):
    n = math.hypot(v[0], v[1])
    return (v[0] / n, v[1] / n) if n > 1e-9 else (0.0, 0.0)


# Flächen im Achsensystem eines Grundstücks, ohne GEOS. Beim Einpassen der Häuser werden tausende Male Rechtecke und
# einfache Formen mit einem Grundstück verglichen. GEOS stellt dafür jedes Mal eine vollständige Verschneidung auf; im
# Achsensystem des Grundstücks genügen Abschneiden an Geraden (Sutherland-Hodgman) und die Gaußsche Trapezformel. Das ist
# in Python fünf- bis sechsmal so schnell (auch im Browser unter Pyodide) und rechnet als reines Python mit einfachen
# Gleitkommazahlen auf jedem Prozessor gleich (siehe vlen).

def local_rings(geom, o, u, v):
    """Ringe einer Fläche im Achsensystem (Ursprung o, Einheitsvektoren u und v): Liste aus (Außenring, [Löcher]),
    jeder Ring eine Liste von (a, b) ohne den wiederholten Startpunkt."""
    ox, oy, ux, uy, vx, vy = float(o[0]), float(o[1]), float(u[0]), float(u[1]), float(v[0]), float(v[1])

    def ring(coords):
        return [((x - ox) * ux + (y - oy) * uy, (x - ox) * vx + (y - oy) * vy) for x, y in list(coords)[:-1]]
    return [(ring(p.exterior.coords), [ring(h.coords) for h in p.interiors]) for p in polys(geom)]


def signed_area(pts):
    """Fläche eines Rings (Liste von Punkten) mit Vorzeichen: positiv gegen den Uhrzeigersinn."""
    if len(pts) < 3:
        return 0.0
    s = 0.0
    px, py = pts[-1]
    for x, y in pts:
        s += px * y - x * py
        px, py = x, y
    return s / 2


def _clip_box(pts, x0, x1, y0, y1):
    """Ring am achsenparallelen Rechteck [x0, x1] × [y0, y1] abschneiden (Sutherland-Hodgman). Bei nicht konvexen
    Ringen können doppelt durchlaufene Kanten entstehen; sie haben keine Fläche, die Fläche bleibt richtig."""
    for axis, val, lower in ((0, x0, True), (0, x1, False), (1, y0, True), (1, y1, False)):
        if len(pts) < 3:
            return []
        out = []
        px, py = pts[-1]
        pc = px if axis == 0 else py
        pin = pc >= val if lower else pc <= val
        for x, y in pts:
            c = x if axis == 0 else y
            cin = c >= val if lower else c <= val
            if cin != pin:
                t = (val - pc) / (c - pc)
                out.append((val, py + t * (y - py)) if axis == 0 else (px + t * (x - px), val))
            if cin:
                out.append((x, y))
            px, py, pc, pin = x, y, c, cin
        pts = out
    return pts


def _clip_halfplane(pts, nx, ny, c):
    """Ring auf der Seite nx * x + ny * y <= c abschneiden (Sutherland-Hodgman an einer Geraden)."""
    if len(pts) < 3:
        return []
    out = []
    px, py = pts[-1]
    pd = nx * px + ny * py - c
    for x, y in pts:
        d = nx * x + ny * y - c
        if (d <= 0) != (pd <= 0):
            t = pd / (pd - d)
            out.append((px + t * (x - px), py + t * (y - py)))
        if d <= 0:
            out.append((x, y))
        px, py, pd = x, y, d
    return out


def area_in_box(rings, x0, x1, y0, y1):
    """Fläche der Ringe (aus local_rings) innerhalb des achsenparallelen Rechtecks [x0, x1] × [y0, y1]."""
    total = 0.0
    for ext, holes in rings:
        a = abs(signed_area(_clip_box(ext, x0, x1, y0, y1)))
        if a > 0:
            total += a - sum(abs(signed_area(_clip_box(h, x0, x1, y0, y1))) for h in holes)
    return total


def _outside(whole, inside):
    """Überstand (Fläche minus Fläche im Grundstück); Rundungsreste der Größenordnung 1e-9 zählen als 0, damit bei
    Gleichstand dieselbe Seite gewinnt wie bei einer exakten Rechnung."""
    out = whole - inside
    return out if out > 1e-9 * whole else 0.0


def fit_rect(poly, min_short=0.0, max_ratio=None, iters=60):
    """Größtes (näherungsweise) Rechteck in poly, ausgerichtet am kleinsten umschließenden Rechteck.

    Startet mit dem umschließenden Rechteck und schiebt jeweils die Seite nach innen, an der am meisten
    Fläche über das Polygon hinausragt. Liefert None, wenn die kurze Seite kleiner als min_short wird.
    max_ratio kürzt zu lange, schmale Rechtecke mittig auf langes/kurzes Verhältnis <= max_ratio.
    Gerechnet wird im Achsensystem, in dem das Rechteck achsenparallel liegt (local_rings, area_in_box)."""
    ax = axes(poly)
    if ax is None:
        return None
    o, e1, e2 = ax
    l1, l2 = vlen(e1), vlen(e2)
    if l2 < 1e-6:
        return None
    u, v = e1 / l1, e2 / l2

    def make(a0, a1, b0, b1):
        """Rechteck (a0, a1, b0, b1) im Achsensystem als Polygon in Kartenkoordinaten."""
        aa, bb = np.array([a0, a1, a1, a0]), np.array([b0, b0, b1, b1])
        return shapely.polygons(o + u * aa[:, None] + v * bb[:, None])

    a0, a1, b0, b1 = 0.0, l1, 0.0, l2
    # 0,05 px Spiel; mit Gehrung statt runder Ecken bleibt der Umriss bei wenigen Ecken (schnelleres Abschneiden)
    fit = local_rings(poly.buffer(0.05, join_style="mitre"), o, u, v)
    for _ in range(iters):
        w, h = a1 - a0, b1 - b0
        if _outside(w * h, area_in_box(fit, a0, a1, b0, b1)) <= 0.003 * w * h:
            break
        da, db = w * 0.12, h * 0.12
        # Überstand je Seite (Streifen von 12 % am Rand), bezogen auf die Seitenlänge (sonst würde immer die lange
        # Seite gekürzt)
        score = (_outside(da * h, area_in_box(fit, a0, a0 + da, b0, b1)) / h,
                 _outside(da * h, area_in_box(fit, a1 - da, a1, b0, b1)) / h,
                 _outside(db * w, area_in_box(fit, a0, a1, b0, b0 + db)) / w,
                 _outside(db * w, area_in_box(fit, a0, a1, b1 - db, b1)) / w)
        k = max(range(4), key=score.__getitem__)   # bei Gleichstand die erste Seite
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
    strict = local_rings(poly.buffer(0.15, join_style="mitre"), o, u, v)
    for _ in range(12):
        if _outside((a1 - a0) * (b1 - b0), area_in_box(strict, a0, a1, b0, b1)) == 0.0:   # ganz im Grundstück
            return make(a0, a1, b0, b1) if min(a1 - a0, b1 - b0) >= min_short else None
        da, db = (a1 - a0) * 0.02, (b1 - b0) * 0.02
        a0, a1, b0, b1 = a0 + da, a1 - da, b0 + db, b1 - db
    return None
