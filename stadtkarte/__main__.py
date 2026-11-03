"""Kommandozeile:  python -m stadtkarte <stadt.yaml> [-o ausgabe] [--seed N]"""
import argparse
import pathlib
import time

from . import config, webpaket
from .generator import building_count, generate
from .interaktiv import interactive_html
from .parallel import png_async
from .render import prewarm, render_svg, split_labels, to_pdf


def main():
    ap = argparse.ArgumentParser(prog="stadtkarte", description="Erzeugt eine Stadtkarte aus einer YAML-Beschreibung.")
    ap.add_argument("datei", help="Stadtbeschreibung (.yaml)")
    ap.add_argument("-o", "--ausgabe", default="ausgabe", help="Zielordner (Standard: ausgabe)")
    ap.add_argument("--seed", type=int, help="überschreibt den Seed aus der Datei")
    ap.add_argument("--nacht", action="store_true", help="Nachtmodus (überschreibt die Datei)")
    args = ap.parse_args()

    try:   # fehlerhafte Angaben (und Eingaben, die der Generator ablehnt) als Meldung statt als Traceback
        raw = config.read_yaml(args.datei)
        cfg = config.from_dict(raw)
        if args.seed is not None:
            cfg["seed"] = args.seed
        if args.nacht:
            cfg["ausgabe"]["nacht"] = True
        t0 = time.time()
        prewarm(cfg)   # Texturen, die nicht von der Stadt abhängen, rechnen schon während des Generators
        m = generate(cfg)
    except (OSError, ValueError) as e:
        raise SystemExit(f"Fehler: {e}") from None
    svg = render_svg(m)
    out = pathlib.Path(args.ausgabe)
    out.mkdir(parents=True, exist_ok=True)
    suffix = "_nacht" if cfg["ausgabe"].get("nacht") else ""
    stem = out / f"{pathlib.Path(args.datei).stem}_{cfg['seed']}{suffix}"
    formats = [x.lower() for x in cfg["ausgabe"]["formate"]]
    written = []
    # PNG (mit Beschriftung) und Bild der interaktiven Karte (ohne) entstehen gleichzeitig in Render-Prozessen
    png_job = png_async(svg) if "png" in formats or "pdf" in formats else None
    base_job = png_async(split_labels(svg)[0]) if "html" in formats else None
    web_job = png_async(webpaket.base_svg(svg)) if "web" in formats else None
    if "svg" in formats:
        stem.with_suffix(".svg").write_text(svg, encoding="utf-8")
        written.append(stem.with_suffix(".svg"))
    if png_job is not None:
        png = png_job.result()
        if "png" in formats:
            stem.with_suffix(".png").write_bytes(png)
            written.append(stem.with_suffix(".png"))
        if "pdf" in formats:
            to_pdf(png, stem.with_suffix(".pdf"))
            written.append(stem.with_suffix(".pdf"))
    if "html" in formats:
        stem.with_suffix(".html").write_text(interactive_html(svg, cfg["name"], base_png=base_job.result()),
                                             encoding="utf-8")
        written.append(stem.with_suffix(".html"))
    if "web" in formats:   # Ordner <kennung>_web mit Kartenbild, Beschriftung, Ortsliste und Stadtbeschreibung
        folder = out / webpaket.folder_name(cfg)
        webpaket.write_folder(folder, webpaket.files(svg, webpaket.places(m), raw, cfg, web_job.result()))
        written.append(folder)
    print(f"{cfg['name']}: {building_count(m)} Gebäude, {len(m['trees'])} Bäume "
          f"({time.time() - t0:.1f} s)")
    for p in written:
        print("  ->", p)


if __name__ == "__main__":
    main()
