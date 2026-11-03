"""Prüfung der Stadtbeschreibung (config.from_dict): fehlerhafte Angaben ergeben eine klare Meldung (ValueError)
statt eines Absturzes mit TypeError/KeyError, und sinnvolle Lücken (leere Abschnitte, fehlender Name) füllen die
Standardwerte."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

import yaml

from stadtkarte import config
from stadtkarte.ui.__main__ import PLACE_TYPES as UI_PLACE_TYPES

ROOT = pathlib.Path(__file__).resolve().parents[1]


def cfg_of(text):
    return config.from_dict(yaml.safe_load(text))


class Beispiele(unittest.TestCase):
    def test_alle_mitgelieferten_beispiele_sind_gueltig(self):
        dateien = sorted((ROOT / "beispiele").glob("*.yaml"))
        self.assertTrue(dateien)
        for pfad in dateien:
            with self.subTest(pfad.name):
                config.load(pfad)

    def test_die_orte_der_oberflaeche_sind_gueltige_typen(self):
        for typ in UI_PLACE_TYPES:
            with self.subTest(typ):
                cfg_of(f"orte:\n  - {{name: X, typ: {typ}}}\n")


class LeereAbschnitte(unittest.TestCase):
    def test_leerer_abschnitt_heisst_standardwert(self):
        for abschnitt, erwartet in (("viertel", []), ("orte", []), ("beschriftung", {})):
            with self.subTest(abschnitt):
                self.assertEqual(cfg_of(f"name: A\n{abschnitt}:\n")[abschnitt], erwartet)
        for abschnitt in ("mauer", "gelaende", "ausgabe"):
            with self.subTest(abschnitt):
                cfg = cfg_of(f"name: A\n{abschnitt}:\n")
                self.assertEqual(cfg[abschnitt]["tore" if abschnitt == "mauer" else
                                                 "biotop" if abschnitt == "gelaende" else "bildgroesse"],
                                 config.DEFAULTS[abschnitt]["tore" if abschnitt == "mauer" else
                                                           "biotop" if abschnitt == "gelaende" else "bildgroesse"])

    def test_leerer_wald_bleibt_kein_wald(self):
        self.assertEqual(cfg_of("gelaende:\n  wald:\n")["gelaende"]["wald"], [])

    def test_leere_datei_ergibt_standardwerte(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = pathlib.Path(tmp) / "leer.yaml"
            pfad.write_text("", encoding="utf-8")
            self.assertEqual(config.load(pfad)["name"], config.DEFAULTS["name"])


class FalscheStruktur(unittest.TestCase):
    def test_klare_meldung_statt_absturz(self):
        faelle = {
            "Liste statt Zuordnung": "- a\n- b\n",
            "nur Text": "nur text\n",
            "mauer ist eine Zahl": "mauer: 5\n",
            "viertel ist eine Zuordnung": "viertel:\n  name: X\n",
            "viertel-Eintrag ist Text": "viertel:\n  - Hafen\n",
            "viertel-Eintrag leer": "viertel:\n  -\n",
            "ort ist Text": "orte:\n  - Schenke\n",
            "name ist eine Liste": "name: [a, b]\n",
            "punkte keine Liste": "stadtform: eigene\nmauer:\n  punkte: 5\n",
            "punkt ist eine Zuordnung": "stadtform: eigene\nmauer:\n  punkte: [{x: 1}]\n",
        }
        for name, text in faelle.items():
            with self.subTest(name), self.assertRaises(ValueError):
                cfg_of(text)

    def test_ungueltiges_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = pathlib.Path(tmp) / "kaputt.yaml"
            pfad.write_text("name: [offen\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "kein gültiges YAML"):
                config.read_yaml(pfad)


class Zahlen(unittest.TestCase):
    def test_unendlich_ist_keine_ganze_zahl(self):
        for wert in (".inf", "-.inf", "'1e400'", ".nan"):
            with self.subTest(wert), self.assertRaisesRegex(ValueError, "einwohner"):
                cfg_of(f"einwohner: {wert}\n")


class Namen(unittest.TestCase):
    def test_name_wird_ein_text(self):
        self.assertEqual(cfg_of("name: 1848\n")["name"], "1848")
        self.assertEqual(cfg_of("name:\n")["name"], config.DEFAULTS["name"])
        self.assertEqual(cfg_of("name: '   '\n")["name"], config.DEFAULTS["name"])

    def test_steuerzeichen_fallen_weg(self):
        # in SVG/XML verboten: der Name würde sonst das SVG unlesbar machen
        self.assertEqual(cfg_of('name: "A\\x01B\\x0b"\n')["name"], "AB")

    def test_ort_ohne_name_bekommt_den_typ_als_namen(self):
        self.assertEqual(cfg_of("orte:\n  - {typ: gasthaus}\n")["orte"][0]["name"], "Gasthaus")
        self.assertEqual(cfg_of("orte:\n  - {typ: gasthaus, name: }\n")["orte"][0]["name"], "Gasthaus")

    def test_viertel_ohne_name(self):
        self.assertEqual(cfg_of("viertel:\n  - {typ: handwerk}\n")["viertel"][0]["name"], "")
        self.assertEqual(cfg_of("viertel:\n  - {typ: handwerk, name: }\n")["viertel"][0]["name"], "")

    def test_kuerzel_und_viertel_der_orte_sind_texte(self):
        ort = cfg_of("orte:\n  - {name: A, typ: laden, kuerzel: 7, viertel: 3}\n")["orte"][0]
        self.assertEqual((ort["kuerzel"], ort["viertel"]), ("7", "3"))


class Typen(unittest.TestCase):
    def test_unbekannter_viertel_typ(self):
        with self.assertRaisesRegex(ValueError, "hafn"):
            cfg_of("viertel:\n  - {name: X, typ: hafn}\n")

    def test_unbekannter_ort_typ(self):
        with self.assertRaisesRegex(ValueError, "zauberturm"):
            cfg_of("orte:\n  - {name: X, typ: zauberturm}\n")

    def test_alternative_schreibweisen_bleiben_gueltig(self):
        self.assertEqual(cfg_of("orte:\n  - {name: X, typ: Dom}\n")["orte"][0]["typ"], "kathedrale")
        self.assertEqual(cfg_of("orte:\n  - {name: X, typ: Schloss}\n")["orte"][0]["typ"], "palast")
        self.assertEqual(cfg_of("orte:\n  - {name: X, typ: burg, lage: Insel}\n")["orte"][0]["lage"], "insel")

    def test_festung_lage(self):
        with self.assertRaisesRegex(ValueError, "lage"):
            cfg_of("orte:\n  - {name: X, typ: festung, lage: landzunke}\n")

    def test_ort_mit_anzahl_ohne_name(self):
        orte = cfg_of("orte:\n  - {typ: gasthaus, anzahl: 2}\n")["orte"]
        self.assertEqual([o["kuerzel"] for o in orte], ["G1", "G2"])


class Formate(unittest.TestCase):
    def test_einzelnes_format_als_text(self):
        self.assertEqual(cfg_of("ausgabe: {formate: PNG}\n")["ausgabe"]["formate"], ["png"])

    def test_doppelte_und_leere_angaben(self):
        self.assertEqual(cfg_of("ausgabe: {formate: [svg, SVG, pdf]}\n")["ausgabe"]["formate"], ["svg", "pdf"])
        self.assertEqual(cfg_of("ausgabe: {formate: }\n")["ausgabe"]["formate"], ["svg", "png"])

    def test_unbekanntes_format(self):
        with self.assertRaisesRegex(ValueError, "jpg"):
            cfg_of("ausgabe: {formate: [svg, jpg]}\n")
        with self.assertRaises(ValueError):
            cfg_of("ausgabe: {formate: 5}\n")


class Kommandozeile(unittest.TestCase):
    def test_fehler_als_meldung_ohne_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = pathlib.Path(tmp) / "falsch.yaml"
            pfad.write_text("name: A\norte:\n  - {name: X, typ: zauberturm}\n", encoding="utf-8")
            res = subprocess.run([sys.executable, "-m", "stadtkarte", str(pfad), "-o", tmp],
                                 capture_output=True, text=True, cwd=ROOT, timeout=120)
        self.assertEqual(res.returncode, 1)
        self.assertIn("Fehler:", res.stderr)
        self.assertIn("zauberturm", res.stderr)
        self.assertNotIn("Traceback", res.stderr)

    def test_fehlende_datei(self):
        res = subprocess.run([sys.executable, "-m", "stadtkarte", "gibt/es/nicht.yaml"],
                             capture_output=True, text=True, cwd=ROOT, timeout=120)
        self.assertEqual(res.returncode, 1)
        self.assertNotIn("Traceback", res.stderr)


if __name__ == "__main__":
    unittest.main()
