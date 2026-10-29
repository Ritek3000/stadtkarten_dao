# Stadtkarten für „Die Alte Ordnung“

Erzeugt aus einer YAML-Beschreibung eine Stadtkarte (SVG, PNG, PDF).

## Oberfläche (empfohlen)

Doppelklick auf **`Stadtkarte starten.bat`**. Beim ersten Start wird die Python-Umgebung eingerichtet, danach öffnet sich die
Stadtkarten-Werkstatt im Browser:

- links alle Angaben (Gelände, Biotop, Mauer, Viertel, besondere Orte, Ausgabe), Himmelsrichtungen per Kompass
- „Karte erzeugen“ zeigt rechts die Vorschau (Mausrad zoomt, Ziehen verschiebt)
- Download als PNG, WebP (klein, gut für Foundry/Roll20), PDF, SVG oder als interaktive Karte, oder alles auf einmal in den Ordner `ausgabe`
- „Öffnen …“/„Speichern“ lädt bzw. speichert die Stadtbeschreibung als `.yaml`; oben rechts lassen sich die Beispiele laden
- Gestaltung nach dem Design System „Die Alte Ordnung“ (wie Webseite, Heldenmaschine und IniTracker): Pergament (hell)
  und Finsternis (dunkel), umschaltbar oben rechts mit Sonne/Mond

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

## Gleicher Seed, gleiche Karte

Gleiche Stadtbeschreibung und gleicher Seed ergeben auf jedem Rechner mit demselben Betriebssystem dieselbe Karte,
unabhängig vom Prozessor. Zwischen Windows und Linux kann eine Karte leicht abweichen, weil beide Systeme
Sinus, Kosinus usw. in der letzten Nachkommastelle anders runden. Wer eine Karte teilen will, gibt daher am
besten die erzeugte Datei weiter. `packaging/determinismus.py` prüft das bei jedem Paketbau: Es erzeugt Karten
mehrfach und ahmt dabei andere Prozessoren nach (andere OpenBLAS-Rechenkerne, numpy ohne AVX-512).

## Mehrere Prozessorkerne

Die Bodentexturen entstehen gleichzeitig in mehreren Threads (bei großen Karten begrenzt, damit der Speicher
nicht ausufert). Die Bilder (Vorschau, volle Ansicht, PNG mit Beschriftung, Bild der interaktiven Karte) rendern
in eigenen Prozessen nebeneinander; bei mindestens vier Kernen wird das PNG schon beim Erzeugen vorbereitet. Die
Karten bleiben dabei bitgenau gleich. Klappt das Starten der Render-Prozesse nicht, rendert das Programm wie
früher nacheinander.

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
| `stadtkarte/interaktiv.py` | interaktive Karte als einzelne HTML-Datei |
| `stadtkarte/parallel.py` | Rendern in eigenen Prozessen |
| `stadtkarte/shapes.py` | Hausgrundrisse: Quadrat, Rechteck, Raute, Fünfeck, Sechseck, L-Form, Achteck; Kreuz nur für Gotteshäuser; Mindestbreite 8 px |
| `stadtkarte/roofs.py` | detaillierte Dächer: Dachflächen mit Licht, Material je Biotop, Schornsteine, Gauben, Moos |
| `stadtkarte/noise.py` | vorberechnete Bodentexturen und Details (Körnung, Gras, Sandrippel, Schneeverwehungen, Felsrisse) |
| `stadtkarte/fonts/` | Schrift EB Garamond mit Lizenz (OFL) – in PNG/PDF verwendet und in SVG eingebettet |
| `stadtkarte/ui/` | Oberfläche: lokaler Webserver (`__main__.py`) und Seite (`index.html`) |
| `stadtkarte/ui/static/` | Schriften (IM Fell English, Spectral; OFL) und Sor-Symbol aus dem Design System „Die Alte Ordnung“ |

## Besondere Orte

| typ | Darstellung |
|---|---|
| `tempel` | Tempel mit kreuzförmigem Grundriss, gepflastertem Vorplatz und Brunnen |
| `kathedrale` (auch `dom`, `muenster`) | Kathedrale auf einem großen Block nahe der Hauptstraße: Langhaus, Querschiff und Chor mit runder Apsis, zwei Fassadentürme und ein Vierungsturm mit grünen Kupferhelmen, davor ein gepflasterter Domplatz mit Brunnen, um den Chor Bäume |
| `kaserne` | Ringbau um einen Exerzierplatz |
| `friedhof` | umzäuntes Feld mit Grabreihen, Bäumen und Kapelle; mit `lage: ausserhalb` (oder bei Platzmangel im Ort) an einer Landstraße vor dem Tor |
| `festung` / `bastion` / `burg` | Sternfestung; `lage: insel` (Brücke), `landzunge` oder `land`. Mit Stadtmauer liegt der Zugang immer innerhalb: Brückenkopf bzw. Landzunge am Ufer in der Stadt, an Land als Zitadelle in der Mauer mit Tor zur Stadt |
| `kontor`, `adelshaus` | ganzer Block als ein großes Gebäude (Adelshaus mit Garten) |
| `werft` | große Halle (bis 30 × 64 px) direkt am Ufer, quer zum Wasser; im Helling liegt ein Schiff im Bau (Kiel und Spanten), dessen Bug aufs Wasser zeigt und von nichts überlagert wird; vor dem Bug bleibt eine Ausfahrt frei (auf See gut zwei Schiffslängen offenes Wasser, im Fluss bis über die Flussmitte), in der keine Stege, Schiffe, Brücken, Inseln oder Festungen liegen (keine Stege, Schiffe, Brücken, Bäume oder Beschriftungen); im Fluss höchstens 35 % der Breite, die Fahrrinne bleibt frei; ohne `viertel` bevorzugt im Hafen, sonst am nächsten freien Stadtufer |
| `gasthaus`, `schmiede`, `laden` | einzelnes, passend gelegenes Haus |
| `wassermuehle` | Mühlhaus am Flussufer mit Wasserrad (Schaufeln, Gischt) im Fluss; ohne Fluss und in der Klamm (Gebirge) wird es eine Windmühle |
| `muehle` (auch `windmuehle`) | Windmühle vor der Stadt an einer Landstraße: runder Turm mit Kegeldach und vier Flügeln |
| `rathaus` (auch `dorfhalle`, `halle`) | lange Halle mit Turm zur Straße und gepflastertem Vorplatz mit Brunnen |
| `palast` (auch `schloss`) | drei Flügel mit Eckpavillons um einen Ehrenhof zur Straße, dahinter ein Garten mit Hecken, Wegkreuz, Brunnen und Baumalleen, alles ummauert; braucht einen großen Block |
| `bauernhof` (auch `hof`, `bauernhaus`) | vor der Stadt an einer Landstraße: Wohnhaus und großer Stall im Winkel, umzäunter Hofplatz mit Heuhaufen und Obstbäumen |

### Mehrere gleiche Orte

Mit `anzahl` entstehen mehrere Orte derselben Art. Sie werden auf der Karte fortlaufend mit Kürzeln markiert,
in der Legende steht die ganze Reihe in einer Zeile (`S1–S5  Schenke`). Das `kuerzel` gibt den Buchstaben vor,
ohne Kürzel nimmt die Werkstatt den ersten Buchstaben des Namens, bei Schmieden `SM`. Mehrere Einträge mit demselben Buchstaben
zählen weiter, so lassen sich die Orte auf Viertel verteilen; einzeln vergebene Kürzel (hier `S1`) werden
übersprungen:

```yaml
orte:
  - name: Schrein der Alten
    kuerzel: S1
    typ: tempel
  - name: Schenke
    kuerzel: S
    typ: gasthaus
    anzahl: 5             # S2 bis S6
    viertel: Handwerkerviertel
  - name: Schenke
    kuerzel: S
    typ: gasthaus
    anzahl: 3             # S7 bis S9
    viertel: Bauernviertel
```

Höchstens 50 je Eintrag. In der Werkstatt steht das Feld „Anzahl“ neben dem Kürzel.

## Landstraßen

Von jedem Tor führt eine Landstraße aus der Stadt, und keine endet im Leeren: Läuft sie auf Küste, Felswand,
Plateaukante oder zurück auf die Stadtmauer zu, weicht sie aus und führt weiter bis zum Kartenrand. Kommt sie nicht
weiter (Bucht, Felsnische), mündet sie in die nächste Landstraße, läuft außen an der Mauer entlang zum nächsten Tor,
endet an der Küste an einer Anlegestelle mit Steg oder, wenn nichts davon geht, an einem kleinen Weiler.

## Armenviertel

Viertel mit `typ: armen` (Oberfläche: „Armenviertel“) werden als Elendsviertel gezeichnet: winzige, leicht schief
stehende Hütten dicht an dicht, auch in den Hinterhöfen, enge ungepflasterte Gassen mit Schlamm und Pfützen,
geflickte Bretterdächer in trüben Farben mit viel Moos, kaum Schornsteine und keine Gauben. Nachts brennt dort
nur selten Licht. Im Sumpf und im Nordland behalten die Hütten Reet- bzw. Schneedächer, in der Wüste Flachdächer.

Armenviertel liegen immer im äußeren Ring der Stadt, nie im Kern (in Großstädten nie in der Altstadt). Mit
`ausserhalb: true` (Oberfläche: Haken „Vor der Stadtmauer“) liegt das Viertel vor der Mauer: die Hütten verteilen
sich in mehreren Siedlungen rund um die Stadt, mit etwas Abstand zur Mauer, nie auf Landstraßen oder im Wasser.

```yaml
viertel:
  - name: Elendsgasse
    typ: armen
    ausserhalb: true    # optional: vor der Stadtmauer, rund um die Stadt
```

## Bebauung

`bebauung` (Werkstatt: „Bebauung“ unter „Allgemein“) verteilt dieselben Einwohner auf mehr Fläche:

| bebauung | Wirkung |
|---|---|
| `dicht` (Standard) | wie bisher |
| `locker` | rund 40 % mehr Stadtfläche: größere Grundstücke mit Abstand zwischen den Häusern, etwas breitere Gassen, mehr Gärten und Bäume |
| `weitlaeufig` | fast die doppelte Fläche, noch mehr Gärten und Grün zwischen den Häusern |

Die Zahl der Häuser bleibt ungefähr gleich (der Hafen wächst mit der Stadt etwas mit). Eine aufgelockerte Stadt
füllt höchstens 90 % der Kartenbreite; stößt sie an den Kartenrand oder an die Küste, wird sie nur so weit
aufgelockert, wie sie tatsächlich an Fläche gewinnt. Bei Großstädten liegen `locker` und `weitlaeufig` deshalb
näher beieinander.

## Stadtform

Der Umriss der Stadt (`stadtform`, in der Werkstatt unter „Allgemein“):

| stadtform | Umriss |
|---|---|
| `zufall` (Standard) | eine der folgenden Formen, fest an den Seed gebunden |
| `rund` | der bisherige rundliche Umriss |
| `oval` | langgestreckt, an der Küste entlang oder dem Fluss folgend |
| `unregelmaessig` | ausgebeult, mit Ein- und Ausbuchtungen |
| `vieleck` | wenige lange, gerade Mauerseiten wie bei einer planmäßig angelegten Stadt |
| `gewachsen` | runder Kern mit ein bis zwei eingemeindeten Ausbuchtungen |

Alle Formen haben etwa dieselbe Fläche, die Einwohnerzahl bestimmt weiter die Größe. Ältere Stadtbeschreibungen
ohne `stadtform` bekommen jetzt je nach Seed eine andere Form; mit `stadtform: rund` sehen sie wieder aus wie früher.

## Großstädte (20.000 bis 250.000 Einwohner)

Ab 20.000 Einwohnern wird die Stadt anders gezeichnet, damit sie auf die Karte passt und lesbar bleibt
(Beispiel: [hauptstadt.yaml](beispiele/hauptstadt.yaml), 180.000 Einwohner):

- **Häuserblöcke statt Einzelhäuser:** geschlossene Häuserzeilen um Innenhöfe; jedes Haus ist eine eigene Dachfläche
  mit eigener Farbe, dazwischen Brandmauern, rundum der First. Jedes Haus liegt an einer Gasse.
- **Altstadt:** die alte Mauer mit Türmen und Toren steht noch mitten in der Stadt, davor eine Ringstraße und an jedem
  alten Tor ein kleiner Torplatz.
- **Mehr Hauptachsen:** zusätzlich zu den Torstraßen laufen breite Straßen vom Marktplatz bis an die äußere Mauer.
- **Vorstädte:** vor den Toren wachsen Häuserblöcke an den Landstraßen entlang, am Tor dicht, nach außen lichter.
  Mit `mauer: vorstaedte: false` (Oberfläche: Haken „Vorstädte“) entfallen sie, ebenso die einzelnen Häuser an den
  Landstraßen vor jeder Stadt; Höfe, Mühlen und ein Armenviertel „vor der Stadtmauer“ bleiben.
- **Große Bauten** (Dom, Palast, Rathaus, Kaserne, Friedhof, Tempel) bekommen mehrere zusammengelegte Blöcke;
  Gasthäuser, Läden und Schmieden sind ein Haus in einer Häuserzeile (in Ortsfarbe, zur Hauptstraße hin).
- Je mehr Einwohner, desto kleiner die Blöcke und schmaler die Gassen; die Stadt füllt bis zu zwei Drittel der Karte.
- Für den Druck lohnt sich `bildgroesse: 3000` oder `4000`. Unter 20.000 Einwohnern bleibt alles wie bisher.

Im Nachtmodus leuchten Fenster einzelner Häuser der Häuserzeilen.

## Stadtbild

- jedes Haus grenzt an eine Straße oder einen Platz (sonst wird es verschoben oder entfällt); Ausnahme sind die
  Hütten im Armenviertel, die auch in den Hinterhöfen stehen
- jeder Platz hat einen Laufbrunnen, große Plätze zusätzlich einen Wochenmarkt; an breiten Straßenstellen stehen Ziehbrunnen
- größere leere Flächen (Höfe, freie Grundstücke) bekommen einzelne Bäume

## Beschriftung verschieben

Liegt eine Beschriftung ungünstig, in der Werkstatt auf „✥ Beschriftung verschieben“ klicken und sie mit der Maus an
die gewünschte Stelle ziehen. Das geht für Viertel, Orte, Festungen, den Stadtnamen und die Legende. Ein Doppelklick
setzt eine Beschriftung zurück, „Zurücksetzen“ alle. Die Downloads (PNG, WebP, PDF, SVG, interaktiv) übernehmen die
neue Lage sofort, ohne dass die Karte neu erzeugt werden muss.

Die Verschiebungen stehen in der Stadtbeschreibung unter `beschriftung` (in Prozent der Kartenbreite, passt daher bei
jeder Bildgröße) und bleiben beim erneuten Erzeugen und beim Speichern der `.yaml` erhalten:

```yaml
beschriftung:
  viertel:Hafen: [2.5, -1.0]   # 2,5 % nach rechts, 1 % nach oben
  orte:H3: [0.8, 0.4]
  titel: [-40, 0]
  legende: [0, -5]
```

Ändert sich der Seed oder die Stadt stark, kann eine verschobene Beschriftung an einer unpassenden Stelle landen, dann
einfach zurücksetzen.

## Interaktive Karte

Der Knopf „Interaktiv“ (Kommandozeile: `formate: [html]`) erzeugt eine einzelne `.html`-Datei, die in jedem Browser ohne
Internet und ohne weitere Dateien läuft und sich z.B. per Mail weitergeben lässt:

- Mausrad bzw. zwei Finger zoomen, Ziehen verschiebt, „Ganz“ zeigt die ganze Karte
- Beschriftung ein-/ausblenden: alles auf einmal (auch mit der Taste B) oder einzeln Stadtname, Viertel,
  Orte und Festungen, Legende

Die Karte ohne Beschriftung ist als Bild eingebettet, die Beschriftung liegt als Vektorebene darüber und bleibt beim
Vergrößern scharf. Auch in der SVG-Datei stehen die Beschriftungen in eigenen Gruppen (`b-viertel`, `b-orte`, `b-titel`,
`b-legende`) und lassen sich z.B. in Inkscape ausblenden.

## Web-Paket

Für die eigene Webseite: Der Knopf „Web-Paket“ lädt eine ZIP-Datei herunter, die Kommandozeile schreibt mit
`formate: [web]` den Ordner `ausgabe/<kennung>_web/`. Darin liegen:

| Datei | Inhalt |
|---|---|
| `karte.webp` | Karte ohne Beschriftung und ohne Raster, genau so groß wie die Karte (Bildgröße × Bildgröße) |
| `beschriftung.svg` | die Beschriftung (Stadtname, Viertel, Orte, Legende; `viewBox` wie das Bild, Verschiebungen schon angewendet). Die Schrift ist nicht eingebettet: die Webseite muss EB Garamond (`stadtkarte/fonts/`) unter dem Namen `EB Garamond` bereitstellen |
| `orte.json` | Orte und Viertel mit Name, Kürzel, Typ, Viertel und Lage im Bild (Pixel, Ursprung oben links; bei Orten die Mitte des Gebäudes), dazu `key` = `data-key` der Beschriftung in `beschriftung.svg`. `nicht_platziert` nennt Orte, für die kein Platz war |
| `stadt.yaml` | die Stadtbeschreibung mit Seed, Kennung und Beschriftungs-Verschiebungen, lässt sich wieder in der Werkstatt öffnen |

Die **Kennung** ist der feste Name der Stadt auf der Webseite. Steht in der Stadtbeschreibung `kennung: rabenfurt`
(nur Kleinbuchstaben a-z, Ziffern, `-` und `_`), wird sie verwendet, sonst wird sie aus dem Namen gebildet. Sie wird in
`stadt.yaml` festgeschrieben, damit die Stadt auch nach einer Umbenennung dieselbe bleibt.

## Ausschnitt

`ausgabe: ausschnitt:` (Oberfläche: „Ausschnitt“ unter Ausgabe) legt fest, wie viel der Karte die Stadt einnimmt:

| Wert | Wirkung |
|---|---|
| `weit` (Standard) | wie bisher: viel Umland mit Feldern, Wald und Landstraßen |
| `normal` | näher heran, die Stadt nimmt rund 60 % der Kartenbreite ein |
| `nah` | die Stadt füllt die Karte fast (rund 80 %), nur ein schmaler Rand Umland |
| `fuellend` | der Ausschnitt wird so gewählt, dass Stadt, Vorstädte, Hafen mit Schiffen, Festung und Orte vor der Stadt (Windmühle, Bauernhof, Friedhof) gerade hineinpassen |

Näher heißt: Häuser, Straßen und Dächer werden größer und detailreicher, Schrift, Legende und Titel bleiben gleich
groß. Die Legende wandert dabei in die Ecke, in der am wenigsten Stadt liegt. Bei `normal` und `nah` können Orte vor
der Stadt oder eine Inselfestung aus dem Bild fallen; die Werkstatt nennt sie dann (`fuellend` zeigt alles).
Großstädte füllen schon von sich aus zwei Drittel der Karte, bei ihnen ändert sich wenig. Mit demselben Seed ist es
dieselbe Stadt, im Detail (Lage einzelner Häuser, Stege, Schiffe) kann sie je nach Ausschnitt leicht abweichen.

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
| `hochplateau` (auch `plateau`, `hochebene`) | zwei Geländestufen, getrennt von einer gut sichtbaren Felskante (Felswand mit Böschungsschraffur, heller Oberkante und Schatten am Fuß) auf der `kueste`-Seite; die Stadt liegt `plateau: oben` (auf dem Plateau, darunter das Tiefland im Dunst) oder `plateau: unten` (am Fuß, darüber das sonnige Plateau), und zwar `kante: direkt` (an der Kante, die Felswand ersetzt dort die Mauer) oder `kante: abstand` (Mauer ringsum). Ein Fluss stürzt als Wasserfall über die Kante; auf der anderen Stufe liegen Felder, ein Wäldchen und einzelne Bäume, eine Festung steht dort auf einem Felssporn; wo ihr Weg die Felswand kreuzt, bringt ein Aufzug (Holzschacht mit Fahrkorb, oben das Windenhaus, unten eine Plattform) die Leute hinauf und hinunter; der Aufzug hängt immer am Straßennetz (in der Stadt an der nächsten Gasse, sonst an der nächsten Landstraße bzw. außen an der Mauer entlang zum nächsten Tor). Hafen/Fischer werden zu Markt/Handwerk, eine Werft liegt am Fluss |

Beispiele: [sumpfdorf.yaml](beispiele/sumpfdorf.yaml), [nordhafen.yaml](beispiele/nordhafen.yaml), [oasenstadt.yaml](beispiele/oasenstadt.yaml), [zwergenstadt.yaml](beispiele/zwergenstadt.yaml), [plateaustadt.yaml](beispiele/plateaustadt.yaml). Die Stadtgröße richtet sich nach `einwohner`, kleine Werte ergeben Dörfer.

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
