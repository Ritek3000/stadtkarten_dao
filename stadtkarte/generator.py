"""Setzt Gelände, Stadt und Umland zu einem Kartenmodell zusammen."""
import copy
import math
import random

import shapely
import shapely.affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import nearest_points, polylabel, split, unary_union

from .city import CityBuilder, city_radius, spread, fit_into_map, make_shape, pick_shape, varied_shape
from .config import OPTIONAL, ROTATION, place_info, to_canonical
from .fortress import build_fortress
from . import leuchtturm, staub
from .geo import Noise1D, axes, blob, clean, lines, oriented_rect, polys, roof, ship_footprint, unit, vlen
from .styles import BIOMES, FORT_TYPES, WET_POOLS
from .surroundings import fill_forest, hamlet, make_bridges, make_fields, make_forest, scatter_trees, suburb_houses
from .terrain import make_coast, make_islands, make_oxbows, make_pools, make_river


def hint_lines(m):
    """Die Hinweise des Generators als Zeilen für die Konsole ("Hinweis: ...")."""
    return ["Hinweis: " + h for h in m["hints"]]


def building_count(m):
    """Anzahl der Gebäude einer Karte (bei Häuserblöcken der Großstadt die einzelnen Häuser der Blöcke)."""
    return sum(len(b["segments"]) if b.get("form") == "block" else 1 for b in m["buildings"] + m["suburbs"])


AUSSCHNITT = {"normal": 0.62, "nah": 0.8, "fuellend": 0.8}   # Anteil des Stadtdurchmessers an der Kartenbreite


def generate(cfg):
    """Karte erzeugen. Mit ausgabe.ausschnitt (normal | nah | fuellend) wird eine entsprechend größere Welt erzeugt
    und das Fenster um die Stadt ausgeschnitten: Häuser, Straßen und Dächer werden größer, Schrift, Legende und
    Titel bleiben in Kartengröße. "fuellend" misst zuerst Stadt, Hafen, Festung und Orte vor der Stadt und erzeugt
    die Welt dann so groß, dass all das gerade auf die Karte passt."""
    W = int(cfg["ausgabe"]["bildgroesse"])
    mode = cfg["ausgabe"].get("ausschnitt", OPTIONAL["ausgabe.ausschnitt"])
    if mode not in AUSSCHNITT or cfg["stadtform"] == "eigene":
        return _generate(cfg, W)
    frac = city_radius(W, cfg["einwohner"], spread(cfg)) / W
    z = max(1.0, AUSSCHNITT[mode] / (2 * frac))
    if mode == "fuellend":
        # Probedurchlauf zum Ausmessen: mit einer Kopie der Beschreibung (die Erzeugung passt sie z.B. bei
        # unpassenden Vierteln an); seine Hinweise stehen im verworfenen Modell und kommen nicht zum Nutzer
        m = _generate(copy.deepcopy(cfg), round(W * z))
        minx, miny, maxx, maxy = _important(m).bounds
        side = max(maxx - minx, maxy - miny) * 1.1 + 2 * 50 * m["s"]   # Rand für Beschriftung
        z = max(1.0, min(W * z / side, 2.5 * z))   # die Welt so groß, dass 'side' gerade die Kartenbreite ist
        m = _generate(cfg, round(W * z))
        c = _important(m).envelope.centroid
    else:
        m = _generate(cfg, round(W * z))
        c = m["shape"].envelope.centroid
    return crop_model(m, c.x, c.y, W, z)


def _important(m):
    """Was auf einer füllenden Karte zu sehen sein muss: Stadt, Hafen, Schiffe, Festung, Orte vor der Stadt."""
    parts = [m["shape"], m["faubourg"], m["slum_outside"]] + [f["area"] for f in m["forts"]]
    parts += list(m["piers"])
    parts += [Point(lb["x"], lb["y"]).buffer(40 * m["s"]) for lb in m["labels"] if lb["kind"] in ("ort", "festung")]
    parts += [Point(sh["x"], sh["y"]).buffer(sh["len"] / 2) for sh in m["ships"]]
    return unary_union([g for g in parts if g is not None and not g.is_empty])


SHIFT_KEYS = ("house", "a", "b", "top", "bot")   # Punkte (x, y) in Wörterbüchern; andere Paare sind Richtungen


def _moved(g, dx, dy):
    """Verschobene Geometrie. Das Verschieben rundet die Koordinaten und kann nahezu entartete Flächen (schmale
    Splitter, Schleifen) ungültig machen; mit einer ungültigen Fläche scheitert später jede Vereinigung
    (unary_union) im Zeichnen mit einer TopologyException. Ungültige Flächen werden daher repariert."""
    out = shapely.affinity.translate(g, dx, dy)
    if g.geom_type in ("Polygon", "MultiPolygon") and not out.is_valid:
        fixed = polys(shapely.make_valid(out))
        out = unary_union(fixed) if fixed else Polygon()
    return out


def _shift(v, dx, dy, in_list=False):
    if hasattr(v, "geom_type"):
        return _moved(v, dx, dy)
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if k in ("x", "y") and isinstance(x, (int, float)) and not isinstance(x, bool):
                out[k] = x + (dx if k == "x" else dy)
            elif k in SHIFT_KEYS and isinstance(x, tuple) and len(x) == 2:
                out[k] = (x[0] + dx, x[1] + dy)
            else:
                out[k] = _shift(x, dx, dy)
        return out
    if isinstance(v, list):
        return [_shift(x, dx, dy, True) for x in v]
    if isinstance(v, tuple):
        if in_list and len(v) >= 2 and all(isinstance(a, (int, float)) and not isinstance(a, bool) for a in v[:2]):
            return (v[0] + dx, v[1] + dy) + tuple(v[2:])   # (x, y, ...) in Listen: Bäume, Türme, Tore, Brunnen ...
        return tuple(_shift(x, dx, dy) for x in v)
    return v


def crop_model(m, cx, cy, W, z):
    """Schneidet das Fenster W x W um (cx, cy) aus der größeren Welt und verschiebt alles in Kartenkoordinaten."""
    Wv = m["W"]
    x0 = min(max(cx - W / 2, 0), Wv - W)
    y0 = min(max(cy - W / 2, 0), Wv - W)
    keep = {"cfg", "biome", "W", "s", "rot", "name"}
    out = {k: (v if k in keep else _shift(v, -x0, -y0)) for k, v in m.items()}
    out["hints"] = list(m["hints"])
    if m.get("great_gate"):
        out["great_gate"] = (m["great_gate"][0] - x0, m["great_gate"][1] - y0) + tuple(m["great_gate"][2:])
    pad = 80 * m["s"]   # Bäume, Felsen und Felder weit außerhalb des Fensters braucht niemand
    inside = lambda x, y: -pad < x < W + pad and -pad < y < W + pad
    for k in ("trees", "rocks", "reeds", "lilies", "haystacks"):
        out[k] = [t for t in out.get(k, []) if inside(t[0], t[1])]
    frame = box(-pad, -pad, W + pad, W + pad)
    out["fields"] = [fl for fl in out["fields"] if fl["poly"].intersects(frame)]
    for k, v in out.items():   # große Flächen (Meer, Land, Wald ...) aufs Fenster zuschneiden: Weichzeichner und
        if hasattr(v, "geom_type") and not v.is_empty and not frame.contains(v):   # Texturen arbeiten sonst auf
            if v.geom_type in ("Polygon", "MultiPolygon"):                        # der ganzen Welt
                out[k] = unary_union(polys(v.intersection(frame))) if v.intersects(frame) else Polygon()
            elif v.geom_type in ("LineString", "MultiLineString") and k != "river_line":
                out[k] = unary_union(lines(v.intersection(frame)))
    out["W"], out["st"], out["zoom"] = W, W / 2000, z
    missing = [lb["text"] for lb in out["labels"] if lb["kind"] in ("ort", "festung")
               and not (0 < lb["x"] < W and 0 < lb["y"] < W)]
    if missing:
        extra = "" if m["cfg"]["ausgabe"].get("ausschnitt") == "fuellend" else " (Ausschnitt 'fuellend' zeigt mehr)"
        out["hints"].append("Außerhalb des Ausschnitts: " + ", ".join(missing) + extra + ".")
    return out


def _generate(cfg, W):
    """Baut das Kartenmodell in Stufen: Gelände, Stadt, Festung, Leuchtturm, Orte vor der Mauer, Wald und Felder,
    Häuser, Bäume und Felsen, Sumpf, Brücken und zuletzt die Prüfung auf Überlagerungen. Die Reihenfolge ist
    verbindlich: alle Stufen ziehen ihre Zufallszahlen aus demselben rng, eine andere Reihenfolge ergäbe zum selben
    Seed eine andere Karte (tests/golden.py würde das melden)."""
    rng = random.Random(cfg["seed"])
    hints = []   # Hinweise an den Nutzer (m["hints"]); jede Karte hat ihre eigene Liste
    s = W / 2000
    g = cfg["gelaende"]
    rot = ROTATION[g["kueste"]]
    has_coast = g["kueste"] != "keine"
    r = city_radius(W, cfg["einwohner"], spread(cfg))
    biome = BIOMES[g["biotop"]]
    plateau = biome["plateau"] and has_coast
    form = pick_shape(cfg["seed"], cfg["stadtform"])

    # Gelände
    sea, coast_y, cx, cy, city_shape = _coast_and_outline(rng, cfg, W, s, r, biome, form, has_coast, plateau)
    custom = custom_wall(cfg, W, rot) if form == "eigene" else None
    terrain, islands, gorge, level_full, custom = _waters(rng, cfg, W, s, r, biome, has_coast, plateau, custom,
                                                          sea, coast_y, (cx, cy), city_shape)
    pools, oases = _pools_and_oases(rng, W, s, r, biome, (cx, cy), terrain)
    if form == "eigene" and custom is None:   # erster Schritt: nur das Gelände, die Mauer wird darauf gezeichnet
        return terrain_model(cfg, W, s, rot, terrain, pools, oases, biome, hints)
    if custom is not None:
        terrain["custom"] = custom
        cx, cy = custom["center"]
        r = custom["radius"]

    # Stadt, Festung, Leuchtturm
    builder = CityBuilder(cfg, rng, W, s, terrain, (cx, cy), r, rot, hints)
    city, ext_roads, internal = builder.build()
    cx, cy = builder.center   # liegt der Umriss im Wasser, rückt die Stadt ans Ufer (sonst unverändert)
    shape = city["shape"]
    if not biome["stilts"]:
        pools = pools.difference(shape.buffer(25 * s))
    forts, fort_bridges, ext_roads, forts_u = _fortress(rng, W, s, cfg, terrain, city, ext_roads, islands, hints)
    sea, river, river_line = terrain["sea"], terrain["river"], terrain["river_line"]
    water, land = terrain["water"], terrain["land"]   # eine Festung an Land hat Meer und Wasser verkleinert
    light, forts_u = _lighthouse(s, W, city, terrain, islands, forts, forts_u)
    if not city["faubourg"].is_empty:   # Großstadt: Vorstädte halten Felder, Wald und Einzelhäuser fern
        forts_u = forts_u.union(city["faubourg"])
    if not city["slum_outside"].is_empty:   # ebenso Hüttensiedlungen vor der Mauer
        forts_u = forts_u.union(city["slum_outside"].buffer(10 * s))
    # Altstadtmauer und ihre Tore zeichnen sich wie die äußere Mauer (die Festung nutzt nur die äußere)
    city["wall"] = city["wall"] + city.pop("old_wall")
    city["gates"] = city["gates"] + city.pop("old_gates")

    # Orte vor der Mauer, Bergwerke, Wald, Felder und Häuser
    pools, forts_u = _outside_places(rng, s, city, builder, ext_roads, shape, water, pools, forts_u)
    mines, paths, forts_u = _mines(rng, s, biome, sea, land, shape, river, ext_roads, forts_u)
    roads_u = unary_union([ln.buffer(w / 2 + 14 * s) for ln, w in ext_roads]) if ext_roads else Polygon()
    forest, forest_trees, fields, fields_u = _forest_and_fields(rng, W, s, cfg, rot, terrain, (cx, cy), r, shape,
                                                                pools, roads_u, forts_u)
    houses = _suburbs(rng, s, cfg, city, ext_roads, water, shape, fields_u, forest, forts_u)
    allowed = _free_ground(s, terrain, shape, pools, roads_u, fields_u, houses, forest, forts, forts_u)

    # Bäume, Felsen, Dünen, Eisschollen, Sumpf
    trees = _trees(rng, s, biome, pools, forest_trees, allowed, shape)
    if plateau:
        forest, fields, fields_u, level_trees = _upper_level(rng, W, s, (cx, cy), r, terrain, forts, forts_u,
                                                             forest, fields, fields_u)
        trees += level_trees
    trees = [(x, y, rad, rng.choice(biome["trees"])) for x, y, rad, _ in trees]
    trees += oasis_palms(rng, s, oases, biome, unary_union([shape.buffer(10 * s), roads_u, fields_u, water]))
    rocks, dunes, floes = _rocks_dunes_floes(rng, s, terrain, shape, pools, allowed, roads_u, fields_u, forest, oases)
    reeds, lilies = _swamp(rng, s, biome, pools, shape, city, houses)

    # Brücken und Abschlussprüfung gegen Überlagerungen
    bridges = _bridges_over_water(s, city, ext_roads, internal, river, river_line, forts, fort_bridges)
    houses, trees = _resolve_overlaps(s, city, bridges, ext_roads, forts, light, houses, trees)

    return {
        "name": cfg["name"], "W": W, "s": s, "rot": rot, "cfg": cfg,
        "sea": sea, "river": river, "land": land, "water": water,
        "fields": fields, "forest": forest, "trees": trees, "suburbs": houses,
        "ext_roads": ext_roads, "bridges": bridges,
        "forts": forts, "biome": biome, "pools": pools, "reeds": reeds, "lilies": lilies,
        "oases": oases, "rocks": rocks, "dunes": dunes, "floes": floes,
        "river_line": river_line, "mines": mines, "paths": paths,
        "klamm_fade": (gorge["y_a"], gorge["y_b"]) if gorge and river is not None else None,
        "plateau": plateau, "plateau_level": level_full, "plateau_oben": plateau and g.get("plateau") == "oben",
        "lighthouse": light,
        "dust": staub.areas(cfg, W, (cx, cy), r, rot),
        "hints": hints,
        **city,
    }


def _coast_and_outline(rng, cfg, W, s, r, biome, form, has_coast, plateau):
    """Küste (bzw. Felsmassiv, Plateaukante), Stadtmitte und, wo es schon jetzt feststeht, der Stadtumriss.
    Liefert (Meer, Küstenfunktion, cx, cy, Umriss); der Umriss bleibt None, wenn er erst nach Fluss und Küste
    entsteht (runde Stadt) oder aus der gezeichneten Mauer kommt (Form "eigene")."""
    g = cfg["gelaende"]
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
    if form == "eigene":
        # Gelände entsteht wie bei einer runden Stadt (Fluss und Küste bleiben gleich, ob schon eine Mauer
        # gezeichnet ist oder nicht); die gezeichnete Mauer wird erst danach zum Stadtumriss. Der Umriss entsteht
        # erst, wenn Küste bzw. Plateaukante feststehen (sie können Mauer sein).
        return sea, coast_y, cx, cy, city_shape
    if biome["mountain"] and has_coast:
        # Felskessel: Stadt rückt tief ins Massiv, Felsflanken links und rechts, unten offen
        # Der Kessel folgt exakt dem Stadtumriss, damit der Fels oben und seitlich direkt an die Stadt grenzt.
        cy = coast_y(cx) + r * 0.45
        if form == "rund":
            city_shape = make_shape(rng, (cx, cy), r)
        else:
            city_shape = varied_shape(rng, (cx, cy), r, form, s, True)
            city_shape, (cx, cy) = fit_into_map(city_shape, (cx, cy), W, s, top=coast_y(cx) - r * 0.65)
        spurs = [blob(rng, cx + side * r * 1.2, cy - r * 0.1, r * 0.65, rough=0.3, stretch=(1.0, 1.3))
                 for side in (-1, 1)]
        sea = unary_union([sea] + spurs).difference(city_shape)
        sea = max(polys(sea), key=lambda q: q.area) if polys(sea) else sea
    elif plateau:
        # direkt an der Kante: die Felskante ersetzt dort die Mauer; mit Abstand: Mauer ringsum, davor ein Streifen Land
        direkt = g["kante"] == "direkt"
        cy = coast_y(cx) + (r * 0.8 if direkt else r * 1.25 + 60 * s)
        city_shape = make_shape(rng, (cx, cy), r) if form == "rund" else varied_shape(rng, (cx, cy), r, form, s, True)
        top = coast_y(cx) - (0.4 * r if direkt else -60 * s)
        city_shape, (cx, cy) = fit_into_map(city_shape, (cx, cy), W, s, top=top)
        if not direkt:   # Buchten der Kante dürfen nicht an die Mauer reichen
            for _ in range(30):
                if not city_shape.buffer(45 * s).intersects(sea):
                    break
                city_shape, (cx, cy) = fit_into_map(city_shape, (cx, cy), W, s, top=city_shape.bounds[1] + 10 * s)
    elif form != "rund":   # andere Stadtform: Umriss vor dem Fluss festlegen, an der Küste mit der Oberkante am Ufer
        city_shape = varied_shape(rng, (cx, cy), r, form, s, has_coast)
        city_shape, (cx, cy) = fit_into_map(city_shape, (cx, cy), W, s,
                                            top=coast_y(cx) - 0.2 * r if has_coast else None)
    elif spread(cfg) > 1:   # runde Stadt mit lockerer Bebauung: so groß, dass sie sonst über den Kartenrand ragt
        city_shape = make_shape(rng, (cx, cy), r)
        city_shape, (cx, cy) = fit_into_map(city_shape, (cx, cy), W, s,
                                            top=coast_y(cx) - 0.2 * r if has_coast else None)
    return sea, coast_y, cx, cy, city_shape


def _waters(rng, cfg, W, s, r, biome, has_coast, plateau, custom, sea, coast_y, center, city_shape):
    """Inseln, Fluss (im Gebirge mit Klamm), Wasser und Land; beim Hochplateau die geschlossene andere Stufe, über die
    der Fluss als Wasserfall fließt; eine gezeichnete Mauer wird zum Stadtumriss geschlossen.
    Liefert (terrain, Inseln, Klamm, ganze Plateaustufe, gezeichnete Mauer); terrain bündelt Meer, Fluss, Wasser,
    Land und Küstenfunktion für Stadt, Festung und Leuchtturm."""
    g = cfg["gelaende"]
    cx, cy = center
    islands = []
    if has_coast:
        islands = make_islands(rng, W, s, sea, coast_y, int(g.get("inseln", 0)))
        if islands:
            sea = sea.difference(unary_union(islands))
    river, river_line = (None, None)
    gorge = None   # Gebirge: Klamm bis ins Tal, dort läuft sie aus und fließt als kleiner Bach weiter
    if biome["mountain"] and g.get("fluss") and city_shape is not None:
        # das Tal beginnt, wo die Felsflanken neben der Stadt enden; die Klamm läuft dort aus (und nicht erst im offenen Land)
        strip = box(cx - 1.7 * r, -W, cx + 1.7 * r, 2 * W)
        flanks = sea.intersection(strip) if sea is not None and not sea.is_empty else None
        valley = flanks.bounds[3] if flanks is not None and not flanks.is_empty else city_shape.bounds[3] - 0.3 * r
        y_a = min(max(valley, cy + 0.3 * r), city_shape.bounds[3] + 40 * s)
        gorge = {"y_a": y_a, "y_b": y_a + 440 * s, "seed": cfg["seed"]}
    if g.get("fluss"):
        river, river_line = make_river(rng, W, s, (cx, cy), r, coast_y, float(g.get("flussbreite", 60)),
                                       estuary=not (biome["mountain"] or plateau),
                                       end_y=(cy - 1.35 * r - 80 * s if biome["mountain"] and has_coast
                                              else -60 if plateau else None),   # Hochplateau: über die Kante hinweg
                                       gorge=gorge)
    if plateau:   # die Stufe ist eine geschlossene Fläche: keine Löcher und keine abgetrennten Splitter
        parts = polys(sea)
        sea = Polygon(max(parts, key=lambda q: q.area).exterior) if parts else sea
    if plateau and river is not None:   # die Kante kreuzt den Fluss quer: gerader Wasserfall von Ufer zu Ufer
        sea = straight_crossing(sea, river, river_line, W, s,
                                keep=None if g["kante"] == "direkt" or city_shape is None else city_shape.buffer(45 * s))
    level_full = sea if plateau else None   # ganze andere Geländestufe (für Kante und Wasserfall)
    if plateau and river is not None:   # der Fluss fließt über die Kante (Wasserfall), die Stufe ist kein Wasser
        sea = sea.difference(river)
    water = unary_union([w for w in (sea, river) if w is not None]) if (sea or river) else Polygon()
    land = box(0, 0, W, W).difference(water)
    if custom is not None:   # gezeichnete Mauer schließen: an Küste bzw. Plateaukante offen, sonst als Ring
        custom = close_custom(custom, sea, W, s)
        city_shape = custom["shape"]
    terrain = dict(sea=sea, river=river, river_line=river_line, water=water, coast_y=coast_y, land=land,
                   mountain=biome["mountain"], plateau=plateau, biome=biome, shape=city_shape,
                   plateau_oben=plateau and g.get("plateau") == "oben")
    return terrain, islands, gorge, level_full, custom


def _pools_and_oases(rng, W, s, r, biome, center, terrain):
    """Tümpel (bei Pfahlbauten auch Wasserflächen mitten im Ort) und Oasen. Liefert (Tümpel samt Oasen, Oasen); in
    terrain stehen die Tümpel nur dort, wo Häuser über Wasser stehen dürfen."""
    cx, cy = center
    water = terrain["water"]
    pools = make_pools(rng, W, s, biome["pools"], water, biome["pool_rough"])
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
    if biome["oxbows"]:   # Auwald: Altarme neben dem Fluss
        arms = make_oxbows(rng, W, s, biome["oxbows"], terrain["river"], terrain["river_line"], (cx, cy), r)
        if not arms.is_empty:
            pools = unary_union([pools, arms]).difference(water.buffer(6 * s))
    oases = make_oases(rng, W, s, biome["oases"], (cx, cy), r, water)
    if oases:
        pools = unary_union([pools] + oases)
    # Nur Pfahldörfer bauen über Wasser; sonst bleiben Seen und Oasen außerhalb des Orts
    terrain["pools"] = pools if biome["stilts"] else Polygon()
    return pools, oases


def _fortress(rng, W, s, cfg, terrain, city, ext_roads, islands, hints):
    """Festung (Insel, Landzunge oder an Land) samt Weg und Brücke. Eine Festung an Land verkleinert Meer, Wasser und
    Land in terrain und verdrängt Schiffe, Stege und Hütten. Liefert (Festungen, Festungsbrücken, Landstraßen samt
    Festungsweg, Fläche, die Wald, Felder und Häuser freihalten muss)."""
    forts, fort_bridges = [], []
    fort_specs = [o for o in cfg["orte"] if o["typ"] in FORT_TYPES]
    for spec in fort_specs[:1]:
        fort = build_fortress(rng, W, s, spec, terrain, city, ext_roads, islands, hints)
        if fort is None:
            continue
        add = fort["land_add"]
        if add is not None:
            sea = terrain["sea"].difference(add)
            water = terrain["water"].difference(add)
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
        hints.append("Es wird nur eine Festung gebaut.")
    forts_u = unary_union([f["area"] for f in forts]) if forts else Polygon()
    # Schiffe, deren Ausfahrt eine Festung, ihre Insel oder Brücke versperrt, legen hier gar nicht erst an
    if forts:
        fort_block = unary_union([f["area"] for f in forts]
                                 + [ln.buffer(w / 2 + 4 * s) for ln, w in fort_bridges])
        city["ships"] = [sh for sh in city["ships"] if sh.get("depart") is None
                         or not sh["depart"].intersects(fort_block)]
    return forts, fort_bridges, ext_roads, forts_u


def _lighthouse(s, W, city, terrain, islands, forts, forts_u):
    """Leuchtturm: jede Küstenstadt, auf einer vorgelagerten Insel oder an der Spitze des Hafens. Er verdrängt, was auf
    seiner Fläche steht. Liefert (Leuchtturm oder None, Freihaltefläche samt Leuchtturm)."""
    light = leuchtturm.place(s, W, city, terrain, islands, forts)
    if light is not None:
        foot = light["area"]
        city["buildings"] = [b for b in city["buildings"] if not b["poly"].intersects(foot)]
        city["stalls"] = [st for st in city["stalls"] if not st["poly"].intersects(foot)]
        city["wells"] = [w_ for w_ in city["wells"] if not foot.buffer(w_[2]).contains(Point(w_[0], w_[1]))]
        city["fountains"] = [w_ for w_ in city["fountains"] if not foot.buffer(w_[2]).contains(Point(w_[0], w_[1]))]
        city["yard_trees"] = [t_ for t_ in city["yard_trees"] if not foot.buffer(t_[2]).contains(Point(t_[0], t_[1]))]
        forts_u = forts_u.union(foot.buffer(20 * s))
        city["labels"].append({"x": light["x"], "y": light["y"], "text": "Leuchtturm", "kind": "ort",
                               "lift": light["r"] * 1.6, "ort": place_info({"name": "Leuchtturm", "typ": "leuchtturm"})})
    return light, forts_u


def _outside_places(rng, s, city, builder, ext_roads, shape, water, pools, forts_u):
    """Friedhöfe ohne Platz im Ort (oder lage: ausserhalb), Windmühlen und Bauernhöfe an eine Landstraße vor die Mauer.
    Liefert (Tümpel ohne die neuen Flächen, Freihaltefläche samt neuen Flächen)."""
    for spec in city["deferred"]:
        place = {"muehle": outside_windmill, "bauernhof": outside_farm}.get(spec["typ"], outside_cemetery)
        area = place(rng, s, spec, builder, ext_roads, shape, water, pools, forts_u)
        if area is not None:
            forts_u = forts_u.union(area.buffer(10 * s))
            pools = pools.difference(area.buffer(8 * s))   # Gräberhügel bzw. Hofplatz: trockener Grund
    return pools, forts_u


def _mines(rng, s, biome, sea, land, shape, river, ext_roads, forts_u):
    """Bergwerke samt Pfaden (nur im Gebirge). Liefert (Bergwerke, Pfade, Freihaltefläche samt Halden)."""
    mines, paths = [], []
    if biome["mountain"] and sea is not None:
        mines, paths = make_mines(rng, s, biome["mines"], sea, land, shape, river, ext_roads)
        if mines:
            forts_u = forts_u.union(unary_union([mn["spoil"].buffer(20 * s) for mn in mines]))
    return mines, paths, forts_u


def _forest_and_fields(rng, W, s, cfg, rot, terrain, center, r, shape, pools, roads_u, forts_u):
    """Wald samt Bäumen und Felder vor der Stadt. Beide meiden Wasser, Stadt, Landstraßen und Freihalteflächen;
    im Gebirge wächst am oberen Hang (Geröll) kein geschlossener Wald. Liefert (Wald, Waldbäume, Felder, Felderfläche)."""
    g = cfg["gelaende"]
    biome, sea, water, land = terrain["biome"], terrain["sea"], terrain["water"], terrain["land"]
    # Gebirge: oberer Hang (bis über die Stadt hinaus) ist Geröll, dort wächst kein geschlossener Wald
    upper_slope = Polygon()
    if biome["mountain"] and sea is not None:
        far = max(sea.distance(Point(x, y)) for x, y in shape.exterior.coords)
        upper_slope = sea.buffer(far * 0.75).intersection(land)
    forest_dirs = [to_canonical(d, rot) for d in g["wald"]]
    forest, forest_trees = make_forest(rng, W, s, center, r, forest_dirs,
                                       unary_union([water.buffer(10 * s), shape.buffer(60 * s), roads_u, forts_u.buffer(30 * s),
                                                    upper_slope]), land,
                                       biome["tree_spacing"], biome["forest_scale"])
    if biome["river_forest"] and terrain["river"] is not None:   # Auwald: Waldstreifen beiderseits des Flusses
        river = terrain["river"]
        band = river.buffer(biome["river_forest"] * s).difference(river.buffer(12 * s)).intersection(land).difference(
            unary_union([shape.buffer(60 * s), roads_u, forts_u.buffer(30 * s), forest.buffer(4 * s),
                         pools.buffer(5 * s), water.difference(river).buffer(10 * s)]))
        band = unary_union(clean(band, 2500 * s * s))
        if not band.is_empty:
            forest_trees = forest_trees + fill_forest(rng, s, band, biome["tree_spacing"])
            forest = forest.union(band)
    blocked = unary_union([water.buffer(18 * s), shape.buffer(50 * s), roads_u, forest.buffer(25 * s),
                           forts_u.buffer(40 * s), pools.buffer(10 * s)])
    field_dirs = [to_canonical(d, rot) for d in g["felder"]]
    fields = make_fields(rng, W, s, center, r, field_dirs, blocked, biome["field_kinds"], biome["field_prob"],
                         biome["field_names"])
    fields_u = unary_union([f["poly"] for f in fields]) if fields else Polygon()
    return forest, forest_trees, fields, fields_u


def _suburbs(rng, s, cfg, city, ext_roads, water, shape, fields_u, forest, forts_u):
    """Vorstadthäuser an den Landstraßen und Weiler an Straßen, die sonst kein Ziel hätten."""
    houses = [] if not cfg["mauer"].get("vorstaedte", True) else suburb_houses(rng, s, ext_roads,
                           unary_union([water.buffer(4 * s), shape.buffer(12 * s), fields_u.buffer(6 * s),
                                        forest.buffer(4 * s), forts_u,
                                        unary_union([ln.buffer(w / 2 + 2 * s) for ln, w in ext_roads])]))
    for ln in city.get("dead_ends", []):   # Straße ohne anderes Ziel: Weiler am Ende
        houses += hamlet(rng, s, ln, unary_union([water.buffer(4 * s), shape.buffer(12 * s), fields_u.buffer(6 * s),
                                                  unary_union([h["poly"].buffer(4 * s) for h in houses] or [Polygon()]),
                                                  unary_union([g.buffer(w / 2 + 2 * s) for g, w in ext_roads])]))
    return houses


def _free_ground(s, terrain, shape, pools, roads_u, fields_u, houses, forest, forts, forts_u):
    """Freies Land für Einzelbäume und Felsen: ohne Wasser, Stadt, Straßen, Felder, Häuser, Festungen und Wald."""
    biome, water, land = terrain["biome"], terrain["water"], terrain["land"]
    houses_u = unary_union([h["poly"].buffer(8 * s) for h in houses]) if houses else Polygon()
    blocked2 = unary_union([water.buffer(10 * s), shape.buffer(30 * s), roads_u, fields_u.buffer(15 * s), houses_u,
                            unary_union([f["fort"] for f in forts]).buffer(12 * s) if forts else Polygon(), forts_u,
                            Polygon() if biome["stilts"] else pools.buffer(4 * s)])
    return land.difference(unary_union([blocked2, forest.buffer(10 * s)]))


def _trees(rng, s, biome, pools, forest_trees, allowed, shape):
    """Waldbäume (über Tümpeln nur vereinzelt) und verstreute Einzelbäume auf freiem Land."""
    if not pools.is_empty:   # Bruchwald: über Tümpeln nur vereinzelte Bäume; auf Eis und in Oasen keine
        keep = 0.3 if biome["pool_style"] == "sumpf" else 0.0
        forest_trees = [tr for tr in forest_trees if not pools.contains(Point(tr[0], tr[1])) or rng.random() < keep]
    return forest_trees + scatter_trees(rng, s, allowed, shape, biome["scatter"])


def _upper_level(rng, W, s, center, r, terrain, forts, forts_u, forest, fields, fields_u):
    """Hochplateau: die andere Geländestufe trägt Felder, ein Wäldchen und verstreute Bäume, nicht direkt an der Kante.
    Liefert (Wald, Felder, Felderfläche, zusätzliche Bäume)."""
    biome, sea, river = terrain["biome"], terrain["sea"], terrain["river"]
    trees = []
    level = sea.buffer(-35 * s).difference(unary_union(
        [river.buffer(14 * s) if river is not None else Polygon(), forts_u.buffer(30 * s)]
        + [f["fort"].buffer(30 * s) for f in forts]))
    if not level.is_empty:
        off = box(-W, -W, 2 * W, 2 * W).difference(level)
        side = rng.choice([-1, 1])
        wood, wood_trees = make_forest(rng, W, s, center, r, [(side * 0.6, -0.8)], off, level,
                                       biome["tree_spacing"], biome["forest_scale"] * 0.7)
        more = make_fields(rng, W, s, center, r, [(0, -1), (-side * 0.7, -0.7)], off.union(wood.buffer(25 * s)),
                           biome["field_kinds"], biome["field_prob"], biome["field_names"])
        fields += more
        fields_u = unary_union([f["poly"] for f in fields]) if fields else Polygon()
        forest = forest.union(wood)
        spare = level.difference(unary_union([wood.buffer(10 * s), fields_u.buffer(12 * s)]))
        trees = wood_trees + scatter_trees(rng, s, spare, Point(-W, -W).buffer(1), count=45)
    return forest, fields, fields_u, trees


def _rocks_dunes_floes(rng, s, terrain, shape, pools, allowed, roads_u, fields_u, forest, oases):
    """Felsbrocken, Dünen (Wüste) und Eisschollen (Eis), je nach Biotop."""
    biome, sea, water, land = terrain["biome"], terrain["sea"], terrain["water"], terrain["land"]
    rocks = make_rocks(rng, s, biome["rocks"], allowed.difference(pools.buffer(6 * s)))
    dunes = make_dunes(rng, s, land.difference(unary_union([
        shape.buffer(50 * s), water.buffer(40 * s), fields_u.buffer(10 * s), forest.buffer(10 * s),
        unary_union(oases).buffer(70 * s) if oases else Polygon(), roads_u]))) if biome["dunes"] else []
    floes = make_floes(rng, s, sea, land) if biome["floes"] and sea is not None else []
    return rocks, dunes, floes


def _swamp(rng, s, biome, pools, shape, city, houses):
    """Sumpf, Altarme und Moorseen: Stelzenhäuser über Wasser (nur Sumpf), Schilf am Ufer, Seerosen. Liefert (Schilf,
    Seerosen)."""
    reeds, lilies = [], []
    if not pools.is_empty and biome["pool_style"] in WET_POOLS:
        if biome["pool_style"] == "sumpf":
            for b in city["buildings"] + houses:
                if b["poly"].intersection(pools).area > 0.2 * b["poly"].area:
                    b["stilts"] = True
        for ln in lines(pools.boundary):
            k = rng.uniform(0, 10) * s
            while k < ln.length:
                if rng.random() < biome["reed_prob"]:
                    q = ln.interpolate(k)
                    reeds.append((q.x, q.y, rng.uniform(0, 180)))
                k += rng.uniform(9, 16) * s
        inner = pools.buffer(-6 * s)
        if not inner.is_empty and biome["lily_area"]:
            minx, miny, maxx, maxy = inner.bounds
            for _ in range(int(inner.area / (biome["lily_area"] * s * s))):
                x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
                if inner.contains(Point(x, y)) and (not shape.contains(Point(x, y)) or rng.random() < 0.3):
                    lilies.append((x, y, rng.uniform(2.5, 5) * s))
    return reeds, lilies


def _bridges_over_water(s, city, ext_roads, internal, river, river_line, forts, fort_bridges):
    """Brücken über den Fluss samt Festungsbrücken. Keine Überlagerungen auf dem Wasser: Stege und Schiffe weichen
    allen Brücken (auch der Festungsbrücke) und den Wasserrädern."""
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
    return bridges


def _resolve_overlaps(s, city, bridges, ext_roads, forts, light, houses, trees):
    """Abschlussprüfung gegen Überlagerungen: Häuser nicht auf Brücken oder Landstraßen, Werften mit freier Ausfahrt,
    Bäume auf nichts anderem. Liefert (Vorstadthäuser, Bäume); Stadt und Schiffe werden in city angepasst."""
    bz = unary_union([ln.buffer(w / 2 + 2 * s) for ln, w in bridges]) if bridges else Polygon()
    rz = unary_union([ln.buffer(w / 2 + 1.5 * s) for ln, w in ext_roads]) if ext_roads else Polygon()
    lifts = [f["lift"]["area"].buffer(3 * s) for f in forts if f.get("lift")]   # Aufzug an der Plateaukante
    keep = unary_union([bz, rz] + lifts)
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
                        + [f["fort"] for f in forts] + ([light["area"]] if light else []))
    shapely.prepare(solid)
    trees = [tr for tr in trees if not solid.intersects(Point(tr[0], tr[1]).buffer(tr[2] * 0.6))]
    city["yard_trees"] = [tr for tr in city["yard_trees"] if not solid.intersects(Point(tr[0], tr[1]).buffer(tr[2] * 0.6))]
    return houses, trees


def custom_wall(cfg, W, rot):
    """Selbst gezeichnete Mauer (mauer.punkte, % der fertigen Karte) in Kartenkoordinaten: Eckpunkte, Türme und
    Tore. None, solange weniger als drei Punkte gezeichnet sind. Den Umriss bildet erst close_custom."""
    pts = cfg["mauer"].get("punkte") or []
    if len(pts) < 3:
        return None
    a = math.radians(-rot)                      # die fertige Karte ist um rot gedreht: zurückdrehen
    c = W / 2

    def internal(px, py):
        x, y = px / 100 * W - c, py / 100 * W - c
        return (c + x * math.cos(a) - y * math.sin(a), c + x * math.sin(a) + y * math.cos(a))
    corners = [internal(p[0], p[1]) for p in pts]
    if not any(p[2] == "tor" for p in pts):
        raise ValueError("Die gezeichnete Mauer braucht mindestens ein Tor (Taste T).")
    return {"corners": corners,
            "towers": [Point(q) for q, p in zip(corners, pts) if p[2] == "turm"],
            "gates": [Point(q) for q, p in zip(corners, pts) if p[2] == "tor"]}


def close_custom(custom, sea, W, s):
    """Umriss aus der gezeichneten Mauer. Enden beide Mauerenden an der Küste (beim Hochplateau: an der Kante),
    ist dort die Stadt offen - Küste bzw. Felswand sind die Mauer: das Land wird entlang der Mauer geteilt, die
    Stadt ist das Stück auf der Mauerseite. Sonst schließt sich der Ring vom letzten zum ersten Punkt."""
    corners = custom["corners"]
    ring = Polygon(corners)
    shape = None
    reach = 40 * s                              # so nah muss ein Mauerende am Meer bzw. an der Kante liegen
    if sea is not None and not sea.is_empty and len(corners) >= 2:
        a, b = Point(corners[0]), Point(corners[-1])
        if a.distance(sea) < reach and b.distance(sea) < reach:
            path = LineString(corners)
            if not path.is_simple:
                raise ValueError("Die gezeichnete Mauer kreuzt sich selbst - bitte die Punkte neu setzen.")

            def into_sea(p):                    # Mauerende bis ins Wasser verlängern
                q = nearest_points(sea, p)[0]
                d = unit((q.x - p.x, q.y - p.y)) if q.distance(p) > 0.5 else (0.0, 0.0)
                return (q.x + d[0] * 12 * s, q.y + d[1] * 12 * s)
            cut = LineString([into_sea(a)] + list(corners) + [into_sea(b)])
            land = box(0, 0, W, W).difference(sea)
            pieces = [pc for poly in polys(land) for pc in polys(split(poly, cut))]
            if len(pieces) > 1:
                inner = ring.buffer(0)
                best = max(pieces, key=lambda pc: pc.intersection(inner).area)
                # das gewählte Stück muss die Mauer wirklich umschließen (nicht das ganze übrige Land)
                if best.area < 2.5 * max(inner.area, 1) and best.intersection(inner).area > 0.5 * inner.area:
                    shape = best
    if shape is None:
        if not ring.is_valid:
            raise ValueError("Die gezeichnete Mauer kreuzt sich selbst - bitte die Punkte neu setzen.")
        shape = ring
    if shape.area < (120 * s) ** 2:
        raise ValueError("Die gezeichnete Mauer umschließt zu wenig Fläche für eine Stadt.")
    center = polylabel(shape, 2 * s)             # Punkt tief im Inneren (auch bei verwinkelten Mauern)
    return dict(custom, shape=shape, center=(center.x, center.y), radius=math.sqrt(shape.area / math.pi),
                offen=shape is not ring)


def terrain_model(cfg, W, s, rot, terrain, pools, oases, biome, hints):
    """Kartenmodell nur mit Gelände (Land, Meer, Inseln, Fluss, Tümpel, Oasen) ohne Stadt und Umland."""
    empty = CityBuilder.empty_out()
    empty.update(shape=Polygon(), city_land=Polygon())
    return {
        "name": cfg["name"], "W": W, "s": s, "rot": rot, "cfg": cfg,
        "sea": terrain["sea"], "river": terrain["river"], "land": terrain["land"], "water": terrain["water"],
        "fields": [], "forest": Polygon(), "trees": [], "suburbs": [], "ext_roads": [], "bridges": [],
        "forts": [], "biome": biome, "pools": pools, "reeds": [], "lilies": [], "oases": oases, "rocks": [],
        "dunes": [], "floes": [], "river_line": terrain["river_line"], "mines": [], "paths": [],
        "plateau": False, "plateau_level": None, "plateau_oben": False, "gelaende_nur": True, "hints": hints, **empty,
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
        builder.hint(f"Kein Platz für den Friedhof '{spec['name']}' gefunden.")
        return None
    chapel = builder._cemetery(poly, "#8f8a80", -1)
    if chapel is None:
        return None
    chapel["ridges"], chapel["shade"] = roof(chapel["poly"])
    chapel["landmark"] = True
    builder.out["buildings"].append(chapel)
    _outside_label(builder, spec, poly, B / 2 + 6 * s)
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
            poly = oriented_rect(cx, cy, tx, ty, L, B)
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


def _outside_label(builder, spec, poly, lift):
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
        builder.hint(f"Kein Platz für die Windmühle '{spec['name']}' gefunden.")
        return None
    c = area.centroid
    tower = c.buffer(10 * s, quad_segs=4)           # Achteck
    mill = {"poly": tower, "color": "#8a6a4a", "district": -1, "landmark": True}
    mill["ridges"], mill["shade"] = roof(tower)
    builder.out["buildings"].append(mill)
    builder.out["windmills"].append({"x": c.x, "y": c.y, "len": 24 * s, "angle": rng.uniform(0, 360)})   # Windrichtung
    _outside_label(builder, spec, tower, 30 * s)
    return area


def outside_farm(rng, s, spec, builder, ext_roads, shape, water, pools, taken):
    """Bauernhof an einer Landstraße: Wohnhaus und großer Stall im Winkel um einen umzäunten Hofplatz."""
    L, B = rng.uniform(70, 85) * s, rng.uniform(52, 62) * s
    area = roadside_spot(rng, s, L, B, ext_roads, shape, water, pools, taken, start=80, gap=20, max_wet=0.1)
    if area is None:
        builder.hint(f"Kein Platz für den Bauernhof '{spec['name']}' gefunden.")
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
    _outside_label(builder, spec, area, B / 2 + 6 * s)
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


def make_dunes(rng, s, free):
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
