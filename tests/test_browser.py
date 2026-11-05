"""Browserversion (stadtkarte/ui/browser.py, web/, packaging/web.py): ohne Pyodide, nur die schnellen Teile."""
import json
import unittest

from stadtkarte.ui import browser


class BrowserApiTest(unittest.TestCase):
    def test_optionen_und_beispiel(self):
        r = browser.handle("GET", "/api/options")
        self.assertEqual(r["status"], 200)
        opt = json.loads(r["body"])
        self.assertIn("hafenstadt", opt["examples"])
        r = browser.handle("GET", "/api/example", "?name=hafenstadt")
        self.assertEqual(json.loads(r["body"])["name"], "Rabenfurt")

    def test_yaml_hin_und_zurueck(self):
        raw = {"name": "Testheim", "seed": 7}
        text = browser.handle("POST", "/api/yaml", body=json.dumps(raw))["body"].decode()
        self.assertEqual(json.loads(browser.handle("POST", "/api/parse", body=text)["body"]), raw)

    def test_fehler_wie_beim_server(self):
        self.assertEqual(browser.handle("GET", "/api/full", "?id=gibtsnicht")["status"], 404)
        self.assertEqual(browser.handle("GET", "/api/unbekannt")["status"], 404)
        r = browser.handle("POST", "/api/generate", body=json.dumps({"einwohner": -5}))
        self.assertEqual(r["status"], 400)
        self.assertIn("einwohner", json.loads(r["body"])["error"])

    def test_spaeter_rechnet_einmal_und_erst_auf_anfrage(self):
        n = []
        job = browser.Spaeter(lambda: n.append(1) or len(n))
        self.assertEqual(n, [])
        self.assertEqual((job.result(), job.result()), (1, 1))


class WebBauTest(unittest.TestCase):
    def test_index_html_passt_zum_bauskript(self):
        import importlib.util
        import pathlib
        spec = importlib.util.spec_from_file_location("web_bau", pathlib.Path(__file__).parents[1] / "packaging" / "web.py")
        web = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(web)
        html = web.index_html()   # bricht ab, wenn sich die Pfade in index.html geändert haben
        self.assertIn('<script src="werkstatt.js"></script>', html)
        self.assertNotIn('"/static/', html)
        self.assertIn("window.stadtkarteDownload", html)


if __name__ == "__main__":
    unittest.main()
