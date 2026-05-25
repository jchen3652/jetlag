# Jet Lag Seattle — Web Visualization

A modern, standalone Leaflet-based visualization using the **exact same data** as the Jupyter notebooks.

## Quick Start

```bash
cd web
npm install
npm run dev
```

Then open http://localhost:5173

## Data Sources

All data comes from the same sources as the notebooks:

- `transit_stops.geojson`, `transit_routes.geojson`, `transit_walkshed.geojson` → generated from `reference_data.kmz`
- `seattle_attractions.geojson` → the standing attractions database

To regenerate transit data after changes:

```bash
python ../scripts/export_for_web.py
```

## Features

- Toggle transit layers (stops, routes, walkshed)
- Toggle individual attraction categories with live updates
- Clean, fast Leaflet map (much nicer than the old Jupyter version)
- Uses the same underlying KMZ + GeoJSON data as everything else in the project
