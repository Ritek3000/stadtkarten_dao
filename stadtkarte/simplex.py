"""Simplex-Rauschen: 2D nach Gustavson (Gitter aus gleichseitigen Dreiecken, keine Kästchen-Muster), dazu
1D-Gradientenrauschen für Linien. Bitgenau auf jedem Prozessor: nur Grundrechenarten, floor und Vergleiche,
keine Winkel- oder Exponentialfunktionen (math.sqrt ist IEEE-genau gerundet)."""
import math

import numpy as np

SQRT3 = math.sqrt(3.0)
FEATURE = 0.5                     # Gitterzellen je Wellenlänge: so entspricht "period" der sichtbaren Fleckgröße
F2 = 0.5 * (SQRT3 - 1.0)          # Schrägung ins Dreiecksgitter
G2 = (3.0 - SQRT3) / 6.0          # und zurück
# 12 Gradienten (Kanten eines Würfels, auf die Ebene projiziert): gleichmäßig verteilte Richtungen
GRAD = np.array([(1, 1), (-1, 1), (1, -1), (-1, -1), (1, 0), (-1, 0), (1, 0), (-1, 0),
                 (0, 1), (0, -1), (0, 1), (0, -1)], np.float64)


class Simplex2:
    """2D-Simplex-Rauschen mit eigener Permutation je Seed; Werte etwa im Bereich -1..1."""

    def __init__(self, seed):
        p = np.random.default_rng(seed).permutation(256)
        self.perm = np.concatenate([p, p]).astype(np.int64)
        self.gi = self.perm % 12

    def noise(self, x, y):
        x, y = np.asarray(x, np.float64), np.asarray(y, np.float64)
        s = (x + y) * F2
        i, j = np.floor(x + s), np.floor(y + s)
        t = (i + j) * G2
        x0, y0 = x - (i - t), y - (j - t)
        i1 = (x0 > y0).astype(np.int64)            # unteres oder oberes Dreieck der Raute
        j1 = 1 - i1
        x1, y1 = x0 - i1 + G2, y0 - j1 + G2
        x2, y2 = x0 - 1.0 + 2.0 * G2, y0 - 1.0 + 2.0 * G2
        ii, jj = i.astype(np.int64) & 255, j.astype(np.int64) & 255
        perm, gi = self.perm, self.gi
        out = np.zeros(x.shape, np.float64)
        for gidx, dx, dy in ((gi[ii + perm[jj]], x0, y0),
                             (gi[ii + i1 + perm[jj + j1]], x1, y1),
                             (gi[ii + 1 + perm[jj + 1]], x2, y2)):
            tt = 0.5 - dx * dx - dy * dy
            tt = np.where(tt > 0, tt, 0.0)
            tt = tt * tt
            out += tt * tt * (GRAD[gidx, 0] * dx + GRAD[gidx, 1] * dy)
        return 70.0 * out


def grid(size, period, seed, warp=0.0, stretch=1.0, rows=256):
    """size x size Werte eines Simplex-Rauschens mit der Wellenlänge 'period' (Pixel). Grobe Wellen werden auf
    einem dünneren Gitter (4 Punkte je Wellenlänge) berechnet und bikubisch vergrößert - das spart bei großen
    Bildern viel Zeit und Speicher; feine Wellen werden Pixel für Pixel berechnet. Zeilenweise in Blöcken.
    warp: Verzerrung der Koordinaten durch ein zweites, gröberes Simplex-Feld (in Wellenlängen) - ergibt
    fließende, wolkige Formen; stretch: Streckung in x-Richtung (z.B. 4 = in Windrichtung lang gezogen)."""
    from PIL import Image
    sp = Simplex2(seed)
    wx, wy = (Simplex2(seed + 7919), Simplex2(seed + 104729)) if warp else (None, None)
    step = period / 4.0 if period >= 8 else 1.0
    m = int(math.ceil(size / step)) + 3
    out = np.empty((m, m), np.float32)
    k = np.arange(m, dtype=np.float64) * (step / period) * FEATURE   # Simplex-Flecken sind halb so groß wie eine Gitterzelle
    for r0 in range(0, m, rows):
        yy, xx = np.meshgrid(k[r0:r0 + rows], k, indexing="ij")
        if warp:   # Koordinaten mit einem gröberen Feld verschieben
            u, v = xx * 0.5, yy * 0.5
            xx, yy = xx + warp * wx.noise(u, v), yy + warp * wy.noise(u, v)
        out[r0:r0 + rows] = sp.noise(xx / stretch, yy)
    if step == 1.0:
        return out[:size, :size]
    big = int(round(m * step))
    return np.asarray(Image.fromarray(out, "F").resize((big, big), Image.BICUBIC))[:size, :size]


class Simplex1:
    """1D-Gradientenrauschen (Simplex in einer Dimension) mit periodischen Gradienten: bei period=n wiederholt es
    sich nach n Einheiten (für geschlossene Umrisse). Skaliert auf dieselbe Streuung wie das frühere Wertrauschen."""
    SCALE = 4.0   # Streuung wie beim früheren Wertrauschen (0,5 gegen 0,41), Spitzen bleiben unter 1,3

    def __init__(self, rng, period=256):
        self.grads = [rng.random() * 2 - 1 for _ in range(period)]
        self.n = period

    def value(self, x):
        i = math.floor(x)
        x0 = x - i
        x1 = x0 - 1.0
        t0 = 1.0 - x0 * x0
        t1 = 1.0 - x1 * x1
        t0 *= t0
        t1 *= t1
        return self.SCALE * (t0 * t0 * self.grads[i % self.n] * x0 + t1 * t1 * self.grads[(i + 1) % self.n] * x1)
