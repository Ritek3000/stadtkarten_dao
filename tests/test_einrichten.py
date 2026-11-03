"""Einrichtung der Python-Umgebung (einrichten.py): eine abgebrochene Einrichtung wird beim nächsten Start wiederholt,
geänderte Anforderungen werden übernommen, ohne Netz startet eine funktionierende Umgebung weiter."""
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import einrichten   # noqa: E402


class Befehle:
    """Ersatz für subprocess.run: merkt sich die Aufrufe und antwortet nach Vorgabe."""

    def __init__(self, root, venv_ok=True, pip_ok=True, imports_ok=True):
        self.root, self.venv_ok, self.pip_ok, self.imports_ok = root, venv_ok, pip_ok, imports_ok
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[1:3] == ["-m", "venv"]:
            if self.venv_ok:
                py = einrichten.venv_python(self.root / ".venv")
                py.parent.mkdir(parents=True)
                py.write_text("", encoding="utf-8")
            return types.SimpleNamespace(returncode=0 if self.venv_ok else 1)
        if cmd[1:3] == ["-m", "pip"]:
            ok = self.pip_ok or "--upgrade" in cmd   # das Aktualisieren von pip selbst darf scheitern
            return types.SimpleNamespace(returncode=0 if ok else 1)
        return types.SimpleNamespace(returncode=0 if self.imports_ok else 1)   # Prüfung der Pakete

    def pip_installs(self):
        return [c for c in self.calls if c[1:3] == ["-m", "pip"] and "-r" in c]


class Einrichten(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        (self.root / "requirements.txt").write_text("numpy\n", encoding="utf-8")
        self.stamp = self.root / ".venv" / ".requirements.sha256"
        self.want = hashlib.sha256(b"numpy\n").hexdigest()

    def tearDown(self):
        self._tmp.cleanup()

    def setup_venv(self, stamp=None):
        py = einrichten.venv_python(self.root / ".venv")
        py.parent.mkdir(parents=True)
        py.write_text("", encoding="utf-8")
        if stamp is not None:
            self.stamp.write_text(stamp, encoding="utf-8")

    def test_erster_start_legt_umgebung_an_und_merkt_sich_den_stand(self):
        run = Befehle(self.root)
        self.assertEqual(einrichten.setup(self.root, run), 0)
        self.assertEqual(len(run.pip_installs()), 1)
        self.assertEqual(self.stamp.read_text(encoding="utf-8"), self.want)

    def test_unveraenderte_anforderungen_tun_nichts(self):
        self.setup_venv(self.want)
        run = Befehle(self.root)
        self.assertEqual(einrichten.setup(self.root, run), 0)
        self.assertEqual(run.calls, [])

    def test_geaenderte_anforderungen_werden_nachinstalliert(self):
        self.setup_venv("alter-stand")
        run = Befehle(self.root)
        self.assertEqual(einrichten.setup(self.root, run), 0)
        self.assertEqual(len(run.pip_installs()), 1)
        self.assertFalse([c for c in run.calls if c[1:3] == ["-m", "venv"]])
        self.assertEqual(self.stamp.read_text(encoding="utf-8"), self.want)

    def test_umgebung_ohne_stempel_aus_der_alten_einrichtung_wird_geprueft(self):
        self.setup_venv()   # so sah die Umgebung vor dem Stempel aus
        run = Befehle(self.root)
        self.assertEqual(einrichten.setup(self.root, run), 0)
        self.assertEqual(self.stamp.read_text(encoding="utf-8"), self.want)

    def test_ohne_netz_startet_eine_funktionierende_umgebung_weiter(self):
        self.setup_venv("alter-stand")
        run = Befehle(self.root, pip_ok=False, imports_ok=True)
        self.assertEqual(einrichten.setup(self.root, run), 0)
        self.assertEqual(self.stamp.read_text(encoding="utf-8"), "alter-stand")   # nächster Start versucht es erneut

    def test_abgebrochene_einrichtung_wird_beim_naechsten_start_wiederholt(self):
        # früher: Umgebung angelegt, pip scheitert (kein Netz) -> der nächste Start übersprang die Einrichtung
        erst = Befehle(self.root, pip_ok=False, imports_ok=False)
        self.assertEqual(einrichten.setup(self.root, erst), 1)
        self.assertFalse(self.stamp.exists())
        zweit = Befehle(self.root)
        self.assertEqual(einrichten.setup(self.root, zweit), 0)
        self.assertEqual(len(zweit.pip_installs()), 1)
        self.assertTrue(self.stamp.exists())

    def test_kaputte_umgebung_ohne_netz_meldet_fehler(self):
        self.setup_venv()
        run = Befehle(self.root, pip_ok=False, imports_ok=False)
        self.assertEqual(einrichten.setup(self.root, run), 1)
        self.assertFalse(self.stamp.exists())

    def test_scheitert_das_anlegen_bleibt_keine_halbe_umgebung(self):
        (self.root / ".venv").mkdir()
        (self.root / ".venv" / "Rest.txt").write_text("", encoding="utf-8")
        self.assertEqual(einrichten.setup(self.root, Befehle(self.root, venv_ok=False)), 1)
        self.assertFalse((self.root / ".venv").exists())


class EchteUmgebung(unittest.TestCase):
    def test_script_legt_eine_echte_umgebung_an(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            shutil.copy(ROOT / "einrichten.py", tmp / "einrichten.py")
            (tmp / "requirements.txt").write_text("# keine Pakete nötig\n", encoding="utf-8")
            env = {**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}   # ohne Netz
            res = subprocess.run([sys.executable, str(tmp / "einrichten.py")], capture_output=True, text=True,
                                 env=env, timeout=300)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertTrue(einrichten.venv_python(tmp / ".venv").exists())
            self.assertTrue((tmp / ".venv" / ".requirements.sha256").exists())
            zweit = subprocess.run([sys.executable, str(tmp / "einrichten.py")], capture_output=True, text=True,
                                   env=env, timeout=60)
            self.assertEqual((zweit.returncode, zweit.stdout), (0, ""))   # unverändert: nichts zu tun


if __name__ == "__main__":
    unittest.main()
