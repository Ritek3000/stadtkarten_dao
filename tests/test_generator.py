"""Regressionstests des Generators. Die langsamen Fälle (Karte erzeugen und zeichnen, je einige Sekunden) lassen sich
mit STADTKARTE_SCHNELL=1 überspringen."""
import contextlib
import io
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest

import shapely
import yaml
from shapely.geometry import Polygon

from stadtkarte import config, generator
from stadtkarte.generator import generate
from stadtkarte.render import render_svg
from tests.golden import klein

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
