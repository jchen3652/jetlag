#!/usr/bin/env python3
"""Rebuild walkable_paths with ALL road/path types (no type thinning) + fast fraction scores.

Uses cached Overpass JSON when present. Scoring is Monte Carlo only (hideable_frac),
vectorized segment tests + multiprocessing.
"""

from __future__ import annotations

import json
import math
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point, box
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "web" / "public" / "data"
CACHE = ROOT / "cache"
STOPS = DATA / "transit_stops.geojson"
PATHS_OUT = DATA / "walkable_paths.geojson"
PATHS_META = DATA / "walkable_paths.meta.json"
SCORES_OUT = DATA / "zone_hideable_scores.json"
OSM_CACHE = CACHE / "33a9ca6b91ac91761455bb341e2542bf2265913c.json"

RULE_M = 10.0 * 0.3048
SAMPLES = 20000
ZONE_M = {
    "small_medium": 0.25 * 1609.344,
    "large": 0.5 * 1609.344,
}

# All OSM highway types treated as marked roads/paths for walking directions.
# Exclude pure motorways (not walkable). Include trunk only if foot allowed later via tags.
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
    "trunk",  # sometimes has sidewalks; buffer will be wide
    "trunk_link",
    "service",
    "road",
    "track",
    "cycleway",
    "bridleway",
    "corridor",
    "platform",
    "crossing",
    "busway",
    "construction",  # skip? keep out
}

# remove construction from set
WALK_HIGHWAYS.discard("construction")

HALF_WIDTH_M = {
    "motorway": 12.0,
    "trunk": 10.0,
    "trunk_link": 7.0,
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
    "busway": 4.0,
}


def buf_pair(highway: str):
    hw = str(highway)
    half = HALF_WIDTH_M.get(hw, 3.0)
    return RULE_M, half + RULE_M  # strict, practical


# ---------------------------------------------------------------------------
# Build paths from OSM cache
# ---------------------------------------------------------------------------
def parse_osm_cache(path: Path) -> gpd.GeoDataFrame:
    print(f"Parsing {path.name} ({path.stat().st_size/1e6:.1f} MB)…", flush=True)
    data = json.loads(path.read_text())
    nodes = {}
    ways = []
    for el in data.get("elements", []):
        t = el.get("type")
        if t == "node":
            nodes[el["id"]] = (el["lon"], el["lat"])
        elif t == "way":
            ways.append(el)
    print(f"  nodes={len(nodes):,} ways={len(ways):,}", flush=True)

    rows = []
    skip = 0
    for w in ways:
        tags = w.get("tags") or {}
        hw = tags.get("highway")
        if hw not in WALK_HIGHWAYS:
            skip += 1
            continue
        if tags.get("access") == "private" or tags.get("foot") == "no":
            continue
        coords = [nodes[nid] for nid in (w.get("nodes") or []) if nid in nodes]
        if len(coords) < 2:
            continue
        try:
            geom = LineString(coords)
        except Exception:
            continue
        if geom.is_empty:
            continue
        rows.append({"highway": hw, "osm_id": w.get("id"), "geometry": geom})

    print(f"  kept={len(rows):,} skipped_nonwalk={skip:,}", flush=True)
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    # light simplify for size, keep all types
    m = gdf.to_crs(3857)
    m["geometry"] = m.geometry.simplify(3.0, preserve_topology=True)
    m = m[~m.geometry.is_empty & m.geometry.notna()]
    m = m[m.geometry.length >= 2.0]
    m = m.explode(index_parts=False).reset_index(drop=True)
    out = m.to_crs(4326)
    print(f"  after simplify: {len(out):,}", flush=True)
    return out


def write_paths(gdf: gpd.GeoDataFrame):
    gdf[["highway", "geometry"]].to_file(PATHS_OUT, driver="GeoJSON")
    counts = gdf["highway"].value_counts().to_dict()
    meta = {
        "n_features": len(gdf),
        "size_mb": PATHS_OUT.stat().st_size / 1e6,
        "highway_counts": counts,
        "note": "All walk-relevant roads/paths; no per-type thinning",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    PATHS_META.write_text(json.dumps(meta, indent=2))
    print(f"Wrote {PATHS_OUT} ({meta['size_mb']:.1f} MB, {len(gdf):,} feats)", flush=True)
    print("  highway mix:", flush=True)
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:20]:
        print(f"    {k:16s} {v}", flush=True)


# ---------------------------------------------------------------------------
# Fast scoring — worker globals set via initializer
# ---------------------------------------------------------------------------
_G = {}


def _init_worker(geoms, highways, samples, zones):
    _G["geoms"] = geoms
    _G["highways"] = highways
    _G["tree"] = STRtree(geoms)
    _G["samples"] = samples
    _G["zones"] = zones


def _local_segments(idxs):
    segs = []  # list then array: ax,ay,bx,by,strict,prac
    geoms = _G["geoms"]
    highways = _G["highways"]
    for j in idxs:
        geom = geoms[j]
        if geom is None or geom.is_empty:
            continue
        sb, pb = buf_pair(highways[j])
        lines = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
        for line in lines:
            c = list(line.coords)
            for i in range(len(c) - 1):
                segs.append((c[i][0], c[i][1], c[i + 1][0], c[i + 1][1], sb, pb))
    if not segs:
        return np.empty((0, 6), dtype=np.float64)
    return np.asarray(segs, dtype=np.float64)


def _hit_frac(xs, ys, segs: np.ndarray, mode: str) -> float:
    """Vectorized-ish: for each point, test against segments with AABB prefilter."""
    if segs.size == 0:
        return 0.0
    n = len(xs)
    hits = 0
    ax, ay, bx, by = segs[:, 0], segs[:, 1], segs[:, 2], segs[:, 3]
    buf = segs[:, 4] if mode == "strict" else segs[:, 5]
    minx = np.minimum(ax, bx) - buf
    maxx = np.maximum(ax, bx) + buf
    miny = np.minimum(ay, by) - buf
    maxy = np.maximum(ay, by) + buf
    buf2 = buf * buf

    for i in range(n):
        px, py = xs[i], ys[i]
        m = (px >= minx) & (px <= maxx) & (py >= miny) & (py <= maxy)
        if not np.any(m):
            continue
        sax, say, sbx, sby = ax[m], ay[m], bx[m], by[m]
        sb2 = buf2[m]
        dx = sbx - sax
        dy = sby - say
        len2 = dx * dx + dy * dy
        # t clamped
        # avoid div0
        t = np.where(len2 > 0, ((px - sax) * dx + (py - say) * dy) / np.where(len2 > 0, len2, 1.0), 0.0)
        t = np.clip(t, 0.0, 1.0)
        qx = sax + t * dx
        qy = say + t * dy
        d2 = (px - qx) ** 2 + (py - qy) ** 2
        if np.any(d2 <= sb2):
            hits += 1
    return hits / n


def _score_stop(args):
    name, mode, route, x, y, lat, lng = args
    samples = _G["samples"]
    zones = _G["zones"]
    tree = _G["tree"]
    pt = Point(x, y)

    rec = {
        "stop_name": name,
        "mode": mode,
        "route": route,
        "lat": lat,
        "lng": lng,
        "zones": {},
    }

    for zkey, radius in zones.items():
        zone_area = math.pi * radius * radius
        # bbox query is faster than buffer geometry for tree
        search = box(x - radius - 25, y - radius - 25, x + radius + 25, y + radius + 25)
        idxs = list(np.atleast_1d(tree.query(search)))
        segs = _local_segments(idxs)

        seed = abs(hash((name, mode, zkey))) % (2**32)
        rng = np.random.default_rng(seed)
        rr = radius * np.sqrt(rng.random(samples))
        th = rng.random(samples) * 2 * math.pi
        xs = x + rr * np.cos(th)
        ys = y + rr * np.sin(th)

        zrec = {
            "radius_m": radius,
            "zone_area_m2": zone_area,
            "n_samples": samples,
            "paths_near": len(idxs),
            "segments_near": int(segs.shape[0]),
        }
        for bmode in ("strict", "practical"):
            frac = _hit_frac(xs, ys, segs, bmode)
            zrec[bmode] = {
                "hideable_frac": float(frac),
                "hideable_area_m2": float(frac * zone_area),
                "sample_hits": int(round(frac * samples)),
            }
        rec["zones"][zkey] = zrec
    return rec


def score_all(paths_m: gpd.GeoDataFrame, stops_m: gpd.GeoDataFrame):
    print(f"Scoring {len(stops_m)} stops × {SAMPLES} samples (multiprocess)…", flush=True)
    geoms = list(paths_m.geometry.values)
    highways = list(paths_m["highway"].astype(str).values)

    # WGS84 coords for output
    stops_ll = stops_m.to_crs(4326)

    stops_m = stops_m.reset_index(drop=True)
    stops_ll = stops_m.to_crs(4326)

    jobs = []
    for i, row in stops_m.iterrows():
        g = row.geometry
        ll = stops_ll.geometry.iloc[i]
        jobs.append(
            (
                str(row.get("stop_name") or "Unnamed"),
                str(row.get("mode") or ""),
                str(row.get("route") or ""),
                float(g.x),
                float(g.y),
                float(ll.y),
                float(ll.x),
            )
        )

    results = []
    t0 = time.time()
    # workers: use CPU count - 1, cap 8
    import os

    n_workers = max(1, min(8, (os.cpu_count() or 4) - 1))
    print(f"  workers={n_workers}", flush=True)

    with ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=_init_worker,
        initargs=(geoms, highways, SAMPLES, ZONE_M),
    ) as ex:
        futs = [ex.submit(_score_stop, job) for job in jobs]
        for k, fut in enumerate(as_completed(futs), 1):
            results.append(fut.result())
            if k % 50 == 0:
                print(f"  scored {k}/{len(jobs)} ({time.time()-t0:.1f}s)", flush=True)

    # stable order by name for readability (rank client-side anyway)
    results.sort(key=lambda r: (r["mode"], r["stop_name"], r["lat"]))
    print(f"  done in {time.time()-t0:.1f}s", flush=True)
    return results


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--score-only",
        action="store_true",
        help="Skip path rebuild; re-score existing walkable_paths.geojson",
    )
    args = ap.parse_args()
    t_all = time.time()

    # 1) paths
    if args.score_only:
        if not PATHS_OUT.exists():
            raise SystemExit(f"Missing {PATHS_OUT}")
        print(f"Loading existing paths {PATHS_OUT}…", flush=True)
        paths = gpd.read_file(PATHS_OUT)
        print(f"  {len(paths)} features", flush=True)
    else:
        if not OSM_CACHE.exists():
            raise SystemExit(f"Missing OSM cache {OSM_CACHE}; run export once to populate cache")
        paths = parse_osm_cache(OSM_CACHE)
        write_paths(paths)

    # 2) score
    stops = gpd.read_file(STOPS)
    paths_m = paths.to_crs(3857)
    stops_m = stops.to_crs(3857)
    scores = score_all(paths_m, stops_m)

    meta = {
        "metric": "hideable_frac",
        "definition": "Monte Carlo fraction of zone disk within path buffer",
        "n_samples": SAMPLES,
        "rule_m": RULE_M,
        "buffer_modes": {
            "strict": "10 ft from OSM centerline",
            "practical": "highway half-width + 10 ft",
        },
        "zone_radii_m": ZONE_M,
        "n_stops": len(scores),
        "n_paths": len(paths),
        "includes_all_roads": True,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    SCORES_OUT.write_text(json.dumps({"meta": meta, "stops": scores}))
    print(f"Wrote {SCORES_OUT} ({SCORES_OUT.stat().st_size/1e6:.2f} MB)", flush=True)

    ranked = sorted(
        scores,
        key=lambda s: s["zones"]["small_medium"]["practical"]["hideable_frac"],
        reverse=True,
    )
    print("\nTop 12 practical hideable_frac (¼ mi, all roads):")
    for i, s in enumerate(ranked[:12], 1):
        f = s["zones"]["small_medium"]["practical"]["hideable_frac"]
        print(f"  {i:2}. {s['stop_name'][:42]:42s} {s['mode']:10s} {f*100:5.1f}%")
    print("\nBottom 5:")
    for s in ranked[-5:]:
        f = s["zones"]["small_medium"]["practical"]["hideable_frac"]
        print(f"      {s['stop_name'][:42]:42s} {s['mode']:10s} {f*100:5.1f}%")

    print(f"\nTotal wall time {time.time()-t_all:.1f}s", flush=True)


if __name__ == "__main__":
    main()
