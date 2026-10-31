"""Stadtgrundriss: Mauer, Tore, Straßen, Viertel, Gebäude und besondere Orte."""
import math
import random

import numpy as np
import shapely
import shapely.affinity
from shapely.geometry import LineString, MultiPoint, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import nearest_points, polylabel, substring, unary_union

from .config import MAX_EINWOHNER, place_info, to_canonical
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


# Großstadt: ab dieser Einwohnerzahl Häuserblöcke statt Einzelhäuser, Altstadtmauer und Vorstädte
GROSS = 20000


BEBAUUNG = {"dicht": 1.0, "locker": 1.4, "weitlaeufig": 1.9}   # Flächenfaktor bei gleicher Einwohnerzahl


def spread(cfg):
    return BEBAUUNG.get(cfg.get("bebauung", "dicht"), 1.0)


def city_radius(W, population, area=1.0):
    """Fläche wächst mit der Einwohnerzahl; 6000 Einwohner ~ 0.22 der Kartenbreite. Großstädte wachsen auf der
    Karte nur noch wenig (bis 0.33), stattdessen wird der Maßstab kleiner und die Bebauung feiner."""
    if population > GROSS:
        r = W * (0.3 + 0.03 * min(1.0, math.log(population / GROSS) / math.log(MAX_EINWOHNER / GROSS)))
    else:
        r = W * max(0.06, min(0.3, 0.222 * math.sqrt(max(population, 100) / 6000)))
    # lockere Bebauung: mehr Fläche (area-fach), höchstens 0.45 der Kartenbreite (Durchmesser 90 %)
    return r if area == 1.0 else min(r * math.sqrt(area), max(r, 0.45 * W))


def make_shape(rng, center, r):
    cx, cy = center
    n = rng.randint(9, 12)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n + rng.uniform(-0.15, 0.15)
        rad = r * rng.uniform(0.9, 1.08)
        pts.append((cx + math.cos(a) * rad * 0.9, cy + math.sin(a) * rad * 1.12))
    return Polygon(pts).buffer(0)


# Stadtformen: rund ist der bisherige Umriss; "zufall" wählt je Seed eine Form
SHAPES = ("rund", "oval", "unregelmaessig", "vieleck", "gewachsen")


def pick_shape(seed, wanted):
    """Stadtform aus der Einstellung; bei "zufall" fest an den Seed gebunden (eigener Zufallsgenerator, damit
    Karten mit Form "rund" genau wie früher aussehen)."""
    if wanted in SHAPES or wanted == "eigene":
        return wanted
    return random.Random(f"stadtform-{seed}").choice(SHAPES)


def varied_shape(rng, center, r, kind, W, s, coastal):
    """Andere Stadtumrisse mit etwa derselben Fläche wie der runde (die Einwohnerzahl bestimmt die Größe):
    oval     - langgestreckt, an Küste oder Fluss entlang (intern: Küste im Norden, Fluss von Süd nach Nord)
    unregelmaessig - ausgebeulter Umriss mit Ein- und Ausbuchtungen
    vieleck  - wenige lange, gerade Mauerseiten (planmäßig angelegte Stadt)
    gewachsen - runder Kern mit einer oder zwei eingemeindeten Ausbuchtungen
    """
    cx, cy = center
    unit_pts = []
    if kind == "oval":
        a = rng.uniform(1.35, 1.7)
        ang = rng.choice([0.0, math.pi / 2]) + rng.uniform(-0.2, 0.2) if coastal else rng.uniform(0, math.pi)
        n = rng.randint(14, 18)
        for i in range(n):
            t = 2 * math.pi * i / n + rng.uniform(-0.1, 0.1)
            x, y = math.cos(t) * a * rng.uniform(0.95, 1.05), math.sin(t) / a * rng.uniform(0.95, 1.05)
            unit_pts.append((x * math.cos(ang) - y * math.sin(ang), x * math.sin(ang) + y * math.cos(ang)))
    elif kind == "unregelmaessig":
        n = rng.randint(18, 24)
        waves = [(k, rng.uniform(0.07, 0.16), rng.uniform(0, 2 * math.pi)) for k in rng.sample([2, 3, 4, 5], 3)]
        for i in range(n):
            t = 2 * math.pi * i / n + rng.uniform(-0.06, 0.06)
            rad = (1 + sum(amp * math.sin(k * t + ph) for k, amp, ph in waves)) * rng.uniform(0.96, 1.04)
            unit_pts.append((math.cos(t) * rad, math.sin(t) * rad))
    elif kind == "vieleck":
        n = rng.randint(5, 7)
        a0 = rng.uniform(0, 2 * math.pi)
        for i in range(n):
            t = a0 + 2 * math.pi * i / n + rng.uniform(-0.12, 0.12)
            rad = rng.uniform(0.95, 1.06)
            unit_pts.append((math.cos(t) * rad, math.sin(t) * rad))
    if kind == "gewachsen":
        core = make_shape(rng, center, r * 0.9)
        parts = [core]
        for _ in range(rng.randint(1, 2)):
            # Ausbuchtungen nicht ins Meer (intern liegt die Küste oben, y klein)
            t = rng.uniform(0.15 * math.pi, 0.85 * math.pi) if coastal else rng.uniform(0, 2 * math.pi)
            if coastal and rng.random() < 0.5:
                t = rng.choice([0.0, math.pi]) + rng.uniform(-0.3, 0.3)
            d = r * rng.uniform(0.75, 0.9)
            parts.append(make_shape(rng, (cx + math.cos(t) * d, cy + math.sin(t) * d), r * rng.uniform(0.45, 0.6)))
        shape = unary_union(parts).buffer(30 * s).buffer(-30 * s)
        shape = max(polys(shape), key=lambda p: p.area)
        shape = Polygon(shape.exterior)
    else:
        shape = Polygon([(cx + x * r, cy + y * r) for x, y in unit_pts]).buffer(0)
    # gleiche Fläche wie der runde Umriss (Ellipse 0.9 x 1.12)
    target = math.pi * 0.9 * 1.12 * r * r
    shape = shapely.affinity.scale(shape, *(2 * [math.sqrt(target / shape.area)]), origin=(cx, cy))
    return shape


def fit_into_map(shape, center, W, s, top=None):
    """Verschiebt (Küste: Oberkante auf 'top') und verkleinert den Umriss, bis er mit Rand auf die Karte passt."""
    cx, cy = center
    if top is not None:
        dy = top - shape.bounds[1]
        shape = shapely.affinity.translate(shape, 0, dy)
        cy += dy
    m = 70 * s
    minx, miny, maxx, maxy = shape.bounds
    kx = min((cx - m) / max(cx - minx, 1), (W - m - cx) / max(maxx - cx, 1))   # Platz nach links/rechts
    ky = min([(W - m - cy) / max(maxy - cy, 1)] + ([] if top is not None else [(cy - m) / max(cy - miny, 1)]))
    if min(kx, ky) < 1.0:
        # in der Richtung stauchen, in der der Umriss übersteht, und in der anderen so weit verbreitern, wie Platz
        # ist: eine langgestreckte Stadt würde sonst auch schmaler und verlöre viel Fläche
        if kx < 1.0 and ky < 1.0:
            sx, sy = kx, ky
        elif kx < 1.0:
            sx, sy = kx, min(ky, 1 / kx, 1.0 if top is not None else ky)   # an der Küste nicht nach oben wachsen
        else:
            sx, sy = min(kx, 1 / ky), ky
        shape = shapely.affinity.scale(shape, sx, sy, origin=(cx, cy))
    return shape, (cx, cy)


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
        pop = cfg["einwohner"]
        self.grand = pop >= GROSS
        # lockere Bebauung: aufgelockert wird nur so weit, wie die Stadt tatsächlich mehr Fläche bekommen hat
        # (Großstädte stoßen an den Kartenrand und wachsen nicht mehr mit)
        self.spread = max(1.0, (r / city_radius(W, pop)) ** 2) if spread(cfg) > 1 else 1.0
        self.g = max(1.0, math.sqrt(pop / GROSS))   # 1 bei 20.000, 3.5 bei 250.000 Einwohnern: wie viel feiner
        self.out = self.empty_out()

    @staticmethod
    def empty_out():
        """Leeres Stadtmodell (alle Listen und Flächen, die der Generator füllt)."""
        return {
            "buildings": [], "streets": [], "paved": [], "internal_roads": [], "plazas": [],
            "grounds": [], "graves": [], "fountains": [], "deferred": [],
            "great_gate": None, "terrace_walls": [], "stairs": [], "wells": [], "stalls": [],
            "towers": [], "gates": [], "wall": [], "yard_trees": [], "labels": [], "piers": [],
            "ships": [], "legend": [], "districts": [], "wheels": [], "windmills": [], "haystacks": [],
            "old_wall": [], "old_gates": [], "faubourg": Polygon(), "slum_outside": Polygon(),
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
        given = self.t.get("shape")   # vom Generator vorgegeben (Felskessel, andere Stadtform, gezeichnete Mauer)
        self.shape = given if given is not None else make_shape(self.rng, self.center, self.r)
        if self.t.get("custom"):   # gezeichnete Mauer: die Bebauung richtet sich nach der Fläche
            base = city_radius(self.W, self.cfg["einwohner"])
            ratio = self.shape.area / (math.pi * base * base)
            if ratio < 0.45:
                print("Hinweis: Die gezeichnete Mauer ist für die Einwohnerzahl sehr eng - die Stadt wird dicht "
                      "bebaut und wirkt kleiner als angegeben.")
            elif ratio > 3.5:
                print("Hinweis: Die gezeichnete Mauer umschließt sehr viel Fläche für die Einwohnerzahl - "
                      "die Stadt wird weitläufig mit vielen Gärten.")
            self.spread = min(3.0, max(1.0, ratio))
        if self.spread > 1:   # nach der tatsächlichen Fläche (am Kartenrand oder an der Küste verkleinert)
            base = city_radius(self.W, self.cfg["einwohner"])
            self.spread = min(self.spread, max(1.0, self.shape.area / (math.pi * base * base)))
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
        custom = t.get("custom")
        if custom:   # gezeichnete Mauer: Tore und Türme genau dort, wo sie gesetzt wurden
            c = np.array(self.center)
            self.gates = []
            for p in custom["gates"]:
                if p.distance(t["water"]) < 8 * s:
                    print("Hinweis: Ein Tor liegt im Wasser und entfällt.")
                    continue
                d = unit((p.x - c[0], p.y - c[1]))
                self.gates.append((math.atan2(d[1], d[0]), p, np.array(d)))
            self.walled = walled
            if not walled:
                return
            wall = self.shape.exterior.difference(t["water"].buffer(4 * s))
            self.out["wall"] = [ln for ln in lines(wall) if ln.length > 10 * s]
            for p in custom["towers"]:
                if p.distance(t["water"]) > 4 * s:
                    self.out["towers"].append((p.x, p.y, wall_angle(self.shape, p)))
            for _, p, _ in self.gates:
                self.out["gates"].append((p.x, p.y, wall_angle(self.shape, p)))
            return
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
        near_city = self.shape.buffer(25 * s)

        def free(q):   # Schritt ohne Meer (bzw. Fels, andere Plateaustufe) und nicht zurück an die Stadt
            return not (sea is not None and sea.distance(Point(q)) < 10 * s) and not near_city.contains(Point(q))
        for a, p, _ in self.gates:
            noise = Noise1D(self.rng)
            pts = [(p.x, p.y)]
            for i in range(1, 600):
                ang = a + 0.5 * noise.fbm(i * 0.035)
                q = (pts[-1][0] + math.cos(ang) * 20 * s, pts[-1][1] + math.sin(ang) * 20 * s)
                if (sea is not None and sea.contains(Point(q))) or self.shape.contains(Point(q)):
                    # keine Straße ins Leere: an Küste, Felswand oder Stadtmauer entlang ausweichen und weiter bis
                    # zum Kartenrand (die Richtung bleibt danach geändert)
                    for off in (0.35, -0.35, 0.7, -0.7, 1.05, -1.05, 1.4, -1.4, 1.75, -1.75, 2.1, -2.1, 2.45, -2.45):
                        q2 = (pts[-1][0] + math.cos(ang + off) * 20 * s, pts[-1][1] + math.sin(ang + off) * 20 * s)
                        q3 = (q2[0] + math.cos(ang + off) * 20 * s, q2[1] + math.sin(ang + off) * 20 * s)
                        if free(q2) and free(q3):   # auch der nächste Schritt muss frei sein (keine Sackgasse)
                            a, q = a + off, q2
                            break
                    else:
                        break
                pts.append(q)
                if not frame.contains(Point(q)):
                    break
            if len(pts) > 2:
                roads.append((LineString(pts), 15 * s))
        # Straße kam nicht bis an den Kartenrand (Bucht, Felsnische): an die nächste andere Landstraße anschließen
        inner = box(0, 0, W, W).buffer(-2 * s)
        river = self.t["river"]
        for i, (ln, w) in enumerate(roads):
            end = Point(ln.coords[-1])
            if not inner.contains(end):
                continue
            if river is not None and river.buffer(15 * s).contains(end):
                # im Fluss gestrandet (z.B. an der Mündung): bis vor das Ufer zurücknehmen
                dry = [g for g in lines(ln.difference(river.buffer(15 * s))) if g.distance(Point(ln.coords[0])) < 1 * s]
                if dry and dry[0].length > 40 * s:
                    ln = dry[0]
                    roads[i] = (ln, w)
                    end = Point(ln.coords[-1])
            best = None
            for j, (o, _) in enumerate(roads):
                if j == i:
                    continue
                t_ = nearest_points(o, end)[0]
                link = LineString([end, t_])
                if link.intersects(self.t["water"]) or link.intersects(self.shape):   # nicht übers Wasser
                    continue
                if best is None or link.length < best.length:
                    best = link
            if best is not None and best.length < 400 * s:
                roads[i] = (LineString(list(ln.coords) + [best.coords[-1]]), w)
                continue
            around = self.ring_route(ln, sea)
            if around is not None and self.shape.distance(end) < 40 * s:
                roads[i] = (around, w)   # an der Stadtmauer gelandet: außen an der Mauer entlang zum nächsten Tor
                continue
            if sea is not None and sea.distance(end) < 30 * s and not (self.t.get("mountain") or self.t.get("plateau")):
                # an der Küste (bzw. Bucht) gelandet: die Straße endet an einer Anlegestelle mit Steg
                shore = nearest_points(sea, end)[0]
                ux, uy = unit((shore.x - end.x, shore.y - end.y)) if shore.distance(end) > 0.5 else (0.0, -1.0)
                tip = (shore.x + ux * 28 * s, shore.y + uy * 28 * s)
                pier = LineString([(end.x, end.y), tip]).buffer(3 * s, cap_style="flat")
                if not pier.intersects(self.shape.buffer(10 * s)):
                    roads[i] = (LineString(list(ln.coords) + [(shore.x - ux * 2 * s, shore.y - uy * 2 * s)]), w)
                    self.out["piers"].append(pier)
                    continue
            if around is not None:   # z.B. Nische an Felswand oder Plateaukante: um die Stadt zum nächsten Tor
                roads[i] = (around, w)
                continue
            # sonst: ein kleiner Weiler am Straßenende ist das Ziel
            self.out.setdefault("dead_ends", []).append(roads[i][0])
        return roads

    def ring_route(self, ln, sea):
        """Weg vom Ende der Straße ln außen an der Stadtmauer entlang zum nächsten anderen Tor (nicht durchs Meer,
        über Fluss, Felswand oder Plateaukante). Liefert die verlängerte Straße oder None."""
        s = self.s
        end, start = Point(ln.coords[-1]), Point(ln.coords[0])
        ring = LineString(self.shape.buffer(22 * s).exterior.coords)
        R, d0 = ring.length, ring.project(end)
        best = None
        for _, g, _ in self.gates:
            if g.distance(start) < 5 * s:   # nicht zurück zum eigenen Tor
                continue
            d1 = ring.project(g)
            for a_, b_, rev in ((d0, d1, False), (d1, d0, True)):
                if b_ >= a_:
                    pts = list(substring(ring, a_, b_).coords)
                else:
                    pts = list(substring(ring, a_, R).coords) + list(substring(ring, 0, b_).coords)
                if rev:
                    pts.reverse()
                tail = LineString([(end.x, end.y)] + pts + [(g.x, g.y)])
                river = self.t["river"]   # auch nicht über den Fluss (an der Mündung wäre das ein Damm im Wasser)
                if (sea is not None and tail.intersects(sea)) or tail.intersects(self.shape.buffer(-3 * s)) \
                        or (river is not None and tail.intersects(river)):
                    continue
                if best is None or tail.length < best.length:
                    best = tail
        return LineString(list(ln.coords) + list(best.coords)[1:]) if best is not None else None

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
        if self.grand:
            self._grand_roads(roads, plazas)
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

    def _grand_roads(self, roads, plazas):
        """Großstadt: zusätzliche Hauptachsen zwischen weit auseinanderliegenden Toren, dazu die Altstadt mit
        alter Mauer, Ringstraße davor, Torplätzen und Tortürmen an den Durchgängen."""
        s, rng, W = self.s, self.rng, self.W
        c = np.array(self.center)
        inner = self.city_land.buffer(-40 * s)
        angs = sorted(a % (2 * math.pi) for a, _, _ in self.gates)
        targets = []
        for i, a in enumerate(angs):
            gap = (angs[(i + 1) % len(angs)] - a) % (2 * math.pi) or 2 * math.pi
            n = int(gap / 1.3)                        # etwa alle 75 Grad eine Achse
            targets += [a + gap * k / (n + 1) for k in range(1, n + 1)]
        if not angs:
            a0 = rng.uniform(0, 2 * math.pi)
            targets = [a0 + k * math.pi / 3 for k in range(6)]
        for a in targets:
            ray = LineString([c, c + np.array([math.cos(a), math.sin(a)]) * W * 2])
            segs = sorted(lines(ray.intersection(inner)), key=lambda ln: ln.distance(Point(c)))
            if not segs:
                continue
            end = max((Point(q) for q in (segs[0].coords[0], segs[0].coords[-1])), key=lambda q: q.distance(Point(c)))
            side = self.side_of(end)
            start = self.plaza_centers.get(side) or self.sides[side].representative_point().coords[0]
            if math.dist(start, (end.x, end.y)) < 120 * s:
                continue
            ln = bezier(start, (end.x, end.y), rng, bend=0.1)
            for piece in lines(ln.intersection(self.sides[side].buffer(2 * s))):
                roads.append((piece, 11 * s))
        if not self.walled:
            return
        # Altstadt: der alte Mauerring, um den die Stadt hinausgewachsen ist
        k = min(0.65, max(0.35, 1.6 * math.sqrt(11000 / self.cfg["einwohner"])))
        old = make_shape(rng, self.center, self.r * k)
        self.old_shape = old
        water = self.t["water"]
        for ring in lines(old.buffer(10 * s).exterior.intersection(self.city_land.buffer(-1 * s))):
            if ring.length > 40 * s:
                roads.append((ring, 8 * s))
        cross = [(ln, w) for ln, w in roads if w >= 11 * s]
        main_pc = list(self.plaza_centers.values())
        gates = []
        for ln, w in cross:
            for p in points(ln.intersection(old.exterior)):
                if not self.city_land.buffer(-4 * s).contains(p) or p.distance(water) < 20 * s:
                    continue
                if any(p.distance(q) < 25 * s for q in gates):
                    continue
                gates.append(p)
                self.out["old_gates"].append((p.x, p.y, wall_angle(old, p)))
                o = unit((p.x - c[0], p.y - c[1]))
                q = (p.x + o[0] * 24 * s, p.y + o[1] * 24 * s)   # Torplatz vor dem alten Tor
                if all(math.dist(q, m) > 90 * s for m in main_pc):
                    pl = blob(rng, q[0], q[1], 21 * s, rough=0.2).intersection(self.city_land).difference(water.buffer(6 * s))
                    if pl.area > 600 * s * s:
                        plazas.append(pl)
        gaps = unary_union([ln.buffer(w / 2 + 5 * s) for ln, w in cross] + [water.buffer(4 * s)])
        wall = old.exterior.intersection(self.city_land).difference(gaps)
        self.out["old_wall"] = [ln for ln in lines(wall) if ln.length > 20 * s]
        for ln in self.out["old_wall"]:
            d = 30 * s
            while d < ln.length - 20 * s:
                p = ln.interpolate(d)
                if all(p.distance(g) > 30 * s for g in gates):
                    self.out["towers"].append((p.x, p.y, wall_angle(old, p)))
                d += rng.uniform(75, 95) * s
        self.old_wall = unary_union(self.out["old_wall"]) if self.out["old_wall"] else None

    def raze_harbor_wall(self):
        """Großstadt: reicht der Hafen von der Altstadt bis in den äußeren Ring, ist die alte Mauer dort längst
        geschleift - kurze Wege zwischen Kai und Stadt. Mauerstücke, Türme und alte Tore im Hafen entfallen."""
        old = getattr(self, "old_shape", None)
        if old is None or not self.out["old_wall"]:
            return
        s = self.s
        harbors = [d["poly"] for d in self.district_list if d["typ"] == "hafen" and not d["poly"].is_empty]
        if not harbors:
            return
        harbor = unary_union(harbors)
        inside = harbor.intersection(old).area
        if inside < 0.08 * harbor.area or harbor.difference(old).area < 0.08 * harbor.area:
            return                                        # Hafen liegt nur innen oder nur außen
        gone = harbor.buffer(12 * s)
        near = harbor.buffer(30 * s)   # kurze Reste, die am Hafenrand entlanglaufen, entfallen ebenfalls
        walls = [g for ln in self.out["old_wall"] for g in lines(ln.difference(gone))
                 if g.length > 20 * s and g.intersection(near).length < 0.5 * g.length]
        if len(walls) == len(self.out["old_wall"]) and sum(w.length for w in walls) >= \
                sum(w.length for w in self.out["old_wall"]) - 1:
            return
        old_lines = unary_union(self.out["old_wall"])
        self.out["old_wall"] = walls
        self.out["towers"] = [t for t in self.out["towers"]
                              if not (old_lines.distance(Point(t[0], t[1])) < 1 * s and gone.contains(Point(t[0], t[1])))]
        self.out["old_gates"] = [g for g in self.out["old_gates"] if not gone.contains(Point(g[0], g[1]))]
        self.old_wall = unary_union(walls) if walls else None

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
            if lage:   # Armenviertel liegen immer im äußeren Ring, also weiter draußen
                p = c + np.array(to_canonical(lage, self.rot)) * r * (0.85 if typ == "armen" else 0.6)
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
            elif typ == "armen":   # am Stadtrand, möglichst weit vom Zentrum und von den anderen Vierteln
                inner = self.city_land.buffer(-25 * s)
                inner = inner if not inner.is_empty else self.city_land
                minx, miny, maxx, maxy = inner.bounds
                best, bd = None, -1
                for _ in range(60):
                    q = (self.rng.uniform(minx, maxx), self.rng.uniform(miny, maxy))
                    if not inner.contains(Point(q)):
                        continue
                    dd = math.dist(q, self.center) + 0.5 * min([math.dist(q, sd) for sd in seeds] or [0])
                    if dd > bd:
                        best, bd = q, dd
                p = np.array(best) if best else None
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
            if sp.get("ausserhalb") and sp["typ"] != "armen":
                print(f"Hinweis: Nur Armenviertel können vor der Mauer liegen - '{sp.get('name')}' liegt in der Stadt.")
                sp["ausserhalb"] = False
            if (self.t.get("mountain") or self.t.get("plateau")) and sp["typ"] in ("hafen", "fischer"):
                new = "markt" if sp["typ"] == "hafen" else "handwerk"
                where = "ins Gebirge" if self.t.get("mountain") else "an die Plateaukante"
                print(f"Hinweis: '{sp.get('name')}' ({sp['typ']}) passt nicht {where} - wird als {new} gebaut.")
                sp["typ"] = new
            if sp["typ"] == "hafen" and not has_water:
                print(f"Hinweis: '{sp.get('name')}' ist ein Hafen, aber es gibt kein Wasser - wird als Markt gebaut.")
                sp["typ"] = "markt"
        if all(sp.get("ausserhalb") for sp in specs):   # alle Viertel vor der Mauer: drinnen einfache Wohnbebauung
            specs = list(specs) + [dict(UNNAMED_DISTRICT)]
        seeds = self.district_seeds(specs)
        self.seeds = seeds
        self.district_list = [{"name": sp.get("name", ""), "typ": sp["typ"], "poly": Polygon(),
                               "outside": bool(sp.get("ausserhalb")), "groesse": sp.get("groesse")} for sp in specs]
        idx = [i for i, sp in enumerate(specs) if not sp.get("ausserhalb")]
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
        self._poor_to_outer_ring(idx)
        for d in self.district_list:
            if d["poly"].is_empty and not d["outside"]:
                print(f"Hinweis: Viertel '{d['name']}' hat keinen Platz gefunden.")
        self.out["districts"] = self.district_list

    def _poor_to_outer_ring(self, idx):
        """Armenviertel liegen nie im inneren Ring (Großstadt: Altstadt; sonst die inneren 60 % der Stadt).
        Was davon im Kern lag, bekommt das nächstgelegene andere Viertel."""
        dl, s = self.district_list, self.s
        poor = [i for i in idx if DISTRICT_TYPES.get(dl[i]["typ"], {}).get("poor") and not dl[i]["poly"].is_empty]
        others = [i for i in idx if i not in poor and not dl[i]["poly"].is_empty]
        if not poor or not others:
            return
        old = getattr(self, "old_shape", None)
        core = old if old is not None else shapely.affinity.scale(self.shape, 0.6, 0.6, origin=self.center)
        core = core.intersection(self.city_land)
        for i in poor:
            inner = dl[i]["poly"].intersection(core)
            if inner.area < 50 * s * s:
                continue
            dl[i]["poly"] = dl[i]["poly"].difference(core)
            for piece in polys(inner):
                j = min(others, key=lambda k: dl[k]["poly"].distance(piece))
                dl[j]["poly"] = dl[j]["poly"].union(piece)

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
        # Größe des Hafens: Breite des Kai-Streifens (groß = bisheriger Hafen)
        depth = {"klein": 65, "mittel": 105}.get(dl[hi].get("groesse"), 150) * s
        harbor = self.sides[side].intersection(self.t["water"].buffer(depth))
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
        if getattr(self, "old_wall", None) is not None:
            blockers.append(self.old_wall.buffer(8 * s))
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
        g = self.g
        for piece in clean(rest, 300 * s2):
            if self.grand:   # Großstadt: kleinere Quartiere, schmalere Quartiersstraßen
                qs = subdivide(piece, 11000 * s2, 6 * s, rng, min_area=250 * s2, var=0.25)
            else:
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
            grand = self.grand and not st.get("paved")   # der Hafen behält seine einzelnen Lagerhäuser
            if grand:
                block_area, alley = st["block"] * 0.5 / g ** 0.5 * s2, max(2.2, st["alley"] * 0.5 / g ** 0.5) * s
            else:
                block_area, alley = st["block"] * s2, st["alley"] * s
            # lockere Bebauung: größere Grundstücke mit Abstand zwischen den Häusern, breitere Gassen, mehr Gärten;
            # zusammen mit der größeren Stadtfläche bleibt die Zahl der Häuser etwa gleich
            A = 1.0 if st.get("paved") else self.spread
            density, inner = st["density"] / A ** 0.5, st.get("inner", 0.0) / A
            if A > 1:
                lot *= A ** 0.5
                block_area *= A ** 0.5
                alley *= 1 + 0.5 * (A - 1)
            for piece in clean(quarter, lot * 0.5):
                blocks = subdivide(piece, block_area, alley, rng, min_area=min(lot, block_area) * 0.5)
                streets.append(piece.difference(unary_union(blocks)) if blocks else piece)
                for blk in blocks:
                    entry = {"poly": blk, "district": di, "ids": []}
                    self.blocks.append(entry)
                    if grand:   # ganzer Block als geschlossene Häuserzeile, selten ein Garten
                        if rng.random() < max(0.9, st["density"]) / A ** 0.5:
                            b = self.block_mass(blk, st, di, poor)
                            if b is not None:
                                entry["ids"].append(len(self.out["buildings"]))
                                self.out["buildings"].append(b)
                        continue
                    # Armenviertel: gleichmäßigere Parzellen, sonst entstehen zu viele zu schmale Restflächen
                    lots = subdivide(blk, lot, 0, rng, min_area=lot * 0.12, var=0.25 if poor else 0.5, jitter=0.1)
                    edge = blk.exterior.buffer(0.8 * s)
                    for lp in lots:
                        # über Sumpfwasser: Pfahlhäuser mit Wasser dazwischen, etwas lockerer
                        wet = pools is not None and pools.contains(lp.representative_point())
                        perim = (not st["perimeter"]) or lp.exterior.intersection(edge).length > 2 * s
                        back = not perim and rng.random() < inner * (0.3 if wet else 1)
                        if (perim and rng.random() < density * (0.75 if wet else 1)) or back:
                            inset = (4 if d["typ"] == "hafen" else 2.4 if wet else 1.0) * s
                            if A > 1 and d["typ"] != "hafen":
                                inset += 2.5 * (A - 1) * s   # Abstand zu den Nachbarhäusern
                            for part in clean(lp.buffer(-inset, join_style="mitre"), lot * 0.12):
                                # nur erlaubte geometrische Formen mit Mindestbreite; zu schmale Restflächen bleiben Hof
                                bp, form = house_shape(part, rng, MIN_HOUSE * s, MAX_HOUSE_RATIO,
                                                       special_chance=0.0 if poor else 0.12)
                                if bp is not None and poor:   # Hütten stehen schief auf dem Grundstück
                                    tilt = shapely.affinity.rotate(bp, rng.uniform(-8, 8), origin="centroid")
                                    if part.buffer(0.6 * s).contains(tilt):
                                        bp = tilt
                                if bp is not None:
                                    entry["ids"].append(len(self.out["buildings"]))
                                    self.out["buildings"].append(
                                        {"poly": bp, "form": form, "color": self.roof_color(st), "district": di,
                                         "poor": poor})
                        elif (not perim or A > 1) and rng.random() < 0.35 * A:   # Hof bzw. Garten mit Baum
                            c = lp.representative_point()
                            rad = max(5 * s, min(14 * s, math.sqrt(lp.area) * 0.4))
                            self.out["yard_trees"].append((c.x, c.y, rad))
        self.out["streets"] = [unary_union(streets).intersection(self.city_land)]
        self.connect_to_streets()

    def block_mass(self, blk, st, di, poor):
        """Großstadt: ein Häuserblock als geschlossene Zeile schmaler Häuser um einen Innenhof. Jedes Haus ist eine
        Dachfläche entlang der Fassade (Voronoi-Zellen aus Punkten auf der Außenkante), mit eigener Dachfarbe;
        der First läuft in halber Haustiefe rund um den Block."""
        s, rng = self.s, self.rng
        parts = clean(blk.buffer(-0.5 * s, join_style="mitre"), 30 * s * s)
        if not parts:
            return None
        mass = orient(max(parts, key=lambda p: p.area), 1.0)
        if min_width(mass) < MIN_HOUSE * s:
            return None
        depth = rng.uniform(10, 13) * s * (0.85 if poor else 1.0)
        court = None
        inner = mass.buffer(-depth, join_style="mitre")
        if not inner.is_empty:
            ip = max(polys(inner), key=lambda p: p.area)
            if ip.area > 70 * s * s and min_width(ip) > 5 * s:
                court = ip
        ring = mass.difference(court) if court is not None else mass
        if ring.geom_type != "Polygon":
            return None
        ring = orient(ring, 1.0)
        ext = mass.exterior                          # gegen den Uhrzeigersinn: Normale (ty, -tx) zeigt nach außen
        # Hausbreiten gleichmäßig um den Block verteilt (mit etwas Spiel), damit an der Nahtstelle kein Splitter bleibt
        pts, normals = [], []
        L = ext.length
        n_h = max(3, round(L / (rng.uniform(9.5, 11.5) * s)))
        k0 = rng.uniform(0, L / n_h)
        for i in range(n_h):
            k = (k0 + (i + rng.uniform(-0.18, 0.18)) * L / n_h) % L
            p, q = ext.interpolate(k), ext.interpolate(min(L, k + 1.0))
            if q.distance(p) < 0.5:
                q, p = p, ext.interpolate(k - 1.0)
            tx, ty = unit((q.x - p.x, q.y - p.y))
            pts.append((p.x, p.y))
            normals.append((ty, -tx))
        segs = []
        cells = shapely.voronoi_polygons(MultiPoint(pts), ordered=True, extend_to=mass.buffer(depth * 3))
        for n, cell in zip(normals, cells.geoms):
            for piece in clean(cell.intersection(ring), 1 * s * s):
                # zu schmale Reste (an Ecken) gehören zum Nachbarhaus
                if segs and min_width(piece) < 0.8 * MIN_HOUSE * s:
                    joined = segs[-1][0].union(piece)
                    if joined.geom_type == "Polygon":
                        segs[-1] = (joined, segs[-1][1], segs[-1][2])
                        continue
                segs.append((piece, n, self.roof_color(st)))
        # übrige Splitter (Anfang der Runde, Ecken) dem Nachbarn mit der längsten gemeinsamen Kante zuschlagen
        i = 0
        while i < len(segs) and len(segs) > 1:
            piece = segs[i][0]
            if min_width(piece) >= 0.8 * MIN_HOUSE * s:
                i += 1
                continue
            grow = piece.buffer(0.2 * s)
            best = max((j for j in range(len(segs)) if j != i), key=lambda j: grow.intersection(segs[j][0]).area)
            joined = segs[best][0].union(piece).buffer(0.01).buffer(-0.01)
            if joined.geom_type != "Polygon" or grow.intersection(segs[best][0]).area <= 0:
                # berührt der Splitter den Nachbarn nur an einem Punkt oder über einen Haarspalt: den Spalt im
                # Ring mit auffüllen (ohne in andere Häuser zu wachsen)
                others = unary_union([sg for j, (sg, _, _) in enumerate(segs) if j not in (i, best)] or [Polygon()])
                bridge = piece.buffer(0.8 * s).intersection(ring).difference(others)
                joined = segs[best][0].union(bridge).buffer(0.01).buffer(-0.01)
                if joined.geom_type != "Polygon":
                    if piece.area < (MIN_HOUSE * s) ** 2:   # winziger, nirgends anschließbarer Rest: weglassen
                        segs.pop(i)
                        i = 0
                    else:
                        i += 1
                    continue
            segs[best] = (joined, segs[best][1], segs[best][2])
            segs.pop(i)
            i = 0
        if not segs:
            segs = [(ring, (0.0, -1.0), self.roof_color(st))]
        mid = mass.buffer(-depth / 2, join_style="mitre")
        ridge = [ln for ln in lines(mid.boundary)] if not mid.is_empty else []
        return {"poly": ring, "form": "block", "segments": segs, "block_ridge": ridge, "color": segs[0][2], "court": court,
                "district": di, "poor": poor, "ridges": None, "shade": None}

    def outside_slums(self, ext):
        """Armenviertel vor der Mauer: Hüttensiedlungen in mehreren Gruppen rund um die Stadt, mit etwas Abstand zur
        Mauer, nicht auf Landstraßen und nicht im Wasser. Schiefe Hütten dicht an dicht, schlammige Pfade dazwischen."""
        dl = self.district_list
        outs = [i for i, d in enumerate(dl) if d["outside"]]
        if not outs:
            return
        s, rng, W = self.s, self.rng, self.W
        s2 = s * s
        st = DISTRICT_TYPES["armen"]
        lot = st["lot"] * s2
        water, pools = self.t["water"], self.t.get("pools")
        blocked = unary_union([self.shape.buffer(16 * s), water.buffer(6 * s)]
                              + [ln.buffer(w / 2 + 3 * s) for ln, w in ext]
                              + ([pools] if pools is not None and not pools.is_empty and not self.t["biome"]["stilts"] else []))
        frame = box(0, 0, W, W).buffer(-15 * s)
        depth = (40 + 30 * min(1.0, self.cfg["einwohner"] / 20000)) * s   # Breite des Hüttengürtels
        n = rng.randint(4, 6) * len(outs) if len(outs) < 3 else 2 * len(outs)
        a0 = rng.uniform(0, 2 * math.pi)
        c = np.array(self.center)
        far = W * 2
        clusters = {i: [] for i in outs}
        used = Polygon()
        for k in range(n):
            a = a0 + 2 * math.pi * k / n + rng.uniform(-0.08, 0.08)
            half = (math.pi / n) * rng.uniform(0.35, 0.7)
            wedge = Polygon([c] + [c + np.array([math.cos(b), math.sin(b)]) * far
                                   for b in np.linspace(a - half, a + half, 8)])
            belt = self.shape.buffer(16 * s + depth * rng.uniform(0.6, 1.25)).difference(blocked)
            for piece in clean(belt.intersection(wedge).intersection(frame).difference(used), 900 * s2):
                clusters[outs[k % len(outs)]].append(piece)
                used = used.union(piece.buffer(8 * s))
        streets, all_area = [], []
        for di, pieces in clusters.items():
            for piece in pieces:
                blocks = subdivide(piece, st["block"] * s2 * 0.6, st["alley"] * s, rng, min_area=lot * 0.5)
                if not blocks:
                    continue
                bu = unary_union(blocks)
                streets.append(piece.difference(bu))
                all_area.append(piece)
                for blk in blocks:
                    for lp in subdivide(blk, lot, 0, rng, min_area=lot * 0.12, var=0.25, jitter=0.1):
                        if rng.random() > 0.85:
                            continue
                        for part in clean(lp.buffer(-1.0 * s, join_style="mitre"), lot * 0.12):
                            bp, form = house_shape(part, rng, MIN_HOUSE * s, MAX_HOUSE_RATIO, special_chance=0.0)
                            if bp is None:
                                continue
                            tilt = shapely.affinity.rotate(bp, rng.uniform(-8, 8), origin="centroid")
                            if part.buffer(0.6 * s).contains(tilt):
                                bp = tilt
                            self.out["buildings"].append({"poly": bp, "form": form, "color": self.roof_color(st),
                                                          "district": di, "poor": True})
            dl[di]["poly"] = unary_union(pieces) if pieces else Polygon()
            if not pieces:
                print(f"Hinweis: Für das Armenviertel '{dl[di]['name']}' ist vor der Mauer kein Platz.")
        if streets:
            self.out["streets"].append(unary_union(streets))
            self.out["slum_outside"] = unary_union(all_area)

    def faubourgs(self, ext):
        """Großstadt: Vorstädte entlang der Landstraßen vor den Toren, am Tor dicht, nach außen ausdünnend."""
        if not self.grand:
            return
        s, rng, W = self.s, self.rng, self.W
        st = DISTRICT_TYPES["wohn"]
        g = self.g
        block_area, alley = st["block"] * 0.5 / g ** 0.5 * s * s, max(2.2, st["alley"] * 0.5 / g ** 0.5) * s
        reach = self.r * min(0.55, 0.2 + 0.1 * g)
        pools = self.t.get("pools")
        taken = unary_union([self.shape.buffer(28 * s), self.t["water"].buffer(8 * s), self.out["slum_outside"].buffer(10 * s)]
                            + ([pools.buffer(4 * s)] if pools is not None and not pools.is_empty else []))
        roads_u = unary_union([ln.buffer(w / 2 + 2 * s) for ln, w in ext]) if ext else Polygon()
        frame = box(0, 0, W, W).buffer(-12 * s)
        kept = []
        for ln, w in ext:
            L = min(ln.length, reach)
            seg = substring(ln, 0, L)
            band = seg.buffer((36 + 8 * g) * s, cap_style="flat").difference(roads_u).difference(taken).intersection(frame)
            taken = taken.union(band)
            for piece in clean(band, 400 * s * s):
                for blk in subdivide(piece, block_area, alley, rng, min_area=block_area * 0.35):
                    t = seg.project(blk.centroid) / max(L, 1)
                    if rng.random() > 1.0 - 0.8 * t:
                        continue
                    b = self.block_mass(blk, st, -1, False)
                    if b is not None:
                        self.out["buildings"].append(b)
                        kept.append(blk)
        if kept:
            ku = unary_union(kept)
            self.out["streets"].append(ku.buffer(alley * 0.9, join_style="mitre").difference(ku).difference(roads_u))
            self.out["faubourg"] = ku.buffer(6 * s)

    def connect_to_streets(self, landmarks=False):
        """Jedes Haus muss an eine Straße oder einen Platz grenzen. Häuser ohne Anschluss werden zur nächsten
        Straße geschoben, wenn dort Platz ist; sonst entfallen sie (die Fläche wird Hof)."""
        s = self.s
        net = unary_union(self.out["streets"] + self.out["plazas"] + self.out["paved"]
                          + [g for g, kind in self.out["grounds"] if kind == "plaza"])
        shapely.prepare(net)
        alive = [b for b in self.out["buildings"] if not b.get("removed")]
        tree = shapely.STRtree([b["poly"] for b in alive])
        shifted = set()
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
            # der Suchbaum kennt nur die alten Lagen: schon verschobene Häuser zusätzlich prüfen
            near = [j for j in set(tree.query(cand.buffer(0.8 * s))) | shifted if j != i]
            ok = (self.city_land.contains(cand) and cand.intersection(net).area < 0.5 * s * s
                  and not any(cand.buffer(0.8 * s).intersects(alive[j]["poly"]) for j in near))
            if ok:
                b["poly"] = cand
                shifted.add(i)
            elif landmarks:
                continue   # Sondergebäude nie streichen
            else:
                b["removed"] = True

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
            if typ == "werft" and not self.t["water"].is_empty:
                target = self._shipyard(di)
                if target is None:
                    print(f"Hinweis: Kein Uferplatz für die Werft '{o['name']}' - sie steht etwas abseits vom Wasser.")
            if target is None and typ in BIG_LANDMARKS:
                blks = [bk for bk in self.blocks if (di is None or bk["district"] == di)
                        and {"friedhof": 2500, "kaserne": 2500, "tempel": 1500, "rathaus": 1500,
                             "palast": 5000, "kathedrale": 4500}.get(typ, 900) * s * s
                        < bk["poly"].area < (16000 if typ in COMPACT else 9000) * s * s
                        and min_width(bk["poly"]) > (42 if typ in COMPACT else 28) * s
                        and (typ not in COMPACT or bk["poly"].area / bk["poly"].minimum_rotated_rectangle.area > 0.7)
                        # Blöcke mit einem schon gesetzten besonderen Ort nicht abräumen (sonst bliebe z.B. von der
                        # Wassermühle nur das Rad samt Beschriftung übrig)
                        and not any(self.out["buildings"][i].get("landmark") for i in bk["ids"])]
                outside = str(o.get("lage", "")) in ("ausserhalb", "aussen", "draussen", "vorderstadt")
                merged = None
                if self.grand and not blks and not outside and typ != "werft":
                    merged = self._merged_block(typ, di)   # Großstadt: mehrere kleine Blöcke zusammenlegen
                    blks = [merged] if merged is not None else []
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
                    if bk is not merged:
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
                if LANDMARK_COLORS.get(typ) and target.get("form") != "block":
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
            where = target["poly"]
            if target.get("form") == "block":   # Großstadt: der Ort ist ein Haus der Häuserzeile, zur Hauptstraße hin
                k = min(range(len(target["segments"])),
                        key=lambda j: target["segments"][j][0].distance(self.main_streets))
                seg, n, col = target["segments"][k]
                target["segments"][k] = (seg, n, LANDMARK_COLORS.get(typ) or col)
                where = seg
            c = where.centroid
            self.out["labels"].append({"x": c.x, "y": c.y, "text": text, "kind": "ort",
                                       "lift": math.sqrt(where.area) * 0.5 + 6 * s,
                                       "ort": place_info(o, self.district_name(target["district"]))})

    def _shipyard(self, di):
        """Werft direkt am Ufer: lange Halle quer zum Ufer, zum Wasser hin offen. Im Helling liegt ein Schiff im Bau;
        sein Heck steckt in der Halle, der Bug zeigt aufs Wasser hinaus. Im Fluss bleibt die Fahrrinne frei
        (der Bug ragt höchstens 35 % der Flussbreite hinein). Liefert die Halle (als Gebäude) oder None."""
        s, rng = self.s, self.rng
        water, river, sea = self.t["water"], self.t["river"], self.t["sea"]
        if self.t.get("mountain") or self.t.get("plateau"):   # Fels bzw. Plateaukante ist kein Ufer: nur am Fluss
            if river is None or river.is_empty:
                return None
            water, sea = river, None
        dl = self.district_list
        if di is None:                                # ohne Angabe bevorzugt im Hafen
            di = next((i for i, d in enumerate(dl) if d["typ"] == "hafen" and not d["poly"].is_empty), None)
        alive = [b for b in self.out["buildings"] if not b.get("removed")]
        net = unary_union(self.out["streets"] + self.out["plazas"] + self.out["paved"])
        crossings = unary_union([ln.buffer(w / 2 + 34 * s) for ln, w in self.out["internal_roads"] if ln.intersects(water)])
        # Durchgangsstraßen (Tor-, Brücken-, Hauptachsen) bleiben frei; schmale Ringstraßen nur außerhalb des Kais:
        # auf dem gepflasterten Hafen sind sie ohnehin unter dem Pflaster verschwunden
        paved = unary_union(self.out["paved"]) if self.out["paved"] else Polygon()
        through = unary_union([ln.buffer(w / 2 + 1 * s) for ln, w in self.out["internal_roads"] if w > 9.5 * s])
        rings = unary_union([ln.buffer(w / 2 + 1 * s) for ln, w in self.out["internal_roads"] if w <= 9.5 * s])
        keep_clear = unary_union([through, rings.difference(paved), unary_union(self.out["plazas"]).buffer(2 * s), crossings]
                                 + [b["poly"].buffer(2 * s) for b in alive if b.get("landmark")]
                                 + [g.buffer(2 * s) for g, _ in self.out["grounds"]]
                                 + ([self.shape.exterior.buffer(12 * s)] if self.walled else []))
        shapely.prepare(keep_clear)

        def search(area, hw):
            sw = hw / 2                               # Schiffsbreite
            cands = []
            for ln in lines(water.boundary.intersection(area.buffer(2 * s))):
                k = hw / 2 + 4 * s
                while k < ln.length - hw / 2 - 4 * s:
                    q, q2 = ln.interpolate(k), ln.interpolate(k + 2)
                    k += 7 * s
                    tx, ty = unit((q2.x - q.x, q2.y - q.y))
                    nx, ny = -ty, tx                   # Normale zeigt ins Land
                    if water.contains(Point(q.x + nx * 6 * s, q.y + ny * 6 * s)):
                        nx, ny = -nx, -ny
                    t_, n_ = np.array([tx, ty]), np.array([nx, ny])
                    # so tief ins Land wie möglich; am gebogenen Ufer ragen die Hallenecken sonst ins Wasser:
                    # notfalls etwas zurück (Helling davor)
                    hall = None
                    for hd in (64 * s, 52 * s, 42 * s, 34 * s, 28 * s):
                        for back in (1.5, 3, 4.5, 6, 8):
                            f0 = np.array([q.x, q.y]) + n_ * back * s
                            h = Polygon([f0 - t_ * hw / 2, f0 + t_ * hw / 2, f0 + t_ * hw / 2 + n_ * hd,
                                         f0 - t_ * hw / 2 + n_ * hd])
                            if not h.intersects(water):
                                break
                        if (not h.intersects(water) and self.city_land.contains(h) and not keep_clear.intersects(h)
                                and h.buffer(3 * s).intersects(net)):
                            hall = h
                            break
                    if hall is None:
                        continue
                    hl = min(62 * s, (hd + back * s - 3 * s) / 0.55)   # das Heck endet vor der Rückwand der Halle
                    probe = Point(q.x - nx * 10 * s, q.y - ny * 10 * s)
                    in_river = river is not None and river.contains(probe) and (sea is None or not sea.contains(probe))
                    out_len = 0.45 * hl
                    # Ausfahrt: auf See gut zwei Schiffslängen offenes Wasser vor dem Bug, im Fluss Wasser bis
                    # über die Flussmitte (dort dreht das Schiff in die Strömung)
                    lane_len = 2.2 * hl
                    if in_river:                       # örtliche Flussbreite quer übers Wasser
                        ray = LineString([(q.x - nx * 1 * s, q.y - ny * 1 * s), (q.x - nx * 600 * s, q.y - ny * 600 * s)])
                        seg = [g for g in lines(ray.intersection(water)) if g.distance(q) < 3 * s]
                        width = seg[0].length if seg else 0
                        out_len = min(out_len, 0.35 * width - 2 * s)
                        if out_len < 0.25 * hl:
                            continue
                        lane_len = 0.6 * width
                    c = np.array([q.x, q.y]) + n_ * (hl / 2 - out_len)
                    hull = ship_footprint(c[0], c[1], hl, sw, math.degrees(math.atan2(-ny, -nx)))
                    bow = hull.difference(hall.buffer(0.5 * s))   # über dem Helling darf ein schmaler Landstreifen liegen
                    if bow.difference(water.buffer(1 * s)).area > 0.25 * bow.area or crossings.intersects(hull):
                        continue
                    q0, bd = np.array([q.x, q.y]), -n_
                    lw = sw / 2 + 6 * s
                    lane = Polygon([q0 - t_ * lw, q0 + t_ * lw, q0 + t_ * lw + bd * lane_len, q0 - t_ * lw + bd * lane_len])
                    ahead = lane.difference(hall.buffer(1 * s))
                    if ahead.difference(water).area > 0.04 * ahead.area or crossings.intersects(lane):
                        continue
                    score = (0 if not in_river else 40) - hall.area / (100 * s * s) \
                        + hall.centroid.distance(Point(self.center)) / (40 * s)
                    cands.append((score, hall, hull, c, (-nx, -ny), hl, sw, lane))
            return cands

        # erst im gewünschten Viertel, dann am ganzen Stadtufer; erst die große Halle, notfalls etwas schmaler
        areas = ([dl[di]["poly"]] if di is not None else []) + [self.city_land]
        cands = []
        for area in areas:
            for hw in (30 * s, 26 * s, 22 * s):
                cands = search(area, hw)
                if cands:
                    break
            if cands:
                break
        if not cands:
            return None
        cands.sort(key=lambda cd: cd[0])
        _, hall, hull, c, (bx, by), hl, sw, lane = rng.choice(cands[:5])
        for b in alive:                                # Häuser auf dem Bauplatz weichen der Werft
            if b["poly"].intersects(hall.buffer(2 * s)) and not b.get("landmark"):
                b["removed"] = True
        self.out["yard_trees"] = [t for t in self.out["yard_trees"] if not hall.buffer(4 * s).contains(Point(t[0], t[1]))]
        self.out["ships"].append({"x": float(c[0]), "y": float(c[1]), "len": hl, "wid": sw,
                                  "angle": math.degrees(math.atan2(by, bx)), "big": False, "slip": True, "hall": hall,
                                  "lane": lane})
        self.shipyard_zones = getattr(self, "shipyard_zones", []) + [hall, hull, lane]   # Stege halten die Ausfahrt frei
        rp = hall.representative_point()
        dd = next((i for i, d in enumerate(dl) if d["poly"].buffer(10 * s).contains(rp)), -1)
        b = {"poly": hall, "form": "rechteck", "color": LANDMARK_COLORS["werft"], "district": dd}
        self.out["buildings"].append(b)
        return b

    def _merged_block(self, typ, di):
        """Großstadt: benachbarte kleine Blöcke (samt Gassen dazwischen) zu einem Bauplatz für ein großes Gebäude
        zusammenlegen, möglichst nah an einer Hauptstraße. Liefert einen Pseudo-Block oder None."""
        s = self.s
        need = {"friedhof": 5000, "kaserne": 4500, "tempel": 3500, "rathaus": 3500,
                "palast": 11000, "kathedrale": 10000}.get(typ, 2500) * s * s
        free = [bk for bk in self.blocks if not any(self.out["buildings"][i].get("landmark") for i in bk["ids"])]
        pool = [bk for bk in free if di is None or bk["district"] == di]
        if not pool:
            return None
        pool.sort(key=lambda bk: bk["poly"].distance(self.main_streets))
        tree = shapely.STRtree([bk["poly"] for bk in free])
        rad = math.sqrt(need) * 1.05
        gap = 3.6 * s * (1 + 0.5 * (self.spread - 1))   # überbrückt Gassen und Quartiersstraßen, nicht die Hauptstraßen
        best = None
        # findet sich kein Bauplatz (z.B. lockere Bebauung: Gärten und breitere Gassen trennen die Blöcke),
        # im größeren Umkreis suchen
        for rad in (rad, rad * 1.5):
            if best is not None:
                break
            for bk in pool[:40]:
                c = bk["poly"].centroid
                near = [free[j] for j in tree.query(c.buffer(rad)) if free[j]["poly"].centroid.distance(c) < rad]
                area = unary_union([b["poly"].buffer(gap, join_style="mitre") for b in near]).buffer(-gap, join_style="mitre")
                area = area.difference(self.main_streets.buffer(1 * s))
                parts = polys(area)
                if not parts:
                    continue
                area = max(parts, key=lambda p: p.area)
                rect = fit_rect(area, 2 * MIN_HOUSE * s)
                if rect is None or rect.area < need * 0.6:
                    continue
                members = [b for b in near if b["poly"].intersects(area)]
                if best is None or rect.area > best[0]:
                    best = (rect.area, area, members)
        if best is None:
            return None
        _, area, members = best
        for b in members:
            self.blocks.remove(b)
        return {"poly": area, "district": di if di is not None else members[0]["district"],
                "ids": [i for b in members for i in b["ids"]]}

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
        occupied += [z.buffer(6 * s) for z in getattr(self, "shipyard_zones", [])]   # Werft mit Schiff im Helling
        # Stege nur am Hafen (am gepflasterten Kai) und im Fluss - nicht die ganze Meeresküste entlang
        # (Anlegestellen am Ende einer Landstraße entstehen in external_roads)
        quay = unary_union(self.out["paved"]).buffer(15 * s) if self.out["paved"] else Polygon()
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
                    if not in_river and not (big and quay.contains(p)):
                        continue
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
                    # Ausfahrt: das Schiff muss vom Steg ablegen können - auf See ein Korridor in Bugrichtung bis
                    # aufs offene Wasser (keine Insel, kein Ufer, keine anderen Stege oder Schiffe), im Fluss
                    # genügt die freie Fahrrinne
                    lane = None
                    if not in_river:
                        far = max(3.0 * hl, 140 * s)
                        lane = LineString([(cx, cy), (cx + nx * far, cy + ny * far)]).buffer(hw / 2 + 3 * s, cap_style="flat")
                        if not water.buffer(1 * s).contains(lane) or any(lane.intersects(o) for o in others):
                            continue
                    if water.buffer(1 * s).contains(hull) and not any(hull.buffer(2 * s).intersects(o) for o in others):
                        self.out["ships"].append({"x": cx, "y": cy, "len": hl, "wid": hw, "angle": angle, "big": big,
                                                  "depart": lane})
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
        self.raze_harbor_wall()
        self.buildings(internal)
        self.outside_slums(ext)
        self.landmarks()
        self.connect_to_streets(landmarks=True)
        self.squares_and_wells()
        self.district_labels()
        if not (self.t.get("mountain") or self.t.get("plateau")):
            self.harbor()
        if self.t["biome"]["forges"]:   # glühende Essen in Handwerksvierteln
            for b in self.out["buildings"]:
                d = b["district"]
                if 0 <= d < len(self.district_list) and self.district_list[d]["typ"] == "handwerk" \
                        and self.rng.random() < 0.15 and not b.get("landmark"):   # z.B. nicht auf einem Domturm
                    b["forge"] = True
        if self.cfg["mauer"].get("vorstaedte", True):   # abschaltbar: keine Vorstädte vor den Toren
            self.faubourgs(ext)
        self.fill_empty_with_trees()
        for b in self.out["buildings"]:
            if not b.get("removed") and "ridges" not in b:
                b["ridges"], b["shade"] = roof(b["poly"])
        self.out["buildings"] = [b for b in self.out["buildings"] if not b.get("removed")]
        self.out["shape"] = self.shape
        self.out["city_land"] = self.city_land
        return self.out, ext, internal
