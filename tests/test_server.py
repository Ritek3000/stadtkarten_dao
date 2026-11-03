"""Lokaler Webserver der Werkstatt: nur Anfragen der Werkstatt selbst, begrenzte Anfragegröße, klare Fehlerantworten."""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from stadtkarte import parallel
from stadtkarte.ui.__main__ import MAX_BODY, Handler
from tests.test_generator import HINWEISE, hinweiskarte


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        parallel.shutdown()   # Render-Prozesse, die das Erzeugen einer Karte gestartet hat
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            res = conn.getresponse()
            return res.status, res.read().decode("utf-8")
        finally:
            conn.close()

    @property
    def own(self):
        return f"http://127.0.0.1:{self.port}"

    def test_eigene_anfragen_funktionieren(self):
        status, text = self.request("GET", "/api/options")
        self.assertEqual(status, 200)
        self.assertIn("hafenstadt", json.loads(text)["examples"])
        status, text = self.request("GET", "/api/options", headers={"Host": f"localhost:{self.port}"})
        self.assertEqual(status, 200)

    def test_fremder_host_wird_abgelehnt(self):   # DNS-Rebinding
        status, text = self.request("GET", "/api/options", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        self.assertNotIn("output_dir", text)
        status, _ = self.request("GET", "/", headers={"Host": f"evil.example:{self.port}"})
        self.assertEqual(status, 403)

    def test_fremder_origin_wird_abgelehnt(self):   # Aufruf durch eine fremde Webseite (CSRF)
        for origin in ("http://evil.example", "null", f"http://127.0.0.1:{self.port + 1}"):
            with self.subTest(origin):
                status, _ = self.request("POST", "/api/parse", body="name: A",
                                         headers={"Origin": origin, "Content-Type": "text/plain"})
                self.assertEqual(status, 403)

    def test_eigener_origin_wird_angenommen(self):
        status, text = self.request("POST", "/api/parse", body="name: A",
                                    headers={"Origin": self.own, "Content-Type": "text/plain"})
        self.assertEqual((status, json.loads(text)), (200, {"name": "A"}))
        status, _ = self.request("POST", "/api/parse", body="name: A")   # ohne Origin (Skripte, Selbsttest)
        self.assertEqual(status, 200)

    def test_ungueltige_laengenangaben(self):
        for laenge in ("-1", str(MAX_BODY + 1), "abc"):
            with self.subTest(laenge):
                status, text = self.request("POST", "/api/parse", body=b"x", headers={"Content-Length": laenge})
                self.assertEqual(status, 400)
                self.assertIn("error", json.loads(text))

    def test_unbekanntes_beispiel_ohne_pfad_in_der_antwort(self):
        status, text = self.request("GET", "/api/example?name=gibtsnicht")
        self.assertEqual(status, 404)
        self.assertNotIn("/", json.loads(text)["error"])
        status, _ = self.request("GET", "/api/example?name=hafenstadt")
        self.assertEqual(status, 200)

    def test_erzeugen_liefert_die_hinweise_ohne_vorsatz(self):
        cfg = hinweiskarte()
        cfg["ausgabe"]["nachtkarte"] = False   # kein Hintergrund-Thread für die Nachtkarte
        status, text = self.request("POST", "/api/generate", body=json.dumps(cfg),
                                    headers={"Content-Type": "application/json"})
        self.assertEqual(status, 200, text[:300])
        self.assertEqual(json.loads(text)["hints"], HINWEISE)

    def test_fehlerhafte_angaben_ergeben_400_mit_meldung(self):
        cfg = {"name": "A", "orte": [{"name": "X", "typ": "zauberturm"}]}
        status, text = self.request("POST", "/api/generate", body=json.dumps(cfg),
                                    headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)
        self.assertIn("zauberturm", json.loads(text)["error"])


if __name__ == "__main__":
    unittest.main()
