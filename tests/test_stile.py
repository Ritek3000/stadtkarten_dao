"""Zeichenstile (ausgabe.stil): Angaben, Filter, Texturen, Schrift. Die langsamen Fälle (Karte zeichnen und rendern)
lassen sich mit STADTKARTE_SCHNELL=1 überspringen."""
import io
import os
import unittest

import numpy as np
from PIL import Image

from stadtkarte import config, stile
from stadtkarte.generator import generate
from stadtkarte.render import render_svg, split_labels, to_png
from stadtkarte.styles import COLORS, STIL_ALIASE, STILE
from tests.golden import klein


class Angaben(unittest.TestCase):
    def test_jeder_stil_ist_gueltig(self):
        for stil in STILE:
            with self.subTest(stil):
                self.assertEqual(config.from_dict({"ausgabe": {"stil": stil}})["ausgabe"]["stil"], stil)

    def test_andere_schreibweisen(self):
        for roh, stil in (("Goldene Stunde", "abendlicht"), ("Sepia-Stich", "sepia"), ("Kolorierter Stich", "stich"),
                          ("Kupferstich", "stich"), ("Feder", "tusche"), ("Skizze", "bleistift"), ("alt", "pergament")):
            with self.subTest(roh):
                self.assertEqual(config.from_dict({"ausgabe": {"stil": roh}})["ausgabe"]["stil"], stil)
        self.assertTrue(set(STIL_ALIASE.values()) <= set(STILE))

    def test_unbekannter_stil_nennt_die_moeglichen(self):
        with self.assertRaisesRegex(ValueError, "tusche.*aquarell"):
            config.from_dict({"ausgabe": {"stil": "comic"}})

    def test_filter_und_texturen(self):
        for stil in stile.EIGENE:
            with self.subTest(stil):
                filt = stile.filter_svg(stil, 0.25, 500)
                self.assertTrue(filt.startswith('<filter id="stil"'))
                self.assertIn('result="out"', filt)   # der letzte Schritt liefert das Ergebnis
                mul, deck = stile.bilder(stil, 500, 0.25)
                self.assertTrue(mul or deck or stile.muster(stil, 0.25, 500) or stil == "pastell")
        self.assertEqual(stile.filter_svg("standard", 1, 2000), "")
        self.assertEqual(stile.filter_svg("pergament", 1, 2000), "")


@unittest.skipIf(os.environ.get("STADTKARTE_SCHNELL") == "1", "langsame Tests übersprungen")
class Zeichnen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = generate(config.from_dict(klein(ausgabe={"bildgroesse": 400})))

    def zeichne(self, stil, nacht=False):
        self.m["cfg"]["ausgabe"]["stil"] = stil
        return render_svg(self.m, nacht=nacht)

    def test_jeder_stil_laesst_sich_rendern(self):
        bilder = {}
        for stil in STILE:
            with self.subTest(stil):
                svg = self.zeichne(stil)
                img = np.asarray(Image.open(io.BytesIO(to_png(svg))).convert("RGB"), dtype=np.float32)
                self.assertEqual(img.shape, (400, 400, 3))
                self.assertGreater(img.std(), 10)   # kein leeres oder einfarbiges Bild
                bilder[stil] = img
        for stil in stile.EIGENE:   # jeder Stil sieht anders aus als die Standardkarte
            self.assertGreater(np.abs(bilder[stil] - bilder["standard"]).mean(), 5, stil)

    def test_filter_umfasst_die_karte_aber_nicht_beschriftung_und_nachtlichter(self):
        svg = self.zeichne("tusche", nacht=True)
        start = svg.index('<g filter="url(#stil)">')
        ende = svg.index("</g></g>", start)
        self.assertLess(ende, svg.index("glowNight)") if "glowNight)" in svg else len(svg))
        self.assertLess(ende, svg.index('<g id="beschriftung">'))
        karte, _ = split_labels(svg)
        self.assertIn('filter="url(#stil)"', karte)

    def test_schrift_in_tinte(self):
        for stil in ("tusche", "pastell", "bleistift"):
            with self.subTest(stil):
                _, schrift = split_labels(self.zeichne(stil))
                ink, halo = stile.schrift(stil)
                self.assertIn(f'fill="{ink}"', schrift)
                self.assertNotIn(f'fill="{COLORS["text"]}"', schrift)
        _, schrift = split_labels(self.zeichne("aquarell"))
        self.assertIn(f'fill="{COLORS["text"]}"', schrift)

    def test_vorschau_sieht_aus_wie_die_volle_aufloesung(self):
        """Die Kanten rechnen in Kartenmaßen: die halb so große Vorschau der Werkstatt hat so viel Tinte wie die volle
        Karte (bei der kleinsten Bildgröße der Oberfläche; bei sehr kleinen Karten sind die Radien unter einem Pixel)."""
        m = generate(config.from_dict(klein(ausgabe={"bildgroesse": 1500, "stil": "tusche"})))
        svg = render_svg(m)
        voll = Image.open(io.BytesIO(to_png(svg))).convert("L").resize((750, 750), Image.BILINEAR)
        halb = Image.open(io.BytesIO(to_png(svg, zoom=0.5))).convert("L")
        a, b = np.asarray(voll, np.float32), np.asarray(halb, np.float32)
        self.assertLess(abs(a.mean() - b.mean()), 6)


if __name__ == "__main__":
    unittest.main()
