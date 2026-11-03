"""Gemeinsame Hilfsfunktionen: Geometrie (geo) und Bildkodierung (bilder)."""
import base64
import io
import math
import unittest

from PIL import Image
from shapely.geometry import Polygon, box

from stadtkarte import bilder, geo


class Geometrie(unittest.TestCase):
    def test_oriented_rect_waagrecht(self):
        r = geo.oriented_rect(10, 20, 1, 0, 8, 4)
        self.assertEqual(r.bounds, (6, 18, 14, 22))
        self.assertAlmostEqual(r.area, 32)

    def test_oriented_rect_gedreht(self):
        r = geo.oriented_rect(0, 0, 0, 1, 8, 4)   # lange Seite zeigt nach unten
        self.assertEqual(tuple(round(v, 6) for v in r.bounds), (-2, -4, 2, 4))

    def test_rings_mit_loch(self):
        flaeche = box(0, 0, 10, 10).difference(box(4, 4, 6, 6))
        (ring, loecher), = geo.rings(flaeche)
        self.assertEqual(len(ring), 5)
        self.assertEqual(len(loecher), 1)
        self.assertEqual(geo.rings(None), [])
        self.assertEqual(geo.rings(Polygon()), [])

    def test_schiffsgrundflaeche(self):
        waagrecht = geo.ship_footprint(0, 0, 40, 10, 0)
        self.assertAlmostEqual(waagrecht.area, 400)
        self.assertEqual(tuple(round(v, 6) for v in waagrecht.bounds), (-20, -5, 20, 5))
        senkrecht = geo.ship_footprint(0, 0, 40, 10, 90)
        self.assertEqual(tuple(round(v, 6) for v in senkrecht.bounds), (-5, -20, 5, 20))
        self.assertTrue(math.isclose(senkrecht.area, 400))


class Bilder(unittest.TestCase):
    def setUp(self):
        self.img = Image.new("RGB", (16, 16), (200, 30, 30))

    def test_webp_uri_ist_ein_lesbares_webp(self):
        uri = bilder.webp_uri(self.img, quality=80, method=0)
        self.assertTrue(uri.startswith("data:image/webp;base64,"))
        roh = base64.b64decode(uri.split(",", 1)[1])
        self.assertEqual(roh[:4], b"RIFF")
        self.assertEqual(Image.open(io.BytesIO(roh)).size, (16, 16))

    def test_png_zu_webp(self):
        png = io.BytesIO()
        Image.new("RGBA", (8, 6), (0, 0, 0, 0)).save(png, "PNG")
        webp = Image.open(io.BytesIO(bilder.png_to_webp(png.getvalue(), 90)))
        self.assertEqual((webp.format, webp.size, webp.mode), ("WEBP", (8, 6), "RGB"))


if __name__ == "__main__":
    unittest.main()
