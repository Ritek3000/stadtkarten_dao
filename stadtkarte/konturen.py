"""Zeichenstil "konturen": nur die Umrisse der Karte, schwarz auf weiß wie in einem Malbuch.

Wie alle Stile sitzt er als SVG-Filter über der gezeichneten Karte (siehe stile.py), die SVG-Datei bleibt eine Vektorkarte.
Der Filter zeichnet keine Flächen und keine Schraffur, sondern nur die Linien, an denen sich die Karte ändert:
Häuser, Straßen, Mauern, Wasser- und Waldränder, Felder, Bäume. Die Beschriftung bleibt (schwarz mit weißem Rand).

- Kanten: Eine feine und eine grobe Weichzeichnung der Karte werden voneinander abgezogen. Linie wird nur dort, wo ein
  Punkt dunkler ist als seine Umgebung (die dunklere Seite einer Grenze und jede dunkle Linie); so entsteht je Grenze ein
  einziger Strich statt zweier Streifen mit einer Lücke dazwischen. Jeder Farbkanal wird für sich geprüft, damit auch
  ein Farbwechsel ohne Helligkeitsunterschied (grünes Feld neben gelbem) eine Linie bekommt;
- Helligkeit vor dem Kantenfinden mit einer Wurzel gestaucht: Unterschiede im Dunkeln (Wald) zählen so viel wie im Hellen;
- harte Schwelle: Was schwächer ist als die Schwelle (Ziegelreihen, Schatten, Nebel), verschwindet; was darüber liegt,
  wird voll schwarz. Zwischen beiden liegt nur eine schmale Stufe, damit die Linien glatte Ränder haben;
- Der Boden wird ohne Körnung und Relief gezeichnet (render.land_svg), sonst fände der Filter darin nur Rauschen;
- ein schmaler Rand der Karte bleibt weiß: An der Kante des Filterbereichs entstünde sonst eine Linie.

Die Zwischenbilder sind deckend (Alpha 1), damit arithmetische Verknüpfungen das Alpha nicht verfälschen."""

import numpy as np

from .stile import _f, _matrix, _table

# Radien der beiden Weichzeichnungen in Kartenmaßen (mal s): die grobe bestimmt die Strichstärke, die feine, wie viel
# Einzelheit stehen bleibt
FEIN, GROB = 0.8, 2.4
GAMMA = 0.5            # Helligkeit vor dem Kantenfinden mit t ** GAMMA stauchen
SCHWELLE = (0.04, 0.09)  # Unterschied der Helligkeit (0..1), ab dem eine Linie beginnt und voll schwarz ist
RAND = 4.0             # weißer Rand der Karte in Kartenmaßen (mal s)


def _glatt(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def filter_teile(s, W):
    """Die Filterschritte für die Konturen (ohne <filter>-Hülle) auf einer Karte der Größe W; letzter Schritt liefert "out"."""
    a, b = SCHWELLE
    m = RAND * s
    umkehr = "".join(f'<feFunc{c} type="linear" slope="-1" intercept="1"/>' for c in "RGB")
    return [
        _matrix(np.eye(3), result="farbe"),   # RGB, Alpha 1
        '<feComponentTransfer in="farbe" result="gestaucht">'
        + "".join(f'<feFunc{c} type="gamma" amplitude="1" exponent="{_f(GAMMA)}" offset="0"/>' for c in "RGB")
        + "</feComponentTransfer>",
        f'<feGaussianBlur in="gestaucht" stdDeviation="{_f(FEIN * s)}" result="fein"/>',
        f'<feGaussianBlur in="gestaucht" stdDeviation="{_f(GROB * s)}" result="grob"/>',
        f'<feComponentTransfer in="grob" result="grobi">{umkehr}</feComponentTransfer>',
        # 0.5 + 0.5 * (fein - grob): kleiner als 0.5 heißt dunkler als die Umgebung
        '<feComposite in="fein" in2="grobi" operator="arithmetic" k2="0.5" k3="0.5" result="diff"/>',
        # je Farbkanal Tinte (1 = schwarz), die drei Kanäle addiert (höchstens 1) und umgekehrt: Schwarz auf Weiß
        _table(lambda t: _glatt(a, b, (0.5 - t) * 2), 257, "diff", "tinte"),
        '<feColorMatrix in="tinte" type="matrix" values="-1 -1 -1 0 1  -1 -1 -1 0 1  -1 -1 -1 0 1  0 0 0 0 1" '
        'result="linien"/>',
        # weißer Rand: innen die Linien, außen Weiß
        f'<feFlood x="{_f(m)}" y="{_f(m)}" width="{_f(W - 2 * m)}" height="{_f(W - 2 * m)}" flood-color="#000" '
        'result="innen"/>',
        '<feComposite in="linien" in2="innen" operator="in" result="mitte"/>',
        '<feFlood flood-color="#fff" result="weiss"/>',
        '<feMerge result="out"><feMergeNode in="weiss"/><feMergeNode in="mitte"/></feMerge>',
    ]
