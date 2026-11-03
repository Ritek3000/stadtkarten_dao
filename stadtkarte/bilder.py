"""Bilder als WebP: Data-URIs für die Texturen in der SVG-Karte, Bytes für Downloads und Pakete."""
import base64
import io

from PIL import Image


def webp_bytes(img, **kw):
    """PIL-Bild als WebP-Bytes (kw: quality, alpha_quality, method ...)."""
    buf = io.BytesIO()
    img.save(buf, "WEBP", **kw)
    return buf.getvalue()


def webp_uri(img, **kw):
    """PIL-Bild als WebP-Data-URI, zum Einbetten in die SVG-Karte."""
    return "data:image/webp;base64," + base64.b64encode(webp_bytes(img, **kw)).decode()


def png_to_webp(png, quality):
    """PNG-Bytes als WebP (ohne Transparenz) neu kodieren."""
    return webp_bytes(Image.open(io.BytesIO(png)).convert("RGB"), quality=quality)
