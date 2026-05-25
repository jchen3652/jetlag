#!/usr/bin/env python3
"""
Export script to generate clean GeoJSON files for the web visualization.
Uses the same logic as the Jupyter notebooks.
"""

from pathlib import Path
import geopandas as gpd
import json

# Make sure we can import the jetlag package
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from jetlag.data import load_reference_kmz, compute_walkshed, filter_to_scope, get_scope_polygon

OUTPUT_DIR = Path(__file__).parent.parent / "web" / "public" / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def export_transit_data():
    print("Loading reference KMZ data...")
    stops, routes = load_reference_kmz()

    scoped_stops = filter_to_scope(stops)

    # For routes (LineStrings), use intersects instead of within.
    # This keeps route segments that cross the scope boundary (common for long lines).
    scope_poly = get_scope_polygon()  # reuse the cached scope
    scoped_routes = routes[routes.intersects(scope_poly)].copy()

    # Optional but recommended: clip routes to the scope so only the relevant portion is shown
    scoped_routes["geometry"] = scoped_routes.geometry.intersection(scope_poly)
    scoped_routes = scoped_routes[~scoped_routes.geometry.is_empty].copy()

    print(f"  Scoped stops: {len(scoped_stops)}")
    print(f"  Scoped routes: {len(scoped_routes)}")

    # Export stops
    stops_geo = scoped_stops[["geometry", "stop_name", "mode", "route"]].copy()
    stops_geo.to_file(OUTPUT_DIR / "transit_stops.geojson", driver="GeoJSON")
    print(f"  Wrote {OUTPUT_DIR / 'transit_stops.geojson'}")

    # Export routes (LineStrings)
    if not scoped_routes.empty:
        routes_geo = scoped_routes[["geometry", "mode", "route"]].copy()
        routes_geo.to_file(OUTPUT_DIR / "transit_routes.geojson", driver="GeoJSON")
        print(f"  Wrote {OUTPUT_DIR / 'transit_routes.geojson'}")

    # Also export a simple walkshed if wanted (optional)
    print("Computing walkshed for web...")
    ws = compute_walkshed(scoped_stops)
    ws_gdf = gpd.GeoDataFrame(geometry=[ws], crs="EPSG:4326")
    ws_gdf.to_file(OUTPUT_DIR / "transit_walkshed.geojson", driver="GeoJSON")
    print(f"  Wrote {OUTPUT_DIR / 'transit_walkshed.geojson'}")

    print("\n✅ Transit data exported for web visualization.")


if __name__ == "__main__":
    export_transit_data()
