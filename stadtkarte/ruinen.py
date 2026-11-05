"""Ruinenviertel: verfallene Häuser.

Ein Ruinenviertel (typ: ruinen) wird zuerst wie ein Wohnviertel bebaut. Danach (plan) verfällt der Anteil ruinenanteil
(Prozent) seiner Häuser; die übrigen bleiben bewohnt und sehen aus wie im Wohnviertel. Eine Ruine ist
  - ein Mauerrest ("mauer"): nur Stücke der Außenmauern stehen noch, dazwischen Lücken; innen liegen Schutt und Balken,
    Gras und Moos wachsen darüber;
  - ein Haus mit eingestürztem Dach ("dach"): ein Dachrest hält noch, seine Bruchkante ist ausgefranst und zeigt die
    Sparren; der Rest des Hauses liegt offen. Auch hier fehlen Stücke der Mauer.
Besondere Orte (Gasthaus, Tempel ...) und Häuserblöcke mit besonderem Ort bleiben unversehrt. In der Großstadt zählt
jedes Haus einer Häuserzeile einzeln.

Das Modell hält fest, was noch steht: b["ruin"] bzw. bei Häuserzeilen b["ruins"][Nr. des Hauses] mit art, rest (Dachrest),
walls (Mauerstücke) und seed. Schutt, Balken und Bewuchs entstehen beim Zeichnen aus dieser Zahl.

Der Verfall zieht keine Zufallszahlen aus dem Generator der Stadt, sondern nutzt einen eigenen aus dem Seed: Ein anderer
Anteil ändert nur, welche Häuser Ruinen sind, nicht das übrige Stadtbild, und Karten ohne Ruinenviertel bleiben unverändert.
Die Ruinen häufen sich zu Gruppen (Simplex-Rauschen mit etwas Zufall), statt gleichmäßig gestreut zu liegen."""
import math
import random

import numpy as np
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import substring, unary_union

from .geo import axes, lines, polys, vlen
from .roofs import _f, _ld, _pd, shade
from .simplex import Simplex2

DACH, MAUER = "dach", "mauer"
CLUSTER = 240          # Größe der Ruinengruppen (px bei 2000 px Bildgröße; Rauschen mit Gruppen etwa einen halben Wert breit)
CLUSTER_WEIGHT = 0.7   # Zufall gegenüber den Gruppen: größer = verstreuter
SHARE_DACH = 0.45      # Anteil der Ruinen mit Dachrest (die übrigen sind Mauerreste)

FLOOR = "#6b6050"                                     # festgetretener Schutt statt Fußboden
STONES = ("#9a9386", "#857d70", "#a79f90", "#8c8478")
STONE, STONE_DARK, BEAM = "#9a9386", "#6f6a5f", "#4a3826"
GREEN = ("#5f7a3a", "#6f8a45", "#7d8f4e", "#4f6b35")


# ------------------------------------------------------------------------------------------------ Modell
def plan(buildings, districts, seed, s):
    """Lässt in jedem Ruinenviertel den Anteil ruinenanteil der Häuser verfallen (markiert sie mit b["ruin"] bzw.
    b["ruins"]). Genau gerundet: bei 60 % von 20 Häusern sind es 12. Der Generator entfernt später noch einzelne Häuser
    (Festung, Leuchtturm, Brücken, Landstraßen); der Anteil der fertigen Karte weicht deshalb etwas ab. Ohne Ruinenviertel
    geschieht nichts."""
    if not any(d.get("typ") == "ruinen" for d in districts):
        return
    rng = random.Random(f"ruinen-{seed}")
    noise = Simplex2(int(seed) % 2 ** 32 + 4271)
    for di, d in enumerate(districts):
        if d.get("typ") != "ruinen" or d.get("outside"):
            continue
        units = []   # (Gebäude, Nr. des Hauses in der Häuserzeile oder None, Grundriss)
        for b in buildings:
            if b.get("district") != di or b.get("removed") or b.get("landmark"):
                continue
            if b.get("form") == "block":
                units += [(b, k, seg[0]) for k, seg in enumerate(b["segments"])]
            else:
                units.append((b, None, b["poly"]))
        count = round(d.get("ruinenanteil", 0) / 100 * len(units))
        if not count:
            continue
        xy = np.array([(u[2].centroid.x, u[2].centroid.y) for u in units])
        cluster = noise.noise(xy[:, 0] / (CLUSTER * s), xy[:, 1] / (CLUSTER * s))
        score = np.array(cluster) + CLUSTER_WEIGHT * np.array([rng.random() for _ in units])
        for i in sorted(np.argsort(-score, kind="stable")[:count]):
            b, k, poly = units[i]
            info = ruin_info(poly, rng, s)
            if k is None:
                b["ruin"] = info
            else:
                b.setdefault("ruins", {})[k] = info


def ruin_info(poly, rng, s):
    """Was von einem Haus steht: Art, Dachrest (oder None) und stehende Mauerstücke."""
    art = DACH if rng.random() < SHARE_DACH else MAUER
    rest = _roof_rest(poly, rng, s) if art == DACH else None
    if rest is None:
        art = MAUER
    return {"art": art, "rest": rest, "walls": _walls(poly, rng, s, art), "seed": rng.getrandbits(31)}


def _roof_rest(poly, rng, s):
    """Der Teil des Daches, der noch hält: eine Seite einer ausgefransten Bruchlinie quer durchs Haus, 25 bis 70 % der
    Fläche (None, wenn der Grundriss dafür zu klein oder zu schmal ist)."""
    c = poly.centroid
    reach = math.hypot(poly.bounds[2] - poly.bounds[0], poly.bounds[3] - poly.bounds[1])
    for _ in range(8):
        a = rng.uniform(0, math.pi)
        d, n = (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))
        off = rng.uniform(-0.2, 0.2) * math.sqrt(poly.area)
        pts, t = [], -reach
        while t <= reach:
            j = off + rng.uniform(-1.3, 1.3) * s   # ausgefranst
            pts.append((c.x + d[0] * t + n[0] * j, c.y + d[1] * t + n[1] * j))
            t += rng.uniform(1.6, 3.2) * s
        far = [(x + n[0] * 2 * reach, y + n[1] * 2 * reach) for x, y in (pts[-1], pts[0])]
        part = poly.intersection(Polygon(pts + far).buffer(0))
        pieces = polys(part)
        if not pieces:
            continue
        rest = max(pieces, key=lambda p: p.area)
        if 0.25 <= rest.area / poly.area <= 0.7 and rest.area > 8 * s * s:
            return rest
    return None


def _walls(poly, rng, s, art):
    """Stehende Mauerstücke entlang des Grundrisses: abwechselnd Stücke und Lücken zufälliger Länge. Bei Mauerresten
    fehlt mehr als bei Häusern mit Dachrest."""
    ring = LineString(poly.exterior.coords)
    length = ring.length
    stand = (5, 14) if art == MAUER else (8, 20)
    gap = (2, 8) if art == MAUER else (1.5, 4)
    t = rng.uniform(0, length)
    standing = rng.random() < 0.6
    pieces, done = [], 0.0
    while done < length:
        run = rng.uniform(*(stand if standing else gap)) * s
        run = min(run, length - done)
        if standing:
            a, b = (t + done) % length, (t + done + run) % length
            if a <= b:
                pieces.append(substring(ring, a, b))
            else:   # das Stück läuft über den Anfang des Rings
                pieces += [substring(ring, a, length), substring(ring, 0, b)]
        done += run
        standing = not standing
    pieces = [p for p in pieces if p.length > 0.5 * s]
    if not pieces:
        pieces = [substring(ring, 0, min(length, 6 * s))]
    return MultiLineString(pieces)


def standing_roofs(b):
    """Was eines Gebäudes noch Schatten wirft: das ganze Dach (bei normalen Häusern der Grundriss selbst), bei Ruinen der
    Dachrest, bei Mauerresten nichts (None); bei Häuserzeilen mit Ruinen die unversehrten Häuser samt Dachresten."""
    if b.get("ruin"):
        return b["ruin"]["rest"]
    ruins = b.get("ruins")
    if not ruins:
        return b["poly"]
    keep = [seg for k, (seg, _, _) in enumerate(b["segments"]) if k not in ruins]
    keep += [r["rest"] for r in ruins.values() if r["rest"] is not None]
    return unary_union(keep) if keep else None


# ------------------------------------------------------------------------------------------------ Zeichnen
def _inside(poly, rng, margin=0.0):
    """Zufälliger Punkt im Grundriss (mit Abstand margin zum Rand), sonst sein Mittelpunkt."""
    area = poly.buffer(-margin) if margin else poly
    area = area if not area.is_empty else poly
    x0, y0, x1, y1 = area.bounds
    for _ in range(20):
        p = Point(rng.uniform(x0, x1), rng.uniform(y0, y1))
        if area.contains(p):
            return p
    return area.representative_point()


def _stone(rng, x, y, r):
    n = rng.randint(4, 6)
    a0 = rng.uniform(0, 2 * math.pi)
    pts = []
    for i in range(n):
        a = a0 + 2 * math.pi * i / n + rng.uniform(-0.25, 0.25)
        rad = r * rng.uniform(0.65, 1.15)
        pts.append(f"{x + math.cos(a) * rad:.1f},{y + math.sin(a) * rad * 0.8:.1f}")
    return "M" + "L".join(pts) + "Z"


def _rubble(poly, rng, s, out):
    """Schutthaufen aus kleinen Steinen."""
    for _ in range(max(2, int(poly.area / (70 * s * s)))):
        c = _inside(poly, rng, 1.2 * s)
        stones = []
        for _ in range(rng.randint(3, 5)):
            x, y = c.x + rng.uniform(-1.6, 1.6) * s, c.y + rng.uniform(-1.6, 1.6) * s
            stones.append(f'<path d="{_stone(rng, x, y, rng.uniform(0.5, 1.2) * s)}" fill="{rng.choice(STONES)}"/>')
        out.append(f'<g stroke="#2b2620" stroke-opacity="0.55" stroke-width="{_f(0.4 * s)}">{"".join(stones)}</g>')


def _growth(poly, rng, s, out):
    """Gras- und Moosflecken auf dem Boden (nur innerhalb des Grundrisses)."""
    for _ in range(max(2, int(poly.area / (90 * s * s)))):
        c = _inside(poly, rng)
        patch = c.buffer(rng.uniform(1.8, 3.6) * s, quad_segs=3).intersection(poly)
        if not patch.is_empty:
            out.append(f'<path d="{_pd(patch)}" fill="{rng.choice(GREEN)}" fill-opacity="{rng.uniform(0.45, 0.75):.2f}"/>')
    for _ in range(max(1, int(poly.area / (200 * s * s)))):   # dunkle Erde dazwischen
        c = _inside(poly, rng)
        patch = c.buffer(rng.uniform(1.2, 2.6) * s, quad_segs=3).intersection(poly)
        if not patch.is_empty:
            out.append(f'<path d="{_pd(patch)}" fill="#3a2f22" fill-opacity="0.28"/>')


def _beams(poly, rng, s, out, count):
    """Herabgefallene Balken."""
    area = poly.buffer(-0.6 * s)
    if area.is_empty:
        return
    segs = []
    for _ in range(count):
        c = _inside(poly, rng, 1.0 * s)
        a, ln = rng.uniform(0, math.pi), rng.uniform(3, 7) * s
        dx, dy = math.cos(a) * ln / 2, math.sin(a) * ln / 2
        part = LineString([(c.x - dx, c.y - dy), (c.x + dx, c.y + dy)]).intersection(area)
        if not part.is_empty:
            segs.append((_ld(part), rng.uniform(0.6, 0.9)))
    for d, w in segs:
        out.append(f'<path d="{d}" fill="none" stroke="{BEAM}" stroke-width="{_f(w * s)}" stroke-linecap="round"/>')


def _roof_rest_svg(poly, info, color, shade_poly, ridges, s, rng, outline, out):
    """Der noch stehende Dachrest: verwitterte Ziegelreihen, Moos, dunkle Bruchkante mit Sparren, Dachscherben davor."""
    rest = info["rest"]
    base = shade(color, 0.8)
    out.append(f'<path d="{_pd(rest)}" fill="{base}"/>')
    if shade_poly is not None:
        sh = shade_poly.intersection(rest)
        if not sh.is_empty:
            out.append(f'<path d="{_pd(sh)}" fill="#000" fill-opacity="0.22"/>')
    ax = axes(poly)
    if ax is not None and vlen(ax[2]) > 1e-6:   # Ziegelreihen parallel zur Traufe
        o, e1, e2 = ax
        u, v = e1 / vlen(e1), e2 / vlen(e2)
        rows, t = [], 1.2 * s
        while t < vlen(e2):
            row = LineString([tuple(o + v * t - u * s), tuple(o + v * t + e1 + u * s)]).intersection(rest)
            if not row.is_empty:
                rows.append(_ld(row))
            t += 2.4 * s
        out.append(f'<path d="{"".join(rows)}" fill="none" stroke="{shade(base, 0.65)}" stroke-opacity="0.55" '
                   f'stroke-width="{_f(0.5 * s)}"/>')
    for r in ridges or []:
        part = r.intersection(rest)
        if not part.is_empty:
            out.append(f'<path d="{_ld(part)}" fill="none" stroke="#000" stroke-opacity="0.5" stroke-width="{_f(0.9 * s)}"/>')
    for _ in range(rng.randint(1, 2)):   # Moos auf dem Dach
        patch = _inside(rest, rng).buffer(rng.uniform(1.4, 2.8) * s, quad_segs=3).intersection(rest)
        if not patch.is_empty:
            out.append(f'<path d="{_pd(patch)}" fill="{rng.choice(GREEN)}" fill-opacity="0.5"/>')
    out.append(f'<path d="{_pd(rest)}" fill="none" stroke="{outline}" stroke-width="{_f(1.1 * s)}"/>')
    # Bruchkante: der Teil des Randes im Inneren des Hauses; davor die Sparren, die in die offene Hälfte ragen
    inside = poly.exterior.buffer(0.5 * s)
    rafters, tiles = [], []
    for ln in lines(rest.exterior.difference(inside)):
        if ln.length < 2 * s:
            continue
        k = rng.uniform(0.5, 1.5) * s
        while k < ln.length:
            p, q = ln.interpolate(k), ln.interpolate(min(ln.length, k + 0.5 * s))
            tx, ty = q.x - p.x, q.y - p.y
            n = math.hypot(tx, ty) or 1
            nx, ny = -ty / n, tx / n
            if rest.contains(Point(p.x + nx * 0.8 * s, p.y + ny * 0.8 * s)):   # weg vom Dachrest
                nx, ny = -nx, -ny
            if rng.random() < 0.8:
                a = math.atan2(ny, nx) + rng.uniform(-0.35, 0.35)
                ln_ = rng.uniform(1.4, 3.4) * s
                part = LineString([(p.x, p.y), (p.x + math.cos(a) * ln_, p.y + math.sin(a) * ln_)]).intersection(poly)
                if not part.is_empty:
                    rafters.append(_ld(part))
            k += rng.uniform(2.0, 3.2) * s
    spots = polys(poly.difference(rest.buffer(0.5 * s)).intersection(rest.buffer(5 * s)))
    for _ in range(rng.randint(4, 8) if spots else 0):   # abgerutschte Dachscherben
        c = _inside(max(spots, key=lambda p: p.area), rng)
        a = rng.uniform(0, 360)
        tiles.append(f'<rect x="{_f(-0.65 * s)}" y="{_f(-0.4 * s)}" width="{_f(1.3 * s)}" height="{_f(0.8 * s)}" '
                     f'transform="translate({_f(c.x)},{_f(c.y)}) rotate({_f(a)})"/>')
    if rafters:
        out.append(f'<path d="{"".join(rafters)}" fill="none" stroke="{BEAM}" stroke-width="{_f(0.75 * s)}" '
                   f'stroke-linecap="round"/>')
    if tiles:
        out.append(f'<g fill="{base}" stroke="#2a1f16" stroke-opacity="0.6" stroke-width="{_f(0.3 * s)}">{"".join(tiles)}</g>')


def ruin_svg(poly, info, color, shade_poly, ridges, s, outline):
    """Eine Ruine: Boden mit Gras und Schutt, Balken, stehende Mauerstücke (innen ein dunkler Fugenstrich), bei Häusern mit
    Dachrest zuoberst das noch hängende Dach. color: Dachfarbe des Hauses, shade_poly und ridges: Schatten und First seines
    heilen Daches (oder None)."""
    rng = random.Random(info["seed"])
    out = [f'<path d="{_pd(poly)}" fill="{FLOOR}"/>']
    _growth(poly, rng, s, out)
    # Grundmauern: wo die Mauer ganz fehlt, bleibt die gestrichelte Linie des Fundaments
    out.append(f'<path d="{_ld(poly.exterior)}" fill="none" stroke="{STONE_DARK}" stroke-opacity="0.8" '
               f'stroke-width="{_f(0.6 * s)}" stroke-dasharray="{_f(1.2 * s)} {_f(1.0 * s)}"/>')
    _rubble(poly, rng, s, out)
    _beams(poly, rng, s, out, rng.randint(1, 3) if info["art"] == MAUER else rng.randint(3, 5))
    wd = _ld(info["walls"])
    out.append(f'<path d="{wd}" fill="none" stroke="{outline}" stroke-width="{_f(2.7 * s)}" stroke-linejoin="round"/>'
               f'<path d="{wd}" fill="none" stroke="{STONE}" stroke-width="{_f(1.7 * s)}" stroke-linejoin="round"/>'
               f'<path d="{wd}" fill="none" stroke="{STONE_DARK}" stroke-opacity="0.8" stroke-width="{_f(0.35 * s)}" '
               f'stroke-dasharray="{_f(1.3 * s)} {_f(1.1 * s)}"/>')
    if info["rest"] is not None:
        _roof_rest_svg(poly, info, color, shade_poly, ridges, s, rng, outline, out)
    return "".join(out)
