"""Kommandozeile:  python -m stadtkarte <stadt.yaml> [-o ausgabe] [--seed N]"""
import argparse
import pathlib
import time

from . import config
from .generator import generate
from .render import render_svg, to_pdf, to_png


def main():
    ap = argparse.ArgumentParser(prog="stadtkarte", description="Erzeugt eine Stadtkarte aus einer YAML-Beschreibung.")
    ap.add_argument("datei", help="Stadtbeschreibung (.yaml)")
    ap.add_argument("-o", "--ausgabe", default="ausgabe", help="Zielordner (Standard: ausgabe)")
    ap.add_argument("--seed", type=int, help="überschreibt den Seed aus der Datei")
    ap.add_argument("--nacht", action="store_true", help="Nachtmodus (überschreibt die Datei)")
    args = ap.parse_args()

    cfg = config.load(args.datei)
    if args.seed is not None:
        cfg["seed"] = args.seed
    if args.nacht:
        cfg["ausgabe"]["nacht"] = True
    t0 = time.time()
    m = generate(cfg)
    svg = render_svg(m)
    out = pathlib.Path(args.ausgabe)
    out.mkdir(parents=True, exist_ok=True)
    suffix = "_nacht" if cfg["ausgabe"].get("nacht") else ""
    stem = out / f"{pathlib.Path(args.datei).stem}_{cfg['seed']}{suffix}"
    formats = [x.lower() for x in cfg["ausgabe"]["formate"]]
    written = []
    if "svg" in formats:
        stem.with_suffix(".svg").write_text(svg, encoding="utf-8")
        written.append(stem.with_suffix(".svg"))
    if "png" in formats or "pdf" in formats:
        png = to_png(svg)
        if "png" in formats:
            stem.with_suffix(".png").write_bytes(png)
            written.append(stem.with_suffix(".png"))
        if "pdf" in formats:
            to_pdf(png, stem.with_suffix(".pdf"))
            written.append(stem.with_suffix(".pdf"))
    print(f"{cfg['name']}: {len(m['buildings']) + len(m['suburbs'])} Gebäude, {len(m['trees'])} Bäume "
          f"({time.time() - t0:.1f} s)")
    for p in written:
        print("  ->", p)


if __name__ == "__main__":
    main()
