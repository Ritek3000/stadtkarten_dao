"""Ruinenviertel (typ: ruinen): Angaben, Anteil der Ruinen, Aufbau der Ruinen, Zeichnen bei Tag und Nacht, Blender-Export
und Determinismus (gleicher Seed, gleiche Karte)."""
import os
import re
import unittest

from shapely.geometry import MultiLineString, Point

from stadtkarte import blender_export, config, ruinen
from stadtkarte.generator import generate
from stadtkarte.render import render_svg
from tests.golden import fingerabdruck_modell, klein

SCHNELL = os.environ.get("STADTKARTE_SCHNELL") == "1"


def stadt(anteil=60, typ="ruinen", seed=5, einwohner=3000, **kw):
    """Kleine Küstenstadt mit Markt im Osten und einem Ruinenviertel (oder Vergleichsviertel) im Westen."""
    ruinen_viertel = {"name": "Ruinen", "typ": typ, "lage": "west"}
    if typ == "ruinen" and anteil is not None:
        ruinen_viertel["ruinenanteil"] = anteil
    return klein(seed=seed, einwohner=einwohner, orte=kw.pop("orte", []), ausgabe={"bildgroesse": 700, "formate": ["svg"]},
                 viertel=[{"name": "Markt", "typ": "markt", "lage": "ost"}, ruinen_viertel], **kw)


def erzeuge(**kw):
    return generate(config.from_dict(stadt(**kw)))


def einheiten(m, typ="ruinen"):
    """(Ruinen, Häuser) im Viertel dieses Typs; Häuser ohne besondere Orte, in Häuserzeilen zählt jedes Haus."""
    di = next(i for i, d in enumerate(m["districts"]) if d["typ"] == typ)
    haeuser = ruinen_n = 0
    for b in m["buildings"]:
        if b["district"] != di or b.get("landmark"):
            continue
        if b.get("form") == "block":
            haeuser += len(b["segments"])
            ruinen_n += len(b.get("ruins", {}))
        else:
            haeuser += 1
            ruinen_n += 1 if b.get("ruin") else 0
    return ruinen_n, haeuser


def alle_ruinen(m):
    """Jede Ruine des Modells als (Grundriss, Angaben)."""
    out = []
    for b in m["buildings"]:
        if b.get("ruin"):
            out.append((b["poly"], b["ruin"]))
        for k, info in (b.get("ruins") or {}).items():
            out.append((b["segments"][k][0], info))
    return out


class Angaben(unittest.TestCase):
    @staticmethod
    def viertel(**angaben):
        return config.from_dict({"viertel": [{"name": "R", "typ": "ruinen", **angaben}]})["viertel"][0]

    def test_typ_und_schreibweisen(self):
        for typ in ("ruinen", "Ruinen", "Ruinenviertel", "ruine"):
            with self.subTest(typ):
                self.assertEqual(self.viertel(typ=typ)["typ"], "ruinen")

    def test_standard_entfaellt(self):
        self.assertNotIn("ruinenanteil", self.viertel())
        self.assertNotIn("ruinenanteil", self.viertel(ruinenanteil=60))
        self.assertNotIn("ruinenanteil", self.viertel(ruinenanteil="60 %"))
        self.assertEqual(config.OPTIONAL["viertel.ruinenanteil"], 60)

    def test_anteil(self):
        for roh, soll in ((40, 40), ("45 %", 45), ("70%", 70), (0, 0), (100, 100), ("5,0", 5), (30.0, 30)):
            with self.subTest(roh):
                self.assertEqual(self.viertel(ruinenanteil=roh)["ruinenanteil"], soll)

    def test_ungueltiger_anteil(self):
        for roh in (101, -5, 12.5, "viel", True, [3]):
            with self.subTest(roh), self.assertRaisesRegex(ValueError, "ruinenanteil"):
                self.viertel(ruinenanteil=roh)

    def test_andere_viertel_haben_keinen_anteil(self):
        v = config.from_dict({"viertel": [{"name": "W", "typ": "wohn", "ruinenanteil": 80}]})["viertel"][0]
        self.assertNotIn("ruinenanteil", v)

    def test_nicht_vor_der_mauer(self):
        """Nur Armenviertel liegen vor der Mauer: das Ruinenviertel bleibt in der Stadt, der Generator weist darauf hin."""
        roh = stadt(anteil=50)
        roh["viertel"][1]["lage"] = "ausserhalb"
        m = generate(config.from_dict(roh))
        self.assertFalse(next(d for d in m["districts"] if d["typ"] == "ruinen")["outside"])
        self.assertTrue(any("Nur Armenviertel" in h for h in m["hints"]))


class Verfall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = {anteil: erzeuge(anteil=anteil) for anteil in (0, 30, 60, 100)}
        cls.wohn = erzeuge(typ="wohn")

    def test_der_anteil_stimmt(self):
        for anteil, m in self.m.items():
            n_ruinen, n_haeuser = einheiten(m)
            with self.subTest(anteil):
                self.assertGreater(n_haeuser, 30)
                if anteil in (0, 100):
                    self.assertEqual(n_ruinen, n_haeuser * anteil // 100)
                else:   # nach dem Verfall entfernt der Generator vereinzelt Häuser (Festung, Leuchtturm): kleine Abweichung
                    self.assertAlmostEqual(n_ruinen, n_haeuser * anteil / 100, delta=2)

    def test_der_standardanteil_gilt_ohne_angabe(self):
        n_ruinen, n_haeuser = einheiten(erzeuge(anteil=None))
        self.assertAlmostEqual(n_ruinen, n_haeuser * 0.6, delta=2)

    def test_ruinen_nur_im_ruinenviertel(self):
        m = self.m[100]
        di = next(i for i, d in enumerate(m["districts"]) if d["typ"] == "ruinen")
        for b in m["buildings"] + m["suburbs"]:
            if b.get("ruin") or b.get("ruins"):
                self.assertEqual(b["district"], di)
        self.assertFalse(any(b.get("ruin") or b.get("ruins") for b in self.wohn["buildings"]))

    def test_besondere_orte_bleiben_heil(self):
        orte = [{"name": "Schenke", "typ": "gasthaus", "viertel": "Ruinen"}, {"name": "Schrein", "typ": "tempel", "viertel": "Ruinen"}]
        m = erzeuge(anteil=100, orte=orte)
        di = next(i for i, d in enumerate(m["districts"]) if d["typ"] == "ruinen")
        orte_hier = [b for b in m["buildings"] if b.get("landmark") and b["district"] == di]
        self.assertTrue(orte_hier, "kein besonderer Ort im Ruinenviertel gelandet")
        self.assertFalse(any(b.get("ruin") or b.get("ruins") for b in orte_hier))
        self.assertEqual(einheiten(m)[0], einheiten(m)[1])   # alle übrigen Häuser sind Ruinen

    def test_ein_anderer_anteil_aendert_nur_die_ruinen(self):
        """Das Stadtbild (Straßen, Häuser, Farben) hängt nicht vom Anteil ab; mit 0 % ist das Viertel ein Wohnviertel."""
        def haeuser(m):
            return [(b["district"], b["poly"].wkt, b["color"]) for b in m["buildings"]]
        soll = haeuser(self.m[0])
        for anteil in (30, 60, 100):
            with self.subTest(anteil):
                self.assertEqual(haeuser(self.m[anteil]), soll)
        self.assertEqual(haeuser(self.wohn), soll)
        self.assertEqual([g.wkt for g in self.m[0]["streets"]], [g.wkt for g in self.wohn["streets"]])

    def test_aufbau_der_ruinen(self):
        gefunden = alle_ruinen(self.m[100])
        self.assertGreater(len(gefunden), 30)
        arten = set()
        for poly, info in gefunden:
            arten.add(info["art"])
            with self.subTest(info["seed"]):
                self.assertIn(info["art"], (ruinen.DACH, ruinen.MAUER))
                self.assertIsInstance(info["walls"], MultiLineString)
                self.assertFalse(info["walls"].is_empty)
                self.assertTrue(poly.buffer(0.05).contains(info["walls"]), "Mauerstücke liegen auf dem Grundriss")
                if info["art"] == ruinen.DACH:
                    self.assertTrue(poly.buffer(0.05).contains(info["rest"]), "der Dachrest liegt im Haus")
                    self.assertTrue(0.25 <= info["rest"].area / poly.area <= 0.7)
                else:
                    self.assertIsNone(info["rest"])
        self.assertEqual(arten, {ruinen.DACH, ruinen.MAUER}, "es entstehen beide Arten von Ruinen")

    def test_mauerstuecke_lassen_luecken(self):
        for poly, info in alle_ruinen(self.m[100]):
            with self.subTest(info["seed"]):
                self.assertLess(info["walls"].length, poly.exterior.length + 1e-6)

    def test_gleicher_seed_gleiche_karte(self):
        again = erzeuge(anteil=60)
        self.assertEqual(fingerabdruck_modell(again), fingerabdruck_modell(self.m[60]))
        self.assertEqual(render_svg(again), render_svg(self.m[60]))

    def test_anderer_seed_andere_ruinen(self):
        a, b = erzeuge(anteil=60, seed=5), erzeuge(anteil=60, seed=6)
        self.assertNotEqual([i["seed"] for _, i in alle_ruinen(a)], [i["seed"] for _, i in alle_ruinen(b)])

    def test_ruinen_bilden_gruppen(self):
        """Nicht jedes zweite Haus, sondern Nachbarschaften: Nachbarn von Ruinen sind häufiger selbst Ruinen als
        gleichmäßig verteilt (bei 50 %)."""
        m = erzeuge(anteil=50, einwohner=6000)
        di = next(i for i, d in enumerate(m["districts"]) if d["typ"] == "ruinen")
        haeuser = [b for b in m["buildings"] if b["district"] == di and not b.get("landmark") and b.get("form") != "block"]
        paare = gleiche = 0
        for i, a in enumerate(haeuser):
            for b in haeuser[i + 1:]:
                if a["poly"].distance(b["poly"]) < 14:
                    paare += 1
                    gleiche += bool(a.get("ruin")) == bool(b.get("ruin"))
        self.assertGreater(paare, 50)
        self.assertGreater(gleiche / paare, 0.6)   # gleichmäßig verteilt wären es 50 %


class Zeichnen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ohne, cls.alle = erzeuge(anteil=0), erzeuge(anteil=100)

    def test_ruinen_werden_gezeichnet(self):
        self.assertNotIn(ruinen.FLOOR, render_svg(self.ohne))
        self.assertIn(ruinen.FLOOR, render_svg(self.alle))

    def test_bewohnte_viertel_bleiben_gleich(self):
        """Ohne Ruinen ist die Karte die eines Wohnviertels: kein Zeichen der Ruinen im SVG."""
        wohn = generate(config.from_dict(stadt(typ="wohn")))
        self.assertEqual(render_svg(self.ohne), render_svg(wohn))

    @staticmethod
    def fenster(svg):
        """Mitten der erleuchteten Fenster im Nachtbild."""
        gruppe = svg[svg.index('<g fill="#ffd77a">'):]
        gruppe = gruppe[:gruppe.index("</g>")]
        return [Point(float(x), float(y)) for x, y in re.findall(r'translate\(([-\d.]+),([-\d.]+)\)', gruppe)]

    def test_nachts_kein_licht_in_ruinen(self):
        di = next(i for i, d in enumerate(self.ohne["districts"]) if d["typ"] == "ruinen")
        haeuser = [b["poly"] for b in self.ohne["buildings"] if b["district"] == di]
        hell = [p for p in self.fenster(render_svg(self.ohne, nacht=True)) if any(h.buffer(0.5).contains(p) for h in haeuser)]
        self.assertTrue(hell, "Voraussetzung: im bewohnten Viertel brennt Licht")
        dunkel = [p for p in self.fenster(render_svg(self.alle, nacht=True)) if any(h.buffer(0.5).contains(p) for h in haeuser)]
        self.assertEqual(dunkel, [])

    def test_ruinen_werfen_kaum_schatten(self):
        """Der Schatten des Viertels schrumpft mit den Ruinen (Mauerreste werfen keinen, Dachreste nur ihren Teil)."""
        for b in self.alle["buildings"]:
            if b.get("ruin") and b["ruin"]["art"] == ruinen.MAUER:
                self.assertIsNone(ruinen.standing_roofs(b))
            elif b.get("ruin"):
                self.assertLess(ruinen.standing_roofs(b).area, b["poly"].area)
        heil = next(b for b in self.ohne["buildings"] if not b.get("ruin"))
        self.assertIs(ruinen.standing_roofs(heil), heil["poly"])


class Blender(unittest.TestCase):
    def test_ruinen_tragen_die_angabe(self):
        m = erzeuge(anteil=50)
        ruin, haeuser = einheiten(m)
        merkmale = blender_export.export_model(m)["buildings"]
        self.assertEqual(sum(1 for f in merkmale if f.get("ruin")), ruin)
        self.assertTrue(all(f["ruin"] is True for f in merkmale if "ruin" in f))
        self.assertFalse(any("ruin" in f for f in blender_export.export_model(erzeuge(anteil=0))["buildings"]))


@unittest.skipIf(SCHNELL, "langsam")
class Grossstadt(unittest.TestCase):
    """In der Großstadt zählt jedes Haus einer Häuserzeile einzeln."""

    @classmethod
    def setUpClass(cls):
        cls.m = erzeuge(anteil=50, einwohner=30000)

    def test_haeuser_der_zeilen_verfallen_einzeln(self):
        zeilen = [b for b in self.m["buildings"] if b.get("ruins")]
        self.assertTrue(zeilen)
        self.assertTrue(any(len(b["ruins"]) < len(b["segments"]) for b in zeilen), "Zeilen mit Ruinen und heilen Häusern")
        n_ruinen, n_haeuser = einheiten(self.m)
        # der Generator entfernt später ganze Häuserzeilen (an Brücken und Landstraßen): der Anteil weicht etwas ab
        self.assertAlmostEqual(n_ruinen, n_haeuser / 2, delta=0.03 * n_haeuser)

    def test_zeilen_zeichnen_und_blender(self):
        svg = render_svg(self.m)
        self.assertIn(ruinen.FLOOR, svg)
        zeilen_mit_ruinen = sum(len(b["ruins"]) for b in self.m["buildings"] if b.get("ruins"))
        merkmale = blender_export.export_model(self.m)["buildings"]
        self.assertEqual(sum(1 for f in merkmale if f.get("ruin")), zeilen_mit_ruinen)


if __name__ == "__main__":
    unittest.main()
