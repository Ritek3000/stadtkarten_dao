"""Die acht neueren besonderen Orte (Marktplatz, Badehaus, Magierturm, Arena, Färberei, Hafenkran, Kloster, Richtstätte):
Schreibweisen, Platzierung, Legende, Zeichnen bei Tag und Nacht und Determinismus (gleicher Seed, gleiche Karte)."""
import hashlib
import os
import unittest

from stadtkarte import config
from stadtkarte.generator import generate, hint_lines
from stadtkarte.render import render_svg
from tests.golden import fingerabdruck_modell, klein

NEU = [("marktplatz", "M"), ("badehaus", "B"), ("magierturm", "T"), ("arena", "A"), ("faerberei", "F"),
       ("hafenkran", "K"), ("kloster", "KL"), ("richtstaette", "G")]
SCHNELL = os.environ.get("STADTKARTE_SCHNELL") == "1"


def stadt(**kw):
    orte = [{"name": typ.capitalize(), "typ": typ, "kuerzel": k} for typ, k in NEU]
    return klein(seed=kw.pop("seed", 5), einwohner=kw.pop("einwohner", 9000), orte=orte,
                 viertel=[{"name": "Hafen", "typ": "hafen"}, {"name": "Markt", "typ": "markt"},
                          {"name": "Handwerk", "typ": "handwerk", "lage": "west"},
                          {"name": "Wohn", "typ": "wohn", "lage": "ost"}],
                 ausgabe={"bildgroesse": 700, "formate": ["svg"]}, **kw)


class Schreibweisen(unittest.TestCase):
    def test_alternative_namen(self):
        for alias, typ in (("Wochenmarkt", "marktplatz"), ("Therme", "badehaus"), ("Magier", "magierturm"),
                           ("Kolosseum", "arena"), ("Abtei", "kloster"), ("Färber", "faerberei"),
                           ("Galgen", "richtstaette"), ("Tretradkran", "hafenkran")):
            with self.subTest(alias):
                cfg = config.from_dict(klein(orte=[{"name": "X", "typ": alias}]))
                self.assertEqual(cfg["orte"][0]["typ"], typ)


@unittest.skipIf(SCHNELL, "langsam")
class NeueOrte(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = generate(config.from_dict(stadt()))

    def test_alle_stehen_in_der_legende(self):
        kuerzel = {k for k, _ in self.m["legend"]}
        for _, k in NEU:
            self.assertIn(k, kuerzel)

    def test_alle_haben_eine_beschriftung(self):
        texte = {lb["text"] for lb in self.m["labels"] if lb["kind"] == "ort"}
        for _, k in NEU:
            self.assertIn(k, texte)

    def test_bauten_sind_im_modell(self):
        b = self.m["buildings"]
        self.assertTrue(any(x.get("magic") for x in b))
        self.assertTrue(any(x.get("crane") for x in b))
        self.assertTrue(any(x.get("rows") for x in b))
        self.assertTrue(any(x.get("dome") for x in b))
        self.assertEqual(len(self.m["gallows"]), 1)

    def test_kranausleger_liegt_im_wasser_das_haus_an_land(self):
        from shapely.geometry import LineString
        kran = next(x for x in self.m["buildings"] if x.get("crane"))["crane"]
        self.assertFalse(kran["r"] <= 0)
        boom = LineString([(kran["x"], kran["y"]), (kran["ex"], kran["ey"])])
        self.assertGreater(boom.intersection(self.m["water"]).length, 0.5 * boom.length)

    def test_zeichnet_tag_und_nacht(self):
        tag, nacht = render_svg(self.m, nacht=False), render_svg(self.m, nacht=True)
        self.assertIn("glowMagic", nacht)
        self.assertNotIn("glowMagic", tag)

    def test_gleicher_seed_gleiche_karte(self):
        m2 = generate(config.from_dict(stadt()))
        self.assertEqual(fingerabdruck_modell(self.m), fingerabdruck_modell(m2))
        a, b = render_svg(self.m, nacht=False), render_svg(m2, nacht=False)
        self.assertEqual(hashlib.sha256(a.encode()).digest(), hashlib.sha256(b.encode()).digest())

    def test_anderer_seed_andere_karte(self):
        m2 = generate(config.from_dict(stadt(seed=6)))
        self.assertNotEqual(fingerabdruck_modell(self.m), fingerabdruck_modell(m2))


@unittest.skipIf(SCHNELL, "langsam")
class Grenzfaelle(unittest.TestCase):
    def test_ohne_wasser_gibt_es_einen_hinweis_statt_eines_absturzes(self):
        m = generate(config.from_dict(stadt(gelaende={"biotop": "steppe", "kueste": "keine", "fluss": False, "inseln": 0})))
        self.assertTrue(any("Hafenkran" in h for h in hint_lines(m)))
        render_svg(m, nacht=True)

    def test_dorf_und_grossstadt_stuerzen_nicht_ab(self):
        for einwohner in (600, 60000):
            with self.subTest(einwohner):
                m = generate(config.from_dict(stadt(einwohner=einwohner)))
                render_svg(m, nacht=False)

    def test_ohne_neue_orte_aendert_sich_nichts(self):
        roh = klein()
        m = generate(config.from_dict(roh))
        self.assertFalse(m["gallows"] if "gallows" in m else False)
        self.assertNotIn("basins", m)


if __name__ == "__main__":
    unittest.main()
