#!/usr/bin/env python3
"""Export OSM walkable path *lines* + per-station hideable-area scores.

Official rule: final hide must be within **10 feet** of a marked path/road.

OSM stores road **centerlines**, not road polygons. We model legal corridor as:

  strict:     buffer = 10 ft from centerline
  practical:  buffer = estimated half-width(highway) + 10 ft

Pipeline is intentionally light (no full osmnx graph topology):
  1. Pull highway ways via Overpass (or reuse osmnx cache JSON)
  2. Build LineStrings, simplify
  3. Score each stop: area(zone ∩ corridor) + Monte Carlo sample frac
  4. Write walkable_paths.geojson + zone_hideable_scores.json
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import requests
from shapely.geometry import LineString, MultiLineString, Point, mapping
from shapely.ops import linemerge, unary_union
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
STOPS_PATH = ROOT / "web" / "public" / "data" / "transit_stops.geojson"
OUT_DIR = ROOT / "web" / "public" / "data"
CACHE_DIR = ROOT / "cache"

RULE_FT = 10.0
RULE_M = RULE_FT * 0.3048  # 3.048 m

ZONE_M = {
    "small_medium": 0.25 * 1609.344,  # 402.336
    "large": 0.5 * 1609.344,  # 804.672
}

# Pedestrian-relevant highway values (map-app "marked path/road" proxy)
WALK_HIGHWAYS = {
    "footway",
    "path",
    "pedestrian",
    "steps",
    "living_street",
    "residential",
    "unclassified",
    "tertiary",
    "tertiary_link",
    "secondary",
    "secondary_link",
    "primary",
    "primary_link",
    "service",
    "road",
    "track",
    "cycleway",
    "bridleway",
    "corridor",
    "platform",
    "crossing",
}

HALF_WIDTH_M = {
    "primary": 8.0,
    "primary_link": 6.0,
    "secondary": 6.0,
    "secondary_link": 5.0,
    "tertiary": 5.0,
    "tertiary_link": 4.0,
    "residential": 4.0,
    "living_street": 3.0,
    "unclassified": 4.0,
    "service": 3.0,
    "road": 4.0,
    "track": 2.0,
    "pedestrian": 2.0,
    "footway": 1.0,
    "path": 1.0,
    "steps": 1.0,
    "cycleway": 1.5,
    "bridleway": 1.5,
    "corridor": 1.0,
    "platform": 2.0,
    "crossing": 1.0,
}


def buffer_m(highway: str, mode: str) -> float:
    if mode == "strict":
        return RULE_M
    return HALF_WIDTH_M.get(highway, 3.0) + RULE_M


def load_stops() -> gpd.GeoDataFrame:
    gdf = gpd.read_file(STOPS_PATH)
    if "stop_name" not in gdf.columns:
        gdf["stop_name"] = "Unnamed"
    return gdf.to_crs(4326)


def stops_bbox_pad(stops: gpd.GeoDataFrame, pad_m: float = 1000.0):
    proj = stops.to_crs(3857)
    minx, miny, maxx, maxy = proj.total_bounds
    minx -= pad_m
    miny -= pad_m
    maxx += pad_m
    maxy += pad_m
    corners = gpd.GeoSeries(
        [Point(minx, miny), Point(maxx, miny), Point(maxx, maxy), Point(minx, maxy)],
        crs=3857,
    ).to_crs(4326)
    west, south, east, north = (
        float(corners.x.min()),
        float(corners.y.min()),
        float(corners.x.max()),
        float(corners.y.max()),
    )
    return west, south, east, north


def overpass_query(west, south, east, north) -> dict:
    # highway ways only (no full relation topology) — much lighter than graph_from_bbox
    hw = "|".join(sorted(WALK_HIGHWAYS))
    q = f"""
    [out:json][timeout:180];
    (
      way["highway"~"^({hw})$"]["area"!~"yes"]["access"!~"private"]({south},{west},{north},{east});
    );
    out body;
    >;
    out skel qt;
    """
    cache_key = CACHE_DIR / "overpass_walk_ways.json"
    if cache_key.exists() and cache_key.stat().st_size > 1_000_000:
        print(f"Using cached Overpass ways: {cache_key} ({cache_key.stat().st_size/1e6:.1f} MB)")
        return json.loads(cache_key.read_text())

    print("Querying Overpass for walkable highway ways...")
    url = "https://overpass-api.de/api/interpreter"
    r = requests.post(url, data={"data": q}, timeout=300)
    r.raise_for_status()
    data = r.json()
    CACHE_DIR.mkdir(exist_ok=True)
    cache_key.write_text(json.dumps(data))
    print(f"  cached {cache_key} ({cache_key.stat().st_size/1e6:.1f} MB)")
    return data


def try_parse_osmnx_cache() -> dict | None:
    """Reuse the heavy osmnx Overpass cache if present (has way+node elements)."""
    p = CACHE_DIR / "33a9ca6b91ac91761455bb341e2542bf2265913c.json"
    if p.exists():
        print(f"Reusing osmnx Overpass cache {p.name} ({p.stat().st_size/1e6:.1f} MB)")
        return json.loads(p.read_text())
    return None


def elements_to_paths(data: dict) -> gpd.GeoDataFrame:
    nodes = {}
    ways = []
    for el in data.get("elements", []):
        if el.get("type") == "node":
            nodes[el["id"]] = (el["lon"], el["lat"])
        elif el.get("type") == "way":
            ways.append(el)

    print(f"  nodes={len(nodes):,} ways={len(ways):,}")
    rows = []
    skipped = 0
    for w in ways:
        tags = w.get("tags") or {}
        hw = tags.get("highway")
        if hw not in WALK_HIGHWAYS:
            # osmnx cache includes non-walk highways — skip
            skipped += 1
            continue
        if tags.get("access") == "private":
            continue
        if tags.get("foot") == "no":
            continue
        coords = []
        for nid in w.get("nodes") or []:
            if nid in nodes:
                coords.append(nodes[nid])
        if len(coords) < 2:
            continue
        try:
            geom = LineString(coords)
        except Exception:
            continue
        if geom.is_empty or geom.length == 0:
            continue
        rows.append({"highway": hw, "osm_id": w.get("id"), "geometry": geom})

    print(f"  walk ways kept={len(rows):,} skipped_nonwalk={skipped:,}")
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    return gdf


def simplify_paths(paths: gpd.GeoDataFrame, tol_m: float = 4.0) -> gpd.GeoDataFrame:
    print(f"Simplifying {len(paths)} lines (tol={tol_m}m)...")
    m = paths.to_crs(3857)
    m["geometry"] = m.geometry.simplify(tol_m, preserve_topology=True)
    m = m[~m.geometry.is_empty & m.geometry.notna()].copy()
    m = m.explode(index_parts=False).reset_index(drop=True)
    # drop tiny slivers
    m = m[m.geometry.length >= 2.0].copy()
    out = m.to_crs(4326)
    print(f"  after simplify: {len(out)}")
    return out


def write_paths_geojson(paths: gpd.GeoDataFrame, path: Path):
    out = paths[["highway", "geometry"]].copy()
    # optional: further thin for web if huge
    out.to_file(path, driver="GeoJSON")
    print(f"Wrote {path} ({path.stat().st_size/1e6:.1f} MB, {len(out)} features)")


def score_stops(stops: gpd.GeoDataFrame, paths: gpd.GeoDataFrame) -> list[dict]:
    """Score each stop by buffering only nearby paths (no full-network prebuffer)."""
    print("Scoring stations (lazy local buffers)...")
    stops_m = stops.to_crs(3857).reset_index(drop=True)
    paths_m = paths.to_crs(3857).reset_index(drop=True)

    geoms = list(paths_m.geometry.values)
    highways = list(paths_m["highway"].astype(str).values)
    tree = STRtree(geoms)

    results = []
    t0 = time.time()
    for _, row in stops_m.iterrows():
        pt = row.geometry
        name = row.get("stop_name") or "Unnamed"
        mode = row.get("mode", "")
        route = row.get("route", "")
        pt_ll = gpd.GeoSeries([pt], crs=3857).to_crs(4326).iloc[0]

        rec = {
            "stop_name": str(name),
            "mode": str(mode),
            "route": str(route) if route is not None else "",
            "lat": float(pt_ll.y),
            "lng": float(pt_ll.x),
            "zones": {},
        }

        for zkey, radius in ZONE_M.items():
            zone = pt.buffer(radius, resolution=24)
            zone_area = float(zone.area)
            # paths that could touch zone under practical buffers (~25m max add)
            search = zone.buffer(25.0)
            idxs = list(np.atleast_1d(tree.query(search)))

            def metrics(mode: str):
                if not idxs:
                    return 0.0, 0.0, 0.0
                parts = []
                for j in idxs:
                    b = geoms[j].buffer(buffer_m(highways[j], mode), resolution=2)
                    if b.intersects(zone):
                        parts.append(b)
                if not parts:
                    return 0.0, 0.0, 0.0
                corridor = unary_union(parts)
                hideable = zone.intersection(corridor)
                a = float(hideable.area)
                frac = a / zone_area if zone_area else 0.0

                n = 200
                rng = np.random.default_rng(
                    abs(hash((str(name), str(mode), zkey, mode))) % (2**32)
                )
                rr = radius * np.sqrt(rng.random(n))
                th = rng.random(n) * 2 * math.pi
                hits = 0
                for x, y in zip(pt.x + rr * np.cos(th), pt.y + rr * np.sin(th)):
                    p = Point(x, y)
                    if corridor.contains(p) or corridor.touches(p):
                        hits += 1
                return a, frac, hits / n

            s_a, s_f, s_mc = metrics("strict")
            p_a, p_f, p_mc = metrics("practical")

            rec["zones"][zkey] = {
                "radius_m": radius,
                "zone_area_m2": zone_area,
                "paths_near": len(idxs),
                "strict": {
                    "hideable_area_m2": s_a,
                    "hideable_frac": s_f,
                    "sample_hit_frac": s_mc,
                    "buffer_m": RULE_M,
                },
                "practical": {
                    "hideable_area_m2": p_a,
                    "hideable_frac": p_f,
                    "sample_hit_frac": p_mc,
                },
            }

        results.append(rec)
        if len(results) % 25 == 0:
            print(f"  scored {len(results)}/{len(stops_m)} ({time.time()-t0:.1f}s)", flush=True)

    print(f"  done {len(results)} in {time.time()-t0:.1f}s", flush=True)
    return results


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stops = load_stops()
    print(f"Stops: {len(stops)}")

    paths_path = OUT_DIR / "walkable_paths.geojson"
    scores_path = OUT_DIR / "zone_hideable_scores.json"
    raw_parquet = OUT_DIR / "_walkable_paths.parquet"

    if raw_parquet.exists():
        print(f"Loading {raw_parquet}")
        paths = gpd.read_parquet(raw_parquet)
    elif paths_path.exists() and paths_path.stat().st_size > 100_000:
        print(f"Loading existing {paths_path}")
        paths = gpd.read_file(paths_path)
    else:
        data = try_parse_osmnx_cache()
        if data is None:
            west, south, east, north = stops_bbox_pad(stops, pad_m=1000)
            data = overpass_query(west, south, east, north)
        paths = elements_to_paths(data)
        if paths.empty:
            raise SystemExit("No walkable paths parsed")
        paths = simplify_paths(paths, tol_m=4.0)
        try:
            paths.to_parquet(raw_parquet)
            print(f"Cached {raw_parquet}")
        except Exception as e:
            print(f"parquet skip: {e}")

    # Write / refresh public geojson (thin if huge for browser)
    display = paths
    if len(paths) > 60000:
        print(f"Thinning {len(paths)} paths for web display (keep denser for scoring)...")
        thin = paths.to_crs(3857)
        thin["geometry"] = thin.geometry.simplify(10.0, preserve_topology=True)
        thin = thin[thin.geometry.length >= 12].to_crs(4326)
        # Prefer footways/paths/residential for hide sampling fidelity
        priority = {
            "footway",
            "path",
            "pedestrian",
            "steps",
            "living_street",
            "residential",
            "service",
            "tertiary",
            "unclassified",
            "cycleway",
            "crossing",
            "platform",
        }
        hi = thin[thin["highway"].isin(priority)]
        lo = thin[~thin["highway"].isin(priority)]
        # Cap display size ~80k features
        if len(hi) > 80000:
            display = hi.sample(80000, random_state=0) if len(hi) > 80000 else hi
        else:
            room = 80000 - len(hi)
            display = pd.concat([hi, lo.head(room)], ignore_index=True)
        print(f"  display features: {len(display)}")
    write_paths_geojson(display, paths_path)

    # Prefer denser network for area scoring when available
    score_paths = paths
    scores = score_stops(stops, score_paths)
    meta = {
        "rule_ft": RULE_FT,
        "rule_m": RULE_M,
        "zone_radii_m": ZONE_M,
        "buffer_modes": {
            "strict": "10 ft from OSM walk-network centerline",
            "practical": "estimated road half-width + 10 ft",
        },
        "network": "OSM highway ways (walk-relevant tags), not road polygons",
        "n_stops": len(scores),
        "n_paths": int(len(paths)),
        "n_paths_display": int(len(display)),
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    scores_path.write_text(json.dumps({"meta": meta, "stops": scores}))
    print(f"Wrote {scores_path} ({scores_path.stat().st_size/1e6:.2f} MB)")
    (OUT_DIR / "walkable_paths.meta.json").write_text(json.dumps(meta, indent=2))

    ranked = sorted(
        scores,
        key=lambda s: s["zones"]["small_medium"]["practical"]["hideable_area_m2"],
        reverse=True,
    )
    print("\nTop 10 practical hideable area (¼ mi):")
    for i, s in enumerate(ranked[:10], 1):
        z = s["zones"]["small_medium"]["practical"]
        print(
            f"  {i:2}. {s['stop_name'][:40]:40s} {s['mode']:10s} "
            f"{z['hideable_area_m2']/1e4:5.2f} ha  frac={z['hideable_frac']*100:4.1f}%"
        )


if __name__ == "__main__":
    main()
