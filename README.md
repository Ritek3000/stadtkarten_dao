# Stadtkarten für „Die Alte Ordnung“

Erzeugt aus einer YAML-Beschreibung eine Stadtkarte (SVG, PNG, PDF).

## Oberfläche (empfohlen)

Doppelklick auf **`Stadtkarte starten.bat`**. Beim ersten Start wird die Python-Umgebung eingerichtet, danach öffnet sich die
Stadtkarten-Werkstatt im Browser:

- links alle Angaben (Gelände, Biotop, Mauer, Viertel, besondere Orte, Ausgabe), Himmelsrichtungen per Kompass
- „Karte erzeugen“ zeigt rechts die Vorschau (Mausrad zoomt, Ziehen verschiebt)
- Download als PNG, WebP (klein, gut für Foundry/Roll20), PDF oder SVG, oder alles auf einmal in den Ordner `ausgabe`
- „Öffnen…“/„Speichern“ lädt bzw. speichert die Stadtbeschreibung als `.yaml`; oben rechts lassen sich die Beispiele laden

Alternativ: `.venv\Scripts\python -m stadtkarte.ui` (Optionen: `--port 8765`, `--kein-browser`).

**Linux / macOS:** `./stadtkarte-starten.sh` im Projektordner ausführen (benötigt Python 3.10 oder neuer; unter
Debian/Ubuntu zusätzlich das Paket `python3-venv`). Beim ersten Start wird die Umgebung eingerichtet, danach öffnet sich
die Werkstatt im Browser. Die Karten nutzen die mitgelieferte freie Schrift EB Garamond (`stadtkarte/fonts`, SIL Open Font
License) und sehen daher unter Windows und Linux gleich aus.

## Einrichtung (einmalig)

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Karte über die Kommandozeile erzeugen

```bash
.venv\Scripts\python -m stadtkarte beispiele\hafenstadt.yaml
```

Ergebnis landet in `ausgabe/`. Mit `--seed 77` probierst du eine andere Variante derselben Stadt.
Alle Angaben sind in [beispiele/hafenstadt.yaml](beispiele/hafenstadt.yaml) erklärt.

## Aufbau

| Datei | Aufgabe |
|---|---|
| `stadtkarte/config.py` | YAML einlesen, Standardwerte, Himmelsrichtungen |
| `stadtkarte/terrain.py` | Küste, Inseln, Fluss |
| `stadtkarte/city.py` | Stadtumriss, Mauer, Tore, Straßen, Viertel, Gebäude, besondere Orte, Hafen |
| `stadtkarte/fortress.py` | Festung/Bastion auf Insel, Landzunge oder an Land |
| `stadtkarte/surroundings.py` | Felder, Wald, Bäume, Vorstadthäuser, Brücken |
| `stadtkarte/styles.py` | Viertel-Typen, Farben, Schrift |
| `stadtkarte/render.py` | Zeichnen als SVG, Export PNG/PDF |
| `stadtkarte/shapes.py` | Hausgrundrisse: Quadrat, Rechteck, Raute, Fünfeck, Sechseck, L-Form, Achteck; Kreuz nur für Gotteshäuser; Mindestbreite 8 px |
| `stadtkarte/roofs.py` | detaillierte Dächer: Dachflächen mit Licht, Material je Biotop, Schornsteine, Gauben, Moos |
| `stadtkarte/noise.py` | vorberechnete Bodentexturen und Details (Körnung, Gras, Sandrippel, Schneeverwehungen, Felsrisse) |
| `stadtkarte/fonts/` | Schrift EB Garamond mit Lizenz (OFL) – in PNG/PDF verwendet und in SVG eingebettet |
| `stadtkarte/ui/` | Oberfläche: lokaler Webserver (`__main__.py`) und Seite (`index.html`) |

## Besondere Orte

| typ | Darstellung |
|---|---|
| `tempel` | Tempel mit kreuzförmigem Grundriss, gepflastertem Vorplatz und Brunnen |
| `kaserne` | Ringbau um einen Exerzierplatz |
| `friedhof` | umzäuntes Feld mit Grabreihen, Bäumen und Kapelle; mit `lage: ausserhalb` (oder bei Platzmangel im Ort) an einer Landstraße vor dem Tor |
| `festung` / `bastion` / `burg` | Sternfestung; `lage: insel` (Brücke), `landzunge` oder `land`. Mit Stadtmauer liegt der Zugang immer innerhalb: Brückenkopf bzw. Landzunge am Ufer in der Stadt, an Land als Zitadelle in der Mauer mit Tor zur Stadt |
| `kontor`, `werft`, `adelshaus` | ganzer Block als ein großes Gebäude (Adelshaus mit Garten) |
| `gasthaus`, `schmiede`, `muehle`, `laden` | einzelnes, passend gelegenes Haus |

## Stadtbild

- jedes Haus grenzt an eine Straße oder einen Platz (sonst wird es verschoben oder entfällt)
- jeder Platz hat einen Laufbrunnen, große Plätze zusätzlich einen Wochenmarkt; an breiten Straßenstellen stehen Ziehbrunnen
- größere leere Flächen (Höfe, freie Grundstücke) bekommen einzelne Bäume

## Nachtmodus

`ausgabe: nacht: true` (Oberfläche: „Nachtmodus“, Kommandozeile: `--nacht`) dunkelt die Karte bläulich ab. Es leuchten
Türme, Tore, Brückenlaternen, Essen, Minen, Laternen entlang der Hauptstraßen und an den Plätzen sowie die Fenster eines
Teils der Häuser. Wie viel leuchtet, hängt von der Einwohnerzahl ab: Dörfer haben wenige Laternen, kaum helle Fenster
und kleinere Wachfeuer. Dateien bekommen den Zusatz `_nacht`.

## Biotope

`gelaende: biotop:` legt Landschaft und Bauweise fest.

| biotop | Wirkung |
|---|---|
| `gemaessigt` (Standard) | grünes Land, Laub- und Nadelbäume, Steinmauer, gepflasterte Plätze |
| `sumpf` (auch `moor`) | Tümpel und Wasserläufe mit Schilf und Seerosen, Pfahlhäuser über Wasser, Bohlenstege und Knüppeldämme, Holzpalisade, Reetdächer, Weiden und Totholz |
| `nordland` (auch `winter`, `schnee`) | verschneites Land, verschneite Tannen, zugefrorene Seen mit Rissen, Eisschollen vor der Küste, Schneedächer, Palisade, Findlinge |
| `steppe` | trockenes Grasland, lichte Baumgruppen und Büsche, Felsbrocken, Palisade |
| `wueste` (auch `oase`) | Sand mit Dünen, Oasen mit Palmenring, grüne Ufer an Fluss und Küste, Lehmhäuser mit Flachdach, Lehmmauer, Palmenhaine |
| `gebirge` (auch `berg`, `zwerge`) | Zwergenstadt am Fels: Felsmassiv mit Steilkante, Graten und Schneefeldern auf der `kueste`-Seite, Stadt in Terrassen mit Stützmauern und Treppen, großes Tor in der Felswand, Klamm mit Wildbach statt Fluss, Mineneingänge mit Abraumhalden, glühende Essen, Schieferdächer, Festung auf einem Felssporn. Hafen/Fischer werden zu Markt/Handwerk |

Beispiele: [sumpfdorf.yaml](beispiele/sumpfdorf.yaml), [nordhafen.yaml](beispiele/nordhafen.yaml), [oasenstadt.yaml](beispiele/oasenstadt.yaml), [zwergenstadt.yaml](beispiele/zwergenstadt.yaml). Die Stadtgröße richtet sich nach `einwohner`, kleine Werte ergeben Dörfer.

## Weitergeben

Im Ordner `verteilung/` liegen nach dem Bauen zwei Dateien zum Weitergeben. Die Empfänger brauchen **kein Python**:

| Datei | Verwendung |
|---|---|
| `Stadtkarten-Werkstatt-Setup.exe` | Doppelklick installiert das Programm für den aktuellen Benutzer (ohne Adminrechte) nach `%LOCALAPPDATA%\Programs\Stadtkarten-Werkstatt`, mit Verknüpfungen auf dem Desktop und im Startmenü. Deinstallation über das Startmenü oder „Apps & Features“. |
| `Stadtkarten-Werkstatt-portable.zip` | Entpacken und `Stadtkarten-Werkstatt.exe` starten, z.B. vom USB-Stick. |

Das Programm öffnet die Werkstatt im Browser; gespeicherte Karten landen in `Dokumente\Stadtkarten`. Zum Beenden das schwarze Fenster schließen.

Da das Setup nicht digital signiert ist, warnt Windows SmartScreen beim ersten Start („Der Computer wurde durch Windows geschützt“) – über „Weitere Informationen“ → „Trotzdem ausführen“ geht es weiter.

**Neu bauen** (z.B. nach Änderungen am Programm):

```bash
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python packaging\build.py
```

Die Version steht in `packaging/build.py` (`VERSION`). Ein neues Setup ersetzt eine ältere Installation automatisch.

### Automatisch auf GitHub bauen (Windows und Linux)

Bei jedem Hochladen von Programmänderungen auf `main` baut GitHub Actions ([.github/workflows/pakete.yml](.github/workflows/pakete.yml))
beide Versionen, startet sie zur Probe (Tag- und Nachtkarte) und stellt sie bereit:

- **Download:** Repository → „Actions“ → „Pakete bauen“ → letzter Lauf → unten „Artifacts“
  (`stadtkarten-werkstatt-windows`, `stadtkarten-werkstatt-linux`, je 30 Tage verfügbar)
- **Release:** Einen Versions-Tag hochladen, z.B. `git tag v1.8.0` und `git push origin v1.8.0` – dann entsteht
  zusätzlich ein GitHub-Release mit Setup, portabler ZIP und Linux-Paket
- **Von Hand:** „Actions“ → „Pakete bauen“ → „Run workflow“

Linux-Paket: `Stadtkarten-Werkstatt-linux-x86_64.tar.gz` entpacken, `./Stadtkarten-Werkstatt` starten; optional
`./installiere-menueeintrag.sh` für einen Eintrag im Anwendungsmenü. Läuft ohne Python (gebaut auf Ubuntu 22.04).

Hinweis: Für private Repositories enthält das kostenlose GitHub-Konto 2.000 Actions-Minuten pro Monat; ein Lauf
braucht etwa 10–15 Minuten (Windows-Minuten zählen doppelt).
