#!/usr/bin/env python3
"""Fast hideable_frac: single-process segment grid + per-point cell lookup.

No multiprocessing (avoids pickle hang on large path sets).
"""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "web" / "public" / "data"
PATHS = DATA / "walkable_paths.geojson"
STOPS = DATA / "transit_stops.geojson"
OUT = DATA / "zone_hideable_scores.json"

RULE_M = 10.0 * 0.3048
SAMPLES = 20000
ZONE_M = {
    "small_medium": 0.25 * 1609.344,
    "large": 0.5 * 1609.344,
}
CELL = 40.0

HALF_WIDTH_M = {
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


def buffers(hw: str):
    half = HALF_WIDTH_M.get(str(hw), 3.0)
    return RULE_M, half + RULE_M


def build_segments(paths_m: gpd.GeoDataFrame):
    rows = []
    for geom, hw in zip(paths_m.geometry.values, paths_m["highway"].astype(str).values):
        if geom is None or geom.is_empty:
            continue
        sb, pb = buffers(hw)
        lines = [geom] if geom.geom_type == "LineString" else list(getattr(geom, "geoms", []))
        for line in lines:
            c = list(line.coords)
            for i in range(len(c) - 1):
                rows.append((c[i][0], c[i][1], c[i + 1][0], c[i + 1][1], sb, pb))
    segs = np.asarray(rows, dtype=np.float64)
    print(f"  segments: {len(segs):,}", flush=True)

    # grid of segment indices (use max buffer for cell membership)
    grid = defaultdict(list)
    for i in range(len(segs)):
        ax, ay, bx, by, sb, pb = segs[i]
        buf = pb  # practical >= strict
        x0 = int(math.floor((min(ax, bx) - buf) / CELL))
        x1 = int(math.floor((max(ax, bx) + buf) / CELL))
        y0 = int(math.floor((min(ay, by) - buf) / CELL))
        y1 = int(math.floor((max(ay, by) + buf) / CELL))
        for ix in range(x0, x1 + 1):
            for iy in range(y0, y1 + 1):
                grid[(ix, iy)].append(i)

    # convert lists to arrays for faster iteration
    grid_arr = {k: np.asarray(v, dtype=np.int32) for k, v in grid.items()}
    print(f"  grid cells: {len(grid_arr):,}", flush=True)
    return segs, grid_arr


def point_near(px, py, segs, grid, mode: str) -> bool:
    """True if point within buffer of any segment in its grid cell."""
    ix = int(math.floor(px / CELL))
    iy = int(math.floor(py / CELL))
    idxs = grid.get((ix, iy))
    if idxs is None or len(idxs) == 0:
        return False
    buf_col = 4 if mode == "strict" else 5
    for j in idxs:
        ax, ay, bx, by = segs[j, 0], segs[j, 1], segs[j, 2], segs[j, 3]
        buf = segs[j, buf_col]
        if px < min(ax, bx) - buf or px > max(ax, bx) + buf:
            continue
        if py < min(ay, by) - buf or py > max(ay, by) + buf:
            continue
        dx = bx - ax
        dy = by - ay
        len2 = dx * dx + dy * dy
        if len2 == 0.0:
            d2 = (px - ax) * (px - ax) + (py - ay) * (py - ay)
        else:
            t = ((px - ax) * dx + (py - ay) * dy) / len2
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            qx = ax + t * dx
            qy = ay + t * dy
            d2 = (px - qx) * (px - qx) + (py - qy) * (py - qy)
        if d2 <= buf * buf:
            return True
    return False


def sample_frac(cx, cy, radius, segs, grid, n, seed, mode: str) -> float:
    rng = np.random.default_rng(seed)
    rr = radius * np.sqrt(rng.random(n))
    th = rng.random(n) * (2 * math.pi)
    xs = cx + rr * np.cos(th)
    ys = cy + rr * np.sin(th)
    hits = 0
    for i in range(n):
        if point_near(xs[i], ys[i], segs, grid, mode):
            hits += 1
    return hits / n


def main():
    t_all = time.time()
    print(f"SAMPLES={SAMPLES}", flush=True)
    print("Loading…", flush=True)
    paths = gpd.read_file(PATHS).to_crs(3857)
    stops = gpd.read_file(STOPS).to_crs(3857).reset_index(drop=True)
    stops_ll = stops.to_crs(4326)
    if "highway" not in paths.columns:
        paths["highway"] = "unknown"
    print(f"  paths={len(paths):,} stops={len(stops)}", flush=True)

    print("Building segment grid…", flush=True)
    t_grid = time.time()
    segs, grid = build_segments(paths)
    print(f"  grid ready in {time.time()-t_grid:.1f}s", flush=True)

    results = []
    t0 = time.time()
    for i, row in stops.iterrows():
        pt = row.geometry
        name = str(row.get("stop_name") or "Unnamed")
        mode = str(row.get("mode") or "")
        route = str(row.get("route") or "")
        ll = stops_ll.geometry.iloc[i]
        rec = {
            "stop_name": name,
            "mode": mode,
            "route": route,
            "lat": float(ll.y),
            "lng": float(ll.x),
            "zones": {},
        }
        for zkey, radius in ZONE_M.items():
            zone_area = math.pi * radius * radius
            seed = abs(hash((name, mode, zkey))) % (2**32)
            zrec = {
                "radius_m": radius,
                "zone_area_m2": zone_area,
                "n_samples": SAMPLES,
            }
            for bmode in ("strict", "practical"):
                # different seed per mode so independent; share samples for speed:
                # recompute once... actually share points across modes
                pass
            # generate points once, test both modes
            rng = np.random.default_rng(seed)
            rr = radius * np.sqrt(rng.random(SAMPLES))
            th = rng.random(SAMPLES) * (2 * math.pi)
            xs = pt.x + rr * np.cos(th)
            ys = pt.y + rr * np.sin(th)
            for bmode in ("strict", "practical"):
                hits = 0
                for k in range(SAMPLES):
                    if point_near(xs[k], ys[k], segs, grid, bmode):
                        hits += 1
                frac = hits / SAMPLES
                zrec[bmode] = {
                    "hideable_frac": float(frac),
                    "hideable_area_m2": float(frac * zone_area),
                    "sample_hits": hits,
                }
            rec["zones"][zkey] = zrec
        results.append(rec)
        if (i + 1) % 10 == 0 or i == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(stops) - i - 1) / rate
            print(
                f"  scored {i+1}/{len(stops)} ({elapsed:.0f}s, {rate:.2f}/s, ETA {eta:.0f}s)",
                flush=True,
            )

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
        "n_stops": len(results),
        "n_segments": int(len(segs)),
        "includes_all_roads": True,
        "engine": "single-process per-point grid",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    OUT.write_text(json.dumps({"meta": meta, "stops": results}))
    print(f"Wrote {OUT} ({OUT.stat().st_size/1e6:.2f} MB) in {time.time()-t_all:.1f}s", flush=True)

    ranked = sorted(
        results,
        key=lambda s: s["zones"]["small_medium"]["practical"]["hideable_frac"],
        reverse=True,
    )
    print("\nTop 10 practical (¼ mi, n=20k):")
    for j, s in enumerate(ranked[:10], 1):
        f = s["zones"]["small_medium"]["practical"]["hideable_frac"]
        print(f"  {j:2}. {s['stop_name'][:42]:42s} {f*100:5.1f}%")
    print("Bottom 5:")
    for s in ranked[-5:]:
        f = s["zones"]["small_medium"]["practical"]["hideable_frac"]
        print(f"      {s['stop_name'][:42]:42s} {f*100:5.1f}%")


if __name__ == "__main__":
    main()
