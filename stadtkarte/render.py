"""Zeichnet das Kartenmodell als SVG (und daraus PNG/PDF)."""
import colorsys
import io
import math
import os
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from xml.sax.saxutils import escape, quoteattr

import numpy as np
import shapely
import shapely.affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from .geo import axes, lines, polys, vlen
from . import noise, umgebung
from .roofs import detailed_roof, material_for
from .city import ship_footprint
from .styles import COLORS as C, DISTRICT_TYPES, FONT, FONT_FILE


def f(v):
    return f"{v:.1f}"


def path_d(g):
    out = []
    for p in polys(g):
        for ring in (p.exterior, *p.interiors):
            cs = list(ring.coords)[:-1]
            if len(cs) >= 3:
                out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in cs) + "Z")
    return "".join(out)


def line_d(g):
    out = []
    for ln in lines(g):
        out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in ln.coords))
    return "".join(out)


def smallcaps(text, size):
    parts = []
    for i, word in enumerate(text.split()):
        if i:
            parts.append(f'<tspan font-size="{f(size * 0.78)}"> </tspan>')
        parts.append(f'<tspan font-size="{f(size)}">{escape(word[0].upper())}</tspan>')
        if len(word) > 1:
            parts.append(f'<tspan font-size="{f(size * 0.78)}">{escape(word[1:].upper())}</tspan>')
    return "".join(parts)


def text_el(x, y, text, size, s, anchor="middle", halo=None):
    halo = halo if halo is not None else 4 * s
    body = smallcaps(text, size)
    common = f'x="{f(x)}" y="{f(y)}" text-anchor="{anchor}" font-family="{FONT}" letter-spacing="{f(0.6 * s)}"'
    return (f'<text {common} fill="none" stroke="{C["text_halo"]}" stroke-width="{f(halo)}" '
            f'stroke-linejoin="round" stroke-opacity="0.85">{body}</text>'
            f'<text {common} fill="{C["text"]}">{body}</text>')


def defs(m):
    s, W = m["s"], m["W"]
    out = [f"""
<linearGradient id="seaGrad" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="{f(W * 0.35)}">
  <stop offset="0" stop-color="{m['biome']['sea_deep']}"/><stop offset="1" stop-color="{m['biome']['sea']}"/></linearGradient>
<radialGradient id="vignette" cx="0.5" cy="0.5" r="0.75">
  <stop offset="0.6" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="0.45"/></radialGradient>
<filter id="blur" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="{f(10 * s)}"/></filter>
<filter id="softblur" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="{f(4 * s)}"/></filter>
<radialGradient id="glowWarm"><stop offset="0" stop-color="{C['glow']}" stop-opacity="0.6"/>
  <stop offset="0.45" stop-color="{C['glow']}" stop-opacity="0.45"/><stop offset="0.72" stop-color="{C['glow']}" stop-opacity="0.15"/>
  <stop offset="1" stop-color="{C['glow']}" stop-opacity="0"/></radialGradient>
<radialGradient id="glowNight"><stop offset="0" stop-color="#ffd27a" stop-opacity="0.85"/>
  <stop offset="0.35" stop-color="#ffb347" stop-opacity="0.5"/><stop offset="0.7" stop-color="#ff9a2a" stop-opacity="0.16"/>
  <stop offset="1" stop-color="#ff9a2a" stop-opacity="0"/></radialGradient>
<radialGradient id="glowWin"><stop offset="0" stop-color="#ffcf6a" stop-opacity="0.55"/>
  <stop offset="0.5" stop-color="#ffb347" stop-opacity="0.22"/><stop offset="1" stop-color="#ffb347" stop-opacity="0"/></radialGradient>
<radialGradient id="glowForge"><stop offset="0" stop-color="#ff6a1a" stop-opacity="0.6"/>
  <stop offset="0.45" stop-color="#ff6a1a" stop-opacity="0.42"/><stop offset="0.72" stop-color="#ff6a1a" stop-opacity="0.14"/>
  <stop offset="1" stop-color="#ff6a1a" stop-opacity="0"/></radialGradient>
<filter id="glow" x="-200%" y="-200%" width="500%" height="500%"><feGaussianBlur stdDeviation="{f(5 * s)}"/></filter>
<filter id="shadow" x="-5%" y="-5%" width="110%" height="110%">
  <feDropShadow dx="{f(2 * s)}" dy="{f(2.5 * s)}" stdDeviation="{f(1.3 * s)}" flood-color="#000" flood-opacity="0.6"/></filter>
<filter id="treeShadow" x="-5%" y="-5%" width="110%" height="110%">
  <feDropShadow dx="{f(3 * s)}" dy="{f(3.5 * s)}" stdDeviation="{f(2 * s)}" flood-color="#000" flood-opacity="0.55"/></filter>
<pattern id="planks" patternUnits="userSpaceOnUse" width="{f(12 * s)}" height="{f(4 * s)}" patternTransform="rotate(35)">
  <rect width="{f(12 * s)}" height="{f(4 * s)}" fill="#8a6d45"/>
  <path d="M0,{f(3.5 * s)}H{f(12 * s)}M{f(7 * s)},0V{f(3.5 * s)}" stroke="#3a2a16" stroke-width="{f(1 * s)}"/></pattern>
<pattern id="cobble" patternUnits="userSpaceOnUse" width="{f(14 * s)}" height="{f(14 * s)}">
  <rect width="{f(14 * s)}" height="{f(14 * s)}" fill="{C['paved']}"/>
  <g fill="none" stroke="#a7a294" stroke-width="{f(0.8 * s)}">
  <rect x="{f(1 * s)}" y="{f(1 * s)}" width="{f(5 * s)}" height="{f(4 * s)}" rx="{f(1.2 * s)}"/>
  <rect x="{f(7.5 * s)}" y="{f(1.5 * s)}" width="{f(5 * s)}" height="{f(4.5 * s)}" rx="{f(1.2 * s)}"/>
  <rect x="{f(3.5 * s)}" y="{f(7.5 * s)}" width="{f(5 * s)}" height="{f(5 * s)}" rx="{f(1.2 * s)}"/>
  <rect x="{f(10 * s)}" y="{f(8 * s)}" width="{f(3.5 * s)}" height="{f(4.5 * s)}" rx="{f(1.2 * s)}"/></g></pattern>
"""]
    stripes = {"wheat": (C["field_wheat"], C["field_wheat2"]), "plowed": (C["field_plowed"], C["field_plowed2"]),
               "meadow": (C["field_meadow"], C["field_meadow2"])}
    stripes.update(m["biome"]["field_colors"] or {})
    for i, fl in enumerate(m["fields"]):
        a, b = stripes[fl["kind"]]
        w = 8 * s
        out.append(f'<pattern id="field{i}" patternUnits="userSpaceOnUse" width="{f(w)}" height="{f(w)}" '
                   f'patternTransform="rotate({f(fl["angle"])})"><rect width="{f(w)}" height="{f(w)}" fill="{a}"/>'
                   f'<rect width="{f(w * 0.35)}" height="{f(w)}" fill="{b}"/></pattern>')
    out.append(f'<clipPath id="landClip"><path d="{path_d(m["land"])}"/></clipPath>')
    out.append(f'<clipPath id="seaClip"><path d="{path_d(m["water"])}"/></clipPath>')
    return "<defs>" + "".join(out) + "</defs>"


def building_svg(b, s, flat=False):
    d = path_d(b["poly"])
    out = [f'<path d="{d}" fill="{b["color"]}" stroke="{C["outline"]}" stroke-width="{f(1.1 * s)}"/>']
    if flat and not b.get("landmark"):   # Lehmbau mit Flachdach: Brüstung und gelegentlich eine Dachluke
        inner = b["poly"].buffer(-2.2 * s, join_style="mitre")
        if not inner.is_empty:
            out.append(f'<path d="{path_d(inner)}" fill="#000" fill-opacity="0.06" stroke="#000" stroke-opacity="0.35" '
                       f'stroke-width="{f(0.7 * s)}"/>')
            c = inner.representative_point()
            if int(c.x * 7 + c.y * 13) % 5 < 2:
                out.append(f'<rect x="{f(c.x - 1.8 * s)}" y="{f(c.y - 1.8 * s)}" width="{f(3.6 * s)}" '
                           f'height="{f(3.6 * s)}" fill="#3a2a1a" fill-opacity="0.7"/>')
        return "".join(out)
    if b.get("shade") is not None:
        out.append(f'<path d="{path_d(b["shade"])}" fill="#000" fill-opacity="0.22"/>')
    if b.get("ridges"):
        rd = "".join(line_d(r) for r in b["ridges"])
        out.append(f'<path d="{rd}" fill="none" stroke="#000" stroke-opacity="0.5" stroke-width="{f(0.8 * s)}"/>')
    return "".join(out)


def block_svg(b, s, to_light, flat):
    """Großstadt: Häuserzeile um einen Hof. Jedes Haus ist eine Dachfläche in eigener Farbe, zum Licht hin heller;
    dazwischen Brandmauern, rundum der First in halber Haustiefe mit hellem Glanz zur Lichtseite."""
    out = []
    if b.get("court") is not None:   # Innenhof: festgetretener Boden statt Wiese, an der Hauswand verschattet
        out.append(f'<path d="{path_d(b["court"])}" fill="#7d7562" fill-opacity="0.75" stroke="#000" '
                   f'stroke-opacity="0.25" stroke-width="{f(2 * s)}"/>')
    for seg, n, col in b["segments"]:
        k = 1.0 if flat else 1 + 0.28 * (n[0] * to_light[0] + n[1] * to_light[1])
        out.append(f'<path d="{path_d(seg)}" fill="{shade(col, k)}"/>')
    walls = "".join(path_d(seg) for seg, _, _ in b["segments"])
    out.append(f'<path d="{walls}" fill="none" stroke="#000" stroke-opacity="0.45" stroke-width="{f(0.5 * s)}"/>')
    if b["block_ridge"] and not flat:
        rd = "".join(line_d(r) for r in b["block_ridge"])
        dx, dy = to_light[0] * 0.5 * s, to_light[1] * 0.5 * s
        out.append(f'<path d="{rd}" fill="none" stroke="#000" stroke-opacity="0.5" stroke-width="{f(0.8 * s)}"/>'
                   f'<path d="{rd}" fill="none" stroke="#fff" stroke-opacity="0.22" stroke-width="{f(0.5 * s)}" '
                   f'transform="translate({f(dx)},{f(dy)})"/>')
    out.append(f'<path d="{path_d(b["poly"])}" fill="none" stroke="{C["outline"]}" stroke-width="{f(1 * s)}"/>')
    return "".join(out)


def shade(hex_color, k):
    """Farbe aufhellen (k>1) oder abdunkeln (k<1)."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(v * k))) for v in (r, g, b)))


def tree_svg(x, y, r, color, s, rng, kind):
    edge = f'stroke="#15221a" stroke-width="{f(1.3 * s)}"'
    color = shade(color, rng.uniform(0.8, 1.2))
    if kind == "nadel":   # Nadelbaum: gezackter Stern
        n = rng.randint(8, 11)
        a0 = rng.uniform(0, math.pi)
        pts = []
        for i in range(2 * n):
            rad = r if i % 2 == 0 else r * 0.62
            a = a0 + math.pi * i / n
            pts.append(f"{f(x + math.cos(a) * rad)},{f(y + math.sin(a) * rad)}")
        dark = shade("#2c4a3e", rng.uniform(0.85, 1.15))
        return (f'<polygon points="{" ".join(pts)}" fill="{dark}" {edge}/>'
                f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r * 0.18)}" fill="#1c2e24"/>')
    if kind == "lappen":  # Laubbaum aus mehreren Kronenlappen
        n = rng.randint(5, 7)
        a0 = rng.uniform(0, math.pi)
        lobes = [(x + math.cos(a0 + 2 * math.pi * i / n) * r * 0.45,
                  y + math.sin(a0 + 2 * math.pi * i / n) * r * 0.45, r * rng.uniform(0.5, 0.62)) for i in range(n)]
        lobes.append((x, y, r * 0.6))
        under = "".join(f'<circle cx="{f(a)}" cy="{f(b)}" r="{f(c)}" fill="{color}" {edge}/>' for a, b, c in lobes)
        over = "".join(f'<circle cx="{f(a)}" cy="{f(b)}" r="{f(c - 1.2 * s)}" fill="{color}"/>' for a, b, c in lobes)
        hi = (f'<circle cx="{f(x - r * 0.28)}" cy="{f(y - r * 0.3)}" r="{f(r * 0.4)}" fill="{shade(color, 1.3)}" '
              f'fill-opacity="0.55"/>')
        return under + over + hi
    if kind == "tanne":   # verschneite Tanne
        n = rng.randint(8, 10)
        a0 = rng.uniform(0, math.pi)
        star = lambda rr, k: " ".join(
            f"{f(x + math.cos(a0 + math.pi * i / n) * (rr if i % 2 == 0 else rr * k))},"
            f"{f(y + math.sin(a0 + math.pi * i / n) * (rr if i % 2 == 0 else rr * k))}" for i in range(2 * n))
        dark = shade("#2a4a3c", rng.uniform(0.85, 1.15))
        return (f'<polygon points="{star(r, 0.62)}" fill="{dark}" {edge}/>'
                f'<polygon points="{star(r * 0.72, 0.5)}" fill="#f4f7f8" fill-opacity="0.85" '
                f'transform="translate({f(-r * 0.12)},{f(-r * 0.12)})"/>'
                f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r * 0.16)}" fill="#1c2e24"/>')
    if kind == "palme":   # Palme: Wedel um einen Stamm
        n = rng.randint(6, 8)
        a0 = rng.uniform(0, math.pi)
        out = []
        for i in range(n):
            a = a0 + 2 * math.pi * i / n + rng.uniform(-0.15, 0.15)
            ex, ey = x + math.cos(a) * r, y + math.sin(a) * r
            nx, ny = -math.sin(a) * r * 0.22, math.cos(a) * r * 0.22
            mx, my = x + math.cos(a) * r * 0.5, y + math.sin(a) * r * 0.5
            out.append(f'<path d="M{f(x)},{f(y)}Q{f(mx + nx)},{f(my + ny)} {f(ex)},{f(ey)}'
                       f'Q{f(mx - nx)},{f(my - ny)} {f(x)},{f(y)}Z" fill="{shade(color, rng.uniform(0.85, 1.2))}" '
                       f'stroke="#1f2a12" stroke-width="{f(0.9 * s)}"/>'
                       f'<path d="M{f(x)},{f(y)}L{f(ex)},{f(ey)}" stroke="#2c3a18" stroke-width="{f(0.6 * s)}"/>')
        out.append(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r * 0.16)}" fill="#6b4f2a" stroke="#2a1d0e" stroke-width="{f(0.7 * s)}"/>')
        return "".join(out)
    if kind == "busch":   # niedriger Busch aus drei Ballen
        out = []
        for _ in range(3):
            bx, by = x + rng.uniform(-0.4, 0.4) * r, y + rng.uniform(-0.4, 0.4) * r
            br = r * rng.uniform(0.38, 0.55)
            out.append(f'<circle cx="{f(bx)}" cy="{f(by)}" r="{f(br)}" fill="{shade(color, rng.uniform(0.85, 1.15))}" {edge}/>')
        return "".join(out)
    if kind == "weide":   # Trauerweide: viele kleine hängende Kronenlappen
        n = rng.randint(9, 13)
        a0 = rng.uniform(0, math.pi)
        out = [f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r * 0.9)}" fill="{shade(color, 0.8)}" {edge}/>']
        for i in range(n):
            a = a0 + 2 * math.pi * i / n
            out.append(f'<circle cx="{f(x + math.cos(a) * r * 0.72)}" cy="{f(y + math.sin(a) * r * 0.72)}" '
                       f'r="{f(r * 0.3)}" fill="{shade(color, rng.uniform(0.9, 1.15))}" {edge}/>')
        out.append(f'<circle cx="{f(x - r * 0.15)}" cy="{f(y - r * 0.15)}" r="{f(r * 0.45)}" fill="{shade(color, 1.2)}"/>')
        return "".join(out)
    if kind == "tot":     # abgestorbener Baum: kahle Äste
        n = rng.randint(4, 6)
        d = "".join(f"M{f(x)},{f(y)}L{f(x + math.cos(a) * r * rng.uniform(0.6, 0.95))},"
                    f"{f(y + math.sin(a) * r * rng.uniform(0.6, 0.95))}"
                    for a in (rng.uniform(0, 2 * math.pi) for _ in range(n)))
        return (f'<path d="{d}" stroke="#2a2118" stroke-width="{f(2.6 * s)}" stroke-linecap="round"/>'
                f'<path d="{d}" stroke="#6b5a45" stroke-width="{f(1.3 * s)}" stroke-linecap="round"/>'
                f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r * 0.18)}" fill="#5a4a38" stroke="#2a2118" stroke-width="{f(0.8 * s)}"/>')
    if kind == "alt":     # alter Riesenbaum mit dunklem Kern
        return (f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r)}" fill="{shade(color, 0.85)}" {edge}/>'
                f'<circle cx="{f(x - r * 0.15)}" cy="{f(y - r * 0.15)}" r="{f(r * 0.72)}" fill="{color}"/>'
                f'<circle cx="{f(x - r * 0.3)}" cy="{f(y - r * 0.3)}" r="{f(r * 0.38)}" fill="{shade(color, 1.25)}"/>'
                f'<circle cx="{f(x + r * 0.2)}" cy="{f(y + r * 0.25)}" r="{f(r * 0.12)}" fill="#1a2a1e" fill-opacity="0.6"/>')
    return (f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r)}" fill="{color}" {edge}/>'
            f'<circle cx="{f(x - r * 0.25)}" cy="{f(y - r * 0.25)}" r="{f(r * 0.55)}" fill="{shade(color, 1.25)}" '
            f'fill-opacity="0.6"/>')


def tree_kind(rng, r, s, weights):
    if r > 15.5 * s and rng.random() < 0.08:
        return "alt"
    return rng.choices(list(weights), list(weights.values()))[0]


def ship_svg(sh, s):
    L, B = sh["len"], sh["wid"]
    hull = (f"M{f(-L / 2)},0 Q{f(-L / 2 + L * 0.15)},{f(-B / 2)} {f(-L * 0.2)},{f(-B / 2)} L{f(L * 0.25)},{f(-B / 2)} "
            f"Q{f(L * 0.45)},{f(-B / 2)} {f(L / 2)},0 Q{f(L * 0.45)},{f(B / 2)} {f(L * 0.25)},{f(B / 2)} "
            f"L{f(-L * 0.2)},{f(B / 2)} Q{f(-L / 2 + L * 0.15)},{f(B / 2)} {f(-L / 2)},0Z")
    out = [f'<g transform="translate({f(sh["x"])},{f(sh["y"])}) rotate({f(sh["angle"])})">',
           f'<path d="{hull}" fill="{"#b48c5c" if sh.get("slip") else "#8a6440"}" stroke="{C["outline"]}" '
           f'stroke-width="{f(1.1 * s)}"/>']
    if sh.get("slip"):   # Schiff im Bau: Kiel und Spanten, noch ohne Deck und Mast
        ribs = "".join(f"M{f(x)},{f(-B * 0.4)}L{f(x)},{f(B * 0.4)}" for x in np.linspace(-L * 0.36, L * 0.38, 9))
        out.append(f'<path d="M{f(-L * 0.42)},0L{f(L * 0.46)},0" stroke="#4a3220" stroke-width="{f(1.4 * s)}"/>'
                   f'<path d="{ribs}" stroke="#5a3f28" stroke-width="{f(0.9 * s)}"/>')
    if sh["big"]:
        out.append(f'<path d="M{f(-L * 0.35)},0 L{f(L * 0.35)},0" stroke="#5a3f28" stroke-width="{f(1 * s)}"/>')
        for mx in (-L * 0.18, L * 0.12):
            out.append(f'<circle cx="{f(mx)}" cy="0" r="{f(2.2 * s)}" fill="#3a2a1a"/>')
        out.append(f'<rect x="{f(-L * 0.08)}" y="{f(-B * 0.75)}" width="{f(L * 0.12)}" height="{f(B * 1.5)}" '
                   f'fill="#e9e2cf" stroke="{C["outline"]}" stroke-width="{f(0.6 * s)}" fill-opacity="0.9"/>')
    out.append("</g>")
    return "".join(out)


def tower_svg(x, y, ang, size, s, color=C["tower"]):
    return (f'<g transform="translate({f(x)},{f(y)}) rotate({f(ang)})">'
            f'<rect x="{f(-size / 2)}" y="{f(-size / 2)}" width="{f(size)}" height="{f(size)}" fill="{color}" '
            f'stroke="{C["outline"]}" stroke-width="{f(1.4 * s)}"/>'
            f'<path d="M{f(-size / 2)},{f(-size / 2)}L{f(size / 2)},{f(size / 2)}M{f(size / 2)},{f(-size / 2)}L{f(-size / 2)},{f(size / 2)}" '
            f'stroke="#000" stroke-opacity="0.35" stroke-width="{f(0.8 * s)}"/></g>')


def rot_xy(m, x, y):
    a = math.radians(m["rot"])
    c = m["W"] / 2
    dx, dy = x - c, y - c
    return c + dx * math.cos(a) - dy * math.sin(a), c + dx * math.sin(a) + dy * math.cos(a)


def text_width(text, size):
    """Grobe Breite eines Kapitälchen-Textes."""
    return len(text) * size * 0.64 + size * 0.2


def legend_rows(rows):
    """Fortlaufend nummerierte Orte gleichen Namens stehen in der Legende in einer Zeile: S1–S5 Schenke."""
    groups, out = {}, []
    for k, name in rows:
        hit = re.fullmatch(r"(.*?)(\d+)", k)
        if hit:
            key = (hit[1], name)
            if key not in groups:
                groups[key] = []
                out.append(key)
            groups[key].append(int(hit[2]))
        else:
            out.append((k, name))
    res = []
    for item in out:
        if item not in groups:
            res.append(item)
            continue
        nums, parts = sorted(set(groups[item])), []
        for n in nums:
            if parts and n == parts[-1][1] + 1:
                parts[-1][1] = n
            else:
                parts.append([n, n])
        pre = item[0]
        res.append((", ".join(f"{pre}{a}" if a == b else f"{pre}{a}–{pre}{b}" if b > a + 1 else f"{pre}{a}, {pre}{b}"
                              for a, b in parts), item[1]))
    return res


def place_labels(m, taken):
    """Setzt Viertel- und Ortsnamen so, dass sie sich nicht überlappen. Schriftgrößen in Kartengröße (st), auch
    wenn die Karte ein vergrößerter Ausschnitt ist; der Abstand zum Ort (lift) ist in Weltmaßen."""
    s = m.get("st", m["s"])
    W = m["W"]
    placed = []

    def box_at(x, y, text, size):
        w = text_width(text, size)
        return (x - w / 2 - 2 * s, y - size * 0.85, x + w / 2 + 2 * s, y + size * 0.25)

    def free(b):
        inside = b[0] > 5 * s and b[1] > 5 * s and b[2] < W - 5 * s and b[3] < W - 5 * s
        return inside and not any(b[0] < t[2] and t[0] < b[2] and b[1] < t[3] and t[1] < b[3] for t in taken)

    def put(cands, text, size, halo, kind, lb):
        for x, y in cands:
            b = box_at(x, y, text, size)
            if free(b):
                break
        else:
            x, y = cands[0]
            b = box_at(x, y, text, size)
        taken.append(b)
        placed.append((x, y, text, size, halo, kind, lb))

    order = sorted(m["labels"], key=lambda lb: lb["kind"] not in ("viertel", "festung"))
    for lb in order:
        x, y = rot_xy(m, lb["x"], lb["y"])
        if lb["kind"] == "festung":
            size = 32 * s
            w = text_width(lb["text"], size)
            lift = lb["lift"]
            put([(x + lift + w / 2, y + size * 0.3), (x - lift - w / 2, y + size * 0.3), (x, y - lift),
                 (x, y + lift + size)], lb["text"], size, 5 * s, "orte", lb)
        elif lb["kind"] == "viertel":
            size = 34 * s
            put([(x, y + dy * s) for dy in (10, -30, 50, -70, 90, -110)], lb["text"], size, 5 * s, "viertel", lb)
        else:
            size = 17 * s
            lift = lb["lift"]
            w = text_width(lb["text"], size)
            cands = [(x, y - lift), (x, y + lift + size * 0.7), (x + lift + w / 2, y + size * 0.3),
                     (x - lift - w / 2, y + size * 0.3), (x, y - lift - size), (x, y + lift + size * 1.7)]
            put(cands, lb["text"], size, 3.5 * s, "orte", lb)
    return placed


def pools_svg(o, m, rng):
    """Stehende Gewässer je Biotop: Sumpftümpel, zugefrorene Seen oder Oasen."""
    pools, s, B = m["pools"], m["s"], m["biome"]
    if pools.is_empty:
        return
    d = path_d(pools)
    if B["pool_style"] == "eis":
        cracks = []
        for p in polys(pools):
            minx, miny, maxx, maxy = p.bounds
            for _ in range(min(8, int(p.area / (1800 * s * s)) + 1)):
                x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
                seg = [f"M{f(x)},{f(y)}"]
                a = rng.uniform(0, 2 * math.pi)
                for _ in range(rng.randint(3, 6)):
                    a += rng.uniform(-0.9, 0.9)
                    x, y = x + math.cos(a) * rng.uniform(8, 22) * s, y + math.sin(a) * rng.uniform(8, 22) * s
                    seg.append(f"L{f(x)},{f(y)}")
                cracks.append("".join(seg))
        o.append(f'<clipPath id="poolClip"><path d="{d}"/></clipPath>'
                 f'<path d="{d}" fill="{B["pool"]}"/>'
                 f'<g clip-path="url(#poolClip)"><path d="{d}" fill="none" stroke="#ffffff" stroke-opacity="0.7" '
                 f'stroke-width="{f(10 * s)}" filter="url(#softblur)"/>'
                 f'<path d="{"".join(cracks)}" fill="none" stroke="#7d9cb0" stroke-width="{f(0.9 * s)}"/>'
                 f'<path d="{"".join(cracks)}" fill="none" stroke="#ffffff" stroke-opacity="0.8" stroke-width="{f(0.6 * s)}" '
                 f'transform="translate({f(1 * s)},{f(1 * s)})"/></g>'
                 f'<path d="{d}" fill="none" stroke="{B["pool_edge"]}" stroke-width="{f(1.3 * s)}"/>')
        return
    if B["pool_style"] == "oase":
        lush = path_d(unary_union([o_.buffer(34 * s) for o_ in m["oases"]])) if m["oases"] else ""
        if lush:
            o.append(f'<path d="{lush}" fill="#6f8a3a" fill-opacity="0.75" filter="url(#softblur)"/>')
        o.append(f'<path d="{d}" fill="{B["pool"]}"/>'
                 f'<path d="{d}" fill="none" stroke="#bfe8de" stroke-opacity="0.8" stroke-width="{f(4 * s)}" filter="url(#softblur)"/>'
                 f'<path d="{d}" fill="none" stroke="{B["pool_edge"]}" stroke-width="{f(1.3 * s)}"/>')
        return
    o.append(f'<clipPath id="poolClip"><path d="{d}"/></clipPath>'
             f'<path d="{d}" fill="{B["pool"]}"/>'
             f'<g clip-path="url(#poolClip)">{noise_open(m, "algae")} opacity="0.5"/>'
             f'<path d="{d}" fill="none" stroke="#9fb092" stroke-opacity="0.35" stroke-width="{f(5 * s)}" filter="url(#softblur)"/></g>'
             f'<path d="{d}" fill="none" stroke="{B["pool_edge"]}" stroke-width="{f(1.3 * s)}"/>')
    reeds = []
    for x, y, a in m["reeds"]:
        for _ in range(rng.randint(3, 5)):
            b = math.radians(a + rng.uniform(-50, 50))
            ln = rng.uniform(4, 8) * s
            reeds.append(f"M{f(x)},{f(y)}l{f(math.cos(b) * ln)},{f(math.sin(b) * ln)}")
    if reeds:
        o.append(f'<path d="{"".join(reeds)}" stroke="#a7a35e" stroke-width="{f(1 * s)}" stroke-linecap="round"/>')
    for x, y, r in m["lilies"]:
        a = rng.uniform(0, 360)
        o.append(f'<g transform="translate({f(x)},{f(y)}) rotate({f(a)})"><path d="M0,0L{f(r)},{f(-r * 0.25)}'
                 f'A{f(r)},{f(r)} 0 1 1 {f(r)},{f(r * 0.25)}Z" fill="#6f8a45" stroke="#2f3b1e" stroke-width="{f(0.6 * s)}"/></g>')
        if rng.random() < 0.2:
            o.append(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r * 0.35)}" fill="#e8d8e0"/>')


def stilts_svg(o, m):
    """Pfähle und Wasserringe unter Stelzenhäusern."""
    s = m["s"]
    posts, rings = [], []
    for b in m["buildings"] + m["suburbs"]:
        if not b.get("stilts"):
            continue
        rings.append(path_d(b["poly"].buffer(2.5 * s, join_style="mitre")))
        for x, y in list(b["poly"].exterior.coords)[:-1]:
            posts.append(f'<circle cx="{f(x + 2.5 * s)}" cy="{f(y + 3 * s)}" r="{f(2.2 * s)}"/>')
    if rings:
        o.append(f'<path d="{"".join(rings)}" fill="none" stroke="#c9d3bf" stroke-opacity="0.45" stroke-width="{f(1 * s)}"/>')
        o.append(f'<g fill="#2a2018">{"".join(posts)}</g>')


# Rauschtexturen (früher SVG-Filter): baseFrequency, Oktaven, Seed, Farbe (linear), Verstärkung, Versatz, Turbulenz,
# optional Verzerrung (Simplex-Domain-Warp: fließende Flecken, Nebelschwaden)
NOISE = {
    "mottleDark": (0.0045, 5, 7, "mottle_dark", 2.6, -1.15, False, 0.45),
    "mottleLight": (0.006, 4, 21, "mottle_light", 2.4, -1.3, False, 0.45),
    "scribble": (0.03, 2, 3, "scribble", 3.0, -1.2, True),
    "rockTex": (0.012, 5, 17, "0.20 0.19 0.17", 2.8, -1.2, False),
    "snowTex": (0.008, 4, 29, "0.96 0.97 0.98", 3.2, -1.25, False),
    "fog": (0.003, 4, 11, "1 1 1", 2.2, -1.0, False, 0.9),
    "algae": (0.02, 3, 5, "0.30 0.38 0.18", 2.5, -1.2, False),
}


_TEX_POOL = None
_TEX_LIMITS = {}
_TEX_LOCK = threading.Lock()


def _texture_limited(W, *args, **kw):
    """Eine Textur belegt beim Rechnen etwa 70 Byte je Pixel (bei 4000 px rund 1 GB). Damit der Speicher
    nicht ausufert, rechnen höchstens so viele gleichzeitig, dass zusammen etwa 32 Millionen Pixel anfallen."""
    n = max(1, min(4, int(32e6 // (W * W))))
    with _TEX_LOCK:
        sem = _TEX_LIMITS.setdefault(n, threading.Semaphore(n))
    with sem:
        return noise.texture(W, *args, **kw)


def _tex_pool():
    """Threads für die Rauschtexturen: numpy gibt bei den großen Array-Rechnungen die GIL frei,
    mehrere Texturen entstehen so auf mehreren Kernen gleichzeitig."""
    global _TEX_POOL
    with _TEX_LOCK:   # bei gleichzeitigem Rendern nur ein Pool
        if _TEX_POOL is None:
            _TEX_POOL = ThreadPoolExecutor(max_workers=max(1, min(4, os.cpu_count() or 1)), thread_name_prefix="textur")
    return _TEX_POOL


def light_dir(m):
    """Richtung zur Lichtquelle (Nordwesten der fertigen Karte) in Kartenkoordinaten, also vor der Drehung."""
    lx = ly = -0.7071067811865476
    return {0: (lx, ly), 90: (ly, -lx), 180: (-lx, -ly), 270: (-ly, lx)}[int(m["rot"]) % 360]


def _hls(hex_color, dl=1.0, ds=1.0, dh=0.0):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l_, s_ = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb((h + dh) % 1.0, min(1.0, l_ * dl), min(1.0, s_ * ds))
    return "#{:02x}{:02x}{:02x}".format(*(int(round(v * 255)) for v in (r, g, b)))


def ground_palette(color):
    """Farbverlauf des Bodens aus seiner Grundfarbe: kühl-satt, Grundton, warm-hell, trocken."""
    return (_hls(color, 0.84, 1.15, 0.012), color, _hls(color, 1.08, 1.05, -0.018), _hls(color, 1.16, 0.92, -0.045))


def umgebung_daten(m):
    """Flächen und Farben für die Bodentönung nach der Umgebung (umgebung.image)."""
    B, s = m["biome"], m["s"]

    def rings(g):
        return [(list(p.exterior.coords), [list(h.coords) for h in p.interiors]) for p in polys(g)]

    def col(key, auto):
        v = B.get(key, "auto")
        return auto if v == "auto" else v
    land = B["land"]
    water = unary_union([g for g in (m["water"], m["pools"]) if g is not None and not g.is_empty] or [Polygon()])
    coastal = m["sea"] is not None and not B["mountain"] and not m.get("plateau")
    return {
        "water": rings(water),
        "forest": rings(m["forest"]),
        "roads": [(list(ln.coords), w + 8 * s) for ln, w in m["ext_roads"]],
        "gates": [(x, y, 40 * s) for x, y, _ in m["gates"]],
        "city_ring": rings(m["shape"].buffer(26 * s).difference(m["shape"])),
        "sea": rings(m["sea"]) if coastal else [],
        "moist": col("moist", _hls(land, 0.8, 1.3, 0.02)),
        "dry": col("dry", _hls(land, 1.15, 0.9, -0.05)),
        "worn": col("worn", _hls(B["road"], 0.72, 0.85)),
        "moss": col("moss", _hls(B["forest_floor"], 0.82, 1.1)),
        "shore": B.get("shore") if coastal else None,
    }


def noise_open(m, *keys, extras=(), base=None, palette=None, shading=None):
    """Öffnendes <use>-Tag einer vorberechneten Rauschtextur (Attribute und '/>' folgen im Aufrufer).
    keys: Texturname oder (Name, Deckkraft); mehrere werden zu einem Bild zusammengelegt.
    palette: Farbverlauf als Untergrund, shading: Relief (Stärke, Wellenlänge) - Licht aus Nordwesten."""
    layers = []
    for k in keys:
        name, op = (k, 1.0) if isinstance(k, str) else k
        bf, octv, seed, col, gain, bias, turb = NOISE[name][:7]
        rgb = tuple(float(v) for v in (m["biome"][col] if col in m["biome"] else col).split())
        layers.append(((bf, octv, seed, rgb, gain, bias, turb) + NOISE[name][7:], op))   # samt Verzerrung
    tid = ("_".join(k if isinstance(k, str) else k[0] for k in keys) + ("_d" if extras else "") + ("_b" if base else "")
           + ("_p" if palette else "") + ("_r" if shading else ""))
    if shading:
        shading = (shading[0], shading[1], *light_dir(m), 71)
    if base and base != m["biome"]["land"]:   # andere Grundfarbe (z.B. zweite Stufe am Hochplateau): eigene Textur
        tid += base.lstrip("#")
    tex = m.setdefault("_tex", {})
    if tid not in tex:   # im Hintergrund berechnen; render_svg wartet erst beim Einbetten am Ende
        tex[tid] = _tex_pool().submit(_texture_limited, m["W"], m["s"], layers, extras=tuple(extras), base=base,
                                      palette=palette, shading=shading)
    return f'<use href="#tex_{tid}"'


def shadow_layer(shapes, dx, dy, opacity, s):
    """Weicher Schlagschatten: Silhouetten versetzt, schwarz, mit Randsaum; Gruppendeckkraft verhindert,
    dass sich überlappende Schatten aufaddieren."""
    return (f'<g opacity="{opacity}" transform="translate({f(dx)},{f(dy)})">'
            f'<g fill="#000" stroke="#000" stroke-opacity="0.45" stroke-width="{f(1.6 * s)}" stroke-linejoin="round">'
            f'{shapes}</g></g>')


def glow_dots(points, grad, s):
    """Lichtschein als Kreise mit radialem Verlauf (entspricht einem weichgezeichneten Kreis, aber ohne Filter)."""
    return "".join(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r + 8 * s)}" fill="url(#{grad})"/>' for x, y, r in points)  # Radius ~ Kreis + 2 Sigma der früheren Unschärfe


def night_svg(o, m, lamps, forge_glow):
    """Nachtmodus: Karte abdunkeln (bläulicher Nachtton), darüber alle Lichtquellen.
    Wie viel leuchtet, hängt von der Ortsgröße ab: Dörfer haben wenige Laternen und kaum helle Fenster."""
    s, W = m["s"], m["W"]
    rng = random.Random(m["cfg"]["seed"] + 99)
    pop = float(m["cfg"].get("einwohner", 5000))
    size = max(0.0, min(1.0, (pop - 800) / 7000))       # 0 = kleines Dorf, 1 = große Stadt
    win_share = 0.08 + 0.27 * size                       # Anteil der Häuser mit hellen Fenstern
    lantern_step = (160 - 105 * size) * s                # Abstand der Laternen entlang der Hauptstraßen
    # Abdunkeln: multiplizierter Nachtton plus leichte zusätzliche Dunkelheit
    o.append(f'<rect x="-10" y="-10" width="{W + 20}" height="{W + 20}" fill="#4a5c94" style="mix-blend-mode:multiply"/>'
             f'<rect x="-10" y="-10" width="{W + 20}" height="{W + 20}" fill="#050914" fill-opacity="0.22"/>')
    lights, dots = [], []
    # vorhandene Lichtquellen: Türme, Tore, Brückenlaternen, Essen, Minen, Zwergentor
    watch = 0.65 + 0.35 * size                           # Wachfeuer im Dorf kleiner
    lights += [(x, y, 16 * s * watch) for x, y, _ in m["towers"]] + [(x, y, 24 * s * watch) for x, y, _ in m["gates"]]
    lights += [(x, y, 11 * s) for x, y in lamps] + [(x, y, 13 * s) for x, y in forge_glow]
    lights += [(mn["x"], mn["y"], 12 * s) for mn in m["mines"]]
    if m["great_gate"]:
        lights.append((m["great_gate"][0], m["great_gate"][1], 34 * s))
    # Laternen am Straßenrand: knapp außerhalb der Straßen- bzw. Platzfläche, nicht auf Häusern oder im Wasser
    street = unary_union(list(m["streets"]) + list(m["plazas"]) + list(m["paved"]))
    taken = unary_union([b["poly"] for b in m["buildings"] + m["suburbs"]]
                        + [st["poly"] for st in m["stalls"]] + [m["water"]]
                        + [Point(x, y).buffer(r) for x, y, r in m["fountains"] + m["wells"]])
    shapely.prepare(street)
    shapely.prepare(taken)

    def edge_lantern(px, py, nx, ny):
        """Vom Punkt (px, py) auf der Straße in Richtung (nx, ny) bis zum Straßenrand. Die Laterne steht direkt an
        der Kante (wie eine Wandlaterne an der Hausfront) - nie in der Straßenmitte."""
        for d in np.arange(0, 40 * s, 0.6 * s):
            if not street.contains(Point(px + nx * d, py + ny * d)):
                if d < 4 * s:          # Straße hier zu schmal für eine Laterne am Rand
                    return None
                x, y = px + nx * (d - 1.8 * s), py + ny * (d - 1.8 * s)
                if taken.intersects(Point(x, y).buffer(1.5 * s)):
                    return None
                return x, y
        return None

    def add_lantern(pos):
        if pos is not None and all(math.dist(pos, l[:2]) > 25 * s for l in lights):
            lights.append((pos[0], pos[1], 11 * s))
            dots.append((pos[0], pos[1], 1.6 * s, "#ffe7a0"))

    for ln, w in m["internal_roads"]:
        if w < 12 * s:
            continue
        k = rng.uniform(0.3, 0.7) * lantern_step
        while k < ln.length:
            p, q = ln.interpolate(k), ln.interpolate(min(ln.length, k + 2))
            k += lantern_step * rng.uniform(0.85, 1.15)
            tx, ty = q.x - p.x, q.y - p.y
            n = math.hypot(tx, ty) or 1
            sides = [1, -1] if rng.random() < 0.5 else [-1, 1]
            for side in sides:   # erst die eine Straßenseite, falls dort kein Platz ist die andere
                pos = edge_lantern(p.x, p.y, -ty / n * side, tx / n * side)
                if pos is not None:
                    add_lantern(pos)
                    break
    for pl in m["plazas"]:
        if not hasattr(pl, "exterior"):
            continue
        c = pl.centroid
        cnt = max(2, int(pl.exterior.length / ((140 - 70 * size) * s)))
        for i in range(cnt):
            p = pl.exterior.interpolate((i + 0.5) / cnt, normalized=True)
            dx, dy = p.x - c.x, p.y - c.y
            n = math.hypot(dx, dy) or 1
            add_lantern(edge_lantern(c.x, c.y, dx / n, dy / n))
    m["lanterns"] = [(x, y) for x, y, *_ in dots]    # für Prüfungen
    # erleuchtete Fenster: nur ein Teil der Häuser, 1-2 Fenster an der Außenwand
    windows = []
    # Großstadt-Blöcke: jedes Haus der Häuserzeile zählt einzeln (Fenster an seiner Fassade zur Gasse)
    units = []
    for b in m["buildings"] + m["suburbs"]:
        if b.get("form") == "block":
            units += [{"poly": seg, "poor": b.get("poor"), "front": n} for seg, n, _ in b["segments"]]
        else:
            units.append(b)
    for b in units:
        if rng.random() > win_share * (0.35 if b.get("poor") else 1):   # Arme sparen Licht
            continue
        ring = b["poly"].exterior
        for _ in range(1 if rng.random() < 0.6 else 2):
            d = rng.uniform(0, ring.length)
            p, q = ring.interpolate(d), ring.interpolate((d + 1.5) % ring.length)
            if b.get("front"):   # an der Fassade zur Gasse: der Randpunkt in Richtung der Außennormale
                nx_, ny_ = b["front"]
                c0 = b["poly"].centroid
                tw = rng.uniform(-2.5, 2.5) * s
                p = ring.interpolate(ring.project(Point(c0.x + nx_ * 40 * s - ny_ * tw, c0.y + ny_ * 40 * s + nx_ * tw)))
                q = Point(p.x - ny_, p.y + nx_)
            tx, ty = q.x - p.x, q.y - p.y
            n = math.hypot(tx, ty) or 1
            tx, ty = tx / n, ty / n
            cx, cy = b["poly"].centroid.x, b["poly"].centroid.y
            ix, iy = cx - p.x, cy - p.y
            k = math.hypot(ix, iy) or 1
            x, y = p.x + ix / k * 1.2 * s, p.y + iy / k * 1.2 * s
            ang = math.degrees(math.atan2(ty, tx))
            windows.append(f'<rect x="{f(-1.2 * s)}" y="{f(-0.7 * s)}" width="{f(2.4 * s)}" height="{f(1.4 * s)}" '
                           f'transform="translate({f(x)},{f(y)}) rotate({f(ang)})"/>')
            lights.append((x, y, 6 * s, "win"))
    # Lichtschein (additiv wirkend über der Dunkelheit), dann die hellen Kerne
    o.append("".join(f'<circle cx="{f(l[0])}" cy="{f(l[1])}" r="{f(l[2])}" fill="url(#{"glowWin" if len(l) > 3 else "glowNight"})"/>'
                     for l in lights))
    if windows:
        o.append(f'<g fill="#ffd77a">{"".join(windows)}</g>')
    o.append("".join(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r)}" fill="{c}" stroke="#3a2a10" stroke-width="{f(0.5 * s)}"/>'
                     for x, y, r, c in dots))


def plateau_level_svg(o, m):
    """Hochplateau: die andere Geländestufe jenseits der Kante. Das Plateau (Stadt unten) ist heller und
    trockener, das Tiefland (Stadt oben) dunkler und leicht im Dunst."""
    W, B = m["W"], m["biome"]
    lvl = m["plateau_level"]
    col = shade(B["land"], 0.68) if m["plateau_oben"] else shade(B["land"], 1.22)
    # Tiefland im bläulichen Dunst, Plateau sonnig und trockener
    haze = (f'<rect width="{W}" height="{W}" fill="#b9c6cf" fill-opacity="0.2"/>' if m["plateau_oben"]
            else f'<rect width="{W}" height="{W}" fill="#eadca0" fill-opacity="0.14"/>')
    o.append(f'<rect width="{W}" height="{W}" fill="{col}"/>'
             f'<clipPath id="levelClip"><path d="{path_d(lvl)}"/></clipPath>'
             f'<g clip-path="url(#levelClip)">'
             f'{noise_open(m, ("mottleDark", 0.8), ("mottleLight", 0.5), ("scribble", 0.35), extras=B["ground_detail"], base=col, palette=ground_palette(col), shading=(B["relief"], 480))}/>'
             f'{haze}</g>')


def plateau_edge_svg(o, m, rng):
    """Kante des Hochplateaus: Felswand als breites Band auf der Seite der anderen Stufe, mit Böschungsschraffur
    (dick an der Oberkante, spitz zum Fuß), hellem Rand oben, Schatten am Fuß und Wasserfall, wo der Fluss
    über die Kante stürzt."""
    s, W, B = m["s"], m["W"], m["biome"]
    full, river = m["plateau_level"], m["river"]
    oben = m["plateau_oben"]   # Stadt oben: die Kante zur Stadt ist die Oberkante, die Wand fällt zum Tiefland ab
    wc = 30 * s
    frame = box(2 * s, 2 * s, W - 2 * s, W - 2 * s)
    edge = full.boundary.intersection(frame)
    if river is not None:
        edge = edge.difference(river.buffer(1 * s))
    edges = [ln for ln in lines(shapely.line_merge(unary_union([q for q in lines(edge) if q.length > 0.5 * s])))
             if ln.length > 6 * s]   # Ring an seiner Naht zusammenfügen (sonst klafft dort eine Lücke im Felsband)
    if not edges:
        return
    band = full.intersection(unary_union([ln.buffer(wc, cap_style="flat") for ln in edges]))
    if river is not None:
        band = band.difference(river)
    band = unary_union(polys(band))   # nur Flächen (Schnitte können Linienreste liefern)
    inner_side = band.boundary.intersection(full.buffer(-1 * s)).intersection(frame)   # Wandseite zur anderen Stufe
    top_line = unary_union(edges) if oben else inner_side
    foot_line = inner_side if oben else unary_union(edges)
    lower = full.difference(band) if oben else m["land"]
    # Schatten am Fuß der Wand auf der unteren Stufe
    o.append(f'<clipPath id="plateauLowClip"><path d="{path_d(lower)}"/></clipPath>'
             f'<g clip-path="url(#plateauLowClip)"><path d="{line_d(foot_line)}" fill="none" stroke="#141a10" '
             f'stroke-opacity="0.6" stroke-width="{f(36 * s)}" filter="url(#blur)"/></g>')
    # Felswand
    o.append(f'<path d="{path_d(band)}" fill="{B["rock"]}"/>'
             f'<clipPath id="plateauBand"><path d="{path_d(band)}"/></clipPath>'
             f'<g clip-path="url(#plateauBand)" opacity="0.4">{noise_open(m, "rockTex", extras=B["rock_detail"], shading=(0.45, 140))}/></g>')
    # Böschungsschraffur quer zur Kante: Striche von der Oberkante zum Fuß, oben dick
    thick, thin = [], []
    for ln in edges:
        k = rng.uniform(0, 3) * s
        while k < ln.length:
            p, q = ln.interpolate(k), ln.interpolate(min(ln.length, k + 1))
            k += rng.uniform(2.6, 3.8) * s
            tx, ty = q.x - p.x, q.y - p.y
            n = math.hypot(tx, ty) or 1
            nx, ny = -ty / n, tx / n
            if not full.contains(Point(p.x + nx * 4 * s, p.y + ny * 4 * s)):
                nx, ny = -nx, -ny                     # Normale zeigt in die Wand hinein
            depth = wc * rng.uniform(0.7, 1.0)
            a, b = (p.x, p.y), (p.x + nx * depth, p.y + ny * depth)
            top, bot = (a, b) if oben else (b, a)
            mid = (top[0] + (bot[0] - top[0]) * 0.45, top[1] + (bot[1] - top[1]) * 0.45)
            thin.append(f"M{f(top[0])},{f(top[1])}L{f(bot[0])},{f(bot[1])}")
            thick.append(f"M{f(top[0])},{f(top[1])}L{f(mid[0])},{f(mid[1])}")
    o.append(f'<g clip-path="url(#plateauBand)">'
             f'<path d="{"".join(thin)}" stroke="{B["rock_dark"]}" stroke-opacity="0.75" stroke-width="{f(0.9 * s)}"/>'
             f'<path d="{"".join(thick)}" stroke="{B["rock_dark"]}" stroke-opacity="0.9" stroke-width="{f(2 * s)}" '
             f'stroke-linecap="round"/></g>')
    # Fuß dunkel, Oberkante als kräftige Linie mit hellem Lichtsaum
    o.append(f'<path d="{line_d(foot_line)}" fill="none" stroke="#2a2418" stroke-opacity="0.8" stroke-width="{f(1.6 * s)}"/>'
             f'<path d="{line_d(top_line)}" fill="none" stroke="#2a2418" stroke-width="{f(2.6 * s)}"/>'
             f'<path d="{line_d(top_line)}" fill="none" stroke="#f3ead0" stroke-opacity="0.85" stroke-width="{f(1.2 * s)}" '
             f'transform="translate({f(-0.8 * s)},{f(-0.8 * s)})"/>')
    # Wasserfall: wo der Fluss die Kante kreuzt, stürzt er auf ganzer Breite über eine gerade Abbruchkante von
    # Ufer zu Ufer (dort, wo die Felswand an beiden Ufern endet); Wasserstreifen in Fallrichtung, Gischt am Fuß
    if river is not None:
        cut = full.boundary.intersection(frame).intersection(river.buffer(1.5 * s))
        for part in polys(cut.buffer(2 * s)):
            ends = [Point(c) for ln in lines(cut.intersection(part)) for c in (ln.coords[0], ln.coords[-1])]
            if len(ends) < 2:
                continue
            a, b = max(((p, q) for p in ends for q in ends), key=lambda pq: pq[0].distance(pq[1]))
            L = a.distance(b)
            if L < 4 * s:
                continue
            tx, ty = (b.x - a.x) / L, (b.y - a.y) / L
            nx, ny = -ty, tx
            mx, my = (a.x + b.x) / 2, (a.y + b.y) / 2
            if not full.contains(Point(mx + nx * 5 * s, my + ny * 5 * s)):
                nx, ny = -nx, -ny                 # Normale zeigt in die Wand (auf die andere Stufe)
            ext = 6 * s                           # etwas über die Ufer hinaus, der Fluss schneidet ab
            ax, ay, bx, by = a.x - tx * ext, a.y - ty * ext, b.x + tx * ext, b.y + ty * ext
            strip = Polygon([(ax, ay), (bx, by), (bx + nx * wc, by + ny * wc), (ax + nx * wc, ay + ny * wc)])
            fall = strip.intersection(river)
            if fall.is_empty:
                continue
            top, foot = (0.0, wc) if oben else (wc, 0.0)   # Abstand der Ober- bzw. Unterkante von der Kante
            down = 1 if oben else -1                       # Fallrichtung entlang der Normalen
            streaks = []
            for _ in range(int(L * wc / (5 * s * s))):
                u, v = rng.uniform(-ext, L + ext), rng.uniform(0.05, 0.95) * wc
                x, y = a.x + tx * u + nx * v, a.y + ty * u + ny * v
                if fall.contains(Point(x, y)):
                    d = rng.uniform(4, 9) * s
                    streaks.append(f"M{f(x)},{f(y)}l{f(nx * d * down)},{f(ny * d * down)}")
            lip = LineString([(ax + nx * top, ay + ny * top), (bx + nx * top, by + ny * top)]).intersection(river)
            base = LineString([(ax + nx * foot, ay + ny * foot), (bx + nx * foot, by + ny * foot)])
            spray = base.buffer(12 * s).intersection(river)
            o.append(f'<path d="{path_d(fall)}" fill="#cfe3ea" fill-opacity="0.9"/>'
                     f'<path d="{"".join(streaks)}" stroke="#ffffff" stroke-opacity="0.75" stroke-width="{f(1 * s)}" '
                     f'stroke-linecap="round"/>'
                     f'<path d="{line_d(lip)}" fill="none" stroke="#ffffff" stroke-width="{f(2 * s)}"/>'
                     f'<path d="{path_d(spray)}" fill="#ffffff" fill-opacity="0.85" filter="url(#blur)"/>')


def lift_svg(o, lift, s):
    """Aufzug an der Plateaukante: hölzerner Schacht mit Schienen und Streben über die Felswand, Seil und Fahrkorb,
    oben das Windenhaus mit Seiltrommel, unten eine Bretterplattform."""
    ux, uy = lift["u"]
    px, py = -uy, ux
    (tx, ty), (bx, by) = lift["top"], lift["bot"]
    L = math.hypot(tx - bx, ty - by)
    sh = f'transform="translate({f(1.5 * s)},{f(2 * s)})"'
    o.append(f'<path d="{path_d(lift["area"])}" fill="#141a10" fill-opacity="0.45" {sh}/>'   # Schlagschatten
             f'<path d="{path_d(lift["shaft"])}" fill="#4a3522" fill-opacity="0.9"/>')
    rails, braces = [], []
    for side in (-1, 1):
        rails.append(f"M{f(tx + px * side * 5 * s)},{f(ty + py * side * 5 * s)}"
                     f"L{f(bx + px * side * 5 * s)},{f(by + py * side * 5 * s)}")
    n = max(2, int(L / (8 * s)))
    for i in range(n):   # Kreuzstreben im Gerüst
        k0, k1 = i / n, (i + 1) / n
        x0, y0 = tx + (bx - tx) * k0, ty + (by - ty) * k0
        x1, y1 = tx + (bx - tx) * k1, ty + (by - ty) * k1
        braces.append(f"M{f(x0 + px * 5 * s)},{f(y0 + py * 5 * s)}L{f(x1 - px * 5 * s)},{f(y1 - py * 5 * s)}"
                      f"M{f(x0 - px * 5 * s)},{f(y0 - py * 5 * s)}L{f(x1 + px * 5 * s)},{f(y1 + py * 5 * s)}")
    o.append(f'<path d="{"".join(braces)}" stroke="#9a7a50" stroke-width="{f(0.8 * s)}" fill="none"/>'
             f'<path d="{"".join(rails)}" stroke="#2a1d10" stroke-width="{f(1.8 * s)}" fill="none"/>'
             f'<path d="M{f(tx)},{f(ty)}L{f(bx)},{f(by)}" stroke="#e6d8b0" stroke-width="{f(0.7 * s)}"/>')
    # Fahrkorb auf etwa einem Drittel der Höhe
    cx, cy = tx + (bx - tx) * 0.38, ty + (by - ty) * 0.38
    cabin = Polygon([(cx + ux * i * 4.5 * s + px * j * 4.5 * s, cy + uy * i * 4.5 * s + py * j * 4.5 * s)
                     for i, j in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    o.append(f'<path d="{path_d(cabin)}" fill="#b08a58" stroke="#2a1d10" stroke-width="{f(1 * s)}"/>'
             f'<path d="M{f(cx - px * 4.5 * s)},{f(cy - py * 4.5 * s)}L{f(cx + px * 4.5 * s)},{f(cy + py * 4.5 * s)}" '
             f'stroke="#5a4028" stroke-width="{f(0.7 * s)}"/>')
    # Plattform unten
    land = lift["landing"]
    lc = land.centroid
    o.append(f'<path d="{path_d(land)}" fill="#a08058" stroke="#2a1d10" stroke-width="{f(1 * s)}"/>'
             + "".join(f'<path d="M{f(lc.x + ux * d * s - px * 8 * s)},{f(lc.y + uy * d * s - py * 8 * s)}'
                     f'L{f(lc.x + ux * d * s + px * 8 * s)},{f(lc.y + uy * d * s + py * 8 * s)}" '
                     f'stroke="#6a5034" stroke-width="{f(0.6 * s)}"/>' for d in (-2.5, 0, 2.5)))
    # Windenhaus oben: Satteldach mit First quer zum Schacht, Seiltrommel an der Schachtseite
    house = lift["house"]
    hc = house.centroid
    r0, r1 = (hc.x - px * 9 * s, hc.y - py * 9 * s), (hc.x + px * 9 * s, hc.y + py * 9 * s)   # First
    c = house.exterior.coords
    lit = Polygon([r0, r1, c[2], c[1]])   # Dachhälfte auf der +u-Seite etwas heller
    o.append(f'<path d="{path_d(house)}" fill="#8a5a3a" stroke="#2a1d10" stroke-width="{f(1.1 * s)}"/>'
             f'<path d="{path_d(lit)}" fill="#ffffff" fill-opacity="0.12"/>'
             f'<path d="M{f(r0[0])},{f(r0[1])}L{f(r1[0])},{f(r1[1])}" stroke="#2a1d10" stroke-width="{f(1 * s)}"/>'
             f'<circle cx="{f(tx)}" cy="{f(ty)}" r="{f(3 * s)}" fill="#6a4a2c" stroke="#2a1d10" stroke-width="{f(0.9 * s)}"/>')


def mountain_svg(o, m, rng):
    """Felsmassiv: Grundton, Felstextur, Hangschraffur, Grate und Schneefelder."""
    s, W, B = m["s"], m["W"], m["biome"]
    rock = m["sea"]
    o.append(f'<rect width="{W}" height="{W}" fill="{B["rock"]}"/>'
             f'{noise_open(m, "rockTex", extras=B["rock_detail"], shading=(0.45, 140))} opacity="0.7"/>')
    if rock is None or rock.is_empty:
        return
    # Hangschraffur: kurze Striche bergab (intern liegt das Land im Süden)
    minx, miny, maxx, maxy = rock.bounds
    n = int(min(3500, rock.area / (260 * s * s)))
    xs = np.array([rng.uniform(minx, maxx) for _ in range(n)])
    ys = np.array([rng.uniform(miny, maxy) for _ in range(n)])
    ok = shapely.contains_xy(rock.buffer(-4 * s), xs, ys)
    dark, light = [], []
    for x, y in zip(xs[ok], ys[ok]):
        a = math.pi / 2 + rng.uniform(-0.5, 0.5)
        ln = rng.uniform(7, 16) * s
        seg = f"M{f(x)},{f(y)}l{f(math.cos(a) * ln)},{f(math.sin(a) * ln)}"
        (dark if rng.random() < 0.7 else light).append(seg)
    o.append(f'<path d="{"".join(dark)}" stroke="{B["rock_dark"]}" stroke-opacity="0.45" stroke-width="{f(1.1 * s)}" '
             f'stroke-linecap="round"/>'
             f'<path d="{"".join(light)}" stroke="#d8d3c8" stroke-opacity="0.35" stroke-width="{f(1.1 * s)}" stroke-linecap="round"/>')
    # Grate: lange gezackte Linien weit im Fels
    inner = rock.buffer(-70 * s)
    if not inner.is_empty:
        ix0, iy0, ix1, iy1 = inner.bounds
        crests = []
        for _ in range(14):
            x, y = rng.uniform(ix0, ix1), rng.uniform(iy0, iy1)
            pts, a = [(x, y)], rng.choice([0, math.pi]) + rng.uniform(-0.4, 0.4)
            for _ in range(rng.randint(6, 14)):
                a += rng.uniform(-0.7, 0.7)
                x, y = x + math.cos(a) * 22 * s, y + math.sin(a) * 22 * s
                pts.append((x, y))
            crests += lines(LineString(pts).intersection(inner))
        cd = "".join(line_d(c) for c in crests)
        if cd:
            o.append(f'<path d="{cd}" fill="none" stroke="#2c2924" stroke-opacity="0.6" stroke-width="{f(3 * s)}" '
                     f'stroke-linejoin="round" transform="translate({f(1.5 * s)},{f(2 * s)})"/>'
                     f'<path d="{cd}" fill="none" stroke="#e6e1d6" stroke-opacity="0.75" stroke-width="{f(1.6 * s)}" stroke-linejoin="round"/>')
    # Schneefelder: abhängig vom Abstand zum Tal (nicht vom Kartenrand), fleckig über eine Rauschmaske
    snow = rock.difference(m["land"].buffer(260 * s))
    if not snow.is_empty:
        o.append(f'<clipPath id="snowClip"><path d="{path_d(snow.buffer(30 * s).intersection(rock))}"/></clipPath>'
                 f'<path d="{path_d(snow)}" fill="#f4f6f7" fill-opacity="0.55" filter="url(#blur)"/>'
                 f'<g clip-path="url(#snowClip)">{noise_open(m, "snowTex")}/></g>')


def slope_svg(o, m, rng):
    """Berghang: steiniger Streifen unter der Felskante, der nach unten in die Alm übergeht.
    Er reicht über die ganze Stadt hinaus; der Stadtboden selbst ist Stein und Geröll."""
    s, B = m["s"], m["biome"]
    rock, land = m["sea"], m["land"]
    if rock is None or rock.is_empty:
        return
    far = max(rock.distance(shapely.Point(x, y)) for x, y in m["shape"].exterior.coords)
    depth = far + 160 * s
    bands = []
    for k in range(9, 0, -1):
        band = land.intersection(rock.buffer(depth * k / 9))
        bands.append(f'<path d="{path_d(band)}"/>')
    o.append(f'<g fill="{B["slope"]}" fill-opacity="0.18" filter="url(#blur)">{"".join(bands)}</g>')
    upper = land.intersection(rock.buffer(depth * 0.75))
    o.append(f'<clipPath id="slopeClip"><path d="{path_d(upper)}"/></clipPath>'
             f'<g clip-path="url(#slopeClip)" opacity="0.45">{noise_open(m, "rockTex", extras=B["rock_detail"], shading=(0.45, 140))}/></g>')
    # Hangschraffur, nach unten immer seltener
    zone = land.intersection(rock.buffer(depth))
    minx, miny, maxx, maxy = zone.bounds
    n = int(min(2500, zone.area / (450 * s * s)))
    xs = np.array([rng.uniform(minx, maxx) for _ in range(n)])
    ys = np.array([rng.uniform(miny, maxy) for _ in range(n)])
    ok = shapely.contains_xy(zone, xs, ys)
    dark, light = [], []
    for x, y in zip(xs[ok], ys[ok]):
        if rng.random() > 1 - rock.distance(shapely.Point(x, y)) / depth:
            continue
        a = math.pi / 2 + rng.uniform(-0.45, 0.45)
        ln = rng.uniform(6, 13) * s
        seg = f"M{f(x)},{f(y)}l{f(math.cos(a) * ln)},{f(math.sin(a) * ln)}"
        (dark if rng.random() < 0.7 else light).append(seg)
    o.append(f'<path d="{"".join(dark)}" stroke="{B["rock_dark"]}" stroke-opacity="0.4" stroke-width="{f(1 * s)}" stroke-linecap="round"/>'
             f'<path d="{"".join(light)}" stroke="#ddd8cc" stroke-opacity="0.3" stroke-width="{f(1 * s)}" stroke-linecap="round"/>')
    # Stadtboden: Fels und Geröll statt Wiese
    o.append(f'<path d="{path_d(m["city_land"])}" fill="{B["city_ground"]}" fill-opacity="0.9"/>'
             f'<clipPath id="cityClip"><path d="{path_d(m["city_land"])}"/></clipPath>'
             f'<g clip-path="url(#cityClip)" opacity="0.5">{noise_open(m, "rockTex", extras=B["rock_detail"], shading=(0.45, 140))}/></g>')


def rock_houses_svg(o, m, rng):
    """In die Felswand gehauene Häuser oberhalb der obersten Terrassen: Fassaden mit Tür und Fenstern."""
    s, rock = m["s"], m["sea"]
    if rock is None:
        return
    gate = m["great_gate"]
    river = m["river"]
    out = []
    for ln in lines(m["city_land"].boundary.intersection(rock.buffer(2 * s))):
        k = rng.uniform(10, 20) * s
        while k < ln.length - 12 * s:
            p, q = ln.interpolate(k), ln.interpolate(k + 3)
            k += rng.uniform(38, 52) * s
            if gate and math.dist((p.x, p.y), gate[:2]) < 70 * s:
                continue
            if river is not None and river.distance(p) < 25 * s:
                continue
            tx, ty = (q.x - p.x) / 3, (q.y - p.y) / 3
            nx, ny = -ty, tx
            if not rock.contains(shapely.Point(p.x + nx * 8 * s, p.y + ny * 8 * s)):
                nx, ny = -nx, -ny
            ang = math.degrees(math.atan2(ny, nx))   # lokale x-Achse zeigt in den Fels
            w = rng.uniform(9, 13) * s                 # halbe Fassadenbreite
            st = f'stroke="#2a2723" stroke-width="{f(1 * s)}"'
            out.append(f'<g transform="translate({f(p.x)},{f(p.y)}) rotate({f(ang)})">'
                       f'<path d="M{f(1 * s)},{f(-w - 3 * s)}L{f(16 * s)},{f(-w + 1 * s)}L{f(16 * s)},{f(w - 1 * s)}'
                       f'L{f(1 * s)},{f(w + 3 * s)}Z" fill="#2e2a25" fill-opacity="0.85"/>'
                       f'<rect x="{f(-1 * s)}" y="{f(-w)}" width="{f(6 * s)}" height="{f(2 * w)}" fill="#c2baa6" {st}/>'
                       f'<path d="M{f(-1 * s)},{f(-w + 3 * s)}H{f(5 * s)}M{f(-1 * s)},{f(w - 3 * s)}H{f(5 * s)}" '
                       f'stroke="#8a8272" stroke-width="{f(0.7 * s)}"/>'
                       f'<path d="M{f(-1.5 * s)},{f(-3 * s)}H{f(2.5 * s)}A{f(3 * s)},{f(3 * s)} 0 0 1 {f(2.5 * s)},{f(3 * s)}'
                       f'H{f(-1.5 * s)}Z" fill="#171411"/>'
                       f'<rect x="{f(-0.5 * s)}" y="{f(-w + 1.8 * s)}" width="{f(2.6 * s)}" height="{f(2.6 * s)}" fill="#ffcf6a"/>'
                       f'<rect x="{f(-0.5 * s)}" y="{f(w - 4.4 * s)}" width="{f(2.6 * s)}" height="{f(2.6 * s)}" fill="#ffcf6a"/></g>')
    o.extend(out)


def cliff_svg(o, m, rng):
    """Steilkante zwischen Tal und Fels: kurze Schraffen in den Fels hinein."""
    s, rock, land = m["s"], m["sea"], m["land"]
    if rock is None:
        return
    ticks = []
    for ln in lines(land.boundary.intersection(rock.buffer(2 * s))):
        k = 0.0
        while k < ln.length - 2:
            p, q = ln.interpolate(k), ln.interpolate(k + 2)
            tx, ty = (q.x - p.x) / 2, (q.y - p.y) / 2
            nx, ny = -ty, tx
            if not rock.contains(shapely.Point(p.x + nx * 6 * s, p.y + ny * 6 * s)):
                nx, ny = -nx, -ny
            ln_ = rng.uniform(5, 13) * s
            ticks.append(f"M{f(p.x)},{f(p.y)}l{f(nx * ln_)},{f(ny * ln_)}")
            k += rng.uniform(4, 6) * s
    if ticks:
        o.append(f'<path d="{"".join(ticks)}" stroke="#34312b" stroke-opacity="0.8" stroke-width="{f(1.2 * s)}" stroke-linecap="round"/>')


def chasm_svg(o, m):
    """Klamm: helle Felskante innen, Wildbach mit Gischt am Grund."""
    s, B = m["s"], m["biome"]
    d = path_d(m["river"])
    o.append(f'<clipPath id="chasmClip"><path d="{d}"/></clipPath>'
             f'<g clip-path="url(#chasmClip)"><path d="{d}" fill="none" stroke="#7a7468" stroke-width="{f(26 * s)}"/>'
             f'<path d="{d}" fill="none" stroke="#5a554c" stroke-width="{f(16 * s)}"/>'
             f'<path d="{d}" fill="none" stroke="#3a3631" stroke-width="{f(8 * s)}"/></g>')
    if m.get("river_line") is not None:
        brook = m["river_line"].intersection(m["river"].buffer(-4 * s))
        bd = line_d(brook)
        if bd:
            o.append(f'<path d="{bd}" fill="none" stroke="{B["river"]}" stroke-width="{f(4 * s)}" stroke-linejoin="round"/>'
                     f'<path d="{bd}" fill="none" stroke="#f2f7f8" stroke-opacity="0.8" stroke-width="{f(1.2 * s)}" '
                     f'stroke-dasharray="{f(3 * s)} {f(5 * s)}"/>')


def great_gate_svg(o, m):
    """Zwergentor in der Felswand; lokale x-Achse zeigt in den Berg."""
    s = m["s"]
    x, y, ang = m["great_gate"]
    st = f'stroke="#26231f" stroke-width="{f(1.4 * s)}"'
    o.append(f'<g transform="translate({f(x)},{f(y)}) rotate({f(ang)}) scale(1.4)">'
             f'<rect x="{f(-14 * s)}" y="{f(-26 * s)}" width="{f(12 * s)}" height="{f(52 * s)}" fill="#a39b8a" {st}/>'
             + "".join(f'<path d="M{f(-14 * s + i * 2.4 * s)},{f(-26 * s)}V{f(26 * s)}" stroke="#6d675b" stroke-width="{f(0.7 * s)}"/>'
                       for i in range(1, 5))
             + f'<path d="M{f(-2 * s)},{f(-22 * s)}H{f(26 * s)}A{f(22 * s)},{f(22 * s)} 0 0 1 {f(26 * s)},{f(22 * s)}'
             f'H{f(-2 * s)}Z" fill="#1c1916" {st}/>'
             f'<rect x="{f(-6 * s)}" y="{f(-34 * s)}" width="{f(40 * s)}" height="{f(10 * s)}" fill="#c4bba6" {st}/>'
             f'<rect x="{f(-6 * s)}" y="{f(24 * s)}" width="{f(40 * s)}" height="{f(10 * s)}" fill="#c4bba6" {st}/>'
             f'<path d="M{f(-6 * s)},{f(-29 * s)}H{f(34 * s)}M{f(-6 * s)},{f(29 * s)}H{f(34 * s)}" stroke="#7d7566" stroke-width="{f(0.8 * s)}"/>'
             f'<path d="M{f(4 * s)},{f(-6 * s)}L{f(14 * s)},0L{f(4 * s)},{f(6 * s)}" fill="none" stroke="#d9a24a" stroke-width="{f(1.6 * s)}"/>'
             f'<g filter="url(#glow)"><circle cx="{f(-18 * s)}" cy="{f(-34 * s)}" r="{f(12 * s)}" fill="{C["glow"]}"/>'
             f'<circle cx="{f(-18 * s)}" cy="{f(34 * s)}" r="{f(12 * s)}" fill="{C["glow"]}"/></g>'
             f'<circle cx="{f(-18 * s)}" cy="{f(-34 * s)}" r="{f(3.5 * s)}" fill="#ffd27a" {st}/>'
             f'<circle cx="{f(-18 * s)}" cy="{f(34 * s)}" r="{f(3.5 * s)}" fill="#ffd27a" {st}/></g>')


def mills_svg(o, m):
    """Wasserräder am Ufer, Windmühlenflügel und Heuhaufen."""
    s = m["s"]
    for wh in m.get("wheels", []):
        L, Wd = wh["len"], wh["wid"]
        hx, hy = wh["house"]   # Wellbaum vom Mühlhaus zum Rad
        o.append(f'<path d="M{f(hx)},{f(hy)}L{f(wh["x"])},{f(wh["y"])}" stroke="{C["outline"]}" stroke-width="{f(3.2 * s)}"/>'
                 f'<path d="M{f(hx)},{f(hy)}L{f(wh["x"])},{f(wh["y"])}" stroke="#5a4128" stroke-width="{f(2 * s)}"/>')
        paddles = "".join(f"M{f(x)},{f(-Wd / 2)}V{f(Wd / 2)}" for x in np.arange(-L / 2 + 1.6 * s, L / 2, 2.2 * s))
        foam = "".join(f'<path d="M{f(x - 1.5 * s)},{f(-Wd / 2 - 1.6 * s)}q{f(1.5 * s)},{f(-1.2 * s)} {f(3 * s)},0"/>'
                       for x in np.arange(-L / 2 + 1.5 * s, L / 2 - 1 * s, 3.2 * s))
        o.append(f'<g transform="translate({f(wh["x"])},{f(wh["y"])}) rotate({f(wh["angle"])})">'
                 f'<rect x="{f(-L / 2 + 1.5 * s)}" y="{f(-Wd / 2 + 1.5 * s)}" width="{f(L)}" height="{f(Wd)}" fill="#000" fill-opacity="0.35"/>'
                 f'<g fill="none" stroke="#ffffff" stroke-opacity="0.75" stroke-width="{f(0.8 * s)}" stroke-linecap="round">{foam}</g>'
                 f'<rect x="{f(-L / 2)}" y="{f(-Wd / 2)}" width="{f(L)}" height="{f(Wd)}" rx="{f(0.6 * s)}" fill="#6b4c30" '
                 f'stroke="{C["outline"]}" stroke-width="{f(0.9 * s)}"/>'
                 f'<path d="{paddles}" stroke="#2e2014" stroke-width="{f(0.8 * s)}"/>'
                 f'<rect x="{f(-1 * s)}" y="{f(-Wd / 2 - 1 * s)}" width="{f(2 * s)}" height="{f(Wd + 3 * s)}" fill="#3a2a1a"/></g>')
    for wm in m.get("windmills", []):
        # Draufsicht: die Flügel drehen sich in einer senkrechten Ebene vor der Kappe und erscheinen von oben nur
        # als schmaler Streifen quer zur Windrichtung (lokal +y). Wie weit er reicht, hängt von der Flügelstellung ab.
        L, y0 = wm["len"], 12.5 * s
        phase = math.radians(wm["angle"] * 7 % 90)
        reach = L * max(abs(math.cos(phase)), abs(math.sin(phase)))
        short = L * min(abs(math.cos(phase)), abs(math.sin(phase)))
        ticks = "".join(f"M{f(x)},{f(y0 - 1.1 * s)}v{f(2.2 * s)}" for x in np.arange(-reach + 2 * s, reach - 1 * s, 2.6 * s)
                        if abs(x) > 3 * s)
        sails = (f'<rect x="{f(-short)}" y="{f(y0 - 0.9 * s)}" width="{f(2 * short)}" height="{f(1.8 * s)}" fill="#cfc5aa" '
                 f'stroke="#3a2a1a" stroke-width="{f(0.5 * s)}"/>'
                 f'<rect x="{f(-reach)}" y="{f(y0 - 1.1 * s)}" width="{f(2 * reach)}" height="{f(2.2 * s)}" fill="#e8dfc8" '
                 f'stroke="#3a2a1a" stroke-width="{f(0.6 * s)}"/>'
                 f'<path d="{ticks}" stroke="#7a6a52" stroke-width="{f(0.4 * s)}"/>'
                 f'<path d="M{f(-reach)},{f(y0)}H{f(reach)}" stroke="#3a2a1a" stroke-width="{f(0.7 * s)}"/>')
        shaft = (f'<rect x="{f(-1.3 * s)}" y="{f(7 * s)}" width="{f(2.6 * s)}" height="{f(y0 - 7 * s)}" fill="#4a3522" '
                 f'stroke="{C["outline"]}" stroke-width="{f(0.5 * s)}"/>'
                 f'<circle cx="0" cy="{f(y0)}" r="{f(1.8 * s)}" fill="#3a2a1a"/>')
        tail = (f'<path d="M0,{f(-7 * s)}V{f(-24 * s)}" stroke="{C["outline"]}" stroke-width="{f(2 * s)}"/>'   # Steert
                f'<path d="M0,{f(-7 * s)}V{f(-24 * s)}" stroke="#6b4c30" stroke-width="{f(1.2 * s)}"/>'
                f'<circle cx="0" cy="{f(-24 * s)}" r="{f(1.6 * s)}" fill="#6b4c30" stroke="{C["outline"]}" stroke-width="{f(0.5 * s)}"/>')
        rot = f'rotate({f(wm["angle"])})'
        o.append(f'<g transform="translate({f(wm["x"] + 2.5 * s)},{f(wm["y"] + 3 * s)}) {rot}" fill="#000" stroke="#000" '
                 f'opacity="0.3"><rect x="{f(-reach)}" y="{f(y0 - 1.1 * s)}" width="{f(2 * reach)}" height="{f(2.2 * s)}"/>'
                 f'<path d="M0,{f(-7 * s)}V{f(-24 * s)}" stroke-width="{f(1.6 * s)}"/></g>'
                 f'<g transform="translate({f(wm["x"])},{f(wm["y"])}) {rot}">{tail}{shaft}{sails}</g>')
    if m.get("haystacks"):
        hs = "".join(f'<circle cx="{f(x + 1.5 * s)}" cy="{f(y + 1.8 * s)}" r="{f(r)}" fill="#000" fill-opacity="0.35"/>'
                     f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r)}" fill="#d6b65a" stroke="#6d5426" stroke-width="{f(0.8 * s)}"/>'
                     f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r * 0.55)}" fill="none" stroke="#a88a3a" stroke-width="{f(0.6 * s)}"/>'
                     for x, y, r in m["haystacks"])
        o.append(hs)


def mines_svg(o, m):
    """Mineneingänge mit Holzrahmen, Gleisen und Abraumhalde."""
    s = m["s"]
    for mn in m["mines"]:
        if not mn["spoil"].is_empty:
            o.append(f'<path d="{path_d(mn["spoil"])}" fill="#8e897d" stroke="#3a3731" stroke-width="{f(1 * s)}"/>')
        o.append(f'<g transform="translate({f(mn["x"])},{f(mn["y"])}) rotate({f(mn["angle"])})">'
                 f'<path d="M{f(-26 * s)},{f(-2.5 * s)}H{f(2 * s)}M{f(-26 * s)},{f(2.5 * s)}H{f(2 * s)}" '
                 f'stroke="#4a3a2a" stroke-width="{f(1 * s)}"/>'
                 + "".join(f'<path d="M{f(-24 * s + i * 4 * s)},{f(-4 * s)}V{f(4 * s)}" stroke="#6b5236" '
                           f'stroke-width="{f(1.2 * s)}"/>' for i in range(6))
                 + f'<path d="M{f(-1 * s)},{f(-8 * s)}H{f(8 * s)}A{f(8 * s)},{f(8 * s)} 0 0 1 {f(8 * s)},{f(8 * s)}H{f(-1 * s)}Z" '
                 f'fill="#141210" stroke="#7a5a3a" stroke-width="{f(2.2 * s)}"/>'
                 f'<g filter="url(#glow)"><circle cx="{f(-4 * s)}" cy="{f(-10 * s)}" r="{f(6 * s)}" fill="{C["glow"]}"/></g>'
                 f'<circle cx="{f(-4 * s)}" cy="{f(-10 * s)}" r="{f(2 * s)}" fill="#ffd27a"/></g>')


def render_svg(m):
    s, W = m["s"], m["W"]
    rng = random.Random(m["cfg"]["seed"])
    B = m["biome"]
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{W}" viewBox="0 0 {W} {W}">', defs(m)]
    if font_face_css():
        o.append(f"<style>{font_face_css()}</style>")
    rot = f'rotate({m["rot"]} {f(W / 2)} {f(W / 2)})'
    o.append(f'<g transform="{rot}">')
    # Wasser bzw. Fels
    if B["mountain"]:
        mountain_svg(o, m, rng)
    elif m.get("plateau"):
        plateau_level_svg(o, m)
    else:
        o.append(f'<rect width="{W}" height="{W}" fill="url(#seaGrad)"/>')
    if m["river"] is not None:
        o.append(f'<path d="{path_d(m["river"])}" fill="{"#1e1c19" if B["chasm"] else B["river"]}"/>')
    if not B["mountain"] and not m.get("plateau"):
        o.append(f'<path d="{path_d(m["land"])}" fill="none" stroke="{B["shallow"]}" stroke-width="{f(34 * s)}" '
                 f'filter="url(#blur)" clip-path="url(#seaClip)"/>')
        o.append(f'<g clip-path="url(#seaClip)" opacity="0.55">{noise_open(m, "fog")}/></g>')
    if m["floes"]:
        fd = "".join(path_d(fl) for fl in m["floes"])
        o.append(f'<path d="{fd}" fill="#f2f6f8" stroke="#8fb0c4" stroke-width="{f(1.2 * s)}"/>')
    # Land
    o.append(f'<path d="{path_d(m["land"])}" fill="{B["land"]}"/>')
    o.append(f'<g clip-path="url(#landClip)">'
             f'{noise_open(m, ("mottleDark", 0.8), ("mottleLight", 0.5), ("scribble", 0.35), extras=B["ground_detail"], base=B["land"], palette=ground_palette(B["land"]), shading=(B["relief"], 480))}/>'
             f'<use href="#tex_umgebung"/></g>')
    tex = m.setdefault("_tex", {})
    tex["umgebung"] = _tex_pool().submit(umgebung.image, W, s, umgebung_daten(m))
    o.append(f'<path d="{path_d(m["land"])}" fill="none" stroke="{C["coast"]}" stroke-width="{f(2.4 * s)}"/>')
    if B["mountain"]:
        slope_svg(o, m, rng)
    if B["chasm"] and m["river"] is not None:
        chasm_svg(o, m)
    if B["mountain"]:
        cliff_svg(o, m, rng)
        rock_houses_svg(o, m, rng)
    if m.get("plateau"):
        plateau_edge_svg(o, m, rng)
    if B["green_banks"] and not m["water"].is_empty:   # Wüste: fruchtbarer Streifen am Wasser
        o.append(f'<g clip-path="url(#landClip)"><path d="{path_d(m["water"])}" fill="none" stroke="#7a8a40" '
                 f'stroke-opacity="0.75" stroke-width="{f(70 * s)}" filter="url(#blur)"/></g>')
    if m["dunes"]:
        dd = "".join(line_d(ln) for ln in m["dunes"])
        o.append(f'<path d="{dd}" fill="none" stroke="#a9874f" stroke-opacity="0.55" stroke-width="{f(2.4 * s)}" '
                 f'stroke-linecap="round"/>'
                 f'<path d="{dd}" fill="none" stroke="#f6e6bb" stroke-opacity="0.6" stroke-width="{f(1.6 * s)}" '
                 f'stroke-linecap="round" transform="translate({f(-2 * s)},{f(-2 * s)})"/>')
    pools_svg(o, m, rng)
    # Wald, Felder
    if not m["forest"].is_empty:
        o.append(f'<path d="{path_d(m["forest"])}" fill="{B["forest_floor"]}" fill-opacity="0.55" filter="url(#softblur)"/>')
    for i, fl in enumerate(m["fields"]):
        o.append(f'<path d="{path_d(fl["poly"])}" fill="url(#field{i})" stroke="#2e2a1e" stroke-width="{f(1.6 * s)}"/>')
    # Landstraßen
    rd = "".join(line_d(ln) for ln, _ in m["ext_roads"])
    if rd:
        o.append(f'<path d="{rd}" fill="none" stroke="{C["road_edge"]}" stroke-opacity="0.6" stroke-width="{f(18 * s)}" '
                 f'stroke-linecap="round" stroke-linejoin="round"/>')
        o.append(f'<path d="{rd}" fill="none" stroke="{B["road"]}" stroke-width="{f(14 * s)}" '
                 f'stroke-linecap="round" stroke-linejoin="round"/>')
        if not m["pools"].is_empty and B["pool_style"] == "sumpf":   # Knüppeldamm über dem Sumpfwasser
            wet = "".join(line_d(ln.intersection(m["pools"].buffer(3 * s))) for ln, _ in m["ext_roads"])
            if wet:
                o.append(f'<path d="{wet}" fill="none" stroke="#3e2f1c" stroke-width="{f(15 * s)}"/>'
                         f'<path d="{wet}" fill="none" stroke="#7d6544" stroke-width="{f(13 * s)}" '
                         f'stroke-dasharray="{f(2.6 * s)} {f(0.9 * s)}"/>')
    for fort in m["forts"]:
        if fort.get("lift"):
            lift_svg(o, fort["lift"], s)
    # Stadtflächen; ihre Randlinie läuft nicht quer über die einmündenden Landstraßen
    # (sonst zeichnet sich dort, wo die Straße in die Gassen übergeht, ein Bogen bzw. Strich ab)
    joins = unary_union([ln.buffer(9 * s) for ln, _ in m["ext_roads"]]) if m["ext_roads"] else None

    def edged(g, fill):
        if joins is None:
            return f'<path d="{path_d(g)}" fill="{fill}" stroke="{B["street_edge"]}" stroke-width="{f(1.2 * s)}"/>'
        # Randlinie aus den Teilflächen: Zuschnitte können GeometryCollections mit Linien- oder Punktresten
        # liefern, deren .boundary None ist
        edge = line_d(unary_union([p.boundary for p in polys(g)]).difference(joins))
        return (f'<path d="{path_d(g)}" fill="{fill}"/>' +
                (f'<path d="{edge}" fill="none" stroke="{B["street_edge"]}" stroke-width="{f(1.2 * s)}"/>' if edge else ""))
    if m["streets"]:   # eine gemeinsame Fläche: Zugangswege (z.B. von der Festungsbrücke) gehen ohne Randlinie
        o.append(edged(unary_union(m["streets"]), B["street"]))   # und ohne sichtbares rundes Ende in die Gassen über
    paved_fill = "url(#cobble)" if B["wall"] == "stein" else B["street"]
    paved = [pv for pv in m["paved"] + m["plazas"] if not pv.is_empty]
    if paved and m["streets"]:
        # Plätze gehen weich in die Gassen über: das Pflaster blendet am Rand über wenige Pixel aus (Maske mit
        # weichgezeichnetem Umriss), die Randlinie fehlt dort, wo eine Gasse einmündet
        street_u = unary_union(m["streets"])
        crisp = unary_union(paved)
        soft = crisp.buffer(2 * s)
        near = street_u.buffer(10 * s)               # nur an den Einmündungen weich, sonst scharfer Rand
        o.append(f'<filter id="pavedSoft" x="-5%" y="-5%" width="110%" height="110%">'
                 f'<feGaussianBlur stdDeviation="{f(3.5 * s)}"/></filter>'
                 f'<clipPath id="pavedNear"><path d="{path_d(near)}"/></clipPath>'
                 f'<mask id="pavedMask" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{W}">'
                 f'<path d="{path_d(crisp.difference(near))}" fill="#fff"/>'
                 f'<g clip-path="url(#pavedNear)"><path d="{path_d(soft)}" fill="#fff" filter="url(#pavedSoft)"/></g></mask>'
                 f'<path d="{path_d(soft.buffer(6 * s))}" fill="{paved_fill}" mask="url(#pavedMask)"/>')
        open_side = street_u.buffer(2 * s) if joins is None else street_u.buffer(2 * s).union(joins)
        edge = line_d(unary_union([p.boundary for pv in paved for p in polys(pv)]).difference(open_side))
        if edge:
            o.append(f'<path d="{edge}" fill="none" stroke="{B["street_edge"]}" stroke-width="{f(1.2 * s)}"/>')
    else:
        for pv in paved:
            o.append(edged(pv, paved_fill))
    slums = [d["poly"] for d in m.get("districts", []) if DISTRICT_TYPES.get(d["typ"], {}).get("poor")]
    if slums and m["streets"]:   # Armenviertel: festgetretener Boden, schlammige Gassen mit Pfützen
        slum = unary_union(slums).buffer(6 * s).intersection(m["city_land"].union(m["slum_outside"]))
        o.append(f'<path d="{path_d(slum)}" fill="#5a4630" fill-opacity="0.35" filter="url(#softblur)"/>')
        mud = slum.intersection(unary_union(m["streets"]))
        if not mud.is_empty:
            o.append(f'<path d="{path_d(mud)}" fill="#5a4630" fill-opacity="0.5"/>')
            mrng = random.Random(m["cfg"]["seed"] + 31)
            minx, miny, maxx, maxy = mud.bounds
            puddles, inner = [], mud.buffer(-1.5 * s)
            shapely.prepare(inner)
            for _ in range(int(mud.area / (900 * s * s))):
                x, y = mrng.uniform(minx, maxx), mrng.uniform(miny, maxy)
                if inner.contains_properly(Point(x, y)):
                    puddles.append(f'<ellipse cx="{f(x)}" cy="{f(y)}" rx="{f(mrng.uniform(1.5, 3.2) * s)}" '
                                   f'ry="{f(mrng.uniform(1, 2) * s)}" transform="rotate({f(mrng.uniform(0, 180))} {f(x)} {f(y)})"/>')
            if puddles:
                o.append(f'<g fill="#3c4a4e" fill-opacity="0.55">{"".join(puddles)}</g>')
    if not m["pools"].is_empty and B["stilts"]:   # Pfahldorf: Gassen und Plätze über dem Sumpfwasser sind Stege
        pools = m["pools"]
        decks = unary_union(list(m["streets"]) + list(m["paved"]) + list(m["plazas"])).intersection(pools)
        if not decks.is_empty:   # Stegstraßen in voller Wegbreite aus Bohlen, dunkle Kante zum Wasser
            o.append(f'<path d="{path_d(decks)}" fill="url(#planks)" stroke="#2e2010" stroke-width="{f(1.4 * s)}"/>')
        # Hauptwege: Bohlen quer zur Laufrichtung, so breit wie der Weg
        for ln, w in m["internal_roads"]:
            walk = line_d(ln.intersection(pools))
            if walk:
                o.append(f'<path d="{walk}" fill="none" stroke="#8a6d45" stroke-width="{f(w - 2 * s)}" '
                         f'stroke-dasharray="{f(2.4 * s)} {f(0.8 * s)}"/>')
    # Sonderflächen: Tempelvorplatz, Exerzierplatz, Friedhof
    for g, kind in m["grounds"]:
        d = path_d(g)
        if kind == "estate":       # Palastgelände: gepflegter Rasen innerhalb einer Mauer
            o.append(f'<path d="{d}" fill="#6a8a4c" fill-opacity="0.85"/>'
                     f'<path d="{d}" fill="none" stroke="{C["outline"]}" stroke-width="{f(4 * s)}"/>'
                     f'<path d="{d}" fill="none" stroke="#a9a493" stroke-width="{f(2.4 * s)}"/>')
        elif kind == "garden":     # Barockgarten: Hecke, Beete und Wegkreuz
            c = g.centroid
            o_, e1, e2 = axes(g)
            cross = unary_union([LineString([(c.x - e1[0], c.y - e1[1]), (c.x + e1[0], c.y + e1[1])]),
                                 LineString([(c.x - e2[0], c.y - e2[1]), (c.x + e2[0], c.y + e2[1])])]
                                ).intersection(g.buffer(-3 * s))
            beds = g.buffer(-3 * s).difference(cross.buffer(3 * s))
            o.append(f'<path d="{d}" fill="#d9cfb2" stroke="#2f4a26" stroke-width="{f(3 * s)}"/>'
                     f'<path d="{path_d(beds)}" fill="#55783f" stroke="#2f4a26" stroke-width="{f(1.6 * s)}"/>'
                     f'<path d="{path_d(beds.buffer(-4 * s))}" fill="none" stroke="#7d9e5a" stroke-width="{f(1 * s)}" '
                     f'stroke-dasharray="{f(1.5 * s)} {f(1.5 * s)}"/>')
        elif kind == "farmyard":   # Hofplatz: festgetretene Erde und Holzzaun
            o.append(f'<path d="{d}" fill="#8b7655" fill-opacity="0.85"/>'
                     f'<path d="{d}" fill="none" stroke="#4a3520" stroke-width="{f(1.4 * s)}" '
                     f'stroke-dasharray="{f(3 * s)} {f(1.2 * s)}"/>')
        elif kind == "plaza":
            fill = "url(#cobble)" if B["wall"] == "stein" else "url(#planks)"
            o.append(f'<path d="{d}" fill="{fill}" stroke="{C["street_edge"]}" stroke-width="{f(1.2 * s)}"/>')
        elif kind == "drill":
            o.append(f'<path d="{d}" fill="#c8b07e" stroke="{C["outline"]}" stroke-width="{f(1 * s)}"/>'
                     f'<path d="{d}" fill="none" stroke="#a88f5e" stroke-width="{f(0.8 * s)}" '
                     f'stroke-dasharray="{f(1 * s)} {f(5 * s)}" transform="translate({f(3 * s)},{f(3 * s)})"/>')
        elif kind == "cemetery":
            o.append(f'<path d="{d}" fill="{B["cemetery"]}" stroke="{C["outline"]}" stroke-width="{f(2.2 * s)}"/>'
                     f'<path d="{d}" fill="none" stroke="#9c958a" stroke-width="{f(1.2 * s)}" '
                     f'stroke-dasharray="{f(3 * s)} {f(2 * s)}"/>')
    if m["graves"]:
        gd = "".join(path_d(g) for g in m["graves"])
        o.append(f'<path d="{gd}" fill="#bdb7a8" stroke="#1e1e1a" stroke-width="{f(0.6 * s)}"/>')
    for x, y, r in m["fountains"]:   # Laufbrunnen: achteckiges Becken, Wasser, Brunnensäule
        oct_ = " ".join(f"{f(x + math.cos(math.pi / 8 + k * math.pi / 4) * r)},{f(y + math.sin(math.pi / 8 + k * math.pi / 4) * r)}"
                        for k in range(8))
        o.append(f'<polygon points="{oct_}" fill="#a29d90" stroke="{C["outline"]}" stroke-width="{f(1.2 * s)}"/>'
                 f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r * 0.7)}" fill="{B["river"]}" stroke="#6d695e" stroke-width="{f(0.6 * s)}"/>'
                 f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r * 0.45)}" fill="none" stroke="#e8f2f4" stroke-opacity="0.6" stroke-width="{f(0.6 * s)}"/>'
                 f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r * 0.2)}" fill="#d9d4c6" stroke="{C["outline"]}" stroke-width="{f(0.6 * s)}"/>')
    for x, y, r in m["wells"]:       # Ziehbrunnen: Steinring, dunkles Wasser, Holzbalken mit Kurbel
        o.append(f'<circle cx="{f(x + 1 * s)}" cy="{f(y + 1.3 * s)}" r="{f(r)}" fill="#000" fill-opacity="0.35"/>'
                 f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r)}" fill="#9a958a" stroke="{C["outline"]}" stroke-width="{f(1 * s)}"/>'
                 f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r * 0.55)}" fill="#1f3a44"/>'
                 f'<path d="M{f(x - r * 1.25)},{f(y)}H{f(x + r * 1.25)}" stroke="#5a3f28" stroke-width="{f(1.3 * s)}"/>'
                 f'<circle cx="{f(x - r * 1.25)}" cy="{f(y)}" r="{f(0.8 * s)}" fill="#3a2a1a"/>'
                 f'<circle cx="{f(x + r * 1.25)}" cy="{f(y)}" r="{f(0.8 * s)}" fill="#3a2a1a"/>')
    if m["stalls"]:                  # Wochenmarkt: Stände mit gestreifter Plane und Schatten
        sil = "".join(path_d(st["poly"]) for st in m["stalls"])
        o.append(shadow_layer(f'<path d="{sil}"/>', 1.5 * s, 1.8 * s, 0.45, s))
        for st in m["stalls"]:
            c1, c2 = st["colors"]
            pts = list(st["poly"].exterior.coords)[:-1]
            u, v = np.array(st["u"]), np.array(st["v"])
            p0 = np.array(pts[0])
            w = vlen(np.array(pts[1]) - p0)
            dd = vlen(np.array(pts[3]) - p0)
            xy = lambda q: f"{f(q[0])},{f(q[1])}"
            stripes = "".join(f"M{xy(p0 + u * (w * k / 6))}L{xy(p0 + u * (w * k / 6) + v * dd)}" for k in (1, 3, 5))
            o.append(f'<path d="{path_d(st["poly"])}" fill="{c1}"/>'
                     f'<path d="{stripes}" stroke="{c2}" stroke-width="{f(w / 6)}"/>'
                     f'<path d="M{xy(p0 + v * dd / 2)}L{xy(p0 + u * w + v * dd / 2)}" stroke="#000" stroke-opacity="0.35" stroke-width="{f(0.6 * s)}"/>'
                     f'<path d="{path_d(st["poly"])}" fill="none" stroke="{C["outline"]}" stroke-width="{f(0.8 * s)}"/>')
    if m["terrace_walls"]:
        tw = "".join(line_d(ln) for ln in m["terrace_walls"])
        o.append(f'<path d="{tw}" fill="none" stroke="#000" stroke-opacity="0.35" stroke-width="{f(9 * s)}" '
                 f'filter="url(#softblur)" transform="translate(0,{f(3 * s)})"/>'
                 f'<path d="{tw}" fill="none" stroke="#2f2c28" stroke-width="{f(6 * s)}" stroke-linecap="round"/>'
                 f'<path d="{tw}" fill="none" stroke="#b3ac9c" stroke-width="{f(3.2 * s)}" stroke-linecap="round" '
                 f'transform="translate(0,{f(-1.4 * s)})"/>'
                 f'<path d="{tw}" fill="none" stroke="#6f6a5f" stroke-width="{f(3.2 * s)}" '
                 f'stroke-dasharray="{f(0.8 * s)} {f(4 * s)}" transform="translate(0,{f(-1.4 * s)})"/>')
    for seg, w in m["stairs"]:
        d = line_d(seg)
        o.append(f'<path d="{d}" fill="none" stroke="#4a4740" stroke-width="{f(w + 1 * s)}"/>'
                 f'<path d="{d}" fill="none" stroke="#d2cdc0" stroke-width="{f(w - 1.5 * s)}" '
                 f'stroke-dasharray="{f(1.3 * s)} {f(1.5 * s)}"/>')
    for ln in m["paths"]:
        d = line_d(ln)
        o.append(f'<path d="{d}" fill="none" stroke="{C["road_edge"]}" stroke-opacity="0.6" stroke-width="{f(7 * s)}" '
                 f'stroke-linecap="round"/><path d="{d}" fill="none" stroke="{B["road"]}" stroke-width="{f(5 * s)}" '
                 f'stroke-linecap="round"/>')
    # Stege, Schiffe, Brücken
    for pier in m["piers"]:
        o.append(f'<path d="{path_d(pier)}" fill="#7a5a3c" stroke="{C["outline"]}" stroke-width="{f(1 * s)}"/>')
    o.append('<g filter="url(#shadow)">' + "".join(ship_svg(sh, s) for sh in m["ships"]) + "</g>")
    lamps = []
    if m["bridges"]:
        # Kontur und Brüstung nur über dem Wasser (enden am Ufer wie Widerlager), die Fahrbahn blendet an Land
        # weich in Gasse, Platz oder Landstraße aus statt als eckiges Brett darauf zu liegen
        wet = m["water"]
        o.append(f'<clipPath id="bridgeWet"><path d="{path_d(wet.buffer(1.5 * s))}"/></clipPath>'
                 f'<filter id="bridgeSoft" x="-5%" y="-5%" width="110%" height="110%">'
                 f'<feGaussianBlur stdDeviation="{f(3 * s)}"/></filter>'
                 f'<mask id="bridgeFade" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{W}">'
                 f'<path d="{path_d(wet.buffer(5 * s))}" fill="#fff" filter="url(#bridgeSoft)"/></mask>')
    for ln, w in m["bridges"]:   # an Land ein kurzes Stück Weg bis zum Platz bzw. zur Straße (schließt den Uferstreifen)
        dry = ln.difference(m["water"].buffer(1 * s))
        if not dry.is_empty:
            col = B["street"] if m["city_land"].buffer(5 * s).contains(dry.centroid) else B["road"]
            o.append(f'<path d="{line_d(dry)}" stroke="{col}" stroke-width="{f(w * 0.8)}" stroke-linecap="round" fill="none"/>')
    for ln, w in m["bridges"]:
        d = line_d(ln)
        o.append(f'<g clip-path="url(#bridgeWet)">'
                 f'<path d="{d}" stroke="{C["outline"]}" stroke-width="{f(w + 4 * s)}" fill="none"/>'   # Kontur
                 f'<path d="{d}" stroke="#9d9482" stroke-width="{f(w)}" fill="none"/></g>'               # Brüstung
                 f'<path d="{d}" stroke="#c2b9a3" stroke-width="{f(max(w - 4.5 * s, w * 0.5))}" fill="none" '
                 f'mask="url(#bridgeFade)"/>')                                                           # Fahrbahn
        # Brückenlaternen abwechselnd an beiden Geländern, nicht in der Brückenmitte
        n = max(2, int(ln.length / (45 * s)))
        for k in range(n + 1):
            p = ln.interpolate(k / n, normalized=True)
            q = ln.interpolate(min(ln.length, ln.project(p) + 2))
            if q.distance(p) < 1e-6:
                q, p0 = p, ln.interpolate(max(0, ln.project(p) - 2))
                tx, ty = q.x - p0.x, q.y - p0.y
            else:
                tx, ty = q.x - p.x, q.y - p.y
            nl = math.hypot(tx, ty) or 1
            side = 1 if k % 2 else -1
            off = w / 2 - 1.2 * s
            lamps.append((p.x - ty / nl * off * side, p.y + tx / nl * off * side))
    # Festungen: dicke Mauer, gepflasterter Hof
    for ft in m["forts"]:
        d = path_d(ft["fort"])
        o.append(f'<g filter="url(#shadow)"><path d="{d}" fill="#8f8a7c" stroke="{C["wall"]}" stroke-width="{f(2.5 * s)}"/></g>'
                 f'<path d="{path_d(ft["fort"].buffer(-7 * s, join_style="mitre"))}" fill="url(#cobble)" '
                 f'stroke="{C["wall"]}" stroke-width="{f(1.5 * s)}"/>')
    if m["rocks"]:
        rk = "".join(f'<ellipse cx="{f(x)}" cy="{f(y)}" rx="{f(rx)}" ry="{f(ry)}" transform="rotate({f(a)} {f(x)} {f(y)})"/>'
                     for x, y, rx, ry, a in m["rocks"])
        hl = "".join(f'<ellipse cx="{f(x - rx * 0.25)}" cy="{f(y - ry * 0.3)}" rx="{f(rx * 0.45)}" ry="{f(ry * 0.35)}"/>'
                     for x, y, rx, ry, a in m["rocks"])
        o.append(shadow_layer(rk, 2 * s, 2.5 * s, 0.5, s) +
                 f'<g fill="#8b877c" stroke="#2e2c27" stroke-width="{f(1 * s)}">{rk}</g>'
                 f'<g fill="#ffffff" fill-opacity="0.35">{hl}</g>')
    # Gebäude
    stilts_svg(o, m)
    # Schattenwurf als versetzte Silhouette (statt teurem feDropShadow über die ganze Karte)
    sil = "".join(path_d(b["poly"]) for b in m["suburbs"] + m["buildings"])
    o.append(shadow_layer(f'<path d="{sil}"/>', 2 * s, 2.5 * s, 0.5, s))
    o.append('<g>')
    detail = m["cfg"]["ausgabe"].get("dachdetails", True)
    biome_name = m["cfg"]["gelaende"]["biotop"]
    lx, ly = -0.6, -0.8                       # Licht von oben links (Bildschirm), ins interne System drehen
    ra = math.radians(-m["rot"])
    to_light = np.array([lx * math.cos(ra) - ly * math.sin(ra), lx * math.sin(ra) + ly * math.cos(ra)])
    roof_rng = random.Random(m["cfg"]["seed"] + 7)
    for b in m["suburbs"] + m["buildings"]:
        flat = B["flat_roofs"] and not b.get("landmark")
        svg = None
        if b.get("form") == "block":
            svg = block_svg(b, s, to_light, B["flat_roofs"])
        elif detail and not flat and b.get("shade") is not None:
            material = material_for(b["color"], biome_name, B["thatch"])
            if b.get("poor") and material not in ("schnee", "reet"):
                material = "flicken"
            svg = detailed_roof(b, s, roof_rng, material, to_light, C["outline"])
        o.append(svg or building_svg(b, s, B["flat_roofs"]))
    o.append("</g>")
    mills_svg(o, m)
    mines_svg(o, m)
    forge_glow = []
    for b in m["buildings"]:
        if b.get("forge"):
            c = b["poly"].representative_point()
            forge_glow.append((c.x, c.y))
    if forge_glow:
        o.append(glow_dots([(x, y, 9 * s) for x, y in forge_glow], "glowForge", s))
        o.append("".join(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(2.4 * s)}" fill="#ffc25a" stroke="#2a1608" '
                         f'stroke-width="{f(0.7 * s)}"/>' for x, y in forge_glow))
    if m["great_gate"]:
        great_gate_svg(o, m)
    # Mauer, Türme, Tore
    wd = "".join(line_d(ln) for ln in m["wall"])
    if wd and B["wall"] == "palisade":
        o.append(f'<path d="{wd}" fill="none" stroke="#2b2014" stroke-width="{f(8 * s)}" stroke-linejoin="round"/>'
                 f'<path d="{wd}" fill="none" stroke="#7a5a3a" stroke-width="{f(5.5 * s)}" '
                 f'stroke-dasharray="{f(2.6 * s)} {f(1 * s)}"/>')
    elif wd and B["wall"] == "lehm":
        o.append(f'<path d="{wd}" fill="none" stroke="#5e4429" stroke-width="{f(10 * s)}" stroke-linejoin="round"/>'
                 f'<path d="{wd}" fill="none" stroke="#c9a46a" stroke-width="{f(6 * s)}" stroke-linejoin="round"/>'
                 f'<path d="{wd}" fill="none" stroke="#8a6a44" stroke-width="{f(6 * s)}" '
                 f'stroke-dasharray="{f(3 * s)} {f(3 * s)}"/>')
    elif wd:
        o.append(f'<path d="{wd}" fill="none" stroke="{C["wall"]}" stroke-width="{f(9 * s)}" stroke-linejoin="round"/>'
                 f'<path d="{wd}" fill="none" stroke="{C["wall_top"]}" stroke-width="{f(4.5 * s)}" stroke-linejoin="round"/>'
                 f'<path d="{wd}" fill="none" stroke="{C["wall"]}" stroke-width="{f(4.5 * s)}" '
                 f'stroke-dasharray="{f(2.5 * s)} {f(3.5 * s)}"/>')
    glow = [(x, y, 13 * s) for x, y, _ in m["towers"]] + [(x, y, 20 * s) for x, y, _ in m["gates"]] + \
           [(x, y, 8 * s) for x, y in lamps]
    o.append(glow_dots(glow, "glowWarm", s))
    for x, y in lamps:
        o.append(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(2.6 * s)}" fill="#ffd27a" stroke="{C["outline"]}" stroke-width="{f(0.7 * s)}"/>')
    tower_color = B["tower"]
    for x, y, a in m["towers"]:
        o.append(tower_svg(x, y, a, 17 * s, s, tower_color))
    for x, y, a in m["gates"]:
        o.append(f'<g transform="translate({f(x)},{f(y)}) rotate({f(a)})">'
                 f'<rect x="{f(-17 * s)}" y="{f(-11 * s)}" width="{f(34 * s)}" height="{f(22 * s)}" fill="#b2493a" '
                 f'stroke="{C["outline"]}" stroke-width="{f(1.5 * s)}"/>'
                 f'<rect x="{f(-6 * s)}" y="{f(-11 * s)}" width="{f(12 * s)}" height="{f(22 * s)}" fill="#7c3328"/></g>')
    # Bäume
    trees = list(m["trees"]) + [(x, y, r, rng.choice(B["trees"])) for x, y, r in m["yard_trees"]]
    trees.sort(key=lambda t: t[1])
    parts = []
    shadows = []
    for x, y, r, c, *fixed in trees:
        kind = fixed[0] if fixed else tree_kind(rng, r, s, B["tree_kinds"])
        if kind == "alt":
            r *= rng.uniform(1.5, 1.9)
        r *= rng.uniform(0.85, 1.15)
        shadows.append(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r * (0.75 if kind in ("tot", "palme") else 0.95))}"/>')
        parts.append(tree_svg(x, y, r, c, s, rng, kind))
    o.append(shadow_layer("".join(shadows), 3 * s, 3.5 * s, 0.45, s))
    o.append("<g>" + "".join(parts) + "</g>")
    # Werft: der Bug des Schiffs im Helling liegt über allem (Schatten, Lichtschein, Bäume); nur das Heck bleibt in
    # der Halle verborgen (Zuschnitt: ganze Karte ohne die Halle)
    for i, sh in enumerate(x for x in m["ships"] if x.get("slip")):
        frame = f"M{f(-W)},{f(-W)}H{f(2 * W)}V{f(2 * W)}H{f(-W)}Z"
        o.append(f'<clipPath id="slipBow{i}"><path clip-rule="evenodd" d="{frame}{path_d(sh["hall"])}"/></clipPath>'
                 f'<g clip-path="url(#slipBow{i})">{ship_svg(sh, s)}</g>')
    if m["cfg"]["ausgabe"].get("nacht"):
        night_svg(o, m, lamps, forge_glow)
    o.append("</g>")  # Ende Drehung

    # Beschriftung (immer aufrecht), Schrift in Kartengröße
    s = m.get("st", s)
    o.append(f'<rect width="{W}" height="{W}" fill="url(#vignette)"/>')
    title_size = 78 * s
    taken = [(W - 60 * s - text_width(m["name"], title_size), W - 70 * s - title_size, W - 60 * s, W - 50 * s)]
    rows = legend_rows(m["legend"]) if m["cfg"]["ausgabe"].get("legende") else []
    lh = 26 * s
    kw = max([52 * s] + [len(k) * 10.5 * s + 6 * s for k, _ in rows])   # Spalte der Kürzel
    bw, bh = 278 * s + kw, (len(rows) + 1) * lh + 20 * s
    x0, y0 = 40 * s, W - 40 * s - bh
    if rows and m.get("zoom", 1) > 1:   # vergrößerter Ausschnitt: die Legende in die Ecke mit der wenigsten Stadt
        city = shapely.affinity.rotate(m["city_land"].union(m["shape"]), m["rot"], origin=(W / 2, W / 2))
        corners = [(40 * s, W - 40 * s - bh), (40 * s, 40 * s), (W - 40 * s - bw, 40 * s)]
        x0, y0 = min(corners, key=lambda c: city.intersection(box(c[0], c[1], c[0] + bw, c[1] + bh)).area)
    if rows:
        taken.append((x0, y0, x0 + bw, y0 + bh))
    for sh in m["ships"]:   # das Schiff im Helling der Werft bleibt frei (der Name steht neben der Halle)
        if sh.get("slip"):
            hull = ship_footprint(sh["x"], sh["y"], sh["len"], sh["wid"], sh["angle"])
            xs, ys = zip(*(rot_xy(m, x, y) for x, y in hull.exterior.coords))
            taken.append((min(xs), min(ys), max(xs), max(ys)))
    # jede Art von Beschriftung in einer eigenen Gruppe: lässt sich in der interaktiven Karte (und z.B. in Inkscape)
    # einzeln ausblenden; split_labels() trennt sie von der übrigen Karte
    # jede einzelne Beschriftung trägt einen Schlüssel (data-key), über den sie von Hand verschoben werden kann
    offsets = m["cfg"].get("beschriftung") or {}
    groups = {"viertel": [], "orte": []}
    used = {}
    m["label_keys"] = []           # (data-key, Beschriftung) für die Ortsliste des Web-Pakets
    for x, y, text, size, halo, kind, lb in place_labels(m, taken):
        key = f"{kind}:{text}"
        used[key] = used.get(key, 0) + 1
        if used[key] > 1:          # gleicher Text mehrfach: zweite Beschriftung heißt "orte:Laden#2"
            key += f"#{used[key]}"
        m["label_keys"].append((key, lb))
        groups[kind].append(movable(key, offsets, W, text_el(x, y, text, size, s, halo=halo)))
    o.append(LABELS_START)
    for kind in ("viertel", "orte"):
        o.append(f'<g id="b-{kind}">{"".join(groups[kind])}</g>')
    title = text_el(W - 60 * s, W - 70 * s, m["name"], title_size, s, anchor="end", halo=7 * s)
    o.append(f'<g id="b-titel">{movable("titel", offsets, W, title)}</g>')
    o.append('<g id="b-legende">')
    if rows:
        legend = [f'<rect x="{f(x0)}" y="{f(y0)}" width="{f(bw)}" height="{f(bh)}" rx="{f(6 * s)}" '
                  f'fill="#1d2118" fill-opacity="0.72" stroke="#c9b98f" stroke-width="{f(1.5 * s)}"/>',
                  text_el(x0 + 18 * s, y0 + lh + 2 * s, "Legende", 22 * s, s, anchor="start", halo=0.01)]
        for i, (k, name) in enumerate(rows):
            y = y0 + lh * (i + 2) + 4 * s
            legend.append(f'<text x="{f(x0 + 18 * s)}" y="{f(y)}" font-family="{FONT}" font-size="{f(18 * s)}" '
                          f'fill="{C["text"]}" font-weight="bold">{escape(k)}</text>'
                          f'<text x="{f(x0 + 18 * s + kw)}" y="{f(y)}" font-family="{FONT}" font-size="{f(18 * s)}" '
                          f'fill="{C["text"]}">{escape(name)}</text>')
        o.append(movable("legende", offsets, W, "".join(legend)))
    o.append("</g>" + LABELS_END)
    grid = int(m["cfg"]["ausgabe"].get("raster") or 0)
    if grid > 0:
        d = "".join(f"M{k},0V{W}M0,{k}H{W}" for k in range(grid, W, grid))
        o.append(f'{RASTER_START}<path d="{d}" stroke="#000" stroke-opacity="0.25" stroke-width="1" fill="none"/></g>')
    tex = {k: fut.result() for k, fut in m.pop("_tex", {}).items()}
    if tex:   # jede Textur nur einmal einbetten, Verwendungen verweisen per <use> darauf
        o.append("<defs>" + "".join(
            f'<image id="tex_{k}" href="{u}" x="0" y="0" width="{W}" height="{W}" preserveAspectRatio="none" '
            f'image-rendering="optimizeSpeed"/>'
            for k, u in tex.items()) + "</defs>")
    o.append("</svg>")
    return "".join(o)


LABELS_START = '<g id="beschriftung">'
RASTER_START = '<g id="raster">'
LABELS_END = "</g><!--/beschriftung-->"


def label_offset(key, offsets, W):
    """Verschiebung einer Beschriftung in Pixeln; gespeichert wird sie in Prozent der Kartenbreite,
    damit sie auch bei anderer Bildgröße passt."""
    dx, dy = offsets.get(key) or (0, 0)
    return float(dx) * W / 100, float(dy) * W / 100


def movable(key, offsets, W, body):
    dx, dy = label_offset(key, offsets, W)
    return f'<g data-key={quoteattr(key)} transform="translate({f(dx)},{f(dy)})">{body}</g>'


_MOVABLE = re.compile(r'<g data-key=("[^"]*"|\'[^\']*\') transform="translate\([^)]*\)">')


def move_labels(svg, offsets, W):
    """Setzt die Verschiebungen in einer fertigen Karte neu, ohne sie neu zu zeichnen."""
    def sub(mt):
        dx, dy = label_offset(unescape(mt.group(1)[1:-1]), offsets, W)
        return f'<g data-key={mt.group(1)} transform="translate({f(dx)},{f(dy)})">'
    return _MOVABLE.sub(sub, svg)


def split_labels(svg):
    """Trennt eine Karte in (Karte ohne Beschriftung, Beschriftungsgruppe)."""
    i = svg.index(LABELS_START)
    j = svg.index(LABELS_END, i) + len(LABELS_END)
    return svg[:i] + svg[j:], svg[i:j]


def strip_grid(svg):
    """Entfernt das Raster (ausgabe.raster) aus einer fertigen Karte."""
    i = svg.find(RASTER_START)
    return svg if i < 0 else svg[:i] + svg[svg.index("</g>", i) + 4:]


def to_png(svg, zoom=None):
    """SVG -> PNG; zoom=0.5 rendert in halber Kantenlänge (etwa viermal schneller, für Vorschauen)."""
    import resvg_py
    fonts = [str(FONT_FILE)] if FONT_FILE.exists() else None
    return bytes(resvg_py.svg_to_bytes(svg_string=svg, zoom=zoom, font_files=fonts))


_FONT_CSS = None


def font_face_css():
    """@font-face mit eingebetteter Schrift, damit die SVG-Datei überall gleich aussieht."""
    global _FONT_CSS
    if _FONT_CSS is None:
        import base64
        _FONT_CSS = ""
        if FONT_FILE.exists():
            data = base64.b64encode(FONT_FILE.read_bytes()).decode()
            _FONT_CSS = ("@font-face{font-family:'EB Garamond';font-weight:400 800;"
                         f"src:url(data:font/ttf;base64,{data}) format('truetype');}}")
    return _FONT_CSS


def to_pdf(png_bytes, path, dpi=150):
    from PIL import Image
    Image.open(io.BytesIO(png_bytes)).convert("RGB").save(path, "PDF", resolution=dpi)
