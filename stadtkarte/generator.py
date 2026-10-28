"""Setzt Gelände, Stadt und Umland zu einem Kartenmodell zusammen."""
import math
import random

import numpy as np
import shapely
import shapely.affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import nearest_points, unary_union

from .city import CityBuilder, city_radius, fit_into_map, make_shape, pick_shape, ship_footprint, varied_shape
from .config import ROTATION, place_info, to_canonical
from .fortress import build_fortress
from .geo import Noise1D, axes, blob, lines, polys, roof, unit, vlen
from .styles import BIOMES, FORT_TYPES
from .surroundings import make_bridges, make_fields, make_forest, scatter_trees, suburb_houses
from .terrain import make_coast, make_islands, make_pools, make_river


def generate(cfg):
    rng = random.Random(cfg["seed"])
    W = int(cfg["ausgabe"]["bildgroesse"])
    s = W / 2000
    g = cfg["gelaende"]
    rot = ROTATION[g["kueste"]]
    has_coast = g["kueste"] != "keine"
    r = city_radius(W, cfg["einwohner"])
    biome = BIOMES[g["biotop"]]

    plateau = biome["plateau"] and has_coast
    if biome["mountain"]:   # Felsmassiv an der "Küstenseite", Inseln gibt es dort nicht
        sea, coast_y = make_coast(rng, W, s, has_coast, depth=0.27, amp=1.6)
        g["inseln"] = 0
    elif plateau:           # Hochplateau: jenseits der Felskante liegt die andere Geländestufe (statt Meer)
        sea, coast_y = make_coast(rng, W, s, True, depth=0.3, amp=1.3)
        g["inseln"] = 0
    else:
        sea, coast_y = make_coast(rng, W, s, has_coast)
    cx = W / 2 + rng.uniform(-0.04, 0.04) * W
    cy = coast_y(cx) + r * 1.0 if has_coast else W / 2
    city_shape = None
    form = pick_shape(cfg["seed"], cfg["stadtform"])
    if biome["mountain"] and has_coast:
        # Felskessel: Stadt rückt tief ins Massiv, Felsflanken links und rechts, unten offen
        # Der Kessel folgt exakt dem Stadtumriss, damit der Fels oben und seitlich direkt an die Stadt grenzt.
        cy = coast_y(cx) + r * 0.45
        if form == "rund":
            city_shape = make_shape(rng, (cx, cy), r)
        else:
            city_shape = varied_shape(rng, (cx, cy), r, form, W, s, True)
            city_shape, (cx, cy) = fit_into_map(city_shape, (cx, cy), W, s, top=coast_y(cx) - r * 0.65)
        spurs = [blob(rng, cx + side * r * 1.2, cy - r * 0.1, r * 0.65, rough=0.3, stretch=(1.0, 1.3))
                 for side in (-1, 1)]
        sea = unary_union([sea] + spurs).difference(city_shape)
        sea = max(polys(sea), key=lambda q: q.area) if polys(sea) else sea
    elif plateau:
        # direkt an der Kante: die Felskante ersetzt dort die Mauer; mit Abstand: Mauer ringsum, davor ein Streifen Land
        direkt = g["kante"] == "direkt"
        cy = coast_y(cx) + (r * 0.8 if direkt else r * 1.25 + 60 * s)
        city_shape = make_shape(rng, (cx, cy), r) if form == "rund" else varied_shape(rng, (cx, cy), r, form, W, s, True)
        top = coast_y(cx) - (0.4 * r if direkt else -60 * s)
        city_shape, (cx, cy) = fit_into_map(city_shape, (cx, cy), W, s, top=top)
        if not direkt:   # Buchten der Kante dürfen nicht an die Mauer reichen
            for _ in range(30):
                if not city_shape.buffer(45 * s).intersects(sea):
                    break
                city_shape, (cx, cy) = fit_into_map(city_shape, (cx, cy), W, s, top=city_shape.bounds[1] + 10 * s)
    elif form != "rund":   # andere Stadtform: Umriss vor dem Fluss festlegen, an der Küste mit der Oberkante am Ufer
        city_shape = varied_shape(rng, (cx, cy), r, form, W, s, has_coast)
        city_shape, (cx, cy) = fit_into_map(city_shape, (cx, cy), W, s,
                                            top=coast_y(cx) - 0.2 * r if has_coast else None)
    islands = []
    if has_coast:
        islands = make_islands(rng, W, s, sea, coast_y, int(g.get("inseln", 0)))
        if islands:
            sea = sea.difference(unary_union(islands))
    river, river_line = (None, None)
    if g.get("fluss"):
        river, river_line = make_river(rng, W, s, (cx, cy), r, coast_y, float(g.get("flussbreite", 60)),
                                       estuary=not (biome["mountain"] or plateau),
                                       end_y=(cy - 1.35 * r - 80 * s if biome["mountain"] and has_coast
                                              else -60 if plateau else None))   # Hochplateau: über die Kante hinweg
    if plateau:   # die Stufe ist eine geschlossene Fläche: keine Löcher und keine abgetrennten Splitter
        parts = polys(sea)
        sea = Polygon(max(parts, key=lambda q: q.area).exterior) if parts else sea
    if plateau and river is not None:   # die Kante kreuzt den Fluss quer: gerader Wasserfall von Ufer zu Ufer
        sea = straight_crossing(sea, river, river_line, W, s,
                                keep=None if g["kante"] == "direkt" else city_shape.buffer(45 * s))
    level_full = sea if plateau else None   # ganze andere Geländestufe (für Kante und Wasserfall)
    if plateau and river is not None:   # der Fluss fließt über die Kante (Wasserfall), die Stufe ist kein Wasser
        sea = sea.difference(river)
    water = unary_union([w for w in (sea, river) if w is not None]) if (sea or river) else Polygon()
    land = box(0, 0, W, W).difference(water)
    terrain = dict(sea=sea, river=river, river_line=river_line, water=water, coast_y=coast_y, land=land,
                   mountain=biome["mountain"], plateau=plateau, biome=biome, shape=city_shape)
    pools = make_pools(rng, W, s, biome["pools"], water)
    if biome["stilts"]:   # Pfahlbausiedlung: Wasserflächen und Kanäle mitten im Ort
        extra = []
        for _ in range(80):
            if len(extra) >= 6:
                break
            a, d = rng.uniform(0, 6.283), r * 0.8 * rng.random() ** 0.5
            x, y = cx + d * math.cos(a), cy + d * math.sin(a)
            if not water.buffer(20 * s).contains(Point(x, y)):
                extra.append(blob(rng, x, y, r * rng.uniform(0.15, 0.28), rough=0.4,
                                  stretch=(rng.uniform(0.7, 1.4), rng.uniform(0.7, 1.4))))
        pools = unary_union([pools] + extra).difference(water.buffer(4 * s))
    oases = make_oases(rng, W, s, biome["oases"], (cx, cy), r, water)
    if oases:
        pools = unary_union([pools] + oases)
    # Nur Pfahldörfer bauen über Wasser; sonst bleiben Seen und Oasen außerhalb des Orts
    terrain["pools"] = pools if biome["stilts"] else Polygon()

    builder = CityBuilder(cfg, rng, W, s, terrain, (cx, cy), r, rot)
    city, ext_roads, internal = builder.build()
    shape = city["shape"]
    if not biome["stilts"]:
        pools = pools.difference(shape.buffer(25 * s))

    # Festung (Insel, Landzunge oder an Land)
    forts, fort_bridges = [], []
    fort_specs = [o for o in cfg["orte"] if o["typ"] in FORT_TYPES]
    for spec in fort_specs[:1]:
        fort = build_fortress(rng, W, s, spec, terrain, city, ext_roads, islands)
        if fort is None:
            continue
        add = fort["land_add"]
        if add is not None:
            sea = sea.difference(add)
            water = water.difference(add)
            land = box(0, 0, W, W).difference(water)
            terrain.update(sea=sea, water=water, land=land)
            city["ships"] = [sh for sh in city["ships"] if not add.buffer(8 * s).contains(Point(sh["x"], sh["y"]))]
            city["piers"] = [p for p in city["piers"] if not p.intersects(add)]
        # Weg und Brücke beginnen am Festungsrand, nicht quer über den Festungshof
        # (Straßen haben runde Enden: um die halbe Breite vor der Mauer enden lassen)
        ext_roads = ext_roads + [(g, w) for ln, w in fort["roads"] for g in lines(ln.difference(fort["fort"].buffer(w / 2)))
                                 if g.length > 2 * s]
        fort_bridges += [(g, w) for ln, w in fort["bridges"] for g in lines(ln.difference(fort["fort"])) if g.length > 2 * s]
        # Hütten vor der Mauer weichen einer Festung an Land
        city["buildings"] = [b for b in city["buildings"] if not b.get("poor") or not b["poly"].intersects(fort["area"])]
        city["buildings"] += fort["buildings"]
        city["towers"] += fort["towers"]
        city["labels"].append(fort["label"])
        if spec.get("kuerzel"):
            city["legend"].append((spec["kuerzel"], spec["name"]))
        forts.append(fort)
    if len(fort_specs) > 1:
        print("Hinweis: Es wird nur eine Festung gebaut.")
    forts_u = unary_union([f["area"] for f in forts]) if forts else Polygon()
    if not city["faubourg"].is_empty:   # Großstadt: Vorstädte halten Felder, Wald und Einzelhäuser fern
        forts_u = forts_u.union(city["faubourg"])
    if not city["slum_outside"].is_empty:   # ebenso Hüttensiedlungen vor der Mauer
        forts_u = forts_u.union(city["slum_outside"].buffer(10 * s))
    # Altstadtmauer und ihre Tore zeichnen sich wie die äußere Mauer (die Festung nutzt nur die äußere)
    city["wall"] = city["wall"] + city.pop("old_wall")
    city["gates"] = city["gates"] + city.pop("old_gates")

    # Friedhöfe ohne Platz im Ort (oder lage: ausserhalb), Windmühlen und Bauernhöfe an eine Landstraße vor die Mauer
    for spec in city["deferred"]:
        place = {"muehle": outside_windmill, "bauernhof": outside_farm}.get(spec["typ"], outside_cemetery)
        area = place(rng, s, spec, builder, ext_roads, shape, water, pools, forts_u)
        if area is not None:
            forts_u = forts_u.union(area.buffer(10 * s))
            pools = pools.difference(area.buffer(8 * s))   # Gräberhügel bzw. Hofplatz: trockener Grund

    mines, paths = [], []
    if biome["mountain"] and sea is not None:
        mines, paths = make_mines(rng, s, biome["mines"], sea, land, shape, river, ext_roads)
        if mines:
            forts_u = forts_u.union(unary_union([mn["spoil"].buffer(20 * s) for mn in mines]))

    roads_u = unary_union([ln.buffer(w / 2 + 14 * s) for ln, w in ext_roads]) if ext_roads else Polygon()
    # Gebirge: oberer Hang (bis über die Stadt hinaus) ist Geröll, dort wächst kein geschlossener Wald
    upper_slope = Polygon()
    if biome["mountain"] and sea is not None:
        far = max(sea.distance(Point(x, y)) for x, y in shape.exterior.coords)
        upper_slope = sea.buffer(far * 0.75).intersection(land)
    forest_dirs = [to_canonical(d, rot) for d in g["wald"]]
    forest, forest_trees = make_forest(rng, W, s, (cx, cy), r, forest_dirs,
                                       unary_union([water.buffer(10 * s), shape.buffer(60 * s), roads_u, forts_u.buffer(30 * s),
                                                    upper_slope]), land,
                                       biome["tree_spacing"], biome["forest_scale"])
    blocked = unary_union([water.buffer(18 * s), shape.buffer(50 * s), roads_u, forest.buffer(25 * s),
                           forts_u.buffer(40 * s), pools.buffer(10 * s)])
    field_dirs = [to_canonical(d, rot) for d in g["felder"]]
    fields = make_fields(rng, W, s, (cx, cy), r, field_dirs, blocked, biome["field_kinds"], biome["field_prob"])
    fields_u = unary_union([f["poly"] for f in fields]) if fields else Polygon()
    houses = suburb_houses(rng, s, ext_roads,
                           unary_union([water.buffer(4 * s), shape.buffer(12 * s), fields_u.buffer(6 * s),
                                        forest.buffer(4 * s), forts_u,
                                        unary_union([ln.buffer(w / 2 + 2 * s) for ln, w in ext_roads])]))
    houses_u = unary_union([h["poly"].buffer(8 * s) for h in houses]) if houses else Polygon()
    blocked2 = unary_union([water.buffer(10 * s), shape.buffer(30 * s), roads_u, fields_u.buffer(15 * s), houses_u,
                            unary_union([f["fort"] for f in forts]).buffer(12 * s) if forts else Polygon(), forts_u,
                            Polygon() if biome["stilts"] else pools.buffer(4 * s)])
    allowed = land.difference(unary_union([blocked2, forest.buffer(10 * s)]))
    if not pools.is_empty:   # Bruchwald: über Tümpeln nur vereinzelte Bäume; auf Eis und in Oasen keine
        keep = 0.3 if biome["pool_style"] == "sumpf" else 0.0
        forest_trees = [tr for tr in forest_trees if not pools.contains(Point(tr[0], tr[1])) or rng.random() < keep]
    trees = forest_trees + scatter_trees(rng, W, s, allowed, shape)
    if plateau:   # die andere Geländestufe: Felder, ein Wäldchen und verstreute Bäume, nicht direkt an der Kante
        level = sea.buffer(-35 * s).difference(unary_union(
            [river.buffer(14 * s) if river is not None else Polygon(), forts_u.buffer(30 * s)]
            + [f["fort"].buffer(30 * s) for f in forts]))
        if not level.is_empty:
            off = box(-W, -W, 2 * W, 2 * W).difference(level)
            side = rng.choice([-1, 1])
            wood, wood_trees = make_forest(rng, W, s, (cx, cy), r, [(side * 0.6, -0.8)], off, level,
                                           biome["tree_spacing"], biome["forest_scale"] * 0.7)
            more = make_fields(rng, W, s, (cx, cy), r, [(0, -1), (-side * 0.7, -0.7)], off.union(wood.buffer(25 * s)),
                               biome["field_kinds"], biome["field_prob"])
            fields += more
            fields_u = unary_union([f["poly"] for f in fields]) if fields else Polygon()
            forest = forest.union(wood)
            spare = level.difference(unary_union([wood.buffer(10 * s), fields_u.buffer(12 * s)]))
            trees += wood_trees + scatter_trees(rng, W, s, spare, Point(-W, -W).buffer(1), count=45)
    trees = [(x, y, rad, rng.choice(biome["trees"])) for x, y, rad, _ in trees]
    trees += oasis_palms(rng, s, oases, biome, unary_union([shape.buffer(10 * s), roads_u, fields_u, water]))
    rocks = make_rocks(rng, s, biome["rocks"], allowed.difference(pools.buffer(6 * s)))
    dunes = make_dunes(rng, W, s, land.difference(unary_union([
        shape.buffer(50 * s), water.buffer(40 * s), fields_u.buffer(10 * s), forest.buffer(10 * s),
        unary_union(oases).buffer(70 * s) if oases else Polygon(), roads_u]))) if biome["dunes"] else []
    floes = make_floes(rng, s, sea, land) if biome["floes"] and sea is not None else []

    # Sumpf: Stelzenhäuser über Wasser, Schilf am Ufer, Seerosen
    reeds, lilies = [], []
    if not pools.is_empty and biome["pool_style"] == "sumpf":
        for b in city["buildings"] + houses:
            if b["poly"].intersection(pools).area > 0.2 * b["poly"].area:
                b["stilts"] = True
        for ln in lines(pools.boundary):
            k = rng.uniform(0, 10) * s
            while k < ln.length:
                if rng.random() < 0.55:
                    q = ln.interpolate(k)
                    reeds.append((q.x, q.y, rng.uniform(0, 180)))
                k += rng.uniform(9, 16) * s
        inner = pools.buffer(-6 * s)
        if not inner.is_empty:
            minx, miny, maxx, maxy = inner.bounds
            for _ in range(int(inner.area / (900 * s * s))):
                x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
                if inner.contains(Point(x, y)) and (not shape.contains(Point(x, y)) or rng.random() < 0.3):
                    lilies.append((x, y, rng.uniform(2.5, 5) * s))

    # keine Überlagerungen auf dem Wasser: Stege und Schiffe weichen allen Brücken (auch der Festungsbrücke)
    # Festungsinseln liegen teils in der Flussmündung: dort ist Land, die Inselstraße braucht keine Brücke
    added = [f["land_add"] for f in forts if f["land_add"] is not None]
    bridge_river = river.difference(unary_union(added)) if river is not None and added else river
    bridges = make_bridges(ext_roads + internal, bridge_river, s, river_line) + fort_bridges
    wheels = [Point(wh["x"], wh["y"]).buffer(wh["len"] / 2 + 4 * s) for wh in city["wheels"]]
    if bridges or wheels:   # auch Wasserräder brauchen freies Wasser
        bz = unary_union([ln.buffer(w / 2 + 6 * s) for ln, w in bridges] + wheels)
        city["piers"] = [p for p in city["piers"] if not p.intersects(bz)]
        city["ships"] = [sh for sh in city["ships"]
                         if not ship_footprint(sh["x"], sh["y"], sh["len"], sh["wid"], sh["angle"]).intersects(bz)]
    # Abschlussprüfung gegen Überlagerungen: Häuser nicht auf Brücken oder Landstraßen, Bäume auf nichts anderem
    bz = unary_union([ln.buffer(w / 2 + 2 * s) for ln, w in bridges]) if bridges else Polygon()
    rz = unary_union([ln.buffer(w / 2 + 1.5 * s) for ln, w in ext_roads]) if ext_roads else Polygon()
    keep = unary_union([bz, rz])
    city["buildings"] = [b for b in city["buildings"]
                         if b.get("landmark") or b.get("district") == -1 or not b["poly"].intersects(keep)]
    houses = [h for h in houses if not h["poly"].intersects(keep)]
    # Werft: über dem Bug des Schiffs im Helling und in der Ausfahrt davor liegt nichts (Stege, andere Schiffe,
    # Häuser weichen);
    # ein Schiff ohne Halle (z.B. von einer Festung verdrängt) entfällt
    halls = [b["poly"] for b in city["buildings"]]
    city["ships"] = [x for x in city["ships"] if not x.get("slip") or any(h is x["hall"] for h in halls)]
    for sh in [x for x in city["ships"] if x.get("slip")]:
        bow = ship_footprint(sh["x"], sh["y"], sh["len"], sh["wid"], sh["angle"]).difference(sh["hall"]).buffer(3 * s)
        bow = bow.union(sh["lane"].difference(sh["hall"]))   # samt Ausfahrt vor dem Bug
        city["piers"] = [p for p in city["piers"] if not p.intersects(bow)]
        city["ships"] = [o for o in city["ships"] if o is sh
                         or not ship_footprint(o["x"], o["y"], o["len"], o["wid"], o["angle"]).intersects(bow)]
        city["buildings"] = [b for b in city["buildings"] if b["poly"] is sh["hall"] or not b["poly"].intersects(bow)]
        houses = [h for h in houses if not h["poly"].intersects(bow)]
    solid = unary_union([keep] + [b["poly"] for b in city["buildings"] + houses] + list(city["piers"])
                        + [ship_footprint(sh["x"], sh["y"], sh["len"], sh["wid"], sh["angle"]) for sh in city["ships"]]
                        + [st["poly"] for st in city["stalls"]]
                        + [Point(x, y).buffer(r) for x, y, r in city["fountains"] + city["wells"]]
                        + [f["fort"] for f in forts])
    shapely.prepare(solid)
    trees = [tr for tr in trees if not solid.intersects(Point(tr[0], tr[1]).buffer(tr[2] * 0.6))]
    city["yard_trees"] = [tr for tr in city["yard_trees"] if not solid.intersects(Point(tr[0], tr[1]).buffer(tr[2] * 0.6))]

    return {
        "name": cfg["name"], "W": W, "s": s, "rot": rot, "cfg": cfg,
        "sea": sea, "river": river, "land": land, "water": water,
        "fields": fields, "forest": forest, "trees": trees, "suburbs": houses,
        "ext_roads": ext_roads, "bridges": bridges,
        "forts": forts, "biome": biome, "pools": pools, "reeds": reeds, "lilies": lilies,
        "oases": oases, "rocks": rocks, "dunes": dunes, "floes": floes,
        "river_line": river_line, "mines": mines, "paths": paths,
        "plateau": plateau, "plateau_level": level_full, "plateau_oben": plateau and g.get("plateau") == "oben",
        **city,
    }


def straight_crossing(level, river, river_line, W, s, keep=None):
    """Hochplateau: Wo der Fluss die Kante kreuzt, verläuft die Kante gerade und quer zum Fluss (Wasserfall von Ufer
    zu Ufer). Das Kantenstück um die Kreuzung (bis es auf beiden Seiten den Fluss verlassen hat) wird durch eine
    geglättete Linie ersetzt, deren Mittelstück senkrecht zum Fluss steht. Die Flächen zwischen alter und neuer
    Kante wechseln die Seite (keep: dort keine neue Stufe)."""
    frame = box(1 * s, 1 * s, W - 1 * s, W - 1 * s)
    edge = level.boundary.intersection(frame)
    for c in [g for g in shapely.get_parts(river_line.intersection(edge)) if g.geom_type == "Point"]:
        ln = min(lines(edge), key=lambda q: q.distance(c), default=None)
        if ln is None or ln.distance(c) > 1 * s:
            continue
        d = river_line.project(c)
        q0, q1 = river_line.interpolate(max(0.0, d - 8 * s)), river_line.interpolate(min(river_line.length, d + 8 * s))
        fx, fy = unit((q1.x - q0.x, q1.y - q0.y))
        px, py = -fy, fx                                   # quer zum Fluss
        probe = LineString([(c.x - px * 300 * s, c.y - py * 300 * s), (c.x + px * 300 * s, c.y + py * 300 * s)])
        across = [g for g in lines(probe.intersection(river)) if g.distance(c) < 1 * s]
        hw = across[0].length / 2 if across else 20 * s
        t = ln.project(c)
        ends = []
        for sign in (-1, 1):   # entlang der Kante nach außen, bis sie den Fluss sicher verlassen hat
            k = hw + 60 * s
            while 0 < t + sign * k < ln.length and (ln.interpolate(t + sign * k).distance(river) < 30 * s
                                                    or k < hw + 60 * s):
                k += 4 * s
            ends.append(t + sign * k)
        if not (0 < ends[0] and ends[1] < ln.length):
            continue
        a, b = ln.interpolate(ends[0]), ln.interpolate(ends[1])
        line = [(c.x + px * d, c.y + py * d) for d in (-hw - 45 * s, -hw - 12 * s, hw + 12 * s, hw + 45 * s)]
        if Point(line[0]).distance(a) > Point(line[-1]).distance(a):
            line.reverse()
        pts = [(a.x, a.y)] + line + [(b.x, b.y)]
        for _ in range(3):   # Chaikin: runde Übergänge, das gerade Mittelstück bleibt gerade
            pts = [pts[0]] + [q for (x0, y0), (x1, y1) in zip(pts, pts[1:])
                              for q in ((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1),
                                        (0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))] + [pts[-1]]
        old = shapely.ops.substring(ln, ends[0], ends[1])
        new = LineString(pts)
        faces = polys(shapely.polygonize(shapely.get_parts(unary_union([old, new]))))
        flip = []
        for fc in faces:
            gain = not level.contains(fc.representative_point())
            if gain and keep is not None and fc.intersects(keep):
                continue
            flip.append(fc)
        if flip:
            fixed = level.symmetric_difference(unary_union(flip)).buffer(0)
            level = max(polys(fixed), key=lambda q: q.area) if polys(fixed) else level
            edge = level.boundary.intersection(frame)
    return level


def outside_cemetery(rng, s, spec, builder, ext_roads, shape, water, pools, taken):
    """Rechteckiger Friedhof neben einer Landstraße vor dem Tor. Im Sumpf darf er teilweise
    in einen Tümpel ragen und wird dort als trockener Hügel aufgeschüttet."""
    L, B = rng.uniform(95, 120) * s, rng.uniform(65, 80) * s
    poly = roadside_spot(rng, s, L, B, ext_roads, shape, water, pools, taken)
    if poly is None:
        print(f"Hinweis: Kein Platz für den Friedhof '{spec['name']}' gefunden.")
        return None
    chapel = builder._cemetery(poly, "#8f8a80", -1)
    if chapel is None:
        return None
    chapel["ridges"], chapel["shade"] = roof(chapel["poly"])
    chapel["landmark"] = True
    builder.out["buildings"].append(chapel)
    _outside_label(builder, spec, poly, B / 2 + 6 * s, s)
    return poly


def roadside_spot(rng, s, L, B, ext_roads, shape, water, pools, taken, start=60, gap=22, max_wet=0.4):
    """Rechteck L x B neben einer Landstraße vor der Stadt (lange Seite parallel zur Straße), möglichst nah am Tor."""
    blocked = unary_union([shape.buffer(30 * s), water.buffer(12 * s), taken,
                           unary_union([ln.buffer(w / 2 + 8 * s) for ln, w in ext_roads]) if ext_roads else Polygon()])
    wet = pools.buffer(6 * s)
    best = None
    for ln, _ in ext_roads:
        k = start * s
        while k < min(ln.length - 10 * s, 400 * s):
            side = rng.choice([-1, 1])
            p, q = ln.interpolate(k), ln.interpolate(k + 3)
            tx, ty = unit((q.x - p.x, q.y - p.y))
            off = gap * s + B / 2
            cx, cy = p.x - ty * off * side, p.y + tx * off * side
            poly = Polygon([(cx + tx * a * L / 2 - ty * b * B / 2, cy + ty * a * L / 2 + tx * b * B / 2)
                            for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
            k += 15 * s
            if poly.intersects(blocked):
                continue
            overlap = poly.intersection(wet).area / poly.area if not wet.is_empty else 0.0
            if overlap > max_wet:
                continue
            score = overlap * 3 + k / (220 * s) + rng.uniform(0, 0.3)
            if best is None or score < best[0]:
                best = (score, poly)
    return best[1] if best else None


def _outside_label(builder, spec, poly, lift, s):
    if spec.get("kuerzel"):
        builder.out["legend"].append((spec["kuerzel"], spec["name"]))
    c = poly.centroid
    builder.out["labels"].append({"x": c.x, "y": c.y, "text": spec.get("kuerzel") or spec["name"],
                                  "kind": "ort", "lift": lift, "ort": place_info(spec)})


def outside_windmill(rng, s, spec, builder, ext_roads, shape, water, pools, taken):
    """Windmühle auf freiem Feld an einer Landstraße: runder Turm mit Kegeldach und vier Flügeln."""
    span = 54 * s                                   # Flügel brauchen Platz
    area = roadside_spot(rng, s, span, span, ext_roads, shape, water, pools, taken, start=90, gap=20, max_wet=0.0)
    if area is None:
        print(f"Hinweis: Kein Platz für die Windmühle '{spec['name']}' gefunden.")
        return None
    c = area.centroid
    tower = c.buffer(10 * s, quad_segs=4)           # Achteck
    mill = {"poly": tower, "color": "#8a6a4a", "district": -1, "landmark": True}
    mill["ridges"], mill["shade"] = roof(tower)
    builder.out["buildings"].append(mill)
    builder.out["windmills"].append({"x": c.x, "y": c.y, "len": 24 * s, "angle": rng.uniform(0, 360)})   # Windrichtung
    _outside_label(builder, spec, tower, 30 * s, s)
    return area


def outside_farm(rng, s, spec, builder, ext_roads, shape, water, pools, taken):
    """Bauernhof an einer Landstraße: Wohnhaus und großer Stall im Winkel um einen umzäunten Hofplatz."""
    L, B = rng.uniform(70, 85) * s, rng.uniform(52, 62) * s
    area = roadside_spot(rng, s, L, B, ext_roads, shape, water, pools, taken, start=80, gap=20, max_wet=0.1)
    if area is None:
        print(f"Hinweis: Kein Platz für den Bauernhof '{spec['name']}' gefunden.")
        return None
    o, e1, e2 = axes(area)
    l1, l2 = vlen(e1), vlen(e2)
    u, v = e1 / l1, e2 / l2

    def rect(x0, y0, x1, y1):
        return Polygon([o + u * x0 + v * y0, o + u * x1 + v * y0, o + u * x1 + v * y1, o + u * x0 + v * y1])
    builder.out["grounds"].append((area, "farmyard"))
    house = rect(6 * s, 6 * s, 6 * s + 26 * s, 6 * s + 15 * s)                     # Wohnhaus an der einen Ecke
    barn = rect(l1 - 6 * s - 20 * s, 6 * s, l1 - 6 * s, l2 - 6 * s)                  # Stall quer über die Tiefe
    for poly, color in ((house, "#a8584f"), (barn, "#7d5a3a")):
        b = {"poly": poly, "color": color, "district": -1, "landmark": poly is house}
        b["ridges"], b["shade"] = roof(poly)
        builder.out["buildings"].append(b)
    for _ in range(rng.randint(2, 3)):                                               # Heuhaufen im Hof
        x, y = o + u * rng.uniform(12 * s, l1 - 34 * s) + v * rng.uniform(l2 * 0.55, l2 - 10 * s)
        builder.out["haystacks"].append((float(x), float(y), rng.uniform(3.5, 5) * s))
    for k in range(rng.randint(2, 4)):                                               # Obstbäume am Haus
        t = o + u * (8 + k * 9) * s + v * (l2 - 6 * s)
        builder.out["yard_trees"].append((float(t[0]), float(t[1]), rng.uniform(5, 7) * s))
    _outside_label(builder, spec, area, B / 2 + 6 * s, s)
    return area


def make_oases(rng, W, s, count, center, r, water):
    """Wüste: grüne Wasserstellen knapp vor der Stadt."""
    oases = []
    frame = box(40 * s, 40 * s, W - 40 * s, W - 40 * s)
    for _ in range(int(count) * 30):
        if len(oases) >= count:
            break
        a, d = rng.uniform(0, 2 * math.pi), r * rng.uniform(1.5, 1.85)
        x, y = center[0] + d * math.cos(a), center[1] + d * math.sin(a) * 1.1
        o = blob(rng, x, y, r * rng.uniform(0.18, 0.28), rough=0.35, stretch=(rng.uniform(0.8, 1.4), 1))
        if not frame.contains(o) or o.buffer(40 * s).intersects(water) or any(o.buffer(80 * s).intersects(q) for q in oases):
            continue
        oases.append(o)
    return oases


def oasis_palms(rng, s, oases, biome, blocked):
    """Palmenring um jede Oase (Bäume mit fester Art 'palme')."""
    palms = []
    for o in oases:
        ring = o.exterior
        k = 0.0
        while k < ring.length:
            p, q = ring.interpolate(k), ring.interpolate(k + 2)
            tx, ty = unit((q.x - p.x, q.y - p.y))
            for _ in range(rng.randint(1, 2)):
                off = rng.uniform(6, 30) * s
                x, y = p.x + ty * off, p.y - tx * off
                if o.contains(Point(x, y)):
                    x, y = p.x - ty * off, p.y + tx * off
                if not blocked.contains(Point(x, y)):
                    palms.append((x, y, rng.uniform(10, 15) * s, rng.choice(biome["trees"]), "palme"))
            k += rng.uniform(12, 20) * s
    return palms


def make_rocks(rng, s, density, allowed):
    """Findlinge und Felsbrocken in kleinen Gruppen."""
    rocks = []
    if density <= 0 or allowed.is_empty:
        return rocks
    minx, miny, maxx, maxy = allowed.bounds
    for _ in range(int(55 * density)):
        cx, cy = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        for _ in range(rng.randint(1, 4)):
            x, y = cx + rng.gauss(0, 12 * s), cy + rng.gauss(0, 12 * s)
            if shapely.contains_xy(allowed, x, y):
                rx = rng.uniform(3, 9) * s
                rocks.append((x, y, rx, rx * rng.uniform(0.6, 0.9), rng.uniform(0, 180)))
    return rocks


def make_dunes(rng, W, s, free):
    """Wüste: geschwungene Dünenkämme, grob in Windrichtung ausgerichtet."""
    dunes = []
    if free.is_empty:
        return dunes
    wind = rng.uniform(0, math.pi)
    minx, miny, maxx, maxy = free.bounds
    for _ in range(90):
        noise = Noise1D(rng)
        x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        pts = [(x, y)]
        for i in range(rng.randint(8, 20)):
            a = wind + 0.9 * noise.fbm(i * 0.25)
            x, y = x + math.cos(a) * 12 * s, y + math.sin(a) * 12 * s
            pts.append((x, y))
        for piece in lines(LineString(pts).intersection(free)):
            if piece.length > 30 * s:
                dunes.append(piece)
    return dunes


def make_floes(rng, s, sea, land):
    """Nordland: Eisschollen im küstennahen Wasser."""
    floes = []
    inner = sea.buffer(-4 * s)
    if inner.is_empty:
        return floes
    minx, miny, maxx, maxy = inner.bounds
    for _ in range(600):
        if len(floes) >= 55:
            break
        x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        p = Point(x, y)
        if not inner.contains(p) or not 15 * s < land.distance(p) < 260 * s:
            continue
        fl = blob(rng, x, y, rng.uniform(5, 20) * s, rough=0.5, n=24)
        if inner.contains(fl) and not any(fl.buffer(4 * s).intersects(q) for q in floes):
            floes.append(fl)
    return floes


def make_mines(rng, s, count, rock, land, shape, river, ext_roads):
    """Gebirge: Mineneingänge an der Felskante mit Abraumhalde und Pfad zur nächsten Straße."""
    mines, paths = [], []
    cands = []
    for ln in lines(land.boundary.intersection(rock.buffer(2 * s))):
        k = 20 * s
        while k < ln.length - 20 * s:
            cands.append((ln, k))
            k += 25 * s
    rng.shuffle(cands)
    roads = unary_union([ln for ln, _ in ext_roads]) if ext_roads else None
    for ln, k in cands:
        if len(mines) >= count:
            break
        p, q = ln.interpolate(k), ln.interpolate(k + 3)
        if shape.distance(p) < 90 * s or (river is not None and river.distance(p) < 60 * s):
            continue
        if any(math.dist((p.x, p.y), (m_["x"], m_["y"])) < 260 * s for m_ in mines):
            continue
        tx, ty = unit((q.x - p.x, q.y - p.y))
        nx, ny = -ty, tx
        if not rock.contains(Point(p.x + nx * 15 * s, p.y + ny * 15 * s)):
            nx, ny = -nx, -ny
        if not land.contains(Point(p.x - nx * 25 * s, p.y - ny * 25 * s)):
            continue
        spoil = blob(rng, p.x - nx * 24 * s + tx * rng.uniform(-14, 14) * s, p.y - ny * 24 * s + ty * rng.uniform(-14, 14) * s,
                     rng.uniform(11, 17) * s, rough=0.4).intersection(land)
        mines.append({"x": p.x, "y": p.y, "angle": math.degrees(math.atan2(ny, nx)), "spoil": spoil})
        if roads is not None:
            start = Point(p.x - nx * 10 * s, p.y - ny * 10 * s)
            end = nearest_points(roads, start)[1]
            if start.distance(end) < 320 * s:
                paths.append(LineString([(start.x, start.y), (end.x, end.y)]))
    return mines, paths
