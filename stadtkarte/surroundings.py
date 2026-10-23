"""Umland: Felder, Wälder, Einzelbäume, Vorstadthäuser, Brücken."""
import math

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from .geo import blob, clean, lines, roof, unit
from .styles import COLORS, DISTRICT_TYPES


def _river_side(river_line, x, y):
    """Auf welcher Seite der Flussmittellinie liegt der Punkt (+1/-1)? An den Enden gilt die verlängerte Linie."""
    d = river_line.project(Point(x, y))
    d = min(max(d, 0.5), river_line.length - 0.5)
    a, b = river_line.interpolate(d - 0.5), river_line.interpolate(d + 0.5)
    return 1 if (b.x - a.x) * (y - a.y) - (b.y - a.y) * (x - a.x) > 0 else -1


def make_bridges(roads, river, s, river_line=None):
    """Brücken, wo Straßen den Fluss überqueren. Ein Straßenstück im Wasser wird nur dann zur Brücke, wenn es an
    beiden Enden auf verschiedenen Seiten des Flusses liegt: Gassen, die am Ufer entlang die Flussfläche nur
    streifen, bekamen sonst eine Brücke längs des Ufers, von der nur die Laternen zu sehen waren."""
    out = []
    if river is None:
        return out
    for ln, w in roads:
        for seg in lines(ln.intersection(river)):
            if river_line is not None and _river_side(river_line, *seg.coords[0]) == _river_side(river_line, *seg.coords[-1]):
                continue
            (x0, y0), (x1, y1) = seg.coords[0], seg.coords[-1]
            ux, uy = unit((x1 - x0, y1 - y0))
            e = 10 * s
            out.append((LineString([(x0 - ux * e, y0 - uy * e), (x1 + ux * e, y1 + uy * e)]), w + 6 * s))
    return out


def make_fields(rng, W, s, center, r, dirs, blocked, kinds=(0.45, 0.35, 0.2), prob=0.72):
    fields = []
    cx, cy = center
    frame = box(0, 0, W, W)
    for v in dirs:
        if v == (0, 0):
            continue
        theta = math.atan2(v[1], v[0])
        phi = theta + rng.uniform(-0.2, 0.2)
        u = np.array([math.cos(phi), math.sin(phi)])
        w = np.array([-u[1], u[0]])
        cw, ch = 165 * s, 120 * s
        origin = np.array(center) + u * (r * 1.15)
        for i in range(8):
            for j in range(-8, 9):
                if rng.random() > prob:
                    continue
                fl, fh = cw * rng.uniform(0.5, 0.92), ch * rng.uniform(0.5, 0.92)
                tilt = rng.uniform(-0.18, 0.18)
                uu = np.array([math.cos(phi + tilt), math.sin(phi + tilt)])
                ww = np.array([-uu[1], uu[0]])
                base = origin + u * (i * cw + rng.uniform(0, 20) * s) + w * (j * ch + rng.uniform(0, 20) * s)
                corners = [base, base + uu * fl, base + uu * fl + ww * fh, base + ww * fh]
                corners = [c_ + np.array([rng.uniform(-9, 9), rng.uniform(-9, 9)]) * s for c_ in corners]
                poly = Polygon(corners).buffer(0)
                c = poly.centroid
                ang = math.atan2(c.y - cy, c.x - cx)
                diff = abs((ang - theta + math.pi) % (2 * math.pi) - math.pi)
                if diff > 0.6 or poly.intersects(blocked):
                    continue
                clipped = poly.intersection(frame)
                if clipped.area < poly.area * 0.5:
                    continue
                kind = rng.choices(["wheat", "plowed", "meadow"], kinds)[0]
                fields.append({"poly": clipped, "kind": kind, "angle": math.degrees(phi + tilt)})
                blocked = blocked.union(poly.buffer(10 * s))
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


def scatter_trees(rng, W, s, allowed, shape, count=70):
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
                corners = [(cx + tx * a * L / 2 - ty * b * B / 2, cy + ty * a * L / 2 + tx * b * B / 2)
                           for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
                poly = Polygon(corners)
                if poly.intersects(taken):
                    continue
                taken = taken.union(poly.buffer(4 * s))
                ridges, shade = roof(poly)
                houses.append({"poly": poly, "color": rng.choice(palette), "ridges": ridges, "shade": shade})
    return houses
