"""Selbsttest des gebauten Programms (ohne Python-Umgebung des Projekts lauffähig).

Startet dist/Stadtkarten-Werkstatt ohne Browser, erzeugt eine kleine Karte über die Oberfläche
(Tag und Nacht), lädt PNG und SVG herunter und prüft sie. Exit-Code 0 = alles in Ordnung.

Aufruf (im Projektordner):  python packaging/selftest.py
"""
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAME = "Stadtkarten-Werkstatt"
EXE = ROOT / "dist" / NAME / (NAME + (".exe" if sys.platform == "win32" else ""))
PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"


def get(path, timeout=300):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def post(path, data, timeout=300):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main():
    if not EXE.exists():
        sys.exit(f"Programm nicht gefunden: {EXE}")
    proc = subprocess.Popen([str(EXE), "--kein-browser", "--port", str(PORT)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(120):
            try:
                get("/", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        else:
            sys.exit("Server startet nicht.")
        _, _, raw = get("/api/options")
        opts = json.loads(raw)
        assert len(opts["biomes"]) >= 6 and "hafenstadt" in opts["examples"], opts
        for night in (False, True):
            _, _, raw = get("/api/example?name=hafenstadt")
            cfg = json.loads(raw)
            cfg["ausgabe"]["bildgroesse"] = 1000
            cfg["ausgabe"]["nacht"] = night
            t = time.time()
            res = post("/api/generate", cfg)
            status, ctype, png = get(f"/api/download?id={res['id']}&format=png")
            assert status == 200 and png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 100_000, (status, ctype, len(png))
            _, _, svg = get(f"/api/download?id={res['id']}&format=svg")
            assert b"font-family:'EB Garamond'" in svg, "Schrift ist nicht eingebettet"
            print(f"ok {'Nacht' if night else 'Tag'}: {res['stats']['gebaeude']} Gebäude, "
                  f"{len(png) // 1024} KB PNG, {time.time() - t:.1f} s")
        print("Selbsttest bestanden.")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
