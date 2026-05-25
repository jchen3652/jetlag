"""Visualization helpers — focused on folium (publication quality + excellent LayerControl).

Folium maps are the recommended output for strategy work:
- Beautiful, self-contained, easily shareable.
- Great LayerControl for toggling walkshed, routes, and now attractions by category.
"""

from __future__ import annotations

import folium
import geopandas as gpd
from shapely.geometry import mapping

# ----------------------------- COLORS (ported from original) -----------------------------
COLORS = {
    "Link": "blue",
    "RapidRide": "#ff7f00",   # vivid orange
    "Monorail": "green",
    "Other": "#888888",
}

# More specific colors per RapidRide letter (approximate branding)
RAPIDRIDE_COLORS = {
    "E": "#E30613",   # red (Aurora)
    "D": "#0033A0",   # blue (Ballard)
    "C": "#00A651",   # green-ish (West Seattle)
    "F": "#6B2D7B",   # purple-ish
    "G": "#00A3E0",
    "H": "#FF6B35",
    "B": "#8B4513",   # fallback
}

START = (47.6075, -122.3380)
START_NAME = "Seattle Art Museum (approx)"


def _get_color(row):
    mode = row.get("mode", "Other")
    route = str(row.get("route", ""))
    if mode == "Link":
        return "blue"
    if mode == "Monorail":
        return "green"
    if mode == "RapidRide":
        return RAPIDRIDE_COLORS.get(route[0], "#ff7f00")
    return COLORS.get(mode, "#888888")


def create_folium_map(
    stops: gpd.GeoDataFrame,
    routes: gpd.GeoDataFrame | None = None,
    walkshed=None,
    center=START,
    zoom=11,
):
    """Rich folium map with transit data + walkshed + route polylines.

    Layers (toggleable):
    - ¼-mile walkshed (shaded)
    - Route polylines (colored by line)
    - Stops (by mode)
    """
    m = folium.Map(
        location=center,
        zoom_start=zoom,
        tiles="cartodbpositron",
        control_scale=True,
        prefer_canvas=True,
    )

    # Walkshed first (under everything)
    if walkshed is not None:
        ws_group = folium.FeatureGroup(name="¼-mile walkshed", show=True)
        try:
            gj = folium.GeoJson(
                data=walkshed,
                style_function=lambda f: {
                    "fillColor": "#5dade2",
                    "color": "#2980b9",
                    "weight": 0.7,
                    "fillOpacity": 0.22,
                },
                tooltip="Area within ¼ mile (~400 m) walk of any candidate stop",
            )
            gj.add_to(ws_group)
        except Exception:
            ws_gs = gpd.GeoSeries([walkshed], crs="EPSG:4326")
            gj = folium.GeoJson(
                data=ws_gs.to_json(),
                style_function=lambda f: {
                    "fillColor": "#5dade2",
                    "color": "#2980b9",
                    "weight": 0.7,
                    "fillOpacity": 0.22,
                },
            )
            gj.add_to(ws_group)
        ws_group.add_to(m)

    # Route polylines
    if routes is not None and not routes.empty:
        route_group = folium.FeatureGroup(name="Route segments", show=True)
        for _, row in routes.iterrows():
            color = _get_color(row)
            coords = [(lat, lon) for lon, lat in row.geometry.coords]  # folium wants lat,lon
            folium.PolyLine(
                coords,
                color=color,
                weight=2.5 if row.get("mode") in ("Link", "RapidRide") else 1.5,
                opacity=0.7,
            ).add_to(route_group)
        route_group.add_to(m)

    # Stops
    if not stops.empty:
        groups = {
            "Link (light rail)": folium.FeatureGroup(name="Link (light rail)", show=True),
            "RapidRide": folium.FeatureGroup(name="RapidRide", show=True),
            "Monorail": folium.FeatureGroup(name="Monorail", show=True),
        }
        for _, row in stops.iterrows():
            mode = row.get("mode", "Other")
            group_name = {
                "Link": "Link (light rail)",
                "RapidRide": "RapidRide",
                "Monorail": "Monorail",
            }.get(mode, "RapidRide")
            color = _get_color(row)
            folium.CircleMarker(
                location=(row.geometry.y, row.geometry.x),
                radius=3.5,
                color=color,
                fill=True,
                fill_opacity=0.85,
                weight=1.0,
                popup=folium.Popup(
                    f"<b>{row.get('stop_name', row.get('display_name', ''))}</b><br>"
                    f"Route: {row.get('route', '')} | Mode: {mode}",
                    max_width=280,
                ),
            ).add_to(groups[group_name])

        for g in groups.values():
            g.add_to(m)

    # Start marker
    folium.Marker(
        location=center,
        popup=f"<b>{START_NAME}</b><br>Game start location",
        icon=folium.Icon(color="black", icon="info-sign"),
    ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    # Title box (ported + extended)
    title_html = f'''
        <div style="position: fixed; bottom: 12px; left: 12px; 
                    background-color: rgba(255,255,255,0.92); 
                    padding: 6px 10px; border-radius: 4px; 
                    box-shadow: 0 1px 4px rgba(0,0,0,0.2); z-index: 9999; font-size: 13px;">
            <b>Jet Lag: The Game</b> — Seattle + Mercer Island (KMZ)<br>
            <span style="color:blue">●</span> Link &nbsp;
            <span style="color:#ff7f00">●</span> RapidRide &nbsp;
            <span style="color:green">●</span> Monorail<br>
            <span style="color:#5dade2">■</span> ¼-mile walkshed (toggle in layer control)
        </div>
    '''
    m.get_root().html.add_child(folium.Element(title_html))
    return m


# ----------------------------- ATTRACTIONS OVERLAY HELPERS -----------------------------
# These allow integrating the attractions visualizability (per-category toggleable layers)
# directly into folium maps alongside transit stops, walksheds, etc.

def _get_attraction_color(category: str, colors: dict | None = None) -> str:
    """Get a nice color for an attraction category."""
    if colors is None:
        # Fallback palette
        colors = {
            "Parks": "#2E8B57",
            "Museums": "#8B4513",
            "Zoos": "#556B2F",
            "Aquariums": "#4682B4",
            "Golf Courses": "#006400",
            "Cinemas": "#4B0082",
            "Libraries": "#DAA520",
            "Hospitals": "#DC143C",
            "Foreign Consulates": "#483D8B",
        }
    return colors.get(category, "#888888")


def add_attractions_to_folium(
    m: folium.Map,
    attractions: gpd.GeoDataFrame,
    colors: dict | None = None,
) -> None:
    """
    Add attraction POIs to an existing folium map as toggleable per-category layers.

    Each category gets its own FeatureGroup so it appears in LayerControl.
    Ideal for combining with transit stops + walkshed on one beautiful map.
    """
    if attractions is None or attractions.empty:
        return

    for cat in sorted(attractions["category"].unique()):
        cat_gdf = attractions[attractions["category"] == cat]
        color = _get_attraction_color(cat, colors)

        group = folium.FeatureGroup(name=f"Attractions: {cat}", show=True)

        for _, row in cat_gdf.iterrows():
            folium.CircleMarker(
                location=(row.geometry.y, row.geometry.x),
                radius=4.5,
                color=color,
                fill=True,
                fill_opacity=0.85,
                weight=1.2,
                popup=folium.Popup(
                    f"<b>{row.get('name', '')}</b><br>Category: {cat}",
                    max_width=220,
                ),
            ).add_to(group)

        group.add_to(m)


