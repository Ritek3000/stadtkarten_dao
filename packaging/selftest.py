"""Selbsttest des gebauten Programms (ohne Python-Umgebung des Projekts lauffähig).

Startet dist/Stadtkarten-Werkstatt ohne Browser, erzeugt eine kleine Karte über die Oberfläche
(Tag und Nacht), lädt PNG, SVG, die interaktive Karte (HTML) und das Web-Paket herunter und prüft sie, verschiebt eine Beschriftung. Unter Linux wird zusätzlich geprüft, dass
gestartete Hilfsprogramme (xdg-user-dir, xdg-open) nicht die mitgebrachten Bibliotheken laden.
Exit-Code 0 = alles in Ordnung.

Aufruf (im Projektordner):  python packaging/selftest.py
"""
import io
import json
import os
import pathlib
import re
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from collections import Counter

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


def webp_size(data):
    """Breite und Höhe einer WebP-Datei (ohne Pillow, der Selbsttest läuft auch ohne Projektumgebung)."""
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP", "keine WebP-Datei"
    chunk = data[12:16]
    if chunk == b"VP8 ":
        w, h = struct.unpack("<HH", data[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if chunk == b"VP8L":
        b = int.from_bytes(data[21:25], "little")
        return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X":
        return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
    raise AssertionError(f"unbekanntes WebP-Format {chunk}")


def check_web_package(data, cfg):
    """Web-Paket (ZIP): Ortsliste, Beschriftung und Kartenbild passen zusammen."""
    z = zipfile.ZipFile(io.BytesIO(data))
    names = sorted(z.namelist())
    folder = names[0].split("/")[0]
    assert names == [f"{folder}/{n}" for n in ("beschriftung.svg", "karte.webp", "orte.json", "stadt.yaml")], names
    orte = json.loads(z.read(f"{folder}/orte.json").decode("utf-8"))
    svg = z.read(f"{folder}/beschriftung.svg").decode("utf-8")
    assert folder == orte["kennung"] + "_web", (folder, orte["kennung"])
    # 1. jeder key genau einmal als data-key, jede Orts- und Viertelbeschriftung in der Ortsliste
    keys = re.findall(r'data-key="([^"]*)"', svg)
    listed = [o["key"] for o in orte["orte"]] + [v["key"] for v in orte["viertel"]]
    count = Counter(keys)
    assert all(count[k] == 1 for k in listed), [k for k in listed if count[k] != 1]
    assert sorted(k for k in keys if k.startswith(("orte:", "viertel:"))) == sorted(listed), "Ortsliste unvollständig"
    # 2. Bildgröße = breite/hoehe = viewBox
    size = webp_size(z.read(f"{folder}/karte.webp"))
    vb = tuple(int(v) for v in re.search(r'viewBox="0 0 (\d+) (\d+)"', svg).groups())
    assert size == (orte["breite"], orte["hoehe"]) == vb, (size, orte["breite"], orte["hoehe"], vb)
    # 3. keine eingebettete Schrift
    assert "@font-face" not in svg and "base64" not in svg, "Schrift in beschriftung.svg eingebettet"
    # 4. jeder Ort der Stadtbeschreibung ist platziert oder als nicht platziert gemeldet
    assert len(orte["orte"]) + len(orte["nicht_platziert"]) == len(cfg["orte"]), \
        (len(orte["orte"]), orte["nicht_platziert"], len(cfg["orte"]))
    assert b"kennung:" in z.read(f"{folder}/stadt.yaml")
    return orte


def fake_xdg_user_dir(folder):
    """Ersatz für xdg-user-dir, der festhält, welchen Bibliothekspfad das Programm an Hilfsprogramme weitergibt."""
    script = folder / "xdg-user-dir"
    script.write_text('#!/bin/sh\nprintf "%s" "$LD_LIBRARY_PATH" > "$(dirname "$0")/ld_library_path.txt"\n'
                      'echo "$HOME"\n')
    script.chmod(0o755)
    env = dict(os.environ, PATH=f"{folder}{os.pathsep}{os.environ.get('PATH', '')}")
    env.pop("LD_LIBRARY_PATH", None)
    return env


def main():
    if not EXE.exists():
        sys.exit(f"Programm nicht gefunden: {EXE}")
    tmp = pathlib.Path(tempfile.mkdtemp())
    env = fake_xdg_user_dir(tmp) if sys.platform.startswith("linux") else None
    proc = subprocess.Popen([str(EXE), "--kein-browser", "--port", str(PORT)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    try:
        for _ in range(120):
            try:
                get("/", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        else:
            sys.exit("Server startet nicht.")
        if env is not None:
            seen = (tmp / "ld_library_path.txt").read_text()
            assert seen == "", f"Hilfsprogramme bekommen die Programmbibliotheken untergeschoben: LD_LIBRARY_PATH={seen}"
            print("ok Umgebung für Hilfsprogramme sauber")
        _, _, raw = get("/api/options")
        opts = json.loads(raw)
        assert len(opts["biomes"]) >= 6 and "hafenstadt" in opts["examples"], opts
        for night in (False, True):
            _, _, raw = get("/api/example?name=hafenstadt")
            cfg = json.loads(raw)
            cfg["ausgabe"]["bildgroesse"] = 1000
            cfg["ausgabe"]["nacht"] = night
            if night:
                cfg["seed"] = 1   # zweite Variante: Seed 1 erzeugte einmal Gassenflächen als GeometryCollection
            t = time.time()
            res = post("/api/generate", cfg)
            assert res["stats"]["rendern"] == "prozesse", "Render-Prozesse laufen nicht (Rückfall auf seriell)"
            status, ctype, png = get(f"/api/download?id={res['id']}&format=png")
            assert status == 200 and png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 100_000, (status, ctype, len(png))
            _, _, svg = get(f"/api/download?id={res['id']}&format=svg")
            assert b"font-family:'EB Garamond'" in svg, "Schrift ist nicht eingebettet"
            if night:   # gleicher Seed muss dieselbe Karte liefern (Prozessor-Varianten prüft determinismus.py)
                again = post("/api/generate", cfg)
                _, _, svg2 = get(f"/api/download?id={again['id']}&format=svg")
                assert svg2 == svg, (f"gleicher Seed, andere Karte ({res['stats']['gebaeude']} gegen "
                                     f"{again['stats']['gebaeude']} Gebäude)")
                print("ok gleicher Seed, gleiche Karte")
            _, _, page = get(f"/api/download?id={res['id']}&format=html")
            assert b"data:image/webp;base64," in page and b'<g id="b-viertel">' in page and b"<text" in page, \
                "interaktive Karte unvollständig"
            if not night:
                orte = check_web_package(get(f"/api/download?id={res['id']}&format=web")[2], cfg)
                print(f"ok Web-Paket: {len(orte['orte'])} Orte, {len(orte['viertel'])} Viertel")
            if not night:   # Beschriftung verschieben: landet ohne Neuerzeugen in der fertigen Karte
                assert '<g data-key="titel"' in res["labels"], "Beschriftung nicht verschiebbar"
                post("/api/labels", {"id": res["id"], "beschriftung": {"titel": [-10, 0]}})
                _, _, svg = get(f"/api/download?id={res['id']}&format=svg")
                assert b'<g data-key="titel" transform="translate(-100.0,0.0)">' in svg, "Verschiebung fehlt in der Karte"
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
