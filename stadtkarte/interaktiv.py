"""Interaktive Karte: eine einzelne HTML-Datei, die ohne Internet und ohne weitere Dateien im Browser läuft.

Die Karte ohne Beschriftung ist als Bild eingebettet, die Beschriftung liegt als Vektorebene darüber (bleibt beim
Vergrößern scharf). Jede Art von Beschriftung lässt sich einzeln ein- und ausblenden.
"""
import base64
import io
from html import escape

from PIL import Image

from .bilder import webp_bytes
from .render import font_face_css, split_labels, to_png

# Gruppen-ID aus render_svg -> Beschriftung des Schalters
GROUPS = [("b-titel", "Stadtname"), ("b-viertel", "Viertel"), ("b-orte", "Orte und Festungen"),
          ("b-legende", "Legende")]

PAGE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{font}
* {{ box-sizing: border-box; }}
/* Leiste in den Farben des Design Systems „Die Alte Ordnung“ (Finsternis): Staubschwarz, Gold, Haarlinien */
html, body {{ margin: 0; height: 100%; overflow: hidden; background: #12100e; color: #ece3cf;
  font-family: 'EB Garamond', Georgia, serif; }}
#ansicht {{ position: fixed; inset: 0; cursor: grab; touch-action: none; }}
#ansicht.ziehen {{ cursor: grabbing; }}
#karte {{ position: absolute; left: 0; top: 0; width: {W}px; height: {W}px; transform-origin: 0 0; }}
#karte img, #karte svg {{ position: absolute; inset: 0; width: 100%; height: 100%; user-select: none; }}
#karte svg {{ pointer-events: none; }}
#leiste {{ position: fixed; top: 12px; left: 12px; max-width: calc(100% - 24px); padding: 10px 14px;
  background: rgba(18, 16, 14, 0.86); -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
  border: 1px solid rgba(204, 180, 84, 0.24); border-radius: 0; font-size: 17px; }}
#leiste::before, #leiste::after {{ content: ""; position: absolute; width: 18px; height: 18px; border: 1px solid #ccb454; }}
#leiste::before {{ top: -1px; left: -1px; border-right: 0; border-bottom: 0; }}
#leiste::after {{ bottom: -1px; right: -1px; border-left: 0; border-top: 0; }}
#leiste h1 {{ margin: 0 0 6px; font-size: 22px; font-weight: 400; letter-spacing: 0.04em; }}
#leiste label {{ display: block; padding: 2px 0; cursor: pointer; color: #b6aa93; }}
#leiste label:hover {{ color: #ece3cf; }}
#leiste label.alle {{ color: #ece3cf; border-bottom: 1px solid rgba(204, 180, 84, 0.24); margin-bottom: 3px; }}
#leiste input {{ accent-color: #ccb454; margin-right: 6px; }}
#leiste .knoepfe {{ display: flex; gap: 6px; margin-top: 8px; }}
#leiste button {{ font: inherit; font-size: 15px; color: inherit; background: none; border: 1px solid #ccb454;
  border-radius: 2px; padding: 2px 10px; cursor: pointer; transition: background-color .24s ease, color .24s ease; }}
#leiste button:hover, #leiste button:focus-visible {{ background: #ccb454; color: #191210; }}
#leiste :focus-visible {{ outline: 1px solid #ccb454; outline-offset: 4px; }}
#leiste .tipp {{ margin-top: 6px; font-size: 13px; color: #b6aa93; }}
#leiste.zu .inhalt {{ display: none; }}
#leiste.zu h1 {{ margin: 0; }}
#leiste h1 {{ cursor: pointer; }}
</style>
</head>
<body>
<div id="ansicht"><div id="karte">
<img src="data:image/webp;base64,{image}" alt="{title}" draggable="false">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {W}">{labels}</svg>
</div></div>
<div id="leiste">
<h1 title="Menü ein-/ausklappen">{title}</h1>
<div class="inhalt">
<label class="alle"><input type="checkbox" id="alle" checked>Beschriftung</label>
{toggles}
<div class="knoepfe"><button id="kleiner" title="Verkleinern">−</button><button id="ganz" title="Ganze Karte">Ganz</button>
<button id="groesser" title="Vergrößern">+</button></div>
<div class="tipp">Mausrad zoomt, Ziehen verschiebt, Taste B blendet die Beschriftung aus</div>
</div>
</div>
<script>
"use strict";
const W = {W};
const ansicht = document.getElementById("ansicht"), karte = document.getElementById("karte");

// Beschriftung ein-/ausblenden
const schalter = [...document.querySelectorAll("input[data-gruppe]")];
const alle = document.getElementById("alle");
for (const s of schalter) {{
  const g = document.getElementById(s.dataset.gruppe);
  if (!g || !g.childElementCount) s.parentElement.hidden = true;   // z.B. Karte ohne Legende
}}
const sichtbar = () => schalter.filter(s => !s.parentElement.hidden);
function anwenden() {{
  for (const s of schalter) document.getElementById(s.dataset.gruppe).style.display = s.checked ? "" : "none";
  const an = sichtbar().filter(s => s.checked).length;
  alle.checked = an > 0;
  alle.indeterminate = an > 0 && an < sichtbar().length;
}}
schalter.forEach(s => s.addEventListener("change", anwenden));
alle.addEventListener("change", () => {{ sichtbar().forEach(s => s.checked = alle.checked); anwenden(); }});
document.addEventListener("keydown", e => {{
  if (e.key === "b" || e.key === "B") {{ alle.checked = !alle.checked; alle.dispatchEvent(new Event("change")); }}
}});
document.querySelector("#leiste h1").addEventListener("click", () => document.getElementById("leiste").classList.toggle("zu"));

// Zoomen und Verschieben
let zoom = 1, x = 0, y = 0, minZoom = 0.05;
const maxZoom = 8;
function zeigen() {{ karte.style.transform = `translate(${{x}}px, ${{y}}px) scale(${{zoom}})`; }}
function ganz() {{
  zoom = minZoom = Math.min(innerWidth / W, innerHeight / W);
  x = (innerWidth - W * zoom) / 2; y = (innerHeight - W * zoom) / 2; zeigen();
}}
function zoomen(f, cx = innerWidth / 2, cy = innerHeight / 2) {{
  const neu = Math.max(minZoom * 0.5, Math.min(maxZoom, zoom * f));
  x = cx - (cx - x) * neu / zoom; y = cy - (cy - y) * neu / zoom; zoom = neu; zeigen();
}}
document.getElementById("ganz").onclick = ganz;
document.getElementById("groesser").onclick = () => zoomen(1.4);
document.getElementById("kleiner").onclick = () => zoomen(1 / 1.4);
ansicht.addEventListener("wheel", e => {{ e.preventDefault(); zoomen(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY); }},
  {{passive: false}});
ansicht.addEventListener("dblclick", e => zoomen(2, e.clientX, e.clientY));
const zeiger = new Map();
let abstand = 0;
ansicht.addEventListener("pointerdown", e => {{
  zeiger.set(e.pointerId, {{x: e.clientX, y: e.clientY}}); ansicht.setPointerCapture(e.pointerId);
  ansicht.classList.add("ziehen");
}});
ansicht.addEventListener("pointermove", e => {{
  const alt = zeiger.get(e.pointerId); if (!alt) return;
  const neu = {{x: e.clientX, y: e.clientY}}; zeiger.set(e.pointerId, neu);
  if (zeiger.size === 2) {{   // zwei Finger: Pinch-Zoom um die Mitte
    const [a, b] = [...zeiger.values()];
    const d = Math.hypot(a.x - b.x, a.y - b.y);
    if (abstand) zoomen(d / abstand, (a.x + b.x) / 2, (a.y + b.y) / 2);
    abstand = d;
  }} else if (zeiger.size === 1) {{
    x += neu.x - alt.x; y += neu.y - alt.y; zeigen();
  }}
}});
function loslassen(e) {{ zeiger.delete(e.pointerId); abstand = 0; if (!zeiger.size) ansicht.classList.remove("ziehen"); }}
ansicht.addEventListener("pointerup", loslassen);
ansicht.addEventListener("pointercancel", loslassen);
addEventListener("resize", ganz);
anwenden(); ganz();
</script>
</body>
</html>
"""


def interactive_html(svg, name, quality=90, base_png=None):
    """Baut aus einer fertigen Karte (render_svg) die interaktive HTML-Datei. base_png: bereits gerenderte Karte
    ohne Beschriftung (spart ein erneutes Rendern)."""
    base, labels = split_labels(svg)
    img = Image.open(io.BytesIO(base_png or to_png(base)))
    image = webp_bytes(img.convert("RGB"), quality=quality)
    toggles = "\n".join(f'<label><input type="checkbox" data-gruppe="{gid}" checked>{text}</label>'
                        for gid, text in GROUPS)
    return PAGE.format(title=escape(name), font=font_face_css(), W=img.width, image=base64.b64encode(image).decode(),
                       labels=labels, toggles=toggles)
