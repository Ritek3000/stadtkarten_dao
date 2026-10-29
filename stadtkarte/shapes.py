"""Hausgrundrisse aus festen geometrischen Formen.

Erlaubt sind: Quadrat, Rechteck, Raute, Fünfeck, Sechseck, L-Form, Achteck; das Kreuz ist Gotteshäusern
vorbehalten (siehe cross_in_rect).
Jede Form wird im Achsensystem des Grundstücks (kleinstes umschließendes Rechteck) definiert und so weit
verkleinert, bis sie vollständig ins Grundstück passt. Normal sind Rechtecke/Quadrate; ungewöhnliche
Grundstücke (Ecken, Restflächen) bekommen die Form, die ihre Fläche am besten nutzt; ab und zu entsteht
zur Abwechslung ein Sonderbau (Achteck, Sechseck, Fünfeck, Raute).
"""
import numpy as np
import shapely
from shapely.geometry import Polygon

from .geo import axes, fit_rect, min_width, vlen

SPECIAL = ("achteck", "sechseck", "fuenfeck", "raute")


def _unit_shapes(rng, aspect):
    """Formen im Einheitsquadrat (x entlang der langen, y entlang der kurzen Achse): Liste (Name, Punkte, Armbreite)."""
    out = []
    # L-Form: eine Ecke fehlt (vier Ausrichtungen)
    cx, cy = rng.uniform(0.4, 0.55), rng.uniform(0.4, 0.55)
    base = [(0, 0), (1, 0), (1, 1 - cy), (1 - cx, 1 - cy), (1 - cx, 1), (0, 1)]
    for mx in (False, True):
        for my in (False, True):
            out.append(("l", [((1 - x) if mx else x, (1 - y) if my else y) for x, y in base], min(1 - cx, 1 - cy)))
    # Fünfeck als Giebelhaus (zwei Ausrichtungen)
    g = rng.uniform(0.6, 0.72)
    out.append(("fuenfeck", [(0, 0), (1, 0), (1, g), (0.5, 1), (0, g)], None))
    out.append(("fuenfeck", [(0, 1), (1, 1), (1, 1 - g), (0.5, 0), (0, 1 - g)], None))
    # Sechseck: an den Enden zugespitzt; Achteck: Ecken abgeschrägt (Abschrägung in echten Längen gleich)
    c = 0.22 / max(aspect, 1)
    out.append(("sechseck", [(c, 0), (1 - c, 0), (1, 0.5), (1 - c, 1), (c, 1), (0, 0.5)], None))
    cy_, cx_ = 0.29, 0.29 / max(aspect, 1)
    out.append(("achteck", [(cx_, 0), (1 - cx_, 0), (1, cy_), (1, 1 - cy_), (1 - cx_, 1), (cx_, 1), (0, 1 - cy_), (0, cy_)], None))
    # Raute aus den Seitenmitten
    out.append(("raute", [(0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5)], None))
    return out


def _fit(poly, strict, o, u, v, l1, l2, pts):
    """Form ins Grundstück skalieren (Binärsuche um die Mitte); liefert (Polygon, Faktor) oder (None, 0)."""
    c = o + u * l1 / 2 + v * l2 / 2
    world = np.array([o + u * (x * l1) + v * (y * l2) for x, y in pts])
    lo, hi, best = 0.35, 1.0, None
    full = Polygon(world)
    if strict.contains(full):
        return full, 1.0
    for _ in range(9):
        mid = (lo + hi) / 2
        cand = Polygon(c + (world - c) * mid)
        if strict.contains(cand):
            best, lo = (cand, mid), mid
        else:
            hi = mid
    return best if best else (None, 0.0)


def house_shape(piece, rng, min_w, max_ratio, special_chance=0.12):
    """Wählt für ein Grundstück eine erlaubte Hausform. Liefert (Polygon, Formname) oder (None, None)."""
    ax = axes(piece)
    if ax is None:
        return None, None
    o, e1, e2 = ax
    l1, l2 = vlen(e1), vlen(e2)
    if l2 < min_w:
        return None, None
    u, v = e1 / l1, e2 / l2
    aspect = l1 / l2
    rect = fit_rect(piece, min_w, max_ratio)
    fill = piece.area / (l1 * l2)
    want_special = rng.random() < special_chance and aspect < 1.8
    if rect is not None and fill > 0.88 and not want_special:
        if rng.random() < 0.12:            # ab und zu ein Winkelbau: eine Ecke des Rechtecks bleibt frei
            ell = _l_from_rect(rect, rng, min_w)
            if ell is not None:
                return ell, "l"
        return _square_up(rect), _rect_name(rect)

    strict = piece.buffer(0.15)
    shapely.prepare(strict)
    cands = []
    for name, pts, arm in _unit_shapes(rng, aspect):
        if not want_special and name in SPECIAL and name != "fuenfeck":   # Sonderbauten nur auf Wunsch
            continue
        shp, k = _fit(piece, strict, o, u, v, l1, l2, pts)
        if shp is None or min_width(shp) < min_w:
            continue
        if arm is not None and arm * l2 * k < min_w * 0.75:   # Flügel von L und Kreuz nicht zu schmal
            continue
        cands.append((name, shp))
    if want_special:
        special = [c for c in cands if c[0] in SPECIAL]
        if special:
            name, shp = special[rng.randrange(len(special))]
            return shp, name
    # sonst: Rechteck bevorzugen, andere Formen nur, wenn sie das Grundstück deutlich besser nutzen
    best_name, best = (_rect_name(rect), _square_up(rect)) if rect is not None else (None, None)
    best_area = best.area * 1.15 if best is not None else 0.0
    for name, shp in cands:
        if name in ("l", "fuenfeck") and shp.area > best_area:
            best_name, best, best_area = name, shp, shp.area
    return best, best_name


def _rect_name(rect):
    ax = axes(rect)
    l1, l2 = vlen(ax[1]), vlen(ax[2])
    return "quadrat" if l1 / max(l2, 1e-6) < 1.2 else "rechteck"


def _square_up(rect):
    """Fast quadratische Rechtecke werden echte Quadrate (lange Seite mittig gekürzt)."""
    o, e1, e2 = axes(rect)
    l1, l2 = vlen(e1), vlen(e2)
    if l1 / max(l2, 1e-6) >= 1.2:
        return rect
    cut = (l1 - l2) / 2
    u = e1 / l1
    a, b = o + u * cut, o + e1 - u * cut
    return Polygon([a, b, b + e2, a + e2])


def _l_from_rect(rect, rng, min_w):
    """L-Form aus einem Rechteck: eine zufällige Ecke wird ausgespart, beide Flügel bleiben >= min_w."""
    o, e1, e2 = axes(rect)
    l1, l2 = vlen(e1), vlen(e2)
    cx, cy = rng.uniform(0.35, 0.5), rng.uniform(0.35, 0.5)
    if l1 * (1 - cx) < min_w or l2 * (1 - cy) < min_w or l2 < 1.6 * min_w:
        return None
    u, v = e1 / l1, e2 / l2
    pts = [(0, 0), (1, 0), (1, 1 - cy), (1 - cx, 1 - cy), (1 - cx, 1), (0, 1)]
    mx, my = rng.random() < 0.5, rng.random() < 0.5
    pts = [((1 - x) if mx else x, (1 - y) if my else y) for x, y in pts]
    return Polygon([o + u * (x * l1) + v * (y * l2) for x, y in pts])


def cross_in_rect(rect, arm=0.42):
    """Kreuzförmiger Grundriss für Gotteshäuser: Längsschiff entlang der langen Achse, Querschiff bei 1/3
    (Kirchengrundriss); bei fast quadratischem Rechteck ein gleicharmiges Kreuz."""
    o, e1, e2 = axes(rect)
    l1, l2 = vlen(e1), vlen(e2)
    u, v = e1 / l1, e2 / l2
    wy = (1 - arm) / 2                       # Breite des Längsschiffs (quer zur langen Achse)
    wx = arm * l2 / l1                       # Breite des Querschiffs, gleich breit wie das Längsschiff
    mid = 0.5 if l1 / l2 < 1.25 else 0.35    # Lage des Querschiffs
    x0, x1 = mid - wx / 2, mid + wx / 2
    pts = [(0, wy), (x0, wy), (x0, 0), (x1, 0), (x1, wy), (1, wy), (1, 1 - wy), (x1, 1 - wy), (x1, 1),
           (x0, 1), (x0, 1 - wy), (0, 1 - wy)]
    return Polygon([o + u * (x * l1) + v * (y * l2) for x, y in pts])
