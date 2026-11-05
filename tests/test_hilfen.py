"""Gemeinsame Hilfsfunktionen: Geometrie (geo) und Bildkodierung (bilder)."""
import base64
import io
import math
import random
import unittest
from unittest import mock

from PIL import Image
import shapely.affinity
import shapely.geometry.base
from shapely.geometry import LineString, Polygon, box

from stadtkarte import bilder, geo, roofs, shapes, terrain


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


class Rechteck(unittest.TestCase):
    """geo.fit_rect: größtes Rechteck im Grundstück. Die Sollwerte stammen aus der Fassung mit GEOS-Verschneidungen;
    die jetzige rechnet im Achsensystem des Grundstücks ohne GEOS. Beim Trapez rückt das Rechteck um 0,0008 px, weil der
    Toleranzrand von 0,05 bzw. 0,15 px jetzt Gehrung statt runder Ecken hat; sonst sind die Ecken dieselben."""

    def pruefe(self, poly, soll):
        rect = geo.fit_rect(poly, 4.0, 3.2)
        ist = list(rect.exterior.coords)
        self.assertEqual(len(ist), len(soll))
        for (x, y), (sx, sy) in zip(ist, soll):
            self.assertAlmostEqual(x, sx, places=3)
            self.assertAlmostEqual(y, sy, places=3)

    def test_gedrehtes_rechteck_bleibt_ganz(self):
        poly = shapely.affinity.rotate(Polygon([(0, 0), (30, 0), (30, 12), (0, 12)]), 25, origin=(0, 0))
        self.pruefe(poly, [(0.0, 0.0), (27.1892, 12.6785), (22.1178, 23.5542), (-5.0714, 10.8757), (0.0, 0.0)])

    def test_trapez(self):
        poly = Polygon([(0, 0), (40, 0), (34, 14), (6, 14)])
        self.pruefe(poly, [(6.1489, 13.72), (33.8503, 13.72), (33.8503, 0.28), (6.1489, 0.28), (6.1489, 13.72)])

    def test_l_form_wird_auf_den_laengeren_schenkel_gekuerzt(self):
        poly = Polygon([(0, 0), (30, 0), (30, 10), (12, 10), (12, 28), (0, 28)])
        self.pruefe(poly, [(0.0, 0.0), (11.7317, 0.0), (11.7317, 28.0), (0.0, 28.0), (0.0, 0.0)])


class FlaechenOhneGeos(unittest.TestCase):
    """geo.local_rings und geo.area_in_box ersetzen beim Einpassen der Häuser die GEOS-Verschneidung. Sie müssen
    dieselben Flächen liefern wie Shapely, auch bei einspringenden Ecken und Löchern."""

    def test_flaeche_im_rechteck_wie_shapely(self):
        rng = random.Random(5)
        o, u, v = (3.0, -2.0), (math.cos(0.4), math.sin(0.4)), (-math.sin(0.4), math.cos(0.4))
        lot = Polygon([(0, 0), (30, 4), (26, 12), (34, 20), (8, 26), (-2, 14)], [[(8, 8), (14, 8), (12, 14)]])
        rings = geo.local_rings(lot, o, u, v)
        for _ in range(200):
            a0, b0 = rng.uniform(-15, 30), rng.uniform(-30, 20)
            a1, b1 = a0 + rng.uniform(0.5, 25), b0 + rng.uniform(0.5, 25)
            corners = [(o[0] + u[0] * a + v[0] * b, o[1] + u[1] * a + v[1] * b) for a, b in ((a0, b0), (a1, b0), (a1, b1), (a0, b1))]
            self.assertAlmostEqual(geo.area_in_box(rings, a0, a1, b0, b1), lot.intersection(Polygon(corners)).area, places=6)

    def test_mehrteilige_flaeche(self):
        teile = box(0, 0, 4, 4).union(box(10, 0, 12, 2))
        rings = geo.local_rings(teile, (0, 0), (1, 0), (0, 1))
        self.assertEqual(len(rings), 2)
        self.assertAlmostEqual(geo.area_in_box(rings, -1, 20, -1, 20), 20)
        self.assertAlmostEqual(geo.area_in_box(rings, 3, 11, 1, 3), 2 + 1)


class Walmdach(unittest.TestCase):
    """geo.hip_planes: konvexe Grundrisse exakt über Halbebenen, die übrigen über die Voronoi-Zerlegung."""

    def pruefe_zerlegung(self, poly, flaechen):
        self.assertEqual(len(flaechen), len(poly.exterior.coords) - 1)
        self.assertAlmostEqual(sum(f[0].area for f in flaechen), poly.area, places=6)
        for i, a in enumerate(flaechen):
            for b in flaechen[i + 1:]:
                self.assertLess(a[0].intersection(b[0]).area, 1e-6)   # keine Überlappung

    def test_konvexe_formen_zerfallen_genau_in_ihre_dachflaechen(self):
        for poly in (Polygon([(0, 0), (30, 0), (30, 14), (15, 22), (0, 14)]),
                     Polygon([(15, 0), (30, 10), (15, 20), (0, 10)]),
                     Polygon([(5, 0), (25, 0), (30, 5), (30, 13), (25, 18), (5, 18), (0, 13), (0, 5)]),
                     shapely.affinity.rotate(Polygon([(0, 0), (28, 2), (31, 15), (3, 19)]), 20)):
            self.assertIsNotNone(geo._convex_hip_planes(poly))
            self.pruefe_zerlegung(poly, geo.hip_planes(poly)[0])

    def test_trapez_hat_first_und_vier_grate(self):
        flaechen, grate = geo.hip_planes(Polygon([(0, 0), (32, 0), (26, 16), (4, 16)]))
        self.assertEqual(len(grate), 5)
        first = [g for g in grate if abs(g.coords[0][1] - g.coords[-1][1]) < 1e-6]   # waagrecht, in halber Höhe
        self.assertEqual(len(first), 1)
        self.assertAlmostEqual(first[0].coords[0][1], 8.0)
        for f, n, rd, traufe, tiefe in flaechen:   # Tiefe: größter Abstand der Fläche zur eigenen Traufe
            self.assertGreater(tiefe, 0.5)
            self.assertAlmostEqual(math.hypot(*n), 1.0)

    def test_grate_beginnen_einen_viertel_pixel_neben_der_wand(self):
        poly = Polygon([(0, 0), (30, 0), (30, 14), (15, 22), (0, 14)])
        for g in geo.hip_planes(poly)[1]:
            self.assertGreaterEqual(poly.exterior.distance(g), 0.25 - 1e-9)

    def test_einspringende_ecke_nimmt_die_voronoi_zerlegung(self):
        winkel = Polygon([(0, 0), (30, 0), (30, 10), (12, 10), (12, 22), (0, 22)])
        self.assertIsNone(geo._convex_hip_planes(winkel))
        flaechen, grate = geo.hip_planes(winkel)
        self.assertEqual(len(flaechen), 6)
        self.assertTrue(grate)

    def test_ergebnis_wird_gemerkt_und_nicht_geteilt(self):
        poly = Polygon([(0, 0), (20, 0), (24, 9), (2, 12)])
        a, b = geo.hip_planes(poly), geo.hip_planes(poly)
        self.assertEqual([f[0].wkb for f in a[0]], [f[0].wkb for f in b[0]])
        a[0].clear()
        self.assertTrue(geo.hip_planes(poly)[0])   # wer die Liste ändert, ändert nicht den Zwischenspeicher


class Hausformen(unittest.TestCase):
    """shapes._halfplanes und shapes._largest_scale: Bei konvexen Grundstücken steht der größte Faktor, mit dem eine
    Hausform hineinpasst, direkt fest. Er muss mit der Prüfung durch GEOS übereinstimmen."""

    def test_konvex_oder_nicht(self):
        self.assertIsNotNone(shapes._halfplanes(Polygon([(0, 0), (20, 0), (24, 9), (2, 12)])))
        self.assertIsNone(shapes._halfplanes(Polygon([(0, 0), (30, 0), (30, 10), (12, 10), (12, 22), (0, 22)])))
        self.assertIsNone(shapes._halfplanes(box(0, 0, 10, 10).difference(box(4, 4, 6, 6))))

    def test_groesster_faktor_wie_geos(self):
        lot = Polygon([(0, 0), (26, -2), (30, 14), (4, 17)])
        planes = shapes._halfplanes(lot)
        for pts in ([(2, 1), (24, 1), (24, 8), (12, 8), (12, 15), (2, 15)],          # L-Form
                    [(3, 2), (25, 2), (25, 10), (14, 16), (3, 10)]):              # Fünfeck
            c = (14.0, 7.0)
            k = shapes._largest_scale(planes, pts, c)
            scaled = lambda f: Polygon([(c[0] + (x - c[0]) * f, c[1] + (y - c[1]) * f) for x, y in pts])
            self.assertTrue(lot.buffer(1e-6).contains(scaled(k)))
            self.assertFalse(lot.contains(scaled(k * 1.001)))


class Ziegelreihen(unittest.TestCase):
    """roofs._clip_line ersetzt LineString(a, b).intersection(Dachfläche) für die Ziegelreihen; dieselben Stücke in
    derselben Richtung, auch bei einspringenden Ecken, Löchern, Strecken mit Ende in der Fläche und durch Ecken."""

    def stuecke_wie_shapely(self, flaeche, a, b):
        ist = roofs._clip_line(roofs._edges(flaeche), a, b)
        soll = [ln for ln in geo.lines(LineString([a, b]).intersection(flaeche)) if ln.length > 1e-9]
        self.assertEqual(len(ist), len(soll))
        for (x0, y0, x1, y1), ln in zip(sorted(ist), sorted(soll, key=lambda ln: ln.coords[0])):
            (sx0, sy0), (sx1, sy1) = ln.coords[0], ln.coords[-1]
            for v, sv in ((x0, sx0), (y0, sy0), (x1, sx1), (y1, sy1)):
                self.assertAlmostEqual(v, sv, places=9)

    def test_zufaellige_strecken(self):
        rng = random.Random(9)
        winkel = Polygon([(0, 0), (30, 0), (30, 10), (12, 10), (12, 22), (0, 22)], [[(3, 3), (8, 3), (8, 6), (3, 6)]])
        for _ in range(300):
            a = (rng.uniform(-10, 40), rng.uniform(-10, 30))
            b = (rng.uniform(-10, 40), rng.uniform(-10, 30))
            self.stuecke_wie_shapely(winkel, a, b)

    def test_durch_eine_ecke_und_mit_ende_innen(self):
        raute = Polygon([(15, 0), (30, 10), (15, 20), (0, 10)])
        self.stuecke_wie_shapely(raute, (-5, 10), (35, 10))      # durch zwei Ecken
        self.stuecke_wie_shapely(raute, (10, 10), (40, 10))      # beginnt in der Fläche
        self.assertEqual(roofs._clip_line(roofs._edges(raute), (-5, 30), (35, 30)), [])   # daneben


class Inseln(unittest.TestCase):
    def test_kuestenstreifen_wird_nur_einmal_berechnet(self):
        """sea.buffer(-25 * s) ist für alle Inselkandidaten gleich. Es je Kandidat neu zu berechnen kostet auf einer langen
        Küste bis zu 36 ms pro Kandidat."""
        meer = box(0, 0, 2000, 600)
        aufrufe = []
        echt = shapely.geometry.base.BaseGeometry.buffer

        def zaehlen(self, distance, *args, **kwargs):
            if distance < 0:
                aufrufe.append(distance)
            return echt(self, distance, *args, **kwargs)
        with mock.patch.object(shapely.geometry.base.BaseGeometry, "buffer", zaehlen):
            inseln = terrain.make_islands(random.Random(3), 2000, 1.0, meer, lambda x: 520.0, 6)
        self.assertGreaterEqual(len(inseln), 2)
        self.assertEqual(len(aufrufe), 1)


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
