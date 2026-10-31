"""Wasser mit Tiefe: Meer vom hellen Flachwasser an der Küste zum dunklen Tiefwasser, mit Simplex-Rauschen zu
Sandbänken und Rinnen aufgebrochen; feine Wellenkräusel auf dem offenen Wasser, aufgelöste Brandung direkt am
Ufer. Flüsse an den Ufern heller, in der Mitte dunkler. Ergebnis: ein Bild, das über der Wasserfläche liegt (in
render.py auf die Wasserfläche zugeschnitten); die Küstenlinien selbst zeichnet render.py als Vektor."""
import base64
import io

import numpy as np
from PIL import Image, ImageFilter

from .noise import _fbm, _hex_rgb
from .umgebung import _blur, _mask


def _unit(n):
    return (n - n.min()) / (n.max() - n.min() + 1e-6)


def _mix(a, b, t):
    return a[None, None, :] * (1 - t[..., None]) + b[None, None, :] * t[..., None]


def image(W, s, data, res=None):
    """data: sea/river (Flächen als Ringe) und Farben deep, sea, shallow, river, foam. Liefert eine Data-URI."""
    res = res or max(256, W // 2)
    k = res / W
    sea_img = _mask(res, k, data["sea"])
    river_img = _mask(res, k, data["river"])
    sea = np.asarray(sea_img, np.float32) / 255
    river = np.asarray(river_img, np.float32) / 255
    water = np.maximum(sea, river)
    land_img = Image.fromarray(((1 - water) * 255).astype(np.uint8), "L")
    rgb = np.zeros((res, res, 3), np.float32)
    # das Bild wird auf die (genaue) Wasserfläche zugeschnitten: Masken um ein Pixel weiten, sonst bleibt am
    # Ufer ein Haarstrich des Untergrunds stehen
    grow = ImageFilter.MaxFilter(3)
    sea_d = np.asarray(sea_img.filter(grow), np.float32) / 255
    river_d = np.asarray(river_img.filter(grow), np.float32) / 255
    if data["sea"]:
        # Nähe zum Land in drei Reichweiten: Küstensaum, Schelf, offene See
        near = _blur(land_img, 18 * s * k)
        shelf = _blur(land_img, 90 * s * k)
        far = _blur(land_img, 260 * s * k)
        bank = _unit(_fbm(res, 260 * s * k, 4, 91, False, warp=0.7))       # Sandbänke und Rinnen
        t = np.clip(near * 2.2 + shelf * 1.9 + far * 0.9 + (bank - 0.5) * 0.35, 0, 1)   # 1 = flach
        deep, mid, shallow = (_hex_rgb(data[c]) for c in ("deep", "sea_col", "shallow"))
        col = np.where((t < 0.5)[..., None], _mix(deep, mid, np.clip(t * 2, 0, 1)),
                       _mix(mid, shallow, np.clip(t * 2 - 1, 0, 1)))
        # feine Wellenkräusel: gestrecktes Simplex, nur auf tieferem Wasser
        ripple = np.abs(_fbm(res, 16 * s * k, 2, 92, False, stretch=3.0) - 0.516) / 0.105
        crest = np.clip(1 - ripple * 1.8, 0, 1) * np.clip(1 - t * 1.4, 0, 1) * 0.16
        col = col * (1 - crest[..., None]) + crest[..., None]
        # Brandung: schmaler, aufgelöster heller Saum direkt am Ufer
        surf = np.clip(_blur(land_img, 3.5 * s * k) * 3.2, 0, 1) * (1 - np.clip((1 - water) * 4, 0, 1))
        broken = np.clip((_unit(_fbm(res, 30 * s * k, 3, 93, False)) - 0.3) * 2.5, 0, 1)
        foam = surf * broken * 0.7
        col = col * (1 - foam[..., None]) + _hex_rgb(data["foam"])[None, None, :] * foam[..., None]
        rgb = col
    if data["river"]:
        bank = np.clip(_blur(Image.fromarray(((1 - river) * 255).astype(np.uint8), "L"), 5 * s * k) * 2.2, 0, 1)
        base, light = _hex_rgb(data["river_col"]), _hex_rgb(data["shallow"])
        flow = _unit(_fbm(res, 40 * s * k, 3, 94, False, stretch=2.0))      # leichte Strömungsflecken
        rc = _mix(base * 0.94, base, flow * 0.8)
        rc = rc * (1 - bank[..., None] * 0.55) + light[None, None, :] * (bank[..., None] * 0.55)   # helle Ufer
        # an der Mündung weich vom Fluss ins Meer überblenden (die Küstenlinie quer durch den Fluss ist gezackt)
        sea_soft = np.clip(_blur(sea_img, 30 * s * k) * 1.8, 0, 1) if data["sea"] else np.zeros_like(river)
        only = (river_d * (1 - np.maximum(sea_soft, sea_d * (1 - river_d))))[..., None]
        rgb = rc * only + rgb * (1 - only)
    img = np.empty((res, res, 4), np.uint8)
    img[..., :3] = np.clip(rgb * 255, 0, 255).astype(np.uint8)
    img[..., 3] = (np.maximum(sea_d, river_d) * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, "WEBP", quality=86, alpha_quality=80, method=0)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
