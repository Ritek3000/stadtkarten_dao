"""
Stadtkarte -> Blender
=====================
Builds a city from the JSON written by ``python -m stadtkarte.blender_export`` in one of two modes:

  OUTPUT_MODE = '2D'   flat Poly/Bezier curves on the XY plane, sorted into one Collection per feature type
                       (Main_Roads, Side_Streets, Waterways, Building_Outlines ...), cleaned for SVG export
  OUTPUT_MODE = '3D'   extruded buildings (height by location and type), road strips with real width, street and
                       plaza surfaces, water, ground slab, city walls - with placeholder materials

Use it
  1. python -m stadtkarte.blender_export beispiele/hafenstadt.yaml -o city.json
  2. Blender: Scripting workspace -> open this file -> set JSON_PATH and OUTPUT_MODE below -> Run Script
     or headless:  blender -b -P stadtkarte_blender.py -- --json city.json --mode 3D --save city.blend

Written for Blender 4.x / 5.x; it only needs bpy, bmesh and mathutils (no third-party packages). Meshes are built
with ``bpy.data.meshes.new()`` + ``from_pydata()``; no ``bpy.ops`` is called while generating geometry.
Lengths below are in Blender units (1 unit = 1 m with default scene units) unless marked "px" (map pixels).
"""
import argparse
import json
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Vector, geometry

# =====================================================================================================================
# CONFIGURATION
# =====================================================================================================================
JSON_PATH = "//city.json"       # file from stadtkarte.blender_export; "//" = next to the saved .blend file
OUTPUT_MODE = '3D'              # '2D' = flat curves for SVG export | '3D' = extruded meshes
RANDOM_SEED = 42                # seeds building heights only; the city layout is fixed by the JSON
UNITS_PER_PIXEL = 0.5           # map pixel -> Blender units (0.5: a 20 px house becomes 10 m wide)
CENTER_ON_ORIGIN = True         # True: city centre at (0, 0); False: lower-left map corner at (0, 0)
REPLACE_PREVIOUS = True         # delete the result of an earlier run ("<city>_2D" / "<city>_3D") before building
                                # (child collections keep their plain names; Blender adds ".001" if the other mode exists)

# --- cleanup (both modes), Blender units -----------------------------------------------------------------------------
MERGE_DISTANCE = 0.005          # points closer than this count as the same point
SIMPLIFY_TOLERANCE = 0.02       # collinear points within this distance of the straight line are dropped (0 = keep)
MIN_AREA = 0.05                 # polygons smaller than this (square units) are dropped

# --- MODE 2D ---------------------------------------------------------------------------------------------------------
CURVE_TYPE = 'POLY'             # 'POLY' (exact polylines) | 'BEZIER' (sharp corners on outlines, smooth on roads/rivers)
ROAD_2D_STYLE = 'centerline'    # 'centerline' | 'outline' (closed outline of the road strip, uses the road width)
FILL_CLOSED_CURVES = False      # True: closed curves get a fill (Curve.fill_mode = 'BOTH')

# --- MODE 3D: building height ----------------------------------------------------------------------------------------
# height = DEFAULT_HEIGHT * type * district * centrality * random, optionally tall "skyscrapers" near the centre
DEFAULT_HEIGHT = 10.0           # height of an ordinary house of average centrality
HEIGHT_VARIATION = 0.35         # random +-35 % per building
CENTER_FACTOR = 2.2             # height multiplier at the city centre ...
OUTSKIRTS_FACTOR = 0.6          # ... falling to this at the city edge
CENTER_FALLOFF = 1.5            # >1 concentrates the tall buildings near the very centre
SKYSCRAPER_ZONE = 0.55          # centrality (0 edge .. 1 centre) above which skyscrapers may appear
SKYSCRAPER_CHANCE = 0.10        # probability per ordinary building inside that zone
SKYSCRAPER_BOOST = 3.0          # extra height multiplier of a skyscraper
SKYSCRAPER_MIN_FOOTPRINT = 60.0 # smallest footprint (square units) that may become a skyscraper
MAX_ASPECT = 6.0                # height <= MAX_ASPECT * sqrt(footprint): thin sheds never turn into needles
MIN_HEIGHT, MAX_HEIGHT = 3.0, 150.0
TYPE_FACTOR = {'house': 1.0, 'landmark': 2.2, 'fort': 1.4, 'suburb': 0.6}     # by building kind
DISTRICT_FACTOR = {                                                          # by district type (Viertel)
    'hafen': 0.9, 'handwerk': 1.0, 'arbeiter': 0.85, 'fischer': 0.7, 'bauern': 0.6,
    'adel': 1.5, 'tempel': 1.3, 'markt': 1.2, 'wohn': 1.0, 'armen': 0.6, 'ruinen': 1.0,
}
POOR_FACTOR = 0.75              # buildings flagged "poor"
RUIN_FACTOR = 0.35              # ruined houses (Ruinenviertel, feature flag "ruin"): low wall stumps, never skyscrapers
GLASS_MIN_HEIGHT = 30.0         # buildings at least this tall get the glass material
MERGE_BUILDINGS = True          # True: one mesh object per district (fast) | False: one object per building

# --- MODE 3D: roads, ground, walls -----------------------------------------------------------------------------------
USE_DATA_ROAD_WIDTHS = True     # True: width from the map data | False: ROAD_WIDTH per class
ROAD_WIDTH = {'main': 7.0, 'side': 4.5, 'country': 6.0, 'bridge': 8.0}      # units, used if the line above is False
ROAD_WIDTH_SCALE = 1.0          # multiplies every road width
MITER_LIMIT = 2.0               # limits how far road corners poke out on sharp bends
ROAD_THICKNESS, BRIDGE_THICKNESS = 0.20, 0.60
LEVELS = {                      # height of each surface's top above the ground plane (z = 0), so layers never z-fight
    'streets': 0.10, 'plazas': 0.14, 'piers': 0.30,
    'road_country': 0.16, 'road_side': 0.20, 'road_main': 0.24, 'road_bridge': 0.60,
}
GROUND_THICKNESS = 3.0          # ground slab depth below z = 0 (forms the river banks and a clean map edge)
WATER_LEVEL = -0.5              # water surface height
WALL_HEIGHT, WALL_THICKNESS = 8.0, 2.0
TOWER_HEIGHT, GATE_HEIGHT = 13.0, 10.0
WALL_BASE = -1.0                # walls start below the ground so they also stand firm at the water's edge

BUILD_LAYERS = {                # switch parts of the 3D city on/off
    'buildings': True, 'roads': True, 'streets': True, 'plazas': True, 'piers': True,
    'water': True, 'ground': True, 'walls': True,
}

# --- MODE 3D: placeholder materials (sRGB colour, roughness, metallic) -----------------------------------------------
# Existing "SK_*" materials are reused untouched, so you can tweak them once and re-run the script.
COLORS = {
    'Building':  ((0.13, 0.13, 0.14), 0.80, 0.0),   # dark grey
    'Glass':     ((0.30, 0.45, 0.55), 0.05, 0.0),   # blue-grey, glossy, semi transparent
    'Landmark':  ((0.46, 0.41, 0.34), 0.85, 0.0),   # warm stone
    'Road':      ((0.20, 0.20, 0.21), 0.90, 0.0),   # asphalt grey
    'Street':    ((0.34, 0.34, 0.35), 0.95, 0.0),   # lighter grey lane surface
    'Plaza':     ((0.52, 0.50, 0.46), 0.95, 0.0),   # paving
    'Bridge':    ((0.38, 0.32, 0.26), 0.90, 0.0),
    'Water':     ((0.05, 0.20, 0.38), 0.05, 0.0),
    'Ground':    ((0.17, 0.27, 0.12), 1.00, 0.0),
    'Wall':      ((0.48, 0.45, 0.40), 0.90, 0.0),
}
# =====================================================================================================================
# END OF CONFIGURATION
# =====================================================================================================================

FORMAT = "stadtkarte-blender"
BUILDING, GLASS, LANDMARK = 0, 1, 2     # material slots of building meshes


# ---------------------------------------------------------------------------------------------------------------------
# input
# ---------------------------------------------------------------------------------------------------------------------
def load_city(path):
    path = bpy.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"City file not found: {path}\nCreate it with:  python -m stadtkarte.blender_export <city.yaml> -o city.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as err:
        raise ValueError(f"{path} is not a valid JSON file ({err})") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError(f"{path} is not a {FORMAT} file - create it with stadtkarte.blender_export")
    return data


class Transform:
    """Map pixels (y down) -> Blender units (y up), optionally centred on the city."""

    def __init__(self, meta):
        self.k = UNITS_PER_PIXEL
        self.ox, self.oy = meta["center"] if CENTER_ON_ORIGIN else (0.0, meta["map_size"])

    def pt(self, p):
        return ((p[0] - self.ox) * self.k, (self.oy - p[1]) * self.k)


# ---------------------------------------------------------------------------------------------------------------------
# 2D geometry helpers (pure Python)
# ---------------------------------------------------------------------------------------------------------------------
def signed_area(ring):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))


def _segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 < 1e-18 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def simplify_polyline(pts, tol):
    """Ramer-Douglas-Peucker: drops points that lie within tol of the line through their neighbours (this removes the
    collinear points of straight walls and the needless density of smooth curves); the shape moves by at most tol."""
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        far, dist = -1, tol
        for k in range(i + 1, j):
            d = _segment_distance(pts[k], pts[i], pts[j])
            if d > dist:
                far, dist = k, d
        if far >= 0:
            keep[far] = True
            stack += [(i, far), (far, j)]
    return [p for p, k in zip(pts, keep) if k]


def clean_points(pts, closed):
    """Removes duplicate points, the repeated closing point and collinear points. None if too little is left."""
    out = []
    for p in pts:
        if not out or math.dist(p, out[-1]) > MERGE_DISTANCE:
            out.append(p)
    if closed:
        while len(out) > 1 and math.dist(out[0], out[-1]) <= MERGE_DISTANCE:
            out.pop()
    need = 3 if closed else 2
    if SIMPLIFY_TOLERANCE > 0 and len(out) > need:
        if closed:     # split the ring at the point farthest from the first one and simplify both halves
            split = max(range(len(out)), key=lambda k: math.dist(out[k], out[0]))
            out = simplify_polyline(out[:split + 1], SIMPLIFY_TOLERANCE)[:-1] \
                + simplify_polyline(out[split:] + out[:1], SIMPLIFY_TOLERANCE)[:-1]
        else:
            out = simplify_polyline(out, SIMPLIFY_TOLERANCE)
    return out if len(out) >= need else None


def prep_polygon(feat, xf):
    """Feature {ring, holes} -> (outer CCW, [holes CW]) in Blender units, or None if it is degenerate."""
    outer = clean_points([xf.pt(p) for p in feat["ring"]], True)
    if outer is None or abs(signed_area(outer)) < MIN_AREA:
        return None
    if signed_area(outer) < 0:
        outer.reverse()
    holes = []
    for h in feat.get("holes", ()):
        ring = clean_points([xf.pt(p) for p in h], True)
        if ring is None or abs(signed_area(ring)) < MIN_AREA:
            continue
        if signed_area(ring) > 0:
            ring.reverse()
        holes.append(ring)
    return outer, holes


def prep_line(feat, xf):
    closed = bool(feat.get("closed"))
    pts = clean_points([xf.pt(p) for p in feat["line"]], closed)
    return (pts, closed) if pts else None


def is_convex(ring):
    n = len(ring)
    for i in range(n):
        a, b, c = ring[i], ring[(i + 1) % n], ring[(i + 2) % n]
        if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) < -1e-9:
            return False
    return True


def cap_faces(rings):
    """Faces (index tuples into the concatenated rings) that fill outer ring minus holes, all facing +Z."""
    outer = rings[0]
    if len(rings) == 1 and is_convex(outer):
        return [tuple(range(len(outer)))]
    flat = [p for r in rings for p in r]
    tris = geometry.tessellate_polygon([[Vector((x, y, 0.0)) for x, y in r] for r in rings])
    faces = []
    for a, b, c in tris:
        cross = (flat[b][0] - flat[a][0]) * (flat[c][1] - flat[a][1]) - (flat[b][1] - flat[a][1]) * (flat[c][0] - flat[a][0])
        if abs(cross) > 1e-12:
            faces.append((a, b, c) if cross > 0 else (a, c, b))
    return faces


def strip_sides(pts, half_width, closed):
    """Left and right edge of a road strip around a polyline, with mitred corners (length limited by MITER_LIMIT)."""
    n = len(pts)
    dirs = []
    for i in range(n if closed else n - 1):
        a, b = pts[i], pts[(i + 1) % n]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        dirs.append(((b[0] - a[0]) / length, (b[1] - a[1]) / length))
    left, right = [], []
    for i, (x, y) in enumerate(pts):
        d0 = dirs[i - 1] if (closed or i > 0) else dirs[0]
        d1 = dirs[i] if (closed or i < n - 1) else dirs[-1]
        n0, n1 = (-d0[1], d0[0]), (-d1[1], d1[0])
        mx, my = n0[0] + n1[0], n0[1] + n1[1]
        ml = math.hypot(mx, my)
        if ml < 1e-9:                                   # path turns back on itself: just use the next segment's normal
            nx, ny, scale = n1[0], n1[1], 1.0
        else:
            nx, ny = mx / ml, my / ml
            scale = min(1.0 / max(nx * n1[0] + ny * n1[1], 1e-6), MITER_LIMIT)
        ox, oy = nx * half_width * scale, ny * half_width * scale
        left.append((x + ox, y + oy))
        right.append((x - ox, y - oy))
    return left, right


# ---------------------------------------------------------------------------------------------------------------------
# mesh construction (lists of vertices/faces -> one Blender mesh)
# ---------------------------------------------------------------------------------------------------------------------
class MeshBuilder:
    def __init__(self):
        self.verts, self.faces, self.mats = [], [], []

    def face(self, idx, mat=0):
        self.faces.append(tuple(idx))
        self.mats.append(mat)

    def add_flat(self, outer, holes, z, mat=0):
        """Flat surface at height z, normal up."""
        rings = [outer] + holes
        base = len(self.verts)
        self.verts.extend((x, y, z) for r in rings for x, y in r)
        for f in cap_faces(rings):
            self.face([base + i for i in f], mat)

    def add_prism(self, outer, holes, z0, z1, mat=0):
        """Closed solid from z0 to z1 with caps; holes become walls facing into the hole."""
        rings = [outer] + holes
        bottom, top = [], []                                    # vertex index of every point, in ring order
        for r in rings:
            n, b0 = len(r), len(self.verts)
            self.verts.extend((x, y, z0) for x, y in r)
            self.verts.extend((x, y, z1) for x, y in r)
            bottom += range(b0, b0 + n)
            top += range(b0 + n, b0 + 2 * n)
            for i in range(n):
                j = (i + 1) % n
                self.face((b0 + i, b0 + j, b0 + n + j, b0 + n + i), mat)   # CCW outer ring -> normal points outward
        for f in cap_faces(rings):
            self.face([top[i] for i in f], mat)
            self.face([bottom[i] for i in reversed(f)], mat)

    def add_strip(self, pts, closed, width, z_top, z_bottom=None, mat=0):
        """Road/wall strip along a polyline. z_bottom=None: flat ribbon at z_top; otherwise a closed solid."""
        left, right = strip_sides(pts, width / 2.0, closed)
        n = len(pts)
        segs = n if closed else n - 1
        base = len(self.verts)
        lt, rt, lb, rb = base, base + n, base + 2 * n, base + 3 * n
        self.verts.extend((x, y, z_top) for x, y in left)
        self.verts.extend((x, y, z_top) for x, y in right)
        if z_bottom is None:
            for i in range(segs):
                j = (i + 1) % n
                self.face((rt + i, rt + j, lt + j, lt + i), mat)
            return
        self.verts.extend((x, y, z_bottom) for x, y in left)
        self.verts.extend((x, y, z_bottom) for x, y in right)
        for i in range(segs):
            j = (i + 1) % n
            self.face((rt + i, rt + j, lt + j, lt + i), mat)    # top
            self.face((lt + i, lt + j, lb + j, lb + i), mat)    # left side
            self.face((rb + i, rb + j, rt + j, rt + i), mat)    # right side
            self.face((lb + i, lb + j, rb + j, rb + i), mat)    # bottom
        if not closed:
            self.face((lb, rb, rt, lt), mat)                    # start cap
            self.face((rb + n - 1, lb + n - 1, lt + n - 1, rt + n - 1), mat)   # end cap


def make_mesh_object(name, mb, collection, materials=(), weld=True, outward=True):
    """MeshBuilder -> mesh object. outward: recalculate normals to point outside (closed solids); weld: merge doubles.
    Normals come first: the pieces are still separate closed shells then, so welding touching pieces afterwards
    cannot confuse the inside/outside test."""
    if not mb.faces:
        return None
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(mb.verts, [], mb.faces)
    for mat in materials:
        mesh.materials.append(mat)
    if len(materials) > 1:
        mesh.polygons.foreach_set("material_index", mb.mats)
    mesh.update()
    if weld or outward:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        if outward:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        if weld:
            bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=MERGE_DISTANCE)
        bm.to_mesh(mesh)
        bm.free()
    mesh.validate()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


# ---------------------------------------------------------------------------------------------------------------------
# materials, collections
# ---------------------------------------------------------------------------------------------------------------------
def get_material(key):
    name = f"SK_{key}"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    rgb, roughness, metallic = COLORS[key]
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*rgb, 1.0)                 # viewport colour (solid mode)
    mat.roughness, mat.metallic = roughness, metallic
    if not getattr(mat, "use_nodes", True):         # Blender 4.x: off by default; 5.x: always on
        mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if mat.node_tree else None
    if bsdf is not None:
        def put(names, value):
            for socket_name in names:
                socket = bsdf.inputs.get(socket_name)
                if socket is not None:
                    socket.default_value = value
                    return
        put(("Base Color",), (*rgb, 1.0))
        put(("Roughness",), roughness)
        put(("Metallic",), metallic)
        if key == 'Glass':
            put(("Transmission Weight", "Transmission"), 0.6)
    return mat


def new_collection(name, parent):
    coll = bpy.data.collections.new(name)
    parent.children.link(coll)
    return coll


def remove_collection_tree(name):
    """Deletes an earlier run: its objects, their mesh/curve data and the collections."""
    root = bpy.data.collections.get(name)
    if root is None:
        return
    for obj in list(root.all_objects):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            (bpy.data.meshes if isinstance(data, bpy.types.Mesh) else bpy.data.curves).remove(data)
    for coll in list(root.children_recursive):
        bpy.data.collections.remove(coll)
    bpy.data.collections.remove(root)


def safe_name(text, limit=56):
    """Blender names are limited to 63 bytes."""
    return text.encode("utf-8")[:limit].decode("utf-8", "ignore") or "unnamed"


# ---------------------------------------------------------------------------------------------------------------------
# MODE 2D: curves
# ---------------------------------------------------------------------------------------------------------------------
def add_curve_object(name, collection, splines, props=None):
    """splines: list of (points, closed, smooth). One curve datablock per object, one spline per feature."""
    if not splines:
        return None
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = '2D'
    curve.fill_mode = 'BOTH' if FILL_CLOSED_CURVES else 'NONE'
    for pts, closed, smooth in splines:
        n = len(pts)
        if CURVE_TYPE == 'BEZIER':
            sp = curve.splines.new('BEZIER')
            sp.bezier_points.add(n - 1)
            sp.bezier_points.foreach_set("co", [c for x, y in pts for c in (x, y, 0.0)])
            handle = 'AUTO' if smooth else 'VECTOR'
            for bp in sp.bezier_points:
                bp.handle_left_type = bp.handle_right_type = handle
        else:
            sp = curve.splines.new('POLY')
            sp.points.add(n - 1)
            sp.points.foreach_set("co", [c for x, y in pts for c in (x, y, 0.0, 1.0)])
        sp.use_cyclic_u = closed
    obj = bpy.data.objects.new(name, curve)
    for key, value in (props or {}).items():
        obj[key] = value
    collection.objects.link(obj)
    return obj


def polygon_splines(feats, xf):
    out = []
    for f in feats:
        prepared = prep_polygon(f, xf)
        if prepared:
            out += [(ring, True, False) for ring in [prepared[0]] + prepared[1]]
    return out


def line_splines(feats, xf, smooth=True):
    out = []
    for f in feats:
        prepared = prep_line(f, xf)
        if prepared:
            out.append((prepared[0], prepared[1], smooth))
    return out


def build_2d(data, xf, root):
    names = ("Main_Roads", "Side_Streets", "Country_Roads", "Bridges", "Plazas", "Piers", "Waterways",
             "Building_Outlines", "City_Walls")
    coll = {n: new_collection(n, root) for n in names}
    objects = 0

    def put(collection, name, splines, props=None):
        nonlocal objects
        if add_curve_object(safe_name(name), coll[collection], splines, props):
            objects += 1

    # roads: one curve object per road class and width, so the width survives as a custom property
    road_groups = {"main": ("Main_Roads", "Main_Road"), "side": ("Side_Streets", "Side_Street"),
                   "country": ("Country_Roads", "Country_Road"), "bridge": ("Bridges", "Bridge")}
    by_width = {}
    for road in data["roads"]:
        by_width.setdefault((road["cls"], road["width"]), []).append(road)
    for (cls, width), roads in sorted(by_width.items()):
        collection, prefix = road_groups[cls]
        width_units = width * xf.k * ROAD_WIDTH_SCALE
        splines = []
        for road in roads:
            prepared = prep_line(road, xf)
            if prepared is None:
                continue
            pts, closed = prepared
            if ROAD_2D_STYLE == 'outline':
                left, right = strip_sides(pts, width_units / 2, closed)
                if closed:
                    splines += [(s, True, False) for s in map(lambda r: clean_points(r, True), (left, right)) if s]
                else:
                    ring = clean_points(left + right[::-1], True)
                    splines += [(ring, True, False)] if ring else []
            else:
                splines.append((pts, closed, True))
        put(collection, f"{prefix}_w{width:g}", splines, {"width_px": width, "width_units": width_units})
    put("Side_Streets", "Lane_Network_Outline", polygon_splines(data["streets"], xf))
    put("Plazas", "Plaza_Outlines", polygon_splines(data["plazas"], xf))
    put("Piers", "Pier_Outlines", polygon_splines(data["piers"], xf))
    put("Waterways", "Shorelines", line_splines(data["shorelines"], xf))
    put("Waterways", "River_Centerline", line_splines(data["waterways"], xf),
        {"width_px": data["waterways"][0]["width"]} if data["waterways"] else None)
    groups = {}
    for b in data["buildings"]:
        if b["kind"] == "house":
            key = f"Houses_{b['district'] or 'Outside'}"
        else:
            key = {"landmark": "Landmarks", "suburb": "Suburb_Houses", "fort": "Fort_Buildings"}[b["kind"]]
        groups.setdefault(key, []).append(b)
    for key, feats in sorted(groups.items()):
        put("Building_Outlines", key, polygon_splines(feats, xf))
    put("City_Walls", "Walls", line_splines(data["walls"], xf, smooth=False))
    put("City_Walls", "Towers", polygon_splines(data["towers"], xf))
    put("City_Walls", "Gates", polygon_splines(data["gates"], xf))
    return {"curve objects": objects, "splines": sum(len(o.data.splines) for c in coll.values() for o in c.objects)}


# ---------------------------------------------------------------------------------------------------------------------
# MODE 3D: meshes
# ---------------------------------------------------------------------------------------------------------------------
def polygon_center(ring):
    """Area centroid of a simple polygon (falls back to the vertex mean for degenerate input)."""
    a = cx = cy = 0.0
    for p, q in zip(ring, ring[1:] + ring[:1]):
        cross = p[0] * q[1] - q[0] * p[1]
        a += cross
        cx += (p[0] + q[0]) * cross
        cy += (p[1] + q[1]) * cross
    if abs(a) < 1e-12:
        return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    return (cx / (3 * a), cy / (3 * a))


def building_height(index, feat, outer, holes, center, radius):
    """Height from building type, district, distance to the city centre and a per-building random factor."""
    rng = random.Random(f"{RANDOM_SEED}:{index}")           # stable per building, independent of the other layers
    cx, cy = polygon_center(outer)
    centrality = max(0.0, 1.0 - math.hypot(cx - center[0], cy - center[1]) / max(radius, 1e-6))   # 1 centre .. 0 edge
    factor = OUTSKIRTS_FACTOR + (CENTER_FACTOR - OUTSKIRTS_FACTOR) * centrality ** CENTER_FALLOFF
    footprint = abs(signed_area(outer)) - sum(abs(signed_area(h)) for h in holes)
    height = DEFAULT_HEIGHT * TYPE_FACTOR.get(feat["kind"], 1.0) * DISTRICT_FACTOR.get(feat.get("district_type"), 1.0) \
        * (POOR_FACTOR if feat.get("poor") else 1.0) * (RUIN_FACTOR if feat.get("ruin") else 1.0) \
        * factor * rng.uniform(1 - HEIGHT_VARIATION, 1 + HEIGHT_VARIATION)
    if feat["kind"] == "house" and not feat.get("ruin") and centrality >= SKYSCRAPER_ZONE \
            and footprint >= SKYSCRAPER_MIN_FOOTPRINT and rng.random() < SKYSCRAPER_CHANCE:
        height *= SKYSCRAPER_BOOST
    height = min(height, MAX_ASPECT * math.sqrt(max(footprint, 0.0)))
    height = max(MIN_HEIGHT, min(height, MAX_HEIGHT))
    slot = LANDMARK if feat["kind"] in ("landmark", "fort") else GLASS if height >= GLASS_MIN_HEIGHT else BUILDING
    return height, slot


def build_buildings(data, xf, coll, stats):
    meta = data["meta"]
    center, radius = xf.pt(meta["center"]), meta["radius"] * xf.k
    materials = [get_material('Building'), get_material('Glass'), get_material('Landmark')]
    builders, heights = {}, []
    for i, feat in enumerate(data["buildings"]):
        prepared = prep_polygon(feat, xf)
        if prepared is None:
            stats["skipped"] += 1
            continue
        outer, holes = prepared
        height, slot = building_height(i, feat, outer, holes, center, radius)
        if MERGE_BUILDINGS:
            other = {"house": "Other", "suburb": "Suburb", "fort": "Fort"}.get(feat["kind"], feat["kind"].capitalize())
            key = f"Buildings_{feat['district'] or other}"
        else:
            key = f"Building_{i:05d}"
        builders.setdefault(key, MeshBuilder()).add_prism(outer, holes, 0.0, height, slot)
        heights.append(height)
    for key, mb in builders.items():
        # merged meshes are not welded: touching neighbours would fuse into non-manifold geometry
        make_mesh_object(safe_name(key), mb, coll, materials, weld=not MERGE_BUILDINGS, outward=True)
    stats["buildings"] = len(heights)
    if heights:
        stats["height min/mean/max"] = f"{min(heights):.1f} / {sum(heights) / len(heights):.1f} / {max(heights):.1f}"
        stats["tall (glass)"] = sum(h >= GLASS_MIN_HEIGHT for h in heights)


def flat_layer(feats, xf, name, collection, mat_key, z, prism_bottom=None, outward=False):
    """Polygons of one layer as a flat surface at z, or as a solid down to prism_bottom."""
    mb = MeshBuilder()
    for feat in feats:
        prepared = prep_polygon(feat, xf)
        if prepared is None:
            continue
        if prism_bottom is None:
            mb.add_flat(*prepared, z)
        else:
            mb.add_prism(*prepared, prism_bottom, z)
    return make_mesh_object(name, mb, collection, [get_material(mat_key)], weld=True, outward=outward)


def build_roads(data, xf, coll):
    builders = {"main": MeshBuilder(), "side": MeshBuilder(), "country": MeshBuilder(), "bridge": MeshBuilder()}
    for road in data["roads"]:
        prepared = prep_line(road, xf)
        if prepared is None:
            continue
        pts, closed = prepared
        cls = road["cls"]
        width = (road["width"] * xf.k if USE_DATA_ROAD_WIDTHS else ROAD_WIDTH[cls]) * ROAD_WIDTH_SCALE
        top = LEVELS[f"road_{cls}"]
        thick = BRIDGE_THICKNESS if cls == "bridge" else ROAD_THICKNESS
        builders[cls].add_strip(pts, closed, width, top, top - thick)
    names = {"main": ("Main_Roads", "Road"), "side": ("Side_Streets", "Street"),
             "country": ("Country_Roads", "Road"), "bridge": ("Bridges", "Bridge")}
    for cls, mb in builders.items():
        collection, mat_key = names[cls]
        make_mesh_object(f"{collection}_Strips", mb, coll[collection], [get_material(mat_key)], weld=True, outward=True)


def build_walls(data, xf, coll):
    wall, towers, gates = MeshBuilder(), MeshBuilder(), MeshBuilder()
    for feat in data["walls"]:
        prepared = prep_line(feat, xf)
        if prepared:
            wall.add_strip(prepared[0], prepared[1], WALL_THICKNESS, WALL_HEIGHT, WALL_BASE)
    for mb, feats, top in ((towers, data["towers"], TOWER_HEIGHT), (gates, data["gates"], GATE_HEIGHT)):
        for feat in feats:
            prepared = prep_polygon(feat, xf)
            if prepared:
                mb.add_prism(*prepared, WALL_BASE, top)
    material = [get_material('Wall')]
    for name, mb in (("Walls", wall), ("Towers", towers), ("Gates", gates)):
        make_mesh_object(name, mb, coll, material, weld=True, outward=True)


def build_3d(data, xf, root):
    stats = {"skipped": 0}
    layers = BUILD_LAYERS
    coll = {n: new_collection(n, root) for n in ("Ground", "Waterways", "Streets", "Plazas", "Piers", "Main_Roads",
                                                 "Side_Streets", "Country_Roads", "Bridges", "Buildings", "City_Walls")}
    if layers['ground']:        # slab with the water cut out: its inner walls are the banks
        flat_layer(data["land"], xf, "Ground", coll["Ground"], 'Ground', 0.0, prism_bottom=-GROUND_THICKNESS, outward=True)
    if layers['water']:
        flat_layer(data["water"], xf, "Water", coll["Waterways"], 'Water', WATER_LEVEL,
                   prism_bottom=-GROUND_THICKNESS, outward=True)
    if layers['streets']:
        flat_layer(data["streets"], xf, "Lane_Surface", coll["Streets"], 'Street', LEVELS['streets'])
    if layers['plazas']:
        flat_layer(data["plazas"], xf, "Plaza_Surface", coll["Plazas"], 'Plaza', LEVELS['plazas'])
    if layers['piers']:
        flat_layer(data["piers"], xf, "Piers", coll["Piers"], 'Plaza', LEVELS['piers'],
                   prism_bottom=WATER_LEVEL - 1.0, outward=True)
    if layers['roads']:
        build_roads(data, xf, coll)
    if layers['buildings']:
        build_buildings(data, xf, coll["Buildings"], stats)
    if layers['walls']:
        build_walls(data, xf, coll["City_Walls"])
    return stats


# ---------------------------------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------------------------------
def widen_viewport_clip(size):
    """Default clip distance would cut a city of this size; no-op when running without a UI."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            space.clip_end = max(space.clip_end, size)
    except Exception:
        pass


def parse_cli():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="stadtkarte_blender", description="Build a Stadtkarte city in Blender.")
    ap.add_argument("--json", help="city file (overrides JSON_PATH)")
    ap.add_argument("--mode", choices=("2D", "3D"), help="overrides OUTPUT_MODE")
    ap.add_argument("--seed", type=int, help="overrides RANDOM_SEED")
    ap.add_argument("--save", help="save the result as this .blend file")
    return ap.parse_args(argv)


def main():
    global JSON_PATH, OUTPUT_MODE, RANDOM_SEED
    args = parse_cli()
    JSON_PATH = args.json or JSON_PATH
    OUTPUT_MODE = args.mode or OUTPUT_MODE
    RANDOM_SEED = RANDOM_SEED if args.seed is None else args.seed
    if OUTPUT_MODE not in ('2D', '3D'):
        raise ValueError(f"OUTPUT_MODE must be '2D' or '3D', not {OUTPUT_MODE!r}")

    data = load_city(JSON_PATH)
    xf = Transform(data["meta"])
    root_name = safe_name(f"{data['meta']['name']}_{OUTPUT_MODE}")
    if REPLACE_PREVIOUS:
        remove_collection_tree(root_name)
    root = new_collection(root_name, bpy.context.scene.collection)

    stats = build_2d(data, xf, root) if OUTPUT_MODE == '2D' else build_3d(data, xf, root)

    widen_viewport_clip(data["meta"]["map_size"] * xf.k * 4)
    print(f"[stadtkarte] {data['meta']['name']} -> collection '{root_name}' ({OUTPUT_MODE})")
    for key, value in stats.items():
        print(f"[stadtkarte]   {key}: {value}")
    if args.save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.save))
        print(f"[stadtkarte] saved {os.path.abspath(args.save)}")
    return root


if __name__ == "__main__":
    main()
