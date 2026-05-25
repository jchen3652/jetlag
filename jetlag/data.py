"""Data loading and basic geospatial utilities for the Seattle Jet Lag notebook.

Uses the reference_data.kmz (OSM-adapted transit data) for simplicity.
No GTFS parsing required.

Primary entry point: load_reference_kmz()
"""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
import zipfile
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import pandas as pd
import osmnx as ox
from shapely.geometry import Point, LineString
from shapely.ops import unary_union

# ----------------------------- CONFIG -----------------------------
def _find_kmz() -> Path:
    """Robustly locate reference_data.kmz no matter where the notebook is run from."""
    candidates = []

    # 1. Relative to this package (best when installed editable)
    try:
        here = Path(__file__).resolve()
        candidates.append(here.parent.parent / "reference_data.kmz")
    except NameError:
        pass

    # 2. Current working directory
    candidates.append(Path.cwd() / "reference_data.kmz")

    # 3. One level up (very common when running from notebooks/ folder)
    candidates.append(Path.cwd().parent / "reference_data.kmz")

    # 4. Two levels up (defensive)
    candidates.append(Path.cwd().parent.parent / "reference_data.kmz")

    for p in candidates:
        if p.exists():
            return p.resolve()

    # Last resort: walk up from cwd looking for the file
    for parent in Path.cwd().parents:
        candidate = parent / "reference_data.kmz"
        if candidate.exists():
            return candidate.resolve()

    raise FileNotFoundError(
        "Could not find reference_data.kmz. "
        "Make sure you are running from the project root or the notebooks/ folder, "
        "or run `uv pip install -e .` after setting up pyproject.toml."
    )

KMZ_PATH = _find_kmz()

# The folders in the KMZ that contain our candidate stops (Points) and some route lines
STOP_FOLDERS = {
    "RapidRide (B, C, D, E, G, H)",
    "1 Line",
    "2 Line (Extension Only)",
    "Seattle Center Monorail",
}

# Folders that contain useful route polylines (LineStrings)
ROUTE_FOLDERS = {
    "RapidRide (B, C, D, E, G, H)",
    "1 Line",
    "2 Line (Extension Only)",
    "Seattle Center Monorail",
    "(Reference) Frequent Transit Network",
}

# Scope cities (matches the original notebook + Mercer Island)
SCOPE_CITIES = [
    "Seattle, Washington, USA",
    "Bellevue, Washington, USA",
    "Redmond, Washington, USA",
    "Mercer Island, Washington, USA",
]

# Simple heuristics to turn a KMZ placemark name into (mode, route_label)
RAPIDRIDE_PREFIX = "RapidRide "
LINK_PREFIXES = ("1 Line", "2 Line")


def _parse_line_info(name: str) -> dict:
    """Return dict with mode, route, display_name from a placemark name."""
    name = name.strip()
    if name.startswith(RAPIDRIDE_PREFIX):
        # e.g. "RapidRide E Line: Aurora Village TC"
        rest = name[len(RAPIDRIDE_PREFIX):]
        letter = rest.split()[0] if rest else "?"
        return {
            "mode": "RapidRide",
            "route": letter,
            "display_name": name,
        }
    if name.startswith(LINK_PREFIXES):
        # e.g. "1 Line: Lynnwood" or "2 Line: Bellevue Downtown"
        line = name.split(":")[0].strip()
        return {
            "mode": "Link",
            "route": line,           # "1 Line" or "2 Line"
            "display_name": name,
        }
    if "Monorail" in name:
        return {
            "mode": "Monorail",
            "route": "Monorail",
            "display_name": name,
        }
    # Frequent network segments etc.
    return {
        "mode": "Other",
        "route": name[:40],
        "display_name": name,
    }


def _get_text(el, tag, ns):
    child = el.find(tag, ns)
    return child.text.strip() if child is not None and child.text else ""


def _get_geom_type(pm, ns):
    for g in ("Point", "LineString", "Polygon"):
        if pm.find(f".//{g}", ns) is not None:
            return g
    return "Other"


def _extract_coordinates(geom_el, ns):
    """Return list of (lon, lat) tuples from a <coordinates> element (KML format)."""
    coords_el = geom_el.find(".//coordinates", ns)
    if coords_el is None or not coords_el.text:
        return []
    raw = coords_el.text.strip()
    pts = []
    for line in raw.split():
        parts = line.split(",")
        if len(parts) >= 2:
            try:
                lon = float(parts[0])
                lat = float(parts[1])
                pts.append((lon, lat))
            except ValueError:
                pass
    return pts


@lru_cache(maxsize=1)
def get_scope_polygon():
    """Cached union of the four city boundaries (same logic as original notebook)."""
    print("Fetching city boundary polygons via osmnx/Nominatim (4 cities incl. Mercer Island)...")
    gdf = ox.geocode_to_gdf(SCOPE_CITIES)
    union = unary_union(gdf.geometry.tolist())
    print(f"  Union of {len(gdf)} city polygons ready.")
    return union


def filter_to_scope(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Keep only rows whose geometry is inside the 4-city scope."""
    if gdf.empty:
        return gdf
    poly = get_scope_polygon()
    mask = gdf.within(poly)
    return gdf[mask].copy()


def compute_walkshed(
    gdf: gpd.GeoDataFrame, radius_m: float = 402.336
) -> "shapely.geometry.base.BaseGeometry":
    """Union of ¼-mile buffers around all points (Web Mercator for accuracy)."""
    if len(gdf) == 0:
        return Point(0, 0).buffer(0)
    pts = gpd.points_from_xy(gdf.geometry.x, gdf.geometry.y)
    pts_gdf = gpd.GeoDataFrame(geometry=pts, crs="EPSG:4326")
    proj = pts_gdf.to_crs(3857)
    buf = proj.buffer(radius_m)
    union_proj = buf.union_all() if hasattr(buf, "union_all") else unary_union(buf)
    return gpd.GeoSeries([union_proj], crs=3857).to_crs(4326).iloc[0]






def load_reference_kmz() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Load stops and route segments from reference_data.kmz.

    Extracts:
    - All <Point> placemarks from the RapidRide, 1 Line, 2 Line, and Monorail folders
      (these represent the actual transit stops).
    - LineStrings for route visualization where available.

    Returns two GeoDataFrames:
      - stops: with columns stop_name, mode, route, folder, geometry (Point)
      - routes: LineString geometries for drawing the lines on the map
    """
    if not KMZ_PATH.exists():
        raise FileNotFoundError(f"KMZ not found: {KMZ_PATH}")

    NS = {"kml": "http://www.opengis.net/kml/2.2"}

    with zipfile.ZipFile(KMZ_PATH) as z:
        kml_bytes = z.read("doc.kml")

    with tempfile.TemporaryDirectory() as tmp:
        kml_path = Path(tmp) / "doc.kml"
        kml_path.write_bytes(kml_bytes)
        tree = ET.parse(kml_path)
        root = tree.getroot()

    target_folders = {
        "RapidRide (B, C, D, E, G, H)": "RapidRide",
        "1 Line": "Link",
        "2 Line (Extension Only)": "Link",
        "Seattle Center Monorail": "Monorail",
    }

    stops_rows = []
    routes_rows = []

    for folder in root.findall(".//kml:Folder", NS):
        fname_el = folder.find("kml:name", NS)
        if fname_el is None:
            continue
        fname = fname_el.text.strip()
        if fname not in target_folders:
            continue
        mode = target_folders[fname]

        for pm in folder.findall(".//kml:Placemark", NS):
            name_el = pm.find("kml:name", NS)
            name = name_el.text.strip() if name_el is not None and name_el.text else "(unnamed)"
            # Clean XML escapes
            name = name.replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<")

            # Extract Point stops
            point = pm.find(".//kml:Point", NS)
            if point is not None:
                coords_el = point.find("kml:coordinates", NS)
                if coords_el is not None and coords_el.text:
                    for coord_str in coords_el.text.strip().split():
                        parts = coord_str.split(",")
                        if len(parts) >= 2:
                            try:
                                lon, lat = float(parts[0]), float(parts[1])
                                stops_rows.append({
                                    "stop_name": name,
                                    "mode": mode,
                                    "route": _infer_route(name, fname),
                                    "folder": fname,
                                    "geometry": Point(lon, lat),
                                })
                                break  # one point per placemark is enough for stops
                            except ValueError:
                                continue

            # Extract LineStrings for route visualization
            ls = pm.find(".//kml:LineString", NS)
            if ls is not None:
                coords_el = ls.find("kml:coordinates", NS)
                if coords_el is not None and coords_el.text:
                    coords = []
                    for coord_str in coords_el.text.strip().split():
                        parts = coord_str.split(",")
                        if len(parts) >= 2:
                            try:
                                coords.append((float(parts[0]), float(parts[1])))
                            except ValueError:
                                continue
                    if len(coords) >= 2:
                        routes_rows.append({
                            "name": name,
                            "mode": mode,
                            "route": _infer_route(name, fname),
                            "folder": fname,
                            "geometry": LineString(coords),
                        })

    stops = gpd.GeoDataFrame(stops_rows, geometry="geometry", crs="EPSG:4326")
    routes = gpd.GeoDataFrame(routes_rows, geometry="geometry", crs="EPSG:4326")

    # Light deduplication (some platforms appear twice)
    if len(stops) > 0:
        stops["lat_rounded"] = stops.geometry.y.round(5)
        stops["lon_rounded"] = stops.geometry.x.round(5)
        stops = stops.drop_duplicates(subset=["stop_name", "lat_rounded", "lon_rounded"])
        stops = stops.drop(columns=["lat_rounded", "lon_rounded"]).reset_index(drop=True)

    print(f"Loaded from KMZ: {len(stops)} stops, {len(routes)} route segments")
    return stops, routes


def _infer_route(name: str, folder: str) -> str:
    """Best-effort route label from placemark name or folder."""
    n = name.upper()
    f = folder.upper()

    # RapidRide letter detection
    if "RAPIDRIDE" in f or "RAPIDRIDE" in n:
        for letter in ["E", "D", "C", "F", "G", "H", "B"]:
            if f" {letter} " in n or f" {letter} LINE" in n or n.startswith(f"{letter} ") or n.endswith(f" {letter}"):
                return letter
        return "RapidRide"

    if "1 LINE" in n or "1 LINE" in f:
        return "1 Line"
    if "2 LINE" in n or "2 LINE" in f:
        return "2 Line"
    if "MONORAIL" in n or "MONORAIL" in f:
        return "Monorail"

    return "Other"
