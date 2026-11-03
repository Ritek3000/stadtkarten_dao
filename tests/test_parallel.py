"""Render-Prozesse (stadtkarte.parallel): nur ein ausgefallener Pool schaltet auf serielles Rendern um, ein fehlerhafter
Auftrag (z.B. ein ungültiges SVG) nicht."""
import unittest
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool

from stadtkarte import parallel

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="red"/></svg>'


def fertig(wert=None, fehler=None):
    fut = Future()
    if fehler is not None:
        fut.set_exception(fehler)
    else:
        fut.set_result(wert)
    return fut


class Pool(unittest.TestCase):
    def setUp(self):
        parallel._BROKEN = False

    def tearDown(self):
        parallel.shutdown()
        parallel._BROKEN = False

    def test_fehler_im_auftrag_laesst_den_pool_in_ruhe(self):
        job = parallel._Job(fertig(fehler=ValueError("kein SVG")), (SVG, None, None))
        with self.assertRaises(ValueError):
            job.result()
        self.assertEqual(parallel.mode(), "prozesse")

    def test_ausgefallener_pool_wird_durch_eigenes_rendern_ersetzt(self):
        job = parallel._Job(fertig(fehler=BrokenProcessPool("Prozess beendet")), (SVG, None, None))
        self.assertEqual(job.result()[:4], b"\x89PNG")
        self.assertEqual(parallel.mode(), "seriell")

    def test_zurueckgenommener_auftrag_rendert_selbst(self):
        fut = Future()
        fut.cancel()
        job = parallel._Job(fut, (SVG, None, None))
        self.assertEqual(job.result()[:4], b"\x89PNG")
        self.assertEqual(parallel.mode(), "prozesse")

    def test_ohne_pool_kommt_der_fehler_erst_bei_result(self):
        parallel._BROKEN = True   # kein Pool: png_async rendert selbst
        job = parallel.png_async("das ist kein SVG")   # darf nicht schon hier auslösen
        with self.assertRaises(ValueError):
            job.result()
        self.assertEqual(parallel.png_async(SVG).result()[:4], b"\x89PNG")

    def test_pool_rendert_und_bleibt_nach_fehlerhaftem_auftrag_aktiv(self):
        self.assertEqual(parallel.png_async(SVG).result()[:4], b"\x89PNG")
        with self.assertRaises(ValueError):
            parallel.png_async("das ist kein SVG").result()
        self.assertEqual(parallel.mode(), "prozesse")
        self.assertEqual(parallel.png_async(SVG).result()[:4], b"\x89PNG")


if __name__ == "__main__":
    unittest.main()
