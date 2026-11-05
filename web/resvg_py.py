"""Ersatz für das Paket resvg-py im Browser: rendert mit resvg-wasm, demselben Renderer als WebAssembly.

resvg-wasm kann keine WebP-Bilder lesen; die Texturen der Karte sind aber als WebP eingebettet. Sie werden daher vor
dem Rendern einmal nach PNG umgewandelt (das Ergebnis bleibt im Zwischenspeicher, Vorschau, Ansicht und Download nutzen
dieselben Texturen). Danach ist das Bild bis auf Rundungen in einzelnen Pixeln gleich dem am Rechner.
"""
import base64
import io
import re

import js
from PIL import Image

_WEBP = re.compile(r"data:image/webp;base64,([A-Za-z0-9+/=]+)")
_PNG = {}


def _png_uri(m):
    data = m.group(1)
    uri = _PNG.get(data)
    if uri is None:
        buf = io.BytesIO()
        Image.open(io.BytesIO(base64.b64decode(data))).save(buf, "PNG", compress_level=1)
        uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        if len(_PNG) > 24:
            _PNG.clear()
        _PNG[data] = uri
    return uri


def svg_to_bytes(svg_string, zoom=None, font_files=None, **_):
    svg = _WEBP.sub(_png_uri, svg_string)
    png = js.stadtkarteRender(svg, float(zoom or 0), js.Array.of(*(str(f) for f in font_files or ())))
    return png.to_bytes()
