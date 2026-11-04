"""Regressionstests des Generators. Die langsamen Fälle (Karte erzeugen und zeichnen, je einige Sekunden) lassen sich
mit STADTKARTE_SCHNELL=1 überspringen."""
import contextlib
import io
import math
import os
import pathlib
import subprocess
import sys
import re
import tempfile
import threading
import unittest
from unittest import mock

import shapely
import yaml
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import nearest_points, unary_union

from stadtkarte import config, fortress, generator, render, umgebung
from stadtkarte.city import CityBuilder, round_kinks
from stadtkarte.generator import generate
from stadtkarte.render import bold_width, render_svg
from stadtkarte.surroundings import make_bridges
from tests.golden import beispiel, klein

ROOT = pathlib.Path(__file__).resolve().parents[1]


def hinweiskarte():
    """Kleine Stadt, in der für den Dom kein Platz ist: der Generator gibt genau einen Hinweis aus."""
    return klein(seed=9, stadtform="oval", orte=[{"name": "Dom", "typ": "kathedrale"}],
                 ausgabe={"bildgroesse": 400, "formate": ["svg"]})


HINWEISE = ["Kein passender Block für 'Dom' gefunden."]


class Hinweise(unittest.TestCase):
    """Die Hinweise des Generators stehen im Kartenmodell (m["hints"]), nicht auf der Konsole."""

    def test_hinweise_stehen_im_modell_und_nicht_auf_der_konsole(self):
        ausgabe = io.StringIO()
        with contextlib.redirect_stdout(ausgabe):
            m = generate(config.from_dict(hinweiskarte()))
        self.assertEqual(ausgabe.getvalue(), "")
        self.assertEqual(m["hints"], HINWEISE)
        self.assertEqual(generator.hint_lines(m), ["Hinweis: " + HINWEISE[0]])

    def test_jede_karte_hat_ihre_eigene_liste(self):
        a = generate(config.from_dict(hinweiskarte()))
        b = generate(config.from_dict(hinweiskarte()))
        self.assertIsNot(a["hints"], b["hints"])
        self.assertEqual((a["hints"], b["hints"]), (HINWEISE, HINWEISE))   # nichts sammelt sich über Karten hinweg an

    def test_gleichzeitig_erzeugte_karten_vermischen_ihre_hinweise_nicht(self):
        mit, ohne = hinweiskarte(), klein(seed=3, ausgabe={"bildgroesse": 400})
        ergebnis = {}

        def erzeugen(name, raw):
            ergebnis[name] = generate(config.from_dict(raw))["hints"]
        ausgabe = io.StringIO()
        with contextlib.redirect_stdout(ausgabe):
            threads = [threading.Thread(target=erzeugen, args=a) for a in (("mit", mit), ("ohne", ohne))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(ausgabe.getvalue(), "")
        self.assertEqual(ergebnis, {"mit": HINWEISE, "ohne": []})

    def test_auch_das_nur_gelaende_hat_eine_liste(self):
        self.assertEqual(generate(config.from_dict(klein(stadtform="eigene")))["hints"], [])

    def test_kommandozeile_und_blender_export_geben_die_hinweise_aus(self):
        with tempfile.TemporaryDirectory() as tmp:
            datei = pathlib.Path(tmp) / "hinweis.yaml"
            datei.write_text(yaml.safe_dump(hinweiskarte(), allow_unicode=True), encoding="utf-8")
            for modul, extra in (("stadtkarte", ["-o", tmp]), ("stadtkarte.blender_export", ["-o", f"{tmp}/b.json"])):
                with self.subTest(modul):
                    res = subprocess.run([sys.executable, "-m", modul, str(datei), *extra], capture_output=True,
                                         text=True, encoding="utf-8", cwd=ROOT, timeout=200)
                    self.assertEqual(res.returncode, 0, res.stderr)
                    self.assertIn("Hinweis: " + HINWEISE[0], res.stdout.splitlines())


class Festung(unittest.TestCase):
    """Findet sich für die Festung nirgends ein Platz, gibt es keine Festung und einen Hinweis. Den Platzmangel erzeugt
    der Test, indem er der Festung verdorbene Geländedaten gibt (Wasser überall)."""

    def test_ohne_jeden_platz_gibt_es_keine_festung(self):
        echt = generator.build_fortress

        def mit_wasser_ueberall(rng, W, s, spec, terrain, city, ext_roads, islands, hints):
            return echt(rng, W, s, spec, {**terrain, "water": box(-W, -W, 2 * W, 2 * W)}, city, ext_roads, islands, hints)
        roh = klein(orte=[{"name": "Burg", "typ": "festung", "lage": "land", "kuerzel": "B"}],
                    ausgabe={"bildgroesse": 300, "formate": ["svg"]})
        with mock.patch.object(generator, "build_fortress", mit_wasser_ueberall):
            m = generate(config.from_dict(roh))
        self.assertEqual(m["forts"], [])
        self.assertEqual([h for h in m["hints"] if "Festung" in h],
                         ["Kein Platz für eine Zitadelle in der Mauer - Festung vor der Stadt.",
                          "Kein Platz für die Festung gefunden."])


class Inselsuche(unittest.TestCase):
    def test_flussflaeche_wird_nur_einmal_berechnet(self):
        """Die Fläche des Flusses außerhalb des Meeres ist für alle Kandidaten gleich. Sie je Kandidat neu zu berechnen
        (sea.buffer(-1) auf der langen Küste) machte die Inselsuche zum Zeitfresser: bis zu 24 s statt unter 1 s."""
        sea = box(0, 0, 1000, 600)                   # Meer im Norden, Stadt darunter
        stadt = box(0, 600, 1000, 1000)
        fluss = box(-10, 560, 1010, 700)             # überquert die Küste: Kandidaten nahe der Küste fallen weg
        differenzen = []
        echt = shapely.geometry.base.BaseGeometry.difference

        def zaehlen(self, other, *args, **kwargs):
            differenzen.append(1)
            return echt(self, other, *args, **kwargs)
        with mock.patch.object(shapely.geometry.base.BaseGeometry, "difference", zaehlen):
            p = fortress._sea_site(1.0, sea, fluss, stadt, Point(500, 400), [])
        self.assertIsNotNone(p)
        self.assertEqual(len(differenzen), 1)
        self.assertGreater(p.distance(stadt), 120)   # Inselplatz 120 bis 230 vor der Stadt
        self.assertFalse(Point(p).buffer(80 + 25).intersects(fluss))


class Bruecken(unittest.TestCase):
    """Die Maske, die die Fahrbahn einer Brücke am Ufer ausblendet, gilt nur auf den Brücken. Weichgezeichnet wird daher
    nur das Wasser rund um die Brücken und nicht die ganze Wasserfläche: resvg rechnete den Weichzeichner sonst für jede
    Brücke über der ganzen Karte (bei voller Größe fast eine Sekunde je Brücke)."""

    def test_maske_deckt_nur_die_umgebung_der_bruecken(self):
        roh = klein(ausgabe={"bildgroesse": 300, "formate": ["svg"]})
        m = generate(config.from_dict(roh))
        svg = render_svg(m, nacht=False)
        self.assertTrue(m["bridges"])
        maske = re.search(r'<mask id="bridgeFade"[^>]*><path d="([^"]*)"', svg).group(1)
        wasser = re.search(r'<clipPath id="bridgeWet"><path d="([^"]*)"', svg).group(1)
        self.assertLess(len(maske), 0.1 * len(wasser))   # statt der ganzen Wasserfläche nur die Umgebung der Brücken
        ringe = [Polygon([tuple(map(float, pt.split(","))) for pt in ring.split("L")]) for ring in re.findall(r"M([^MZ]*)Z", maske)]
        flaeche = unary_union([r.buffer(0) for r in ringe]).buffer(0.2)   # der Pfad ist auf 0,1 gerundet
        for ln, _ in m["bridges"]:
            ueber_wasser = ln.intersection(m["water"])
            self.assertFalse(ueber_wasser.is_empty)
            self.assertTrue(flaeche.contains(ueber_wasser), "die Maske muss das Wasser unter jeder Brücke decken")


def stadt_am_fluss():
    """Stadt ohne Mauer (9000 Einwohner) am Fluss, deren Torstraßen früher an einer Flussbiegung abgeschnitten wurden und als
    Stummel am Ufer endeten."""
    return {"name": "T70", "seed": 737201, "einwohner": 9000, "stadtform": "vieleck",
            "gelaende": {"biotop": "gemaessigt", "kueste": "sued", "fluss": True, "flussbreite": 40, "inseln": 2,
                         "wald": ["west"], "felder": ["ost"]},
            "mauer": {"vorhanden": False, "tore": 3}, "viertel": [{"name": "Markt", "typ": "markt"}], "orte": [],
            "ausgabe": {"bildgroesse": 700}}


def flussschleife():
    """Wüste mit einem windungsreichen Fluss: eine Landstraße kreuzt ihn dreimal, einmal an einer Schleife."""
    return {"name": "T98", "seed": 871535, "einwohner": 600, "stadtform": "oval",
            "gelaende": {"biotop": "wueste", "kueste": "keine", "fluss": True, "flussbreite": 100, "inseln": 0,
                         "wald": ["west"], "felder": ["ost"]},
            "mauer": {"vorhanden": False, "tore": 4}, "viertel": [{"name": "Markt", "typ": "markt"}], "orte": [],
            "ausgabe": {"bildgroesse": 700}}


def endet_frontal_am_fluss(m, ln):
    """Läuft die Linie ln an einem Ende frontal auf den Fluss zu und hört dort auf (Abstand unter 4 px, Richtung zum
    nächsten Uferpunkt)?"""
    s, river = m["s"], m["river"]
    for ende in (0, 1):
        c = ln.coords[0] if ende == 0 else ln.coords[-1]
        if Point(c).distance(river) >= 4 * s:
            continue
        q = ln.interpolate(10 * s) if ende == 0 else ln.interpolate(ln.length - 10 * s)
        n = nearest_points(river, Point(c))[0]
        tx, ty, vx, vy = c[0] - q.x, c[1] - q.y, n.x - c[0], n.y - c[1]
        if math.hypot(vx, vy) < 1e-6:
            vx, vy = tx, ty
        if (tx * vx + ty * vy) / ((math.hypot(tx, ty) or 1) * (math.hypot(vx, vy) or 1)) > 0.6:
            return True
    return False


class StrassenUndFluss(unittest.TestCase):
    """Keine Straße führt ins Wasser und endet dort: Torstraßen laufen an Land um eine Flussbiegung herum, und wo eine
    Straße eine Flussschleife kreuzt, liegt eine Brücke."""

    @staticmethod
    def land_mit_bucht():
        """Eine Uferseite, in die der Fluss von oben eine Bucht schneidet (200 mal 200 mit Einschnitt 40 breit, 140 tief)."""
        stadt = object.__new__(CityBuilder)
        stadt.s = 1.0
        stadt.sides = [box(0, 0, 200, 200).difference(box(80, 60, 120, 200))]
        return stadt

    def test_strasse_ueber_land_bleibt_unveraendert(self):
        stadt = self.land_mit_bucht()
        ln = LineString([(20, 20), (100, 30), (180, 20)])
        self.assertEqual([p.wkt for p in stadt.road_on_land(ln, 0)], [ln.wkt])

    def test_strasse_durch_die_bucht_fuehrt_um_sie_herum(self):
        stadt = self.land_mit_bucht()
        ln = LineString([(40, 190), (100, 192), (160, 190)])   # geradewegs über das Wasser
        stuecke = stadt.road_on_land(ln, 0)
        self.assertEqual(len(stuecke), 1)   # kein Stummel, kein abgetrenntes Reststück
        weg = stuecke[0]
        self.assertTrue(weg.within(stadt.sides[0].buffer(2)))
        self.assertLess(Point(weg.coords[0]).distance(Point(40, 190)), 1)
        self.assertLess(Point(weg.coords[-1]).distance(Point(160, 190)), 1)
        self.assertGreater(weg.length, 2 * 130)   # am Grund der Bucht (unter y = 60) entlang

    def test_ohne_weg_bleibt_der_zuschnitt(self):
        stadt = object.__new__(CityBuilder)
        stadt.s = 1.0
        stadt.sides = [box(0, 0, 60, 60)]
        ln = LineString([(10, 30), (200, 30)])   # das Ziel liegt weit außerhalb
        self.assertEqual([round(p.length) for p in stadt.road_on_land(ln, 0)], [52])   # nur der Teil bis zum Rand (plus 2)

    def test_torstrassen_enden_nicht_am_fluss(self):
        m = generate(config.from_dict(stadt_am_fluss()))
        s = m["s"]
        torstrassen = [ln for ln, w in m["internal_roads"] if abs(w - 14 * s) < 1e-6]
        self.assertGreaterEqual(len(torstrassen), len(m["gates"]))   # jedes Tor hat eine Straße
        self.assertEqual([ln.wkt for ln in torstrassen if endet_frontal_am_fluss(m, ln)], [])

    def test_flussschleife_hat_eine_bruecke(self):
        m = generate(config.from_dict(flussschleife()))
        s = m["s"]
        bruecken = unary_union([ln.buffer(w / 2 + 2 * s) for ln, w in m["bridges"]])
        for ln, _ in m["ext_roads"]:
            im_wasser = ln.intersection(m["river"]).difference(bruecken)
            self.assertLess(im_wasser.length, 6 * s, "Straße liegt ohne Brücke im Fluss")

    def test_brueckenregel_schleife_ja_streifen_nein(self):
        fluss = LineString([(-200, 0), (200, 0)]).buffer(30)   # waagerechtes Band, Ufer bei y = +-30
        mitte = LineString([(-200, 0), (200, 0)])
        schleife = LineString([(-100, 60), (-50, 35), (0, 10), (50, 35), (100, 60)])   # taucht tief ein, kommt am selben Ufer heraus
        streifen = LineString([(-100, 31), (0, 28.5), (100, 31)])                      # berührt das Wasser kaum
        endet = LineString([(-100, 60), (-50, 35), (0, 10)])                           # endet im Wasser
        quer = LineString([(0, 60), (0, -60)])
        self.assertEqual(len(make_bridges([(schleife, 10)], fluss, 1.0, mitte)), 1)
        self.assertEqual(make_bridges([(streifen, 10)], fluss, 1.0, mitte), [])
        self.assertEqual(make_bridges([(endet, 10)], fluss, 1.0, mitte), [])
        self.assertEqual(len(make_bridges([(quer, 10)], fluss, 1.0, mitte)), 1)


def knickwinkel(ln, s):
    """Die Richtungswechsel (rad) einer Linie an ihren Punkten; kurze Stücke unter 8 px zählen nicht."""
    c, winkel = list(ln.coords), []
    for (x0, y0), (x1, y1), (x2, y2) in zip(c, c[1:], c[2:]):
        if math.hypot(x1 - x0, y1 - y0) < 8 * s or math.hypot(x2 - x1, y2 - y1) < 8 * s:
            continue
        w = abs(math.atan2(y2 - y1, x2 - x1) - math.atan2(y1 - y0, x1 - x0))
        winkel.append(min(w, 2 * math.pi - w))
    return winkel


class Landstrassen(unittest.TestCase):
    """Landstraßen biegen vor der Küste in einer Kurve ab, statt am Ufer im letzten Schritt zu knicken."""

    def test_scharfe_ecken_werden_zur_kurve(self):
        ecke = [(0, 0), (20, 0), (20, 20), (40, 20)]
        runder = round_kinks(ecke)
        self.assertEqual((runder[0], runder[-1]), (ecke[0], ecke[-1]))   # Anfang und Ende bleiben
        self.assertLess(max(knickwinkel(LineString(runder), 0.05)), 0.5)   # auch die kurzen Stücke zählen
        spitze = round_kinks([(0, 0), (20, 0), (0, 5)])   # fast kehrtwendung
        self.assertLess(max(knickwinkel(LineString(spitze), 0.05)), 1.5)

    def test_sanfte_kurven_bleiben_unveraendert(self):
        sanft = [(0, 0), (20, 0), (39, 6), (56, 16), (70, 30)]   # höchstens etwa 0,3 rad je Punkt
        self.assertEqual(round_kinks(sanft), sanft)

    def test_landstrassen_der_beispiele_knicken_nicht_ab(self):
        for name in ("hafenstadt", "nordhafen", "hauptstadt"):
            with self.subTest(name):
                m = generate(config.from_dict(beispiel(name, bildgroesse=500)))
                for ln, _ in m["ext_roads"]:
                    self.assertLessEqual(max(knickwinkel(ln, m["s"]) or [0]), 0.5, f"{name}: Straße knickt ab")

    def test_landstrassen_laufen_nicht_ins_meer(self):
        m = generate(config.from_dict(beispiel("hafenstadt", bildgroesse=500)))
        for ln, _ in m["ext_roads"]:
            self.assertLess(ln.intersection(m["sea"]).length, 1.0)


class Legende(unittest.TestCase):
    """Zwischen den Kürzeln und den Namen der Legende bleibt ein Abstand."""

    def test_zeichenbreiten_stimmen_mit_der_schrift_ueberein(self):
        """Die Tabelle der fetten Zeichenbreiten ist aus der Schriftdatei gemessen; hier wird sie nachgemessen."""
        from PIL import ImageFont, features
        schrift = ImageFont.truetype(str(ROOT / "stadtkarte" / "fonts" / "EBGaramond-Variable.ttf"), 1000)
        try:
            schrift.set_variation_by_axes([700])
        except (OSError, AttributeError):
            self.skipTest("Pillow kann die Schriftstärke nicht einstellen")
        if not features.check("raqm"):
            self.skipTest("ohne raqm gibt Pillow gerundete Zeichenbreiten")
        for text in ("G1–G12", "SM1–SM3", "MW1–MW9", "WM1, WM2", "W1, W2", "L1–L7", "H3", "SCH1–SCH12"):
            with self.subTest(text):
                echt = schrift.getlength(text) / 1000 * 18
                self.assertAlmostEqual(bold_width(text, 18), echt, delta=0.03 * echt)

    def test_kuerzel_und_name_beruehren_sich_nicht(self):
        roh = klein(orte=[{"name": "Gasthaus", "typ": "gasthaus", "kuerzel": "G", "anzahl": 12},
                          {"name": "Schmiede", "typ": "schmiede", "kuerzel": "SM", "anzahl": 3},
                          {"name": "Muehle", "typ": "muehle", "kuerzel": "MW", "anzahl": 9},
                          {"name": "Hof", "typ": "bauernhof", "kuerzel": "WM", "anzahl": 2}],
                     ausgabe={"bildgroesse": 600, "legende": True})
        m = generate(config.from_dict(roh))
        svg = render_svg(m, nacht=False)
        zeilen = re.findall(r'<text x="([\d.]+)" y="([\d.]+)" font-family="[^"]*" font-size="([\d.]+)" fill="[^"]*" '
                            r'font-weight="bold">([^<]*)</text><text x="([\d.]+)"', svg)
        self.assertGreaterEqual(len(zeilen), 4)
        for x_kuerzel, _, groesse, kuerzel, x_name in zeilen:
            luecke = float(x_name) - float(x_kuerzel) - bold_width(kuerzel, float(groesse))
            self.assertGreaterEqual(luecke, 0.7 * float(groesse), f"{kuerzel}: Abstand zum Namen zu klein ({luecke:.1f} px)")


def stadtbruecken(m):
    """Die Brücken über den Fluss in der Stadt als (Linie, Breite), von Norden nach Süden (die Brücke einer Festungsinsel
    liegt außerhalb)."""
    return sorted((b for b in m["bridges"] if b[0].intersects(m["river"]) and m["shape"].contains(b[0].centroid)),
                  key=lambda b: b[0].centroid.y)


class MehrereBruecken(unittest.TestCase):
    """gelaende.bruecken: bis zu fünf Brücken über den Fluss in der Stadt (die erste liegt in der Stadtmitte)."""

    @classmethod
    def karte(cls, name, n, **gelaende):
        roh = beispiel(name, bildgroesse=500)
        roh["gelaende"] = {**roh["gelaende"], "bruecken": n, **gelaende}
        return generate(config.from_dict(roh))

    @classmethod
    def setUpClass(cls):
        cls.hafen = {n: cls.karte("hafenstadt", n) for n in (1, 3, 5)}

    def test_die_gewuenschte_anzahl_entsteht(self):
        for n, m in self.hafen.items():
            with self.subTest(n):
                self.assertEqual(len(stadtbruecken(m)), n)
                self.assertEqual(len(m["bridges"]), n + 1)   # dazu die Brücke zur Festungsinsel
                self.assertEqual([h for h in m["hints"] if "Brücken" in h], [])

    def test_die_erste_bruecke_bleibt_wo_sie_war(self):
        (eine, _), = stadtbruecken(self.hafen[1])
        for n in (3, 5):
            with self.subTest(n):
                self.assertTrue(any(ln.equals_exact(eine, 1e-6) for ln, _ in stadtbruecken(self.hafen[n])))

    def test_mindestabstand_und_breite(self):
        for n in (3, 5):
            bruecken = stadtbruecken(self.hafen[n])
            s = self.hafen[n]["s"]
            with self.subTest(n):
                for (a, _), (b, _) in zip(bruecken, bruecken[1:]):
                    self.assertGreaterEqual(a.centroid.distance(b.centroid), 80 * s)
                haupt = stadtbruecken(self.hafen[1])[0][1]
                self.assertEqual(max(w for _, w in bruecken), haupt)   # die Hauptbrücke ist die breiteste
                self.assertEqual(sum(w == haupt for _, w in bruecken), 1)

    def test_mit_hafen_nur_flussaufwaerts(self):
        """Der Hafen liegt flussabwärts der Brücken: Küste im Norden, also liegen die weiteren Brücken südlich der ersten."""
        haupt = stadtbruecken(self.hafen[1])[0][0]
        for ln, _ in stadtbruecken(self.hafen[5]):
            self.assertGreaterEqual(ln.centroid.y, haupt.centroid.y - 1e-6)

    def test_ohne_hafen_auch_flussabwaerts(self):
        m = self.karte("plateaustadt", 5)
        haupt = stadtbruecken(self.karte("plateaustadt", 1))[0][0]
        ys = [ln.centroid.y for ln, _ in stadtbruecken(m)]
        self.assertEqual(len(ys), 5)
        self.assertTrue(min(ys) < haupt.centroid.y - 1 < haupt.centroid.y + 1 < max(ys))

    def test_ein_hafenviertel_im_gebirge_und_auf_dem_plateau_zaehlt_nicht(self):
        """Dort wird der Hafen zum Markt, die Brücken liegen auf beiden Seiten der Mitte."""
        roh = beispiel("plateaustadt", bildgroesse=500)
        roh["gelaende"] = {**roh["gelaende"], "bruecken": 5}
        roh["viertel"] = list(roh.get("viertel") or []) + [{"name": "Hafen", "typ": "hafen"}]
        m = generate(config.from_dict(roh))
        ys = [ln.centroid.y for ln, _ in stadtbruecken(m)]
        haupt = stadtbruecken(self.karte("plateaustadt", 1))[0][0].centroid.y
        self.assertEqual(len(ys), 5)
        self.assertTrue(min(ys) < haupt < max(ys))

    def test_nichts_liegt_auf_einer_bruecke(self):
        m = self.hafen[5]
        deck = unary_union([ln.buffer(w / 2) for ln, w in m["bridges"]])
        self.assertFalse(any(b["poly"].intersects(deck) for b in m["buildings"]))
        self.assertFalse(any(p.intersects(deck) for p in m["piers"]))
        self.assertFalse(any(h["poly"].intersects(deck) for h in m["suburbs"]))

    def test_jede_bruecke_verbindet_beide_ufer(self):
        """Über dem Wasser ein Stück von Ufer zu Ufer, an beiden Enden Land."""
        m = self.hafen[5]
        for ln, _ in stadtbruecken(m):
            nass = ln.intersection(m["water"])
            trocken = ln.difference(m["water"])
            self.assertEqual(nass.geom_type, "LineString")
            self.assertEqual(trocken.geom_type, "MultiLineString")
            self.assertEqual(len(trocken.geoms), 2)

    def test_zu_wenig_platz_ergibt_weniger_bruecken_und_einen_hinweis(self):
        m = self.karte("sumpfdorf", 5)
        anzahl = len(stadtbruecken(m))
        self.assertTrue(1 < anzahl < 5)
        self.assertIn(f"Nur {anzahl} von 5 gewünschten Brücken passen über den Fluss in die Stadt.", m["hints"])

    def test_ohne_fluss_keine_wirkung_und_kein_hinweis(self):
        m = generate(config.from_dict(klein(gelaende={"fluss": False, "bruecken": 5})))
        self.assertEqual(m["bridges"], [])
        self.assertEqual([h for h in m["hints"] if "Brücken" in h], [])

    def test_gleiche_angaben_gleiche_karte(self):
        a, b = self.karte("hafenstadt", 4), self.karte("hafenstadt", 4)
        self.assertEqual([ln.wkt for ln, _ in a["bridges"]], [ln.wkt for ln, _ in b["bridges"]])

    def test_alle_bruecken_werden_gezeichnet(self):
        m = self.hafen[5]
        svg = render_svg(m, nacht=False)
        self.assertEqual(svg.count('<g clip-path="url(#bridgeWet)">'), len(m["bridges"]))


class Nachtkarte(unittest.TestCase):
    """Die Nachtkarte entsteht aus derselben Stadt wie die Tagkarte (Werkstatt: erst Tag, dann Nacht). Gebäude und die
    Texturen, die von der Stadt abhängen, sind in beiden gleich und werden nicht noch einmal gerechnet; das Ergebnis
    bleibt aber Zeichen für Zeichen dasselbe wie beim Zeichnen ohne Tagkarte davor."""

    @staticmethod
    def stadt():
        return generate(config.from_dict(klein(ausgabe={"bildgroesse": 300, "formate": ["svg"]})))

    def test_nacht_nach_tag_ist_dasselbe_wie_nacht_allein(self):
        m = self.stadt()
        render_svg(m, nacht=False)
        nach_tag = render_svg(m, nacht=True)
        allein = render_svg(self.stadt(), nacht=True)
        self.assertEqual(nach_tag, allein)

    def test_daecher_und_stadttexturen_werden_nur_einmal_gerechnet(self):
        dach, textur = [], []
        echt_dach, echt_textur = render.detailed_roof, umgebung.image

        def zaehle_dach(*a, **k):
            dach.append(1)
            return echt_dach(*a, **k)

        def zaehle_textur(*a, **k):
            textur.append(1)
            return echt_textur(*a, **k)
        m = self.stadt()
        with mock.patch.object(render, "detailed_roof", zaehle_dach), mock.patch.object(umgebung, "image", zaehle_textur):
            render_svg(m, nacht=False)
            tag = (len(dach), len(textur))
            render_svg(m, nacht=True)
            self.assertEqual((len(dach), len(textur)), tag)   # die Nacht rechnet weder Dächer noch die Umgebungstextur neu
            self.assertGreater(tag[0], 0)
            self.assertEqual(tag[1], 1)

    def test_wurde_die_stadt_veraendert_wird_die_textur_neu_gerechnet(self):
        textur = []
        echt = umgebung.image

        def zaehle(*a, **k):
            textur.append(1)
            return echt(*a, **k)
        m = self.stadt()
        with mock.patch.object(umgebung, "image", zaehle):
            render_svg(m, nacht=False)
            m["forest"] = Polygon()   # die Umgebungstextur hängt vom Wald ab
            render_svg(m, nacht=True)
        self.assertEqual(len(textur), 2)


class Zuschnitt(unittest.TestCase):
    def test_verschieben_repariert_ungueltige_flaechen(self):
        schleife = Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])   # Schleife (Schmetterling): ungültig
        self.assertFalse(schleife.is_valid)
        verschoben = generator._moved(schleife, 10, 20)
        self.assertTrue(verschoben.is_valid)
        self.assertGreater(verschoben.area, 0)
        self.assertEqual(verschoben.bounds, (10, 20, 12, 22))

    def test_gueltige_flaechen_bleiben_unveraendert(self):
        quadrat = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
        self.assertTrue(shapely.equals_exact(generator._moved(quadrat, 1, 1), Polygon([(1, 1), (5, 1), (5, 5), (1, 5)]), 1e-9))


# Beide Konfigurationen stürzten beim Zeichnen ab (TopologyException in unary_union über die Gassen): Armenviertel
# vor der Mauer, vergrößerter Ausschnitt ("nah"). Beim Zuschnitt auf das Kartenfenster wurde eine Gassenfläche durch
# Rundung beim Verschieben ungültig.
ABSTUERZE = {
    "wueste_west": {
        "name": "Fuzz106", "seed": 745200, "einwohner": 6000, "stadtform": "zufall", "bebauung": "weitlaeufig",
        "gelaende": {"biotop": "wueste", "kueste": "west", "fluss": True, "flussbreite": 200, "inseln": 6,
                     "wald": [], "felder": ["sued"], "plateau": "unten", "kante": "abstand",
                     "staub": {"a1": "finsternis", "mitte": "mittel", "ueberall": "wenig"}},
        "mauer": {"vorhanden": True, "tore": 5, "vorstaedte": True},
        "viertel": [{"name": "Adel", "typ": "adel", "lage": "nord"}, {"name": "Markt", "typ": "markt"},
                    {"name": "Arme", "typ": "armen", "lage": "ausserhalb"}],
        "orte": [{"name": "Mühle", "typ": "wassermuehle"}, {"name": "Werft", "typ": "werft"},
                 {"name": "Schenke", "typ": "gasthaus", "anzahl": 3},
                 {"name": "Friedhof", "typ": "friedhof", "lage": "ausserhalb"}, {"name": "Dom", "typ": "kathedrale"}],
        "ausgabe": {"bildgroesse": 600, "stil": "standard", "ausschnitt": "nah", "dachdetails": True},
    },
    "gemaessigt_vieleck": {
        "name": "Fuzz268", "seed": 792058, "einwohner": 15000, "stadtform": "vieleck", "bebauung": "locker",
        "gelaende": {"biotop": "gemaessigt", "kueste": "west", "fluss": False, "flussbreite": 60, "inseln": 6,
                     "wald": ["nord", "west"], "felder": ["sued"], "plateau": "oben", "kante": "direkt", "staub": {}},
        "mauer": {"vorhanden": True, "tore": 7, "vorstaedte": True},
        "viertel": [{"name": "Hafen", "typ": "hafen"}, {"name": "Arme", "typ": "armen", "lage": "ausserhalb"}],
        "orte": [{"name": "Dom", "typ": "kathedrale"}],
        "ausgabe": {"bildgroesse": 400, "stil": "pergament", "ausschnitt": "nah", "dachdetails": True},
    },
}


@unittest.skipIf(os.environ.get("STADTKARTE_SCHNELL") == "1", "langsame Tests übersprungen")
class Abstuerze(unittest.TestCase):
    def test_karten_mit_armenviertel_vor_der_mauer_lassen_sich_zeichnen(self):
        for name, raw in ABSTUERZE.items():
            with self.subTest(name):
                m = generate(config.from_dict(raw))
                self.assertTrue(all(g.is_valid for g in m["streets"]))
                self.assertIn("<svg", render_svg(m)[:200])


if __name__ == "__main__":
    unittest.main()
