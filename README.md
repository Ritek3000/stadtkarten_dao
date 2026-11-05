# Stadtkarten für „Die Alte Ordnung“

Erzeugt aus einer YAML-Beschreibung eine Stadtkarte (SVG, PNG, PDF).

## Oberfläche (empfohlen)

Doppelklick auf **`Stadtkarte starten.bat`**. Beim ersten Start wird die Python-Umgebung eingerichtet, danach öffnet sich die
Stadtkarten-Werkstatt im Browser:

- die **Startseite** bietet vier Wege: **Neue Stadtkarte**, **Zufällige Stadtkarte**, **Stadtkarte öffnen** und **Beispiel laden**
- **Neue Stadtkarte** führt Schritt für Schritt durch die Angaben, jede auf einer eigenen Seite: Allgemein, Gelände,
  Befestigung, Viertel, Besondere Orte und Ausgabe (Himmelsrichtungen per Kompass). Oben zeigt eine Schrittleiste, wo man ist,
  und springt auf Klick zu jeder Seite. Auf der letzten Seite steht „Karte erzeugen“ (bei der eigenen Stadtform „Gelände erzeugen“).
  Nur eine neue Karte nutzt den Assistenten
- **Zufällige Stadtkarte** würfelt alle Angaben (auch Name, Stil, Ausschnitt und Staub; meist Pergament oder Standard, sonst einer der übrigen Stile; nur stimmige Kombinationen,
  etwa Hafen nur mit Wasser) und zeichnet die Karte sofort. Die eigene Stadtform wird nicht gewürfelt, sie braucht das Zeichnen
- **Stadtkarte öffnen** lädt eine gespeicherte Stadtbeschreibung (`.yaml`) und zeichnet die Karte sofort; mit „Als .yaml speichern“
  in der Kartenansicht entsteht sie. Gleicher Seed und gleiche Angaben ergeben dieselbe Karte. Fertige Bilder (PNG, SVG, PDF) lassen
  sich nicht öffnen, sie enthalten die Angaben nicht; im Web-Paket liegt aber eine `stadt.yaml`
- **Beispiel laden** zeichnet eine der mitgelieferten Städte
- sobald eine Karte erzeugt ist (neu, gewürfelt, geöffnet oder als Beispiel), steht links die Einstellungsleiste mit allen
  Abschnitten untereinander und rechts die Karte (Mausrad zoomt, Ziehen verschiebt). Angaben ändern und „Karte erzeugen“
  zeichnet sie neu; „Startseite“ oben rechts beendet die Karte
- die Programmversion steht oben neben dem Titel
- **Tag und Nacht:** Zu jeder Karte entsteht auch die Nachtkarte (siehe [Nachtmodus](#nachtmodus)). Die Tagkarte erscheint zuerst,
  die Nachtkarte wird danach im Hintergrund gezeichnet; sobald sie fertig ist, wird der Schalter „Tag | Nacht“ oben in der
  Kartenansicht aktiv
- Download als PNG, WebP (klein, gut für Foundry/Roll20), PDF (das Kartenbild als Raster, keine Vektoren), SVG oder als interaktive Karte, oder alles auf einmal in den Ordner `ausgabe`;
  es gilt immer die Version, die gerade angezeigt wird (Nachtkarten tragen den Zusatz `_nacht`)
- Gestaltung nach dem Design System „Die Alte Ordnung“ (wie Webseite, Heldenmaschine und IniTracker): Pergament (hell)
  und Finsternis (dunkel), umschaltbar oben rechts mit Sonne/Mond

Alternativ: `.venv\Scripts\python -m stadtkarte.ui` (Optionen: `--port 8765`, `--kein-browser`).

**Linux / macOS:** `./stadtkarte-starten.sh` im Projektordner ausführen (benötigt Python 3.10 oder neuer; unter
Debian/Ubuntu zusätzlich das Paket `python3-venv`). Beim ersten Start wird die Umgebung eingerichtet, danach öffnet sich
die Werkstatt im Browser. Die Karten nutzen die mitgelieferte freie Schrift EB Garamond (`stadtkarte/fonts`, SIL Open Font
License) und sehen daher unter Windows und Linux gleich aus.

## Einrichtung

Die Startskripte richten die Python-Umgebung (`.venv`) beim ersten Start selbst ein und halten sie aktuell: Ändert sich
`requirements.txt` (etwa nach einem Update des Programms), werden die Pakete beim nächsten Start nachinstalliert. Eine
abgebrochene Einrichtung (z.B. ohne Netz) wird beim nächsten Start wiederholt; läuft die vorhandene Umgebung noch, startet das
Programm ohne Netz damit weiter. Die Arbeit macht `einrichten.py`, es lässt sich auch allein aufrufen (`python einrichten.py`).
Von Hand geht es so:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

`requirements.txt` ist bewusst locker, damit die Werkstatt auf jeder Python-Version ab 3.10 läuft (getestet mit 3.10 bis 3.13).
Tests und Paketbau nutzen die exakten Versionen aus `requirements-lock.txt` (Python 3.12 oder neuer).

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

Auch die Bibliotheksversionen spielen hinein. Eine andere Shapely-/GEOS-Version rechnet einzelne Eckpunkte anders: Die Karte
hat dieselben Häuser, Bäume, Straßen und Hinweise, aber einzelne Linien haben ein paar Punkte mehr oder weniger, die Datei ist
dann nicht byte-gleich. Eine andere NumPy- oder Pillow-Version ändert nur einzelne Bytes der eingebetteten Texturbilder.
`requirements-lock.txt` legt die Versionen fest, mit denen Tests und Pakete entstehen. Aktualisieren: neue Versionen in einer
frischen Umgebung installieren, Tests und `packaging/determinismus.py` laufen lassen, bei gewollt anderen Karten die
Vergleichstests neu schreiben (siehe Tests), dann die Versionen in der Datei eintragen.

## Mehrere Prozessorkerne

Die Bodentexturen entstehen gleichzeitig in mehreren Threads (bei großen Karten begrenzt, damit der Speicher
nicht ausufert). Die Bilder (Vorschau, volle Ansicht, PNG mit Beschriftung, Bild der interaktiven Karte) rendern
in eigenen Prozessen nebeneinander; bei mindestens vier Kernen wird das PNG schon beim Erzeugen vorbereitet. Die
Karten bleiben dabei bitgenau gleich. Klappt das Starten der Render-Prozesse nicht, rendert das Programm wie
früher nacheinander.

## Häuser einpassen ohne GEOS

Shapely/GEOS ist für beliebige Formen gebaut und stellt bei jeder Verschneidung einen vollständigen Schnittgraphen auf.
Beim Einpassen der Häuser vergleicht der Generator aber tausende Male nur ein Rechteck oder eine einfache Hausform mit
einem kleinen Grundstück. Diese Stellen rechnen ohne GEOS, in reinem Python (auf jedem Prozessor gleich):

- `geo.fit_rect` (größtes Rechteck im Grundstück) rechnet im Achsensystem des Grundstücks, in dem das Rechteck
  achsenparallel liegt: Abschneiden an vier Geraden (Sutherland-Hodgman) und die Gaußsche Flächenformel
  (`geo.local_rings`, `geo.area_in_box`). Etwa viermal so schnell wie zuvor.
- `shapes._fit` (Sonderformen wie Fünfeck, Achteck, L-Form): Bei einem konvexen Grundstück steht der größte Maßstab, mit
  dem die Form hineinpasst, direkt fest (`shapes._largest_scale`); nur bei nicht konvexen Grundstücken prüft weiter GEOS.
- `geo.hip_planes` (Walmdach für Grundrisse, die keine Rechtecke sind): Bei konvexen Grundrissen ist jede Dachfläche ein
  Schnitt von Halbebenen (exakt, mit durchgehenden Graten); Grundrisse mit einspringenden Ecken bekommen weiter die
  Voronoi-Zerlegung. Generator und Zeichnen fragen dasselbe Haus ab, das Ergebnis wird gemerkt.

Der Generator braucht für die sieben Beispiele 19 statt 26 s (Hafenstadt 2,7 statt 4,1 s, Oasenstadt 1,1 statt 2,5 s;
Großstädte gewinnen wenig, ihre Häuserzeilen entstehen anders). Im Browser unter Pyodide sind es für fünf Beispiele
38 statt 49 s. Die Häuser sind fast dieselben wie zuvor: Der Toleranzrand von 0,05 bzw. 0,15 px hat jetzt Gehrung statt
runder Ecken, dadurch liegen einzelne Häuser um Bruchteile eines Pixels anders, und in einzelnen Karten entsteht ein Haus
mehr oder weniger (Vergleichstests zu Version 1.37.2 neu geschrieben). Das Zeichnen bleibt etwa gleich schnell; dort
kosten die Rauschtexturen (numpy) die meiste Zeit.

## Aufbau

| Datei | Aufgabe |
|---|---|
| `einrichten.py` | richtet die Python-Umgebung (`.venv`) ein und hält sie aktuell (Aufruf der Startskripte) |
| `stadtkarte/config.py` | YAML einlesen und prüfen, Standardwerte (`DEFAULTS`, `OPTIONAL`), Himmelsrichtungen |
| `stadtkarte/generator.py` | setzt Gelände, Stadt und Umland zum Kartenmodell zusammen (Ausschnitt, Festung, Leuchtturm, Mühlen) |
| `stadtkarte/geo.py` | Geometrie-Hilfen (Flächen, Linien, Rechtecke, Achsen), Flächenrechnung ohne GEOS für die Häuser, Walmdächer, 1D-Rauschen |
| `stadtkarte/simplex.py` | Simplex-Rauschen, bitgenau auf jedem Prozessor |
| `stadtkarte/bilder.py` | Bilder als WebP: Data-URIs für die Texturen, Bytes für Downloads |
| `stadtkarte/terrain.py` | Küste, Inseln, Fluss |
| `stadtkarte/city.py` | Stadtumriss, Mauer, Tore, Straßen, Viertel, Gebäude, besondere Orte, Hafen |
| `stadtkarte/fortress.py` | Festung/Bastion auf Insel, Landzunge oder an Land |
| `stadtkarte/surroundings.py` | Felder, Wald, Bäume, Vorstadthäuser, Brücken |
| `stadtkarte/styles.py` | Viertel-Typen, Farben, Schrift |
| `stadtkarte/leuchtturm.py` | Leuchtturm der Küstenstadt (Insel oder Hafenspitze) |
| `stadtkarte/gebirge.py`, `stadtkarte/schlucht.py` | Gebirge mit Höhenrelief und die Klamm als Bild über dem Fels bzw. dem Fluss |
| `stadtkarte/wasser.py` | Wasser mit Tiefe, Brandung und Flussufern als Bild |
| `stadtkarte/umgebung.py`, `stadtkarte/papier.py`, `stadtkarte/staub.py` | Bodentönung nach Umgebung, Papierstruktur des Pergament-Stils, Staub |
| `stadtkarte/stile.py` | weitere Zeichenstile (Tusche, Aquarell, Sepia-Stich …): Filter, Papier- und Randtexturen, Schriftfarben |
| `stadtkarte/webpaket.py` | Web-Paket: Kartenbild, Beschriftung, Ortsliste und Stadtbeschreibung |
| `stadtkarte/render.py` | Zeichnen als SVG, Export PNG/PDF; `render_svg` setzt die Karte aus Ebenen zusammen (`water_svg`, `land_svg`, `streets_svg` … `labels_svg`), von unten nach oben |
| `stadtkarte/interaktiv.py` | interaktive Karte als einzelne HTML-Datei |
| `stadtkarte/parallel.py` | Rendern in eigenen Prozessen |
| `stadtkarte/blender_export.py` | Karte als reine Geometrie (JSON) für Blender schreiben |
| `blender/stadtkarte_blender.py` | Blender-Skript: 2D-Kurven oder extrudierte 3D-Stadt aus dieser JSON-Datei |
| `stadtkarte/shapes.py` | Hausgrundrisse: Quadrat, Rechteck, Raute, Fünfeck, Sechseck, L-Form, Achteck; Kreuz nur für Gotteshäuser; Mindestbreite 8 px |
| `stadtkarte/roofs.py` | detaillierte Dächer: Dachflächen mit Licht, Material je Biotop, Schornsteine, Gauben, Moos |
| `stadtkarte/noise.py` | vorberechnete Bodentexturen und Details (Körnung, Gras, Sandrippel, Schneeverwehungen, Felsrisse) |
| `stadtkarte/fonts/` | Schrift EB Garamond mit Lizenz (OFL) – in PNG/PDF verwendet und in SVG eingebettet |
| `stadtkarte/ui/` | Oberfläche: lokaler Webserver (`__main__.py`) und Seite (`index.html`) |
| `stadtkarte/ui/static/` | Schriften (IM Fell English, Spectral; OFL) und Sor-Symbol aus dem Design System „Die Alte Ordnung“ |
| `tests/` | Unit-Tests (`python -m unittest`) |
| `requirements.txt`, `requirements-lock.txt`, `requirements-build.txt` | Pakete: locker für Anwender, exakt für Tests und Paketbau, plus PyInstaller |

## Besondere Orte

| typ | Darstellung |
|---|---|
| `tempel` | Tempel mit kreuzförmigem Grundriss, gepflastertem Vorplatz und Brunnen |
| `kathedrale` (auch `dom`, `muenster`) | Kathedrale auf einem großen Block nahe der Hauptstraße: Langhaus, Querschiff und Chor mit runder Apsis, zwei Fassadentürme und ein Vierungsturm mit grünen Kupferhelmen, davor ein gepflasterter Domplatz mit Brunnen, um den Chor Bäume |
| `kaserne` | Ringbau um einen Exerzierplatz |
| `friedhof` | umzäuntes Feld mit Grabreihen, Bäumen und Kapelle; mit `lage: ausserhalb` (oder bei Platzmangel im Ort) an einer Landstraße vor dem Tor |
| `festung` / `bastion` / `burg` | Sternfestung; `lage: insel` (Brücke), `landzunge` oder `land`. Mit Stadtmauer liegt der Zugang immer innerhalb: Brückenkopf bzw. Landzunge am Ufer in der Stadt, an Land als Zitadelle in der Mauer mit Tor zur Stadt |
| `kontor`, `adelshaus` | ganzer Block als ein großes Gebäude (Adelshaus mit Garten) |
| `werft` | große Halle (bis 30 × 64 px) direkt am Ufer, quer zum Wasser; im Helling liegt ein Schiff im Bau (Kiel und Spanten), dessen Bug aufs Wasser zeigt und von nichts überlagert wird; vor dem Bug bleibt eine Ausfahrt frei (auf See gut zwei Schiffslängen offenes Wasser, im Fluss bis über die Flussmitte), in der keine Stege, Schiffe, Brücken, Inseln, Festungen, Bäume oder Beschriftungen liegen; im Fluss höchstens 35 % der Breite, die Fahrrinne bleibt frei; ohne `viertel` bevorzugt im Hafen, sonst am nächsten freien Stadtufer |
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
Plateaukante oder zurück auf die Stadtmauer zu, weicht sie aus und führt weiter bis zum Kartenrand. Sie biegt dabei
schon etwa 200 px vor der Küste in einer weiten Kurve ab (und hält 25 px Abstand), statt am Ufer abzuknicken; wo es
nicht anders geht, werden verbleibende scharfe Ecken nachträglich abgerundet. Kommt sie nicht
weiter (Bucht, Felsnische), mündet sie in die nächste Landstraße, läuft außen an der Mauer entlang zum nächsten Tor,
endet an der Küste an einer Anlegestelle mit Steg oder, wenn nichts davon geht, an einem kleinen Weiler.

## Brücken

Ein Fluss, der die Stadt teilt, bekommt eine Brücke in der Stadtmitte. Mit `gelaende: bruecken:` (Werkstatt: „Brücken“ unter
Gelände, neben dem Fluss) sind es mehr, **höchstens 5** (Standard: 1; mehr als 5 meldet die Prüfung als Fehler):

```yaml
gelaende:
  fluss: true
  bruecken: 3
```

- Die erste Brücke liegt wie bisher in der Stadtmitte, die übrigen verteilen sich gleichmäßig am Fluss entlang durch die
  Stadt, mindestens 90 px (bei Bildgröße 2000) voneinander entfernt. Sie sind etwas schmaler als die Hauptbrücke.
- Jede endet an beiden Ufern in einem kleinen Platz, der mit einer Gasse ans Straßennetz anschließt; Häuser, Schiffe, Stege
  und Wasserräder weichen ihr.
- Hat die Stadt ein Hafenviertel am Meer, liegen die weiteren Brücken nur flussaufwärts vom Hafen: Der Hafen bleibt
  flussabwärts der Brücken, damit die Schiffe zu den Kais kommen.
- Wo am Fluss kein Platz ist (kleine Stadt, kurzes Flussstück in der Stadt), entstehen weniger Brücken; die Ausgabe nennt das
  mit einer „Hinweis“-Zeile. Teilt der Fluss die Stadt gar nicht, gibt es keine Brücke (auch dazu ein Hinweis, wenn mehr als
  eine gewünscht war). Ohne Fluss (`fluss: false`) hat die Angabe keine Wirkung.
- Die Brücke zu einer Festung auf einer Insel gehört nicht dazu, sie zählt nicht mit. In der Klamm (Gebirge) sind es
  Steinbrücken über die Schlucht.
- Der Blender-Export (`Bridges`) enthält alle Brücken.

## Staub

Staub ist in der Welt allgegenwärtig, an manchen Stellen dichter; in hoher Konzentration wird er zur Finsternis.
`gelaende: staub:` legt Staubflächen in ein 5×5-Raster über der Karte (Felder `a1` bis `e5`: Spalte a–e von
links, Zeile 1–5 von oben), über die Stadt (`mitte`) oder als Schleier über die ganze Karte (`ueberall`); auch
Himmelsrichtungen um die Stadt (`nordwest` …) gehen. Jede Fläche hat eine Stärke:

| Stärke | Wirkung |
|---|---|
| `wenig` | leichter, dunkler Schleier über allem |
| `mittel` | alles darunter nur noch schemenhaft |
| `finsternis` | im Kern schwarz, nichts mehr erkennbar; am Rand fransen Schwaden aus |

```yaml
gelaende:
  staub: {a3: finsternis, a4: finsternis, b4: mittel, d1: wenig, mitte: wenig, ueberall: wenig}
```

In der Werkstatt unter Gelände: das Raster „Staub“ mit 25 Feldern (oben links = A1; jeder Klick schaltet
weiter: leer, wenig, mittel, Finsternis), „Stadt“ für Staub über der Stadt und „Überall“ für einen Schleier über
der ganzen Karte. Der Staub liegt über
allem, auch über Laternen und Leuchtfeuer, aber unter der Beschriftung.

## Hafen

Ein Viertel mit `typ: hafen` hat die Option `groesse: klein | mittel | gross` (Werkstatt: „Größe“ beim
Hafenviertel). Sie bestimmt, wie breit der gepflasterte Kai-Streifen am Ufer wird; `gross` (Standard) ist der
bisherige Hafen. In einer sehr kleinen Stadt, in der der Kai das ganze Land einnähme (etwa bei einem sehr
breiten Fluss), wird er schmaler, damit für die übrigen Viertel Land bleibt; die Ausgabe nennt das mit einer
„Hinweis“-Zeile. Stege und Schiffe gibt es nur am Kai und im Fluss; ein Schiff legt nur dort an, wo es frei aufs
offene Wasser ablegen kann. Jede Küstenstadt hat einen großen Leuchtturm, bevorzugt auf einer vorgelagerten Insel,
sonst an der Spitze des Hafens; bei Nacht strahlt sein Feuer weit übers Wasser.

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
| `eigene` | die Stadtmauer selbst zeichnen (siehe unten) |

### Eigene Stadtform: Mauer selbst zeichnen

In der Werkstatt unter Allgemein „Stadtform: Eigene“ wählen, die weiteren Seiten ausfüllen, dann:

1. **Gelände erzeugen** (Button auf der letzten Seite des Assistenten) – die Karte zeigt nur Land, Küste, Inseln, Fluss und Tümpel, noch ohne Stadt.
2. **Mauer zeichnen** (links in der Einstellungsleiste unter „Allgemein“) – Linksklick setzt einen Turm, die Taste **T** ein Tor an der Mausposition, dazwischen
   entsteht die Mauer; die Rücktaste nimmt den letzten Punkt zurück, Rechtsklick (oder Esc) beendet das Zeichnen
   und schließt den Ring. „Mauer löschen“ fängt von vorn an.
3. **Stadt erzeugen** – innerhalb der Mauer entstehen Viertel, Straßen und Häuser, außen Landstraßen ab den Toren,
   Felder, Wald und Höfe. Türme und Tore stehen genau dort, wo sie gesetzt wurden.
4. **Mauer bearbeiten** – Türme und Tore lassen sich nachträglich ändern, ohne die Mauer neu zu zeichnen. Jeder Punkt
   ist eine Ecke der Mauer, ein Verschieben formt die Mauer also um. Punkt mit der Maus ziehen; Doppelklick auf einen
   Punkt schaltet zwischen Turm und Tor um; Doppelklick auf eine Mauerseite fügt einen Turm ein (die Taste **T** über der
   Mauer ein Tor, über einem Punkt schaltet sie um); **Entf** oder Rechtsklick löscht den Punkt unter der Maus;
   **Strg+Z** macht den letzten Schritt rückgängig (auch nach „Mauer löschen“); Esc oder Rechtsklick daneben beendet.
   Sich kreuzende Mauerseiten werden rot gezeichnet. Die Stadt ändert sich erst mit **Stadt erzeugen** (der Modus
   bleibt dabei an, man kann gleich weiter feilen). Dann entstehen Straßen, Viertel und Häuser neu nach der geänderten
   Mauer; das Gelände bleibt gleich.

Beginnt und endet die Mauer an der Küste (bzw. am Hochplateau an der Kante), ist die Stadt dort offen: Küste
und Felswand sind die Mauer, es wird kein Mauerstück übers Wasser gezogen. Der Fluss zählt nicht als Mauer.

Das Gelände bleibt dabei dasselbe. Die Bebauung richtet sich nach der gezeichneten Fläche: eine große Mauer bei
wenigen Einwohnern ergibt eine weitläufige Stadt mit Gärten, eine sehr enge Mauer eine dichte, kleinere Stadt (die
Werkstatt weist darauf hin). Tore im Wasser entfallen; die Mauer darf sich nicht kreuzen und braucht mindestens ein
Tor. In der YAML-Datei steht die Mauer als `mauer: punkte:` mit `[x, y, turm|tor]` in Prozent der Karte (von links
oben). Im Gebirge gibt es die eigene Form (noch) nicht; der Ausschnitt ist bei ihr immer „weit“.

Alle Formen haben etwa dieselbe Fläche, die Einwohnerzahl bestimmt weiter die Größe. Ältere Stadtbeschreibungen
ohne `stadtform` bekommen jetzt je nach Seed eine andere Form; mit `stadtform: rund` sehen sie wieder aus wie früher.

## Großstädte (20.000 bis 250.000 Einwohner)

Ab 20.000 Einwohnern wird die Stadt anders gezeichnet, damit sie auf die Karte passt und lesbar bleibt
(Beispiel: [hauptstadt.yaml](beispiele/hauptstadt.yaml), 180.000 Einwohner):

- **Häuserblöcke statt Einzelhäuser:** geschlossene Häuserzeilen um Innenhöfe; jedes Haus ist eine eigene Dachfläche
  mit eigener Farbe, dazwischen Brandmauern, rundum der First. Jedes Haus liegt an einer Gasse.
- **Altstadt:** die alte Mauer mit Türmen und Toren steht noch mitten in der Stadt, davor eine Ringstraße und an jedem
  alten Tor ein kleiner Torplatz. Reicht der Hafen von der Altstadt bis in den äußeren Ring, ist die alte Mauer dort
  geschleift (kurze Wege zwischen Kai und Stadt).
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
- bedeckt Wasser den ganzen Stadtumriss (kleine Stadt an einem sehr breiten Fluss oder an der Küste), rückt die Stadt so
  wenig wie möglich ans Ufer, bis gut zwei Drittel ihrer Fläche auf Land liegen; die Ausgabe nennt das mit einer
  „Hinweis“-Zeile. Eine selbst gezeichnete Mauer bleibt, wo sie ist; liegt sie ganz im Wasser, gibt es eine Fehlermeldung.
- Gelände und Bodentexturen beruhen auf Simplex-Rauschen: Küsten, Flussläufe, Landstraßen und Umrisse (1D), Bodenflecken und Nebel (verzerrt, fließend), Felsrisse (Nulllinien), Schneeverwehungen (in Windrichtung gestreckt) und Sandrippel; ohne Kästchen-Muster und auf jedem Prozessor bitgleich
- Boden mit Relief (sanfte Bodenwellen, Licht immer von Nordwesten der fertigen Karte) und Farbverlauf aus der Bodenfarbe des Biotops; dazu eine Tönung nach der Umgebung: am Wasser satter, fern davon trockener, an Landstraßen, Toren und entlang der Mauer ausgetreten, am Waldrand moosig, an der Küste ein Sand- bzw. Kiesstreifen (Farben je Biotop in `styles.py`: moist, dry, worn, moss, shore, relief)
- Felder als gewachsene Feldmark: je Richtung eine Flur aus Gewannen mit eigener Pflugrichtung, darin lange, schmale Ackerstreifen dicht an dicht (im Gewann meist dieselbe Frucht, einzelne Brachen), Feldwege und Hecken an den Gewanngrenzen, gedämpfte Farben
- Stege und Schiffe nur am gepflasterten Hafenkai und im Fluss, nicht an der offenen Küste; endet eine Landstraße an der Küste, bekommt sie eine Anlegestelle mit Steg
- Wasser mit Tiefe: helles Flachwasser an der Küste, nach außen dunkler, mit Sandbänken und Rinnen; feine Wellenkräusel auf tiefem Wasser, Brandung am Ufer, gestrichelte Küstenlinien; Flüsse mit hellen Ufern, an der Mündung weich ins Meer übergehend (Farben aus dem Biotop: sea_deep, sea, shallow, river)
- Plätze gehen weich in die einmündenden Gassen über; Brücken enden mit Brüstung an der Uferkante und blenden an Land in Platz, Gasse oder Landstraße aus
- keine Straße läuft ins Wasser und endet dort: Eine Straße vom Tor zum Platz, in deren Weg eine Flussbiegung (oder eine Einbuchtung der Mauer) liegt, führt an Land um die Biegung herum, statt am Ufer abgeschnitten zu werden und ins Leere zu zeigen. Eine Landstraße, die eine Flussschleife anschneidet und auf derselben Seite wieder herauskommt, bekommt dort eine Brücke; Gassen, die das Ufer nur streifen, bekommen keine

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
| `orte.json` | Orte und Viertel mit Name, Kürzel, Typ, Viertel und Lage im Bild (Pixel, Ursprung oben links; bei Orten die Mitte des Gebäudes), dazu `key` = `data-key` der Beschriftung in `beschriftung.svg`. `art` ist `ort`, `festung` oder `leuchtturm` (der Leuchtturm einer Küstenstadt entsteht von selbst). `nicht_platziert` nennt Orte, für die kein Platz war |
| `stadt.yaml` | die Stadtbeschreibung mit Seed, Kennung und Beschriftungs-Verschiebungen, lässt sich wieder in der Werkstatt öffnen |

Die **Kennung** ist der feste Name der Stadt auf der Webseite. Steht in der Stadtbeschreibung `kennung: rabenfurt`
(nur Kleinbuchstaben a-z, Ziffern, `-` und `_`), wird sie verwendet, sonst wird sie aus dem Namen gebildet. Sie wird in
`stadt.yaml` festgeschrieben, damit die Stadt auch nach einer Umbenennung dieselbe bleibt.

## Blender: 2D-Kurven oder 3D-Stadt

Aus jeder Karte lässt sich in Blender (4.x oder 5.x) entweder ein Satz sauberer 2D-Kurven für einen SVG-Export
oder eine extrudierte 3D-Stadt erzeugen. Blenders eigenes Python kennt weder shapely noch Pillow und kann den Generator
deshalb nicht selbst starten; zuerst schreibt die normale Umgebung die Geometrie als JSON, dann liest Blender sie ein:

```bash
.venv\Scripts\python -m stadtkarte.blender_export beispiele\hafenstadt.yaml -o ausgabe\stadt.json
```

In Blender im Arbeitsbereich *Scripting* `blender/stadtkarte_blender.py` öffnen, oben im Konfigurationsblock
`JSON_PATH` und `OUTPUT_MODE` einstellen und *Run Script* drücken. Ohne Oberfläche geht es auch so:

```bash
blender -b -P blender/stadtkarte_blender.py -- --json ausgabe/stadt.json --mode 3D --save stadt.blend
```

| `OUTPUT_MODE` | Ergebnis |
|---|---|
| `'2D'` | flache Poly- oder Bézierkurven auf der XY-Ebene, je Art eine Collection: `Main_Roads`, `Side_Streets`, `Country_Roads`, `Bridges`, `Plazas`, `Piers`, `Waterways`, `Building_Outlines` (je Viertel ein Objekt), `City_Walls`. Straßenobjekte tragen ihre Breite als benutzerdefinierte Eigenschaft. Die Kurven sind bereinigt: keine doppelten Punkte, kein wiederholter Schlusspunkt (geschlossene Kurven sind zyklisch), Punkte auf geraden Strecken entfallen (Abweichung höchstens `SIMPLIFY_TOLERANCE`) |
| `'3D'` | Häuser als Quader-Körper mit Boden und Dach, Straßen als Streifen mit echter Breite (Hauptstraße, Ringgasse, Landstraße, Brücke), Gassen- und Platzflächen, Wasser, Geländeplatte mit Ufern, Mauer mit Türmen und Toren; dazu einfache Materialien (`SK_*`): graue Straßen, dunkelgraue Häuser, Glas für hohe Türme |

Die Gebäudehöhe hängt vom Gebäudetyp, vom Viertel und von der Entfernung zur Stadtmitte ab (innen hoch, außen niedrig;
in der Mitte können einzelne Hochhäuser entstehen) und bekommt eine zufällige Streuung, die `RANDOM_SEED` festlegt.
Alle Höhen, Breiten, Ebenen und Farben stehen im Konfigurationsblock am Anfang des Skripts. Normalen zeigen bei den
Körpern nach außen, doppelte Punkte entfernt das Skript beim Aufbau (Häuserzeilen bleiben bewusst getrennte, geschlossene
Körper). Wer `MERGE_BUILDINGS = False` setzt, bekommt ein Objekt je Haus statt eines je Viertel. Ein erneuter Lauf ersetzt
das Ergebnis des vorigen. Nicht übernommen werden Bäume, Felder, Wald, Schiffe und Beschriftungen.

## Stil

`ausgabe: stil:` (Oberfläche: „Stil“ unter Ausgabe) bestimmt das Aussehen der fertigen Karte:

| Wert | Wirkung |
|---|---|
| `pergament` (Standard) | wie auf altem Papier: Papierstruktur mit Fasern, Körnung und Stockflecken, warmer Sepiaton, unregelmäßig gebräunter Rand, Küstenlinie wie mit der Feder gezeichnet |
| `standard` | ohne Papier: klare Farben, dunkle Vignette am Rand |
| `tusche` | Feder und Tinte auf Elfenbeinpapier: Umrisse als dunkle Tintenlinien, fast ohne Farbe, Schrift in Tinte |
| `aquarell` | weiche, leicht verlaufene Farben, Papierkörnung, zum Rand hin ausbleichend |
| `sepia` (Sepia-Stich) | einfarbig braun wie ein alter Druck, mit Papierfasern und dunklem Rand |
| `schatzkarte` | gealtertes, fleckiges Pergament in gedeckten Farben mit angebrannten Ecken |
| `abendlicht` (Goldene Stunde) | die Karte in warmem Abendlicht, Lichtschein oben rechts, dunkler Rand |
| `farbdruck` | wenige Farbflächen und Rasterpunkte wie eine alte Lithografie |
| `pastell` | helle, sanfte Farben mit klaren Umrissen, Schrift in dunklem Violett |
| `bleistift` | Graustufen mit feiner Schraffur wie eine Skizze, Schrift in Graphit |
| `stich` (Kolorierter Stich) | Tintenlinien mit blasser Handkolorierung |

Andere Schreibweisen gehen auch, etwa `Goldene Stunde`, `Sepia-Stich`, `Kupferstich` oder `Skizze`. Die Stile ab `tusche`
legen einen SVG-Filter über die gezeichnete Karte (Farben umrechnen, Umrisse aus Helligkeitskanten als Tintenlinien,
weichzeichnen) und darüber eine Papier- bzw. Randtextur (`stadtkarte/stile.py`). Beschriftung, Nachtlichter, Leuchtfeuer und
Staub liegen über dem Filter und bleiben scharf; die SVG-Datei bleibt eine Vektorkarte. Die Nachtkarte dunkelt die gestaltete
Karte ab. Der Filter kostet beim Rendern etwas Zeit (bei 1600 px je nach Stil rund 1 bis 6 Sekunden mehr als `standard`). Die Linien
rechnen in Kartenmaßen und sehen daher in jeder Bildgröße und in der halb so großen Vorschau der Werkstatt gleich aus.

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

Die Nachtkarte dunkelt die Karte bläulich ab. Es leuchten Türme, Tore, Brückenlaternen, Essen, Minen, Laternen entlang der
Hauptstraßen und an den Plätzen sowie die Fenster eines Teils der Häuser. Wie viel leuchtet, hängt von der Einwohnerzahl ab:
Dörfer haben wenige Laternen, kaum helle Fenster und kleinere Wachfeuer. Dateien bekommen den Zusatz `_nacht`.

**In der Werkstatt** entsteht die Nachtkarte immer mit (Ausgabe: „Nachtkarte mitberechnen“, standardmäßig an,
`ausgabe: nachtkarte: true`). Beide Karten zeigen dieselbe Stadt; nur die Darstellung unterscheidet sich, die Stadt selbst wird
nur einmal berechnet. Die Tagkarte kommt ohne zusätzliche Wartezeit, die Nachtkarte folgt im Hintergrund (nach wenigen Sekunden
die Vorschau, danach die volle Auflösung). Die Nachtkarte kostet etwas Rechenzeit im Hintergrund; wer sie nicht braucht, schaltet
„Nachtkarte mitberechnen“ aus. Verschobene Beschriftungen gelten für beide Karten. Fordert man eine neue Karte an, bevor die
Nachtkarte der alten fertig ist, wird sie nicht mehr gezeichnet. Downloads, „Alle Formate speichern“, interaktive Karte und
Web-Paket enthalten jeweils die Version, die gerade angezeigt wird (das Web-Paket nennt sie in `orte.json` und `stadt.yaml`).

**Kommandozeile und Stadtbeschreibung:** Dort entsteht weiter eine einzelne Karte. `ausgabe: nacht: true` (Kommandozeile:
`--nacht`) zeichnet sie als Nachtkarte. In der Werkstatt hat `nacht` keine Wirkung mehr, weil dort immer beide Karten entstehen.

## Biotope

`gelaende: biotop:` legt Landschaft und Bauweise fest.

| biotop | Wirkung |
|---|---|
| `gemaessigt` (Standard) | grünes Land, Laub- und Nadelbäume, Steinmauer, gepflasterte Plätze |
| `sumpf` (auch `moor`) | Tümpel und Wasserläufe mit Schilf und Seerosen, Pfahlhäuser über Wasser, Bohlenstege und Knüppeldämme, Holzpalisade, Reetdächer, Weiden und Totholz |
| `nordland` (auch `winter`, `schnee`) | verschneites Land, verschneite Tannen, zugefrorene Seen mit Rissen, Eisschollen vor der Küste, Schneedächer, Palisade, Findlinge |
| `steppe` | trockenes Grasland, lichte Baumgruppen und Büsche, Felsbrocken, Palisade |
| `wueste` (auch `oase`) | Sand mit Dünen, Oasen mit Palmenring, grüne Ufer an Fluss und Küste, Lehmhäuser mit Flachdach, Lehmmauer, Palmenhaine |
| `gebirge` (auch `berg`, `zwerge`) | Zwergenstadt am Fels: Felsmassiv mit Höhenrelief auf der `kueste`-Seite (lange Rücken und Täler, Schummerung mit Licht aus Nordwesten, Verschattung der Täler, Höhenfärbung, Schnee auf den Gipfeln, schwache Höhenlinien) und Steilkante, Stadt auf Terrassenstufen (bei hohen Städten eine Stufe mehr): Stützmauern mit Mauerfläche, hellem Rand und Schattenwurf auf die tiefere Stufe, die Stufen nach Höhe getönt (oben heller, unten dunkler) und Treppen an den Hauptstraßen, großes Tor in der Felswand, Klamm als Schlucht statt Fluss (steile Felswände mit Licht aus Nordwesten, Wandbreite und Wandart wechseln: Absätze, glatte Wand, Geröllhang; hier und da etwas breiter mit Schotterbänken im Grund, nie zu breit; schmaler dunkler Wildbach mit Gischt und Felsbrocken). Wo die Felsflanken ins Tal auslaufen, läuft die Klamm aus: die Wände werden niedriger, der Grund geht ins Blau des Wassers über und die Klamm wird schmaler, bis sie als kleiner Bach durchs Tal fließt. Mineneingänge mit Abraumhalden, glühende Essen, Schieferdächer, Festung auf einem Felssporn. Hafen/Fischer werden zu Markt/Handwerk |
| `hochplateau` (auch `plateau`, `hochebene`) | zwei Geländestufen, getrennt von einer gut sichtbaren Felskante (Felswand mit Böschungsschraffur, heller Oberkante und Schatten am Fuß) auf der `kueste`-Seite; die Stadt liegt `plateau: oben` (auf dem Plateau, darunter das Tiefland im Dunst) oder `plateau: unten` (am Fuß, darüber das sonnige Plateau), und zwar `kante: direkt` (an der Kante, die Felswand ersetzt dort die Mauer) oder `kante: abstand` (Mauer ringsum). Ein Fluss stürzt als Wasserfall über die Kante; auf der anderen Stufe liegen Felder, ein Wäldchen und einzelne Bäume, eine Festung steht dort auf einem Felssporn; wo ihr Weg die Felswand kreuzt, bringt ein Aufzug (Holzschacht mit Fahrkorb, oben das Windenhaus, unten eine Plattform) die Leute hinauf und hinunter; der Aufzug hängt immer am Straßennetz (in der Stadt an der nächsten Gasse, sonst an der nächsten Landstraße bzw. außen an der Mauer entlang zum nächsten Tor). Hafen/Fischer werden zu Markt/Handwerk, eine Werft liegt am Fluss |

Beispiele: [sumpfdorf.yaml](beispiele/sumpfdorf.yaml), [nordhafen.yaml](beispiele/nordhafen.yaml), [oasenstadt.yaml](beispiele/oasenstadt.yaml), [zwergenstadt.yaml](beispiele/zwergenstadt.yaml), [plateaustadt.yaml](beispiele/plateaustadt.yaml). Die Stadtgröße richtet sich nach `einwohner`, kleine Werte ergeben Dörfer.

## Tests

```bash
.venv\Scripts\python -m unittest          # Linux/macOS: .venv/bin/python -m unittest
```

Die Tests liegen in `tests/` und brauchen nur die Pakete aus `requirements.txt` (ein Test der Oberfläche führt ihre
Standardwert-Funktion mit Node aus und entfällt ohne Node). Sie prüfen die Stadtbeschreibung (fehlerhafte Angaben ergeben eine
klare Meldung statt eines Absturzes), die Einrichtung der Umgebung, die Render-Prozesse, die Sicherheitsregeln des lokalen
Webservers, die Standardwerte der Oberfläche und Karten, die früher beim Zeichnen abgestürzt sind. Ob dieselbe Karte auf jedem
Prozessor entsteht, prüft weiterhin `packaging/determinismus.py`. Auf GitHub laufen die Tests bei jeder Änderung und bei Pull
Requests (siehe unten).

**Standardwerte:** Sie stehen nur in `stadtkarte/config.py`: `DEFAULTS` für alles, was eine Beschreibung enthalten muss, und
`OPTIONAL` für Angaben, die fehlen dürfen (`bebauung: dicht`, `stil: pergament`, `ausschnitt: weit` …). Die Oberfläche bekommt
beide beim Start vom Server (`/api/options`) und wiederholt sie nicht. Fehlen in einer Datei `wald` und `felder`, gelten
deshalb in der Oberfläche wie in der Kommandozeile Wald im Westen und Felder im Osten und Süden; ein ausdrücklich leeres
`wald:` bedeutet weiterhin „kein Wald“.

**Karten-Vergleichstests:** Ein Umbau darf die Karten nicht verändern. `tests/test_karten.py` erzeugt 23 feste Karten (die
Beispiele, dazu eigene Mauer, Binnenland, die Stadtformen, Nacht, Zuschnitt, Raster, fünf Brücken u.a.) und vergleicht sie mit den
Fingerabdrücken in `tests/golden/karten.json`: Hinweise des Generators, Zahlen (Häuser, Bäume, Straßen …), das Kartenmodell
nach dem Generator, das gezeichnete SVG ohne Bilder und die Bilder einzeln. Eine Abweichung nennt die Stufe: Ändert sich schon
das Modell, liegt es am Generator; bleibt es gleich und nur das SVG ändert sich, am Zeichnen. Bibliotheken und Betriebssystem
bestimmen, wie streng verglichen wird (Einzelheiten im Kopf von `tests/golden.py`); auf GitHub mit den Versionen aus
`requirements-lock.txt` wird alles verglichen. Die Läufe dauern ein bis zwei Minuten.

```bash
python -m tests.golden                  # alle Karten vergleichen, Abweichungen mit Stufe ausgeben
python -m tests.golden hafen            # nur Karten mit "hafen" im Namen
python -m tests.golden --update         # nach einer GEWOLLTEN Änderung der Karten: Fingerabdrücke neu schreiben
```

Nach `--update` gehört die geänderte `tests/golden/karten.json` mit in den Commit; im Review zeigt sie, welche Karten sich
verändert haben. Mit `STADTKARTE_SCHNELL=1` bleiben die langsamen Tests (Karten) aus.

## Weitergeben

Im Ordner `verteilung/` liegt nach dem Bauen die Datei zum Weitergeben (unter Windows die ZIP, unter Linux das `tar.gz`).
Die Empfänger brauchen **kein Python**:

| Datei | Verwendung |
|---|---|
| `Stadtkarten-Werkstatt-portable.zip` | Entpacken und `Stadtkarten-Werkstatt.exe` starten, z.B. vom USB-Stick. |

Ein Setup mit Installation gibt es nicht mehr: Eine selbstentpackende Setup.exe, die ein PowerShell-Skript startet, hat bei
Browsern und Virenscannern Fehlalarme ausgelöst („Gefährlicher Download blockiert“). Wer eine ältere Version mit dem Setup
installiert hat, kann sie weiter über das Startmenü oder „Apps & Features“ deinstallieren.

Das Programm öffnet die Werkstatt im Browser; gespeicherte Karten landen in `Dokumente\Stadtkarten`. Zum Beenden das schwarze Fenster schließen.

Da das Programm nicht digital signiert ist, warnt Windows SmartScreen beim ersten Start („Der Computer wurde durch Windows geschützt“) – über „Weitere Informationen“ → „Trotzdem ausführen“ geht es weiter. Auch ein Browser kann den Download als unbekannt beanstanden; in Chrome unter `chrome://downloads` bei dem Eintrag „Behalten“ wählen.

**Neu bauen** (z.B. nach Änderungen am Programm):

```bash
.venv\Scripts\python -m pip install -r requirements-build.txt    # Python 3.12 oder neuer; dieselben Versionen wie auf GitHub
.venv\Scripts\python packaging\build.py
```

Die Version wird aus `stadtkarte/__init__.py` übernommen. Zum Aktualisieren den alten Ordner löschen und die neue ZIP entpacken.

### Automatisch auf GitHub bauen (Windows und Linux)

Bei jedem Hochladen von Programmänderungen auf `main` testet GitHub Actions ([.github/workflows/pakete.yml](.github/workflows/pakete.yml))
zuerst den Code (pyflakes und `python -m unittest` mit Python 3.12 und 3.13 sowie zur Warnung mit 3.10), baut dann
beide Versionen, startet sie zur Probe (Tag- und Nachtkarte) und stellt sie bereit. Bei Pull Requests laufen nur die Tests.
Die Läufe arbeiten mit Leserechten; nur der Release-Schritt darf schreiben:

- **Download:** Repository → „Actions“ → „Pakete bauen“ → letzter Lauf → unten „Artifacts“
  (`stadtkarten-werkstatt-windows`, `stadtkarten-werkstatt-linux`, je 30 Tage verfügbar)
- **Release:** Einen Versions-Tag hochladen, z.B. `git tag v1.8.0` und `git push origin v1.8.0` – dann entsteht
  zusätzlich ein GitHub-Release mit portabler ZIP und Linux-Paket
- **Von Hand:** „Actions“ → „Pakete bauen“ → „Run workflow“

Linux-Paket: `Stadtkarten-Werkstatt-linux-x86_64.tar.gz` entpacken, `./Stadtkarten-Werkstatt` starten; optional
`./installiere-menueeintrag.sh` für einen Eintrag im Anwendungsmenü. Läuft ohne Python (gebaut auf Ubuntu 22.04).

Hinweis: Für private Repositories enthält das kostenlose GitHub-Konto 2.000 Actions-Minuten pro Monat; ein Lauf
braucht etwa 10–15 Minuten (Windows-Minuten zählen doppelt).
