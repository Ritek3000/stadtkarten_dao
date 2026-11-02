"""Exportiert ein Kartenmodell als reine Geometrie (JSON) für Blender: blender/stadtkarte_blender.py liest die Datei.

Blenders eigenes Python kennt weder shapely noch Pillow und kann den Generator deshalb nicht selbst starten. Dieses
Modul läuft in der normalen Umgebung der Stadtkarten, erzeugt die Karte und schreibt nur Zahlenlisten, die Blender
ohne Zusatzpakete einliest.

    python -m stadtkarte.blender_export beispiele/hafenstadt.yaml [-o datei.json] [--seed N]

Alle Koordinaten stehen in Kartenpixeln, im Bildkoordinatensystem (y zeigt nach unten) und schon in der Ausrichtung der
fertigen Karte (die Drehung zur Küstenlage ist eingerechnet). Blender spiegelt y und skaliert."""
import argparse
import contextlib
import io
import json
import math
import pathlib

import yaml
from shapely.geometry import box

from . import config
from .generator import generate
from .geo import lines, polys

FORMAT = "stadtkarte-blender"
VERSION = 1
RING_ROAD_WIDTH = 9.5      # wie in city.py: bis zu dieser Breite (mal s) sind Straßen Ringgassen, darüber Hauptstraßen
MIN_AREA = 0.5             # kleinere Flächen (px²) sind Rundungsreste
TOWER_RADIUS = 8.0         # Grundriss der Türme und Torhäuser wie im Kartenbild (render.py), in px mal s
GATE_SIZE = (34.0, 22.0)


class Frame:
    """Dreht Punkte so, wie render.py die ganze Karte dreht (um die Kartenmitte), und rundet auf 1/1000 px."""

    def __init__(self, m):
        a = math.radians(m["rot"])
        self.ca, self.sa, self.c, self.deg = math.cos(a), math.sin(a), m["W"] / 2, m["rot"]

    def pt(self, x, y):
        dx, dy = x - self.c, y - self.c
        return [round(self.c + dx * self.ca - dy * self.sa, 3), round(self.c + dx * self.sa + dy * self.ca, 3)]

    def ring(self, coords):
        pts = [self.pt(x, y) for x, y, *_ in coords]
        if len(pts) > 1 and pts[0] == pts[-1]:   # shapely wiederholt den ersten Punkt am Ende
            pts.pop()
        return pts

    def polygon(self, poly, **props):
        return {"ring": self.ring(poly.exterior.coords), "holes": [self.ring(i.coords) for i in poly.interiors], **props}

    def polygons(self, geom, **props):
        return [self.polygon(p, **props) for p in polys(geom) if p.area >= MIN_AREA]

    def line(self, ln, **props):
        pts = [self.pt(x, y) for x, y, *_ in ln.coords]
        closed = len(pts) > 2 and pts[0] == pts[-1]   # Inselufer und geschlossene Mauern sind Ringe
        if closed:
            pts.pop()
        return {"line": pts, "closed": closed, **props}


def _building_polys(b):
    """Ein Gebäude oder bei Häuserblöcken (Großstadt) die einzelnen Häuser des Blocks."""
    if b.get("form") == "block" and b.get("segments"):
        return [seg[0] for seg in b["segments"]]
    return [b["poly"]]


def _buildings(m, fr):
    out = []
    districts = m["districts"]

    def add(poly_list, kind, b):
        d = b.get("district", -1)
        dist = districts[d] if 0 <= d < len(districts) else None
        for p in poly_list:
            for part in polys(p):
                if part.area >= MIN_AREA:
                    out.append(fr.polygon(part, kind=kind, form=b.get("form") or "", poor=bool(b.get("poor")),
                                          district=dist["name"] if dist else "", district_type=dist["typ"] if dist else ""))

    for b in m["buildings"]:
        add(_building_polys(b), "landmark" if b.get("landmark") else "house", b)
    for b in m["suburbs"]:   # Vorstadthäuser vor den Toren
        add(_building_polys(b), "suburb", b)
    for fort in m["forts"]:
        for b in fort["buildings"]:
            add(_building_polys(b), "fort", b)
    return out


def _roads(m, fr):
    """Straßen, Landstraßen und Brücken. Dieselbe Linie kommt im Modell mehrfach vor (eine Straße über das Wasser ist
    zugleich Brücke, Festungsbrücken stehen auch in der Brückenliste); doppelte Streifen würden in Blender
    übereinanderliegen, deshalb zählt jede Linie einmal, und eine Brücke geht vor."""
    s = m["s"]
    found = [(ln, w, "side" if w <= RING_ROAD_WIDTH * s else "main") for ln, w in m["internal_roads"]]
    found += [(ln, w, "country") for ln, w in m["ext_roads"]]
    found += [(ln, w, "bridge") for ln, w in m["bridges"]]
    for fort in m["forts"]:
        found += [(ln, w, "side") for ln, w in fort["roads"]]
        found += [(ln, w, "bridge") for ln, w in fort["bridges"]]
    unique = {}
    for ln, w, cls in found:
        feat = fr.line(ln, width=round(w, 3), cls=cls)
        pts = [tuple(p) for p in feat["line"]]
        key = min(tuple(pts), tuple(reversed(pts)))   # gleiche Linie in beiden Richtungen
        if key not in unique or cls == "bridge":
            unique[key] = feat
    return list(unique.values())


def _shorelines(m, fr):
    """Ufer von Meer, Fluss und Inseln als Linien; der Kartenrand zählt nicht als Ufer."""
    W = m["W"]
    inner = box(0.6, 0.6, W - 0.6, W - 0.6)
    return [fr.line(ln) for ln in lines(m["water"].boundary.intersection(inner)) if ln.length > 1.0]


def _rect(x, y, angle, w, h, fr):
    """Rechteck w x h um (x, y), gedreht um angle Grad (SVG-Drehrichtung)."""
    a = math.radians(angle)
    ca, sa = math.cos(a), math.sin(a)
    return fr.ring([(x + ca * px - sa * py, y + sa * px + ca * py)
                    for px, py in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))])


def _octagon(x, y, r, fr):
    return fr.ring([(x + r * math.cos(math.pi / 8 + k * math.pi / 4), y + r * math.sin(math.pi / 8 + k * math.pi / 4))
                    for k in range(8)])


def _walls(m, fr):
    s = m["s"]
    towers = {}   # die Türme der Festung stehen auch in m["towers"]: nach Position nur einmal
    for x, y, _ in list(m["towers"]) + [t for fort in m["forts"] for t in fort["towers"]]:
        towers.setdefault((round(x, 2), round(y, 2)), (x, y))
    return {
        "walls": [fr.line(ln) for ln in m["wall"] if ln.length > 1.0],
        "towers": [{"ring": _octagon(x, y, TOWER_RADIUS * s, fr), "holes": []} for x, y in towers.values()],
        "gates": [{"ring": _rect(x, y, a, GATE_SIZE[0] * s, GATE_SIZE[1] * s, fr), "holes": []}
                  for x, y, a in m["gates"]],
    }


def export_model(m):
    """Kartenmodell (Ergebnis von generate) -> Wörterbuch, das sich unverändert als JSON speichern lässt."""
    fr = Frame(m)
    c = m["shape"].centroid
    radius = math.sqrt(m["shape"].area / math.pi)
    river_width = float(m["cfg"]["gelaende"].get("flussbreite", 0))
    waterways = []
    if m.get("river_line") is not None and not m["river_line"].is_empty:
        waterways = [fr.line(ln, width=river_width) for ln in lines(m["river_line"])]
    data = {
        "format": FORMAT, "version": VERSION,
        "meta": {"name": m["name"], "seed": m["cfg"]["seed"], "map_size": m["W"], "scale": m["s"],
                 "rotation": m["rot"], "center": fr.pt(c.x, c.y), "radius": round(radius, 3),
                 "unit": "px", "y_axis": "down"},
        "buildings": _buildings(m, fr),
        "roads": _roads(m, fr),
        "streets": [q for g in m["streets"] for q in fr.polygons(g)],
        "plazas": [q for g in list(m["plazas"]) + list(m["paved"]) for q in fr.polygons(g)],
        "piers": [q for g in m["piers"] for q in fr.polygons(g)],
        "water": fr.polygons(m["water"]),
        "land": fr.polygons(m["land"]),
        "shorelines": _shorelines(m, fr),
        "waterways": waterways,
    }
    data.update(_walls(m, fr))
    return data


def write(data, path):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser(prog="stadtkarte.blender_export",
                                 description="Erzeugt eine Stadtkarte und schreibt ihre Geometrie als JSON für Blender.")
    ap.add_argument("datei", help="Stadtbeschreibung (.yaml)")
    ap.add_argument("-o", "--ausgabe", help="Zieldatei (Standard: ausgabe/<name>_<seed>_blender.json)")
    ap.add_argument("--seed", type=int, help="überschreibt den Seed aus der Datei")
    args = ap.parse_args()

    with open(args.datei, encoding="utf-8") as fh:
        cfg = config.from_dict(yaml.safe_load(fh) or {})
    if args.seed is not None:
        cfg["seed"] = args.seed
    with contextlib.redirect_stdout(io.StringIO()) as hints:   # Hinweise des Generators bleiben sichtbar, aber gebündelt
        m = generate(cfg)
    if hints.getvalue().strip():
        print(hints.getvalue().strip())
    data = export_model(m)
    target = args.ausgabe or pathlib.Path("ausgabe") / f"{pathlib.Path(args.datei).stem}_{cfg['seed']}_blender.json"
    out = write(data, target)
    print(f"{m['name']}: {len(data['buildings'])} Gebäude, {len(data['roads'])} Straßen, {len(data['streets'])} Gassenflächen")
    print("  ->", out)


if __name__ == "__main__":
    main()
