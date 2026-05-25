"""Seattle-only parks and attractions dataset from OpenStreetMap.

Replicates the POI categories and query patterns from
https://github.com/taibeled/JetLagHideAndSeek (overpass.ts + constants)
but limited to the same 4-city scope used by the Jet Lag Seattle strategy work
(Seattle + Bellevue + Redmond + Mercer Island). No transit data.

Primary entry points:
    load_or_fetch_attractions()   # main for notebooks
    fetch_seattle_attractions()
    load_seattle_attractions()

The saved GeoJSON at data/seattle_attractions.geojson is the standing database.
Point me (Grok) at it in this chat when you want to ask questions about the data.

Category checkboxes and interactive maps live in the companion notebook.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point
from tqdm import tqdm

from .data import SCOPE_CITIES, get_scope_polygon

# ---------------------------- CONSTANTS ----------------------------

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
HEADERS = {
    "User-Agent": "jetlag-seattle-attractions/0.1 (Jet Lag Hide & Seek strategy tools)"
}

# Exact categories from the referenced JetLagHideAndSeek implementation
# (the "nearest X" features the game supports for questions).
CATEGORY_DEFINITIONS: dict[str, dict[str, Any]] = {
    "Parks": {"leisure": ["park", "garden"]},
    "Museums": {"tourism": "museum"},
    "Zoos": {"tourism": "zoo"},
    "Aquariums": {"tourism": "aquarium"},
    "Golf Courses": {"leisure": "golf_course"},
    "Cinemas": {"amenity": "cinema"},
    "Libraries": {"amenity": "library"},
    "Hospitals": {"amenity": "hospital"},
    "Foreign Consulates": {"diplomatic": True},
}

CATEGORY_COLORS: dict[str, str] = {
    "Parks": "#2E8B57",          # sea green
    "Museums": "#8B4513",        # saddle brown
    "Zoos": "#556B2F",           # dark olive
    "Aquariums": "#4682B4",      # steel blue
    "Golf Courses": "#006400",   # dark green
    "Cinemas": "#4B0082",        # indigo
    "Libraries": "#DAA520",      # goldenrod
    "Hospitals": "#DC143C",      # crimson
    "Foreign Consulates": "#483D8B",  # dark slate blue
}

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
DATA_DIR = PROJECT_ROOT / "data"
ATTRACTIONS_PATH = DATA_DIR / "seattle_attractions.geojson"
DUCKDB_PATH = DATA_DIR / "seattle_attractions.duckdb"


# ---------------------------- HELPERS ----------------------------

def _build_tag_filter(tag_dict: dict[str, Any]) -> str:
    """Build Overpass tag filter string. Supports lists for regex alternation.
    Special: value True or None means 'key present' (e.g. for diplomatic key)."""
    parts: list[str] = []
    for k, v in tag_dict.items():
        if v is True or v is None:
            parts.append(f'["{k}"]')  # key presence (any value)
        elif isinstance(v, (list, tuple, set)):
            alt = "|".join(str(x) for x in v)
            parts.append(f'["{k}"~"^({alt})$"]')
        else:
            parts.append(f'["{k}"="{v}"]')
    return "".join(parts)


def _parse_elements(elements: list[dict], category: str) -> list[dict]:
    """Turn Overpass elements (with center or node lat/lon) into row dicts. Only named features."""
    rows: list[dict] = []
    for el in elements:
        tags = el.get("tags", {}) or {}
        name = tags.get("name") or tags.get("name:en") or tags.get("official_name")
        if not name:
            continue

        if "center" in el:
            lat = float(el["center"]["lat"])
            lon = float(el["center"]["lon"])
        elif el.get("type") == "node" and "lat" in el and "lon" in el:
            lat = float(el["lat"])
            lon = float(el["lon"])
        else:
            continue

        rows.append(
            {
                "osm_type": el["type"],
                "osm_id": el["id"],
                "name": name,
                "category": category,
                "lat": lat,
                "lon": lon,
                "geometry": Point(lon, lat),
            }
        )
    return rows


def _query_overpass(ql: str, timeout: int = 180) -> list[dict]:
    """POST to Overpass and return elements list. Basic error handling + small backoff."""
    resp = requests.post(
        OVERPASS_URL,
        data=ql.encode("utf-8"),
        headers=HEADERS,
        timeout=timeout,
    )
    if resp.status_code == 429:
        time.sleep(5)
        resp = requests.post(OVERPASS_URL, data=ql.encode("utf-8"), headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.json().get("elements", [])


# ---------------------------- CORE API ----------------------------

def fetch_seattle_attractions(
    force: bool = False,
    verbose: bool = True,
) -> gpd.GeoDataFrame:
    """Fetch fresh data from Overpass API for all categories, clip to 4-city scope.

    Returns a GeoDataFrame with columns:
        name, category, osm_type, osm_id, lat, lon, geometry (Point)
    Only features with a name are kept. Duplicates removed.

    This is a network call. Use load_or_fetch_attractions() in notebooks for daily use.
    """
    if not force and ATTRACTIONS_PATH.exists():
        if verbose:
            print(f"Existing {ATTRACTIONS_PATH} found — loading (pass force=True to re-fetch).")
        return load_seattle_attractions()

    scope = get_scope_polygon()
    minx, miny, maxx, maxy = scope.bounds
    # Overpass bbox order: (south, west, north, east)
    obbox = f"{miny:.5f},{minx:.5f},{maxy:.5f},{maxx:.5f}"

    all_rows: list[dict] = []

    # Regular categories
    for i, (cat, tag_dict) in enumerate(tqdm(
        list(CATEGORY_DEFINITIONS.items()), desc="Fetching categories", disable=not verbose
    )):
        tag_f = _build_tag_filter(tag_dict)
        ql = f"""[out:json][timeout:120];
(
  node{tag_f}({obbox});
  way{tag_f}({obbox});
  relation{tag_f}({obbox});
);
out center;
"""
        try:
            els = _query_overpass(ql)
            rows = _parse_elements(els, cat)
            all_rows.extend(rows)
            if verbose:
                print(f"  {cat}: {len(rows)}")
        except Exception as e:
            if verbose:
                print(f"  WARN {cat}: {e}")
        if i < len(CATEGORY_DEFINITIONS) - 1:
            time.sleep(2)  # Be nice to Overpass API; prevents 504 timeouts on long sessions

    if not all_rows:
        raise RuntimeError("No attractions fetched. Check network or Overpass availability.")

    gdf = gpd.GeoDataFrame(all_rows, geometry="geometry", crs="EPSG:4326")

    # Strict spatial filter to our 4-city scope (centers can occasionally sit just outside)
    gdf = gdf[gdf.within(scope)].copy()

    # Deduplicate (same OSM object shouldn't appear twice)
    before = len(gdf)
    gdf = gdf.drop_duplicates(subset=["osm_type", "osm_id"]).reset_index(drop=True)
    if verbose and len(gdf) != before:
        print(f"  Deduplicated: {before} → {len(gdf)}")

    # Nice ordering for the file and for easy reading by Grok in chat
    gdf = gdf.sort_values(["category", "name"]).reset_index(drop=True)

    if verbose:
        print(f"\nTotal named attractions inside scope: {len(gdf)}")
        print(gdf["category"].value_counts().to_string())

    return gdf


def save_attractions(
    gdf: gpd.GeoDataFrame,
    path: Path | None = None,
    also_duckdb: bool = False,
) -> Path:
    """Persist the attractions GeoDataFrame as GeoJSON + sidecar metadata.

    The GeoJSON is the primary standing database.
    """
    if path is None:
        path = ATTRACTIONS_PATH

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Write GeoJSON. Prefer pyogrio when installed (cleaner/faster), otherwise let geopandas choose.
    try:
        gdf.to_file(path, driver="GeoJSON", engine="pyogrio", encoding="utf-8")
    except Exception:
        gdf.to_file(path, driver="GeoJSON", encoding="utf-8")  # fallback (usually Fiona)

    # Metadata for context (human + future Grok chats)
    meta = {
        "count": int(len(gdf)),
        "categories": {k: int(v) for k, v in gdf["category"].value_counts().to_dict().items()},
        "scope_cities": SCOPE_CITIES,
        "crs": "EPSG:4326",
        "fetched_at": pd.Timestamp.utcnow().isoformat(),
        "source": "OpenStreetMap (Overpass API) — modeled on taibeled/JetLagHideAndSeek",
        "columns": list(gdf.columns),
    }
    meta_path = path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    if also_duckdb:
        _export_duckdb(gdf, DUCKDB_PATH)

    print(f"Saved {len(gdf)} attractions → {path}")
    print(f"Metadata → {meta_path}")
    return path


def _export_duckdb(gdf: gpd.GeoDataFrame, db_path: Path) -> None:
    """Optional: export to DuckDB with spatial extension for advanced spatial SQL queries."""
    try:
        import duckdb
    except ImportError:
        print("duckdb not installed — skipping DuckDB export. Run `uv pip install duckdb` to enable.")
        return

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute("INSTALL spatial; LOAD spatial;")

    # Create table from the gdf via pandas + attach geometry
    pdf = pd.DataFrame(gdf.drop(columns="geometry"))
    pdf["geometry"] = gdf.geometry.apply(lambda g: g.wkt)
    con.register("src", pdf)
    con.execute(
        """
        CREATE OR REPLACE TABLE attractions AS
        SELECT *, ST_GeomFromText(geometry) AS geom
        FROM src
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_cat ON attractions(category);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_name ON attractions(name);")
    count = con.execute("SELECT count(*) FROM attractions").fetchone()[0]
    print(f"DuckDB written → {db_path} ({count} rows, spatial enabled)")
    con.close()


def load_seattle_attractions(path: Path | None = None) -> gpd.GeoDataFrame:
    """Load the persisted standing database (GeoJSON)."""
    if path is None:
        path = ATTRACTIONS_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run fetch_seattle_attractions(force=True) or load_or_fetch_attractions() first."
        )
    try:
        gdf = gpd.read_file(path, engine="pyogrio")
    except Exception:
        gdf = gpd.read_file(path)  # fallback (Fiona or whatever is available)
    # Ensure proper types
    if "osm_id" in gdf.columns:
        gdf["osm_id"] = gdf["osm_id"].astype("int64")
    return gdf


def load_or_fetch_attractions(
    force: bool = False,
    verbose: bool = True,
    also_duckdb: bool = False,
) -> gpd.GeoDataFrame:
    """Convenience for notebooks: load from disk if present, else fetch + save.

    This is the recommended function for the attractions notebook.
    """
    if not force and ATTRACTIONS_PATH.exists():
        if verbose:
            print(f"Loading cached attractions from {ATTRACTIONS_PATH}")
        gdf = load_seattle_attractions()
        if verbose:
            print(f"  {len(gdf)} attractions, {gdf.category.nunique()} categories")
        return gdf

    gdf = fetch_seattle_attractions(force=True, verbose=verbose)
    save_attractions(gdf, also_duckdb=also_duckdb)
    return gdf


def get_attractions_summary(gdf: gpd.GeoDataFrame | None = None) -> pd.DataFrame:
    """Quick per-category counts + sample names (handy reference)."""
    if gdf is None:
        gdf = load_seattle_attractions()
    summary = (
        gdf.groupby("category")
        .agg(
            count=("name", "count"),
            sample_names=("name", lambda s: ", ".join(s.head(3).tolist())),
        )
        .reset_index()
        .sort_values("count", ascending=False)
    )
    return summary


# ---------------------------- EXPORTS ----------------------------

__all__ = [
    "fetch_seattle_attractions",
    "load_seattle_attractions",
    "load_or_fetch_attractions",
    "save_attractions",
    "get_attractions_summary",
    "CATEGORY_DEFINITIONS",
    "CATEGORY_COLORS",
    "ATTRACTIONS_PATH",
    "DUCKDB_PATH",
    "SCOPE_CITIES",
]
