"""Meer, Küste, Inseln und Fluss."""
import math
import random

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from .geo import Noise1D, blob, polys


def smoothstep(e0, e1, x):
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def make_coast(rng, W, s, has_coast, depth=0.17, amp=1.0):
    """Liefert Meer-Polygon (oder None) und eine Funktion x -> y der Küstenlinie.
    Im Gebirge ist dieselbe Fläche das Felsmassiv (tiefer und zerklüfteter)."""
    if not has_coast:
        return None, None
    big, mid, small = Noise1D(rng), Noise1D(rng), Noise1D(rng)
    base = W * depth

    def coast_y(x):
        if amp == 1.0:   # exakt die ursprüngliche Formel, damit bestehende Seeds gleich bleiben
            return (base + W * 0.05 * big.fbm(x / W * 3, 4) + W * 0.03 * mid.fbm(x / W * 10, 3)
                    + W * 0.014 * small.fbm(x / W * 45, 3))
        return (base + amp * (W * 0.05 * big.fbm(x / W * 3, 4) + W * 0.03 * mid.fbm(x / W * 10, 3)
                + W * 0.014 * small.fbm(x / W * 45, 3)))

    n = 600
    pts = [(-20, -20)] + [(W * i / n, coast_y(W * i / n)) for i in range(n + 1)] + [(W + 20, -20)]
    pts[1] = (-20, pts[1][1])
    pts[-2] = (W + 20, pts[-2][1])
    sea = Polygon(pts).buffer(0)
    # Landzungen und Buchten abseits der Stadtmitte
    for _ in range(rng.randint(3, 5)):
        x = rng.choice([rng.uniform(0.02, 0.3), rng.uniform(0.7, 0.98)]) * W
        y = coast_y(x)
        if rng.random() < 0.5:
            tongue = blob(rng, x, y - rng.uniform(20, 50) * s, rng.uniform(35, 75) * s, rough=0.5,
                          stretch=(rng.uniform(0.5, 1.2), rng.uniform(1.0, 1.8)))
            sea = sea.difference(tongue)
        else:
            bay = blob(rng, x, y + rng.uniform(15, 35) * s, rng.uniform(30, 60) * s, rough=0.45,
                       stretch=(rng.uniform(1.0, 1.6), rng.uniform(0.6, 1.0)))
            sea = sea.union(bay)
    # feine Felskante: kleine Ausbisse entlang der Küstenlinie
    sea = max(polys(sea), key=lambda p: p.area)   # abgetrennte Binnenseen verwerfen
    edge = [p for p in sea.exterior.coords if 0 < p[0] < W and p[1] > 0]
    nibbles = [Point(*rng.choice(edge)).buffer(rng.uniform(4, 11) * s) for _ in range(160)] if edge else []
    if nibbles:
        sea = sea.union(unary_union(nibbles)).buffer(1.5 * s).buffer(-1.5 * s)
    return sea, coast_y


def make_islands(rng, W, s, sea, coast_y, count):
    islands = []
    inner = None   # sea.buffer(-25 * s) ist für alle Kandidaten gleich: beim ersten Bedarf, dann nur einmal berechnen
    for _ in range(count * 4):
        if len(islands) >= count:
            break
        x = rng.uniform(0.05, 0.95) * W
        y = rng.uniform(0.0, coast_y(x) - 90 * s)
        if y < 10 * s:
            continue
        isl = blob(rng, x, y, rng.uniform(18, 50) * s, rough=0.35, stretch=(rng.uniform(1, 1.8), 1))
        if inner is None:
            inner = sea.buffer(-25 * s)
        if inner.contains(isl) and all(isl.distance(o) > 40 * s for o in islands):
            islands.append(isl)
    return islands


def make_river(rng, W, s, center, r, coast_y, width, estuary=True, end_y=None, gorge=None):
    """Fluss vom Süden durch das Stadtzentrum zur Küste (bzw. zum Nordrand).
    gorge (Gebirge): {"y_a", "y_b", "seed"}. Der Fluss ist eine Klamm mit leicht wechselnder Breite (in der Stadt
    gleichmäßig, nie zu breit). Wo das Tal beginnt (y_a), läuft sie aus: bis y_b wird sie glatt schmaler und fließt als
    kleiner Bach weiter. Das Rauschen für die Breite kommt aus einem eigenen, vom Seed abgeleiteten Zufallsgenerator: der
    übrige Zufallsstrom der Karte bleibt unverändert."""
    cx, cy = center
    noise = Noise1D(rng)
    y0 = W + 40
    y1 = coast_y(cx) - 80 * s if coast_y else -40
    if end_y is not None:
        y1 = min(y1, end_y)
    n = 160
    ref = noise.fbm(cy / W * 3)
    line = []
    for i in range(n + 1):
        y = y0 + (y1 - y0) * i / n
        d = min(1.0, abs(y - cy) / (W * 0.35))
        amp = W * (0.025 + 0.12 * d)
        line.append((cx + amp * (noise.fbm(y / W * 3) - ref) * 2, y))
    mouth = coast_y(cx) if coast_y else -W

    if gorge:
        gn = Noise1D(random.Random(f"klamm-{gorge['seed']}"))
        ys = [min(y0, y1) + abs(y0 - y1) * i / 200 for i in range(201)]
        vals = [gn.fbm(y / (W * 0.16)) for y in ys]
        lo, hi = min(vals), max(vals)

        brook = min(20.0, max(12.0, 0.3 * width)) * s                   # Breite des Baches im Tal

        def w_at(y):
            v = (gn.fbm(y / (W * 0.16)) - lo) / (hi - lo + 1e-9)       # 0..1, schmal bis breit
            vary = smoothstep(r * 1.0, r * 1.5, abs(y - cy))            # in der Stadt gleichmäßig, außerhalb wechselnd
            f = 1 + vary * (-0.18 + 0.38 * v)                           # 0,82 .. 1,2: leichte Schwankung, nie zu breit
            gorge_w = min(width * s * f, 80 * s)                        # auch bei großer Flussbreite nicht über 80 px
            t = smoothstep(gorge["y_a"], gorge["y_b"], y)               # flussabwärts: die Klamm läuft aus, wird zum Bach
            return (1 - t) * gorge_w + t * min(brook, gorge_w)
    else:
        def w_at(y):
            return width * s * (1 + (1.8 if estuary else 0.3) * smoothstep(cy + 0.2 * r, mouth + 40 * s, y))

    parts = []
    for (x0, y_0), (x1, y_1) in zip(line, line[1:]):
        w = w_at((y_0 + y_1) / 2)
        parts.append(LineString([(x0, y_0), (x1, y_1)]).buffer(w / 2))
    river = unary_union(parts).buffer(4 * s).buffer(-4 * s)
    return river.intersection(box(-50, -50, W + 50, W + 50)), LineString(line)


def make_pools(rng, W, s, density, water):
    """Sumpf: verstreute Tümpel und gewundene Wasserläufe (getrennt von Meer und Fluss)."""
    if density <= 0:
        return Polygon()
    parts = []
    for _ in range(int(55 * density)):
        x, y = rng.uniform(0, W), rng.uniform(0, W)
        parts.append(blob(rng, x, y, rng.uniform(16, 75) * s, rough=0.45,
                          stretch=(rng.uniform(0.7, 1.5), rng.uniform(0.7, 1.5))))
    for _ in range(int(14 * density)):
        noise = Noise1D(rng)
        x, y = rng.uniform(0, W), rng.uniform(0, W)
        a0 = rng.uniform(0, 2 * math.pi)
        pts = [(x, y)]
        for i in range(rng.randint(12, 30)):
            a = a0 + 1.6 * noise.fbm(i * 0.15)
            x, y = x + math.cos(a) * 14 * s, y + math.sin(a) * 14 * s
            pts.append((x, y))
        parts.append(LineString(pts).buffer(rng.uniform(4, 9) * s))
    pools = unary_union(parts).intersection(box(0, 0, W, W))
    if water is not None and not water.is_empty:
        pools = pools.difference(water.buffer(6 * s))
    return pools.buffer(2 * s).buffer(-2 * s)
