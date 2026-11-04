"""Umland: Felder, Wälder, Einzelbäume, Vorstadthäuser, Brücken."""
import math

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from .geo import blob, clean, lines, oriented_rect, roof, unit
from .styles import COLORS, DISTRICT_TYPES


def _river_side(river_line, x, y):
    """Auf welcher Seite der Flussmittellinie liegt der Punkt (+1/-1)? An den Enden gilt die verlängerte Linie."""
    d = river_line.project(Point(x, y))
    d = min(max(d, 0.5), river_line.length - 0.5)
    a, b = river_line.interpolate(d - 0.5), river_line.interpolate(d + 0.5)
    return 1 if (b.x - a.x) * (y - a.y) - (b.y - a.y) * (x - a.x) > 0 else -1


def make_bridges(roads, river, s, river_line=None):
    """Brücken, wo Straßen den Fluss überqueren. Ein Straßenstück im Wasser wird zur Brücke, wenn es an beiden Enden
    auf verschiedenen Seiten des Flusses liegt. Gassen, die am Ufer entlang die Flussfläche nur streifen, bekommen keine
    (sonst läge eine Brücke längs des Ufers, von der nur die Laternen zu sehen wären). Auch ein Stück, das auf dieselbe
    Seite zurückführt, aber tief ins Wasser reicht, ist eine Querung: eine Straße, die eine Flussschleife anschneidet,
    läge sonst ohne Brücke mitten im Fluss."""
    out = []
    if river is None:
        return out
    bank = river.boundary
    for ln, w in roads:
        for seg in lines(ln.intersection(river)):
            if river_line is not None and _river_side(river_line, *seg.coords[0]) == _river_side(river_line, *seg.coords[-1]) \
                    and not (seg.interpolate(0.5, normalized=True).distance(bank) >= 4 * s
                             and seg.distance(Point(ln.coords[0])) > 0.5 * s and seg.distance(Point(ln.coords[-1])) > 0.5 * s):
                continue   # streift das Ufer oder endet im Wasser: keine Querung
            (x0, y0), (x1, y1) = seg.coords[0], seg.coords[-1]
            ux, uy = unit((x1 - x0, y1 - y0))
            e = 10 * s
            out.append((LineString([(x0 - ux * e, y0 - uy * e), (x1 + ux * e, y1 + uy * e)]), w + 6 * s))
    return out


def make_fields(rng, W, s, center, r, dirs, blocked, kinds=(0.45, 0.35, 0.2), prob=0.72):
    """Flur vor der Stadt wie in einer gewachsenen Feldmark: eine unregelmäßige Fläche je Richtung, in Gewanne
    (Feldblöcke) mit eigener Ausrichtung geteilt, jedes Gewann in lange, schmale Ackerstreifen verschiedener
    Breite. Streifen liegen dicht an dicht (nur ein schmaler Rain dazwischen), Gewanne trennen Feldwege und
    Hecken. Felder gibt es nur, wo Platz ist; prob steuert, wie viele Streifen bestellt sind."""
    fields = []
    frame = box(0, 0, W, W).buffer(-4 * s)
    furlong_id = 0
    for v in dirs:
        if v == (0, 0):
            continue
        theta = math.atan2(v[1], v[0])
        u = np.array([math.cos(theta), math.sin(theta)])
        # Flur: unregelmäßige Fläche vor der Stadt in dieser Richtung
        dist = r * 1.15 + 260 * s
        fc = np.array(center) + u * dist
        side = np.array([-u[1], u[0]])
        flur = unary_union([blob(rng, *(fc + side * off * s + u * rng.uniform(-60, 80) * s), rng.uniform(170, 240) * s,
                                 rough=0.4, stretch=(rng.uniform(0.9, 1.3), rng.uniform(0.8, 1.1)))
                            for off in (-170, 0, 170)])           # Flur aus mehreren Lappen: ausgefranster Rand
        flur = flur.difference(blocked).intersection(frame)
        parts = [p for p in clean(flur, 4000 * s * s)]
        if not parts:
            continue
        flur = max(parts, key=lambda p: p.area)
        # Gewanne: Voronoi-Zellen aus wenigen Punkten, getrennt durch Feldwege (Abstand 7 px)
        minx, miny, maxx, maxy = flur.bounds
        pts = []
        for _ in range(60):
            if len(pts) >= max(3, int(flur.area / (14000 * s * s))):
                break
            p = Point(rng.uniform(minx, maxx), rng.uniform(miny, maxy))
            if flur.contains(p) and all(p.distance(q) > 70 * s for q in pts):
                pts.append(p)
        if len(pts) < 2:
            pts = [flur.representative_point()]
            cells = [flur]
        else:
            cells = list(shapely.voronoi_polygons(shapely.MultiPoint(pts), extend_to=flur.buffer(50 * s)).geoms)
        for cell in cells:
            block = cell.intersection(flur).buffer(-3.5 * s, join_style="mitre")
            for gew in clean(block, 1500 * s * s):
                furlong_id += 1
                main = rng.choices(["wheat", "plowed", "meadow"], kinds)[0]   # im Gewann meist dieselbe Frucht
                # Ausrichtung des Gewanns: meist quer oder längs zur Flur, mit etwas Abweichung
                ang = theta + rng.choice([0.0, math.pi / 2]) + rng.uniform(-0.35, 0.35)
                a = np.array([math.cos(ang), math.sin(ang)])     # Streifenrichtung (Pflugrichtung)
                b = np.array([-a[1], a[0]])                      # quer dazu
                c = gew.centroid
                # Projektion von Hand statt np.dot: das liefe über OpenBLAS und rundet je nach Prozessor anders
                bx, by = float(b[0]), float(b[1])
                proj = [(q[0] - c.x) * bx + (q[1] - c.y) * by for q in gew.exterior.coords]
                lo, hi = min(proj), max(proj)
                k = lo
                while k < hi:
                    width = rng.uniform(16, 38) * s           # Breite des Ackerstreifens
                    k2 = min(hi, k + width)
                    p0 = np.array([c.x, c.y]) + b * k
                    p1 = np.array([c.x, c.y]) + b * k2
                    far = 600 * s
                    band = Polygon([p0 - a * far, p0 + a * far, p1 + a * far, p1 - a * far])
                    strip = gew.intersection(band).buffer(-0.9 * s, join_style="mitre")   # schmaler Rain
                    for piece in clean(strip, 250 * s * s):
                        if rng.random() > prob + 0.2:            # mal ein Stück Brache (bleibt Wiese)
                            continue
                        kind = main if rng.random() < 0.7 else rng.choices(["wheat", "plowed", "meadow"], kinds)[0]
                        fields.append({"poly": piece, "kind": kind, "angle": math.degrees(ang),
                                       "furlong": furlong_id, "tone": rng.uniform(0.92, 1.06)})
                    k = k2
        blocked = blocked.union(flur.buffer(10 * s))
    return fields


def tree_color(rng):
    return rng.choice(COLORS["trees"])


def make_forest(rng, W, s, center, r, dirs, blocked, land, spacing=1.0, scale=1.0):
    parts = []
    for v in dirs:
        dist = r + W * 0.33 if v != (0, 0) else 0
        c = (center[0] + v[0] * dist, center[1] + v[1] * dist)
        parts.append(blob(rng, c[0], c[1], W * rng.uniform(0.24, 0.32) * scale, rough=0.45))
    if not parts:
        return Polygon(), []
    forest = unary_union(parts).intersection(land).difference(blocked)
    forest = unary_union(clean(forest, 4000 * s * s))
    trees = []
    if forest.is_empty:
        return forest, trees
    sp = 23 * s * spacing
    minx, miny, maxx, maxy = forest.bounds
    xs, ys = np.meshgrid(np.arange(minx, maxx, sp), np.arange(miny, maxy, sp * 0.87))
    xs = xs + (np.arange(xs.shape[0])[:, None] % 2) * sp / 2
    xs = xs.ravel() + np.array([rng.uniform(-6, 6) * s for _ in range(xs.size)])
    ys = ys.ravel() + np.array([rng.uniform(-6, 6) * s for _ in range(ys.size)])
    inner = forest.buffer(-6 * s)
    mask = shapely.contains_xy(inner, xs, ys)
    for x, y in zip(xs[mask], ys[mask]):
        trees.append((float(x), float(y), rng.uniform(12, 17) * s, tree_color(rng)))
    return forest, trees


def scatter_trees(rng, s, allowed, shape, count=70):
    trees = []
    if allowed.is_empty:
        return trees
    minx, miny, maxx, maxy = allowed.bounds
    for _ in range(count):
        cx, cy = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        for _ in range(rng.randint(1, 9)):
            x, y = cx + rng.gauss(0, 22 * s), cy + rng.gauss(0, 22 * s)
            if shapely.contains_xy(allowed, x, y):
                trees.append((x, y, rng.uniform(9, 15) * s, tree_color(rng)))
    # Büsche entlang der Mauer
    ext = shape.exterior
    k = 0.0
    while k < ext.length:
        k += rng.uniform(25, 70) * s
        p, q = ext.interpolate(k), ext.interpolate(k + 2)
        tx, ty = unit((q.x - p.x, q.y - p.y))
        for side in (-1, 1):
            off = rng.uniform(18, 40) * s
            x, y = p.x - ty * off * side, p.y + tx * off * side
            if not shape.contains(Point(x, y)) and shapely.contains_xy(allowed, x, y) and rng.random() < 0.5:
                trees.append((x, y, rng.uniform(7, 11) * s, tree_color(rng)))
    return trees


def _try_house(rng, s, poly, palette, houses, taken):
    """Setzt ein Haus, wenn der Platz frei ist; liefert die belegte Fläche (taken) zurück."""
    if poly.intersects(taken):
        return taken
    ridges, shade = roof(poly)
    houses.append({"poly": poly, "color": rng.choice(palette), "ridges": ridges, "shade": shade})
    return taken.union(poly.buffer(4 * s))


def suburb_houses(rng, s, roads, blocked):
    houses = []
    palette = DISTRICT_TYPES["bauern"]["palette"] + DISTRICT_TYPES["wohn"]["palette"]
    taken = blocked
    for ln, _ in roads:
        k = 45 * s
        limit = min(ln.length, rng.uniform(220, 380) * s)
        while k < limit:
            p, q = ln.interpolate(k), ln.interpolate(k + 3)
            k += rng.uniform(22, 34) * s
            tx, ty = unit((q.x - p.x, q.y - p.y))
            for side in (-1, 1):
                if rng.random() > 0.45 * (1 - k / limit * 0.6):
                    continue
                L, B = rng.uniform(18, 28) * s, rng.uniform(12, 16) * s
                off = 9 * s + B / 2 + rng.uniform(0, 1.5) * s   # Hausfront direkt an der Landstraße
                cx, cy = p.x - ty * off * side, p.y + tx * off * side
                taken = _try_house(rng, s, oriented_rect(cx, cy, tx, ty, L, B), palette, houses, taken)
    return houses


def hamlet(rng, s, road, blocked):
    """Weiler am Ende einer Landstraße, die sonst kein Ziel hätte: zwei bis drei Höfe an den letzten Metern der
    Straße (beidseits, der Straße folgend)."""
    palette = DISTRICT_TYPES["bauern"]["palette"]
    houses, taken = [], blocked
    for back in (6, 32, 58, 84, 110, 136):
        if len(houses) >= 3:
            break
        k = road.length - back * s
        if k < 3 * s:
            break
        p, q = road.interpolate(k - 3 * s), road.interpolate(k)
        tx, ty = unit((q.x - p.x, q.y - p.y))
        for side in ((1, -1) if rng.random() < 0.5 else (-1, 1)):
            if len(houses) >= 3:
                break
            L, B = rng.uniform(18, 26) * s, rng.uniform(12, 15) * s
            off = 9 * s + B / 2 + 1 * s
            cx, cy = q.x - ty * off * side, q.y + tx * off * side
            taken = _try_house(rng, s, oriented_rect(cx, cy, tx, ty, L, B), palette, houses, taken)
    return houses
