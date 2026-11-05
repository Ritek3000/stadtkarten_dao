"""Standardwerte: Die Oberfläche wiederholt sie nicht, sie kommen vom Server (config.DEFAULTS, config.OPTIONAL).

Der Test führt die Funktion norm() aus stadtkarte/ui/index.html mit Node aus (der Block zwischen den Markierungen
"// >>> Standardwerte" und "// <<< Standardwerte") und prüft: Was die Seite aus einer Beschreibung macht, ergibt nach
der Prüfung durch den Server (config.from_dict) dasselbe wie die Beschreibung allein."""
import copy
import json
import pathlib
import shutil
import subprocess
import unittest

import yaml

from stadtkarte import config
from stadtkarte.city import GROSS
from stadtkarte.ui.__main__ import options

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = ROOT / "stadtkarte" / "ui" / "index.html"
NODE = shutil.which("node")


def seite_normalisiert(beschreibungen):
    """norm() der Seite, angewandt auf eine Liste von Beschreibungen (mit den echten Optionen des Servers)."""
    html = HTML.read_text(encoding="utf-8")
    block = html[html.index("// >>> Standardwerte"):html.index("// <<< Standardwerte")]
    skript = ('const eingabe = JSON.parse(require("fs").readFileSync(0, "utf8"));\nconst OPT = eingabe.optionen;\n'
              + block + '\nconsole.log(JSON.stringify(eingabe.beschreibungen.map(norm)));\n')
    res = subprocess.run([NODE, "-e", skript], input=json.dumps({"optionen": options(), "beschreibungen": beschreibungen}),
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


class Optionen(unittest.TestCase):
    def test_standardwerte_und_grenzen_kommen_vom_server(self):
        opt = options()
        self.assertEqual(opt["defaults"], config.ui_defaults())
        self.assertEqual(opt["optional"], config.OPTIONAL)
        self.assertEqual(opt["limits"], {"einwohner_max": config.MAX_EINWOHNER, "grossstadt": GROSS,
                                         "bruecken_max": config.MAX_BRIDGES})
        json.dumps(opt)   # muss als JSON auslieferbar sein

    def test_die_oberflaeche_traegt_keine_kommandozeilenangaben_ein(self):
        self.assertNotIn("nacht", options()["defaults"]["ausgabe"])
        self.assertIn("nacht", config.DEFAULTS["ausgabe"])

    def test_die_vorgaben_sind_selbst_eine_gueltige_beschreibung(self):
        self.assertEqual(config.from_dict(config.ui_defaults()), config.from_dict({}))

    def test_fehlende_angaben_haben_den_wert_aus_der_tabelle(self):
        """Jeder Eintrag in OPTIONAL stimmt mit dem überein, was geschieht, wenn die Angabe fehlt."""
        plateau = {"gelaende": {"biotop": "hochplateau"}}
        hafen = {"viertel": [{"name": "Hafen", "typ": "hafen"}]}
        ruinen = {"viertel": [{"name": "Ruinen", "typ": "ruinen"}]}
        faelle = {"bebauung": ({}, lambda c: c), "ausgabe.stil": ({}, lambda c: c["ausgabe"]),
                  "ausgabe.ausschnitt": ({}, lambda c: c["ausgabe"]), "gelaende.plateau": (plateau, lambda c: c["gelaende"]),
                  "gelaende.kante": (plateau, lambda c: c["gelaende"]), "viertel.groesse": (hafen, lambda c: c["viertel"][0]),
                  "viertel.ruinenanteil": (ruinen, lambda c: c["viertel"][0])}
        self.assertEqual(set(faelle), set(config.OPTIONAL), "OPTIONAL und dieser Test passen nicht zusammen")
        for schluessel, wert in config.OPTIONAL.items():
            basis, abschnitt = faelle[schluessel]
            with self.subTest(schluessel):
                ohne = copy.deepcopy(basis)
                mit = copy.deepcopy(basis)
                name = schluessel.split(".")[-1]
                ziel = mit if "." not in schluessel else mit.setdefault(schluessel.split(".")[0], {})
                if schluessel.startswith("viertel"):
                    ziel = mit["viertel"][0]
                ziel[name] = wert
                self.assertEqual(config.from_dict(mit), config.from_dict(ohne))
                self.assertEqual(abschnitt(config.from_dict(ohne)).get(name, wert), wert)


@unittest.skipUnless(NODE, "Node ist nicht installiert")
class SeiteMitNode(unittest.TestCase):
    def pruefe(self, rohe):
        for roh, norm in zip(rohe, seite_normalisiert(copy.deepcopy(rohe))):
            self.assertEqual(config.from_dict(norm), config.from_dict(copy.deepcopy(roh)))

    def test_leere_beschreibung(self):
        self.pruefe([{}])

    def test_alle_beispiele(self):
        beispiele = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "beispiele").glob("*.yaml"))]
        self.assertTrue(beispiele)
        self.pruefe(beispiele)

    def test_luecken_und_leere_angaben(self):
        self.pruefe([
            {"name": "A", "seed": 5},
            {"gelaende": None}, {"mauer": None}, {"ausgabe": None}, {"viertel": None, "orte": None},
            {"gelaende": {"wald": None}}, {"gelaende": {"felder": None, "biotop": "wueste"}},   # leer = kein Wald
            {"gelaende": {"wald": "west", "felder": "ost"}},                                      # ein einzelner Wert
            {"gelaende": {"biotop": "hochplateau"}}, {"ausgabe": {"formate": None}}, {"name": None},
            {"beschriftung": {"titel": [1, 2]}}, {"stadtform": "oval", "bebauung": "locker"},
        ])

    def test_wald_und_felder_wie_beim_server(self):
        (fehlt, leer) = seite_normalisiert([{}, {"gelaende": {"wald": None, "felder": None}}])
        self.assertEqual((fehlt["gelaende"]["wald"], fehlt["gelaende"]["felder"]), (["west"], ["ost", "sued"]))
        self.assertEqual((leer["gelaende"]["wald"], leer["gelaende"]["felder"]), ([], []))

    def test_die_kommandozeile_bleibt_unberuehrt(self):
        (norm,) = seite_normalisiert([{}])
        self.assertNotIn("nacht", norm["ausgabe"])


if __name__ == "__main__":
    unittest.main()
