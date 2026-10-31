"""Leuchtturm jeder Küstenstadt: bevorzugt auf einer vorgelagerten Insel, sonst an der Spitze des Hafens. Groß
und weithin sichtbar - die Spielwelt ist dunkel. Ohne Zufall, damit die übrige Karte unverändert bleibt."""
import math

from shapely.geometry import Point
from shapely.ops import nearest_points, polylabel, unary_union

from .city import ship_footprint
from .geo import lines, polys

RADIUS = 22        # Turm samt Sockel (Kartenpixel bei 2000 px): groß und weithin sichtbar


def place(s, W, city, terrain, islands, forts):
    """Liefert {x, y, r, insel, area} oder None (keine Küste, kein Platz)."""
    sea = terrain["sea"]
    if sea is None or sea.is_empty or terrain.get("mountain") or terrain.get("plateau"):
        return None
    r = RADIUS * s
    shape = city["shape"]
    frame = Point(W / 2, W / 2).buffer(W * 0.47).envelope   # nicht am Kartenrand
    taken = unary_union([f["area"] for f in forts]
                        + [f["fort"].buffer(20 * s) for f in forts]
                        + [ship_footprint(sh["x"], sh["y"], sh["len"], sh["wid"], sh["angle"]).buffer(8 * s)
                           for sh in city["ships"]]
                        + [sh["lane"] for sh in city["ships"] if sh.get("lane") is not None]
                        + [sh["depart"] for sh in city["ships"] if sh.get("depart") is not None]
                        + [p.buffer(2 * s) for p in city["piers"]] or [Point(-1e9, -1e9)])
    paved = unary_union(city["paved"]) if city["paved"] else None
    anchor = paved.centroid if paved is not None and not paved.is_empty else shape.centroid
    # 1. vorgelagerte Insel: frei, groß genug, nicht zu weit vor der Stadt
    best = None
    for isl in islands:
        isl = isl.difference(taken)
        for part in polys(isl):
            core = part.buffer(-(r + 4 * s))
            if core.is_empty:
                continue
            c = polylabel(core.buffer(0), 1 * s) if core.geom_type == "Polygon" else core.representative_point()
            d = c.distance(anchor)
            if not frame.contains(c) or d > 650 * s or d < 60 * s:
                continue
            if best is None or d < best[0]:
                best = (d, c)
    if best is not None:
        c = best[1]
        return {"x": c.x, "y": c.y, "r": r, "insel": True, "area": c.buffer(r + 4 * s)}
    # 2. Spitze des Hafens: der Punkt am Kai, der am weitesten aufs Meer hinausragt (auch an der Flussmündung);
    #    ohne Hafen am Stadtufer
    for base in (paved, city["city_land"]):
        if base is None or base.is_empty:
            continue
        hit = _quay_spot(s, base, sea, terrain["water"], taken, frame, anchor, r)
        if hit is not None:
            return {"x": hit.x, "y": hit.y, "r": r, "insel": False, "area": hit.buffer(r + 4 * s)}
    return None


def _quay_spot(s, base, sea, water, taken, frame, anchor, r):
    """Platz am Ufer von base, möglichst weit draußen am Meer: nahe am Meer selbst oder an der Mündung."""
    mouth = sea.buffer(250 * s)
    edge = base.boundary.intersection(water.buffer(3 * s)).intersection(mouth)
    cands = []
    for ln in lines(edge):
        k = 0.0
        while k <= ln.length:
            p = ln.interpolate(k)
            k += 6 * s
            q = nearest_points(sea, p)[0]
            dx, dy = p.x - q.x, p.y - q.y         # vom Wasser weg, ins Land
            n = math.hypot(dx, dy) or 1.0
            if n < 0.5:                            # Punkt liegt genau auf der Wasserlinie: Richtung zur Stadtmitte
                dx, dy = anchor.x - p.x, anchor.y - p.y
                n = math.hypot(dx, dy) or 1.0
            for inland in (r + 2 * s, r + 14 * s):   # direkt an der Kaikante, sonst etwas zurückgesetzt
                c = Point(p.x + dx / n * inland, p.y + dy / n * inland)
                foot = c.buffer(r + 3 * s)
                if not frame.contains(c) or foot.intersects(taken) or not base.buffer(4 * s).contains(foot.buffer(-6 * s)):
                    continue
                seaward = sea.intersection(c.buffer(r * 6)).area - c.distance(sea) * r   # nah und offen zum Meer
                cands.append((seaward, -c.distance(anchor), c))
                break
    if not cands:
        return None
    return max(cands, key=lambda t: (t[0], t[1]))[2]
