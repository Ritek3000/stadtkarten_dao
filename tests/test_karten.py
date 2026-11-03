"""Karten-Vergleichstests: fertige Karten dürfen sich durch Umbauten nicht verändern (Einzelheiten in tests/golden.py).

Jede Karte hat einen eigenen Test. Die Karten werden einmal gemeinsam und parallel erzeugt; das dauert etwa eine bis zwei
Minuten, mit STADTKARTE_SCHNELL=1 bleibt der Test aus. Hat sich eine Karte gewollt verändert (Änderung am Generator oder
am Zeichnen), schreibt `python -m tests.golden --update` die Fingerabdrücke neu; die Änderung der Datei
tests/golden/karten.json gehört dann mit in den Commit und zeigt im Review, welche Karten sich verändert haben."""
import os
import unittest

from tests import golden


@unittest.skipIf(os.environ.get("STADTKARTE_SCHNELL") == "1", "langsame Tests übersprungen")
class Karten(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gespeichert = golden.laden()
        cls.aktuell = golden.berechne_alle()

    def test_keine_veralteten_eintraege(self):
        veraltet = sorted(set(self.gespeichert["faelle"]) - set(golden.faelle()))
        self.assertEqual(veraltet, [], "stehen in tests/golden/karten.json, aber nicht mehr in tests/golden.py "
                                       "(python -m tests.golden --update)")


def _test_fuer(name):
    def test(self):
        soll = self.gespeichert["faelle"].get(name)
        if soll is None:
            self.fail(f"Die Karte '{name}' ist noch nicht gespeichert: python -m tests.golden --update {name}")
        fehler = golden.unterschiede(soll, self.aktuell[name], self.gespeichert["umgebung"])
        if fehler:
            self.fail(f"Die Karte '{name}' weicht von tests/golden/karten.json ab:\n  " + "\n  ".join(fehler)
                      + f"\nGewollt? Dann: python -m tests.golden --update {name}")
    test.__doc__ = f"Karte {name}"
    return test


for _name in golden.faelle():
    setattr(Karten, f"test_{_name}", _test_fuer(_name))


if __name__ == "__main__":
    unittest.main()
