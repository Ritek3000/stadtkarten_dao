"""Klamm als echte Schlucht: aus der Klammfläche entsteht ein Tiefenfeld (Rand oben, Grund unten) mit steilen Wänden und
Felsbändern. Wie beim Gebirge (gebirge.py) kommt das Licht aus Nordwesten: die Wand, die zum Licht schaut, ist hell, die
gegenüberliegende liegt im Schatten, der Grund ist dunkel. Ergebnis: ein Bild, das über der Klammfläche liegt (Rand und
Wildbach zeichnet render.py als Vektor darüber).

Die Klamm ist schmal; ein halb aufgelöstes Bild wirkt hier grob. Deshalb wird in voller Auflösung gerechnet, aber nur im
Rechteck um die Klamm."""
import base64
import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .gebirge import _blur, _smooth
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


def image(W, s, data):
    """data: river (Klammfläche als Ringe), light (Licht-x, Licht-y), Farben rock_col, rock_dark. Liefert eine Data-URI
    (Bild in Kartengröße, außerhalb der Klamm durchsichtig)."""
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
    half = float(np.percentile(dist[mask > 0.5], 92)) if (mask > 0.5).any() else 1.0   # halbe Klammbreite
    # Wandprofil: steil am Rand, nach unten flacher; dazu Felsbänder (Stufen) mit unregelmäßigem Verlauf
    u = 1 - np.exp(-dist / max(2.0, 0.42 * half))                # 0 am Rand .. 1 am Grund
    size = max(h, w)
    wob = _fbm(size, 34 * s, 3, 321, False)[:h, :w]
    wob = (wob - wob.mean()) / (wob.std() + 1e-6)
    u = np.clip(u + 0.04 * wob * (1 - u), 0, 1)
    steps = 6.0
    band = np.floor(u * steps)
    zn = np.clip((band + _smooth(u * steps - band, 0.0, 0.45)) / steps, 0, 1)   # je Stufe: steile Wand, dann Absatz
    # Beleuchtung: Rand 0, Grund tief; Hangneigung aus dem Gefälle
    z = -zn * 0.55 * half
    gy, gx = np.gradient(z.astype(np.float64))
    lx, ly = data["light"]
    L = np.array([lx * 0.75, ly * 0.75, 0.7])
    L /= np.linalg.norm(L)
    lit = (-gx * L[0] - gy * L[1] + L[2]) / np.sqrt(gx * gx + gy * gy + 1)
    shade = np.clip((lit - L[2]) * 1.5, -1, 1).astype(np.float32)
    # Färbung in drei Stufen: heller Fels am Rand, Wand, dunkler (aber nicht schwarzer) Grund
    rock, dark = _hex_rgb(data["rock_col"]), _hex_rgb(data["rock_dark"])
    c_rim = np.clip(rock * 1.10 + 0.02, 0, 1)
    c_wall = rock * 0.62 + dark * 0.2
    c_floor = dark * 0.55 + np.array([0.00, 0.015, 0.03], np.float32)
    t1 = _smooth(zn, 0.0, 0.55)[..., None]
    t2 = _smooth(zn, 0.45, 1.0)[..., None]
    col = (c_rim[None, None, :] * (1 - t1) + c_wall[None, None, :] * t1) * (1 - t2) + c_floor[None, None, :] * t2
    # feine Körnung in halber Auflösung erzeugen (Pixel für Pixel wäre teuer) und hochskalieren
    grit = _fbm(max(hh, hw), 5.5 * s, 3, 322, False)[:hh, :hw]
    grit = np.asarray(Image.fromarray(grit.astype(np.float32), "F").resize((w, h), Image.BICUBIC))
    col = col * (1 + 0.08 * ((grit - grit.mean()) / (grit.std() + 1e-6))[..., None])
    sun = np.array([1.0, 0.95, 0.82], np.float32)
    cool = np.array([0.60, 0.65, 0.78], np.float32)
    weak = (1 - 0.6 * _smooth(zn, 0.55, 1.0))[..., None]            # am Grund wirkt das Licht kaum noch
    col = col * (1 + 0.75 * np.clip(shade, 0, 1)[..., None] * weak * (sun[None, None, :] - 0.5))
    col = col * (1 - 0.62 * np.clip(-shade, 0, 1)[..., None] * (1 - cool[None, None, :] * 0.7))
    # Kanten der Felsbänder als dünne dunkle Linien (Schichtung)
    q = u * steps
    gq = np.hypot(*np.gradient(q.astype(np.float64))) + 1e-4
    dd = np.abs(q - np.round(q)) / gq                              # Abstand zur nächsten Bandkante in Pixeln
    ledge = np.clip(1 - (dd - 0.4) / 0.9, 0, 1) * 0.38 * (1 - _smooth(zn, 0.8, 1.0)) * _smooth(u, 0.06, 0.22)
    col = col * (1 - ledge[..., None]) + np.array([0.07, 0.06, 0.05], np.float32)[None, None, :] * ledge[..., None]
    img = np.empty((h, w, 4), np.uint8)
    img[..., :3] = np.clip(col * 255, 0, 255).astype(np.uint8)
    # auf die (genaue) Klammfläche zuschneiden; Maske um ein Pixel weiten, sonst bleibt am Rand ein Haarstrich
    img[..., 3] = np.asarray(mask_img.filter(ImageFilter.MaxFilter(3)), np.uint8)
    return img
