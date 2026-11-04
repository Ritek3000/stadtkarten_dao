"""Zeichenstile über "standard" und "pergament" hinaus (Tusche, Aquarell, Sepia-Stich ...).

Jeder Stil besteht aus drei Teilen:
- einem SVG-Filter über der gezeichneten Karte (ohne Beschriftung und ohne Nachtlichter): Farben umrechnen,
  Kanten herausziehen (Tuschelinien), weichzeichnen. So bleibt die SVG-Datei eine Vektorkarte, und PNG, PDF,
  Nachtkarte und interaktive Karte zeigen denselben Stil;
- einer vorberechneten Textur über der Karte (wie beim Pergament): ein Bild, das im Modus "multiply" Papierfasern
  und Wolken einbringt, und ein zweites, das Rand, Lichtschein oder Brandspuren darüberlegt;
- auf Wunsch anderen Schriftfarben (dunkle Tinte statt heller Schrift).

Die Kanten entstehen aus der Helligkeit: leicht weichgezeichnet, waagerechte und senkrechte Differenz
(feConvolveMatrix mit Versatz 0.5, damit negative Werte nicht abgeschnitten werden), davon der Betrag über eine
Tabelle. Alle Zwischenbilder sind deckend (Alpha 1), damit arithmetische Verknüpfungen das Alpha nicht verfälschen."""

import numpy as np
from PIL import Image

from .bilder import webp_uri
from .noise import _fbm, _hex_rgb, memoized
from .styles import STILE

_CACHE = {}

EIGENE = [k for k in STILE if k not in ("standard", "pergament")]   # Stile aus diesem Modul

# Schriftfarben (Schrift, Schriftrand) für Stile mit heller Karte: dunkle Tinte statt heller Schrift
_SCHRIFT = {"tusche": ("#2a1d12", "#f1e7d0"), "pastell": ("#5b5068", "#fbf8f2"), "bleistift": ("#2d2d30", "#f4f2ee")}


def schrift(stil):
    """(Schriftfarbe, Randfarbe) oder None, wenn die Beschriftung bleibt wie sie ist."""
    return _SCHRIFT.get(stil)


# --- Filterbausteine -------------------------------------------------------------------------------------------

def _f(x):
    return f"{x:.4f}".rstrip("0").rstrip(".") or "0"


def _vals(a):
    return " ".join(_f(float(v)) for v in np.ravel(a))


def _sat_matrix(k):
    """Sättigung k (1 = unverändert) als 3x3-Matrix."""
    lum = np.array([0.299, 0.587, 0.114])
    return k * np.eye(3) + (1 - k) * np.tile(lum, (3, 1))


def _matrix(m3, offset=(0, 0, 0), src="SourceGraphic", result="farbe"):
    """feColorMatrix aus 3x3-Matrix und Versatz; Alpha wird 1."""
    rows = [list(m3[i]) + [0, offset[i]] for i in range(3)] + [[0, 0, 0, 0, 1]]
    return f'<feColorMatrix in="{src}" type="matrix" values="{_vals(rows)}" result="{result}"/>'


def _table(fn, n=33, src="", result=""):
    """feComponentTransfer: jeder Farbkanal t -> fn(t) (fn liefert ein RGB-Tripel oder eine Zahl)."""
    t = np.linspace(0, 1, n)
    v = np.array([np.broadcast_to(np.asarray(fn(x), float), (3,)) for x in t]).clip(0, 1)
    funcs = "".join(f'<feFunc{c} type="table" tableValues="{_vals(v[:, i])}"/>' for i, c in enumerate("RGB"))
    return f'<feComponentTransfer in="{src}" result="{result}">{funcs}</feComponentTransfer>'


def _ramp(cols):
    """Farbverlauf über mehrere Farben: t (0..1) -> RGB."""
    cs = np.array([_hex_rgb(c) for c in cols], float)

    def fn(t):
        x = min(max(t, 0.0), 1.0) * (len(cs) - 1)
        i = min(int(x), len(cs) - 2)
        return cs[i] * (1 - (x - i)) + cs[i + 1] * (x - i)
    return fn


def _treppe(n, weich=0.45):
    """Weiche Treppe mit n Stufen: Farbflächen wie im Druck, aber mit weichen Übergängen (harte Stufen je Kanal
    ergäben grelle Farbbänder)."""
    def fn(t):
        x = t * n - 0.5
        i = np.floor(x)
        r = np.clip((x - i - 0.5) / weich + 0.5, 0, 1)
        r = r * r * (3 - 2 * r)
        return float(np.clip((i + r + 0.5) / n, 0, 1))
    return fn


KANTE = 5.5   # Verstärkung der Kanten
_LUM = _matrix(np.tile([0.299, 0.587, 0.114], (3, 1)), result="lum")


def _kanten(s, gain=KANTE):
    """Kantenstärke 0..1 (grau) als Ergebnis "kante", aus der Helligkeit "lum": Betrag der Differenz zweier
    Weichzeichnungen (Difference of Gaussians). Beide Radien sind in Kartenmaßen, daher sehen die Linien in jeder
    Bildgröße und auch in der halb so großen Vorschau gleich aus (eine Faltung oder ein Versatz rechnet dagegen in
    Bildpunkten). Die Differenz wird um 0.5 verschoben, damit negative Werte nicht abgeschnitten werden."""
    absfn = lambda t: min(1.0, abs(t - 0.5) * 2 * gain)
    return (f'<feGaussianBlur in="lum" stdDeviation="{_f(0.7 * s)}" result="l1"/>'
            f'<feGaussianBlur in="lum" stdDeviation="{_f(2.2 * s)}" result="l2"/>'
            '<feComponentTransfer in="l2" result="l2i">'
            + "".join(f'<feFunc{c} type="linear" slope="-1" intercept="1"/>' for c in "RGB") + "</feComponentTransfer>"
            '<feComposite in="l1" in2="l2i" operator="arithmetic" k2="0.5" k3="0.5" result="dog"/>'
            + _table(absfn, 129, "dog", "kante"))


def _mal(a, b, result):
    """Produkt zweier deckender Bilder."""
    return f'<feComposite in="{a}" in2="{b}" operator="arithmetic" k1="1" result="{result}"/>'


def _abdunkeln(src, staerke, result):
    """src * (1 - staerke * kante)."""
    return (f'<feComponentTransfer in="kante" result="nk">'
            + "".join(f'<feFunc{c} type="linear" slope="{_f(-staerke)}" intercept="1"/>' for c in "RGB")
            + "</feComponentTransfer>" + _mal(src, "nk", result))


def _tinte(a, b, ramp):
    """Tinte aus Kanten und Dunkelheit: t = 1 - min(1, a*kante + b*(1-lum)), dann Farbverlauf."""
    inv = ('<feComponentTransfer in="lum" result="iv">'
           + "".join(f'<feFunc{c} type="linear" slope="-1" intercept="1"/>' for c in "RGB") + "</feComponentTransfer>")
    tot = a + b   # gewichtetes Mittel (k2 + k3 = 1 hält Alpha bei 1), die Tabelle streckt wieder
    return (inv + f'<feComposite in="kante" in2="iv" operator="arithmetic" k2="{_f(a / tot)}" k3="{_f(b / tot)}" '
            f'result="w"/>' + _table(lambda w: ramp(1 - min(1.0, w * tot)), 41, "w", "out"))


def filter_svg(stil, s, W):
    """<filter id="stil"> für die Karte (Größe W in Nutzerkoordinaten) oder "" für Stile ohne Filter."""
    p = []
    if stil == "tusche":
        p += [_LUM, _kanten(s), _tinte(1.5, 0.12, _ramp(["#2a1d12", "#7a6450", "#f1e7d0"]))]
    elif stil == "aquarell":
        p += [_LUM, _kanten(s), f'<feGaussianBlur in="SourceGraphic" stdDeviation="{_f(3.75 * s)}" result="weich"/>',
              _matrix(0.75 * _sat_matrix(1.25), (0.32, 0.32, 0.32), "weich"), _abdunkeln("farbe", 0.33, "out")]
    elif stil == "sepia":
        p += [_LUM, _kanten(s), _table(lambda t: _ramp(["#2b1a0e", "#7b5532", "#c9a774", "#f2e2bf"])(t ** 0.9), 41,
                                       "lum", "braun"), _abdunkeln("braun", 0.4, "out")]
    elif stil == "schatzkarte":
        p += [_matrix(0.85 * np.diag([1.05, 0.9, 0.65]) @ _sat_matrix(0.45), (0.12, 0.12, 0.12), result="out")]
    elif stil == "abendlicht":
        p += [_matrix(np.diag([1.12, 0.98, 0.78]), (0.05, 0.02, -0.02)),
              '<feComponentTransfer in="farbe" result="out">'
              + "".join(f'<feFunc{c} type="gamma" amplitude="1" exponent="0.95" offset="0"/>' for c in "RGB")
              + "</feComponentTransfer>"]
    elif stil == "farbdruck":
        p += [_LUM, _kanten(s), f'<feGaussianBlur in="SourceGraphic" stdDeviation="{_f(1.5 * s)}" result="weich"/>',
              _matrix(_sat_matrix(1.05), src="weich", result="satt"),
              _table(_treppe(6), 97, "satt", "flach"),
              _matrix(0.86 * np.diag([1.0, 0.97, 0.9]), (0.12, 0.116, 0.108), "flach"), _abdunkeln("farbe", 0.45, "out")]
    elif stil == "pastell":
        p += [_LUM, _kanten(s), _matrix(0.68 * _sat_matrix(1.05), (0.32, 0.32, 0.32)), _abdunkeln("farbe", 0.5, "out")]
    elif stil == "bleistift":
        p += [_LUM, _kanten(s), _tinte(1.2, 0.42, _ramp(["#2d2d30", "#8a8a8c", "#f4f2ee"]))]
    elif stil == "stich":
        p += [_LUM, _kanten(s), _matrix(0.5 * _sat_matrix(0.65), (0.47, 0.44, 0.37)),
              '<feColorMatrix in="kante" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1.5 0 0 0 0" result="tinte"/>',
              '<feFlood flood-color="#2b2015" result="tf"/>',
              '<feComposite in="tf" in2="tinte" operator="in" result="linien"/>',
              '<feComposite in="linien" in2="farbe" operator="over" result="out"/>']
    if not p:
        return ""
    return (f'<filter id="stil" filterUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{W}" '
            'color-interpolation-filters="sRGB">' + "".join(p) + "</filter>")


# --- Texturen über der Karte -----------------------------------------------------------------------------------

def _norm(a):
    lo, hi = np.percentile(a, 1), np.percentile(a, 99)
    return np.clip((a - lo) / (hi - lo + 1e-6), 0, 1).astype(np.float32)


def cache_key(stil, W, s, res=None):
    return (stil, W, round(s, 4), res or max(256, W // 2))


def bilder(stil, W, s, res=None):
    """(Multiplikationsbild, Deckbild) als Data-URIs (jeweils None, wenn der Stil keins hat). Hängt nur von Stil,
    Größe und Maßstab ab und wird gemerkt (Tag- und Nachtkarte teilen sie)."""
    res = res or max(256, W // 2)
    return memoized(_CACHE, cache_key(stil, W, s, res), lambda: _bilder(stil, W, s, res), limit=6)


def _bilder(stil, W, s, res):
    k = res / W
    sc = s * k / 0.8   # die Rauschmaße unten gelten für eine Karte von 1600 px
    lazy = {}

    def n(name):
        if name not in lazy:
            lazy[name] = {"faser": lambda: _norm(_fbm(res, 40 * sc, 3, 12, False, stretch=6.0)),
                          "wolke": lambda: _norm(_fbm(res, 380 * sc, 4, 13, False, warp=0.8)),
                          "korn": lambda: np.random.default_rng(11).random((res, res), dtype=np.float32),
                          "rand": lambda: _norm(_fbm(res, 60 * sc, 4, 14, False))}[name]()
        return lazy[name]

    yy, xx = (np.mgrid[0:res, 0:res].astype(np.float32) + 0.5) / res
    rad = np.hypot(xx - 0.5, yy - 0.5) / 0.707
    mul = None
    deck = []   # (Farbe, Deckkraft) von unten nach oben

    def vignette(col, staerke, start=0.6):
        deck.append((col, np.clip((rad - start) / (1 - start), 0, 1) ** 1.6 * staerke))

    if stil == "tusche":
        mul = 0.93 + 0.07 * n("faser")
        vignette("#c9b28a", 0.4)
    elif stil == "aquarell":
        mul = (0.94 + 0.06 * n("korn")) * (1 - 0.0625 * n("wolke") - 0.02 * n("korn"))
        deck.append(("#f7f1e3", np.clip((rad - 0.72 + (n("wolke") - 0.5) * 0.2) / 0.2, 0, 1)))
    elif stil == "sepia":
        mul = (0.9 + 0.1 * n("faser")) * (0.92 + 0.08 * n("wolke"))
        vignette("#6b4423", 0.55)
    elif stil == "schatzkarte":
        mul = (0.85 + 0.15 * n("wolke")) * (0.92 + 0.08 * n("faser"))
        deck.append(("#2a160a", 0.8 * np.clip((rad - 0.8 + (n("rand") - 0.5) * 0.16) / 0.1, 0, 1)))
    elif stil == "abendlicht":
        deck.append(("#ffcf7a", 0.25 * np.clip(1 - np.hypot(xx - 0.85, yy - 0.1) / 1.2, 0, 1)))
        vignette("#3b1f2a", 0.55)
    elif stil == "farbdruck":
        mul = 0.95 + 0.05 * n("faser")
        vignette("#d8c8a0", 0.5)
    elif stil == "bleistift":
        mul = 0.94 + 0.06 * n("korn") * (0.5 + n("faser"))
    elif stil == "stich":
        mul = (0.92 + 0.08 * n("faser")) * (0.95 + 0.05 * n("wolke"))
        vignette("#a8885a", 0.45)

    mul_uri = None
    if mul is not None:
        g = (np.clip(mul, 0, 1) * 255).astype(np.uint8)
        mul_uri = webp_uri(Image.fromarray(np.dstack([g, g, g]), "RGB"), quality=84, method=0)
    deck_uri = None
    if deck:   # Schichten übereinander ("über"-Verknüpfung) zu einem Bild mit Transparenz
        rgb = np.zeros((res, res, 3), np.float32)
        a = np.zeros((res, res), np.float32)
        for col, al in deck:
            al = np.clip(al, 0, 1).astype(np.float32)
            neu = al + a * (1 - al)
            rgb = (np.asarray(_hex_rgb(col), np.float32) * al[..., None]
                   + rgb * (a * (1 - al))[..., None]) / np.maximum(neu, 1e-6)[..., None]
            a = neu
        img = np.dstack([np.clip(rgb, 0, 1) * 255, a * 255]).astype(np.uint8)
        deck_uri = webp_uri(Image.fromarray(img, "RGBA"), quality=84, method=0)
    return mul_uri, deck_uri


def muster(stil, s, W):
    """Regelmäßiges Muster über der Karte (Rasterpunkte, Schraffur) als SVG oder ""."""
    if stil == "farbdruck":   # Rasterpunkte wie im Druck
        d = 3.75 * s
        return (f'<pattern id="stilmuster" patternUnits="userSpaceOnUse" width="{_f(d)}" height="{_f(d)}" '
                f'patternTransform="rotate(15)"><circle cx="{_f(d / 2)}" cy="{_f(d / 2)}" r="{_f(d * 0.28)}" '
                f'fill="#3a2e22" fill-opacity="0.22"/></pattern>'
                f'<rect width="{W}" height="{W}" fill="url(#stilmuster)" style="mix-blend-mode:multiply"/>')
    if stil == "bleistift":   # feine schräge Schraffur
        d = 3.4 * s
        return (f'<pattern id="stilmuster" patternUnits="userSpaceOnUse" width="{_f(d)}" height="{_f(d)}" '
                f'patternTransform="rotate(-40)"><rect width="{_f(d)}" height="{_f(d * 0.35)}" fill="#55555a" '
                f'fill-opacity="0.13"/></pattern>'
                f'<rect width="{W}" height="{W}" fill="url(#stilmuster)" style="mix-blend-mode:multiply"/>')
    return ""
