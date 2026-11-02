"""Gebirge mit Höhe: aus der Felsfläche entsteht ein Höhenfeld, das im Inneren des Massivs hoch und zum Tal hin flach
ist und von langen Rücken durchzogen wird, die vom Massiv ins Tal laufen (Gratrauschen aus Simplex-Rauschen, in
Talrichtung gestreckt). Daraus werden Schummerung (Licht aus Nordwesten wie überall auf der Karte), Verschattung der
Täler, eine Färbung nach Höhe (Fußhang, Fels, Hochfels, Schnee) und schwache Höhenlinien berechnet. Ergebnis: ein
Bild, das über der Felsfläche liegt (die Felsfläche selbst und die Felskante zeichnet render.py als Vektor).

Alles wird in Fließkomma gerechnet: 8-Bit-Zwischenstufen (z.B. PIL-Weichzeichner auf einer Maske) ergeben im
Höhenfeld Treppchen, und die zeigen sich in der Schummerung als dünne Linien parallel zum Felsrand."""
import base64
import io

import numpy as np
from PIL import Image, ImageFilter

from .noise import _fbm, _hex_rgb
from .simplex import grid
from .umgebung import _mask


def _smooth(x, lo, hi):
    t = np.clip((x - lo) / (hi - lo + 1e-9), 0, 1)
    return t * t * (3 - 2 * t)


def _blur(a, sigma):
    """Gauß-Weichzeichner in Fließkomma: grob verkleinern, trennbar falten, glatt vergrößern."""
    n = a.shape[0]
    f = max(1, int(sigma / 3))
    small = np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((max(2, n // f),) * 2, Image.BOX)) \
        if f > 1 else a.astype(np.float32)
    sg = max(0.5, sigma / f)
    r = int(3 * sg) + 1
    x = np.arange(-r, r + 1)
    ker = np.exp(-x ** 2 / (2 * sg ** 2))
    ker /= ker.sum()
    pad = np.pad(small, r, mode="edge")   # am Bildrand setzt sich das Massiv fort
    tmp = np.apply_along_axis(lambda v: np.convolve(v, ker, "valid"), 1, pad)
    out = np.apply_along_axis(lambda v: np.convolve(v, ker, "valid"), 0, tmp).astype(np.float32)
    return np.asarray(Image.fromarray(out, "F").resize((n, n), Image.BICUBIC)) if f > 1 else out


def _ridges(res, period, octaves, seed, stretch, warp=0.0, power=3.0, gain=2.2):
    """Gratrauschen (Ridged Multifractal): scharfe Kämme an den Nulllinien des Rauschens, jede feinere Stufe nur dort,
    wo die gröbere schon hoch ist. stretch zieht die Rücken in Nord-Süd-Richtung (intern liegt das Tal im Süden)."""
    total = np.zeros((res, res), np.float32)
    amp, weight, norm = 1.0, 1.0, 0.0
    for o in range(octaves):
        n = grid(res, period / 2 ** o, seed * 16 + o, warp=warp if o < 2 else 0.0, stretch=stretch if o < 2 else 1.0).T
        r = (1.0 - np.abs(n)) ** power * weight
        weight = np.clip(r * gain, 0, 1)
        total += r * amp
        norm += amp
        amp *= 0.5
        if period / 2 ** o < 6:
            break
    return total / norm


def image(W, s, data, res=None):
    """data: rock (Flächen als Ringe), light (Licht-x, Licht-y), Farben rock_col, rock_dark, snow. Liefert eine Data-URI."""
    res = res or max(256, W // 2)
    k = res / W
    rock_img = _mask(res, k, data["rock"])
    mask = np.asarray(rock_img, np.float32) / 255
    # Höhenhülle: je weiter im Fels, desto höher (die Weichzeichner einer Randfläche liefern am Rand 0,5)
    near = _smooth(_blur(mask, 36 * s * k), 0.5, 1.0)
    mid = _smooth(_blur(mask, 120 * s * k), 0.5, 1.0)
    far = _smooth(_blur(mask, 320 * s * k), 0.5, 1.0)
    env = 0.30 * near + 0.40 * mid + 0.30 * far
    # lange Rücken des Massivs und kleinere Seitenrücken
    big = _ridges(res, 560 * s * k, 5, 311, 5.5, warp=0.7)
    side = _ridges(res, 170 * s * k, 4, 312, 3.3, warp=0.4)
    h = env * (0.28 + 0.70 * big + 0.12 * side)
    inside = mask > 0.5
    hs = h / (np.percentile(h[inside], 99.5) + 1e-6) if inside.any() else h
    # Schummerung: Höhe in Pixeln, Hangneigung aus dem Gefälle; light zeigt zur Lichtquelle
    z = hs * 360 * s * k
    gy, gx = np.gradient(z.astype(np.float64))
    lx, ly = data["light"]
    L = np.array([lx * 0.7, ly * 0.7, 0.8])
    L /= np.linalg.norm(L)
    lit = (-gx * L[0] - gy * L[1] + L[2]) / np.sqrt(gx * gx + gy * gy + 1)
    shade = np.clip((lit - L[2]) * 2.0, -1, 1).astype(np.float32)   # -1 Schatten .. 1 Licht, 0 = eben
    slope = np.clip(np.sqrt(gx * gx + gy * gy) / 1.4, 0, 1).astype(np.float32)
    # Färbung nach Höhe: Fußhang dunkler und erdiger, Hochfels heller und grauer
    rock, dark = _hex_rgb(data["rock_col"]), _hex_rgb(data["rock_dark"])
    foot = rock * 0.84 + dark * 0.16
    high = np.clip(rock * 1.10 + 0.05, 0, 1)
    t = _smooth(hs, 0.0, 0.7)[..., None]
    col = foot[None, None, :] * (1 - t) + high[None, None, :] * t
    grit = _fbm(res, 8 * s * k, 3, 304, False)   # Gesteinskörnung
    col = col * (1 + 0.05 * ((grit - grit.mean()) / (grit.std() + 1e-6))[..., None])
    # Täler liegen tiefer als ihre Umgebung und sind verschattet
    hs1 = np.clip(hs, 0, 1).astype(np.float32)
    ao = np.clip((_blur(hs1, 14 * s * k) - hs1) * 7.0, 0, 1)
    col = col * (1 - 0.5 * ao[..., None])
    # Schnee: ab einer Höhe mit fleckiger Grenze; an steilen Hängen bleibt der Fels frei
    lvl = 0.62 + 0.05 * (_fbm(res, 150 * s * k, 3, 305, False) - 0.516) / 0.105
    snow = np.clip(_smooth(hs, lvl, lvl + 0.10) * (1 - 0.7 * np.clip(slope * 1.2, 0, 1)), 0, 1)
    white, blue = _hex_rgb(data["snow"]), np.array([0.55, 0.65, 0.78], np.float32)
    snow_col = white[None, None, :] * (0.55 + 0.45 * np.clip(shade + 0.6, 0, 1))[..., None] \
        + blue[None, None, :] * np.clip(-shade, 0, 1)[..., None] * 0.5
    col = col * (1 - snow[..., None]) + snow_col * snow[..., None]
    # Licht und Schatten: warm in der Sonne, kühl im Schatten; auf Schnee schwächer
    weak = (1 - 0.4 * snow)[..., None]
    sun = np.array([1.0, 0.95, 0.82], np.float32)
    cool = np.array([0.55, 0.60, 0.74], np.float32)
    col = col * (1 + 0.6 * np.clip(shade, 0, 1)[..., None] * weak * (sun[None, None, :] - 0.5))
    col = col * (1 - 0.65 * np.clip(-shade, 0, 1)[..., None] * weak * (1 - cool[None, None, :]))
    # Höhenlinien: dünn und blass, nur über dem Fußhang
    gh = np.hypot(*np.gradient(hs.astype(np.float64))) + 1e-5
    q = hs * 5
    dist = np.abs(q - np.round(q)) / (gh * 5)   # Abstand zur nächsten Höhenlinie in Pixeln
    line = np.clip(1 - (dist - 0.5) / 0.9, 0, 1) * 0.20 * _smooth(hs, 0.05, 0.2) * (1 - 0.6 * snow)
    ink = np.array([0.30, 0.24, 0.17], np.float32)
    col = col * (1 - line[..., None]) + ink[None, None, :] * line[..., None]
    img = np.empty((res, res, 4), np.uint8)
    img[..., :3] = np.clip(col * 255, 0, 255).astype(np.uint8)
    # auf die (genaue) Felsfläche zuschneiden; Maske um ein Pixel weiten, sonst bleibt am Rand ein Haarstrich
    img[..., 3] = np.asarray(rock_img.filter(ImageFilter.MaxFilter(3)), np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, "WEBP", quality=88, alpha_quality=80, method=0)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
