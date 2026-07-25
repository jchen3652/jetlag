#!/usr/bin/env python3
"""Precompute ONLY hideable_frac per station zone (Monte Carlo sampling).

For each stop:
  1. Query path features near the zone (STRtree on ~80k lines — cheap)
  2. Flatten only those local lines to segments
  3. Drop N random points in the zone disk; count how many are within buffer

Score = hit_frac  (and area estimate = frac * π r²)

No parks / tentacles / radar heuristics.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "web" / "public" / "data"
STOPS = DATA / "transit_stops.geojson"
PATHS = DATA / "walkable_paths.geojson"
OUT = DATA / "zone_hideable_scores.json"

RULE_M = 10.0 * 0.3048
ZONE_M = {
    "small_medium": 0.25 * 1609.344,
    "large": 0.5 * 1609.344,
}
SAMPLES = 20000  # prefer scripts/rebuild_paths_and_score.py (faster + all roads)

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


def buf_m(highway: str, mode: str) -> float:
    if mode == "strict":
        return RULE_M
    return HALF_WIDTH_M.get(str(highway), 3.0) + RULE_M


def path_to_segments(geom, strict_b: float, prac_b: float, out: list):
    if geom is None or geom.is_empty:
        return
    lines = [geom] if geom.geom_type == "LineString" else list(getattr(geom, "geoms", []))
    for line in lines:
        coords = list(line.coords)
        for i in range(len(coords) - 1):
            ax, ay = coords[i][0], coords[i][1]
            bx, by = coords[i + 1][0], coords[i + 1][1]
            out.append((ax, ay, bx, by, strict_b, prac_b))


def near_any(px: float, py: float, segs: list, mode: str) -> bool:
    for ax, ay, bx, by, sb, pb in segs:
        buf = sb if mode == "strict" else pb
        if px < min(ax, bx) - buf or px > max(ax, bx) + buf:
            continue
        if py < min(ay, by) - buf or py > max(ay, by) + buf:
            continue
        dx, dy = bx - ax, by - ay
        len2 = dx * dx + dy * dy
        if len2 == 0.0:
            d2 = (px - ax) ** 2 + (py - ay) ** 2
        else:
            t = ((px - ax) * dx + (py - ay) * dy) / len2
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            qx = ax + t * dx
            qy = ay + t * dy
            d2 = (px - qx) ** 2 + (py - qy) ** 2
        if d2 <= buf * buf:
            return True
    return False


def main():
    t_all = time.time()
    print("Loading stops…", flush=True)
    stops = gpd.read_file(STOPS).to_crs(3857).reset_index(drop=True)
    print(f"  {len(stops)} stops", flush=True)

    print("Loading paths…", flush=True)
    paths = gpd.read_file(PATHS).to_crs(3857).reset_index(drop=True)
    if "highway" not in paths.columns:
        paths["highway"] = "unknown"
    geoms = list(paths.geometry.values)
    highways = list(paths["highway"].astype(str).values)
    print(f"  {len(geoms)} path features", flush=True)

    print("STRtree on path features…", flush=True)
    tree = STRtree(geoms)

    results = []
    t0 = time.time()
    for i, row in stops.iterrows():
        pt = row.geometry
        name = str(row.get("stop_name") or "Unnamed")
        mode = str(row.get("mode") or "")
        route = str(row.get("route") or "")
        pt_ll = gpd.GeoSeries([pt], crs=3857).to_crs(4326).iloc[0]

        rec = {
            "stop_name": name,
            "mode": mode,
            "route": route,
            "lat": float(pt_ll.y),
            "lng": float(pt_ll.x),
            "zones": {},
        }

        for zkey, radius in ZONE_M.items():
            zone_area = math.pi * radius * radius
            search = pt.buffer(radius + 25.0, resolution=6)
            idxs = list(np.atleast_1d(tree.query(search)))

            # Local segments only
            segs = []
            for j in idxs:
                path_to_segments(geoms[j], buf_m(highways[j], "strict"), buf_m(highways[j], "practical"), segs)

            seed = abs(hash((name, mode, zkey))) % (2**32)
            rng = np.random.default_rng(seed)
            rr = radius * np.sqrt(rng.random(SAMPLES))
            th = rng.random(SAMPLES) * 2 * math.pi
            xs = pt.x + rr * np.cos(th)
            ys = pt.y + rr * np.sin(th)

            zrec = {
                "radius_m": radius,
                "zone_area_m2": zone_area,
                "n_samples": SAMPLES,
                "paths_near": len(idxs),
                "segments_near": len(segs),
            }
            for bmode in ("strict", "practical"):
                hits = sum(1 for x, y in zip(xs, ys) if segs and near_any(x, y, segs, bmode))
                frac = hits / SAMPLES
                zrec[bmode] = {
                    "hideable_frac": frac,
                    "hideable_area_m2": frac * zone_area,
                    "sample_hits": hits,
                }
            rec["zones"][zkey] = zrec

        results.append(rec)
        if len(results) % 50 == 0:
            print(f"  scored {len(results)}/{len(stops)} ({time.time()-t0:.1f}s)", flush=True)

    meta = {
        "metric": "hideable_frac",
        "definition": "Monte Carlo fraction of zone disk within path buffer",
        "n_samples": SAMPLES,
        "rule_m": RULE_M,
        "buffer_modes": {
            "strict": "10 ft from OSM walk centerline",
            "practical": "highway half-width + 10 ft",
        },
        "zone_radii_m": ZONE_M,
        "n_stops": len(results),
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    OUT.write_text(json.dumps({"meta": meta, "stops": results}))
    print(f"Wrote {OUT} ({OUT.stat().st_size/1e6:.2f} MB) in {time.time()-t_all:.1f}s", flush=True)

    ranked = sorted(
        results,
        key=lambda s: s["zones"]["small_medium"]["practical"]["hideable_frac"],
        reverse=True,
    )
    print("\nTop 15 by practical hideable_frac (¼ mi):")
    for i, s in enumerate(ranked[:15], 1):
        f = s["zones"]["small_medium"]["practical"]["hideable_frac"]
        print(f"  {i:2}. {s['stop_name'][:42]:42s} {s['mode']:10s} {f*100:5.1f}%")


if __name__ == "__main__":
    main()
