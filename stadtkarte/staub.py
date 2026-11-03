"""Staub: in der Spielwelt allgegenwärtig, an manchen Stellen dichter. In hoher Konzentration wird er zur
Finsternis. Staubflächen liegen in einem 5x5-Raster über der fertigen Karte (Felder a1 bis e5: Spalte a-e von
links, Zeile 1-5 von oben), in Himmelsrichtungen um die Stadt (wie Wald und Felder), über der Stadt ("mitte") oder
als Schleier über der ganzen Karte ("ueberall"); jede mit einer Stärke:
  wenig      - leichter, dunkler Schleier über allem
  mittel     - alles darunter nur noch schemenhaft
  finsternis - im Kern schwarz, nichts mehr erkennbar; zum Rand hin verwehend
Gezeichnet wird ein Bild über der fertigen Karte (unter der Beschriftung, über Licht und Leuchtfeuer)."""
import math
import random

import numpy as np
from PIL import Image, ImageFilter

from .geo import blob
from .bilder import webp_uri
from .noise import FBM_MEAN, FBM_STD, _fbm, _hex_rgb

STUFEN = {"wenig": 0.55, "mittel": 0.8, "finsternis": 0.99}   # Deckkraft im Kern
GRID = {c + r for c in "abcde" for r in "12345"}                # Rasterfelder über der Karte (5x5)


def areas(cfg, W, center, r, rot):
    """Staubflächen als [(Fläche, Stärke)] in Kartenkoordinaten (vor der Drehung) und die Stärke des Schleiers
    über der ganzen Karte. Eigener Zufall: die übrige Karte bleibt unverändert."""
    from .config import to_canonical
    wish = cfg["gelaende"].get("staub") or {}
    rng = random.Random(f"staub-{cfg['seed']}")
    cx, cy = center
    out = []
    a = math.radians(-rot)                      # Rasterfelder liegen auf der fertigen Karte: zurückdrehen
    half = W / 2
    for key, level in sorted(wish.items()):
        if key in ("ueberall", "mitte"):
            continue
        if key in GRID:
            col, row = "abcde".index(key[0]), int(key[1]) - 1
            fx, fy = (col + 0.5) / 5 * W - half, (row + 0.5) / 5 * W - half
            px, py = half + fx * math.cos(a) - fy * math.sin(a), half + fx * math.sin(a) + fy * math.cos(a)
            out.append((blob(rng, px, py, W * rng.uniform(0.12, 0.145), rough=0.45,
                             stretch=(rng.uniform(0.9, 1.2), rng.uniform(0.9, 1.2))), level))
            continue
        dx, dy = to_canonical(key, rot)
        dist = r + W * 0.3
        px, py = cx + dx * dist, cy + dy * dist
        out.append((blob(rng, px, py, W * rng.uniform(0.21, 0.27), rough=0.5,
                         stretch=(rng.uniform(0.8, 1.3), rng.uniform(0.8, 1.3))), level))
    if wish.get("mitte"):
        out.append((blob(rng, cx, cy, r * 1.05, rough=0.35), wish["mitte"]))
    return out, wish.get("ueberall")


def image(W, s, patches, overall, res=None):
    """Data-URI (WebP mit Transparenz) des Staubs. patches: [(Ringe, Stärke)]."""
    from .umgebung import _mask
    res = res or max(256, W // 2)
    k = res / W
    alpha = np.zeros((res, res), np.float32)
    wisp = (_fbm(res, 260 * s * k, 4, 301, False, warp=0.9) - FBM_MEAN) / FBM_STD        # verwehte Schwaden
    wisp = np.clip(0.5 + wisp * 0.22, 0, 1)
    for rings, level in patches:
        m = _mask(res, k, rings)
        core = np.asarray(m.filter(ImageFilter.GaussianBlur(110 * s * k)), np.float32) / 255
        core = np.clip(core * 1.6, 0, 1)
        if level == "finsternis":
            # Kern vollständig schwarz; der Rand franst in Schwaden aus (Rauschen verschiebt die Grenze)
            edge = np.clip((core - 0.35 + (wisp - 0.5) * 0.7) * 2.6, 0, 1)
            edge = edge * edge * (3 - 2 * edge)
            a = STUFEN[level] * np.clip(edge + 0.45 * core * wisp, 0, 1)
        else:
            core = core * core * (3 - 2 * core)                                    # weicher Rand, voller Kern
            a = STUFEN[level] * core * (0.7 + 0.5 * wisp)
        alpha = 1 - (1 - alpha) * (1 - np.clip(a, 0, 1))
    if overall:
        veil = STUFEN[overall] * (0.6 + 0.6 * wisp) * (0.55 if overall == "finsternis" else 0.7)
        alpha = 1 - (1 - alpha) * (1 - np.clip(veil, 0, 0.95))
    # Farbe: tiefes Schwarzbraun, in dünnen Schleiern ein Hauch heller (Staubkörnung)
    grain = np.random.default_rng(302).random((res, res), dtype=np.float32)
    dark, dust = _hex_rgb("#0c0a08"), _hex_rgb("#3b342b")
    t = np.clip((1 - alpha) * 0.9 * (0.6 + 0.4 * grain), 0, 1)[..., None]
    rgb = dark[None, None, :] * (1 - t) + dust[None, None, :] * t
    img = np.empty((res, res, 4), np.uint8)
    img[..., :3] = np.clip(rgb * 255, 0, 255).astype(np.uint8)
    img[..., 3] = np.clip(alpha * 255, 0, 255).astype(np.uint8)
    return webp_uri(Image.fromarray(img, "RGBA"), quality=86, alpha_quality=90, method=0)

