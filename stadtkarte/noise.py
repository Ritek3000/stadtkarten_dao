"""Vorberechnete Rauschtexturen.

Ersetzt SVG-Filter aus feTurbulence + feColorMatrix (beim Rendern sehr teuer) durch fertige Bilder (in der
Auflösung der Karte). Grundlage ist Simplex-Rauschen (simplex.py): ohne Kästchen-Muster, dazu verzerrt (fließende
Flecken, Nebelschwaden), als Nulllinien (Felsrisse) und gestreckt (Schneeverwehungen). Helligkeit und Streuung
entsprechen den früheren Filtern, Filterfarben gelten wie dort im linearen Farbraum.
"""
import base64
import io

import numpy as np
from PIL import Image, ImageFilter

from .simplex import grid

# gemessene Verteilung des feTurbulence-Kanals (linearer Farbraum)
STATS = {"fractalNoise": (0.516, 0.105), "turbulence": (0.309, 0.141)}
_CACHE = {}


def _fbm(size, period, octaves, seed, turbulence, warp=0.0, stretch=1.0):
    """Simplex-Rauschen mit mehreren Oktaven; period = Wellenlänge der gröbsten Oktave in Pixeln.
    turbulence: Beträge der Oktaven (bauschig), warp/stretch siehe simplex.grid (nur die groben Oktaven)."""
    total = np.zeros((size, size), np.float32)
    amp = 1.0
    for o in range(octaves):
        layer = grid(size, period, seed * 16 + o, warp=warp if o < 2 else 0.0, stretch=stretch)
        total += amp * (np.abs(layer) if turbulence else layer)
        amp *= 0.5
        period /= 2
        if period < 1.5:
            break
    mean, std = STATS["turbulence" if turbulence else "fractalNoise"]
    total = (total - total.mean()) / (total.std() + 1e-6)
    return total * std + mean


def _lin_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def _layer(W, s, res, spec):
    base_freq, octaves, seed, rgb_linear, gain, bias, turbulence = spec[:7]
    warp = spec[7] if len(spec) > 7 else 0.0       # optional: Verzerrung (fließende Formen)
    period = (1.0 / (base_freq / s)) * res / W     # Wellenlänge in Pixeln des Texturbildes
    n = _fbm(res, period, octaves, seed, turbulence, warp=warp)
    alpha = np.clip(gain * n + bias, 0, 1)
    rgb = _lin_to_srgb(np.array(rgb_linear, np.float32))
    return rgb, alpha


def _soft(a, radius):
    """Leichtes Weichzeichnen eines Werte-Arrays (0..1) über PIL."""
    if radius <= 0.2:
        return a
    img = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(img, np.float32) / 255


def _detail(kind, res, s, seed, density=1.0):
    """Feine Bodendetails als Deckkraft-Array (0..1). Größen gelten für 2000 px und skalieren mit s."""
    rng = np.random.default_rng(seed)
    if kind == "grain":           # Körnung des Bodens
        n = _soft(rng.random((res, res), np.float32), 0.7 * s)
        n = (n - n.mean()) / (n.std() + 1e-6)
        return np.clip((n - 0.9) * 0.6, 0, 1)
    if kind == "sparkle":         # vereinzelte helle Punkte (Schnee, Kristalle)
        return _soft((rng.random((res, res)) < 0.0012 * density).astype(np.float32), 0.5 * s)
    if kind in ("stipple", "strokes"):   # Grasbüschel bzw. trockene Halme, in Gruppen
        clump = _fbm(res, 120 * s * res / (2000 * s), 3, seed + 1, False)
        clump = np.clip((clump - 0.45) * 4, 0, 1)
        k = int(res * res / (55 * s * s) * density)
        ys, xs = rng.integers(0, res, k), rng.integers(0, res, k)
        keep = rng.random(k) < clump[ys, xs]
        ys, xs = ys[keep], xs[keep]
        a = np.zeros((res, res), np.float32)
        if kind == "stipple":
            r = max(1, int(round(0.8 * s)))
            for dy in range(r + 1):
                for dx in range(r + 1):
                    a[np.clip(ys + dy, 0, res - 1), np.clip(xs + dx, 0, res - 1)] = 1
        else:
            steps = max(3, int(4 * s))
            ang = rng.uniform(-0.6, 0.6, len(xs)) - np.pi / 2
            for i in range(steps):
                a[np.clip((ys + np.sin(ang) * i).astype(int), 0, res - 1),
                  np.clip((xs + np.cos(ang) * i).astype(int), 0, res - 1)] = 1
        return _soft(a, 0.5 * s)
    if kind in ("ripple_light", "ripple_dark"):   # Sandrippel quer zum Wind
        y, x = np.mgrid[0:res, 0:res].astype(np.float32)
        # zwei Verzerrungsstufen machen die Kämme gewunden; Wellenlänge schwankt leicht
        warp = _fbm(res, 320 * s, 3, seed + 2, False)
        warp2 = _fbm(res, 90 * s, 2, seed + 4, False)
        wave = 15 * s * (0.8 + 0.4 * _fbm(res, 400 * s, 2, seed + 5, False))
        phase = (x * 0.94 + y * 0.34) / wave * 2 * np.pi + (warp - 0.5) * 70 + (warp2 - 0.5) * 22
        if kind == "ripple_dark":
            phase = phase + 0.9
        v = np.sin(phase)
        fade = np.clip((_fbm(res, 260 * s, 3, seed + 3, False) - 0.5) * 6, 0, 1)   # nur stellenweise sichtbar
        return np.clip((v - 0.78) * 4.5, 0, 1) * fade
    if kind == "drift":           # Schneeverwehungen: in Windrichtung 4:1 gestreckte, leicht verwehte Flecken
        n = _fbm(res, res / 10, 4, seed, False, warp=0.25, stretch=5.0)
        return np.clip((n - 0.56) * 5, 0, 1)
    if kind == "cracks_hi":       # helle Bruchkante, leicht versetzt neben dem Riss
        shift = max(1, int(round(1.2 * s)))
        return np.roll(_detail("cracks", res, s, seed), (-shift, -shift), axis=(0, 1))
    if kind == "cracks":          # Felsrisse: Nulllinien eines Simplex-Rauschens - lange, mäandernde Linien
        n = _fbm(res, 45 * s, 5, seed, False)
        ridged = 1 - np.abs(n - n.mean()) / (n.std() * 3)
        mask = np.clip((_fbm(res, 220 * s, 2, seed + 1, False) - 0.45) * 6, 0, 1)   # Risse nur stellenweise
        return np.clip((ridged - 0.965) * 30, 0, 1) * mask
    raise ValueError(kind)


def _hex_rgb(h):
    return np.array([int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)], np.float32)


def texture(W, s, layers, res=None, extras=(), base=None):
    """Data-URI eines RGBA-Bildes aus einer oder mehreren übereinandergelegten Rauschschichten.
    layers: Liste aus (Parameter, Deckkraft); Parameter = (baseFrequency, Oktaven, Seed, Farbe linear,
    Verstärkung, Versatz, Turbulenz). Mehrere Schichten in einem Bild sparen Renderzeit."""
    res = res or W
    key = (W, round(s, 4), res, tuple((tuple(map(str, sp)), op) for sp, op in layers), tuple(map(tuple, extras)), base)
    if key in _CACHE:
        return _CACHE[key]
    out_rgb = np.zeros((res, res, 3), np.float32)   # vormultipliziert
    out_a = np.zeros((res, res), np.float32)
    if base:   # deckender Untergrund: Bild ohne Transparenz, komprimiert viel besser
        out_rgb[:] = _hex_rgb(base)
        out_a[:] = 1
    for spec, opacity in layers:
        rgb, alpha = _layer(W, s, res, spec)
        a = alpha * opacity
        out_rgb = rgb[None, None, :] * a[..., None] + out_rgb * (1 - a[..., None])
        out_a = a + out_a * (1 - a)
    # feine Details (Körnung, Gras, Rippel, Risse ...): extras = (Art, Farbe #rrggbb, Deckkraft, Seed[, Dichte])
    for ex in extras:
        kind, color, opacity, seed = ex[:4]
        a = _detail(kind, res, s, seed, *(ex[4:5] or [1.0])) * opacity
        out_rgb = _hex_rgb(color)[None, None, :] * a[..., None] + out_rgb * (1 - a[..., None])
        out_a = a + out_a * (1 - a)
    img = np.empty((res, res, 4), np.uint8)
    img[..., :3] = np.clip(out_rgb / np.maximum(out_a, 1e-6)[..., None] * 255, 0, 255).astype(np.uint8)
    img[..., 3] = np.clip(out_a * 255, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    if base:
        Image.fromarray(img[..., :3], "RGB").save(buf, "WEBP", quality=82, method=0)
    else:
        Image.fromarray(img, "RGBA").save(buf, "WEBP", quality=82, alpha_quality=70, method=0)
    uri = "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
    if len(_CACHE) > 40:
        _CACHE.clear()
    _CACHE[key] = uri
    return uri
