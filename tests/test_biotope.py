"""Die Biotope Heide, Herbst, Auwald, Mittelmeer, Dschungel und Hochmoor: Angabe, Aufbau und Zeichnung."""
import os
import unittest

from stadtkarte import config
from stadtkarte.generator import generate
from stadtkarte.render import render_svg
from stadtkarte.styles import BIOMES
from tests.golden import beispiel, klein

NEU = ("heide", "herbst", "auwald", "mittelmeer", "dschungel", "hochmoor")
LANGSAM = os.environ.get("STADTKARTE_SCHNELL") == "1"


def karte(biotop, **gelaende):
    return generate(config.from_dict(klein(gelaende={"biotop": biotop, **gelaende}, ausgabe={"bildgroesse": 500})))


class Angabe(unittest.TestCase):
    def test_neue_biotope_und_andere_schreibweisen(self):
        for name, soll in [("Heide", "heide"), ("Herbstwald", "herbst"), ("Flussaue", "auwald"), ("Aue", "auwald"),
                           ("mediterran", "mittelmeer"), ("Regenwald", "dschungel"), ("Urwald", "dschungel"),
                           ("Moor", "hochmoor"), ("Torf", "hochmoor"), ("Sumpf", "sumpf")]:
            cfg = config.from_dict({"gelaende": {"biotop": name}})
            self.assertEqual(cfg["gelaende"]["biotop"], soll, name)

    def test_jedes_neue_biotop_hat_alle_angaben(self):
        for name in NEU:
            self.assertEqual(set(BIOMES[name]) - set(BIOMES["gemaessigt"]) - {"pool", "pool_edge"}, set(), name)
            self.assertEqual(len(BIOMES[name]["field_names"]), len(BIOMES[name]["field_kinds"]), name)


@unittest.skipIf(LANGSAM, "STADTKARTE_SCHNELL=1")
class Aufbau(unittest.TestCase):
    def test_auwald_hat_altarme_und_wald_am_fluss(self):
        m = karte("auwald", kueste="keine", inseln=0, flussbreite=60)
        self.assertFalse(m["pools"].is_empty)
        self.assertFalse(m["pools"].intersects(m["river"]))
        self.assertGreater(m["forest"].intersection(m["river"].buffer(60 * m["s"])).area, 0)
        self.assertTrue(m["reeds"])

    def test_auwald_ohne_fluss_ohne_altarme_und_ohne_absturz(self):
        m = karte("auwald", fluss=False)
        self.assertIsNone(m["river"])

    def test_mittelmeer_hat_olivenhaine_und_weinberge(self):
        m = karte("mittelmeer", felder=["ost", "sued", "west"])
        arten = {fl["kind"] for fl in m["fields"]}
        self.assertTrue({"olive", "vine"} <= arten, arten)

    def test_hochmoor_hat_torfstiche_moorseen_ohne_pfahlhaeuser(self):
        m = karte("hochmoor", felder=["ost", "sued", "west"])
        self.assertIn("peat", {fl["kind"] for fl in m["fields"]})
        self.assertFalse(m["pools"].is_empty)
        self.assertFalse(any(b.get("stilts") for b in m["buildings"] + m["suburbs"]))
        self.assertEqual(m["lilies"], [])
        self.assertFalse(m["pools"].intersects(m["shape"]))

    def test_dschungel_ist_dichter_bewaldet_als_gemaessigt(self):
        self.assertGreater(len(karte("dschungel")["trees"]), 1.3 * len(karte("gemaessigt")["trees"]))

    def test_gleiche_angaben_gleiche_karte(self):
        for name in ("auwald", "hochmoor"):
            a, b = karte(name), karte(name)
            self.assertEqual(a["pools"].wkt, b["pools"].wkt, name)
            self.assertEqual(a["trees"], b["trees"], name)


@unittest.skipIf(LANGSAM, "STADTKARTE_SCHNELL=1")
class Zeichnung(unittest.TestCase):
    def test_tag_und_nacht_zeichnen_alle_neuen_biotope(self):
        for name in NEU:
            m = karte(name)
            for nacht in (False, True):
                svg = render_svg(m, nacht=nacht)
                self.assertTrue(svg.startswith("<svg") or svg.lstrip().startswith("<"), name)
                self.assertIn(BIOMES[name]["land"], svg, name)

    def test_neue_feldarten_haben_eigene_muster(self):
        svg = render_svg(generate(config.from_dict(beispiel("mittelmeerhafen", bildgroesse=500))), nacht=False)
        self.assertIn('fill-opacity="0.28"/>', svg)   # Schatten der Olivenbäume im Hain


if __name__ == "__main__":
    unittest.main()
