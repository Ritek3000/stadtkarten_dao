"""Viertel-Typen, Farben und Größen (Flächen gelten für Bildgröße 2000 px)."""
import pathlib

DISTRICT_TYPES = {
    "hafen": dict(block=7000, lot=2000, alley=16, density=0.8, perimeter=False, paved=True,
                  palette=["#7b5b3e", "#8c6a48", "#6d4f35", "#9a7752", "#5f6f78"]),
    "handwerk": dict(block=10000, lot=640, alley=6, density=0.98, inner=0.35, perimeter=True,
                     palette=["#b9a66b", "#9fae6c", "#c98a6b", "#a89c5e", "#c47264", "#8fa064", "#7f8fa0"]),
    "arbeiter": dict(block=9000, lot=540, alley=6, density=0.99, inner=0.45, perimeter=True,
                     palette=["#5d4f8f", "#4f4a7d", "#6a5a9e", "#7a5d8c", "#8b6b5a", "#56628a"]),
    "fischer": dict(block=7000, lot=520, alley=6, density=0.85, inner=0.15, perimeter=True,
                    palette=["#5f8f8c", "#6f7f6a", "#a0745c", "#7d9a8e", "#c9a46a"]),
    "bauern": dict(block=11000, lot=760, alley=7, density=0.8, inner=0.1, perimeter=True,
                   palette=["#c0675e", "#b4775a", "#a8584f", "#c98462", "#9c6a4e"]),
    "adel": dict(block=9000, lot=1400, alley=11, density=0.55, perimeter=True,
                 palette=["#6c4f9a", "#5b3f8a", "#7d5fae", "#8a6aa0"]),
    "tempel": dict(block=7000, lot=900, alley=11, density=0.7, perimeter=True,
                   palette=["#d9d2c0", "#c8bfa8", "#b8b3a3", "#a9a08a"]),
    "markt": dict(block=4500, lot=500, alley=12, density=0.85, perimeter=True,
                  palette=["#c47264", "#b9a66b", "#c98a6b", "#9fae6c"]),
    "wohn": dict(block=9500, lot=600, alley=6, density=0.97, inner=0.3, perimeter=True,
                 palette=["#c47264", "#b4775a", "#a89c5e", "#8b6b5a", "#9fae6c"]),
    # Armenviertel: winzige, schiefe Hütten dicht an dicht (auch in den Hinterhöfen), enge schlammige Gassen,
    # geflickte Bretterdächer in trüben Farben
    "armen": dict(block=4500, lot=380, alley=3.5, density=1.0, inner=0.95, perimeter=True, poor=True,
                  palette=["#7a6a55", "#6b5e4c", "#857660", "#5f574a", "#8a7a62", "#6f6553", "#77705f"]),
}

# Besondere Gebäude
LANDMARK_COLORS = {
    "kontor": "#6b4a2f", "adelshaus": "#5e3f95", "tempel": "#e2dccb", "kaserne": "#6e6e72",
    "werft": "#456a78", "muehle": "#8a6a4a", "friedhof": "#8f8a80", "festung": "#7d7869", "gasthaus": None, "schmiede": "#4f5a66", "laden": None,
    "wassermuehle": "#7a3f3f", "rathaus": "#8c4f3a", "palast": "#55657e", "bauernhof": None,
    "kathedrale": "#6a707c",
}
BIG_LANDMARKS = {"kontor", "adelshaus", "tempel", "kaserne", "werft", "friedhof", "rathaus", "palast", "kathedrale"}
FORT_TYPES = {"festung", "bastion", "burg"}

COLORS = dict(
    sea_deep="#7fa9bb", sea="#9cc4d2", shallow="#c3dde3", river="#94bfcd",
    land="#4e5f3f", land_dark="#2f3a27", coast="#26301f",
    street="#cdc8b6", street_edge="#7d786a", paved="#d2cec4",
    road="#c1bcaa", road_edge="#6a6658",
    wall="#2b2b2b", wall_top="#9c9a92", tower="#d48b3a", glow="#ffb347",
    outline="#231e1a", text="#f4efe2", text_halo="#1d1d1d",
    trees=["#2f5a3a", "#3b6b40", "#2b4f35", "#456f3c", "#36603f"],
    field_wheat="#c4ac5a", field_wheat2="#a68e3f", field_plowed="#6e5340", field_plowed2="#57402f",
    field_meadow="#7f8f4e", field_meadow2="#6e7d42",
)

# Mitgelieferte freie Schrift (SIL OFL), damit Karten unter Windows und Linux gleich aussehen
FONT = "'EB Garamond', 'Palatino Linotype', 'Book Antiqua', Palatino, Georgia, serif"
FONT_FILE = pathlib.Path(__file__).with_name("fonts") / "EBGaramond-Variable.ttf"

# Biotope: Farben, Vegetation und Bauweise. Jedes Biotop überschreibt nur, was es anders macht.
_BIOME_BASE = dict(
    land=COLORS["land"], mottle_dark="0.12 0.16 0.10", mottle_light="0.45 0.52 0.36", scribble="0.10 0.13 0.08",
    sea_deep=COLORS["sea_deep"], sea=COLORS["sea"], shallow=COLORS["shallow"], river=COLORS["river"],
    trees=COLORS["trees"], tree_kinds={"lappen": 0.5, "rund": 0.3, "nadel": 0.2},
    tree_spacing=1.0, forest_scale=1.0, forest_floor="#26331f",
    street=COLORS["street"], street_edge=COLORS["street_edge"], road=COLORS["road"],
    wall="stein", tower=COLORS["tower"],           # stein | palisade | lehm
    pools=0, pool_style=None, stilts=False, oases=0,  # pool_style: sumpf | eis | oase
    field_kinds=[0.45, 0.35, 0.2], field_prob=0.72, field_colors=None,
    thatch=None, roof_share=0.6, flat_roofs=False,  # thatch: Dachfarben, die die Viertelfarben teilweise ersetzen
    rocks=0, dunes=False, green_banks=False, floes=0, cemetery="#3e5235",
    # Gebirge: Felsmassiv statt Meer, Klamm statt Fluss, Terrassen, Minen, Essen
    mountain=False, chasm=False, terraces=False, forges=False, mines=0, rock="#8a857a", rock_dark="#4a463f",
    # Hochplateau: zweite Geländestufe jenseits einer Felskante (oben: Tiefland, unten: Plateau)
    plateau=False,
    # Bodendetails in der vorberechneten Landtextur: (Art, Farbe, Deckkraft, Seed[, Dichte])
    ground_detail=[("grain", "#1c2615", 0.35, 41), ("grain", "#a3b97c", 0.22, 42),
                   ("stipple", "#1f2c18", 0.55, 43), ("stipple", "#9fb874", 0.4, 44, 0.6)],
    rock_detail=[],
    # Bodentönung nach der Umgebung (umgebung.py): "auto" = aus der Bodenfarbe abgeleitet, None = keine
    moist="auto", dry="auto", worn="auto", moss="auto", shore="#c9b98a",
    relief=0.27,         # Stärke der Schummerung auf dem Boden
)

BIOMES = {
    "gemaessigt": dict(_BIOME_BASE),
    "sumpf": dict(_BIOME_BASE,
        ground_detail=[("grain", "#22261a", 0.4, 41), ("grain", "#8f9a66", 0.2, 42),
                       ("stipple", "#2a3020", 0.55, 43, 1.2), ("strokes", "#8c8f5a", 0.35, 44, 0.5)],
        land="#4b5236", mottle_dark="0.14 0.15 0.08", mottle_light="0.40 0.44 0.26",
        river="#6b8576", shallow="#8a9f88", trees=["#3d4a2a", "#46552f", "#334026", "#55603a", "#4b5a3c"],
        tree_kinds={"weide": 0.42, "lappen": 0.22, "rund": 0.2, "tot": 0.16},
        street="#8f7c5a", street_edge="#4e4230", road="#8a7856", wall="palisade", tower="#8a6a46",
        pools=1.0, pool_style="sumpf", stilts=True, pool="#526349", pool_edge="#2c3422",
        field_kinds=[0.1, 0.25, 0.65], field_prob=0.35,
        thatch=["#a89a5e", "#8e7f4a", "#b3a26a", "#7d6b48", "#9a8a52"],
        dry=None, shore="#5f5a40",
    ),
    "nordland": dict(_BIOME_BASE,
        ground_detail=[("drift", "#ffffff", 0.55, 41), ("drift", "#9fb3c2", 0.3, 45),
                       ("grain", "#a9bccb", 0.25, 42), ("sparkle", "#ffffff", 0.95, 46)],
        land="#dde5e8", mottle_dark="0.62 0.70 0.76", mottle_light="1 1 1", scribble="0.60 0.67 0.72",
        sea_deep="#3c5d76", sea="#6a8ea5", shallow="#d3e3ea", river="#7898ad",
        trees=["#2c4a3e", "#335445", "#29453a", "#3a5a48"], tree_kinds={"tanne": 0.75, "rund": 0.12, "tot": 0.13},
        tree_spacing=1.1, forest_floor="#9eb0b8",
        street="#b3aea2", street_edge="#6b675e", road="#b5afa0", wall="palisade", tower="#8a6a46",
        pools=0.45, pool_style="eis", pool="#bcd3de", pool_edge="#6f8ea0",
        field_kinds=[0.0, 1.0, 0.0], field_prob=0.25,
        field_colors={"plowed": ("#d3d9db", "#a7a59c")},
        thatch=["#eef1f2", "#e3e8ea", "#d6dde0"], roof_share=0.75,
        rocks=1.0, floes=1.0, cemetery="#cfd8dc",
        moist=None, dry=None, worn="#b3ab98", shore="#b4bab8", relief=0.32,
    ),
    "steppe": dict(_BIOME_BASE,
        ground_detail=[("grain", "#5a5530", 0.35, 41), ("grain", "#d8cd92", 0.22, 42),
                       ("strokes", "#e0d08e", 0.5, 43, 1.3), ("strokes", "#5c5a2f", 0.35, 44, 0.8)],
        land="#a7a065", mottle_dark="0.45 0.43 0.25", mottle_light="0.82 0.78 0.52", scribble="0.35 0.33 0.18",
        trees=["#5a6b34", "#667a3a", "#4f5e2e", "#748446"], tree_kinds={"rund": 0.45, "busch": 0.4, "tot": 0.15},
        tree_spacing=1.8, forest_scale=0.6, forest_floor="#6e6b3a",
        street="#c9b98d", street_edge="#7f6f4a", road="#c2b386", wall="palisade", tower="#8a6a46",
        field_kinds=[0.6, 0.25, 0.15], field_prob=0.6,
        thatch=["#b9a66b", "#a8935a", "#c4b07a", "#9c8752"],
        rocks=0.8, cemetery="#7d7a48",
        moist="#7f8b48", shore="#d9cc98",
    ),
    "wueste": dict(_BIOME_BASE,
        ground_detail=[("ripple_light", "#f7e9c6", 0.5, 41), ("ripple_dark", "#a07c47", 0.35, 41),
                       ("grain", "#8c6a3c", 0.25, 42), ("grain", "#fff1cf", 0.2, 43)],
        land="#d9be88", mottle_dark="0.62 0.48 0.28", mottle_light="0.97 0.89 0.68", scribble="0.55 0.42 0.25",
        sea_deep="#2f7f94", sea="#5fb0bd", shallow="#a7d8cf", river="#4d9fae",
        trees=["#5b7a35", "#6a8a3a", "#4f6d2f", "#7a9445"], tree_kinds={"palme": 0.65, "busch": 0.35},
        tree_spacing=1.5, forest_scale=0.55, forest_floor="#8f8a4a",
        street="#e6d3a6", street_edge="#9b7c4c", road="#e1cc9a", wall="lehm", tower="#c99a5e",
        pools=0, pool_style="oase", pool="#3f9aa3", pool_edge="#2a5d5e", oases=2,
        field_kinds=[0.5, 0.15, 0.35], field_prob=0.55,
        thatch=["#c9a06a", "#b88d5a", "#d4b07c", "#a97e4e", "#c2955f"], roof_share=0.85, flat_roofs=True,
        rocks=0.6, dunes=True, green_banks=True, cemetery="#c9b48a",
        moist="#86934a", dry="#e8d3a0", shore="#efdcae", relief=0.3,
    ),
    "gebirge": dict(_BIOME_BASE,
        ground_detail=[("grain", "#262a1e", 0.4, 41), ("grain", "#b9bb9c", 0.25, 42),
                       ("stipple", "#2b3324", 0.5, 43, 0.7), ("stipple", "#8a8676", 0.45, 44, 0.6)],
        rock_detail=[("cracks", "#221f1b", 0.8, 47), ("cracks_hi", "#ddd7ca", 0.4, 47)],
        land="#6f7752", mottle_dark="0.30 0.32 0.24", mottle_light="0.62 0.64 0.48", scribble="0.25 0.26 0.20",
        river="#7fb0c0", trees=["#2e4a3c", "#355243", "#2a4436", "#3d5a44"],
        tree_kinds={"nadel": 0.72, "rund": 0.16, "tot": 0.12}, tree_spacing=1.2, forest_floor="#2a3a2c",
        street="#a9a69c", street_edge="#5e5b54", road="#b3ad9f", wall="stein", tower="#a8a08c",
        field_kinds=[0.15, 0.15, 0.7], field_prob=0.4,
        thatch=["#5d6470", "#4f5661", "#6b7280", "#59606b", "#8a5a3a"], roof_share=0.8,
        rocks=1.5, cemetery="#55604a",
        mountain=True, chasm=True, terraces=True, forges=True, mines=4,
        slope="#8a8476", city_ground="#968f80",   # steiniger Hang und Stadtboden
    ),
    "hochplateau": dict(_BIOME_BASE,
        ground_detail=[("grain", "#2a3018", 0.38, 41), ("grain", "#c9c08a", 0.22, 42),
                       ("strokes", "#d6cc8e", 0.35, 43, 0.8), ("stipple", "#2c3420", 0.45, 44, 0.7)],
        land="#6c7547", mottle_dark="0.30 0.32 0.20", mottle_light="0.66 0.66 0.44", scribble="0.24 0.25 0.16",
        trees=["#3f5a34", "#4a6438", "#36502e", "#56703e"], tree_kinds={"lappen": 0.4, "rund": 0.35, "nadel": 0.25},
        tree_spacing=1.2, forest_floor="#2f3a26",
        street="#c4bca2", street_edge="#756d58", road="#beb59a",
        field_kinds=[0.5, 0.25, 0.25], field_prob=0.6,
        rock="#a09276", rock_dark="#4e4535", rocks=0.6,
        plateau=True,
    ),
}
BIOME_ALIASES = {"gemaessigtes": "gemaessigt", "wald": "gemaessigt", "moor": "sumpf", "winter": "nordland",
                 "schnee": "nordland", "tundra": "nordland", "norden": "nordland", "wueste": "wueste",
                 "oase": "wueste", "sand": "wueste", "savanne": "steppe", "grasland": "steppe",
                 "plateau": "hochplateau", "hochebene": "hochplateau", "tafelberg": "hochplateau",
                 "tafelland": "hochplateau", "berg": "gebirge", "berge": "gebirge", "zwerge": "gebirge", "gebirgsstadt": "gebirge"}

# Zeichenstile der fertigen Karte (ausgabe.stil); umgesetzt in render.py, papier.py und stile.py.
# Schlüssel -> (Name in der Oberfläche, kurze Beschreibung). Die Reihenfolge ist die der Auswahl.
STILE = {
    "pergament": ("Pergament (altes Papier)", "Papierstruktur, warmer Ton, gebräunter Rand, Küste wie mit der Feder"),
    "standard": ("Standard (ohne Papier)", "klare Farben, dunkle Vignette am Rand"),
    "tusche": ("Tusche", "Feder und Tinte auf Elfenbeinpapier, fast ohne Farbe"),
    "aquarell": ("Aquarell", "weiche, leicht verlaufene Farben, Papierkörnung, ausbleichender Rand"),
    "sepia": ("Sepia-Stich", "einfarbig braun wie ein alter Druck"),
    "schatzkarte": ("Schatzkarte", "gealtertes, fleckiges Pergament mit angebrannten Ecken"),
    "abendlicht": ("Goldene Stunde", "die Karte in warmem Abendlicht"),
    "farbdruck": ("Farbdruck", "wenige Farbflächen und Rasterpunkte wie eine alte Lithografie"),
    "pastell": ("Pastell", "helle, sanfte Farben mit klaren Umrissen"),
    "bleistift": ("Bleistift", "Graustufen mit Schraffur wie eine Skizze"),
    "stich": ("Kolorierter Stich", "Tintenlinien mit blasser Handkolorierung"),
}
# andere Schreibweisen
STIL_ALIASE = {"normal": "standard", "modern": "standard", "papier": "pergament", "alt": "pergament",
               "historisch": "pergament", "feder": "tusche", "tinte": "tusche", "wasserfarbe": "aquarell",
               "sepiastich": "sepia", "schatz": "schatzkarte", "goldenestunde": "abendlicht", "abend": "abendlicht",
               "lithografie": "farbdruck", "druck": "farbdruck", "pastel": "pastell", "skizze": "bleistift",
               "kupferstich": "stich", "koloriert": "stich", "kolorierterstich": "stich"}
