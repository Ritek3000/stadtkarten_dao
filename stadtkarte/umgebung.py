"""Bodentönung nach der Umgebung: der Boden ist nicht überall gleich. Nah am Wasser satter und dunkler, fern davon
trockener, an Landstraßen, vor den Toren und rund um die Mauer ausgetreten und erdig, am Waldrand moosig, an der
Küste ein Sand- bzw. Kiesstreifen. Die Flächen der Karte werden als weiche Masken gerastert, Simplex-Rauschen
macht ihre Ränder unregelmäßig. Ergebnis: ein halbdurchsichtiges Bild, das über der Bodentextur liegt."""
import base64
import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .noise import _fbm, _hex_rgb


def _mask(res, k, polys=(), lines=(), dots=()):
    """Flächen (Liste aus Außenring und Löchern), Linien (Koordinaten, Breite) und Punkte (x, y, Radius) als
    0..1-Maske; k = Pixel des Bildes je Kartenpixel."""
    img = Image.new("L", (res, res), 0)
    d = ImageDraw.Draw(img)
    for ext, holes in polys:
        d.polygon([(x * k, y * k) for x, y in ext], fill=255)
        for h in holes:
            d.polygon([(x * k, y * k) for x, y in h], fill=0)
    for coords, width in lines:
        d.line([(x * k, y * k) for x, y in coords], fill=255, width=max(1, int(round(width * k))), joint="curve")
    for x, y, r in dots:
        d.ellipse([(x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k], fill=255)
    return img


def _blur(img, radius):
    return np.asarray(img.filter(ImageFilter.GaussianBlur(max(0.5, radius))), np.float32) / 255


def image(W, s, data, res=None):
    """data: Flächen und Farben (siehe render.umgebung_daten). Liefert eine Data-URI (WebP mit Transparenz)."""
    res = res or max(256, W // 2)               # halbe Auflösung genügt für weiche Tönungen
    k = res / W
    out_rgb = np.zeros((res, res, 3), np.float32)
    out_a = np.zeros((res, res), np.float32)

    def put(color, alpha):
        nonlocal out_rgb, out_a
        if color is None:
            return
        out_rgb = _hex_rgb(color)[None, None, :] * alpha[..., None] + out_rgb * (1 - alpha[..., None])
        out_a = alpha + out_a * (1 - alpha)

    def vary(seed, lo=0.45):                    # unregelmäßige Ränder und Stärke
        n = _fbm(res, 180 * s * k, 4, seed, False, warp=0.5)
        n = (n - n.min()) / (n.max() - n.min() + 1e-6)
        return lo + (1 - lo) * n

    water_img = _mask(res, k, data["water"])
    water = np.asarray(water_img, np.float32) / 255
    dry = 1 - np.clip(_blur(water_img, 260 * s * k) * 3.5, 0, 1)
    put(data["dry"], dry * 0.22 * vary(81))
    near = np.clip(_blur(water_img, 55 * s * k) * 2.4, 0, 1) * (1 - water)
    put(data["moist"], near * 0.42 * vary(82, 0.55))
    if data["forest"]:
        f_img = _mask(res, k, data["forest"])
        fb = _blur(f_img, 16 * s * k)
        band = np.clip(fb * 3.2, 0, 1) * (1 - np.asarray(f_img, np.float32) / 255)
        put(data["moss"], band * 0.38 * vary(83))
    worn = np.maximum(_blur(_mask(res, k, lines=data["roads"]), 7 * s * k) * 1.6,
                      _blur(_mask(res, k, data["city_ring"], dots=data["gates"]), 22 * s * k) * 1.2)
    put(data["worn"], np.clip(worn, 0, 1) * 0.55 * vary(84, 0.4))
    if data["shore"] and data["sea"]:
        sea_img = _mask(res, k, data["sea"])
        sea = np.asarray(sea_img, np.float32) / 255
        width = vary(85, 0.3)                    # mal breiter Strand, mal nur ein Saum
        band = np.clip(_blur(sea_img, 9 * s * k) * 2.6 * width * 1.6, 0, 1) * (1 - sea)
        put(data["shore"], band * 0.75)
    img = np.empty((res, res, 4), np.uint8)
    img[..., :3] = np.clip(out_rgb / np.maximum(out_a, 1e-6)[..., None] * 255, 0, 255).astype(np.uint8)
    img[..., 3] = np.clip(out_a * 255, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, "WEBP", quality=85, alpha_quality=80, method=0)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
