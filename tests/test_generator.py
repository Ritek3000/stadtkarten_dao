"""Regressionstests des Generators. Die langsamen Fälle (Karte erzeugen und zeichnen, je einige Sekunden) lassen sich
mit STADTKARTE_SCHNELL=1 überspringen."""
import os
import unittest

import shapely
from shapely.geometry import Polygon

from stadtkarte import config, generator
from stadtkarte.generator import generate
from stadtkarte.render import render_svg


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
