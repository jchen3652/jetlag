"""Jet Lag: The Game — Seattle strategy utilities.

Thin, importable helpers so the notebook can stay as plain Python exploration.

Recommended usage in a notebook:

    from jetlag.data import load_reference_kmz, filter_to_scope, compute_walkshed
    from jetlag.viz import create_folium_map, create_ipyleaflet_explorer

    candidates, routes = load_reference_kmz()
    scoped = filter_to_scope(candidates)          # 4-city scope incl. Mercer Island
    ws = compute_walkshed(scoped)

    m = create_folium_map(scoped, routes, walkshed=ws)
    m
"""

from .data import (
    load_reference_kmz,
    filter_to_scope,
    compute_walkshed,
)
from .viz import (
    create_folium_map,
    add_attractions_to_folium,
)
from .attractions import (
    fetch_seattle_attractions,
    load_seattle_attractions,
    load_or_fetch_attractions,
    save_attractions,
    get_attractions_summary,
    CATEGORY_DEFINITIONS,
    CATEGORY_COLORS,
    ATTRACTIONS_PATH,
    DUCKDB_PATH,
)

__all__ = [
    "load_reference_kmz",
    "filter_to_scope",
    "compute_walkshed",
    "create_folium_map",
    "add_attractions_to_folium",
    "fetch_seattle_attractions",
    "load_seattle_attractions",
    "load_or_fetch_attractions",
    "save_attractions",
    "get_attractions_summary",
    "CATEGORY_DEFINITIONS",
    "CATEGORY_COLORS",
    "ATTRACTIONS_PATH",
    "DUCKDB_PATH",
]
