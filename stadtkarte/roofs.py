"""Detaillierte Dächer: Dachflächen mit Licht, Materialtextur (Ziegel, Schiefer, Schindel, Reet, Schnee),
Schornsteine und Glanz auf First und Graten."""
import colorsys
import math

import numpy as np
import shapely
from shapely.geometry import Polygon

from .geo import axes, hip_planes, is_rect, lines, polys, vdot, vlen

# Zeilenabstand und Fugenabstand (px bei 2000 px Bildgröße) je Material
MATERIALS = {
    "ziegel": dict(row=2.6, joint=2.8, jitter=0.15),
    "schiefer": dict(row=2.2, joint=3.8, jitter=0.25),
    "schindel": dict(row=2.4, joint=2.2, jitter=0.45),
    "reet": dict(row=0, joint=0, jitter=0),
    "schnee": dict(row=3.6, joint=0, jitter=0),
    "flicken": dict(row=2.0, joint=3.0, jitter=0.6),   # Armenviertel: krumme Bretter, mit Flicken
}


def _f(v):
    return f"{v:.1f}"


def _pd(g):
    out = []
    for p in polys(g):
        for ring in (p.exterior, *p.interiors):
            cs = list(ring.coords)[:-1]
            if len(cs) >= 3:
                out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in cs) + "Z")
    return "".join(out)


def _ld(g):
    return "".join("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in ln.coords) for ln in lines(g))


def shade(hex_color, k):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(v * k))) for v in (r, g, b)))


REED_ROOFS = ("sumpf", "steppe", "heide", "auwald", "hochmoor", "dschungel")   # Strohfarben sind dort Reet bzw. Palmblatt


def material_for(color, biome, thatch):
    """Dachmaterial aus Biotop und Dachfarbe."""
    if biome == "gebirge":
        return "schiefer"
    if biome == "nordland":
        return "schnee" if color in (thatch or []) else "schindel"
    if biome in REED_ROOFS and color in (thatch or []):
        return "reet"
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, sat, _ = colorsys.rgb_to_hsv(r, g, b)
    hue = h * 360
    if sat > 0.25 and (hue < 35 or hue > 340):
        return "ziegel"
    if sat > 0.2 and hue < 95:
        return "schindel"
    return "schiefer"


def planes(poly):
    """Walmdach-Flächen aus dem kleinsten umschließenden Rechteck:
    (Fläche, Normale nach außen, Richtung der Ziegelreihen, Punkt auf der Traufe, Tiefe bis zum First).
    Andere Grundrisse (L, Kreuz, Dreieck, Vielecke) bekommen ein allgemeines Walmdach."""
    if not is_rect(poly):
        return hip_planes(poly)[0]
    ax = axes(poly)
    if ax is None:
        return []
    o, e1, e2 = ax
    l1, l2 = vlen(e1), vlen(e2)
    if l2 < 1e-6:
        return []
    u, v = e1 / l1, e2 / l2
    h = min(l2 / 2, l1 / 2)
    a = o + e2 / 2 + u * h
    b = o + e1 + e2 / 2 - u * h
    raw = [
        (Polygon([o, o + e1, b, a]), -v, u, o, l2 / 2),
        (Polygon([o + e2, o + e1 + e2, b, a]), v, u, o + e2, l2 / 2),
        (Polygon([o, a, o + e2]), -u, v, o, h),
        (Polygon([o + e1, b, o + e1 + e2]), u, v, o + e1, h),
    ]
    out = []
    for geom, n, rd, eave, depth in raw:
        g = geom.buffer(0).intersection(poly)
        if not g.is_empty and g.area > 1:
            out.append((g, n, rd, eave, depth))
    return out


def _texture(geom, n, rd, eave, depth, s, rng, material):
    """Liefert (Fugenlinien, helle Striche) als SVG-Pfaddaten für eine Dachfläche."""
    if material == "reet":
        minx, miny, maxx, maxy = geom.bounds
        k = int(geom.area / (3.0 * s * s))
        if k <= 0:
            return "", ""
        xs = np.array([rng.uniform(minx, maxx) for _ in range(k)])
        ys = np.array([rng.uniform(miny, maxy) for _ in range(k)])
        ok = shapely.contains_xy(geom, xs, ys)
        dark, light = [], []
        for x, y in zip(xs[ok], ys[ok]):
            ln = rng.uniform(2, 4) * s
            seg = f"M{_f(x)},{_f(y)}l{_f(n[0] * ln)},{_f(n[1] * ln)}"
            (dark if rng.random() < 0.6 else light).append(seg)
        return "".join(dark), "".join(light)
    m = MATERIALS[material]
    spacing = m["row"] * s
    reach = depth + 40 * s
    rows, cand = [], []
    edges = _edges(geom)
    for i in range(1, int(depth / spacing) + 1):
        p0 = eave - n * (i * spacing)
        segs = _clip_line(edges, p0 - rd * reach, p0 + rd * reach)
        rows.append("".join(f"M{x0:.1f},{y0:.1f}L{x1:.1f},{y1:.1f}" for x0, y0, x1, y1 in segs))
        if not m["joint"]:
            continue
        step = m["joint"] * s
        for x0, y0, x1, y1 in segs:
            length = math.sqrt((x1 - x0) * (x1 - x0) + (y1 - y0) * (y1 - y0))
            if length < 1e-6:
                continue
            ts, t = [], (step / 2 if i % 2 else 0) + rng.uniform(0, 0.5) * s
            while t < length:   # Fugenabstände mit leichter Unregelmäßigkeit
                ts.append(t)
                t += step * (1 + rng.uniform(-m["jitter"], m["jitter"]))
            if not ts:
                continue
            ts = np.array(ts) / length
            px, py = x0 + (x1 - x0) * ts, y0 + (y1 - y0) * ts
            cand.append((px, py, px + n[0] * spacing, py + n[1] * spacing))
    joints = ""
    if cand:   # eine Fuge nur, wo ihr Ende noch auf dem Dach liegt: alle Fugen der Fläche in einem Punkttest
        px, py, ex, ey = (np.concatenate(c) for c in zip(*cand))
        ok = shapely.contains_xy(geom.buffer(0.3 * s), ex, ey)
        joints = "".join(f"M{_f(a)},{_f(b)}L{_f(c)},{_f(d)}" for a, b, c, d in zip(px[ok], py[ok], ex[ok], ey[ok]))
    return "".join(rows) + joints, ""


def _edges(geom):
    """Kanten aller Ringe einer Fläche als (ax, ay, bx, by)."""
    out = []
    for p in polys(geom):
        for ring in (p.exterior, *p.interiors):
            cs = list(ring.coords)
            out += [(*cs[k], *cs[k + 1]) for k in range(len(cs) - 1)]
    return out


def _clip_line(edges, a, b):
    """Teile der Strecke a-b, die in der Fläche (Kanten aus _edges) liegen, als (x0, y0, x1, y1) in Richtung a -> b.
    Ersetzt LineString(a, b).intersection(Fläche) für die Ziegelreihen (je Dachfläche bis zu zwanzig): die Schnittpunkte
    mit den Kanten, nach der Lage auf der Strecke sortiert, paarweise innen (gerade-ungerade-Regel). Eine Ecke auf der
    Strecke zählt nur für die Kante, deren anderes Ende auf der positiven Seite liegt: so wird nichts doppelt gezählt."""
    ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
    dx, dy = bx - ax, by - ay
    hits = []
    for px, py, qx, qy in edges:
        dp = (px - ax) * dy - (py - ay) * dx      # Seite der Kantenenden bezüglich der Geraden
        dq = (qx - ax) * dy - (qy - ay) * dx
        if (dp > 0) != (dq > 0):
            t = dp / (dp - dq)
            x, y = px + t * (qx - px), py + t * (qy - py)
            hits.append(((x - ax) * dx + (y - ay) * dy, x, y))
    hits.sort()
    L2 = dx * dx + dy * dy
    out = []
    for (t0, x0, y0), (t1, x1, y1) in zip(hits[::2], hits[1::2]):
        if t0 < 0:                                 # Anfang bzw. Ende der Strecke liegt in der Fläche
            t0, x0, y0 = 0.0, ax, ay
        if t1 > L2:
            t1, x1, y1 = L2, bx, by
        if t1 > t0:
            out.append((x0, y0, x1, y1))
    return out


# Wie stark Dächer vermoosen bzw. verwittern (Wahrscheinlichkeit je Dach)
MOSS = {"reet": 0.7, "schindel": 0.55, "ziegel": 0.45, "schiefer": 0.3, "schnee": 0.0, "flicken": 0.85}


def _weathering(poly, s, rng, material):
    """Moos- und Verwitterungsflecken: kleine, unregelmäßige Kleckse aus überlappenden Kreisen."""
    if rng.random() > MOSS[material] or poly.area < 120 * s * s:
        return ""
    minx, miny, maxx, maxy = poly.bounds
    inner = poly.buffer(-2.5 * s)
    if inner.is_empty:
        return ""
    out = []
    for _ in range(rng.randint(1, 3)):
        for _try in range(8):
            x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
            if inner.contains(shapely.Point(x, y)):
                break
        else:
            continue
        col = rng.choice(["#4f6a2e", "#5d7436", "#3e4a2a"]) if material != "schiefer" else rng.choice(["#4f6a2e", "#2c2a26"])
        blob = "".join(f'<circle cx="{_f(x + rng.uniform(-2, 2) * s)}" cy="{_f(y + rng.uniform(-2, 2) * s)}" '
                       f'r="{_f(rng.uniform(1.2, 2.6) * s)}"/>' for _ in range(rng.randint(2, 4)))
        out.append(f'<g fill="{col}" fill-opacity="{rng.uniform(0.25, 0.42):.2f}">{blob}</g>')
    return "".join(out)


def _patches(pl, s, rng, base, outline):
    """Aufgenagelte Flicken: kleine Brettstücke in anderer Farbe, entlang der Traufe ausgerichtet."""
    out = []
    for geom, n, rd, _, _ in pl:
        inner = geom.buffer(-1.6 * s)
        if inner.is_empty or rng.random() < 0.3:
            continue
        minx, miny, maxx, maxy = inner.bounds
        for _ in range(rng.randint(1, 2)):
            x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
            if not inner.contains(shapely.Point(x, y)):
                continue
            c = np.array([x, y])
            hw, hh = rng.uniform(1.4, 2.6) * s, rng.uniform(0.9, 1.5) * s
            pts = [c - rd * hw - n * hh, c + rd * hw - n * hh, c + rd * hw + n * hh, c - rd * hw + n * hh]
            col = shade(rng.choice([base, "#8d7a58", "#6e6a5e", "#9a8664"]), rng.uniform(0.75, 1.2))
            out.append(f'<polygon points="{" ".join(f"{_f(px)},{_f(py)}" for px, py in pts)}" fill="{col}" '
                       f'stroke="{outline}" stroke-opacity="0.7" stroke-width="{_f(0.4 * s)}"/>')
    return "".join(out)


def _dormers(poly, pl, s, rng, base, to_light, outline, material):
    """Gauben auf den langen Dachflächen größerer Häuser: kleiner Giebel mit First und Fenster zur Traufe."""
    ax = axes(poly)
    if ax is None or material == "schnee" or poly.area < 420 * s * s or not is_rect(poly):
        return ""
    _, e1, e2 = ax
    l1, l2 = vlen(e1), vlen(e2)
    if l1 < 26 * s or l2 < 12 * s:
        return ""
    u = e1 / l1
    out = []
    for _, n, _, eave, _ in pl[:2]:                  # die beiden langen Dachflächen
        if rng.random() > 0.55:
            continue
        hw, hd = 2.4 * s, min(2.4 * s, l2 * 0.16)
        count = 1 if l1 < 40 * s else rng.randint(1, 2)
        for j in range(count):
            t = (j + 1) / (count + 1) + rng.uniform(-0.08, 0.08)
            c = eave + u * (l1 * t) - n * (hd + 1.2 * s)
            corners = [c - u * hw - n * hd, c + u * hw - n * hd, c + u * hw + n * hd, c - u * hw + n * hd]
            if not poly.buffer(-0.5 * s).contains(Polygon(corners)):
                continue
            k = 1 + 0.3 * vdot(n, to_light)
            pts = " ".join(f"{_f(x)},{_f(y)}" for x, y in corners)
            ridge = (c - n * hd, c + n * hd)
            win = (c + n * hd - u * hw * 0.6, c + n * hd + u * hw * 0.6)
            out.append(f'<polygon points="{pts}" fill="{shade(base, k * 1.08)}" stroke="{outline}" stroke-width="{_f(0.6 * s)}"/>'
                       f'<path d="M{_f(ridge[0][0])},{_f(ridge[0][1])}L{_f(ridge[1][0])},{_f(ridge[1][1])}" '
                       f'stroke="#000" stroke-opacity="0.45" stroke-width="{_f(0.6 * s)}"/>'
                       f'<path d="M{_f(win[0][0])},{_f(win[0][1])}L{_f(win[1][0])},{_f(win[1][1])}" '
                       f'stroke="#2a2016" stroke-width="{_f(1.1 * s)}"/>')
    return "".join(out)


def detailed_roof(b, s, rng, material, to_light, outline):
    """Komplettes SVG eines Gebäudes mit detailliertem Dach (oder None, wenn die Form nicht passt)."""
    poly = b["poly"]
    pl = planes(poly)
    if not pl:
        return None
    base = shade(b["color"], 1.05 if material == "schnee" else rng.uniform(0.92, 1.08))   # jedes Dach etwas anders
    out = []
    tex_dark, tex_light = [], []
    for geom, n, rd, eave, depth in pl:
        k = 1 + 0.3 * vdot(n, to_light)
        out.append(f'<path d="{_pd(geom)}" fill="{shade(base, k)}"/>')
        dark, light = _texture(geom, n, rd, eave, depth, s, rng, material)
        tex_dark.append(dark)
        tex_light.append(light)
    td, tl = "".join(tex_dark), "".join(tex_light)
    if td:
        col = "#9fb3c0" if material == "schnee" else shade(base, 0.6)
        out.append(f'<path d="{td}" fill="none" stroke="{col}" stroke-opacity="0.75" stroke-width="{_f(0.55 * s)}"/>')
    if tl:
        out.append(f'<path d="{tl}" fill="none" stroke="{shade(base, 1.3)}" stroke-opacity="0.7" stroke-width="{_f(0.55 * s)}"/>')
    # First und Grate: dunkle Kante, darüber ein heller Glanzstreifen zum Licht hin
    if b.get("ridges"):
        rd_ = "".join(_ld(r) for r in b["ridges"])
        dx, dy = -to_light[0] * 0.5 * s, -to_light[1] * 0.5 * s
        out.append(f'<path d="{rd_}" fill="none" stroke="#000" stroke-opacity="0.55" stroke-width="{_f(1 * s)}"/>'
                   f'<path d="{rd_}" fill="none" stroke="{shade(base, 1.45)}" stroke-opacity="0.8" '
                   f'stroke-width="{_f(0.6 * s)}" transform="translate({_f(-dx)},{_f(-dy)})"/>')
    if material == "flicken":
        out.append(_patches(pl, s, rng, base, outline))
    out.append(_weathering(poly, s, rng, material))
    if not b.get("poor"):   # Hütten haben keine Gauben
        out.append(_dormers(poly, pl, s, rng, base, to_light, outline, material))
    out.append(f'<path d="{_pd(poly)}" fill="none" stroke="{outline}" stroke-width="{_f(1.1 * s)}"/>')
    # Schornstein (bei Essen immer, mit Rauch)
    forge = b.get("forge")
    if b.get("ridges") and (forge or rng.random() < (0.1 if b.get("poor") else 0.35)) and poly.area > 140 * s * s:
        ax = axes(poly)
        _, e1, e2 = ax
        u = e1 / vlen(e1)
        v = e2 / vlen(e2)
        ridge = b["ridges"][0]
        c = ridge.interpolate(rng.uniform(0.2, 0.8), normalized=True)
        c = np.array([c.x, c.y]) + v * rng.choice([-1, 1]) * 2.2 * s
        hw = 1.8 * s
        sq = [c - u * hw - v * hw, c + u * hw - v * hw, c + u * hw + v * hw, c - u * hw + v * hw]
        if poly.contains(Polygon(sq)):
            pts = " ".join(f"{_f(x)},{_f(y)}" for x, y in sq)
            out.append(f'<polygon points="{pts}" fill="#7a6a5c" stroke="{outline}" stroke-width="{_f(0.7 * s)}"/>'
                       f'<circle cx="{_f(c[0])}" cy="{_f(c[1])}" r="{_f(0.9 * s)}" fill="#1e1612"/>')
            if forge:
                for i in range(3):
                    sx = c[0] + (i * 3.5 + rng.uniform(0, 1.5)) * s
                    sy = c[1] - (i * 3 + rng.uniform(0, 1.5)) * s
                    out.append(f'<circle cx="{_f(sx)}" cy="{_f(sy)}" r="{_f((2 + i * 1.3) * s)}" fill="#cfcac0" '
                               f'fill-opacity="{0.45 - i * 0.12:.2f}"/>')
    return "".join(out)
