"""Stadtgrundriss: Mauer, Tore, Straßen, Viertel, Gebäude und besondere Orte."""
import math

import numpy as np
import shapely
import shapely.affinity
from shapely.geometry import LineString, MultiPoint, Point, Polygon, box
from shapely.ops import nearest_points, polylabel, unary_union

from .config import place_info, to_canonical
from .shapes import cross_in_rect, house_shape
from .geo import (Noise1D, axes, blob, clean, cut, fit_rect, lines, min_width, points, polys, roof, subdivide,
                  unit, vlen)
from .roofs import shade as shade_hex
from .styles import BIG_LANDMARKS, BIOMES, DISTRICT_TYPES, FORT_TYPES, LANDMARK_COLORS

COMPACT = {"friedhof", "kaserne", "tempel", "palast", "kathedrale"}


def ship_footprint(cx, cy, length, width, angle_deg):
    """Grundfläche eines Schiffs als gedrehtes Rechteck."""
    a = math.radians(angle_deg)
    u, v = np.array([math.cos(a), math.sin(a)]), np.array([-math.sin(a), math.cos(a)])
    c = np.array([cx, cy])
    return Polygon([c - u * length / 2 - v * width / 2, c + u * length / 2 - v * width / 2,
                    c + u * length / 2 + v * width / 2, c - u * length / 2 + v * width / 2])
# Hausmaße: kürzeste Seite in px (bei 2000 px Bildgröße) und größtes Verhältnis lange/kurze Seite
MIN_HOUSE = 8.0
MAX_HOUSE_RATIO = 3.2

# Ohne angegebene Viertel: eine einzige Wohnbebauung ohne Namen (es wird nichts beschriftet)
UNNAMED_DISTRICT = {"name": "", "typ": "wohn"}


def city_radius(W, population):
    """Fläche wächst mit der Einwohnerzahl; 6000 Einwohner ~ 0.22 der Kartenbreite."""
    return W * max(0.06, min(0.3, 0.222 * math.sqrt(max(population, 100) / 6000)))


def make_shape(rng, center, r):
    cx, cy = center
    n = rng.randint(9, 12)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n + rng.uniform(-0.15, 0.15)
        rad = r * rng.uniform(0.9, 1.08)
        pts.append((cx + math.cos(a) * rad * 0.9, cy + math.sin(a) * rad * 1.12))
    return Polygon(pts).buffer(0)


def bezier(p0, p1, rng, bend=0.2, n=30):
    p0, p1 = np.array(p0, float), np.array(p1, float)
    d = p1 - p0
    ctrl = (p0 + p1) / 2 + np.array([-d[1], d[0]]) * rng.uniform(-bend, bend)
    ts = np.linspace(0, 1, n)
    return LineString([tuple((1 - t) ** 2 * p0 + 2 * (1 - t) * t * ctrl + t * t * p1) for t in ts])


def _angdist(a, b):
    x = abs(a - b) % (2 * math.pi)
    return min(x, 2 * math.pi - x)


def wall_angle(shape, p):
    ext = shape.exterior
    d = ext.project(p)
    a, b = ext.interpolate(d - 4), ext.interpolate(d + 4)
    return math.degrees(math.atan2(b.y - a.y, b.x - a.x))


class CityBuilder:
    def __init__(self, cfg, rng, W, s, terrain, center, r, rot):
        self.cfg, self.rng, self.W, self.s = cfg, rng, W, s
        self.t = terrain
        self.center, self.r, self.rot = center, r, rot
        self.out = {
            "buildings": [], "streets": [], "paved": [], "internal_roads": [], "plazas": [],
            "grounds": [], "graves": [], "fountains": [], "deferred": [],
            "great_gate": None, "terrace_walls": [], "stairs": [], "wells": [], "stalls": [],
            "towers": [], "gates": [], "wall": [], "yard_trees": [], "labels": [], "piers": [],
            "ships": [], "legend": [], "districts": [], "wheels": [], "windmills": [], "haystacks": [],
        }

    def roof_color(self, st):
        """Biotop-typische Dächer (Reet, Schnee, Lehm) überwiegen, die Viertelfarbe bleibt als Beimischung."""
        biome = BIOMES[self.cfg["gelaende"]["biotop"]]
        thatch = biome["thatch"]
        if thatch and self.rng.random() < biome["roof_share"]:
            return self.rng.choice(thatch)
        return self.rng.choice(st["palette"])

    # ---------------------------------------------------------------- Umriss
    def outline(self):
        t = self.t
        given = self.t.get("shape")   # im Gebirge vom Generator vorgegeben (Felskessel)
        self.shape = given if given is not None else make_shape(self.rng, self.center, self.r)
        land = box(0, 0, self.W, self.W).difference(t["water"])
        self.city_land = self.shape.intersection(land)
        self.sides = sorted(clean(self.city_land, 3000 * self.s ** 2), key=lambda p: -p.area)
        self.city_land = unary_union(self.sides)

    def side_of(self, p):
        p = p if isinstance(p, Point) else Point(p)
        return min(range(len(self.sides)), key=lambda i: self.sides[i].distance(p))

    # ---------------------------------------------------------------- Mauer & Tore
    def walls_and_gates(self):
        s, W, t = self.s, self.W, self.t
        walled = self.cfg["mauer"].get("vorhanden", True)
        count = int(self.cfg["mauer"].get("tore", 4))
        c = np.array(self.center)
        frame = box(0, 0, W, W).buffer(-40 * s)
        cands = []
        for deg in range(0, 360, 2):
            a = math.radians(deg)
            d = np.array([math.cos(a), math.sin(a)])
            pts_ = points(LineString([c, c + d * W * 2]).intersection(self.shape.exterior))
            if not pts_:
                continue
            p = min(pts_, key=lambda q: q.distance(Point(c)))
            if p.distance(t["water"]) < 45 * s or not frame.contains(p):
                continue
            probe = LineString([(p.x, p.y), (p.x + d[0] * 180 * s, p.y + d[1] * 180 * s)])
            if probe.intersects(t["water"]):
                continue
            cands.append((a, p, d))
        gates = []
        if cands and count > 0:
            gates.append(self.rng.choice(cands))
            while len(gates) < count:
                best = max(cands, key=lambda cd: min(_angdist(cd[0], g[0]) for g in gates))
                if min(_angdist(best[0], g[0]) for g in gates) < 0.35:
                    break
                gates.append(best)
        self.gates = gates
        self.walled = walled
        if not walled:
            return
        wall = self.shape.exterior.difference(t["water"].buffer(4 * s))
        self.out["wall"] = [ln for ln in lines(wall) if ln.length > 20 * s]
        # Türme zuerst an die Mauerenden (am Wasser), dann an die Ecken des Umrisses. Ein Turm braucht Abstand zu
        # Toren und anderen Türmen: Ecken dicht an einem Mauerende ergaben sonst zwei sich überlappende Türme.
        tower_pts = []
        for ln in self.out["wall"]:
            tower_pts += [Point(ln.coords[0]), Point(ln.coords[-1])]
        tower_pts += [Point(x, y) for x, y in list(self.shape.exterior.coords)[:-1]]
        wall_u = unary_union(self.out["wall"])
        placed = []
        for p in tower_pts:
            if p.distance(wall_u) > 2 * s or not box(0, 0, W, W).contains(p):
                continue
            if any(p.distance(g[1]) < 35 * s for g in gates) or any(p.distance(q) < 28 * s for q in placed):
                continue
            placed.append(p)
            self.out["towers"].append((p.x, p.y, wall_angle(self.shape, p)))
        for _, p, _ in gates:
            self.out["gates"].append((p.x, p.y, wall_angle(self.shape, p)))

    # ---------------------------------------------------------------- Straßen
    def external_roads(self):
        s, W = self.s, self.W
        sea = self.t["sea"]
        frame = box(-30, -30, W + 30, W + 30)
        roads = []
        for a, p, d in self.gates:
            noise = Noise1D(self.rng)
            pts = [(p.x, p.y)]
            for i in range(1, 600):
                ang = a + 0.5 * noise.fbm(i * 0.035)
                q = (pts[-1][0] + math.cos(ang) * 20 * s, pts[-1][1] + math.sin(ang) * 20 * s)
                if sea is not None and sea.contains(Point(q)):
                    break
                if self.shape.contains(Point(q)):
                    break
                pts.append(q)
                if not frame.contains(Point(q)):
                    break
            if len(pts) > 2:
                roads.append((LineString(pts), 15 * s))
        return roads

    def internal_roads(self):
        s, t = self.s, self.t
        roads, plazas = [], []
        plaza_centers = {}
        if t["river"] is not None and len(self.sides) > 1:
            rl = t["river_line"]
            c = Point(self.center)
            m = rl.interpolate(rl.project(c))
            d0 = rl.project(m)
            a, b = rl.interpolate(max(0, d0 - 8)), rl.interpolate(d0 + 8)
            tx, ty = unit((b.x - a.x, b.y - a.y))
            nx, ny = -ty, tx
            far = self.W * 0.3
            long = LineString([(m.x - nx * far, m.y - ny * far), (m.x + nx * far, m.y + ny * far)])
            segs = lines(long.intersection(t["river"]))
            if segs:
                seg = min(segs, key=lambda ln: ln.distance(m))
                ends = []
                for x, y in (seg.coords[0], seg.coords[-1]):
                    o = unit((x - m.x, y - m.y))
                    ends.append(((x + o[0] * 10 * s, y + o[1] * 10 * s), o))
                main_side = 0
                for (e, o) in ends:
                    side = self.side_of(e)
                    pc = (e[0] + o[0] * 55 * s, e[1] + o[1] * 55 * s)
                    rad = (52 if side == main_side else 40) * s * min(1.0, (self.r / (0.222 * self.W)) ** 0.6)
                    pl = blob(self.rng, pc[0], pc[1], rad, rough=0.18).intersection(self.city_land)
                    plazas.append(pl)
                    plaza_centers[side] = pc
                    roads.append((LineString([e, pc]), 16 * s))
                roads.append((LineString([ends[0][0], ends[1][0]]), 16 * s))
                self.bridge_ends = [e for e, _ in ends]
        if not plaza_centers:
            pc = self.center if self.city_land.contains(Point(self.center)) else \
                nearest_points(self.city_land, Point(self.center))[0].coords[0]
            plazas.append(blob(self.rng, pc[0], pc[1], 60 * s * min(1.0, (self.r / (0.222 * self.W)) ** 0.6),
                               rough=0.18).intersection(self.city_land))
            for i in range(len(self.sides)):
                plaza_centers[i] = pc
        self.plaza_centers = plaza_centers
        # Torstraßen
        for _, p, _ in self.gates:
            side = self.side_of(p)
            target = plaza_centers.get(side)
            if target is None:
                target = self.sides[side].representative_point().coords[0]
            ln = bezier((p.x, p.y), target, self.rng)
            for piece in lines(ln.intersection(self.sides[side].buffer(2 * s))):
                roads.append((piece, 14 * s))
        # Ringstraße innen an der Mauer
        if self.walled:
            for side in self.sides:
                for ring in lines(side.buffer(-32 * s).boundary):
                    if ring.length > 60 * s:
                        roads.append((ring, 9 * s))
        # Gebirge: Hauptstraße vom Marktplatz hinauf zum großen Tor in der Felswand
        if self.t.get("mountain"):
            gate = self.great_gate()
            if gate is not None:
                side = self.side_of(gate)
                target = plaza_centers.get(side) or self.sides[side].representative_point().coords[0]
                ln = bezier(target, gate, self.rng, bend=0.12)
                for piece in lines(ln.intersection(self.sides[side].buffer(2 * s))):
                    roads.append((piece, 16 * s))
        self.out["plazas"] = [p for p in plazas if not p.is_empty]
        return roads

    def great_gate(self):
        """Zwergentor: am obersten Punkt der Felswand (intern liegt der Berg im Norden)."""
        s = self.s
        edge = [ln for ln in lines(self.city_land.boundary.intersection(self.t["sea"].buffer(3 * s)))
                if ln.length > 60 * s]
        if not edge:
            return None
        top = Point(self.center[0], self.city_land.bounds[1] - 50 * s)
        ln = min(edge, key=lambda e: e.distance(top))
        d = min(max(ln.project(top), 25 * s), ln.length - 25 * s)
        p, q = ln.interpolate(d), ln.interpolate(min(ln.length, d + 4))
        tx, ty = unit((q.x - p.x, q.y - p.y))
        nx, ny = -ty, tx
        if not self.t["sea"].contains(Point(p.x + nx * 20 * s, p.y + ny * 20 * s)):
            nx, ny = -nx, -ny
        self.out["great_gate"] = (p.x, p.y, math.degrees(math.atan2(ny, nx)))
        return (p.x - nx * 4 * s, p.y - ny * 4 * s)

    # ---------------------------------------------------------------- Viertel
    def district_seeds(self, specs):
        s, r = self.s, self.r
        c = np.array(self.center)
        t = self.t
        seeds = []
        for spec in specs:
            typ, lage = spec["typ"], spec.get("lage")
            p = None
            if lage:
                p = c + np.array(to_canonical(lage, self.rot)) * r * 0.6
            elif typ == "hafen" and t["sea"] is not None:
                if t["river_line"] is not None:
                    inside = [q for q in t["river_line"].coords if self.shape.contains(Point(q))]
                    mouth = min(inside, key=lambda q: q[1]) if inside else (c[0], c[1] - r)
                    side = self.rng.choice([-1, 1])
                    p = np.array(mouth) + np.array([side * 110 * s, 160 * s])
                else:
                    p = np.array([c[0], t["coast_y"](c[0]) + 70 * s])
            elif typ == "fischer" and t["sea"] is not None:
                x = c[0] + self.rng.choice([-1, 1]) * r * 0.5
                p = np.array([x, t["coast_y"](x) + 60 * s])
            elif typ == "bauern":
                p = c + np.array([self.rng.uniform(-0.3, 0.3), 0.65]) * r
            if p is None:
                best, bd = None, -1
                minx, miny, maxx, maxy = self.city_land.bounds
                for _ in range(40):
                    q = (self.rng.uniform(minx, maxx), self.rng.uniform(miny, maxy))
                    if not self.city_land.contains(Point(q)):
                        continue
                    dd = min([math.dist(q, sd) for sd in seeds] or [1e9])
                    if dd > bd:
                        best, bd = q, dd
                p = np.array(best if best else self.center)
            pp = Point(p)
            if not self.city_land.buffer(-15 * s).contains(pp):
                inner = self.city_land.buffer(-25 * s)
                pp = nearest_points(inner if not inner.is_empty else self.city_land, pp)[0]
            for sd in seeds:
                if math.dist((pp.x, pp.y), sd) < 30 * s:
                    pp = Point(pp.x + 31 * s, pp.y)
            seeds.append((pp.x, pp.y))
        return seeds

    def _voronoi(self, seeds, idx, area):
        """Teilt 'area' per Voronoi auf die Saatpunkte idx auf; jede Uferseite nur an Viertel dieser Seite."""
        out = {i: [] for i in idx}
        if not idx:
            return out
        if len(idx) == 1:
            out[idx[0]] = clean(area, 1)
            return out
        W = self.W
        # Winziger Versatz: exakt gleiche x/y-Werte lassen GEOS sonst kaputte Zellen erzeugen
        pts = MultiPoint([(seeds[i][0] + 0.37 * (k + 1), seeds[i][1] + 0.61 * (k + 1)) for k, i in enumerate(idx)])
        cells = shapely.voronoi_polygons(pts, extend_to=box(-W, -W, 2 * W, 2 * W))
        side = {i: self.side_of(seeds[i]) for i in idx}
        for cell in cells.geoms:
            # Ein Innenpunkt der Zelle liegt immer am nächsten an ihrem eigenen Saatpunkt
            rc = cell.representative_point()
            owner = min(idx, key=lambda i: rc.distance(Point(seeds[i])))
            for piece in clean(cell.intersection(area), 1):
                rp = piece.representative_point()
                ps = self.side_of(rp)
                if side[owner] != ps:
                    same = [i for i in idx if side[i] == ps]
                    if same:
                        out[min(same, key=lambda i: rp.distance(Point(seeds[i])))].append(piece)
                        continue
                out[owner].append(piece)
        return out

    def districts(self):
        specs = self.cfg["viertel"] or [dict(UNNAMED_DISTRICT)]
        has_water = not self.t["water"].is_empty
        for sp in specs:
            sp.setdefault("typ", "wohn")
            if self.t.get("mountain") and sp["typ"] in ("hafen", "fischer"):
                new = "markt" if sp["typ"] == "hafen" else "handwerk"
                print(f"Hinweis: '{sp.get('name')}' ({sp['typ']}) passt nicht ins Gebirge - wird als {new} gebaut.")
                sp["typ"] = new
            if sp["typ"] == "hafen" and not has_water:
                print(f"Hinweis: '{sp.get('name')}' ist ein Hafen, aber es gibt kein Wasser - wird als Markt gebaut.")
                sp["typ"] = "markt"
        seeds = self.district_seeds(specs)
        self.seeds = seeds
        self.district_list = [{"name": sp.get("name", ""), "typ": sp["typ"], "poly": Polygon()} for sp in specs]
        idx = list(range(len(specs)))
        area = self.city_land
        harbor = self.carve_harbor()
        if harbor is not None:
            hi = next(i for i, sp in enumerate(specs) if sp["typ"] == "hafen")
            self.district_list[hi]["poly"] = harbor
            idx.remove(hi)
            area = area.difference(harbor)
            # Saatpunkte, die im Hafen gelandet sind (z.B. Lage Richtung Meer), auf Land davor schieben
            inner = area.buffer(-30 * self.s)
            inner = inner if not inner.is_empty else area
            for i in idx:
                p = Point(seeds[i])
                if harbor.buffer(20 * self.s).contains(p) or not inner.contains(p):
                    q = nearest_points(inner, p)[0]
                    seeds[i] = (q.x, q.y)
            for i in idx:   # auseinanderrücken, falls zwei Punkte zusammenfallen
                for j in idx:
                    if j < i and math.dist(seeds[i], seeds[j]) < 40 * self.s:
                        q = nearest_points(inner, Point(seeds[i][0], seeds[i][1] + 60 * self.s))[0]
                        seeds[i] = (q.x, q.y)
        for i, ps in self._voronoi(seeds, idx, area).items():
            self.district_list[i]["poly"] = unary_union(ps) if ps else Polygon()
        for d in self.district_list:
            if d["poly"].is_empty:
                print(f"Hinweis: Viertel '{d['name']}' hat keinen Platz gefunden.")
        self.out["districts"] = self.district_list

    def carve_harbor(self):
        """Der Hafen wird ein breiter Kai-Streifen entlang Fluss und Küste auf einer Uferseite."""
        dl = self.district_list
        hi = next((i for i, d in enumerate(dl) if d["typ"] == "hafen"), None)
        if hi is None or self.t["water"].is_empty:
            return None
        s, W = self.s, self.W
        side = self.side_of(self.seeds[hi])
        fishers = [self.side_of(self.seeds[i]) for i, d in enumerate(dl) if d["typ"] == "fischer"]
        free = [i for i in range(len(self.sides)) if i not in fishers]
        if side in fishers and free:
            side = free[0]
        ends = getattr(self, "bridge_ends", None)
        limit_y = (min(e[1] for e in ends) if ends else self.center[1]) - 60 * s
        harbor = self.sides[side].intersection(self.t["water"].buffer(150 * s))
        if ends:   # Hafen nur flussabwärts der Brücke
            harbor = harbor.intersection(box(-W, -W, 2 * W, limit_y))
        harbor = unary_union(clean(harbor, 2000 * s * s))
        if harbor.is_empty:
            return None
        # Saatpunkt in den Hafen legen, damit die Uferseiten-Logik stimmt
        rp = harbor.representative_point()
        self.seeds[hi] = (rp.x, rp.y)
        return harbor

    def terraces(self, main):
        """Gebirge: Stützmauern quer zum Hang (Berg liegt intern im Norden), Treppen an den Hauptstraßen."""
        s, rng = self.s, self.rng
        minx, miny, maxx, maxy = self.city_land.bounds
        n = 3 if (maxy - miny) < 550 * s else 4
        noise = Noise1D(rng)
        rows = []
        for k in range(1, n + 1):
            y0 = miny + (maxy - miny) * k / (n + 1)
            rows.append(LineString([(x, y0 + 22 * s * noise.fbm(x / (180 * s) + k * 7))
                                    for x in np.arange(minx - 20 * s, maxx + 20 * s, 15 * s)]))
        terr = unary_union(rows).intersection(self.city_land.buffer(-2 * s))
        self.out["terrace_walls"] = [ln for ln in lines(terr.difference(main.buffer(1 * s))) if ln.length > 8 * s]
        for ln, w in self.out["internal_roads"]:
            if w >= 8 * s:
                self.out["stairs"] += [(seg, w) for seg in lines(ln.intersection(terr.buffer(7 * s)))]
        return terr

    # ---------------------------------------------------------------- Bebauung
    def buildings(self, internal):
        s, rng = self.s, self.rng
        s2 = s * s
        main = unary_union([ln.buffer(w / 2) for ln, w in internal]).intersection(self.city_land)
        self.main_streets = main
        blockers = [main, unary_union(self.out["plazas"]), self.t["water"].buffer(3 * s)]
        if self.walled:
            blockers.append(self.shape.exterior.buffer(30 * s))
        if self.t["biome"]["terraces"]:
            blockers.append(self.terraces(main).buffer(4 * s))
        blocker = unary_union(blockers)
        streets = [main, unary_union(self.out["plazas"])]
        self.blocks = []
        pools = self.t.get("pools")
        if pools is not None and pools.is_empty:
            pools = None
        if pools is not None:
            shapely.prepare(pools)
        dl = self.district_list
        for d in dl:
            d["cell"] = d["poly"]
        # Gepflasterte Viertel (Hafen) behalten ihre Fläche
        quarters = []
        paved = [i for i, d in enumerate(dl) if DISTRICT_TYPES.get(d["typ"], {}).get("paved")]
        for di in paved:
            self.out["paved"].append(dl[di]["poly"])
            region = dl[di]["poly"].difference(blocker).difference(self.t["water"].buffer(40 * s))
            quarters += [(p, di) for p in clean(region, 300 * s2)]
        # Übrige Fläche erst in Quartiere zerlegen und diese ganz einem Viertel zuordnen,
        # damit Viertelgrenzen auf Gassen statt quer durch Häuserblöcke laufen.
        rest = self.city_land.difference(blocker).difference(unary_union([dl[i]["poly"] for i in paved]))
        cands = [i for i in range(len(dl)) if i not in paved and not dl[i]["poly"].is_empty]
        for piece in clean(rest, 300 * s2):
            qs = subdivide(piece, 16000 * s2, 8 * s, rng, min_area=250 * s2, var=0.25)
            streets.append(piece.difference(unary_union(qs)) if qs else piece)
            for q in qs:
                rp = q.representative_point()
                owner = next((i for i in cands if dl[i]["poly"].contains(rp)), None)
                if owner is None and cands:
                    owner = min(cands, key=lambda i: dl[i]["poly"].distance(rp))
                if owner is not None:
                    quarters.append((q, owner))
        # kleine Viertel, die kein Quartier abbekommen haben, erhalten das am stärksten überlappende
        for i in cands:
            if any(o == i for _, o in quarters):
                continue
            counts = {}
            for _, o in quarters:
                counts[o] = counts.get(o, 0) + 1
            options = [k for k, (q, o) in enumerate(quarters) if o not in paved and counts.get(o, 0) > 1]
            if options:
                k = max(options, key=lambda k: quarters[k][0].intersection(dl[i]["cell"]).area
                        - quarters[k][0].distance(dl[i]["cell"]))
                quarters[k] = (quarters[k][0], i)
        for i in cands:
            mine = [q.buffer(6 * s) for q, o in quarters if o == i]
            dl[i]["poly"] = unary_union(mine).buffer(-6 * s) if mine else Polygon()
        for quarter, di in quarters:
            d = dl[di]
            st = DISTRICT_TYPES.get(d["typ"], DISTRICT_TYPES["wohn"])
            poor = st.get("poor", False)
            lot = st["lot"] * s2
            for piece in clean(quarter, lot * 0.5):
                blocks = subdivide(piece, st["block"] * s2, st["alley"] * s, rng, min_area=lot * 0.5)
                streets.append(piece.difference(unary_union(blocks)) if blocks else piece)
                for blk in blocks:
                    entry = {"poly": blk, "district": di, "ids": []}
                    self.blocks.append(entry)
                    # Armenviertel: gleichmäßigere Parzellen, sonst entstehen zu viele zu schmale Restflächen
                    lots = subdivide(blk, lot, 0, rng, min_area=lot * 0.12, var=0.25 if poor else 0.5, jitter=0.1)
                    edge = blk.exterior.buffer(0.8 * s)
                    for lp in lots:
                        # über Sumpfwasser: Pfahlhäuser mit Wasser dazwischen, etwas lockerer
                        wet = pools is not None and pools.contains(lp.representative_point())
                        perim = (not st["perimeter"]) or lp.exterior.intersection(edge).length > 2 * s
                        back = not perim and rng.random() < st.get("inner", 0.0) * (0.3 if wet else 1)
                        if (perim and rng.random() < st["density"] * (0.75 if wet else 1)) or back:
                            inset = (4 if d["typ"] == "hafen" else 2.4 if wet else 1.0) * s
                            for piece in clean(lp.buffer(-inset, join_style="mitre"), lot * 0.12):
                                # nur erlaubte geometrische Formen mit Mindestbreite; zu schmale Restflächen bleiben Hof
                                bp, form = house_shape(piece, rng, MIN_HOUSE * s, MAX_HOUSE_RATIO,
                                                       special_chance=0.0 if poor else 0.12)
                                if bp is not None and poor:   # Hütten stehen schief auf dem Grundstück
                                    tilt = shapely.affinity.rotate(bp, rng.uniform(-8, 8), origin="centroid")
                                    if piece.buffer(0.6 * s).contains(tilt):
                                        bp = tilt
                                if bp is not None:
                                    entry["ids"].append(len(self.out["buildings"]))
                                    self.out["buildings"].append(
                                        {"poly": bp, "form": form, "color": self.roof_color(st), "district": di,
                                         "poor": poor})
                        elif not perim and rng.random() < 0.35:
                            c = lp.representative_point()
                            rad = max(5 * s, min(14 * s, math.sqrt(lp.area) * 0.4))
                            self.out["yard_trees"].append((c.x, c.y, rad))
        self.out["streets"] = [unary_union(streets).intersection(self.city_land)]
        self.connect_to_streets()

    def connect_to_streets(self, landmarks=False):
        """Jedes Haus muss an eine Straße oder einen Platz grenzen. Häuser ohne Anschluss werden zur nächsten
        Straße geschoben, wenn dort Platz ist; sonst entfallen sie (die Fläche wird Hof)."""
        s = self.s
        net = unary_union(self.out["streets"] + self.out["plazas"] + self.out["paved"]
                          + [g for g, kind in self.out["grounds"] if kind == "plaza"])
        shapely.prepare(net)
        alive = [b for b in self.out["buildings"] if not b.get("removed")]
        tree = shapely.STRtree([b["poly"] for b in alive])
        moved = dropped = 0
        for i, b in enumerate(alive):
            if landmarks != bool(b.get("landmark")) or b.get("courtyard") or b.get("poor"):
                # erst normale Häuser, nach dem Platzieren die Sondergebäude; Kapellen/Festung über Hof erschlossen;
                # Hütten im Armenviertel stehen auch in den Hinterhöfen, erreichbar über Trampelpfade
                continue
            poly = b["poly"]
            d = poly.distance(net)
            if d <= 2 * s:
                continue
            p_house, p_net = nearest_points(poly, net)
            dx, dy = p_net.x - p_house.x, p_net.y - p_house.y
            k = (d - 0.8 * s) / d
            cand = shapely.affinity.translate(poly, dx * k, dy * k)
            near = [j for j in tree.query(cand.buffer(0.8 * s)) if j != i]
            ok = (self.city_land.contains(cand) and cand.intersection(net).area < 0.5 * s * s
                  and not any(cand.buffer(0.8 * s).intersects(alive[j]["poly"]) for j in near))
            if ok:
                b["poly"] = cand
                moved += 1
            elif landmarks:
                continue   # Sondergebäude nie streichen
            else:
                b["removed"] = True
                dropped += 1
        self.stats = {k: self.stats.get(k, 0) + v for k, v in (("verschoben", moved), ("entfernt", dropped))}             if hasattr(self, "stats") else {"verschoben": moved, "entfernt": dropped}

    def _replace_block(self, blk, color, label_src, inset):
        # erst prüfen, ob ein rechteckiges Sondergebäude hineinpasst, dann den Block räumen
        parts = clean(blk["poly"].buffer(-inset, join_style="mitre"), 10)
        if not parts:
            return None
        poly = fit_rect(max(parts, key=lambda p: p.area), 2 * MIN_HOUSE * self.s)   # Sondergebäude ebenfalls rechteckig
        if poly is None:
            return None
        for i in blk["ids"]:
            self.out["buildings"][i]["removed"] = True
        blk["ids"] = []
        self.out["yard_trees"] = [t for t in self.out["yard_trees"] if not blk["poly"].contains(Point(t[0], t[1]))]
        special = {"tempel": self._temple, "kaserne": self._barracks, "friedhof": self._cemetery,
                   "rathaus": self._townhall, "palast": self._palace,
                   "kathedrale": self._cathedral}.get(label_src)
        if special:
            b = special(poly, color, blk["district"])
            if b is not None:
                self.out["buildings"].append(b)
                self.out["buildings"] += b.pop("annex", [])   # Anbauten (Rathaus-, Domtürme) über dem Hauptbau zeichnen
                return b
        if label_src == "adelshaus":   # Herrenhaus mit Garten
            c = poly.centroid
            poly = shapely.affinity.scale(poly, 0.62, 0.62, origin=c)
            for _ in range(6):
                q = blk["poly"].buffer(-inset).representative_point()
                x = q.x + self.rng.uniform(-30, 30) * self.s
                y = q.y + self.rng.uniform(-30, 30) * self.s
                if blk["poly"].buffer(-6 * self.s).contains(Point(x, y)) and not poly.buffer(6 * self.s).contains(Point(x, y)):
                    self.out["yard_trees"].append((x, y, self.rng.uniform(7, 12) * self.s))
        b = {"poly": poly, "color": color, "district": blk["district"]}
        self.out["buildings"].append(b)
        return b

    # ---------------------------------------------------------------- Sonderblöcke
    def _temple(self, area, color, district):
        """Tempel mit gepflastertem Vorplatz und Brunnen."""
        s = self.s
        pieces = cut(area, 0.55, 0)
        if len(pieces) < 2:
            return None
        pieces.sort(key=lambda p: p.distance(self.main_streets))
        plaza, rest = pieces[0], unary_union(pieces[1:])
        parts = clean(rest.buffer(-3 * s, join_style="mitre"), 50 * s * s)
        if not parts:
            return None
        self.out["grounds"].append((plaza, "plaza"))
        c = plaza.representative_point()
        self.out["fountains"].append((c.x, c.y, 7 * s))
        hall = cross_in_rect(fit_rect(max(parts, key=lambda p: p.area)) or max(parts, key=lambda p: p.area))
        return {"poly": hall, "form": "kreuz", "color": color, "district": district}

    def _frame(self, rect):
        """Achsen eines rechteckigen Bauplatzes, ausgerichtet zur nächsten Hauptstraße: liefert (o, u, v, L, D)
        mit der Vorderseite bei y = 0 und rect(x0, y0, x1, y1) in Pixeln."""
        o, e1, e2 = axes(rect)
        L, D = vlen(e1), vlen(e2)
        u, v = e1 / L, e2 / D
        front = LineString([o, o + e1]).distance(self.main_streets)
        back = LineString([o + e2, o + e1 + e2]).distance(self.main_streets)
        if back < front:
            o, v = o + e2, -v
        return o, u, v, L, D

    @staticmethod
    def _rect(o, u, v, x0, y0, x1, y1):
        return Polygon([o + u * x0 + v * y0, o + u * x1 + v * y0, o + u * x1 + v * y1, o + u * x0 + v * y1])

    def _townhall(self, area, color, district):
        """Rathaus bzw. Dorfhalle: lange Halle mit Turm zur Straße und gepflastertem Vorplatz mit Brunnen."""
        s = self.s
        o, u, v, L, D = self._frame(area)
        R = lambda *a: self._rect(o, u, v, *a)
        yh = 0.34 * D
        hall = R(0.08 * L, yh, 0.92 * L, 0.95 * D)
        t = min(0.3 * min(L, D), 16 * s)
        tower = R(L / 2 - t / 2, yh - 0.55 * t, L / 2 + t / 2, yh + 0.45 * t)
        court = R(0, 0, L, yh).intersection(area)
        if not court.is_empty:
            self.out["grounds"].append((court, "plaza"))
            if yh - 0.55 * t > 12 * s:
                c = o + u * (L / 2) + v * ((yh - 0.55 * t) / 2)
                self.out["fountains"].append((float(c[0]), float(c[1]), min(6 * s, (yh - 0.55 * t) * 0.3)))
        top = {"poly": tower, "color": shade_hex(color, 0.8), "district": district, "landmark": True}
        return {"poly": hall, "color": color, "district": district, "annex": [top]}

    def _palace(self, area, color, district):
        """Palast: drei Flügel um einen Ehrenhof zur Straße, Eckpavillons, dahinter ein Garten, alles ummauert."""
        s, rng = self.s, self.rng
        o, u, v, L, D = self._frame(area)
        R = lambda *a: self._rect(o, u, v, *a)
        x0, x1, ww = 0.12 * L, 0.88 * L, max(0.17 * L, 12 * s)
        yf, yb0, yb1 = 0.1 * D, 0.42 * D, 0.6 * D
        p = ww * 1.3
        parts = [R(x0, yb0, x1, yb1), R(x0, yf, x0 + ww, yb1), R(x1 - ww, yf, x1, yb1),
                 R(x0 + ww / 2 - p / 2, yf - (p - ww) / 2, x0 + ww / 2 + p / 2, yf + p - (p - ww) / 2),
                 R(x1 - ww / 2 - p / 2, yf - (p - ww) / 2, x1 - ww / 2 + p / 2, yf + p - (p - ww) / 2),
                 R(L / 2 - 0.1 * L, yb0 - 0.04 * D, L / 2 + 0.1 * L, yb1 + 0.03 * D)]
        palace = unary_union(parts).intersection(area)
        if palace.geom_type != "Polygon":
            return None
        self.out["grounds"].append((area, "estate"))
        garden = R(0.05 * L, yb1 + 0.07 * D, 0.95 * L, 0.96 * D)
        if garden.area > 400 * s * s:
            self.out["grounds"].append((garden, "garden"))
            gc = garden.centroid
            self.out["fountains"].append((gc.x, gc.y, 6 * s))
            for y in np.arange(yb1 + 0.1 * D, 0.95 * D, 9 * s):   # Baumalleen an den beiden Gartenseiten
                for x in (0.025 * L, 0.975 * L):
                    q = o + u * x + v * y
                    self.out["yard_trees"].append((float(q[0]), float(q[1]), rng.uniform(3.5, 4.5) * s))
        court = R(x0 + ww, 0, x1 - ww, yb0).intersection(area)
        self.out["grounds"].append((court, "plaza"))
        c = o + u * (L / 2) + v * (yb0 * 0.55)
        self.out["fountains"].append((float(c[0]), float(c[1]), 7 * s))
        return {"poly": palace, "color": color, "district": district}

    def _cathedral(self, area, color, district):
        """Kathedrale: Langhaus, Querschiff und Chor mit runder Apsis, zwei Türme an der Fassade und ein
        Vierungsturm. Das Langhaus folgt der langen Seite des Blocks, die Fassade zeigt zur Hauptstraße hin auf
        einen gepflasterten Domplatz mit Brunnen; um den Chor stehen Bäume."""
        s, rng = self.s, self.rng
        o, e1, e2 = axes(area)
        if vlen(e2) > vlen(e1):
            e1, e2 = e2, e1
        La, Lb = vlen(e1), vlen(e2)
        u, v = e1 / La, e2 / Lb
        if LineString([o + e1, o + e1 + e2]).distance(self.main_streets) < LineString([o, o + e2]).distance(self.main_streets):
            o, u = o + e1, -u        # Fassade an das Ende des Blocks, das näher an der Hauptstraße liegt
        R = lambda *a: self._rect(o, u, v, *a)
        P = lambda x, y: o + u * x + v * y
        w = min(0.4 * Lb, 0.27 * La)          # Breite des Langhauses (mit Seitenschiffen)
        if w < 14 * s:
            return None
        c = Lb / 2
        xp = max(0.2 * La, 14 * s)            # Domplatz vor der Fassade
        t = 0.55 * w                          # Seitenlänge der Fassadentürme
        xe = La - 0.06 * La                   # Scheitel der Apsis
        wc = 0.86 * w                         # Breite des Chors
        xa = xe - wc / 2                      # Mittelpunkt der Apsis
        xq0 = xp + 0.5 * (xa - xp)            # Querschiff
        xq1 = xq0 + 0.8 * w
        if xq1 > xa - 0.3 * w:
            return None
        arm = min(0.42 * Lb, 1.25 * w)        # halbe Länge des Querschiffs
        apse = Polygon([P(xa + math.cos(a) * wc / 2, c + math.sin(a) * wc / 2)
                        for a in np.linspace(-math.pi / 2, math.pi / 2, 9)] + [P(xa - 1, c + wc / 2), P(xa - 1, c - wc / 2)])
        body = unary_union([R(xp + 0.5 * t, c - w / 2, xq0 + 0.5, c + w / 2), R(xq0, c - arm, xq1, c + arm),
                            R(xq1 - 0.5, c - wc / 2, xa, c + wc / 2), apse,
                            R(xp, c - w / 2 - 0.12 * t, xp + t, c + w / 2 + 0.12 * t)])   # Westwerk zwischen den Türmen
        body = body.intersection(area)
        if body.geom_type != "Polygon":
            return None
        towers = [R(xp - 0.08 * t, y0, xp + 0.92 * t, y0 + t)
                  for y0 in (c - w / 2 - 0.18 * t, c + w / 2 + 0.18 * t - t)]
        r8 = 0.36 * w
        cx = (xq0 + xq1) / 2
        crossing = Polygon([P(cx + math.cos(a) * r8, c + math.sin(a) * r8)
                            for a in np.arange(8) * math.pi / 4 + math.pi / 8])
        plaza = R(0, 0, xp + 0.1 * t, Lb).intersection(area)
        if not plaza.is_empty:
            self.out["grounds"].append((plaza, "plaza"))
            if xp > 18 * s:
                f = P(xp * 0.45, c)
                self.out["fountains"].append((float(f[0]), float(f[1]), min(7 * s, xp * 0.2)))
        keep = unary_union([body, *towers]).buffer(5 * s)
        inner = area.buffer(-5 * s)
        for _ in range(14):                   # Bäume um Chor und Querschiff (Domfreiheit)
            q = P(rng.uniform(xq0, La), rng.uniform(0, Lb))
            pt = Point(float(q[0]), float(q[1]))
            if inner.contains(pt) and not keep.contains(pt):
                self.out["yard_trees"].append((float(q[0]), float(q[1]), rng.uniform(5, 8) * s))
        spire = "#5e8b78"                     # Turmhelme mit grüner Kupferpatina
        annex = [{"poly": tw, "color": spire, "district": district, "landmark": True} for tw in towers]
        annex.append({"poly": crossing, "color": spire, "district": district, "landmark": True})
        return {"poly": body, "color": color, "district": district, "annex": annex}

    def _barracks(self, area, color, district):
        """Kaserne als Ringbau um einen Exerzierplatz."""
        s = self.s
        yard = area.buffer(-17 * s, join_style="mitre")
        if yard.is_empty or yard.area < 300 * s * s:
            return None
        yard = max(polys(yard), key=lambda p: p.area)
        ring = area.difference(yard.buffer(1.5 * s, join_style="mitre"))
        self.out["grounds"].append((yard, "drill"))
        mid = [ln for ln in lines(area.buffer(-8.5 * s, join_style="mitre").boundary)]
        return {"poly": ring, "color": color, "district": district, "ridges": mid, "shade": None}

    def _cemetery(self, area, color, district):
        """Friedhof mit Zaun, Grabreihen, Bäumen und Kapelle."""
        s, rng = self.s, self.rng
        ax = axes(area)
        if ax is None:
            return None
        o, e1, e2 = ax
        l1, l2 = vlen(e1), vlen(e2)
        u, v = e1 / l1, e2 / l2
        self.out["grounds"].append((area, "cemetery"))
        cc = o + u * min(18 * s, l1 * 0.2) + v * l2 / 2
        chapel = Polygon([cc - u * 9 * s - v * 6 * s, cc + u * 9 * s - v * 6 * s,
                          cc + u * 9 * s + v * 6 * s, cc - u * 9 * s + v * 6 * s]).intersection(area)
        inner = area.buffer(-6 * s).difference(chapel.buffer(6 * s))
        a = 0.0
        while a < l1:
            b = 0.0
            while b < l2:
                g = o + u * a + v * b
                grave = Polygon([g, g + u * 3.5 * s, g + u * 3.5 * s + v * 6.5 * s, g + v * 6.5 * s])
                if inner.contains(grave):
                    if rng.random() < 0.85:
                        self.out["graves"].append(grave)
                    elif rng.random() < 0.5:
                        self.out["yard_trees"].append((g[0], g[1], rng.uniform(6, 9) * s))
                b += 11 * s
            a += 8 * s
        return {"poly": cross_in_rect(chapel.minimum_rotated_rectangle).intersection(area), "form": "kreuz",
                "courtyard": True, "color": color, "district": district}   # Friedhofskapelle als kleines Gotteshaus

    def landmarks(self):
        s, rng = self.s, self.rng
        names = {d["name"].lower(): i for i, d in enumerate(self.district_list)}
        used = set()
        for o in self.cfg["orte"]:
            typ = o["typ"]
            if typ in FORT_TYPES:   # Festungen baut der Generator außerhalb der Stadt
                continue
            if typ == "wassermuehle" and self.t["river"] is None:
                print(f"Hinweis: Kein Fluss für die Wassermühle '{o['name']}' - es wird eine Windmühle.")
                typ = "muehle"
            elif typ == "wassermuehle" and self.t["biome"]["chasm"]:   # der Fluss liegt tief unten in der Klamm
                print(f"Hinweis: In der Klamm ist keine Wassermühle möglich - '{o['name']}' wird eine Windmühle.")
                typ = "muehle"
            if typ in ("muehle", "bauernhof"):   # Windmühle und Bauernhof stehen vor der Stadt an einer Landstraße
                self.out["deferred"].append(dict(o, typ=typ, typ_yaml=o["typ"]))
                continue
            di = names.get(str(o.get("viertel", "")).lower())
            if di is not None and not any(b["district"] == di for b in self.out["buildings"]):
                print(f"Hinweis: Ort '{o['name']}' wird woanders platziert, Viertel '{o.get('viertel')}' ist leer.")
                di = None
            alive = [b for b in self.out["buildings"] if not b.get("removed") and id(b) not in used
                     and (di is None or b["district"] == di)]
            target = None
            if typ in BIG_LANDMARKS:
                blks = [bk for bk in self.blocks if (di is None or bk["district"] == di)
                        and {"friedhof": 2500, "kaserne": 2500, "tempel": 1500, "rathaus": 1500,
                             "palast": 5000, "kathedrale": 4500}.get(typ, 900) * s * s
                        < bk["poly"].area < (16000 if typ in COMPACT else 9000) * s * s
                        and min_width(bk["poly"]) > (42 if typ in COMPACT else 28) * s
                        and (typ not in COMPACT or bk["poly"].area / bk["poly"].minimum_rotated_rectangle.area > 0.7)
                        # Blöcke mit einem schon gesetzten besonderen Ort nicht abräumen (sonst bliebe z.B. von der
                        # Wassermühle nur das Rad samt Beschriftung übrig)
                        and not any(self.out["buildings"][i].get("landmark") for i in bk["ids"])]
                outside = str(o.get("lage", "")).lower() in ("ausserhalb", "aussen", "draussen", "vor der stadt")
                if typ == "friedhof" and (outside or not blks):
                    self.out["deferred"].append(o)   # wird vom Generator vor der Mauer angelegt
                    continue
                if typ in COMPACT and not blks:
                    print(f"Hinweis: Kein passender Block für '{o['name']}' gefunden.")
                if typ == "werft":
                    blks.sort(key=lambda bk: bk["poly"].distance(self.t["water"]))
                    blks = blks[:3]
                elif typ in ("palast", "kathedrale"):   # der größte Block an einer Hauptstraße
                    blks.sort(key=lambda bk: bk["poly"].distance(self.main_streets) / s - bk["poly"].area / (200 * s * s))
                    blks = blks[:2]
                else:
                    blks.sort(key=lambda bk: bk["poly"].distance(self.main_streets))
                    blks = blks[:6]
                if blks:
                    bk = rng.choice(blks)
                    self.blocks.remove(bk)
                    color = LANDMARK_COLORS.get(typ) or "#8a6a4a"
                    target = self._replace_block(bk, color, typ, 1.5 * s)
            if target is None and alive:
                if typ == "wassermuehle":   # Haus direkt am Flussufer, das Wasserrad hängt im Fluss
                    river = self.t["river"]
                    target, p, q = self._mill_house(alive, river)
                    n = unit((q.x - p.x, q.y - p.y)) if q.distance(p) > 0.1 else (0.0, 1.0)
                    c = (q.x + n[0] * 3 * s, q.y + n[1] * 3 * s)       # Rad an der Uferkante, halb im Wasser
                    self.out["wheels"].append({"x": c[0], "y": c[1], "len": 18 * s, "wid": 6 * s, "house": (p.x, p.y),
                                               "angle": math.degrees(math.atan2(n[0], -n[1]))})
                elif typ in ("gasthaus", "schmiede", "laden"):
                    alive.sort(key=lambda b: b["poly"].distance(self.main_streets) - b["poly"].area * 0.002 / s)
                    target = rng.choice(alive[:12])
                else:
                    target = rng.choice(alive)
                if LANDMARK_COLORS.get(typ):
                    target["color"] = LANDMARK_COLORS[typ]
            if target is None:
                continue
            used.add(id(target))
            target["landmark"] = True
            if typ == "schmiede":
                target["forge"] = True
            text = o.get("kuerzel") or o["name"]
            if o.get("kuerzel"):
                self.out["legend"].append((o["kuerzel"], o["name"]))
            c = target["poly"].centroid
            self.out["labels"].append({"x": c.x, "y": c.y, "text": text, "kind": "ort",
                                       "lift": math.sqrt(target["poly"].area) * 0.5 + 6 * s,
                                       "ort": place_info(o, self.district_name(target["district"]))})

    def district_name(self, i):
        """Name des Viertels mit dem Index i (None außerhalb der Viertel oder bei namenlosen Vierteln)."""
        return (self.district_list[i]["name"] or None) if 0 <= i < len(self.district_list) else None

    def _mill_house(self, alive, river):
        """Mühlhaus der Wassermühle: ein Haus direkt am Wasser, ohne Straße zwischen Haus und Fluss. Gibt es keins,
        entsteht ein eigenes Mühlhaus auf dem Uferstreifen. Liefert (Haus, Punkt am Haus, Punkt am Ufer)."""
        s = self.s
        streets = unary_union(self.out["streets"] + self.out["plazas"] + self.out["paved"])
        # Abstand zu Brücken: dort, wo eine Straße den Fluss quert, hätte das Rad keinen Platz
        crossings = unary_union([ln.intersection(river).buffer(w / 2 + 22 * s) for ln, w in self.out["internal_roads"]
                                 if ln.intersects(river)])
        best = None
        for b in alive:
            d = b["poly"].distance(river)
            if d > 12 * s or (best is not None and d >= best[0]) or b["poly"].intersects(crossings):
                continue
            p, q = nearest_points(b["poly"], river)
            if d > 1 * s and LineString([p, q]).intersects(streets):
                continue
            best = (d, b, p, q)
        if best is not None:
            return best[1], best[2], best[3]
        # eigenes Mühlhaus am Ufer: Rechteck parallel zum Ufer, auf Land, ohne Straßen und Häuser zu berühren
        taken = unary_union([streets, crossings] + [b["poly"] for b in self.out["buildings"]
                                                    if not b.get("removed")]).buffer(1.5 * s)
        L, H = 16 * s, 11 * s
        cx, cy = self.center
        spot = None
        for ln in lines(river.boundary.intersection(self.city_land.buffer(1 * s))):
            k = 4 * s
            while k < ln.length - 4 * s:
                q, q2 = ln.interpolate(k), ln.interpolate(k + 2)
                k += 6 * s
                tx, ty = unit((q2.x - q.x, q2.y - q.y))
                nx, ny = -ty, tx
                if river.contains(Point(q.x + nx * 4 * s, q.y + ny * 4 * s)):
                    nx, ny = -nx, -ny                         # Normale zeigt aufs Land
                c = (q.x + nx * (H / 2 + 1 * s), q.y + ny * (H / 2 + 1 * s))
                rect = Polygon([(c[0] + a * tx * L / 2 + b * nx * H / 2, c[1] + a * ty * L / 2 + b * ny * H / 2)
                                for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
                if self.city_land.contains(rect) and not rect.intersects(taken) and not rect.intersects(river):
                    score = math.hypot(c[0] - cx, c[1] - cy)
                    if spot is None or score < spot[0]:
                        spot = (score, rect)
        if spot is None:
            print("Hinweis: Kein Haus und kein Platz direkt am Fluss für die Wassermühle - sie steht etwas abseits.")
            b = min(alive, key=lambda b: b["poly"].distance(river))
            p, q = nearest_points(b["poly"], river)
            return b, p, q
        rect = spot[1]
        rp = rect.representative_point()
        di = next((i for i, d in enumerate(self.district_list) if d["poly"].buffer(10 * s).contains(rp)), -1)
        b = {"poly": rect, "form": "rechteck", "color": "#7a3f3f", "district": di}
        self.out["buildings"].append(b)
        p, q = nearest_points(rect, river)
        return b, p, q

    def district_labels(self):
        for d in self.district_list:
            ps = polys(d["poly"])
            if not ps or not d["name"]:
                continue
            p = max(ps, key=lambda q: q.area)
            c = polylabel(p, tolerance=4)
            self.out["labels"].append({"x": c.x, "y": c.y, "text": d["name"], "kind": "viertel",
                                       "viertel": {"name": d["name"], "typ": d["typ"]}})

    # ---------------------------------------------------------------- Hafen
    def harbor(self):
        """Stege und Schiffe. Im Fluss bleibt eine Fahrrinne frei: Stege höchstens 1/4 der Flussbreite,
        Schiffe längsseits am Ufer, nichts ragt weiter als 35 % in den Fluss. Nichts überlagert Brücken
        oder andere Stege und Schiffe."""
        s, rng = self.s, self.rng
        water, sea, river = self.t["water"], self.t["sea"], self.t["river"]
        # Brückenbereiche (Straßen über Wasser) und schon belegte Flächen
        occupied = [ln.buffer(w / 2 + 14 * s).intersection(water.buffer(10 * s))
                    for ln, w in self.out["internal_roads"] if ln.intersects(water)]
        for d in self.district_list:
            if d["typ"] not in ("hafen", "fischer"):
                continue
            big = d["typ"] == "hafen"
            bank = d.get("cell", d["poly"]).boundary.intersection(water.buffer(5 * s))
            for ln in lines(bank):
                step = (80 if big else 60) * s
                k = step / 2
                while k < ln.length:
                    p, q = ln.interpolate(k), ln.interpolate(min(ln.length, k + 3))
                    k += step * rng.uniform(0.8, 1.2)
                    tx, ty = unit((q.x - p.x, q.y - p.y))
                    nx, ny = -ty, tx
                    if not water.contains(Point(p.x + nx * 15 * s, p.y + ny * 15 * s)):
                        nx, ny = -nx, -ny
                    probe = Point(p.x + nx * 15 * s, p.y + ny * 15 * s)
                    in_river = river is not None and river.contains(probe) and (sea is None or not sea.contains(probe))
                    length = (48 if big else 26) * s
                    wid = (9 if big else 6) * s
                    if in_river:   # örtliche Breite: Strahl quer übers Wasser bis zum anderen Ufer
                        ray = LineString([(p.x + nx * 1 * s, p.y + ny * 1 * s), (p.x + nx * 600 * s, p.y + ny * 600 * s)])
                        seg = [g for g in lines(ray.intersection(water)) if g.distance(p) < 3 * s]
                        width = seg[0].length if seg else 0.0
                        length = min(length, 0.25 * width)
                        if length < 10 * s:
                            continue
                    pier = Polygon([(p.x - tx * wid / 2 - nx * 4 * s, p.y - ty * wid / 2 - ny * 4 * s),
                                    (p.x + tx * wid / 2 - nx * 4 * s, p.y + ty * wid / 2 - ny * 4 * s),
                                    (p.x + tx * wid / 2 + nx * length, p.y + ty * wid / 2 + ny * length),
                                    (p.x - tx * wid / 2 + nx * length, p.y - ty * wid / 2 + ny * length)])
                    if not water.buffer(6 * s).contains(pier) or any(pier.buffer(3 * s).intersects(o) for o in occupied):
                        continue
                    self.out["piers"].append(pier)
                    occupied.append(pier.buffer(2 * s))
                    if rng.random() > (0.7 if big else 0.6):
                        continue
                    hl, hw = (rng.uniform(46, 64), rng.uniform(14, 18)) if big else (rng.uniform(18, 24), 7)
                    hl, hw = hl * s, hw * s
                    side = rng.choice([-1, 1])
                    if in_river and hl <= length - 1 * s and rng.random() < 0.6:
                        # kleines Schiff, nicht länger als der Steg: darf quer zum Fluss längs am Steg liegen,
                        # ragt aber nicht über die Stegspitze hinaus (Fahrrinne bleibt frei)
                        off = wid / 2 + hw / 2 + 5 * s
                        along = length - hl / 2 - 0.5 * s
                        cx = p.x + nx * along + tx * off * side
                        cy = p.y + ny * along + ty * off * side
                        angle = math.degrees(math.atan2(ny, nx))
                    elif in_river:
                        # längsseits: parallel zum Ufer neben dem Steg, nicht weiter als 35 % in den Fluss
                        dist = hw / 2 + 3 * s
                        if dist + hw / 2 > 0.35 * width:
                            continue
                        off = wid / 2 + hl / 2 + 5 * s
                        cx, cy = p.x + nx * dist + tx * off * side, p.y + ny * dist + ty * off * side
                        angle = math.degrees(math.atan2(ty, tx))
                    else:
                        off = wid / 2 + hw / 2 + 5 * s
                        cx = p.x + nx * (length * 0.55) + tx * off * side
                        cy = p.y + ny * (length * 0.55) + ty * off * side
                        angle = math.degrees(math.atan2(ny, nx))
                    hull = ship_footprint(cx, cy, hl, hw, angle)
                    others = occupied[:-1]   # der eigene Steg darf direkt daneben liegen (Abstand ist schon eingerechnet)
                    if water.buffer(1 * s).contains(hull) and not any(hull.buffer(2 * s).intersects(o) for o in others):
                        self.out["ships"].append({"x": cx, "y": cy, "len": hl, "wid": hw, "angle": angle, "big": big})
                        occupied.append(hull.buffer(2 * s))

    # ---------------------------------------------------------------- Plätze, Brunnen, Bäume
    def squares_and_wells(self):
        """Brunnen in der Mitte jedes Platzes; große Plätze bekommen einen Wochenmarkt mit Ständen in Reihen,
        die Wege der einmündenden Straßen bleiben frei. Dazu Ziehbrunnen an breiten Straßenstellen."""
        s, rng = self.s, self.rng
        roads = unary_union([ln.buffer(w / 2 + 3 * s) for ln, w in self.out["internal_roads"]])
        palette = [("#b8483a", "#efe2c4"), ("#3f6a8a", "#efe2c4"), ("#c79a3a", "#7a3a2a"), ("#5d7a3a", "#efe2c4"),
                   ("#7a4a8a", "#efe2c4"), ("#c46a2a", "#f2d8a0")]
        for plaza in self.out["plazas"]:
            if plaza.is_empty or plaza.area < 1500 * s * s:
                continue
            c = polylabel(max(polys(plaza), key=lambda q: q.area), tolerance=1)
            fr = 8 * s
            self.out["fountains"].append((c.x, c.y, fr))
            if plaza.area < 5000 * s * s:
                continue
            ax = axes(plaza)
            if ax is None:
                continue
            _, e1, e2 = ax
            u, v = e1 / vlen(e1), e2 / vlen(e2)
            room = plaza.buffer(-4 * s).difference(roads).difference(Point(c.x, c.y).buffer(fr + 9 * s))
            shapely.prepare(room)
            sw, sd, gx, gy = 9 * s, 6.5 * s, 13.5 * s, 12.5 * s   # Standbreite/-tiefe, Raster
            ext = math.sqrt(plaza.area) * 1.2
            for i in np.arange(-ext, ext, gx):
                for j in np.arange(-ext, ext, gy):
                    if rng.random() < 0.18:
                        continue   # Lücken zwischen den Ständen
                    q = np.array([c.x, c.y]) + u * i + v * j
                    stall = Polygon([q - u * sw / 2 - v * sd / 2, q + u * sw / 2 - v * sd / 2,
                                     q + u * sw / 2 + v * sd / 2, q - u * sw / 2 + v * sd / 2])
                    if room.contains(stall):
                        self.out["stalls"].append({"poly": stall, "u": tuple(u), "v": tuple(v),
                                                   "colors": rng.choice(palette)})
        # Ziehbrunnen am Straßenrand: freie Stelle direkt neben der Straße, nicht auf der Fahrbahn,
        # nicht an einem Haus, nicht auf Plätzen; weit genug voneinander und von den Toren entfernt
        streets = unary_union(self.out["streets"])
        if streets.is_empty:
            return
        r = 3.6 * s
        bl = unary_union([b["poly"] for b in self.out["buildings"] if not b.get("removed")])
        blocked = unary_union([streets, bl.buffer(1.5 * s), unary_union(self.out["plazas"]).buffer(25 * s),
                               unary_union(self.out["paved"]).buffer(2 * s) if self.out["paved"] else Polygon(),
                               unary_union([g for g, _ in self.out["grounds"]]).buffer(2 * s),
                               unary_union([st["poly"] for st in self.out["stalls"]]).buffer(2 * s) if self.out["stalls"] else Polygon(),
                               self.shape.exterior.buffer(12 * s), self.t["water"].buffer(4 * s)]
                              + ([self.t["pools"]] if self.t.get("pools") is not None else []))
        shapely.prepare(blocked)
        edges = [ln for ln in lines(streets.boundary) if ln.length > 30 * s]
        if not edges:
            return
        weights = np.array([ln.length for ln in edges])
        target = max(2, int(self.city_land.area / (70000 * s * s)))
        tries = 0
        while len(self.out["wells"]) < target and tries < 4000:
            tries += 1
            ln = edges[rng.choices(range(len(edges)), weights)[0]]
            k = rng.uniform(0, ln.length)
            p, q = ln.interpolate(k), ln.interpolate(min(ln.length, k + 2))
            tx, ty = unit((q.x - p.x, q.y - p.y))
            for side in (1, -1):                      # die Seite, die nicht Straße ist
                x, y = p.x - ty * side * (r + 0.6 * s), p.y + tx * side * (r + 0.6 * s)
                spot = Point(x, y).buffer(r)
                if streets.contains(Point(x, y)):
                    continue
                if not self.city_land.contains(spot) or blocked.intersects(spot):
                    break
                if any(math.dist((x, y), w[:2]) < 140 * s for w in self.out["wells"]):
                    break
                if any(math.dist((x, y), (g[0], g[1])) < 50 * s for g in self.out["gates"]):
                    break
                self.out["wells"].append((x, y, r))
                break

    def fill_empty_with_trees(self):
        """Größere leere Flächen in der Stadt (Höfe, freigebliebene Grundstücke) bekommen einzelne Bäume."""
        s, rng = self.s, self.rng
        bl = [b["poly"] for b in self.out["buildings"] if not b.get("removed")]
        obstacles = unary_union(
            [unary_union(bl).buffer(3 * s)] + [unary_union(self.out["streets"] + self.out["plazas"] + self.out["paved"]).buffer(2 * s)]
            + [g.buffer(2 * s) for g, _ in self.out["grounds"]] + [st["poly"].buffer(2 * s) for st in self.out["stalls"]]
            + [Point(x, y).buffer(r + 3 * s) for x, y, r in self.out["yard_trees"]]
            + [Point(x, y).buffer(r + 4 * s) for x, y, r in self.out["wells"]]
            + [self.shape.exterior.buffer(8 * s)] + ([self.t["pools"]] if self.t.get("pools") is not None else []))
        free = self.city_land.difference(obstacles)
        if free.is_empty:
            return
        step = 13 * s
        minx, miny, maxx, maxy = free.bounds
        xs, ys = np.meshgrid(np.arange(minx, maxx, step), np.arange(miny, maxy, step))
        xs = xs.ravel() + np.array([rng.uniform(-4, 4) * s for _ in range(xs.size)])
        ys = ys.ravel() + np.array([rng.uniform(-4, 4) * s for _ in range(ys.size)])
        ok = shapely.contains_xy(free, xs, ys)
        if not ok.any():
            return
        pts = shapely.points(xs[ok], ys[ok])
        clear = shapely.distance(obstacles, pts)       # Abstand zum nächsten Haus, zur Straße, ...
        placed = []
        for p, cl in sorted(zip(pts, clear), key=lambda pc: -pc[1]):
            if cl < 7 * s or rng.random() > 0.75:
                continue
            r = min(cl - 1.5 * s, 11 * s) * rng.uniform(0.8, 1.0)
            if any(math.dist((p.x, p.y), (q[0], q[1])) < r + q[2] + 2 * s for q in placed):
                continue
            placed.append((p.x, p.y, r))
        self.out["yard_trees"] += placed

    # ---------------------------------------------------------------- alles
    def build(self):
        self.outline()
        self.walls_and_gates()
        ext = self.external_roads()
        internal = self.internal_roads()
        self.out["internal_roads"] = internal
        self.districts()
        self.buildings(internal)
        self.landmarks()
        self.connect_to_streets(landmarks=True)
        self.squares_and_wells()
        self.district_labels()
        if not self.t.get("mountain"):
            self.harbor()
        if self.t["biome"]["forges"]:   # glühende Essen in Handwerksvierteln
            for b in self.out["buildings"]:
                d = b["district"]
                if 0 <= d < len(self.district_list) and self.district_list[d]["typ"] == "handwerk" \
                        and self.rng.random() < 0.15 and not b.get("landmark"):   # z.B. nicht auf einem Domturm
                    b["forge"] = True
        self.fill_empty_with_trees()
        for b in self.out["buildings"]:
            if not b.get("removed") and "ridges" not in b:
                b["ridges"], b["shade"] = roof(b["poly"])
        self.out["buildings"] = [b for b in self.out["buildings"] if not b.get("removed")]
        self.out["shape"] = self.shape
        self.out["city_land"] = self.city_land
        return self.out, ext, internal
