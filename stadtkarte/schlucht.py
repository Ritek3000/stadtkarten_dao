"""Klamm als echte Schlucht: aus der Klammfläche entsteht ein Tiefenfeld (Rand oben, Grund unten). Wie beim Gebirge
(gebirge.py) kommt das Licht aus Nordwesten: die Wand, die zum Licht schaut, ist hell, die gegenüberliegende liegt im
Schatten, der Grund ist dunkel. Ergebnis: ein Bild, das über der Klammfläche liegt (Rand und Wildbach zeichnet
render.py als Vektor darüber).

Abwechslung statt Maserung: Wandbreite und Wandart wechseln im Verlauf und von Wand zu Wand (gestufte Wand mit
Absätzen, glatte steile Wand, flacherer Geröllhang), die Absätze wandern und ihre Kanten sind unterbrochen. Wo die
Klamm breiter ist, bleibt zwischen den Wänden ein flacher Grund mit helleren Schotterbänken. Flussabwärts (hinter
der Stadt, wo das Tal beginnt) werden die Wände glatt niedriger und das Bild blendet aus: die Klamm läuft aus und
geht in einen kleinen Bach über.

Die Klamm ist schmal; ein halb aufgelöstes Bild wirkt hier grob. Deshalb wird in voller Auflösung gerechnet, aber nur im
Rechteck um die Klamm."""
import base64
import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .gebirge import _blur, _smooth
from .geo import vlen3
from .noise import _fbm, _hex_rgb


def _mask(shape, off, rings):
    """Klammfläche als 8-Bit-Maske im Ausschnitt shape = (Höhe, Breite) mit Ursprung off."""
    img = Image.new("L", (shape[1], shape[0]), 0)
    d = ImageDraw.Draw(img)
    for ext, holes in rings:
        d.polygon([(x - off[0], y - off[1]) for x, y in ext], fill=255)
        for h in holes:
            d.polygon([(x - off[0], y - off[1]) for x, y in h], fill=0)
    return img


def fade(y, y_a, y_b):
    """1 in der Klamm (y <= y_a), 0 im Bach (y >= y_b), dazwischen glatt (y wächst flussabwärts)."""
    t = np.clip((y - y_a) / max(1e-6, y_b - y_a), 0, 1)
    return 1 - t * t * (3 - 2 * t)


def image(W, s, data):
    """data: river (Klammfläche als Ringe), light (Licht-x, Licht-y), Farben rock_col, rock_dark, fade (y_a, y_b) oder
    None. Liefert eine Data-URI (Bild in Kartengröße, außerhalb der Klamm durchsichtig)."""
    xs = [x for ext, _ in data["river"] for x, _ in ext]
    ys = [y for ext, _ in data["river"] for _, y in ext]
    out = np.zeros((W, W, 4), np.uint8)
    if xs:
        pad = int(10 * s)
        x0, y0 = max(0, int(min(xs)) - pad), max(0, int(min(ys)) - pad)
        x1, y1 = min(W, int(max(xs)) + pad + 1), min(W, int(max(ys)) + pad + 1)
        out[y0:y1, x0:x1] = _relief(x1 - x0, y1 - y0, (x0, y0), s, data)
    buf = io.BytesIO()
    Image.fromarray(out, "RGBA").save(buf, "WEBP", quality=90, alpha_quality=85, method=0)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def _relief(w, h, off, s, data):
    mask_img = _mask((h, w), off, data["river"])
    mask = np.asarray(mask_img, np.float32) / 255
    # Abstand zum Rand im Inneren: wiederholtes Erodieren (Schachbrettabstand) in halber Auflösung (4x schneller; der
    # Abstand wird ohnehin weichgezeichnet), dann glatt auf volle Größe gebracht
    hh, hw = max(2, h // 2), max(2, w // 2)
    cur = mask_img.resize((hw, hh), Image.BOX).point(lambda v: 255 if v > 127 else 0)
    dist_h = np.zeros((hh, hw), np.float32)
    for _ in range(int(min(60, max(6, 40 * s)))):
        cur = cur.filter(ImageFilter.MinFilter(3))
        dist_h += (np.asarray(cur) > 127)
    dist = np.asarray(Image.fromarray(dist_h * 2, "F").resize((w, h), Image.BICUBIC)) * (mask > 0.5)
    dist = _blur(dist, 1.3)
    size = max(h, w)

    def field(period, seed, octaves=3):   # Rauschen mit Mittel 0 und Streuung 1 in Kartengröße (fest je Karte)
        n = _fbm(size, period * s, octaves, seed, False, warp=0.3)[:h, :w]
        return ((n - n.mean()) / (n.std() + 1e-6)).astype(np.float32)
    n_width, n_kind, n_wob, n_gap, n_bar = field(75, 331), field(170, 332), field(42, 333), field(30, 334, 2), field(55, 335)
    # Wandbreite und Wandart wechseln im Verlauf und von Wand zu Wand (die Felder sind schmaler als die Klamm lang)
    ww = np.maximum(7 * s, (16 + 8 * np.tanh(n_width)) * s)
    kind = 0.5 + 0.5 * np.tanh(n_kind)
    w_scree = _smooth(kind, 0.62, 0.88)                          # flacherer Geröllhang
    w_sheer = _smooth(kind, 0.30, 0.46) * (1 - w_scree)          # glatte steile Wand
    w_step = np.clip(1 - w_scree - w_sheer, 0, 1)                # Wand mit Absätzen
    t = np.clip(dist / ww, 0, 1)                                 # 0 am Rand .. 1 am Fuß der Wand
    zn_sheer = 1 - (1 - t) ** 2.4
    tw = np.clip(t + 0.11 * n_wob, 0, 1)                         # die Absätze wandern
    steps = 4.0
    band = np.floor(tw * steps)
    zn_step = np.clip((band + _smooth(tw * steps - band, 0.0, 0.5)) / steps, 0, 1)
    zn_scree = 0.8 * (1 - (1 - np.clip(dist / (ww * 1.7), 0, 1)) ** 1.6)
    zn = w_step * zn_step + w_sheer * zn_sheer + w_scree * zn_scree
    # flussabwärts werden die Wände glatt niedriger
    rows = off[1] + np.arange(h, dtype=np.float32)
    g = fade(rows, *data["fade"])[:, None] if data.get("fade") else np.ones((h, 1), np.float32)
    # Beleuchtung: Rand 0, Grund tief; Hangneigung aus dem Gefälle
    z = -zn * 15 * s * g
    gy, gx = np.gradient(z.astype(np.float64))
    lx, ly = data["light"]
    L = np.array([lx * 0.75, ly * 0.75, 0.7])
    L /= vlen3(L)   # nicht np.linalg.norm: OpenBLAS rundet je nach Prozessor anders
    lit = (-gx * L[0] - gy * L[1] + L[2]) / np.sqrt(gx * gx + gy * gy + 1)
    shade = np.clip((lit - L[2]) * 1.5, -1, 1).astype(np.float32)
    # Färbung: heller Fels am Rand, Wand, dunkler (aber nicht schwarzer) Grund; Geröllhänge heller und warm
    rock, dark = _hex_rgb(data["rock_col"]), _hex_rgb(data["rock_dark"])
    c_rim = np.clip(rock * 1.10 + 0.02, 0, 1)
    c_wall = rock * 0.62 + dark * 0.2
    c_floor = dark * 0.6 + np.array([0.00, 0.015, 0.03], np.float32)
    c_gravel = np.clip(rock * 0.80 + 0.02, 0, 1)
    t1 = _smooth(zn, 0.0, 0.55)[..., None]
    t2 = _smooth(zn, 0.45, 1.0)[..., None]
    wall = c_wall[None, None, :] * (1 - 0.55 * w_scree[..., None]) + np.clip(rock * 0.92, 0, 1)[None, None, :] * (0.55 * w_scree[..., None])
    col = (c_rim[None, None, :] * (1 - t1) + wall * t1) * (1 - t2) + c_floor[None, None, :] * t2
    # flacher Grund: am Fuß der Wände dunkel (Schatten), zur Mitte hin heller, dazu Fleckung und Schotterbänke; breite
    # Abschnitte der Klamm bekommen so einen abwechslungsreichen Grund statt einer großen dunklen Fläche
    wide = _smooth(dist - ww, 0.0, 34 * s)
    col = col * (0.82 + 0.5 * wide[..., None] * t2) * (1 + 0.10 * n_bar[..., None] * t2)
    bars = _smooth(n_bar, -0.1, 0.8) * _smooth(dist - ww, 2 * s, 12 * s)
    col = col * (1 - 0.75 * bars[..., None]) + c_gravel[None, None, :] * (0.75 * bars[..., None])
    # feine Körnung in halber Auflösung erzeugen (Pixel für Pixel wäre teuer) und hochskalieren
    grit = _fbm(max(hh, hw), 5.5 * s, 3, 322, False)[:hh, :hw]
    grit = np.asarray(Image.fromarray(grit.astype(np.float32), "F").resize((w, h), Image.BICUBIC))
    col = col * (1 + 0.08 * ((grit - grit.mean()) / (grit.std() + 1e-6))[..., None])
    sun = np.array([1.0, 0.95, 0.82], np.float32)
    cool = np.array([0.60, 0.65, 0.78], np.float32)
    weak = (1 - 0.6 * _smooth(zn, 0.55, 1.0))[..., None]            # am Grund wirkt das Licht kaum noch
    col = col * (1 + 0.75 * np.clip(shade, 0, 1)[..., None] * weak * (sun[None, None, :] - 0.5))
    col = col * (1 - 0.62 * np.clip(-shade, 0, 1)[..., None] * (1 - cool[None, None, :] * 0.7))
    # flussabwärts geht der Grund ins Blau des Baches über und die Wände hellen auf (sonst wirkte das Ausblenden wie Ruß)
    away = (1 - g)[..., None]   # (Zeilen, 1, 1): 0 in der Klamm, 1 im Bach
    water_tone = np.array([0.20, 0.36, 0.44], np.float32)
    bank_tone = np.clip(rock * 0.95, 0, 1)
    col = col * (1 - 0.8 * away * t2) + water_tone[None, None, :] * (0.8 * away * t2)
    col = col * (1 - 0.5 * away * (1 - t2)) + bank_tone[None, None, :] * (0.5 * away * (1 - t2))
    # Kanten der Absätze als dünne dunkle Linien, nur an gestuften Wänden und immer wieder unterbrochen
    q = tw * steps
    gq = np.hypot(*np.gradient(q.astype(np.float64))) + 1e-4
    dd = np.abs(q - np.round(q)) / gq                              # Abstand zur nächsten Kante in Pixeln
    broken = _smooth(n_gap, -0.3, 0.5)                             # an manchen Stellen fehlt die Kante
    ledge = np.clip(1 - (dd - 0.4) / 0.9, 0, 1) * 0.40 * w_step * broken * (1 - _smooth(zn, 0.8, 1.0)) * _smooth(t, 0.06, 0.22) * g
    col = col * (1 - ledge[..., None]) + np.array([0.07, 0.06, 0.05], np.float32)[None, None, :] * ledge[..., None]
    img = np.empty((h, w, 4), np.uint8)
    img[..., :3] = np.clip(col * 255, 0, 255).astype(np.uint8)
    # auf die (genaue) Klammfläche zuschneiden (ein Pixel weiter, sonst bleibt ein Haarstrich); flussabwärts ausblenden
    alpha = np.asarray(mask_img.filter(ImageFilter.MaxFilter(3)), np.float32) * np.clip(g * 1.1, 0, 1)
    img[..., 3] = alpha.astype(np.uint8)
    return img
