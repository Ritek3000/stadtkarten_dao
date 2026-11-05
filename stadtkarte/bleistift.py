"""Zeichenstil "bleistift": die Karte wie mit dem Bleistift skizziert.

Alles geschieht im SVG-Filter über der Karte (siehe stile.py), die SVG-Datei bleibt eine Vektorkarte:
- zittrige Linien: Die Karte wird vor dem Kantenfinden mit Rauschen (feTurbulence) leicht verbogen
  (feDisplacementMap), zweimal mit anderem Rauschen; beide Kantenbilder übereinander ergeben doppelte, leicht
  versetzte Striche wie bei einer Skizze. Ein grobes Rauschen ändert den Strichdruck entlang der Linien;
- Schraffur nach Helligkeit: Eine nahtlose Kachel trägt drei Schraffurlagen in ihren Farbkanälen (Rot: schräge Striche,
  Grün: quer dazu, Blau: zusätzliche Striche zwischen denen in Rot). Helle Flächen bleiben weißes Papier, mittlere
  bekommen die erste Lage, dunkle die Kreuzschraffur, sehr dunkle die dichte Kreuzschraffur. Die Kachel wird über die
  Karte gelegt (feTile) und ebenfalls leicht verbogen, damit man die Wiederholung nicht sieht;
- ein leichter Graphitschleier in dunklen Flächen, dann Graphit auf Papier.

Die Kachel rechnet nur mit Ganzzahlen und Grundrechenarten (auf jedem Prozessor gleich) und wird verlustfrei
eingebettet, damit die Farbkanäle getrennt bleiben."""

import numpy as np
from PIL import Image

from .bilder import webp_uri
from .noise import memoized

_CACHE = {}

N = 384          # Kachel in Texeln
Q = 12           # Linienabstand entlang einer Bildachse in Texeln (teilt N); quer zu den Linien Q / Wurzel 2
ABSTAND = 4.0    # Linienabstand quer zu den Strichen in Kartenmaßen (mal s)
KACHEL = N * ABSTAND / (Q / np.sqrt(2))   # Kantenlänge der Kachel in Kartenmaßen (mal s)

GRAPHIT = ["#2b2b2f", "#6d6d72", "#f5f3ee"]   # dunkel -> Papier


def _f(x):
    return f"{x:.4f}".rstrip("0").rstrip(".") or "0"


def _lage(rng, richtung, versatz=0.0):
    """Eine Schraffurlage (0..1 Graphit) auf der N x N-Kachel, nahtlos. Linien laufen entlang i - richtung*j, also
    schräg; jede Linie besteht aus Strichen mit Lücken, eigenem Druck, an den Enden auslaufend und leicht schief."""
    i, j = np.mgrid[0:N, 0:N]
    u = (i + richtung * j) % N                    # quer zu den Linien (ganzzahlig)
    w = (i - richtung * j) % N                    # entlang der Linien
    lines = N // Q
    druck = np.zeros((lines, N), np.float32)      # je Linie und Stelle entlang der Linie
    lage = np.zeros((lines, N), np.float32)       # Versatz quer zur Linie (Texel)
    for li in range(lines):
        pos = int(rng.integers(0, N))
        ende = pos + N
        while pos < ende:
            laenge = int(rng.integers(4 * Q, 9 * Q))
            luecke = int(rng.integers(0, 2 * Q))
            p = 0.55 + 0.45 * float(rng.random())
            off = (float(rng.random()) - 0.5) * 0.3 * Q
            schief = (float(rng.random()) - 0.5) * 0.25 * Q
            n = min(laenge, ende - pos)
            t = (np.arange(n, dtype=np.float32) + 0.5) / laenge
            auslauf = np.minimum(1.0, np.minimum(t, 1.0 - t) / 0.12)
            idx = (pos + np.arange(n)) % N
            druck[li, idx] = p * auslauf
            lage[li, idx] = off + schief * (t - 0.5)
            pos += laenge + luecke
    k = u // Q
    abst = np.abs((u % Q).astype(np.float32) - (Q / 2 + versatz * Q) - lage[k, w])
    abst = np.minimum(abst, Q - abst)
    halb = 0.17 * Q
    profil = np.clip(1.0 - abst / halb, 0, 1)
    profil = profil * profil * (3 - 2 * profil)
    korn = 0.7 + 0.3 * rng.random((N, N), dtype=np.float32)   # Graphitkorn im Strich
    return np.clip(profil * druck[k, w] * korn, 0, 1)


def kachel():
    """Die Schraffurkachel als verlustfreie WebP-Data-URI (Rot, Grün, Blau = drei Lagen); hängt von nichts ab."""
    def rechne():
        rng = np.random.default_rng(23)
        lagen = [_lage(rng, 1), _lage(rng, -1), _lage(rng, 1, 0.5)]
        img = (np.dstack(lagen) * 255 + 0.5).astype(np.uint8)
        return webp_uri(Image.fromarray(img, "RGB"), lossless=True, quality=100, method=4)
    return memoized(_CACHE, "kachel", rechne, limit=2)


def _deckend(src, rows, result):
    """feColorMatrix mit 3x4-Zeilen (Faktoren für R, G, B und Versatz); Alpha wird 1."""
    vals = []
    for r in rows:
        vals += [r[0], r[1], r[2], 0, r[3]]
    vals += [0, 0, 0, 0, 1]
    return (f'<feColorMatrix in="{src}" type="matrix" values="{" ".join(_f(v) for v in vals)}" '
            f'result="{result}"/>')


def _verbogen(src, s, seed, result, scale=2.2, freq=13):
    """src mit Rauschen leicht verbogen (Hand, die nicht ganz ruhig ist)."""
    return (f'<feTurbulence type="fractalNoise" baseFrequency="{_f(1 / (freq * s))}" numOctaves="2" seed="{seed}" '
            f'result="r{seed}"/>'
            f'<feDisplacementMap in="{src}" in2="r{seed}" scale="{_f(scale * s)}" xChannelSelector="R" '
            f'yChannelSelector="G" result="{result}"/>')


def _kante(s, lum, result, gain):
    """Kantenstärke wie stile._kanten (Differenz zweier Weichzeichnungen), mit eigenen Namen."""
    from .stile import _table
    absfn = lambda t: min(1.0, abs(t - 0.5) * 2 * gain)
    return (f'<feGaussianBlur in="{lum}" stdDeviation="{_f(0.6 * s)}" result="{lum}a"/>'
            f'<feGaussianBlur in="{lum}" stdDeviation="{_f(2.0 * s)}" result="{lum}b"/>'
            f'<feComponentTransfer in="{lum}b" result="{lum}c">'
            + "".join(f'<feFunc{c} type="linear" slope="-1" intercept="1"/>' for c in "RGB") + "</feComponentTransfer>"
            f'<feComposite in="{lum}a" in2="{lum}c" operator="arithmetic" k2="0.5" k3="0.5" result="{lum}d"/>'
            + _table(absfn, 129, f"{lum}d", result))


def _gewichte(t):
    """Helligkeit t (0..1) -> Deckkraft der drei Schraffurlagen."""
    d = min(max((0.6 - t) / 0.45, 0.0), 1.0)   # Dunkelheit: Wasser, Äcker und Plätze bleiben fast Papier
    stufe = lambda a, b: min(max((d - a) / (b - a), 0.0), 1.0)
    return (0.85 * stufe(0.3, 0.75), 0.8 * stufe(0.7, 0.95), 0.7 * stufe(0.9, 1.0))


def filter_teile(s):
    """Die Filterschritte für den Bleistift (ohne <filter>-Hülle); letzter Schritt liefert "out"."""
    from .stile import _ramp, _table
    lum = [0.299, 0.587, 0.114, 0]
    k = KACHEL * s
    return [
        # zwei leicht verschieden verbogene Fassungen der Karte, je Helligkeit und Kanten
        _verbogen("SourceGraphic", s, 3, "v1"), _deckend("v1", [lum] * 3, "lum1"), _kante(s, "lum1", "k1", 4.5),
        _verbogen("SourceGraphic", s, 9, "v2", 2.8, 9), _deckend("v2", [lum] * 3, "lum2"), _kante(s, "lum2", "k2", 3.2),
        # Strichdruck: grobes Rauschen 0.55..1 entlang der Linien
        f'<feTurbulence type="fractalNoise" baseFrequency="{_f(1 / (70 * s))}" numOctaves="2" seed="5" result="rd"/>',
        _deckend("rd", [[0.9, 0, 0, 0.2]] * 3, "druck"),
        '<feComposite in="k1" in2="k2" operator="arithmetic" k1="-1" k2="0.85" k3="0.7" result="kk"/>',
        '<feComposite in="kk" in2="druck" operator="arithmetic" k1="1" result="linien"/>',
        # Schraffur nach Helligkeit
        f'<feImage href="{kachel()}" x="0" y="0" width="{_f(k)}" height="{_f(k)}" preserveAspectRatio="none" '
        'result="kachel0"/>',
        '<feTile in="kachel0" result="kachel1"/>',
        _deckend("kachel1", [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]], "kachel2"),
        _verbogen("kachel2", s, 17, "kachel", 3.5, 40),
        _table(_gewichte, 65, "lum1", "gew"),
        '<feComposite in="gew" in2="kachel" operator="arithmetic" k1="1" result="sg"/>',
        _deckend("sg", [[1.15, 1.05, 0.95, 0]] * 3, "schraffur"),
        # leichter Graphitschleier in dunklen Flächen
        _table(lambda t: 0.2 * min(max((0.5 - t) / 0.35, 0.0), 1.0), 33, "lum1", "schleier"),
        '<feComposite in="linien" in2="schraffur" operator="arithmetic" k2="1" k3="1" result="ls"/>',
        '<feComposite in="ls" in2="schleier" operator="arithmetic" k2="1" k3="1" result="graphit"/>',
        _table(lambda g: _ramp(GRAPHIT)(1 - g), 41, "graphit", "out"),
    ]
