"""Festung/Bastion: sternförmige Wehranlage auf einer Insel, einer Landzunge oder an Land."""
import math

import numpy as np
import shapely
from shapely.affinity import rotate
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points, unary_union

from .city import ship_footprint
from .config import place_info
from .geo import blob, lines, roof, unit
from .styles import LANDMARK_COLORS


def star_fort(cx, cy, a, ang):
    """Quadratische Festung mit rautenförmigen Bastionen an den Ecken."""
    h = a / 2
    corners = [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]
    b = 0.36 * a
    parts = [Polygon(corners)] + [Polygon([(x, y - b), (x + b, y), (x, y + b), (x - b, y)]) for x, y in corners]
    fort = rotate(unary_union(parts), ang, origin=(cx, cy))
    towers = [rotate(Point(x, y), ang, origin=(cx, cy)) for x, y in corners]
    return fort, [(p.x, p.y, ang) for p in towers]


def _rect(c, u, v, lu, lv):
    c, u, v = np.array(c), np.array(u), np.array(v)
    return Polygon([c - u * lu - v * lv, c + u * lu - v * lv, c + u * lu + v * lv, c - u * lu + v * lv])


def _inner_buildings(cx, cy, a, ang, s):
    """Bergfried in der Mitte, zwei Mannschaftshäuser an den Seiten."""
    t = math.radians(ang)
    u, v = (math.cos(t), math.sin(t)), (-math.sin(t), math.cos(t))
    out = [(_rect((cx, cy), u, v, a * 0.17, a * 0.17), LANDMARK_COLORS["festung"])]
    for side in (-1, 1):
        c = (cx + v[0] * side * a * 0.33, cy + v[1] * side * a * 0.33)
        out.append((_rect(c, u, v, a * 0.26, a * 0.085), "#8c6a4a"))
    blds = []
    for poly, color in out:
        ridges, shade = roof(poly)
        blds.append({"poly": poly, "color": color, "ridges": ridges, "shade": shade, "district": -1})
    return blds


def _sea_site(s, sea, river, city_land, anchor, islands, avoid=None):
    """Sucht einen Inselplatz 120-230 px vor der Stadt, möglichst nah am Anker (Hafen)."""
    minx, miny, maxx, maxy = sea.bounds
    inner = sea.buffer(-14 * s)
    best, bd = None, 1e18
    for x in np.arange(minx, maxx, 18 * s):
        for y in np.arange(miny, maxy, 18 * s):
            p = Point(x, y)
            d = city_land.distance(p)
            if not 120 * s < d < 230 * s:
                continue
            disk = p.buffer(80 * s)
            if not inner.contains(disk):
                continue
            if river is not None and disk.buffer(25 * s).intersects(river.difference(sea.buffer(-1))):
                continue
            if any(disk.buffer(30 * s).intersects(i) for i in islands):
                continue
            if avoid is not None and disk.buffer(20 * s).intersects(avoid):
                continue
            score = p.distance(anchor)
            if score < bd:
                best, bd = p, score
    return best


def _inner_shore(s, city, water):
    """Uferlinie der Stadt innerhalb der Mauer (mit Abstand zur Mauer selbst)."""
    shore = city["city_land"].boundary.intersection(water.buffer(2 * s))
    walls = unary_union(city["wall"]) if city["wall"] else None
    if walls is not None:
        shore = shore.difference(walls.buffer(40 * s))
    return [ln for ln in lines(shore) if ln.length > 10 * s]


def _slip_zone(s, city):
    """Werft mit dem Schiff im Helling und seiner Ausfahrt: dort landet keine Festungsbrücke, und dort liegt weder
    Festungsinsel noch Landzunge (das Schiff muss hinausfahren können)."""
    return unary_union([ship_footprint(sh["x"], sh["y"], sh["len"], sh["wid"], sh["angle"]).union(sh["hall"]).union(sh["lane"])
                        for sh in city["ships"] if sh.get("slip")]).buffer(30 * s)   # mit Widerlager und Brückenkopf


def _landing_inside(s, city, water, p, avoid=None):
    """Uferpunkt innerhalb der Mauer, den eine gerade Brücke von p aus erreicht, ohne Mauer oder Land zu kreuzen."""
    walls = unary_union(city["wall"]).buffer(6 * s) if city["wall"] else Polygon()
    slips = _slip_zone(s, city)   # keine Brücke über den Bug und kein Brückenkopf neben der Werft
    best = None
    for ln in _inner_shore(s, city, water):
        k = 0.0
        while k <= ln.length:
            q = ln.interpolate(k)
            k += 6 * s
            if avoid is not None and avoid.buffer(30 * s).contains(q):
                continue
            seg = LineString([(p.x, p.y), (q.x, q.y)])
            if seg.intersects(walls) or seg.intersection(city["city_land"]).length > 3 * s or seg.intersects(slips):
                continue
            if best is None or seg.length < best[0]:
                best = (seg.length, q)
    return best[1] if best else None


def _connect_inside(s, city, start, direction=None, width=10):
    """Weg vom Zugang (Brückenkopf, Festungstor) zur nächsten Straße in der Stadt; Häuser im Weg werden geräumt.
    Mit direction läuft der Weg erst ein Stück geradeaus weiter (z.B. in Brückenrichtung) und biegt dann ab."""
    net = unary_union(city["streets"] + city["plazas"] + city["paved"])
    if net.is_empty:
        return
    pts = [(start.x, start.y)]
    if direction is not None:
        ahead = Point(start.x + direction[0] * 22 * s, start.y + direction[1] * 22 * s)
        if city["city_land"].contains(ahead) and not net.contains(Point(start.x, start.y)):
            pts.append((ahead.x, ahead.y))
    target = nearest_points(net, Point(pts[-1]))[0]
    if target.distance(Point(pts[-1])) >= 1:
        pts.append((target.x, target.y))
    if len(pts) < 2:
        return
    path = LineString(pts).buffer(width / 2 * s).intersection(city["city_land"])
    city["buildings"] = [b for b in city["buildings"] if not b["poly"].intersects(path.buffer(1 * s))]
    city["yard_trees"] = [t for t in city["yard_trees"] if not path.buffer(t[2]).contains(Point(t[0], t[1]))]
    city["wells"] = [w for w in city["wells"] if not path.buffer(w[2]).contains(Point(w[0], w[1]))]
    city["streets"].append(path)


def _citadel_site(s, W, city, water, a):
    """Zitadelle in der Stadtmauer: Platz auf der Mauerlinie, fern von Toren und Wasser.
    Liefert (Mittelpunkt, Winkel, Punkt auf der Mauer, Richtung nach innen) oder None."""
    shape = city["shape"]
    gates = [Point(x, y) for x, y, _ in city["gates"]]
    best = None
    for ln in city["wall"]:
        k = 30 * s
        while k < ln.length - 30 * s:
            q, q2 = ln.interpolate(k), ln.interpolate(k + 3)
            k += 15 * s
            if any(q.distance(g) < 110 * s for g in gates) or q.distance(water) < 60 * s:
                continue
            tx, ty = unit((q2.x - q.x, q2.y - q.y))
            nx, ny = -ty, tx
            if not shape.contains(Point(q.x + nx * 8 * s, q.y + ny * 8 * s)):
                nx, ny = -nx, -ny                       # (nx, ny) zeigt in die Stadt
            c = Point(q.x - nx * a * 0.3, q.y - ny * a * 0.3)
            if not (a < c.x < W - a and a < c.y < W - a):
                continue
            score = min([q.distance(g) for g in gates] or [0])   # möglichst weit weg von den Toren
            if best is None or score > best[0]:
                best = (score, c, math.degrees(math.atan2(ty, tx)), q, (nx, ny))
    return best[1:] if best else None


def _plateau_lift(s, road, level, u, oben):
    """Aufzug an der Plateaukante, wo der Festungsweg die Felswand kreuzt: Schacht quer über die Wand (a auf der
    Stufe der Festung, b auf der Seite der Stadt), oben das Windenhaus, unten eine Plattform."""
    ux, uy = u
    hits = [g for g in shapely.get_parts(road.intersection(level.boundary)) if g.geom_type == "Point"]
    if not hits:
        return None
    e = max(hits, key=lambda q: road.project(q))          # letzter Kantenpunkt vor der Stadt
    a = (e.x - ux * 40 * s, e.y - uy * 40 * s)          # hinter dem Fuß bzw. der Oberkante der Felswand (30 px)
    b = (e.x + ux * 4 * s, e.y + uy * 4 * s)
    top, bot = (b, a) if oben else (a, b)
    out = (1 if oben else -1)                            # vom Schacht weg auf die obere Stufe
    hw, hl = 9 * s, 7 * s                                # Windenhaus: halbe Breite quer, halbe Tiefe längs
    hc = (top[0] + ux * out * hl, top[1] + uy * out * hl)
    px, py = -uy, ux

    def rect(c, along, across):
        return Polygon([(c[0] + ux * i * along + px * j * across, c[1] + uy * i * along + py * j * across)
                        for i, j in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    shaft = LineString([a, b]).buffer(6 * s, cap_style="flat")
    house = rect(hc, hl, hw)
    pc = (bot[0] - ux * out * 5 * s, bot[1] - uy * out * 5 * s)
    landing = rect(pc, 5 * s, 8 * s)
    # Endpunkte der Wege: an der Hausseite hinter dem Windenhaus, unten hinter der Plattform
    a_end, b_end = ((pc[0] - ux * out * 5 * s, pc[1] - uy * out * 5 * s), (hc[0] + ux * out * hl, hc[1] + uy * out * hl))
    if not oben:
        a_end, b_end = b_end, a_end
    return {"a": a_end, "b": b_end, "top": top, "bot": bot, "u": u, "shaft": shaft, "house": house, "landing": landing,
            "area": unary_union([shaft, house, landing])}


def build_fortress(rng, W, s, spec, terrain, city, ext_roads, islands):
    """Liefert dict mit Festungsgeometrie, Gebäuden, Türmen, Brücke/Straße und Landergänzung."""
    sea, river, water = terrain["sea"], terrain["river"], terrain["water"]
    shape, city_land = city["shape"], city["city_land"]
    paved = unary_union(city["paved"]) if city["paved"] else None
    anchor = paved.representative_point() if paved is not None and not paved.is_empty else city_land.centroid
    lage = str(spec.get("lage", "insel")).lower()
    a = 58 * s
    res = {"land_add": None, "bridges": [], "roads": []}
    walled = bool(city["wall"])          # mit Mauer liegt der Zugang immer innerhalb der Mauer
    gates = [Point(x, y) for x, y, _ in city["gates"]]

    def road_to_gate(p):
        if not gates:
            return
        g = min(gates, key=lambda q: q.distance(p))
        mid = ((p.x + g.x) / 2, (p.y + g.y) / 2)
        res["roads"].append((LineString([(p.x, p.y), mid, (g.x, g.y)]), 12 * s))

    if (terrain.get("mountain") or terrain.get("plateau")) and sea is not None and lage != "land":
        # Gebirge: Festung auf einem Felssporn, Bergpfad hinunter zur Stadt (Hochplateau: auf der anderen Stufe)
        p = _sea_site(s, sea, river, city_land, anchor, islands, _slip_zone(s, city))
        if p is None:
            print("Hinweis: Kein Felssporn für die Festung gefunden - sie wird an Land gebaut.")
            lage = "land"
        else:
            center = p
            shore = nearest_points(city_land, p)[0]
            ux, uy = unit((shore.x - p.x, shore.y - p.y))
            ang = math.degrees(math.atan2(uy, ux))
            road = LineString([(p.x, p.y), (shore.x + ux * 15 * s, shore.y + uy * 15 * s)])
            lift = _plateau_lift(s, road, sea, (ux, uy), terrain.get("plateau_oben")) if terrain.get("plateau") else None
            if lift is None:
                res["roads"].append((road, 10 * s))
            else:   # Hochplateau: der Weg endet an beiden Enden des Aufzugs, der die Felswand überwindet
                res["lift"] = lift
                for a_, b_ in (((p.x, p.y), lift["a"]), (lift["b"], road.coords[-1])):
                    if Point(a_).distance(Point(b_)) > 2 * s:
                        res["roads"].append((LineString([a_, b_]), 10 * s))
            lage = "fels"
    if sea is not None and lage not in ("land", "fels"):
        if lage == "landzunge":
            # Küstenpunkt außerhalb der Mauer, dann Landzunge ins Meer (intern liegt das Meer immer im Norden)
            if walled:   # Landzunge wächst aus dem Ufer innerhalb der Mauer
                cands = [ln.interpolate(k) for ln in _inner_shore(s, city, sea)   # nur Meeresufer, nicht Flussufer
                         for k in np.arange(0, ln.length, 8 * s)]
                cands = [p for p in cands if (river is None or p.distance(river) > 100 * s)
                         and (paved is None or p.distance(paved) > 20 * s)]
            else:        # ohne Mauer: Küstenpunkt außerhalb der Stadt
                coast = [Point(c) for c in sea.exterior.coords if 0 < c[0] < W and c[1] > 0]
                cands = [p for p in coast if 90 * s < shape.distance(p) < 260 * s
                         and (river is None or p.distance(river) > 120 * s)]
            slips = _slip_zone(s, city)        # Landzunge nicht vor die Werft (Ausfahrt bleibt frei)
            cands = [p for p in cands if not unary_union([LineString([(p.x, p.y), (p.x, p.y - 90 * s)]).buffer(32 * s),
                                                          Point(p.x, p.y - 90 * s).buffer(72 * s)]).intersects(slips)]
            if cands:
                q = min(cands, key=lambda p: p.distance(anchor))
                tip = Point(q.x, q.y - 90 * s)
                tongue = unary_union([LineString([(q.x, q.y + 10 * s), (tip.x, tip.y)]).buffer(30 * s),
                                      blob(rng, tip.x, tip.y, 62 * s, rough=0.2)]).difference(
                    city["city_land"].buffer(2 * s) if walled else Polygon())
                res["land_add"] = tongue
                center = tip
                ang = rng.uniform(-15, 15)
                res["roads"].append((LineString([(tip.x, tip.y), (q.x, q.y)]), 12 * s))
                if walled:
                    _connect_inside(s, city, q)
                else:
                    road_to_gate(Point(q.x, q.y + 20 * s))
            else:
                lage = "insel"
        if lage != "landzunge":
            p = _sea_site(s, sea, river, city_land, anchor, islands, _slip_zone(s, city))
            if p is None:
                print("Hinweis: Kein Platz für eine Inselfestung gefunden - sie wird an Land gebaut.")
                lage = "land"
            else:
                center = p
                res["land_add"] = blob(rng, p.x, p.y, 76 * s, rough=0.22).union(p.buffer(66 * s))
                shore = _landing_inside(s, city, water, p) if walled else None
                if shore is None:
                    if walled:
                        print("Hinweis: Kein Brückenkopf innerhalb der Mauer erreichbar - Brücke zum nächsten Ufer.")
                    target = paved if paved is not None and not paved.is_empty else city_land
                    free = target.difference(_slip_zone(s, city))
                    shore = nearest_points(free if not free.is_empty else target, p)[0]
                ux, uy = unit((shore.x - p.x, shore.y - p.y))
                ang = math.degrees(math.atan2(uy, ux))
                # der berechnete Uferpunkt kann vor der gezeichneten (gewellten) Küste im Wasser liegen:
                # bis zum ersten Land hinter dem Uferpunkt weitergehen
                ray = LineString([(p.x, p.y), (shore.x + ux * 40 * s, shore.y + uy * 40 * s)])
                wet = [g for g in lines(ray.intersection(water).difference(res["land_add"])) if g.length > 1]
                if wet:
                    far = max((Point(c) for g in wet for c in (g.coords[0], g.coords[-1])), key=p.distance)
                    if far.distance(p) > shore.distance(p):
                        shore = far
                # Brücke nur über das Wasser zwischen Inselufer und Stadtufer, auf der Insel eine Straße zum Tor
                line = LineString([(p.x, p.y), (shore.x, shore.y)])
                off = [g for g in lines(line.difference(res["land_add"])) if g.length > 2 * s]
                edge = Point(off[0].coords[0]) if off else p
                e = 6 * s   # Widerlager: Brückenenden liegen ein Stück auf dem Ufer
                res["bridges"].append((LineString([(edge.x - ux * e, edge.y - uy * e),
                                                   (shore.x + ux * 2 * e, shore.y + uy * 2 * e)]), 15 * s))
                # Brückenkopf: füllt kleine Buchten der gewellten Küste neben Brückenende und Weg auf; nicht auf dem
                # gepflasterten Hafen (dort gibt es keine Buchten, der Brückenkopf wäre ein Grasbuckel am Pflaster)
                if walled and (paved is None or paved.distance(shore) > 10 * s):
                    head = LineString([(shore.x - ux * 2 * s, shore.y - uy * 2 * s),
                                       (shore.x + ux * 45 * s, shore.y + uy * 45 * s)])
                    res["land_add"] = res["land_add"].union(head.buffer(14 * s))   # runde Enden, keine eckigen Schultern
                if edge.distance(p) > a:
                    res["roads"].append((LineString([(p.x, p.y), (edge.x - ux * e * 0.5, edge.y - uy * e * 0.5)]), 12 * s))
                if walled:
                    # Weg so breit wie die Brücke, beginnt unter dem Brückenende: kein Breitensprung am Übergang
                    _connect_inside(s, city, Point(shore.x + ux * 2 * s, shore.y + uy * 2 * s), (ux, uy), width=15)
    if (sea is None or lage == "land") and walled:
        # Zitadelle: in die Stadtmauer eingebaut, Tor zur Stadt hin
        site = _citadel_site(s, W, city, water, a)
        if site is not None:
            center, ang, q, (nx, ny) = site
            fort, _ = star_fort(center.x, center.y, a, ang)
            city["wall"] = [ln for w in city["wall"] for ln in lines(w.difference(fort.buffer(-2 * s)))]
            city["towers"] = [tw for tw in city["towers"] if not fort.buffer(10 * s).contains(Point(tw[0], tw[1]))]
            city["buildings"] = [b for b in city["buildings"] if not b["poly"].intersects(fort.buffer(6 * s))]
            city["yard_trees"] = [t for t in city["yard_trees"] if not fort.buffer(6 * s).contains(Point(t[0], t[1]))]
            gate = Point(center.x + nx * a * 0.5, center.y + ny * a * 0.5)   # Festungstor auf der Stadtseite
            _connect_inside(s, city, gate)
            lage = "zitadelle"
        else:
            print("Hinweis: Kein Platz für eine Zitadelle in der Mauer - Festung vor der Stadt.")
    if (sea is None or lage == "land") and lage != "zitadelle":
        # an Land: freier Platz vor der Mauer, möglichst nahe an einem Tor
        roads_u = unary_union([ln.buffer(w / 2 + 40 * s) for ln, w in ext_roads]) if ext_roads else Polygon()
        best = None
        for _ in range(400):
            t = rng.uniform(0, 2 * math.pi)
            d = rng.uniform(170, 250) * s
            c = shape.centroid
            p = Point(c.x + math.cos(t) * (shape.exterior.distance(c) + d), c.y + math.sin(t) * (shape.exterior.distance(c) + d))
            disk = p.buffer(75 * s)
            if not (0 < p.x < W and 0 < p.y < W) or disk.intersects(water.buffer(20 * s)) \
                    or disk.intersects(shape.buffer(60 * s)) or disk.intersects(roads_u):
                continue
            score = min([p.distance(g) for g in gates] or [0])
            if best is None or score < best[0]:
                best = (score, p)
        if best is None:
            print("Hinweis: Kein Platz für die Festung gefunden.")
            return None
        center = best[1]
        ang = rng.uniform(0, 90)
        road_to_gate(center)

    fort, towers = star_fort(center.x, center.y, a, ang)
    area = fort.buffer(15 * s) if res["land_add"] is None else res["land_add"].union(fort)
    if res.get("lift"):
        area = area.union(res["lift"]["area"])
    res.update(fort=fort, towers=towers, buildings=_inner_buildings(center.x, center.y, a, ang, s), area=area,
               label={"x": center.x, "y": center.y, "text": spec.get("kuerzel") or spec["name"],
                      "kind": "festung", "lift": a * 0.75, "ort": place_info(spec)})
    return res
