"""Zeichenstil "pergament": die fertige Karte wirkt wie auf altem Papier gezeichnet. Papierstruktur aus Simplex-
Rauschen (Fasern, Körnung, Wolken und Stockflecken), gealterter Rand und ein warmer Farbton über allem. Das Bild
wird im Modus "multiply" über die Karte gelegt: Weiß lässt die Karte unverändert, alles andere tönt sie ein."""
import base64
import io

import numpy as np
from PIL import Image

from .noise import _fbm, _hex_rgb


def _unit(n):
    lo, hi = np.percentile(n, 1), np.percentile(n, 99)
    return np.clip((n - lo) / (hi - lo + 1e-6), 0, 1)


def image(W, s, tint="#efe0bf", edge="#8a6a3c", res=None):
    """Papierstruktur als Data-URI (WebP, deckend, zum Multiplizieren)."""
    res = res or max(256, W // 2)
    k = res / W
    rng = np.random.default_rng(1307)
    clouds = _unit(_fbm(res, 420 * s * k, 4, 201, False, warp=0.8))             # wolkige Vergilbung
    fibers = _unit(_fbm(res, 40 * s * k, 3, 202, False, stretch=6.0))          # lange Papierfasern
    fibers2 = _unit(_fbm(res, 30 * s * k, 2, 203, False, stretch=5.0).T)       # und quer dazu
    grain = rng.random((res, res), dtype=np.float32)
    spots = np.clip((_unit(_fbm(res, 70 * s * k, 3, 204, False, warp=0.4)) - 0.86) * 6, 0, 1)   # Stockflecken
    y, x = (np.mgrid[0:res, 0:res].astype(np.float32) + 0.5) / res
    d = np.minimum(np.minimum(x, 1 - x), np.minimum(y, 1 - y))                 # Abstand zum Rand
    ragged = 0.035 + 0.02 * _unit(_fbm(res, 120 * s * k, 3, 205, False))
    burn = np.clip(1 - d / ragged, 0, 1) ** 1.6                                 # unregelmäßig gebräunter Rand
    base = _hex_rgb(tint)
    dark = _hex_rgb(edge)
    # Helligkeit 1 = Papierweiß (Karte bleibt), darunter Einfärbung
    shade = (1 - 0.10 * clouds - 0.035 * (fibers - 0.5) - 0.025 * (fibers2 - 0.5) - 0.03 * (grain - 0.5)
             - 0.10 * spots)
    rgb = (0.55 + 0.45 * base)[None, None, :] * shade[..., None]               # leichter warmer Grundton
    rgb = rgb * (1 - burn[..., None] * 0.55) + dark[None, None, :] * (burn[..., None] * 0.55)
    img = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img, "RGB").save(buf, "WEBP", quality=84, method=0)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
